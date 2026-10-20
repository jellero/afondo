"""Explicitly licensed, bounded pre-processing of locally held article texts.

Never downloads an article or uses feed metadata as AI input. The only
eligible articles are individually approved by an operator for external AI
processing. Intended for operator cron/systemd schedules, not a public API.
"""
from __future__ import annotations

import argparse
from datetime import date, datetime, timezone
import json

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from afondo.admin_security import require_admin
from afondo.db import connection, initialize
from afondo.ai_extraction import ExtractionError, MAX_INPUT_CHARS
from afondo import ai_workflow

router = APIRouter(prefix="/api/v1/admin", tags=["AI preparation"],
                   dependencies=[Depends(require_admin)])


class ProcessingGrant(BaseModel):
    allowed: bool = False
    basis: str = Field(default="", max_length=1000)
    checked_by: str = Field(default="", max_length=120)
    expires_on: date | None = None


def eligible_articles(limit: int = 10) -> list[dict]:
    """Only articles granted externally processed AI use, never RSS-only items."""
    today = date.today().isoformat()
    with connection() as conn:
        rows = conn.execute(
            """SELECT a.id, a.title, length(a.body) AS text_chars, a.created_at,
                      p.basis, p.checked_by, p.checked_at, p.expires_on
               FROM articles a
               JOIN article_processing_grants p ON p.article_id=a.id
               WHERE p.allowed=1 AND p.expires_on IS NULL OR 1=0"""
        ).fetchall() if False else conn.execute(
            """SELECT a.id, a.title, length(a.body) AS text_chars, a.created_at,
                      p.basis, p.checked_by, p.checked_at, p.expires_on
               FROM articles a
               JOIN article_processing_grants p ON p.article_id=a.id
               WHERE p.allowed=1
                 AND (p.expires_on IS NULL OR p.expires_on >= ?)
                 AND length(a.body) <= ?
                 AND NOT EXISTS (
                   SELECT 1 FROM ai_analysis_runs r WHERE r.article_id=a.id
                 )
               ORDER BY a.created_at ASC LIMIT ?""",
            (today, MAX_INPUT_CHARS, limit),
        ).fetchall()
    return [dict(row) for row in rows]


def processing_grants() -> list[dict]:
    with connection() as conn:
        rows = conn.execute(
            """SELECT a.id AS article_id, a.title, a.outlet, a.author,
                      length(a.body) AS text_chars,
                      COALESCE(p.allowed,0) AS allowed, p.basis, p.checked_by,
                      p.checked_at, p.expires_on,
                      (SELECT r.status FROM ai_analysis_runs r
                       WHERE r.article_id=a.id ORDER BY r.started_at DESC LIMIT 1)
                       AS ai_status
               FROM articles a LEFT JOIN article_processing_grants p ON p.article_id=a.id
               ORDER BY a.created_at DESC LIMIT 150"""
        ).fetchall()
    return [dict(row) for row in rows]


def process_once(*, limit: int = 5, dry_run: bool = True) -> dict:
    """One bounded batch, suitable for external scheduler.

    Costs can be incurred only with dry_run=False. Uses existing atomic
    reservations and 25/day and 1/hour quotas from ai_workflow.
    """
    if not 1 <= limit <= 20:
        raise ValueError("limit must be between 1 and 20")
    candidates = eligible_articles(limit)
    result = {"eligible": len(candidates), "processed": 0, "failed": 0,
              "skipped": 0, "dry_run": dry_run, "items": []}
    if dry_run:
        result["items"] = [{"article_id": item["id"], "status": "eligible"}
                           for item in candidates]
        return result
    if not candidates:
        return result
    try:
        entry = ai_workflow.active_provider()
    except ExtractionError as exc:
        return {**result, "error": str(exc)}
    for item in candidates:
        try:
            run_id, article = ai_workflow._reserve_run(
                item["id"], entry["provider"], entry["model"]
            )
        except HTTPException as exc:
            result["skipped"] += 1
            result["items"].append({"article_id": item["id"], "status": "skipped",
                                    "reason": exc.status_code})
            if exc.status_code == 429:
                break
            continue
        try:
            output = ai_workflow.extract(article, entry)
            ai_workflow._complete(run_id, output)
            result["processed"] += 1
            result["items"].append({
                "article_id": item["id"], "status": "candidates_pending_review",
                "candidate_count": len(output["candidates"]),
            })
        except Exception:
            ai_workflow._update_failure(run_id)
            result["failed"] += 1
            result["items"].append({"article_id": item["id"], "status": "failed"})
    return result


@router.get("/preanalysis")
def get_preanalysis():
    return {"items": processing_grants(), "eligible": len(eligible_articles(150)),
            "notice": "Only articles explicitly licensed for provider AI transfer are eligible."}


@router.put("/articles/{article_id}/processing")
def set_processing(article_id: str, payload: ProcessingGrant):
    if payload.allowed and (len(payload.basis.strip()) < 20 or not payload.checked_by.strip()):
        raise HTTPException(
            status_code=422, detail="AI processing requires documented rights (20+ chars) and reviewer"
        )
    if payload.allowed and payload.expires_on and payload.expires_on < date.today():
        raise HTTPException(status_code=422, detail="Permission has already expired")
    with connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        found = conn.execute("SELECT id FROM articles WHERE id=?", (article_id,)).fetchone()
        if not found:
            raise HTTPException(status_code=404, detail="Article not found")
        conn.execute(
            """INSERT INTO article_processing_grants
               (article_id,allowed,basis,checked_by,checked_at,expires_on)
               VALUES (?,?,?,?,?,?)
               ON CONFLICT(article_id) DO UPDATE SET
                 allowed=excluded.allowed,basis=excluded.basis,
                 checked_by=excluded.checked_by,checked_at=excluded.checked_at,
                 expires_on=excluded.expires_on""",
            (article_id, int(payload.allowed), payload.basis.strip(),
             payload.checked_by.strip(), datetime.now(timezone.utc).isoformat(),
             payload.expires_on.isoformat() if payload.expires_on else None),
        )
    return {"article_id": article_id, "allowed": payload.allowed,
            "eligible": article_id in {a["id"] for a in eligible_articles(150)}}


@router.post("/preanalysis/once")
def admin_process_once():
    """One admin-triggered batch; network and billing only for licensed input."""
    return process_once(limit=3, dry_run=False)


def main() -> None:
    parser = argparse.ArgumentParser(description="AFONDO licensed pre-analysis worker")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--once", action="store_true")
    parser.add_argument("--limit", type=int, default=5)
    args = parser.parse_args()
    initialize()
    print(json.dumps(process_once(limit=args.limit, dry_run=not args.once),
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
