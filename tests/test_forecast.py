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

class ForecastPurchaseCountTests(unittest.TestCase):
    def test_count_includes_larger_final_purchases_in_each_month(self):
        from app.core.planning import plan_order
        from decimal import Decimal as D
        rules = dict(minOrderInBaseAsset='.001', minOrderInQuoteAsset='0',
                     quantityDecimals=8, notionalDecimals=2)
        plan = plan_order(rules, '.001', '100000', '0', '190')
        settings = dict(live=True, withdrawals_enabled=True, withdraw_threshold='1900',
                        quote='EUR', expected_monthly_deposit='190', timezone='UTC',
                        deposit_day=1, deposit_time='00:00')
        snapshot = dict(btcBalance='0', price='100000', nextPurchaseAt='2026-11-01T00:00:00Z',
                        withdrawalForecastPlan=dict(orderAmount=str(plan.quantity), plannedCost=str(plan.cost),
                        baseOrderAmount=str(plan.base_quantity), basePlannedCost=str(plan.base_cost), budget='190',
                        intervalSeconds=2592000, nextDepositAt='2026-12-01T00:00:00Z', marketRules=rules, feeRate='0'))
        now = datetime(2026, 11, 1, tzinfo=timezone.utc)
        self.assertEqual(plan.quantity, D('.0019'))
        self.assertEqual(forecast.forecast_details(settings, snapshot, now)['remainingPurchases'], 10)
        self.assertEqual(forecast.withdrawal_forecast(settings, snapshot, '190',
                         now)[0], '2027-08-01T00:00:00+00:00')
        snapshot['btcBalance'] = '.019'
        self.assertEqual(forecast.forecast_details(settings, snapshot, now)['remainingPurchases'], 0)
