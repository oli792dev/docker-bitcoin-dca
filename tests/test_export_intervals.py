"""Exports always cover one complete confirmed withdrawal cycle."""
import csv
import io
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from threading import Event
from unittest.mock import Mock, patch
from app.data import activity
from app.data import reporting
from app.webpage import web_ui


def record(name, day, kind='Buy', status='completed', amount='80', simulated=False):
    result={'id':name,'exchange':'KRAKEN','simulated':simulated,'row':{
        'datetime':f'2026-10-{day:02d}T12:00:00Z','type':kind,'identifier':'BTC',
        'assetType':'Crypto','price':'80000','shares':'.001','amount':amount,
        'fee':'.20','currency':'EUR','tax':'0'}}
    if kind=='TransferOut':result.update(withdrawalStatus=status,netWithdrawalAmount=True)
    return result


def stamp(day):return int(datetime.fromisoformat(f'2026-10-{day:02d}T12:00:00+00:00').timestamp()*1000)


class ExportIntervals(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        for name,value in [('ACTIVITY_PATH',Path(temp.name)/'activity.sqlite3')]:
            p=patch.object(activity,name,value);p.start();self.addCleanup(p.stop)
        self.records=[record('old-buy',1),record('previous',5,'TransferOut'),
                      record('buy-one',6),record('buy-two',8,amount='160'),
                      record('last',10,'TransferOut'),record('later-buy',11,amount='1000')]
        activity.append_activity_records(self.records)

    def export(self,start=1,end=12):
        return reporting.parqet_aggregate_rows(activity.parqet_interval_records(stamp(start),stamp(end)),'KRAKEN')

    def test_withdrawal_api_returns_account_scoped_bounds_without_key_identity(self):
        records = [record('a-first', 2, 'TransferOut'), record('b-first', 5, 'TransferOut'),
                   record('a-second', 8, 'TransferOut')]
        for item, identity in zip(records, ['secret-fingerprint-a', 'secret-fingerprint-b', 'secret-fingerprint-a']):
            item['accountIdentity'] = identity
        buys = [
            {**record('a-buy', 1), 'accountIdentity': 'secret-fingerprint-a'},
            {**record('b-buy', 4), 'accountIdentity': 'secret-fingerprint-b'},
            {**record('b-simulated', 1, simulated=True), 'accountIdentity': 'secret-fingerprint-b'},
            {**record('b-unverified', 2), 'accountIdentity': 'secret-fingerprint-b', 'purchaseStatus': 'unverified'},
            {**record('b-other-exchange', 3), 'accountIdentity': 'secret-fingerprint-b', 'exchange': 'BITVAVO'},
        ]
        activity.append_activity_records(buys)
        handler = object.__new__(web_ui.Handler)
        handler.path = '/api/withdrawals'
        handler.settings = {'exchange':'KRAKEN'}
        handler._require_authentication = lambda: True
        results = []
        handler._json = lambda status, data: results.append(data)
        with patch.object(web_ui, 'withdrawal_records', return_value=records):
            handler.do_GET()
        self.assertEqual([r['startTimestamp'] for r in results[0]], [0, 0, stamp(2)])
        self.assertEqual([r['analysisStartTimestamp'] for r in results[0]], [stamp(1), stamp(4), stamp(2)])
        self.assertNotIn('secret-fingerprint', str(results))
        self.assertTrue(all(set(r) == {'timestamp','startTimestamp','analysisStartTimestamp','txId','exchange'} for r in results[0]))

    def test_only_latest_cycle_even_when_selection_contains_multiple_withdrawals(self):
        row=self.export()[0]
        self.assertEqual(Decimal(row['amount']),Decimal('240.40'))
        self.assertEqual(row['datetime'],'2026-10-10T12:00:00Z')
        self.assertEqual(Decimal(row['shares']),Decimal('.001'))
        self.assertEqual(row['fee'],'0')

    def test_start_inside_cycle_restores_earlier_purchases_after_previous_withdrawal(self):
        self.assertEqual(self.export(9),self.export())

    def test_first_withdrawal_uses_all_prior_real_purchases(self):
        row=self.export(4,5)[0]
        self.assertEqual(Decimal(row['amount']),Decimal('80.20'))
        self.assertEqual(row['datetime'],'2026-10-05T12:00:00Z')

    def test_no_withdrawal_in_selected_range_means_no_export(self):
        self.assertEqual(self.export(10,12),[])

    def test_upper_bound_does_not_select_later_withdrawal(self):
        activity.append_activity_records([record('future',13,'TransferOut')])
        self.assertEqual(self.export()[0]['datetime'],'2026-10-10T12:00:00Z')

    def test_failed_pending_simulated_and_non_btc_do_not_split_cycle(self):
        other=record('eth',9,'TransferOut');other['row']['identifier']='ETH'
        activity.append_activity_records([record('failed',7,'TransferOut',status='failed'),
            record('pending',9,'TransferOut',status='submitted'),
            record('simulated',9,'TransferOut',simulated=True),other])
        self.assertEqual(Decimal(self.export()[0]['amount']),Decimal('240.40'))

    def test_purchases_at_previous_boundary_excluded_and_at_last_boundary_included(self):
        activity.append_activity_records([record('at-previous',5,amount='1000'),record('at-last',10)])
        self.assertEqual(Decimal(self.export()[0]['amount']),Decimal('320.60'))

    def test_aggregation_itself_excludes_previous_cycles_and_later_purchases(self):
        row=reporting.parqet_aggregate_rows(self.records,'KRAKEN')[0]
        self.assertEqual(Decimal(row['amount']),Decimal('240.40'))

    def test_exchange_switch_does_not_mix_withdrawal_cycles(self):
        buy=record('bitvavo-buy',7,amount='9999');buy['exchange']='BITVAVO'
        withdrawal=record('bitvavo-withdraw',9,'TransferOut');withdrawal['exchange']='BITVAVO'
        activity.append_activity_records([buy,withdrawal])
        rows=activity.parqet_interval_records(stamp(1),stamp(12))
        self.assertEqual({r['exchange'] for r in rows},{'KRAKEN'})
        self.assertEqual(Decimal(reporting.parqet_aggregate_rows(rows,'BITVAVO')[0]['amount']),Decimal('240.40'))
        all_records=activity.read_activity_records()
        self.assertEqual(Decimal(reporting.parqet_aggregate_rows(all_records,'KRAKEN')[0]['amount']),Decimal('240.40'))
        self.assertEqual(activity.latest_real_buy('KRAKEN').day,11)
        self.assertEqual(activity.latest_real_buy('BITVAVO').day,7)


    def test_selection_releases_ledger_write_lock_and_keeps_read_snapshot(self):
        entered, release = Event(), Event()
        decode = activity.json.loads

        def pause_decode(payload):
            entered.set()
            if not release.wait(5):
                raise TimeoutError("Export selection did not resume")
            return decode(payload)

        with patch.object(activity.json, "loads", side_effect=pause_decode), ThreadPoolExecutor(2) as pool:
            reader = pool.submit(activity.parqet_interval_records, stamp(1), stamp(12))
            try:
                self.assertTrue(entered.wait(2))
                writer = pool.submit(activity.append_activity_records, [record('concurrent', 7)])
                self.assertEqual(writer.result(timeout=2), 1)
            finally:
                release.set()
            self.assertEqual([item['id'] for item in reader.result()], ['buy-one', 'buy-two', 'last'])

    def test_export_uses_settled_cached_fx_on_http_failure(self):
        purchase = record("usd", 6, amount="100")
        purchase["row"]["currency"] = "USD"
        activity.append_activity_records([purchase])
        self.cache_fx(6, stored_on=14)

        response = Mock()
        response.raise_for_status.side_effect = reporting.requests.HTTPError()
        with (
            patch.object(reporting.time, "time", return_value=self.fx_time(20)),
            patch.object(reporting.requests, "get", return_value=response) as fetch,
        ):
            self.assertEqual(Decimal(self.export()[0]["amount"]), Decimal("330.58"))
        fetch.assert_called_once()

    def test_fx_outage_does_not_use_missing_invalid_or_provisional_rates(self):
        for trade_day, stored_on, rate in [(6, None, ".9"), (6, 14, "NaN"), (6, 7, ".9"), (17, 17, ".9")]:
            with self.subTest(trade_day=trade_day, stored_on=stored_on, rate=rate):
                if stored_on:
                    self.cache_fx(trade_day, stored_on, rate)
                purchase = {**record("usd", trade_day)["row"], "currency": "USD"}
                with (
                    patch.object(reporting.time, "time", return_value=self.fx_time(20)),
                    patch.object(reporting.requests, "get", side_effect=reporting.requests.Timeout),
                    self.assertRaises(reporting.requests.Timeout),
                ):
                    reporting._usd_eur_rates([purchase])

    def test_expired_provisional_rate_is_refreshed(self):
        self.cache_fx(17, stored_on=17)
        purchase = {**record("usd", 17)["row"], "currency": "USD"}
        response = Mock()
        response.json.return_value = {"rates": {"2026-10-16": {"EUR": ".95"}}}
        with (
            patch.object(reporting.time, "time", return_value=self.fx_time(20)),
            patch.object(reporting.requests, "get", return_value=response) as fetch,
        ):
            self.assertEqual(list(reporting._usd_eur_rates([purchase]).values()), [Decimal(".95")])
        fetch.assert_called_once()

    @staticmethod
    def fx_time(day):
        return datetime(2026, 10, day, 12, tzinfo=UTC).timestamp()

    def cache_fx(self, trade_day, stored_on, rate=".9"):
        with patch.object(activity.time, "time", return_value=self.fx_time(stored_on)):
            activity.cache_put_many({
                f"fx:USD:EUR:2026-10-{trade_day:02d}": {
                    "rate": rate,
                    "referenceDate": f"2026-10-{trade_day - 1:02d}",
                }
            })

    def test_http_export_uses_complete_cycle_instead_of_selected_activity_range(self):
        handler=object.__new__(web_ui.Handler)
        handler.path=f'/api/export.csv?start={stamp(9)}&end={stamp(12)}'
        handler.settings={'exchange':'KRAKEN'}
        handler._require_authentication=lambda:True
        sent=[];handler._send=lambda *args:sent.append(args)
        handler._json=lambda *args:self.fail(str(args))
        handler.do_GET()
        self.assertEqual(sent[0][0],200)
        row=list(csv.DictReader(io.StringIO(sent[0][1]),delimiter=';'))[0]
        self.assertEqual(Decimal(row['amount']),Decimal('240.40'))


if __name__=='__main__':unittest.main()
