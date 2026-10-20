"""AFONDO admin-only authentication and encrypted-at-rest provider API keys.

Administrative token and Fernet master key are supplied only by the server
environment. The browser holds the admin token in memory for this session.
"""
from __future__ import annotations

import os
import secrets

from cryptography.fernet import Fernet, InvalidToken
from fastapi import Header, HTTPException, Request


def require_admin(
    request: Request,
    x_admin_token: str | None = Header(default=None),
) -> None:
    token = os.getenv("AFONDO_ADMIN_TOKEN", "")
    if len(token) < 24:
        raise HTTPException(status_code=503, detail="Admin not configured")
    # Never encourage credentials over a remotely served plain HTTP connection.
    if request.url.scheme != "https" and request.url.hostname not in (
        "localhost", "127.0.0.1", "::1", "testserver"
    ):
        raise HTTPException(status_code=403, detail="Admin requires HTTPS")
    if not x_admin_token or not secrets.compare_digest(x_admin_token, token):
        raise HTTPException(status_code=401, detail="Unauthorized",
                            headers={"WWW-Authenticate": "AFONDO-Token"})


def cipher() -> Fernet:
    master = os.getenv("AFONDO_ENCRYPTION_KEY", "")
    if not master:
        raise HTTPException(status_code=503, detail="Encryption master key not configured")
    try:
        return Fernet(master.encode("ascii"))
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=503, detail="Encryption master key invalid") from exc


def encrypt_secret(raw: str) -> str:
    return cipher().encrypt(raw.encode("utf-8")).decode("ascii")


def decrypt_secret(value: str) -> str:
    try:
        return cipher().decrypt(value.encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError) as exc:
        raise HTTPException(status_code=503, detail="Cannot decrypt stored credentials") from exc
