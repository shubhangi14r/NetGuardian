"""Inventory service -- owns product stock, backed by Postgres.

Two network hops happen on a protected call:
  inventory -> auth      (HTTP, token verification)
  inventory -> postgres  (TCP/5432, data)
Both are instrumented so a failure in either is distinguishable in the logs.
"""

from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager
from typing import Any, Dict, List

import asyncpg
import httpx
from fastapi import Depends, FastAPI, Header, HTTPException, Request
from pydantic import BaseModel, Field

from shared import netkit

SERVICE = "inventory"
AUTH_URL = os.getenv("AUTH_URL", "http://auth:8000")
DB_DSN = os.getenv(
    "DATABASE_URL",
    "postgresql://shn:shn_password@postgres:5432/shn",
)

SEED_ITEMS = [
    ("SKU-1001", "Mechanical Keyboard", 4999, 25),
    ("SKU-1002", "27in Monitor", 18999, 8),
    ("SKU-1003", "USB-C Dock", 6499, 40),
    ("SKU-1004", "Noise Cancelling Headphones", 12999, 12),
]


async def _connect_with_retry(attempts: int = 30, delay_s: float = 2.0) -> asyncpg.Pool:
    """Postgres accepts TCP connections before it is ready to serve queries.

    depends_on alone does not cover that gap, so the service retries instead of
    crash-looping on first boot.
    """
    last: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            return await asyncpg.create_pool(DB_DSN, min_size=1, max_size=8, command_timeout=5)
        except Exception as exc:  # noqa: BLE001 - any driver error means "not up yet"
            last = exc
            await asyncio.sleep(delay_s)
    raise RuntimeError(f"postgres unreachable after {attempts} attempts: {last}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.pool = await _connect_with_retry()
    async with app.state.pool.acquire() as conn:
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS items (
                sku        TEXT PRIMARY KEY,
                name       TEXT NOT NULL,
                price_inr  INTEGER NOT NULL CHECK (price_inr >= 0),
                stock      INTEGER NOT NULL CHECK (stock >= 0)
            )
            """
        )
        await conn.executemany(
            "INSERT INTO items (sku, name, price_inr, stock) VALUES ($1, $2, $3, $4) "
            "ON CONFLICT (sku) DO NOTHING",
            SEED_ITEMS,
        )
    app.state.http = netkit.http_client()
    app.state.logger.info("inventory ready", extra={"service": SERVICE, "fields": {"auth_url": AUTH_URL}})
    try:
        yield
    finally:
        await app.state.http.aclose()
        await app.state.pool.close()


app = FastAPI(title="Inventory Service", version="0.1.0", lifespan=lifespan)
logger, metrics = netkit.install(app, SERVICE)


async def require_user(
    request: Request,
    authorization: str | None = Header(default=None),
) -> str:
    """Verify the bearer token by calling the auth service over HTTP."""
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="missing bearer token")
    token = authorization.split(" ", 1)[1]

    trace_id = getattr(request.state, "trace_id", "-")
    try:
        resp = await request.app.state.http.post(
            f"{AUTH_URL}/verify",
            json={"token": token},
            headers={netkit.TRACE_HEADER: trace_id},
        )
    except httpx.HTTPError as exc:
        # auth unreachable is a *network* fault, not a credential problem --
        # 503 keeps the two cases separable for the anomaly detector.
        metrics.record_dependency_failure()
        logger.warning(
            "auth unreachable",
            extra={"service": SERVICE, "fields": {"trace_id": trace_id, "error": type(exc).__name__}},
        )
        raise HTTPException(status_code=503, detail="auth service unreachable") from exc

    if resp.status_code == 401:
        raise HTTPException(status_code=401, detail="invalid token")
    if resp.status_code >= 500:
        metrics.record_dependency_failure()
        raise HTTPException(status_code=503, detail="auth service error")

    return resp.json()["username"]


class StockUpdate(BaseModel):
    delta: int = Field(..., description="Positive to restock, negative to sell")


@app.get("/items")
async def list_items(request: Request) -> Dict[str, Any]:
    """Public catalogue -- no token needed, so it stays useful when auth is down."""
    async with request.app.state.pool.acquire() as conn:
        rows = await conn.fetch("SELECT sku, name, price_inr, stock FROM items ORDER BY sku")
    return {"count": len(rows), "items": [dict(r) for r in rows]}


@app.get("/items/{sku}")
async def get_item(sku: str, request: Request) -> Dict[str, Any]:
    async with request.app.state.pool.acquire() as conn:
        row = await conn.fetchrow("SELECT sku, name, price_inr, stock FROM items WHERE sku = $1", sku)
    if row is None:
        raise HTTPException(status_code=404, detail="unknown sku")
    return dict(row)


@app.post("/items/{sku}/stock")
async def adjust_stock(
    sku: str,
    update: StockUpdate,
    request: Request,
    username: str = Depends(require_user),
) -> Dict[str, Any]:
    """Protected write -- exercises the inventory -> auth hop on every call."""
    async with request.app.state.pool.acquire() as conn:
        row = await conn.fetchrow(
            "UPDATE items SET stock = stock + $2 WHERE sku = $1 RETURNING sku, name, price_inr, stock",
            sku,
            update.delta,
        )
    if row is None:
        raise HTTPException(status_code=404, detail="unknown sku")

    logger.info(
        "stock adjusted",
        extra={"service": SERVICE, "fields": {"sku": sku, "delta": update.delta, "by": username}},
    )
    return {"updated_by": username, **dict(row)}


@app.get("/")
async def root() -> Dict[str, Any]:
    return {"service": SERVICE, "endpoints": ["/items", "/items/{sku}", "/health", "/metrics"]}
