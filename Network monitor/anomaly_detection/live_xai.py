
import time
import requests
import pandas as pd

from anomaly_detector import ML_MODELS, ML_FEATURES
from xai_explainer import explain_anomaly

MONITOR_URL = "http://127.0.0.1:9000/metrics"

# Temporary mapping for live XAI demonstration
MODEL_MAPPING = {
    "gateway": "api-service",
    "auth": "secondary-service",
    "inventory": "database-service"
}

print("NetGuardian Live Explainable AI Started")
print("Press Ctrl+C to stop.")

try:
    while True:
        try:
            response = requests.get(
                MONITOR_URL, timeout=5
            )
            response.raise_for_status()

            services = response.json()

            for metrics in services:
                service = metrics.get("service")

                print("\n-------------------------")
                print("Service:", service)
                print("Status:", metrics.get("status"))

                if metrics.get("status") != "UP":
                    print("Skipping: Service is DOWN")
                    continue

                if any(
                    metrics.get(f) is None
                    for f in ML_FEATURES
                ):
                    print("Skipping: Missing metrics")
                    continue

                model_name = MODEL_MAPPING.get(service)

                if model_name not in ML_MODELS:
                    print("No model found for:", service)
                    continue

                model = ML_MODELS[model_name]

                X = pd.DataFrame(
                    [[float(metrics[f]) for f in ML_FEATURES]],
                    columns=ML_FEATURES
                )

                prediction = model.predict(X)[0]
                score = model.decision_function(X)[0]

                explanation = explain_anomaly(model, X)

                print("Live metrics:", X.iloc[0].to_dict())
                print(
                    "Prediction:",
                    "ANOMALY" if prediction == -1 else "NORMAL"
                )
                print("Anomaly score:", round(float(score), 6))
               
                # Human-readable Explainable AI output
                print("\n========== XAI EXPLANATION ==========")

                if prediction == -1:
                    print("AI Decision: ANOMALOUS")
                    print(
                        "The model classified this network "
                        "activity as unusual."
                    )
                else:
                    print("AI Decision: NORMAL")
                    print(
                        "The model classified this network "
                        "activity as normal."
                    )

                feature_names = {
                    "latency": "Network latency",
                    "response_time": "Response time",
                    "p95_latency_ms": "95th percentile latency",
                    "p95_response_time_ms":
                        "95th percentile response time"
                }

                ranked = explanation["feature_explanations"]

                print("\nFeature sensitivity analysis:")

                for index, item in enumerate(ranked, start=1):
                    name = feature_names.get(
                        item["feature"], item["feature"]
                    )

                    sensitivity = item["sensitivity"]

                    print(
                        f"{index}. {name}: "
                        f"sensitivity = {sensitivity:.6f}"
                    )

                if explanation["top_feature"] is not None:
                    top = feature_names.get(
                        explanation["top_feature"],
                        explanation["top_feature"]
                    )

                    print("\nExplanation:")
                    print(
                        f"The model's anomaly score is most "
                        f"sensitive to changes in {top} "
                        f"among the tested feature values."
                    )
                else:
                    print(
                        "\nNo measurable feature sensitivity "
                        "was found over the tested values."
                    )

                print(
                    "\nNote: Sensitivity describes how the "
                    "model score responds to feature changes. "
                    "It does not establish causation."
                )

                print("=====================================")


        except requests.RequestException as error:
            print("Monitoring API error:", error)

        time.sleep(5)

except KeyboardInterrupt:
    print("\nLive XAI stopped.")
