"""Source catalog and explicit rights-gated discovery configuration.

Registering a source NEVER authorizes fetching or processing its content.
Operator grants must be provisioned separately, with permission evidence.
"""
from __future__ import annotations

import json
import os
from datetime import date
from pathlib import Path
from urllib.parse import urlsplit

DEFAULT_CATALOG = Path(__file__).resolve().parents[2] / "config" / "source_candidates.json"
DEFAULT_GRANTS = Path(__file__).resolve().parents[2] / "config" / "source_grants.json"
USES = frozenset({"metadata_discovery"})


class SourceConfigError(ValueError):
    pass


def _load_json(path: Path) -> dict:
    with path.open(encoding="utf-8") as handle:
        result = json.load(handle)
    if not isinstance(result, dict):
        raise SourceConfigError("Expected a JSON object")
    return result


def source_catalog() -> dict:
    path = Path(os.getenv("AFONDO_SOURCE_CATALOG", str(DEFAULT_CATALOG)))
    catalog = _load_json(path)
    sources = catalog.get("sources")
    if not isinstance(sources, list) or len({s["id"] for s in sources}) != len(sources):
        raise SourceConfigError("Source catalog is missing or contains duplicate identifiers")
    return catalog


def source_grants() -> dict:
    """Missing grant file is a safe and supported state: no discovery."""
    path = Path(os.getenv("AFONDO_SOURCE_GRANTS", str(DEFAULT_GRANTS)))
    if not path.is_file():
        return {}
    contents = _load_json(path)
    grants = contents.get("sources", {})
    if not isinstance(grants, dict):
        raise SourceConfigError("Invalid grant object")
    return grants


def configured_sources() -> list[dict]:
    grants = source_grants()
    return [_configured(source, grants.get(source["id"])) for source in source_catalog()["sources"]]


def _https_url(value: object) -> bool:
    if not isinstance(value, str):
        return False
    parts = urlsplit(value)
    return bool(parts.scheme == "https" and parts.hostname and not parts.username
                and not parts.password and not parts.fragment)


def _configured(source: dict, grant: object) -> dict:
    mode = source["discovery"]["method"]
    feed_url = source["discovery"].get("url") if mode == "rss" else None
    adapter = "feed" if mode == "rss" else "unconfigured"
    if mode == "licensed_api":
        adapter = "partner_api"
    elif mode in ("rss_catalog", "site", "site_or_feed_to_confirm"):
        adapter = "feed_setup_required"
    valid_grant = False
    grant_reason = "permission_not_recorded"
    rights_checked_at = None
    if isinstance(grant, dict):
        rights_checked_at = grant.get("reviewed_on")
        conditions = [
            grant.get("permission_recorded") is True,
            "metadata_discovery" in grant.get("allowed_uses", []),
            isinstance(grant.get("permission_reference"), str)
            and len(grant["permission_reference"].strip()) >= 8,
            isinstance(grant.get("approved_by"), str)
            and bool(grant["approved_by"].strip()),
        ]
        expires = grant.get("expires_on")
        if expires:
            try:
                conditions.append(date.fromisoformat(expires) >= date.today())
            except (ValueError, TypeError):
                conditions.append(False)
        valid_grant = all(conditions)
        grant_reason = "permission_recorded" if valid_grant else "permission_incomplete_or_expired"
        # For sources that offer only a catalog, a verified feed/API endpoint
        # must be recorded explicitly by the operator.
        if grant.get("endpoint"):
            feed_url = grant["endpoint"]
            adapter = grant.get("adapter", "feed")
    if adapter not in ("feed", "json_api"):
        ready = False
        if valid_grant:
            grant_reason = "adapter_or_endpoint_not_configured"
    else:
        ready = valid_grant and _https_url(feed_url)
        if valid_grant and not ready:
            grant_reason = "invalid_https_endpoint"
    return {
        "id": source["id"],
        "name": source["name"],
        "type": source["type"],
        "regions": source["regions"],
        "languages": source["languages"],
        "site": source["site"],
        "priority": source["priority"],
        "discovery_method": mode,
        "adapter": adapter,
        "discovery_url": feed_url,
        "rights_status": source["rights"],
        "rights_reviewed_on": rights_checked_at,
        "permission_status": grant_reason,
        "enabled": ready,
        # Internal auth config only, never return this field from public API.
        "_grant": grant if isinstance(grant, dict) else {},
    }


def public_source(source: dict) -> dict:
    return {key: value for key, value in source.items() if not key.startswith("_")}


def get_source(source_id: str) -> dict | None:
    return next((s for s in configured_sources() if s["id"] == source_id), None)


def safe_source_url(source: dict) -> str:
    """Only accept HTTPS to the origin/domain approved in operator grant.

    No dynamic URL supplied by an API caller is ever fetched.
    """
    if not source["enabled"]:
        raise SourceConfigError("Source not approved for automated metadata discovery")
    url = source["discovery_url"]
    if not _https_url(url):
        raise SourceConfigError("HTTPS endpoint required")
    parts = urlsplit(url)
    if parts.port not in (None, 443):
        raise SourceConfigError("Only standard HTTPS port 443 is allowed")
    grant = source["_grant"]
    domain = grant.get("approved_host")
    if not domain or not isinstance(domain, str):
        raise SourceConfigError("Explicit approved_host is required")
    # A pinned single exact host (not a broad host-suffix rule).
    if parts.hostname != domain.strip().lower():
        raise SourceConfigError("Endpoint must match approved_host exactly")
    return url
