"""Forecast input failures remain distinct from programming failures."""
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from app.trading import forecast


class ForecastFailureTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 10, 29, tzinfo=timezone.utc)
        self.settings = dict(live=True, withdrawals_enabled=True, withdraw_threshold=500,
                             deposit_day=1, timezone='UTC')
        self.snapshot = dict(btcBalance='.001', price='100000', withdrawalForecastPlan=dict(
            orderAmount='.001', plannedCost='101', budget='202', intervalSeconds=86400,
            nextDepositAt='2026-11-01T00:00:00+00:00'))

    def test_missing_snapshot_waits_but_invalid_supplied_data_is_unavailable(self):
        self.assertEqual(forecast.withdrawal_forecast(self.settings, {}, '202', self.now)[1],
                         'Waiting for account price and order minimums')
        for value in ('bad', '-1', 'NaN', None):
            with self.subTest(value=value):
                self.snapshot['price'] = value
                self.assertEqual(forecast.withdrawal_forecast(self.settings, self.snapshot, '202', self.now)[1],
                                 'Forecast unavailable: invalid account or order data')

    def test_invalid_input_warning_is_deduplicated(self):
        self.snapshot['price'] = 'bad'
        with patch.object(forecast, '_LAST_INVALID', None), patch.object(forecast.LOG, 'warning') as warning:
            forecast.withdrawal_forecast(self.settings, self.snapshot, '202', self.now)
            forecast.withdrawal_forecast(self.settings, self.snapshot, '202', self.now)
        self.assertEqual(warning.call_count, 1)

    def test_programming_errors_are_not_reported_as_waiting(self):
        with patch.object(forecast, 'deposit_at', side_effect=TypeError('programming mistake')):
            with self.assertRaisesRegex(TypeError, 'programming mistake'):
                forecast.withdrawal_forecast(self.settings, self.snapshot, '202', self.now)

    def test_reached_threshold_needs_no_future_order_reference(self):
        self.snapshot.pop('withdrawalForecastPlan')
        self.snapshot['btcBalance'] = '.005'
        self.assertEqual(forecast.withdrawal_forecast(self.settings, self.snapshot, '202', self.now)[0],
                         self.now.isoformat())

    def test_absent_order_fields_wait_and_invalid_order_fields_do_not(self):
        plan = self.snapshot['withdrawalForecastPlan']
        plan.pop('budget')
        self.assertEqual(forecast.withdrawal_forecast(self.settings, self.snapshot, '202', self.now)[1],
                         'Waiting for account price and order minimums')
        plan['budget'] = '202'
        plan['nextDepositAt'] = 'invalid date'
        self.assertEqual(forecast.withdrawal_forecast(self.settings, self.snapshot, '202', self.now)[1],
                         'Forecast unavailable: invalid account or order data')
