"""
Configuration for NetGuardian Network Monitoring module.

Edit SERVICES to point at whatever your teammates' services expose.
Each service just needs a URL that returns any HTTP response
(a dedicated /health endpoint is ideal, but any reachable route works).
"""

SERVICES = [
    {"name": "gateway", "url": "http://127.0.0.1:8080/health"},
    {"name": "auth", "url": "http://127.0.0.1:8001/health"},
    {"name": "inventory", "url": "http://127.0.0.1:8002/health"},
]

# How often to probe each service (seconds)
POLL_INTERVAL_SECONDS = 2

# How many recent probes to keep per service for rolling stats
WINDOW_SIZE = 60  # e.g. 60 probes * 2s interval = last 2 minutes

# Request timeout (seconds) — a timeout counts as a failed probe
REQUEST_TIMEOUT_SECONDS = 1.5

# A service is marked DOWN after this many consecutive failed probes
DOWN_AFTER_CONSECUTIVE_FAILURES = 3
