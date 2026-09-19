"""
NetGuardian - Network Monitoring API

Exposes the NetworkMonitor's rolling metrics over HTTP so:
  - Person 3 (Dashboard) can poll /metrics for live visualization
  - Person 4 (Anomaly Detection) can poll /metrics or /metrics/{name}
    as the feature source for the ML model / rule engine

Run with:
    pip install -r requirements.txt
    uvicorn monitor_api:app --reload --port 9000
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from network_monitor import NetworkMonitor

monitor = NetworkMonitor()


@asynccontextmanager
async def lifespan(app: FastAPI):
    monitor.start()
    yield
    monitor.stop()


app = FastAPI(title="NetGuardian Network Monitoring", lifespan=lifespan)

# Allow the dashboard (likely a separate React/HTML app on another port) to call this freely
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
def root():
    return {"service": "netguardian-monitoring", "status": "running"}


@app.get("/metrics")
def get_all_metrics():
    """Rolling metrics for every monitored service."""
    return monitor.get_all_metrics()


@app.get("/metrics/{service_name}")
def get_service_metrics(service_name: str):
    """Rolling metrics for a single service."""
    metrics = monitor.get_metrics(service_name)
    if metrics["sample_count"] == 0 and service_name not in [
        s["name"] for s in monitor.services
    ]:
        raise HTTPException(status_code=404, detail="Unknown service name")
    return metrics


@app.get("/status")
def get_status_summary():
    """Quick UP/DOWN summary — cheap endpoint for the dashboard's top-level view."""
    all_metrics = monitor.get_all_metrics()
    return {
        "services": {m["service"]: m["status"] for m in all_metrics},
        "any_down": any(m["status"] == "DOWN" for m in all_metrics),
    }
