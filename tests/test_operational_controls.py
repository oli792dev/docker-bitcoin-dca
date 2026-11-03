"""Offline operational safety regression coverage."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from app.trading import runtime


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
    def test_filters_are_server_side_and_totals_remain_unfiltered(self):
        from app.data import activity
        with tempfile.TemporaryDirectory() as tmp, patch.object(activity, 'ACTIVITY_PATH', Path(tmp)/'activity.json'):
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

class BackupIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        from app.data import activity
        self.activity=activity
        self.patch=patch.object(activity,'ACTIVITY_PATH',self.root/'activity.json');self.patch.start();self.addCleanup(self.patch.stop)
        from app.core.configuration import ConfigStore
        self.store=ConfigStore(self.root/'config.json')
        self.store.create_account('operator','long dashboard password')
        self.activity.append_activity_records([self.record('first')])
        (self.root/'state.json').write_text('{}')
        (self.root/'installation.json').write_text('{"firstStartedAt":"2026-01-01T00:00:00Z"}')

    def record(self,identifier):
        return {'id': identifier, 'exchange':'KRAKEN','row': {'datetime':'2026-01-01T00:00:00Z','type':'Buy','identifier':'BTC','shares':'1','amount':'10','fee':'1','price':'10','currency':'EUR'}}

    def test_snapshot_includes_wal_and_activity_merge_never_deletes(self):
        from app.data.backup import Backups,decrypt,unpack
        manager=Backups(self.root)
        self.activity.bind_legacy_account('KRAKEN','EUR','identity')
        filename,raw=manager.create('activity','long backup password')
        self.assertFalse((self.root/'backups').exists())
        self.assertTrue(filename.endswith('.dcabackup'))
        manifest,data=unpack(decrypt(raw,'long backup password'))
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

    def test_earlier_config_backup_keeps_current_pause(self):
        from app.data.backup import Backups
        manager=Backups(self.root)
        _,raw=manager.create('config','long backup password')
        raw=self.rewrite_backup(raw,lambda data:data.pop('controls.json'))
        for controls in [{'paused':False,'until':None},{'paused':True,'until':'2099-01-01T00:00:00Z'}]:
            with self.subTest(controls=controls):
                (self.root/'controls.json').write_text(json.dumps(controls))
                manager.restore(raw,'long backup password','config')
                self.assertEqual(json.loads((self.root/'controls.json').read_text()),controls)

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
        with patch('app.data.backup.Backups.create',return_value=('test.dcabackup',b'test')) as create:
            with self.assertRaisesRegex(ValueError,'different') as error:account.backup(payload)
            self.assertEqual(error.exception.field,'backupPassword')
            create.assert_not_called()

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

    def test_legacy_account_binding_conflicts_are_rejected_without_changing_history(self):
        from app.data.backup import Backups
        self.activity.bind_legacy_account('KRAKEN','EUR','original-account')
        manager=Backups(self.root);_,raw=manager.create('activity','long backup password')
        with self.activity._db() as db:
            db.execute("UPDATE metadata SET value='different-account' WHERE key='legacy_account:KRAKEN:EUR'")
        with self.assertRaisesRegex(ValueError,'account bindings'):
            manager.restore(raw,'long backup password','activity')
        self.assertEqual(len(self.activity.read_activity_records()),1)

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
            with patch.object(self.activity,'ACTIVITY_PATH',target/'activity.json'):
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
    def test_search_matches_hidden_attributes_unicode_and_dates_across_pages(self):
        from app.data import activity
        with tempfile.TemporaryDirectory() as tmp, patch.object(activity, 'ACTIVITY_PATH', Path(tmp)/'activity.json'):
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

    def test_unknown_optional_amounts_do_not_break_text_search(self):
        from app.data.activity import _matches_search
        record={'exchange':'KRAKEN','row':{'type':'Buy','fee':None,'price':None,'amount':None}}
        self.assertTrue(_matches_search(json.dumps(record),'Kraken'))

    def test_search_uses_the_tables_browser_timezone_at_midnight(self):
        from app.data import activity
        with tempfile.TemporaryDirectory() as tmp, patch.object(activity,'ACTIVITY_PATH',Path(tmp)/'activity.json'):
            activity.append_activity_records([{'id':'midnight','row':{'datetime':'2026-01-01T23:30:00Z','type':'Buy','identifier':'BTC','shares':'1','amount':'10','price':'10','fee':'0','currency':'EUR'}}])
            self.assertEqual(activity.read_report(0,2000000000000,search='02/01/2026 00:30',search_timezone='Europe/Berlin')[1],1)
            self.assertEqual(activity.read_report(0,2000000000000,search='02/01/2026 00:30',search_timezone='UTC')[1],0)
            with self.assertRaises(ValueError):activity.read_report(0,2000000000000,search='test',search_timezone='Unknown/Timezone')
