"""Assemble production pages with a disposable configuration and no exchange client."""
import json
from types import SimpleNamespace
import tempfile
from pathlib import Path

from app.core.configuration import ConfigStore
from app.webpage.settings_ui import settings_page
from app.webpage.design_system import DESIGN_CSS
from app.webpage.templates import dashboard_page, load_page

with tempfile.TemporaryDirectory() as directory:
    store = ConfigStore(Path(directory) / 'config.json')
    store.create_account('browser-fixture', 'fictional-browser-password')
    store.commit(store.snapshot()['settings'])
    live_data=store.public();live_data['settings']['live']=True
    live_store=SimpleNamespace(public=lambda:json.loads(json.dumps(live_data)))
    print(json.dumps({
        '/': dashboard_page().replace('__REPORT_FROM__', '2026-01-01T00:00:00Z').replace('__WITHDRAW_DESTINATION__', 'Fixture destination'),
        '/settings': settings_page(store),
        '/settings?embedded=1': settings_page(store,embedded=True),
        '/settings-live':settings_page(live_store),
        '/settings-live?embedded=1':settings_page(live_store,embedded=True),
        '/login': load_page('login').replace('__DESIGN_CSS__', DESIGN_CSS).replace('{{ERROR}}', ''),
    }))
