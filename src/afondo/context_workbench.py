"""Document-grounded context workbench for AFONDO administrators.

Documents are submitted as short human-supplied excerpts with canonical source
URLs and permission records. They are never downloaded by this service.
After independent review, locally stored excerpts are matched against factual
AI candidates. Numeric/temporal signals are suggestions, NOT verdicts.

No context match is visible in the public feed or influences scoring unless a
separate evidence record is created and independently accepted by a reviewer.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
import re
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, HttpUrl

from afondo.admin_security import require_admin
from afondo.context_checks import context_signals
from afondo.db import connection

router = APIRouter(
    prefix="/api/v1/admin", tags=["Evidence workbench"],
    dependencies=[Depends(require_admin)],
)

STOP = frozenset((
    "della dello degli delle nella nelle sulla sulle hanno questo questa "
    "quello anche stato stati dalla dalla sono essere secondo quanto "
    "prima dopo quali quale molto ancora della della sopra sotto "
    "the with from this that those these their about where which "
    "were been have reported reports there according said says"
).split())


class DocumentInput(BaseModel):
    title: str = Field(min_length=12, max_length=300)
    url: HttpUrl
    publisher: str = Field(min_length=3, max_length=160)
    source_group: str = Field(min_length=3, max_length=160)
    source_kind: str = Field(pattern="^(primary|secondary)$")
    excerpt: str = Field(min_length=40, max_length=4500)
    locator: str = Field(min_length=3, max_length=240)
    permission_reference: str = Field(min_length=20, max_length=800)
    recorded_by: str = Field(min_length=2, max_length=120)
    publication_date: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")


class ReviewInput(BaseModel):
    decision: str = Field(pattern="^(approve|reject|retire)$")
    checked_by: str = Field(min_length=2, max_length=120)
    review_note: str = Field(min_length=25, max_length=1000)


class MatchDecision(BaseModel):
    decision: str = Field(pattern="^(relevant|irrelevant)$")
    reviewed_by: str = Field(min_length=2, max_length=120)
    review_note: str = Field(min_length=20, max_length=1000)


class EvidenceProposal(BaseModel):
    stance: str = Field(pattern="^(supports|refutes|unclear)$")
    reason: str = Field(min_length=30, max_length=1000)


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def terms(value: str) -> set[str]:
    return {word for word in re.findall(r"[^\W\d_]{4,}", value.casefold())
            if word not in STOP and not word.isdecimal()}


def match_candidate(candidate: dict, document: dict) -> dict | None:
    """Lexical retrieval; low-rank similarities never imply factual support."""
    claim = candidate["normalized_claim"]
    search = terms(claim) | terms(candidate["quote"])
    excerpt = terms(document["excerpt"])
    if len(search) < 3 or not excerpt:
        return None
    overlap = search & excerpt
    fraction = len(overlap) / len(search)
    if len(overlap) < 3 or fraction < 0.35:
        return None
    return {
        "overlap_terms": sorted(overlap)[:30],
        "match_fraction": round(fraction, 4),
        "signals": context_signals(candidate["quote"], document["excerpt"]),
    }


def _suggest(conn, candidate: dict, document: dict) -> bool:
    comparison = match_candidate(candidate, document)
    if comparison is None:
        return False
    conn.execute(
        """INSERT OR IGNORE INTO document_claim_matches
           (id, candidate_id, document_id, match_fraction, overlap_terms,
            signals_json, review_status, created_at)
           VALUES (?,?,?,?,?,?,'pending',?)""",
        (str(uuid4()), candidate["id"], document["id"],
         comparison["match_fraction"], json.dumps(comparison["overlap_terms"]),
         json.dumps(comparison["signals"], ensure_ascii=False), now()),
    )
    return True


def scan_for_document(conn, document_id: str) -> int:
    doc = conn.execute(
        "SELECT * FROM evidence_documents WHERE id=? AND status='approved'",
        (document_id,),
    ).fetchone()
    if not doc:
        return 0
    candidates = conn.execute(
        """SELECT c.id,c.quote,c.normalized_claim FROM ai_candidates c
           WHERE c.kind='factual' ORDER BY c.rowid DESC LIMIT 500"""
    ).fetchall()
    return sum(bool(_suggest(conn, dict(item), dict(doc))) for item in candidates)


def scan_for_run(conn, run_id: str) -> int:
    docs = conn.execute(
        """SELECT * FROM evidence_documents WHERE status='approved'
           ORDER BY created_at DESC LIMIT 200"""
    ).fetchall()
    candidates = conn.execute(
        "SELECT id,quote,normalized_claim FROM ai_candidates WHERE kind='factual' AND run_id=?",
        (run_id,),
    ).fetchall()
    return sum(
        bool(_suggest(conn, dict(c), dict(d)))
        for c in candidates for d in docs
    )


@router.post("/documents", status_code=201)
def submit_document(payload: DocumentInput):
    from datetime import date
    from urllib.parse import urlsplit
    uri = urlsplit(str(payload.url))
    if (uri.scheme != "https" or uri.username or uri.password
            or uri.port not in (None, 443)):
        raise HTTPException(status_code=422, detail="Document needs ordinary HTTPS origin")
    if payload.publication_date:
        try:
            date.fromisoformat(payload.publication_date)
        except ValueError:
            raise HTTPException(status_code=422, detail="Invalid publication date") from None
    document_id = str(uuid4())
    with connection() as conn:
        conn.execute(
            """INSERT INTO evidence_documents
               (id,title,url,publisher,source_group,source_kind,excerpt,locator,
                permission_reference,recorded_by,publication_date,status,created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,'submitted',?)""",
            (document_id,payload.title.strip(),str(payload.url),
             payload.publisher.strip(),payload.source_group.strip(),
             payload.source_kind,payload.excerpt.strip(),payload.locator.strip(),
             payload.permission_reference.strip(),payload.recorded_by.strip(),
             payload.publication_date,now()),
        )
    return {"id":document_id,"status":"submitted",
            "notice":"Document remains unavailable for comparisons until human review"}


@router.get("/documents")
def documents(limit: int = Query(100,ge=1,le=200)):
    with connection() as conn:
        rows = conn.execute(
            """SELECT id,title,url,publisher,source_group,source_kind,
                      excerpt,locator,publication_date,status,created_at,
                      reviewed_at,review_note,permission_reference,recorded_by
               FROM evidence_documents ORDER BY created_at DESC LIMIT ?""",
            (limit,),
        ).fetchall()
    return {"items":[dict(row) for row in rows]}


@router.post("/documents/{document_id}/review")
def review_document(document_id: str, payload: ReviewInput):
    status = {"approve":"approved","reject":"rejected","retire":"retired"}[payload.decision]
    with connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        doc = conn.execute(
            "SELECT status FROM evidence_documents WHERE id=?", (document_id,),
        ).fetchone()
        if not doc:
            raise HTTPException(status_code=404,detail="Document not found")
        if (status == "retired" and doc["status"] != "approved") or (
            status in ("approved","rejected") and doc["status"] != "submitted"
        ):
            raise HTTPException(status_code=409,detail="Document already reviewed or retired")
        conn.execute(
            """UPDATE evidence_documents SET status=?,reviewed_at=?,
               reviewed_by=?,review_note=? WHERE id=?""",
            (status,now(),payload.checked_by.strip(),payload.review_note.strip(),document_id),
        )
        matches = scan_for_document(conn, document_id) if status=="approved" else 0
    return {"id":document_id,"status":status,"possible_matches":matches,
            "notice":"Approval records human inspection, not the truth of any claim"}


@router.get("/context-queue")
def context_queue(limit: int = Query(80,ge=1,le=200)):
    with connection() as conn:
        rows = conn.execute(
            """SELECT m.id, m.candidate_id, m.review_status,
                     m.match_fraction,m.overlap_terms,m.signals_json,
                     m.reviewer_note,m.created_at,
                     c.article_id,c.quote,c.normalized_claim,c.claim_id,
                     d.id AS document_id,d.title,d.url,d.publisher,
                     d.locator,d.excerpt,d.source_kind,d.source_group
               FROM document_claim_matches m
               JOIN ai_candidates c ON c.id=m.candidate_id
               JOIN evidence_documents d ON d.id=m.document_id AND d.status='approved'
               ORDER BY m.created_at DESC LIMIT ?""",
            (limit,),
        ).fetchall()
    return {"items":[{
        **{k:v for k,v in dict(row).items() if k not in ("overlap_terms","signals_json")},
        "overlap_terms":json.loads(row["overlap_terms"]),
        "signals":json.loads(row["signals_json"]),
    } for row in rows],"notice":"Only matches to approved excerpts; no public verdict"}


@router.post("/context-matches/{match_id}/decision")
def decide_match(match_id: str,payload: MatchDecision):
    with connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            """SELECT m.review_status FROM document_claim_matches m
               JOIN evidence_documents d ON d.id=m.document_id
               WHERE m.id=? AND d.status='approved'""",
            (match_id,),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404,detail="No current approved document match")
        if row["review_status"] != "pending":
            raise HTTPException(status_code=409,detail="Already reviewed")
        conn.execute(
            """UPDATE document_claim_matches
               SET review_status=?,reviewer_note=?,reviewed_by=?,reviewed_at=?
               WHERE id=?""",
            (payload.decision,payload.review_note.strip(),
             payload.reviewed_by.strip(),now(),match_id),
        )
    return {"id":match_id,"review_status":payload.decision}


@router.post("/context-matches/{match_id}/evidence-proposal")
def promote_to_pending_evidence(match_id: str, payload: EvidenceProposal):
    """Operator creates *pending* proof, never an accepted factual stance."""
    with connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            """SELECT m.review_status,c.claim_id,d.url,d.source_kind,
                      d.source_group,d.locator,d.excerpt,d.id AS document_id
               FROM document_claim_matches m
               JOIN ai_candidates c ON c.id=m.candidate_id
               JOIN evidence_documents d ON d.id=m.document_id AND d.status='approved'
               WHERE m.id=?""",
            (match_id,),
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=404,detail="Match or approved document not found")
        if row["review_status"] != "relevant" or not row["claim_id"]:
            raise HTTPException(
                status_code=409,
                detail="Review the match and accept the factual claim first",
            )
        evidence_id = str(uuid4())
        note = (
            "Documento revisionato, posizione: " + row["locator"]
            + ". Estratto: " + row["excerpt"][:600]
            + ". Motivazione revisore: " + payload.reason
        )
        conn.execute(
            """INSERT INTO evidence
               (id,claim_id,url,stance,source_kind,source_group,
                note,review_status,created_at,reviewed_at)
               VALUES (?,?,?,?,?,?,?,'pending',?,NULL)""",
            (evidence_id,row["claim_id"],row["url"],payload.stance,
             row["source_kind"],row["source_group"],note[:3000],now()),
        )
        conn.execute(
            """INSERT INTO document_evidence_links(match_id,evidence_id,document_id)
               VALUES (?,?,?)""",
            (match_id,evidence_id,row["document_id"]),
        )
    return {"evidence_id":evidence_id,"review_status":"pending",
            "note":"Separate evidence review is required before scoring changes"}
