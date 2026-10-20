"""Editorial publication controls for prominent, qualitative news labels.

A model's speculation may not appear as 'sensationalistic' or 'out of context'.
Only a human-operated, documented approved review can activate those labels.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, HttpUrl

from afondo.admin_security import require_admin
from afondo.db import connection
from afondo.public_feed import TOPICS

router = APIRouter(prefix="/api/v1/admin/editorial",
                   tags=["Editorial review"], dependencies=[Depends(require_admin)])

Topic = Literal["attualita", "politica", "economia", "mondo", "tecnologia",
                "scienza", "salute", "ambiente", "sport", "cultura"]


class EditorialInput(BaseModel):
    topic: Topic | None = None
    featured: bool = False
    sensationalistic: bool = False
    out_of_context: bool = False
    note: str = Field(default="", max_length=1200)
    evidence_url: HttpUrl | None = None
    status: Literal["draft", "approved"] = "draft"


@router.get("")
def list_editorial_reviews(limit: int = Query(60, ge=1, le=100)):
    with connection() as conn:
        rows = conn.execute(
            """SELECT a.id, a.title, a.outlet, a.source_url, a.created_at,
                      e.topic, e.status, e.featured, e.sensationalistic,
                      e.out_of_context, e.note, e.evidence_url, e.updated_at
               FROM articles a LEFT JOIN editorial_reviews e ON a.id=e.article_id
               ORDER BY a.created_at DESC LIMIT ?""",
            (limit,),
        ).fetchall()
    return {"items": [dict(row) for row in rows], "topics": list(TOPICS)}


@router.put("/{article_id}")
def save_editorial_review(article_id: str, payload: EditorialInput):
    if payload.status == "approved" and (payload.sensationalistic or payload.out_of_context):
        # Qualitative, potentially harmful assertions demand a written explanation
        # plus a directly inspectable document (article/original evidence).
        if len(payload.note.strip()) < 40:
            raise HTTPException(status_code=422, detail="Reviewed warnings require a detailed note (40+ characters)")
        if not payload.evidence_url:
            raise HTTPException(status_code=422, detail="Reviewed warnings require an evidence URL")
    if payload.evidence_url:
        parts = urlsplit(str(payload.evidence_url))
        if parts.scheme != "https" or parts.username or parts.password or parts.port not in (None, 443):
            raise HTTPException(status_code=422, detail="Evidence must be a standard HTTPS link")
    with connection() as conn:
        found = conn.execute("SELECT 1 FROM articles WHERE id=?", (article_id,)).fetchone()
        if not found:
            raise HTTPException(status_code=404, detail="Article not found")
        now = datetime.now(timezone.utc).isoformat()
        conn.execute(
            """INSERT INTO editorial_reviews
               (article_id,topic,status,featured,sensationalistic,out_of_context,
                note,evidence_url,updated_at)
               VALUES (?,?,?,?,?,?,?,?,?)
               ON CONFLICT(article_id) DO UPDATE SET
                 topic=excluded.topic,status=excluded.status,featured=excluded.featured,
                 sensationalistic=excluded.sensationalistic,out_of_context=excluded.out_of_context,
                 note=excluded.note,evidence_url=excluded.evidence_url,
                 updated_at=excluded.updated_at""",
            (article_id, payload.topic, payload.status, int(payload.featured),
             int(payload.sensationalistic), int(payload.out_of_context),
             payload.note.strip(), str(payload.evidence_url) if payload.evidence_url else None, now),
        )
    return {"article_id": article_id, "status": payload.status,
            "visible_warning": payload.status == "approved"
            and (payload.sensationalistic or payload.out_of_context),
            "message": "Publishing a warning is a documented editorial decision, not AI-determined truth."}
