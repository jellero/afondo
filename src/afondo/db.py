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
            CREATE TABLE IF NOT EXISTS ai_evidence_leads (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              candidate_id TEXT NOT NULL REFERENCES ai_candidates(id) ON DELETE CASCADE,
              discovered_item_id INTEGER NOT NULL REFERENCES discovered_items(id) ON DELETE CASCADE,
              source_id TEXT NOT NULL,
              shared_terms TEXT NOT NULL,
              rank_score REAL NOT NULL,
              UNIQUE(candidate_id, discovered_item_id)
            );
            CREATE INDEX IF NOT EXISTS idx_ai_leads_candidate ON ai_evidence_leads(candidate_id);
            CREATE TABLE IF NOT EXISTS article_processing_grants (
              article_id TEXT PRIMARY KEY REFERENCES articles(id) ON DELETE CASCADE,
              allowed INTEGER NOT NULL DEFAULT 0,
              basis TEXT NOT NULL DEFAULT '',
              checked_by TEXT NOT NULL DEFAULT '',
              checked_at TEXT NOT NULL,
              expires_on TEXT
            );
            CREATE TABLE IF NOT EXISTS verified_attributions (
              article_id TEXT PRIMARY KEY REFERENCES articles(id) ON DELETE CASCADE,
              outlet_confirmed INTEGER NOT NULL DEFAULT 0,
              byline_confirmed INTEGER NOT NULL DEFAULT 0,
              checked_by TEXT NOT NULL,
              source_note TEXT NOT NULL,
              checked_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS editorial_review_events (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              article_id TEXT NOT NULL REFERENCES articles(id) ON DELETE CASCADE,
              event_kind TEXT NOT NULL,
              status TEXT NOT NULL,
              sensationalistic INTEGER NOT NULL DEFAULT 0,
              out_of_context INTEGER NOT NULL DEFAULT 0,
              note TEXT NOT NULL DEFAULT '',
              evidence_url TEXT,
              change_reason TEXT NOT NULL DEFAULT '',
              happened_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_editorial_events_article
              ON editorial_review_events(article_id, happened_at);
            CREATE TABLE IF NOT EXISTS evidence_documents (
              id TEXT PRIMARY KEY,
              title TEXT NOT NULL,
              url TEXT NOT NULL,
              publisher TEXT NOT NULL,
              source_group TEXT NOT NULL,
              source_kind TEXT NOT NULL,
              excerpt TEXT NOT NULL,
              locator TEXT NOT NULL,
              permission_reference TEXT NOT NULL,
              recorded_by TEXT NOT NULL,
              publication_date TEXT,
              status TEXT NOT NULL CHECK (
                status IN ('submitted','approved','rejected','retired')
              ),
              created_at TEXT NOT NULL,
              reviewed_at TEXT,
              reviewed_by TEXT,
              review_note TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_evidence_documents_status
              ON evidence_documents(status,created_at);
            CREATE TABLE IF NOT EXISTS document_claim_matches (
              id TEXT PRIMARY KEY,
              candidate_id TEXT NOT NULL REFERENCES ai_candidates(id) ON DELETE CASCADE,
              document_id TEXT NOT NULL REFERENCES evidence_documents(id),
              match_fraction REAL NOT NULL,
              overlap_terms TEXT NOT NULL,
              signals_json TEXT NOT NULL,
              review_status TEXT NOT NULL DEFAULT 'pending',
              reviewer_note TEXT,
              reviewed_by TEXT,
              reviewed_at TEXT,
              created_at TEXT NOT NULL,
              UNIQUE(candidate_id,document_id)
            );
            CREATE INDEX IF NOT EXISTS idx_context_matches_status
              ON document_claim_matches(review_status,created_at);
            CREATE TABLE IF NOT EXISTS document_evidence_links (
              match_id TEXT PRIMARY KEY REFERENCES document_claim_matches(id),
              evidence_id TEXT UNIQUE NOT NULL REFERENCES evidence(id),
              document_id TEXT NOT NULL REFERENCES evidence_documents(id)
            );
            CREATE TABLE IF NOT EXISTS editorial_reviews (
              article_id TEXT PRIMARY KEY REFERENCES articles(id) ON DELETE CASCADE,
              topic TEXT,
              status TEXT NOT NULL DEFAULT 'draft',
              featured INTEGER NOT NULL DEFAULT 0,
              sensationalistic INTEGER NOT NULL DEFAULT 0,
              out_of_context INTEGER NOT NULL DEFAULT 0,
              note TEXT NOT NULL DEFAULT '',
              evidence_url TEXT,
              updated_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_editorial_status ON editorial_reviews(status,featured);
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
