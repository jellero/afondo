"""Operator CLI cannot activate unlicensed feeds."""

from afondo.sync_sources import run


def test_dry_run_does_not_fetch_unlicensed_sources(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("AFONDO_DB_PATH", str(tmp_path / "sources.sqlite3"))
    monkeypatch.setenv("AFONDO_SOURCE_GRANTS", str(tmp_path / "missing.json"))
    assert run(dry_run=True) == 0
    output = capsys.readouterr().out
    assert output.count('"status": "skipped"') == 20
    assert '"status": "ready"' not in output


def test_unknown_source_does_not_fetch(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("AFONDO_DB_PATH", str(tmp_path / "sources.sqlite3"))
    monkeypatch.setenv("AFONDO_SOURCE_GRANTS", str(tmp_path / "missing.json"))
    assert run(source_ids={"not-a-real-feed"}, dry_run=False) == 2
    assert "Unknown source IDs" in capsys.readouterr().out
