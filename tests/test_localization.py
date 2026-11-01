"""Presentation language never changes trading configuration, identifiers or export data."""
import json
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock
from app.core.configuration import DEFAULTS, validate
from app.webpage.i18n import localize_page, translate, german_catalog
from app.webpage.settings_ui import settings_page
from app.webpage.web_ui import Handler, _login_page
from app.webpage.templates import dashboard_page


class LocalizationTests(TestCase):
    def test_german_pages_cover_navigation_notes_and_accessibility_labels(self):
        dashboard=localize_page(dashboard_page(),'de')
        self.assertIn('<html lang="de">',dashboard)
        self.assertIn('>Zeitraumanalyse<',dashboard)
        self.assertIn('>Prüfe diese Überweisung sorgfältig.',dashboard)
        self.assertTrue('title="Anwendungseinstellungen"' in dashboard)
        self.assertIn('Kaufintervall = Zeit vom letzten Kauf',dashboard)
        self.assertIn('>Anmelden<',_login_page(language='de'))
        self.assertIn('>Benutzername<',_login_page(language='de'))
        self.assertIn('>Sign in<',_login_page(language='en'))

    def test_saved_language_is_in_settings_but_user_values_are_not_translated(self):
        values={**DEFAULTS,'language':'de','kraken_withdraw_key':'Before </script>'}
        page=settings_page(SimpleNamespace(public=lambda:dict(settings=values,username='Enabled',complete=True,passwordChangeRequired=False)))
        self.assertIn('<label for="language">Sprache</label>',page)
        self.assertIn('>Prüfen und speichern<',page)
        self.assertIn('"username": "Enabled"',page)
        self.assertNotIn('Before </script>',page)
        self.assertIn('"language": "de"',page)
        self.assertIn('id="settingsContent"',page)
        self.assertIn('class="settings-footer"',page)

    def test_translated_responses_preserve_financial_and_user_data(self):
        handler=object.__new__(Handler);handler.settings={'language':'de'};handler._send=Mock()
        handler._json(200,{'nextPurchaseStatus':'Waiting for deposit','target':'Before','quote':'EUR',
            'destination':'Kraken saved withdrawal method: Before',
            'activities':[{'type':'Buy','shares':'0.00006','currency':'EUR'}]})
        result=json.loads(handler._send.call_args.args[1])
        self.assertEqual(result['nextPurchaseStatus'],'Warten auf Einzahlung')
        self.assertEqual(result['target'],'Before');self.assertEqual(result['quote'],'EUR')
        self.assertEqual(result['destination'],'Before')
        self.assertEqual(result['activities'],[{'type':'Buy','shares':'0.00006','currency':'EUR'}])

    def test_language_validation_fallback_and_placeholder_contract(self):
        self.assertEqual(validate({'language':'de'},require_credentials=False)['language'],'de')
        with self.assertRaisesRegex(ValueError,'Language'):validate({'language':'fr'},require_credentials=False)
        self.assertEqual(translate('Custom exchange message','de'),'Custom exchange message')
        self.assertEqual(translate('Enabled','en'),'Enabled')
        self.assertEqual(translate('Available EUR balance on exchange','de'),'Verfügbares EUR-Guthaben auf der Börse')
        import re
        for source,target in german_catalog().items():
            self.assertEqual(set(re.findall(r'\{(\w+)\}',source)),set(re.findall(r'\{(\w+)\}',target)),source)
        self.assertEqual(translate('Manual withdrawal is unavailable: enable LIVE_TRADING=true.','de'),
                         'Manuelle Auszahlung nicht verfügbar: echten Handel aktivieren.')
