"""
===============================================================================
AERO PISTON ENGINE DIGITAL TWIN: TELEMETRY EVENT MODEL
===============================================================================
Represents a single unified, end-to-end diagnostic timestep produced by the
telemetry pipeline:
  Plant -> CAN Encoder -> Transport -> CAN Decoder -> Integrity Check
  -> Physics Observer -> Residual Detector -> Fault Discriminator -> RUL Estimator
===============================================================================
"""

import json
from dataclasses import dataclass, field, asdict
from typing import Dict, Any, Optional


@dataclass
class TelemetryEvent:
    """
    Structured representation of a complete diagnostic timestep.
    """
    # Timing and Sequence
    timestamp: float
    sequence: int
    cycle_id: int

    # Decoded Flight & Engine Telemetry (from CAN frames)
    rpm: float
    throttle_pct: float
    fuel_flow_gps: float
    egt1: float
    egt2: float
    egt3: float
    egt4: float
    cht1: float
    cht2: float
    cht3: float
    cht4: float
    oil_press_bar: float
    oil_temp_c: float
    airspeed_mps: float
    altitude_m: float
    status_flags: int = 0
    rolling_counter: int = 0

    # Physics Observer Expected Values
    observer_values: Dict[str, float] = field(default_factory=dict)

    # Physics Residuals (Raw and Filtered)
    residuals: Dict[str, float] = field(default_factory=dict)
    ewma_residuals: Dict[str, float] = field(default_factory=dict)

    # Fault Isolation & Discrimination
    fault_status: str = "NORMAL"                                # 'NORMAL', 'CAUTION', 'ALERT'
    fault_classification: Optional[str] = "NOMINAL"             # 'NOMINAL', 'SENSOR_FAULT', 'PLANT_FAULT'
    fault_subtype: Optional[str] = "NONE"                       # 'NONE', 'INJECTOR_CLOG', 'SENSOR_DRIFT', 'OIL_LEAK', etc.
    fault_location: Optional[str] = "NONE"                      # 'CYLINDER_1'..'4', 'EGT_SENSOR_1'..'4', 'OIL_SYSTEM'
    fault_confidence: Optional[float] = 1.0                     # 0.0 to 1.0
    fault_justification: Optional[str] = None

    # Remaining Useful Life (RUL)
    rul_hours: Optional[float] = None
    rul_lower_hours: Optional[float] = None
    rul_upper_hours: Optional[float] = None
    rul_uncertainty_hours: Optional[float] = None

    # Pipeline Verification Flags
    transport_ok: bool = True
    frame_ok: bool = True
    error_message: Optional[str] = None

    @property
    def max_egt(self) -> float:
        return max(self.egt1, self.egt2, self.egt3, self.egt4)

    @property
    def max_cht(self) -> float:
        return max(self.cht1, self.cht2, self.cht3, self.cht4)

    def to_dict(self) -> Dict[str, Any]:
        """Converts the TelemetryEvent to a serializable dictionary."""
        return asdict(self)

    def to_json(self, indent: Optional[int] = None) -> str:
        """Serializes the TelemetryEvent to a JSON string."""
        return json.dumps(self.to_dict(), indent=indent)

    def format_console_line(self) -> str:
        """
        Formats a compact, readable, single-line telemetry string for console output.
        Example:
          [000042] T=4.2s RPM=5201 EGT3=732.5 CHT=164.2 OIL_P=2.45 STATUS=NORMAL RUL=200.0h
        """
        rul_str = f"{self.rul_hours:.1f}h" if self.rul_hours is not None else "N/A"
        
        diag_str = self.fault_status
        if self.fault_subtype and self.fault_subtype != "NONE":
            diag_str = f"{self.fault_status}:{self.fault_subtype}"

        return (
            f"[{self.cycle_id:06d}] "
            f"T={self.timestamp:6.1f}s | "
            f"RPM={self.rpm:4.0f} | "
            f"TH={self.throttle_pct:4.1f}% | "
            f"EGTmax={self.max_egt:5.1f}°C | "
            f"CHTmax={self.max_cht:5.1f}°C | "
            f"OIL={self.oil_press_bar:4.2f}b/{self.oil_temp_c:4.1f}°C | "
            f"STATUS={diag_str:18s} | "
            f"RUL={rul_str}"
        )
