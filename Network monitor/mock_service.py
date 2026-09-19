"""
Optional helper: a trivial /health server so you can test the monitor
before your teammates' real services (API, secondary, database) exist.

Run three of these on different ports to simulate the 3-service setup
in config.py:
    uvicorn mock_service:app --port 8001
    uvicorn mock_service:app --port 8002
    uvicorn mock_service:app --port 8003

To test failure/DOWN detection, just Ctrl+C one of them and watch its
status flip to DOWN in /status after a few probes.
"""

from fastapi import FastAPI

app = FastAPI()


@app.get("/health")
def health():
    return {"status": "ok"}
