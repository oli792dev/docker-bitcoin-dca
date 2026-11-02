"""Shared German catalog for presentation only; financial data and API identifiers stay unchanged."""

import json
import re
from functools import lru_cache
from html import escape
from html.parser import HTMLParser
from pathlib import Path

from app.webpage.templates import load_asset

_ROOT = Path(__file__).parent


@lru_cache(maxsize=1)
def german_catalog():
    return json.loads((_ROOT / "locales" / "de.json").read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def _patterns():
    patterns = []
    for source, target in german_catalog().items():
        if "{" not in source:
            continue
        names = re.findall(r"\{(\w+)\}", source)
        expression = re.escape(source)
        for name in names:
            expression = expression.replace(re.escape("{" + name + "}"), "(?P<" + name + ">.+?)")
        patterns.append((re.compile("^" + expression + "$", re.S), target))
    return patterns


def translate(value, language="en"):
    if language != "de" or not isinstance(value, str):
        return value
    catalog = german_catalog()
    if value in catalog:
        return catalog[value]
    for pattern, target in _patterns():
        match = pattern.fullmatch(value)
        if match:
            values = match.groupdict()
            if "reason" in values:
                values["reason"] = "; ".join(translate(part, language) for part in values["reason"].split("; "))
            return re.sub(r"\{(\w+)\}", lambda token, values=values: values[token[1]], target)
    return value


class _Page(HTMLParser):
    def __init__(self, language):
        super().__init__(convert_charrefs=False)
        self.language = language
        self.parts = []
        self.skip = 0

    def handle_starttag(self, tag, attrs):
        raw = self.get_starttag_text()

        def attribute(match):
            return match[1] + match[2] + escape(translate(match[3], self.language), quote=True) + match[2]

        raw = re.sub(r'((?:aria-label|placeholder|title)\s*=\s*)([\'"])(.*?)\2', attribute, raw)
        if tag == "html":
            raw = re.sub(r'lang="en"', 'lang="' + self.language + '"', raw)
        self.parts.append(raw)
        if tag in ("script", "style", "code"):
            self.skip += 1

    def handle_endtag(self, tag):
        self.parts.append("</" + tag + ">")
        if tag in ("script", "style", "code"):
            self.skip -= 1

    def handle_data(self, data):
        if not self.skip:
            normalized = " ".join(data.split())
            translated = translate(normalized, self.language)
            if translated != normalized:
                leading = re.match(r"^\s*", data)[0]
                trailing = re.search(r"\s*$", data)[0]
                data = leading + escape(translated) + trailing
        self.parts.append(data)

    def handle_entityref(self, name):
        self.parts.append("&" + name + ";")

    def handle_charref(self, name):
        self.parts.append("&#" + name + ";")

    def handle_comment(self, data):
        self.parts.append("<!--" + data + "-->")

    def handle_decl(self, decl):
        self.parts.append("<!" + decl + ">")

    def handle_startendtag(self, tag, attrs):
        self.parts.append(self.get_starttag_text())


def localize_page(page, language="en"):
    language = language if language in ("de", "en") else "en"
    if language == "de":
        parser = _Page(language)
        parser.feed(page)
        page = "".join(parser.parts)
    payload = json.dumps(
        {"language": language, "catalog": german_catalog() if language == "de" else {}}, ensure_ascii=False
    )
    payload = payload.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    script = "<script data-i18n>globalThis.DCA_I18N=" + payload + ";" + load_asset("i18n.js") + "</script>"
    return page.replace("</head>", script + "</head>", 1)
