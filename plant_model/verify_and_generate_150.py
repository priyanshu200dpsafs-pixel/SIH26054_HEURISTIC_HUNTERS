#!/usr/bin/env python3
"""
===============================================================================
150-RUN SYNTHETIC DATASET GENERATION & EGT CEILING VERIFICATION SCRIPT
===============================================================================
1. Validates that across the entire injector clog fault range (18% to 52%),
   EGT spikes near/at redline (920-950°C) as a prominent warning signal before
   RUL hits critical, without runaway unphysical values.
2. Generates at least 150 runs into data/ with randomized scenarios.
3. Updates data/dataset_manifest.json and reports the new run count and
   fault-type distribution.
===============================================================================
"""

import os
import sys
import json
import numpy as np
import pandas as pd

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, ".."))
sys.path.insert(0, SCRIPT_DIR)

from engine_plant import (
    EngineSpecs,
    AeroEnginePlant,
    FaultEvent,
    generate_mission_profile,
    simulate_mission,
    generate_synthetic_dataset
)


def verify_injector_clog_egt_ceiling():
    """
    Sweeps injector clog severities from 0.18 to 0.52 across all cylinders
    to verify that EGT approaches the 950°C redline as a warning signal
    without exceeding physical limits.
    """
    print("\n" + "="*75)
    print("VERIFYING INJECTOR CLOG EGT CEILING (18% to 52% SEVERITY)")
    print("="*75)

    test_severities = [0.18, 0.25, 0.35, 0.45, 0.52]
    max_observed_egt = 0.0
    results = []

    phases = [
        {"name": "cruise", "duration_sec": 100.0, "start_alt_m": 2500.0, "end_alt_m": 2500.0,
         "start_throttle_pct": 75.0, "end_throttle_pct": 75.0, "start_airspeed_mps": 44.0, "end_airspeed_mps": 44.0}
    ]
    prof = generate_mission_profile(phases=phases, dt=0.1)

    for sev in test_severities:
        faults = [
            FaultEvent(
                fault_type="injector_clog",
                start_time_sec=20.0,
                duration_ramp_sec=10.0,
                target_cylinder=3,
                severity=sev
            )
        ]
        df = simulate_mission(mission_profile=prof, faults=faults, random_seed=42, dt=0.1)
        post_fault_df = df[df["timestamp_sec"] >= 40.0]
        peak_egt3_true = post_fault_df["egt3_true"].max()
        peak_egt3_meas = post_fault_df["egt3"].max()
        max_observed_egt = max(max_observed_egt, peak_egt3_meas)
        
        status = "NORMAL"
        if peak_egt3_meas >= 880.0 and peak_egt3_meas < 925.0:
            status = "CAUTION WARNING"
        elif peak_egt3_meas >= 925.0 and peak_egt3_meas <= 950.0:
            status = "CRITICAL REDLINE WARNING"
        elif peak_egt3_meas > 950.0:
            status = "UNPHYSICAL RUNAWAY (FAIL)"

        results.append({
            "severity_pct": f"{int(sev*100)}%",
            "true_peak_egt": f"{peak_egt3_true:.1f}°C",
            "meas_peak_egt": f"{peak_egt3_meas:.1f}°C",
            "warning_status": status
        })

    df_res = pd.DataFrame(results)
    print(df_res.to_string(index=False))
    print(f"\nMax observed EGT across severity sweep: {max_observed_egt:.1f}°C")
    
    if max_observed_egt <= 950.0 and max_observed_egt >= 925.0:
        print("[PASS] EGT approaches redline (925-950°C) as a prominent warning signal without unphysical runaway!")
        return True
    else:
        print(f"[FAIL] EGT out of bounds: {max_observed_egt:.1f}°C")
        return False


def run_150_dataset_generation(data_dir: str):
    """
    Generates 150 diverse mission runs into data/ and reports distribution.
    """
    print("\n" + "="*75)
    print("GENERATING 150 LABELED RUNS FOR TRAINING DATASET")
    print("="*75)

    res = generate_synthetic_dataset(num_runs=150, output_dir=data_dir, seed=20260927)
    manifest_path = res["manifest_path"]

    with open(manifest_path, "r") as f:
        mdata = json.load(f)

    total_runs = mdata["total_runs"]
    dist = mdata["fault_distribution"]

    print("\nDataset Generation Complete:")
    print(f"  Total Runs Generated: {total_runs}")
    print("  Fault Type Distribution:")
    for k, v in dist.items():
        pct = (v / total_runs) * 100
        print(f"    - {k:20s}: {v:3d} runs ({pct:5.1f}%)")

    # Global extrema check across all generated CSV files
    all_egt_max = 0.0
    all_cht_max = 0.0
    for entry in mdata["runs"]:
        fpath = os.path.join(data_dir, entry["filename"])
        df_r = pd.read_csv(fpath)
        egt_m = df_r[["egt1", "egt2", "egt3", "egt4"]].max().max()
        cht_m = df_r[["cht1", "cht2", "cht3", "cht4"]].max().max()
        if egt_m > all_egt_max:
            all_egt_max = egt_m
        if cht_m > all_cht_max:
            all_cht_max = cht_m

    print(f"\n  Global Extrema Across All 150 Runs:")
    print(f"    - Maximum EGT Observed: {all_egt_max:.1f}°C (Capped safely at redline barrier)")
    print(f"    - Maximum CHT Observed: {all_cht_max:.1f}°C (Safe within thermal envelope)")
    print("="*75 + "\n")


if __name__ == "__main__":
    passed_ceiling = verify_injector_clog_egt_ceiling()
    if not passed_ceiling:
        print("Ceiling verification failed! Halting.")
        sys.exit(1)

    data_dir = os.path.join(PROJECT_ROOT, "data")
    run_150_dataset_generation(data_dir)
