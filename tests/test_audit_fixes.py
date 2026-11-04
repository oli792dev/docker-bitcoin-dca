"""Regressions for funding completeness and automatic withdrawal recovery."""

import json
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from decimal import Decimal as D
from pathlib import Path
from unittest.mock import Mock, patch

from app.data import activity
from app.exchanges.bitvavo import Bitvavo
from app.exchanges.kraken import Kraken
from app.trading import bot
from app.trading.deposits import sync_deposits
from app.trading.withdrawals import reconcile_withdrawals


class AuditFixTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        for owner, name, value in (
            (activity, 'ACTIVITY_PATH', self.root / 'activity.sqlite3'),
            (activity, 'SNAPSHOT_PATH', self.root / 'dashboard.json'),
            (bot, 'STATE_PATH', self.root / 'state.json'),
        ):
            replacement = patch.object(owner, name, value)
            replacement.start()
            self.addCleanup(replacement.stop)
        self.settings = dict(exchange='KRAKEN', quote='EUR', live=True, timezone='UTC',
                             deposit_day=1, buy_amount=D('.001'), withdrawals_enabled=True,
                             withdraw_threshold=D('100'), order_status_check_seconds=30)

    def test_partial_deposit_history_stays_pending_until_the_whole_credit_is_verified(self):
        now = datetime(2026, 11, 1, 9, tzinfo=UTC)
        first = dict(id='first', timestamp=int((now + timedelta(seconds=1)).timestamp() * 1000),
                     status='completed', symbol='EUR', amount='100', fee='0')
        second = dict(first, id='second', amount='200')
        for exchange, adapter in (('KRAKEN', Kraken), ('BITVAVO', Bitvavo)):
            with self.subTest(exchange=exchange), patch.object(adapter, 'booked_balance', return_value=D('100')) as booked:
                api = object.__new__(adapter)
                api.fiat_deposits = Mock(return_value=[first])
                if exchange == 'KRAKEN':
                    api._fiat_ledger = Mock(return_value={
                        'first': dict(type='deposit', asset='ZEUR', time=str(first['timestamp'] / 1000),
                                      amount='100', fee='0', balance='200')})
                else:
                    api.request = Mock(return_value={'items':[
                        dict(transactionId='first', executedAt='2026-11-01T09:00:01Z', type='deposit',
                             receivedCurrency='EUR', receivedAmount='100', feesCurrency='EUR', feesAmount='0')
                    ], 'currentPage':1, 'totalPages':1})
                state = {}
                settings = dict(exchange=exchange, quote='EUR')
                sync_deposits(api, settings, state, now, D('100'))
                booked.return_value = D('400')
                sync_deposits(api, settings, state, now + timedelta(minutes=5), D('400'))
                self.assertIn('pending', state['fiat_observation'])
                api.fiat_deposits.return_value = [first, second]
                if exchange == 'KRAKEN':
                    api._fiat_ledger.return_value['second'] = dict(
                        type='deposit', asset='ZEUR', time=str(first['timestamp'] / 1000 + 1),
                        amount='200', fee='0', balance='400')
                else:
                    api.request.return_value['items'].append(dict(
                        transactionId='second', executedAt='2026-11-01T09:00:02Z', type='deposit',
                        receivedCurrency='EUR', receivedAmount='200', feesCurrency='EUR', feesAmount='0'))
                records, _ = sync_deposits(api, settings, state, now + timedelta(minutes=10), D('400'))
                self.assertNotIn('pending', state['fiat_observation'])
                self.assertEqual(sum(D(record['row']['amount']) for record in records), D('300'))
                self.assertEqual(len([r for r in activity.read_activity_records() if r['exchange'] == exchange]), 2)

    def test_completed_withdrawal_rearms_even_if_new_bitcoin_already_exceeds_threshold(self):
        from test_manual_withdrawal import API
        api = API('KRAKEN')
        original_send = api.withdraw_btc
        def send(request):
            result = original_send(request)
            result['id'] = 'test-' + str(len(api.sent))
            return result
        api.withdraw_btc = send
        state = {}
        bot.maybe_withdraw_btc(api, state, self.settings)
        reconcile_withdrawals(api, self.settings, force=True)
        api.available = D('.002')
        bot.maybe_withdraw_btc(api, state, self.settings)
        self.assertEqual(len(api.sent), 2)
        self.assertEqual({r['withdrawalStatus'] for r in activity.read_activity_records()}, {'completed', 'submitted'})

    def test_old_bitvavo_checkpoint_never_uses_available_balance_to_verify_booked_credit(self):
        now = datetime(2026, 11, 1, 9, tzinfo=UTC)
        state = {'fiat_observation':dict(identity=['BITVAVO','EUR'], balance='100', checkedAt=now.isoformat(), historyStartAt=now.isoformat())}
        api = object.__new__(Bitvavo)
        api.fiat_deposits = Mock(return_value=[dict(
            id='first', timestamp=int((now + timedelta(seconds=1)).timestamp() * 1000),
            status='completed', symbol='EUR', amount='100', fee='0')])
        with patch.object(Bitvavo, 'booked_balance', return_value=D('400')):
            sync_deposits(api, dict(exchange='BITVAVO',quote='EUR'), state, now + timedelta(minutes=5), D('200'))
        self.assertIn('pending', state['fiat_observation'])

    def test_mixed_fiat_bookings_reconcile_without_hiding_unconfirmed_deposits(self):
        api = object.__new__(Kraken)
        api._fiat_ledger = Mock(return_value={
            'buy': dict(type='trade', asset='ZEUR', time='1', amount='-20', fee='1', balance='79'),
            'bank': dict(type='deposit', asset='ZEUR', time='2', amount='100', fee='2', balance='177'),
            'sell': dict(type='trade', asset='ZEUR', time='3', amount='30', fee='1', balance='206'),
        })
        self.assertTrue(api.non_deposit_balance_change('EUR', 0, 4000, D('100'), D('206'), D('98')))
        self.assertFalse(api.non_deposit_balance_change('EUR', 0, 4000, D('100'), D('206'), D('50')))
        api = object.__new__(Bitvavo)
        api.request = Mock(return_value={'items':[
            dict(transactionId='buy', executedAt='1970-01-01T00:00:01Z', type='buy',
                 sentCurrency='EUR', sentAmount='20', feesCurrency='EUR', feesAmount='1'),
            dict(transactionId='bank', executedAt='1970-01-01T00:00:02Z', type='deposit',
                 receivedCurrency='EUR', receivedAmount='100', feesCurrency='EUR', feesAmount='2'),
            dict(transactionId='sell', executedAt='1970-01-01T00:00:03Z', type='sell',
                 receivedCurrency='EUR', receivedAmount='30', feesCurrency='EUR', feesAmount='1'),
        ], 'currentPage':1, 'totalPages':1})
        self.assertTrue(api.non_deposit_balance_change('EUR', 0, 4000, D('100'), D('206'), D('98')))
        self.assertFalse(api.non_deposit_balance_change('EUR', 0, 4000, D('100'), D('206'), D('50')))

    def test_missing_history_never_verifies_a_known_deposit(self):
        api = object.__new__(Kraken)
        api._fiat_ledger = Mock(return_value={})
        self.assertFalse(api.non_deposit_balance_change('EUR', 0, 4000, D('100'), D('100'), D('98')))

    def test_unconfirmed_withdrawal_never_rearms_on_a_new_balance(self):
        from test_manual_withdrawal import API
        api = API('KRAKEN')
        state = {}
        bot.maybe_withdraw_btc(api, state, self.settings)
        api.btc_withdrawals = Mock(return_value=[])
        api.available = D('.002')
        bot.maybe_withdraw_btc(api, state, self.settings)
        self.assertEqual(len(api.sent), 1)

    def test_fee_above_bitcoin_balance_does_not_stop_a_funded_purchase(self):
        api = object.__new__(Kraken)
        api.withdraw_key = 'wallet'
        api.private = Mock(return_value={'fee': '.00002'})
        api.balance = lambda currency: D('.00001') if currency == 'BTC' else D('1000')
        api.price = lambda symbol: D('100000')
        api.estimate_taker_fee = lambda symbol, amount: amount * D('.002')
        api.market = lambda *args, **kwargs: dict(status='trading', minOrderInBaseAsset='.0001',
                                                 minOrderInQuoteAsset='5', quantityDecimals=8, notionalDecimals=2)
        api.buy_btc = Mock(return_value={'orderId': 'new-buy'})
        self.settings['withdraw_threshold'] = D('.50')
        with patch.object(bot, 'read_state', return_value={}), patch.object(Kraken, 'booked_balance', return_value=D('1000')):
            wait = bot._run_once(api, self.settings, 300)
        self.assertEqual(wait, 30)
        state = json.loads(bot.STATE_PATH.read_text())
        self.assertEqual(state['pending_order']['exchangeOrderId'], 'new-buy')
        self.assertNotIn('pending_withdrawal', state)

    def test_withdrawal_storage_failure_still_blocks_the_purchase(self):
        from test_manual_withdrawal import API
        api = API('KRAKEN')
        with patch.object(bot, 'save_state', side_effect=OSError('disk full')):
            with self.assertRaises(OSError):
                bot.maybe_withdraw_btc(api, {}, self.settings)
        self.assertEqual(api.sent, [])
