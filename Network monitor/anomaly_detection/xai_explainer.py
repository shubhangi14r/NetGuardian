import pandas as pd


def explain_anomaly(model, input_data):
    """
    Local sensitivity explanation for Isolation Forest.

    Measures how changing one feature by +10% or
    -10% affects the model's anomaly decision score.
    """

    original_score = float(
        model.decision_function(input_data)[0]
    )

    explanations = []

    for feature in input_data.columns:
        original_value = float(input_data.iloc[0][feature])

        # Use a nonzero step even for zero-valued features.
        step = max(abs(original_value) * 0.10, 0.01)

        changed_scores = []

        for new_value in (
            original_value + step,
            original_value - step
        ):
            modified = input_data.copy()
            modified.loc[modified.index[0], feature] = max(
                0.0, new_value
            )

            new_score = float(
                model.decision_function(modified)[0]
            )

            changed_scores.append(new_score)

        sensitivity = max(
            abs(score - original_score)
            for score in changed_scores
        )

        explanations.append({
            "feature": feature,
            "value": original_value,
            "sensitivity": round(sensitivity, 6)
        })

    explanations.sort(
        key=lambda item: item["sensitivity"],
        reverse=True
    )

    return {
        "method": "local_sensitivity",
        "top_feature": explanations[0]["feature"],
        "feature_explanations": explanations
    }