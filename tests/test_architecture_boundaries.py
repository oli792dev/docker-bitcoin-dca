"""Contracts shared across exchange errors, dashboard statuses and backup storage."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import requests

from app.data import activity, backup
from app.exchanges.bitvavo import Bitvavo
from app.exchanges.permissions import check_permissions
from app.webpage.status import dashboard_status


class ArchitectureBoundaryTests(unittest.TestCase):
    def test_permission_evidence_uses_exchange_code_not_message_wording(self):
        api = Bitvavo(api_key='fictional', api_secret='fictional')
        api.session = Mock()
        response = Mock(status_code=403)
        response.json.return_value = {'errorCode':311, 'error':'opaque private detail'}
        response.raise_for_status.side_effect = requests.HTTPError('403 Forbidden')
        api.session.request.return_value = response
        with self.assertRaises(requests.RequestException) as caught:
            api.balance('EUR')
        self.assertEqual(getattr(caught.exception, 'code', None), 311)
        self.assertEqual(getattr(caught.exception, 'category', None), 'permission_denied')
        evidence = check_permissions(api, 'EUR')
        self.assertEqual(evidence['funds']['status'], 'denied')
        self.assertNotIn('opaque private detail', str(evidence))
        response.status_code = 503
        response.raise_for_status.side_effect = requests.HTTPError('503 Unavailable')
        self.assertEqual(check_permissions(api, 'EUR')['funds']['status'], 'unknown')

    def test_malformed_exchange_codes_never_become_permission_evidence(self):
        api = Bitvavo(api_key='fictional', api_secret='fictional')
        api.session = Mock()
        response = Mock(status_code=403)
        api.session.request.return_value = response
        for code in ('311', [], {'code':311}, True):
            with self.subTest(code=code):
                response.json.return_value = {'errorCode':code, 'error':'opaque detail'}
                with self.assertRaises(requests.RequestException) as caught:
                    api.balance('EUR')
                self.assertIsNone(caught.exception.code)
                self.assertEqual(caught.exception.category, 'uncertain')

    def test_display_wording_cannot_change_error_severity(self):
        status = dashboard_status(balance_matches=True, purchase_status='Wording changed completely',
                 purchase_status_code='purchase_rejected', live=True, exchange_check_pending=False,
                 startup_delay=False, worker_healthy=True, worker_error=False)
        self.assertEqual(status.tone, 'error')
        self.assertTrue(status.warning)
        from app.core.purchase_status import PURCHASE_LABELS, PurchaseStatus
        self.assertEqual(set(PURCHASE_LABELS), set(PurchaseStatus))
        unknown = dashboard_status(balance_matches=True, purchase_status='Bot active',
                  purchase_status_code='unknown-future-code', live=True, exchange_check_pending=False,
                  startup_delay=False, worker_healthy=True, worker_error=False)
        self.assertEqual((unknown.label, unknown.tone), ('Schedule pending', 'waiting'))

    def test_owned_schema_index_is_created_and_accepted_by_backup_validator(self):
        indexes = {**getattr(activity, 'SCHEMA_INDEXES', {}), 'activity_exchange':('activity','exchange')}
        with tempfile.TemporaryDirectory() as root, \
             patch.object(activity, 'ACTIVITY_PATH', Path(root)/'activity.sqlite3'), \
             patch.object(activity, 'SCHEMA_INDEXES', indexes, create=True):
            with activity._db() as db:
                self.assertIsNotNone(db.execute("SELECT name FROM sqlite_master WHERE name='activity_exchange'").fetchone())
            self.assertEqual(backup._records(activity.ACTIVITY_PATH), {})
            with activity._db() as db:
                db.execute('CREATE INDEX unexpected_index ON activity(currency)')
            with self.assertRaisesRegex(ValueError, 'schema'):
                backup._records(activity.ACTIVITY_PATH)
