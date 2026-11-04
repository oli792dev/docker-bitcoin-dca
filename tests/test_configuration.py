"""Configuration lifecycle and financial guards, without live exchange requests."""
import io
import json
import os
import logging
import requests
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from datetime import datetime, timezone
from unittest.mock import Mock, patch
from app.data import activity
from app.trading import bot
from app.core import configuration as config
from app.trading import runtime
from app.webpage import settings_ui
from app.webpage import web_ui

PASSWORD = 'a-long-private-password'
CREDENTIALS = {'kraken_api_key': 'fictional-key', 'kraken_api_secret': 'c2VjcmV0'}


class ConfigurationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.store = config.ConfigStore(self.root / 'config.json')
        for name, value in [('ACTIVITY_PATH', self.root / 'activity.sqlite3'),
                            ('SNAPSHOT_PATH', self.root / 'dashboard.json')]:
            p = patch.object(activity, name, value)
            p.start(); self.addCleanup(p.stop)
        self.factory = patch.object(runtime, 'create_exchange', side_effect=lambda settings: Mock(open_orders=Mock(return_value=[]), btc_withdrawals=Mock(return_value=[])))
        self.api_factory = self.factory.start(); self.addCleanup(self.factory.stop)
        self.app = runtime.Runtime(self.store, self.root / 'state.json')

    def account(self): self.store.create_account('operator', PASSWORD)
    def ready(self, **settings):
        self.account()
        self.app.save({'current_password':PASSWORD,'settings': {**CREDENTIALS, **settings}})
        self.app.worker.reconfigure.clear()

    def test_invalid_configuration_identifies_field_for_inline_errors(self):
        for field, value in [('deposit_day',32),('deposit_time','25:00'),('timezone','Not/AZone'),('buy_amount','NaN')]:
            with self.subTest(field=field),self.assertRaises(ValueError) as error:
                config.validate({field:value},require_credentials=False)
            self.assertEqual(getattr(error.exception,'field',None),field)

    def test_unknown_persisted_settings_are_rejected(self):
        self.ready()
        saved=json.loads(self.store.path.read_text())
        saved['settings']['unsupported_setting']=True
        self.store.path.write_text(json.dumps(saved))
        with self.assertRaises(ValueError):config.ConfigStore(self.store.path)

    def test_missing_withdrawal_target_identifies_the_exchange_field(self):
        cases=[({'exchange':'KRAKEN'},'kraken_withdraw_key'),
               ({'exchange':'BITVAVO'},'withdraw_address'),
               ({'exchange':'BITVAVO','withdraw_address':'example','withdraw_network':''},'withdraw_network')]
        for settings,field in cases:
            with self.subTest(field=field):
                with self.assertRaises(ValueError) as error:
                    config.validate({**settings,'withdrawals_enabled':True},require_credentials=False)
                self.assertEqual(getattr(error.exception,'field',None),field)

    def test_settings_endpoint_preserves_validation_field_metadata(self):
        self.ready()
        handler=object.__new__(web_ui.Handler)
        handler.runtime=self.app;handler._json=Mock();handler._require_authentication=lambda:True
        handler._settings_body=lambda:{'settings':{'deposit_time':'25:00'}}
        handler._settings_post('/api/settings')
        status,body=handler._json.call_args.args
        self.assertEqual(status,400)
        self.assertEqual(body['field'],'deposit_time')
        self.assertEqual(self.store.snapshot()['settings']['deposit_time'],'00:00')

    def test_failed_snapshot_write_cannot_apply_settings_or_allow_transactions(self):
        self.ready();self.app.exchange_check_pending=False
        old=self.app.api
        with patch.object(activity,'write_dashboard_snapshot',side_effect=OSError('disk full')):
            with self.assertRaises(OSError):
                self.app.save({'settings':{'quote':'USD'},'current_password':PASSWORD})
        self.assertEqual(self.store.snapshot()['settings']['quote'],'EUR')
        self.assertEqual(self.app.settings['quote'],'EUR')
        self.assertIs(self.app.api,old)
        self.assertTrue(self.app.exchange_check_pending)
        with self.assertRaisesRegex(ValueError,'storage'):
            self.app.action('confirm','session','preview')
        self.app.invalidate_sessions=Mock()
        with patch.object(self.app,'_check_exchange_activity',return_value=False) as check,patch.object(bot,'run_once') as run:
            self.app.cycle()
        check.assert_called_once();run.assert_not_called()
        self.assertFalse(self.app._configuration_uncertain)
        self.app.invalidate_sessions.assert_called_once()

    def test_failed_commit_after_replace_reloads_actual_durable_settings(self):
        self.ready();self.app.exchange_check_pending=False
        write=self.store._write
        def replaced_then_failed(data):
            write(data)
            raise OSError('directory fsync failed after replace')
        with patch.object(self.store,'_write',side_effect=replaced_then_failed):
            with self.assertRaises(OSError):
                self.app.save({'settings':{'quote':'USD'},'current_password':PASSWORD})
            self.assertTrue(self.app._configuration_uncertain)
            with patch.object(bot,'run_once') as run:
                with self.assertRaises(OSError):self.app.cycle()
                run.assert_not_called()
        self.assertEqual(self.app.settings['quote'],'EUR')
        with patch.object(self.app,'_check_exchange_activity',return_value=False),patch.object(bot,'run_once') as run:
            self.app.cycle()
            run.assert_not_called()
        self.assertEqual(self.app.settings['quote'],'USD')
        self.assertEqual(self.store.snapshot()['settings']['quote'],'USD')
        self.assertTrue(self.app.exchange_check_pending)

    def test_failed_first_configuration_can_be_retried_without_manual_recovery(self):
        self.account()
        with patch.object(self.store,'commit',side_effect=OSError('disk full')):
            with self.assertRaises(OSError):self.app.save({'settings':CREDENTIALS})
        self.app.save({'settings':CREDENTIALS})
        self.assertTrue(self.store.snapshot()['complete'])
        self.assertTrue(self.app.exchange_check_pending)

    def test_dashboard_refresh_is_persisted_without_rescheduling_exchange_checks(self):
        self.ready();api=self.app.api;self.app.worker.reconfigure.clear()
        interval=self.app.worker.interval
        self.app.save({'settings':{'dashboard_refresh_seconds':75}})
        self.assertEqual(config.ConfigStore(self.store.path).snapshot()['settings']['dashboard_refresh_seconds'],75)
        self.assertEqual(self.app.worker.interval,interval)
        self.assertFalse(self.app.worker.reconfigure.is_set())
        self.assertIs(self.app.api,api)
        for value in (0,4,3601,30.5,'30',True):
            with self.subTest(value=value),self.assertRaises(ValueError):
                config.validate({'dashboard_refresh_seconds':value},require_credentials=False)

    def test_language_change_is_saved_without_rescheduling_or_replacing_exchange(self):
        self.ready();api=self.app.api;self.api_factory.reset_mock()
        self.app.worker.reconfigure.clear()
        self.app.save({'settings':{'language':'de'}})
        self.assertEqual(config.ConfigStore(self.store.path).snapshot()['settings']['language'],'de')
        self.assertIs(self.app.api,api);self.api_factory.assert_not_called()
        self.assertFalse(self.app.worker.reconfigure.is_set())


    def test_cosmetic_save_reuses_adapter_and_validation_failure_closes_replacement(self):
        self.ready()
        old=self.app.api
        with patch.object(runtime,'create_exchange') as factory:
            self.app.save({'settings':{'display_currency':'USD'}})
            factory.assert_not_called();old.session.close.assert_not_called()
        replacement=Mock();replacement.validate_withdrawal_settings.side_effect=ValueError('invalid target')
        with patch.object(runtime,'create_exchange',return_value=replacement):
            with self.assertRaises(ValueError):
                self.app.save({'settings':{'kraken_withdraw_key':'other','withdrawals_enabled':True},'current_password':PASSWORD})
        replacement.session.close.assert_called_once();old.session.close.assert_not_called()
        self.assertIs(self.app.api,old)

    def test_no_default_account_or_exchange_calls_before_configuration(self):
        self.assertIsNone(self.store.snapshot()['account'])
        self.assertFalse(self.store.authenticate('admin', 'admin'))
        self.app.cycle()
        self.api_factory.assert_not_called()
        self.assertFalse(self.store.path.exists())

    def test_account_is_hashed_private_and_can_only_be_created_once(self):
        self.account()
        raw = self.store.path.read_text()
        self.assertNotIn(PASSWORD, raw)
        self.assertEqual(self.store.path.stat().st_mode & 0o777, 0o600)
        self.assertTrue(self.store.authenticate('operator', PASSWORD))
        self.assertFalse(self.store.authenticate('operator', 'wrong'))
        with self.assertRaises(ValueError): self.account()
        public = self.store.public()
        self.assertNotIn('password_hash', json.dumps(public))
        self.assertFalse(public['complete'])

    def test_parallel_first_account_creation_claims_only_one_account(self):
        def create(name):
            try: self.store.create_account(name, PASSWORD); return True
            except ValueError: return False
        with ThreadPoolExecutor(2) as pool:
            self.assertEqual(sum(pool.map(create, ['first', 'second'])), 1)

    def test_saved_credentials_are_masked_and_blank_preserves_them(self):
        self.ready()
        self.app.save({'current_password':PASSWORD,'settings': {'kraken_api_key': '', 'kraken_api_secret': '', 'parqet_enabled': False}})
        self.assertEqual(self.store.snapshot()['settings']['kraken_api_key'], CREDENTIALS['kraken_api_key'])
        public = self.store.public()
        self.assertTrue(public['settings']['kraken_api_key_configured'])
        self.assertNotIn('fictional-key', json.dumps(public))
        self.assertNotIn('c2VjcmV0', settings_ui.settings_page(self.store))
        self.assertNotIn(PASSWORD, settings_ui.settings_page(self.store))
        reloaded = config.ConfigStore(self.store.path)
        self.assertEqual(reloaded.snapshot(), self.store.snapshot())

    def test_failed_atomic_save_leaves_memory_and_file_unchanged(self):
        self.ready()
        old = self.store.snapshot(); raw = self.store.path.read_bytes()
        with patch.object(config.os, 'replace', side_effect=OSError('disk unavailable')):
            with self.assertRaises(OSError): self.app.save({'current_password':PASSWORD,'settings': {'buy_amount': '.001'}})
        self.assertEqual(self.store.snapshot(), old)
        self.assertEqual(self.store.path.read_bytes(), raw)
        self.assertEqual(self.app.settings['buy_amount'], 0)
        self.assertEqual(list(self.root.glob('.config-*')), [])

    def test_validation_rejects_bad_values_before_persisting(self):
        self.ready()
        for values in [{'deposit_day': 32}, {'check_interval_seconds': 5}, {'live': 'true'}, {'buy_amount': 'NaN'},
                       {'withdraw_threshold': '-1'}, {'timezone': '../wrong'}, {'exchange': 'OTHER'},
                       {'kraken_api_secret': 'invalid'}, {'withdrawals_enabled': True}, {'unknown': 1},
                       {'exchange': 'BITVAVO', 'quote': 'USD'}]:
            with self.subTest(values=values), self.assertRaises(ValueError):
                self.app.save({'current_password':PASSWORD,'settings': values})

    def test_environment_cannot_create_account_or_enable_trading(self):
        env={'WEB_UI_ENABLED':'false','EXCHANGE':'BITVAVO','KRAKEN_API_KEY':'old-key',
             'KRAKEN_API_SECRET':'c2VjcmV0','BITVAVO_API_KEY':'old-key','BITVAVO_API_SECRET':'old-secret',
             'LIVE_TRADING':'true','BUY_AMOUNT':'10','WEB_UI_USERNAME':'old-user','WEB_UI_PASSWORD':'admin'}
        with patch.dict(os.environ,env,clear=True):
            store=config.ConfigStore(self.root/'fresh.json')
        self.assertFalse(store.snapshot()['complete'])
        self.assertIsNone(store.snapshot()['account'])
        self.assertFalse(store.snapshot()['settings']['live'])
        self.assertEqual(store.snapshot()['settings']['exchange'],'KRAKEN')
        self.assertEqual(store.snapshot()['settings']['buy_amount'],'0')
        self.assertFalse(store.authenticate('old-user','admin'))

    def test_environment_cannot_override_saved_settings_or_keys(self):
        self.ready(buy_amount='.0006')
        previous=self.store.snapshot()
        with patch.dict(os.environ,{'EXCHANGE':'BITVAVO','BUY_AMOUNT':'100','LIVE_TRADING':'true',
                                   'KRAKEN_API_KEY':'wrong-key','WEB_UI_PASSWORD':'admin'},clear=True):
            reloaded=config.ConfigStore(self.store.path)
        self.assertEqual(reloaded.snapshot(),previous)
        self.assertTrue(reloaded.authenticate('operator',PASSWORD))
        self.assertFalse(reloaded.authenticate('operator','admin'))

    def test_login_has_no_environment_or_default_account_fallback(self):
        h=object.__new__(web_ui.Handler);h.runtime=None
        body=b'username=admin&password=admin';h.headers={'Content-Length':str(len(body))}
        h.rfile=io.BytesIO(body);h._send=Mock()
        with patch.dict(os.environ,{'WEB_UI_USERNAME':'admin','WEB_UI_PASSWORD':'admin'}):
            h.client_address=('127.0.0.1',1234)
            h._handle_login()
        self.assertEqual(h._send.call_args.args[0],401)

    def test_pending_and_queued_actions_block_identity_or_live_changes(self):
        self.ready()
        for state in [{'pending_order': {'id': 'x'}}, {'pending_withdrawal': {'id': 'x'}}]:
            self.app.state_path.write_text(json.dumps(state))
            for values in [{'live': True}, {'quote': 'USD'}, {'kraken_api_key': 'new-key'}]:
                with self.subTest(state=state, values=values), self.assertRaisesRegex(ValueError, 'Resolve pending'):
                    self.app.save({'current_password':PASSWORD,'settings': values})
        self.app.state_path.unlink()
        with patch.object(activity, 'withdrawal_records', return_value=[{'withdrawalStatus': 'submitted'}]):
            with self.assertRaises(ValueError): self.app.save({'current_password':PASSWORD,'settings': {'live': True}})
        self.app.worker.queue.put('queued-action')
        with self.assertRaises(ValueError): self.app.save({'current_password':PASSWORD,'settings': {'live': True}})

    def test_exchange_switch_requires_explicit_keys_even_if_old_keys_are_saved(self):
        self.ready(bitvavo_api_key='old-bitvavo-key',bitvavo_api_secret='old-bitvavo-secret')
        previous=self.store.snapshot();self.api_factory.reset_mock()
        for update in [{'exchange':'BITVAVO'},
                       {'exchange':'BITVAVO','bitvavo_api_key':'new-key'},
                       {'exchange':'BITVAVO','bitvavo_api_secret':'new-secret'},
                       {'exchange':'BITVAVO','bitvavo_api_key':' ','bitvavo_api_secret':''}]:
            with self.subTest(update=update):
                with self.assertRaisesRegex(ValueError,'entering the API key and API secret'):
                    self.app.save({'current_password':PASSWORD,'settings':update})
                with self.assertRaisesRegex(ValueError,'entering the API key and API secret'):
                    self.app.test_connection(update)
                self.assertEqual(self.store.snapshot(),previous)
        self.api_factory.assert_not_called()
        self.app.save({'current_password':PASSWORD,'settings':{'exchange':'BITVAVO','bitvavo_api_key':'new-key','bitvavo_api_secret':'new-secret'}})
        self.assertEqual(self.store.snapshot()['settings']['bitvavo_api_key'],'new-key')
        self.assertEqual(self.store.snapshot()['settings']['bitvavo_api_secret'],'new-secret')

    def test_feature_toggles_do_not_recalculate_purchase_schedule(self):
        self.ready()
        self.app.state_path.write_text(json.dumps({'pending_withdrawal': {'id': 'x'}}))
        self.app.save({'current_password':PASSWORD,'settings': {'withdrawals_enabled': False, 'manual_withdrawal_enabled': False, 'parqet_enabled': False}})
        self.assertFalse(self.app.worker.reconfigure.is_set())
        with self.assertRaisesRegex(ValueError, 'disabled'): self.app.action('preview', 'session')
        self.assertIn('pending_withdrawal', json.loads(self.app.state_path.read_text()))

    def test_startup_delay_is_applied_after_setup_not_before(self):
        self.ready(startup_delay_seconds=60)
        with patch.object(bot, 'run_once') as run:
            self.app.cycle(); run.assert_not_called()
            self.app.ready_at = 0
            with patch.object(bot, 'latest_recorded_buy_time', return_value=None) as history:
                self.app.cycle()
            history.assert_called_once_with('KRAKEN', account_identity=self.app.settings['account_identity'])
            run.assert_called_once()

    def test_exchange_switch_resets_old_schedule_without_changing_history(self):
        self.ready(startup_delay_seconds=0)
        self.app._synchronize_state()
        self.app.state_path.write_text(json.dumps({'configuration_account': ['KRAKEN', 'EUR'], 'last_order_at': '2026-10-01', 'spent': '20'}))
        self.app.save({'current_password':PASSWORD,'settings': {'exchange': 'BITVAVO', 'bitvavo_api_key': 'b-key', 'bitvavo_api_secret': 'b-secret'}})
        with patch.object(bot, 'run_once'), patch.object(bot, 'latest_recorded_buy_time', return_value=None) as latest:
            self.app.cycle()
        self.assertNotIn('last_order_at', json.loads(self.app.state_path.read_text()))
        self.assertEqual(json.loads((self.root / 'previous-account-state.json').read_text())['spent'], '20')
        self.assertEqual(activity.read_dashboard_snapshot()['exchange'], 'BITVAVO')
        latest.assert_called_once_with('BITVAVO', account_identity=self.app.settings['account_identity'])

    def test_new_api_key_resets_account_checkpoints_and_arming(self):
        self.ready(startup_delay_seconds=0)
        self.app._synchronize_state()
        state=json.loads(self.app.state_path.read_text())
        state.update(withdrawal_armed=True,fiat_observation={'balance':'200'},last_order_at='2026-10-30T10:00:00Z')
        self.app.state_path.write_text(json.dumps(state))
        self.app.save({'current_password':PASSWORD,'settings':{'kraken_api_key':'different-account-key'}})
        self.app._synchronize_state()
        state=json.loads(self.app.state_path.read_text())
        self.assertNotIn('withdrawal_armed',state)
        self.assertNotIn('fiat_observation',state)
        self.assertNotIn('last_order_at',state)
        self.assertNotIn('different-account-key',self.app.state_path.read_text())

    def test_secret_rotation_preserves_account_binding_and_arming(self):
        self.ready(startup_delay_seconds=0)
        self.app._synchronize_state()
        state=json.loads(self.app.state_path.read_text())
        state.update(withdrawal_armed=True,last_order_at='2026-10-30T10:00:00Z')
        self.app.state_path.write_text(json.dumps(state))
        self.app.save({'current_password':PASSWORD,'settings':{'kraken_api_secret':'bmV3LXNlY3JldA=='}})
        self.app._synchronize_state()
        self.assertEqual(json.loads(self.app.state_path.read_text()),state)

    def test_stored_new_api_key_cannot_discard_unresolved_request(self):
        self.ready(startup_delay_seconds=0)
        self.app._synchronize_state()
        state=json.loads(self.app.state_path.read_text())
        state['pending_order']={'id':'unresolved'}
        self.app.state_path.write_text(json.dumps(state))
        self.app.settings['kraken_api_key']='other-account'
        with self.assertRaisesRegex(ValueError,'Resolve pending'):
            self.app._synchronize_state()
        self.assertEqual(json.loads(self.app.state_path.read_text()),state)


    def test_enabling_live_trading_does_not_reuse_simulated_execution_state(self):
        self.ready(startup_delay_seconds=0)
        self.app._synchronize_state()
        state=json.loads(self.app.state_path.read_text())
        state.update(spent='100',last_order_at='2026-10-30T10:00:00Z')
        self.app.state_path.write_text(json.dumps(state))
        self.app.save({'current_password':PASSWORD,'settings': {'live':True}})
        with patch.object(bot,'run_once'),patch.object(bot,'latest_recorded_buy_time',return_value=None):
            self.app.cycle()
        state=json.loads(self.app.state_path.read_text())
        self.assertNotIn('spent',state)
        self.assertNotIn('last_order_at',state)
        self.assertTrue(state['configuration_live'])


    def test_connection_test_only_reads_balances_and_does_not_save(self):
        self.account()
        before = self.store.snapshot()
        adapter = Mock(); self.api_factory.side_effect = None; self.api_factory.return_value = adapter
        self.app.test_connection(CREDENTIALS)
        self.assertEqual(adapter.balance.call_args_list, [unittest.mock.call('EUR'), unittest.mock.call('BTC')])
        adapter.buy.assert_not_called(); adapter.withdraw_btc.assert_not_called()
        self.assertEqual(before, self.store.snapshot())
        adapter.session.close.assert_called_once()

    def test_account_update_requires_current_password(self):
        self.ready()
        with self.assertRaisesRegex(ValueError, 'current password'):
            self.app.save({'password': 'new-password-is-long', 'current_password': 'wrong'})
        self.assertTrue(self.app.save({'password': 'new-password-is-long', 'current_password': PASSWORD}))
        self.assertFalse(self.store.authenticate('operator', PASSWORD))
        self.assertTrue(self.store.authenticate('operator', 'new-password-is-long'))

    def test_username_can_change_without_replacing_password(self):
        self.ready()
        self.assertTrue(self.app.save({'username': 'renamed', 'current_password': PASSWORD}))
        self.assertTrue(self.store.authenticate('renamed', PASSWORD))
        self.assertFalse(self.store.authenticate('operator', PASSWORD))



    def test_deposit_time_persists_and_requests_a_schedule_refresh(self):
        self.ready()
        calls=self.api_factory.call_count
        self.app.save({'settings':{'deposit_time':'09:30'}})
        self.assertTrue(self.app.worker.reconfigure.is_set())
        self.assertEqual(self.api_factory.call_count,calls)
        self.assertEqual(config.ConfigStore(self.store.path).snapshot()['settings']['deposit_time'],'09:30')
        for clock in ('24:00','9:30','12:60','12:30:01','invalid'):
            with self.subTest(clock=clock),self.assertRaises(ValueError):self.app.save({'settings':{'deposit_time':clock}})
        self.assertEqual(self.app.settings['deposit_time'],'09:30')

    def test_dashboard_preferences_are_saved_without_rescheduling(self):
        self.ready()
        self.app.save({'current_password':PASSWORD,'settings': {'display_currency':'USD'}})
        self.assertEqual(self.store.public()['settings']['display_currency'],'USD')
        self.assertEqual(self.app.settings['display_currency'],'USD')
        self.assertFalse(self.app.worker.reconfigure.is_set())
        self.assertEqual(config.ConfigStore(self.store.path).public()['settings']['display_currency'],'USD')
        with self.assertRaises(ValueError): self.app.save({'current_password':PASSWORD,'settings':{'display_currency':'GBP'}})
        for appearance in ('light','dark','system'):
            with self.subTest(appearance=appearance):
                calls=self.api_factory.call_count
                self.app.save({'settings':{'appearance':appearance}})
                self.assertEqual(config.ConfigStore(self.store.path).public()['settings']['appearance'],appearance)
                self.assertFalse(self.app.worker.reconfigure.is_set())
                self.assertEqual(self.api_factory.call_count,calls)
                handler=object.__new__(web_ui.Handler);handler.settings=self.app.settings
                self.assertIn('data-appearance="'+appearance+'"',handler._dashboard_html())
                self.assertIn('data-appearance="'+appearance+'"',handler._login_page())
                self.assertIn('data-appearance="'+appearance+'"',settings_ui.settings_page(self.store,embedded=True))
        with self.assertRaises(ValueError):self.app.save({'settings':{'appearance':'invalid'}})

    def test_old_configuration_gains_display_currency_default(self):
        self.ready()
        data=self.store.snapshot();data['settings'].pop('display_currency');data['settings'].pop('appearance');data['settings'].pop('deposit_time')
        self.store.path.write_text(json.dumps(data))
        reloaded=config.ConfigStore(self.store.path)
        self.assertEqual(reloaded.public()['settings']['display_currency'],'EUR')
        self.assertEqual(reloaded.public()['settings']['appearance'],'system')
        self.assertEqual(reloaded.public()['settings']['deposit_time'],'00:00')
        self.assertTrue(reloaded.authenticate('operator',PASSWORD))

    def test_setup_step_two_omits_credentials_but_settings_keeps_them(self):
        self.account()
        page=settings_ui.settings_page(self.store)
        self.assertNotIn('<h2>Login Credentials</h2>',page)
        self.assertNotIn('id="username"',page)
        self.assertIn('id="connectionStatus"',page)
        self.app.save({'current_password':PASSWORD,'settings':CREDENTIALS})
        page=settings_ui.settings_page(self.store)
        self.assertIn('aria-label="Login credentials"',page)
        self.assertIn('id="dashboardOptions"',page)
        self.assertIn('role="switch"',page)

    def test_fresh_default_setup_writes_account_and_settings_to_volume(self):
        volume=self.root/'webui-data'/'config.json'
        with patch.object(config,'CONFIG_PATH',volume):
            fresh=config.ConfigStore()
            fresh.create_account('new-operator',PASSWORD)
            fresh.commit(config.validate(CREDENTIALS))
            reloaded=config.ConfigStore()
        self.assertTrue(reloaded.authenticate('new-operator',PASSWORD))
        self.assertTrue(reloaded.snapshot()['complete'])
        self.assertEqual(reloaded.path,volume)

    def automatic_check(self):
        self.ready(startup_delay_seconds=0)
        self.app.api.open_orders.return_value=[]
        self.app.api.btc_withdrawals.return_value=[]

    def test_startup_check_waits_for_orders_and_withdrawals(self):
        self.automatic_check()
        self.app.api.open_orders.return_value=[{'id':'open'}]
        with patch.object(bot,'run_once') as run:
            self.app.cycle()
            run.assert_not_called()
            with self.assertRaisesRegex(ValueError,'automatic exchange check'):self.app.action('preview','session')
            self.app.api.open_orders.return_value=[]
            self.app.api.btc_withdrawals.return_value=[{'status':'pending'}]
            self.app.cycle();run.assert_not_called()
            self.app.api.btc_withdrawals.return_value=[{'status':'completed'}]
            self.app.cycle();run.assert_called_once()
            self.app.cycle();self.assertEqual(run.call_count,2)
        self.assertFalse(self.app.exchange_check_pending)
        self.assertEqual(self.app.api.open_orders.call_count,3)
        self.app.api.buy_btc.assert_not_called();self.app.api.withdraw_btc.assert_not_called()

    def test_check_failure_and_unknown_status_keep_gate_closed(self):
        self.automatic_check()
        with patch.object(bot,'run_once') as run:
            self.app.api.open_orders.side_effect=requests.ReadTimeout('offline')
            with self.assertRaises(requests.ReadTimeout):self.app.cycle()
            self.app.api.open_orders.side_effect=None
            for response in [None,[{}],[{'status':'unknown'}]]:
                self.app.api.btc_withdrawals.return_value=response
                try:self.app.cycle()
                except ValueError:pass
                self.assertTrue(self.app.exchange_check_pending)
            run.assert_not_called()


    def test_unchanged_account_binding_does_not_rewrite_scheduling_state(self):
        self.ready(startup_delay_seconds=0)
        self.app._synchronize_state()
        before=self.app.state_path.read_bytes()
        with patch.object(activity,'write_json_atomic') as write:
            self.app._synchronize_state()
            self.app._check_exchange_activity()
        write.assert_not_called()
        self.assertEqual(self.app.state_path.read_bytes(),before)

    def test_active_runtime_logs_startup_purchase_history(self):
        self.ready(startup_delay_seconds=0)
        last=datetime(2026,10,28,11,tzinfo=timezone.utc)
        with patch.object(bot,'latest_recorded_buy_time',return_value=last),patch.object(bot,'run_once'):
            with self.assertLogs(runtime.LOG,level='INFO') as logs:self.app.cycle()
        self.assertTrue(any('Startup history:' in line and str(last) in line for line in logs.output))
        self.assertEqual(self.app.settings['startup_last_buy_at'],last)
        self.assertTrue(self.app.settings['startup_schedule_log_pending'])

    def test_credentials_are_directly_available_and_partial_save_preserves_settings(self):
        self.ready()
        page=settings_ui.settings_page(self.store,embedded=True)
        self.assertIn('aria-label="Login credentials"',page)
        self.assertNotIn('editDashboardCredentials',page)
        self.assertNotIn('Account recovery',page)
        before=self.store.snapshot()['settings']
        self.app.save({'current_password':PASSWORD,'settings':{},'username':'renamed','current_password':PASSWORD})
        self.assertEqual(self.store.snapshot()['settings'],before)
        self.app.save({'current_password':PASSWORD,'settings':{'kraken_api_key':'replacement-key'}})
        self.assertEqual(self.store.snapshot()['settings']['buy_amount'],before['buy_amount'])
        self.assertTrue(self.app.exchange_check_pending)

    def test_setup_html_escapes_embedded_data(self):
        self.ready(kraken_withdraw_key='</script><script>alert(1)</script>')
        page = settings_ui.settings_page(self.store)
        self.assertNotIn('</script><script>alert(1)', page)
        self.assertIn('\\u003c/script', page)

    def test_report_start_is_volume_saved_without_changing_settings_or_worker(self):
        self.ready()
        first=self.store.first_started_at
        self.assertEqual(self.store.report_from(),first)
        self.api_factory.reset_mock();self.app.worker.reconfigure.clear()
        settings=self.store.snapshot()
        saved=self.app.save_report_from({'from':'2026-10-01T12:34:56+02:00'})
        self.assertEqual(saved,{'from':'2026-10-01T10:34:56+00:00'})
        reloaded=config.ConfigStore(self.store.path)
        self.assertEqual(reloaded.report_from(),saved['from'])
        self.assertEqual(reloaded.first_started_at,first)
        self.assertEqual(self.store.snapshot(),settings)
        self.api_factory.assert_not_called();self.assertFalse(self.app.worker.reconfigure.is_set())
        for value in ('invalid','2026-10-01T12:34',None):
            with self.assertRaises(ValueError):self.app.save_report_from({'from':value})
        self.assertEqual(reloaded.report_from(),saved['from'])
        with patch.object(config,'write_json_atomic',side_effect=OSError('disk full')):
            with self.assertRaises(OSError):self.app.save_report_from({'from':'2026-10-02T00:00:00Z'})
        self.assertEqual(reloaded.report_from(),saved['from'])

    def test_forecast_deposit_starts_empty_and_is_saved_in_volume_without_exchange_calls(self):
        self.ready()
        self.assertEqual(self.store.snapshot()['settings']['expected_monthly_deposit'],'')
        self.api_factory.reset_mock()
        self.app.worker.reconfigure.clear()
        result=self.app.save_forecast_deposit({'monthlyDeposit':'200.50'})
        self.assertEqual(result,{'monthlyDeposit':'200.50'})
        reloaded=config.ConfigStore(self.store.path)
        self.assertEqual(reloaded.snapshot()['settings']['expected_monthly_deposit'],'200.50')
        self.api_factory.assert_not_called()
        self.assertFalse(self.app.worker.reconfigure.is_set())
        self.app.save_forecast_deposit({'monthlyDeposit':''})
        self.assertEqual(config.ConfigStore(self.store.path).snapshot()['settings']['expected_monthly_deposit'],'')
        self.app.save({'settings':{'expected_monthly_deposit':'275.75'}})
        self.assertEqual(config.ConfigStore(self.store.path).snapshot()['settings']['expected_monthly_deposit'],'275.75')
        self.api_factory.assert_not_called()
        self.assertFalse(self.app.worker.reconfigure.is_set())

    def test_forecast_deposit_rejects_invalid_values_without_modifying_config(self):
        self.ready();before=self.store.path.read_bytes()
        for payload in [{'monthlyDeposit':'-1'},{'monthlyDeposit':'NaN'},{'monthlyDeposit':'Infinity'},
                        {'monthlyDeposit':True},{'monthlyDeposit':None},{'monthlyDeposit':'10','live':True}]:
            with self.subTest(payload=payload),self.assertRaises(ValueError):self.app.save_forecast_deposit(payload)
            self.assertEqual(self.store.path.read_bytes(),before)

    def test_forecast_endpoint_requires_session_and_action_header_and_ignores_query_override(self):
        request=self.server()
        self.assertEqual(request('/api/settings/forecast',{'monthlyDeposit':'200'})[0],401)
        request('/api/setup/account',{'username':'operator','password':PASSWORD})
        request('/api/settings',{'settings':CREDENTIALS})
        self.assertEqual(request('/api/settings/forecast',{'monthlyDeposit':'200'},header=False)[0],400)
        self.assertEqual(request('/api/settings/forecast',{'monthlyDeposit':'200'})[0],200)
        status,body=request('/api/schedule?monthlyDeposit=9999')
        self.assertEqual(status,200)
        self.assertEqual(json.loads(body)['expectedMonthlyDeposit'],'200')
        self.assertNotIn('bitcoinDcaMonthlyDeposit',web_ui.HTML)

    def server(self):
        # Exercise the real HTTP handlers in memory; no listening socket or exchange.
        self.cookie = ''
        def request(path, payload=None, header=True):
            h = object.__new__(web_ui.Handler)
            h.runtime = self.app; h.settings = self.app.settings
            h.worker = self.app.worker; h.withdrawal_service = self.app.worker.submit
            h.path = path; h.headers = {'Cookie': self.cookie}
            if payload is not None:
                body = json.dumps(payload).encode()
                h.headers.update({'Content-Length': str(len(body)), 'Content-Type': 'application/json'})
                if header: h.headers['X-DCA-Action'] = 'settings'
                h.rfile = io.BytesIO(body)
            h.wfile = io.BytesIO()
            result = {}; headers = {}
            h.send_response = lambda status: result.update(status=status)
            h.send_header = lambda key, value: headers.update({key: value})
            h.end_headers = lambda: None
            h.do_GET() if payload is None else h.do_POST()
            if 'Set-Cookie' in headers: self.cookie = headers['Set-Cookie'].split(';')[0]
            return result['status'], h.wfile.getvalue().decode()
        return request

    def test_setup_and_settings_logs_describe_changes_without_secret_values(self):
        with self.assertLogs('bitcoin-dca.settings',level='INFO') as captured:
            self.ready()
            self.app.save({'current_password':PASSWORD,'settings':{'parqet_enabled':False,'kraken_api_key':'PRIVATE-NEW-KEY'}})
            self.app.test_connection({})
        output='\n'.join(captured.output)
        self.assertIn('Initial dashboard account created',output)
        self.assertIn('First-run bot configuration completed',output)
        self.assertIn('changed fields=kraken_api_key,parqet_enabled',output)
        self.assertIn('connection test started',output)
        self.assertIn('connection test succeeded',output)
        for secret in [PASSWORD,'PRIVATE-NEW-KEY',CREDENTIALS['kraken_api_secret']]:
            self.assertNotIn(secret,output)
        self.assertTrue(all(record.levelno==logging.INFO for record in captured.records))

    def test_settings_failures_use_expected_levels_and_redact_exception_text(self):
        request=self.server()
        request('/api/setup/account',{'username':'operator','password':PASSWORD})
        for error,status,level in [(ValueError('PRIVATE-ERROR-DETAIL'),400,logging.INFO),
                                   (requests.ReadTimeout('PRIVATE-ERROR-DETAIL'),502,logging.WARNING),
                                   (RuntimeError('PRIVATE-ERROR-DETAIL'),500,logging.ERROR)]:
            with self.subTest(error=type(error).__name__):
                with patch.object(self.app,'test_connection',side_effect=error):
                    with self.assertLogs(web_ui.LOG,level='DEBUG') as captured:
                        result=request('/api/settings/test',{})
                self.assertEqual(result[0],status)
                self.assertEqual(captured.records[0].levelno,level)
                self.assertNotIn('PRIVATE-ERROR-DETAIL','\n'.join(captured.output))
                self.assertTrue(all(record.exc_info is None for record in captured.records))

    def test_settings_blocked_by_pending_transaction_is_logged_at_info(self):
        self.ready()
        self.app.state_path.write_text(json.dumps({'pending_order':{'id':'pending'}}))
        with self.assertLogs('bitcoin-dca.settings',level='INFO') as captured:
            with self.assertRaises(ValueError): self.app.save({'current_password':PASSWORD,'settings':{'live':True}})
        self.assertTrue(any('Settings update blocked' in line for line in captured.output))
        self.assertEqual(captured.records[0].levelno,logging.INFO)

    def test_settings_dialog_uses_authenticated_embedded_page(self):
        request=self.server()
        request('/api/setup/account',{'username':'operator','password':PASSWORD})
        status,page=request('/settings?embedded=1')
        self.assertEqual(status,200)
        self.assertIn('"embedded": true',page)
        self.cookie=''
        status,page=request('/settings?embedded=1')
        self.assertEqual(status,401)
        self.assertIn('dca-settings-auth-required',page)
        status,page=request('/')
        self.assertEqual(status,200)
        self.assertIn('Sign in',page)

    def test_http_setup_login_settings_and_feature_enforcement(self):
        request = self.server()
        status, page = request('/')
        self.assertEqual(status, 200); self.assertIn('id="accountForm"', page); self.assertIn('id="setupRestoreForm"', page)
        self.assertEqual(request('/api/settings')[0], 401)
        credentials = {'username': 'operator', 'password': PASSWORD}
        self.assertEqual(request('/api/setup/account', credentials, header=False)[0], 400)
        self.assertEqual(request('/api/setup/account', credentials)[0], 200)
        self.assertEqual(request('/api/setup/account', credentials)[0], 400)
        self.assertEqual(request('/api/schedule')[0], 403)
        self.assertEqual(request('/api/settings', {'settings': {**CREDENTIALS, 'manual_withdrawal_enabled': False, 'parqet_enabled': False}})[0], 200)
        status, page = request('/')
        self.assertIn('Settings</button>', page)
        self.assertIn('#manualWithdraw,#withdrawal-note', page)
        self.assertIn('#parqet-note', page)
        self.assertEqual(request('/api/withdrawal/preview', {})[0], 403)
        self.assertEqual(request('/api/export.csv?start=0&end=1000')[0], 403)
        public = request('/api/settings')[1]
        self.assertNotIn('fictional-key', public)
        result = request('/api/settings', {'password': 'new-password-is-long', 'current_password': PASSWORD})
        self.assertEqual(result[0], 200)
        self.assertEqual(request('/api/settings')[0], 401)
        self.assertIn('Sign in', request('/')[1])



    def test_live_and_pause_are_saved_together_and_disabling_live_clears_pause(self):
        self.ready()
        self.app.save({'settings':{'live':True},'pause':True,'current_password':PASSWORD})
        self.assertTrue(self.store.snapshot()['settings']['live'])
        self.assertTrue(self.app.controls.snapshot()['paused'])
        self.app.save({'settings':{'live':False}})
        self.assertFalse(self.store.snapshot()['settings']['live'])
        self.assertFalse(self.app.controls.snapshot()['paused'])

    def test_pause_is_durable_before_a_failed_live_activation_commit(self):
        self.ready()
        with patch.object(self.store,'commit',side_effect=OSError('disk failure')):
            with self.assertRaises(OSError):
                self.app.save({'settings':{'live':True},'pause':True,'current_password':PASSWORD})
        self.assertFalse(self.store.snapshot()['settings']['live'])
        self.assertTrue(self.app.controls.snapshot()['paused'])
        self.assertTrue(self.app._configuration_uncertain)

    def test_pause_is_not_cleared_before_live_deactivation_is_durable(self):
        self.ready(live=True)
        self.app.set_pause({'paused':True})
        def fail_clear(paused, until=None):
            self.assertFalse(paused)
            self.assertFalse(self.store.snapshot()['settings']['live'])
            raise OSError('failed pause write')
        with patch.object(self.app.controls,'set',side_effect=fail_clear):
            with self.assertRaises(OSError):self.app.save({'settings':{'live':False}})
        self.assertTrue(self.app.controls.snapshot()['paused'])
        self.assertTrue(self.app._configuration_uncertain)

if __name__ == '__main__': unittest.main()
