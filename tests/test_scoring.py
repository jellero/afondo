from afondo.extract import extract_candidates
from afondo.scoring import score_article, score_claim


def accepted(stance="supports", source_group="official", source_kind="primary"):
    return {
        "review_status": "accepted",
        "stance": stance,
        "source_group": source_group,
        "source_kind": source_kind,
    }


def test_candidate_extraction_is_deduplicated():
    text = (
        "Questa frase contiene numeri e dati da verificare. "
        "Questa frase contiene numeri e dati da verificare. "
        "Una seconda frase utile con alcune indicazioni."
    )
    assert len(extract_candidates(text)) == 2


def test_pending_evidence_never_scores():
    item = accepted()
    item["review_status"] = "pending"
    assert score_claim([item])["status"] == "insufficient_evidence"


def test_one_primary_source_can_support_a_claim():
    assert score_claim([accepted()])["status"] == "supported"


def test_two_reprints_of_one_source_are_not_independent():
    items = [
        accepted(source_group="agency-A", source_kind="secondary"),
        accepted(source_group="agency-A", source_kind="secondary"),
    ]
    assert score_claim(items)["status"] == "insufficient_evidence"


def test_two_independent_secondary_sources_count():
    items = [
        accepted(source_group="one", source_kind="secondary"),
        accepted(source_group="two", source_kind="secondary"),
    ]
    assert score_claim(items)["status"] == "supported"


def test_conflicting_accepted_evidence_abstains():
    assert score_claim([accepted(), accepted(stance="refutes")])["status"] == "disputed"


def test_article_abstains_with_too_little_coverage():
    result = score_article([
        {"status": "supported"},
        {"status": "insufficient_evidence"},
        {"status": "insufficient_evidence"},
    ])
    assert result["score"] is None
    assert result["status"] == "insufficient_evidence"


def test_article_support_rate_is_limited_to_reviewed_claims():
    result = score_article([
        {"status": "supported"},
        {"status": "refuted"},
    ])
    assert result["score"] == 50
    assert result["metric"] == "experimental_claim_support_ratio"
