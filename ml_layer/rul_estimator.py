#!/usr/bin/env python3
"""
===============================================================================
DIGITAL TWIN: REMAINING USEFUL LIFE (RUL) ESTIMATOR (PHASE 3A)
===============================================================================
Predicts Remaining Safe Flight Hours with a calibrated uncertainty band
(10th to 90th percentile prediction interval) using an ensemble Random Forest
Quantile Regressor trained on physics residual trends and cumulative damage metrics.

SCIENTIFIC AUDIT & REBUILD UPGRADES (PHASE 3A):
  1. STATELESS INFERENCE: The estimator's predict() method is strictly stateless.
     The exact same feature vector always produces the exact same prediction,
     with zero hidden state or unannounced post-inference clamping.
  2. DECOUPLED TEMPORAL FILTER: A dedicated TemporalRULFilter class handles
     continuous stream smoothing when deployed in live telemetry missions.
  3. MISSION-GROUPED TRAINING: Training operates strictly on held-in TRAIN sorties;
     zero validation or test sorties are ingested during model training.
  4. QUANTILE INTERVALS: Computes Q10, Q50, and Q90 bounds directly across
     the ensemble tree predictions, guaranteeing Q10 <= Q50 <= Q90 without
     quantile crossing.
  5. BASELINES: Exposes Baseline A (Constant Healthy RUL) and Baseline B
     (Deterministic Physics Limit-Margin Estimator) for rigorous benchmarking.

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


# =============================================================================
# 1. BASELINE ESTIMATORS FOR BENCHMARKING
# =============================================================================
class BaselineA_ConstantRUL:
    """
    Baseline A: Naive constant healthy engine RUL.
    Always predicts nominal Time-Between-Overhaul (TBO) safe operating hours (195.0 hrs).
    """
    def __init__(self, constant_rul_hours: float = 195.0):
        self.constant_rul_hours = constant_rul_hours

    def predict(self, feature_vector: np.ndarray) -> Dict[str, float]:
        val = self.constant_rul_hours
        return {
            "rul_hours": round(val, 2),
            "rul_lower_hours": round(val - 15.0, 2),
            "rul_upper_hours": round(val + 15.0, 2),
            "uncertainty_band_hours": 30.0,
            "rul_minutes": round(val * 60.0, 1),
        }


class BaselineB_PhysicsLimitEstimator:
    """
    Baseline B: Deterministic, physics/damage-derived limit-margin estimator.
    Calculates remaining safe flight hours directly from thermodynamic limit proximity:
      - EGT continuous caution: 880°C, Redline: 950°C (Margin: 70°C)
      - CHT continuous caution: 200°C, Redline: 250°C (Margin: 50°C)
      - Oil Pressure minimum: 1.50 bar (Margin: 1.50 bar)
      - Oil Temperature critical: 125°C (Margin: 20°C)

    Does NOT use machine learning or random forests. Pure analytical calculation.
    """
    def __init__(self, nominal_tbo_hours: float = 195.0):
        self.nominal_tbo_hours = nominal_tbo_hours

    def predict(
        self,
        feature_vector: np.ndarray,
        current_telemetry: Optional[Dict[str, Any]] = None
    ) -> Dict[str, float]:
        max_egt_res = float(feature_vector[0])
        max_cht_res = float(feature_vector[1])
        oil_p_res = float(feature_vector[3])
        oil_t_res = float(feature_vector[4])
        anom_duration = float(feature_vector[8])
        cum_stress = float(feature_vector[9])

        # Compute normalized severity across physical limits
        s_egt = max_egt_res / 70.0
        s_cht = max_cht_res / 50.0
        s_oil_p = oil_p_res / 1.50
        s_oil_t = oil_t_res / 20.0

        peak_severity = max(s_egt, s_cht, s_oil_p, s_oil_t)

        if peak_severity < 0.25 and anom_duration < 1.0:
            # Engine is in nominal healthy regime
            pred_rul = max(100.0, self.nominal_tbo_hours - 0.05 * anom_duration)
            q10 = pred_rul - 12.0
            q90 = pred_rul + 12.0
        else:
            # Active thermodynamic/mechanical degradation
            sev_clamped = min(1.0, max(0.0, peak_severity))
            # Analytical degradation curve: severe drop followed by time-stress attrition
            stress_reduction = (self.nominal_tbo_hours - 30.0) * (sev_clamped ** 0.75)
            time_wear = 0.25 * anom_duration + 0.01 * cum_stress
            pred_rul = max(2.0, self.nominal_tbo_hours - stress_reduction - time_wear)
            # Physical uncertainty spreads as damage progresses
            spread = max(4.0, 15.0 * (1.0 + sev_clamped))
            q10 = max(0.5, pred_rul - spread * 0.5)
            q90 = pred_rul + spread * 0.5

        return {
            "rul_hours": round(pred_rul, 2),
            "rul_lower_hours": round(q10, 2),
            "rul_upper_hours": round(q90, 2),
            "uncertainty_band_hours": round(q90 - q10, 2),
            "rul_minutes": round(pred_rul * 60.0, 1),
        }


# =============================================================================
# 2. DECOUPLED TEMPORAL STREAM FILTER
# =============================================================================
class TemporalRULFilter:
    """
    Independent temporal post-processing filter for mission telemetry streaming.
    Decoupled completely from raw model inference.
    Enforces continuous monotonic degradation tracking under active faults.
    """
    def __init__(self, initial_rul_hours: float = 195.0):
        self.initial_rul_hours = initial_rul_hours
        self.current_rul_hours = initial_rul_hours
        self.current_q90_hours = initial_rul_hours + 20.0

    def reset(self):
        """Resets filter tracking state between mission sorties."""
        self.current_rul_hours = self.initial_rul_hours
        self.current_q90_hours = self.initial_rul_hours + 20.0

    def filter(
        self,
        raw_pred: Dict[str, float],
        is_active_fault: bool = False
    ) -> Dict[str, float]:
        """
        Applies monotonic degradation tracking if an active fault has been confirmed.
        """
        q50 = raw_pred["rul_hours"]
        q10 = raw_pred["rul_lower_hours"]
        q90 = raw_pred["rul_upper_hours"]

        if is_active_fault:
            self.current_rul_hours = min(self.current_rul_hours, q50)
            self.current_q90_hours = min(self.current_q90_hours, q90)
        else:
            self.current_rul_hours = q50
            self.current_q90_hours = q90

        filt_q50 = max(0.5, self.current_rul_hours)
        filt_q10 = max(0.2, min(filt_q50, q10))
        filt_q90 = max(filt_q50, self.current_q90_hours)
        spread = filt_q90 - filt_q10

        return {
            "rul_hours": round(filt_q50, 2),
            "rul_lower_hours": round(filt_q10, 2),
            "rul_upper_hours": round(filt_q90, 2),
            "uncertainty_band_hours": round(spread, 2),
            "rul_minutes": round(filt_q50 * 60.0, 1),
            "rul_lower_minutes": round(filt_q10 * 60.0, 1),
            "rul_upper_minutes": round(filt_q90 * 60.0, 1)
        }


# =============================================================================
# 3. STATELESS RANDOM FOREST QUANTILE ESTIMATOR
# =============================================================================
class RULEstimator:
    """
    Random Forest Quantile Ensemble for explainable, physics-grounded RUL prediction.
    Features strictly causal feature engineering and stateless prediction.
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

    def reset(self):
        """No-op: Model inference is strictly stateless."""
        pass

    def extract_features(
        self,
        current_telemetry: Dict[str, Any],
        detector_output: Dict[str, Any],
        recent_history: Optional[List[Dict[str, Any]]] = None
    ) -> np.ndarray:
        """
        Extracts the 13-dimensional physics residual feature vector from detector output.
        Strictly causal: information strictly at or before current timestep t.
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
        run_files: Optional[List[str]] = None,
        max_runs_to_use: int = 150,
        subsample_step: int = 10,
        random_seed: int = 42
    ) -> Dict[str, Any]:
        """
        Processes training runs through ResidualAnomalyDetector and trains
        the Random Forest Quantile Regressor on physics residual features and cumulative damage.

        If run_files is provided, ONLY those files (e.g. held-in TRAIN sorties) are used.
        """
        if run_files is not None:
            csv_files = [os.path.join(data_directory, f) if not os.path.isabs(f) else f for f in run_files]
        else:
            logger.info(f"Loading training runs from: {data_directory}...")
            csv_files = sorted(glob.glob(os.path.join(data_directory, "run_*.csv")))
            csv_files = csv_files[:max_runs_to_use]

        if not csv_files:
            raise FileNotFoundError(f"No run CSV files found to train on!")

        logger.info(f"Processing {len(csv_files)} training sorties through physics detector for feature extraction...")

        X_rows = []
        y_rows = []

        for fpath in csv_files:
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

        # Train Random Forest Ensemble (100 estimators, max_depth=12, fixed seed)
        logger.info("Training Random Forest Quantile Ensemble...")
        self.model = RandomForestRegressor(
            n_estimators=100,
            max_depth=12,
            min_samples_leaf=2,
            random_state=random_seed,
            n_jobs=-1
        )
        self.model.fit(X, y)

        self.is_trained = True
        os.makedirs(MODEL_DIR, exist_ok=True)
        model_pkg = {
            "model": self.model,
            "feature_names": self.FEATURE_NAMES,
            "train_runs_count": len(csv_files),
            "train_samples": len(X),
            "random_seed": random_seed
        }
        model_save_path = os.path.join(MODEL_DIR, "rul_models.joblib")
        joblib.dump(model_pkg, model_save_path)
        logger.info(f"RUL models saved to '{model_save_path}'.")

        return {
            "train_sorties": len(csv_files),
            "train_samples": len(X),
            "model_path": model_save_path
        }

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
        STRICTLY STATELESS RUL INFERENCE.
        Predicts Remaining Useful Life with calibrated uncertainty interval [Q10, Q90].
        The exact same feature vector always produces the exact same prediction.
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

        # Enforce valid physical bounds and monotonic quantile intervals without state mutation
        q50 = max(0.5, raw_q50)
        q10 = max(0.2, min(q50, raw_q10))
        q90 = max(q50, raw_q90)
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
        """Returns explainable model feature importance breakdown across physics residuals."""
        if not self.is_trained or self.model is None:
            self.load_model()
        return dict(sorted(zip(self.FEATURE_NAMES, self.model.feature_importances_), key=lambda x: -x[1]))


if __name__ == "__main__":
    from dataset_split import get_grouped_splits
    splits = get_grouped_splits(DATA_DIR, seed=42)
    train_files = [r["filename"] for r in splits["train"]]

    estimator = RULEstimator()
    res = estimator.train_on_dataset(
        data_directory=DATA_DIR,
        run_files=train_files,
        random_seed=42
    )
    print("\n--- RUL MODEL TRAINING COMPLETED (TRAIN SORTIES ONLY) ---")
    print(f"Trained on {res['train_samples']} samples from {res['train_sorties']} sorties.")
    print("Feature Importances (Model Feature Importance, Not Causal Importance):")
    for k, v in estimator.get_feature_importances().items():
        print(f"  {k:26s}: {v*100:5.2f}%")
