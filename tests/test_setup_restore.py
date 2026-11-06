"""Restore an encrypted login backup before creating a dashboard account."""

import base64
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from threading import BoundedSemaphore, Event
from concurrent.futures import ThreadPoolExecutor
from app.webpage import web_ui

from app.core.configuration import ConfigStore, validate
from app.data import activity
from app.data.backup import Backups
from app.trading.runtime import Runtime
from app.webpage.web_ui import Handler


class SetupRestoreTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        replacement = patch.object(web_ui, '_RESTORE_UPLOADS', BoundedSemaphore(1), create=True)
        replacement.start()
        self.addCleanup(replacement.stop)
        self.root = Path(temporary.name)
        self.target = self.root / 'target'
        self.target.mkdir()
        for owner, name, value in (
            (activity, 'ACTIVITY_PATH', self.target / 'activity.sqlite3'),
            (activity, 'SNAPSHOT_PATH', self.target / 'dashboard.json'),
        ):
            replacement = patch.object(owner, name, value)
            replacement.start()
            self.addCleanup(replacement.stop)
        replacement = patch('app.trading.runtime.create_exchange', return_value=Mock())
        replacement.start()
        self.addCleanup(replacement.stop)
        self.store = ConfigStore(self.target / 'config.json')
        (self.target / 'state.json').write_text('{}')
        self.runtime = Runtime(self.store, self.target / 'state.json')

    def archive(self, scope):
        source = self.root / ('source-' + scope)
        source.mkdir()
        store = ConfigStore(source / 'config.json')
        store.create_account('archived-user', 'archived-login-password')
        store.commit(validate({'kraken_api_key':'fixture-key', 'kraken_api_secret':'c2VjcmV0'}))
        (source / 'state.json').write_text('{}')
        with patch.object(activity, 'ACTIVITY_PATH', source / 'activity.sqlite3'):
            activity.append_activity_records([{
                'id':'archived-buy', 'exchange':'KRAKEN', 'row':{
                    'datetime':'2026-10-01T12:00:00Z', 'type':'Buy', 'identifier':'BTC',
                    'shares':'.001', 'price':'80000', 'amount':'80', 'fee':'.20', 'currency':'EUR'}}])
            _, raw = Backups(source).create(scope, 'archive-backup-password')
        return {'password':'archive-backup-password', 'archive':base64.b64encode(raw).decode()}

    def request(self, payload, action_header=True, reader=None, path="/api/setup/restore"):
        handler = object.__new__(Handler)
        handler.runtime = self.runtime
        handler.path = path
        body = json.dumps(payload).encode()
        handler.headers = {'Content-Length':str(len(body)), 'Content-Type':'application/json'}
        if action_header:
            handler.headers['X-DCA-Action'] = 'settings'
        handler.rfile = reader if reader is not None else io.BytesIO(body)
        self.handler = handler
        handler.wfile = io.BytesIO()
        responses = []
        handler._json = lambda status, result: responses.append((status, result))
        handler.send_response = lambda status: responses.append((status, None))
        handler.send_header = lambda *args: None
        handler.end_headers = lambda: None
        handler.do_POST()
        status, result = responses[0]
        return status, result if result is not None else json.loads(handler.wfile.getvalue())

    def test_full_restore_before_account_creation_uses_archived_login_and_history(self):
        status, result = self.request(self.archive('full'))
        self.assertEqual(status, 200, result)
        self.assertTrue(result['signInRequired'])
        self.assertTrue(self.store.authenticate('archived-user', 'archived-login-password'))
        self.assertEqual([record['id'] for record in activity.read_activity_records()], ['archived-buy'])
        self.assertTrue(self.runtime.exchange_check_pending)

    def test_config_restore_before_account_creation_uses_archived_login_without_history(self):
        status, result = self.request(self.archive('config'))
        self.assertEqual(status, 200, result)
        self.assertTrue(self.store.authenticate('archived-user', 'archived-login-password'))
        self.assertEqual(activity.read_activity_records(), [])

    def test_activities_backup_cannot_initialize_an_account(self):
        status, _ = self.request(self.archive('activity'))
        self.assertEqual(status, 400)
        self.assertIsNone(self.store.snapshot()['account'])
        self.assertEqual(activity.read_activity_records(), [])

    def test_existing_account_cannot_be_replaced_without_authentication(self):
        payload = self.archive('config')
        self.store.create_account('current-user', 'current-login-password')
        status, _ = self.request(payload)
        self.assertEqual(status, 400)
        self.assertTrue(self.store.authenticate('current-user', 'current-login-password'))

    def test_setup_restore_rejects_existing_financial_state(self):
        payload = self.archive('config')
        (self.target / 'state.json').write_text('{"last_order_at":"2026-10-02T12:00:00Z"}')
        status, _ = self.request(payload)
        self.assertEqual(status, 400)
        self.assertIsNone(self.store.snapshot()['account'])

    def test_wrong_backup_password_leaves_account_creation_available(self):
        payload = self.archive('config')
        payload['password'] = 'incorrect-backup-password'
        status, _ = self.request(payload)
        self.assertEqual(status, 400)
        self.assertIsNone(self.store.snapshot()['account'])
        self.store.create_account('new-user', 'new-login-password')
        self.assertTrue(self.store.authenticate('new-user', 'new-login-password'))

    def test_setup_restore_requires_the_action_header(self):
        status, _ = self.request(self.archive('config'), action_header=False)
        self.assertEqual(status, 400)
        self.assertIsNone(self.store.snapshot()['account'])

    def test_failed_restore_does_not_block_backup_after_creating_a_new_account(self):
        payload = self.archive('config')
        payload['password'] = 'incorrect-backup-password'
        self.assertEqual(self.request(payload)[0], 400)
        self.store.create_account('new-user', 'new-login-password')
        self.runtime.save({'settings':{'kraken_api_key':'fixture-key', 'kraken_api_secret':'c2VjcmV0'}})
        result = self.runtime.backup({'scope':'config', 'password':'another-backup-password',
                                      'current_password':'new-login-password'})
        self.assertTrue(result['archive'])

    def test_setup_restore_cannot_replace_history_even_without_an_account(self):
        payload = self.archive('config')
        activity.append_activity_records([{
            'id':'keep-buy', 'row':{'datetime':'2026-10-01T12:00:00Z', 'type':'Buy', 'identifier':'BTC',
                                  'shares':'.001', 'amount':'80', 'price':'80000', 'fee':'.2', 'currency':'EUR'}}])
        status, _ = self.request(payload)
        self.assertEqual(status, 400)
        self.assertIsNone(self.store.snapshot()['account'])
        self.assertEqual([record['id'] for record in activity.read_activity_records()], ['keep-buy'])

    def test_failed_setup_restores_are_rate_limited(self):
        payload = self.archive('config')
        payload['password'] = 'incorrect-backup-password'
        for _ in range(5):
            self.assertEqual(self.request(payload)[0], 400)
        self.assertEqual(self.request(payload)[0], 429)
        self.assertIsNone(self.store.snapshot()['account'])

    def test_existing_account_rejects_restore_before_reading_body(self):
        self.store.create_account('current-user', 'current-login-password')
        reader = Mock(); reader.read.side_effect = AssertionError('Body must not be read')
        self.assertEqual(self.request({}, reader=reader)[0], 400)
        reader.read.assert_not_called()
        self.assertTrue(self.handler.close_connection)

    def test_rate_limited_setup_rejects_before_reading_body(self):
        for _ in range(5):
            self.assertEqual(self.request({'password':'invalid-password', 'archive':'invalid'})[0], 400)
        reader = Mock(); reader.read.side_effect = AssertionError('Body must not be read')
        self.assertEqual(self.request({}, reader=reader)[0], 429)
        reader.read.assert_not_called()

    def test_only_one_restore_body_is_admitted_and_failures_release_slot(self):
        self.assertTrue(web_ui._RESTORE_UPLOADS.acquire(blocking=False))
        reader = Mock(); reader.read.side_effect = AssertionError('Body must not be read')
        try:
            self.assertEqual(self.request({}, reader=reader)[0], 429)
            reader.read.assert_not_called()
        finally:
            web_ui._RESTORE_UPLOADS.release()
        self.assertEqual(self.request({'password':'invalid-password', 'archive':'invalid'})[0], 400)
        self.assertTrue(web_ui._RESTORE_UPLOADS.acquire(blocking=False))
        web_ui._RESTORE_UPLOADS.release()

    def test_account_created_during_upload_cannot_be_replaced(self):
        payload = self.archive('config')
        raw = json.dumps(payload).encode()
        def read(length):
            self.store.create_account('new-owner', 'new-owner-password')
            return raw
        self.assertEqual(self.request(payload, reader=Mock(read=read))[0], 400)
        self.assertTrue(self.store.authenticate('new-owner', 'new-owner-password'))

    def test_restore_parser_rejects_containers_before_generic_json_parsing(self):
        for path in ['/api/setup/restore', '/api/settings/restore']:
            for raw in [b'[]', b'{"archive":[0,0,0]}', b'{"archive":{"nested":[]}}']:
                handler = object.__new__(Handler)
                handler.path = path
                handler.headers = {'Content-Length':str(len(raw)), 'Content-Type':'application/json', 'X-DCA-Action':'settings'}
                handler.rfile = io.BytesIO(raw)
                with patch.object(web_ui.json, 'loads', side_effect=AssertionError('Generic parser must not see containers')):
                    with self.assertRaises(ValueError):
                        handler._settings_body()

    def test_normal_restore_is_authenticated_before_body_or_upload_admission(self):
        reader = Mock(); reader.read.side_effect = AssertionError('Body must not be read')
        with patch.object(Handler, '_has_valid_session', return_value=False):
            self.assertEqual(self.request({}, reader=reader, path='/api/settings/restore')[0], 401)
        reader.read.assert_not_called()
        self.assertTrue(web_ui._RESTORE_UPLOADS.acquire(blocking=False))
        web_ui._RESTORE_UPLOADS.release()

    def test_authenticated_restore_shares_setup_upload_admission(self):
        reader = Mock(); reader.read.side_effect = AssertionError('Body must not be read')
        self.assertTrue(web_ui._RESTORE_UPLOADS.acquire(blocking=False))
        try:
            with patch.object(Handler, '_require_authentication', return_value=True):
                self.assertEqual(self.request({}, reader=reader, path='/api/settings/restore')[0], 429)
            reader.read.assert_not_called()
        finally:
            web_ui._RESTORE_UPLOADS.release()

    def test_runtime_error_releases_upload_admission(self):
        with patch.object(self.runtime, 'backup', side_effect=OSError('fixture storage failure')):
            self.assertEqual(self.request({'password':'invalid-password', 'archive':'invalid'})[0], 500)
        self.assertTrue(web_ui._RESTORE_UPLOADS.acquire(blocking=False))
        web_ui._RESTORE_UPLOADS.release()

    def test_restore_string_parser_rejects_duplicate_unknown_and_nonstring_fields(self):
        from app.core.security import string_object
        limits = {'password':1024, 'archive':16}
        for raw in ['{}', '{"password":"ok","archive":null}', '{"password":"ok","archive":true}',
                    '{"password":"ok","archive":1}', '{"password":"ok","archive":"a","archive":"b"}',
                    '{"password":"ok","other":"a"}', '{"password":"ok","archive":"a"} []',
                    '{"password":"ok","archive":"a",}', '{"password":"ok","archive":"'+'a'*17+'"}']:
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                string_object(raw, limits)
        raw = ' \n {"archive":"AA==", "pass\\u0077ord":"a\\"b\\\\c\\u00e4"} \t'
        self.assertEqual(string_object(raw, limits), {'archive':'AA==', 'password':'a"b\\cä'})

    def test_restore_parser_accepts_the_supported_archive_and_password_lengths(self):
        from app.data.backup import MAX_BYTES
        archive = 'A' * ((MAX_BYTES + 128) * 4 // 3 + 4)
        password = '🔒' * 1024
        raw = json.dumps({'password':password, 'archive':archive}).encode()
        handler = object.__new__(Handler)
        handler.path = '/api/setup/restore'
        handler.headers = {'Content-Length':str(len(raw)), 'Content-Type':'application/json', 'X-DCA-Action':'settings'}
        handler.rfile = io.BytesIO(raw)
        self.assertEqual(handler._settings_body(), {'password':password, 'archive':archive})

    def test_parallel_upload_is_rejected_while_first_request_is_reading(self):
        entered, finish = Event(), Event()
        payload = {'password':'invalid-password', 'archive':'invalid'}
        raw = json.dumps(payload).encode()
        def read(length):
            entered.set()
            if not finish.wait(5):
                raise AssertionError('Upload test timed out')
            return raw
        with ThreadPoolExecutor(1) as pool:
            first = pool.submit(self.request, payload, reader=Mock(read=read))
            try:
                self.assertTrue(entered.wait(5))
                second_reader = Mock(); second_reader.read.side_effect = AssertionError('Parallel body must not be read')
                self.assertEqual(self.request(payload, reader=second_reader)[0], 429)
                second_reader.read.assert_not_called()
            finally:
                finish.set()
            self.assertEqual(first.result(timeout=5)[0], 400)

    def test_direct_runtime_setup_restore_still_reserves_password_attempts(self):
        from app.core.security import PasswordConfirmationError
        payload = {'password':'invalid-password', 'archive':'invalid'}
        for _ in range(5):
            with self.assertRaises(ValueError):
                self.runtime.backup(payload, restore=True, setup=True)
        with self.assertRaises(PasswordConfirmationError):
            self.runtime.backup(payload, restore=True, setup=True)

    def authenticated_restore(self, scope):
        payload = self.archive(scope)
        self.store.create_account('current-user', 'current-login-password')
        self.store.commit(validate({'kraken_api_key':'fixture-key', 'kraken_api_secret':'c2VjcmV0'}))
        payload.update(scope=scope, current_password='current-login-password')
        with patch.object(Handler, '_has_valid_session', return_value=True):
            status, result = self.request(payload, path='/api/settings/restore')
        self.assertEqual(status, 200, result)
        self.assertTrue(result['signInRequired'])
        if scope == 'activity':
            self.assertTrue(self.store.authenticate('current-user', 'current-login-password'))
        else:
            self.assertTrue(self.store.authenticate('archived-user', 'archived-login-password'))

    def test_authenticated_full_restore_http_envelope_remains_supported(self):
        self.authenticated_restore('full')

    def test_authenticated_config_restore_http_envelope_remains_supported(self):
        self.authenticated_restore('config')

    def test_authenticated_activities_restore_http_envelope_remains_supported(self):
        self.authenticated_restore('activity')

    def test_missing_action_header_does_not_consume_setup_restore_attempts(self):
        for _ in range(6):
            self.assertEqual(self.request({}, action_header=False)[0], 400)
        self.assertEqual(self.runtime.setup_restore_attempts.attempts, {})
        self.assertEqual(self.request({'password':'invalid-password', 'archive':'invalid'})[0], 400)
