#!/usr/bin/env python3
"""
===============================================================================
DIGITAL TWIN: RESIDUAL CALCULATOR & ANOMALY DETECTOR (PHASE 3)
===============================================================================
Calculates physics-grounded residuals:
  r_k(t) = | y_sensor,k(t) - y_expected,k(t) |
and applies Exponentially Weighted Moving Average (EWMA) filtering to detect
developing anomalies BEFORE raw parameters cross safety redlines.
===============================================================================
"""

import os
import sys
from typing import Dict, Any, List, Optional, Tuple

import numpy as np

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)

from physics_estimator import PhysicsExpectedEstimator


class ResidualAnomalyDetector:
    """
    Tracks sensor-to-model residuals in real-time, suppresses noise via EWMA,
    and flags developing thermal and mechanical anomalies.
    """

    def __init__(self, ewma_alpha: float = 0.05):
        self.estimator = PhysicsExpectedEstimator()
        self.alpha = ewma_alpha  # Filter smoothing parameter (0.05 @ 10 Hz ~ 2s lag)
        
        # Tracked signals
        self.signals = [
            "rpm",
            "egt1", "egt2", "egt3", "egt4",
            "cht1", "cht2", "cht3", "cht4",
            "oil_press_bar", "oil_temp_c", "fuel_flow_gps"
        ]

        # EWMA residual state
        self.ewma_residuals: Dict[str, float] = {s: 0.0 for s in self.signals}
        self.raw_residuals: Dict[str, float] = {s: 0.0 for s in self.signals}
        self.signed_residuals: Dict[str, float] = {s: 0.0 for s in self.signals}

        # Calibrated Statistical Thresholds (3-sigma bounds + transient margins)
        # Why: Set above Gaussian sensor noise (3 * sigma) and normal throttle rate mismatch,
        # but far below destructive physical damage thresholds.
        self.alert_thresholds = {
            "rpm": 120.0,              # RPM droop threshold
            "egt1": 28.0, "egt2": 28.0, "egt3": 28.0, "egt4": 28.0,  # °C (Catches clog at +28°C rise!)
            "cht1": 12.0, "cht2": 12.0, "cht3": 12.0, "cht4": 12.0,  # °C
            "oil_press_bar": 0.40,     # bar
            "oil_temp_c": 8.0,         # °C
            "fuel_flow_gps": 0.45      # g/s
        }

        # Caution thresholds (60% of alert threshold for yellow advisory)
        self.caution_thresholds = {k: v * 0.60 for k, v in self.alert_thresholds.items()}

        # Cumulative damage and anomaly exposure tracking (PHM fatigue integration)
        self.anomaly_duration_sec: float = 0.0
        self.cumulative_stress: float = 0.0
        self.is_mechanical_fault: bool = False

    def reset(self):
        """Resets detector state and internal physics estimator."""
        self.estimator.reset()
        self.ewma_residuals = {s: 0.0 for s in self.signals}
        self.raw_residuals = {s: 0.0 for s in self.signals}
        self.signed_residuals = {s: 0.0 for s in self.signals}
        self.anomaly_duration_sec = 0.0
        self.cumulative_stress = 0.0
        self.is_mechanical_fault = False

    def process_telemetry(
        self,
        dt: float,
        telemetry: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Ingests a 10 Hz telemetry sample (from CAN or plant), steps the physics
        estimator, computes residuals, and flags anomaly status.

        Returns:
          Dict containing:
            - 'expected': Dict of expected values
            - 'residuals': Dict of instantaneous residuals
            - 'ewma_residuals': Filtered residuals
            - 'status': 'NORMAL', 'CAUTION', or 'ALERT'
            - 'alerted_signals': List of signals breaching threshold
            - 'max_egt_residual': Peak EGT residual across 4 cylinders
            - 'max_cht_residual': Peak CHT residual across 4 cylinders
        """
        th = float(telemetry.get("throttle_pct", 50.0))
        alt = float(telemetry.get("altitude_m", 1500.0))
        ias = float(telemetry.get("airspeed_mps", 40.0))

        # 1. Step independent physics estimator
        exp = self.estimator.step(dt=dt, throttle_pct=th, altitude_m=alt, airspeed_mps=ias)

        # 2. Compute residuals
        alerted_signals = []
        caution_signals = []
        status = "NORMAL"

        for s in self.signals:
            meas_val = float(telemetry.get(s, 0.0))
            exp_val = float(exp[f"{s}_exp"])
            
            # Signed residual: (meas - exp)
            signed_diff = meas_val - exp_val
            abs_diff = abs(signed_diff)

            self.signed_residuals[s] = signed_diff
            self.raw_residuals[s] = abs_diff

            # Update EWMA filter: S(t) = alpha * r(t) + (1 - alpha) * S(t-1)
            prev_ewma = self.ewma_residuals[s]
            curr_ewma = self.alpha * abs_diff + (1.0 - self.alpha) * prev_ewma
            self.ewma_residuals[s] = round(curr_ewma, 3)

            # Check thresholds
            if curr_ewma >= self.alert_thresholds[s]:
                alerted_signals.append(s)
            elif curr_ewma >= self.caution_thresholds[s]:
                caution_signals.append(s)

        if len(alerted_signals) > 0:
            status = "ALERT"
        elif len(caution_signals) > 0:
            status = "CAUTION"

        # Cylinder unbalance metrics
        egt_residuals = [self.ewma_residuals[f"egt{i}"] for i in range(1, 5)]
        cht_residuals = [self.ewma_residuals[f"cht{i}"] for i in range(1, 5)]

        max_egt_res = max(egt_residuals)
        max_cht_res = max(cht_residuals)
        affected_egt_cyl = int(np.argmax(egt_residuals)) + 1
        affected_cht_cyl = int(np.argmax(cht_residuals)) + 1

        # Check for genuine physical power/mechanical fault vs sensor drift:
        # A plant fault produces correlated power droop or loss of oil pressure or CHT rise
        rpm_r = self.ewma_residuals["rpm"]
        oil_p_r = self.ewma_residuals["oil_press_bar"]
        is_mech = (
            (max_egt_res > 20.0 and rpm_r > 40.0) or
            (oil_p_r > 0.30) or
            (max_cht_res > 10.0)
        )
        self.is_mechanical_fault = is_mech

        if is_mech:
            self.anomaly_duration_sec += dt
            step_stress = (
                max(0.0, max_egt_res - self.caution_thresholds["egt1"]) * 1.0 +
                max(0.0, max_cht_res - self.caution_thresholds["cht1"]) * 4.0 +
                max(0.0, rpm_r - 40.0) * 0.3 +
                max(0.0, oil_p_r - 0.25) * 200.0
            )
            self.cumulative_stress += step_stress * dt

        return {
            "timestamp_sec": telemetry.get("timestamp_sec", 0.0),
            "status": status,
            "alerted_signals": alerted_signals,
            "caution_signals": caution_signals,
            "expected": exp,
            "raw_residuals": dict(self.raw_residuals),
            "signed_residuals": dict(self.signed_residuals),
            "ewma_residuals": dict(self.ewma_residuals),
            "max_egt_residual": max_egt_res,
            "max_cht_residual": max_cht_res,
            "affected_egt_cylinder": affected_egt_cyl,
            "affected_cht_cylinder": affected_cht_cyl,
            "anomaly_duration_sec": round(self.anomaly_duration_sec, 2),
            "cumulative_stress": round(self.cumulative_stress, 2),
            "is_mechanical_fault": self.is_mechanical_fault,
        }
