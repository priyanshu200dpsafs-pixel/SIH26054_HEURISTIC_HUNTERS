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
from dataclasses import dataclass, field, asdict
from typing import Dict, Any, List, Optional

from digital_twin.health_state import (
    EngineHealthState,
    TelemetryQuality,
    RedlineStatus,
    ResidualStatus
)
from digital_twin.explanation import Explanation


def _safe_float(val: Any) -> Optional[float]:
    """Helper to convert values safely to rounded float or None."""
    if val is None:
        return None
    try:
        f = float(val)
        return round(f, 2)
    except (ValueError, TypeError):
        return None


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


@dataclass
class DigitalTwinState:
    """
    Canonical, unified runtime state produced by DigitalTwinRuntime for every cycle.
    Provides complete structured data across telemetry, physics, ML, and health.
    """
    # 1. Temporal & Sequence Identity
    timestamp: float = 0.0
    sequence_number: int = 0
    cycle_id: int = 0

    # 2. Operational Health & Telemetry Status
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
            "explanation": self.explanation.to_dict() if hasattr(self.explanation, "to_dict") else asdict(self.explanation),
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
        Formats the canonical diagnostic terminal card as specified in Phase 3B.
        """
        rul_str = f"{self.rul_hours:.2f} h" if self.rul_hours is not None else "N/A"
        if self.rul_q10_hours is not None and self.rul_q90_hours is not None:
            unc_str = f"[{self.rul_q10_hours:.2f}, {self.rul_q90_hours:.2f}] h"
        else:
            unc_str = "[N/A, N/A] h"

        eng_state_val = self.engine_state.value if hasattr(self.engine_state, "value") else str(self.engine_state)
        telem_stat_val = self.telemetry_status.value if hasattr(self.telemetry_status, "value") else str(self.telemetry_status)
        redline_val = self.redline_status.value if hasattr(self.redline_status, "value") else str(self.redline_status)
        
        # Display ANOMALY if anomaly detected or status is CAUTION/ALERT/ANOMALY
        raw_res = self.residual_status.value if hasattr(self.residual_status, "value") else str(self.residual_status)
        if raw_res in ("CAUTION", "ALERT", "ANOMALY") or (hasattr(self.physics, "anomaly_detected") and self.physics.anomaly_detected):
            res_val = "ANOMALY"
        else:
            res_val = "NORMAL"

        lines = [
            "========================================================",
            "             REAL-TIME DIGITAL TWIN",
            "========================================================",
            "",
            f"TIME: {self.timestamp:.1f} s",
            f"FRAME: {self.sequence_number}",
            "",
            f"ENGINE STATE : {eng_state_val}",
            f"FAULT        : {self.fault_type.upper()}",
            "",
            f"RUL          : {rul_str}",
            f"UNCERTAINTY  : {unc_str}",
            "",
            f"RESIDUAL     : {res_val}",
            f"REDLINE      : {redline_val}",
            "",
            "EVIDENCE:"
        ]

        if hasattr(self.explanation, "evidence") and self.explanation.evidence:
            for ev in self.explanation.evidence[:4]:
                if isinstance(ev, dict) or hasattr(ev, "get"):
                    feat_name = ev.get("feature", "feature")
                    val = ev.get("value", 0.0)
                    unit = ev.get("unit", "")
                    sign = "+" if isinstance(val, (int, float)) and val > 0 else ""
                    lines.append(f"  {feat_name:<14s}: {sign}{val} {unit}")
                else:
                    lines.append(f"  {str(ev)}")
        else:
            lines.append("  None (All physics residuals within 3-sigma expected envelope)")

        lines.extend([
            "",
            f"TELEMETRY    : {telem_stat_val}",
            f"LATENCY      : {self.processing_time_ms:.1f} ms",
            "========================================================"
        ])
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
