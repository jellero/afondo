"""Suggest *document leads*, never proof, from licensed local source metadata.

Shared title keywords indicate only topical relevance. They must NEVER feed
the truth-verdict engine until a reviewer has read the original source.
"""
from __future__ import annotations

import json
import re
from unicodedata import normalize

from afondo.source_registry import configured_sources

STOP = frozenset("""
della dello degli delle all alle nel negli nella nelle sopra sotto oltre dalla
dalle dagli sono siamo è essere stato stati ha hanno un una uno il lo la i gli
le per con tra fra che di da in su dal ai al dei del dell questo questa nella
secondo anche come quando dove dopo prima rispetto anni anno mese giorni
the and from into with this that those these were been have has had will
their there being about above below news says said report reported according
to for is are was be by at an on its it a of as not than year years data
""".split())


def tokens(value: str) -> set[str]:
    text = normalize("NFKC", value).casefold()
    return {word for word in re.findall(r"[^\W\d_]{4,}", text)
            if word not in STOP}


def find_leads(conn, claim: str, *, limit: int = 8) -> list[dict]:
    """Read index metadata only when grant explicitly permits internal matching."""
    permitted = {
        entry["id"]: entry for entry in configured_sources()
        if entry["enabled"] and
        "internal_evidence_lookup" in entry["_grant"].get("allowed_uses", [])
    }
    if not permitted:
        return []
    query_terms = tokens(claim)
    if len(query_terms) < 3:
        return []
    rows = conn.execute(
        """SELECT id,source_id,title,url,published_at
           FROM discovered_items ORDER BY discovered_at DESC LIMIT 1000"""
    ).fetchall()
    matched = []
    for row in rows:
        source = permitted.get(row["source_id"])
        if source is None:
            continue
        title_terms = tokens(row["title"])
        shared = sorted(query_terms & title_terms)
        if len(shared) < 3:
            continue
        precision = len(shared) / max(len(title_terms), 1)
        if precision < 0.4:
            continue
        matched.append({
            "discovered_item_id": row["id"],
            "source_id": row["source_id"],
            "title": row["title"],
            "url": row["url"],
            "source_type": source["type"],
            "shared_terms": shared,
            "rank_score": round(precision, 4),
            "warning": "Pertinenza tematica da metadati: NON è conferma fattuale.",
        })
    matched.sort(key=lambda x: (
        x["source_type"] != "primary_evidence",
        -x["rank_score"],
        -len(x["shared_terms"]),
    ))
    return matched[:limit]


def save_leads(conn, candidate_id: str, claim: str) -> int:
    count = 0
    for match in find_leads(conn, claim):
        conn.execute(
            """INSERT OR IGNORE INTO ai_evidence_leads
               (candidate_id,discovered_item_id,source_id,shared_terms,rank_score)
               VALUES (?,?,?,?,?)""",
            (candidate_id, match["discovered_item_id"], match["source_id"],
             json.dumps(match["shared_terms"]), match["rank_score"]),
        )
        count += 1
    return count
