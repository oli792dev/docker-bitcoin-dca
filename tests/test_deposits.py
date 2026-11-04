"""Offline exchange fixtures for confirmed fiat deposits and scheduled price snapshots."""
import tempfile
import unittest
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from unittest.mock import Mock, patch
import requests
from app.exchanges.kraken import Kraken, KrakenAPIError
from app.exchanges.bitvavo import Bitvavo
from app.trading.deposits import sync_deposits
from app.trading.funding import observe_deposit
from app.data import activity
from app.exchanges.market_prices import collect_prices


class DepositTests(unittest.TestCase):
    def test_kraken_booked_ledger_is_paginated_and_filters_internal_transfers(self):
        api=object.__new__(Kraken)
        entry={'type':'deposit','asset':'ZEUR','time':'1793516400.125','amount':'200','fee':'0'}
        api.private=Mock(side_effect=[{'count':3,'ledger':{'one':entry}},
            {'count':3,'ledger':{'two':{**entry,'subtype':'spotfromfutures'},'three':{**entry,'asset':'ZUSD'}}}])
        rows=api.fiat_deposits('EUR',0,1793520000000)
        self.assertEqual(rows,[{'id':'one','timestamp':1793516400125,'symbol':'EUR','amount':'200','fee':'0','status':'completed'}])
        self.assertEqual(api.private.call_args_list[1].args[1]['ofs'],1)
        api.private=Mock(return_value={'count':2,'ledger':{'one':entry}})
        with self.assertRaises(KrakenAPIError):api.fiat_deposits('EUR')

    def test_bitvavo_fiat_history_excludes_canceled_and_retains_identical_deposits(self):
        api=object.__new__(Bitvavo)
        entry={'symbol':'EUR','timestamp':1793516400000,'amount':'200','fee':'0','status':'completed','address':'PRIVATE IBAN'}
        api.request=Mock(return_value=[entry,entry,{**entry,'status':'canceled'}])
        rows=api.fiat_deposits('EUR',0,1793520000000)
        self.assertEqual(len(rows),2);self.assertNotEqual(rows[0]['id'],rows[1]['id'])
        self.assertNotIn('PRIVATE',str(rows))
        self.assertEqual(api.fiat_deposits('EUR',0,1793520000000),rows)
        self.assertEqual(api.request.call_args.args,('GET','/depositHistory'))
        self.assertTrue(api.request.call_args.kwargs['private'])
        api.request=Mock(side_effect=[[entry]*1000,[entry],[]])
        self.assertEqual(len(api.fiat_deposits('EUR',0,1793520000000)),1)

    def test_bitvavo_private_history_signature_includes_the_api_version_and_query(self):
        import hashlib,hmac
        api=object.__new__(Bitvavo);api.key='fake-key';api.secret='fake-secret';api.session=Mock()
        api.session.request.return_value.json.return_value=[];api.session.request.return_value.status_code=200
        with patch('app.exchanges.bitvavo.time.time',return_value=1000):
            api.request('GET','/depositHistory',params={'symbol':'EUR','limit':1000},private=True)
        headers=api.session.request.call_args.kwargs['headers']
        expected=hmac.new(b'fake-secret',b'1000000GET/v2/depositHistory?symbol=EUR&limit=1000',hashlib.sha256).hexdigest()
        self.assertEqual(headers['Bitvavo-Access-Signature'],expected)

    def test_api_sync_is_idempotent_and_early_offline_deposit_advances_the_month(self):
        now=datetime(2026,11,1,9,tzinfo=timezone.utc)
        settings={'exchange':'KRAKEN','quote':'EUR','live':True,'deposit_day':1,'deposit_time':'12:00','timezone':'UTC'}
        state={};api=Mock();api.fiat_deposits.return_value=[{'id':'bank','timestamp':int(now.timestamp()*1000)-3600000,
            'status':'completed','symbol':'EUR','amount':'200','fee':'0'}]
        with tempfile.TemporaryDirectory() as root,patch.object(activity,'ACTIVITY_PATH',Path(root)/'activity.json'):
            self.assertEqual(sync_deposits(api,settings,state,now.replace(hour=7),Decimal(0)),([],0))
            api.fiat_deposits.assert_not_called()
            records,inserted=sync_deposits(api,settings,state,now,Decimal(200))
            self.assertEqual(inserted,1)
            due,_,received=observe_deposit(state,settings,now,datetime(2026,10,1,12,tzinfo=timezone.utc),datetime(2026,11,1,12,tzinfo=timezone.utc),Decimal(200),records)
            self.assertTrue(received);self.assertEqual(due,datetime(2026,12,1,12,tzinfo=timezone.utc))
            self.assertEqual(sync_deposits(api,settings,state,now,Decimal(200))[1],0)
            api.fiat_deposits.side_effect=requests.ConnectionError('offline')
            calls=api.fiat_deposits.call_count
            self.assertEqual(calls,2)
            with self.assertRaises(requests.ConnectionError):sync_deposits(api,settings,state,now,Decimal(210))
            self.assertIn('pending',state['fiat_observation'])
            self.assertEqual(api.fiat_deposits.call_count,3)
            self.assertEqual(len(activity.read_activity_records()),1)

    def test_every_check_replays_the_history_window_and_pending_checks_survive_restart(self):
        from datetime import timedelta
        import json
        settings={'exchange':'KRAKEN','quote':'EUR'}
        now=datetime(2026,11,1,9,tzinfo=timezone.utc)
        state={};api=Mock();api.fiat_deposits.return_value=[]
        sync_deposits(api,settings,state,now,Decimal(100))
        sync_deposits(api,settings,state,now+timedelta(minutes=5),Decimal(92))
        sync_deposits(api,settings,state,now+timedelta(minutes=10),Decimal(92))
        self.assertEqual(api.fiat_deposits.call_count,2)
        sync_deposits(api,settings,state,now+timedelta(minutes=15),Decimal(292))
        self.assertEqual(api.fiat_deposits.call_args.args[1],int(now.timestamp()*1000))
        self.assertIn('pending',state['fiat_observation'])
        # A restart or unchanged balance must not lose an awaiting confirmation window.
        state=json.loads(json.dumps(state))
        sync_deposits(api,settings,state,now+timedelta(minutes=20),Decimal(292))
        self.assertEqual(api.fiat_deposits.call_count,4)
        self.assertEqual(api.fiat_deposits.call_args.args[1],int(now.timestamp()*1000))

    def test_released_hold_does_not_create_unverified_deposit(self):
        now=datetime(2026,11,1,9,tzinfo=timezone.utc)
        settings={'exchange':'KRAKEN','quote':'EUR'}
        api=type('BookedAPI', (), {'booked_balance': lambda api, currency: Decimal('200')})(); api.fiat_deposits=Mock(return_value=[])
        state={}
        sync_deposits(api,settings,state,now,Decimal('100'))
        sync_deposits(api,settings,state,now,Decimal('200'))
        self.assertNotIn('pending',state['fiat_observation'])
        api.fiat_deposits.assert_called_once()

    def test_booked_increase_checks_even_when_new_funds_are_held(self):
        now=datetime(2026,11,1,9,tzinfo=timezone.utc)
        settings={'exchange':'KRAKEN','quote':'EUR'}
        values=iter([Decimal('200'),Decimal('300')]); api=type('BookedAPI', (), {'booked_balance': lambda api, currency: next(values)})(); api.fiat_deposits=Mock()
        api.fiat_deposits.return_value=[]
        state={}
        sync_deposits(api,settings,state,now,Decimal('100'))
        sync_deposits(api,settings,state,now,Decimal('100'))
        self.assertIn('pending',state['fiat_observation'])
        api.fiat_deposits.assert_called_once()

    def test_kraken_complete_credit_chain_classifies_sales_but_not_missing_deposits(self):
        api=object.__new__(Kraken)
        row={'type':'trade','asset':'ZEUR','time':'1793516400.125','amount':'100','fee':'1','balance':'199'}
        api.private=Mock(return_value={'count':1,'ledger':{'sale':row}})
        self.assertTrue(api.non_deposit_balance_change('EUR',0,1793520000000,Decimal('100'),Decimal('199')))
        self.assertFalse(api.non_deposit_balance_change('EUR',0,1793520000000,Decimal('0'),Decimal('199')))
        api.private=Mock(return_value={'count':1,'ledger':{'deposit':{**row,'type':'deposit'}}})
        self.assertFalse(api.non_deposit_balance_change('EUR',0,1793520000000,Decimal('100'),Decimal('199')))

    def test_non_deposit_proceeds_clear_pending_without_activity_or_deposit_confirmation(self):
        now=datetime(2026,11,1,9,tzinfo=timezone.utc)
        settings={'exchange':'KRAKEN','quote':'EUR'}
        values=iter([Decimal('100'),Decimal('200')])
        api=type('CreditAPI', (), {'booked_balance': lambda api, currency: next(values),
            'non_deposit_balance_change':lambda api,*args: True})()
        api.fiat_deposits=Mock(return_value=[])
        state={}
        sync_deposits(api,settings,state,now,Decimal('100'))
        self.assertEqual(sync_deposits(api,settings,state,now,Decimal('200')),([],0))
        self.assertNotIn('pending',state['fiat_observation'])
        self.assertEqual(state['fiat_observation']['confirmed'],[])

    def test_booked_adapter_balances_ignore_order_holds(self):
        api=object.__new__(Kraken)
        api._balance_scope_depth=0
        api.private=Mock(return_value={'ZEUR':{'balance':'200','hold_trade':'100','credit':'10','credit_used':'2'}})
        self.assertEqual(api.balance('EUR'),Decimal('108'))
        self.assertEqual(api.booked_balance('EUR'),Decimal('200'))
        api=Bitvavo(api_key='fixture-key',api_secret='fixture-secret')
        api.request=Mock(return_value=[{'symbol':'EUR','available':'100','inOrder':'100'}])
        with api.balance_snapshot():
            self.assertEqual(api.balance('EUR'),Decimal('100'))
            self.assertEqual(api.booked_balance('EUR'),Decimal('200'))
        api.request.assert_called_once()

    def test_unverified_or_failed_proceeds_read_retains_window(self):
        from datetime import timedelta
        now=datetime(2026,11,1,9,tzinfo=timezone.utc)
        settings={'exchange':'KRAKEN','quote':'EUR'}
        values=iter([Decimal('100'),Decimal('200'),Decimal('200'),Decimal('200')])
        api=type('CreditAPI', (), {'booked_balance': lambda api, currency: next(values),
            'non_deposit_balance_change':lambda api,*args: api.classify(*args)})()
        api.classify=Mock(side_effect=[False,requests.ConnectionError('offline'),False])
        api.fiat_deposits=Mock(return_value=[])
        state={}
        sync_deposits(api,settings,state,now,Decimal('100'))
        sync_deposits(api,settings,state,now+timedelta(minutes=1),Decimal('200'))
        pending=dict(state['fiat_observation']['pending'])
        with self.assertRaises(requests.ConnectionError):
            sync_deposits(api,settings,state,now+timedelta(days=2),Decimal('200'))
        sync_deposits(api,settings,state,now+timedelta(days=3),Decimal('200'))
        self.assertEqual(state['fiat_observation']['pending'],pending)
        self.assertEqual(state['fiat_observation']['confirmed'],[])
        self.assertTrue(all(call.args[1]==int(now.timestamp()*1000) for call in api.fiat_deposits.call_args_list))

    def test_worker_prices_keep_purchase_price_if_conversion_is_unavailable(self):
        api=Mock();api.price.return_value=Decimal(88000)
        self.assertEqual(collect_prices(api,{'quote':'EUR','exchange':'KRAKEN'},Decimal(80000)),{'EUR':'80000','USD':'88000'})
        api.price.assert_called_once_with('BTC-USD')
        api.price.side_effect=requests.ReadTimeout()
        with self.assertLogs('bitcoin-dca.prices',level='DEBUG') as logs:
            self.assertEqual(collect_prices(api,{'quote':'EUR','exchange':'KRAKEN'},Decimal(80000)),{'EUR':'80000'})
        self.assertFalse(any(':WARNING:' in line for line in logs.output))
        api._logged_states={}
        with self.assertLogs('bitcoin-dca.prices',level='DEBUG') as logs:
            for _ in range(2):collect_prices(api,{'quote':'EUR','exchange':'KRAKEN','display_currency':'USD'},Decimal(80000))
        self.assertEqual(sum(line.startswith('WARNING:') for line in logs.output),1)
