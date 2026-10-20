"""Auditable, permissioned AI candidate workflow with bounded inference requests."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from hashlib import sha256
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException

from afondo.admin_security import require_admin
from afondo.ai_extraction import ExtractionError, MAX_INPUT_CHARS, active_provider, extract
from afondo.db import connection
from afondo.evidence_discovery import save_leads

router = APIRouter(prefix="/api/v1/admin", tags=["AI extraction"],
                   dependencies=[Depends(require_admin)])

MAX_DAILY_REQUESTS = 25
MIN_ARTICLE_INTERVAL_SECONDS = 3600


def clock() -> datetime:
    return datetime.now(timezone.utc)


def _reserve_run(article_id: str, provider: str, model: str) -> tuple[str, dict]:
    run_id = str(uuid4())
    with connection() as conn:
        # Single-writer reservation: concurrent HTTP workers must not bypass quotas.
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT id, title, body, language FROM articles WHERE id = ?", (article_id,)
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Article not found")
        article = dict(row)
        if len(article["body"]) > MAX_INPUT_CHARS:
            raise HTTPException(status_code=422, detail=(
                f"Article exceeds {MAX_INPUT_CHARS} characters; AI extraction not attempted"
            ))
        now = clock()
        since_day = (now - timedelta(hours=24)).isoformat()
        since_article = (now - timedelta(seconds=MIN_ARTICLE_INTERVAL_SECONDS)).isoformat()
        global_count = conn.execute(
            "SELECT COUNT(*) FROM ai_analysis_runs WHERE started_at >= ?", (since_day,)
        ).fetchone()[0]
        recent = conn.execute(
            "SELECT COUNT(*) FROM ai_analysis_runs WHERE article_id=? AND started_at >= ?",
            (article_id, since_article),
        ).fetchone()[0]
        if global_count >= MAX_DAILY_REQUESTS:
            raise HTTPException(status_code=429, detail="Daily AI request limit reached")
        if recent:
            raise HTTPException(status_code=429, detail="This article was analyzed recently")
        conn.execute(
            """INSERT INTO ai_analysis_runs
               (id, article_id, provider, model, prompt_version, status, started_at,
                input_sha256, input_chars)
               VALUES (?, ?, ?, ?, 'claim-extraction-v1', 'running', ?, ?, ?)""",
            (run_id, article_id, provider, model, now.isoformat(),
             sha256(article["body"].encode("utf-8")).hexdigest(),
             len(article["body"])),
        )
    return run_id, article


def _update_failure(run_id: str) -> None:
    with connection() as conn:
        conn.execute(
            "UPDATE ai_analysis_runs SET status='failed', finished_at=? WHERE id=?",
            (clock().isoformat(), run_id),
        )


def _complete(run_id: str, result: dict) -> None:
    with connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT article_id FROM ai_analysis_runs WHERE id=? AND status='running'",
            (run_id,),
        ).fetchone()
        if row is None:
            raise ExtractionError("AI run was not in running state")
        for item in result["candidates"]:
            candidate_id = str(uuid4())
            conn.execute(
                """INSERT INTO ai_candidates
                   (id, run_id, article_id, quote, normalized_claim, kind, start_offset,
                    end_offset, review_status)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending')""",
                (candidate_id, run_id, row["article_id"], item["quote"], item["claim"],
                 item["kind"], item["start_offset"], item["end_offset"]),
            )
            if item["kind"] == "factual":
                # Metadata leads are *never* accepted evidence; title overlap
                # only prepares a reading list for subsequent human fact-check.
                save_leads(conn, candidate_id, item["claim"])
        conn.execute(
            """UPDATE ai_analysis_runs
               SET status='completed', finished_at=?, input_tokens=?, output_tokens=?,
                   candidate_count=?, rejected_candidate_count=? WHERE id=?""",
            (clock().isoformat(), result["input_tokens"], result["output_tokens"],
             len(result["candidates"]), result["unanchored_or_duplicate"], run_id),
        )


def analysis_detail(article_id: str) -> dict:
    with connection() as conn:
        runs = [
            dict(row) for row in conn.execute(
                """SELECT id, provider, model, prompt_version, status, started_at,
                          finished_at, input_sha256, input_chars, input_tokens,
                          output_tokens, candidate_count, rejected_candidate_count
                   FROM ai_analysis_runs WHERE article_id=?
                   ORDER BY started_at DESC LIMIT 20""",
                (article_id,),
            ).fetchall()
        ]
        latest = runs[0] if runs else None
        items = []
        if latest:
            items = [
                dict(row) for row in conn.execute(
                    """SELECT id, run_id, article_id, quote, normalized_claim, kind,
                              start_offset, end_offset, review_status, claim_id
                       FROM ai_candidates WHERE run_id=? ORDER BY start_offset, id""",
                    (latest["id"],),
                ).fetchall()
            ]
            for item in items:
                item["leads"] = [
                    dict(lead) for lead in conn.execute(
                        """SELECT l.source_id, d.title, d.url, l.rank_score,
                                  l.shared_terms
                           FROM ai_evidence_leads l
                           JOIN discovered_items d ON d.id=l.discovered_item_id
                           WHERE l.candidate_id=? ORDER BY l.rank_score DESC LIMIT 8""",
                        (item["id"],),
                    ).fetchall()
                ]
    return {"article_id": article_id, "runs": runs, "candidates": items,
            "current_run_id": latest["id"] if latest else None}


@router.get("/article-queue")
def article_queue(limit: int = 40):
    if not 1 <= limit <= 100:
        raise HTTPException(status_code=422, detail="limit must be between 1 and 100")
    with connection() as conn:
        rows = conn.execute(
            """SELECT a.id, a.title, a.language, a.created_at, a.source_url,
                      length(a.body) AS text_chars,
                      (SELECT r.status FROM ai_analysis_runs r
                       WHERE r.article_id=a.id ORDER BY r.started_at DESC LIMIT 1)
                      AS ai_status
               FROM articles a ORDER BY a.created_at DESC LIMIT ?""",
            (limit,),
        ).fetchall()
    return {"items": [dict(row) for row in rows], "max_input_chars": MAX_INPUT_CHARS}


@router.get("/articles/{article_id}/ai")
def get_article_ai(article_id: str):
    with connection() as conn:
        exists = conn.execute("SELECT 1 FROM articles WHERE id=?", (article_id,)).fetchone()
        if not exists:
            raise HTTPException(status_code=404, detail="Article not found")
    return analysis_detail(article_id)


@router.post("/articles/{article_id}/ai-extract")
def ai_extract_article(article_id: str):
    try:
        provider = active_provider()
    except ExtractionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    run_id, article = _reserve_run(article_id, provider["provider"], provider["model"])
    try:
        result = extract(article, provider)
        _complete(run_id, result)
    except ExtractionError as exc:
        _update_failure(run_id)
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except Exception:
        _update_failure(run_id)
        # Suppress provider payloads, credentials and article text in unexpected errors.
        raise HTTPException(status_code=502, detail="AI extraction failed unexpectedly") from None
    return analysis_detail(article_id)


@router.post("/ai-candidates/{candidate_id}/decision")
def review_candidate(candidate_id: str, decision: str):
    if decision not in ("accept", "reject"):
        raise HTTPException(status_code=422, detail="Expected accept or reject")
    with connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        item = conn.execute(
            "SELECT * FROM ai_candidates WHERE id=?", (candidate_id,)
        ).fetchone()
        if not item:
            raise HTTPException(status_code=404, detail="AI candidate not found")
        if item["review_status"] != "pending":
            raise HTTPException(status_code=409, detail="Candidate already reviewed")
        claim_id = None
        if decision == "accept":
            if item["kind"] != "factual":
                raise HTTPException(
                    status_code=409, detail="Only factual claims may enter verification"
                )
            article = conn.execute(
                "SELECT body FROM articles WHERE id=?", (item["article_id"],)
            ).fetchone()
            if not article or article["body"][item["start_offset"]:item["end_offset"]] != item["quote"]:
                raise HTTPException(status_code=409, detail="Original article text changed")
            existing = conn.execute(
                "SELECT id FROM claims WHERE article_id=? AND text=? LIMIT 1",
                (item["article_id"], item["quote"]),
            ).fetchone()
            if existing:
                claim_id = existing["id"]
            else:
                claim_id = str(uuid4())
                position = conn.execute(
                    "SELECT COALESCE(MAX(position), -1) + 1 FROM claims WHERE article_id=?",
                    (item["article_id"],),
                ).fetchone()[0]
                conn.execute(
                    "INSERT INTO claims (id, article_id, position, text) VALUES (?, ?, ?, ?)",
                    (claim_id, item["article_id"], position, item["quote"]),
                )
        conn.execute(
            "UPDATE ai_candidates SET review_status=?, claim_id=? WHERE id=?",
            ("accepted" if decision == "accept" else "rejected", claim_id, candidate_id),
        )
    return {"candidate_id": candidate_id, "decision": decision,
            "claim_id": claim_id, "status": "reviewed",
            "note": "Acceptance does not verify the truth of a claim"}
