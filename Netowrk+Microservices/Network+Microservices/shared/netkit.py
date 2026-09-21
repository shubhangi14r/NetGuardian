"""Shared networking helpers for the self-healing-network services.

Person 1 owns this module. It exists so that every service speaks the same
"wire dialect": identical health endpoints, identical per-request latency
logging, and a single HTTP client with sane timeouts. Person 2 (monitoring)
scrapes the metrics this module records; Person 5 (self-healing) drives the
health endpoints it installs.
"""

from __future__ import annotations

import json
import logging
import os
import socket
import sys
import time
import uuid
from collections import deque
from typing import Any, Deque, Dict

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

# Correlation id header, propagated across every hop so a single user request
# can be followed through gateway -> auth -> inventory in the logs.
TRACE_HEADER = "X-Trace-Id"

# How many recent requests each service keeps in memory for /metrics.
_WINDOW = 500


def _now_ms() -> float:
    return time.perf_counter() * 1000.0


class JsonLogFormatter(logging.Formatter):
    """One JSON object per line -- easy for Person 2 to parse off stdout."""

    def format(self, record: logging.LogRecord) -> str:
        payload: Dict[str, Any] = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(record.created)),
            "level": record.levelname,
            "service": getattr(record, "service", "-"),
            "msg": record.getMessage(),
        }
        extra = getattr(record, "fields", None)
        if extra:
            payload.update(extra)
        return json.dumps(payload)


def configure_logging(service_name: str) -> logging.Logger:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonLogFormatter())
    logger = logging.getLogger(service_name)
    logger.handlers = [handler]
    logger.setLevel(os.getenv("LOG_LEVEL", "INFO").upper())
    logger.propagate = False
    return logger


class Metrics:
    """In-process request statistics.

    Deliberately tiny: this is the seam Person 2 replaces (or scrapes) when the
    real monitoring service lands. Until then every container can already
    report its own latency, error rate and dependency failures.
    """

    def __init__(self) -> None:
        self.started_at = time.time()
        self.total = 0
        self.errors = 0
        self.dependency_failures = 0
        self.latencies_ms: Deque[float] = deque(maxlen=_WINDOW)
        self.by_route: Dict[str, Dict[str, float]] = {}

    def record(self, route: str, status: int, duration_ms: float) -> None:
        self.total += 1
        if status >= 500:
            self.errors += 1
        self.latencies_ms.append(duration_ms)
        slot = self.by_route.setdefault(route, {"count": 0, "errors": 0, "total_ms": 0.0})
        slot["count"] += 1
        slot["total_ms"] += duration_ms
        if status >= 500:
            slot["errors"] += 1

    def record_dependency_failure(self) -> None:
        self.dependency_failures += 1

    def snapshot(self) -> Dict[str, Any]:
        lat = sorted(self.latencies_ms)
        def pct(p: float) -> float:
            if not lat:
                return 0.0
            idx = min(len(lat) - 1, int(round((p / 100.0) * (len(lat) - 1))))
            return round(lat[idx], 2)

        return {
            "uptime_s": round(time.time() - self.started_at, 1),
            "requests_total": self.total,
            "errors_total": self.errors,
            "dependency_failures_total": self.dependency_failures,
            "error_rate": round(self.errors / self.total, 4) if self.total else 0.0,
            "latency_ms": {
                "p50": pct(50),
                "p95": pct(95),
                "p99": pct(99),
                "max": round(max(lat), 2) if lat else 0.0,
            },
            "routes": {
                name: {
                    "count": int(v["count"]),
                    "errors": int(v["errors"]),
                    "avg_ms": round(v["total_ms"] / v["count"], 2) if v["count"] else 0.0,
                }
                for name, v in self.by_route.items()
            },
        }


def install(app: FastAPI, service_name: str, version: str = "0.1.0") -> tuple[logging.Logger, Metrics]:
    """Attach logging, latency middleware, /health, /ready and /metrics."""

    logger = configure_logging(service_name)
    metrics = Metrics()
    app.state.logger = logger
    app.state.metrics = metrics
    app.state.service_name = service_name

    @app.middleware("http")
    async def timing_middleware(request: Request, call_next):  # type: ignore[no-untyped-def]
        trace_id = request.headers.get(TRACE_HEADER) or uuid.uuid4().hex[:12]
        request.state.trace_id = trace_id
        start = _now_ms()
        try:
            response = await call_next(request)
        except Exception:
            duration = _now_ms() - start
            metrics.record(request.url.path, 500, duration)
            logger.exception(
                "unhandled error",
                extra={"service": service_name, "fields": {
                    "trace_id": trace_id,
                    "path": request.url.path,
                    "duration_ms": round(duration, 2),
                }},
            )
            return JSONResponse(status_code=500, content={"detail": "internal error", "trace_id": trace_id})

        duration = _now_ms() - start
        metrics.record(request.url.path, response.status_code, duration)
        response.headers[TRACE_HEADER] = trace_id
        response.headers["X-Service"] = service_name
        response.headers["X-Duration-Ms"] = f"{duration:.2f}"

        # /health is polled every few seconds by Docker and by Person 5's
        # healer; logging it would drown out real traffic.
        if request.url.path not in ("/health", "/metrics"):
            logger.info(
                "request",
                extra={"service": service_name, "fields": {
                    "trace_id": trace_id,
                    "method": request.method,
                    "path": request.url.path,
                    "status": response.status_code,
                    "duration_ms": round(duration, 2),
                    "client": request.client.host if request.client else None,
                }},
            )
        return response

    @app.get("/health", tags=["ops"])
    async def health() -> Dict[str, Any]:
        """Liveness. Cheap, no dependencies -- Docker's healthcheck target."""
        return {
            "status": "ok",
            "service": service_name,
            "version": version,
            "host": socket.gethostname(),
            "uptime_s": round(time.time() - metrics.started_at, 1),
        }

    @app.get("/metrics", tags=["ops"])
    async def metrics_endpoint() -> Dict[str, Any]:
        """Per-service counters. Person 2's collector polls this."""
        return {"service": service_name, **metrics.snapshot()}

    return logger, metrics


def http_client(timeout_s: float | None = None) -> httpx.AsyncClient:
    """One place to configure inter-service HTTP.

    A short timeout matters for the course project: when Person 5 kills a
    container, callers must fail fast and visibly rather than hanging.
    """
    timeout = timeout_s if timeout_s is not None else float(os.getenv("HTTP_TIMEOUT_S", "3.0"))
    return httpx.AsyncClient(
        timeout=httpx.Timeout(timeout, connect=min(timeout, 2.0)),
        headers={"User-Agent": "shn-internal/0.1"},
        follow_redirects=False,
    )
