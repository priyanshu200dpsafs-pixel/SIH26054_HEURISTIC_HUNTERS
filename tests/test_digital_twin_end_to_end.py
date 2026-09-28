#!/usr/bin/env python3
"""
===============================================================================
PHASE 3B INTEGRATION TEST SUITE: COMPLETE END-TO-END TELEMETRY PIPELINE
===============================================================================
SIH26054 — Explainable Digital Twin for MALE UAV Aero Piston Powerplant

Validates the full unmocked live pipeline:
  Engine Plant (AeroEnginePlant)
        ↓
  CAN Frame Encoder (EngineCANEncoder, 28-byte envelopes)
        ↓
  Cross-Platform Transport (LocalUDPTransport on 127.0.0.1)
        ↓
  CAN Frame Decoder (EngineCANDecoder, CRC-8, Parity, DBC)
        ↓
  Telemetry Event (TelemetryEvent model)
        ↓
  Digital Twin Runtime (DigitalTwinRuntime, Physics Observer, Residuals, ML)
        ↓
  Unified State (DigitalTwinState)

Scenarios Tested:
  1. Nominal baseline mission
  2. Injector clog combustion failure
  3. Oil leak lubrication failure
  4. Thermocouple sensor drift instrument fault
  5. Cooling duct ram-air blockage
  6. Machine-readable JSON streaming schema conformance
===============================================================================
"""

import os
import sys
import json
import socket
import unittest
from typing import Dict, Any, List, Optional

# Ensure project root is in sys.path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from plant_model.engine_plant import (
    AeroEnginePlant,
    FaultEvent,
    FaultManager,
    generate_mission_profile
)
from plant_model.physics_core import EngineSpecs
from can_bus.local_udp_transport import LocalUDPTransport
from can_bus.can_encoder import EngineCANEncoder
from can_bus.can_decoder import EngineCANDecoder
from can_bus.telemetry_event import TelemetryEvent
from digital_twin.runtime import DigitalTwinRuntime
from digital_twin.state import (
    DigitalTwinState,
    EngineHealthState,
    TelemetryQuality,
    RedlineStatus,
    ResidualStatus
)


def get_ephemeral_port() -> int:
    """Finds an available local port for isolated UDP socket testing."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class TestDigitalTwinEndToEnd(unittest.TestCase):
    """End-to-end integration tests traversing the complete hardware-free telemetry chain."""

    def run_pipeline(
        self,
        fault_type: str = "nominal",
        fault_severity: float = 0.5,
        fault_start_t: float = 1.0,
        fault_cylinder: int = 2,
        cycles: int = 25,
        seed: int = 42
    ) -> List[DigitalTwinState]:
        """Executes the full pipeline for N cycles and returns recorded DigitalTwinStates."""
        port = get_ephemeral_port()
        specs = EngineSpecs()
        plant = AeroEnginePlant(specs=specs, seed=seed)

        # Fault management
        events = []
        if fault_type == "injector_clog":
            events.append(FaultEvent(
                fault_type="injector_clog",
                start_time_sec=fault_start_t,
                duration_ramp_sec=1.0,
                target_cylinder=fault_cylinder,
                severity=fault_severity
            ))
        elif fault_type == "oil_leak":
            events.append(FaultEvent(
                fault_type="oil_leak",
                start_time_sec=fault_start_t,
                duration_ramp_sec=1.5,
                severity=fault_severity
            ))
        elif fault_type == "sensor_drift":
            events.append(FaultEvent(
                fault_type="sensor_drift",
                start_time_sec=fault_start_t,
                duration_ramp_sec=0.8,
                sensor_name="egt2",
                drift_rate=15.0,
                severity=fault_severity
            ))
        elif fault_type == "cooling_duct_blockage":
            events.append(FaultEvent(
                fault_type="cooling_duct_blockage",
                start_time_sec=fault_start_t,
                duration_ramp_sec=1.5,
                severity=fault_severity
            ))

        fault_mgr = FaultManager(faults=events)
        encoder = EngineCANEncoder()
        transport = LocalUDPTransport(port=port)
        decoder = EngineCANDecoder()
        runtime = DigitalTwinRuntime(specs=specs, ewma_alpha=0.05)

        # Generate realistic flight profile
        dt = 0.1
        profile = generate_mission_profile(
            phases=[{
                "name": "climb",
                "duration_sec": cycles * dt,
                "start_alt_m": 500.0,
                "end_alt_m": 500.0 + (cycles * dt * 10.0),
                "start_throttle_pct": 82.0,
                "end_throttle_pct": 84.0,
                "start_airspeed_mps": 38.0,
                "end_airspeed_mps": 42.0
            }],
            dt=dt
        )
        steps = profile.to_dict(orient="records")[:cycles]

        states: List[DigitalTwinState] = []

        try:
            for idx, step_data in enumerate(steps):
                sim_time = float(step_data["timestamp_sec"])
                th = float(step_data["throttle_pct"])
                alt = float(step_data["altitude_m"])
                ias = float(step_data["airspeed_mps"])

                # 1. Step Plant
                phys_faults = fault_mgr.get_physical_fault_state(sim_time)
                sensor_biases = fault_mgr.get_sensor_drift_bias(sim_time)
                true_state = plant.step(
                    dt=dt,
                    throttle_pct=th,
                    altitude_m=alt,
                    airspeed_mps=ias,
                    fault_phys_state=phys_faults
                )
                sensor_telem = plant.apply_sensors(true_state, sensor_drift_biases=sensor_biases)
                sensor_telem["throttle_pct"] = th
                sensor_telem["altitude_m"] = alt
                sensor_telem["airspeed_mps"] = ias

                # 2. Encode CAN Frames
                packets = encoder.encode_telemetry_cycle(sensor_telem, timestamp=sim_time)
                self.assertEqual(len(packets), 4, "Each cycle must produce exactly 4 CAN frames")

                # 3. Transmit via Localhost UDP
                for pkt in packets:
                    transport.send(pkt)

                # 4. Receive and Decode Frames
                decoded_cycle: Optional[Dict[str, Any]] = None
                for _ in range(len(packets)):
                    rx_bytes = transport.receive(timeout=1.0)
                    self.assertIsNotNone(rx_bytes, f"UDP packet receive timeout on cycle {idx}")
                    res = decoder.process_frame(rx_bytes)
                    if res is not None:
                        decoded_cycle = res

                self.assertIsNotNone(decoded_cycle, f"Failed to assemble 4-frame CAN cycle {idx}")
                decoded_cycle["cycle_id"] = idx

                # 5. Build TelemetryEvent
                telem_event = TelemetryEvent(
                    timestamp=sim_time,
                    sequence=decoded_cycle["sequence"],
                    cycle_id=idx,
                    rpm=decoded_cycle["rpm"],
                    throttle_pct=decoded_cycle["throttle_pct"],
                    fuel_flow_gps=decoded_cycle["fuel_flow_gps"],
                    egt1=decoded_cycle["egt1"],
                    egt2=decoded_cycle["egt2"],
                    egt3=decoded_cycle["egt3"],
                    egt4=decoded_cycle["egt4"],
                    cht1=decoded_cycle["cht1"],
                    cht2=decoded_cycle["cht2"],
                    cht3=decoded_cycle["cht3"],
                    cht4=decoded_cycle["cht4"],
                    oil_press_bar=decoded_cycle["oil_press_bar"],
                    oil_temp_c=decoded_cycle["oil_temp_c"],
                    airspeed_mps=decoded_cycle["airspeed_mps"],
                    altitude_m=decoded_cycle["altitude_m"]
                )
                self.assertIsNotNone(telem_event)

                # 6. Process through DigitalTwinRuntime
                dt_state = runtime.process(decoded_cycle, dt=dt)
                states.append(dt_state)

        finally:
            transport.close()

        return states

    def test_01_nominal_pipeline(self):
        """End-to-End Scenario 1: Nominal operation over live UDP transport."""
        states = self.run_pipeline(fault_type="nominal", cycles=20)
        self.assertEqual(len(states), 20)

        # Every frame must be valid and healthy
        for s in states:
            self.assertEqual(s.telemetry_status, TelemetryQuality.VALID)
            self.assertEqual(s.engine_state, EngineHealthState.HEALTHY)
            self.assertEqual(s.fault_type, "nominal")
            self.assertGreater(s.rul_hours, 120.0)
            self.assertGreaterEqual(s.health_score, 0.90)
            self.assertLess(s.processing_time_ms, 25.0, "Sub-25ms processing latency required")

    def test_02_injector_clog_pipeline(self):
        """End-to-End Scenario 2: Injector clog combustion fault over live UDP transport."""
        states = self.run_pipeline(
            fault_type="injector_clog",
            fault_severity=0.60,
            fault_start_t=0.5,
            fault_cylinder=2,
            cycles=40
        )
        self.assertEqual(len(states), 40)

        # Pre-fault (first 5 cycles) must be healthy
        self.assertEqual(states[0].engine_state, EngineHealthState.HEALTHY)

        # Post-fault must transition to DEGRADED and diagnose injector_clog
        final_state = states[-1]
        self.assertEqual(final_state.engine_state, EngineHealthState.DEGRADED)
        self.assertEqual(final_state.fault_type, "injector_clog")
        self.assertTrue(final_state.residual_status in ("CAUTION", "ALERT"))
        self.assertLess(final_state.rul_hours, 180.0)
        self.assertTrue(len(final_state.explanation.evidence) > 0)

    def test_03_oil_leak_pipeline(self):
        """End-to-End Scenario 3: Oil leak lubrication failure over live UDP transport."""
        states = self.run_pipeline(
            fault_type="oil_leak",
            fault_severity=0.75,
            fault_start_t=0.5,
            cycles=80
        )
        self.assertEqual(len(states), 80)

        # After thermal lag, oil leak should be classified
        later_states = states[45:]
        oil_detected = any(s.fault_type == "oil_leak" for s in later_states)
        self.assertTrue(oil_detected, "Oil leak must be detected in end-to-end pipeline")
        self.assertTrue(any(s.engine_state in (EngineHealthState.DEGRADED, EngineHealthState.CRITICAL) for s in later_states))

    def test_04_sensor_drift_pipeline(self):
        """End-to-End Scenario 4: EGT sensor drift over live UDP transport."""
        states = self.run_pipeline(
            fault_type="sensor_drift",
            fault_severity=0.60,
            fault_start_t=0.5,
            cycles=35
        )
        self.assertEqual(len(states), 35)

        later_states = states[20:]
        drift_detected = any(s.fault_type == "sensor_drift" for s in later_states)
        self.assertTrue(drift_detected, "Sensor drift must be diagnosed in end-to-end pipeline")

        # Health score must remain moderately high because powertrain is mechanically intact
        drift_states = [s for s in later_states if s.fault_type == "sensor_drift"]
        if drift_states:
            self.assertGreaterEqual(drift_states[-1].health_score, 0.75)

    def test_05_cooling_blockage_pipeline(self):
        """End-to-End Scenario 5: Cooling duct blockage over live UDP transport."""
        states = self.run_pipeline(
            fault_type="cooling_duct_blockage",
            fault_severity=0.60,
            fault_start_t=0.5,
            cycles=35
        )
        self.assertEqual(len(states), 35)
        # Verify pipeline safely completes all cycles without transport or runtime crash
        for s in states:
            self.assertIsNotNone(s.engine_state)
            self.assertIsNotNone(s.rul_hours)

    def test_06_json_schema_compliance(self):
        """End-to-End Scenario 6: Machine-readable JSON streaming format compliance."""
        states = self.run_pipeline(fault_type="nominal", cycles=5)
        for s in states:
            json_str = s.to_json()
            parsed = json.loads(json_str)

            # Check mandatory root fields from prompt specification
            required_keys = [
                "timestamp", "sequence_number", "engine_state", "fault_type",
                "fault_confidence", "rul_hours", "rul_q10_hours", "rul_q90_hours",
                "residual_status", "residual_magnitude", "early_warning",
                "redline_status", "health_score", "explanation", "telemetry",
                "physics", "predictions"
            ]
            for key in required_keys:
                self.assertIn(key, parsed, f"JSON missing required key: {key}")

            # Verify no NaN or Inf in JSON
            self.assertFalse("NaN" in json_str)
            self.assertFalse("Infinity" in json_str)


if __name__ == "__main__":
    unittest.main(verbosity=2)
