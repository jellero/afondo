"""Candidate documentary leads are not evidence, and honor current source permissions."""
from datetime import datetime, timezone
import json

from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from afondo.db import connection
from afondo.main import app
from afondo.evidence_discovery import find_leads

AUTH = {"X-Admin-Token": "lead-test-admin-long-enough-to-be-accepted"}


def test_candidates_are_metadata_leads_only_and_can_be_revoked(monkeypatch, tmp_path):
    from afondo import ai_workflow
    monkeypatch.setenv("AFONDO_DB_PATH", str(tmp_path / "leads.sqlite3"))
    monkeypatch.setenv("AFONDO_ADMIN_TOKEN", AUTH["X-Admin-Token"])
    monkeypatch.setenv("AFONDO_ENCRYPTION_KEY", Fernet.generate_key().decode())
    grant_file = tmp_path / "source-grants.json"
    monkeypatch.setenv("AFONDO_SOURCE_GRANTS", str(grant_file))
    permissions = {
        "sources": {"rainews-it": {
            "permission_recorded": True,
            "allowed_uses": ["metadata_discovery", "internal_evidence_lookup"],
            "permission_reference": "Mock grant, only in test fixture",
            "approved_by": "Reviewer",
            "reviewed_on": "2026-10-20",
            "approved_host": "www.rainews.it",
        }}
    }
    grant_file.write_text(json.dumps(permissions), encoding="utf-8")

    def output(article, _provider):
        quote = "I prezzi medi italiani sono aumentati"
        start = article["body"].index(quote)
        return {
            "provider":"openai","model":"mock",
            "candidates":[{"quote":quote,
                "claim":"Prezzi medi italiani aumentati nel trimestre",
                "kind":"factual","start_offset":start,
                "end_offset":start+len(quote)}],
            "unanchored_or_duplicate":0,"input_tokens":20,"output_tokens":10,
            "prompt_version":"claim-extraction-v1",
        }
    monkeypatch.setattr(ai_workflow, "extract", output)

    with TestClient(app) as client:
        with connection() as conn:
            conn.execute(
                """INSERT INTO discovered_items
                   (source_id,title,url,published_at,discovered_at,external_id)
                   VALUES (?,?,?,?,?,?)""",
                ("rainews-it", "Prezzi medi italiani aumentati secondo gli ultimi dati",
                 "https://www.rainews.it/test/story",
                 datetime.now(timezone.utc).isoformat(),
                 datetime.now(timezone.utc).isoformat(), "x"),
            )
            leads = find_leads(conn, "Prezzi medi italiani aumentati nel trimestre")
            assert len(leads) == 1
            assert leads[0]["warning"].startswith("Pertinenza tematica")
        article = client.post("/api/v1/articles", json={
            "title": "Articolo economico di verifica", "language": "it",
            "text": ("I prezzi medi italiani sono aumentati nel trimestre, "
                     "secondo una fonte che ha pubblicato un comunicato ufficiale. "
                     "La misura è stata descritta in un rapporto separato."),
        }).json()
        permission = client.put(
            f"/api/v1/admin/articles/{article['id']}/processing",
            headers=AUTH,
            json={"allowed": True,
                  "basis": "Offline test data authorized for simulated AI provider use",
                  "checked_by": "Test reviewer"},
        )
        assert permission.status_code == 200
        client.put("/api/v1/admin/ai",headers=AUTH,json={
            "provider":"openai","model":"mock-model",
            "api_key":"testing-only-key","active":True,
        })
        extracted = client.post(
            f"/api/v1/admin/articles/{article['id']}/ai-extract",
            headers=AUTH,
        )
        assert extracted.status_code == 200
        candidate = extracted.json()["candidates"][0]
        assert len(candidate["leads"]) == 1
        assert candidate["leads"][0]["source_id"] == "rainews-it"
        assert article["assessment"]["score"] is None
        with connection() as conn:
            assert conn.execute("SELECT COUNT(*) FROM evidence").fetchone()[0] == 0

        # Revoking the license must hide any previously recorded metadata leads.
        permissions["sources"]["rainews-it"]["allowed_uses"] = ["metadata_discovery"]
        grant_file.write_text(json.dumps(permissions), encoding="utf-8")
        refreshed = client.get(
            f"/api/v1/admin/articles/{article['id']}/ai",headers=AUTH
        )
        assert refreshed.status_code == 200
        assert refreshed.json()["candidates"][0]["leads"] == []
