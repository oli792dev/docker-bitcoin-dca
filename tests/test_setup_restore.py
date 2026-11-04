"""Restore an encrypted login backup before creating a dashboard account."""

import base64
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from app.core.configuration import ConfigStore, validate
from app.data import activity
from app.data.backup import Backups
from app.trading.runtime import Runtime
from app.webpage.web_ui import Handler


class SetupRestoreTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.target = self.root / 'target'
        self.target.mkdir()
        for owner, name, value in (
            (activity, 'ACTIVITY_PATH', self.target / 'activity.json'),
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
        with patch.object(activity, 'ACTIVITY_PATH', source / 'activity.json'):
            activity.append_activity_records([{
                'id':'archived-buy', 'exchange':'KRAKEN', 'row':{
                    'datetime':'2026-10-01T12:00:00Z', 'type':'Buy', 'identifier':'BTC',
                    'shares':'.001', 'price':'80000', 'amount':'80', 'fee':'.20', 'currency':'EUR'}}])
            _, raw = Backups(source).create(scope, 'archive-backup-password')
        return {'password':'archive-backup-password', 'archive':base64.b64encode(raw).decode()}

    def request(self, payload, action_header=True):
        handler = object.__new__(Handler)
        handler.runtime = self.runtime
        handler.path = '/api/setup/restore'
        body = json.dumps(payload).encode()
        handler.headers = {'Content-Length':str(len(body)), 'Content-Type':'application/json'}
        if action_header:
            handler.headers['X-DCA-Action'] = 'settings'
        handler.rfile = io.BytesIO(body)
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
