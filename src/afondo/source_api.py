"""Operator-gated source registry and metadata discovery endpoints."""
from __future__ import annotations

import os
import secrets

from fastapi import APIRouter, Header, HTTPException, Query, status

from afondo.source_ingestion import SourceSyncError, discovered_items, source_stats, sync_source
from afondo.source_registry import (
    SourceConfigError, configured_sources, get_source, public_source,
)

router = APIRouter(prefix="/api/v1", tags=["source discovery"])


@router.get("/sources")
def list_sources():
    stats = source_stats()
    return {
        "items": [
            {**public_source(source), "sync": stats.get(source["id"], {})}
            for source in configured_sources()
        ],
        "notes": "Registered != licensed. Sources without a complete grant cannot be scanned.",
    }


@router.get("/sources/{source_id}")
def source_detail(source_id: str):
    source = get_source(source_id)
    if not source:
        raise HTTPException(status_code=404, detail="Unknown source")
    return {**public_source(source), "sync": source_stats().get(source_id, {})}


@router.get("/discoveries")
def get_discoveries(source_id: str | None = Query(default=None), limit: int = Query(30, ge=1, le=100)):
    if source_id and not get_source(source_id):
        raise HTTPException(status_code=404, detail="Unknown source")
    return {"items": discovered_items(source_id=source_id, limit=limit)}


@router.post("/sources/{source_id}/sync")
def sync_source_endpoint(
    source_id: str, x_ingest_token: str | None = Header(default=None)
):
    token = os.getenv("AFONDO_INGEST_TOKEN")
    if not token:
        raise HTTPException(status_code=503, detail="Source ingestion is disabled")
    if not x_ingest_token or not secrets.compare_digest(x_ingest_token, token):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")
    source = get_source(source_id)
    if not source:
        raise HTTPException(status_code=404, detail="Unknown source")
    if not source["enabled"]:
        raise HTTPException(status_code=409, detail={
            "reason": source["permission_status"], "adapter": source["adapter"]
        })
    try:
        return sync_source(source)
    except SourceConfigError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except (SourceSyncError, ValueError) as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
