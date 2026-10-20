"""Conservative public history for verified outlet attribution and bylines.

No automated ratings of people. All results use published editorial records with
a verified source URL; author identity is scoped to a specific publisher/domain.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from hashlib import sha256
import re
from unicodedata import normalize
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from afondo.admin_security import require_admin
from afondo.db import connection

router = APIRouter(prefix="/api/v1/history", tags=["provenance and history"])
admin_router = APIRouter(
    prefix="/api/v1/admin", tags=["verified attribution"],
    dependencies=[Depends(require_admin)],
)


def norm(value: str) -> str:
    return " ".join(normalize("NFKC", value).casefold().split())


def attribution_key(outlet: str | None, url: str | None) -> tuple[str, str] | None:
    """Publisher identity only when both outlet and original HTTPS origin exist."""
    if not outlet or not url:
        return None
    try:
        parsed = urlsplit(url)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
            return None
        if parsed.port not in (None, 443):
            return None
    except ValueError:
        return None
    return norm(outlet), parsed.hostname.lower()


def _id(parts: tuple[str, ...]) -> str:
    return sha256("|".join(parts).encode("utf-8")).hexdigest()[:20]


def outlet_id(outlet: str, url: str) -> str | None:
    identity = attribution_key(outlet, url)
    return _id(("outlet", *identity)) if identity else None


def byline_id(author: str | None, outlet: str, url: str) -> str | None:
    identity = attribution_key(outlet, url)
    if not author or not norm(author) or not identity:
        return None
    if norm(author) in {"redazione", "staff", "editorial", "editorial staff", "agenzia"}:
        return None
    # Do NOT merge a common name across publishers: these are publication
    # bylines, not proven unique human identities.
    return _id(("byline", *identity, norm(author)))


class AttributionInput(BaseModel):
    outlet_confirmed: bool = False
    byline_confirmed: bool = False
    checked_by: str = Field(min_length=2, max_length=120)
    source_note: str = Field(min_length=20, max_length=800)


@admin_router.put("/articles/{article_id}/attribution")
def confirm_attribution(article_id: str, payload: AttributionInput):
    with connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT id, author, outlet, source_url FROM articles WHERE id=?", (article_id,)
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Article not found")
        if payload.outlet_confirmed and not attribution_key(row["outlet"], row["source_url"]):
            raise HTTPException(status_code=422, detail="HTTPS source URL and publisher name required")
        if payload.byline_confirmed and (
            not payload.outlet_confirmed
            or not byline_id(row["author"], row["outlet"] or "", row["source_url"] or "")
        ):
            raise HTTPException(
                status_code=422,
                detail="Author byline requires verified publisher, URL and valid author name",
            )
        conn.execute(
            """INSERT INTO verified_attributions
               (article_id,outlet_confirmed,byline_confirmed,checked_by,source_note,checked_at)
               VALUES (?,?,?,?,?,?)
               ON CONFLICT(article_id) DO UPDATE SET
                outlet_confirmed=excluded.outlet_confirmed,
                byline_confirmed=excluded.byline_confirmed,
                checked_by=excluded.checked_by,source_note=excluded.source_note,
                checked_at=excluded.checked_at""",
            (article_id, int(payload.outlet_confirmed), int(payload.byline_confirmed),
             payload.checked_by.strip(), payload.source_note.strip(),
             datetime.now(timezone.utc).isoformat()),
        )
    return {"article_id": article_id, "outlet_confirmed": payload.outlet_confirmed,
            "byline_confirmed": payload.byline_confirmed}


@admin_router.get("/attributions")
def list_attributions():
    with connection() as conn:
        rows = conn.execute(
            """SELECT a.id AS article_id, a.title, a.outlet, a.author, a.source_url,
                      COALESCE(v.outlet_confirmed,0) AS outlet_confirmed,
                      COALESCE(v.byline_confirmed,0) AS byline_confirmed,
                      v.checked_by, v.source_note, v.checked_at
               FROM articles a LEFT JOIN verified_attributions v
                ON v.article_id=a.id
               ORDER BY a.created_at DESC LIMIT 150"""
        ).fetchall()
    return {"items": [dict(row) for row in rows]}


def history_links(article: dict) -> dict:
    if not article.get("outlet_confirmed"):
        return {"outlet": None, "author": None}
    key = outlet_id(article["outlet"], article["source_url"])
    author = (byline_id(article["author"], article["outlet"], article["source_url"])
              if article.get("byline_confirmed") else None)
    return {"outlet": key, "author": author}


def _published_rows() -> list[dict]:
    # Source + name were independently checked by an operator; no scraping.
    with connection() as conn:
        rows = conn.execute(
            """SELECT a.id, a.title, a.author, a.outlet, a.source_url,
                      a.created_at, e.updated_at, e.note, e.evidence_url,
                      e.sensationalistic, e.out_of_context, e.topic,
                      v.outlet_confirmed, v.byline_confirmed
               FROM articles a
               JOIN editorial_reviews e ON e.article_id=a.id AND e.status='approved'
               JOIN verified_attributions v ON v.article_id=a.id
               WHERE v.outlet_confirmed=1 AND a.outlet IS NOT NULL
                     AND a.source_url IS NOT NULL
               ORDER BY e.updated_at DESC LIMIT 1000"""
        ).fetchall()
    return [dict(row) for row in rows]


def _identity_index() -> dict[str, dict]:
    index = {}
    for row in _published_rows():
        links = history_links(row)
        items = [
            ("outlet", links["outlet"], row["outlet"]),
            ("author", links["author"], row["author"]),
        ]
        for kind, slug, label in items:
            if not slug:
                continue
            entry = index.setdefault(
                kind + ":" + slug,
                {"id": slug, "type": kind, "name": label,
                 "outlet": row["outlet"], "articles": [], "origin": urlsplit(row["source_url"]).hostname},
            )
            entry["articles"].append(row)
    return index


def _summary(entry: dict) -> dict:
    rows = entry["articles"]
    flags = Counter()
    for row in rows:
        if row["sensationalistic"]:
            flags["sensationalistic"] += 1
        if row["out_of_context"]:
            flags["out_of_context"] += 1
    return {
        "article_count": len(rows),
        "articles_with_sensationalism_note": flags["sensationalistic"],
        "articles_with_context_note": flags["out_of_context"],
        "sample_status": "limited" if len(rows) < 10 else "descriptive_only",
        "rating": None,
        "disclaimer": (
            "Storico parziale dei soli articoli approvati e attribuiti da un revisore. "
            "Non è un voto né una misura rappresentativa dell'affidabilità di una persona "
            "o testata; gli omonimi su testate differenti restano separati."
        ),
    }


@router.get("")
def list_history(kind: str = Query("outlet", pattern="^(outlet|author)$"),
                 q: str = Query("", max_length=90)):
    needle = norm(q)
    items = []
    for entry in _identity_index().values():
        if entry["type"] != kind or (needle and needle not in norm(entry["name"])):
            continue
        items.append({
            "id": entry["id"], "name": entry["name"],
            "outlet": entry["outlet"], "type": kind, "origin": entry["origin"],
            "summary": _summary(entry),
        })
    items.sort(key=lambda item: (-item["summary"]["article_count"], norm(item["name"])))
    return {"items": items[:100], "total": len(items),
            "note": "Solo byline e testate con attribuzione verificata; nessun voto reputazionale."}


@router.get("/{kind}/{slug}")
def get_history(kind: str, slug: str):
    if kind not in ("outlet", "author") or not re.fullmatch(r"[0-9a-f]{20}", slug):
        raise HTTPException(status_code=404, detail="History profile not found")
    entry = _identity_index().get(kind + ":" + slug)
    if entry is None:
        raise HTTPException(status_code=404, detail="History profile not found")
    articles = entry["articles"][:100]
    with connection() as conn:
        events = {}
        for row in articles:
            reviewed = conn.execute(
                """SELECT event_kind, happened_at, sensationalistic, out_of_context,
                          note, evidence_url, change_reason
                   FROM editorial_review_events
                   WHERE article_id=? AND status='approved'
                   ORDER BY happened_at ASC, id ASC LIMIT 100""",
                (row["id"],),
            ).fetchall()
            events[row["id"]] = [dict(item) for item in reviewed]
    return {
        "id": entry["id"], "type": kind, "name": entry["name"],
        "outlet": entry["outlet"], "origin": entry["origin"],
        "summary": _summary(entry),
        "articles": [
            {"id": row["id"], "title": row["title"], "author": row["author"],
             "outlet": row["outlet"], "url": row["source_url"],
             "created_at": row["created_at"], "updated_at": row["updated_at"],
             "note": row["note"], "evidence_url": row["evidence_url"],
             "flags": {
                 "sensationalistic": bool(row["sensationalistic"]),
                 "out_of_context": bool(row["out_of_context"]),
             }, "revisions": events[row["id"]]}
            for row in articles
        ],
    }
