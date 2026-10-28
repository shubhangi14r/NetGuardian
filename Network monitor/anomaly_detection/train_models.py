import pandas as pd
import joblib
from sklearn.ensemble import IsolationForest

DATA_FILE = "network_metrics.csv"

FEATURES = [
    "latency",
    "response_time",
    "p95_latency_ms",
    "p95_response_time_ms"
]

SERVICES = [
    "gateway",
    "auth",
    "inventory"
]

df = pd.read_csv(DATA_FILE, low_memory=False)

for service in SERVICES:
    data = df[df["service"] == service].copy()
    data = data.dropna(subset=FEATURES)

    X = data[FEATURES]

    print(f"Training {service} with {len(X)} samples")

    model = IsolationForest(
        n_estimators=200,
        contamination=0.05,
        random_state=42,
        n_jobs=-1
    )

    model.fit(X)

    filename = f"{service}_isolation_forest.pkl"
    joblib.dump(model, filename)

    print(f"Saved {filename}")

print("Training complete")
