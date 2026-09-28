#!/usr/bin/env python3
"""
===============================================================================
AERO PISTON ENGINE DIGITAL TWIN: REAL-TIME STREAM EXECUTABLE (PHASE 3B)
===============================================================================
Connects the live telemetry pipeline:
  Engine Plant (Physics simulation + Fault injection)
    ↓
  CAN Encoder (DBC packing + 28-byte wire envelope)
    ↓
  Localhost UDP Transport (Cross-platform simulation bus)
    ↓
  CAN Decoder (Frame integrity validation + signal decode)
    ↓
  DigitalTwinRuntime (Physics observer, residuals, fault isolation, stateless RUL)
    ↓
  Unified DigitalTwinState (Terminal display / JSON streaming)

Usage:
  python run_digital_twin.py --duration 30 --rate 10 --seed 42
  python run_digital_twin.py --fault injector_clog --severity 0.6 --duration 30 --seed 42
  python run_digital_twin.py --fault oil_leak --severity 0.5 --duration 20 --json
===============================================================================
"""

import os
import sys
import time
import signal
import argparse
from typing import Dict, Any, List, Optional, Tuple

# Ensure project root is in sys.path
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from plant_model.engine_plant import (
    EngineSpecs,
    AeroEnginePlant,
    FaultEvent,
    FaultManager,
    generate_mission_profile
)
from can_bus.local_udp_transport import LocalUDPTransport
from can_bus.can_encoder import EngineCANEncoder
from can_bus.can_decoder import EngineCANDecoder
from digital_twin.runtime import DigitalTwinRuntime
from digital_twin.state import DigitalTwinState, EngineHealthState


class DigitalTwinStreamOrchestrator:
    """
    Main runtime orchestrator connecting plant simulation, CAN transport,
    decoding, and real-time DigitalTwinRuntime execution.
    """

    def __init__(
        self,
        fault_type: str = "nominal",
        fault_severity: float = 0.5,
        fault_start_t: float = 10.0,
        fault_cylinder: int = 2,
        duration_sec: float = 30.0,
        rate_hz: float = 10.0,
        random_seed: int = 42,
        port: int = 5555,
        fast_mode: bool = False,
        verbose: bool = False,
        json_output: bool = False
    ):
        self.duration_sec = duration_sec
        self.rate_hz = rate_hz
        self.dt = 1.0 / rate_hz
        self.random_seed = random_seed
        self.fast_mode = fast_mode
        self.verbose = verbose
        self.json_output = json_output
        self.interrupted = False

        # Initialize Plant & Faults
        self.specs = EngineSpecs()
        self.plant = AeroEnginePlant(specs=self.specs, seed=random_seed)
        self.fault_manager = self._setup_faults(
            fault_type=fault_type,
            severity=fault_severity,
            start_t=fault_start_t,
            cylinder=fault_cylinder
        )

        # Initialize CAN Layer
        self.encoder = EngineCANEncoder()
        self.decoder = EngineCANDecoder()
        self.transport = LocalUDPTransport(port=port)

        # Initialize Digital Twin Runtime Engine
        self.runtime = DigitalTwinRuntime(specs=self.specs, ewma_alpha=0.05)

    def _setup_faults(
        self,
        fault_type: str,
        severity: float,
        start_t: float,
        cylinder: int
    ) -> FaultManager:
        fault_events = []
        ft = fault_type.lower().strip()
        if ft in ("cooling_blockage", "cooling_duct_blockage", "cowl_blockage"):
            ft = "cooling_duct_blockage"
        elif ft in ("injector_clog", "injector"):
            ft = "injector_clog"
        elif ft in ("sensor_drift", "drift", "sensor"):
            ft = "sensor_drift"
        elif ft in ("oil_leak", "leak"):
            ft = "oil_leak"

        if ft == "injector_clog":
            fault_events.append(FaultEvent(
                fault_type="injector_clog",
                start_time_sec=start_t,
                duration_ramp_sec=8.0,
                target_cylinder=cylinder,
                severity=severity
            ))
        elif ft == "oil_leak":
            fault_events.append(FaultEvent(
                fault_type="oil_leak",
                start_time_sec=start_t,
                duration_ramp_sec=10.0,
                severity=severity
            ))
        elif ft == "cooling_duct_blockage":
            fault_events.append(FaultEvent(
                fault_type="cooling_duct_blockage",
                start_time_sec=start_t,
                duration_ramp_sec=12.0,
                severity=severity
            ))
        elif ft == "sensor_drift":
            fault_events.append(FaultEvent(
                fault_type="sensor_drift",
                start_time_sec=start_t,
                duration_ramp_sec=5.0,
                sensor_name="egt2",
                drift_rate=0.8,
                severity=severity
            ))
        return FaultManager(faults=fault_events)

    def _generate_flight_profile(self) -> List[Dict[str, float]]:
        """Generates dynamic throttle and altitude profiles for the flight."""
        if self.duration_sec <= 20.0:
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
            climb_dur = min(40.0, self.duration_sec * 0.4)
            cruise_dur = self.duration_sec - climb_dur
            phases = [
                {
                    "name": "climb",
                    "duration_sec": climb_dur,
                    "start_alt_m": 500.0,
                    "end_alt_m": 2200.0,
                    "start_throttle_pct": 88.0,
                    "end_throttle_pct": 82.0,
                    "start_airspeed_mps": 36.0,
                    "end_airspeed_mps": 42.0,
                },
                {
                    "name": "patrol_cruise",
                    "duration_sec": cruise_dur,
                    "start_alt_m": 2200.0,
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
        """Clean shutdown handler."""
        self.interrupted = True

    def run(self) -> List[DigitalTwinState]:
        """Executes the live telemetry mission streaming and runtime analysis."""
        signal.signal(signal.SIGINT, self.handle_signal)
        signal.signal(signal.SIGTERM, self.handle_signal)

        profile = self._generate_flight_profile()
        total_steps = len(profile)

        if not self.json_output:
            print("\n" + "=" * 75)
            print("DIGITAL TWIN REAL-TIME TELEMETRY RUNTIME INTEGRATION (PHASE 3B)")
            print("=" * 75)
            print(f"Mission Duration:    {self.duration_sec:.1f} s ({total_steps} cycles @ {self.rate_hz} Hz)")
            print(f"Engine Type:         {self.specs.engine_name}")
            print(f"Injected Fault:      {self.fault_manager.faults[0].fault_type.upper() if self.fault_manager.faults else 'NOMINAL'}")
            print(f"CAN Transport:       Localhost UDP (127.0.0.1:{self.transport.bound_port})")
            print("=" * 75 + "\n")

        states: List[DigitalTwinState] = []
        cycle_idx = 0

        try:
            for step_data in profile:
                if self.interrupted:
                    break

                t_cycle_start = time.perf_counter()
                sim_time = step_data["timestamp_sec"]
                throttle = step_data["throttle_pct"]
                altitude = step_data["altitude_m"]
                airspeed = step_data["airspeed_mps"]

                # 1. Step Engine Plant Simulation
                phys_fault_state = self.fault_manager.get_physical_fault_state(sim_time)
                sensor_biases = self.fault_manager.get_sensor_drift_bias(sim_time)
                true_state = self.plant.step(
                    dt=self.dt,
                    throttle_pct=throttle,
                    altitude_m=altitude,
                    airspeed_mps=airspeed,
                    fault_phys_state=phys_fault_state
                )
                sensor_telemetry = self.plant.apply_sensors(
                    true_state=true_state,
                    sensor_drift_biases=sensor_biases
                )
                sensor_telemetry["throttle_pct"] = throttle
                sensor_telemetry["altitude_m"] = altitude
                sensor_telemetry["airspeed_mps"] = airspeed

                # 2. CAN Frame Encoding (DBC + 28-Byte Wire Envelopes)
                can_packets = self.encoder.encode_telemetry_cycle(
                    telemetry=sensor_telemetry,
                    timestamp=sim_time
                )

                # 3. Transport Transmission (Localhost UDP Bus)
                for pkt in can_packets:
                    self.transport.send(pkt)

                # 4. Transport Reception & CAN Decoding
                decoded_telemetry: Optional[Dict[str, Any]] = None
                for _ in range(len(can_packets)):
                    recv_bytes = self.transport.receive(timeout=1.0)
                    if recv_bytes is not None:
                        res = self.decoder.process_frame(recv_bytes)
                        if res is not None:
                            decoded_telemetry = res

                if decoded_telemetry is None:
                    continue

                # 5. Process through DigitalTwinRuntime
                dt_state = self.runtime.process(
                    telemetry=decoded_telemetry,
                    dt=self.dt
                )
                states.append(dt_state)
                cycle_idx += 1

                # 6. Stream Output
                if self.json_output:
                    print(dt_state.to_json(), flush=True)
                elif self.verbose:
                    print(dt_state.format_terminal_card(), flush=True)
                    print("-" * 75, flush=True)
                else:
                    print(dt_state.format_console_line(), flush=True)

                # 7. Real-time rate throttling (unless --fast is passed)
                if not self.fast_mode:
                    elapsed = time.perf_counter() - t_cycle_start
                    sleep_time = self.dt - elapsed
                    if sleep_time > 0:
                        time.sleep(sleep_time)

        finally:
            self.transport.close()

        if not self.json_output:
            print("\n" + self.runtime.format_mission_summary() + "\n")

        return states


def main():
    parser = argparse.ArgumentParser(
        description="Aero Piston Engine Explainable Digital Twin Real-Time Stream (Phase 3B)",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )
    parser.add_argument("--fault", type=str, default="nominal",
                        choices=["nominal", "injector_clog", "oil_leak", "cooling_duct_blockage", "cooling_blockage", "sensor_drift"],
                        help="Fault type to inject during mission")
    parser.add_argument("--severity", type=float, default=0.5,
                        help="Fault severity fraction (0.0 to 1.0)")
    parser.add_argument("--fault-start", type=float, default=10.0,
                        help="Time in seconds when fault initiates")
    parser.add_argument("--cylinder", type=int, default=2, choices=[1, 2, 3, 4],
                        help="Target cylinder for cylinder-specific faults")
    parser.add_argument("--duration", type=float, default=30.0,
                        help="Total mission flight duration in seconds")
    parser.add_argument("--rate", type=float, default=10.0,
                        help="Telemetry streaming frequency in Hz")
    parser.add_argument("--seed", type=int, default=42,
                        help="Deterministic random seed for simulation")
    parser.add_argument("--port", type=int, default=5555,
                        help="Localhost UDP IPC socket port")
    parser.add_argument("--fast", action="store_true",
                        help="Run at full CPU speed without real-time sleep")
    parser.add_argument("--verbose", action="store_true",
                        help="Print comprehensive multi-line terminal cards with evidence")
    parser.add_argument("--json", action="store_true",
                        help="Emit machine-readable JSON lines for streaming consumers")

    args = parser.parse_args()

    orchestrator = DigitalTwinStreamOrchestrator(
        fault_type=args.fault,
        fault_severity=args.severity,
        fault_start_t=args.fault_start,
        fault_cylinder=args.cylinder,
        duration_sec=args.duration,
        rate_hz=args.rate,
        random_seed=args.seed,
        port=args.port,
        fast_mode=args.fast,
        verbose=args.verbose,
        json_output=args.json
    )

    orchestrator.run()


if __name__ == "__main__":
    main()
