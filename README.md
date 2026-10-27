# NetGuardian — Self-Healing (Person 5)

**Review-2 deliverable:** automatically detect a failed service and restart/recover it.

## How it works
`self_healer.py` runs a background loop (every 2 s) that checks every service with two signals:
the HTTP `/health` probe and the Docker container state (`running`, `exited`, `unhealthy`).

Per service, a state machine drives recovery:

`HEALTHY → SUSPECT → (3 consecutive failures) → HEALING → RECOVERING → HEALTHY`
with `BACKOFF` for retries and `GAVE_UP` as a circuit breaker.

| Feature | What it does |
|---|---|
| Failure threshold | 3 consecutive failed checks (~6 s) before acting, so one dropped probe doesn't trigger a restart |
| Right action | stopped/exited container → `docker start`; running-but-hung/unhealthy → `docker restart` |
| Dependency-aware | if `postgres` is down, `inventory` isn't restarted until it's back |
| Exponential backoff | retries wait 5 s, 10 s, 20 s … |
| Circuit breaker | after 3 failed attempts → `GAVE_UP` (no infinite restart loop); manual heal resets it |
| Metrics | restart count, recoveries, recovery time per outage and average (MTTR) |
| Event log | `FAILURE_CONFIRMED`, `RESTART_ATTEMPT`, `RECOVERED`, … also printed as JSON lines |

Settings live in `config.py`.

## Run
```bash
cd "Self healing"
python healer_api.py        # no pip install needed; Docker CLI must be available
```
API on `http://localhost:9002`:

| Method | Path | Purpose |
|---|---|---|
| GET | `/healing/status` | state, restarts, recovery times per service |
| GET | `/healing/events?limit=50` | recent healing events, newest first |
| POST | `/healing/heal/{name}` | manually trigger recovery |
| POST | `/healing/pause` · `/healing/resume` | stop/resume automatic healing |

## Demo
```bash
./run_demo.sh auth          # kills shn-auth, shows it healed back automatically
```
(or run `docker stop shn-auth` and watch `/healing/events`).

## Tests
```bash
python test_self_healer.py  # 10 tests, no Docker required (simulated containers + clock)
```
Covers: blip ignored, stopped→start, hung→restart, dependency order, retry/backoff, give-up, manual override, pause.

## Integration with the team
* Uses Person 1's container names (`shn-*`), `/health` endpoints and healthchecks.
* Complements `restart: unless-stopped`, which does not restart a container that was *stopped* or is *unhealthy*.
* Person 3 can poll `GET :9002/healing/status` and `/healing/events` for a dashboard panel (CORS is open).
