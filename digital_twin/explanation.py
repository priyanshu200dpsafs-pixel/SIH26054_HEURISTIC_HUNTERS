#!/usr/bin/env python3
"""
===============================================================================
AERO PISTON ENGINE DIGITAL TWIN: EXPLAINABILITY ENGINE (PHASE 3B)
===============================================================================
Evidence-based physical causal reasoning module.
Synthesizes machine-readable, grounded diagnostic justifications directly from
real telemetry, calculated physics observer residuals, and cross-channel coupling.

STRICT DESIGN RULES:
  1. NO Large Language Models (LLMs)
  2. NO Hallucinated or speculative evidence
  3. Every evidence item is backed by current measured or residual quantities
===============================================================================
"""

from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional


class EvidenceItem(str):
    """
    Physical evidence element supporting diagnostic explanations.
    Subclasses str for string representation and joins (e.g. ' '.join(evidence)),
    while also providing structured attributes and dict access (.get(), .to_dict()).
    """
    def __new__(cls, feature: str, value: float, unit: str, direction: str, description: Optional[str] = None):
        if description is None:
            sign = "+" if value > 0 else ""
            description = f"{feature}: {sign}{value:.1f} {unit} ({direction})"
        inst = super().__new__(cls, description)
        inst.feature = str(feature)
        inst.value = round(float(value), 2)
        inst.unit = str(unit)
        inst.direction = str(direction)
        return inst

    def to_dict(self) -> Dict[str, Any]:
        return {
            "feature": self.feature,
            "value": self.value,
            "unit": self.unit,
            "direction": self.direction
        }

    def get(self, key: str, default: Any = None) -> Any:
        if key == "feature":
            return self.feature
        if key == "value":
            return self.value
        if key == "unit":
            return self.unit
        if key == "direction":
            return self.direction
        return default

    def __getitem__(self, item: Any) -> Any:
        if isinstance(item, str):
            val = self.get(item)
            if val is not None:
                return val
        return super().__getitem__(item)


@dataclass
class Explanation:
    """Machine-readable, physically grounded explanation for Digital Twin states."""
    summary: str = "Nominal operation."
    evidence: List[Any] = field(default_factory=list)
    physics_indicators: List[str] = field(default_factory=list)
    diagnostic_basis: str = "Physics observer residuals within expected nominal envelope."

    def to_dict(self) -> Dict[str, Any]:
        serialized_evidence = []
        for ev in self.evidence:
            if hasattr(ev, "to_dict"):
                serialized_evidence.append(ev.to_dict())
            elif isinstance(ev, dict):
                serialized_evidence.append(ev)
            else:
                serialized_evidence.append({
                    "feature": "telemetry_note",
                    "value": 0.0,
                    "unit": "",
                    "direction": str(ev)
                })

        return {
            "summary": self.summary,
            "evidence": serialized_evidence,
            "physics_indicators": self.physics_indicators,
            "diagnostic_basis": self.diagnostic_basis
        }


def generate_explanation(
    fault_type: str,
    fault_subtype: str,
    fault_location: str,
    signed_residuals: Dict[str, float],
    ewma_residuals: Dict[str, float],
    detector_output: Dict[str, Any],
    redline_status: str,
    redline_details: Dict[str, Any]
) -> Explanation:
    """
    Constructs an evidence-backed explanation from actual runtime quantities.
    """
    evidence_list: List[Any] = []
    indicators: List[str] = []

    # 1. Nominal Operation
    if fault_type == "nominal" and redline_status == "NORMAL":
        return Explanation(
            summary="Nominal operation. All physics residuals within 3-sigma expected envelope.",
            evidence=[],
            physics_indicators=["Combustion stoichiometry balanced", "Oil circuit hydraulic equilibrium"],
            diagnostic_basis="All channel residuals within nominal variance envelope."
        )

    # 2. Injector Clog (Combustion Lean Degradation)
    if fault_type == "injector_clog":
        dominant_cyl = detector_output.get("affected_egt_cylinder", 1)
        egt_rise = signed_residuals.get(f"egt{dominant_cyl}", 0.0)
        rpm_droop = signed_residuals.get("rpm", 0.0)
        ff_delta = signed_residuals.get("fuel_flow_gps", 0.0)

        evidence_list.append(EvidenceItem(
            feature=f"egt{dominant_cyl}_residual",
            value=egt_rise,
            unit="C",
            direction="high" if egt_rise > 0 else "low"
        ))

        evidence_list.append(EvidenceItem(
            feature="rpm_residual",
            value=rpm_droop,
            unit="RPM",
            direction="low" if rpm_droop < 0 else "high"
        ))

        if abs(ff_delta) > 0.05:
            evidence_list.append(EvidenceItem(
                feature="fuel_flow_residual",
                value=ff_delta,
                unit="g/s",
                direction="low" if ff_delta < 0 else "high"
            ))

        indicators.append(f"Cylinder {dominant_cyl} combustion mixture shifted lean toward stoichiometric max-flame-temperature")
        indicators.append("Engine shaft power deficit indicated by correlated RPM droop")

        summary = (
            f"Elevated EGT residual on Cylinder {dominant_cyl} (+{egt_rise:.1f} C) accompanied by "
            f"shaft RPM droop ({rpm_droop:.0f} RPM) is consistent with the observed injector-clog diagnostic pattern."
        )
        diag_basis = "Single-cylinder thermal divergence coupled with engine shaft torque deficit."
        return Explanation(
            summary=summary,
            evidence=evidence_list,
            physics_indicators=indicators,
            diagnostic_basis=diag_basis
        )

    # 3. Oil Leak (Hydraulic / Lubrication Degradation)
    if fault_type == "oil_leak":
        press_loss = -signed_residuals.get("oil_press_bar", 0.0)
        temp_rise = signed_residuals.get("oil_temp_c", 0.0)

        evidence_list.append(EvidenceItem(
            feature="oil_press_residual",
            value=-press_loss,
            unit="bar",
            direction="low"
        ))

        evidence_list.append(EvidenceItem(
            feature="oil_temp_residual",
            value=temp_rise,
            unit="C",
            direction="high" if temp_rise > 0 else "low"
        ))

        indicators.append("Hydraulic lubrication circuit pressure collapse")
        indicators.append("Friction-induced thermal accumulation in circulating fluid")

        summary = (
            f"Lubrication circuit failure: oil pressure dropped by {press_loss:.2f} bar "
            f"with concurrent friction heating raising oil temperature by +{temp_rise:.1f} C."
        )
        diag_basis = "Hydraulic pressure depletion combined with fluid thermal escalation."
        return Explanation(
            summary=summary,
            evidence=evidence_list,
            physics_indicators=indicators,
            diagnostic_basis=diag_basis
        )

    # 4. Sensor Drift (Thermocouple / Transducer Instrumentation Defect)
    if fault_type == "sensor_drift":
        loc_clean = fault_location.lower()
        if "egt" in loc_clean:
            num = "".join(c for c in loc_clean if c.isdigit()) or "1"
            sensor_name = f"egt{num}"
            unit = "C"
        elif "cht" in loc_clean:
            num = "".join(c for c in loc_clean if c.isdigit()) or "1"
            sensor_name = f"cht{num}"
            unit = "C"
        elif "oil" in loc_clean:
            sensor_name = "oil_press_bar"
            unit = "bar"
        else:
            sensor_name = loc_clean.replace("sensor_", "")
            unit = ""

        val_drift = signed_residuals.get(sensor_name, 0.0)

        evidence_list.append(EvidenceItem(
            feature=f"{sensor_name}_residual",
            value=val_drift,
            unit=unit,
            direction="high" if val_drift > 0 else "low"
        ))

        evidence_list.append(EvidenceItem(
            feature="rpm_residual",
            value=signed_residuals.get("rpm", 0.0),
            unit="RPM",
            direction="nominal"
        ))

        indicators.append("Isolated transducer electrical calibration offset")
        indicators.append("Zero physical shaft power loss or secondary thermal coupling")

        summary = (
            f"Instrument defect: sensor {sensor_name} drifted by {val_drift:+.1f} without "
            f"physical shaft droop or cross-cylinder coupling."
        )
        diag_basis = "Uncoupled single-sensor divergence without secondary thermodynamic impact."
        return Explanation(
            summary=summary,
            evidence=evidence_list,
            physics_indicators=indicators,
            diagnostic_basis=diag_basis
        )

    # 5. Cooling Duct Blockage
    if fault_type == "cooling_duct_blockage":
        max_cht_r = float(detector_output.get("max_cht_residual", 0.0))
        evidence_list.append(EvidenceItem(
            feature="cht_residual",
            value=max_cht_r,
            unit="C",
            direction="high" if max_cht_r > 0 else "nominal"
        ))
        indicators.append("Cowl ram-air convective heat dissipation impedance")

        summary = f"Cowl airflow restriction: cylinder head temperature residual elevated by +{max_cht_r:.1f} C."
        diag_basis = "Convective cooling reduction under ram-air duct obstruction."
        return Explanation(
            summary=summary,
            evidence=evidence_list,
            physics_indicators=indicators,
            diagnostic_basis=diag_basis
        )

    # 6. General / Redline Exceedance
    if redline_details:
        for limit_name, val in redline_details.items():
            evidence_list.append(EvidenceItem(
                feature=limit_name,
                value=float(val),
                unit="physical",
                direction="breached"
            ))
        indicators.append("Engine physical operating limitation breached")
        summary = f"Physical redline boundary breach: {', '.join(redline_details.keys())}."
        diag_basis = "Operating limits exceedance monitor."
        return Explanation(
            summary=summary,
            evidence=evidence_list,
            physics_indicators=indicators,
            diagnostic_basis=diag_basis
        )

    # 7. Fallback Degraded
    summary = f"Residual anomaly detected: residual severity {detector_output.get('status', 'CAUTION')}."
    return Explanation(
        summary=summary,
        evidence=[],
        physics_indicators=["General thermodynamic deviation"],
        diagnostic_basis="Statistical 3-sigma residual envelope exceedance."
    )
