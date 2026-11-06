"""Serialize configuration changes with the single exchange account worker."""

import hmac
import json
import logging
import time
from pathlib import Path

from app.core.configuration import ConfigStore, ConfigurationError, account_values, runtime_settings, validate
from app.core.security import AttemptLimiter, PasswordConfirmationError
from app.data.storage import STATE_PATH
from app.exchanges.exchange import create_exchange
from app.trading.identity import account_identity

LOG = logging.getLogger("bitcoin-dca.settings")
IDENTITY_FIELDS = ("exchange", "quote", "kraken_api_key", "kraken_api_secret", "bitvavo_api_key", "bitvavo_api_secret")


class Runtime:
    def __init__(self, store=None, state_path=None):
        from app.trading.account import ACCOUNT_LOCK
        from app.trading.worker import Worker

        self.lock = ACCOUNT_LOCK
        from app.data.backup import recover_restore

        recover_restore(Path(state_path).parent if state_path is not None else STATE_PATH.parent)
        self.store = store or ConfigStore()
        self.state_path = Path(state_path) if state_path is not None else STATE_PATH
        self.settings = runtime_settings(self.store.snapshot()["settings"])
        self.settings["account_identity"] = account_identity(self.settings)
        from app.trading.controls import PauseControl

        self.controls = PauseControl(self.state_path.with_name("controls.json"))
        self.settings["transaction_gate"] = (
            lambda: self.controls.snapshot()["paused"] or self.state_path.with_name(".restore-journal").exists()
        )
        self.api = None
        self.service = None
        self.session_validator = lambda token: False
        self.invalidate_sessions = lambda: None
        self._configuration_uncertain = False
        self.password_attempts = AttemptLimiter(capacity=1)
        self.setup_restore_attempts = AttemptLimiter(capacity=1)
        self.startup_pending = True
        self.exchange_check_pending = True
        self.ready_at = time.monotonic() + self.settings["startup_delay_seconds"]
        self.worker = Worker(self.cycle, self.action, self.settings["check_interval_seconds"])
        if self.store.snapshot()["complete"]:
            self.api = create_exchange(self.settings)
            self._synchronize_state()
        LOG.info(
            "Application configuration loaded"
            if self.api
            else "Waiting for first-run configuration; purchases are paused"
        )

    @property
    def recovery_required(self):
        """A durable unfinished restore blocks financial work until restart recovery."""
        return self.state_path.with_name(".restore-journal").exists()

    def shutdown(self):
        finished = self.worker.shutdown()
        if finished and self.lock.acquire(timeout=5):
            try:
                self.service = None
                self._close_adapter(self.api)
            finally:
                self.lock.release()
        elif finished:
            LOG.warning("An account request is still finishing; connection cleanup deferred to process exit")
        return finished

    @staticmethod
    def _close_adapter(adapter):
        if adapter and hasattr(adapter, "session"):
            try:
                adapter.session.close()
            except Exception:
                LOG.warning("Previous exchange connection could not be closed cleanly")

    def _recover_configuration(self):
        """Reload the durable source after an interrupted save; fail closed on any error."""
        if not self._configuration_uncertain:
            return
        with self.store.lock:
            data = self.store._read(self.store.path)
            if not data.get("account"):
                raise RuntimeError("Stored settings could not be verified; transactions remain paused.")
            # A failed fsync may follow a successful replace. Confirm durability
            # before letting either the old or the new configuration trade.
            self.store._write(data)
            values = runtime_settings(data["settings"])
            values["account_identity"] = account_identity(values)
            adapter = create_exchange(values) if data["complete"] else None
            old_api = self.api
            from app.data.storage import installation_started_at

            self.store.first_started_at = installation_started_at(self.store.path.parent)
            self.store.data = data
            self.settings.update(values)
            self.api = adapter
            self.service = None
            self.exchange_check_pending = self.startup_pending = True
            self.worker.interval = values["check_interval_seconds"]
            self.ready_at = time.monotonic()
            self.invalidate_sessions()
            self._close_adapter(old_api)
            if self.api:
                self._synchronize_state()
            self._configuration_uncertain = False
            LOG.info("Stored settings verified after interrupted save; automatic exchange check required")

    def _check_exchange_activity(self):
        """Read-only startup gate; never submit or retry financial requests here."""
        from app.core.logging_utils import log_transition
        from app.data.activity import withdrawal_records
        from app.trading.withdrawals import reconcile_withdrawals

        orders = self.api.open_orders()
        if not isinstance(orders, list):
            raise ValueError("Open exchange orders could not be verified.")
        transfers = self.api.btc_withdrawals(0, int(time.time() * 1000))
        if not isinstance(transfers, list):
            raise ValueError("Complete withdrawal status could not be verified.")
        terminal = {"completed", "success", "failed", "failure", "canceled", "cancelled"}
        pending = any(
            not isinstance(item, dict) or str(item.get("status", "")).lower() not in terminal for item in transfers
        )
        reconcile_withdrawals(self.api, self.settings, force=True, submitted_only=True)
        recorded = any(
            row.get("withdrawalStatus") == "submitted" and row.get("exchange") in ("", None, self.settings["exchange"])
            for row in withdrawal_records(unresolved=True)
        )
        if orders or pending or recorded:
            log_transition(
                LOG,
                self,
                "startup-exchange-check",
                "waiting",
                logging.INFO,
                "Startup exchange check: waiting for open orders or Bitcoin withdrawals to close; new transactions are paused",
            )
            return False
        self.exchange_check_pending = False
        LOG.info("Startup exchange check passed: no open orders or Bitcoin withdrawals; scheduling may resume")
        return True

    def unresolved(self):
        from app.data.activity import withdrawal_records

        state = json.loads(self.state_path.read_text()) if self.state_path.exists() else {}
        return bool(
            state.get("pending_order")
            or state.get("pending_withdrawal")
            or state.get("pending_withdrawal_context")
            or state.get("fiat_observation", {}).get("pending")
            or withdrawal_records(unresolved=True)
        )

    def _synchronize_state(self):
        from app.data.activity import write_json_atomic

        identity = [self.settings["exchange"], self.settings["quote"], account_identity(self.settings)]
        state = json.loads(self.state_path.read_text()) if self.state_path.exists() else {}
        if (
            state.get("configuration_account", identity) != identity
            or state.get("configuration_live", self.settings["live"]) != self.settings["live"]
        ):
            if self.unresolved():
                raise ValueError(
                    "Resolve pending transactions before changing exchange, account credentials or purchase currency."
                )
            # Keep historical activity untouched; old account scheduling must not carry over.
            write_json_atomic(self.state_path.with_name("previous-account-state.json"), state)
            state = {}
        if state.get("configuration_account") != identity or state.get("configuration_live") != self.settings["live"]:
            state["configuration_account"] = identity
            state["configuration_live"] = self.settings["live"]
            write_json_atomic(self.state_path, state)

    def cycle(self):
        from app.trading.bot import latest_recorded_buy_time, run_once, update_dashboard_schedule

        with self.lock:
            if self.worker.stop.is_set():
                return self.worker.interval
            self._recover_configuration()
            if not self.api:
                return self.worker.interval
            remaining = self.ready_at - time.monotonic()
            if remaining > 0:
                update_dashboard_schedule(None, "Waiting for startup delay")
                return max(1, remaining)
            self._synchronize_state()
            if self.exchange_check_pending:
                update_dashboard_schedule(None, "Checking exchange for open orders and withdrawals")
                if not self._check_exchange_activity():
                    update_dashboard_schedule(None, "Waiting for open exchange orders or withdrawals")
                    return self.worker.interval
            if self.startup_pending:
                self.settings["startup_last_buy_at"] = latest_recorded_buy_time(
                    self.settings["exchange"], account_identity=self.settings["account_identity"]
                )
                self.settings["startup_schedule_log_pending"] = True
                LOG.info(
                    "Startup history: last real Bitcoin purchase on %s=%s; aligning the purchase schedule",
                    self.settings["exchange"],
                    self.settings["startup_last_buy_at"] or "none",
                )
                self.startup_pending = False
            return run_once(self.api, self.settings, self.worker.interval)

    def action(self, action, session, token=None):
        from app.trading.bot import manual_withdrawal_service

        with self.lock:
            if self.worker.stop.is_set():
                raise ValueError("Container is stopping; request was not executed.")
            if self._configuration_uncertain:
                raise ValueError("Settings storage is being verified; transactions remain paused.")
            if self.controls.snapshot()["paused"] or self.state_path.with_name(".restore-journal").exists():
                raise ValueError("Transactions are paused. Resume in Settings first.")
            if not self.api or not self.settings["manual_withdrawal_enabled"]:
                raise ValueError("Manual withdrawals are disabled in Settings.")
            if self.exchange_check_pending:
                raise ValueError(
                    "Waiting for the automatic exchange check and any open orders or withdrawals to close."
                )
            if not self.session_validator(session):
                raise ValueError("Your session expired. Sign in again before requesting a withdrawal.")
            if not self.service:
                self.service = manual_withdrawal_service(self.api, self.settings)
            return self.service(action, session, token)

    def save(self, payload):
        with self.lock, self.store.lock:
            if self.worker.stop.is_set():
                raise ValueError("Container is stopping; settings were not changed.")
            self._recover_configuration()
            if not isinstance(payload, dict) or set(payload) - {
                "settings",
                "username",
                "password",
                "current_password",
                "pause",
            }:
                raise ValueError("Invalid settings request.")
            previous = self.store.snapshot()
            values = validate(payload.get("settings", {}), previous["settings"])
            pause_requested = payload.get("pause")
            if "pause" in payload and type(pause_requested) is not bool:
                raise ValueError("Invalid pause request.")
            if pause_requested and not values["live"]:
                raise ValueError("Enable live trading to pause transactions.")
            if previous["settings"]["live"] and not values["live"]:
                pause_requested = False
            if pause_requested is not None and self.recovery_required:
                raise ValueError("Restore recovery is required; restart the container before resuming.")
            account = previous["account"]
            if not account:
                raise ValueError("Create a dashboard account first.")
            account_changed = bool(
                payload.get("password") or payload.get("username", account["username"]) != account["username"]
            )
            protected_fields = IDENTITY_FIELDS + (
                "withdraw_address",
                "withdraw_network",
                "kraken_withdraw_key",
                "withdraw_threshold",
            )
            sensitive = previous["complete"] and (
                any(values[k] != previous["settings"][k] for k in protected_fields)
                or values["live"]
                and not previous["settings"]["live"]
                or values["withdrawals_enabled"]
                and not previous["settings"]["withdrawals_enabled"]
            )
            if account_changed or sensitive:
                retry = self.password_attempts.consume(account["username"])
                if retry:
                    raise PasswordConfirmationError("Too many password confirmation attempts. Try again later.", retry)
                if not self.store.authenticate(account["username"], payload.get("current_password", "")):
                    LOG.info("Sensitive settings update rejected: current password verification failed")
                    raise PasswordConfirmationError("Your current password is incorrect.")
                self.password_attempts.clear(account["username"])
                LOG.info("Current password verified for sensitive settings update")
            if account_changed:
                username = payload.get("username") or account["username"]
                password = payload.get("password", "")
                if password:
                    account = account_values(username, password)
                else:
                    if not isinstance(username, str) or not 3 <= len(username.strip()) <= 64:
                        raise ValueError("Username must contain 3–64 characters.")
                    account = {**account, "username": username.strip()}
            identity_changed = any(values[key] != previous["settings"][key] for key in IDENTITY_FIELDS)
            financial_mode_changed = values["live"] != previous["settings"]["live"]
            if (identity_changed or financial_mode_changed) and (
                self.unresolved() or self.worker.queue.unfinished_tasks
            ):
                LOG.info(
                    "Settings update blocked: unresolved transactions or queued account actions; configuration unchanged"
                )
                raise ValueError(
                    "Resolve pending orders, withdrawals and queued requests before changing exchange, credentials, currency or trading mode."
                )
            settings = runtime_settings(values)
            settings["account_identity"] = account_identity(settings)
            adapter_changed = (
                self.api is None
                or identity_changed
                or values["kraken_withdraw_key"] != previous["settings"]["kraken_withdraw_key"]
            )
            adapter = create_exchange(settings) if adapter_changed else self.api
            previous_gate = self.exchange_check_pending
            try:
                if values["withdrawals_enabled"]:
                    adapter.validate_withdrawal_settings(settings)
                # Set the financial gate before the first fallible write. If any
                # write fails, only a verified durable reload may release it.
                self._configuration_uncertain = True
                self.exchange_check_pending = True
                self.service = None
                if identity_changed:
                    from app.data.activity import write_dashboard_snapshot

                    write_dashboard_snapshot(
                        {
                            "exchange": values["exchange"],
                            "quote": values["quote"],
                            "nextPurchaseAt": None,
                            "nextPurchaseStatus": "Waiting for account check",
                        }
                    )
                # Persist the restrictive gate before activating live trading.
                # Clearing pause comes only after the new configuration is durable.
                if pause_requested is True:
                    self.controls.set(True)
                self.store.commit(values, account)
                if pause_requested is False:
                    self.controls.set(False)
            except Exception:
                if adapter_changed:
                    self._close_adapter(adapter)
                raise
            # A shared mapping keeps existing HTTP handlers up to date. Preserve running
            # scheduling metadata for cosmetic feature toggles and account edits.
            schedule_fields = (
                "exchange",
                "quote",
                "buy_amount",
                "deposit_day",
                "deposit_time",
                "timezone",
                "live",
                "check_interval_seconds",
                "startup_delay_seconds",
                "order_status_check_seconds",
            )
            schedule_changed = (
                not previous["complete"]
                or identity_changed
                or any(values[k] != previous["settings"][k] for k in schedule_fields)
            )
            self.settings.update(settings)
            old_api = self.api
            self.api = adapter
            if adapter_changed:
                self._close_adapter(old_api)
            self.service = None  # Invalidate all previews after any configuration change.
            self.worker.interval = values["check_interval_seconds"]
            self.exchange_check_pending = (
                previous_gate or not previous["complete"] or identity_changed or financial_mode_changed
            )
            self._configuration_uncertain = False
            if pause_requested is not None:
                self.worker.reconfigure.set()
                LOG.info("Transaction pause saved with settings: paused=%s", pause_requested)
            if schedule_changed:
                self.settings.pop("startup_last_buy_at", None)
                self.startup_pending = True
                self.ready_at = time.monotonic() + (values["startup_delay_seconds"] if not previous["complete"] else 0)
                self.worker.reconfigure.set()
            changed_fields = sorted(key for key in values if values[key] != previous["settings"][key])
            if not previous["complete"]:
                LOG.info(
                    "First-run bot configuration completed: exchange=%s; live trading=%s; startup delay=%ss",
                    values["exchange"],
                    values["live"],
                    values["startup_delay_seconds"],
                )
            LOG.info(
                "Settings applied: changed fields=%s; account credentials changed=%s; purchase schedule refresh requested=%s",
                ",".join(changed_fields) or "none",
                account_changed,
                schedule_changed,
            )
            LOG.info(
                "Application settings saved: exchange=%s; live trading=%s; automatic withdrawals=%s; manual withdrawals=%s; Parqet=%s",
                values["exchange"],
                values["live"],
                values["withdrawals_enabled"],
                values["manual_withdrawal_enabled"],
                values["parqet_enabled"],
            )
            return account_changed

    def save_forecast_deposit(self, payload):
        """Persist a reporting assumption without touching the exchange worker."""
        if not isinstance(payload, dict) or set(payload) != {"monthlyDeposit"}:
            raise ValueError("Invalid monthly deposit request.")
        with self.store.lock:
            if self._configuration_uncertain or self.worker.stop.is_set():
                raise ValueError("Settings are being verified or the container is stopping; try again later.")
            previous = self.store.snapshot()
            if not previous["complete"]:
                raise ValueError("Complete initial configuration first.")
            values = validate({"expected_monthly_deposit": payload["monthlyDeposit"]}, previous["settings"])
            amount = values["expected_monthly_deposit"]
            if amount != previous["settings"].get("expected_monthly_deposit", ""):
                self.store.commit(values)
                self.settings["expected_monthly_deposit"] = amount
                LOG.info(
                    "Expected monthly deposit saved: amount=%s %s; forecast only; purchase schedule unchanged",
                    amount or "unset",
                    values["quote"],
                )
            return {"monthlyDeposit": amount}

    def save_report_from(self, payload):
        if not isinstance(payload, dict) or set(payload) != {"from"}:
            raise ValueError("Invalid report start request.")
        if self.worker.stop.is_set():
            raise ValueError("Container is stopping; try again later.")
        value = self.store.save_report_from(payload["from"])
        LOG.info("Period Analysis start date saved: from=%s; purchase schedule unchanged", value)
        return {"from": value}

    def test_connection(self, payload):
        # Read-only and serialized so a connection test cannot race a financial action.
        with self.lock:
            if self.worker.stop.is_set():
                raise ValueError("Container is stopping; connection test was not started.")
            values = validate(payload, self.store.snapshot()["settings"])
            LOG.info(
                "Exchange connection test started: exchange=%s; quote currency=%s; read-only balance and deposit-history access",
                values["exchange"],
                values["quote"],
            )
            started = time.monotonic()
            api = create_exchange(runtime_settings(values))
            try:
                from app.exchanges.permissions import check_permissions

                permissions = check_permissions(api, values["quote"])
                LOG.info(
                    "Exchange connection test succeeded; read-only permission check completed: exchange=%s; duration=%.2fs",
                    values["exchange"],
                    time.monotonic() - started,
                )
                return {
                    "message": "Read-only permission check completed. No order or withdrawal was submitted.",
                    "permissions": permissions,
                }
            finally:
                if hasattr(api, "session"):
                    api.session.close()

    def set_pause(self, payload):
        """Serialize pause changes with financial actions, retaining the schedule."""
        if not isinstance(payload, dict) or set(payload) - {"paused", "until"}:
            raise ValueError("Invalid pause request.")
        with self.lock:
            if self.state_path.with_name(".restore-journal").exists():
                raise ValueError("Restore recovery is required; restart the container before resuming.")
            if payload.get("paused") is True and not self.settings.get("live", False):
                raise ValueError("Enable and save live trading before pausing transactions.")
            result = self.controls.set(payload.get("paused"), payload.get("until"))
            self.service = None
            self.worker.reconfigure.set()
            LOG.info("Transaction pause updated: paused=%s; until=%s", result["paused"], result["until"])
            return result

    def _require_empty_installation(self):
        from app.data.activity import has_activity_records

        saved = self.store.snapshot()
        state = json.loads(self.state_path.read_text()) if self.state_path.exists() else {}
        if saved["account"] is not None or saved["complete"] or state or has_activity_records():
            raise ValueError("Initial backup restore is available only on an empty installation without an account.")

    def reserve_setup_restore(self):
        """Reject closed or exhausted setup before the HTTP handler reads an upload."""
        with self.lock, self.store.lock:
            self._require_empty_installation()
            retry = self.setup_restore_attempts.consume("initial-backup-restore")
            if retry:
                raise PasswordConfirmationError("Too many password confirmation attempts. Try again later.", retry)

    def backup(self, payload, restore=False, setup=False, *, setup_attempt_reserved=False):
        """Reauthenticate, or allow initial restore only before an account or history exists."""
        import base64

        from app.data.backup import MAX_BYTES, Backups

        allowed = (
            {"password", "archive"}
            if setup
            else (
                {"scope", "password", "current_password", "archive"}
                if restore
                else {"scope", "password", "current_password"}
            )
        )
        if not isinstance(payload, dict) or set(payload) != allowed or setup and not restore:
            raise ValueError("Invalid backup request.")
        with self.lock, self.store.lock:
            saved = self.store.snapshot()
            account = saved["account"]
            if setup:
                self._require_empty_installation()
            elif not account:
                raise ValueError("Complete dashboard account setup first.")
            attempt_key = "initial-backup-restore" if setup else account["username"]
            attempts = self.setup_restore_attempts if setup else self.password_attempts
            retry = 0 if setup and setup_attempt_reserved else attempts.consume(attempt_key)
            if retry:
                raise PasswordConfirmationError("Too many password confirmation attempts. Try again later.", retry)
            if not setup and not self.store.authenticate(account["username"], payload["current_password"]):
                raise PasswordConfirmationError("Your current password is incorrect.")
            if not setup:
                attempts.clear(attempt_key)
            if self.worker.stop.is_set() or self._configuration_uncertain:
                raise ValueError("Settings are being verified or the container is stopping; try again later.")
            manager = Backups(self.state_path.parent)
            if not restore:
                if isinstance(payload["password"], str) and hmac.compare_digest(
                    payload["password"].encode("utf-8"), payload["current_password"].encode("utf-8")
                ):
                    raise ConfigurationError(
                        "Backup password must be different from the dashboard password.", "backupPassword"
                    )
                filename, encrypted = manager.create(payload["scope"], payload["password"])
                LOG.info("Encrypted backup created: scope=%s", payload["scope"])
                return {"filename": filename, "archive": base64.b64encode(encrypted).decode()}
            if not isinstance(payload["archive"], str) or len(payload["archive"]) > (MAX_BYTES + 128) * 4 // 3 + 4:
                raise ValueError("Backup exceeds the 32 MiB limit.")
            try:
                encrypted = base64.b64decode(payload["archive"], validate=True)
            except ValueError:
                raise ValueError("Invalid backup encoding.") from None
            if self.unresolved() or self.worker.queue.unfinished_tasks:
                raise ValueError("Resolve pending transactions and queued requests before restoring a backup.")
            try:
                result = manager.restore(encrypted, payload["password"], None if setup else payload["scope"])
            except BaseException:
                self.exchange_check_pending = True
                self.service = None
                if self.recovery_required:
                    LOG.error("Restore recovery required; restart the container. New transactions remain blocked.")
                    self.controls.set(True)
                raise
            self._configuration_uncertain = True
            self._recover_configuration()
            self.invalidate_sessions()
            self.worker.reconfigure.set()
            attempts.clear(attempt_key)
            LOG.info(
                "Encrypted backup restored: scope=%s; transactions paused=%s; automatic exchange check required",
                result["scope"],
                result["paused"],
            )
            return {**result, "signInRequired": True}
