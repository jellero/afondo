"""Newsroom-like public feed with conservative evidence states.

The tests use local SQLite and never hit outside news sites or AI providers.
"""
from datetime import datetime, timezone
import json

from fastapi.testclient import TestClient
from afondo.db import connection
from afondo.main import app

ADMIN = {"X-Admin-Token": "portal-admin-token-long-enough-for-testing"}


def client(monkeypatch, tmp_path):
    monkeypatch.setenv("AFONDO_DB_PATH", str(tmp_path / "portal.sqlite3"))
    monkeypatch.setenv("AFONDO_SOURCE_GRANTS", str(tmp_path / "grants.json"))
    monkeypatch.setenv("AFONDO_ADMIN_TOKEN", ADMIN["X-Admin-Token"])
    return TestClient(app)


def submit(c):
    r = c.post("/api/v1/articles", json={
        "title": "Il costo dell'energia in Italia e i dati ufficiali",
        "language": "it", "outlet": "Redazione dimostrativa",
        "source_url": "https://example.com/energia",
        "text": (
            "Secondo la relazione pubblica, i prezzi dell'energia sono aumentati "
            "nel periodo preso in esame da diversi osservatori indipendenti. "
            "L'istituto statistico ha pubblicato una seconda tabella di confronto."
        ),
    })
    assert r.status_code == 201
    return r.json()["id"]


def test_editorial_approval_is_required_for_publication(monkeypatch, tmp_path):
    with client(monkeypatch, tmp_path) as c:
        assert c.get("/").status_code == 200
        assert "viste a fondo." in c.get("/").text
        assert c.get("/portal.css").status_code == 200
        assert c.get("/portal.js").status_code == 200
        assert c.get("/analyze").status_code == 200
        article_id = submit(c)
        first = c.get("/api/v1/feed").json()
        assert first["items"] == []

        # Without authentication, nobody may publicly stigmatize an article.
        denied = c.put(f"/api/v1/admin/editorial/{article_id}", json={
            "status": "approved", "sensationalistic": True,
            "note": "Una nota sufficientemente estesa da motivare un giudizio pubblico.",
            "evidence_url": "https://example.com/report",
        })
        assert denied.status_code == 401

        draft = c.put(f"/api/v1/admin/editorial/{article_id}", headers=ADMIN,
                      json={"status": "draft", "topic": "economia",
                            "featured": True, "sensationalistic": True})
        assert draft.status_code == 200
        assert c.get("/api/v1/feed").json()["items"] == []

        invalid = c.put(f"/api/v1/admin/editorial/{article_id}", headers=ADMIN,
                        json={"status": "approved", "sensationalistic": True})
        assert invalid.status_code == 422
        assert c.get("/api/v1/feed").json()["items"] == []

        approved = c.put(f"/api/v1/admin/editorial/{article_id}", headers=ADMIN,
                         json={
                             "status": "approved", "featured": True, "topic": "economia",
                             "sensationalistic": True, "out_of_context": True,
                             "note": ("Il titolo allarga impropriamente la portata "
                                      "del confronto citato: occorre distinguere "
                                      "le categorie e gli intervalli temporali."),
                             "evidence_url": "https://example.com/report",
                         })
        assert approved.status_code == 200
        feed = c.get("/api/v1/feed?topic=economia").json()
        assert feed["total"] == 1
        item = feed["items"][0]
        assert item["featured"] is True
        assert item["indicator"]["state"] == "caution"
        assert {flag["kind"] for flag in item["indicator"]["flags"]} == {
            "sensationalistic", "out_of_context"
        }
        assert item["indicator"]["evidence_url"] == "https://example.com/report"
        assert c.get("/api/v1/feed?topic=scienza").json()["items"] == []
        assert c.get("/api/v1/feed?sort=verificate").json()["total"] == 1

        # Retraction: returning to draft removes article from public view.
        c.put(f"/api/v1/admin/editorial/{article_id}", headers=ADMIN,
              json={"status": "draft", "topic": "economia"})
        assert c.get("/api/v1/feed").json()["total"] == 0


def test_metadata_discovery_requires_public_display_grant(monkeypatch, tmp_path):
    with client(monkeypatch, tmp_path) as c:
        now = datetime.now(timezone.utc).isoformat()
        headline = "Nuove misure economiche sulle esportazioni italiane e la crescita"
        with connection() as conn:
            for source, suffix in [("rainews-it", "a"), ("dw-en", "b")]:
                conn.execute(
                    """INSERT INTO discovered_items
                       (source_id,title,url,published_at,discovered_at,external_id)
                       VALUES (?,?,?,?,?,?)""",
                    (source, headline, f"https://example.net/news/{suffix}",
                     now, now, suffix),
                )
        # Even previously cached headlines must not be public without
        # a current grant for both ingestion AND public title display.
        assert c.get("/api/v1/feed").json()["items"] == []

        grants = {
            "sources": {
                "rainews-it": {
                    "permission_recorded": True,
                    "allowed_uses": ["metadata_discovery", "public_metadata_display"],
                    "permission_reference": "Test fixture not a real publisher license",
                    "approved_by": "Unit test", "reviewed_on": "2026-10-20",
                    "approved_host": "www.rainews.it",
                },
                "dw-en": {
                    "permission_recorded": True,
                    "allowed_uses": ["metadata_discovery", "public_metadata_display"],
                    "permission_reference": "Test fixture not a real publisher license",
                    "approved_by": "Unit test", "reviewed_on": "2026-10-20",
                    "approved_host": "rss.dw.com",
                },
            }
        }
        (tmp_path / "grants.json").write_text(json.dumps(grants), encoding="utf-8")
        feed = c.get("/api/v1/feed?sort=tendenza").json()
        assert feed["total"] == 2
        assert all(i["coverage_sources"] == 2 for i in feed["items"])
        assert all(i["indicator"]["state"] == "unverified" for i in feed["items"])
        assert all(i["topic"] == "economia" for i in feed["items"])

        # Expiring/revoking a license removes previously cached titles.
        grants["sources"]["dw-en"]["allowed_uses"] = ["metadata_discovery"]
        (tmp_path / "grants.json").write_text(json.dumps(grants), encoding="utf-8")
        reduced = c.get("/api/v1/feed").json()
        assert reduced["total"] == 1
        assert reduced["items"][0]["coverage_sources"] == 0
        assert c.get("/api/v1/feed?sort=tendenza").json()["items"] == []


def test_existing_claim_assessment_is_partial_and_not_editorial(monkeypatch, tmp_path):
    with client(monkeypatch, tmp_path) as c:
        article_id = submit(c)
        result = c.put(f"/api/v1/admin/editorial/{article_id}",
                       headers=ADMIN, json={"status": "approved"})
        assert result.status_code == 200
        public = c.get("/api/v1/feed").json()["items"][0]
        assert public["indicator"]["state"] == "unverified"
        assert public["indicator"]["label"] == "Non ancora verificata"
        assert public["source"] == "Redazione dimostrativa"
        assert "body" not in public
        assert "key_ciphertext" not in str(public)
