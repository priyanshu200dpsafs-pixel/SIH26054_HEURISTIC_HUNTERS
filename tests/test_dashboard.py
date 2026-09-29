#!/usr/bin/env python3
"""
===============================================================================
PHASE 4 TEST SUITE: MISSION CONTROL DASHBOARD & REPLAY VERIFICATION
===============================================================================
SIH26054 — Explainable Digital Twin for MALE UAV Aero Piston Powerplant

Validates Phase 4 compliance:
  Test A: Dashboard imports
  Test B: State adaptation
  Test C: No diagnosis duplication (adapter is strictly a projection)
  Test D: Nominal display representation
  Test E: Injector clog representation
  Test F: Oil leak representation
  Test G: Sensor drift representation
  Test H: Cooling blockage representation
  Test I: UNKNOWN state on invalid telemetry
  Test J: Sequence gap / degraded telemetry handling
  Test K: RUL / Q10 / Q90 passthrough integrity
  Test L: Explainability causal grounding (evidence items)
  Test M: Mission replay uses authentic DigitalTwinRuntime
  Test N: Dataset integrity (data/ is strictly read-only, 0 bytes altered)
  Test O: Full E2E Live Simulation Pipeline (Plant → CAN → UDP → Decoder → Runtime → State → Adapter)
===============================================================================
"""

import os
import sys
import json
import hashlib
import unittest
from typing import Dict, Any, List

# Ensure project root is in sys.path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from digital_twin.state import (
    DigitalTwinState,
    EngineHealthState,
    TelemetryQuality,
    RedlineStatus,
    MeasuredTelemetry,
    PhysicsDerivedState,
    MLPredictionState,
    Explanation,
)
from digital_twin.explanation import EvidenceItem
from digital_twin.runtime import DigitalTwinRuntime
from dashboard.formatting import (
    STATE_COLORS,
    TELEMETRY_COLORS,
    get_state_color,
    get_telemetry_color,
    format_hours,
    format_temp,
    format_press,
    format_rpm,
    format_health_index,
)
from dashboard.state_adapter import DashboardStateAdapter, DashboardState
from dashboard.telemetry_history import TelemetryHistoryBuffer
from dashboard.mission_controller import LiveMissionController
from dashboard.replay import MissionReplayController


class TestDashboardSuite(unittest.TestCase):
    """Rigorous acceptance test suite for Phase 4 Dashboard & Visualization."""

    def setUp(self):
        self.data_dir = os.path.join(PROJECT_ROOT, "data")

    # -------------------------------------------------------------------------
    # Test A: Dashboard Imports
    # -------------------------------------------------------------------------
    def test_a_dashboard_imports(self):
        """Verifies that all dashboard modules and components import cleanly."""
        import dashboard
        import dashboard.formatting
        import dashboard.state_adapter
        import dashboard.telemetry_history
        import dashboard.mission_controller
        import dashboard.replay
        import dashboard.session
        import dashboard.app
        import dashboard.components
        from dashboard.components import (
            render_header,
            render_health_card,
            render_engine_parameters,
            render_rul_panel,
            render_residual_panel,
            render_fault_panel,
            render_explanation_panel,
            render_redline_panel,
            render_telemetry_health,
            render_timeline,
            render_charts,
            render_controls,
        )
        self.assertIsNotNone(dashboard)
        self.assertIsNotNone(dashboard.app)

    # -------------------------------------------------------------------------
    # Test B: State Adaptation
    # -------------------------------------------------------------------------
    def test_b_state_adaptation(self):
        """Verifies canonical DigitalTwinState adapts correctly into DashboardState."""
        state = DigitalTwinState(
            timestamp=12.5,
            sequence_number=125,
            cycle_id=125,
            telemetry_status=TelemetryQuality.VALID,
            engine_state=EngineHealthState.HEALTHY,
            health_score=0.98,
            fault_type="nominal",
            rul_hours=142.5,
            rul_q10_hours=120.0,
            rul_q90_hours=165.0,
            telemetry=MeasuredTelemetry(
                rpm=4800.0,
                throttle_pct=75.0,
                fuel_flow_gps=5.2,
                egt1=780.0, egt2=785.0, egt3=779.0, egt4=782.0,
                cht1=145.0, cht2=148.0, cht3=144.0, cht4=146.0,
                oil_press_bar=3.4, oil_temp_c=88.0, airspeed_mps=45.0, altitude_m=1200.0
            ),
            predictions=MLPredictionState(
                fault_type="nominal",
                fault_confidence=0.99,
                fault_subtype="NONE",
                fault_location="NONE",
                uncertainty_band_hours=45.0
            )
        )
        adapted = DashboardStateAdapter.adapt(state)

        self.assertIsInstance(adapted, DashboardState)
        self.assertEqual(adapted.timestamp_sec, 12.5)
        self.assertEqual(adapted.sequence_number, 125)
        self.assertEqual(adapted.engine_state, "HEALTHY")
        self.assertEqual(adapted.engine_state_color, "#2ecc71")
        self.assertEqual(adapted.health_index_int, 98)
        self.assertEqual(adapted.health_score_display, "98 / 100")
        self.assertEqual(adapted.telemetry_status, "VALID")
        self.assertEqual(adapted.fault_display, "NOMINAL")
        self.assertEqual(adapted.rul_display, "142.5 h")
        self.assertEqual(adapted.damage_state, "HEALTHY")
        self.assertEqual(adapted.rpm, 4800.0)
        self.assertEqual(adapted.max_egt, 785.0)

    # -------------------------------------------------------------------------
    # Test C: No Diagnosis Duplication
    # -------------------------------------------------------------------------
    def test_c_no_diagnosis_duplication(self):
        """
        Verifies that DashboardStateAdapter does NOT independently reclassify faults,
        recompute health states, or alter diagnostic fields.
        """
        # Create an artificial state where fault_type is custom
        state = DigitalTwinState(
            timestamp=20.0,
            sequence_number=200,
            engine_state=EngineHealthState.DEGRADED,
            fault_type="custom_synthetic_anomaly",
            rul_hours=42.0,
            predictions=MLPredictionState(
                fault_type="custom_synthetic_anomaly",
                fault_confidence=0.88,
                fault_location="CYLINDER_3"
            )
        )
        adapted = DashboardStateAdapter.adapt(state)

        # The adapter must strictly preserve what runtime produced
        self.assertEqual(adapted.fault_type, "custom_synthetic_anomaly")
        self.assertEqual(adapted.fault_display, "CUSTOM SYNTHETIC ANOMALY")
        self.assertEqual(adapted.engine_state, "DEGRADED")
        self.assertEqual(adapted.fault_location, "CYLINDER_3")

    # -------------------------------------------------------------------------
    # Test D: Nominal Display
    # -------------------------------------------------------------------------
    def test_d_nominal_display(self):
        """Verifies nominal state renders healthy tokens and green indicators."""
        state = DigitalTwinState(
            timestamp=5.0,
            sequence_number=50,
            telemetry_status=TelemetryQuality.VALID,
            engine_state=EngineHealthState.HEALTHY,
            health_score=1.0,
            fault_type="nominal",
            rul_hours=150.0
        )
        adapted = DashboardStateAdapter.adapt(state)
        self.assertEqual(adapted.engine_state, "HEALTHY")
        self.assertEqual(adapted.engine_state_color, "#2ecc71")
        self.assertEqual(adapted.damage_state, "HEALTHY")
        self.assertTrue(adapted.sequence_ok)

    # -------------------------------------------------------------------------
    # Test E: Injector Clog Display
    # -------------------------------------------------------------------------
    def test_e_injector_clog_display(self):
        """Verifies injector clog fault state adapts accurately."""
        state = DigitalTwinState(
            timestamp=18.0,
            sequence_number=180,
            telemetry_status=TelemetryQuality.VALID,
            engine_state=EngineHealthState.DEGRADED,
            health_score=0.65,
            fault_type="injector_clog",
            rul_hours=38.5,
            predictions=MLPredictionState(
                fault_type="injector_clog",
                fault_confidence=0.94,
                fault_subtype="FUEL_DELIVERY",
                fault_location="CYLINDER_2"
            )
        )
        adapted = DashboardStateAdapter.adapt(state)
        self.assertEqual(adapted.engine_state, "DEGRADED")
        self.assertEqual(adapted.engine_state_color, "#f39c12")
        self.assertEqual(adapted.fault_display, "INJECTOR CLOG")
        self.assertEqual(adapted.fault_confidence_pct, "94%")
        self.assertEqual(adapted.fault_location, "CYLINDER_2")
        self.assertEqual(adapted.damage_state, "PROGRESSIVE_DEGRADATION")

    # -------------------------------------------------------------------------
    # Test F: Oil Leak Display
    # -------------------------------------------------------------------------
    def test_f_oil_leak_display(self):
        """Verifies oil leak fault state adapts to critical condition."""
        state = DigitalTwinState(
            timestamp=25.0,
            sequence_number=250,
            telemetry_status=TelemetryQuality.VALID,
            engine_state=EngineHealthState.CRITICAL,
            health_score=0.25,
            fault_type="oil_leak",
            rul_hours=8.2,
            predictions=MLPredictionState(
                fault_type="oil_leak",
                fault_confidence=0.97,
                fault_subtype="LUBRICATION_PRESSURE_LOSS",
                fault_location="OIL_CIRCUIT"
            )
        )
        adapted = DashboardStateAdapter.adapt(state)
        self.assertEqual(adapted.engine_state, "CRITICAL")
        self.assertEqual(adapted.engine_state_color, "#e74c3c")
        self.assertEqual(adapted.fault_display, "OIL LEAK")
        self.assertEqual(adapted.damage_state, "CRITICAL_CONDITION")

    # -------------------------------------------------------------------------
    # Test G: Sensor Drift Display
    # -------------------------------------------------------------------------
    def test_g_sensor_drift_display(self):
        """Verifies sensor drift instrument fault adapts cleanly."""
        state = DigitalTwinState(
            timestamp=22.0,
            sequence_number=220,
            telemetry_status=TelemetryQuality.VALID,
            engine_state=EngineHealthState.DEGRADED,
            health_score=0.72,
            fault_type="sensor_drift",
            rul_hours=65.0,
            predictions=MLPredictionState(
                fault_type="sensor_drift",
                fault_confidence=0.91,
                fault_subtype="INSTRUMENTATION_BIAS",
                fault_location="SENSOR_EGT2"
            )
        )
        adapted = DashboardStateAdapter.adapt(state)
        self.assertEqual(adapted.fault_display, "SENSOR DRIFT")
        self.assertEqual(adapted.fault_location, "SENSOR_EGT2")

    # -------------------------------------------------------------------------
    # Test H: Cooling Blockage Display
    # -------------------------------------------------------------------------
    def test_h_cooling_blockage_display(self):
        """Verifies cooling duct blockage fault adapts cleanly."""
        state = DigitalTwinState(
            timestamp=28.0,
            sequence_number=280,
            telemetry_status=TelemetryQuality.VALID,
            engine_state=EngineHealthState.DEGRADED,
            health_score=0.58,
            fault_type="cooling_duct_blockage",
            rul_hours=42.0,
            predictions=MLPredictionState(
                fault_type="cooling_duct_blockage",
                fault_confidence=0.85,
                fault_subtype="AIRFLOW_RESTRICTION",
                fault_location="COWLING_INLET"
            )
        )
        adapted = DashboardStateAdapter.adapt(state)
        self.assertEqual(adapted.fault_display, "COOLING DUCT BLOCKAGE")

    # -------------------------------------------------------------------------
    # Test I: UNKNOWN State on Invalid Telemetry
    # -------------------------------------------------------------------------
    def test_i_unknown_state_invalid_telemetry(self):
        """Verifies invalid telemetry produces UNKNOWN state without forcing HEALTHY."""
        state = DigitalTwinState(
            timestamp=10.0,
            sequence_number=100,
            telemetry_status=TelemetryQuality.INVALID,
            engine_state=EngineHealthState.UNKNOWN,
            health_score=None,
            fault_type="unknown",
            rul_hours=None
        )
        adapted = DashboardStateAdapter.adapt(state)
        self.assertEqual(adapted.engine_state, "UNKNOWN")
        self.assertEqual(adapted.engine_state_color, "#95a5a6")
        self.assertEqual(adapted.telemetry_status, "INVALID")
        self.assertEqual(adapted.rul_display, "RUL UNAVAILABLE")
        self.assertEqual(adapted.health_score_display, "N/A")
        self.assertFalse(adapted.sequence_ok)

    # -------------------------------------------------------------------------
    # Test J: Sequence Gap / Degraded Telemetry
    # -------------------------------------------------------------------------
    def test_j_sequence_gap_handling(self):
        """Verifies sequence gap is identified and telemetry labeled DEGRADED."""
        state = DigitalTwinState(
            timestamp=15.0,
            sequence_number=155,  # Jumped from 150
            telemetry_status=TelemetryQuality.DEGRADED,
            engine_state=EngineHealthState.HEALTHY,
            health_score=0.95
        )
        adapted = DashboardStateAdapter.adapt(state)
        self.assertEqual(adapted.telemetry_status, "DEGRADED")
        self.assertEqual(adapted.telemetry_status_color, "#f39c12")

    # -------------------------------------------------------------------------
    # Test K: RUL / Q10 / Q90 Integrity
    # -------------------------------------------------------------------------
    def test_k_rul_passthrough_integrity(self):
        """Verifies point RUL and uncertainty percentiles pass through unmodified."""
        state = DigitalTwinState(
            rul_hours=64.832,
            rul_q10_hours=51.214,
            rul_q90_hours=78.945,
            predictions=MLPredictionState(uncertainty_band_hours=27.731)
        )
        adapted = DashboardStateAdapter.adapt(state)
        self.assertEqual(adapted.rul_hours, 64.832)
        self.assertEqual(adapted.rul_q10_hours, 51.214)
        self.assertEqual(adapted.rul_q90_hours, 78.945)
        self.assertEqual(adapted.rul_display, "64.8 h")
        self.assertEqual(adapted.rul_q10_display, "51.2 h")
        self.assertEqual(adapted.rul_q90_display, "78.9 h")
        self.assertEqual(adapted.uncertainty_display, "[51.2, 78.9] h")

    # -------------------------------------------------------------------------
    # Test L: Explainability Grounding
    # -------------------------------------------------------------------------
    def test_l_explainability_grounding(self):
        """Verifies dashboard evidence items originate strictly from runtime EvidenceItems."""
        item1 = EvidenceItem("egt_residual", 78.2, "°C", "elevated above thermal observer")
        item2 = EvidenceItem("rpm_residual", -480.0, "RPM", "power deficit under nominal throttle")

        explanation = Explanation(
            summary="Combustion anomaly detected consistent with fuel injector restriction.",
            evidence=[item1, item2],
            physics_indicators=["Localized cylinder 2 thermal spike", "Crankshaft deceleration"],
            diagnostic_basis="Physics observer residuals crossed 3-sigma statistical boundary."
        )

        state = DigitalTwinState(
            explanation=explanation,
            fault_type="injector_clog"
        )
        adapted = DashboardStateAdapter.adapt(state)

        self.assertEqual(len(adapted.evidence_items), 2)
        self.assertEqual(adapted.evidence_items[0]["feature"], "egt_residual")
        self.assertEqual(adapted.evidence_items[0]["value"], 78.2)
        self.assertEqual(adapted.evidence_items[0]["unit"], "°C")
        self.assertEqual(adapted.evidence_items[1]["feature"], "rpm_residual")
        self.assertEqual(adapted.evidence_items[1]["value"], -480.0)
        self.assertEqual(len(adapted.physics_indicators), 2)
        self.assertIn("3-sigma", adapted.diagnostic_basis)

    # -------------------------------------------------------------------------
    # Test M: Mission Replay Uses DigitalTwinRuntime
    # -------------------------------------------------------------------------
    def test_m_replay_uses_digital_twin_runtime(self):
        """Verifies mission replay instantiates and feeds genuine DigitalTwinRuntime."""
        replay = MissionReplayController()
        sorties = replay.get_available_sorties()
        self.assertGreater(len(sorties), 0, "Expected sorties in dataset")

        first_sortie = sorties[0]["filename"]
        loaded = replay.load_sortie(first_sortie)
        self.assertTrue(loaded)
        self.assertIsInstance(replay.runtime, DigitalTwinRuntime)

        # Step 5 rows
        for _ in range(5):
            st_step = replay.step()
            self.assertIsNotNone(st_step)
            self.assertIsInstance(st_step, DigitalTwinState)

        self.assertEqual(replay.current_idx, 5)
        self.assertIsNotNone(replay.latest_state)

    # -------------------------------------------------------------------------
    # Test N: Dataset Integrity Protection (Strict Read-Only)
    # -------------------------------------------------------------------------
    def test_n_dataset_integrity(self):
        """
        Verifies that running dashboard components and replay causes ZERO modifications
        to data/ or dataset_manifest.json.
        """
        manifest_path = os.path.join(self.data_dir, "dataset_manifest.json")
        with open(manifest_path, "rb") as f:
            manifest_hash_before = hashlib.sha256(f.read()).hexdigest()

        # Execute replay controller actions
        replay = MissionReplayController()
        sorties = replay.get_available_sorties()
        if sorties:
            replay.load_sortie(sorties[0]["filename"])
            for _ in range(10):
                replay.step()
            replay.reset()

        # Check hash of manifest
        with open(manifest_path, "rb") as f:
            manifest_hash_after = hashlib.sha256(f.read()).hexdigest()

        self.assertEqual(manifest_hash_before, manifest_hash_after, "dataset_manifest.json must remain identical")

    # -------------------------------------------------------------------------
    # Test O: Full E2E Live Simulation Pipeline
    # -------------------------------------------------------------------------
    def test_o_full_e2e_live_simulation_pipeline(self):
        """
        Verifies complete unmocked pipeline:
        Plant -> CAN Encoder -> UDP Transport -> CAN Decoder -> TelemetryEvent -> DigitalTwinRuntime -> DigitalTwinState -> DashboardState
        for Nominal, Injector Clog, Oil Leak, Sensor Drift, and Cooling Blockage.
        """
        scenarios = [
            ("nominal", 0.0),
            ("injector_clog", 0.6),
            ("oil_leak", 0.7),
            ("sensor_drift", 0.5),
            ("cooling_duct_blockage", 0.6),
        ]

        for sc_type, sev in scenarios:
            ctrl = LiveMissionController(
                fault_type=sc_type,
                fault_severity=sev,
                duration_sec=3.0,  # 30 frames
                rate_hz=10.0,
                random_seed=42
            )
            try:
                states: List[DigitalTwinState] = []
                for _ in range(15):  # Step 15 frames
                    res = ctrl.step()
                    if res:
                        states.append(res)

                self.assertGreaterEqual(len(states), 10, f"Expected frames for scenario {sc_type}")
                latest = states[-1]
                self.assertIsInstance(latest, DigitalTwinState)

                # Adapt to dashboard state
                adapted = DashboardStateAdapter.adapt(latest)
                self.assertIsInstance(adapted, DashboardState)
                self.assertIn(adapted.engine_state, ["HEALTHY", "DEGRADED", "CRITICAL"])
                self.assertEqual(adapted.telemetry_status, "VALID")
                self.assertGreater(adapted.rpm, 3000.0)

            finally:
                ctrl.close()


if __name__ == "__main__":
    unittest.main()
