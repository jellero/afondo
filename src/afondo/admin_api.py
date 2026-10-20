"""Authenticated AFONDO administration APIs.

No key is ever returned. Connection tests send only an authenticated GET to
a fixed provider models endpoint (no article text, no inference).
"""
from __future__ import annotations

from datetime import date
import urllib.error
import urllib.request
from typing import Literal
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, HttpUrl, field_validator

from afondo.admin_security import decrypt_secret, encrypt_secret, require_admin
from afondo.admin_store import (
    admin_grants, ai_config, ai_configs, delete_ai, delete_source,
    save_ai, save_grant, source_overrides, upsert_source,
)
from afondo.source_registry import configured_sources, get_source, source_catalog
from afondo.source_ingestion import source_stats

router = APIRouter(prefix="/api/v1/admin", tags=["Administration"],
                   dependencies=[Depends(require_admin)])

PROVIDERS = {
    "openai": "https://api.openai.com/v1/models",
    "anthropic": "https://api.anthropic.com/v1/models",
    "gemini": "https://generativelanguage.googleapis.com/v1beta/models",
}


def _safe_https(value: str) -> bool:
    try:
        parsed = urlsplit(value)
        return (parsed.scheme == "https" and bool(parsed.hostname)
                and not parsed.username and not parsed.password
                and parsed.port in (None, 443) and not parsed.fragment)
    except ValueError:
        return False


class SourceInput(BaseModel):
    id: str = Field(min_length=2, max_length=70, pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    name: str = Field(min_length=2, max_length=200)
    type: Literal["newsroom", "news_agency", "primary_evidence", "factcheck_reference"]
    regions: list[str] = Field(min_length=1, max_length=12)
    languages: list[str] = Field(min_length=1, max_length=15)
    site: HttpUrl
    priority: str = Field(default="pilot", min_length=2, max_length=60)
    discovery_method: Literal[
        "rss", "rss_catalog", "site", "site_or_feed_to_confirm", "licensed_api"
    ] = "rss"
    feed_url: HttpUrl | None = None
    active: bool = False

    @field_validator("site", "feed_url")
    @classmethod
    def only_https(cls, value):
        if value is not None and not _safe_https(str(value)):
            raise ValueError("Use a standard public HTTPS URL without credentials")
        return value

    @field_validator("regions", "languages")
    @classmethod
    def normalize_list(cls, value: list[str]) -> list[str]:
        cleaned = [part.strip() for part in value]
        if any(not part or len(part) > 32 for part in cleaned):
            raise ValueError("Invalid or overlong list element")
        return cleaned


class GrantInput(BaseModel):
    permission_recorded: bool = False
    public_display_allowed: bool = False
    permission_reference: str = Field(default="", max_length=1500)
    approved_by: str = Field(default="", max_length=160)
    reviewed_on: date | None = None
    expires_on: date | None = None
    endpoint: HttpUrl | None = None
    adapter: Literal["feed", "json_api"] = "feed"
    api_schema: dict[str, str] | None = None
    token_env: str | None = Field(default=None, pattern=r"^AFONDO_SOURCE_[A-Z0-9_]+$")
    token_header: Literal["Authorization", "X-API-Key"] = "Authorization"

    @field_validator("endpoint")
    @classmethod
    def https_only(cls, value):
        if value is not None and not _safe_https(str(value)):
            raise ValueError("HTTPS port 443 required")
        return value


class AIInput(BaseModel):
    provider: Literal["openai", "anthropic", "gemini"]
    model: str = Field(min_length=2, max_length=120, pattern=r"^[a-zA-Z0-9._:/-]+$")
    api_key: str | None = Field(default=None, max_length=500)
    active: bool = True


def _definition(source: SourceInput) -> dict:
    return {
        "id": source.id, "name": source.name, "type": source.type,
        "regions": source.regions, "languages": source.languages,
        "site": str(source.site), "priority": source.priority,
        "discovery": {
            "method": source.discovery_method,
            "url": str(source.feed_url) if source.feed_url else None,
        },
        "rights": "review_required",
        "active": source.active,
    }


def _metadata(detail: dict) -> dict:
    return {
        "id": detail["id"], "name": detail["name"], "type": detail["type"],
        "regions": detail["regions"], "languages": detail["languages"],
        "site": detail["site"], "priority": detail["priority"],
        "discovery_method": detail["discovery_method"],
        "feed_url": detail["discovery_url"],
        "active": detail.get("active", True),
        "enabled": detail["enabled"], "permission_status": detail["permission_status"],
    }


@router.get("/status")
def admin_status():
    sources = configured_sources()
    return {
        "authenticated": True, "sources": len(sources),
        "discovery_enabled": sum(s["enabled"] for s in sources),
        "ai_providers": len(ai_configs()),
        "ai_engine": "not_connected_to_verification_pipeline",
    }


@router.get("/sources")
def list_admin_sources():
    grants = admin_grants()
    stats = source_stats()
    entries = []
    for source in configured_sources():
        row = _metadata(source)
        row["sync"] = stats.get(source["id"], {})
        grant = grants.get(source["id"], source["_grant"])
        # Never return credentials or token values.
        row["grant"] = {
            "permission_recorded": grant.get("permission_recorded", False),
            "public_display_allowed": "public_metadata_display" in grant.get("allowed_uses", []),
            "permission_reference": grant.get("permission_reference", ""),
            "approved_by": grant.get("approved_by", ""),
            "reviewed_on": grant.get("reviewed_on"),
            "expires_on": grant.get("expires_on"),
            "endpoint": grant.get("endpoint"),
            "adapter": grant.get("adapter", "feed"),
            "api_schema": grant.get("api_schema"),
            "token_env": grant.get("token_env"),
            "token_header": grant.get("token_header", "Authorization"),
        }
        entries.append(row)
    return {"items": entries}


@router.post("/sources", status_code=201)
def add_source(payload: SourceInput):
    if get_source(payload.id) is not None:
        raise HTTPException(status_code=409, detail="Source ID already exists")
    _, deleted = source_overrides()
    # IDs of bundled sources that have been soft-deleted may only be restored
    # via an explicit edit; never silently reuse them.
    originals = {s["id"] for s in source_catalog()["sources"]}
    if payload.id in originals or payload.id in deleted:
        raise HTTPException(status_code=409, detail="Source ID is reserved")
    upsert_source(_definition(payload), invalidate_grant=True)
    return {"id": payload.id, "status": "created", "enabled": False}


@router.put("/sources/{source_id}")
def edit_source(source_id: str, payload: SourceInput):
    current = get_source(source_id)
    if current is None:
        raise HTTPException(status_code=404, detail="Source not found")
    if payload.id != source_id:
        raise HTTPException(status_code=422, detail="Source ID cannot be changed")
    stored = next(
        entry for entry in source_catalog()["sources"] if entry["id"] == source_id
    )
    changed_connection = (
        stored["site"] != str(payload.site)
        or stored["discovery"]["method"] != payload.discovery_method
        or stored["discovery"].get("url") != (
            str(payload.feed_url) if payload.feed_url else None
        )
    )
    upsert_source(_definition(payload), invalidate_grant=changed_connection)
    return {"id": source_id, "status": "updated", "grant_reset": changed_connection}


@router.delete("/sources/{source_id}")
def remove_source(source_id: str):
    if not get_source(source_id):
        raise HTTPException(status_code=404, detail="Source not found")
    delete_source(source_id)
    return {"id": source_id, "status": "archived"}


@router.put("/sources/{source_id}/grant")
def upsert_grant(source_id: str, payload: GrantInput):
    source = get_source(source_id)
    if not source:
        raise HTTPException(status_code=404, detail="Source not found")
    if payload.permission_recorded:
        if not payload.reviewed_on or not payload.approved_by.strip():
            raise HTTPException(status_code=422, detail="Reviewer and review date required")
        if len(payload.permission_reference.strip()) < 8:
            raise HTTPException(status_code=422, detail="Documented permission reference required")
        if payload.expires_on and payload.expires_on < date.today():
            raise HTTPException(status_code=422, detail="Permission expired")
    endpoint = str(payload.endpoint) if payload.endpoint else source["discovery_url"]
    if payload.permission_recorded and not endpoint:
        raise HTTPException(status_code=422, detail="Exact API/RSS endpoint required")
    host = urlsplit(endpoint).hostname if endpoint else None
    grant = {
        "permission_recorded": payload.permission_recorded,
        "allowed_uses": (
            ["metadata_discovery"]
            + (["public_metadata_display"] if payload.public_display_allowed else [])
            if payload.permission_recorded else []
        ),
        "permission_reference": payload.permission_reference.strip(),
        "approved_by": payload.approved_by.strip(),
        "reviewed_on": str(payload.reviewed_on) if payload.reviewed_on else None,
        "expires_on": str(payload.expires_on) if payload.expires_on else None,
        "approved_host": host,
        "endpoint": str(payload.endpoint) if payload.endpoint else None,
        "adapter": payload.adapter,
    }
    if payload.api_schema:
        grant["api_schema"] = payload.api_schema
    if payload.token_env:
        grant["token_env"] = payload.token_env
        grant["token_header"] = payload.token_header
    if payload.adapter == "json_api" and not payload.api_schema and payload.permission_recorded:
        raise HTTPException(status_code=422, detail="JSON API schema required")
    save_grant(source_id, grant)
    refreshed = get_source(source_id)
    return {
        "id": source_id, "enabled": refreshed["enabled"],
        "permission_status": refreshed["permission_status"],
    }


def _public_ai(entry: dict) -> dict:
    return {"provider": entry["provider"], "model": entry["model"],
            "active": bool(entry["active"]), "has_key": bool(entry["key_ciphertext"]),
            "updated_at": entry["updated_at"]}


@router.get("/ai")
def get_ai_settings():
    return {"items": [_public_ai(entry) for entry in ai_configs()],
            "available_providers": list(PROVIDERS),
            "engine_status": "not_connected_to_verification_pipeline"}


@router.put("/ai")
def put_ai_settings(payload: AIInput):
    encrypted = encrypt_secret(payload.api_key.strip()) if payload.api_key and payload.api_key.strip() else None
    try:
        save_ai(payload.provider, payload.model, encrypted, payload.active)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _public_ai(ai_config(payload.provider))


@router.delete("/ai/{provider}")
def remove_ai_settings(provider: Literal["openai", "anthropic", "gemini"]):
    if not delete_ai(provider):
        raise HTTPException(status_code=404, detail="Provider not configured")
    return {"provider": provider, "status": "deleted"}


@router.post("/ai/{provider}/test")
def test_ai_connection(provider: Literal["openai", "anthropic", "gemini"]):
    row = ai_config(provider)
    if not row or not row["key_ciphertext"]:
        raise HTTPException(status_code=404, detail="Provider has no stored key")
    secret = decrypt_secret(row["key_ciphertext"])
    headers = {"Accept": "application/json"}
    if provider == "openai":
        headers["Authorization"] = f"Bearer {secret}"
    elif provider == "anthropic":
        headers["x-api-key"] = secret
        headers["anthropic-version"] = "2023-06-01"
    else:
        headers["x-goog-api-key"] = secret
    req = urllib.request.Request(PROVIDERS[provider], headers=headers, method="GET")
    # HTTPS fixed endpoints, no user-configured URL and no redirects to carry secrets.
    from afondo.source_ingestion import _NoRedirect, SourceSyncError
    opener = urllib.request.build_opener(_NoRedirect)
    try:
        with opener.open(req, timeout=8) as response:
            response.read(1000)
            return {"provider": provider, "connected": response.status == 200,
                    "note": "Provider credentials accepted by models endpoint; no AI analysis executed"}
    except urllib.error.HTTPError as exc:
        return {"provider": provider, "connected": False, "http_status": exc.code}
    except (OSError, ValueError, SourceSyncError) as exc:
        # Avoid leaking keys/URLs from exception messages.
        raise HTTPException(status_code=502, detail="Provider connection failed") from exc
