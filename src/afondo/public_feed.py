"""Public AFONDO news feed: clear provenance, conservative indicators.

Never equate a headline with proven misinformation. Editorial 'sensationalistic'
and 'out of context' flags require explicit human review and evidence.
Metadata-only RSS articles always remain unverified.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone, timedelta
from collections import defaultdict

from fastapi import APIRouter, Query
from afondo.db import connection
from afondo.scoring import score_claim, score_article
from afondo.feed_parser import canonical_url
from afondo.source_registry import configured_sources

router = APIRouter(prefix="/api/v1", tags=["public news feed"])

TOPICS = {
    "attualita": ("attualità", "cronaca", "società", "protest", "election", "incident", "notizia"),
    "politica": ("governo", "parlament", "minister", "elezion", "politic", "senato", "president", "congress", "government", "vote", "minister"),
    "economia": ("econom", "inflazion", "prezz", "mercat", "borsa", "lavoro", "finanz", "pil", "bank", "stock", "tariff", "trade", "inflation", "economy", "market"),
    "mondo": ("ucrain", "guerra", "international", "global", "nazioni unite", "war", "conflict", "europa", "world", "asia", "africa", "mediorient"),
    "tecnologia": ("intelligenza artificiale", "artificial intelligence", "tecnolog", "software", "smartphone", "cyber", "digital", "openai", "chip", "startup", "ai ", "robot"),
    "scienza": ("ricerc", "scienz", "astronom", "space", "nasa", "study", "scientist", "research", "fisica", "spazio"),
    "salute": ("salute", "sanit", "ospedal", "medic", "vaccin", "disease", "health", "virus", "malatt"),
    "ambiente": ("clima", "ambient", "inquin", "energy", "energia", "climate", "emission", "sostenib", "meteo", "weather"),
    "sport": ("sport", "calcio", "tennis", "formula 1", "basket", "football", "olimp", "champion", "serie a"),
    "cultura": ("cultura", "cinema", "film", "music", "musica", "arte", "festival", "teatro", "book", "libro"),
}
STOPWORDS = frozenset(("della dello degli delle nella nelle alla alle con per tra che una uno un the and for with from this that news"
                      " sulle nella della anche come dopo prima delle they their have into di da in su ai agli al del dei il la le lo i"
                      " a e of in on to at is are as an new has nel non più all nel dopo oggi today says say said").split())


def classify_topic(title: str) -> str:
    """Crude discovery metadata categorizer, not a semantic article analysis."""
    normalized = title.lower()
    points = {topic: sum(normalized.count(word) for word in terms)
              for topic, terms in TOPICS.items() if topic != "attualita"}
    best = max(points, key=points.get, default="attualita")
    return best if points and points[best] > 0 else "attualita"


def parse_date(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        date = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if date.tzinfo is None:
            date = date.replace(tzinfo=timezone.utc)
        return date.astimezone(timezone.utc)
    except (ValueError, TypeError):
        return None


def signal_for_editorial(editorial: dict | None, claim_result: dict | None) -> dict:
    flags = []
    if editorial and editorial.get("status") == "approved":
        if editorial.get("sensationalistic"):
            flags.append({"kind": "sensationalistic", "label": "Titolo sensazionalistico"})
        if editorial.get("out_of_context"):
            flags.append({"kind": "out_of_context", "label": "Fuori contesto"})
    if flags:
        return {
            "state": "caution", "label": flags[0]["label"],
            "flags": flags, "reviewed": True,
            "note": editorial.get("note") or "", "evidence_url": editorial.get("evidence_url"),
        }

    if claim_result and claim_result.get("status") == "provisional":
        counts = claim_result.get("counts") or {}
        if counts.get("refuted", 0):
            return {
                "state": "disputed", "label": "Affermazioni contestate",
                "flags": [], "reviewed": False, "note": "",
                "evidence_url": None,
            }
        if counts.get("supported", 0) and not counts.get("refuted", 0):
            return {
                "state": "supported", "label": "Affermazioni supportate",
                "flags": [], "reviewed": False, "note": "",
                "evidence_url": None,
            }
    return {
        "state": "unverified", "label": "Non ancora verificata",
        "flags": [], "reviewed": False, "note": "", "evidence_url": None,
    }


def _claim_assessments(conn, article_id: str) -> dict:
    claims = conn.execute("SELECT id FROM claims WHERE article_id=?", (article_id,)).fetchall()
    results = []
    for claim in claims:
        evidence = [
            dict(row) for row in conn.execute(
                """SELECT e.stance, e.source_kind, e.source_group,
                          CASE WHEN l.match_id IS NOT NULL
                            AND (d.status IS NULL OR d.status != 'approved')
                            THEN 'pending' ELSE e.review_status END AS review_status
                   FROM evidence e
                   LEFT JOIN document_evidence_links l ON l.evidence_id=e.id
                   LEFT JOIN evidence_documents d ON d.id=l.document_id
                   WHERE e.claim_id=?""", (claim["id"],)
            ).fetchall()
        ]
        results.append(score_claim(evidence))
    return score_article(results)


def _headline_tokens(text: str) -> set[str]:
    return {w for w in re.findall(r"[^\W\d_]{4,}", text.lower())
            if w not in STOPWORDS}


def coverage_counts(items: list[dict]) -> dict[str, int]:
    """Rough *coverage* indicator. Requires two distinct named source IDs.

    Never marketed as reader popularity, objective accuracy or independent proof.
    Matching is deliberately strict and limited to recent items.
    """
    recent = [
        item for item in items if item.get("published_at")
        and parse_date(item["published_at"])
        and parse_date(item["published_at"]) >= datetime.now(timezone.utc) - timedelta(days=3)
    ]
    tokens = {item["id"]: _headline_tokens(item["title"]) for item in recent}
    graph = defaultdict(set)
    for index, a in enumerate(recent):
        ta = tokens[a["id"]]
        if len(ta) < 3:
            continue
        for b in recent[index+1:]:
            tb = tokens[b["id"]]
            if len(tb) < 3:
                continue
            overlap = len(ta & tb)
            if overlap >= 3 and overlap / max(len(ta), len(tb)) >= 0.65:
                graph[a["id"]].add(b["id"])
                graph[b["id"]].add(a["id"])
    # Only direct matches are counted, not transitive clusters that can drift.
    by_id = {item["id"]: item for item in recent}
    result = {}
    for item in recent:
        group = {item["id"]} | graph[item["id"]]
        source_ids = {by_id[k]["source_key"] for k in group if by_id[k].get("source_key")}
        result[item["id"]] = len(source_ids) if len(source_ids) >= 2 else 0
    return result


def get_feed(topic: str = "tutti", sort: str = "recenti",
             query: str = "", limit: int = 60) -> dict:
    with connection() as conn:
        article_rows = conn.execute(
            """SELECT a.id, a.title, a.source_url, a.author, a.outlet, a.created_at,
                      e.topic, e.status AS editorial_status, e.sensationalistic,
                      e.out_of_context, e.note, e.evidence_url, e.featured,
                      COALESCE(v.outlet_confirmed,0) AS outlet_confirmed,
                      COALESCE(v.byline_confirmed,0) AS byline_confirmed,
                      (SELECT r.status FROM ai_analysis_runs r
                       WHERE r.article_id=a.id ORDER BY r.started_at DESC LIMIT 1)
                       AS ai_preanalysis_status
               FROM articles a LEFT JOIN editorial_reviews e ON e.article_id=a.id
               LEFT JOIN verified_attributions v ON v.article_id=a.id
               ORDER BY a.created_at DESC LIMIT 150"""
        ).fetchall()
        discoveries = conn.execute(
            """SELECT id, source_id, title, url, published_at, discovered_at
               FROM discovered_items ORDER BY discovered_at DESC LIMIT 250"""
        ).fetchall()
        editorial = {
            row["id"]: {
                "status": row["editorial_status"],
                "sensationalistic": bool(row["sensationalistic"]),
                "out_of_context": bool(row["out_of_context"]),
                "note": row["note"], "evidence_url": row["evidence_url"],
            } for row in article_rows
        }
        items = []
        for row in article_rows:
            # User-submitted texts must never be public without editorial approval.
            if row["editorial_status"] != "approved":
                continue
            topic_id = row["topic"] or classify_topic(row["title"])
            assessment = _claim_assessments(conn, row["id"])
            from afondo.history import history_links
            items.append({
                "history": history_links(dict(row)),
                "preanalysis": (
                    "candidate_review_pending"
                    if row["ai_preanalysis_status"] == "completed" else
                    "failed" if row["ai_preanalysis_status"] == "failed" else "not_started"
                ),
                "id": "a-" + row["id"], "kind": "article", "article_id": row["id"],
                "title": row["title"], "url": row["source_url"],
                "source": row["outlet"] or "AFONDO / Testo inviato",
                "source_key": (row["outlet"] or "").strip().casefold() or None,
                "author": row["author"], "published_at": row["created_at"],
                "topic": topic_id,
                "topic_method": "editorial" if row["topic"] else "title_keywords",
                "indicator": signal_for_editorial(editorial[row["id"]], assessment),
                "featured": bool(row["featured"]) and row["editorial_status"] == "approved",
                "summary": "Consulta le affermazioni e le prove registrate in AFONDO.",
            })
    sources = configured_sources()
    name_by_id = {item["id"]: item["name"] for item in sources}
    display_allowed = {
        src["id"] for src in sources
        if src["enabled"] and
        "public_metadata_display" in src["_grant"].get("allowed_uses", [])
    }
    for row in discoveries:
        if row["source_id"] not in display_allowed:
            continue
        items.append({
            "history": {"outlet": None, "author": None},
            "preanalysis": "not_applicable_metadata_only",
            "id": "d-" + str(row["id"]), "kind": "discovery", "article_id": None,
            "title": row["title"], "url": row["url"],
            "source": name_by_id.get(row["source_id"], row["source_id"]),
            "source_key": row["source_id"], "author": None,
            "published_at": row["published_at"] or row["discovered_at"],
            "topic": classify_topic(row["title"]), "topic_method": "title_keywords",
            "indicator": signal_for_editorial(None, None),
            "featured": False,
            "summary": "Titolo e collegamento dalla fonte originale. Nessuna verifica del contenuto disponibile.",
        })
    # Same URL may appear from both manual analysis and source discovery.
    unique = {}
    for item in items:
        normalized = canonical_url(item["url"]) if item["url"] else None
        key = normalized or item["id"]
        if key not in unique or item["kind"] == "article":
            unique[key] = item
    items = list(unique.values())
    counts = coverage_counts(items)
    for item in items:
        item["coverage_sources"] = counts.get(item["id"], 0)
    accepted_topics = set(TOPICS) | {"tutti"}
    if topic not in accepted_topics:
        topic = "tutti"
    if topic != "tutti":
        items = [item for item in items if item["topic"] == topic]
    if query.strip():
        needle = query.strip().casefold()[:100]
        items = [item for item in items if needle in (item["title"] + " " + item["source"]).casefold()]
    def timestamp(item):
        return parse_date(item["published_at"]) or datetime.min.replace(tzinfo=timezone.utc)
    if sort == "tendenza":
        items = [item for item in items if item["coverage_sources"] >= 2]
        items.sort(key=lambda item: (item["coverage_sources"], timestamp(item)), reverse=True)
    elif sort == "verificate":
        items = [item for item in items if item["indicator"]["state"] != "unverified"]
        items.sort(key=timestamp, reverse=True)
    else:
        items.sort(key=lambda item: (item["featured"], timestamp(item)), reverse=True)
    return {
        "items": items[:limit],
        "total": len(items),
        "topic": topic, "sort": sort,
        "as_of": datetime.now(timezone.utc).isoformat(),
        "disclaimer": (
            "La frequenza di copertura non misura popolarità né verifica i fatti. "
            "Le segnalazioni 'sensazionalistico' o 'fuori contesto' richiedono "
            "una revisione editoriale documentata. I testi inviati richiedono approvazione "
            "prima della pubblicazione. I feed solo metadati non sono verificati."
        ),
    }


@router.get("/feed")
def public_feed(
    topic: str = Query("tutti", max_length=32),
    sort: str = Query("recenti", pattern="^(recenti|tendenza|verificate)$"),
    q: str = Query("", max_length=100),
    limit: int = Query(48, ge=1, le=100),
):
    return get_feed(topic=topic, sort=sort, query=q, limit=limit)
