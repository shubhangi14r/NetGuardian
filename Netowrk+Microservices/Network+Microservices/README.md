# chhabra_cn — Self-Healing Network (Person 1: Network + Microservices)

Foundation layer for the Computer Networks semester project. This repository
contains the **containerised microservice environment** that the rest of the
team builds on: three HTTP services plus a database, each in its own container,
communicating over a user-defined Docker bridge network.

**Person 1 deliverable for Review-2** — *2–3 services running, HTTP
communication, Docker setup* — is complete and verified end to end.

---

## Why containers (and not one Python file)

If the whole application were one process, the services would talk to each
other through function calls and there would be no networking to measure. Each
service here is a separate container with its own IP on a shared bridge
network, so every interaction is a real TCP connection carrying real HTTP —
latency, packet loss, DNS resolution and connection failures all become
observable, which is exactly what Persons 2–5 need to work with.

## Topology

```
                      host :8080
                          │
                          ▼
                   ┌─────────────┐
                   │   gateway   │  172.28.0.x   (only published container)
                   └──┬───────┬──┘
            HTTP/8000 │       │ HTTP/8000
                      ▼       ▼
              ┌──────────┐  ┌───────────┐
              │   auth   │◄─┤ inventory │   inventory verifies every
              └──────────┘  └─────┬─────┘   token by calling auth
                  HTTP/8000       │ TCP/5432
                                  ▼
                            ┌──────────┐
                            │ postgres │
                            └──────────┘
                 network: shnnet (bridge, 172.28.0.0/16)
```

| Service     | Image               | Internal address        | Published | Role                                  |
|-------------|---------------------|-------------------------|-----------|---------------------------------------|
| `gateway`   | `shn/gateway:0.1.0` | `http://gateway:8000`   | `8080`    | Entry point, forwards to auth/inventory |
| `auth`      | `shn/auth:0.1.0`    | `http://auth:8000`      | —         | Login, HMAC token issue/verify        |
| `inventory` | `shn/inventory:0.1.0` | `http://inventory:8000` | —       | Product catalogue and stock           |
| `postgres`  | `postgres:16-alpine`| `postgres:5432`         | —         | Persistent storage                    |

Only the gateway is reachable from the host. The other three are addressable
only from inside `shnnet` — a deliberate choice that mirrors how production
systems expose a single edge.

### Networking concepts this exercises

- **DNS** — containers resolve each other by service name via Docker's embedded
  DNS server; no IP is hard-coded anywhere. Verified: `auth → 172.28.0.2`,
  `postgres → 172.28.0.3`, `inventory → 172.28.0.4`.
- **TCP / HTTP** — every inter-service call is HTTP/1.1 over TCP with a 3 s
  timeout so failures surface fast instead of hanging.
- **Ports and NAT** — `8080:8000` port publishing; the bridge network NATs
  container traffic out to the host.
- **Fault classification** — a downstream that *refuses* a request returns its
  own 4xx; a downstream that is *unreachable* produces a `503`. Keeping these
  separate is what lets Person 4 tell an application bug from a network fault.
- **Request tracing** — an `X-Trace-Id` header is generated at the gateway and
  propagated through every hop, so one user request can be followed across
  three containers in the logs.

---

## Running it

```bash
docker compose up -d --build
```

Then:

```bash
./scripts/smoke_test.sh
```

Current result — **11/11 passing**:

```
==> Health
  PASS  gateway /health
  PASS  all services UP
==> Catalogue (gateway -> inventory -> postgres)
  PASS  GET /api/items
  PASS  GET /api/items/SKU-1002
==> Auth (gateway -> auth)
  PASS  bad password rejected
  PASS  login returned a token
==> Protected write (gateway -> inventory -> auth -> postgres)
  PASS  no token => 401
  PASS  stock adjust with token
==> Observability hooks
  PASS  GET /metrics
  PASS  GET /api/topology
  PASS  trace id propagated

passed: 11   failed: 0
```

Shut down with `docker compose down` (add `-v` to drop the database volume).

## API

All through the gateway at `http://localhost:8080`.

| Method | Path                     | Auth   | Notes                                    |
|--------|--------------------------|--------|------------------------------------------|
| `POST` | `/api/login`             | —      | `{"username","password"}` → token        |
| `GET`  | `/api/items`             | —      | Catalogue; stays up when auth is down    |
| `GET`  | `/api/items/{sku}`       | —      | Single item                              |
| `POST` | `/api/items/{sku}/stock` | Bearer | `{"delta": -3}`; triggers the auth hop   |
| `GET`  | `/api/status`            | —      | Health + latency of every service        |
| `GET`  | `/api/topology`          | —      | Node/edge list of the service graph      |
| `GET`  | `/health`                | —      | On every service; Docker's probe target  |
| `GET`  | `/metrics`               | —      | On every service; p50/p95/p99, error rate|

Test users: `tej / cn2026`, `admin / admin123`, `guest / guest`.

Quick manual run:

```bash
curl -s localhost:8080/api/status | python3 -m json.tool
TOKEN=$(curl -s -X POST localhost:8080/api/login -H 'Content-Type: application/json' \
  -d '{"username":"tej","password":"cn2026"}' | python3 -c 'import sys,json;print(json.load(sys.stdin)["token"])')
curl -s -X POST localhost:8080/api/items/SKU-1001/stock \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' -d '{"delta":-3}'
```

## Failure demonstration

```bash
./scripts/failure_demo.sh
```

Stops the auth container and shows the system degrade honestly. Verified
output: `overall` flips from `HEALTHY` to `DEGRADED`, auth reports
`"state": "DOWN"` with `ConnectError`, the public catalogue keeps returning
`200`, and login returns `503` (unreachable) rather than `401` (bad
credentials). Restarting auth returns the system to `HEALTHY` within seconds.

That manual restart is precisely the step Person 5 automates.

---

## What the rest of the team plugs into

This layer was built to leave clean seams rather than to be rewritten later.

| Person | Owns              | Hook already in place                                                        |
|--------|-------------------|------------------------------------------------------------------------------|
| 2      | Network monitoring| `/metrics` on every service (p50/p95/p99, error rate, dependency failures); one JSON log line per request on stdout with `duration_ms`; `/api/status` gives UP/DEGRADED/DOWN with per-probe latency |
| 3      | Dashboard         | `/api/topology` returns the node/edge graph to render; `/api/status` is the live feed; CORS is already open |
| 4      | Anomaly detection | `dependency_failures_total` and the 503-vs-4xx split separate network faults from application faults; per-route latency history is retained in a 500-request window |
| 5      | Self-healing      | Docker `HEALTHCHECK` on all three services (unhealthy after 3 failed probes), `restart: unless-stopped`, and named containers (`shn-auth`, …) that a healer can restart by name |

## Layout

```
chhabra_cn/
├── docker-compose.yml         # topology, network, healthchecks, ports
├── shared/netkit.py           # logging, latency middleware, /health, /metrics
├── services/
│   ├── gateway/               # edge: forwards, aggregates status, topology
│   ├── auth/                  # login + token verification
│   └── inventory/             # catalogue + stock, talks to auth and postgres
└── scripts/
    ├── smoke_test.sh          # 11 end-to-end checks
    └── failure_demo.sh        # kill auth, observe, recover
```

Each service is a `python:3.12-slim` image running uvicorn as a non-root user,
with pinned dependencies and requirements installed in a cached layer ahead of
the source copy.

## Notes for the next milestone

- `AUTH_SECRET` and the Postgres password are development defaults in
  `docker-compose.yml`. Move them to a `.env` file before the final demo.
- The `/metrics` store is in-process and resets when a container restarts —
  fine as a stopgap, but Person 2's collector should scrape and persist it.
- Adding a fourth service later means one block in `docker-compose.yml` plus an
  entry in the gateway's `DOWNSTREAM` map; nothing else needs to change.
