"""Local read-only portfolio dashboard and on-demand Parqet export."""
import html
from app.webpage.i18n import localize_page, translate
import json
import logging
import re
from app.webpage.templates import load_page
import requests
import ssl
from app.webpage.tls import TLSHandshakeError
from datetime import datetime, timezone, timedelta
from app.core.deposit_calendar import deposit_at
from zoneinfo import ZoneInfo
from decimal import Decimal, InvalidOperation
from html.parser import HTMLParser
from http.cookies import CookieError, SimpleCookie
from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse
from secrets import token_urlsafe
from threading import RLock
import time
import traceback
from app.core.security import AttemptLimiter, PasswordConfirmationError
from concurrent.futures import ThreadPoolExecutor
from app.webpage import price_cache
from app.exchanges.exchange_errors import UncertainWithdrawalError
from app.webpage.favicon_assets import FAVICON_ICO, FAVICON_PNG, APPLE_TOUCH_ICON_PNG, FAVICON_MASK_SVG
from app.data.analytics import report as build_report
from app.data.activity import parqet_interval_records, withdrawal_records, read_report

from app.data.activity import read_dashboard_snapshot
from app.data.reporting import parqet_aggregate_rows, parqet_csv


from app.webpage.scroll_ui import SCROLL_CSS, SCROLL_SCRIPT
from app.webpage.design_system import DESIGN_CSS, apply_appearance

from app.trading.forecast import withdrawal_forecast, forecast_details


LOG = logging.getLogger("bitcoin-dca.web")

FAVICON_SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">
<title>Bitcoin DCA Dashboard</title>
<rect x="1" y="1" width="62" height="62" rx="15" fill="#0b1020" stroke="#26324a" stroke-width="2"/>
<circle cx="32" cy="32" r="24" fill="#8bafff"/>
<g transform="rotate(14 32 32)" fill="none" stroke="#0b1020" stroke-width="4.5" stroke-linecap="square" stroke-linejoin="round">
<path d="M23 19v27M23 19h11c13 0 13 13 0 13H23m0 0h13c14 0 14 14 0 14H23"/>
<path d="M28 13v6m7-6v6M28 46v6m7-6v6"/>
</g>
</svg>"""

HTML = load_page("dashboard")


LOGIN_HTML = load_page("login")

SESSION_TTL_SECONDS = 30 * 60
_SESSION_LOCK = RLock()
_LOGIN_ATTEMPTS = AttemptLimiter()
_SESSIONS = {}


HTML = HTML.replace("__SCROLL_CSS__", SCROLL_CSS).replace("__SCROLL_SCRIPT__", SCROLL_SCRIPT).replace("__DESIGN_CSS__", DESIGN_CSS)
LOGIN_HTML = LOGIN_HTML.replace("__DESIGN_CSS__", DESIGN_CSS)

def _login_page(error="", appearance="system", language="en"):
    page = apply_appearance(LOGIN_HTML.replace("{{ERROR}}", html.escape(translate(error,language))), appearance)
    return localize_page(page,language)


class _PageTextParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []

    def handle_data(self, data):
        if data and data.strip():
            self.parts.append(data.strip())


def _kraken_public_btc_price(currency):
    currency = currency.upper()
    if currency not in ("EUR", "USD"):
        raise ValueError("Display currency and QUOTE_CURRENCY must be EUR or USD")
    url = f"https://www.kraken.com/convert/btc/{currency.lower()}"
    response = requests.get(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (compatible; BitcoinDCA/1.0)",
            "Accept": "text/html,application/xhtml+xml",
        },
        timeout=15,
    )
    response.raise_for_status()
    parser = _PageTextParser()
    parser.feed(response.text)
    page_text = " ".join(" ".join(parser.parts).split())
    number = r"([0-9][0-9,]*(?:\.[0-9]+)?)"
    patterns = (
        rf"1\s*BTC\s*=\s*{number}\s*{currency}\b",
        rf"1(?:\.00)?\s*BTC\s*=\s*[$€]\s*{number}",
    )
    for pattern in patterns:
        match = re.search(pattern, page_text, flags=re.IGNORECASE)
        if match:
            try:
                price = Decimal(match.group(1).replace(",", ""))
            except InvalidOperation:
                continue
            if price.is_finite() and price > 0:
                return price
    raise RuntimeError(f"Could not find the BTC/{currency} price on Kraken’s public converter page")


def _public_market_price(display_currency, quote_currency, currencies=()):
    display_currency=display_currency.upper()
    quote_currency=quote_currency.upper()
    needed={display_currency,quote_currency,*currencies}
    if not needed <= {'EUR','USD'}:
        raise ValueError('Display and historical fiat currencies must be EUR or USD')
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures={c:executor.submit(price_cache.get_price,c,_kraken_public_btc_price) for c in needed}
        prices={c:f.result() for c,f in futures.items()}
    target=prices[display_currency][0]
    return {'currency':display_currency,'quoteCurrency':quote_currency,'price':str(target),
            'conversionRate':str(target/prices[quote_currency][0]),
            'conversionRates':{c:str(target/v[0]) for c,v in prices.items()},
            'source':'Kraken public conversion page','updatedAt':int(min(v[1] for v in prices.values())),
            'stale':any(v[2] for v in prices.values())}


def _period(query):
    try:
        start_ms = int(query["start"][0])
        end_ms = int(query["end"][0])
    except (KeyError, ValueError, IndexError):
        raise ValueError("start and end must be Unix timestamps in milliseconds")
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    if start_ms < 0 or end_ms <= start_ms or end_ms > now_ms + 60_000:
        raise ValueError("Invalid period; end must be after start and not in the future")
    return start_ms, end_ms


def session_is_valid(token):
    with _SESSION_LOCK:
        expires_at = _SESSIONS.get(token)
        if expires_at is None:
            return False
        if expires_at <= time.monotonic():
            _SESSIONS.pop(token, None)
            return False
        return True


class Handler(BaseHTTPRequestHandler):
    settings = None
    runtime = None
    withdrawal_service = None
    worker = None
    tls_context = None

    def _login_page(self, error=""):
        return _login_page(error, (self.settings or {}).get("appearance", "system"), (self.settings or {}).get("language", "en"))

    def setup(self):
        if self.tls_context is not None:
            self.request.settimeout(10)
            try:
                self.request = self.tls_context.wrap_socket(self.request, server_side=True)
            except (ssl.SSLError, ConnectionError, TimeoutError) as error:
                self.request.close()
                raise TLSHandshakeError(error) from None
        super().setup()


    def end_headers(self):
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Referrer-Policy', 'same-origin')
        self.send_header('Content-Security-Policy', "frame-ancestors 'self'")
        super().end_headers()

    def _send(self, status, body, content_type="application/json; charset=utf-8", filename=None, *, cache_control="no-store"):
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", cache_control)
        if filename:
            self.send_header("Content-Disposition", 'attachment; filename="' + filename + '"')
        self.end_headers()
        self.wfile.write(body)

    def _json(self, status, obj):
        language = (self.settings or {}).get('language','en')
        # Localize only presentation fields, never ledger values or exchange IDs.
        def presentation(value):
            if isinstance(value, dict):
                return {key: translate(item,language) if key in ('error','message','reason','destination','nextPurchaseStatus','estimatedWithdrawalStatus','botStatusLabel') and isinstance(item,str) else presentation(item) for key,item in value.items()}
            if isinstance(value, list): return [presentation(item) for item in value]
            return value
        obj = presentation(obj)
        self._send(status, json.dumps(obj, ensure_ascii=False).encode("utf-8"))

    def _has_valid_session(self):
        try:
            cookies = SimpleCookie(self.headers.get("Cookie", ""))
            morsel = cookies.get("dca_session")
        except CookieError:
            return False
        if morsel is None:
            return False
        token = morsel.value
        return session_is_valid(token)

    def _require_authentication(self):
        if self._has_valid_session():
            if self.runtime and urlparse(self.path).path not in ('/api/settings', '/api/settings/test', '/settings', '/logout', '/'):
                data = self.runtime.store.snapshot()
                if not data['complete'] or data['account'].get('password_change_required'):
                    self._json(403, {'error': 'Complete configuration and update your password in Settings first.'})
                    return False
            return True
        self._json(401, {"error": "Authentication required"})
        return False

    def _handle_login(self):
        client = self.client_address[0]
        retry = _LOGIN_ATTEMPTS.consume(client)
        if retry:
            LOG.info('Dashboard sign-in rate limited')
            self.send_response(429)
            self.send_header('Retry-After', str(retry))
            body = self._login_page('Too many sign-in attempts. Please try again later.').encode('utf-8')
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-store')
            self.end_headers();self.wfile.write(body)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0 or length > 4096:
                raise ValueError("Invalid login request")
            form = parse_qs(self.rfile.read(length).decode("utf-8"), keep_blank_values=True)
            username = form.get("username", [""])[0]
            password = form.get("password", [""])[0]
        except (ValueError, UnicodeDecodeError):
            self._send(400, self._login_page("Please enter your username and password."), "text/html; charset=utf-8")
            return

        valid = bool(self.runtime and self.runtime.store.authenticate(username, password))
        if not valid:
            self._send(401, self._login_page("The username or password is incorrect."), "text/html; charset=utf-8")
            return

        _LOGIN_ATTEMPTS.clear(client)
        token = token_urlsafe(32)
        now = time.monotonic()
        with _SESSION_LOCK:
            expired = [key for key, expiry in _SESSIONS.items() if expiry <= now]
            for key in expired:
                _SESSIONS.pop(key, None)
            _SESSIONS[token] = now + SESSION_TTL_SECONDS
        self.send_response(303)
        self.send_header(
            "Set-Cookie",
            f"dca_session={token}; Path=/; Max-Age={SESSION_TTL_SECONDS}; Secure; HttpOnly; SameSite=Strict",
        )
        self.send_header("Location", "/")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _handle_logout(self):
        try:
            cookies = SimpleCookie(self.headers.get("Cookie", ""))
            morsel = cookies.get("dca_session")
        except CookieError:
            morsel = None
        if morsel is not None:
            with _SESSION_LOCK:
                _SESSIONS.pop(morsel.value, None)
        self.send_response(303)
        self.send_header("Set-Cookie", "dca_session=; Path=/; Max-Age=0; Secure; HttpOnly; SameSite=Strict")
        self.send_header("Location", "/")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _settings_body(self):
        if self.headers.get('X-DCA-Action') != 'settings' or self.headers.get('Content-Type') != 'application/json':
            raise ValueError('Invalid settings request.')
        length = int(self.headers.get('Content-Length', '0'))
        if not 0 < length <= 32768:
            raise ValueError('Invalid settings request size.')
        data = json.loads(self.rfile.read(length).decode('utf-8'))
        if not isinstance(data, dict): raise ValueError('Invalid settings request.')
        return data

    def _settings_post(self, path):
        if not self.runtime:
            self._json(404, {'error': 'Settings unavailable.'})
            return
        operation = {'/api/setup/account': 'Initial account creation', '/api/settings/test': 'Exchange connection test', '/api/settings': 'Settings update', '/api/settings/forecast': 'Forecast settings update'}[path]
        if path != '/api/setup/account' and not self._require_authentication():
            LOG.info('%s rejected: authentication required', operation)
            return
        try:
            payload = self._settings_body()
            if path == '/api/setup/account':
                self.runtime.store.create_account(payload.get('username'), payload.get('password'))
                token = token_urlsafe(32)
                with _SESSION_LOCK: _SESSIONS[token] = time.monotonic() + SESSION_TTL_SECONDS
                self.send_response(200)
                self.send_header('Set-Cookie', f'dca_session={token}; Path=/; Max-Age={SESSION_TTL_SECONDS}; Secure; HttpOnly; SameSite=Strict')
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', '2')
                self.send_header('Cache-Control', 'no-store')
                self.end_headers()
                self.wfile.write(b'{}')
            elif path == '/api/settings/forecast':
                self._json(200, self.runtime.save_forecast_deposit(payload))
            elif path == '/api/settings/test':
                self._json(200, self.runtime.test_connection(payload))
            else:
                changed = self.runtime.save(payload)
                if changed:
                    with _SESSION_LOCK: _SESSIONS.clear()
                    LOG.info('Dashboard account credentials updated; all dashboard sessions invalidated')
                self._json(200, {'saved': True, 'signInRequired': changed})
        except PasswordConfirmationError as exc:
            if exc.retry_after:
                self.send_response(429)
                self.send_header('Retry-After', str(exc.retry_after))
                body = json.dumps({'error': str(exc)}).encode()
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(body)))
                self.send_header('Cache-Control', 'no-store')
                self.end_headers();self.wfile.write(body)
            else: self._json(400, {'error': str(exc)})
        except (ValueError, UnicodeDecodeError) as exc:
            LOG.info('%s rejected: invalid request, configuration or account verification', operation)
            self._json(400, {'error': str(exc)})
        except requests.RequestException as exc:
            LOG.warning('%s unavailable: exchange/network request failed (%s)', operation, type(exc).__name__)
            # Exchange errors may contain request details. Never echo them to the browser.
            self._json(502, {'error': 'Exchange connection failed. Check credentials, permissions and internet access.'})
        except Exception as exc:
            LOG.error('%s failed unexpectedly (%s); configuration was not confirmed', operation, type(exc).__name__)
            # Omit exception text and locals: exchange errors can contain secrets.
            LOG.debug('Settings failure stack:\n%s', ''.join(traceback.format_list(traceback.extract_tb(exc.__traceback__))))
            self._json(500, {'error': 'Settings could not be confirmed. Check persistent storage and try again.'})

    def _dashboard_html(self):
        settings = self.settings
        hidden = []
        if not settings.get('manual_withdrawal_enabled', True): hidden += ['#manualWithdraw', '#withdrawal-note']
        if not settings.get('parqet_enabled', True): hidden += ['#download', '#parqet-actions', '#exportMessage', '#parqet-note', '#manual-export-note']
        if not settings.get('withdrawals_enabled', False): hidden += ['#automatic-withdrawal-note']
        styles = '<style>' + ','.join(hidden) + '{display:none!important}</style>' if hidden else ''
        page = HTML.replace('</head>', styles + '</head>')
        if not settings.get('withdrawals_enabled', False):
            page = page.replace('Schedule and automatic withdrawal</strong>', 'Purchase schedule</strong>')
        if not settings.get('parqet_enabled', True):
            page = page.replace('Period analysis and Parqet export</strong>', 'Period analysis</strong>')
            page = page.replace('to review activity and prepare a Parqet export.', 'to review activity.')
        return localize_page(apply_appearance(page, settings.get("appearance", "system")), settings.get("language", "en"))

    def do_POST(self):
        if self.runtime:
            from app.core.configuration import runtime_settings
            self.settings = runtime_settings(self.runtime.store.snapshot()['settings'])
        parsed = urlparse(self.path)
        if parsed.path in ('/api/setup/account', '/api/settings', '/api/settings/test', '/api/settings/forecast'):
            self._settings_post(parsed.path)
            return
        if parsed.path == "/login":
            self._handle_login()
            return
        if parsed.path == "/logout":
            self._handle_logout()
            return
        if not self._require_authentication():
            return
        if parsed.path == "/api/ui-events":
            if self.headers.get("X-DCA-Action") != "ui-event" or self.headers.get("Content-Type") != "application/json":
                self._json(403, {"error": "Invalid UI event"})
                return
            messages = {
                "withdrawal_clicked": "Manual withdrawal button clicked",
                "withdrawal_confirmed": "Manual withdrawal confirmed in dashboard; submission requested",
                "withdrawal_cancelled": "Manual withdrawal cancelled in dashboard; no submission",
                "withdrawal_expired": "Manual withdrawal confirmation expired; no submission",
                "export_clicked": "Parqet CSV export button clicked",
                "settings_closed": "Settings dialog closed",
                "settings_save_cancelled": "Settings review cancelled; no save submitted",
            }
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= 256:
                    raise ValueError("Invalid UI event")
                payload = json.loads(self.rfile.read(length).decode("utf-8"))
                event = payload.get("event") if isinstance(payload, dict) else None
                if not isinstance(event, str) or event not in messages:
                    raise ValueError("Invalid UI event")
                LOG.info(messages[event])
                self._json(200, {"logged": True})
            except (ValueError, UnicodeDecodeError):
                self._json(400, {"error": "Invalid UI event"})
            return
        if parsed.path in ("/api/withdrawal/preview", "/api/withdrawal/confirm"):
            if not (self.settings or {}).get('manual_withdrawal_enabled', True):
                self._json(403, {'error': 'Manual withdrawals are disabled in Settings.'})
                return
            # A custom header plus JSON prevents cross-origin form submissions.
            if self.headers.get("X-DCA-Action") != "withdrawal" or self.headers.get("Content-Type") != "application/json":
                self._json(403, {"error": "Invalid withdrawal request"})
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= 4096:
                    raise ValueError("Invalid request body")
                payload = json.loads(self.rfile.read(length).decode("utf-8"))
                if not isinstance(payload, dict):
                    raise ValueError("Invalid request body")
                session = SimpleCookie(self.headers.get("Cookie", ""))["dca_session"].value
                token = payload.get("token")
                if parsed.path.endswith("/confirm") and not isinstance(token, str):
                    raise ValueError("Confirmation token is required")
                result = self.withdrawal_service("preview" if parsed.path.endswith("/preview") else "confirm", session, token)
                LOG.info("Manual withdrawal %s request accepted", "confirmation" if parsed.path.endswith("/confirm") else "preview")
                self._json(202 if "jobId" in result else 200, result)
            except (ValueError, UnicodeDecodeError) as exc:
                LOG.log(logging.ERROR if isinstance(exc, UncertainWithdrawalError) else logging.INFO,
                        "Manual withdrawal request rejected: %s", exc)
                self._json(400, {"error": str(exc)})
            except requests.RequestException as exc:
                LOG.warning("Manual withdrawal request unavailable: %s", exc)
                LOG.debug("Manual withdrawal transport failure", exc_info=True)
                self._json(503, {"error": "Exchange request failed. Check exchange status before retrying."})
            except Exception:
                LOG.exception("Manual withdrawal request failed")
                self._json(502, {"error": "Withdrawal could not be confirmed. Check exchange status and container logs before trying again."})
            return
        self._json(404, {"error": "Not found"})

    def do_GET(self):
        if self.runtime:
            from app.core.configuration import runtime_settings
            self.settings = runtime_settings(self.runtime.store.snapshot()['settings'])
        parsed = urlparse(self.path)
        if parsed.path == '/healthz':
            healthy=bool(self.worker and self.worker.healthy())
            self._json(200 if healthy else 503,{'healthy':healthy})
            return
        icon = {
            "/bitcoin-dca-icon-v3.png": (APPLE_TOUCH_ICON_PNG, "image/png"),
            "/safari-pinned-tab-v3.svg": (FAVICON_MASK_SVG, "image/svg+xml; charset=utf-8"),
            "/apple-touch-icon-precomposed.png": (APPLE_TOUCH_ICON_PNG, "image/png"),
            "/favicon.ico": (FAVICON_ICO, "image/x-icon"),
            "/favicon-32.png": (FAVICON_PNG, "image/png"),
            "/apple-touch-icon.png": (APPLE_TOUCH_ICON_PNG, "image/png"),
        }.get(parsed.path)
        if icon is not None:
            self._send(200, icon[0], icon[1], cache_control="public, max-age=86400")
            return
        if parsed.path == "/favicon.svg":
            self._send(200, FAVICON_SVG, "image/svg+xml; charset=utf-8", cache_control="public, max-age=86400")
            return
        if self.runtime and parsed.path in ('/', '/configure', '/settings', '/api/settings'):
            from app.webpage.settings_ui import settings_page
            data = self.runtime.store.snapshot()
            if not data['account']:
                if parsed.path == '/api/settings':
                    self._json(401, {'error': 'Create an account first.'})
                else:
                    LOG.info('First-run setup opened; dashboard account creation is required')
                    self._send(200, settings_page(self.runtime.store, create_account=True), 'text/html; charset=utf-8')
                return
            if parsed.path in ('/configure', '/settings') and not self._has_valid_session():
                if parse_qs(parsed.query).get('embedded') == ['1']:
                    self._send(401, '<script>parent.postMessage({type:"dca-settings-auth-required"},location.origin)</script>', 'text/html; charset=utf-8')
                    return
                self._send(200, self._login_page(), 'text/html; charset=utf-8')
                return
            if self._has_valid_session():
                if parsed.path == '/api/settings':
                    self._json(200, self.runtime.store.public())
                    return
                if parsed.path in ('/configure', '/settings') or not data['complete'] or data['account'].get('password_change_required'):
                    LOG.info('Settings opened' if data['complete'] else 'First-run bot configuration opened')
                    self._send(200, settings_page(self.runtime.store, embedded=parse_qs(parsed.query).get("embedded") == ["1"]), 'text/html; charset=utf-8')
                    return
        if parsed.path == "/" and not self._has_valid_session():
            self._send(200, self._login_page(), "text/html; charset=utf-8")
            return
        if not self._require_authentication():
            return
        if parsed.path == "/":
            self._send(200, self._dashboard_html(), "text/html; charset=utf-8")
            return
        if parsed.path.startswith('/api/withdrawal/jobs/'):
            session=SimpleCookie(self.headers.get('Cookie',''))['dca_session'].value
            try:
                self._json(200,self.worker.get_job(parsed.path.rsplit('/',1)[-1],session))
            except (ValueError,AttributeError) as exc:
                self._json(404,{'error':str(exc)})
            return
        if parsed.path == "/api/withdrawal/config":
            settings = self.settings
            kraken = settings["exchange"] == "KRAKEN"
            destination = ("Kraken saved withdrawal method: " + (settings.get("kraken_withdraw_key") or "not configured")) if kraken else ("Bitvavo address: " + (settings.get("withdraw_address") or "not configured") + "; network: " + settings.get("withdraw_network", "BTC"))
            missing = []
            if self.runtime and self.runtime.exchange_check_pending:
                missing.append('wait for the automatic exchange check and open transactions to close')
            if not settings.get('manual_withdrawal_enabled', True):
                missing.append('enable manual withdrawals in Settings')
            if not settings["live"]:
                missing.append("enable LIVE_TRADING=true")
            if kraken:
                if not settings.get("kraken_withdraw_key"):
                    missing.append("set KRAKEN_WITHDRAW_KEY to your saved Bitcoin withdrawal method in Settings")
            else:
                if not settings.get("withdraw_address"):
                    missing.append("set WITHDRAW_ADDRESS in Settings")
                if not settings.get("withdraw_network"):
                    missing.append("set WITHDRAW_NETWORK in Settings")
            if not self.withdrawal_service:
                missing.append("restart the bot to enable the withdrawal service")
            reason = "Manual withdrawal is unavailable: " + "; ".join(missing) + "." if missing else ""
            self._json(200, {"destination": destination, "enabled": not missing, "reason": reason,
                             "exchange": settings["exchange"],
                             "target": (settings.get("kraken_withdraw_key") if kraken else settings.get("withdraw_address")) or "",
                             "network": None if kraken else settings.get("withdraw_network", "BTC")})
            return
        query = parse_qs(parsed.query)
        if parsed.path == "/api/market-price":
            currency = query.get("currency", ["EUR"])[0].upper()
            try:
                market = _public_market_price(currency, self.settings["quote"], query.get("currencies",[""])[0].split(",") if query.get("currencies",[""])[0] else ())
                self._json(200, market)
            except ValueError as exc:
                self._json(400, {"error": str(exc)})
            except (RuntimeError, requests.RequestException) as exc:
                LOG.warning("Kraken reference price unavailable: %s", exc)
                LOG.debug("Reference price fetch failure", exc_info=True)
                self._json(503, {"error": str(exc)})
            except Exception:
                LOG.exception("Kraken public price page fetch failed")
                self._json(502, {"error": "Could not fetch the current BTC price from Kraken’s public page. Check container internet access."})
            return
        try:
            if parsed.path == "/api/schedule":
                snapshot = read_dashboard_snapshot()
                exchange_check_pending = bool(self.runtime and self.runtime.exchange_check_pending)
                exchange_status = ('Waiting for startup delay' if exchange_check_pending and time.monotonic() < self.runtime.ready_at else 'Waiting for automatic exchange check')
                if exchange_check_pending:
                    snapshot = {**snapshot, 'nextPurchaseAt':None, 'nextPurchaseStatus':exchange_status}
                balance_matches = (snapshot.get("quote") == self.settings["quote"]
                                   and snapshot.get("exchange") == self.settings["exchange"])
                if exchange_check_pending:
                    forecast_at, forecast_status = None, exchange_status
                else:
                    forecast_at, forecast_status = withdrawal_forecast(
                        self.settings, snapshot if balance_matches else {},
                        self.settings.get("expected_monthly_deposit") or "0", datetime.now(timezone.utc))
                checked_at = snapshot.get('updatedAt') if balance_matches else None
                worker_error = bool(self.worker and self.worker.last_error)
                if self.worker and not self.worker.healthy():
                    status_label = 'Worker unavailable'
                elif worker_error:
                    status_label = 'Account check failed; retrying'
                elif exchange_check_pending:
                    status_label = exchange_status
                elif not balance_matches:
                    status_label = 'Waiting for account check'
                elif (str(snapshot.get('nextPurchaseStatus','')).startswith(('Waiting','Checking'))
                      and snapshot['nextPurchaseStatus'] != 'Waiting for confirmation that the previous order has ended'):
                    status_label = snapshot['nextPurchaseStatus']
                elif not self.settings.get('live'):
                    status_label = 'Simulation'
                else:
                    status_label = 'Bot active'
                status_warning = worker_error or bool(self.worker and not self.worker.healthy())
                status_tone = 'error' if status_warning else 'active' if status_label == 'Bot active' else 'waiting'
                self._json(200, {
                    "botStatusLabel": status_label,
                    "botStatusTone": status_tone,
                    "botStatusWarning": worker_error or bool(self.worker and not self.worker.healthy()),
                    "lastAccountCheckAt": checked_at,
                    "staleAfterSeconds": max(120, self.settings.get('check_interval_seconds',300)*2),
                    "forecastDetails": forecast_details(self.settings,snapshot) if forecast_at and balance_matches else None,
                    "exchangeCheckPending": exchange_check_pending,
                    "expectedMonthlyDeposit": self.settings.get("expected_monthly_deposit", ""),
                    "quote": self.settings["quote"],
                    "exchange": self.settings["exchange"],
                    "quoteBalance": snapshot.get("quoteBalance") if balance_matches else None,
                    "configuredBuyAmount": str(self.settings.get("buy_amount", 0)),
                    "finalPurchase": bool((snapshot.get("withdrawalForecastPlan") or {}).get("useRemainingBudget")) if balance_matches else False,
                    "effectiveBuyAmount": (snapshot.get("withdrawalForecastPlan") or {}).get("orderAmount") if balance_matches else None,
                    "btcBalance": snapshot.get("btcBalance") if balance_matches else None,
                    "estimatedWithdrawalAt": forecast_at,
                    "estimatedWithdrawalStatus": forecast_status,
                    "balanceUpdatedAt": snapshot.get("updatedAt") if balance_matches else None,
                    "nextPurchaseAt": snapshot.get("nextPurchaseAt"),
                    "nextPurchaseStatus": snapshot.get("nextPurchaseStatus", "Schedule pending"),
                    "timezone": self.settings["timezone"],
                    "serverTime": datetime.now(timezone.utc).isoformat(),
                })
                return
            records = []
            if parsed.path == "/api/withdrawals":
                withdrawals = [
                    {
                        "timestamp": _row_timestamp_ms(record["row"]),
                        "txId": record.get("id", ""),
                    }
                    for record in withdrawal_records()
                    if record.get('withdrawalStatus')=='completed' 
                ]
                withdrawals.sort(key=lambda item: item["timestamp"])
                self._json(200, withdrawals)
                return
            if parsed.path in ("/api/analytics", "/api/export.csv"):
                if parsed.path == "/api/export.csv":
                    if not (self.settings or {}).get('parqet_enabled', True):
                        self._json(403, {'error': 'Parqet CSV export is disabled in Settings.'})
                        return
                    LOG.info("Parqet CSV export requested")
                start_ms, end_ms = _period(query)
                if parsed.path == "/api/export.csv":
                    selected_records=parqet_interval_records(start_ms,end_ms)
                    real_records = [record for record in selected_records if not record.get("simulated")]
                    if not any(record["row"].get("type") == "TransferOut" and record.get("withdrawalStatus")=="completed" for record in real_records):
                        raise ValueError(
                            "No confirmed bot-recorded BTC withdrawal was found in the selected period. "
                            "The Parqet export requires a purchase and a withdrawal. "
                            "Choose a period that includes a withdrawal, or export after your first withdrawal."
                        )
                    if not any(record["row"].get("type") == "Buy" for record in real_records):
                        raise ValueError(
                            "No real bot purchase was found since the previous confirmed withdrawal. "
                            "The Parqet export requires a real purchase and a withdrawal; dry-run purchases are excluded."
                        )
                    rows = parqet_aggregate_rows(
                        selected_records, self.settings["exchange"]
                    )
                    if not rows:
                        raise ValueError(
                            "The selected period must contain at least one real purchase "
                            "and one bot-recorded BTC withdrawal."
                        )
                    filename = "parqet_btc_" + str(start_ms) + "_" + str(end_ms) + ".csv"
                    csv_data = parqet_csv(rows)
                    self._send(200, csv_data, "text/csv; charset=utf-8", filename)
                    LOG.info("Parqet CSV export response sent: rows=%s; selected period=%s..%s", len(rows), start_ms, end_ms)
                else:
                    page=int(query.get('page',['1'])[0]);limit=int(query.get('limit',['10'])[0])
                    page_records,total,page,totals,balance=read_report(start_ms,end_ms,page,limit)
                    snapshot=read_dashboard_snapshot()
                    snapshot['trackedBtc']=str(balance)
                    if snapshot.get('quote') not in (None,self.settings['quote']):snapshot['price']='0'
                    result=build_report(self.settings,totals,snapshot,page_records)
                    limit=max(1,min(1000,limit))
                    result['pagination']={'page':page,'pageSize':limit,'total':total,'pages':max(1,(total+limit-1)//limit)}
                    self._json(200, result)
                return
            self._json(404, {"error": "Not found"})
        except ValueError as exc:
            if parsed.path == "/api/export.csv":
                LOG.info("Parqet CSV export rejected: %s", exc)
            self._json(400, {"error": str(exc)})
        except requests.RequestException as exc:
            LOG.warning("%s unavailable due to an external service: %s", "Parqet CSV export" if parsed.path == "/api/export.csv" else "Web UI data", exc)
            LOG.debug("External reporting service failure", exc_info=True)
            self._json(503, {"error": "External data service unavailable. Please try again later."})
        except Exception as exc:
            LOG.exception("%s failed unexpectedly", "Parqet CSV export" if parsed.path == "/api/export.csv" else "Web UI request")
            self._json(502, {"error": "Stored bot activity could not be loaded. Check the container logs."})

    def log_message(self, fmt, *args):
        LOG.debug("Web UI %s - %s", self.address_string(), fmt % args)


def _row_timestamp_ms(row):
    value = datetime.fromisoformat(row["datetime"].replace("Z", "+00:00"))
    return int(value.timestamp() * 1000)


def serve(settings, port, withdrawal_service=None, worker=None, runtime=None, stop=None):
    import os
    from app.webpage.tls import certificate_hosts, https_context, renew_certificates, HTTPSWebServer
    from threading import Thread, Event
    if runtime is not None:
        runtime.session_validator = session_is_valid
        def invalidate_sessions():
            with _SESSION_LOCK: _SESSIONS.clear()
        runtime.invalidate_sessions = invalidate_sessions
    hosts = certificate_hosts(os.getenv("WEB_UI_TLS_HOSTS", ""))
    context = https_context(hosts)
    handler = type("ConfiguredHandler", (Handler,), {"settings": settings, "withdrawal_service": staticmethod(withdrawal_service), "worker":worker, "runtime":runtime, "tls_context":context})
    server = HTTPSWebServer(("0.0.0.0", port), handler)
    LOG.info("HTTPS dashboard listening on container port %s.", port)
    stop = stop or Event()
    Thread(target=renew_certificates, args=(handler, hosts, stop), name="https-certificate-renewal", daemon=True).start()
    server.timeout = 0.5
    try:
        while not stop.is_set():
            server.handle_request()
    finally:
        stop.set()
        server.server_close()


