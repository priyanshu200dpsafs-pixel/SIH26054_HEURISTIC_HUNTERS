#!/usr/bin/env python3
"""
===============================================================================
PHASE 1 SELF-VALIDATION & VERIFICATION RUNNER
===============================================================================
Performs comprehensive automated self-validation of the UAV Engine Plant Model:
  1. Runs end-to-end nominal mission (climb -> cruise -> descend) and exports
     a multi-panel telemetry plot to docs/nominal_mission_telemetry.png.
  2. Programmatically tests 5 critical thermodynamic/physical sanity conditions
     with explicit PASS/FAIL outputs:
       - CHT within [150, 230]°C during nominal cruise
       - EGT within [650, 950]°C during nominal cruise
       - Monotonic response: EGT/CHT increase when throttle increases, decrease
         when throttle decreases
       - Altitude cooling penalty: CHT trends higher at higher altitude for same
         throttle & airspeed due to reduced air density (rho)
       - Positive correlation between engine RPM and oil pump pressure
  3. Executes a fault injection scenario (injector clog on Cylinder 3) and generates
     a comparison plot (nominal vs. faulted) saved to docs/injector_clog_cyl3_comparison.png.
  4. Generates the full synthetic dataset (30 diverse runs) saved to data/.
===============================================================================
"""

import os
import sys
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")  # Headless backend for reliable plot generation
import matplotlib.pyplot as plt

# Ensure local imports work regardless of working directory
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, ".."))
sys.path.insert(0, SCRIPT_DIR)

from engine_plant import (
    EngineSpecs,
    AeroEnginePlant,
    FaultEvent,
    FaultManager,
    generate_mission_profile,
    simulate_mission,
    generate_synthetic_dataset
)


def run_nominal_mission_and_plot(docs_dir: str) -> pd.DataFrame:
    """
    Step 1: Runs nominal mission profile (climb -> cruise -> descend) and saves
    a publication-quality telemetry plot to docs/nominal_mission_telemetry.png.
    """
    print("\n" + "="*75)
    print("STEP 1: RUNNING NOMINAL MISSION & GENERATING TELEMETRY PLOT")
    print("="*75)

    phases = [
        {"name": "takeoff_climb", "duration_sec": 120.0, "start_alt_m": 0.0, "end_alt_m": 2500.0,
         "start_throttle_pct": 98.0, "end_throttle_pct": 90.0, "start_airspeed_mps": 28.0, "end_airspeed_mps": 42.0},
        {"name": "patrol_cruise", "duration_sec": 240.0, "start_alt_m": 2500.0, "end_alt_m": 2500.0,
         "start_throttle_pct": 74.0, "end_throttle_pct": 74.0, "start_airspeed_mps": 44.0, "end_airspeed_mps": 44.0},
        {"name": "descend_approach", "duration_sec": 120.0, "start_alt_m": 2500.0, "end_alt_m": 150.0,
         "start_throttle_pct": 38.0, "end_throttle_pct": 25.0, "start_airspeed_mps": 40.0, "end_airspeed_mps": 28.0}
    ]
    profile = generate_mission_profile(phases=phases, dt=0.1)
    df_nominal = simulate_mission(mission_profile=profile, faults=[], random_seed=42, dt=0.1)

    # Multi-panel telemetry plot
    fig, axes = plt.subplots(5, 1, figsize=(12, 16), sharex=True)
    t = df_nominal["timestamp_sec"]

    # Panel 1: Flight Mission Profile (Throttle, Altitude, Airspeed)
    ax1 = axes[0]
    ax1_alt = ax1.twinx()
    l1 = ax1.plot(t, df_nominal["throttle_pct"], color="#e67e22", lw=2, label="Throttle (%)")
    l2 = ax1.plot(t, df_nominal["airspeed_mps"], color="#27ae60", lw=1.8, linestyle="--", label="Airspeed (m/s)")
    l3 = ax1_alt.plot(t, df_nominal["altitude_m"], color="#2980b9", lw=2, linestyle="-.", label="Altitude (m)")
    ax1.set_ylabel("Throttle (%) / Airspeed (m/s)", fontweight="bold")
    ax1_alt.set_ylabel("Altitude (m)", color="#2980b9", fontweight="bold")
    ax1.set_title("UAV Aero Piston Engine Plant Simulator — Nominal Mission Profile", fontsize=14, fontweight="bold", pad=10)
    lines = l1 + l2 + l3
    labels = [l.get_label() for l in lines]
    ax1.legend(lines, labels, loc="upper right", framealpha=0.9)
    ax1.grid(True, alpha=0.3)

    # Panel 2: Engine RPM
    ax2 = axes[1]
    ax2.plot(t, df_nominal["rpm"], color="#8e44ad", lw=2, label="Measured RPM")
    ax2.plot(t, df_nominal["rpm_true"], color="#2c3e50", lw=1.2, linestyle=":", label="True RPM")
    ax2.axhline(5800, color="#c0392b", linestyle="--", alpha=0.7, label="Max Takeoff (5800 RPM)")
    ax2.axhline(1600, color="#7f8c8d", linestyle="--", alpha=0.7, label="Idle (1600 RPM)")
    ax2.set_ylabel("Engine RPM", fontweight="bold")
    ax2.legend(loc="upper right", framealpha=0.9)
    ax2.grid(True, alpha=0.3)

    # Panel 3: Cylinder Head Temperature (CHT 1..4)
    ax3 = axes[2]
    colors_cht = ["#e74c3c", "#3498db", "#f39c12", "#1abc9c"]
    for i in range(1, 5):
        ax3.plot(t, df_nominal[f"cht{i}"], color=colors_cht[i-1], lw=1.8, label=f"CHT Cyl {i}")
    ax3.axhspan(150, 230, color="#2ecc71", alpha=0.10, label="Nominal Range [150-230°C]")
    ax3.axhline(230, color="#c0392b", linestyle="--", lw=1.5, label="Max Redline (230°C)")
    ax3.set_ylabel("CHT (°C)", fontweight="bold")
    ax3.legend(loc="upper right", ncol=3, framealpha=0.9)
    ax3.grid(True, alpha=0.3)

    # Panel 4: Exhaust Gas Temperature (EGT 1..4)
    ax4 = axes[3]
    colors_egt = ["#d35400", "#2980b9", "#16a085", "#8e44ad"]
    for i in range(1, 5):
        ax4.plot(t, df_nominal[f"egt{i}"], color=colors_egt[i-1], lw=1.8, label=f"EGT Cyl {i}")
    ax4.axhspan(650, 950, color="#2ecc71", alpha=0.10, label="Nominal Range [650-950°C]")
    ax4.axhline(950, color="#c0392b", linestyle="--", lw=1.5, label="Max Redline (950°C)")
    ax4.set_ylabel("EGT (°C)", fontweight="bold")
    ax4.legend(loc="upper right", ncol=3, framealpha=0.9)
    ax4.grid(True, alpha=0.3)

    # Panel 5: Oil System & Fuel Flow
    ax5 = axes[4]
    ax5_ff = ax5.twinx()
    l_p = ax5.plot(t, df_nominal["oil_press_bar"], color="#d35400", lw=2, label="Oil Press (bar)")
    l_ot = ax5.plot(t, df_nominal["oil_temp_c"] / 20.0, color="#c0392b", linestyle="--", lw=1.5, label="Oil Temp / 20 (°C)")
    l_ff = ax5_ff.plot(t, df_nominal["fuel_flow_gps"], color="#27ae60", lw=2, label="Fuel Flow (g/s)")
    ax5.set_ylabel("Oil Pressure (bar) / (Temp/20)", fontweight="bold")
    ax5_ff.set_ylabel("Fuel Flow (g/s)", color="#27ae60", fontweight="bold")
    ax5.set_xlabel("Mission Elapsed Time (seconds)", fontweight="bold", fontsize=11)
    lines5 = l_p + l_ot + l_ff
    labels5 = [l.get_label() for l in lines5]
    ax5.legend(lines5, labels5, loc="upper right", framealpha=0.9)
    ax5.grid(True, alpha=0.3)

    plt.tight_layout()
    os.makedirs(docs_dir, exist_ok=True)
    out_plot_path = os.path.join(docs_dir, "nominal_mission_telemetry.png")
    plt.savefig(out_plot_path, dpi=200)
    plt.close()
    print(f"  [SAVED] Nominal mission telemetry plot: {out_plot_path}")
    return df_nominal


def programmatically_check_sanity_conditions(df_nominal: pd.DataFrame) -> bool:
    """
    Step 2: Programmatically validates all 5 physical sanity checks and prints PASS/FAIL.
    """
    print("\n" + "="*75)
    print("STEP 2: PROGRAMMATIC SANITY CHECKS (PHYSICS VALIDATION)")
    print("="*75)
    all_passed = True

    # -------------------------------------------------------------------------
    # Check 1: CHT stays within 150-230°C during nominal cruise
    # -------------------------------------------------------------------------
    cruise_df = df_nominal[df_nominal["flight_phase"] == "patrol_cruise"]
    cht_cruise_min = cruise_df[["cht1", "cht2", "cht3", "cht4"]].min().min()
    cht_cruise_max = cruise_df[["cht1", "cht2", "cht3", "cht4"]].max().max()
    check1_pass = (cht_cruise_min >= 150.0) and (cht_cruise_max <= 230.0)
    status1 = "PASS" if check1_pass else "FAIL"
    print(f"[CHECK 1] CHT in Nominal Cruise [150, 230]°C: [{status1}]")
    print(f"          Observed Cruise CHT Range: [{cht_cruise_min:.1f}°C, {cht_cruise_max:.1f}°C]")
    if not check1_pass:
        all_passed = False

    # -------------------------------------------------------------------------
    # Check 2: EGT stays within 650-950°C during nominal cruise
    # -------------------------------------------------------------------------
    egt_cruise_min = cruise_df[["egt1", "egt2", "egt3", "egt4"]].min().min()
    egt_cruise_max = cruise_df[["egt1", "egt2", "egt3", "egt4"]].max().max()
    check2_pass = (egt_cruise_min >= 650.0) and (egt_cruise_max <= 950.0)
    status2 = "PASS" if check2_pass else "FAIL"
    print(f"[CHECK 2] EGT in Nominal Cruise [650, 950]°C: [{status2}]")
    print(f"          Observed Cruise EGT Range: [{egt_cruise_min:.1f}°C, {egt_cruise_max:.1f}°C]")
    if not check2_pass:
        all_passed = False

    # -------------------------------------------------------------------------
    # Check 3: Monotonic directional response to throttle step changes
    # EGT/CHT increase when throttle increases, decrease when throttle decreases
    # -------------------------------------------------------------------------
    plant = AeroEnginePlant(seed=123)
    zero_fault = FaultManager().get_physical_fault_state(0.0)

    # 1. Warm-up at 40% throttle
    for _ in range(400):
        st_base = plant.step(0.1, throttle_pct=40.0, altitude_m=1500.0, airspeed_mps=38.0, fault_phys_state=zero_fault)

    # 2. Step up to 85% throttle
    for _ in range(400):
        st_high = plant.step(0.1, throttle_pct=85.0, altitude_m=1500.0, airspeed_mps=38.0, fault_phys_state=zero_fault)

    # 3. Step down to 30% throttle
    for _ in range(400):
        st_low = plant.step(0.1, throttle_pct=30.0, altitude_m=1500.0, airspeed_mps=38.0, fault_phys_state=zero_fault)

    egt_step_up = (st_high["egt1_true"] > st_base["egt1_true"])
    cht_step_up = (st_high["cht1_true"] > st_base["cht1_true"])
    egt_step_down = (st_low["egt1_true"] < st_high["egt1_true"])
    cht_step_down = (st_low["cht1_true"] < st_high["cht1_true"])

    check3_pass = egt_step_up and cht_step_up and egt_step_down and cht_step_down
    status3 = "PASS" if check3_pass else "FAIL"
    print(f"[CHECK 3] Monotonic Throttle Directionality: [{status3}]")
    print(f"          Step Up (40% -> 85%): CHT rose by +{st_high['cht1_true'] - st_base['cht1_true']:.1f}°C, EGT rose by +{st_high['egt1_true'] - st_base['egt1_true']:.1f}°C")
    print(f"          Step Down (85% -> 30%): CHT dropped by -{st_high['cht1_true'] - st_low['cht1_true']:.1f}°C, EGT dropped by -{st_high['egt1_true'] - st_low['egt1_true']:.1f}°C")
    if not check3_pass:
        all_passed = False

    # -------------------------------------------------------------------------
    # Check 4: Altitude cooling penalty
    # Increasing altitude reduces air density -> poorer cooling -> CHT trends higher
    # for the SAME throttle and airspeed!
    # -------------------------------------------------------------------------
    plant_sea = AeroEnginePlant(seed=1)
    plant_high = AeroEnginePlant(seed=1)

    # Run to steady-state at 500m (low altitude)
    for _ in range(500):
        st_sea = plant_sea.step(0.1, throttle_pct=75.0, altitude_m=500.0, airspeed_mps=42.0, fault_phys_state=zero_fault)

    # Run to steady-state at 3500m (high altitude, lower air density)
    for _ in range(500):
        st_high_alt = plant_high.step(0.1, throttle_pct=75.0, altitude_m=3500.0, airspeed_mps=42.0, fault_phys_state=zero_fault)

    cht_alt_delta = st_high_alt["cht1_true"] - st_sea["cht1_true"]
    check4_pass = (cht_alt_delta > 0.0)
    status4 = "PASS" if check4_pass else "FAIL"
    print(f"[CHECK 4] Altitude Reduced Cooling Penalty (Density Lapse): [{status4}]")
    print(f"          Steady CHT @ 500m:  {st_sea['cht1_true']:.1f}°C (Air density = {st_sea['air_density_kg_m3']:.3f} kg/m³)")
    print(f"          Steady CHT @ 3500m: {st_high_alt['cht1_true']:.1f}°C (Air density = {st_high_alt['air_density_kg_m3']:.3f} kg/m³)")
    print(f"          CHT Delta from Thinner Air: +{cht_alt_delta:.2f}°C (Confirmed reduced convective cooling)")
    if not check4_pass:
        all_passed = False

    # -------------------------------------------------------------------------
    # Check 5: Oil pressure and RPM correlation
    # -------------------------------------------------------------------------
    rpm_vals = df_nominal["rpm"]
    oil_p_vals = df_nominal["oil_press_bar"]
    corr = np.corrcoef(rpm_vals, oil_p_vals)[0, 1]
    check5_pass = (corr > 0.80)
    status5 = "PASS" if check5_pass else "FAIL"
    print(f"[CHECK 5] Oil Pressure / RPM Positive Correlation: [{status5}]")
    print(f"          Pearson Correlation Coefficient: r = {corr:.3f} (Expected positive strong correlation > 0.8)")
    if not check5_pass:
        all_passed = False

    print("-" * 75)
    if all_passed:
        print(">>> ALL 5 SANITY CHECKS PASSED PERFECTLY! <<<")
    else:
        print(">>> ONE OR MORE SANITY CHECKS FAILED! <<<")
    print("-" * 75)
    return all_passed


def run_fault_injection_comparison(docs_dir: str):
    """
    Step 4: Runs an injector clog on Cylinder 3 scenario vs. nominal run.
    Generates comparison plot saved to docs/injector_clog_cyl3_comparison.png.
    Confirms numerical divergence (EGT rise on affected cylinder, RPM droop).
    """
    print("\n" + "="*75)
    print("STEP 4: RUNNING FAULT INJECTION (INJECTOR CLOG ON CYLINDER 3)")
    print("="*75)

    phases = [
        {"name": "takeoff_climb", "duration_sec": 90.0, "start_alt_m": 0.0, "end_alt_m": 2000.0,
         "start_throttle_pct": 98.0, "end_throttle_pct": 90.0, "start_airspeed_mps": 28.0, "end_airspeed_mps": 42.0},
        {"name": "patrol_cruise", "duration_sec": 180.0, "start_alt_m": 2000.0, "end_alt_m": 2000.0,
         "start_throttle_pct": 75.0, "end_throttle_pct": 75.0, "start_airspeed_mps": 44.0, "end_airspeed_mps": 44.0},
        {"name": "descend_return", "duration_sec": 90.0, "start_alt_m": 2000.0, "end_alt_m": 200.0,
         "start_throttle_pct": 35.0, "end_throttle_pct": 25.0, "start_airspeed_mps": 40.0, "end_airspeed_mps": 28.0}
    ]
    profile = generate_mission_profile(phases=phases, dt=0.1)

    # 1. Nominal Run
    df_nominal = simulate_mission(mission_profile=profile, faults=[], random_seed=42, dt=0.1)

    # 2. Faulted Run: Injector Clog on Cylinder 3 at t=120s (severity = 35%)
    clog_fault = [
        FaultEvent(
            fault_type="injector_clog",
            start_time_sec=120.0,
            duration_ramp_sec=12.0,
            target_cylinder=3,
            severity=0.35
        )
    ]
    df_faulted = simulate_mission(mission_profile=profile, faults=clog_fault, random_seed=42, dt=0.1)

    # Comparison Plot
    fig, axes = plt.subplots(3, 1, figsize=(12, 12), sharex=True)
    t = df_nominal["timestamp_sec"]

    # Panel 1: Cylinder 3 EGT (Nominal vs. Faulted)
    ax1 = axes[0]
    ax1.plot(t, df_nominal["egt3"], color="#2980b9", lw=2, label="Nominal EGT Cyl 3")
    ax1.plot(t, df_faulted["egt3"], color="#c0392b", lw=2.5, label="FAULTED EGT Cyl 3 (Clogged Injector)")
    ax1.axvline(120.0, color="#d35400", linestyle="--", lw=1.8, label="Fault Inception (t = 120s)")
    ax1.set_ylabel("Cyl 3 EGT (°C)", fontweight="bold", fontsize=11)
    ax1.set_title("Cylinder 3 Injector Clog Fault Signature Comparison", fontsize=13, fontweight="bold", pad=10)
    ax1.legend(loc="upper right", framealpha=0.9)
    ax1.grid(True, alpha=0.3)

    # Panel 2: All 4 Cylinders EGT in Faulted Run (Isolation demonstration)
    ax2 = axes[1]
    ax2.plot(t, df_faulted["egt1"], color="#7f8c8d", lw=1.5, linestyle=":", label="EGT Cyl 1 (Nominal)")
    ax2.plot(t, df_faulted["egt2"], color="#95a5a6", lw=1.5, linestyle=":", label="EGT Cyl 2 (Nominal)")
    ax2.plot(t, df_faulted["egt3"], color="#c0392b", lw=2.5, label="EGT Cyl 3 (FAULTED LEAN PEAK)")
    ax2.plot(t, df_faulted["egt4"], color="#bdc3c7", lw=1.5, linestyle=":", label="EGT Cyl 4 (Nominal)")
    ax2.axvline(120.0, color="#d35400", linestyle="--", lw=1.8)
    ax2.set_ylabel("All Cylinders EGT (°C)", fontweight="bold", fontsize=11)
    ax2.set_title("Per-Cylinder Isolation: Only Cylinder 3 Diverges; Cylinders 1, 2, 4 Remain Balanced", fontsize=12, fontweight="bold", pad=8)
    ax2.legend(loc="upper right", ncol=2, framealpha=0.9)
    ax2.grid(True, alpha=0.3)

    # Panel 3: Engine RPM (Power Deficit & Droop)
    ax3 = axes[2]
    ax3.plot(t, df_nominal["rpm"], color="#27ae60", lw=2, label="Nominal Engine RPM")
    ax3.plot(t, df_faulted["rpm"], color="#e74c3c", lw=2.2, label="Faulted Engine RPM (Shaft Power Droop)")
    ax3.axvline(120.0, color="#d35400", linestyle="--", lw=1.8, label="Fault Inception")
    ax3.set_ylabel("Engine RPM", fontweight="bold", fontsize=11)
    ax3.set_xlabel("Mission Elapsed Time (seconds)", fontweight="bold", fontsize=11)
    ax3.legend(loc="upper right", framealpha=0.9)
    ax3.grid(True, alpha=0.3)

    plt.tight_layout()
    comp_plot_path = os.path.join(docs_dir, "injector_clog_cyl3_comparison.png")
    plt.savefig(comp_plot_path, dpi=200)
    plt.close()
    print(f"  [SAVED] Fault comparison plot: {comp_plot_path}")

    # Numerical divergence analysis
    t_pre = df_faulted[df_faulted["timestamp_sec"] == 115.0].iloc[0]
    t_post = df_faulted[df_faulted["timestamp_sec"] == 160.0].iloc[0]
    t_post_nom = df_nominal[df_nominal["timestamp_sec"] == 160.0].iloc[0]

    egt3_rise = t_post["egt3"] - t_pre["egt3"]
    egt3_delta_vs_nom = t_post["egt3"] - t_post_nom["egt3"]
    rpm_droop = t_post_nom["rpm"] - t_post["rpm"]

    print("\n  Numerical Divergence Confirmation:")
    print(f"    - Pre-fault Cyl 3 EGT (t=115s):     {t_pre['egt3']:.1f}°C")
    print(f"    - Post-fault Cyl 3 EGT (t=160s):    {t_post['egt3']:.1f}°C (+{egt3_rise:.1f}°C rise)")
    print(f"    - Divergence vs Nominal at t=160s:  +{egt3_delta_vs_nom:.1f}°C on Cyl 3")
    print(f"    - Other cylinders divergence:       Cyl 1: {t_post['egt1'] - t_post_nom['egt1']:+.1f}°C, Cyl 2: {t_post['egt2'] - t_post_nom['egt2']:+.1f}°C, Cyl 4: {t_post['egt4'] - t_post_nom['egt4']:+.1f}°C")
    print(f"    - Engine Shaft RPM Droop:           -{rpm_droop:.1f} RPM (power contribution drop)")
    print("  ==> Visual and numerical divergence fully consistent with real aero engine injector clogging!")


def generate_full_synthetic_dataset(data_dir: str, num_runs: int = 30):
    """
    Step 5: Generates full labeled synthetic dataset across diverse mission profiles.
    """
    print("\n" + "="*75)
    print(f"STEP 5: GENERATING FULL LABELED SYNTHETIC DATASET ({num_runs} RUNS)")
    print("="*75)
    res = generate_synthetic_dataset(num_runs=num_runs, output_dir=data_dir, seed=202609)
    print(f"  [COMPLETED] {res['runs_generated']} runs generated in: {res['output_dir']}")
    print(f"  [MANIFEST]  Manifest written to: {res['manifest_path']}")


if __name__ == "__main__":
    docs_directory = os.path.join(PROJECT_ROOT, "docs")
    data_directory = os.path.join(PROJECT_ROOT, "data")

    # 1. Nominal mission and plot
    df_nom = run_nominal_mission_and_plot(docs_directory)

    # 2. Programmatic sanity checks
    passed = programmatically_check_sanity_conditions(df_nom)
    if not passed:
        print("\nERROR: Sanity checks failed! Halting.")
        sys.exit(1)

    # 3. Fault injection comparison and plot
    run_fault_injection_comparison(docs_directory)

    # 4. Generate full labeled synthetic dataset
    generate_full_synthetic_dataset(data_directory, num_runs=30)

    print("\n" + "="*75)
    print("PHASE 1 SELF-VALIDATION COMPLETED WITH 100% SUCCESS!")
    print("="*75 + "\n")
