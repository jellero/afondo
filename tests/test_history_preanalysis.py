"""Offline tests for licensed pre-analysis and source/byline publication histories."""
from datetime import date, timedelta
import json

from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from afondo.db import connection
from afondo.history import byline_id, outlet_id
from afondo.main import app

TOKEN = "test-admin-token-for-preanalysis-and-history-long"
AUTH = {"X-Admin-Token": TOKEN}


def setup(monkeypatch, tmp_path):
    monkeypatch.setenv("AFONDO_DB_PATH", str(tmp_path / "batch.sqlite3"))
    monkeypatch.setenv("AFONDO_SOURCE_GRANTS", str(tmp_path / "missing-grants.json"))
    monkeypatch.setenv("AFONDO_ADMIN_TOKEN", TOKEN)
    monkeypatch.setenv("AFONDO_ENCRYPTION_KEY", Fernet.generate_key().decode())
    return TestClient(app)


def article(client, name="Marta Rossi"):
    response = client.post("/api/v1/articles", json={
        "title": "Rapporto economico sui prezzi energetici italiani",
        "text": (
            "Nel rapporto ufficiale, i prezzi medi dell'energia sono cresciuti "
            "nel periodo misurato secondo la pubblicazione statistica. "
            "Una seconda relazione contiene dati sugli stessi consumatori."
        ),
        "author": name, "outlet": "Giornale Demo",
        "source_url": "https://news.example.org/energia",
    })
    assert response.status_code == 201
    return response.json()["id"]


def test_no_implicit_provider_processing_without_individual_grant(monkeypatch, tmp_path):
    with setup(monkeypatch, tmp_path) as client:
        article_id = article(client)
        configured = client.put("/api/v1/admin/ai", headers=AUTH, json={
            "provider": "openai", "model": "mock-model", "api_key": "test-key", "active": True
        })
        assert configured.status_code == 200
        dry = client.get("/api/v1/admin/preanalysis", headers=AUTH).json()
        assert dry["eligible"] == 0

        result = client.post("/api/v1/admin/preanalysis/once", headers=AUTH)
        assert result.status_code == 200
        assert result.json()["processed"] == 0

        with connection() as conn:
            assert conn.execute("SELECT COUNT(*) FROM ai_analysis_runs").fetchone()[0] == 0

        invalid = client.put(
            f"/api/v1/admin/articles/{article_id}/processing",
            headers=AUTH,
            json={"allowed": True, "basis": "yes", "checked_by": ""},
        )
        assert invalid.status_code == 422
        assert client.get("/api/v1/admin/preanalysis", headers=AUTH).json()["eligible"] == 0


def test_preanalysis_licensed_batch_does_not_publish_or_verify_claim(monkeypatch, tmp_path):
    from afondo import ai_workflow

    def simulated_extract(source, provider):
        assert provider["provider"] == "openai"
        snippet = "i prezzi medi dell'energia sono cresciuti"
        start = source["body"].index(snippet)
        return {
            "provider": "openai", "model": provider["model"],
            "candidates": [{
                "quote": snippet, "claim": "I prezzi medi sono aumentati",
                "kind": "factual", "start_offset": start,
                "end_offset": start + len(snippet)
            }],
            "unanchored_or_duplicate": 0,
            "input_tokens": 100, "output_tokens": 40,
            "prompt_version": "claim-extraction-v1",
        }
    monkeypatch.setattr(ai_workflow, "extract", simulated_extract)
    with setup(monkeypatch, tmp_path) as client:
        article_id = article(client)
        client.put("/api/v1/admin/ai", headers=AUTH, json={
            "provider": "openai", "model": "mock-model", "api_key": "test-key", "active": True,
        })
        allowed = client.put(f"/api/v1/admin/articles/{article_id}/processing",
            headers=AUTH,
            json={"allowed": True,
                  "basis": "Licenza per invio del testo al provider AI in fase di test",
                  "checked_by": "Test reviewer",
                  "expires_on": (date.today()+timedelta(days=3)).isoformat()})
        assert allowed.status_code == 200
        assert allowed.json()["eligible"] is True
        before = client.get("/api/v1/admin/preanalysis", headers=AUTH).json()
        assert before["eligible"] == 1
        processed = client.post("/api/v1/admin/preanalysis/once", headers=AUTH)
        assert processed.status_code == 200
        assert processed.json()["processed"] == 1
        assert processed.json()["items"][0]["status"] == "candidates_pending_review"
        assert client.get("/api/v1/feed").json()["items"] == []
        details = client.get(f"/api/v1/admin/articles/{article_id}/ai", headers=AUTH).json()
        assert details["runs"][0]["status"] == "completed"
        assert details["candidates"][0]["review_status"] == "pending"
        assert client.get("/api/v1/admin/preanalysis", headers=AUTH).json()["eligible"] == 0
        repeated = client.post("/api/v1/admin/preanalysis/once", headers=AUTH)
        assert repeated.json()["processed"] == 0


def test_expired_processing_permission_is_skipped(monkeypatch, tmp_path):
    from afondo.preanalysis import eligible_articles
    with setup(monkeypatch, tmp_path) as client:
        article_id = article(client)
        # Exact expiry validated before entering the DB.
        expired = client.put(
            f"/api/v1/admin/articles/{article_id}/processing", headers=AUTH,
            json={"allowed":True, "checked_by":"Reviewer",
                  "basis":"Contract permitting provider AI processing",
                  "expires_on":"2000-01-01"},
        )
        assert expired.status_code == 422
        assert eligible_articles() == []


def test_history_requires_verified_identity_and_published_article(monkeypatch, tmp_path):
    with setup(monkeypatch, tmp_path) as client:
        article_id = article(client)
        other = article(client, name="Marco Rossi")
        assert client.get("/api/v1/history").json()["items"] == []
        approved = {"status":"approved", "topic":"economia"}
        for aid in (article_id, other):
            assert client.put(f"/api/v1/admin/editorial/{aid}", headers=AUTH,
                              json=approved).status_code == 200
        assert client.get("/api/v1/history?kind=outlet").json()["items"] == []

        attribution = {
            "outlet_confirmed": True, "byline_confirmed": True,
            "checked_by": "Editor",
            "source_note": "Firma e testata ricontrollate sull'articolo originale ufficiale."
        }
        res = client.put(
            f"/api/v1/admin/articles/{article_id}/attribution", headers=AUTH,
            json=attribution,
        )
        assert res.status_code == 200
        out = client.get("/api/v1/history?kind=outlet").json()
        assert out["total"] == 1
        assert out["items"][0]["summary"]["rating"] is None
        assert out["items"][0]["summary"]["article_count"] == 1
        author = client.get("/api/v1/history?kind=author").json()
        assert author["items"][0]["name"] == "Marta Rossi"
        slug = author["items"][0]["id"]
        history = client.get(f"/api/v1/history/author/{slug}").json()
        assert history["summary"]["sample_status"] == "limited"
        assert history["articles"][0]["revisions"][0]["event_kind"] == "published"
        assert "body" not in history["articles"][0]

        feed = client.get("/api/v1/feed").json()
        linked = next(item for item in feed["items"] if item["article_id"] == article_id)
        assert linked["history"]["outlet"]
        assert linked["history"]["author"]
        unlinked = next(item for item in feed["items"] if item["article_id"] == other)
        assert unlinked["history"] == {"outlet": None, "author": None}


def test_editorial_revision_requires_reason_and_preserves_timeline(monkeypatch, tmp_path):
    with setup(monkeypatch, tmp_path) as client:
        article_id = article(client)
        client.put(f"/api/v1/admin/articles/{article_id}/attribution",
                   headers=AUTH,
                   json={"outlet_confirmed":True,"checked_by":"Editor",
                         "source_note":"Link originale alla testata confermato manualmente."})
        approved = client.put(f"/api/v1/admin/editorial/{article_id}",headers=AUTH,
                              json={"status":"approved"})
        assert approved.status_code == 200
        change = {
            "status":"approved", "out_of_context":True,
            "note":("La comunicazione utilizza un periodo differente dalla relazione "
                    "di riferimento e il confronto richiede ulteriore contesto."),
            "evidence_url":"https://example.org/report"
        }
        assert client.put(f"/api/v1/admin/editorial/{article_id}",
                          headers=AUTH,json=change).status_code == 422
        change["change_reason"] = "Nuove prove accettate e revisione della contestualizzazione."
        assert client.put(f"/api/v1/admin/editorial/{article_id}",
                          headers=AUTH,json=change).status_code == 200
        slug = outlet_id("Giornale Demo","https://news.example.org/energia")
        events = client.get(f"/api/v1/history/outlet/{slug}").json()["articles"][0]["revisions"]
        assert [event["event_kind"] for event in events] == ["published","revised"]
        assert events[-1]["change_reason"] == change["change_reason"]


def test_byline_never_merges_across_different_publishers():
    assert byline_id("Mario Rossi", "Giornale A", "https://one.example/a") != (
        byline_id("Mario Rossi", "Giornale B", "https://two.example/a")
    )
    assert outlet_id("Giornale A", "http://one.example/a") is None
