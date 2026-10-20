"""Deterministic tests: never call live providers or charge API credits."""
import json

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from afondo.ai_extraction import (
    ExtractOutput, ExtractionError, SCHEMA, extract, request_spec, validated_candidates
)
from afondo.db import connection
from afondo.main import app


ADMIN = {"X-Admin-Token": "test-admin-token-very-long-for-workflow"}


def setup(monkeypatch, tmp_path):
    monkeypatch.setenv("AFONDO_DB_PATH", str(tmp_path / "ai.sqlite3"))
    monkeypatch.setenv("AFONDO_SOURCE_GRANTS", str(tmp_path / "no-grants.json"))
    monkeypatch.setenv("AFONDO_ADMIN_TOKEN", ADMIN["X-Admin-Token"])
    monkeypatch.setenv("AFONDO_ENCRYPTION_KEY", Fernet.generate_key().decode())
    return TestClient(app)


def sample_article(client):
    first = (
        "Il rapporto del comune indica una crescita del 12 percento "
        "nelle spese del settore pubblico durante l'ultimo trimestre."
    )
    second = (
        "Secondo gli esperti, il risultato potrebbe avere un impatto "
        "significativo sulle famiglie nei prossimi mesi."
    )
    response = client.post("/api/v1/articles", json={
        "title": "Analisi di un rapporto pubblico",
        "language": "it",
        "text": first + " " + second,
    })
    assert response.status_code == 201
    return response.json(), first, second


def fake_extraction(article, _provider=None):
    quote = "una crescita del 12 percento"
    assert quote in article["body"]
    start = article["body"].find(quote)
    return {
        "provider": "openai", "model": "mock-model",
        "candidates": [
            {"quote": quote, "claim": "Le spese sono cresciute del 12%",
             "kind": "factual", "start_offset": start, "end_offset": start + len(quote)}
        ],
        "unanchored_or_duplicate": 0, "input_tokens": 123,
        "output_tokens": 42, "prompt_version": "claim-extraction-v1",
    }


def test_ai_extraction_review_and_quota(monkeypatch, tmp_path):
    from afondo import ai_workflow

    monkeypatch.setattr(ai_workflow, "extract", fake_extraction)
    with setup(monkeypatch, tmp_path) as client:
        article, *_ = sample_article(client)
        article_id = article["id"]
        configured = client.put("/api/v1/admin/ai", json={
            "provider": "openai", "model": "mock-model",
            "api_key": "fake-secret-value-for-test", "active": True
        }, headers=ADMIN)
        assert configured.status_code == 200

        response = client.post(f"/api/v1/admin/articles/{article_id}/ai-extract", headers=ADMIN)
        assert response.status_code == 200
        data = response.json()
        assert len(data["candidates"]) == 1
        assert data["runs"][0]["status"] == "completed"
        assert data["runs"][0]["input_tokens"] == 123
        assert "key_ciphertext" not in response.text
        candidate_id = data["candidates"][0]["id"]

        throttled = client.post(f"/api/v1/admin/articles/{article_id}/ai-extract", headers=ADMIN)
        assert throttled.status_code == 429
        assert client.post(
            f"/api/v1/admin/ai-candidates/{candidate_id}/decision?decision=accept",
        ).status_code == 401

        accepted = client.post(
            f"/api/v1/admin/ai-candidates/{candidate_id}/decision?decision=accept",
            headers=ADMIN,
        )
        assert accepted.status_code == 200
        assert accepted.json()["claim_id"]
        assert client.post(
            f"/api/v1/admin/ai-candidates/{candidate_id}/decision?decision=accept",
            headers=ADMIN,
        ).status_code == 409
        refreshed = client.get(f"/api/v1/articles/{article_id}").json()
        assert any(claim["text"] == "una crescita del 12 percento" for claim in refreshed["claims"])
        # Human accepted a candidate, not a factual verdict.
        assert refreshed["assessment"]["score"] is None

        with connection() as conn:
            count = conn.execute("SELECT COUNT(*) FROM ai_analysis_runs").fetchone()[0]
        assert count == 1


def test_provider_not_configured_means_no_external_call(monkeypatch, tmp_path):
    with setup(monkeypatch, tmp_path) as client:
        article, *_ = sample_article(client)
        failed = client.post(
            f"/api/v1/admin/articles/{article['id']}/ai-extract", headers=ADMIN,
        )
        assert failed.status_code == 409
        with connection() as conn:
            assert conn.execute("SELECT COUNT(*) FROM ai_analysis_runs").fetchone()[0] == 0


def test_no_oversize_ai_request(monkeypatch, tmp_path):
    with setup(monkeypatch, tmp_path) as client:
        client.put("/api/v1/admin/ai", json={
            "provider": "openai", "model": "mock-model",
            "api_key": "mock-secret", "active": True,
        }, headers=ADMIN)
        article = client.post("/api/v1/articles", json={
            "title": "Articolo troppo lungo", "text": "Lorem ipsum. " * 1500,
        }).json()
        response = client.post(
            f"/api/v1/admin/articles/{article['id']}/ai-extract", headers=ADMIN
        )
        assert response.status_code == 422
        with connection() as conn:
            assert conn.execute("SELECT COUNT(*) FROM ai_analysis_runs").fetchone()[0] == 0


def test_failed_inference_not_reported_as_valid(monkeypatch, tmp_path):
    from afondo import ai_workflow
    def broken(_article, _provider=None):
        raise ExtractionError("Provider HTTP 429")
    monkeypatch.setattr(ai_workflow, "extract", broken)
    with setup(monkeypatch, tmp_path) as client:
        article, *_ = sample_article(client)
        client.put("/api/v1/admin/ai", json={
            "provider": "openai", "model": "mock-model", "api_key": "test", "active": True
        }, headers=ADMIN)
        response = client.post(
            f"/api/v1/admin/articles/{article['id']}/ai-extract", headers=ADMIN
        )
        assert response.status_code == 502
        assert "Provider HTTP 429" in response.text
        details = client.get(
            f"/api/v1/admin/articles/{article['id']}/ai", headers=ADMIN
        ).json()
        assert details["runs"][0]["status"] == "failed"
        assert details["candidates"] == []


def test_verbatim_quote_validation_discards_hallucinations():
    body = "Il Ministero ha diffuso un comunicato con numeri verificabili a fine mese."
    valid_quote = "un comunicato con numeri verificabili"
    generated = ExtractOutput.model_validate({
        "claims": [
            {"quote": valid_quote, "claim": "Pubblicazione di numeri ufficiali", "kind": "factual"},
            {"quote": "Questo fatto NON esiste nel testo", "claim": "Una notizia falsa", "kind": "factual"}
        ]
    })
    retained = validated_candidates(body, generated)
    assert len(retained) == 1
    assert body[retained[0]["start_offset"]:retained[0]["end_offset"]] == valid_quote


@pytest.mark.parametrize("provider,expected", [
    ("openai", "https://api.openai.com/v1/responses"),
    ("anthropic", "https://api.anthropic.com/v1/messages"),
    ("gemini", "https://generativelanguage.googleapis.com/v1beta/models/gemini-test:generateContent"),
])
def test_fixed_provider_origins_and_structured_payload(provider, expected):
    entry = {"provider": provider, "model": "gemini-test" if provider == "gemini" else "model-test"}
    article = {"title": "Demo", "language": "it", "body": "Una frase verificabile."}
    url, headers, payload = request_spec(entry, "safe-placeholder-secret", article)
    assert url == expected
    assert SCHEMA["required"] == ["claims"]
    assert "safe-placeholder-secret" not in json.dumps(payload)
    assert headers["Content-Type"] == "application/json"
    if provider == "openai":
        assert payload["store"] is False
        assert payload["text"]["format"]["strict"] is True
    elif provider == "anthropic":
        assert payload["output_config"]["format"]["type"] == "json_schema"
    else:
        assert payload["generationConfig"]["responseFormat"]["text"]["schema"] == SCHEMA


def test_provider_response_parsing_rejects_invalid_json():
    from afondo.ai_extraction import _parse_provider_response
    with pytest.raises(ExtractionError):
        _parse_provider_response("openai", {
            "status": "completed",
            "output": [{"type": "message",
                        "content": [{"type": "output_text", "text": '{"claims": "garbage"}'}]}],
        })
