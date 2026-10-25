"""AFONDO Check v0.1 API. Explicitly no autonomous fact-checking or web scraping."""

from contextlib import asynccontextmanager
from datetime import datetime, timezone
import os
from pathlib import Path
import secrets
from uuid import uuid4

from fastapi import FastAPI, Header, HTTPException, Query, status
from fastapi.responses import FileResponse

from afondo.db import connection, initialize
from afondo.extract import extract_candidates
from afondo.schemas import ArticleCreate, EvidenceCreate, EvidenceReview
from afondo.scoring import score_article, score_claim
from afondo.source_api import router as source_router
from afondo.admin_api import router as admin_router
from afondo.ai_workflow import router as ai_workflow_router
from afondo.public_feed import router as public_feed_router
from afondo.editorial_api import router as editorial_router
from afondo.preanalysis import router as preanalysis_router
from afondo.history import router as history_router, admin_router as attribution_router
from afondo.context_workbench import router as context_router


def timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


@asynccontextmanager
async def lifespan(_: FastAPI):
    initialize()
    yield


app = FastAPI(
    title="AFONDO Check",
    version="0.1.0",
    description="Prototipo trasparente: estrazione candidata e verifica basata su prove revisionate.",
    lifespan=lifespan,
)


app.include_router(source_router)
app.include_router(admin_router)
app.include_router(ai_workflow_router)
app.include_router(public_feed_router)
app.include_router(editorial_router)
app.include_router(preanalysis_router)
app.include_router(history_router)
app.include_router(attribution_router)
app.include_router(context_router)


@app.get("/")
def homepage(article: str | None = None):
    if article:
        from fastapi.responses import RedirectResponse
        from urllib.parse import urlencode
        return RedirectResponse(url="/analyze?" + urlencode({"article": article}), status_code=307)
    return FileResponse(
        Path(__file__).resolve().parents[2] / "web" / "portal.html",
        media_type="text/html",
    )


@app.get("/portal.css")
def portal_css():
    return FileResponse(Path(__file__).resolve().parents[2] / "web" / "portal.css",
                        media_type="text/css")


@app.get("/portal.js")
def portal_js():
    return FileResponse(Path(__file__).resolve().parents[2] / "web" / "portal.js",
                        media_type="application/javascript")


@app.get("/history")
def history_page():
    return FileResponse(
        Path(__file__).resolve().parents[2] / "web" / "history.html",
        media_type="text/html",
    )


@app.get("/history.js")
def history_script():
    return FileResponse(
        Path(__file__).resolve().parents[2] / "web" / "history.js",
        media_type="application/javascript",
    )


@app.get("/analyze")
def analyze_page():
    return FileResponse(Path(__file__).resolve().parents[2] / "web" / "index.html",
                        media_type="text/html")


@app.get("/sources")
def sources_page():
    index = Path(__file__).resolve().parents[2] / "web" / "sources.html"
    return FileResponse(index, media_type="text/html")


@app.get("/news")
def discovery_page():
    page = Path(__file__).resolve().parents[2] / "web" / "discoveries.html"
    return FileResponse(page, media_type="text/html")


@app.get("/admin")
def admin_page():
    return FileResponse(
        Path(__file__).resolve().parents[2] / "web" / "admin.html",
        media_type="text/html",
        headers={"Cache-Control": "no-store", "Content-Security-Policy": "default-src 'none'; "
                 "style-src 'self' 'unsafe-inline'; script-src 'self'; "
                 "connect-src 'self'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'"},
    )


@app.get("/admin.js")
def admin_script():
    return FileResponse(
        Path(__file__).resolve().parents[2] / "web" / "admin.js",
        media_type="application/javascript",
        headers={"Cache-Control": "no-store"},
    )


@app.get("/health")
def health():
    return {"status": "ok", "service": "afondo-check", "version": "0.1.0"}


def _article(article_id: str) -> dict:
    with connection() as conn:
        article = conn.execute("SELECT * FROM articles WHERE id = ?", (article_id,)).fetchone()
        if article is None:
            raise HTTPException(status_code=404, detail="Article not found")
        claims = conn.execute(
            "SELECT * FROM claims WHERE article_id = ? ORDER BY position",
            (article_id,),
        ).fetchall()
        expanded = []
        for claim in claims:
            evidence = [
                dict(row) for row in conn.execute(
                    "SELECT * FROM evidence WHERE claim_id = ? ORDER BY created_at",
                    (claim["id"],),
                ).fetchall()
            ]
            expanded.append({
                **dict(claim),
                "evidence": evidence,
                "assessment": score_claim(evidence),
            })
    return {
        **dict(article),
        "extraction_method": "heuristic_v1_candidate_sentences",
        "claims": expanded,
        "assessment": score_article([claim["assessment"] for claim in expanded]),
    }


@app.post("/api/v1/articles", status_code=status.HTTP_201_CREATED)
def create_article(payload: ArticleCreate):
    article_id = str(uuid4())
    candidates = extract_candidates(payload.text)
    with connection() as conn:
        conn.execute(
            """INSERT INTO articles
               (id, title, body, source_url, language, author, outlet, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                article_id, payload.title, payload.text, str(payload.source_url)
                if payload.source_url else None,
                payload.language, payload.author, payload.outlet, timestamp(),
            ),
        )
        for position, text in enumerate(candidates):
            conn.execute(
                "INSERT INTO claims (id, article_id, position, text) VALUES (?, ?, ?, ?)",
                (str(uuid4()), article_id, position, text),
            )
    return _article(article_id)


@app.get("/api/v1/articles")
def list_articles(limit: int = Query(20, ge=1, le=100)):
    with connection() as conn:
        items = conn.execute(
            """SELECT id, title, source_url, language, author, outlet, created_at
               FROM articles ORDER BY created_at DESC LIMIT ?""",
            (limit,),
        ).fetchall()
    return {"items": [dict(item) for item in items]}


@app.get("/api/v1/articles/{article_id}")
def get_article(article_id: str):
    return _article(article_id)


@app.post("/api/v1/claims/{claim_id}/evidence", status_code=status.HTTP_201_CREATED)
def add_evidence(claim_id: str, payload: EvidenceCreate):
    with connection() as conn:
        claim = conn.execute("SELECT id, article_id FROM claims WHERE id = ?", (claim_id,)).fetchone()
        if claim is None:
            raise HTTPException(status_code=404, detail="Claim not found")
        evidence_id = str(uuid4())
        conn.execute(
            """INSERT INTO evidence
               (id, claim_id, url, stance, source_kind, source_group, note,
                review_status, created_at, reviewed_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', ?, NULL)""",
            (
                evidence_id, claim_id, str(payload.url), payload.stance,
                payload.source_kind, payload.source_group.strip(), payload.note,
                timestamp(),
            ),
        )
    return {
        "id": evidence_id,
        "claim_id": claim_id,
        "review_status": "pending",
        "article_id": claim["article_id"],
    }


@app.post("/api/v1/evidence/{evidence_id}/review")
def review_evidence(
    evidence_id: str,
    payload: EvidenceReview,
    x_review_token: str | None = Header(default=None),
):
    configured = os.getenv("AFONDO_REVIEW_TOKEN")
    if not configured:
        raise HTTPException(status_code=503, detail="Review endpoint is disabled")
    if not x_review_token or not secrets.compare_digest(x_review_token, configured):
        raise HTTPException(status_code=403, detail="Forbidden")
    with connection() as conn:
        result = conn.execute(
            "UPDATE evidence SET review_status = ?, reviewed_at = ? WHERE id = ?",
            (payload.decision, timestamp(), evidence_id),
        )
        if result.rowcount == 0:
            raise HTTPException(status_code=404, detail="Evidence not found")
    return {"id": evidence_id, "review_status": payload.decision}
