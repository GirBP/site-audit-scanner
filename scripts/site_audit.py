#!/usr/bin/env python3
"""Read-only static website crawler and evidence-based audit reporter."""

from __future__ import annotations

import argparse
import collections
import dataclasses
import datetime as dt
import html
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import re
import socket
import sys
import time
from typing import Any, Iterable
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET


VERSION = "1.0.0"
SEVERITIES = ("critical", "high", "medium", "low")
DEFAULT_EXCLUDES = (
    r"(^|/)(admin|logout|delete|remove|wp-admin|checkout|account)(/|$)",
    r"[?&](token|key|secret|password|auth)=",
)
ASSET_EXTENSIONS = {
    ".avif", ".webp", ".jpg", ".jpeg", ".png", ".gif", ".svg", ".ico",
    ".css", ".js", ".mjs", ".map", ".woff", ".woff2", ".ttf", ".eot",
    ".pdf", ".zip", ".rar", ".7z", ".mp4", ".webm", ".mp3", ".wav",
}
STOPWORDS = {
    "і", "й", "та", "а", "але", "або", "в", "у", "на", "до", "з", "із",
    "зі", "за", "для", "по", "про", "від", "під", "над", "при", "без",
    "це", "цей", "ця", "ці", "того", "що", "як", "який", "яка", "які",
    "ми", "ви", "вони", "він", "вона", "воно", "їх", "наш", "ваш", "не",
    "так", "вже", "ще", "можна", "the", "a", "an", "and", "or", "but",
    "in", "on", "at", "to", "from", "for", "of", "with", "without", "is",
    "are", "be", "this", "that", "these", "those", "it", "we", "you",
}
WORD_RE = re.compile(r"[0-9A-Za-zА-Яа-яІіЇїЄєҐґ]+(?:[’'ʼ-][0-9A-Za-zА-Яа-яІіЇїЄєҐґ]+)*")


@dataclasses.dataclass
class Finding:
    rule: str
    severity: str
    url: str
    message: str
    evidence: str = ""
    recommendation: str = ""

    def as_dict(self) -> dict[str, str]:
        return dataclasses.asdict(self)


@dataclasses.dataclass
class FetchResult:
    requested_url: str
    final_url: str
    status: int
    headers: dict[str, str]
    body: bytes
    ttfb_ms: float
    total_ms: float
    error: str = ""


class AuditHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.html_attrs: dict[str, str] = {}
        self.title_parts: list[str] = []
        self._in_title = False
        self._heading: dict[str, Any] | None = None
        self._anchor: dict[str, Any] | None = None
        self._button: dict[str, Any] | None = None
        self._label: dict[str, Any] | None = None
        self._json_ld: list[str] | None = None
        self._skip_depth = 0
        self._in_body = False
        self.body_text_parts: list[str] = []
        self.headings: list[dict[str, Any]] = []
        self.meta: list[dict[str, str]] = []
        self.links: list[dict[str, str]] = []
        self.images: list[dict[str, str]] = []
        self.sources: list[dict[str, str]] = []
        self.scripts: list[dict[str, str]] = []
        self.stylesheets: list[dict[str, str]] = []
        self.inputs: list[dict[str, str]] = []
        self.labels: list[dict[str, str]] = []
        self.buttons: list[dict[str, str]] = []
        self.forms: list[dict[str, str]] = []
        self.json_ld_blocks: list[str] = []
        self.comments = 0
        self.inline_styles = 0
        self.ids: list[str] = []
        self.semantic = collections.Counter()
        self.tech_source_markers: list[str] = []

    @staticmethod
    def _attrs(attrs: list[tuple[str, str | None]]) -> dict[str, str]:
        return {str(k).lower(): "" if v is None else str(v) for k, v in attrs}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        a = self._attrs(attrs)
        if "id" in a:
            self.ids.append(a["id"])
        if "style" in a:
            self.inline_styles += 1
        if tag == "html":
            self.html_attrs = a
        if tag == "body":
            self._in_body = True
        if tag == "title":
            self._in_title = True
        if tag in {"script", "style", "noscript", "svg"}:
            self._skip_depth += 1
        if tag == "script":
            self.scripts.append(a)
            if a.get("type", "").lower() == "application/ld+json":
                self._json_ld = []
        elif tag == "meta":
            self.meta.append(a)
        elif tag == "link":
            rel = a.get("rel", "").lower().split()
            if "stylesheet" in rel:
                self.stylesheets.append(a)
            else:
                self.links.append({"tag": "link", **a, "text": ""})
        elif tag == "a":
            self._anchor = {"tag": "a", **a, "_text": []}
        elif tag == "img":
            self.images.append(a)
        elif tag == "source":
            self.sources.append(a)
        elif re.fullmatch(r"h[1-6]", tag):
            self._heading = {"level": int(tag[1]), "attrs": a, "_text": []}
        elif tag == "form":
            self.forms.append(a)
        elif tag in {"input", "select", "textarea"}:
            self.inputs.append({
                "tag": tag,
                **a,
                "_wrapped_label": "1" if self._label is not None else "",
            })
        elif tag == "label":
            self._label = {**a, "_text": []}
        elif tag == "button":
            self._button = {**a, "_text": []}
        if tag in {"main", "nav", "header", "footer", "section", "article", "aside", "address"}:
            self.semantic[tag] += 1

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        if tag.lower() in {"script", "style", "noscript", "svg"}:
            self._skip_depth = max(0, self._skip_depth - 1)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag == "title":
            self._in_title = False
        if re.fullmatch(r"h[1-6]", tag) and self._heading:
            text = clean_text(" ".join(self._heading.pop("_text")))
            self.headings.append({**self._heading, "text": text})
            self._heading = None
        elif tag == "a" and self._anchor:
            text = clean_text(" ".join(self._anchor.pop("_text")))
            self.links.append({**self._anchor, "text": text})
            self._anchor = None
        elif tag == "button" and self._button:
            text = clean_text(" ".join(self._button.pop("_text")))
            self.buttons.append({**self._button, "text": text})
            self._button = None
        elif tag == "label" and self._label:
            text = clean_text(" ".join(self._label.pop("_text")))
            self.labels.append({**self._label, "text": text})
            self._label = None
        if tag == "script" and self._json_ld is not None:
            self.json_ld_blocks.append("".join(self._json_ld).strip())
            self._json_ld = None
        if tag in {"script", "style", "noscript", "svg"}:
            self._skip_depth = max(0, self._skip_depth - 1)
        if tag == "body":
            self._in_body = False

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self.title_parts.append(data)
        if self._heading is not None:
            self._heading["_text"].append(data)
        if self._anchor is not None:
            self._anchor["_text"].append(data)
        if self._button is not None:
            self._button["_text"].append(data)
        if self._label is not None:
            self._label["_text"].append(data)
        if self._json_ld is not None:
            self._json_ld.append(data)
        if self._in_body and self._skip_depth == 0:
            text = clean_text(data)
            if text:
                self.body_text_parts.append(text)

    def handle_comment(self, data: str) -> None:
        self.comments += 1

    @property
    def title(self) -> str:
        return clean_text(" ".join(self.title_parts))

    @property
    def body_text(self) -> str:
        return clean_text(" ".join(self.body_text_parts))


def clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def safe_url(value: str) -> str:
    try:
        p = urllib.parse.urlsplit(value)
        host = p.hostname or ""
        if p.port:
            host = f"{host}:{p.port}"
        return urllib.parse.urlunsplit((p.scheme, host, p.path, "", ""))
    except Exception:
        return value.split("?", 1)[0]


def normalize_http_url(value: str, base: str | None = None) -> str:
    joined = urllib.parse.urljoin(base or value, value)
    p = urllib.parse.urlsplit(joined)
    path = re.sub(r"/{2,}", "/", p.path or "/")
    return urllib.parse.urlunsplit((p.scheme.lower(), p.netloc.lower(), path, "", ""))


def origin(value: str) -> tuple[str, str]:
    p = urllib.parse.urlsplit(value)
    return p.scheme.lower(), p.netloc.lower()


def is_local_or_file_url(value: str) -> bool:
    p = urllib.parse.urlsplit(value)
    return p.scheme == "file" or (p.hostname or "").lower() in {"127.0.0.1", "localhost", "::1"}


def is_html_candidate(value: str) -> bool:
    path = urllib.parse.urlsplit(value).path
    suffix = Path(path).suffix.lower()
    return not suffix or suffix in {".html", ".htm", ".php", ".asp", ".aspx", ".jsp"}


def attr_content(meta: Iterable[dict[str, str]], key: str, value: str) -> str:
    key = key.lower()
    value = value.lower()
    for item in meta:
        if item.get(key, "").lower() == value:
            return clean_text(item.get("content", ""))
    return ""


def rel_link(links: Iterable[dict[str, str]], rel_name: str) -> str:
    for item in links:
        rel = item.get("rel", "").lower().split()
        if rel_name.lower() in rel:
            return item.get("href", "")
    return ""


def fetch_url(url: str, timeout: float, method: str = "GET", max_bytes: int = 8_000_000) -> FetchResult:
    headers = {
        "User-Agent": f"SiteAuditScanner/{VERSION} (+read-only audit)",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.5",
    }
    if method == "GET" and max_bytes < 8_000_000:
        headers["Range"] = f"bytes=0-{max_bytes - 1}"
    req = urllib.request.Request(url, headers=headers, method=method)
    start = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            header_time = time.perf_counter()
            body = b"" if method == "HEAD" else response.read(max_bytes + 1)
            end = time.perf_counter()
            status = int(getattr(response, "status", 200) or 200)
            return FetchResult(
                requested_url=url,
                final_url=response.geturl(),
                status=status,
                headers={k.lower(): v for k, v in response.headers.items()},
                body=body[:max_bytes],
                ttfb_ms=round((header_time - start) * 1000, 1),
                total_ms=round((end - start) * 1000, 1),
                error="response truncated" if len(body) > max_bytes else "",
            )
    except urllib.error.HTTPError as exc:
        end = time.perf_counter()
        body = b""
        if method != "HEAD":
            try:
                body = exc.read(max_bytes)
            except Exception:
                pass
        return FetchResult(
            requested_url=url,
            final_url=exc.geturl() or url,
            status=int(exc.code),
            headers={k.lower(): v for k, v in exc.headers.items()},
            body=body,
            ttfb_ms=round((end - start) * 1000, 1),
            total_ms=round((end - start) * 1000, 1),
            error=str(exc),
        )
    except (urllib.error.URLError, TimeoutError, socket.timeout, OSError) as exc:
        end = time.perf_counter()
        return FetchResult(
            requested_url=url,
            final_url=url,
            status=0,
            headers={},
            body=b"",
            ttfb_ms=round((end - start) * 1000, 1),
            total_ms=round((end - start) * 1000, 1),
            error=str(exc),
        )


def decode_body(result: FetchResult) -> str:
    ctype = result.headers.get("content-type", "")
    match = re.search(r"charset=([A-Za-z0-9._-]+)", ctype, re.I)
    encoding = match.group(1) if match else "utf-8"
    try:
        return result.body.decode(encoding, errors="replace")
    except LookupError:
        return result.body.decode("utf-8", errors="replace")


def parse_html(text: str) -> AuditHTMLParser:
    parser = AuditHTMLParser()
    parser.feed(text)
    parser.close()
    return parser


def text_metrics(text: str) -> dict[str, Any]:
    words = [w.lower() for w in WORD_RE.findall(text)]
    sentences = [s for s in re.split(r"[.!?]+", text) if WORD_RE.search(s)]
    useful = [w for w in words if w not in STOPWORDS and len(w) > 2 and not w.isdigit()]
    counts = collections.Counter(useful)
    stop_count = sum(1 for w in words if w in STOPWORDS)
    shingles = collections.Counter(tuple(words[i:i + 5]) for i in range(max(0, len(words) - 4)))
    repeated_shingles = sum(count - 1 for count in shingles.values() if count > 1)
    return {
        "characters_excluding_spaces": len(re.sub(r"\s+", "", text)),
        "words": len(words),
        "unique_words": len(set(words)),
        "unique_percent": round(100 * len(set(words)) / len(words), 1) if words else 0,
        "stopwords": stop_count,
        "stopword_percent": round(100 * stop_count / len(words), 1) if words else 0,
        "average_sentence_words": round(len(words) / len(sentences), 1) if sentences else 0,
        "average_word_length": round(sum(len(w) for w in words) / len(words), 1) if words else 0,
        "repeated_5_word_sequences": repeated_shingles,
        "top_terms": [{"term": term, "count": count} for term, count in counts.most_common(15)],
    }


def detect_technologies(source: str, parser: AuditHTMLParser) -> list[str]:
    checks = {
        "WordPress": r"wp-content|wp-includes",
        "Shopify": r"cdn\.shopify\.com|Shopify\.theme|shopify-section",
        "React": r"data-reactroot|__REACT_DEVTOOLS_GLOBAL_HOOK__",
        "Next.js": r"__NEXT_DATA__|/_next/",
        "Vue": r"data-v-|__VUE__|/_nuxt/",
        "Google Tag Manager": r"googletagmanager\.com|GTM-[A-Z0-9]+",
        "Google Analytics": r"google-analytics\.com|gtag\(",
        "Plerdy": r"plerdy\.com|plerdy",
    }
    return [name for name, pattern in checks.items() if re.search(pattern, source, re.I)]


def analyze_page(
    url: str,
    source: str,
    parser: AuditHTMLParser,
    fetch: FetchResult,
    production: bool,
) -> tuple[dict[str, Any], list[Finding]]:
    findings: list[Finding] = []

    def add(rule: str, severity: str, message: str, evidence: str = "", recommendation: str = "") -> None:
        findings.append(Finding(rule, severity, safe_url(url), message, clean_text(evidence)[:500], recommendation))

    description = attr_content(parser.meta, "name", "description")
    robots = attr_content(parser.meta, "name", "robots")
    indexable = not bool(re.search(r"\b(noindex|none)\b", robots, re.I))
    viewport = attr_content(parser.meta, "name", "viewport")
    canonical_raw = rel_link(parser.links, "canonical")
    canonical = normalize_http_url(canonical_raw, url) if canonical_raw else ""
    h1s = [h for h in parser.headings if h["level"] == 1]
    og = {
        name: attr_content(parser.meta, "property", name)
        for name in ("og:title", "og:description", "og:url", "og:type", "og:image")
    }
    twitter = {
        name: attr_content(parser.meta, "name", name)
        for name in ("twitter:card", "twitter:title", "twitter:description", "twitter:image")
    }
    json_ld_types: list[str] = []
    invalid_json_ld = 0
    for block in parser.json_ld_blocks:
        if not block:
            continue
        try:
            data = json.loads(block)
            stack = data if isinstance(data, list) else [data]
            while stack:
                item = stack.pop()
                if isinstance(item, dict):
                    value = item.get("@type")
                    if isinstance(value, list):
                        json_ld_types.extend(str(x) for x in value)
                    elif value:
                        json_ld_types.append(str(value))
                    graph = item.get("@graph")
                    if isinstance(graph, list):
                        stack.extend(graph)
        except json.JSONDecodeError:
            invalid_json_ld += 1

    if fetch.status == 0:
        add("HTTP_FETCH_FAILED", "critical", "Page could not be fetched", fetch.error, "Fix DNS/server/network access.")
    elif fetch.status >= 500:
        add("HTTP_SERVER_ERROR", "critical", f"Page returned HTTP {fetch.status}", fetch.error, "Fix server error before release.")
    elif fetch.status >= 400:
        add("HTTP_CLIENT_ERROR", "high", f"Page returned HTTP {fetch.status}", fetch.error, "Restore, redirect, or remove incoming links.")
    if not parser.title:
        add("TITLE_MISSING", "high", "Page title is missing", "", "Add a unique descriptive title.")
    elif not 15 <= len(parser.title) <= 65:
        add("TITLE_LENGTH", "low", f"Title length is {len(parser.title)} characters", parser.title, "Review snippet clarity; do not optimize by length alone.")
    if not description:
        add("DESCRIPTION_MISSING", "medium", "Meta description is missing", "", "Add a unique human-readable description.")
    elif not 50 <= len(description) <= 170:
        add("DESCRIPTION_LENGTH", "low", f"Description length is {len(description)} characters", description, "Review search-snippet clarity.")
    if not canonical:
        add("CANONICAL_MISSING", "high", "Canonical link is missing", "", "Add one absolute canonical URL.")
    elif canonical != normalize_http_url(url):
        if is_local_or_file_url(url) and not is_local_or_file_url(canonical):
            add(
                "CANONICAL_LOCAL_ENVIRONMENT",
                "low",
                "Canonical points to production while scan runs locally",
                f"canonical={canonical}",
                "Expected for local/staging source; verify exact production URL after deployment.",
            )
        else:
            add("CANONICAL_MISMATCH", "medium", "Canonical differs from current URL", f"canonical={canonical}", "Confirm intentional consolidation or correct canonical.")
    if re.search(r"\b(noindex|none)\b", robots, re.I):
        add("ROBOTS_NOINDEX", "critical" if production else "medium", "Page has noindex", robots, "Remove only when page must be indexed.")
    if not h1s:
        add(
            "H1_MISSING",
            "high" if indexable else "low",
            "H1 is missing" if indexable else "Non-indexable page has no H1",
            "",
            "Add one clear page-level heading." if indexable else "No action needed for intentional redirect/utility page.",
        )
    elif len(h1s) > 1:
        add("H1_MULTIPLE", "medium", f"Page contains {len(h1s)} H1 headings", " | ".join(h["text"] for h in h1s), "Confirm one primary page heading.")
    levels = [h["level"] for h in parser.headings]
    skips = [(levels[i - 1], levels[i]) for i in range(1, len(levels)) if levels[i] > levels[i - 1] + 1]
    if skips:
        add("HEADING_LEVEL_SKIP", "low", "Heading hierarchy skips levels", str(skips[:10]), "Use levels to express hierarchy.")
    lang = parser.html_attrs.get("lang", "")
    if not lang:
        add("HTML_LANG_MISSING", "medium", "HTML lang attribute is missing", "", "Set the primary document language.")
    if not viewport:
        add("VIEWPORT_MISSING", "high", "Viewport meta is missing", "", "Add a mobile viewport declaration.")
    if parser.inline_styles:
        add("INLINE_STYLES", "low", f"{parser.inline_styles} inline style attributes found", "", "Move repeated styles to CSS where practical.")
    if parser.comments:
        add("HTML_COMMENTS", "low", f"{parser.comments} HTML comments found", "", "Review for stale notes or sensitive information.")
    duplicate_ids = [key for key, count in collections.Counter(parser.ids).items() if key and count > 1]
    if duplicate_ids:
        add("DUPLICATE_IDS", "medium", f"{len(duplicate_ids)} duplicate IDs found", ", ".join(duplicate_ids[:20]), "Make IDs unique.")
    missing_alt = [img for img in parser.images if "alt" not in img]
    if missing_alt:
        add("IMAGE_ALT_MISSING", "high", f"{len(missing_alt)} images lack alt attribute", ", ".join(i.get("src", "") for i in missing_alt[:10]), "Add meaningful alt or alt=\"\" for decorative images.")
    missing_dimensions = [img for img in parser.images if not img.get("width") or not img.get("height")]
    if missing_dimensions:
        add("IMAGE_DIMENSIONS_MISSING", "medium", f"{len(missing_dimensions)} images lack width/height", ", ".join(i.get("src", "") for i in missing_dimensions[:10]), "Declare intrinsic dimensions to reduce layout shifts.")
    large_nonresponsive = [
        img for img in parser.images
        if img.get("src") and not img.get("srcset") and not img.get("sizes")
        and not img.get("src", "").lower().endswith(".svg")
    ]
    if large_nonresponsive:
        add("IMAGE_RESPONSIVE_MISSING", "low", f"{len(large_nonresponsive)} raster images have no srcset/sizes", ", ".join(i.get("src", "") for i in large_nonresponsive[:10]), "Provide responsive variants where image display size varies.")
    hash_links = [link for link in parser.links if link.get("tag") == "a" and link.get("href", "") == "#"]
    if hash_links:
        add("HASH_ONLY_LINK", "medium", f"{len(hash_links)} links use href=\"#\"", "", "Use a button or real fragment target.")
    javascript_links = [link for link in parser.links if link.get("href", "").lower().startswith("javascript:")]
    if javascript_links:
        add("JAVASCRIPT_LINK", "medium", f"{len(javascript_links)} javascript: links found", "", "Use semantic buttons or URLs.")
    unsafe_blank = [
        link for link in parser.links
        if link.get("tag") == "a" and link.get("target", "").lower() == "_blank"
        and not {"noopener", "noreferrer"}.intersection(link.get("rel", "").lower().split())
    ]
    if unsafe_blank:
        add("BLANK_REL_MISSING", "medium", f"{len(unsafe_blank)} target=_blank links lack noopener/noreferrer", "", "Add rel=\"noopener noreferrer\".")
    if any(not value for value in og.values()):
        missing = [name for name, value in og.items() if not value]
        add("OPEN_GRAPH_INCOMPLETE", "medium", "Open Graph metadata is incomplete", ", ".join(missing), "Add complete share-preview metadata.")
    if not twitter["twitter:card"]:
        add("TWITTER_CARD_MISSING", "low", "X/Twitter card metadata is missing", "", "Add twitter:card and matching preview fields.")
    if invalid_json_ld:
        add("JSONLD_INVALID", "high", f"{invalid_json_ld} JSON-LD blocks contain invalid JSON", "", "Fix structured-data JSON.")
    mixed = re.findall(r"(?:src|href)=[\"'](http://[^\"']+)", source, re.I) if url.startswith("https://") else []
    if mixed:
        add("MIXED_CONTENT", "high", f"{len(mixed)} HTTP resources referenced from HTTPS page", ", ".join(safe_url(x) for x in mixed[:10]), "Use HTTPS resources.")
    label_fors = {label.get("for", "") for label in parser.labels if label.get("for")}
    unlabeled: list[str] = []
    for field in parser.inputs:
        if field.get("type", "").lower() in {"hidden", "submit", "button", "reset", "image"}:
            continue
        field_id = field.get("id", "")
        named = (
            field_id in label_fors
            or field.get("_wrapped_label") == "1"
            or bool(field.get("aria-label") or field.get("aria-labelledby"))
        )
        if not named:
            unlabeled.append(field.get("name") or field_id or field.get("tag", "field"))
    if unlabeled:
        add("FORM_LABEL_MISSING", "high", f"{len(unlabeled)} form fields lack programmatic labels", ", ".join(unlabeled[:20]), "Associate label/for or aria-labelledby.")
    nameless_buttons = [
        b for b in parser.buttons
        if not clean_text(b.get("text", "")) and not b.get("aria-label") and not b.get("title")
    ]
    if nameless_buttons:
        add("BUTTON_NAME_MISSING", "high", f"{len(nameless_buttons)} buttons lack accessible names", "", "Add visible text or aria-label.")
    metrics = text_metrics(parser.body_text)
    if metrics["words"] < 80:
        add("THIN_VISIBLE_TEXT", "low", f"Only {metrics['words']} visible words found", "", "Confirm page satisfies its search intent; utility pages may be short.")

    duplicate_pairs = collections.Counter(
        (normalize_http_url(link.get("href", ""), url), clean_text(link.get("text", "")).lower())
        for link in parser.links
        if link.get("tag") == "a" and link.get("href")
    )
    repeated_links = sum(1 for count in duplicate_pairs.values() if count > 1)
    page = {
        "url": safe_url(url),
        "status": fetch.status,
        "final_url": safe_url(fetch.final_url),
        "title": parser.title,
        "description": description,
        "canonical": canonical,
        "robots": robots,
        "lang": lang,
        "headings": [{"level": h["level"], "text": h["text"]} for h in parser.headings],
        "h1": [h["text"] for h in h1s],
        "links_count": sum(1 for x in parser.links if x.get("tag") == "a"),
        "duplicate_link_pairs": repeated_links,
        "images_count": len(parser.images),
        "scripts_count": len(parser.scripts),
        "stylesheets_count": len(parser.stylesheets),
        "forms_count": len(parser.forms),
        "json_ld_types": sorted(set(json_ld_types)),
        "open_graph": og,
        "twitter": twitter,
        "semantic_landmarks": dict(parser.semantic),
        "text_metrics": metrics,
        "technologies": detect_technologies(source, parser),
        "html_bytes": len(fetch.body),
        "ttfb_ms": fetch.ttfb_ms,
        "total_ms": fetch.total_ms,
        "response_headers": {
            key: fetch.headers.get(key, "")
            for key in (
                "content-type", "content-length", "content-encoding", "cache-control",
                "x-robots-tag", "content-security-policy", "strict-transport-security",
                "x-content-type-options", "referrer-policy", "permissions-policy",
                "x-frame-options",
            )
            if fetch.headers.get(key)
        },
        "findings": [finding.as_dict() for finding in findings],
    }
    return page, findings


def extract_internal_links(url: str, parser: AuditHTMLParser, root_origin: tuple[str, str]) -> tuple[set[str], set[str], list[dict[str, str]]]:
    internal: set[str] = set()
    external: set[str] = set()
    records: list[dict[str, str]] = []
    for item in parser.links:
        if item.get("tag") != "a":
            continue
        href = item.get("href", "").strip()
        if not href or href.startswith(("#", "mailto:", "tel:", "sms:", "viber:", "javascript:", "data:")):
            continue
        absolute = normalize_http_url(href, url)
        parsed = urllib.parse.urlsplit(absolute)
        if parsed.scheme not in {"http", "https"}:
            continue
        record = {
            "source": safe_url(url),
            "target": safe_url(absolute),
            "anchor": clean_text(item.get("text", "")),
            "rel": item.get("rel", ""),
        }
        records.append(record)
        if origin(absolute) == root_origin:
            internal.add(absolute)
        else:
            external.add(absolute)
    return internal, external, records


def parse_sitemap(xml_text: str, base_url: str) -> list[str]:
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return []
    urls: list[str] = []
    for element in root.iter():
        if element.tag.lower().endswith("loc") and element.text:
            value = normalize_http_url(element.text.strip(), base_url)
            if value.startswith(("http://", "https://")):
                urls.append(value)
    return urls


def security_findings(start_url: str, headers: dict[str, str]) -> list[Finding]:
    findings: list[Finding] = []

    def add(rule: str, severity: str, message: str, recommendation: str) -> None:
        findings.append(Finding(rule, severity, safe_url(start_url), message, "", recommendation))

    local = is_local_or_file_url(start_url)
    csp = headers.get("content-security-policy", "")
    if not csp:
        add("HEADER_CSP_MISSING", "low" if local else "medium", "Content-Security-Policy header is missing", "Local server may differ; add a tested production CSP.")
    if start_url.startswith("https://") and not headers.get("strict-transport-security"):
        add("HEADER_HSTS_MISSING", "medium", "HSTS header is missing on HTTPS", "Add HSTS after confirming all subdomains support HTTPS.")
    if headers.get("x-content-type-options", "").lower() != "nosniff":
        add("HEADER_NOSNIFF_MISSING", "low", "X-Content-Type-Options: nosniff is missing", "Add nosniff.")
    if not headers.get("referrer-policy"):
        add("HEADER_REFERRER_POLICY_MISSING", "low", "Referrer-Policy header is missing", "Set an explicit privacy-appropriate policy.")
    if not headers.get("permissions-policy"):
        add("HEADER_PERMISSIONS_POLICY_MISSING", "low", "Permissions-Policy header is missing", "Disable unneeded browser capabilities.")
    if not headers.get("x-frame-options") and "frame-ancestors" not in csp.lower():
        add("HEADER_FRAME_POLICY_MISSING", "low" if local else "medium", "No framing policy found", "Local server may differ; set CSP frame-ancestors or X-Frame-Options in production.")
    return findings


def robots_and_sitemaps(start_url: str, timeout: float, explicit_sitemap: str | None) -> dict[str, Any]:
    p = urllib.parse.urlsplit(start_url)
    root = urllib.parse.urlunsplit((p.scheme, p.netloc, "/", "", ""))
    robots_url = urllib.parse.urljoin(root, "robots.txt")
    robots = fetch_url(robots_url, timeout)
    robots_text = decode_body(robots) if robots.status == 200 else ""
    sitemap_urls = []
    for line in robots_text.splitlines():
        if line.lower().startswith("sitemap:"):
            sitemap_urls.append(line.split(":", 1)[1].strip())
    if explicit_sitemap:
        sitemap_urls.insert(0, normalize_http_url(explicit_sitemap, start_url))
    if not sitemap_urls:
        sitemap_urls.append(urllib.parse.urljoin(root, "sitemap.xml"))
    discovered: list[str] = []
    sitemap_status: list[dict[str, Any]] = []
    for value in dict.fromkeys(sitemap_urls):
        result = fetch_url(value, timeout)
        sitemap_status.append({"url": safe_url(value), "status": result.status, "error": result.error})
        if result.status == 200:
            discovered.extend(parse_sitemap(decode_body(result), value))
    disallow_all = False
    active_star = False
    for raw in robots_text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        key, _, value = line.partition(":")
        if key.lower().strip() == "user-agent":
            active_star = value.strip() == "*"
        elif key.lower().strip() == "disallow" and active_star and value.strip() == "/":
            disallow_all = True
    return {
        "robots": {
            "url": safe_url(robots_url),
            "status": robots.status,
            "disallow_all": disallow_all,
            "sitemaps": [safe_url(x) for x in sitemap_urls],
        },
        "sitemap_status": sitemap_status,
        "urls": list(dict.fromkeys(discovered)),
    }


def check_http_resource(url: str, timeout: float) -> dict[str, Any]:
    result = fetch_url(url, timeout, method="HEAD")
    if result.status in {0, 405, 501}:
        result = fetch_url(url, timeout, method="GET", max_bytes=1)
    length = result.headers.get("content-length", "")
    try:
        size = int(length)
    except (TypeError, ValueError):
        size = 0
    return {
        "url": safe_url(url),
        "status": result.status,
        "content_type": result.headers.get("content-type", ""),
        "bytes": size,
        "error": result.error,
    }


def crawl_http(args: argparse.Namespace) -> dict[str, Any]:
    start_url = normalize_http_url(args.target)
    p = urllib.parse.urlsplit(start_url)
    if p.username or p.password:
        raise ValueError("Credentials in target URL are forbidden")
    root_origin = origin(start_url)
    excludes = [re.compile(pattern, re.I) for pattern in (*DEFAULT_EXCLUDES, *args.exclude)]

    def excluded(value: str) -> bool:
        return any(pattern.search(value) for pattern in excludes)

    discovery = robots_and_sitemaps(start_url, args.timeout, args.sitemap)
    queue = collections.deque([start_url])
    for value in discovery["urls"]:
        if origin(value) == root_origin and is_html_candidate(value):
            queue.append(value)
    queued = set(queue)
    pages: list[dict[str, Any]] = []
    findings: list[Finding] = []
    link_records: list[dict[str, str]] = []
    external_links: set[str] = set()
    parsers: dict[str, AuditHTMLParser] = {}
    raw_status: dict[str, int] = {}

    while queue and len(pages) < args.max_pages:
        url = queue.popleft()
        if excluded(url):
            continue
        result = fetch_url(url, args.timeout)
        raw_status[url] = result.status
        ctype = result.headers.get("content-type", "")
        if result.status and "html" not in ctype.lower() and Path(urllib.parse.urlsplit(url).path).suffix.lower() not in {".html", ".htm", ".php", ""}:
            continue
        source = decode_body(result)
        parser = parse_html(source)
        parsers[url] = parser
        page, page_findings = analyze_page(url, source, parser, result, args.production)
        pages.append(page)
        findings.extend(page_findings)
        internal, external, records = extract_internal_links(url, parser, root_origin)
        link_records.extend(records)
        external_links.update(external)
        for target in sorted(internal):
            if (
                target not in queued
                and not excluded(target)
                and is_html_candidate(target)
                and len(queued) < args.max_pages * 20
            ):
                queue.append(target)
                queued.add(target)

    unique_internal_targets = sorted({
        record["target"] for record in link_records
        if origin(record["target"]) == root_origin
    })
    link_checks: list[dict[str, Any]] = []
    for target in unique_internal_targets[:args.max_links]:
        normalized = normalize_http_url(target)
        if normalized in raw_status:
            status = raw_status[normalized]
            link_checks.append({"url": safe_url(normalized), "status": status, "bytes": 0, "error": ""})
        else:
            link_checks.append(check_http_resource(normalized, args.timeout))
    broken = [item for item in link_checks if item["status"] == 0 or item["status"] >= 400]
    for item in broken:
        findings.append(Finding(
            "INTERNAL_LINK_BROKEN",
            "high",
            item["url"],
            f"Internal target returned HTTP {item['status'] or 'network error'}",
            item.get("error", ""),
            "Restore, redirect, or remove links to this target.",
        ))

    image_urls: set[str] = set()
    for page_url, parser in parsers.items():
        for image in parser.images:
            src = image.get("src", "").strip()
            if src:
                value = normalize_http_url(src, page_url)
                if origin(value) == root_origin:
                    image_urls.add(value)
    resource_checks: list[dict[str, Any]] = []
    for value in sorted(image_urls)[:args.max_resources]:
        item = check_http_resource(value, args.timeout)
        resource_checks.append(item)
        if item["status"] == 0 or item["status"] >= 400:
            findings.append(Finding(
                "IMAGE_RESOURCE_BROKEN", "high", item["url"],
                f"Image returned HTTP {item['status'] or 'network error'}",
                item.get("error", ""), "Fix the image URL or restore the file.",
            ))
        if item.get("bytes", 0) > 500_000:
            findings.append(Finding(
                "IMAGE_RESOURCE_LARGE", "medium", item["url"],
                f"Image response is {item['bytes']:,} bytes",
                "", "Provide appropriately compressed responsive variants.",
            ))

    if discovery["robots"]["disallow_all"]:
        findings.append(Finding(
            "ROBOTS_DISALLOW_ALL",
            "critical" if args.production else "medium",
            discovery["robots"]["url"],
            "robots.txt disallows all crawling",
            "User-agent: * / Disallow: /",
            "Keep on staging; remove for production only when indexing is intended.",
        ))
    if discovery["robots"]["status"] not in {200, 404}:
        findings.append(Finding(
            "ROBOTS_UNAVAILABLE", "medium", discovery["robots"]["url"],
            f"robots.txt returned HTTP {discovery['robots']['status']}",
            "", "Serve a stable robots.txt.",
        ))
    start_headers = pages[0].get("response_headers", {}) if pages else {}
    findings.extend(security_findings(start_url, start_headers))

    return finalize_audit(
        target=safe_url(start_url),
        mode="http",
        pages=pages,
        findings=findings,
        discovery=discovery,
        link_records=link_records,
        link_checks=link_checks,
        external_links=sorted(safe_url(x) for x in external_links),
        resource_checks=resource_checks,
        excluded_patterns=list(DEFAULT_EXCLUDES) + list(args.exclude),
        production=args.production,
    )


def local_link_target(root: Path, source: Path, href: str) -> Path | None:
    if not href or href.startswith(("#", "mailto:", "tel:", "javascript:", "data:", "//")):
        return None
    parsed = urllib.parse.urlsplit(href)
    if parsed.scheme in {"http", "https"}:
        return None
    path = urllib.parse.unquote(parsed.path)
    target = (root / path.lstrip("/")) if path.startswith("/") else (source.parent / path)
    try:
        resolved = target.resolve()
        resolved.relative_to(root.resolve())
    except (OSError, ValueError):
        return None
    if resolved.is_dir():
        resolved = resolved / "index.html"
    return resolved


def crawl_local(args: argparse.Namespace) -> dict[str, Any]:
    root = Path(args.target).expanduser().resolve()
    if root.is_file():
        html_files = [root]
        root = root.parent
    elif root.is_dir():
        html_files = sorted(root.rglob("*.html"))
        index = root / "index.html"
        if index in html_files:
            html_files.remove(index)
            html_files.insert(0, index)
    else:
        raise ValueError(f"Target does not exist: {root}")
    excludes = [re.compile(pattern, re.I) for pattern in (*DEFAULT_EXCLUDES, *args.exclude)]
    html_files = [p for p in html_files if not any(x.search(p.as_posix()) for x in excludes)][:args.max_pages]
    pages: list[dict[str, Any]] = []
    findings: list[Finding] = []
    link_records: list[dict[str, str]] = []
    link_checks: dict[str, dict[str, Any]] = {}
    resource_checks: dict[str, dict[str, Any]] = {}
    for path in html_files:
        body = path.read_bytes()
        fetch = FetchResult(
            requested_url=path.as_uri(),
            final_url=path.as_uri(),
            status=200,
            headers={"content-type": "text/html; charset=utf-8"},
            body=body,
            ttfb_ms=0,
            total_ms=0,
        )
        source = body.decode("utf-8", errors="replace")
        parser = parse_html(source)
        page, page_findings = analyze_page(path.as_uri(), source, parser, fetch, args.production)
        pages.append(page)
        findings.extend(page_findings)
        for item in parser.links:
            if item.get("tag") != "a":
                continue
            href = item.get("href", "").strip()
            target = local_link_target(root, path, href)
            if target is None:
                continue
            key = target.as_uri()
            exists = target.exists()
            link_records.append({
                "source": path.as_uri(),
                "target": key,
                "anchor": clean_text(item.get("text", "")),
                "rel": item.get("rel", ""),
            })
            link_checks[key] = {"url": key, "status": 200 if exists else 404, "bytes": target.stat().st_size if exists else 0, "error": ""}
        for image in parser.images:
            target = local_link_target(root, path, image.get("src", ""))
            if target is None:
                continue
            key = target.as_uri()
            exists = target.exists()
            size = target.stat().st_size if exists else 0
            resource_checks[key] = {"url": key, "status": 200 if exists else 404, "bytes": size, "error": ""}
    for item in link_checks.values():
        if item["status"] >= 400:
            findings.append(Finding(
                "INTERNAL_LINK_BROKEN", "high", item["url"],
                "Local internal target is missing", "", "Fix the link or restore the file.",
            ))
    for item in resource_checks.values():
        if item["status"] >= 400:
            findings.append(Finding(
                "IMAGE_RESOURCE_BROKEN", "high", item["url"],
                "Local image target is missing", "", "Fix the image URL or restore the file.",
            ))
        elif item["bytes"] > 500_000:
            findings.append(Finding(
                "IMAGE_RESOURCE_LARGE", "medium", item["url"],
                f"Image file is {item['bytes']:,} bytes", "", "Provide compressed responsive variants.",
            ))
    discovery = {
        "robots": {"url": "", "status": 0, "disallow_all": False, "sitemaps": []},
        "sitemap_status": [],
        "urls": [],
    }
    return finalize_audit(
        target=str(root),
        mode="local",
        pages=pages,
        findings=findings,
        discovery=discovery,
        link_records=link_records,
        link_checks=list(link_checks.values()),
        external_links=[],
        resource_checks=list(resource_checks.values()),
        excluded_patterns=list(DEFAULT_EXCLUDES) + list(args.exclude),
        production=args.production,
    )


def duplicate_findings(pages: list[dict[str, Any]]) -> list[Finding]:
    findings: list[Finding] = []
    for field, rule, label in (
        ("title", "DUPLICATE_TITLE", "title"),
        ("description", "DUPLICATE_DESCRIPTION", "meta description"),
        ("h1", "DUPLICATE_H1", "H1"),
    ):
        values: dict[str, list[str]] = collections.defaultdict(list)
        for page in pages:
            value = page.get(field)
            if isinstance(value, list):
                value = " | ".join(value)
            value = clean_text(str(value or "")).lower()
            if value:
                values[value].append(page["url"])
        for value, urls in values.items():
            if len(urls) > 1:
                findings.append(Finding(
                    rule, "medium", urls[0],
                    f"Duplicate {label} appears on {len(urls)} pages",
                    f"{value[:180]} | " + " | ".join(urls[:10]),
                    f"Make each indexable page's {label} specific to its intent.",
                ))
    return findings


def finalize_audit(
    *,
    target: str,
    mode: str,
    pages: list[dict[str, Any]],
    findings: list[Finding],
    discovery: dict[str, Any],
    link_records: list[dict[str, str]],
    link_checks: list[dict[str, Any]],
    external_links: list[str],
    resource_checks: list[dict[str, Any]],
    excluded_patterns: list[str],
    production: bool,
) -> dict[str, Any]:
    cross = duplicate_findings(pages)
    findings.extend(cross)
    for item in cross:
        for page in pages:
            if page["url"] == item.url:
                page["findings"].append(item.as_dict())
                break
    counts = collections.Counter(f.severity for f in findings)
    score = max(0, 100 - counts["critical"] * 20 - counts["high"] * 10 - counts["medium"] * 3 - counts["low"])
    if counts["critical"]:
        decision = "BLOCKED"
    elif counts["high"]:
        decision = "REVIEW-REQUIRED"
    else:
        decision = "PASS-STATIC"
    return {
        "schema": 1,
        "scanner": {"name": "site-audit-scanner", "version": VERSION},
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "target": target,
        "mode": mode,
        "production_mode": production,
        "decision": decision,
        "diagnostic_score": score,
        "summary": {
            "pages_scanned": len(pages),
            "findings": {severity: counts[severity] for severity in SEVERITIES},
            "internal_links_seen": len(link_records),
            "internal_targets_checked": len(link_checks),
            "broken_internal_targets": sum(1 for x in link_checks if x["status"] == 0 or x["status"] >= 400),
            "external_links_listed": len(external_links),
            "image_resources_checked": len(resource_checks),
            "broken_image_resources": sum(1 for x in resource_checks if x["status"] == 0 or x["status"] >= 400),
        },
        "discovery": discovery,
        "excluded_patterns": excluded_patterns,
        "pages": pages,
        "findings": [f.as_dict() for f in sorted(
            findings,
            key=lambda item: (SEVERITIES.index(item.severity), item.rule, item.url),
        )],
        "links": {
            "records": link_records,
            "checks": link_checks,
            "external": external_links,
        },
        "resources": resource_checks,
        "limitations": [
            "Static crawler does not execute JavaScript.",
            "Diagnostic score is not a Google ranking score.",
            "Fetch timing is not Core Web Vitals.",
            "E-E-A-T, AEO, UX and accessibility require manual/rendered validation.",
            "External links are listed but not fetched.",
        ],
    }


def markdown_report(audit: dict[str, Any]) -> str:
    s = audit["summary"]
    lines = [
        "# Website audit",
        "",
        f"- Target: `{audit['target']}`",
        f"- Generated: `{audit['generated_at']}`",
        f"- Mode: `{audit['mode']}`",
        f"- Decision: **{audit['decision']}**",
        f"- Diagnostic score: **{audit['diagnostic_score']}/100** (not a ranking score)",
        f"- Pages: **{s['pages_scanned']}**",
        f"- Findings: critical {s['findings']['critical']}, high {s['findings']['high']}, medium {s['findings']['medium']}, low {s['findings']['low']}",
        f"- Broken internal targets: **{s['broken_internal_targets']}**",
        f"- Broken image resources: **{s['broken_image_resources']}**",
        "",
        "## Priority findings",
        "",
        "| Severity | Rule | URL | Finding | Evidence |",
        "|---|---|---|---|---|",
    ]
    if not audit["findings"]:
        lines.append("| — | — | — | No static findings | — |")
    for item in audit["findings"]:
        lines.append(
            "| {severity} | `{rule}` | `{url}` | {message} | {evidence} |".format(
                severity=item["severity"],
                rule=item["rule"],
                url=item["url"].replace("|", "\\|"),
                message=item["message"].replace("|", "\\|"),
                evidence=(item["evidence"] or "—").replace("|", "\\|"),
            )
        )
    lines.extend(["", "## Pages", "", "| Status | URL | Title | H1 | Words | HTML | TTFB |", "|---:|---|---|---|---:|---:|---:|"])
    for page in audit["pages"]:
        lines.append(
            f"| {page['status']} | `{page['url']}` | {page['title'].replace('|', '\\|') or '—'} | "
            f"{(' / '.join(page['h1'])).replace('|', '\\|') or '—'} | {page['text_metrics']['words']} | "
            f"{page['html_bytes']:,} B | {page['ttfb_ms']} ms |"
        )
    lines.extend([
        "",
        "## Limits",
        "",
        *[f"- {item}" for item in audit["limitations"]],
        "",
        "Run rendered browser/mobile pass before release decision.",
        "",
    ])
    return "\n".join(lines)


def html_report(audit: dict[str, Any]) -> str:
    findings_rows = "".join(
        "<tr class=\"sev-{severity}\"><td>{severity}</td><td><code>{rule}</code></td>"
        "<td><code>{url}</code></td><td>{message}</td><td>{evidence}</td></tr>".format(
            **{k: html.escape(str(item.get(k, ""))) for k in ("severity", "rule", "url", "message", "evidence")}
        )
        for item in audit["findings"]
    ) or "<tr><td colspan=\"5\">No static findings</td></tr>"
    page_rows = "".join(
        "<tr><td>{status}</td><td><code>{url}</code></td><td>{title}</td><td>{h1}</td>"
        "<td>{words}</td><td>{size}</td><td>{ttfb} ms</td></tr>".format(
            status=page["status"],
            url=html.escape(page["url"]),
            title=html.escape(page["title"] or "—"),
            h1=html.escape(" / ".join(page["h1"]) or "—"),
            words=page["text_metrics"]["words"],
            size=f"{page['html_bytes']:,} B",
            ttfb=page["ttfb_ms"],
        )
        for page in audit["pages"]
    )
    counts = audit["summary"]["findings"]
    payload = html.escape(json.dumps(audit, ensure_ascii=False))
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Website audit — {html.escape(audit['target'])}</title>
<style>
:root{{--bg:#f7f7f4;--card:#fff;--text:#18211d;--muted:#627068;--line:#dfe5df;--red:#a52727;--orange:#a65d00;--blue:#245d7d}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--text);font:15px/1.5 system-ui,sans-serif}}
main{{max-width:1200px;margin:auto;padding:32px 20px}}h1{{font-size:clamp(28px,4vw,48px);margin:.2em 0}}h2{{margin-top:36px}}
.meta,.cards{{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:12px}}.card{{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:16px}}
.value{{font-size:28px;font-weight:750}}.muted{{color:var(--muted)}}table{{width:100%;border-collapse:collapse;background:var(--card);font-size:13px}}
th,td{{border:1px solid var(--line);padding:9px;vertical-align:top;text-align:left}}th{{position:sticky;top:0;background:#eef2ee}}code{{word-break:break-all}}
.sev-critical td:first-child,.sev-high td:first-child{{color:var(--red);font-weight:700}}.sev-medium td:first-child{{color:var(--orange);font-weight:700}}
.scroll{{overflow:auto;border-radius:12px;border:1px solid var(--line)}}details{{margin-top:24px}}
</style></head><body><main>
<p class="muted">site-audit-scanner {VERSION}</p>
<h1>Website audit</h1><p><code>{html.escape(audit['target'])}</code></p>
<div class="cards">
<div class="card"><div class="muted">Decision</div><div class="value">{audit['decision']}</div></div>
<div class="card"><div class="muted">Diagnostic score</div><div class="value">{audit['diagnostic_score']}/100</div><small>Not a ranking score</small></div>
<div class="card"><div class="muted">Pages</div><div class="value">{audit['summary']['pages_scanned']}</div></div>
<div class="card"><div class="muted">Critical / high</div><div class="value">{counts['critical']} / {counts['high']}</div></div>
</div>
<h2>Findings</h2><div class="scroll"><table><thead><tr><th>Severity</th><th>Rule</th><th>URL</th><th>Finding</th><th>Evidence</th></tr></thead><tbody>{findings_rows}</tbody></table></div>
<h2>Pages</h2><div class="scroll"><table><thead><tr><th>Status</th><th>URL</th><th>Title</th><th>H1</th><th>Words</th><th>HTML</th><th>TTFB</th></tr></thead><tbody>{page_rows}</tbody></table></div>
<h2>Limits</h2><ul>{''.join(f'<li>{html.escape(x)}</li>' for x in audit['limitations'])}</ul>
<details><summary>Embedded JSON</summary><pre id="json">{payload}</pre></details>
</main></body></html>"""


def write_reports(audit: dict[str, Any], output: Path) -> None:
    output.mkdir(parents=True, exist_ok=True)
    (output / "audit.json").write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (output / "summary.md").write_text(markdown_report(audit), encoding="utf-8")
    (output / "report.html").write_text(html_report(audit), encoding="utf-8")


def fail_threshold(audit: dict[str, Any], threshold: str) -> bool:
    if threshold == "none":
        return False
    limit = SEVERITIES.index(threshold)
    return any(SEVERITIES.index(item["severity"]) <= limit for item in audit["findings"])


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Read-only website SEO/UX/technical audit")
    parser.add_argument("target", help="HTTP(S) URL, HTML file, or local document root")
    parser.add_argument("--output", required=True, help="Directory for audit.json, summary.md and report.html")
    parser.add_argument("--max-pages", type=int, default=200)
    parser.add_argument("--max-links", type=int, default=500)
    parser.add_argument("--max-resources", type=int, default=300)
    parser.add_argument("--timeout", type=float, default=12)
    parser.add_argument("--sitemap", help="Explicit sitemap URL")
    parser.add_argument("--exclude", action="append", default=[], help="Regex path exclusion; repeatable")
    parser.add_argument("--production", action="store_true", help="Treat noindex/disallow-all as release blockers")
    parser.add_argument("--fail-on", choices=("none", *SEVERITIES), default="none")
    parser.add_argument("--version", action="version", version=VERSION)
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    if args.max_pages < 1 or args.max_links < 0 or args.max_resources < 0 or args.timeout <= 0:
        parser.error("numeric limits must be positive")
    try:
        if re.match(r"^https?://", args.target, re.I):
            audit = crawl_http(args)
        else:
            audit = crawl_local(args)
        output = Path(args.output).expanduser().resolve()
        write_reports(audit, output)
    except (ValueError, OSError, urllib.error.URLError) as exc:
        print(f"site-audit-scanner: ERROR: {exc}", file=sys.stderr)
        return 2
    summary = audit["summary"]
    print(
        f"site-audit-scanner: {audit['decision']} | pages={summary['pages_scanned']} | "
        f"critical={summary['findings']['critical']} high={summary['findings']['high']} "
        f"medium={summary['findings']['medium']} low={summary['findings']['low']}"
    )
    print(f"reports: {output / 'report.html'}")
    return 1 if fail_threshold(audit, args.fail_on) else 0


if __name__ == "__main__":
    raise SystemExit(main())
