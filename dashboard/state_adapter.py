#!/usr/bin/env python3
"""
===============================================================================
AERO PISTON ENGINE DIGITAL TWIN: STATE ADAPTER (PHASE 4)
===============================================================================
Converts the canonical `DigitalTwinState` into presentation-ready structures
for the Mission Control Dashboard.

STRICT DESIGN RULES:
  1. The UI is strictly an OBSERVATION SURFACE.
  2. NO duplicated physics calculations.
  3. NO duplicated fault classification.
  4. NO duplicated RUL inference.
  5. Consumes DigitalTwinState as the single source of truth.
===============================================================================
"""

from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional

from digital_twin.state import DigitalTwinState, EngineHealthState, TelemetryQuality, RedlineStatus
from dashboard.formatting import (
    format_hours,
    format_temp,
    format_press,
    format_rpm,
    format_pct,
    format_fuel_flow,
    format_latency,
    format_health_index,
    get_state_color,
    get_telemetry_color,
    get_redline_color,
)


@dataclass
class DashboardState:
    """Flattened, display-ready data model consumed directly by dashboard components."""
    # Identification & Sequencing
    timestamp_sec: float = 0.0
    sequence_number: int = 0
    cycle_id: int = 0

    # Operational Health & Telemetry Quality
    engine_state: str = "UNKNOWN"
    engine_state_color: str = "#95a5a6"
    health_score: Optional[float] = None
    health_score_display: str = "N/A"
    health_index_int: int = 0
    telemetry_status: str = "VALID"
    telemetry_status_color: str = "#2ecc71"
    sequence_ok: bool = True

    # Fault Diagnosis & Isolation
    fault_type: str = "nominal"
    fault_display: str = "NOMINAL"
    fault_confidence: Optional[float] = None
    fault_confidence_pct: str = "N/A"
    fault_subtype: str = "NONE"
    fault_location: str = "NONE"

    # Prognostics & RUL Uncertainty
    rul_hours: Optional[float] = None
    rul_display: str = "RUL UNAVAILABLE"
    rul_q10_hours: Optional[float] = None
    rul_q10_display: str = "N/A"
    rul_q90_hours: Optional[float] = None
    rul_q90_display: str = "N/A"
    uncertainty_band_hours: Optional[float] = None
    uncertainty_display: str = "N/A"
    damage_state: str = "HEALTHY"

    # Physics Residuals & Redlines
    residual_status: str = "NORMAL"
    residual_magnitude: float = 0.0
    early_warning: bool = False
    redline_status: str = "NORMAL"
    redline_status_color: str = "#2ecc71"
    redline_details: Dict[str, Any] = field(default_factory=dict)

    # Measured Telemetry Values
    rpm: float = 0.0
    rpm_display: str = "N/A"
    throttle_pct: float = 0.0
    throttle_display: str = "N/A"
    fuel_flow_gps: float = 0.0
    fuel_flow_display: str = "N/A"
    egt1: float = 0.0
    egt2: float = 0.0
    egt3: float = 0.0
    egt4: float = 0.0
    max_egt: float = 0.0
    max_egt_display: str = "N/A"
    cht1: float = 0.0
    cht2: float = 0.0
    cht3: float = 0.0
    cht4: float = 0.0
    max_cht: float = 0.0
    max_cht_display: str = "N/A"
    oil_press_bar: float = 0.0
    oil_press_display: str = "N/A"
    oil_temp_c: float = 0.0
    oil_temp_display: str = "N/A"
    airspeed_mps: float = 0.0
    altitude_m: float = 0.0

    # Physics Derived Quantities
    expected_values: Dict[str, float] = field(default_factory=dict)
    ewma_residuals: Dict[str, float] = field(default_factory=dict)
    signed_residuals: Dict[str, float] = field(default_factory=dict)
    max_egt_residual: float = 0.0
    max_cht_residual: float = 0.0

    # Evidence-Based Explainability
    explanation_summary: str = "Nominal operation."
    evidence_items: List[Dict[str, Any]] = field(default_factory=list)
    physics_indicators: List[str] = field(default_factory=list)
    diagnostic_basis: str = ""

    # Operational Performance
    processing_time_ms: float = 0.0
    processing_latency_display: str = "N/A"

    # Raw Serialized State
    raw_state: Optional[DigitalTwinState] = None


class DashboardStateAdapter:
    """
    Stateless adapter transforming DigitalTwinState records into DashboardState.
    Performs purely visual normalization and formatting.
    """

    @staticmethod
    def adapt(state: DigitalTwinState) -> DashboardState:
        """Transforms a canonical DigitalTwinState into a presentation-ready DashboardState."""
        eng_state_str = state.engine_state.value if hasattr(state.engine_state, "value") else str(state.engine_state)
        telem_stat_str = state.telemetry_status.value if hasattr(state.telemetry_status, "value") else str(state.telemetry_status)
        redline_str = state.redline_status.value if hasattr(state.redline_status, "value") else str(state.redline_status)
        res_str = state.residual_status.value if hasattr(state.residual_status, "value") else str(state.residual_status)

        # Health score & index
        h_score = state.health_score
        h_index = int(round(h_score * 100)) if h_score is not None else 0

        # Prognostic Damage State Determination (Derived from health state & RUL)
        if eng_state_str == "CRITICAL":
            damage_state = "CRITICAL_CONDITION"
        elif eng_state_str == "DEGRADED":
            if state.rul_hours is not None and state.rul_hours < 50.0:
                damage_state = "PROGRESSIVE_DEGRADATION"
            else:
                damage_state = "INCIPIENT_DEGRADATION"
        elif eng_state_str == "UNKNOWN":
            damage_state = "UNKNOWN"
        else:
            damage_state = "HEALTHY"

        # Telemetry shortcuts
        telem = state.telemetry
        physics = state.physics
        preds = state.predictions
        expl = state.explanation

        # Explainability evidence items
        evidence_list = []
        if hasattr(expl, "evidence") and expl.evidence:
            for ev in expl.evidence:
                if hasattr(ev, "to_dict"):
                    evidence_list.append(ev.to_dict())
                elif isinstance(ev, dict):
                    evidence_list.append(ev)
                else:
                    evidence_list.append({
                        "feature": "telemetry_note",
                        "value": 0.0,
                        "unit": "",
                        "direction": str(ev)
                    })

        # Uncertainty interval
        unc_display = "N/A"
        if state.rul_q10_hours is not None and state.rul_q90_hours is not None:
            unc_display = f"[{state.rul_q10_hours:.1f}, {state.rul_q90_hours:.1f}] h"

        conf_pct = f"{int(round(preds.fault_confidence * 100))}%" if preds.fault_confidence is not None else "N/A"

        return DashboardState(
            timestamp_sec=round(float(state.timestamp), 2),
            sequence_number=int(state.sequence_number),
            cycle_id=int(state.cycle_id),
            engine_state=eng_state_str,
            engine_state_color=get_state_color(eng_state_str),
            health_score=h_score,
            health_score_display=format_health_index(h_score),
            health_index_int=h_index,
            telemetry_status=telem_stat_str,
            telemetry_status_color=get_telemetry_color(telem_stat_str),
            sequence_ok=(telem_stat_str != "INVALID"),
            fault_type=state.fault_type,
            fault_display=state.fault_type.upper().replace("_", " "),
            fault_confidence=preds.fault_confidence,
            fault_confidence_pct=conf_pct,
            fault_subtype=preds.fault_subtype,
            fault_location=preds.fault_location,
            rul_hours=state.rul_hours,
            rul_display=format_hours(state.rul_hours),
            rul_q10_hours=state.rul_q10_hours,
            rul_q10_display=format_hours(state.rul_q10_hours),
            rul_q90_hours=state.rul_q90_hours,
            rul_q90_display=format_hours(state.rul_q90_hours),
            uncertainty_band_hours=preds.uncertainty_band_hours,
            uncertainty_display=unc_display,
            damage_state=damage_state,
            residual_status=res_str,
            residual_magnitude=float(state.residual_magnitude),
            early_warning=bool(state.early_warning),
            redline_status=redline_str,
            redline_status_color=get_redline_color(redline_str),
            redline_details=state.redline_details or {},
            rpm=telem.rpm,
            rpm_display=format_rpm(telem.rpm),
            throttle_pct=telem.throttle_pct,
            throttle_display=format_pct(telem.throttle_pct),
            fuel_flow_gps=telem.fuel_flow_gps,
            fuel_flow_display=format_fuel_flow(telem.fuel_flow_gps),
            egt1=telem.egt1,
            egt2=telem.egt2,
            egt3=telem.egt3,
            egt4=telem.egt4,
            max_egt=telem.max_egt,
            max_egt_display=format_temp(telem.max_egt),
            cht1=telem.cht1,
            cht2=telem.cht2,
            cht3=telem.cht3,
            cht4=telem.cht4,
            max_cht=telem.max_cht,
            max_cht_display=format_temp(telem.max_cht),
            oil_press_bar=telem.oil_press_bar,
            oil_press_display=format_press(telem.oil_press_bar),
            oil_temp_c=telem.oil_temp_c,
            oil_temp_display=format_temp(telem.oil_temp_c),
            airspeed_mps=telem.airspeed_mps,
            altitude_m=telem.altitude_m,
            expected_values=physics.expected_values,
            ewma_residuals=physics.ewma_residuals,
            signed_residuals=physics.signed_residuals,
            max_egt_residual=physics.max_egt_residual,
            max_cht_residual=physics.max_cht_residual,
            explanation_summary=expl.summary if hasattr(expl, "summary") else str(expl),
            evidence_items=evidence_list,
            physics_indicators=expl.physics_indicators if hasattr(expl, "physics_indicators") else [],
            diagnostic_basis=expl.diagnostic_basis if hasattr(expl, "diagnostic_basis") else "",
            processing_time_ms=state.processing_time_ms,
            processing_latency_display=format_latency(state.processing_time_ms),
            raw_state=state
        )
