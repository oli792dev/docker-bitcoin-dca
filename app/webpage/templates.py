"""Load bundled pages and inline their own assets without a build tool or network request."""

import re
from functools import lru_cache
from pathlib import Path

_ROOT = Path(__file__).parent
_PAGES = frozenset(("dashboard", "login", "settings", "scroll"))


@lru_cache(maxsize=32)
def load_asset(name):
    if not re.fullmatch(r"[a-z][a-z0-9-]*\.(?:css|js)", name):
        raise ValueError("Unknown bundled asset.")
    return (_ROOT / "static" / name).read_text(encoding="utf-8")


@lru_cache(maxsize=4)
def load_page(name):
    if name not in _PAGES:
        raise ValueError("Unknown bundled page.")
    page = (_ROOT / "templates" / (name + ".html")).read_text(encoding="utf-8")

    def asset(match):
        return load_asset(match[1])

    return re.sub(r"__STATIC_([a-z][a-z0-9-]*\.(?:css|js))__", asset, page)


def dashboard_page():
    from app.webpage.design_system import DESIGN_CSS
    from app.webpage.scroll_ui import SCROLL_CSS, SCROLL_SCRIPT

    return (
        load_page("dashboard")
        .replace("__SCROLL_CSS__", SCROLL_CSS)
        .replace("__SCROLL_SCRIPT__", SCROLL_SCRIPT)
        .replace("__DESIGN_CSS__", DESIGN_CSS)
    )
