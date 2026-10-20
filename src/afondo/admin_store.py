"""SQLite-backed administrator configuration.

Catalog overrides are different from source grants: listing a source does not
authorize harvesting. Secrets are stored encrypted; never returned to clients.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json

from afondo.db import connection


def iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def source_overrides() -> tuple[dict[str, dict], set[str]]:
    with connection() as conn:
        exists = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='admin_sources'"
        ).fetchone()
        if not exists:
            return {}, set()
        rows = conn.execute("SELECT id, definition_json, deleted FROM admin_sources").fetchall()
    return (
        {r["id"]: json.loads(r["definition_json"]) for r in rows if not r["deleted"]},
        {r["id"] for r in rows if r["deleted"]},
    )


def admin_grants() -> dict[str, dict]:
    with connection() as conn:
        exists = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='admin_source_grants'"
        ).fetchone()
        if not exists:
            return {}
        rows = conn.execute("SELECT source_id, grant_json FROM admin_source_grants").fetchall()
    return {r["source_id"]: json.loads(r["grant_json"]) for r in rows}


def upsert_source(definition: dict, *, invalidate_grant: bool) -> None:
    with connection() as conn:
        conn.execute(
            """INSERT INTO admin_sources (id, definition_json, deleted, updated_at)
               VALUES (?, ?, 0, ?)
               ON CONFLICT(id) DO UPDATE SET definition_json=excluded.definition_json,
               deleted=0, updated_at=excluded.updated_at""",
            (definition["id"], json.dumps(definition, ensure_ascii=False), iso_now()),
        )
        if invalidate_grant:
            # Keep explicit revocation even if a legacy JSON grant was configured.
            conn.execute(
                """INSERT INTO admin_source_grants(source_id,grant_json,updated_at)
                   VALUES (?, ?, ?)
                   ON CONFLICT(source_id) DO UPDATE SET grant_json=excluded.grant_json,
                   updated_at=excluded.updated_at""",
                (definition["id"], json.dumps({"permission_recorded": False}), iso_now()),
            )


def delete_source(source_id: str) -> None:
    with connection() as conn:
        conn.execute(
            """INSERT INTO admin_sources(id, definition_json, deleted, updated_at)
               VALUES (?, '{}', 1, ?)
               ON CONFLICT(id) DO UPDATE SET deleted=1, updated_at=excluded.updated_at""",
            (source_id, iso_now()),
        )
        conn.execute(
            """INSERT INTO admin_source_grants(source_id,grant_json,updated_at)
               VALUES (?, ?, ?)
               ON CONFLICT(source_id) DO UPDATE SET grant_json=excluded.grant_json,
               updated_at=excluded.updated_at""",
            (source_id, '{"permission_recorded":false}', iso_now()),
        )


def save_grant(source_id: str, config: dict) -> None:
    with connection() as conn:
        conn.execute(
            """INSERT INTO admin_source_grants(source_id,grant_json,updated_at)
               VALUES (?, ?, ?)
               ON CONFLICT(source_id) DO UPDATE SET grant_json=excluded.grant_json,
               updated_at=excluded.updated_at""",
            (source_id, json.dumps(config, ensure_ascii=False), iso_now()),
        )


def ai_configs() -> list[dict]:
    with connection() as conn:
        return [dict(row) for row in conn.execute(
            "SELECT provider, model, key_ciphertext, active, updated_at FROM admin_ai"
            " ORDER BY provider"
        ).fetchall()]


def ai_config(provider: str) -> dict | None:
    with connection() as conn:
        row = conn.execute(
            "SELECT provider, model, key_ciphertext, active, updated_at "
            "FROM admin_ai WHERE provider = ?", (provider,),
        ).fetchone()
    return dict(row) if row else None


def save_ai(provider: str, model: str, encrypted_key: str | None, active: bool) -> None:
    with connection() as conn:
        previous = conn.execute(
            "SELECT key_ciphertext FROM admin_ai WHERE provider = ?", (provider,)
        ).fetchone()
        key = encrypted_key if encrypted_key is not None else (
            previous["key_ciphertext"] if previous else None
        )
        if not key:
            raise ValueError("API key required for this provider")
        if active:
            conn.execute("UPDATE admin_ai SET active = 0")
        conn.execute(
            """INSERT INTO admin_ai (provider, model, key_ciphertext, active, updated_at)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(provider) DO UPDATE SET model=excluded.model,
               key_ciphertext=excluded.key_ciphertext,
               active=excluded.active, updated_at=excluded.updated_at""",
            (provider, model, key, int(active), iso_now()),
        )


def delete_ai(provider: str) -> bool:
    with connection() as conn:
        result = conn.execute("DELETE FROM admin_ai WHERE provider = ?", (provider,))
    return result.rowcount > 0
