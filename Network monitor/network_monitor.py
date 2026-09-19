"""
NetGuardian - Network Monitoring module (Person 2 responsibility)

Responsibilities covered here:
  - Latency measurement (TCP connect time)
  - Response time measurement (full HTTP request/response time)
  - Request failure / "packet-loss-like" metric (rolling failure rate)
  - UP / DOWN detection (based on consecutive failures)

Design:
  A background thread probes every configured service on a fixed
  interval. Each probe result (success/failure, latency, response time)
  is pushed into a fixed-size rolling window (collections.deque) per
  service. Public methods compute summary stats from that window on
  demand, so this module can be polled cheaply by the dashboard (Person 3)
  or the anomaly detector (Person 4) at any time.
"""

import socket
import statistics
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Deque, Dict, List, Optional
from urllib.parse import urlparse

import requests

from config import (
    DOWN_AFTER_CONSECUTIVE_FAILURES,
    POLL_INTERVAL_SECONDS,
    REQUEST_TIMEOUT_SECONDS,
    SERVICES,
    WINDOW_SIZE,
)


@dataclass
class ProbeResult:
    timestamp: float
    success: bool
    tcp_latency_ms: Optional[float]      # time to establish TCP connection
    response_time_ms: Optional[float]    # total time for full HTTP request
    error: Optional[str] = None


@dataclass
class ServiceState:
    name: str
    url: str
    history: Deque[ProbeResult] = field(default_factory=lambda: deque(maxlen=WINDOW_SIZE))
    consecutive_failures: int = 0
    status: str = "UNKNOWN"  # UP / DOWN / UNKNOWN


def _measure_tcp_latency(host: str, port: int, timeout: float) -> Optional[float]:
    """Time how long it takes to open a raw TCP connection (pure network latency,
    separate from the time the app takes to build a response)."""
    start = time.perf_counter()
    try:
        with socket.create_connection((host, port), timeout=timeout):
            pass
        return (time.perf_counter() - start) * 1000
    except OSError:
        return None


def _probe_once(service: Dict) -> ProbeResult:
    url = service["url"]
    parsed = urlparse(url)
    host = parsed.hostname
    port = parsed.port or (443 if parsed.scheme == "https" else 80)

    tcp_latency_ms = _measure_tcp_latency(host, port, REQUEST_TIMEOUT_SECONDS)

    start = time.perf_counter()
    try:
        resp = requests.get(url, timeout=REQUEST_TIMEOUT_SECONDS)
        response_time_ms = (time.perf_counter() - start) * 1000
        success = resp.status_code < 500  # 2xx-4xx counted as "service reachable"
        error = None if success else f"HTTP {resp.status_code}"
        return ProbeResult(time.time(), success, tcp_latency_ms, response_time_ms, error)
    except requests.RequestException as exc:
        response_time_ms = (time.perf_counter() - start) * 1000
        return ProbeResult(time.time(), False, tcp_latency_ms, response_time_ms, str(exc))


class NetworkMonitor:
    """Runs background probing for all configured services and exposes
    rolling metrics. This is the object the API layer (monitor_api.py)
    wraps and serves over HTTP."""

    def __init__(self, services: List[Dict] = None, poll_interval: int = None):
        self.services = services or SERVICES
        self.poll_interval = poll_interval or POLL_INTERVAL_SECONDS
        self._states: Dict[str, ServiceState] = {
            s["name"]: ServiceState(name=s["name"], url=s["url"]) for s in self.services
        }
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None

    # ---------- lifecycle ----------

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=5)

    def _run_loop(self):
        while not self._stop_event.is_set():
            for service in self.services:
                self._probe_and_record(service)
            self._stop_event.wait(self.poll_interval)

    # ---------- probing ----------

    def _probe_and_record(self, service: Dict):
        result = _probe_once(service)
        with self._lock:
            state = self._states[service["name"]]
            state.history.append(result)

            if result.success:
                state.consecutive_failures = 0
            else:
                state.consecutive_failures += 1

            if state.consecutive_failures >= DOWN_AFTER_CONSECUTIVE_FAILURES:
                state.status = "DOWN"
            else:
                state.status = "UP"

    # ---------- metrics API (read-only, thread-safe) ----------

    def get_metrics(self, name: str) -> Dict:
        """Returns metrics in the shared contract format agreed with
        Person 4 (Anomaly Detection):
            { service, latency, response_time, failure_rate, status }
        Note: failure_rate is a COUNT of failed probes in the current
        rolling window (matches her example values like 2, 3) — not a
        percentage. The percentage version is still included separately
        as failure_rate_pct for anyone who wants it.
        """
        with self._lock:
            state = self._states[name]
            history = list(state.history)

        if not history:
            return {
                "service": name,
                "latency": None,
                "response_time": None,
                "failure_rate": 0,
                "status": state.status,
            }

        latencies = [r.tcp_latency_ms for r in history if r.tcp_latency_ms is not None]
        resp_times = [r.response_time_ms for r in history if r.response_time_ms is not None]
        failures = sum(1 for r in history if not r.success)

        return {
            # --- contract fields (agreed with Person 4) ---
            "service": name,
            "latency": round(statistics.mean(latencies), 2) if latencies else None,
            "response_time": round(statistics.mean(resp_times), 2) if resp_times else None,
            "failure_rate": failures,  # count of failed probes in the window
            "status": state.status,
            # --- extra fields, safe to ignore if not needed ---
            "failure_rate_pct": round((failures / len(history)) * 100, 2),
            "timestamp": history[-1].timestamp,
            "p95_latency_ms": round(_percentile(latencies, 95), 2) if latencies else None,
            "p95_response_time_ms": round(_percentile(resp_times, 95), 2) if resp_times else None,
            "consecutive_failures": state.consecutive_failures,
            "sample_count": len(history),
            "last_error": history[-1].error,
        }

    def get_all_metrics(self) -> List[Dict]:
        return [self.get_metrics(name) for name in self._states]


def _percentile(values: List[float], pct: float) -> float:
    if not values:
        return 0.0
    values_sorted = sorted(values)
    k = (len(values_sorted) - 1) * (pct / 100)
    f, c = int(k), min(int(k) + 1, len(values_sorted) - 1)
    if f == c:
        return values_sorted[f]
    return values_sorted[f] + (values_sorted[c] - values_sorted[f]) * (k - f)
