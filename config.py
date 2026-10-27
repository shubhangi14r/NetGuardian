"""
Configuration for the NetGuardian Self-Healing module (Person 5).

Each entry describes one thing the healer watches and may recover:
  name        - label used in the API / dashboard (matches the monitor's names)
  container   - Docker container name from docker-compose.yml (restart target)
  health_url  - HTTP liveness endpoint published on the host (None = Docker
                healthcheck only, e.g. Postgres has no HTTP endpoint)
  depends_on  - services that must be healthy before THIS one is restarted.
                Restarting inventory while Postgres is down would just fail,
                so the healer fixes the dependency first.
"""

SERVICES = [
    {"name": "postgres",  "container": "shn-postgres",         "health_url": None,
     "depends_on": []},
    {"name": "auth",      "container": "shn-auth",             "health_url": "http://127.0.0.1:8001/health",
     "depends_on": []},
    {"name": "inventory", "container": "shn-inventory",        "health_url": "http://127.0.0.1:8002/health",
     "depends_on": ["postgres", "auth"]},
    {"name": "gateway",   "container": "shn-gateway",          "health_url": "http://127.0.0.1:8080/health",
     "depends_on": ["auth", "inventory"]},
    {"name": "frontend",  "container": "netguardian-frontend", "health_url": "http://127.0.0.1:5173/",
     "depends_on": ["gateway"]},
]

# How often every service is checked (seconds)
CHECK_INTERVAL_S = 2.0

# HTTP probe timeout (seconds); a timeout counts as a failed check
PROBE_TIMEOUT_S = 1.5

# A service is declared FAILED after this many consecutive failed checks.
# 3 x 2s = ~6s of confirmed failure, which filters out one-off blips.
FAILURE_THRESHOLD = 3

# After a restart, how long we wait for the service to become healthy again
RECOVERY_TIMEOUT_S = 30.0

# Retry policy: wait BACKOFF_BASE_S * 2^(attempt-1) between restart attempts
BACKOFF_BASE_S = 5.0
MAX_RESTART_ATTEMPTS = 3          # then the healer GIVES UP (circuit breaker)

# A recovered service must stay healthy this long before its retry counter resets
STABLE_AFTER_S = 30.0

# Seconds docker waits for a graceful stop before killing (docker restart -t)
DOCKER_STOP_TIMEOUT_S = 5

# Healing API (the dashboard polls this)
API_HOST = "0.0.0.0"
API_PORT = 9002

# How many events the in-memory event log keeps
EVENT_LOG_SIZE = 200
