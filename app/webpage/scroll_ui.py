"""Shared overflow indicators, scrollbars and dialog background locking."""
from app.webpage.templates import load_asset, load_page

SCROLL_CSS = load_asset("scroll.css")
SCROLL_SCRIPT = load_page("scroll")
