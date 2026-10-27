import requests
import time
import os
import joblib
import pandas as pd
from pathlib import Path
from .xai_explainer import explain_anomaly

MONITOR_URL = "http://127.0.0.1:9000/metrics"

MODEL_DIR = Path(__file__).resolve().parent

ML_FEATURES = [
    "latency",
    "response_time",
    "p95_latency_ms",
    "p95_response_time_ms"
]

ML_MODELS = {
    "gateway": joblib.load(MODEL_DIR / "gateway_isolation_forest.pkl"),
    "auth": joblib.load(MODEL_DIR / "auth_isolation_forest.pkl"),
    "inventory": joblib.load(MODEL_DIR / "inventory_isolation_forest.pkl")
}

# Provisional operational thresholds, in milliseconds.
# Recalibrate after collecting representative baseline traffic.
THRESHOLDS = {
    "gateway": {
        "latency": 20.0,
        "response_time": 50.0
    },
    "auth": {
        "latency": 20.0,
        "response_time": 50.0
    },
    "inventory": {
        "latency": 20.0,
        "response_time": 50.0
    }
}
FAILURE_RATE_THRESHOLD = 20
MIN_SAMPLES = 5

ENABLE_ML_ALERTS = os.getenv("ENABLE_ML_ALERTS", "true").lower() == "true"

REQUIRED_FIELDS = [
    "service",
    "latency",
    "response_time",
    "failure_rate",
    "status",
    "failure_rate_pct",
    "timestamp",
    "p95_latency_ms",
    "p95_response_time_ms",
    "consecutive_failures",
    "sample_count",
    "last_error"
]


# ---------------------------------------------------
# 1. Validate incoming metrics
# ---------------------------------------------------

def validate_metrics(metrics):

    missing_fields = []

    for field in REQUIRED_FIELDS:
        if field not in metrics:
            missing_fields.append(field)

    if missing_fields:
        return False, missing_fields

    return True, []


# ---------------------------------------------------
# 2. Detect rule-based anomalies
# ---------------------------------------------------

def detect_anomalies(metrics):

    anomalies = []

    service = metrics["service"]

    # Rule 1: Service is completely unreachable
    if metrics["status"] == "DOWN":
        anomalies.append({
            "type": "SERVICE_DOWN",
            "severity": "critical",
            "message": f"{service} is unreachable"
        })

    # Avoid making decisions with too little data
    if metrics["sample_count"] < MIN_SAMPLES:
        return anomalies

    # Rule 2: Too many probes are failing
    if metrics["failure_rate_pct"] > FAILURE_RATE_THRESHOLD:
        anomalies.append({
            "type": "HIGH_FAILURE_RATE",
            "severity": "critical",
            "message": f"{metrics['failure_rate_pct']}% of recent probes failed"
        })

    # Get thresholds for this service
    service_thresholds = THRESHOLDS.get(service)

    if service_thresholds is None:
        return anomalies

    # Rule 3: High latency
    latency_limit = service_thresholds["latency"]

    if (
        metrics["latency"] is not None
        and metrics["latency"] > latency_limit
    ):
        anomalies.append({
            "type": "HIGH_LATENCY",
            "severity": "warning",
            "message":
                f"Latency is {metrics['latency']} ms "
                f"(operational threshold: {round(latency_limit, 3)} ms)"
        })

    # Rule 4: High response time
    response_limit = service_thresholds["response_time"]

    if (
        metrics["response_time"] is not None
        and metrics["response_time"] > response_limit
    ):
        anomalies.append({
            "type": "HIGH_RESPONSE_TIME",
            "severity": "warning",
            "message":
                f"Response time is {metrics['response_time']} ms "
                f"(operational threshold: {round(response_limit, 3)} ms)"
        })

    return anomalies


def detect_ml_anomaly(metrics):

    service = metrics["service"]

    if service not in ML_MODELS:
        return None

    for feature in ML_FEATURES:
        if metrics.get(feature) is None:
            return None

    input_data = pd.DataFrame(
        [[metrics[feature] for feature in ML_FEATURES]],
        columns=ML_FEATURES
    )

    model = ML_MODELS[service]

    prediction = model.predict(input_data)[0]
    score = model.decision_function(input_data)[0]

    # Explain the model's prediction using XAI
    explanation = explain_anomaly(model, input_data)

    if prediction == -1:
        return {
            "is_anomaly": True,
            "type": "ML_ANOMALY",
            "severity": "warning",
            "score": round(float(score), 4),
            "message": "Network behaviour is unusual compared with the learned baseline",
            "explanation": explanation
        }


    return {
        "is_anomaly": False,
        "score": round(float(score), 4)
    }
# ---------------------------------------------------
# 3. Main monitoring loop
# ---------------------------------------------------


def main():

    while True:

        try:

            # Get latest network metrics from Person 2's monitoring API
            response = requests.get(
                MONITOR_URL,
                timeout=5
            )

            # Raise an exception for HTTP errors such as 500
            response.raise_for_status()

            # Convert JSON response into Python data
            all_metrics = response.json()

            print("\n--- NetGuardian Anomaly Check ---")

            # Check every monitored service
            for metrics in all_metrics:

                # First make sure the data is valid
                valid, missing_fields = validate_metrics(metrics)

                if not valid:
                    print(
                        f"⚠ {metrics.get('service', 'unknown')}: "
                        f"invalid metrics - "
                        f"missing {missing_fields}"
                    )

                    continue

                # Run all anomaly detection rules
                anomalies = detect_anomalies(metrics)

                ml_result = detect_ml_anomaly(metrics)

                if ml_result is not None and ml_result["is_anomaly"]:
                  anomalies.append(ml_result)


                # If any anomaly was detected
                if anomalies:

                    print(
                        f"\n⚠ {metrics['service']}"
                    )

                    for anomaly in anomalies:

                        print(
                            f"  [{anomaly['severity'].upper()}] "
                            f"{anomaly['type']} - "
                            f"{anomaly['message']}"
                        )

                # No anomaly detected
                else:

                    print(
                        f"✓ {metrics['service']}: healthy"
                    )

        except requests.RequestException as error:

            print(
                "Could not connect to monitoring API:",
                error
            )

        # Wait before checking again
        time.sleep(2)


# ---------------------------------------------------
# 4. Start the program
# ---------------------------------------------------

if __name__ == "__main__":
    main()
    