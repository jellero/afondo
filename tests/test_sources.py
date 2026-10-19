"""Offline tests for AFONDO source connectors; never call live publisher sites."""

import json

import pytest
from fastapi.testclient import TestClient

from afondo.db import initialize
from afondo.feed_parser import canonical_url, parse_feed, parse_json_api
from afondo.main import app
from afondo.source_ingestion import SourceSyncError, discovered_items, sync_source
from afondo.source_registry import (
    SourceConfigError, configured_sources, get_source, safe_source_url,
)


RSS = b"""<?xml version="1.0"?>
<rss version="2.0"><channel><title>Fixture</title>
<item><title>Notizia di prova A</title><link>https://example.org/a?utm_source=feed</link>
<pubDate>Mon, 19 Oct 2026 10:00:00 GMT</pubDate></item>
<item><title>Notizia di prova A</title><link>https://example.org/a</link></item>
<item><title>Notizia di prova B</title><link>https://example.org/b</link></item>
</channel></rss>"""


def grant(tmp_path, monkeypatch, source_id="rainews-it", adapter="feed", endpoint=None):
    values = {
        "permission_recorded": True,
        "allowed_uses": ["metadata_discovery"],
        "permission_reference": "Example documented license ref ONLY for fixture tests",
        "approved_by": "Test operator",
        "reviewed_on": "2026-10-19",
        "expires_on": "2099-10-19",
        "approved_host": "www.rainews.it" if source_id == "rainews-it" else "partner.example.org",
    }
    if endpoint:
        values["endpoint"] = endpoint
        values["adapter"] = adapter
    path = tmp_path / "grants.json"
    path.write_text(json.dumps({"sources": {source_id: values}}), encoding="utf-8")
    monkeypatch.setenv("AFONDO_SOURCE_GRANTS", str(path))
    return path


def test_catalog_has_20_distinct_registered_sources(monkeypatch, tmp_path):
    monkeypatch.setenv("AFONDO_SOURCE_GRANTS", str(tmp_path / "no-grants.json"))
    sources = configured_sources()
    assert len(sources) == 20
    assert len({item["id"] for item in sources}) == 20
    assert all(not item["enabled"] for item in sources)
    assert {item["type"] for item in sources} == {
        "newsroom", "news_agency", "primary_evidence", "factcheck_reference"
    }


def test_public_grants_are_required(monkeypatch, tmp_path):
    grant(tmp_path, monkeypatch)
    source = get_source("rainews-it")
    assert source["enabled"] is True
    assert safe_source_url(source) == "https://www.rainews.it/rss/tutti"
    assert get_source("ap-en")["enabled"] is False


def test_grant_requires_exact_approved_host(monkeypatch, tmp_path):
    path = grant(tmp_path, monkeypatch)
    values = json.loads(path.read_text())
    values["sources"]["rainews-it"]["approved_host"] = "evil.example"
    path.write_text(json.dumps(values))
    assert get_source("rainews-it")["enabled"] is False
    with pytest.raises(SourceConfigError):
        safe_source_url(get_source("rainews-it"))


def test_rss_parser_canonicalizes_and_deduplicates_urls():
    items = parse_feed(RSS)
    assert [entry["url"] for entry in items] == ["https://example.org/a", "https://example.org/b"]
    assert items[0]["published_at"] == "2026-10-19T10:00:00+00:00"
    assert canonical_url("javascript:alert(1)") is None
    assert canonical_url("https://u:p@example.org/secret") is None


def test_atom_parser():
    atom = b"""<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom">
    <entry><title>Atom item</title><link rel="alternate" href="https://example.org/item" />
    <published>2026-10-19T12:00:00Z</published></entry></feed>"""
    items = parse_feed(atom)
    assert len(items) == 1
    assert items[0]["published_at"] == "2026-10-19T12:00:00+00:00"


def test_rdf_parser():
    rdf = b"""<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">
    <item><title>RDF item</title><link>https://example.org/rdf</link></item>
    </rdf:RDF>"""
    assert parse_feed(rdf)[0]["title"] == "RDF item"


def test_reject_xml_entities():
    with pytest.raises(ValueError):
        parse_feed(b'<!DOCTYPE rss [<!ENTITY x SYSTEM "file:///etc/passwd">]><rss>&x;</rss>')


def test_json_partner_api_parser():
    payload = json.dumps({
        "response": {"results": [
            {"webTitle": "News from licensed partner", "webUrl": "https://example.org/a",
             "webPublicationDate": "2026-10-19T12:45:00Z", "id": "abc"}
        ]}
    }).encode()
    schema = {
        "items_path": "response.results", "title_field": "webTitle", "url_field": "webUrl",
        "published_field": "webPublicationDate", "id_field": "id"
    }
    assert parse_json_api(payload, schema)[0]["external_id"] == "abc"


def test_metadata_sync_is_idempotent_with_offline_fixture(monkeypatch, tmp_path):
    monkeypatch.setenv("AFONDO_DB_PATH", str(tmp_path / "db.sqlite3"))
    grant(tmp_path, monkeypatch)
    initialize()
    source = get_source("rainews-it")
    calls = []

    def fake_fetch(url, headers):
        calls.append((url, headers))
        return RSS, {"etag": '"fixture-v1"'}, False

    first = sync_source(source, fetch=fake_fetch)
    assert first["new_items"] == 2
    assert len(discovered_items(source_id=source["id"])) == 2
    with pytest.raises(SourceSyncError, match="cooldown"):
        sync_source(source, fetch=fake_fetch)
    second = sync_source(source, fetch=fake_fetch, force=True)
    assert second["new_items"] == 0
    assert len(discovered_items(source_id=source["id"])) == 2
    assert calls[1][1]["If-None-Match"] == '"fixture-v1"'


def test_source_api_denies_unlicensed_sync_and_lists_registry(monkeypatch, tmp_path):
    monkeypatch.setenv("AFONDO_DB_PATH", str(tmp_path / "db.sqlite3"))
    monkeypatch.setenv("AFONDO_SOURCE_GRANTS", str(tmp_path / "missing.json"))
    monkeypatch.setenv("AFONDO_INGEST_TOKEN", "test-ingest-token")
    with TestClient(app) as client:
        response = client.get("/api/v1/sources")
        assert response.status_code == 200
        assert len(response.json()["items"]) == 20
        assert "sources" in client.get("/sources").text
        forbidden = client.post("/api/v1/sources/rainews-it/sync")
        assert forbidden.status_code == 403
        disabled = client.post(
            "/api/v1/sources/rainews-it/sync",
            headers={"X-Ingest-Token": "test-ingest-token"},
        )
        assert disabled.status_code == 409
        assert client.get("/api/v1/discoveries").json()["items"] == []


def test_json_api_can_be_configured_but_is_never_enabled_implicitly(monkeypatch, tmp_path):
    endpoint = "https://partner.example.org/official/v1/content"
    grant(tmp_path, monkeypatch, source_id="guardian-en", adapter="json_api", endpoint=endpoint)
    source = get_source("guardian-en")
    assert source["adapter"] == "json_api"
    assert source["enabled"] is True
    assert safe_source_url(source) == endpoint
    # The grant in this test is mock data. It must not be used for a real request.
