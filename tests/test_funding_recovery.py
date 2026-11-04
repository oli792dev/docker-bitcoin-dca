"""Regressions for offset deposits and withdrawals accepted after a retry."""

import json
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from decimal import Decimal as D
from pathlib import Path
from unittest.mock import Mock, patch

import requests

from app.data import activity
from app.exchanges.bitvavo import Bitvavo
from app.exchanges.kraken import Kraken
from app.trading import bot
from app.trading.deposits import sync_deposits
from app.trading.withdrawals import reconcile_withdrawals


class FundingRecoveryTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        for owner, name, value in (
            (activity, 'ACTIVITY_PATH', self.root / 'activity.json'),
            (bot, 'STATE_PATH', self.root / 'state.json'),
        ):
            replacement = patch.object(owner, name, value)
            replacement.start()
            self.addCleanup(replacement.stop)

    def test_deposit_is_imported_when_a_purchase_offsets_or_exceeds_the_credit(self):
        now = datetime(2026, 11, 1, 9, tzinfo=UTC)
        for adapter, exchange in ((Kraken, 'KRAKEN'), (Bitvavo, 'BITVAVO')):
            for balance in (D('100'), D('20')):
                with self.subTest(exchange=exchange,balance=balance), patch.object(adapter,'booked_balance',return_value=D('100')) as booked:
                    api = object.__new__(adapter)
                    api.fiat_deposits = Mock(return_value=[dict(
                        id=str(balance), timestamp=int((now+timedelta(seconds=60)).timestamp()*1000),
                        symbol='EUR', status='completed', amount='80', fee='0')])
                    state = {}
                    settings = dict(exchange=exchange,quote='EUR')
                    sync_deposits(api,settings,state,now,D('100'))
                    booked.return_value = balance
                    records, inserted = sync_deposits(api,settings,state,now+timedelta(minutes=5),balance)
                    self.assertEqual(inserted,1)
                    self.assertEqual(records[0]['row']['amount'],'80')
                    self.assertNotIn('pending',state['fiat_observation'])
                    self.assertEqual(sync_deposits(api,settings,state,now+timedelta(minutes=10),balance)[1],0)

    def test_late_history_without_balance_increase_survives_restart(self):
        now = datetime(2026,11,1,9,tzinfo=UTC)
        api = object.__new__(Kraken)
        api.fiat_deposits = Mock(return_value=[])
        settings = dict(exchange='KRAKEN',quote='EUR')
        with patch.object(Kraken,'booked_balance',return_value=D('100')):
            state = {}
            sync_deposits(api,settings,state,now,D('100'))
            sync_deposits(api,settings,state,now+timedelta(minutes=5),D('100'))
            state = json.loads(json.dumps(state))
            api.fiat_deposits.return_value = [dict(
                id='late',timestamp=int((now+timedelta(minutes=1)).timestamp()*1000),
                symbol='EUR',status='completed',amount='80',fee='0')]
            records, inserted = sync_deposits(api,settings,state,now+timedelta(minutes=10),D('100'))
        self.assertEqual(inserted,1)
        self.assertEqual(records[0]['id'],'fiat-deposit:KRAKEN:EUR:late')

    def withdrawal_api(self, accepted_on_retry):
        class API:
            supports_withdrawal_idempotency = True
            calls = 0
            accepted_at = None
            def balance(self,currency): return D('.0045')
            def price(self,symbol): return D('81000')
            def withdrawal_request(self,amount,key,settings):
                return dict(symbol='BTC',address='bc1-test',network='BTC',amount=str(amount),idempotencyKey=key)
            def withdraw_btc(self,request):
                self.calls += 1
                if self.calls == 1:
                    if not accepted_on_retry: self.accepted_at = int(bot.time.time()*1000)
                    raise requests.ConnectionError('response unavailable')
                if self.accepted_at is None: self.accepted_at = int(bot.time.time()*1000)
                return {}
            def btc_withdrawals(self,start,end):
                if self.accepted_at is not None and start <= self.accepted_at <= end:
                    row = dict(address='bc1-test',timestamp=self.accepted_at,status='completed',amount='.0044',fee='.0001')
                    return [row,dict(row,timestamp=row['timestamp']+1)] if getattr(self,'ambiguous',False) else [row]
                return []
        return API()

    def test_delayed_retry_and_lost_success_response_both_reconcile(self):
        settings = dict(exchange='BITVAVO',live=True,quote='EUR',withdrawals_enabled=True,withdraw_threshold=D('100'))
        for accepted_on_retry in (True,False):
            with self.subTest(accepted_on_retry=accepted_on_retry):
                api = self.withdrawal_api(accepted_on_retry)
                state = {}
                start = 1800000000 + (10000 if accepted_on_retry else 0)
                with patch.object(bot.time,'time',return_value=start):
                    bot.maybe_withdraw_btc(api,state,settings)
                state = json.loads(bot.STATE_PATH.read_text())
                with patch.object(bot.time,'time',return_value=start+316):
                    bot.maybe_withdraw_btc(api,state,settings)
                    reconcile_withdrawals(api,settings,force=True)
                record = activity.get_activity_record(state['last_withdrawal']['activityId'])
                self.assertEqual(record['withdrawalStatus'],'completed')
                self.assertEqual(datetime.fromisoformat(record['row']['datetime'].replace('Z','+00:00')).timestamp(),api.accepted_at/1000)
                self.assertEqual(api.calls,2)

    def test_ambiguous_retry_history_stays_unresolved(self):
        api = self.withdrawal_api(True)
        api.ambiguous = True
        state = {}
        settings = dict(exchange='BITVAVO',live=True,quote='EUR',withdrawals_enabled=True,withdraw_threshold=D('100'))
        with patch.object(bot.time,'time',return_value=1800000000): bot.maybe_withdraw_btc(api,state,settings)
        with patch.object(bot.time,'time',return_value=1800000316):
            bot.maybe_withdraw_btc(api,state,settings)
            reconcile_withdrawals(api,settings,force=True)
        self.assertEqual(activity.read_activity_records()[0]['withdrawalStatus'],'submitted')

    def test_legacy_bitvavo_record_can_find_a_late_accepted_request(self):
        api = self.withdrawal_api(True)
        api.accepted_at = 1800000316000
        activity.append_activity_records([dict(
            id='withdrawal:legacy',exchange='BITVAVO',withdrawalStatus='submitted',
            withdrawalAddress='bc1-test',grossWithdrawalAmountBtc='.0045',
            row=dict(datetime=datetime.fromtimestamp(1800000000,UTC).isoformat(),type='TransferOut',
                     identifier='BTC',shares='.0045',amount='364.5',price='81000',fee='0',currency='EUR'))])
        with patch.object(bot.time,'time',return_value=1800000316):
            reconcile_withdrawals(api,dict(exchange='BITVAVO'),force=True)
        self.assertEqual(activity.read_activity_records()[0]['withdrawalStatus'],'completed')

    def test_replayed_old_deposit_is_excluded_from_a_later_credit_verification(self):
        now = datetime(2026,11,1,9,tzinfo=UTC)
        first = dict(id='first',timestamp=int((now+timedelta(minutes=1)).timestamp()*1000),
                     symbol='EUR',status='completed',amount='80',fee='0')
        second = dict(first,id='second',timestamp=int((now+timedelta(minutes=6)).timestamp()*1000),amount='100')
        api = object.__new__(Kraken)
        api.fiat_deposits = Mock(return_value=[first])
        api._fiat_ledger = Mock(return_value={'second':dict(
            type='deposit',asset='ZEUR',time=str(second['timestamp']/1000),amount='100',fee='0',balance='200')})
        with patch.object(Kraken,'booked_balance',return_value=D('100')) as booked:
            state = {}
            settings = dict(exchange='KRAKEN',quote='EUR')
            sync_deposits(api,settings,state,now,D('100'))
            sync_deposits(api,settings,state,now+timedelta(minutes=5),D('100'))
            api.fiat_deposits.return_value = [first,second]
            booked.return_value = D('200')
            records, inserted = sync_deposits(api,settings,state,now+timedelta(minutes=10),D('200'))
        self.assertNotIn('pending',state['fiat_observation'])
        self.assertEqual(inserted,1)
        self.assertEqual({record['row']['amount'] for record in records},{'80','100'})
