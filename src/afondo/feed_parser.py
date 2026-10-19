"""Safe feed/JSON metadata parsing. No article body is downloaded or retained."""
from __future__ import annotations

from datetime import datetime
from email.utils import parsedate_to_datetime
import json
import xml.etree.ElementTree as ET
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode

MAX_ITEMS = 100
TRACKING_PREFIXES = ("utm_",)
TRACKING_KEYS = {"fbclid", "gclid", "mc_cid", "mc_eid"}


def canonical_url(value: str | None) -> str | None:
    if not value or not isinstance(value, str) or len(value) > 4096:
        return None
    url = value.strip()
    try:
        parts = urlsplit(url)
        if parts.scheme not in ("http", "https") or not parts.hostname:
            return None
        if parts.username or parts.password:
            return None
        port = parts.port
        if port and port not in (80, 443):
            return None
        host = parts.hostname.lower()
        host += f":{port}" if port and not (parts.scheme == "https" and port == 443) else ""
        params = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
                  if not k.lower().startswith(TRACKING_PREFIXES)
                  and k.lower() not in TRACKING_KEYS]
        return urlunsplit((parts.scheme.lower(), host, parts.path or "/", urlencode(params), ""))
    except ValueError:
        return None


def _tag_name(element: ET.Element) -> str:
    return element.tag.rsplit("}", 1)[-1].lower()


def _child(node: ET.Element, name: str) -> ET.Element | None:
    return next((item for item in node if _tag_name(item) == name), None)


def _text(node: ET.Element, key: str) -> str | None:
    found = _child(node, key)
    if found is None:
        return None
    value = "".join(found.itertext()).strip()
    return value or None


def _link(node: ET.Element) -> str | None:
    # RSS/RDF uses a link element body; Atom uses link href.
    for element in node:
        if _tag_name(element) != "link":
            continue
        href = element.get("href")
        rel = element.get("rel", "alternate")
        if href and rel == "alternate":
            return href
        if not href and element.text:
            return element.text.strip()
    return None


def _date(value: str | None) -> str | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.isoformat()
    except ValueError:
        pass
    try:
        return parsedate_to_datetime(value).isoformat()
    except (ValueError, TypeError, OverflowError):
        return None


def parse_feed(payload: bytes, limit: int = MAX_ITEMS) -> list[dict]:
    # Harden stdlib parser against entity declarations and needless oversized input.
    if len(payload) > 1_500_000 or b"<!doctype" in payload.lower() or b"<!entity" in payload.lower():
        raise ValueError("Feed too large or contains unsupported XML declarations")
    try:
        root = ET.fromstring(payload)
    except ET.ParseError as exc:
        raise ValueError("Invalid RSS/Atom/RDF XML") from exc
    if _tag_name(root) not in ("rss", "feed", "rdf"):
        raise ValueError("Not an RSS/Atom/RDF feed")
    # RSS 2 items under channel; RDF 1 items directly under rdf; Atom entries under feed.
    nodes = [node for node in root.iter() if _tag_name(node) in ("item", "entry")]
    result = []
    seen = set()
    for node in nodes:
        title = _text(node, "title")
        url = canonical_url(_link(node))
        if not title or not url or url in seen:
            continue
        seen.add(url)
        result.append({
            "title": " ".join(title.split())[:500],
            "url": url,
            "published_at": _date(_text(node, "pubDate") or _text(node, "published")
                                  or _text(node, "updated") or _text(node, "date")),
            "external_id": (_text(node, "guid") or _text(node, "id") or url)[:1000],
        })
        if len(result) >= min(limit, MAX_ITEMS):
            break
    return result


def _get_path(value: object, dotted_path: str) -> object:
    for key in dotted_path.split("."):
        if not isinstance(value, dict) or key not in value:
            return None
        value = value[key]
    return value


def parse_json_api(payload: bytes, schema: dict, limit: int = MAX_ITEMS) -> list[dict]:
    if len(payload) > 1_500_000:
        raise ValueError("API response too large")
    try:
        data = json.loads(payload)
    except (UnicodeDecodeError, ValueError) as exc:
        raise ValueError("Invalid JSON response") from exc
    items = _get_path(data, schema.get("items_path", "items"))
    if not isinstance(items, list):
        raise ValueError("Configured items_path did not return a list")
    result = []
    seen = set()
    for item in items[:min(MAX_ITEMS * 3, 300)]:
        if not isinstance(item, dict):
            continue
        title = _get_path(item, schema.get("title_field", "title"))
        url = canonical_url(_get_path(item, schema.get("url_field", "url")))
        if not isinstance(title, str) or not title.strip() or not url or url in seen:
            continue
        seen.add(url)
        result.append({
            "title": " ".join(title.split())[:500],
            "url": url,
            "published_at": _date(_get_path(item, schema.get("published_field", "published_at"))),
            "external_id": str(_get_path(item, schema.get("id_field", "id")) or url)[:1000],
        })
        if len(result) >= min(limit, MAX_ITEMS):
            break
    return result
