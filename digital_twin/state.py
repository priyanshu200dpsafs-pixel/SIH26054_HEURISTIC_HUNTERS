#!/usr/bin/env python3
"""
===============================================================================
AERO PISTON ENGINE DIGITAL TWIN: UNIFIED CANONICAL STATE MODEL (PHASE 3B)
===============================================================================
Defines the strongly typed, single source of truth for runtime Digital Twin state.
Distinguishes:
  1. Measured telemetry (CAN frames / sensors)
  2. Physics-derived state (observer expected, residuals, anomaly tracking)
  3. ML predictions (stateless quantile RUL, uncertainty, fault discrimination)
  4. Operational health & redlines (deterministic state, simulation health index)
  5. Explainable diagnostics (evidence-based causal summaries)

SCIENTIFIC INTEGRITY NOTICE:
  - The health_score is a deterministic simulation index [0.0, 1.0],
    NOT a certified aircraft safety metric.
  - The RUL target represents a model-based degradation countdown,
    NOT an empirically validated metallurgical life prediction.
===============================================================================
"""

import json
from enum import Enum
from dataclasses import dataclass, field, asdict
from typing import Dict, Any, List, Optional


class EngineHealthState(str, Enum):
    """Deterministic high-level engine operational state."""
    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    CRITICAL = "CRITICAL"
    UNKNOWN = "UNKNOWN"


class TelemetryQuality(str, Enum):
    """Quality and integrity of incoming telemetry frame."""
    VALID = "VALID"
    DEGRADED = "DEGRADED"
    INVALID = "INVALID"


class RedlineStatus(str, Enum):
    """Physical engine boundary proximity status."""
    NORMAL = "NORMAL"
    CAUTION = "CAUTION"
    ALERT = "ALERT"
    REDLINE = "REDLINE"


class ResidualStatus(str, Enum):
    """Statistical anomaly detector status."""
    NORMAL = "NORMAL"
    CAUTION = "CAUTION"
    ALERT = "ALERT"


@dataclass
class Explanation:
    """
    Evidence-based explainable diagnostic record.
    Generated strictly from actual observed physics residuals and coupling metrics.
    No generative LLM or fabricated justifications.
    """
    summary: str = "Nominal operation. All physics residuals within 3-sigma expected envelope."
    evidence: List[str] = field(default_factory=list)
    feature_contributions: Dict[str, float] = field(default_factory=dict)
    physics_indicators: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class MeasuredTelemetry:
    """Raw and validated measurements decoded from CAN transport."""
    rpm: float = 0.0
    throttle_pct: float = 0.0
    fuel_flow_gps: float = 0.0
    egt1: float = 0.0
    egt2: float = 0.0
    egt3: float = 0.0
    egt4: float = 0.0
    cht1: float = 0.0
    cht2: float = 0.0
    cht3: float = 0.0
    cht4: float = 0.0
    oil_press_bar: float = 0.0
    oil_temp_c: float = 0.0
    airspeed_mps: float = 0.0
    altitude_m: float = 0.0
    status_flags: int = 0
    rolling_counter: int = 0

    @property
    def max_egt(self) -> float:
        return max(self.egt1, self.egt2, self.egt3, self.egt4)

    @property
    def max_cht(self) -> float:
        return max(self.cht1, self.cht2, self.cht3, self.cht4)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class PhysicsDerivedState:
    """Quantities produced by the independent physics observer & anomaly detector."""
    expected_values: Dict[str, float] = field(default_factory=dict)
    raw_residuals: Dict[str, float] = field(default_factory=dict)
    signed_residuals: Dict[str, float] = field(default_factory=dict)
    ewma_residuals: Dict[str, float] = field(default_factory=dict)
    max_egt_residual: float = 0.0
    max_cht_residual: float = 0.0
    residual_status: ResidualStatus = ResidualStatus.NORMAL
    residual_magnitude: float = 0.0
    anomaly_detected: bool = False
    anomaly_duration_sec: float = 0.0
    cumulative_stress: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        res = asdict(self)
        res["residual_status"] = self.residual_status.value
        return res


@dataclass
class MLPredictionState:
    """Stateless ML predictions and uncertainty intervals."""
    rul_hours: Optional[float] = None
    rul_q10_hours: Optional[float] = None
    rul_q50_hours: Optional[float] = None
    rul_q90_hours: Optional[float] = None
    uncertainty_band_hours: Optional[float] = None
    filtered_rul_hours: Optional[float] = None
    fault_type: str = "nominal"
    fault_subtype: str = "NONE"
    fault_confidence: Optional[float] = None
    fault_location: str = "NONE"
    error_message: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _safe_float(val: Any) -> Any:
    """Converts numpy numbers and objects to json-safe Python types."""
    if val is None:
        return None
    try:
        import numpy as np
        if isinstance(val, (np.floating, float)):
            return round(float(val), 3)
        if isinstance(val, (np.integer, int)):
            return int(val)
        if isinstance(val, np.ndarray):
            return [_safe_float(x) for x in val]
    except ImportError:
        pass
    if isinstance(val, float):
        return round(val, 3)
    return val


@dataclass
class DigitalTwinState:
    """
    Canonical, unified runtime representation of the Aero Piston Engine Digital Twin.
    Produced once per telemetry cycle (10 Hz nominal).
    """
    # 1. Identification & Timing
    timestamp: float
    sequence_number: int
    cycle_id: int

    # 2. Overall Status
    telemetry_status: TelemetryQuality = TelemetryQuality.VALID
    engine_state: EngineHealthState = EngineHealthState.HEALTHY
    health_score: Optional[float] = 1.0  # Simulation health index [0.0, 1.0]

    # 3. Fault & RUL Summaries (Flattened for fast consumer access)
    fault_type: str = "nominal"
    fault_confidence: Optional[float] = None
    rul_hours: Optional[float] = None
    rul_q10_hours: Optional[float] = None
    rul_q50_hours: Optional[float] = None
    rul_q90_hours: Optional[float] = None

    # 4. Residual & Safety Margin Summaries
    residual_status: str = "NORMAL"
    residual_magnitude: float = 0.0
    early_warning: bool = False
    redline_status: str = "NORMAL"
    redline_details: Dict[str, Any] = field(default_factory=dict)

    # 5. Explanations & Detailed Stage Records
    explanation: Explanation = field(default_factory=Explanation)
    telemetry: MeasuredTelemetry = field(default_factory=MeasuredTelemetry)
    physics: PhysicsDerivedState = field(default_factory=PhysicsDerivedState)
    predictions: MLPredictionState = field(default_factory=MLPredictionState)

    # 6. Operational Performance
    processing_time_ms: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        """Serializes the DigitalTwinState to a dictionary."""
        d = {
            "timestamp": round(self.timestamp, 3),
            "sequence_number": int(self.sequence_number),
            "cycle_id": int(self.cycle_id),
            "telemetry_status": self.telemetry_status.value if isinstance(self.telemetry_status, TelemetryQuality) else str(self.telemetry_status),
            "engine_state": self.engine_state.value if isinstance(self.engine_state, EngineHealthState) else str(self.engine_state),
            "health_score": _safe_float(self.health_score),
            "fault_type": str(self.fault_type),
            "fault_confidence": _safe_float(self.fault_confidence),
            "rul_hours": _safe_float(self.rul_hours),
            "rul_q10_hours": _safe_float(self.rul_q10_hours),
            "rul_q50_hours": _safe_float(self.rul_q50_hours),
            "rul_q90_hours": _safe_float(self.rul_q90_hours),
            "residual_status": str(self.residual_status),
            "residual_magnitude": _safe_float(self.residual_magnitude),
            "early_warning": bool(self.early_warning),
            "redline_status": str(self.redline_status),
            "redline_details": self.redline_details,
            "explanation": self.explanation.to_dict(),
            "telemetry": self.telemetry.to_dict(),
            "physics": self.physics.to_dict(),
            "predictions": self.predictions.to_dict(),
            "processing_time_ms": round(self.processing_time_ms, 2)
        }
        return d

    def to_json(self, indent: Optional[int] = None) -> str:
        """Serializes the state to a JSON string."""
        return json.dumps(self.to_dict(), indent=indent)

    def format_terminal_card(self) -> str:
        """
        Formats a clean, multi-line diagnostic telemetry card for terminal display.
        """
        conf_str = f"{self.fault_confidence * 100:.0f}%" if self.fault_confidence is not None else "N/A"
        rul_str = f"{self.rul_hours:.1f}h" if self.rul_hours is not None else "N/A"
        q10_str = f"{self.rul_q10_hours:.1f}" if self.rul_q10_hours is not None else "N/A"
        q90_str = f"{self.rul_q90_hours:.1f}" if self.rul_q90_hours is not None else "N/A"
        health_str = f"{self.health_score * 100:.0f}%" if self.health_score is not None else "N/A"
        warn_str = "ACTIVE" if self.early_warning else "OFF"

        lines = [
            f"[{self.timestamp:6.1f}s | Seq:{self.sequence_number:05d} | Cyc:{self.cycle_id:04d}] "
            f"STATE: {self.engine_state.value:<8s} | FAULT: {self.fault_type.upper():<16s} "
            f"(Conf: {conf_str})",
            f"  RPM: {self.telemetry.rpm:4.0f} | Throttle: {self.telemetry.throttle_pct:4.1f}% | "
            f"EGTmax: {self.telemetry.max_egt:5.1f} C | CHTmax: {self.telemetry.max_cht:5.1f} C | "
            f"Oil: {self.telemetry.oil_press_bar:4.2f}b / {self.telemetry.oil_temp_c:4.1f} C",
            f"  RESIDUAL: {self.residual_status:<7s} (Peak: {self.residual_magnitude:4.1f}) | "
            f"REDLINE: {self.redline_status:<7s} | EARLY WARNING: {warn_str}",
            f"  SIM RUL: {rul_str:<6s} [{q10_str}, {q90_str}h] | "
            f"HEALTH INDEX: {health_str} | Latency: {self.processing_time_ms:.1f}ms"
        ]
        if self.explanation.evidence:
            lines.append(f"  WHY: {self.explanation.summary}")
            for ev in self.explanation.evidence[:3]:
                lines.append(f"    - {ev}")
        return "\n".join(lines)

    def format_console_line(self) -> str:
        """Single-line compact stream format for terminal output."""
        rul_s = f"{self.rul_hours:.1f}h" if self.rul_hours is not None else "N/A"
        diag_s = f"{self.fault_type.upper()}" if self.fault_type != "nominal" else "NOMINAL"
        return (
            f"[{self.sequence_number:06d}] T={self.timestamp:6.1f}s | "
            f"STATE={self.engine_state.value:<8s} | "
            f"RPM={self.telemetry.rpm:4.0f} | EGTmax={self.telemetry.max_egt:5.1f} C | "
            f"CHTmax={self.telemetry.max_cht:5.1f} C | OIL={self.telemetry.oil_press_bar:4.2f}b | "
            f"RES={self.residual_status:<7s} | DIAG={diag_s:<14s} | RUL={rul_s:>6s}"
        )
