"""Offline operational safety regression coverage."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from app.trading import runtime
from app.trading.controls import PauseControl


class PauseTests(unittest.TestCase):
    def test_pause_is_durable_bounded_and_does_not_replace_schedule(self):
        from app.trading.controls import PauseControl
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'controls.json'
            control = PauseControl(path)
            control.set(True, '2030-01-01T00:00:00Z')
            self.assertTrue(PauseControl(path).snapshot(now=1)['paused'])
            self.assertFalse(control.snapshot(now=2000000000)['paused'])
            self.assertTrue(json.loads(path.read_text())['paused'])
            for until in ['bad', '2030-01-01', 123]:
                with self.assertRaises(ValueError): control.set(True, until)
            control.set(False)
            self.assertFalse(control.snapshot()['paused'])

    def test_manual_action_is_rejected_before_exchange_access(self):
        account = object.__new__(runtime.Runtime)
        import threading
        account.lock = threading.RLock()
        account.worker = Mock()
        account.worker.stop.is_set.return_value = False
        account._configuration_uncertain = False
        account.api = Mock()
        account.settings = {'manual_withdrawal_enabled': True}
        account.exchange_check_pending = False
        account.store = Mock()
        account.store.snapshot.return_value = {'account': {}}
        account.session_validator = lambda session: True
        account.service = Mock(return_value={})
        account.state_path = Path("/tmp/no-restore-test/state.json")
        account.controls = Mock()
        account.controls.snapshot.return_value = {'paused': True}
        with self.assertRaisesRegex(ValueError, 'paused'):
            account.action('confirm', 'session', 'token')

    def test_resume_keeps_corrupt_controls_fail_closed(self):
        from threading import RLock
        from app.trading.controls import PauseControl

        with tempfile.TemporaryDirectory() as tmp:
            account = object.__new__(runtime.Runtime)
            account.lock = RLock()
            account.state_path = Path(tmp) / "state.json"
            account.settings = {"live": True}
            account.worker = Mock()
            path = account.state_path.with_name("controls.json")
            path.write_text("{broken")
            account.controls = PauseControl(path)
            with self.assertRaisesRegex(ValueError, "controls"):
                account.set_pause({"paused": False})
            self.assertEqual(path.read_text(), "{broken")

    def test_pause_can_only_be_enabled_with_saved_live_trading(self):
        import threading
        account=object.__new__(runtime.Runtime)
        account.lock=threading.RLock()
        account.settings={'live':False}
        account.controls=Mock()
        account.controls.set.return_value={'paused':True,'until':None}
        account.worker=Mock()
        with tempfile.TemporaryDirectory() as tmp:
            account.state_path=Path(tmp)/'state.json'
            with self.assertRaisesRegex(ValueError,'live trading'):
                account.set_pause({'paused':True,'until':None})
            account.controls.set.assert_not_called()
            account.settings['live']=True
            account.set_pause({'paused':True,'until':None})
            account.controls.set.assert_called_once_with(True,None)
            account.settings['live']=False
            account.set_pause({'paused':False,'until':None})
            account.controls.set.assert_called_with(False,None)

class ActivityFilterTests(unittest.TestCase):
    def test_report_and_worker_share_the_dedicated_exact_balance_query(self):
        from decimal import Decimal
        from app.data import activity

        rows = [
            ("buy", "Buy", "BTC", "0.12345678", False),
            ("simulation", "Buy", "BTC", "9", True),
            ("other", "Buy", "ETH", "9", False),
            ("withdrawal", "TransferOut", "BTC", "0.01234567", False),
        ]
        records = [
            {"id": identifier, "simulated": simulated, "row": {
                "datetime": "2026-01-01T00:00:00Z", "type": kind,
                "identifier": asset, "shares": shares, "currency": "EUR",
            }}
            for identifier, kind, asset, shares, simulated in rows
        ]
        with tempfile.TemporaryDirectory() as tmp, patch.object(activity, "ACTIVITY_PATH", Path(tmp) / "activity.sqlite3"):
            activity.append_activity_records(records)
            with patch.object(activity, "_totals", wraps=activity._totals) as totals:
                self.assertEqual(activity.ledger_balance(), Decimal("0.11111111"))
                totals.assert_not_called()
                self.assertEqual(activity.read_report(0, 2000000000000)[-1], Decimal("0.11111111"))
                totals.assert_called_once()

    def test_ledger_revision_changes_only_after_activity_writes(self):
        from app.data import activity

        record = {"id": "buy", "row": {
            "datetime": "2026-01-01T00:00:00Z", "type": "Buy",
            "identifier": "BTC", "shares": "1", "currency": "EUR",
        }}
        with tempfile.TemporaryDirectory() as tmp, patch.object(activity, "ACTIVITY_PATH", Path(tmp) / "activity.sqlite3"):
            before = activity.activity_revision()
            activity.append_activity_records([record])
            appended = activity.activity_revision()
            self.assertNotEqual(before, appended)
            activity.append_activity_records([record])
            activity.cache_put_many({"test": {}})
            self.assertEqual(appended, activity.activity_revision())
            record["row"]["shares"] = "2"
            activity.update_activity_record(record)
            self.assertNotEqual(appended, activity.activity_revision())

    def test_filters_are_server_side_and_totals_remain_unfiltered(self):
        from app.data import activity
        with tempfile.TemporaryDirectory() as tmp, patch.object(activity, 'ACTIVITY_PATH', Path(tmp)/'activity.sqlite3'):
            activity.append_activity_records([
                {'id': 'buy', 'row': {'datetime':'2026-01-01T00:00:00Z','type':'Buy','identifier':'BTC','shares':'1','amount':'10','fee':'1','currency':'EUR'}},
                {'id': 'sim', 'simulated':True,'row': {'datetime':'2026-01-01T00:00:00Z','type':'Buy','identifier':'BTC','shares':'1','amount':'10','fee':'1','currency':'EUR'}},
            ])
            rows,total,_,totals,_ = activity.read_report(0, 2000000000000, kind='Buy', status='simulation')
            self.assertEqual([row['id'] for row in rows], ['sim'])
            self.assertEqual(total,1)
            self.assertEqual(sum(item['count'] for item in totals),2)
            with self.assertRaises(ValueError):activity.read_report(0,2000000000000,kind="Buy' OR 1=1")

class PermissionTests(unittest.TestCase):
    def test_read_success_never_proves_trade_or_withdraw_permission(self):
        from app.exchanges.permissions import check_permissions
        api=Mock(spec=['balance','open_orders','fiat_deposits','btc_withdrawals'])
        api.open_orders.return_value=[]
        api.fiat_deposits.return_value=[]
        api.btc_withdrawals.return_value=[]
        result=check_permissions(api,'EUR')
        self.assertEqual(result['funds']['status'],'proven')
        self.assertEqual(result['orders']['status'],'proven')
        self.assertEqual(result['history']['status'],'proven')
        self.assertEqual(result['trade']['status'],'unknown')
        self.assertEqual(result['withdraw']['status'],'unknown')

class BackupTests(unittest.TestCase):
    def test_authenticated_encryption_rejects_wrong_password_and_tampering(self):
        from app.data.backup import encrypt, decrypt
        payload=b'private configuration and ledger'
        encrypted=encrypt(payload,'correct horse battery staple')
        self.assertNotIn(payload,encrypted)
        self.assertEqual(decrypt(encrypted,'correct horse battery staple'),payload)
        for raw,password in [(encrypted,'wrong password value'),(encrypted[:-1]+bytes([encrypted[-1]^1]),'correct horse battery staple')]:
            with self.assertRaises(ValueError):decrypt(raw,password)

    def test_archive_names_and_decompressed_sizes_are_strictly_validated(self):
        from app.data.backup import unpack
        import io,zipfile
        for name in ['../config.json','/config.json','unexpected','manifest.json']:
            data=io.BytesIO()
            with zipfile.ZipFile(data,'w') as archive:archive.writestr(name,'{}')
            with self.assertRaises(ValueError):unpack(data.getvalue())

    def test_archive_limits_directory_reads_during_open(self):
        import io
        import zipfile

        from app.data import backup

        output = io.BytesIO()
        with zipfile.ZipFile(output, "w") as archive:
            manifest = zipfile.ZipInfo("manifest.json")
            manifest.comment = b"metadata" * 20
            archive.writestr(manifest, "{}")

        with patch.object(backup, "MAX_ZIP_METADATA_READ", 128):
            with self.assertRaisesRegex(ValueError, "Backup ZIP metadata exceeds"):
                backup.unpack(output.getvalue())

class BackupIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        from app.data import activity
        self.activity=activity
        self.patch=patch.object(activity,'ACTIVITY_PATH',self.root/'activity.sqlite3');self.patch.start();self.addCleanup(self.patch.stop)
        from app.core.configuration import ConfigStore
        self.store=ConfigStore(self.root/'config.json')
        self.store.create_account('operator','long dashboard password')
        self.activity.append_activity_records([self.record('first')])
        (self.root/'state.json').write_text('{}')
        (self.root/'installation.json').write_text('{"firstStartedAt":"2026-01-01T00:00:00Z"}')

    def record(self,identifier):
        return {'id': identifier, 'exchange':'KRAKEN','row': {'datetime':'2026-01-01T00:00:00Z','type':'Buy','identifier':'BTC','shares':'1','amount':'10','fee':'1','price':'10','currency':'EUR'}}

    def test_interrupted_journal_cleanup_keeps_activity_and_allows_restart(self):
        from app.data import backup
        manager = backup.Backups(self.root)
        _, raw = manager.create('config', 'long backup password')
        real_remove = backup.shutil.rmtree
        interrupted = False
        def remove(path, *args, **kwargs):
            nonlocal interrupted
            if Path(path).name.startswith('.restore-') and not interrupted:
                interrupted = True
                (Path(path) / 'activity.sqlite3').unlink()
                raise OSError('interrupted cleanup')
            return real_remove(path, *args, **kwargs)
        with patch.object(backup.shutil, 'rmtree', side_effect=remove):
            manager.restore(raw, 'long backup password', 'config')
        backup.recover_restore(self.root)
        self.assertEqual([r['id'] for r in self.activity.read_activity_records()], ['first'])
        self.assertFalse((self.root / '.restore-journal').exists())

    def test_missing_snapshot_source_never_overwrites_activity(self):
        from app.data.backup import sqlite_snapshot
        import sqlite3
        with self.assertRaises(sqlite3.OperationalError):
            sqlite_snapshot(self.root / 'missing.sqlite3', self.root / 'activity.sqlite3')
        self.assertEqual([r['id'] for r in self.activity.read_activity_records()], ['first'])

    def test_oversized_snapshot_is_rejected_before_reading_it_into_memory(self):
        from app.data import activity, backup

        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            with patch.object(activity, "ACTIVITY_PATH", directory / "activity.sqlite3"):
                with activity._db() as db:
                    db.execute("INSERT INTO cache VALUES ('large', zeroblob(?), 0)", (backup.MAX_BYTES,))
                with patch.object(Path, "read_bytes", side_effect=AssertionError("oversized snapshot read")):
                    with self.assertRaisesRegex(ValueError, "32 MiB"):
                        backup.Backups(directory).create("activity", "test-backup-password")

    def test_snapshot_includes_wal_and_activity_merge_never_deletes(self):
        from app.data import backup
        from app.data.backup import Backups, decrypt, unpack
        manager=Backups(self.root)
        filename,raw=manager.create('activity','long backup password')
        self.assertFalse((self.root/'backups').exists())
        self.assertTrue(filename.endswith('.dcabackup'))
        with patch.object(backup, "MAX_ZIP_METADATA_READ", 512):
            manifest, data = unpack(decrypt(raw, 'long backup password'))
        self.assertGreater(len(data["activity.sqlite3"]), 512)
        self.assertEqual(manifest['scope'],'activity')
        self.activity.append_activity_records([self.record('later')])
        manager.restore(raw,'long backup password','activity')
        manager.restore(raw,'long backup password','activity')
        manager.restore(raw,'long backup password','activity')
        self.assertEqual(len(self.activity.read_activity_records()),2)
        self.assertEqual({r['id'] for r in self.activity.read_activity_records()},{'first','later'})
        self.assertFalse((self.root/'controls.json').exists())
        self.assertFalse((self.root/'.restore-journal').exists())

    def rewrite_backup(self,raw,change):
        import hashlib,io,zipfile
        from app.data.backup import decrypt,encrypt,unpack
        password='long backup password'
        manifest,data=unpack(decrypt(raw,password));change(data)
        manifest['files']={name:hashlib.sha256(value).hexdigest() for name,value in data.items()}
        output=io.BytesIO()
        with zipfile.ZipFile(output,'w',compression=zipfile.ZIP_STORED) as archive:
            archive.writestr('manifest.json',json.dumps(manifest))
            for name,value in data.items():archive.writestr(name,value)
        return encrypt(output.getvalue(),password)

    def test_config_backup_requires_its_pause_controls(self):
        from app.data.backup import Backups
        manager=Backups(self.root)
        _,raw=manager.create('config','long backup password')
        incomplete=self.rewrite_backup(raw,lambda data:data.pop('controls.json'))
        before=(self.root/'config.json').read_bytes()
        with self.assertRaises(ValueError):manager.restore(incomplete,'long backup password','config')
        self.assertEqual((self.root/'config.json').read_bytes(),before)


    def test_invalid_archived_pause_is_rejected_before_restoring_settings(self):
        from app.data.backup import Backups
        manager=Backups(self.root)
        path=self.root/'controls.json'
        path.write_text('{"paused":false,"until":null}')
        for scope in ('full','config'):
            _,raw=manager.create(scope,'long backup password')
            for controls in [{'paused':'false','until':None},{'paused':True,'until':'invalid'},{'paused':True,'until':'2099-01-01'}]:
                with self.subTest(scope=scope,controls=controls):
                    changed=self.rewrite_backup(raw,lambda data:data.update({'controls.json':json.dumps(controls).encode()}))
                    previous={name:(self.root/name).read_bytes() for name in ['config.json','state.json','controls.json']}
                    with self.assertRaises(ValueError):manager.restore(changed,'long backup password',scope)
                    self.assertEqual({name:(self.root/name).read_bytes() for name in previous},previous)
                    self.assertFalse((self.root/'.restore-journal').exists())

    def test_invalid_archived_account_is_rejected_before_live_mutation(self):
        from app.data.backup import Backups

        manager = Backups(self.root)
        password = "long backup password"
        _, raw = manager.create("full", password)
        config_path = self.root / "config.json"
        original = config_path.read_bytes()
        for scope, update in (
            (None, {"username": None}),
            ("config", {"username": " operator "}),
            ("full", {"username": "op"}),
            ("config", {"username": "op\ud800"}),
            ("config", {"password_hash": None}),
            ("config", {"password_hash": "invalid base64"}),
            ("config", {"password_hash": "YWJj"}),
        ):
            with self.subTest(scope=scope, update=update):
                config = json.loads(original)
                config["account"].update(update)
                invalid = self.rewrite_backup(raw, lambda files: files.update({"config.json": json.dumps(config).encode()}))
                callback = Mock()
                with self.assertRaisesRegex(ValueError, "Invalid backup login credentials"):
                    manager.restore(invalid, password, scope, before_mutation=callback)
                callback.assert_not_called()
                self.assertEqual(config_path.read_bytes(), original)
                self.assertFalse((self.root / ".restore-journal").exists())

    def test_activity_restore_does_not_replace_malformed_current_controls(self):
        from app.data.backup import Backups

        manager = Backups(self.root)
        password = "long backup password"
        _, raw = manager.create("activity", password)
        path = self.root / "controls.json"
        malformed = b'{"paused": "off"}'
        path.write_bytes(malformed)
        callback = Mock()
        with self.assertRaisesRegex(ValueError, "Invalid transaction controls"):
            manager.restore(raw, password, "activity", before_mutation=callback)
        callback.assert_not_called()
        self.assertEqual(path.read_bytes(), malformed)

    def test_full_restore_initializes_an_interrupted_empty_activity_database(self):
        from app.data.backup import Backups

        manager = Backups(self.root)
        password = "long backup password"
        _, raw = manager.create("full", password)
        activity_path = self.root / "activity.sqlite3"
        activity_path.write_bytes(b"")
        manager.restore(raw, password, "full")
        self.assertEqual(self.activity.read_activity_records(), [self.record("first")])

    def test_restore_repairs_malformed_controls_and_preserves_original_bytes(self):
        from app.data.backup import Backups

        manager = Backups(self.root)
        password = "long backup password"
        path = self.root / "controls.json"
        for scope, malformed in (("config", b'{"paused"'), ("full", b"\xff")):
            with self.subTest(scope=scope):
                _, raw = manager.create(scope, password)
                path.write_bytes(malformed)
                self.assertFalse(manager.restore(raw, password, scope)["paused"])
                self.assertEqual(PauseControl(path).snapshot(), {"paused": False, "until": None})
                saved = [item for item in self.root.glob(".restore-invalid-controls-*") if item.read_bytes() == malformed]
                self.assertEqual(len(saved), 1)
                self.assertEqual(saved[0].stat().st_mode & 0o777, 0o600)

    def test_durable_rollback_repairs_malformed_current_controls_after_interruption(self):
        from app.data import backup

        manager = backup.Backups(self.root)
        password = "long backup password"
        _, raw = manager.create("config", password)
        path = self.root / "controls.json"
        malformed = b'{"paused": "off"}\n'
        path.write_bytes(malformed)
        original_config = (self.root / "config.json").read_bytes()
        callback = Mock()
        original_write = backup.write_json_atomic

        def fail_commit(target, data):
            if target == self.root / "report-preferences.json":
                raise OSError("restore interrupted")
            original_write(target, data)

        with patch.object(backup, "recover_restore", wraps=backup.recover_restore) as recover:
            recover.side_effect = [None, OSError("process interrupted before recovery")]
            with patch.object(backup, "write_json_atomic", side_effect=fail_commit):
                with self.assertRaisesRegex(OSError, "process interrupted"):
                    manager.restore(raw, password, "config", before_mutation=callback)
        callback.assert_called_once_with()
        self.assertTrue((self.root / backup.JOURNAL / "manifest.json").exists())
        self.assertEqual(PauseControl(self.root / backup.JOURNAL / "controls.json").snapshot(),
                         {"paused": True, "until": None})
        backup.recover_restore(self.root)
        self.assertEqual((self.root / "config.json").read_bytes(), original_config)
        self.assertEqual(PauseControl(path).snapshot(), {"paused": True, "until": None})
        self.assertEqual([item.read_bytes() for item in self.root.glob(".restore-invalid-controls-*")], [malformed])

    def test_restore_preserves_archived_or_current_pause_for_each_scope(self):
        from app.data.backup import Backups
        manager=Backups(self.root)
        path=self.root/'controls.json'
        states=[{'paused':False,'until':None},{'paused':True,'until':None},{'paused':True,'until':'2099-01-01T00:00:00Z'}]
        for scope in ('full','config','activity'):
            for archived in states:
                with self.subTest(scope=scope,archived=archived):
                    path.write_text(json.dumps(archived))
                    _,raw=manager.create(scope,'long backup password')
                    current={'paused':not archived['paused'],'until':None}
                    path.write_text(json.dumps(current))
                    result=manager.restore(raw,'long backup password',scope)
                    expected=current if scope=='activity' else archived
                    self.assertEqual(json.loads(path.read_text()),expected)
                    self.assertEqual(result['paused'],expected['paused'])

    def test_backup_scopes_have_exact_contents_and_filename_suffixes(self):
        from app.data.backup import Backups, FILES, decrypt, unpack
        manager=Backups(self.root)
        for scope,suffix,expected in [('full','full',FILES),('activity','activities',{'activity.sqlite3'}),('config','config',{'config.json','report-preferences.json','controls.json'})]:
            with self.subTest(scope=scope):
                filename,raw=manager.create(scope,'long backup password')
                manifest,data=unpack(decrypt(raw,'long backup password'))
                self.assertEqual(manifest['scope'],scope)
                self.assertEqual(set(data),set(expected))
                self.assertTrue(filename.endswith('-'+suffix+'.dcabackup'),filename)

    def test_config_restore_keeps_current_history_state_and_installation(self):
        from app.data.backup import Backups
        manager=Backups(self.root)
        self.store.save_report_from('2025-03-01T00:00:00Z')
        archived_config=json.loads((self.root/'config.json').read_text())
        _,raw=manager.create('config','long backup password')
        changed=self.store.snapshot();changed['account']['username']='new-operator'
        self.store._write(changed)
        self.store.save_report_from('2026-06-01T00:00:00Z')
        self.activity.append_activity_records([self.record('later')])
        state={'last_order_at':'2026-10-01T12:00:00Z','funding':'current'}
        (self.root/'state.json').write_text(json.dumps(state))
        installation=(self.root/'installation.json').read_bytes()
        history=self.activity.read_activity_records()
        manager.restore(raw,'long backup password','config')
        self.assertEqual(json.loads((self.root/'config.json').read_text()),archived_config)
        self.assertEqual(self.store.report_from(),'2025-03-01T00:00:00+00:00')
        self.assertEqual(self.activity.read_activity_records(),history)
        self.assertEqual(json.loads((self.root/'state.json').read_text()),state)
        self.assertEqual((self.root/'installation.json').read_bytes(),installation)
        self.assertFalse(json.loads((self.root/'controls.json').read_text())['paused'])

    def test_restore_scope_must_be_available_and_full_can_restore_config_only(self):
        from app.data.backup import Backups
        manager=Backups(self.root)
        _,config=manager.create('config','long backup password')
        _,activities=manager.create('activity','long backup password')
        for raw,scope in [(config,'full'),(config,'activity'),(activities,'config')]:
            with self.subTest(scope=scope):
                with self.assertRaises(ValueError):manager.restore(raw,'long backup password',scope)
        _,full=manager.create('full','long backup password')
        self.activity.append_activity_records([self.record('later')])
        manager.restore(full,'long backup password','config')
        self.assertEqual(len(self.activity.read_activity_records()),2)

    def test_config_restore_failure_rolls_back_without_changing_financial_state(self):
        from app.data import backup
        manager=backup.Backups(self.root)
        _,raw=manager.create('config','long backup password')
        changed=self.store.snapshot();changed['account']['username']='keep-current-login'
        self.store._write(changed)
        state={'last_order_at':'2026-10-01T12:00:00Z'}
        (self.root/'state.json').write_text(json.dumps(state))
        real_write=backup.write_json_atomic
        failed=False
        def fail_once(path,data):
            nonlocal failed
            if Path(path)==self.root/'report-preferences.json' and not failed:
                failed=True
                raise OSError('injected config failure')
            return real_write(path,data)
        with patch.object(backup,'write_json_atomic',side_effect=fail_once):
            with self.assertRaisesRegex(OSError,'injected config failure'):
                manager.restore(raw,'long backup password','config')
        self.assertEqual(json.loads((self.root/'config.json').read_text()),changed)
        self.assertEqual(json.loads((self.root/'state.json').read_text()),state)
        self.assertEqual([r['id'] for r in self.activity.read_activity_records()],['first'])
        self.assertTrue(json.loads((self.root/'controls.json').read_text())['paused'])
        self.assertFalse((self.root/'.restore-journal').exists())

    def test_runtime_config_restore_reloads_settings_login_and_exchange_gate(self):
        from app.trading.runtime import Runtime
        account=Runtime(self.store,self.root/'state.json')
        account.invalidate_sessions=Mock()
        payload={'scope':'config','password':'long backup password','current_password':'long dashboard password'}
        archive=account.backup(payload)
        changed=self.store.snapshot();changed['settings']['expected_monthly_deposit']='123'
        self.store._write(changed);self.store.data=changed
        result=account.backup({**payload,'archive':archive['archive']},restore=True)
        self.assertTrue(result['signInRequired'])
        self.assertEqual(account.store.snapshot()['settings']['expected_monthly_deposit'],'')
        self.assertFalse(account.controls.snapshot()['paused'])
        self.assertTrue(account.exchange_check_pending)
        self.assertTrue(account.invalidate_sessions.called)

    def test_repeated_full_restore_does_not_duplicate_activity(self):
        from app.data.backup import Backups
        manager=Backups(self.root)
        _,raw=manager.create('full','long backup password')
        for _ in range(3):manager.restore(raw,'long backup password','full')
        self.assertEqual([row['id'] for row in self.activity.read_activity_records()],['first'])

    def test_restore_rejects_conflicting_duplicate_ids_without_changing_history(self):
        from app.data.backup import Backups
        manager=Backups(self.root)
        _,raw=manager.create('activity','long backup password')
        changed=self.record('first');changed['row']['amount']='11'
        self.activity.update_activity_record(changed)
        with self.assertRaisesRegex(ValueError,'conflicts with existing Activity'):
            manager.restore(raw,'long backup password','activity')
        self.assertEqual(self.activity.read_activity_records(),[changed])
        self.assertFalse((self.root/'.restore-journal').exists())

    def test_full_restore_rejects_history_loss_and_rolls_back_mid_commit_failure(self):
        from app.data import backup
        manager=backup.Backups(self.root)
        _,raw=manager.create('full','long backup password')
        self.activity.append_activity_records([self.record('later')])
        with self.assertRaisesRegex(ValueError,'remove Activity'):
            manager.restore(raw,'long backup password','full')
        _,raw=manager.create('full','long backup password')
        original=(self.root/'config.json').read_bytes()
        real_write=backup.write_json_atomic
        failed=[False]
        def fail_once(path,data):
            if Path(path)==self.root/'state.json' and not failed[0]:
                failed[0]=True
                raise OSError('injected disk failure')
            return real_write(path,data)
        with patch.object(backup,'write_json_atomic',side_effect=fail_once):
            with self.assertRaisesRegex(OSError,'injected'):
                manager.restore(raw,'long backup password','full')
        self.assertEqual(json.loads((self.root/'config.json').read_text()),json.loads(original))
        self.assertTrue(json.loads((self.root/'controls.json').read_text())['paused'])
        self.assertEqual(len(self.activity.read_activity_records()),2)

    def test_pending_archived_financial_state_never_replays(self):
        from app.data.backup import Backups
        (self.root/'state.json').write_text('{"pending_order":{"clientOrderId":"old"}}')
        manager=Backups(self.root);_,raw=manager.create('full','long backup password')
        (self.root/'state.json').write_text('{}')
        with self.assertRaisesRegex(ValueError,'pending financial'):
            manager.restore(raw,'long backup password','full')

    def test_backup_password_must_differ_from_dashboard_password(self):
        from app.trading.runtime import Runtime
        account=Runtime(self.store,self.root/'state.json')
        payload={'scope':'full','password':'long dashboard password','current_password':'long dashboard password'}
        with patch('app.data.backup.Backups.snapshot') as snapshot:
            with self.assertRaisesRegex(ValueError,'different') as error:account.backup(payload)
            self.assertEqual(error.exception.field,'backupPassword')
            snapshot.assert_not_called()

    def test_backup_encoding_releases_account_and_store_locks(self):
        from app.data.backup import Backups
        from app.trading.runtime import Runtime

        account = Runtime(self.store, self.root / "state.json")
        encode = Backups.encode

        def unlocked_encode(*args):
            self.assertFalse(account.lock._is_owned())
            self.assertFalse(account.store.lock._is_owned())
            return encode(*args)

        with patch.object(Backups, "encode", side_effect=unlocked_encode):
            backup = account.backup({
                "scope": "config", "password": "different backup password",
                "current_password": "long dashboard password",
            })
        self.assertTrue(backup["archive"])

    def test_old_backup_can_be_restored_even_if_password_matches_current_login(self):
        import base64
        from app.data.backup import Backups
        from app.trading.runtime import Runtime
        password='long dashboard password'
        _,raw=Backups(self.root).create('full',password)
        account=Runtime(self.store,self.root/'state.json')
        result=account.backup({'scope':'full','password':password,'current_password':password,'archive':base64.b64encode(raw).decode()},restore=True)
        self.assertTrue(result['restored'])

    def test_runtime_restore_reauthenticates_invalidates_sessions_and_requires_recheck(self):
        import base64
        from app.trading.runtime import Runtime
        from app.core.security import PasswordConfirmationError
        account=Runtime(self.store,self.root/'state.json')
        account.invalidate_sessions=Mock()
        payload={'scope':'full','password':'long backup password','current_password':'incorrect'}
        with self.assertRaises(PasswordConfirmationError):account.backup(payload)
        self.assertFalse((self.root/'backups').exists())
        payload['current_password']='long dashboard password'
        archive=account.backup(payload)
        self.assertTrue(base64.b64decode(archive['archive']).startswith(b'DCA-BACKUP-1'))
        result=account.backup({**payload,'archive':archive['archive']},restore=True)
        self.assertTrue(result['signInRequired'])
        self.assertFalse(account.controls.snapshot()['paused'])
        self.assertTrue(account.exchange_check_pending)
        self.assertTrue(account.startup_pending)
        self.assertTrue(account.worker.reconfigure.is_set())
        self.assertTrue(account.invalidate_sessions.called)

    def test_startup_rolls_back_durable_journal_and_preserves_pause(self):
        from app.data.backup import FILES,recover_restore,sqlite_snapshot
        from app.data.storage import write_json_atomic
        journal=self.root/'.restore-journal';journal.mkdir()
        existed={name:(self.root/name).exists() for name in FILES}
        for name,present in existed.items():
            if present:
                if name.endswith('sqlite3'):sqlite_snapshot(self.root/name,journal/name)
                else:write_json_atomic(journal/name,json.loads((self.root/name).read_text()))
        write_json_atomic(journal/'manifest.json',existed)
        (self.root/'state.json').write_text('{"spent":"999"}')
        recover_restore(self.root)
        self.assertEqual(json.loads((self.root/'state.json').read_text()),{})
        self.assertTrue(json.loads((self.root/'controls.json').read_text())['paused'])
        self.assertFalse(journal.exists())


class PermissionScopeTests(unittest.TestCase):
    def test_missing_closed_orders_scope_is_not_proven_by_open_orders_success(self):
        from app.exchanges.permissions import check_permissions
        api=Mock(spec=['balance','open_orders','fiat_deposits','btc_withdrawals','permission_scopes'])
        api.open_orders.return_value=[];api.fiat_deposits.return_value=[];api.btc_withdrawals.return_value=[]
        api.permission_scopes.return_value={'funds':True,'orders':False,'history':True,'trade':True,'withdraw':False}
        self.assertEqual(check_permissions(api,'EUR')['orders']['status'],'denied')
        # Explicit scope absence wins even if an earlier cached read succeeded.
        self.assertEqual(check_permissions(api,'EUR')['withdraw']['status'],'denied')
        api.balance.side_effect=ValueError('temporary unavailable')
        self.assertEqual(check_permissions(api,'EUR')['funds']['status'],'unknown')

    def test_kraken_metadata_requires_both_open_and_closed_order_scopes(self):
        from app.exchanges.kraken import Kraken
        api=object.__new__(Kraken)
        api.private=Mock(return_value={'permissions':['query-funds','query-open-trades','query-ledger','modify-trades']})
        scopes=api.permission_scopes()
        self.assertFalse(scopes['orders'])
        self.assertTrue(scopes['funds']);self.assertTrue(scopes['trade'])
        api.private.assert_called_once_with('GetApiKeyInfo')

class RestoreQueueTests(unittest.TestCase):
    setUp=BackupIntegrationTests.setUp
    record=BackupIntegrationTests.record

    def test_queued_and_unresolved_financial_work_block_restore_before_archive_access(self):
        from app.trading.runtime import Runtime
        account=Runtime(self.store,self.root/'state.json')
        payload={'scope':'full','password':'long backup password','current_password':'long dashboard password','archive':'eA=='}
        for pending,queued in [(True,0),(False,1)]:
            account.worker.queue.unfinished_tasks=queued
            with patch.object(account,'unresolved',return_value=pending),patch('app.data.backup.Backups.restore') as restore:
                with self.assertRaisesRegex(ValueError,'pending transactions'):
                    account.backup(payload,restore=True)
                restore.assert_not_called()

class ReviewFixTests(unittest.TestCase):
    setUp=BackupIntegrationTests.setUp
    record=BackupIntegrationTests.record

    def test_full_backup_restores_period_preferences_and_installation_memory(self):
        from app.trading.runtime import Runtime
        account=Runtime(self.store,self.root/'state.json')
        archived_start=json.loads((self.root/"installation.json").read_text())["firstStartedAt"]
        account.store.save_report_from('2025-03-01T00:00:00Z')
        payload={'scope':'full','password':'long backup password','current_password':'long dashboard password'}
        archive=account.backup(payload)
        account.store.save_report_from('2026-06-01T00:00:00Z')
        account.store.first_started_at='2026-07-01T00:00:00+00:00'
        account.backup({**payload,'archive':archive['archive']},restore=True)
        self.assertEqual(account.store.report_from(),'2025-03-01T00:00:00+00:00')
        self.assertEqual(account.store.first_started_at,archived_start)

    def test_confirmed_filter_includes_completed_withdrawals_and_real_buys(self):
        withdrawal=self.record('withdrawal');withdrawal['row']['type']='TransferOut';withdrawal['withdrawalStatus']='completed'
        self.activity.append_activity_records([withdrawal])
        rows,*_=self.activity.read_report(0,2000000000000,status='confirmed')
        self.assertEqual({row['id'] for row in rows},{'first','withdrawal'})

    def test_paused_known_withdrawal_result_is_recorded_without_resubmission(self):
        from app.trading import bot
        api=Mock();state={'pending_withdrawal':{'asset':'XBT','amount':'.001'},'pending_withdrawal_context':{'exchange':'KRAKEN','result':{'id':'known'}}}
        settings={'live':True,'exchange':'KRAKEN','withdrawals_enabled':True,'transaction_gate':lambda:True}
        with patch.object(bot,'reconcile_withdrawals'),patch.object(bot,'get_activity_record',return_value=None),patch.object(bot,'save_state'),patch.object(bot,'persist_bot_withdrawal') as persist:
            bot.maybe_withdraw_btc(api,state,settings)
        persist.assert_called_once()
        api.withdraw_btc.assert_not_called()
        self.assertNotIn('pending_withdrawal',state)
        self.assertEqual(state['last_withdrawal']['id'],'known')

    def test_fresh_restore_reloads_default_report_start_from_archived_installation(self):
        from app.trading.runtime import Runtime
        from app.core.configuration import ConfigStore
        from app.data.backup import Backups
        _,raw=Backups(self.root).create('full','long backup password')
        import base64
        with tempfile.TemporaryDirectory() as tmp:
            target=Path(tmp);store=ConfigStore(target/'config.json')
            store.create_account('bootstrap','new dashboard password')
            (target/'state.json').write_text('{}')
            with patch.object(self.activity,'ACTIVITY_PATH',target/'activity.sqlite3'):
                account=Runtime(store,target/'state.json')
                account.backup({'scope':'full','password':'long backup password','current_password':'new dashboard password','archive':base64.b64encode(raw).decode()},restore=True)
                self.assertEqual(store.first_started_at,'2026-01-01T00:00:00Z')
                self.assertEqual(store.report_from(),'2026-01-01T00:00:00Z')
                self.assertEqual(store.snapshot()['account']['username'],'operator')

    def test_invalid_archived_reporting_preference_is_rejected_before_mutation(self):
        from app.data.backup import Backups
        manager=Backups(self.root)
        (self.root/'report-preferences.json').write_text('{"from":"2026-01-01"}')
        _,raw=manager.create('full','long backup password')
        self.store.save_report_from('2025-01-01T00:00:00Z')
        with self.assertRaisesRegex(ValueError,'reporting preferences'):
            manager.restore(raw,'long backup password','full')
        self.assertEqual(self.store.report_from(),'2025-01-01T00:00:00+00:00')
        self.assertFalse((self.root/'.restore-journal').exists())

class ActivitySearchTests(unittest.TestCase):
    def test_search_evaluates_each_candidate_once_and_clamps_the_page(self):
        from app.data import activity

        with tempfile.TemporaryDirectory() as tmp, patch.object(activity, "ACTIVITY_PATH", Path(tmp) / "activity.sqlite3"):
            with activity._db() as db:
                db.executemany(
                    "INSERT INTO activity(id,timestamp,kind,asset,simulated,payload) VALUES (?,?,'Buy','BTC',0,?)",
                    [(str(i), i, json.dumps({"id": str(i)})) for i in range(1, 6)],
                )
            with patch.object(activity, "_matches_search", return_value=True) as matches:
                rows, total, page, _, _ = activity.read_report(0, 5, page=99, limit=2, search="buy")
            self.assertEqual(([row["id"] for row in rows], total, page), (["1"], 5, 3))
            self.assertEqual(matches.call_count, 5)

    def test_search_leaves_ledger_writes_available(self):
        from threading import Event, Thread
        from app.data import activity

        entered, release, written = Event(), Event(), Event()

        def match(*args):
            entered.set()
            return release.wait(5)

        def write():
            activity.cache_put_many({"test": {"value": 1}})
            written.set()

        with tempfile.TemporaryDirectory() as tmp, patch.object(activity, "ACTIVITY_PATH", Path(tmp) / "activity.sqlite3"):
            with activity._db() as db:
                db.execute("INSERT INTO activity(id,timestamp,kind,asset,simulated,payload) VALUES ('1',1,'Buy','BTC',0,'{}')")
            with patch.object(activity, "_matches_search", side_effect=match):
                reader = Thread(target=activity.read_report, args=(0, 1), kwargs={"search": "buy"})
                writer = Thread(target=write)
                reader.start()
                try:
                    self.assertTrue(entered.wait(2))
                    writer.start()
                    self.assertTrue(written.wait(2), "The search held the ledger write lock")
                finally:
                    release.set()
                    reader.join()
                    if writer.ident is not None:
                        writer.join()

    def test_search_matches_hidden_attributes_unicode_and_dates_across_pages(self):
        from app.data import activity
        with tempfile.TemporaryDirectory() as tmp, patch.object(activity, 'ACTIVITY_PATH', Path(tmp)/'activity.sqlite3'):
            for i in range(12):
                activity.append_activity_records([{'id':str(i),'exchange':'KRAKEN','withdrawalId':'Überweisung-123' if i==11 else 'other','row':{'datetime':'2026-01-02T12:34:00Z','type':'Buy','identifier':'BTC','shares':'0.001','price':'100','amount':'10','fee':'1','currency':'EUR'}}])
            rows,total,page,totals,_=activity.read_report(0,2000000000000,limit=5,search='ÜBERWEISUNG-123 kraken')
            self.assertEqual([r['id'] for r in rows],['11'])
            self.assertEqual(total,1)
            self.assertEqual(sum(g['count'] for g in totals),12)
            self.assertEqual(activity.read_report(0,2000000000000,search='02/01/2026')[1],12)
            self.assertEqual(activity.read_report(0,2000000000000,search='€10,00')[1],12)
            self.assertEqual(activity.read_report(0,2000000000000,search="%' OR 1=1")[1],0)
            with self.assertRaises(ValueError): activity.read_report(0,2000000000000,search='x'*257)

    def test_decimal_search_matches_the_visible_rounded_values(self):
        from app.data import activity
        with tempfile.TemporaryDirectory() as tmp, patch.object(activity, "ACTIVITY_PATH", Path(tmp) / "activity.sqlite3"):
            for number in ("3.534", "3.535", "13.53", "3.525"):
                activity.append_activity_records([{
                    "id": number, "exchange": "KRAKEN",
                    "row": {"datetime": "2026-01-02T12:34:00Z", "type": "Buy", "identifier": "BTC",
                            "shares": "0.0000353", "price": "100", "amount": number, "fee": "0", "currency": "EUR"},
                }])
            for search in ("3,53", "3.53", "€3,53 kraken", "3,53 €"):
                with self.subTest(search=search):
                    rows, *_ = activity.read_report(0, 2000000000000, search=search)
                    self.assertEqual({row["id"] for row in rows}, {"3.534", "3.525"})
            rows, *_ = activity.read_report(0, 2000000000000, search="3,54")
            self.assertEqual([row["id"] for row in rows], ["3.535"])
            rows, *_ = activity.read_report(0, 2000000000000, search="0,0000353")
            self.assertEqual(len(rows), 4)

    def test_decimal_search_uses_display_currency_and_rate_before_pagination(self):
        from app.data import activity

        with tempfile.TemporaryDirectory() as tmp, patch.object(activity, "ACTIVITY_PATH", Path(tmp) / "activity.sqlite3"):
            for index, (currency, amount) in enumerate((("USD", "4.415"), ("USD", "4.42"), ("EUR", "3.53"))):
                activity.append_activity_records([{
                    "id": str(index),
                    "row": {"type": "Buy", "identifier": "BTC", "datetime": "2026-01-02T12:34:00Z",
                            "currency": currency, "amount": amount, "shares": "0.001", "price": "100", "fee": "0"},
                }])
            def search(query, **pagination):
                return activity.read_report(0, 2000000000000, search=query, search_fx="USD:0.8", **pagination)
            rows, total, page, *_ = search("3,53 €", page=2, limit=1)
            self.assertEqual(([row["id"] for row in rows], total, page), (["0"], 2, 2))
            self.assertEqual(search("4,42")[1], 0)
            self.assertEqual(search("$3.53")[1], 0)
            self.assertEqual(search("3.53 USD")[1], 0)
            self.assertEqual(search("3.53 EUR")[1], 2)
            self.assertEqual(search("3,54")[1], 1)
            with self.assertRaisesRegex(ValueError, "conversion"):
                activity.read_report(0, 2000000000000, search="3,53", search_fx="USD:inf")

    def test_unknown_optional_amounts_do_not_break_text_search(self):
        from app.data.activity import _matches_search
        record={'exchange':'KRAKEN','row':{'type':'Buy','fee':None,'price':None,'amount':None}}
        self.assertTrue(_matches_search(json.dumps(record),'Kraken'))

    def test_search_uses_the_tables_browser_timezone_at_midnight(self):
        from app.data import activity
        with tempfile.TemporaryDirectory() as tmp, patch.object(activity,'ACTIVITY_PATH',Path(tmp)/'activity.sqlite3'):
            activity.append_activity_records([{'id':'midnight','row':{'datetime':'2026-01-01T23:30:00Z','type':'Buy','identifier':'BTC','shares':'1','amount':'10','price':'10','fee':'0','currency':'EUR'}}])
            self.assertEqual(activity.read_report(0,2000000000000,search='02/01/2026 00:30',search_timezone='Europe/Berlin')[1],1)
            self.assertEqual(activity.read_report(0,2000000000000,search='02/01/2026 00:30',search_timezone='UTC')[1],0)
            with self.assertRaises(ValueError):activity.read_report(0,2000000000000,search='test',search_timezone='Unknown/Timezone')
