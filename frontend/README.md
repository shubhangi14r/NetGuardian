# NetGuardian Frontend

React + Vite dashboard integrated with the existing NetGuardian gateway,
network monitor, and anomaly detection APIs.

## Screens

- **Overview** — service health, latency, anomaly counts, rolling metrics
- **Services** — detailed gateway + monitor telemetry
- **Network Map** — live topology from `/api/topology`
- **Inventory** — catalogue and authenticated stock controls

## API integration

| Frontend | Backend |
|---|---|
| `VITE_GATEWAY_URL` | Gateway on `http://localhost:8080` |
| `VITE_MONITOR_URL` | Monitoring API on `http://localhost:9000` |
| `VITE_ANOMALY_URL` | Anomaly API on `http://localhost:9001` |

The gateway already has CORS enabled. The anomaly API was updated to enable
CORS as well.

## Local development

```bash
npm install
npm run dev
```

Open `http://localhost:5173`.

Start the gateway stack first:

```bash
cd ../Netowrk+Microservices/Network+Microservices
docker compose up -d --build
```

Start the monitoring API:

```bash
cd "../../../Network monitor"
uvicorn monitor_api:app --reload --port 9000
```

Start anomaly detection:

```bash
cd anomaly_detection
uvicorn anomaly_api:app --reload --port 9001
```

Demo login:

- `tej / cn2026`
- `admin / admin123`
- `guest / guest`

## Docker

From the microservices directory:

```bash
docker compose up -d --build
```

The dashboard will be available at `http://localhost:5173`.

The monitoring and anomaly APIs remain separate Python processes unless you
containerize those modules as a later deployment step.
