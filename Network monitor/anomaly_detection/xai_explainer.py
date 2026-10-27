
def explain_anomaly(model, input_data):
    """
    Explain an Isolation Forest prediction using
    multi-scale feature perturbation.

    Lower decision_function scores indicate
    more anomalous observations.

    Sensitivity is NOT a probability or
    a causal feature contribution.
    """

    original_score = float(
        model.decision_function(input_data)[0]
    )

    explanations = []

    # Test larger changes than the previous 10%.
    multipliers = [0.0, 0.25, 0.5, 0.75, 1.25, 2.0]

    for feature in input_data.columns:
        original_value = float(
            input_data.iloc[0][feature]
        )

        results = []

        for multiplier in multipliers:
            modified = input_data.copy()

            if original_value == 0:
                new_value = multiplier
            else:
                new_value = original_value * multiplier

            modified.loc[
                modified.index[0], feature
            ] = new_value

            new_score = float(
                model.decision_function(modified)[0]
            )

            results.append({
                "tested_value": round(new_value, 6),
                "score_change": round(
                    new_score - original_score, 6
                )
            })

        sensitivity = max(
            abs(item["score_change"])
            for item in results
        )

        explanations.append({
            "feature": feature,
            "value": original_value,
            "sensitivity": round(sensitivity, 6),
            "tested_changes": results
        })

    explanations.sort(
        key=lambda item: item["sensitivity"],
        reverse=True
    )

    top_feature = (
        explanations[0]["feature"]
        if explanations
        and explanations[0]["sensitivity"] > 0
        else None
    )

    return {
        "method": "multi_scale_sensitivity",
        "original_score": round(original_score, 6),
        "top_feature": top_feature,
        "explanation_available": top_feature is not None,
        "feature_explanations": explanations
    }
