#!/usr/bin/env python3
"""
Unit and Physics Validation Tests for UAV Engine Plant Simulator (Phase 1).
Run with: python3 plant_model/test_plant.py
"""

import os
import unittest
import numpy as np
import pandas as pd
from engine_plant import (
    EngineSpecs,
    AeroEnginePlant,
    FaultEvent,
    FaultManager,
    isa_atmosphere,
    generate_mission_profile,
    simulate_mission,
    generate_synthetic_dataset
)


class TestAeroEnginePlant(unittest.TestCase):
    
    def test_isa_atmosphere(self):
        """Test ISA standard atmosphere model calculations."""
        # Sea level
        t0, p0, rho0, sigma0 = isa_atmosphere(0.0)
        self.assertAlmostEqual(t0, 288.15, places=2)
        self.assertAlmostEqual(p0, 101325.0, delta=10.0)
        self.assertAlmostEqual(rho0, 1.225, delta=0.01)
        self.assertAlmostEqual(sigma0, 1.0, places=3)

        # 3000m (typical MALE UAV cruise)
        t3k, p3k, rho3k, sigma3k = isa_atmosphere(3000.0)
        self.assertLess(t3k, t0, "Temperature must decrease with altitude")
        self.assertLess(p3k, p0, "Pressure must decrease with altitude")
        self.assertLess(rho3k, rho0, "Air density must decrease with altitude")
        self.assertLess(sigma3k, 1.0)
        self.assertGreater(sigma3k, 0.70)

    def test_nominal_mission_ranges(self):
        """Verify operating ranges strictly adhere to specifications."""
        prof = generate_mission_profile()
        df = simulate_mission(mission_profile=prof, faults=[], random_seed=42)

        # CHT Range [150, 230]°C
        cht_min = df[["cht1", "cht2", "cht3", "cht4"]].min().min()
        cht_max = df[["cht1", "cht2", "cht3", "cht4"]].max().max()
        self.assertGreaterEqual(cht_min, 150.0, f"CHT min {cht_min} is below 150°C")
        self.assertLessEqual(cht_max, 230.0, f"CHT max {cht_max} is above 230°C")

        # EGT Range [650, 950]°C
        egt_min = df[["egt1", "egt2", "egt3", "egt4"]].min().min()
        egt_max = df[["egt1", "egt2", "egt3", "egt4"]].max().max()
        self.assertGreaterEqual(egt_min, 650.0, f"EGT min {egt_min} is below 650°C")
        self.assertLessEqual(egt_max, 950.0, f"EGT max {egt_max} is above 950°C")

        # Oil Pressure Range [1.8, 5.0] bar
        p_min = df["oil_press_bar"].min()
        p_max = df["oil_press_bar"].max()
        self.assertGreaterEqual(p_min, 1.8, f"Oil pressure min {p_min} bar")
        self.assertLessEqual(p_max, 5.0, f"Oil pressure max {p_max} bar")

        # Oil Temperature Range [70, 115]°C
        ot_min = df["oil_temp_c"].min()
        ot_max = df["oil_temp_c"].max()
        self.assertGreaterEqual(ot_min, 70.0, f"Oil temp min {ot_min}°C")
        self.assertLessEqual(ot_max, 115.0, f"Oil temp max {ot_max}°C")

    def test_directional_physics_throttle(self):
        """Higher throttle must yield higher RPM, EGT, CHT, and fuel flow."""
        plant = AeroEnginePlant(seed=42)
        zero_fault = FaultManager().get_physical_fault_state(0.0)

        # Low throttle steady state
        for _ in range(400):
            st_low = plant.step(0.1, throttle_pct=25.0, altitude_m=1000.0, airspeed_mps=35.0, fault_phys_state=zero_fault)

        # High throttle steady state
        for _ in range(400):
            st_high = plant.step(0.1, throttle_pct=90.0, altitude_m=1000.0, airspeed_mps=35.0, fault_phys_state=zero_fault)

        self.assertGreater(st_high["rpm_true"], st_low["rpm_true"] + 2000.0)
        self.assertGreater(st_high["egt1_true"], st_low["egt1_true"] + 80.0)
        self.assertGreater(st_high["cht1_true"], st_low["cht1_true"] + 20.0)
        self.assertGreater(st_high["fuel_flow_gps_true"], st_low["fuel_flow_gps_true"] * 2.0)

    def test_injector_clog_physical_coupling(self):
        """Injector clog on Cylinder 3 must increase Cyl 3 EGT and cause RPM droop."""
        phases = [
            {"name": "cruise", "duration_sec": 120.0, "start_alt_m": 2000.0, "end_alt_m": 2000.0,
             "start_throttle_pct": 75.0, "end_throttle_pct": 75.0, "start_airspeed_mps": 42.0, "end_airspeed_mps": 42.0}
        ]
        prof = generate_mission_profile(phases=phases, dt=0.1)
        faults = [
            FaultEvent(
                fault_type="injector_clog",
                start_time_sec=40.0,
                duration_ramp_sec=10.0,
                target_cylinder=3,
                severity=0.35
            )
        ]
        df = simulate_mission(mission_profile=prof, faults=faults, random_seed=42)

        # Compare t=35s (nominal) to t=80s (fully faulted)
        t_pre = df[df["timestamp_sec"] == 35.0].iloc[0]
        t_post = df[df["timestamp_sec"] == 80.0].iloc[0]

        # Cyl 3 EGT must rise significantly due to lean combustion
        egt3_rise = t_post["egt3_true"] - t_pre["egt3_true"]
        self.assertGreater(egt3_rise, 60.0, f"Expected Cyl 3 EGT rise > 60°C, got {egt3_rise}°C")

        # Other cylinders should NOT show abnormal rises
        egt1_change = abs(t_post["egt1_true"] - t_pre["egt1_true"])
        self.assertLess(egt1_change, 10.0, f"Cyl 1 EGT should be stable, changed by {egt1_change}°C")

        # Engine shaft power reduction should cause RPM droop
        rpm_droop = t_pre["rpm_true"] - t_post["rpm_true"]
        self.assertGreater(rpm_droop, 150.0, f"Expected RPM droop > 150 RPM, got {rpm_droop}")

    def test_sensor_drift_isolation(self):
        """Sensor drift must alter telemetry BUT leave true physical state untainted."""
        phases = [
            {"name": "cruise", "duration_sec": 80.0, "start_alt_m": 2000.0, "end_alt_m": 2000.0,
             "start_throttle_pct": 75.0, "end_throttle_pct": 75.0, "start_airspeed_mps": 42.0, "end_airspeed_mps": 42.0}
        ]
        prof = generate_mission_profile(phases=phases, dt=0.1)
        faults = [
            FaultEvent(
                fault_type="sensor_drift",
                start_time_sec=20.0,
                sensor_name="egt2",
                drift_rate=1.0  # +1.0 °C per second
            )
        ]
        df = simulate_mission(mission_profile=prof, faults=faults, random_seed=42)

        t_late = df[df["timestamp_sec"] == 70.0].iloc[0]
        # True physical state should be completely nominal
        self.assertAlmostEqual(t_late["egt2_true"], t_late["egt1_true"] + 8.0, delta=12.0)
        # Measured telemetry should show substantial drift: ~50s * 1.0°C/s = ~50°C bias
        bias = t_late["egt2"] - t_late["egt2_true"]
        self.assertGreater(bias, 40.0, f"Expected sensor drift bias > 40°C, got {bias}°C")

        # Crucially: RPM and other physical states should remain within normal cruise regime
        self.assertGreaterEqual(t_late["rpm_true"], 4200.0)
        self.assertLessEqual(t_late["rpm_true"], 5200.0)

    def test_dataset_generation(self):
        """Batch generation must output valid CSVs, manifest, and non-empty rows."""
        import json
        import tempfile
        import shutil
        temp_data_dir = tempfile.mkdtemp(prefix="uav_test_data_")
        try:
            res = generate_synthetic_dataset(num_runs=3, output_dir=temp_data_dir, seed=42)
            self.assertEqual(res["runs_generated"], 3)
            self.assertTrue(os.path.exists(res["manifest_path"]))

            # Read first run dynamically from manifest
            with open(res["manifest_path"], "r") as f:
                manifest = json.load(f)
            runs_list = manifest["runs"] if isinstance(manifest, dict) and "runs" in manifest else manifest
            first_filename = runs_list[0]["filename"]
            run_file = os.path.join(temp_data_dir, first_filename)
            self.assertTrue(os.path.exists(run_file))
            df_run = pd.read_csv(run_file)
            self.assertGreater(len(df_run), 100)
            self.assertFalse(df_run.isnull().values.any(), "Generated dataset must not contain NaN values")
        finally:
            shutil.rmtree(temp_data_dir, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
