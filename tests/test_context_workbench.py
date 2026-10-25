"""Offline evidence workbench contract tests: no downloads, no model billing."""
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from afondo.context_checks import context_signals
from afondo.db import connection
from afondo.main import app

ADMIN = {"X-Admin-Token": "editorial-context-admin-key-for-testing"}
REVIEW = {"X-Review-Token": "review-key-for-workbench-testing"}


def client(monkeypatch, tmp_path):
    monkeypatch.setenv("AFONDO_DB_PATH", str(tmp_path / "documents.sqlite3"))
    monkeypatch.setenv("AFONDO_SOURCE_GRANTS", str(tmp_path / "no-grants.json"))
    monkeypatch.setenv("AFONDO_ADMIN_TOKEN", ADMIN["X-Admin-Token"])
    monkeypatch.setenv("AFONDO_REVIEW_TOKEN", REVIEW["X-Review-Token"])
    monkeypatch.setenv("AFONDO_ENCRYPTION_KEY", Fernet.generate_key().decode())
    return TestClient(app)


def article(c):
    quote = "I prezzi energia elettrica sono aumentati del 40% nel 2025"
    body = (
        quote + ". Il rapporto menziona inoltre un differente intervallo "
        "di osservazione e una tabella riportata da più quotidiani."
    )
    response = c.post("/api/v1/articles", json={
        "title": "L'andamento dei prezzi energia elettrica nel 2025",
        "text": body, "language": "it",
    })
    assert response.status_code == 201
    return response.json()["id"], quote


def upload(c):
    response = c.post("/api/v1/admin/documents", headers=ADMIN, json={
        "title": "Documento ufficiale sul prezzo dell'energia elettrica",
        "url": "https://statistics.example.org/energy/table-2",
        "publisher": "Ente statistico",
        "source_group": "Statistica nazionale",
        "source_kind": "primary",
        "excerpt": (
            "Nel 2024 i prezzi energia elettrica sono aumentati del 4% "
            "nel confronto annuale per i consumatori domestici secondo l'indice."
        ),
        "locator": "Pagina 2, tabella 4",
        "permission_reference": "Citazione di un estratto di esempio autorizzato nel test",
        "recorded_by": "Ricercatore A",
        "publication_date": "2025-01-23",
    })
    assert response.status_code == 201
    return response.json()["id"]


def fake_model(data, _provider):
    quote = "I prezzi energia elettrica sono aumentati del 40% nel 2025"
    assert quote in data["body"]
    start = data["body"].index(quote)
    return {
        "provider": "openai", "model": "offline-mock",
        "candidates": [{
            "quote": quote,
            "claim": "I prezzi energia elettrica sono aumentati del 40% nel 2025",
            "kind": "factual", "start_offset": start,
            "end_offset": start+len(quote),
        }],
        "unanchored_or_duplicate": 0,
        "input_tokens": 30, "output_tokens": 22,
        "prompt_version": "claim-extraction-v1",
    }


def configure(c, article_id):
    assert c.put("/api/v1/admin/ai", headers=ADMIN, json={
        "provider": "openai", "model": "offline-mock",
        "api_key": "nonreal-offline-api-key", "active": True,
    }).status_code == 200
    assert c.put(
        f"/api/v1/admin/articles/{article_id}/processing",
        headers=ADMIN,
        json={
            "allowed": True,
            "basis": "Offline test authorizes use of this synthetic article with mock AI.",
            "checked_by": "Research Editor",
        },
    ).status_code == 200


def test_numbers_and_dates_only_emit_review_signals():
    signals = context_signals(
        "Nel 2025 l'aumento è stato del 40%, con un dato del 1,5%.",
        "Nel 2024 l'aumento è stato del 4%, con un dato del 1.5%.",
    )
    assert {signal["code"] for signal in signals} == {
        "different_explicit_quantity", "different_explicit_years"
    }
    assert all(signal["level"] == "review" for signal in signals)
    assert context_signals("Nel 2025 il tasso è 1,5%", "Nel 2025 il tasso è 1.5%") == []
    assert context_signals("Un aumento elevato", "Una riduzione importante") == []


def test_cannot_approve_own_source_excerpt(monkeypatch, tmp_path):
    with client(monkeypatch, tmp_path) as c:
        doc_id = upload(c)
        denied = c.post(
            f"/api/v1/admin/documents/{doc_id}/review", headers=ADMIN,
            json={
                "decision": "approve", "checked_by": "Ricercatore A",
                "review_note": "Ho controllato il testo originale e il riferimento.",
            },
        )
        assert denied.status_code == 409
        assert c.get("/api/v1/admin/context-queue", headers=ADMIN).json()["items"] == []


def test_source_excerpt_matching_and_evidence_review(monkeypatch, tmp_path):
    from afondo import ai_workflow
    monkeypatch.setattr(ai_workflow, "extract", fake_model)
    with client(monkeypatch, tmp_path) as c:
        article_id, _ = article(c)
        configure(c, article_id)
        extracted = c.post(
            f"/api/v1/admin/articles/{article_id}/ai-extract", headers=ADMIN
        )
        assert extracted.status_code == 200
        candidate_id = extracted.json()["candidates"][0]["id"]
        assert c.get("/api/v1/admin/context-queue", headers=ADMIN).json()["items"] == []

        doc_id = upload(c)
        assert c.get("/api/v1/admin/context-queue", headers=ADMIN).json()["items"] == []
        accepted_doc = c.post(
            f"/api/v1/admin/documents/{doc_id}/review", headers=ADMIN,
            json={
                "decision": "approve", "checked_by": "Ricercatore B",
                "review_note": "Controllo condotto sul testo e sulla tabella indicata.",
            },
        )
        assert accepted_doc.status_code == 200
        assert accepted_doc.json()["possible_matches"] == 1
        queue = c.get("/api/v1/admin/context-queue", headers=ADMIN).json()["items"]
        assert len(queue) == 1
        match = queue[0]
        assert match["review_status"] == "pending"
        assert "different_explicit_years" in {s["code"] for s in match["signals"]}
        assert "different_explicit_quantity" in {s["code"] for s in match["signals"]}
        assert "review_status" not in c.get("/api/v1/feed").text or (
            c.get("/api/v1/feed").json()["items"] == []
        )

        # Neither the extracted quote nor a document match changes proof ratings.
        article_view = c.get(f"/api/v1/articles/{article_id}").json()
        assert article_view["assessment"]["score"] is None
        assert c.get(f"/api/v1/admin/documents", headers=ADMIN).status_code == 200
        assert c.get("/api/v1/admin/context-queue").status_code == 401
        refused = c.post(
            f"/api/v1/admin/context-matches/{match['id']}/evidence-proposal",
            headers=ADMIN,
            json={"stance": "refutes",
                  "reason": "Differenza significativa tra anno e percentuale citati."},
        )
        assert refused.status_code == 409

        claim = c.post(
            f"/api/v1/admin/ai-candidates/{candidate_id}/decision?decision=accept",
            headers=ADMIN,
        )
        assert claim.status_code == 200
        assert claim.json()["claim_id"]
        decided = c.post(
            f"/api/v1/admin/context-matches/{match['id']}/decision",
            headers=ADMIN,
            json={
                "decision": "relevant", "reviewed_by": "Verificatore C",
                "review_note": "L'estratto parla dello stesso tipo di indicatore e richiede confronto.",
            },
        )
        assert decided.status_code == 200

        proposed = c.post(
            f"/api/v1/admin/context-matches/{match['id']}/evidence-proposal",
            headers=ADMIN,
            json={"stance": "refutes",
                  "reason": "La tabella riporta un periodo differente e un valore numerico minore."},
        )
        assert proposed.status_code == 200
        evidence_id = proposed.json()["evidence_id"]
        assert proposed.json()["review_status"] == "pending"
        assert c.post(
            f"/api/v1/admin/context-matches/{match['id']}/evidence-proposal",
            headers=ADMIN,
            json={"stance": "refutes",
                  "reason": "Una nuova proposta duplicata deve essere rifiutata dal sistema."},
        ).status_code == 409

        before = c.get(f"/api/v1/articles/{article_id}").json()
        target = next(item for item in before["claims"] if item["id"]==claim.json()["claim_id"])
        assert target["assessment"]["status"] == "insufficient_evidence"
        reviewed = c.post(
            f"/api/v1/evidence/{evidence_id}/review", headers=REVIEW,
            json={"decision": "accepted"},
        )
        assert reviewed.status_code == 200
        after = c.get(f"/api/v1/articles/{article_id}").json()
        target = next(item for item in after["claims"] if item["id"]==claim.json()["claim_id"])
        assert target["assessment"]["status"] == "refuted"
        # Even then, article-wide scoring needs representative claim coverage.
        assert after["assessment"]["score"] is None

        retired = c.post(
            f"/api/v1/admin/documents/{doc_id}/review", headers=ADMIN,
            json={
                "decision": "retire", "checked_by": "Ricercatore B",
                "review_note": "Licenza e accuratezza del riferimento revocate in seguito.",
            },
        )
        assert retired.status_code == 200
        assert c.get("/api/v1/admin/context-queue", headers=ADMIN).json()["items"] == []
        after_retire = c.get(f"/api/v1/articles/{article_id}").json()
        target = next(item for item in after_retire["claims"]
                      if item["id"]==claim.json()["claim_id"])
        assert target["assessment"]["status"] == "insufficient_evidence"
        assert target["evidence"][0]["stored_review_status"] == "accepted"
        assert target["evidence"][0]["review_status"] == "pending"
        blocked = c.post(
            f"/api/v1/evidence/{evidence_id}/review", headers=REVIEW,
            json={"decision": "accepted"},
        )
        assert blocked.status_code == 409


def test_article_cannot_be_a_documentary_reference_to_itself():
    from afondo.context_workbench import match_candidate, _suggest
    from unittest.mock import Mock

    original = {
        "id": "candidate-1",
        "quote": "I prezzi energia elettrica sono aumentati nel 2025",
        "normalized_claim": "Prezzi energia elettrica aumentati nel 2025",
        "article_source_url": "https://example.com/article",
    }
    copied = {
        "id": "document-1",
        "url": "https://example.com/article#paragraph4",
        "excerpt": "I prezzi energia elettrica sono aumentati nel 2025. "
                   "Il giornale ripete lo stesso titolo senza fonti esterne.",
    }
    assert match_candidate(original, copied) is not None
    fake_conn = Mock()
    assert _suggest(fake_conn, original, copied) is False
    fake_conn.execute.assert_not_called()
