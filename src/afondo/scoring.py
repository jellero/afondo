"""Transparent, intentionally limited evidence scoring. Not a truth oracle.

Only explicitly accepted evidence can influence a claim's status.
Independent groups prevent several articles citing one agency from counting twice.
"""

from collections import Counter
from typing import Any


def _credible(evidence: list[dict[str, Any]]) -> bool:
    groups = {e["source_group"].strip().casefold() for e in evidence if e.get("source_group")}
    return bool(
        len(groups) >= 2
        or any(e.get("source_kind") == "primary" for e in evidence)
    )


def score_claim(evidence: list[dict[str, Any]]) -> dict[str, Any]:
    accepted = [e for e in evidence if e.get("review_status") == "accepted"]
    supports = [e for e in accepted if e.get("stance") == "supports"]
    refutes = [e for e in accepted if e.get("stance") == "refutes"]

    if supports and refutes:
        status = "disputed"
    elif _credible(supports):
        status = "supported"
    elif _credible(refutes):
        status = "refuted"
    else:
        status = "insufficient_evidence"

    return {
        "status": status,
        "accepted_evidence": len(accepted),
        "independent_support_groups": len({
            e["source_group"].strip().casefold()
            for e in supports if e.get("source_group")
        }),
        "independent_refute_groups": len({
            e["source_group"].strip().casefold()
            for e in refutes if e.get("source_group")
        }),
    }


def score_article(claim_assessments: list[dict[str, Any]]) -> dict[str, Any]:
    """Evidence-only claim confirmation rate, never a full editorial reliability rating.

    Require at least two resolved claims and 60% coverage; otherwise abstain.
    Disputed claims do not count as resolved.
    """
    n = len(claim_assessments)
    counts = Counter(c["status"] for c in claim_assessments)
    resolved = counts["supported"] + counts["refuted"]
    coverage = round(resolved / n, 3) if n else 0.0
    can_score = resolved >= 2 and coverage >= 0.6

    return {
        "metric": "experimental_claim_support_ratio",
        "score": round(100 * counts["supported"] / resolved) if can_score else None,
        "claim_count": n,
        "resolved_claims": resolved,
        "coverage": coverage,
        "counts": dict(counts),
        "status": "provisional" if can_score else "insufficient_evidence",
        "warning": (
            "Non è un giudizio complessivo di attendibilità della notizia, "
            "dell'autore o della testata. È basato solo su prove esaminate."
        ),
    }
