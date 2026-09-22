"""Gateway -- the only container published to the host.

Everything a user does enters here and is forwarded over HTTP to the internal
services by their Docker DNS names. It also aggregates downstream health, which
is the feed Person 3's dashboard and Person 5's healer both consume.
"""

from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager
from typing import Any, Dict, List

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from shared import netkit

SERVICE = "gateway"
AUTH_URL = os.getenv("AUTH_URL", "http://auth:8000")
INVENTORY_URL = os.getenv("INVENTORY_URL", "http://inventory:8000")

# The service map. Person 5's recovery logic reads this to know what it may
# restart, and the dashboard reads it to draw the topology.
DOWNSTREAM: Dict[str, str] = {
    "auth": AUTH_URL,
    "inventory": INVENTORY_URL,
}


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.http = netkit.http_client()
    app.state.logger.info(
        "gateway ready",
        extra={"service": SERVICE, "fields": {"downstream": list(DOWNSTREAM)}},
    )
    try:
        yield
    finally:
        await app.state.http.aclose()


app = FastAPI(title="API Gateway", version="0.1.0", lifespan=lifespan)
logger, metrics = netkit.install(app, SERVICE)

# The dashboard will be served from a different origin during development.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=[netkit.TRACE_HEADER, "X-Service", "X-Duration-Ms"],
)


async def forward(
    request: Request,
    method: str,
    base_url: str,
    path: str,
    *,
    json_body: Any | None = None,
    pass_auth: bool = False,
) -> Any:
    """Proxy one call downstream, translating transport faults into 503.

    Distinguishing "the service said no" (4xx passed through) from "I could not
    reach the service" (503) is the whole point -- it is what lets the anomaly
    detector tell an application bug from a network fault.
    """
    trace_id = getattr(request.state, "trace_id", "-")
    headers = {netkit.TRACE_HEADER: trace_id}
    if pass_auth and (auth_header := request.headers.get("authorization")):
        headers["Authorization"] = auth_header

    try:
        resp = await request.app.state.http.request(
            method, f"{base_url}{path}", json=json_body, headers=headers
        )
    except httpx.HTTPError as exc:
        metrics.record_dependency_failure()
        logger.warning(
            "downstream unreachable",
            extra={"service": SERVICE, "fields": {
                "trace_id": trace_id, "target": f"{base_url}{path}", "error": type(exc).__name__,
            }},
        )
        raise HTTPException(status_code=503, detail=f"{base_url} unreachable") from exc

    if resp.status_code >= 400:
        detail = resp.json().get("detail", resp.text) if resp.headers.get(
            "content-type", ""
        ).startswith("application/json") else resp.text
        raise HTTPException(status_code=resp.status_code, detail=detail)
    return resp.json()


class LoginRequest(BaseModel):
    username: str
    password: str


class StockUpdate(BaseModel):
    delta: int


@app.post("/api/login")
async def login(body: LoginRequest, request: Request) -> Any:
    return await forward(request, "POST", AUTH_URL, "/login", json_body=body.model_dump())


@app.get("/api/items")
async def items(request: Request) -> Any:
    return await forward(request, "GET", INVENTORY_URL, "/items")


@app.get("/api/items/{sku}")
async def item(sku: str, request: Request) -> Any:
    return await forward(request, "GET", INVENTORY_URL, f"/items/{sku}")


@app.post("/api/items/{sku}/stock")
async def adjust_stock(sku: str, body: StockUpdate, request: Request) -> Any:
    return await forward(
        request, "POST", INVENTORY_URL, f"/items/{sku}/stock",
        json_body=body.model_dump(), pass_auth=True,
    )


@app.get("/api/status")
async def status(request: Request) -> Dict[str, Any]:
    """Fan out to every downstream /health in parallel and time each probe.

    This single endpoint is the contract handed to Persons 2, 3 and 5.
    """
    client: httpx.AsyncClient = request.app.state.http

    async def probe(name: str, base: str) -> Dict[str, Any]:
        started = asyncio.get_event_loop().time()
        try:
            resp = await client.get(f"{base}/health", timeout=2.0)
            latency_ms = round((asyncio.get_event_loop().time() - started) * 1000, 2)
            healthy = resp.status_code == 200
            return {
                "service": name,
                "url": base,
                "state": "UP" if healthy else "DEGRADED",
                "http_status": resp.status_code,
                "latency_ms": latency_ms,
            }
        except httpx.HTTPError as exc:
            latency_ms = round((asyncio.get_event_loop().time() - started) * 1000, 2)
            return {
                "service": name,
                "url": base,
                "state": "DOWN",
                "http_status": None,
                "latency_ms": latency_ms,
                "error": type(exc).__name__,
            }

    results: List[Dict[str, Any]] = await asyncio.gather(
        *(probe(name, base) for name, base in DOWNSTREAM.items())
    )
    results.append({
        "service": SERVICE, "url": "self", "state": "UP",
        "http_status": 200, "latency_ms": 0.0,
    })

    down = [r["service"] for r in results if r["state"] != "UP"]
    return {
        "overall": "HEALTHY" if not down else "DEGRADED",
        "unhealthy": down,
        "services": results,
    }


@app.get("/api/topology")
async def topology() -> Dict[str, Any]:
    """Static edge list of the service graph, for the dashboard to render."""
    return {
        "nodes": [
            {"id": "gateway", "kind": "service", "published_port": 8080},
            {"id": "auth", "kind": "service"},
            {"id": "inventory", "kind": "service"},
            {"id": "postgres", "kind": "database"},
        ],
        "edges": [
            {"from": "gateway", "to": "auth", "protocol": "HTTP/1.1", "port": 8000},
            {"from": "gateway", "to": "inventory", "protocol": "HTTP/1.1", "port": 8000},
            {"from": "inventory", "to": "auth", "protocol": "HTTP/1.1", "port": 8000},
            {"from": "inventory", "to": "postgres", "protocol": "TCP", "port": 5432},
        ],
    }


@app.get("/")
async def root() -> Dict[str, Any]:
    return {
        "service": SERVICE,
        "endpoints": ["/api/login", "/api/items", "/api/status", "/api/topology", "/health", "/metrics"],
    }
