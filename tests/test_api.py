from fastapi.testclient import TestClient
from afondo.main import app


def client_for_test(monkeypatch, tmp_path):
    monkeypatch.setenv("AFONDO_DB_PATH", str(tmp_path / "test.sqlite3"))
    monkeypatch.setenv("AFONDO_REVIEW_TOKEN", "local-test-only-secret")
    return TestClient(app)


def test_article_lifecycle_and_evidence_review(monkeypatch, tmp_path):
    with client_for_test(monkeypatch, tmp_path) as client:
        assert client.get("/health").json()["status"] == "ok"
        create = client.post("/api/v1/articles", json={
            "title": "Articolo dimostrativo",
            "language": "it",
            "text": (
                "Il rapporto statistico indica una variazione significativa nel periodo osservato. "
                "Il documento di ricerca descrive una crescita rilevante nell'ultimo trimestre."
            ),
        })
        assert create.status_code == 201
        article = create.json()
        assert len(article["claims"]) == 2
        assert article["assessment"]["score"] is None

        evidence_ids = []
        for claim in article["claims"]:
            result = client.post(f"/api/v1/claims/{claim['id']}/evidence", json={
                "url": "https://example.org/report",
                "source_group": "primary-report",
                "source_kind": "primary",
                "stance": "supports",
                "note": "Documento originale da controllare in dettaglio.",
            })
            assert result.status_code == 201
            evidence_ids.append(result.json()["id"])

        before = client.get(f"/api/v1/articles/{article['id']}").json()
        assert before["assessment"]["score"] is None

        denied = client.post(
            f"/api/v1/evidence/{evidence_ids[0]}/review",
            json={"decision": "accepted"},
        )
        assert denied.status_code == 403

        for evidence_id in evidence_ids:
            reviewed = client.post(
                f"/api/v1/evidence/{evidence_id}/review",
                headers={"X-Review-Token": "local-test-only-secret"},
                json={"decision": "accepted"},
            )
            assert reviewed.status_code == 200

        final = client.get(f"/api/v1/articles/{article['id']}").json()
        assert final["assessment"]["score"] == 100
        assert final["assessment"]["status"] == "provisional"
        assert len(client.get("/api/v1/articles").json()["items"]) == 1


def test_no_url_fetch_and_validation(monkeypatch, tmp_path):
    with client_for_test(monkeypatch, tmp_path) as client:
        bad = client.post("/api/v1/articles", json={
            "title": "Valore non valido",
            "text": "a" * 70,
            "source_url": "file:///etc/passwd",
        })
        assert bad.status_code == 422
        assert client.get("/api/v1/articles/missing").status_code == 404


def test_review_disabled_when_not_configured(monkeypatch, tmp_path):
    monkeypatch.setenv("AFONDO_DB_PATH", str(tmp_path / "test.sqlite3"))
    monkeypatch.delenv("AFONDO_REVIEW_TOKEN", raising=False)
    with TestClient(app) as client:
        response = client.post("/api/v1/evidence/some-id/review", json={"decision": "accepted"})
        assert response.status_code == 503
