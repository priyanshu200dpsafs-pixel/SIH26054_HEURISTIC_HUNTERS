#!/usr/bin/env python3
"""
===============================================================================
PHASE 2: LIVE END-TO-END TELEMETRY ORCHESTRATOR
===============================================================================
SIH26054 — Explainable Digital Twin for MALE UAV Aero Piston Powerplant

Runs a live, deterministic, cross-platform telemetry pipeline connecting:
  1. Engine Plant (thermodynamics, rotor dynamics, sensor noise/drift)
  2. CAN Frame Encoder (validates signals, encodes DBC, wraps in 28-byte envelopes)
  3. Transport Layer (cross-platform localhost UDP IPC on 127.0.0.1:<port>)
  4. CAN Frame Decoder (validates envelope, CRC-8, sequence, DBC, 0x100 parity)
  5. Physics Observer (independent nominal analytic engine model)
  6. Residual Detector (raw & EWMA residuals, 3-sigma thresholds)
  7. Fault Discriminator (cross-channel coupling vs. isolated sensor drift)
  8. RUL Estimator (Random Forest Quantile Regressor on physics features)
  9. TelemetryEvent (structured diagnostic event output)

Usage:
  python run_mission_stream.py
  python run_mission_stream.py --duration 30 --rate 10
  python run_mission_stream.py --fault injector_clog --severity 0.35 --seed 42
  python run_mission_stream.py --fault sensor_drift --sensor egt1 --severity 0.40
  python run_mission_stream.py --fault oil_leak --severity 0.45
  python run_mission_stream.py --fault cooling_blockage --severity 0.40
  python run_mission_stream.py --json
===============================================================================
"""

import os
import sys
import time
import signal
import argparse
import warnings
from typing import Dict, Any, List, Optional
from pathlib import Path

# Suppress scikit-learn unpickling version notice
warnings.filterwarnings("ignore", category=UserWarning, module="sklearn")

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
sys.path.insert(0, str(SCRIPT_DIR / "plant_model"))
sys.path.insert(0, str(SCRIPT_DIR / "can_bus"))
sys.path.insert(0, str(SCRIPT_DIR / "ml_layer"))

from plant_model.engine_plant import (
    AeroEnginePlant,
    FaultEvent,
    FaultManager,
    generate_mission_profile,
)
from plant_model.physics_core import EngineSpecs
from can_bus.local_udp_transport import LocalUDPTransport
from can_bus.can_encoder import EngineCANEncoder
from can_bus.can_decoder import EngineCANDecoder
from can_bus.telemetry_event import TelemetryEvent
from can_bus.exceptions import (
    TelemetryPipelineError,
    TransportError,
    FrameValidationError,
    SequenceError,
    DecodeError,
    TelemetryValidationError,
    DiagnosticError,
)
from ml_layer.residual_detector import ResidualAnomalyDetector
from ml_layer.fault_discriminator import FaultDiscriminator
from ml_layer.rul_estimator import RULEstimator


class MissionStreamOrchestrator:
    """
    Coordinates the complete live end-to-end telemetry pipeline.
    """

    def __init__(
        self,
        duration_sec: float = 30.0,
        rate_hz: float = 10.0,
        fault_type: str = "nominal",
        fault_severity: float = 0.35,
        fault_cylinder: int = 3,
        fault_sensor: str = "egt1",
        fault_start_sec: float = 5.0,
        random_seed: int = 42,
        port: int = 5005,
        realtime: bool = True,
        json_output: bool = False,
        verbose: bool = False,
        quiet: bool = False,
    ):
        self.duration_sec = duration_sec
        self.rate_hz = rate_hz
        self.dt = 1.0 / rate_hz
        self.total_cycles = int(round(duration_sec * rate_hz))

        # Fault Configuration
        self.fault_type_raw = fault_type.lower().strip()
        self.fault_severity = fault_severity
        self.fault_cylinder = fault_cylinder
        self.fault_sensor = fault_sensor
        self.fault_start_sec = fault_start_sec
        self.random_seed = random_seed

        # Network & Output Configuration
        self.port = port
        self.realtime = realtime
        self.json_output = json_output
        self.verbose = verbose
        self.quiet = quiet

        # Lifecycle flags
        self.running = True
        self.interrupted = False

        # Component Initialization
        self.plant = AeroEnginePlant(seed=self.random_seed)
        self.fault_manager = self._init_fault_manager()
        self.encoder = EngineCANEncoder()
        self.transport: Optional[LocalUDPTransport] = None
        self.decoder = EngineCANDecoder(strict_sequence=True)
        self.detector = ResidualAnomalyDetector(ewma_alpha=0.05)
        self.discriminator = FaultDiscriminator()
        self.rul_estimator = RULEstimator()
        self.rul_estimator.load_model()

        # Telemetry history buffer for RUL derivative computation
        self.recent_history: List[Dict[str, Any]] = []

        # Diagnostics metrics
        self.last_reported_fault: Optional[str] = None
        self.total_frames_sent: int = 0
        self.total_frames_received: int = 0
        self.total_cycles_completed: int = 0

    def _init_fault_manager(self) -> FaultManager:
        """Instantiates FaultManager with the requested fault scenario."""
        ft = self.fault_type_raw

        # Normalize alias
        if ft in ("cooling_blockage", "cooling_duct_blockage", "cowl_blockage"):
            canonical_type = "cooling_duct_blockage"
        elif ft in ("injector_clog", "injector"):
            canonical_type = "injector_clog"
        elif ft in ("sensor_drift", "drift", "sensor"):
            canonical_type = "sensor_drift"
        elif ft in ("oil_leak", "leak"):
            canonical_type = "oil_leak"
        elif ft in ("nominal", "none", ""):
            canonical_type = "nominal"
        else:
            raise ValueError(
                f"Unknown fault type '{ft}'. Expected one of: nominal, injector_clog, sensor_drift, oil_leak, cooling_blockage"
            )

        fault_events: List[FaultEvent] = []
        if canonical_type != "nominal":
            if canonical_type == "sensor_drift":
                fault_events.append(
                    FaultEvent(
                        fault_type=canonical_type,
                        start_time_sec=self.fault_start_sec,
                        duration_ramp_sec=10.0,
                        sensor_name=self.fault_sensor,
                        severity=self.fault_severity,
                        drift_rate=1.2,
                    )
                )
            elif canonical_type == "injector_clog":
                fault_events.append(
                    FaultEvent(
                        fault_type=canonical_type,
                        start_time_sec=self.fault_start_sec,
                        duration_ramp_sec=12.0,
                        target_cylinder=self.fault_cylinder,
                        severity=self.fault_severity,
                    )
                )
            else:
                fault_events.append(
                    FaultEvent(
                        fault_type=canonical_type,
                        start_time_sec=self.fault_start_sec,
                        duration_ramp_sec=15.0,
                        severity=self.fault_severity,
                    )
                )

        return FaultManager(faults=fault_events)

    def _generate_flight_profile(self) -> List[Dict[str, float]]:
        """
        Generates realistic flight input profile for the mission duration.
        """
        if self.duration_sec <= 40.0:
            phases = [
                {
                    "name": "takeoff_climb",
                    "duration_sec": self.duration_sec,
                    "start_alt_m": 500.0,
                    "end_alt_m": 500.0 + self.duration_sec * 15.0,
                    "start_throttle_pct": 82.0,
                    "end_throttle_pct": 84.0,
                    "start_airspeed_mps": 38.0,
                    "end_airspeed_mps": 44.0,
                }
            ]
        else:
            climb_dur = min(60.0, self.duration_sec * 0.4)
            cruise_dur = self.duration_sec - climb_dur
            phases = [
                {
                    "name": "climb",
                    "duration_sec": climb_dur,
                    "start_alt_m": 200.0,
                    "end_alt_m": 2000.0,
                    "start_throttle_pct": 88.0,
                    "end_throttle_pct": 82.0,
                    "start_airspeed_mps": 35.0,
                    "end_airspeed_mps": 42.0,
                },
                {
                    "name": "patrol_cruise",
                    "duration_sec": cruise_dur,
                    "start_alt_m": 2000.0,
                    "end_alt_m": 2200.0,
                    "start_throttle_pct": 74.0,
                    "end_throttle_pct": 76.0,
                    "start_airspeed_mps": 42.0,
                    "end_airspeed_mps": 43.0,
                },
            ]

        df_prof = generate_mission_profile(phases=phases, dt=self.dt)
        return [row.to_dict() for _, row in df_prof.iterrows()]

    def handle_signal(self, signum, frame):
        """Clean shutdown on Ctrl+C or SIGTERM."""
        self.interrupted = True
        self.running = False

    def run(self) -> List[TelemetryEvent]:
        """
        Executes the complete telemetry pipeline for the configured mission.
        """
        # Register signal handlers
        signal.signal(signal.SIGINT, self.handle_signal)
        signal.signal(signal.SIGTERM, self.handle_signal)

        # Initialize UDP localhost transport
        self.transport = LocalUDPTransport(host="127.0.0.1", port=self.port, default_timeout=2.0)

        flight_steps = self._generate_flight_profile()
        total_steps = min(len(flight_steps), self.total_cycles)

        if not self.json_output and not self.quiet:
            print("=" * 80)
            print("SIH26054 — LIVE END-TO-END TELEMETRY ORCHESTRATOR (PHASE 2)")
            print("=" * 80)
            print(f"Transport  : Localhost UDP 127.0.0.1:{self.port} (Loopback IPC)")
            print(f"Mission    : {self.duration_sec:.1f}s @ {self.rate_hz:.1f} Hz ({total_steps} cycles = {total_steps*4} CAN frames)")
            print(f"Scenario   : FAULT='{self.fault_type_raw.upper()}' (sev={self.fault_severity:.2f}, start={self.fault_start_sec:.1f}s)")
            print(f"Random Seed: {self.random_seed} (Deterministic)")
            print(f"Rate Mode  : {'Real-Time Wall-Clock' if self.realtime else 'Fast Non-Blocking'}")
            print("-" * 80)

        events: List[TelemetryEvent] = []

        try:
            for cycle_idx in range(total_steps):
                if not self.running:
                    break

                step_start_time = time.perf_counter()
                f_input = flight_steps[cycle_idx]
                sim_time = float(f_input["timestamp_sec"])
                throttle = float(f_input["throttle_pct"])
                altitude = float(f_input["altitude_m"])
                airspeed = float(f_input["airspeed_mps"])

                # -------------------------------------------------------------
                # 1. ADVANCE ENGINE PLANT & GENERATE SENSOR STATE
                # -------------------------------------------------------------
                phys_fault_state = self.fault_manager.get_physical_fault_state(sim_time)
                sensor_drift_biases = self.fault_manager.get_sensor_drift_bias(sim_time)

                true_state = self.plant.step(
                    dt=self.dt,
                    throttle_pct=throttle,
                    altitude_m=altitude,
                    airspeed_mps=airspeed,
                    fault_phys_state=phys_fault_state,
                )

                sensor_telemetry = self.plant.apply_sensors(
                    true_state=true_state,
                    sensor_drift_biases=sensor_drift_biases,
                )
                sensor_telemetry["throttle_pct"] = throttle
                sensor_telemetry["altitude_m"] = altitude
                sensor_telemetry["airspeed_mps"] = airspeed

                # -------------------------------------------------------------
                # 2. CAN FRAME ENCODER (DBC + 28-Byte Simulation Wire Envelope)
                # -------------------------------------------------------------
                # Generates 4 envelopes: 0x100, 0x101, 0x102, 0x103
                can_packets = self.encoder.encode_telemetry_cycle(
                    telemetry=sensor_telemetry,
                    timestamp=sim_time,
                )

                # -------------------------------------------------------------
                # 3. TRANSPORT TRANSMISSION (Localhost UDP IPC)
                # -------------------------------------------------------------
                for pkt in can_packets:
                    self.transport.send(pkt)
                    self.total_frames_sent += 1

                # -------------------------------------------------------------
                # 4. TRANSPORT RECEPTION & CAN DECODER
                # -------------------------------------------------------------
                decoded_telemetry: Optional[Dict[str, Any]] = None
                for _ in range(len(can_packets)):
                    recv_bytes = self.transport.receive(timeout=1.0)
                    if recv_bytes is None:
                        raise TransportError(f"UDP frame receive timeout at sim_time={sim_time:.2f}s")
                    self.total_frames_received += 1

                    # Decoder validates envelope CRC-8, sequence, DBC, and 0x100 parity
                    res = self.decoder.process_frame(recv_bytes)
                    if res is not None:
                        decoded_telemetry = res

                if decoded_telemetry is None:
                    raise FrameValidationError(f"Incomplete CAN cycle received at sim_time={sim_time:.2f}s")

                # -------------------------------------------------------------
                # 5. PHYSICS OBSERVER & RESIDUAL DETECTOR
                # Consumes ONLY decoded telemetry from the transport. Zero shortcut!
                # -------------------------------------------------------------
                detector_out = self.detector.process_telemetry(
                    dt=self.dt,
                    telemetry=decoded_telemetry,
                )

                # -------------------------------------------------------------
                # 6. FAULT DISCRIMINATOR
                # -------------------------------------------------------------
                fault_info = self.discriminator.classify_anomaly(detector_out)

                # -------------------------------------------------------------
                # 7. RUL ESTIMATOR
                # -------------------------------------------------------------
                self.recent_history.append({
                    "timestamp_sec": sim_time,
                    "max_egt_residual": float(detector_out["max_egt_residual"]),
                })
                if len(self.recent_history) > 30:
                    self.recent_history.pop(0)

                feat_vec = self.rul_estimator.extract_features(
                    current_telemetry=decoded_telemetry,
                    detector_output=detector_out,
                    recent_history=self.recent_history,
                )
                rul_out = self.rul_estimator.predict(feat_vec)

                # -------------------------------------------------------------
                # 8. TELEMETRY EVENT MODEL
                # -------------------------------------------------------------
                event = TelemetryEvent(
                    timestamp=sim_time,
                    sequence=decoded_telemetry["sequence"],
                    cycle_id=cycle_idx,
                    rpm=decoded_telemetry["rpm"],
                    throttle_pct=decoded_telemetry["throttle_pct"],
                    fuel_flow_gps=decoded_telemetry["fuel_flow_gps"],
                    egt1=decoded_telemetry["egt1"],
                    egt2=decoded_telemetry["egt2"],
                    egt3=decoded_telemetry["egt3"],
                    egt4=decoded_telemetry["egt4"],
                    cht1=decoded_telemetry["cht1"],
                    cht2=decoded_telemetry["cht2"],
                    cht3=decoded_telemetry["cht3"],
                    cht4=decoded_telemetry["cht4"],
                    oil_press_bar=decoded_telemetry["oil_press_bar"],
                    oil_temp_c=decoded_telemetry["oil_temp_c"],
                    airspeed_mps=decoded_telemetry["airspeed_mps"],
                    altitude_m=decoded_telemetry["altitude_m"],
                    status_flags=decoded_telemetry.get("status_flags", 0),
                    rolling_counter=decoded_telemetry.get("rolling_counter", 0),
                    observer_values=detector_out["expected"],
                    residuals=detector_out["raw_residuals"],
                    ewma_residuals=detector_out["ewma_residuals"],
                    fault_status=detector_out["status"],
                    fault_classification=fault_info["classification"],
                    fault_subtype=fault_info["fault_subtype"],
                    fault_location=fault_info["fault_location"],
                    fault_confidence=fault_info["confidence"],
                    fault_justification=fault_info["justification"],
                    rul_hours=rul_out["rul_hours"],
                    rul_lower_hours=rul_out["rul_lower_hours"],
                    rul_upper_hours=rul_out["rul_upper_hours"],
                    rul_uncertainty_hours=rul_out["uncertainty_band_hours"],
                    transport_ok=True,
                    frame_ok=True,
                )

                events.append(event)
                self.total_cycles_completed += 1

                # -------------------------------------------------------------
                # 9. STRUCTURED OUTPUT EMISSION
                # -------------------------------------------------------------
                if self.json_output:
                    print(event.to_json())
                elif not self.quiet:
                    print(event.format_console_line())

                    # Announce new fault diagnosis transition
                    current_fault_key = f"{event.fault_classification}:{event.fault_subtype}"
                    if event.fault_status in ("CAUTION", "ALERT") and current_fault_key != self.last_reported_fault:
                        self.last_reported_fault = current_fault_key
                        print(
                            f"\n>>> [DIAGNOSTIC ADVISORY @ T={sim_time:5.1f}s] "
                            f"TYPE={event.fault_classification} | "
                            f"SUBTYPE={event.fault_subtype} | "
                            f"LOCATION={event.fault_location} | "
                            f"CONFIDENCE={event.fault_confidence*100:.1f}%\n"
                            f"    Justification: {event.fault_justification}\n"
                        )

                # -------------------------------------------------------------
                # 10. MONOTONIC RATE PACING (if realtime enabled)
                # -------------------------------------------------------------
                if self.realtime:
                    elapsed = time.perf_counter() - step_start_time
                    sleep_duration = self.dt - elapsed
                    if sleep_duration > 0:
                        time.sleep(sleep_duration)

        except (KeyboardInterrupt, SystemExit):
            self.interrupted = True
        except TelemetryPipelineError as e:
            print(f"\n[PIPELINE ERROR] {type(e).__name__}: {e}", file=sys.stderr)
            raise
        finally:
            self._cleanup()

        return events

    def _cleanup(self):
        """Releases transport socket and prints completion banner."""
        if self.transport:
            self.transport.close()

        if not self.json_output and not self.quiet:
            print("-" * 80)
            if self.interrupted:
                print(">>> Mission interrupted by user (Ctrl+C). Clean shutdown complete.")
            else:
                print(">>> Mission simulation completed successfully.")
            print(f"Summary: {self.total_cycles_completed} cycles completed | {self.total_frames_sent} CAN frames transmitted & decoded.")
            print("=" * 80)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="SIH26054 — Explainable Digital Twin Telemetry Orchestrator (Phase 2)",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--duration", type=float, default=30.0, help="Mission duration in seconds")
    parser.add_argument("--rate", type=float, default=10.0, help="Simulation rate in Hz (default 10 Hz)")
    parser.add_argument(
        "--fault",
        type=str,
        default="nominal",
        choices=["nominal", "injector_clog", "sensor_drift", "oil_leak", "cooling_blockage", "cooling_duct_blockage"],
        help="Injected fault scenario",
    )
    parser.add_argument("--severity", type=float, default=0.35, help="Fault severity (0.0 to 1.0)")
    parser.add_argument("--cylinder", type=int, default=3, choices=[1, 2, 3, 4], help="Target cylinder for cylinder faults")
    parser.add_argument("--sensor", type=str, default="egt1", help="Target sensor for sensor drift faults")
    parser.add_argument("--start-time", type=float, default=5.0, help="Inception time of the fault in seconds")
    parser.add_argument("--seed", type=int, default=42, help="Deterministic random seed")
    parser.add_argument("--port", type=int, default=5005, help="Localhost UDP transport port")
    parser.add_argument("--fast", "--no-realtime", dest="realtime", action="store_false", help="Run at maximum CPU speed without real-time delays")
    parser.add_argument("--json", action="store_true", help="Output machine-readable JSON per timestep")
    parser.add_argument("--verbose", action="store_true", help="Enable verbose logging")
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    orchestrator = MissionStreamOrchestrator(
        duration_sec=args.duration,
        rate_hz=args.rate,
        fault_type=args.fault,
        fault_severity=args.severity,
        fault_cylinder=args.cylinder,
        fault_sensor=args.sensor,
        fault_start_sec=args.start_time,
        random_seed=args.seed,
        port=args.port,
        realtime=args.realtime,
        json_output=args.json,
        verbose=args.verbose,
    )
    orchestrator.run()
