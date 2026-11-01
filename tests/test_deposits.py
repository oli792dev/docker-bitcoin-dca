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
            records,inserted=sync_deposits(api,settings,state,now,datetime(2026,10,1,12,tzinfo=timezone.utc))
            self.assertEqual(inserted,1)
            due,_,received=observe_deposit(state,settings,now,datetime(2026,10,1,12,tzinfo=timezone.utc),datetime(2026,11,1,12,tzinfo=timezone.utc),Decimal(200),records)
            self.assertTrue(received);self.assertEqual(due,datetime(2026,12,1,12,tzinfo=timezone.utc))
            self.assertEqual(sync_deposits(api,settings,state,now,datetime(2026,10,1,12,tzinfo=timezone.utc))[1],0)
            api.fiat_deposits.side_effect=requests.ConnectionError('offline')
            saved=dict(state['deposit_history'])
            with self.assertRaises(requests.ConnectionError):sync_deposits(api,settings,state,now,now)
            self.assertEqual(state['deposit_history'],saved)
            self.assertEqual(len(activity.read_activity_records()),1)

    def test_worker_prices_keep_purchase_price_if_conversion_is_unavailable(self):
        api=Mock();api.price.return_value=Decimal(88000)
        self.assertEqual(collect_prices(api,{'quote':'EUR','exchange':'KRAKEN'},Decimal(80000)),{'EUR':'80000','USD':'88000'})
        api.price.assert_called_once_with('BTC-USD')
        api.price.side_effect=requests.ReadTimeout()
        self.assertEqual(collect_prices(api,{'quote':'EUR','exchange':'KRAKEN'},Decimal(80000)),{'EUR':'80000'})
