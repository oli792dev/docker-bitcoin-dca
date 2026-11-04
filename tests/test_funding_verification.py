"""Authoritative ledger evidence is required to release uncertain funding."""
import unittest
from decimal import Decimal as D
from unittest.mock import Mock
from app.exchanges.kraken import Kraken
from app.exchanges.bitvavo import Bitvavo

class FundingEvidenceTests(unittest.TestCase):


    def test_missing_or_stale_anchor_never_confirms_an_unbooked_deposit(self):
        for anchor in ({}, {'anchor':{'asset':'ZEUR','time':'1','balance':'100'}}):
            api = object.__new__(Kraken)
            api._fiat_ledger = Mock(side_effect=[anchor, {}])
            self.assertFalse(api.non_deposit_balance_change('EUR',2000,3000,None,D('200')))

    def test_bitvavo_sale_requires_complete_balanced_transaction_history(self):
        api = object.__new__(Bitvavo)
        sale={'transactionId':'sale','executedAt':'2026-11-02T12:00:01Z','type':'sell',
              'sentCurrency':'BTC','sentAmount':'.001','receivedCurrency':'EUR','receivedAmount':'101',
              'feesCurrency':'EUR','feesAmount':'1'}
        api.request = Mock(return_value={'items':[sale],'currentPage':1,'totalPages':1})
        start=1793620800000
        self.assertTrue(api.non_deposit_balance_change('EUR',start,start+2000,D('100'),D('200')))
        self.assertFalse(api.non_deposit_balance_change('EUR',start,start+2000,D('100'),D('201')))
        api.request.return_value['items']=[{**sale,'type':'deposit'}]
        self.assertFalse(api.non_deposit_balance_change('EUR',start,start+2000,D('100'),D('200')))
        api.request.return_value={'items':[],'currentPage':1,'totalPages':1}
        self.assertFalse(api.non_deposit_balance_change('EUR',start,start+2000,D('100'),D('200')))

    def test_bitvavo_incomplete_pagination_is_rejected(self):
        api=object.__new__(Bitvavo)
        api.request=Mock(return_value={'items':[],'currentPage':1,'totalPages':2})
        with self.assertRaises(ValueError):
            api.non_deposit_balance_change('EUR',0,1000,D('100'),D('200'))
