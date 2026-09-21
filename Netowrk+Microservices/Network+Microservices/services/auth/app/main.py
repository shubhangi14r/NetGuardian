"""Auth service -- issues and verifies tokens.

Reachable inside the compose network as http://auth:8000.
Only the gateway is published to the host; this service is internal.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
from typing import Any, Dict

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from shared import netkit

SERVICE = "auth"
SECRET = os.getenv("AUTH_SECRET", "dev-secret-change-me").encode()
TOKEN_TTL_S = int(os.getenv("TOKEN_TTL_S", "3600"))

# A tiny in-memory user table. A real deployment would put this in Postgres;
# keeping it in memory keeps the auth container dependency-free, which is what
# makes it a useful control in the failure demos.
USERS = {
    "admin": "admin123",
    "tej": "cn2026",
    "guest": "guest",
}

app = FastAPI(title="Auth Service", version="0.1.0")
logger, metrics = netkit.install(app, SERVICE)


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _sign(payload: bytes) -> str:
    return _b64(hmac.new(SECRET, payload, hashlib.sha256).digest())


def issue_token(username: str) -> str:
    body = json.dumps({"sub": username, "exp": int(time.time()) + TOKEN_TTL_S}).encode()
    return f"{_b64(body)}.{_sign(body)}"


def read_token(token: str) -> Dict[str, Any]:
    try:
        body_b64, signature = token.split(".", 1)
        body = _unb64(body_b64)
    except Exception:
        raise HTTPException(status_code=401, detail="malformed token")

    # compare_digest, not ==, so the check doesn't leak signature bytes by timing.
    if not hmac.compare_digest(signature, _sign(body)):
        raise HTTPException(status_code=401, detail="bad signature")

    claims = json.loads(body)
    if claims.get("exp", 0) < time.time():
        raise HTTPException(status_code=401, detail="token expired")
    return claims


class LoginRequest(BaseModel):
    username: str
    password: str


class VerifyRequest(BaseModel):
    token: str


@app.post("/login")
async def login(req: LoginRequest) -> Dict[str, Any]:
    expected = USERS.get(req.username)
    if expected is None or not hmac.compare_digest(expected, req.password):
        logger.info("login rejected", extra={"service": SERVICE, "fields": {"username": req.username}})
        raise HTTPException(status_code=401, detail="invalid credentials")

    logger.info("login ok", extra={"service": SERVICE, "fields": {"username": req.username}})
    return {"token": issue_token(req.username), "expires_in": TOKEN_TTL_S, "username": req.username}


@app.post("/verify")
async def verify(req: VerifyRequest) -> Dict[str, Any]:
    """Called server-to-server by inventory on every protected request.

    This is the hop that makes auth latency visible in inventory's numbers --
    useful when Person 4 looks for correlated anomalies across services.
    """
    claims = read_token(req.token)
    return {"valid": True, "username": claims["sub"], "expires_at": claims["exp"]}


@app.get("/")
async def root() -> Dict[str, Any]:
    return {"service": SERVICE, "endpoints": ["/login", "/verify", "/health", "/metrics"]}
