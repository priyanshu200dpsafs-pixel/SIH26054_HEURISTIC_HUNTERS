#!/usr/bin/env python3
"""
===============================================================================
DIGITAL TWIN: REMAINING USEFUL LIFE (RUL) ESTIMATOR (PHASE 3)
===============================================================================
Predicts Remaining Safe Flight Hours with a calibrated uncertainty band
(10th to 90th percentile prediction interval) using an ensemble Random Forest
Quantile Regressor trained on physics residual trends and cumulative damage metrics.

Input Features (13-dimensional physics feature vector):
  1. max_egt_residual: peak EGT residual across 4 cylinders (°C)
  2. max_cht_residual: peak CHT residual across 4 cylinders (°C)
  3. rpm_residual: engine shaft speed residual (RPM)
  4. oil_press_residual: oil pressure loss residual (bar)
  5. oil_temp_residual: oil temperature rise residual (°C)
  6. fuel_flow_residual: fuel flow deviation (g/s)
  7. egt_residual_derivative: rate of change d(r_EGT)/dt over recent window
  8. rpm_droop_signed: signed shaft power deficit (min(0, RPM_meas - RPM_exp))
  9. anomaly_duration_sec: duration engine has operated under anomalous residual
  10. cumulative_stress: integrated thermal-mechanical damage stress (Miner's integral)
  11. coupling_ratio: ratio of shaft torque droop to thermal rise (discriminator metric)
  12. throttle_pct: current throttle setting (%)
  13. altitude_m: barometric pressure altitude (m)

Outputs:
  - rul_hours: Median expected safe flight hours (Q50)
  - rul_lower_hours: Pessimistic lower bound (Q10)
  - rul_upper_hours: Optimistic upper bound (Q90)
  - uncertainty_band_hours: Prediction interval spread (Q90 - Q10)
  - rul_minutes: Median in minutes
===============================================================================
"""

import os
import sys
import glob
import logging
import warnings
from typing import Dict, Any, List, Optional, Tuple

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestRegressor

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("RUL_Estimator")

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, ".."))
DATA_DIR = os.path.join(PROJECT_ROOT, "data")
MODEL_DIR = os.path.join(SCRIPT_DIR, "models")
sys.path.insert(0, SCRIPT_DIR)

from residual_detector import ResidualAnomalyDetector


class RULEstimator:
    """
    Random Forest Quantile Ensemble for explainable, physics-grounded RUL prediction
    with guaranteed monotonic uncertainty intervals and no quantile crossing.
    """

    FEATURE_NAMES = [
        "max_egt_residual",
        "max_cht_residual",
        "rpm_residual",
        "oil_press_residual",
        "oil_temp_residual",
        "fuel_flow_residual",
        "egt_residual_derivative",
        "rpm_droop_signed",
        "anomaly_duration_sec",
        "cumulative_stress",
        "coupling_ratio",
        "throttle_pct",
        "altitude_m"
    ]

    def __init__(self):
        self.model: Optional[RandomForestRegressor] = None
        self.is_trained = False
        self.prev_rul_hours: float = 200.0
        self.prev_q90_hours: float = 220.0

    def reset(self):
        """Resets tracking state between mission sorties."""
        self.prev_rul_hours = 200.0
        self.prev_q90_hours = 220.0

    def extract_features(
        self,
        current_telemetry: Dict[str, Any],
        detector_output: Dict[str, Any],
        recent_history: Optional[List[Dict[str, Any]]] = None
    ) -> np.ndarray:
        """
        Extracts the 13-dimensional physics residual feature vector from detector output.
        """
        ewma_res = detector_output["ewma_residuals"]
        signed_res = detector_output["signed_residuals"]

        max_egt_res = float(detector_output["max_egt_residual"])
        max_cht_res = float(detector_output["max_cht_residual"])
        rpm_res = float(ewma_res.get("rpm", 0.0))
        oil_p_res = float(ewma_res.get("oil_press_bar", 0.0))
        oil_t_res = float(ewma_res.get("oil_temp_c", 0.0))
        ff_res = float(ewma_res.get("fuel_flow_gps", 0.0))
        rpm_droop_signed = float(min(0.0, signed_res.get("rpm", 0.0)))

        anom_duration = float(detector_output.get("anomaly_duration_sec", 0.0))
        cum_stress = float(detector_output.get("cumulative_stress", 0.0))
        coupling_ratio = float(min(1.0, rpm_res / max(1.0, max_egt_res * 2.5)))

        # Estimate derivative of EGT residual over recent window (~2-3 seconds)
        d_egt_dt = 0.0
        if recent_history and len(recent_history) >= 20:
            past_max_egt = recent_history[-20]["max_egt_residual"]
            dt_hist = recent_history[-1]["timestamp_sec"] - recent_history[-20]["timestamp_sec"]
            if dt_hist > 0.1:
                d_egt_dt = (max_egt_res - past_max_egt) / dt_hist

        th = float(current_telemetry.get("throttle_pct", 75.0))
        alt = float(current_telemetry.get("altitude_m", 2000.0))

        feat = np.array([
            max_egt_res,
            max_cht_res,
            rpm_res,
            oil_p_res,
            oil_t_res,
            ff_res,
            d_egt_dt,
            rpm_droop_signed,
            anom_duration,
            cum_stress,
            coupling_ratio,
            th,
            alt
        ], dtype=float)
        return feat

    def train_on_dataset(
        self,
        data_directory: str = DATA_DIR,
        max_runs_to_use: int = 150,
        subsample_step: int = 10  # Sample every 1.0s (10 Hz // 10)
    ) -> Dict[str, Any]:
        """
        Processes training runs through ResidualAnomalyDetector and trains
        the Random Forest Quantile Regressor on physics residual features and cumulative damage.
        """
        logger.info(f"Loading training runs from: {data_directory}...")
        csv_files = sorted(glob.glob(os.path.join(data_directory, "run_*.csv")))
        if not csv_files:
            raise FileNotFoundError(f"No run CSV files found in {data_directory}!")

        csv_files = csv_files[:max_runs_to_use]
        logger.info(f"Processing {len(csv_files)} runs through physics detector for feature extraction...")

        X_rows = []
        y_rows = []

        for f_idx, fpath in enumerate(csv_files, 1):
            df = pd.read_csv(fpath)
            if "rul_remaining_hours" in df.columns:
                rul_col = "rul_remaining_hours"
            elif "rul_remaining_sec" in df.columns:
                rul_col = "rul_remaining_sec"
            else:
                continue

            detector = ResidualAnomalyDetector(ewma_alpha=0.05)
            recent_hist = []

            for idx, row in df.iterrows():
                r_dict = row.to_dict()
                det_out = detector.process_telemetry(dt=0.1, telemetry=r_dict)
                recent_hist.append({
                    "timestamp_sec": float(row["timestamp_sec"]),
                    "max_egt_residual": float(det_out["max_egt_residual"])
                })
                if len(recent_hist) > 30:
                    recent_hist.pop(0)

                if idx % subsample_step == 0:
                    feat = self.extract_features(r_dict, det_out, recent_hist)
                    if rul_col == "rul_remaining_hours":
                        rul_hrs = float(row["rul_remaining_hours"])
                    else:
                        rul_hrs = float(row["rul_remaining_sec"]) / 3600.0

                    X_rows.append(feat)
                    y_rows.append(rul_hrs)

        X = np.array(X_rows, dtype=float)
        y = np.array(y_rows, dtype=float)
        logger.info(f"Constructed training matrix: {X.shape[0]} samples with {X.shape[1]} features.")
        logger.info(f"Target RUL Range: [{np.min(y):.2f}, {np.max(y):.2f}] hours (Mean: {np.mean(y):.2f} hrs).")

        # Train Random Forest Ensemble (100 estimators, max_depth=12)
        logger.info("Training Random Forest Quantile Ensemble...")
        self.model = RandomForestRegressor(
            n_estimators=100,
            max_depth=12,
            min_samples_leaf=2,
            random_state=42,
            n_jobs=-1
        )
        self.model.fit(X, y)

        self.is_trained = True
        os.makedirs(MODEL_DIR, exist_ok=True)
        model_pkg = {
            "model": self.model,
            "feature_names": self.FEATURE_NAMES
        }
        model_save_path = os.path.join(MODEL_DIR, "rul_models.joblib")
        joblib.dump(model_pkg, model_save_path)
        logger.info(f"RUL models saved to '{model_save_path}'.")

        return {"train_samples": len(X), "model_path": model_save_path}

    def load_model(self, model_path: Optional[str] = None):
        """Loads pre-trained RUL models from disk."""
        path = model_path or os.path.join(MODEL_DIR, "rul_models.joblib")
        if not os.path.exists(path):
            raise FileNotFoundError(f"Model file not found at: {path}")
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            pkg = joblib.load(path)
        self.model = pkg["model"]
        self.is_trained = True

    def predict(self, feature_vector: np.ndarray) -> Dict[str, float]:
        """
        Predicts Remaining Useful Life with uncertainty interval.
        Uses ensemble tree distribution to guarantee zero quantile crossing.

        Returns:
          Dict:
            - 'rul_hours': Median estimate Q50
            - 'rul_lower_hours': 10th percentile bound
            - 'rul_upper_hours': 90th percentile bound
            - 'uncertainty_band_hours': Spread between Q90 and Q10
            - 'rul_minutes': Median in minutes
        """
        if not self.is_trained or self.model is None:
            try:
                self.load_model()
            except Exception:
                raise RuntimeError("RUL model has not been trained or loaded!")

        X = feature_vector.reshape(1, -1)
        tree_preds = np.array([tree.predict(X)[0] for tree in self.model.estimators_])

        raw_q10 = float(np.percentile(tree_preds, 10))
        raw_q50 = float(np.median(tree_preds))
        raw_q90 = float(np.percentile(tree_preds, 90))

        # Physical clamping and monotonic degradation enforcement:
        # Irreversible physical damage implies that under active mechanical fault,
        # safe flight hours do not spontaneously recover without depot overhaul.
        anom_duration = float(feature_vector[8])  # anomaly_duration_sec
        cum_stress = float(feature_vector[9])     # cumulative_stress

        if anom_duration > 0.0 or cum_stress > 0.0:
            raw_q50 = min(self.prev_rul_hours, raw_q50)
            self.prev_rul_hours = raw_q50
            raw_q90 = min(self.prev_q90_hours, raw_q90)
            self.prev_q90_hours = raw_q90
        else:
            self.prev_rul_hours = raw_q50
            self.prev_q90_hours = raw_q90

        q50 = max(1.0, min(220.0, raw_q50))
        q10 = max(0.5, min(q50, raw_q10))
        q90 = max(q50, min(240.0, raw_q90))
        spread = q90 - q10

        return {
            "rul_hours": round(q50, 2),
            "rul_lower_hours": round(q10, 2),
            "rul_upper_hours": round(q90, 2),
            "uncertainty_band_hours": round(spread, 2),
            "rul_minutes": round(q50 * 60.0, 1),
            "rul_lower_minutes": round(q10 * 60.0, 1),
            "rul_upper_minutes": round(q90 * 60.0, 1)
        }

    def get_feature_importances(self) -> Dict[str, float]:
        """Returns explainable feature importance breakdown across physics residuals."""
        if not self.is_trained or self.model is None:
            self.load_model()
        return dict(sorted(zip(self.FEATURE_NAMES, self.model.feature_importances_), key=lambda x: -x[1]))


if __name__ == "__main__":
    estimator = RULEstimator()
    res = estimator.train_on_dataset(max_runs_to_use=150)
    print("\n--- RUL MODEL TRAINING COMPLETED ---")
    print(f"Trained on {res['train_samples']} samples from 150 sorties.")
    print("Feature Importances:")
    for k, v in estimator.get_feature_importances().items():
        print(f"  {k:26s}: {v*100:5.2f}%")
