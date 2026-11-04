"""First-run account creation and authenticated application settings."""

import json
import re

from app.webpage.design_system import DESIGN_CSS, apply_appearance
from app.webpage.i18n import localize_page
from app.webpage.scroll_ui import SCROLL_CSS, SCROLL_SCRIPT
from app.webpage.templates import load_page

PAGE = load_page("settings")


PAGE = (
    PAGE.replace("__SCROLL_CSS__", SCROLL_CSS)
    .replace("__SCROLL_SCRIPT__", SCROLL_SCRIPT)
    .replace("__DESIGN_CSS__", DESIGN_CSS)
)


def settings_page(store, create_account=False, embedded=False):
    # The unauthenticated first step must not expose imported credentials or destinations.
    data = dict(settings={}, complete=False, username="") if create_account else store.public()
    data["pause"] = {"paused": False, "until": None}
    data["pauseUnavailable"] = False
    data["recoveryRequired"] = False
    if not create_account and getattr(store, "path", None) is not None:
        from app.trading.controls import PauseControl

        data["recoveryRequired"] = store.path.with_name(".restore-journal").exists()
        try:
            data["pause"] = PauseControl(store.path.with_name("controls.json")).snapshot()
        except (ValueError, OSError):
            data["pauseUnavailable"] = True
    data["createAccount"] = create_account
    data["embedded"] = embedded
    encoded = json.dumps(data).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    page = PAGE
    if not data["complete"]:
        page = re.sub(r"<!--dashboard-credentials-start-->.*?<!--dashboard-credentials-end-->", "", page, flags=re.S)
    page = apply_appearance(page.replace("__INITIAL__", encoded), data["settings"].get("appearance", "system"))
    language = data["settings"].get("language", "en")
    return localize_page(page, language)
