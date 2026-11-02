"""Account-key boundaries preserve history without reusing another account's schedule."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from app.data import activity
from app.trading import bot


def buy(identifier, when, identity=None):
    record = {'id': identifier, 'exchange': 'KRAKEN', 'row': {
        'datetime': when, 'type': 'Buy', 'identifier': 'BTC', 'currency': 'EUR',
        'shares': '.001', 'amount': '80', 'fee': '.2', 'price': '80000'}}
    if identity:
        record['accountIdentity'] = identity
    return record


class AccountHistoryTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        for key, name in [('ACTIVITY_PATH', 'activity.json'), ('SNAPSHOT_PATH', 'dashboard.json')]:
            fixture = patch.object(activity, key, Path(directory.name) / name)
            fixture.start()
            self.addCleanup(fixture.stop)

    def test_legacy_history_is_claimed_once_and_keys_have_independent_last_buys(self):
        activity.append_activity_records([buy('legacy', '2026-10-01T12:00:00Z')])
        activity.bind_legacy_account('KRAKEN', 'EUR', 'first-key')
        activity.bind_legacy_account('KRAKEN', 'EUR', 'second-key')
        self.assertEqual(bot.latest_recorded_buy_time('KRAKEN', 'first-key').day, 1)
        self.assertIsNone(bot.latest_recorded_buy_time('KRAKEN', 'second-key'))
        activity.append_activity_records([buy('new-account', '2026-10-05T12:00:00Z', 'second-key')])
        self.assertEqual(bot.latest_recorded_buy_time('KRAKEN', 'first-key').day, 1)
        self.assertEqual(bot.latest_recorded_buy_time('KRAKEN', 'second-key').day, 5)

    def test_account_tag_survives_reconciliation_retry_without_duplicate_buy(self):
        from unittest.mock import Mock
        api = Mock()
        api.normalize_bot_buy.side_effect = lambda *args: [buy('trade-ref', '2026-10-05T12:00:00Z')]
        settings = {'exchange': 'KRAKEN', 'quote': 'EUR', 'account_identity': 'first-key'}
        bot.persist_bot_buy(api, {}, settings, 'event', 0)
        bot.persist_bot_buy(api, {}, settings, 'event', 0)
        records = activity.read_activity_records()
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]['accountIdentity'], 'first-key')

    def test_matching_legacy_trade_id_cannot_be_claimed_by_a_new_key(self):
        from unittest.mock import Mock
        activity.append_activity_records([buy('trade-ref', '2026-10-01T12:00:00Z')])
        activity.bind_legacy_account('KRAKEN', 'EUR', 'first-key')
        api = Mock()
        api.normalize_bot_buy.return_value = [buy('trade-ref', '2026-10-05T12:00:00Z')]
        bot.persist_bot_buy(api, {}, {'exchange':'KRAKEN','quote':'EUR','account_identity':'second-key'}, 'event', 0)
        self.assertEqual(len(activity.read_activity_records()), 2)
        self.assertEqual(activity.latest_real_buy('KRAKEN', 'second-key').day, 5)

    def test_account_export_does_not_absorb_another_accounts_purchase(self):
        rows = [buy('first-buy', '2026-10-01T12:00:00Z', 'first-key'),
                buy('second-buy', '2026-10-02T12:00:00Z', 'second-key')]
        ending = buy('ending', '2026-10-03T12:00:00Z', 'second-key')
        ending['row']['type'] = 'TransferOut'
        ending['withdrawalStatus'] = 'completed'
        activity.append_activity_records([*rows, ending])
        records = activity.parqet_interval_records(0, 2**62)
        self.assertEqual({r.get('accountIdentity') for r in records}, {'second-key'})
