"""Opt-in, rights-gated metadata discovery for registered sources.

Only title, URL, published timestamp and source references are stored. Never fetch
articles, bypass paywalls, scrape arbitrary sites, or re-publish article bodies.
"""
from __future__ import annotations

from datetime import datetime, timezone
import ipaddress
import os
import socket
import urllib.error
import urllib.request
from urllib.parse import urlsplit

from afondo.db import connection
from afondo.feed_parser import parse_feed, parse_json_api
from afondo.source_registry import SourceConfigError, safe_source_url

MAX_RESPONSE = 1_500_000
MIN_SYNC_SECONDS = 900
USER_AGENT = "AFONDO-Discovery/0.1 (contact: configure-operator-contact; metadata-only)"


class SourceSyncError(RuntimeError):
    pass


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _validate_public_hostname(hostname: str) -> None:
    """Block private/loopback hosts and DNS responses, including literal addresses.

    This is defense-in-depth for operator-pinned feed endpoints, not a hardened
    public general-purpose HTTP proxy. In production pin resolved public IPs
    at the transport layer and enforce outbound firewall egress rules.
    """
    if hostname.lower() in ("localhost",) or hostname.lower().endswith((".local", ".internal")):
        raise SourceSyncError("Private host is not permitted")
    try:
        ips = [ipaddress.ip_address(hostname)]
    except ValueError:
        try:
            ips = [ipaddress.ip_address(record[4][0])
                   for record in socket.getaddrinfo(hostname, 443, type=socket.SOCK_STREAM)]
        except (OSError, ValueError) as exc:
            raise SourceSyncError("Could not resolve source host") from exc
    if not ips or any(not address.is_global for address in ips):
        raise SourceSyncError("Non-public feed address blocked")


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise SourceSyncError("HTTP redirect blocked: record the final approved HTTPS endpoint")


def _download(url: str, headers: dict[str, str]) -> tuple[bytes, dict[str, str], bool]:
    _validate_public_hostname(urlsplit(url).hostname or "")
    request = urllib.request.Request(url, headers=headers, method="GET")
    opener = urllib.request.build_opener(_NoRedirect)
    try:
        with opener.open(request, timeout=10) as response:
            if response.status == 304:
                return b"", {}, True
            if response.status != 200:
                raise SourceSyncError(f"Unexpected source HTTP status: {response.status}")
            length = response.headers.get("Content-Length")
            if length and int(length) > MAX_RESPONSE:
                raise SourceSyncError("Response exceeds allowed size")
            payload = response.read(MAX_RESPONSE + 1)
            if len(payload) > MAX_RESPONSE:
                raise SourceSyncError("Response exceeds allowed size")
            return payload, {
                "etag": response.headers.get("ETag") or "",
                "last_modified": response.headers.get("Last-Modified") or "",
            }, False
    except urllib.error.HTTPError as exc:
        if exc.code == 304:
            return b"", {}, True
        raise SourceSyncError(f"Source returned HTTP {exc.code}") from exc
    except (OSError, ValueError) as exc:
        raise SourceSyncError("Unable to fetch source safely") from exc


def _headers(source: dict, previous: dict | None) -> dict[str, str]:
    headers = {"User-Agent": USER_AGENT, "Accept": "application/rss+xml, application/atom+xml, application/xml, application/json"}
    if previous:
        if previous.get("etag"):
            headers["If-None-Match"] = previous["etag"]
        if previous.get("last_modified"):
            headers["If-Modified-Since"] = previous["last_modified"]
    if source["adapter"] == "json_api":
        grant = source["_grant"]
        env_name = grant.get("token_env")
        if env_name:
            if not isinstance(env_name, str) or not env_name.startswith("AFONDO_SOURCE_"):
                raise SourceConfigError("API secret must use AFONDO_SOURCE_ environment variable")
            token = os.getenv(env_name)
            if not token:
                raise SourceConfigError("Partner API secret missing")
            header = grant.get("token_header", "Authorization")
            if header not in ("Authorization", "X-API-Key"):
                raise SourceConfigError("Unsupported API authentication header")
            headers[header] = ("Bearer " + token) if header == "Authorization" else token
    return headers


def _state(source_id: str) -> dict | None:
    with connection() as conn:
        row = conn.execute("SELECT * FROM source_sync_state WHERE source_id = ?", (source_id,)).fetchone()
    return dict(row) if row is not None else None


def source_stats() -> dict[str, dict]:
    with connection() as conn:
        states = [dict(row) for row in conn.execute("SELECT * FROM source_sync_state").fetchall()]
        counts = conn.execute(
            "SELECT source_id, COUNT(*) AS total FROM discovered_items GROUP BY source_id"
        ).fetchall()
    result = {row["source_id"]: row for row in states}
    for row in counts:
        result.setdefault(row["source_id"], {})["items_count"] = row["total"]
    return result


def discovered_items(source_id: str | None = None, limit: int = 30) -> list[dict]:
    query = """SELECT id, source_id, title, url, published_at, discovered_at
               FROM discovered_items"""
    args: tuple = ()
    if source_id:
        query += " WHERE source_id = ?"
        args = (source_id,)
    query += " ORDER BY discovered_at DESC, id DESC LIMIT ?"
    with connection() as conn:
        rows = conn.execute(query, args + (limit,)).fetchall()
    return [dict(row) for row in rows]


def _write_status(source_id: str, result: str, count: int, headers: dict | None = None, error: str = "") -> None:
    with connection() as conn:
        prior = conn.execute(
            "SELECT etag, last_modified FROM source_sync_state WHERE source_id = ?", (source_id,)
        ).fetchone()
        old_etag = prior["etag"] if prior else ""
        old_modified = prior["last_modified"] if prior else ""
        conn.execute(
            """INSERT INTO source_sync_state
               (source_id, last_sync, status, items_seen, etag, last_modified, error)
               VALUES (?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(source_id) DO UPDATE SET
                 last_sync=excluded.last_sync, status=excluded.status,
                 items_seen=excluded.items_seen, etag=excluded.etag,
                 last_modified=excluded.last_modified, error=excluded.error""",
            (source_id, now(), result, count,
             (headers or {}).get("etag") or old_etag,
             (headers or {}).get("last_modified") or old_modified,
             error[:250]),
        )


def sync_source(source: dict, *, fetch=_download, force: bool = False) -> dict:
    """Explicit operator-triggered metadata sync after documented permission.

    Inject fetch for deterministic offline tests; NEVER takes caller-supplied URLs.
    """
    url = safe_source_url(source)
    previous = _state(source["id"])
    if previous and not force:
        try:
            last = datetime.fromisoformat(previous["last_sync"])
            if (datetime.now(timezone.utc) - last).total_seconds() < MIN_SYNC_SECONDS:
                raise SourceSyncError("Source cooldown active: wait at least 15 minutes")
        except (TypeError, ValueError):
            pass
    # An attempted sync is recorded before accessing the network to enforce cooldown.
    _write_status(source["id"], "running", 0)
    try:
        payload, response_headers, unmodified = fetch(url, _headers(source, previous))
        if unmodified:
            _write_status(source["id"], "not_modified", 0, response_headers)
            return {"source_id": source["id"], "status": "not_modified", "new_items": 0}
        if source["adapter"] == "feed":
            items = parse_feed(payload)
        elif source["adapter"] == "json_api":
            schema = source["_grant"].get("api_schema")
            if not isinstance(schema, dict):
                raise SourceConfigError("Partner API field mapping missing")
            items = parse_json_api(payload, schema)
        else:
            raise SourceConfigError("No implemented connector for this source")
        # Only permitted metadata. Idempotency is enforced per source and canonical URL.
        added = 0
        with connection() as conn:
            for item in items:
                cursor = conn.execute(
                    """INSERT OR IGNORE INTO discovered_items
                       (source_id, title, url, published_at, discovered_at, external_id)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (source["id"], item["title"], item["url"], item["published_at"],
                     now(), item["external_id"]),
                )
                added += cursor.rowcount
        _write_status(source["id"], "ok", len(items), response_headers)
        return {"source_id": source["id"], "status": "ok",
                "items_seen": len(items), "new_items": added}
    except Exception as exc:
        _write_status(source["id"], "error", 0, error=str(exc))
        if isinstance(exc, (SourceConfigError, SourceSyncError, ValueError)):
            raise
        raise SourceSyncError("Source synchronization failed") from exc
