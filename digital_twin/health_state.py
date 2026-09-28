#!/usr/bin/env python3
"""
===============================================================================
AERO PISTON ENGINE DIGITAL TWIN: HEALTH STATE & REDLINE ENGINE (PHASE 3B)
===============================================================================
Transparent, deterministic operational health state determination and physical
limit boundary evaluation for Rotax 912-class UAV powerplants.

SCIENTIFIC INTEGRITY NOTICE:
  The health_score is a deterministic simulation index [0.0, 1.0], NOT a
  certified aircraft safety metric. It represents an engineering simulation
  index grounded in physical residual deviation and thermal stress.
===============================================================================
"""

from enum import Enum
from typing import Dict, Any, Tuple, Optional, List


class EngineHealthState(str, Enum):
    """Deterministic high-level engine operational state."""
    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    CRITICAL = "CRITICAL"
    UNKNOWN = "UNKNOWN"


class TelemetryQuality(str, Enum):
    """Quality and transport integrity of incoming telemetry frame."""
    VALID = "VALID"
    DEGRADED = "DEGRADED"
    INVALID = "INVALID"


class RedlineStatus(str, Enum):
    """Physical engine operating boundary status."""
    NORMAL = "NORMAL"
    CAUTION = "CAUTION"
    ALERT = "ALERT"
    REDLINE = "REDLINE"


class ResidualStatus(str, Enum):
    """Statistical physics observer residual status."""
    NORMAL = "NORMAL"
    CAUTION = "CAUTION"
    ALERT = "ALERT"
    ANOMALY = "ANOMALY"


class HealthStateEngine:
    """
    Evaluates physical limits, residual deviations, and fault diagnoses to
    compute deterministic engine health state and simulation health index.
    """

    def __init__(self):
        # Physical operating boundaries (Rotax 912 single source of truth)
        self.limits = {
            "egt_caution": 880.0,
            "egt_alert": 940.0,
            "egt_redline": 950.0,
            "cht_caution": 200.0,
            "cht_alert": 240.0,
            "cht_redline": 250.0,
            "oil_press_caution": 2.20,
            "oil_press_alert": 1.80,
            "oil_press_redline": 1.50,
            "oil_temp_caution": 110.0,
            "oil_temp_alert": 118.0,
            "oil_temp_redline": 125.0,
            "rpm_redline": 5900.0
        }

    def check_redlines(self, telemetry: Dict[str, Any]) -> Tuple[RedlineStatus, Dict[str, Any]]:
        """
        Evaluates current physical sensor telemetry against engine operating limitations.
        Returns the highest severity status and a dictionary of breached limits.
        """
        breached: Dict[str, float] = {}
        max_egt = max(float(telemetry.get(f"egt{i}", 0.0)) for i in range(1, 5))
        max_cht = max(float(telemetry.get(f"cht{i}", 0.0)) for i in range(1, 5))
        oil_p = float(telemetry.get("oil_press_bar", 3.0))
        oil_t = float(telemetry.get("oil_temp_c", 80.0))
        rpm = float(telemetry.get("rpm", 4000.0))

        # 1. Critical Redline Limits
        if max_egt >= self.limits["egt_redline"]:
            breached["egt_redline"] = max_egt
        if max_cht >= self.limits["cht_redline"]:
            breached["cht_redline"] = max_cht
        if oil_p <= self.limits["oil_press_redline"] and rpm > 2000.0:
            breached["oil_press_redline"] = oil_p
        if oil_t >= self.limits["oil_temp_redline"]:
            breached["oil_temp_redline"] = oil_t
        if rpm >= self.limits["rpm_redline"]:
            breached["rpm_redline"] = rpm

        if breached:
            return RedlineStatus.REDLINE, breached

        # 2. Alert Limits (90-95% of redline)
        if max_egt >= self.limits["egt_alert"]:
            breached["egt_alert"] = max_egt
        if max_cht >= self.limits["cht_alert"]:
            breached["cht_alert"] = max_cht
        if oil_p <= self.limits["oil_press_alert"] and rpm > 2000.0:
            breached["oil_press_alert"] = oil_p
        if oil_t >= self.limits["oil_temp_alert"]:
            breached["oil_temp_alert"] = oil_t

        if breached:
            return RedlineStatus.ALERT, breached

        # 3. Caution Limits
        if max_egt >= self.limits["egt_caution"]:
            breached["egt_caution"] = max_egt
        if max_cht >= self.limits["cht_caution"]:
            breached["cht_caution"] = max_cht
        if oil_p <= self.limits["oil_press_caution"] and rpm > 2000.0:
            breached["oil_press_caution"] = oil_p
        if oil_t >= self.limits["oil_temp_caution"]:
            breached["oil_temp_caution"] = oil_t

        if breached:
            return RedlineStatus.CAUTION, breached

        return RedlineStatus.NORMAL, {}

    def determine_health_state(
        self,
        telemetry_quality: TelemetryQuality,
        redline_status: RedlineStatus,
        residual_status: ResidualStatus,
        fault_type: str,
        is_plant_fault: bool,
        rul_hours: Optional[float]
    ) -> EngineHealthState:
        """
        Deterministic, transparent operational state decision logic.
        Decouples transport telemetry corruption from engine physical health.
        """
        # Telemetry invalid -> cannot safely diagnose engine
        if telemetry_quality == TelemetryQuality.INVALID:
            return EngineHealthState.UNKNOWN

        # Physical limit redline breach
        if redline_status == RedlineStatus.REDLINE:
            return EngineHealthState.CRITICAL

        # Redline alert combined with confirmed plant mechanical fault
        if redline_status == RedlineStatus.ALERT and is_plant_fault:
            return EngineHealthState.CRITICAL

        # Severe degradation countdown expiration
        if rul_hours is not None and rul_hours <= 5.0 and is_plant_fault:
            return EngineHealthState.CRITICAL

        # Confirmed residual anomaly or diagnosed fault
        if residual_status in (ResidualStatus.ALERT, ResidualStatus.CAUTION) or fault_type != "nominal":
            return EngineHealthState.DEGRADED

        return EngineHealthState.HEALTHY

    def calculate_health_score(
        self,
        engine_state: EngineHealthState,
        fault_type: str,
        norm_residual_magnitude: float,
        redline_status: RedlineStatus
    ) -> Optional[float]:
        """
        Calculates simulation health index [0.0, 1.0].
        Clearly designated as simulation metric, not certified safety probability.
        """
        if engine_state == EngineHealthState.HEALTHY:
            return round(max(0.92, 1.0 - 0.05 * norm_residual_magnitude), 3)
        elif engine_state == EngineHealthState.DEGRADED:
            if fault_type == "sensor_drift":
                # Instrument defect; powertrain mechanically sound
                return 0.82
            else:
                # Mechanical degradation index proportional to residual severity
                return round(max(0.20, 0.75 - 0.35 * min(1.5, norm_residual_magnitude)), 3)
        elif engine_state == EngineHealthState.CRITICAL:
            penalty = 1.0 if redline_status == RedlineStatus.REDLINE else 0.5
            return round(max(0.02, 0.18 - 0.10 * penalty), 3)
        return None
