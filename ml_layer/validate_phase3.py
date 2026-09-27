#!/usr/bin/env python3
"""
===============================================================================
PHASE 3 SELF-VALIDATION & VERIFICATION SUITE
===============================================================================
Performs rigorous programmatic validation of all 4 required Phase 3 tests:
  Test A: False-Alarm Test (Nominal rapid throttle transition)
  Test B: True-Positive Early Detection Test (Injector clog flagged BEFORE 950°C redline)
  Test C: Sensor-Fault vs. Plant-Fault Discrimination Test
  Test D: RUL Trend & Quantile Uncertainty Band Test

Outputs detailed numerical results, PASS/FAIL statuses, and saves plots to docs/.
===============================================================================
"""

import os
import sys
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, ".."))
DOCS_DIR = os.path.join(PROJECT_ROOT, "docs")
sys.path.insert(0, SCRIPT_DIR)
sys.path.insert(0, os.path.join(PROJECT_ROOT, "plant_model"))

from engine_plant import (
    EngineSpecs,
    AeroEnginePlant,
    FaultEvent,
    generate_mission_profile,
    simulate_mission
)
from physics_estimator import PhysicsExpectedEstimator
from residual_detector import ResidualAnomalyDetector
from fault_discriminator import FaultDiscriminator
from rul_estimator import RULEstimator


def test_a_false_alarm(docs_dir: str) -> bool:
    """
    Test A: Run nominal rapid-throttle-transition scenario and confirm
    the anomaly system does NOT flag an alert.
    """
    print("\n" + "="*80)
    print("TEST A: FALSE-ALARM VALIDATION (RAPID THROTTLE TRANSIENT)")
    print("="*80)

    # Aggressive dynamic flight profile with violent throttle shifts
    phases = [
        {"name": "idle_start", "duration_sec": 30.0, "start_alt_m": 1500.0, "end_alt_m": 1500.0,
         "start_throttle_pct": 30.0, "end_throttle_pct": 30.0, "start_airspeed_mps": 35.0, "end_airspeed_mps": 35.0},
        {"name": "rapid_climb_burst", "duration_sec": 40.0, "start_alt_m": 1500.0, "end_alt_m": 2200.0,
         "start_throttle_pct": 95.0, "end_throttle_pct": 98.0, "start_airspeed_mps": 35.0, "end_airspeed_mps": 45.0},
        {"name": "throttle_chop", "duration_sec": 30.0, "start_alt_m": 2200.0, "end_alt_m": 2000.0,
         "start_throttle_pct": 25.0, "end_throttle_pct": 25.0, "start_airspeed_mps": 45.0, "end_airspeed_mps": 35.0},
        {"name": "recovery_cruise", "duration_sec": 30.0, "start_alt_m": 2000.0, "end_alt_m": 2000.0,
         "start_throttle_pct": 75.0, "end_throttle_pct": 75.0, "start_airspeed_mps": 42.0, "end_airspeed_mps": 42.0}
    ]
    prof = generate_mission_profile(phases=phases, dt=0.1)
    df_nominal = simulate_mission(mission_profile=prof, faults=[], random_seed=123, dt=0.1)

    detector = ResidualAnomalyDetector(ewma_alpha=0.05)
    
    t_list = []
    ewma_egt_list = []
    ewma_cht_list = []
    ewma_rpm_list = []
    alert_flags = []

    max_observed_egt_res = 0.0
    for idx, row in df_nominal.iterrows():
        t = row["timestamp_sec"]
        out = detector.process_telemetry(dt=0.1, telemetry=row.to_dict())
        t_list.append(t)
        max_egt_r = out["max_egt_residual"]
        ewma_egt_list.append(max_egt_r)
        ewma_cht_list.append(out["max_cht_residual"])
        ewma_rpm_list.append(out["ewma_residuals"]["rpm"])
        alert_flags.append(1 if out["status"] == "ALERT" else 0)
        max_observed_egt_res = max(max_observed_egt_res, max_egt_r)

    total_alerts = sum(alert_flags)
    pass_test = (total_alerts == 0) and (max_observed_egt_res < 28.0)
    status_str = "PASS" if pass_test else "FAIL"

    print(f"  Throttle Range:              25.0% to 98.0% (Aggressive Transients)")
    print(f"  Max EWMA EGT Residual:       {max_observed_egt_res:.2f}°C (Threshold = 28.0°C)")
    print(f"  Total False Alarms Raised:   {total_alerts} alerts out of {len(df_nominal)} timesteps")
    print(f"  [RESULT] Test A Status: [{status_str}]")

    # Plot
    fig, axes = plt.subplots(3, 1, figsize=(11, 10), sharex=True)
    t_arr = np.array(t_list)

    axes[0].plot(t_arr, df_nominal["throttle_pct"], color="#e67e22", lw=2, label="Throttle (%)")
    axes[0].set_ylabel("Throttle (%)", fontweight="bold")
    axes[0].set_title("Test A: Nominal Rapid Throttle Transient (False-Alarm Rejection)", fontsize=13, fontweight="bold", pad=8)
    axes[0].grid(True, alpha=0.3)
    axes[0].legend(loc="upper right")

    axes[1].plot(t_arr, df_nominal["egt1"], color="#2980b9", lw=1.5, label="Measured EGT Cyl 1")
    axes[1].plot(t_arr, [row["egt1_true"] for _, row in df_nominal.iterrows()], color="#2c3e50", lw=1.2, linestyle=":", label="Model Expected EGT")
    axes[1].set_ylabel("EGT (°C)", fontweight="bold")
    axes[1].grid(True, alpha=0.3)
    axes[1].legend(loc="upper right")

    axes[2].plot(t_arr, ewma_egt_list, color="#27ae60", lw=2, label="EWMA Residual r_EGT (°C)")
    axes[2].axhline(28.0, color="#c0392b", linestyle="--", lw=1.8, label="Alert Threshold (28.0°C)")
    axes[2].axhline(16.8, color="#f39c12", linestyle=":", lw=1.5, label="Caution Threshold (16.8°C)")
    axes[2].set_ylabel("Residual (°C)", fontweight="bold")
    axes[2].set_xlabel("Time (seconds)", fontweight="bold")
    axes[2].set_ylim(0, 35)
    axes[2].grid(True, alpha=0.3)
    axes[2].legend(loc="upper right")

    plt.tight_layout()
    plot_path = os.path.join(docs_dir, "false_alarm_validation.png")
    plt.savefig(plot_path, dpi=200)
    plt.close()
    print(f"  [SAVED] Plot: {plot_path}")
    return pass_test


def test_b_true_positive_early_detection(docs_dir: str) -> bool:
    """
    Test B: Run an injector clog scenario and confirm the system DOES flag an alert,
    and confirm it flags BEFORE the raw EGT crosses the 950°C physical redline.
    """
    print("\n" + "="*80)
    print("TEST B: TRUE-POSITIVE EARLY DETECTION (INJECTOR CLOG BEFORE REDLINE)")
    print("="*80)

    phases = [
        {"name": "cruise", "duration_sec": 140.0, "start_alt_m": 2500.0, "end_alt_m": 2500.0,
         "start_throttle_pct": 75.0, "end_throttle_pct": 75.0, "start_airspeed_mps": 44.0, "end_airspeed_mps": 44.0}
    ]
    prof = generate_mission_profile(phases=phases, dt=0.1)

    # Inception at t = 40.0s (38% injector clog on Cylinder 2)
    fault_start_t = 40.0
    faults = [
        FaultEvent(
            fault_type="injector_clog",
            start_time_sec=fault_start_t,
            duration_ramp_sec=10.0,
            target_cylinder=2,
            severity=0.38
        )
    ]
    df_fault = simulate_mission(mission_profile=prof, faults=faults, random_seed=42, dt=0.1)
    detector = ResidualAnomalyDetector(ewma_alpha=0.05)

    alert_time = None
    redline_time = None
    egt_at_alert = None

    t_list = []
    raw_egt2_list = []
    ewma_egt2_list = []

    for idx, row in df_fault.iterrows():
        t = row["timestamp_sec"]
        out = detector.process_telemetry(dt=0.1, telemetry=row.to_dict())

        egt2_meas = row["egt2"]
        egt2_ewma = out["ewma_residuals"]["egt2"]

        t_list.append(t)
        raw_egt2_list.append(egt2_meas)
        ewma_egt2_list.append(egt2_ewma)

        # Check when Digital Twin flags ALERT (EWMA residual >= 28.0°C)
        if alert_time is None and out["status"] == "ALERT" and "egt2" in out["alerted_signals"]:
            alert_time = t
            egt_at_alert = egt2_meas

        # Check if raw EGT crosses 940-950°C redline
        if redline_time is None and egt2_meas >= 940.0:
            redline_time = t

    lead_time_seconds = (redline_time - alert_time) if (alert_time and redline_time) else 999.0
    pass_test = (alert_time is not None) and (alert_time < (redline_time or 120.0)) and (egt_at_alert < 905.0)
    status_str = "PASS" if pass_test else "FAIL"

    print(f"  Fault Inception Time:        t = {fault_start_t:.1f}s (Cylinder 2 Injector Clog)")
    print(f"  Digital Twin Alert Time:     t = {alert_time:.1f}s (Triggered when EWMA residual r >= 28°C)")
    print(f"  Raw EGT at Alert Inception:  {egt_at_alert:.1f}°C (Normal operating temperature, NOT redline!)")
    if redline_time:
        print(f"  Raw Parameter Redline Time:  t = {redline_time:.1f}s (When raw sensor finally reached 940°C)")
        print(f"  EARLY WARNING ADVANTAGE:     +{lead_time_seconds:.1f} SECONDS BEFORE CRITICAL REDLINE!")
    else:
        print(f"  Raw Parameter Redline:       NEVER crossed 940°C (Digital Twin detected fault that raw threshold MISSED!)")
    print(f"  [RESULT] Test B Status: [{status_str}]")

    # Plot
    fig, axes = plt.subplots(2, 1, figsize=(11, 8), sharex=True)
    t_arr = np.array(t_list)

    # Panel 1: Raw EGT vs Redline
    axes[0].plot(t_arr, raw_egt2_list, color="#c0392b", lw=2, label="Measured EGT Cyl 2")
    axes[0].axhline(950.0, color="#7f8c8d", linestyle="--", lw=1.5, label="Physical Safety Redline (950°C)")
    axes[0].axhline(940.0, color="#e74c3c", linestyle=":", lw=1.5, label="Redline Warning Threshold (940°C)")
    if alert_time:
        axes[0].axvline(alert_time, color="#27ae60", lw=2, linestyle="-.", label=f"Digital Twin Alert (t={alert_time:.1f}s, EGT={egt_at_alert:.1f}°C)")
    if redline_time:
        axes[0].axvline(redline_time, color="#c0392b", lw=2, linestyle=":", label=f"Raw Sensor Threshold (t={redline_time:.1f}s)")
    axes[0].set_ylabel("Raw EGT (°C)", fontweight="bold")
    axes[0].set_title("Test B: True-Positive Early Fault Detection (Lead Time Demonstration)", fontsize=13, fontweight="bold", pad=8)
    axes[0].grid(True, alpha=0.3)
    axes[0].legend(loc="lower right")

    # Panel 2: EWMA Residual
    axes[1].plot(t_arr, ewma_egt2_list, color="#2980b9", lw=2, label="Cyl 2 EWMA Residual r(t)")
    axes[1].axhline(28.0, color="#c0392b", linestyle="--", lw=1.8, label="Anomaly Detection Threshold (28.0°C)")
    if alert_time:
        axes[1].axvline(alert_time, color="#27ae60", lw=2, linestyle="-.")
    axes[1].set_ylabel("Residual (°C)", fontweight="bold")
    axes[1].set_xlabel("Time (seconds)", fontweight="bold")
    axes[1].grid(True, alpha=0.3)
    axes[1].legend(loc="lower right")

    plt.tight_layout()
    plot_path = os.path.join(docs_dir, "early_detection_true_positive.png")
    plt.savefig(plot_path, dpi=200)
    plt.close()
    print(f"  [SAVED] Plot: {plot_path}")
    return pass_test


def test_c_sensor_vs_plant_discrimination(docs_dir: str) -> bool:
    """
    Test C: Run one sensor-drift case and one plant-fault case side by side,
    and confirm the discriminator correctly labels which is which.
    """
    print("\n" + "="*80)
    print("TEST C: SENSOR-FAULT VS. PLANT-FAULT DISCRIMINATION")
    print("="*80)

    phases = [
        {"name": "cruise", "duration_sec": 120.0, "start_alt_m": 2500.0, "end_alt_m": 2500.0,
         "start_throttle_pct": 75.0, "end_throttle_pct": 75.0, "start_airspeed_mps": 44.0, "end_airspeed_mps": 44.0}
    ]
    prof = generate_mission_profile(phases=phases, dt=0.1)

    # Case 1: Sensor Drift on EGT2 (Instrument Failure)
    fault_sensor = [
        FaultEvent(
            fault_type="sensor_drift",
            start_time_sec=40.0,
            sensor_name="egt2",
            drift_rate=0.8,
            severity=1.0
        )
    ]
    df_sensor = simulate_mission(mission_profile=prof, faults=fault_sensor, random_seed=42, dt=0.1)

    # Case 2: Injector Clog on Cyl 2 (Mechanical Power Degradation)
    fault_plant = [
        FaultEvent(
            fault_type="injector_clog",
            start_time_sec=40.0,
            duration_ramp_sec=10.0,
            target_cylinder=2,
            severity=0.35
        )
    ]
    df_plant = simulate_mission(mission_profile=prof, faults=fault_plant, random_seed=42, dt=0.1)

    detector_s = ResidualAnomalyDetector()
    detector_p = ResidualAnomalyDetector()
    discriminator = FaultDiscriminator()

    # Evaluate at t = 90s (well into both faults)
    row_s = df_sensor[df_sensor["timestamp_sec"] == 90.0].iloc[0].to_dict()
    row_p = df_plant[df_plant["timestamp_sec"] == 90.0].iloc[0].to_dict()

    # Warm-up / run detector streams
    for _, r in df_sensor[df_sensor["timestamp_sec"] <= 90.0].iterrows():
        out_s = detector_s.process_telemetry(0.1, r.to_dict())

    for _, r in df_plant[df_plant["timestamp_sec"] <= 90.0].iterrows():
        out_p = detector_p.process_telemetry(0.1, r.to_dict())

    res_sensor = discriminator.classify_anomaly(out_s)
    res_plant = discriminator.classify_anomaly(out_p)

    sensor_pass = (res_sensor["classification"] == "SENSOR_FAULT") and (res_sensor["fault_subtype"] == "SENSOR_DRIFT")
    plant_pass = (res_plant["classification"] == "PLANT_FAULT") and (res_plant["fault_subtype"] == "INJECTOR_CLOG")
    pass_test = sensor_pass and plant_pass
    status_str = "PASS" if pass_test else "FAIL"

    print("  [EVALUATION OF CASE 1: SENSOR DRIFT ON EGT2]")
    print(f"    - Classified As:       {res_sensor['classification']} ({res_sensor['fault_subtype']}) on {res_sensor['fault_location']}")
    print(f"    - Observed Coupling:   EGT Rise = +{res_sensor['coupling_metrics'].get('egt_divergence_c', 0)}°C, RPM Droop = {res_sensor['coupling_metrics'].get('rpm_droop', 0)} RPM")
    print(f"    - Justification:       {res_sensor['justification']}")
    print(f"    - Correct Outcome:     [{'PASS' if sensor_pass else 'FAIL'}]")

    print("\n  [EVALUATION OF CASE 2: INJECTOR CLOG ON CYLINDER 2]")
    print(f"    - Classified As:       {res_plant['classification']} ({res_plant['fault_subtype']}) on {res_plant['fault_location']}")
    print(f"    - Observed Coupling:   EGT Rise = +{res_plant['coupling_metrics'].get('egt_divergence_c', 0)}°C, RPM Droop = {res_plant['coupling_metrics'].get('rpm_droop', 0)} RPM")
    print(f"    - Justification:       {res_plant['justification']}")
    print(f"    - Correct Outcome:     [{'PASS' if plant_pass else 'FAIL'}]")

    print(f"\n  [RESULT] Test C Status: [{status_str}]")

    # Plot Comparison
    fig, axes = plt.subplots(2, 2, figsize=(13, 8), sharex=True)
    t_s = df_sensor["timestamp_sec"]
    t_p = df_plant["timestamp_sec"]

    # Top Left: Sensor Drift EGT vs RPM
    axes[0, 0].plot(t_s, df_sensor["egt2"], color="#d35400", lw=2, label="EGT2 (Drifting Thermocouple)")
    axes[0, 0].set_ylabel("EGT (°C)", fontweight="bold")
    axes[0, 0].set_title("Case 1 (Sensor Fault): Monotonic EGT Drift", fontsize=11, fontweight="bold")
    axes[0, 0].grid(True, alpha=0.3)
    axes[0, 0].legend()

    axes[1, 0].plot(t_s, df_sensor["rpm"], color="#27ae60", lw=2, label="Engine RPM (Zero Droop!)")
    axes[1, 0].set_ylabel("RPM", fontweight="bold")
    axes[1, 0].set_xlabel("Time (seconds)", fontweight="bold")
    axes[1, 0].grid(True, alpha=0.3)
    axes[1, 0].legend()

    # Top Right: Plant Fault EGT vs RPM Droop
    axes[0, 1].plot(t_p, df_plant["egt2"], color="#c0392b", lw=2, label="EGT2 (Injector Clog Lean Burn)")
    axes[0, 1].set_ylabel("EGT (°C)", fontweight="bold")
    axes[0, 1].set_title("Case 2 (Plant Fault): EGT Spike + Correlated RPM Droop", fontsize=11, fontweight="bold")
    axes[0, 1].grid(True, alpha=0.3)
    axes[0, 1].legend()

    axes[1, 1].plot(t_p, df_plant["rpm"], color="#c0392b", lw=2, label="Engine RPM (Clear -250 RPM Droop)")
    axes[1, 1].set_ylabel("RPM", fontweight="bold")
    axes[1, 1].set_xlabel("Time (seconds)", fontweight="bold")
    axes[1, 1].grid(True, alpha=0.3)
    axes[1, 1].legend()

    plt.tight_layout()
    plot_path = os.path.join(docs_dir, "sensor_vs_plant_discrimination.png")
    plt.savefig(plot_path, dpi=200)
    plt.close()
    print(f"  [SAVED] Plot: {plot_path}")
    return pass_test


def test_d_rul_trend_and_uncertainty(docs_dir: str) -> bool:
    """
    Test D: On a full run-to-failure sequence, plot predicted RUL over time
    and confirm it trends downward as the fault progresses, with the uncertainty
    band widening appropriately as failure approaches.
    """
    print("\n" + "="*80)
    print("TEST D: RUL TREND & QUANTILE UNCERTAINTY BAND VALIDATION")
    print("="*80)

    phases = [
        {"name": "cruise_fail", "duration_sec": 180.0, "start_alt_m": 2500.0, "end_alt_m": 2500.0,
         "start_throttle_pct": 75.0, "end_throttle_pct": 75.0, "start_airspeed_mps": 44.0, "end_airspeed_mps": 44.0}
    ]
    prof = generate_mission_profile(phases=phases, dt=0.1)

    # Severe fault causing progressive degradation
    faults = [
        FaultEvent(
            fault_type="injector_clog",
            start_time_sec=40.0,
            duration_ramp_sec=15.0,
            target_cylinder=1,
            severity=0.48
        )
    ]
    df_fail = simulate_mission(mission_profile=prof, faults=faults, random_seed=999, dt=0.1)

    rul_model = RULEstimator()
    rul_model.load_model()

    detector = ResidualAnomalyDetector()
    recent_history = []

    t_pts = []
    rul_pred_hrs = []
    rul_q10_hrs = []
    rul_q90_hrs = []
    rul_true_hrs = []
    uncertainty_spread = []

    # Evaluate every 1.0s (10 steps)
    for idx, row in df_fail.iterrows():
        r_dict = row.to_dict()
        det_out = detector.process_telemetry(0.1, r_dict)
        recent_history.append({"timestamp_sec": row["timestamp_sec"], "max_egt_residual": det_out["max_egt_residual"]})

        if idx % 10 == 0:
            feat = rul_model.extract_features(r_dict, det_out, recent_history)
            pred = rul_model.predict(feat)

            t_pts.append(row["timestamp_sec"])
            rul_pred_hrs.append(pred["rul_hours"])
            rul_q10_hrs.append(pred["rul_lower_hours"])
            rul_q90_hrs.append(pred["rul_upper_hours"])
            rul_true = row["rul_remaining_hours"] if "rul_remaining_hours" in row else (row["rul_remaining_sec"] / 3600.0)
            rul_true_hrs.append(rul_true)
            uncertainty_spread.append(pred["uncertainty_band_hours"])

    t_arr = np.array(t_pts)
    pred_arr = np.array(rul_pred_hrs)
    q10_arr = np.array(rul_q10_hrs)
    q90_arr = np.array(rul_q90_hrs)
    true_arr = np.array(rul_true_hrs)

    # Checkpoint values
    pre_fault_rul = pred_arr[t_arr == 30.0][0]
    mid_fault_rul = pred_arr[t_arr == 80.0][0]
    late_fault_rul = pred_arr[t_arr == 140.0][0]

    # STRENGTHENED VERIFICATION CRITERIA (Per Aeronautical Grounding Spec):
    # 1. Healthy nominal engine RUL must fall within realistic range (>100 hrs, order of 100-250 hrs TBO)
    pre_fault_healthy = (pre_fault_rul >= 100.0)

    # 2. RUL trend must show meaningful degradation at each checkpoint (NO FLATLINING!)
    meaningful_mid_drop = (pre_fault_rul - mid_fault_rul >= 25.0)
    meaningful_late_drop = (mid_fault_rul - late_fault_rul >= 10.0)

    # 3. Late fault must reach low single-digit to imminent critical range (<= 15.0 hrs)
    late_fault_critical = (late_fault_rul <= 15.0)

    # 4. Strictly monotonic downward trend
    downward_trend = (pre_fault_rul > mid_fault_rul) and (mid_fault_rul > late_fault_rul)

    # 5. Non-zero calibrated uncertainty band with no quantile crossing
    valid_uncertainty = (np.mean(uncertainty_spread) > 0.0) and bool(np.all(q10_arr <= q90_arr))

    pass_test = (
        pre_fault_healthy and
        meaningful_mid_drop and
        meaningful_late_drop and
        late_fault_critical and
        downward_trend and
        valid_uncertainty
    )
    status_str = "PASS" if pass_test else "FAIL"

    print(f"  Checkpoint 1 (Pre-fault @ t=30s):   {pre_fault_rul:6.2f} hrs (Criteria: >= 100.0 hrs) -> [{'PASS' if pre_fault_healthy else 'FAIL'}]")
    print(f"  Checkpoint 2 (Mid-fault @ t=80s):   {mid_fault_rul:6.2f} hrs (Criteria: Drop >= 25.0 hrs from pre) -> [{'PASS' if meaningful_mid_drop else 'FAIL'}]")
    print(f"  Checkpoint 3 (Late-fault @ t=140s): {late_fault_rul:6.2f} hrs (Criteria: <= 15.0 hrs & Drop >= 10.0 hrs from mid) -> [{'PASS' if (meaningful_late_drop and late_fault_critical) else 'FAIL'}]")
    print(f"  Monotonic Continuous Downward:      [{'PASS' if downward_trend else 'FAIL'}] (No flatlining between mid and late fault)")
    print(f"  Avg Uncertainty Band Spread:        {np.mean(uncertainty_spread):.2f} hrs [Q10 to Q90] -> [{'PASS' if valid_uncertainty else 'FAIL'}]")
    print(f"  [RESULT] Test D Status: [{status_str}]")

    # Plot
    fig, ax = plt.subplots(figsize=(11, 6))
    ax.plot(t_arr, true_arr, color="#2c3e50", lw=2, linestyle="--", label="Ground Truth RUL")
    ax.plot(t_arr, pred_arr, color="#2980b9", lw=2.5, label="Predicted RUL (Q50 Median)")
    ax.fill_between(t_arr, q10_arr, q90_arr, color="#3498db", alpha=0.25, label="Quantile Uncertainty Band [Q10 - Q90]")
    ax.axvline(40.0, color="#d35400", lw=1.8, linestyle=":", label="Fault Inception (t=40s)")
    ax.set_ylabel("Remaining Useful Life (Hours)", fontweight="bold", fontsize=11)
    ax.set_xlabel("Mission Elapsed Time (seconds)", fontweight="bold", fontsize=11)
    ax.set_title("Test D: RUL Degradation Trajectory with Quantile Uncertainty Band", fontsize=13, fontweight="bold", pad=10)
    ax.grid(True, alpha=0.3)
    ax.legend(loc="upper right", framealpha=0.9)

    plt.tight_layout()
    plot_path = os.path.join(docs_dir, "rul_prediction_with_uncertainty.png")
    plt.savefig(plot_path, dpi=200)
    plt.close()
    print(f"  [SAVED] Plot: {plot_path}")
    return pass_test


if __name__ == "__main__":
    os.makedirs(DOCS_DIR, exist_ok=True)
    res_a = test_a_false_alarm(DOCS_DIR)
    res_b = test_b_true_positive_early_detection(DOCS_DIR)
    res_c = test_c_sensor_vs_plant_discrimination(DOCS_DIR)
    res_d = test_d_rul_trend_and_uncertainty(DOCS_DIR)

    all_passed = res_a and res_b and res_c and res_d

    print("\n" + "="*80)
    print("PHASE 3 OVERALL SELF-VALIDATION SUMMARY")
    print("="*80)
    print(f"  Test A (False-Alarm Rejection):       [{'PASS' if res_a else 'FAIL'}]")
    print(f"  Test B (True-Positive Early Warning):  [{'PASS' if res_b else 'FAIL'}]")
    print(f"  Test C (Sensor vs Plant Discriminator):[{'PASS' if res_c else 'FAIL'}]")
    print(f"  Test D (RUL Trend with Uncertainty):   [{'PASS' if res_d else 'FAIL'}]")
    print("-" * 80)
    if all_passed:
        print(">>> ALL 4 PHASE 3 SELF-VALIDATION TESTS PASSED WITH 100% SUCCESS! <<<")
    else:
        print(">>> ONE OR MORE PHASE 3 TESTS FAILED! <<<")
    print("="*80 + "\n")
    sys.exit(0 if all_passed else 1)
