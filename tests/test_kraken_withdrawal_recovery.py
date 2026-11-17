"""Recovery of a non-idempotent withdrawal uses Kraken history only."""

import json
import tempfile
import time
import unittest
from decimal import Decimal
from pathlib import Path
from unittest.mock import Mock, patch

import requests

from app.data import activity
from app.exchanges.kraken import Kraken, KrakenAPIError
from app.trading import bot
from app.trading.withdrawals import reconcile_withdrawals


class KrakenWithdrawalRecoveryTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        for module, name, path in (
            (activity, "ACTIVITY_PATH", root / "activity.sqlite3"),
            (bot, "STATE_PATH", root / "state.json"),
        ):
            replacement = patch.object(module, name, path)
            replacement.start()
            self.addCleanup(replacement.stop)
        self.settings = dict(exchange="KRAKEN", quote="EUR", live=True, withdrawals_enabled=False)
        self.timestamp = int(time.time() - 100)
        self.state = {
            "pending_withdrawal": dict(asset="XBT", key="wallet", amount=".0044", fee=".0001"),
            "pending_withdrawal_context": dict(
                exchange="KRAKEN", quote="EUR", price="81000", timestamp_ms=self.timestamp * 1000, manual=True
            ),
        }
        self.history_row = dict(
            asset="XXBT",
            refid="kraken-ref",
            key="wallet",
            amount=".0044",
            fee=".0001",
            time=self.timestamp + 1,
            status="Success",
            txid="tx-42",
        )
        self.api = object.__new__(Kraken)
        self.api.private = Mock(return_value=[self.history_row])
        self.api.withdraw_btc = Mock(side_effect=AssertionError("must not submit"))

    def test_unique_history_recovers_when_paused_and_restores_verified_activity(self):
        self.settings["transaction_gate"] = lambda: True
        bot.maybe_withdraw_btc(self.api, self.state, self.settings)
        self.api.withdraw_btc.assert_not_called()
        self.assertEqual(
            self.api.private.call_args.args[0],
            "WithdrawStatus",
        )
        self.assertNotIn("pending_withdrawal", self.state)
        self.assertEqual(self.state["last_withdrawal"]["id"], "kraken-ref")
        (record,) = activity.read_activity_records()
        self.assertEqual(record["withdrawalStatus"], "completed")
        self.assertEqual(record["txId"], "tx-42")
        self.assertTrue(record["manual"])

    def test_absent_or_ambiguous_evidence_keeps_the_request_pending(self):
        for rows in (
            [],
            [dict(self.history_row, key="other")],
            [dict(self.history_row, key=None)],
            [dict(self.history_row, asset="ETH")],
            [dict(self.history_row, amount=".0043")],
            [dict(self.history_row, fee=".0002")],
            [dict(self.history_row, fee=None)],
            [dict(self.history_row, time=self.timestamp - 2)],
            [dict(self.history_row, time=self.timestamp)],
            [dict(self.history_row, time=self.timestamp + 60)],
            [dict(self.history_row, refid="")],
            [dict(self.history_row, status=None)],
            [self.history_row, dict(self.history_row, refid="different-ref")],
            [self.history_row, dict(self.history_row, refid="different-ref", key=None)],
            [self.history_row, dict(self.history_row, key="other")],
        ):
            with self.subTest(rows=rows):
                self.state["pending_withdrawal_context"]["timestamp_ms"] = self.timestamp * 1000 + 1
                self.api.private.return_value = rows
                bot.maybe_withdraw_btc(self.api, self.state, self.settings)
                self.assertIn("pending_withdrawal", self.state)
                self.assertEqual(activity.read_activity_records(), [])
                self.api.withdraw_btc.assert_not_called()

    def test_recovery_after_interrupted_activity_write_reuses_saved_result(self):
        self.api.private.return_value = [dict(self.history_row, status="Pending")]
        insert = bot.persist_bot_withdrawal

        def insert_then_interrupt(*args):
            insert(*args)
            raise OSError("Process interrupted after Activity insert")

        with patch.object(bot, "persist_bot_withdrawal", side_effect=insert_then_interrupt):
            with self.assertRaises(OSError):
                bot.maybe_withdraw_btc(self.api, self.state, self.settings)
        saved_state = json.loads(bot.STATE_PATH.read_text())
        self.api.private.reset_mock()
        bot.maybe_withdraw_btc(self.api, saved_state, self.settings)
        self.api.private.assert_not_called()
        self.api.withdraw_btc.assert_not_called()
        self.assertNotIn("pending_withdrawal", saved_state)
        self.assertEqual([r["withdrawalStatus"] for r in activity.read_activity_records()], ["submitted"])
        self.api.private.return_value = [self.history_row]
        reconcile_withdrawals(self.api, self.settings, force=True)
        self.assertEqual([r["withdrawalStatus"] for r in activity.read_activity_records()], ["completed"])

    def test_success_without_reference_is_an_uncertain_outcome(self):
        self.api.private.return_value = {}
        with self.assertRaises(KrakenAPIError):
            Kraken.withdraw_btc(self.api, self.state["pending_withdrawal"])

    def test_lost_response_uses_the_saved_attempt_after_restart(self):
        self.api.withdraw_btc.side_effect = requests.ReadTimeout("response lost")
        self.api.balance = Mock(return_value=Decimal(".0045"))
        self.api.price = Mock(return_value=Decimal("81000"))
        now = self.timestamp
        with patch.object(bot.time, "time", return_value=now):
            bot.maybe_withdraw_btc(self.api, {}, self.settings, manual_request=self.state["pending_withdrawal"])
        state = json.loads(bot.STATE_PATH.read_text())
        self.assertEqual(state["pending_withdrawal_context"]["kraken_recovery_until_ms"], (now + 40) * 1000)
        bot.maybe_withdraw_btc(self.api, state, self.settings)
        self.api.withdraw_btc.assert_called_once()
        self.assertNotIn("pending_withdrawal", state)
        self.assertEqual(activity.read_activity_records()[0]["withdrawalId"], self.history_row["refid"])

    def test_completed_recovery_waits_for_the_previous_balance_to_decrease(self):
        self.state["pending_withdrawal_context"]["balanceBefore"] = ".0045"
        bot.maybe_withdraw_btc(self.api, self.state, self.settings)
        self.settings.update(withdrawals_enabled=True, withdraw_threshold=Decimal("100"))
        self.api.balance = Mock(side_effect=[Decimal(".0045"), Decimal(".005"), Decimal(".004")])
        self.api.price = Mock(return_value=Decimal("81000"))
        self.api.withdrawal_request = Mock(return_value=self.state["last_withdrawal"] | {"asset": "XBT", "amount": ".0039"})
        self.api.withdraw_btc.side_effect = None
        self.api.withdraw_btc.return_value = {"id": "new-withdrawal"}
        for _ in range(2):
            bot.maybe_withdraw_btc(self.api, self.state, self.settings)
            self.api.withdraw_btc.assert_not_called()
        bot.maybe_withdraw_btc(self.api, self.state, self.settings)
        self.api.withdraw_btc.assert_called_once()
