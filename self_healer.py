"""
NetGuardian - Self-Healing module (Person 5 responsibility)

Goal: automatically detect a failed service and restart/recover it.

How it works
------------
A background thread checks every service every CHECK_INTERVAL_S seconds using
TWO independent signals:
  1. HTTP /health probe  (is the app actually answering?)
  2. Docker container state (is the container running / marked unhealthy?)

Each service is driven by a small state machine:

    HEALTHY --fail--> SUSPECT --(N consecutive fails)--> HEALING
       ^                                                    |
       |                                    restart issued, waiting for /health
       |                                                    v
       +------------- recovered <-------------------- RECOVERING
                                                            | timeout
                                                            v
                                         BACKOFF --(wait)--> HEALING (retry)
                                            | attempts exhausted
                                            v
                                         GAVE_UP  (circuit breaker, needs manual heal)

Safety features
  * Threshold      : needs several consecutive failures before acting (no
                     restarting on a single dropped probe).
  * Dependency-aware: if postgres is down, inventory is NOT restarted until
                     postgres is back (restarting it first would be pointless).
  * Exponential backoff + max attempts: no infinite restart loops.
  * Right action   : container stopped/exited -> `docker start`;
                     running but hung/unhealthy -> `docker restart`.
  * Metrics        : restart count, recovery time (MTTR), event log.

Only the standard library is used, and Docker/HTTP access is injectable, so the
whole decision logic can be unit-tested without Docker (see test_self_healer.py).
"""

from __future__ import annotations

import json
import subprocess
import threading
import time
import urllib.error
import urllib.request
from collections import deque
from typing import Callable, Deque, Dict, List, Optional, Tuple

import config

# ---- states -----------------------------------------------------------------
HEALTHY = "HEALTHY"
SUSPECT = "SUSPECT"        # failing, but below the threshold
HEALING = "HEALING"        # restart command in flight
RECOVERING = "RECOVERING"  # restart done, waiting for service to answer
BACKOFF = "BACKOFF"        # restart did not work, waiting before retry
BLOCKED = "BLOCKED"        # failing, but a dependency is down - fix that first
GAVE_UP = "GAVE_UP"        # attempts exhausted


# ---- default (real) probes ---------------------------------------------------
def http_probe(url: str, timeout: float) -> Tuple[bool, Optional[str]]:
    """True if the URL answers with a non-5xx response."""
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return resp.status < 500, None if resp.status < 500 else f"HTTP {resp.status}"
    except urllib.error.HTTPError as exc:
        return exc.code < 500, None if exc.code < 500 else f"HTTP {exc.code}"
    except Exception as exc:  # refused, timeout, DNS ... all mean "not serving"
        return False, type(exc).__name__


class DockerCLI:
    """Thin wrapper over the docker command line (swapped for a fake in tests)."""

    def _run(self, args: List[str], timeout: float = 60.0) -> Tuple[int, str]:
        try:
            p = subprocess.run(["docker", *args], capture_output=True, text=True, timeout=timeout)
            return p.returncode, (p.stdout or p.stderr).strip()
        except FileNotFoundError:
            return 127, "docker CLI not found"
        except subprocess.TimeoutExpired:
            return 124, "docker command timed out"

    def state(self, container: str) -> Dict[str, Optional[str]]:
        """-> {"status": running|exited|..., "health": healthy|unhealthy|starting|None}"""
        fmt = "{{.State.Status}}|{{if .State.Health}}{{.State.Health.Status}}{{end}}"
        code, out = self._run(["inspect", "--format", fmt, container], timeout=10)
        if code != 0:
            return {"status": "missing", "health": None}
        status, _, health = out.partition("|")
        return {"status": status or "unknown", "health": health or None}

    def start(self, container: str) -> Tuple[bool, str]:
        code, out = self._run(["start", container])
        return code == 0, out

    def restart(self, container: str) -> Tuple[bool, str]:
        code, out = self._run(["restart", "-t", str(config.DOCKER_STOP_TIMEOUT_S), container])
        return code == 0, out


# ---- per-service record ------------------------------------------------------
class ServiceRecord:
    def __init__(self, spec: Dict):
        self.name: str = spec["name"]
        self.container: str = spec["container"]
        self.health_url: Optional[str] = spec.get("health_url")
        self.depends_on: List[str] = spec.get("depends_on", [])

        self.state = HEALTHY
        self.consecutive_failures = 0
        self.last_error: Optional[str] = None
        self.container_state: Dict[str, Optional[str]] = {"status": "unknown", "health": None}

        self.attempts = 0                    # restart attempts for the current outage
        self.total_restarts = 0              # lifetime
        self.total_recoveries = 0
        self.failed_since: Optional[float] = None
        self.last_recovery_s: Optional[float] = None   # MTTR of last outage
        self.recovery_times: List[float] = []
        self.next_attempt_at: float = 0.0
        self.recover_deadline: float = 0.0
        self.healthy_since: Optional[float] = None
        self.action_running = False          # a docker command thread is active

    def to_dict(self, now: float) -> Dict:
        mttr = (sum(self.recovery_times) / len(self.recovery_times)) if self.recovery_times else None
        return {
            "service": self.name,
            "container": self.container,
            "state": self.state,
            "consecutive_failures": self.consecutive_failures,
            "last_error": self.last_error,
            "container_status": self.container_state.get("status"),
            "container_health": self.container_state.get("health"),
            "restart_attempts": self.attempts,
            "total_restarts": self.total_restarts,
            "total_recoveries": self.total_recoveries,
            "last_recovery_s": self.last_recovery_s,
            "avg_recovery_s": round(mttr, 2) if mttr is not None else None,
            "down_for_s": round(now - self.failed_since, 1) if self.failed_since else 0,
            "depends_on": self.depends_on,
        }


# ---- the healer --------------------------------------------------------------
class SelfHealer:
    def __init__(
        self,
        services: Optional[List[Dict]] = None,
        docker: Optional[DockerCLI] = None,
        probe: Callable[[str, float], Tuple[bool, Optional[str]]] = http_probe,
        clock: Callable[[], float] = time.time,
        run_actions_async: bool = True,
    ):
        specs = services or config.SERVICES
        self.records: Dict[str, ServiceRecord] = {s["name"]: ServiceRecord(s) for s in specs}
        self.docker = docker or DockerCLI()
        self._probe = probe
        self._clock = clock
        self._async = run_actions_async

        self.events: Deque[Dict] = deque(maxlen=config.EVENT_LOG_SIZE)
        self.paused = False
        self.started_at = clock()
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    # ----- lifecycle -----
    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True, name="self-healer")
        self._thread.start()
        self._log("-", "HEALER_STARTED", f"watching {', '.join(self.records)}")

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self.tick()
            except Exception as exc:  # the healer itself must never die
                self._log("-", "HEALER_ERROR", f"{type(exc).__name__}: {exc}")
            self._stop.wait(config.CHECK_INTERVAL_S)

    # ----- events -----
    def _log(self, service: str, kind: str, detail: str = "") -> None:
        event = {"ts": self._clock(), "service": service, "event": kind, "detail": detail}
        with self._lock:
            self.events.append(event)
        print(json.dumps({**event, "msg": "self-healer"}), flush=True)

    # ----- one monitoring cycle -----
    def check(self, rec: ServiceRecord) -> Tuple[bool, Optional[str]]:
        """Combine HTTP probe + Docker state into one healthy/unhealthy verdict."""
        rec.container_state = self.docker.state(rec.container)
        cs = rec.container_state
        if cs["status"] != "running":
            return False, f"container {cs['status']}"
        if cs["health"] == "unhealthy":
            return False, "docker healthcheck unhealthy"
        if rec.health_url:
            ok, err = self._probe(rec.health_url, config.PROBE_TIMEOUT_S)
            if not ok:
                return False, err or "probe failed"
        return True, None

    def tick(self) -> None:
        now = self._clock()
        with self._lock:
            results = {name: self.check(rec) for name, rec in self.records.items()}
            if self.paused:                       # observe only, never act
                return
            for name, rec in self.records.items():
                ok, err = results[name]
                self._advance(rec, ok, err, now)

    def _dependency_down(self, rec: ServiceRecord) -> Optional[str]:
        for dep in rec.depends_on:
            d = self.records.get(dep)
            if d and d.state in (SUSPECT, HEALING, RECOVERING, BACKOFF, GAVE_UP) and d.consecutive_failures > 0:
                return dep
        return None

    def _advance(self, rec: ServiceRecord, ok: bool, err: Optional[str], now: float) -> None:
        # ---- service answers ----
        if ok:
            rec.consecutive_failures = 0
            rec.last_error = None
            if rec.state in (SUSPECT, BLOCKED):
                self._log(rec.name, "BLIP_CLEARED", "failed checks resolved on their own")
                rec.state, rec.failed_since = HEALTHY, None
            elif rec.state in (HEALING, RECOVERING, BACKOFF, GAVE_UP):
                if rec.action_running:           # docker command still returning
                    return
                took = round(now - (rec.failed_since or now), 1)
                rec.last_recovery_s = took
                rec.recovery_times.append(took)
                rec.total_recoveries += 1
                self._log(rec.name, "RECOVERED", f"back online after {took}s ({rec.attempts} attempt(s))")
                rec.state, rec.failed_since, rec.healthy_since = HEALTHY, None, now
                rec.next_attempt_at = 0.0
            else:  # steady healthy
                if rec.healthy_since is None:
                    rec.healthy_since = now
                if rec.attempts and now - rec.healthy_since >= config.STABLE_AFTER_S:
                    rec.attempts = 0             # stable again: forgive past retries
            return

        # ---- service does not answer ----
        rec.consecutive_failures += 1
        rec.last_error = err
        rec.healthy_since = None
        if rec.failed_since is None:
            rec.failed_since = now

        if rec.state == HEALTHY:
            rec.state = SUSPECT
            self._log(rec.name, "FAILURE_SUSPECTED", f"{err} (1/{config.FAILURE_THRESHOLD})")

        if rec.state in (SUSPECT, BLOCKED):
            if rec.consecutive_failures < config.FAILURE_THRESHOLD:
                return
            blocker = self._dependency_down(rec)
            if blocker:
                if rec.state != BLOCKED:
                    rec.state = BLOCKED
                    self._log(rec.name, "WAITING_ON_DEPENDENCY", f"not restarting until '{blocker}' is healthy")
                return
            if rec.state == SUSPECT:
                self._log(rec.name, "FAILURE_CONFIRMED", f"{rec.consecutive_failures} consecutive failures: {err}")
            self._begin_heal(rec, now)
            return

        if rec.state == HEALING:
            return                                # command still running

        if rec.state == RECOVERING:
            if now >= rec.recover_deadline:
                self._log(rec.name, "RESTART_NO_EFFECT", f"still down {config.RECOVERY_TIMEOUT_S:.0f}s after restart")
                if rec.attempts >= config.MAX_RESTART_ATTEMPTS:
                    rec.state = GAVE_UP
                    self._log(rec.name, "GAVE_UP", f"{rec.attempts} attempts failed - manual intervention needed")
                else:
                    wait = config.BACKOFF_BASE_S * (2 ** (rec.attempts - 1))
                    rec.next_attempt_at = now + wait
                    rec.state = BACKOFF
                    self._log(rec.name, "BACKOFF", f"retrying in {wait:.0f}s")
            return

        if rec.state == BACKOFF and now >= rec.next_attempt_at:
            if self._dependency_down(rec):
                return
            self._begin_heal(rec, now)

    # ----- the actual recovery action -----
    def _begin_heal(self, rec: ServiceRecord, now: float, manual: bool = False) -> None:
        if rec.action_running:
            return
        rec.attempts += 1
        rec.total_restarts += 1
        rec.state = HEALING
        # stopped/exited container -> start; running but hung/unhealthy -> restart
        stopped = rec.container_state.get("status") in ("exited", "created", "dead", "paused")
        verb = "start" if stopped else "restart"
        self._log(rec.name, "RESTART_ATTEMPT",
                  f"docker {verb} {rec.container} (attempt {rec.attempts}/{config.MAX_RESTART_ATTEMPTS}"
                  f"{', manual' if manual else ''})")
        rec.action_running = True

        def work() -> None:
            fn = self.docker.start if verb == "start" else self.docker.restart
            success, out = fn(rec.container)
            with self._lock:
                rec.action_running = False
                done = self._clock()
                if success:
                    rec.state = RECOVERING
                    rec.recover_deadline = done + config.RECOVERY_TIMEOUT_S
                    self._log(rec.name, "RESTART_ISSUED", f"docker {verb} ok, waiting for health")
                else:
                    rec.state = RECOVERING          # let the deadline logic back off/retry
                    rec.recover_deadline = done
                    self._log(rec.name, "RESTART_FAILED", out[:200])

        if self._async:
            threading.Thread(target=work, daemon=True, name=f"heal-{rec.name}").start()
        else:
            work()

    # ----- operator controls (used by the API) -----
    def manual_heal(self, name: str) -> Dict:
        with self._lock:
            rec = self.records.get(name)
            if not rec:
                return {"ok": False, "error": f"unknown service '{name}'"}
            if rec.action_running:
                return {"ok": False, "error": "a recovery action is already running"}
            rec.attempts = 0                      # operator override resets the breaker
            rec.consecutive_failures = max(rec.consecutive_failures, 1)
            rec.failed_since = rec.failed_since or self._clock()
            rec.container_state = self.docker.state(rec.container)
            self._begin_heal(rec, self._clock(), manual=True)
            return {"ok": True, "service": name, "state": rec.state}

    def pause(self, paused: bool) -> None:
        self.paused = paused
        self._log("-", "HEALER_PAUSED" if paused else "HEALER_RESUMED")

    # ----- read side -----
    def snapshot(self) -> Dict:
        now = self._clock()
        with self._lock:
            services = [r.to_dict(now) for r in self.records.values()]
        unhealthy = [s["service"] for s in services if s["state"] != HEALTHY]
        return {
            "healer": "PAUSED" if self.paused else "ACTIVE",
            "overall": "HEALTHY" if not unhealthy else "HEALING",
            "unhealthy": unhealthy,
            "uptime_s": round(now - self.started_at, 1),
            "total_restarts": sum(s["total_restarts"] for s in services),
            "total_recoveries": sum(s["total_recoveries"] for s in services),
            "policy": {
                "check_interval_s": config.CHECK_INTERVAL_S,
                "failure_threshold": config.FAILURE_THRESHOLD,
                "max_restart_attempts": config.MAX_RESTART_ATTEMPTS,
                "recovery_timeout_s": config.RECOVERY_TIMEOUT_S,
            },
            "services": services,
        }

    def recent_events(self, limit: int = 50) -> List[Dict]:
        with self._lock:
            return list(self.events)[-limit:][::-1]    # newest first
