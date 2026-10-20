"""Administrator tests. All external AI requests are replaced by offline fakes."""
import json
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from afondo.db import connection
from afondo.main import app


def setup(monkeypatch, tmp_path):
    monkeypatch.setenv("AFONDO_DB_PATH", str(tmp_path / "admin.sqlite3"))
    monkeypatch.setenv("AFONDO_SOURCE_GRANTS", str(tmp_path / "no-grants.json"))
    monkeypatch.setenv("AFONDO_ADMIN_TOKEN", "integration-test-admin-token-very-long")
    monkeypatch.setenv("AFONDO_ENCRYPTION_KEY", Fernet.generate_key().decode())
    return TestClient(app)


AUTH = {"X-Admin-Token": "integration-test-admin-token-very-long"}


def test_auth_required_for_admin_data(monkeypatch, tmp_path):
    with setup(monkeypatch, tmp_path) as client:
        assert client.get("/admin").status_code == 200
        assert client.get("/admin.js").status_code == 200
        assert client.get("/api/v1/admin/status").status_code == 401
        assert client.get("/api/v1/admin/status", headers={"X-Admin-Token": "wrong"}).status_code == 401
        assert client.get("/api/v1/admin/status", headers=AUTH).json()["sources"] == 20
        assert client.get("/api/v1/admin/ai", headers=AUTH).json()["items"] == []


def test_admin_disabled_without_token(monkeypatch, tmp_path):
    with setup(monkeypatch, tmp_path) as client:
        monkeypatch.delenv("AFONDO_ADMIN_TOKEN")
        response = client.get("/api/v1/admin/status", headers=AUTH)
        assert response.status_code == 503


def test_source_crud_and_explicit_rights_gate(monkeypatch, tmp_path):
    with setup(monkeypatch, tmp_path) as client:
        initial = client.get("/api/v1/admin/sources", headers=AUTH).json()["items"]
        assert len(initial) == 20
        body = {
            "id": "test-news-en", "name": "Test News",
            "type": "newsroom", "regions": ["GLOBAL"], "languages": ["en"],
            "site": "https://testnews.example.org/",
            "priority": "pilot", "discovery_method": "rss",
            "feed_url": "https://testnews.example.org/feed.xml", "active": True,
        }
        create = client.post("/api/v1/admin/sources", headers=AUTH, json=body)
        assert create.status_code == 201
        assert create.json()["enabled"] is False
        assert client.post("/api/v1/admin/sources", headers=AUTH, json=body).status_code == 409
        unlicensed = client.post("/api/v1/sources/test-news-en/sync")
        assert unlicensed.status_code == 503

        grant = {
            "permission_recorded": True,
            "permission_reference": "Documented test-only permission contract",
            "approved_by": "Local test reviewer",
            "reviewed_on": "2026-10-20",
            "expires_on": "2099-01-01",
            "adapter": "feed",
        }
        response = client.put(
            "/api/v1/admin/sources/test-news-en/grant", headers=AUTH, json=grant
        )
        assert response.status_code == 200
        assert response.json()["enabled"] is True
        assert client.get("/api/v1/sources/test-news-en").json()["enabled"] is True

        modified = {**body, "feed_url": "https://testnews.example.org/new-feed.xml"}
        result = client.put(
            "/api/v1/admin/sources/test-news-en", headers=AUTH, json=modified
        )
        assert result.status_code == 200
        assert result.json()["grant_reset"] is True
        assert client.get("/api/v1/sources/test-news-en").json()["enabled"] is False

        # Re-record reviewed grant for the new endpoint.
        assert client.put(
            "/api/v1/admin/sources/test-news-en/grant", headers=AUTH, json=grant
        ).json()["enabled"] is True

        assert client.delete(
            "/api/v1/admin/sources/test-news-en", headers=AUTH
        ).status_code == 200
        assert client.get("/api/v1/sources/test-news-en").status_code == 404
        assert len(client.get("/api/v1/sources").json()["items"]) == 20


def test_no_self_attested_grant_without_details(monkeypatch, tmp_path):
    with setup(monkeypatch, tmp_path) as client:
        result = client.put(
            "/api/v1/admin/sources/rainews-it/grant",
            headers=AUTH,
            json={"permission_recorded": True},
        )
        assert result.status_code == 422
        assert client.get("/api/v1/sources/rainews-it").json()["enabled"] is False


def test_grant_revocation_sticks_even_if_legacy_grant_exists(monkeypatch, tmp_path):
    with setup(monkeypatch, tmp_path) as client:
        legacy = {
            "sources": {"rainews-it": {
                "permission_recorded": True,
                "allowed_uses": ["metadata_discovery"],
                "permission_reference": "Only a mocked legacy permission",
                "approved_by": "Test",
                "reviewed_on": "2026-10-20",
                "approved_host": "www.rainews.it",
            }}
        }
        (tmp_path / "no-grants.json").write_text(json.dumps(legacy))
        assert client.get("/api/v1/sources/rainews-it").json()["enabled"] is True
        revoked = client.put(
            "/api/v1/admin/sources/rainews-it/grant", headers=AUTH,
            json={"permission_recorded": False}
        )
        assert revoked.status_code == 200
        assert revoked.json()["enabled"] is False


def test_ai_key_encrypted_and_never_returned(monkeypatch, tmp_path):
    with setup(monkeypatch, tmp_path) as client:
        key = "sk-secret-is-only-for-testing-do-not-use"
        added = client.put("/api/v1/admin/ai", headers=AUTH, json={
            "provider": "openai", "model": "gpt-test", "api_key": key, "active": True
        })
        assert added.status_code == 200
        assert added.json()["has_key"] is True
        assert key not in added.text

        listing = client.get("/api/v1/admin/ai", headers=AUTH)
        assert listing.json()["items"][0]["provider"] == "openai"
        assert key not in listing.text
        with connection() as conn:
            encrypted = conn.execute(
                "SELECT key_ciphertext FROM admin_ai WHERE provider='openai'"
            ).fetchone()["key_ciphertext"]
        assert key not in encrypted
        assert encrypted.startswith("gAAAA")

        updated = client.put("/api/v1/admin/ai", headers=AUTH, json={
            "provider": "openai", "model": "gpt-other", "active": True
        })
        assert updated.status_code == 200
        with connection() as conn:
            assert conn.execute(
                "SELECT key_ciphertext FROM admin_ai WHERE provider='openai'"
            ).fetchone()["key_ciphertext"] == encrypted

        removed = client.delete("/api/v1/admin/ai/openai", headers=AUTH)
        assert removed.status_code == 200
        assert client.get("/api/v1/admin/ai", headers=AUTH).json()["items"] == []


def test_ai_connection_uses_fixed_endpoint_and_no_article_body(monkeypatch, tmp_path):
    from afondo import admin_api

    class Response:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def read(self, _):
            return b'{"data": []}'

    seen = {}

    class Opener:
        def open(self, request, timeout):
            seen["url"] = request.full_url
            seen["header"] = request.get_header("Authorization")
            return Response()

    monkeypatch.setattr(admin_api.urllib.request, "build_opener", lambda *_: Opener())
    with setup(monkeypatch, tmp_path) as client:
        client.put("/api/v1/admin/ai", headers=AUTH, json={
            "provider": "openai", "model": "gpt-test", "api_key": "sk-mock-key"
        })
        tested = client.post("/api/v1/admin/ai/openai/test", headers=AUTH)
        assert tested.status_code == 200
        assert tested.json()["connected"] is True
        assert seen["url"] == "https://api.openai.com/v1/models"
        assert seen["header"] == "Bearer sk-mock-key"


def test_ai_credential_requires_master_key(monkeypatch, tmp_path):
    with setup(monkeypatch, tmp_path) as client:
        monkeypatch.delenv("AFONDO_ENCRYPTION_KEY")
        result = client.put("/api/v1/admin/ai", headers=AUTH, json={
            "provider": "gemini", "model": "gemini-3.5-flash",
            "api_key": "mock-secret", "active": True,
        })
        assert result.status_code == 503
        assert client.get("/api/v1/admin/ai", headers=AUTH).json()["items"] == []


def test_active_provider_is_unique(monkeypatch, tmp_path):
    with setup(monkeypatch, tmp_path) as client:
        for provider in ("openai", "anthropic"):
            response = client.put("/api/v1/admin/ai", headers=AUTH, json={
                "provider": provider, "model": "mock-model",
                "api_key": "mock-secret-" + provider, "active": True
            })
            assert response.status_code == 200
        items = client.get("/api/v1/admin/ai", headers=AUTH).json()["items"]
        assert len([item for item in items if item["active"]]) == 1
        assert next(item for item in items if item["active"])["provider"] == "anthropic"


def test_admin_rejects_plain_http_remote_host(monkeypatch, tmp_path):
    with setup(monkeypatch, tmp_path):
        with TestClient(app, base_url="http://afondo.example.com") as client:
            result = client.get("/api/v1/admin/status", headers=AUTH)
            assert result.status_code == 403
