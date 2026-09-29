#!/usr/bin/env python3
"""
===============================================================================
AERO PISTON ENGINE DIGITAL TWIN: LIVE MISSION CONTROLLER (PHASE 4)
===============================================================================
Manages live simulation streaming for the dashboard strictly through the
authentic CAN/UDP telemetry transport pipeline.

STRICT ARCHITECTURAL INTEGRITY:
  Dashboard
      ↓
  LiveMissionController
      ↓
  AeroEnginePlant
      ↓
  EngineCANEncoder (28-byte wire envelopes)
      ↓
  LocalUDPTransport (127.0.0.1 UDP IPC)
      ↓
  EngineCANDecoder (CRC-8, sequence continuity, DBC unpack)
      ↓
  TelemetryEvent
      ↓
  DigitalTwinRuntime
      ↓
  DigitalTwinState
===============================================================================
"""

import os
import sys
import socket
from typing import Dict, Any, List, Optional

# Ensure project root is in sys.path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
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
from digital_twin.state import DigitalTwinState


def get_ephemeral_port() -> int:
    """Finds an available local port for isolated UDP socket streaming."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class LiveMissionController:
    """
    Controls live simulation execution, fault injection parameters,
    and step-by-step telemetry advancement over localhost UDP transport.
    """

    def __init__(
        self,
        fault_type: str = "nominal",
        fault_severity: float = 0.5,
        fault_start_t: Optional[float] = None,
        fault_cylinder: int = 2,
        duration_sec: float = 30.0,
        rate_hz: float = 10.0,
        random_seed: int = 42,
        port: Optional[int] = None
    ):
        self.fault_type = fault_type
        self.fault_severity = fault_severity
        self.fault_start_t = fault_start_t if fault_start_t is not None else min(2.0, duration_sec * 0.2)
        self.fault_cylinder = fault_cylinder
        self.duration_sec = duration_sec
        self.rate_hz = rate_hz
        self.dt = 1.0 / rate_hz
        self.random_seed = random_seed
        self.port = port or get_ephemeral_port()

        # Pipeline components
        self.specs = EngineSpecs()
        self.plant: Optional[AeroEnginePlant] = None
        self.fault_manager: Optional[FaultManager] = None
        self.encoder: Optional[EngineCANEncoder] = None
        self.transport: Optional[LocalUDPTransport] = None
        self.decoder: Optional[EngineCANDecoder] = None
        self.runtime: Optional[DigitalTwinRuntime] = None

        # Simulation execution state
        self.profile: List[Dict[str, float]] = []
        self.current_step_idx: int = 0
        self.is_active: bool = False
        self.is_finished: bool = False
        self.latest_state: Optional[DigitalTwinState] = None

        self._initialize_pipeline()

    def _setup_faults(self) -> FaultManager:
        """Constructs FaultEvent matching plant model specifications."""
        fault_events = []
        ft = self.fault_type.lower().strip()
        if ft in ("cooling_blockage", "cooling_duct_blockage", "cowl_blockage"):
            ft = "cooling_duct_blockage"
        elif ft in ("injector_clog", "injector"):
            ft = "injector_clog"
        elif ft in ("sensor_drift", "drift", "sensor"):
            ft = "sensor_drift"
        elif ft in ("oil_leak", "leak"):
            ft = "oil_leak"

        ramp_sec = min(1.5, self.duration_sec * 0.15)

        if ft == "injector_clog":
            fault_events.append(FaultEvent(
                fault_type="injector_clog",
                start_time_sec=self.fault_start_t,
                duration_ramp_sec=ramp_sec,
                target_cylinder=self.fault_cylinder,
                severity=self.fault_severity
            ))
        elif ft == "oil_leak":
            fault_events.append(FaultEvent(
                fault_type="oil_leak",
                start_time_sec=self.fault_start_t,
                duration_ramp_sec=ramp_sec,
                severity=self.fault_severity
            ))
        elif ft == "cooling_duct_blockage":
            fault_events.append(FaultEvent(
                fault_type="cooling_duct_blockage",
                start_time_sec=self.fault_start_t,
                duration_ramp_sec=ramp_sec,
                severity=self.fault_severity
            ))
        elif ft == "sensor_drift":
            fault_events.append(FaultEvent(
                fault_type="sensor_drift",
                start_time_sec=self.fault_start_t,
                duration_ramp_sec=ramp_sec,
                sensor_name="egt2",
                drift_rate=15.0,
                severity=self.fault_severity
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

    def _initialize_pipeline(self):
        """Initializes all physical and transport layers."""
        self.plant = AeroEnginePlant(specs=self.specs, seed=self.random_seed)
        self.fault_manager = self._setup_faults()
        self.encoder = EngineCANEncoder()
        self.decoder = EngineCANDecoder()
        self.transport = LocalUDPTransport(port=self.port)
        self.runtime = DigitalTwinRuntime(specs=self.specs, ewma_alpha=0.05)
        self.profile = self._generate_flight_profile()
        self.current_step_idx = 0
        self.is_finished = False

    def reset(
        self,
        fault_type: Optional[str] = None,
        fault_severity: Optional[float] = None,
        fault_start_t: Optional[float] = None,
        duration_sec: Optional[float] = None,
        rate_hz: Optional[float] = None,
        seed: Optional[int] = None
    ):
        """Resets and reconfigures simulation pipeline."""
        if fault_type is not None:
            self.fault_type = fault_type
        if fault_severity is not None:
            self.fault_severity = fault_severity
        if duration_sec is not None:
            self.duration_sec = duration_sec
        if rate_hz is not None:
            self.rate_hz = rate_hz
            self.dt = 1.0 / rate_hz
        if fault_start_t is not None:
            self.fault_start_t = fault_start_t
        else:
            self.fault_start_t = min(2.0, self.duration_sec * 0.2)
        if seed is not None:
            self.random_seed = seed

        self.close()
        self.port = get_ephemeral_port()
        self._initialize_pipeline()
        self.latest_state = None

    def step(self) -> Optional[DigitalTwinState]:
        """
        Executes one discrete simulation step through the entire authentic pipeline:
        Plant -> CAN Encoder -> UDP Socket -> CAN Decoder -> DigitalTwinRuntime -> DigitalTwinState.
        """
        if self.current_step_idx >= len(self.profile):
            self.is_finished = True
            return self.latest_state

        step_data = self.profile[self.current_step_idx]
        sim_time = float(step_data["timestamp_sec"])
        throttle = float(step_data["throttle_pct"])
        altitude = float(step_data["altitude_m"])
        airspeed = float(step_data["airspeed_mps"])

        # 1. Step Plant Simulation
        phys_faults = self.fault_manager.get_physical_fault_state(sim_time)
        sensor_biases = self.fault_manager.get_sensor_drift_bias(sim_time)
        true_state = self.plant.step(
            dt=self.dt,
            throttle_pct=throttle,
            altitude_m=altitude,
            airspeed_mps=airspeed,
            fault_phys_state=phys_faults
        )
        sensor_telem = self.plant.apply_sensors(true_state, sensor_drift_biases=sensor_biases)
        sensor_telem["throttle_pct"] = throttle
        sensor_telem["altitude_m"] = altitude
        sensor_telem["airspeed_mps"] = airspeed

        # 2. CAN Frame Encoding (DBC + 28-Byte Wire Envelopes)
        can_packets = self.encoder.encode_telemetry_cycle(sensor_telem, timestamp=sim_time)

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
            self.current_step_idx += 1
            return self.latest_state

        # 5. Process through DigitalTwinRuntime
        dt_state = self.runtime.process(telemetry=decoded_telemetry, dt=self.dt)
        self.latest_state = dt_state
        self.current_step_idx += 1

        if self.current_step_idx >= len(self.profile):
            self.is_finished = True

        return dt_state

    @property
    def progress_fraction(self) -> float:
        """Returns the mission progress fraction [0.0, 1.0]."""
        if not self.profile:
            return 0.0
        return min(1.0, float(self.current_step_idx) / float(len(self.profile)))

    @property
    def current_time_sec(self) -> float:
        """Current elapsed simulation time in seconds."""
        if self.latest_state:
            return self.latest_state.timestamp
        return float(self.current_step_idx) * self.dt

    def close(self):
        """Closes the UDP IPC transport cleanly."""
        if self.transport is not None:
            try:
                self.transport.close()
            except Exception:
                pass
