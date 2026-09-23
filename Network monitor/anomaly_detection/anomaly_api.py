import requests

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from anomaly_detector import (
    validate_metrics,
    detect_anomalies,
    detect_ml_anomaly
)


MONITOR_URL = "http://127.0.0.1:9000/metrics"

app = FastAPI(
    title="NetGuardian Anomaly Detection API"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def analyse_service(metrics):

    # -----------------------------
    # Step 1: Validate data
    # -----------------------------

    valid, missing_fields = validate_metrics(metrics)

    if not valid:
        return {
            "service": metrics.get("service", "unknown"),
            "overall_status": "INVALID_DATA",
            "missing_fields": missing_fields
        }


    # -----------------------------
    # Step 2: Rule-based detection
    # -----------------------------

    rule_anomalies = detect_anomalies(metrics)


    # -----------------------------
    # Step 3: ML detection
    # -----------------------------

    ml_result = detect_ml_anomaly(metrics)


    # -----------------------------
    # Step 4: Combine severity
    # -----------------------------

    overall_status = "HEALTHY"

    # Critical rule beats everything else
    if any(
        anomaly["severity"] == "critical"
        for anomaly in rule_anomalies
    ):
        overall_status = "CRITICAL"

    # Warning rule
    elif rule_anomalies:
        overall_status = "WARNING"

    # ML-only anomaly
    elif (
        ml_result is not None
        and ml_result["is_anomaly"]
    ):
        overall_status = "WARNING"


    # -----------------------------
    # Step 5: Final clean output
    # -----------------------------

    return {
        "service": metrics["service"],
        "overall_status": overall_status,

        "network_status": metrics["status"],

        "rule_anomalies": rule_anomalies,

        "ml": ml_result,

        "metrics": {
            "latency": metrics["latency"],
            "response_time": metrics["response_time"],
            "failure_rate_pct": metrics["failure_rate_pct"],
            "p95_latency_ms": metrics["p95_latency_ms"],
            "p95_response_time_ms": metrics["p95_response_time_ms"],
            "consecutive_failures": metrics["consecutive_failures"]
        },

        "timestamp": metrics["timestamp"]
    }


@app.get("/")
def root():

    return {
        "service": "netguardian-anomaly-detection",
        "status": "running"
    }


@app.get("/anomalies")
def get_anomalies():

    try:

        response = requests.get(
            MONITOR_URL,
            timeout=5
        )

        response.raise_for_status()

        all_metrics = response.json()

    except requests.RequestException as error:

        raise HTTPException(
            status_code=503,
            detail=f"Monitoring API unavailable: {error}"
        )


    results = []

    for metrics in all_metrics:

        result = analyse_service(metrics)

        results.append(result)


    return results