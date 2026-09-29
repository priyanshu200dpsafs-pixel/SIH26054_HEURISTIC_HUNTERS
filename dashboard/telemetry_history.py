#!/usr/bin/env python3
"""
===============================================================================
AERO PISTON ENGINE DIGITAL TWIN: TELEMETRY HISTORY BUFFER (PHASE 4)
===============================================================================
Thread-safe, strictly bounded rolling ring-buffer for time-series charts and
deterministic mission timeline milestone detection.

MEMORY SAFETY:
  - Bounded to `max_history_points` (default 300 cycles @ 10 Hz = 30 seconds).
  - Automatically drops oldest frames when full to guarantee constant memory.
===============================================================================
"""

from collections import deque
from typing import Dict, Any, List, Optional
import pandas as pd

from digital_twin.state import DigitalTwinState


class TelemetryHistoryBuffer:
    """
    Maintains a fixed-size sliding window of telemetry, physics, and ML states
    for real-time time-series rendering and mission event logging.
    """

    def __init__(self, max_history_points: int = 300):
        self.max_history_points = max(50, int(max_history_points))
        self.buffer: deque = deque(maxlen=self.max_history_points)
        self.timeline_events: List[Dict[str, Any]] = []

        # State transition tracking
        self.last_engine_state: Optional[str] = None
        self.last_fault_type: str = "nominal"
        self.last_residual_status: str = "NORMAL"
        self.last_redline_status: str = "NORMAL"
        self.first_anomaly_time: Optional[float] = None
        self.first_fault_time: Optional[float] = None

    def clear(self):
        """Clears all history and resets timeline events."""
        self.buffer.clear()
        self.timeline_events.clear()
        self.last_engine_state = None
        self.last_fault_type = "nominal"
        self.last_residual_status = "NORMAL"
        self.last_redline_status = "NORMAL"
        self.first_anomaly_time = None
        self.first_fault_time = None

    def add(self, state: DigitalTwinState):
        """Appends a new DigitalTwinState record and evaluates milestone events."""
        t = float(state.timestamp)
        seq = int(state.sequence_number)
        eng_state = state.engine_state.value if hasattr(state.engine_state, "value") else str(state.engine_state)
        res_stat = state.residual_status.value if hasattr(state.residual_status, "value") else str(state.residual_status)
        redline_stat = state.redline_status.value if hasattr(state.redline_status, "value") else str(state.redline_status)
        fault = str(state.fault_type)

        # 1. Detect timeline events
        if len(self.buffer) == 0:
            self._log_event(t, "MISSION_START", "Simulation telemetry streaming initialized.")

        # Anomaly detection event
        if res_stat in ("CAUTION", "ALERT", "ANOMALY") and self.first_anomaly_time is None:
            self.first_anomaly_time = t
            self._log_event(t, "RESIDUAL_ANOMALY", f"Physics observer residual crossed 3-sigma threshold ({res_stat}).")

        # Engine state transition event
        if self.last_engine_state is not None and eng_state != self.last_engine_state:
            self._log_event(
                t,
                "STATE_TRANSITION",
                f"Operational health state transitioned: {self.last_engine_state} → {eng_state}."
            )

        # Fault classification event
        if fault != "nominal" and fault != self.last_fault_type:
            if self.first_fault_time is None:
                self.first_fault_time = t
            self._log_event(
                t,
                "FAULT_CLASSIFIED",
                f"Multivariate physics coupling confirmed: {fault.upper().replace('_', ' ')}."
            )

        # Redline breach event
        if redline_stat in ("ALERT", "REDLINE") and self.last_redline_status != redline_stat:
            details_str = ", ".join(f"{k}: {v}" for k, v in (state.redline_details or {}).items())
            self._log_event(
                t,
                "REDLINE_BREACH",
                f"Physical operating boundary {redline_stat}: {details_str or 'Threshold reached'}."
            )

        self.last_engine_state = eng_state
        self.last_fault_type = fault
        self.last_residual_status = res_stat
        self.last_redline_status = redline_stat

        # 2. Extract chart datapoint
        telem = state.telemetry
        physics = state.physics
        preds = state.predictions

        point = {
            "timestamp": t,
            "sequence": seq,
            "rpm": telem.rpm,
            "throttle_pct": telem.throttle_pct,
            "fuel_flow_gps": telem.fuel_flow_gps,
            "max_egt": telem.max_egt,
            "egt1": telem.egt1,
            "egt2": telem.egt2,
            "egt3": telem.egt3,
            "egt4": telem.egt4,
            "max_cht": telem.max_cht,
            "cht1": telem.cht1,
            "cht2": telem.cht2,
            "cht3": telem.cht3,
            "cht4": telem.cht4,
            "oil_press_bar": telem.oil_press_bar,
            "oil_temp_c": telem.oil_temp_c,
            "airspeed_mps": telem.airspeed_mps,
            "altitude_m": telem.altitude_m,
            "rul_hours": state.rul_hours,
            "rul_q10": state.rul_q10_hours,
            "rul_q90": state.rul_q90_hours,
            "health_score": state.health_score,
            "health_index": round(state.health_score * 100, 1) if state.health_score is not None else None,
            "max_egt_residual": physics.max_egt_residual,
            "max_cht_residual": physics.max_cht_residual,
            "oil_press_residual": abs(physics.signed_residuals.get("oil_press_bar", 0.0)),
            "oil_temp_residual": abs(physics.signed_residuals.get("oil_temp_c", 0.0)),
            "rpm_residual": abs(physics.signed_residuals.get("rpm", 0.0)),
            "residual_magnitude": state.residual_magnitude,
            "engine_state": eng_state,
            "fault_type": fault,
            "processing_time_ms": state.processing_time_ms
        }
        self.buffer.append(point)

    def _log_event(self, timestamp: float, event_type: str, description: str):
        """Records a timestamped event into the timeline."""
        self.timeline_events.append({
            "timestamp": timestamp,
            "time_str": f"{int(timestamp // 60):02d}:{timestamp % 60:04.1f}",
            "type": event_type,
            "description": description
        })

    def to_dataframe(self) -> pd.DataFrame:
        """Converts buffer points to a pandas DataFrame for charting."""
        if not self.buffer:
            return pd.DataFrame()
        return pd.DataFrame(list(self.buffer))

    def get_timeline_events(self) -> List[Dict[str, Any]]:
        """Returns the list of detected mission milestone events."""
        return list(self.timeline_events)

    def __len__(self) -> int:
        return len(self.buffer)
