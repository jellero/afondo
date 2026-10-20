"""SQLite MVP persistence. Replace with migrations/PostgreSQL before multi-worker production."""

from contextlib import contextmanager
import os
from pathlib import Path
import sqlite3
from typing import Iterator


def _path() -> Path:
    return Path(os.getenv("AFONDO_DB_PATH", "data/afondo.sqlite3"))


@contextmanager
def connection() -> Iterator[sqlite3.Connection]:
    path = _path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def initialize() -> None:
    with connection() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS articles (
              id TEXT PRIMARY KEY,
              title TEXT NOT NULL,
              body TEXT NOT NULL,
              source_url TEXT,
              language TEXT NOT NULL,
              author TEXT,
              outlet TEXT,
              created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS claims (
              id TEXT PRIMARY KEY,
              article_id TEXT NOT NULL REFERENCES articles(id) ON DELETE CASCADE,
              position INTEGER NOT NULL,
              text TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_claims_article ON claims(article_id);
            CREATE TABLE IF NOT EXISTS evidence (
              id TEXT PRIMARY KEY,
              claim_id TEXT NOT NULL REFERENCES claims(id) ON DELETE CASCADE,
              url TEXT NOT NULL,
              stance TEXT NOT NULL,
              source_kind TEXT NOT NULL,
              source_group TEXT NOT NULL,
              note TEXT NOT NULL,
              review_status TEXT NOT NULL DEFAULT 'pending',
              created_at TEXT NOT NULL,
              reviewed_at TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_evidence_claim ON evidence(claim_id);
            CREATE TABLE IF NOT EXISTS discovered_items (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              source_id TEXT NOT NULL,
              title TEXT NOT NULL,
              url TEXT NOT NULL,
              published_at TEXT,
              discovered_at TEXT NOT NULL,
              external_id TEXT,
              UNIQUE(source_id, url)
            );
            CREATE INDEX IF NOT EXISTS idx_discovered_source_time
              ON discovered_items(source_id, discovered_at);
            CREATE TABLE IF NOT EXISTS ai_analysis_runs (
              id TEXT PRIMARY KEY,
              article_id TEXT NOT NULL REFERENCES articles(id) ON DELETE CASCADE,
              provider TEXT NOT NULL,
              model TEXT NOT NULL,
              prompt_version TEXT NOT NULL,
              status TEXT NOT NULL,
              started_at TEXT NOT NULL,
              finished_at TEXT,
              input_sha256 TEXT NOT NULL,
              input_chars INTEGER NOT NULL,
              input_tokens INTEGER,
              output_tokens INTEGER,
              candidate_count INTEGER NOT NULL DEFAULT 0,
              rejected_candidate_count INTEGER NOT NULL DEFAULT 0
            );
            CREATE INDEX IF NOT EXISTS idx_ai_runs_article
              ON ai_analysis_runs(article_id, started_at);
            CREATE INDEX IF NOT EXISTS idx_ai_runs_started
              ON ai_analysis_runs(started_at);
            CREATE TABLE IF NOT EXISTS ai_candidates (
              id TEXT PRIMARY KEY,
              run_id TEXT NOT NULL REFERENCES ai_analysis_runs(id),
              article_id TEXT NOT NULL REFERENCES articles(id) ON DELETE CASCADE,
              quote TEXT NOT NULL,
              normalized_claim TEXT NOT NULL,
              kind TEXT NOT NULL,
              start_offset INTEGER NOT NULL,
              end_offset INTEGER NOT NULL,
              review_status TEXT NOT NULL DEFAULT 'pending',
              claim_id TEXT REFERENCES claims(id)
            );
            CREATE INDEX IF NOT EXISTS idx_ai_candidates_run ON ai_candidates(run_id);
            CREATE TABLE IF NOT EXISTS admin_sources (
              id TEXT PRIMARY KEY,
              definition_json TEXT NOT NULL,
              deleted INTEGER NOT NULL DEFAULT 0,
              updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS admin_source_grants (
              source_id TEXT PRIMARY KEY,
              grant_json TEXT NOT NULL,
              updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS admin_ai (
              provider TEXT PRIMARY KEY,
              model TEXT NOT NULL,
              key_ciphertext TEXT NOT NULL,
              active INTEGER NOT NULL DEFAULT 0,
              updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS source_sync_state (
              source_id TEXT PRIMARY KEY,
              last_sync TEXT NOT NULL,
              status TEXT NOT NULL,
              items_seen INTEGER NOT NULL DEFAULT 0,
              etag TEXT NOT NULL DEFAULT '',
              last_modified TEXT NOT NULL DEFAULT '',
              error TEXT NOT NULL DEFAULT ''
            );
            """
        )
