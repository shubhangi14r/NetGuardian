import pandas as pd
from anomaly_detector import ML_MODELS, ML_FEATURES
from xai_explainer import explain_anomaly

print("Available models:", list(ML_MODELS.keys()))
print("Model features:", ML_FEATURES)

if not ML_MODELS:
    raise RuntimeError("No trained models were loaded.")

service = next(iter(ML_MODELS))
model = ML_MODELS[service]

# Demonstration values only, not actual traffic.
sample_values = {
    feature: 100.0 for feature in ML_FEATURES
}

input_data = pd.DataFrame(
    [[sample_values[f] for f in ML_FEATURES]],
    columns=ML_FEATURES
)

prediction = model.predict(input_data)[0]
result = explain_anomaly(model, input_data)

print("\nService:", service)
print("Prediction:", "ANOMALY" if prediction == -1 else "NORMAL")
print("\nXAI Explanation:")
print(result)
