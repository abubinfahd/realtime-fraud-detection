"""
Azure Machine Learning Managed Online Endpoint Scoring Script.
Executes real-time Hybrid Fraud Detection (LightGBM + Isolation Forest).
"""

import json
import logging
import os
from pathlib import Path
import joblib
import numpy as np

bundle = None
lgb_model = None
iso_forest = None
feature_names = None
thresholds = None

FEATURE_COLUMNS = [
    "amount",
    "hour_of_day",
    "day_of_week",
    "is_weekend",
    "distance_from_home_km",
    "velocity_1h",
    "velocity_24h",
    "avg_amount_24h",
    "amount_to_avg_ratio",
    "high_risk_mcc",
]

def init():
    """Executed once when the inference container initializes."""
    global bundle, lgb_model, iso_forest, feature_names, thresholds
    
    logging.info("Initializing Azure ML Fraud Inference Engine...")
    
    # Azure ML mounts registered models to AZUREML_MODEL_DIR
    model_dir = os.getenv("AZUREML_MODEL_DIR", ".")
    
    # Locate fraud_model.joblib
    model_path = Path(model_dir) / "fraud_model.joblib"
    if not model_path.exists():
        # Search recursively in model directory
        candidates = list(Path(model_dir).rglob("fraud_model.joblib"))
        if candidates:
            model_path = candidates[0]
        else:
            raise FileNotFoundError(f"fraud_model.joblib not found in {model_dir}")

    logging.info(f"Loading model bundle from: {model_path}")
    bundle = joblib.load(model_path)
    
    lgb_model = bundle.get("supervised_model")
    iso_forest = bundle.get("unsupervised_model")
    feature_names = bundle.get("feature_names", FEATURE_COLUMNS)
    thresholds = bundle.get("thresholds", {"flagged": 0.40, "rejected": 0.75})
    
    logging.info(f"Loaded model bundle successfully. Features: {len(feature_names)}")


def run(raw_data):
    """
    Executed for every incoming prediction request.
    Expects JSON with 'data' key or a direct JSON transaction dictionary.
    """
    try:
        payload = json.loads(raw_data)
        
        # Support both {"data": [...]} and {"amount": 500, ...}
        if isinstance(payload, dict) and "data" in payload:
            items = payload["data"]
            if isinstance(items, dict):
                items = [items]
        elif isinstance(payload, list):
            items = payload
        else:
            items = [payload]

        results = []
        for item in items:
            # Extract features in expected order
            features = []
            for col in feature_names:
                val = float(item.get(col, 0.0))
                features.append(val)
            
            X = np.asarray(features, dtype=np.float64).reshape(1, -1)
            
            # 1. Supervised Fraud Probability (LightGBM)
            fraud_prob = float(lgb_model.predict_proba(X)[0, 1]) if lgb_model else 0.0
            
            # 2. Unsupervised Anomaly Score (Isolation Forest)
            if iso_forest:
                raw_anomaly = float(iso_forest.decision_function(X)[0])
                # Sigmoid normalization (outliers closer to 1.0)
                anomaly_score = float(1.0 / (1.0 + np.exp(raw_anomaly * 4.0)))
            else:
                anomaly_score = 0.0
            
            # 3. Composite Risk Score (65% LightGBM + 35% Isolation Forest)
            composite_risk = float(np.clip(0.65 * fraud_prob + 0.35 * anomaly_score, 0.0, 1.0))
            
            # 4. Final Verdict
            flagged_thresh = thresholds.get("flagged", 0.40)
            rejected_thresh = thresholds.get("rejected", 0.75)
            
            if composite_risk >= rejected_thresh:
                status = "REJECTED"
            elif composite_risk >= flagged_thresh:
                status = "FLAGGED"
            else:
                status = "APPROVED"
                
            results.append({
                "status": status,
                "risk_score": round(composite_risk, 4),
                "lightgbm_fraud_prob": round(fraud_prob, 4),
                "isolation_forest_anomaly": round(anomaly_score, 4),
                "thresholds": {"flagged": flagged_thresh, "rejected": rejected_thresh}
            })
            
        return {"predictions": results}

    except Exception as e:
        logging.error(f"Prediction error: {str(e)}", exc_info=True)
        return {"error": str(e)}

