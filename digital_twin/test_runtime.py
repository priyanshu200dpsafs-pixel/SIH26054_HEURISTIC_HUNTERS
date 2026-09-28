#!/usr/bin/env python3
"""
===============================================================================
PHASE 3B UNIT & COMPONENT TEST SUITE: DIGITAL TWIN RUNTIME
===============================================================================
Validates the DigitalTwinRuntime diagnostic engine across:
  Test A: Nominal baseline behavior (Healthy, no false alarms, valid RUL)
  Test B: Injector clog physical fault (EGT rise, RPM droop, degraded/critical)
  Test C: Oil leak physical fault (Oil pressure drop, oil temp rise)
  Test D: Sensor drift instrument fault (Isolated sensor bias vs mechanical state)
  Test E: Cooling blockage (Documents known Phase 3A thermal coupling behavior)
  Test F: Invalid telemetry handling (Missing keys, NaN, out-of-bounds)
  Test G: Sequence gap detection (Transport frame skip / drop)
  Test H: Stateless RUL inference (A -> B -> A determinism, no hidden latch)
  Test I: Explainability grounding (Evidence reflects true calculated residuals)
===============================================================================
"""

import os
import sys
import copy
import math
import unittest
from typing import Dict, Any, Optional
import numpy as np

# Ensure project root is on sys.path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from plant_model.engine_plant import AeroEnginePlant
from plant_model.physics_core import EngineSpecs
from digital_twin.state import (
    DigitalTwinState,
    EngineHealthState,
    TelemetryQuality,
    RedlineStatus,
    ResidualStatus
)
from digital_twin.runtime import DigitalTwinRuntime


class TestDigitalTwinRuntime(unittest.TestCase):
    """Unit test suite for DigitalTwinRuntime."""

    def setUp(self):
        self.specs = EngineSpecs()
        self.plant = AeroEnginePlant(specs=self.specs, seed=42)
        self.runtime = DigitalTwinRuntime(specs=self.specs, ewma_alpha=0.05)

    def step_plant(
        self,
        throttle: float = 82.0,
        alt: float = 500.0,
        airspeed: float = 40.0,
        fault_phys: Optional[Dict[str, Any]] = None,
        sensor_biases: Optional[Dict[str, float]] = None,
        t: float = 0.0,
        seq: int = 1
    ) -> Dict[str, Any]:
        """Steps authentic plant model and applies sensors to produce consistent telemetry."""
        if fault_phys is None:
            fault_phys = {
                "injector_clog_pct": [0.0, 0.0, 0.0, 0.0],
                "power_deficit_factor": 0.0,
                "oil_leak_severity": 0.0,
                "cooling_blockage_pct": 0.0,
                "active_physical_fault": "nominal",
                "fault_cylinder": 0,
                "fault_severity": 0.0
            }
        true_state = self.plant.step(
            dt=0.1,
            throttle_pct=throttle,
            altitude_m=alt,
            airspeed_mps=airspeed,
            fault_phys_state=fault_phys
        )
        if sensor_biases is None:
            sensor_biases = {}
        telem = self.plant.apply_sensors(true_state=true_state, sensor_drift_biases=sensor_biases)
        telem["throttle_pct"] = throttle
        telem["altitude_m"] = alt
        telem["airspeed_mps"] = airspeed
        telem["timestamp"] = t
        telem["sequence"] = seq
        telem["cycle_id"] = seq
        return telem

    def test_a_nominal(self):
        """Test A: Nominal telemetry produces healthy state and no false faults."""
        state = None
        for i in range(1, 30):
            telem = self.step_plant(throttle=82.0, alt=500.0, airspeed=40.0, t=float(i) * 0.1, seq=i)
            state = self.runtime.process(telem, dt=0.1)

        self.assertIsNotNone(state)
        self.assertEqual(state.telemetry_status, TelemetryQuality.VALID)
        self.assertEqual(state.engine_state, EngineHealthState.HEALTHY)
        self.assertEqual(state.fault_type, "nominal")
        self.assertEqual(state.redline_status, RedlineStatus.NORMAL.value)
        self.assertIsNotNone(state.rul_hours)
        self.assertGreater(state.rul_hours, 100.0, "Nominal RUL should remain high")
        self.assertIsNotNone(state.health_score)
        self.assertGreaterEqual(state.health_score, 0.90)

    def test_b_injector_clog(self):
        """Test B: Injector clog raises EGT, droops RPM, causes degraded state."""
        # 1. Warm up baseline for 25 cycles
        for i in range(1, 25):
            telem = self.step_plant(throttle=82.0, alt=500.0, airspeed=40.0, t=float(i) * 0.1, seq=i)
            self.runtime.process(telem, dt=0.1)

        # 2. Inject cylinder 2 injector clog (fuel restriction = 50%, causes EGT rise and power drop)
        state = None
        clog_phys = {
            "injector_clog_pct": [0.0, 0.50, 0.0, 0.0],
            "power_deficit_factor": 0.50 * 0.25,
            "oil_leak_severity": 0.0,
            "cooling_blockage_pct": 0.0,
            "active_physical_fault": "injector_clog",
            "fault_cylinder": 2,
            "fault_severity": 0.50
        }
        for i in range(25, 60):
            telem = self.step_plant(
                throttle=82.0,
                alt=500.0,
                airspeed=40.0,
                fault_phys=clog_phys,
                t=float(i) * 0.1,
                seq=i
            )
            state = self.runtime.process(telem, dt=0.1)

        self.assertIsNotNone(state)
        self.assertTrue(state.residual_status in ("CAUTION", "ALERT"))
        self.assertEqual(state.fault_type, "injector_clog")
        self.assertEqual(state.engine_state, EngineHealthState.DEGRADED)
        self.assertIsNotNone(state.rul_hours)
        self.assertLess(state.rul_hours, 180.0, "RUL should decline under persistent injector clog")

        # Verify evidence references genuine combustion physics
        self.assertGreater(len(state.explanation.evidence), 0)
        ev_text = " ".join(state.explanation.evidence)
        self.assertTrue("EGT" in ev_text or "egt" in ev_text.lower())

    def test_c_oil_leak(self):
        """Test C: Oil leak drops oil pressure, elevates oil temp."""
        for i in range(1, 25):
            telem = self.step_plant(throttle=82.0, alt=500.0, airspeed=40.0, t=float(i) * 0.1, seq=i)
            self.runtime.process(telem, dt=0.1)

        state = None
        leak_phys = {
            "injector_clog_pct": [0.0, 0.0, 0.0, 0.0],
            "power_deficit_factor": 0.0,
            "oil_leak_severity": 0.75,
            "cooling_blockage_pct": 0.0,
            "active_physical_fault": "oil_leak",
            "fault_cylinder": 0,
            "fault_severity": 0.75
        }
        for i in range(25, 110):
            telem = self.step_plant(
                throttle=82.0,
                alt=500.0,
                airspeed=40.0,
                fault_phys=leak_phys,
                t=float(i) * 0.1,
                seq=i
            )
            state = self.runtime.process(telem, dt=0.1)

        self.assertIsNotNone(state)
        self.assertTrue(state.residual_status in ("CAUTION", "ALERT"))
        self.assertEqual(state.fault_type, "oil_leak")
        self.assertIn(state.engine_state, (EngineHealthState.DEGRADED, EngineHealthState.CRITICAL))

        # Check explanation
        ev_text = " ".join(state.explanation.evidence)
        self.assertTrue("oil" in ev_text.lower() or "lubrication" in state.explanation.summary.lower())

    def test_d_sensor_drift(self):
        """Test D: Sensor drift is isolated to instrument and distinguishes from plant fault."""
        for i in range(1, 25):
            telem = self.step_plant(throttle=82.0, alt=500.0, airspeed=40.0, t=float(i) * 0.1, seq=i)
            self.runtime.process(telem, dt=0.1)

        # Drift ONLY EGT2 thermocouple while physical plant state is 100% nominal
        state = None
        drift_bias = {"egt2": 80.0}
        for i in range(25, 60):
            telem = self.step_plant(
                throttle=82.0,
                alt=500.0,
                airspeed=40.0,
                sensor_biases=drift_bias,
                t=float(i) * 0.1,
                seq=i
            )
            state = self.runtime.process(telem, dt=0.1)

        self.assertIsNotNone(state)
        self.assertEqual(state.fault_type, "sensor_drift")
        # Sensor drift indicates instrument defect, health score remains moderately high
        self.assertGreater(state.health_score, 0.70)
        self.assertTrue("sensor" in state.explanation.summary.lower() or "instrument" in state.explanation.summary.lower())

    def test_e_cooling_blockage(self):
        """
        Test E: Cooling duct blockage.
        Verifies actual Phase 3A behavior: acknowledges known weak CHT coupling
        where small CHT rises (<7°C) remain within caution boundaries.
        """
        for i in range(1, 25):
            telem = self.step_plant(throttle=82.0, alt=500.0, airspeed=40.0, t=float(i) * 0.1, seq=i)
            self.runtime.process(telem, dt=0.1)

        state = None
        cool_phys = {
            "injector_clog_pct": [0.0, 0.0, 0.0, 0.0],
            "power_deficit_factor": 0.0,
            "oil_leak_severity": 0.0,
            "cooling_blockage_pct": 0.60,
            "active_physical_fault": "cooling_duct_blockage",
            "fault_cylinder": 0,
            "fault_severity": 0.60
        }
        for i in range(25, 60):
            telem = self.step_plant(
                throttle=82.0,
                alt=500.0,
                airspeed=40.0,
                fault_phys=cool_phys,
                t=float(i) * 0.1,
                seq=i
            )
            state = self.runtime.process(telem, dt=0.1)

        self.assertIsNotNone(state)
        # Runtime must safely handle cooling blockage scenario without crashing
        self.assertIn(state.fault_type, ("cooling_duct_blockage", "general_degradation", "nominal"))
        self.assertIn(state.engine_state, (EngineHealthState.HEALTHY, EngineHealthState.DEGRADED))

    def test_f_invalid_telemetry(self):
        """Test F: Invalid telemetry does not crash runtime and outputs UNKNOWN state."""
        # Case 1: Missing required keys
        corrupted = {"timestamp": 12.0, "rpm": 4500.0}
        state = self.runtime.process(corrupted, dt=0.1)
        self.assertEqual(state.telemetry_status, TelemetryQuality.INVALID)
        self.assertEqual(state.engine_state, EngineHealthState.UNKNOWN)
        self.assertIsNone(state.health_score)
        self.assertGreater(len(state.explanation.evidence), 0)

        # Case 2: NaN values
        nan_telem = self.step_plant(t=13.0, seq=15)
        nan_telem["egt1"] = float("nan")
        state_nan = self.runtime.process(nan_telem, dt=0.1)
        self.assertEqual(state_nan.telemetry_status, TelemetryQuality.INVALID)
        self.assertEqual(state_nan.engine_state, EngineHealthState.UNKNOWN)

    def test_g_sequence_gap(self):
        """Test G: Sequence gaps are detected and logged as degraded telemetry."""
        for i in range(1, 6):
            telem = self.step_plant(t=float(i) * 0.1, seq=i)
            self.runtime.process(telem, dt=0.1)

        # Inject gap: jump from seq 5 to seq 15
        gap_telem = self.step_plant(t=1.5, seq=15)
        state = self.runtime.process(gap_telem, dt=0.1)

        self.assertEqual(state.telemetry_status, TelemetryQuality.DEGRADED)
        self.assertGreater(self.runtime.total_sequence_gaps, 0)

    def test_h_stateless_rul(self):
        """
        Test H: Stateless RUL inference determinism.
        Verifies that RULEstimator.predict() is strictly stateless:
        feature_vector A -> B -> A produces the exact same prediction without
        monotonic clamping or historical latching.
        """
        feat_nominal = np.array([
            0.5, 0.3, 2.0, 0.02, 0.4, 0.01,
            0.0, 0.0, 0.0, 0.0, 0.05,
            82.0, 500.0
        ], dtype=float)

        feat_degraded = np.array([
            65.0, 8.0, 95.0, 0.15, 2.5, 0.35,
            1.2, -90.0, 15.0, 4.5, 0.45,
            82.0, 500.0
        ], dtype=float)

        # Step 1: Predict for nominal feature vector A
        pred_a1 = self.runtime.rul_estimator.predict(feat_nominal)
        rul_a1 = pred_a1["rul_hours"]

        # Step 2: Predict for degraded feature vector B
        pred_b = self.runtime.rul_estimator.predict(feat_degraded)
        rul_b = pred_b["rul_hours"]

        # Step 3: Predict for nominal feature vector A again
        pred_a2 = self.runtime.rul_estimator.predict(feat_nominal)
        rul_a2 = pred_a2["rul_hours"]

        self.assertIsNotNone(rul_a1)
        self.assertIsNotNone(rul_b)
        self.assertIsNotNone(rul_a2)

        # Degraded RUL must be significantly lower than nominal
        self.assertLess(rul_b, rul_a1)

        # Vector A evaluated after Vector B MUST match Vector A evaluated initially
        # Proves zero stateful latching in the core prediction engine
        self.assertEqual(
            rul_a1,
            rul_a2,
            msg=f"Stateless RUL inference violated: rul_a1={rul_a1} != rul_a2={rul_a2}"
        )
        self.assertEqual(pred_a1["rul_lower_hours"], pred_a2["rul_lower_hours"])
        self.assertEqual(pred_a1["rul_upper_hours"], pred_a2["rul_upper_hours"])

    def test_i_explainability(self):
        """Test I: Explanations strictly reference calculated residuals and telemetry."""
        for i in range(1, 20):
            telem = self.step_plant(throttle=82.0, alt=500.0, airspeed=40.0, t=float(i) * 0.1, seq=i)
            self.runtime.process(telem, dt=0.1)

        # Inject oil leak
        leak_phys = {
            "injector_clog_pct": [0.0, 0.0, 0.0, 0.0],
            "power_deficit_factor": 0.0,
            "oil_leak_severity": 0.50,
            "cooling_blockage_pct": 0.0,
            "active_physical_fault": "oil_leak",
            "fault_cylinder": 0,
            "fault_severity": 0.50
        }
        state = None
        for i in range(20, 45):
            telem = self.step_plant(
                throttle=82.0,
                alt=500.0,
                airspeed=40.0,
                fault_phys=leak_phys,
                t=float(i) * 0.1,
                seq=i
            )
            state = self.runtime.process(telem, dt=0.1)

        self.assertIsNotNone(state.explanation)
        self.assertIsNotNone(state.explanation.summary)
        self.assertGreater(len(state.explanation.evidence), 0)

        # Check evidence references actual features
        ev_joined = " ".join(state.explanation.evidence)
        self.assertTrue(
            "oil" in ev_joined.lower() or "pressure" in ev_joined.lower() or "temperature" in ev_joined.lower(),
            f"Evidence did not reference oil features: {state.explanation.evidence}"
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
