#!/usr/bin/env python3
"""
===============================================================================
PHASE 2 SELF-VALIDATION: CAN BUS ROUND-TRIP PACK/DECODE ACCURACY TEST
===============================================================================
Verifies end-to-end correctness of the CAN Bus Layer:
  1. Takes realistic plant model telemetry vectors across multiple flight regimes:
       - Low Ground Idle
       - High-Power Takeoff Climb
       - Patrol Cruise
       - Faulted Injector Clog (Elevated EGT on Cylinder 2, RPM droop)
  2. Packs signals into raw 8-byte CAN frames (IDs 0x100, 0x101, 0x102, 0x103)
     using engine_telemetry.dbc.
  3. Transmits over the virtual CAN bus and receives via CAN listener.
  4. Decodes frames back to physical values and checks that absolute error for
     EVERY signal is strictly within the DBC quantization resolution limit.
  5. Outputs a detailed numerical PASS/FAIL report.
===============================================================================
"""

import os
import sys
import unittest
from typing import Dict, Any, List, Tuple

import can
import cantools
import pandas as pd

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, ".."))
sys.path.insert(0, SCRIPT_DIR)

from can_pack import load_engine_dbc, pack_telemetry_dict, get_can_bus
from can_listen import EngineCANTelemetryDecoder


def run_can_roundtrip_verification() -> bool:
    """
    Executes automated round-trip pack/decode accuracy test and prints
    detailed numerical report with PASS/FAIL for all signals.
    """
    print("\n" + "="*80)
    print("PHASE 2 SELF-VALIDATION: CAN BUS ROUND-TRIP PACK/DECODE ACCURACY CHECK")
    print("="*80)

    db = load_engine_dbc()
    # Use python-can virtual bus on dedicated channel 'roundtrip_test'
    tx_bus = can.Bus(channel="vcan_roundtrip", interface="virtual")
    rx_bus = can.Bus(channel="vcan_roundtrip", interface="virtual")
    decoder = EngineCANTelemetryDecoder(db)

    # Test cases representing distinct operational flight regimes
    test_cases = [
        {
            "name": "Takeoff / Climb (Full Power)",
            "telemetry": {
                "rpm": 5642.75,
                "throttle_pct": 98.0,
                "fuel_flow_gps": 5.412,
                "egt1": 875.4, "egt2": 878.1, "egt3": 881.6, "egt4": 873.9,
                "cht1": 212.3, "cht2": 213.7, "cht3": 216.5, "cht4": 218.1,
                "oil_press_bar": 4.652,
                "oil_temp_c": 98.4,
                "airspeed_mps": 38.6,
                "altitude_m": 1250.5
            }
        },
        {
            "name": "Cruise (Moderate Power)",
            "telemetry": {
                "rpm": 4820.50,
                "throttle_pct": 74.0,
                "fuel_flow_gps": 3.845,
                "egt1": 825.2, "egt2": 831.7, "egt3": 834.1, "egt4": 826.8,
                "cht1": 182.4, "cht2": 183.8, "cht3": 186.2, "cht4": 187.9,
                "oil_press_bar": 4.120,
                "oil_temp_c": 86.5,
                "airspeed_mps": 44.2,
                "altitude_m": 2500.0
            }
        },
        {
            "name": "Degraded / Faulted (Injector Clog on Cyl 2)",
            "telemetry": {
                "rpm": 4568.25,
                "throttle_pct": 75.0,
                "fuel_flow_gps": 3.480,
                "egt1": 824.8, "egt2": 941.6, "egt3": 835.0, "egt4": 826.1,  # Cyl 2 EGT lean spike!
                "cht1": 184.1, "cht2": 195.4, "cht3": 186.5, "cht4": 188.0,
                "oil_press_bar": 3.985,
                "oil_temp_c": 89.2,
                "airspeed_mps": 42.8,
                "altitude_m": 2500.0
            }
        },
        {
            "name": "Descent / Idle (Low Power)",
            "telemetry": {
                "rpm": 1645.00,
                "throttle_pct": 18.0,
                "fuel_flow_gps": 0.885,
                "egt1": 692.3, "egt2": 696.1, "egt3": 698.4, "egt4": 690.7,
                "cht1": 161.2, "cht2": 162.0, "cht3": 164.5, "cht4": 165.1,
                "oil_press_bar": 2.240,
                "oil_temp_c": 76.8,
                "airspeed_mps": 28.5,
                "altitude_m": 350.0
            }
        }
    ]

    # DBC Signal Quantization Resolutions
    tolerances = {
        "rpm": 0.25,           # 16-bit, scale 0.25 RPM
        "throttle_pct": 0.50,  # 8-bit, scale 0.5 %
        "fuel_flow_gps": 0.001,# 16-bit, scale 0.001 g/s
        "egt1": 0.10, "egt2": 0.10, "egt3": 0.10, "egt4": 0.10,  # 16-bit, scale 0.1 °C
        "cht1": 0.10, "cht2": 0.10, "cht3": 0.10, "cht4": 0.10,  # 16-bit, scale 0.1 °C
        "oil_press_bar": 0.001,# 16-bit, scale 0.001 bar
        "oil_temp_c": 0.10,    # 16-bit, scale 0.1 °C
        "airspeed_mps": 0.10,  # 16-bit, scale 0.1 m/s
        "altitude_m": 0.50     # 16-bit, scale 0.5 m
    }

    all_tests_passed = True
    total_signals_tested = 0
    total_signals_passed = 0

    for case in test_cases:
        print(f"\n--- Scenario: {case['name']} ---")
        orig = case["telemetry"]

        # 1. Pack telemetry into 4 CAN frames
        frames = pack_telemetry_dict(orig, db, rolling_counter=3)

        # 2. Transmit frames over virtual bus
        for f in frames:
            tx_bus.send(f)

        # 3. Receive and decode frames from bus
        for _ in range(len(frames)):
            rx_msg = rx_bus.recv(timeout=1.0)
            if rx_msg is not None:
                decoder.decode_frame(rx_msg)

        decoded = decoder.get_snapshot()

        # 4. Compare every signal against DBC quantization resolution
        print(f"{'Signal Name':20s} | {'Original':10s} | {'Decoded':10s} | {'Error':10s} | {'Max Tol':8s} | Status")
        print("-" * 75)

        for sig, tol in tolerances.items():
            val_orig = orig[sig]
            val_dec = decoded[sig]
            err = abs(val_orig - val_dec)
            passed = (err <= tol + 1e-6)
            status = "PASS" if passed else "FAIL"

            total_signals_tested += 1
            if passed:
                total_signals_passed += 1
            else:
                all_tests_passed = False

            fmt_orig = f"{val_orig:8.3f}" if tol < 0.1 else f"{val_orig:8.1f}"
            fmt_dec = f"{val_dec:8.3f}" if tol < 0.1 else f"{val_dec:8.1f}"
            fmt_err = f"{err:8.4f}" if tol < 0.1 else f"{err:8.2f}"
            print(f"{sig:20s} | {fmt_orig} | {fmt_dec} | {fmt_err} | ±{tol:<6.3f} | [{status}]")

    print("\n" + "="*80)
    print("PHASE 2 SUMMARY & ROUND-TRIP ACCURACY RESULTS")
    print("="*80)
    print(f"Total Signals Checked: {total_signals_tested}")
    print(f"Total Signals Passed:  {total_signals_passed} / {total_signals_tested}")
    accuracy_pct = (total_signals_passed / total_signals_tested) * 100.0
    print(f"Round-Trip Accuracy:   {accuracy_pct:.2f}%")

    if all_tests_passed:
        print(">>> OVERALL PHASE 2 STATUS: PASS <<<")
    else:
        print(">>> OVERALL PHASE 2 STATUS: FAIL <<<")
    print("="*80 + "\n")

    tx_bus.shutdown()
    rx_bus.shutdown()
    return all_tests_passed


if __name__ == "__main__":
    success = run_can_roundtrip_verification()
    sys.exit(0 if success else 1)
