"""Public, installation-independent metadata for Home Screen web apps."""

WEB_APP_HEAD = """<link rel="apple-touch-icon" type="image/png" sizes="180x180" href="/apple-touch-icon.png?v=5">
<link rel="manifest" href="/manifest.webmanifest">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-title" content="Bitcoin DCA">
<meta name="mobile-web-app-capable" content="yes">"""

WEB_APP_MANIFEST = {
    "id": "/",
    "name": "Bitcoin DCA Dashboard",
    "short_name": "Bitcoin DCA",
    "start_url": "/",
    "scope": "/",
    "display": "standalone",
    "icons": [
        {"src": "/apple-touch-icon.png?v=5", "sizes": "180x180", "type": "image/png", "purpose": "any"},
        {"src": "/favicon.svg?v=5", "sizes": "any", "type": "image/svg+xml", "purpose": "any"},
    ],
}
