"""
Configuration for NetGuardian Network Monitoring.

Use Docker service names when running inside the Docker network.
Use localhost URLs when running the monitor directly on your host.
"""

import os

RUNNING_IN_DOCKER = os.getenv("RUNNING_IN_DOCKER", "false").lower() == "true"

if RUNNING_IN_DOCKER:
    SERVICES = [
        {"name": "gateway", "url": "http://gateway:8000/health"},
        {"name": "auth", "url": "http://auth:8000/health"},
        {"name": "inventory", "url": "http://inventory:8000/health"},
    ]
else:
    SERVICES = [
        {"name": "gateway", "url": "http://localhost:8080/health"},
        {"name": "auth", "url": "http://localhost:8001/health"},
        {"name": "inventory", "url": "http://localhost:8002/health"},
    ]

# How often to probe each service (seconds)
POLL_INTERVAL_SECONDS = 2

# Number of recent probes used for rolling statistics
WINDOW_SIZE = 60

# Request timeout (seconds)
REQUEST_TIMEOUT_SECONDS = 1.5

# Mark a service DOWN after this many consecutive failures
DOWN_AFTER_CONSECUTIVE_FAILURES = 3