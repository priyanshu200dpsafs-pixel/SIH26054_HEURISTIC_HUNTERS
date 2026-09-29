#!/usr/bin/env python3
"""
===============================================================================
AERO PISTON ENGINE DIGITAL TWIN: DASHBOARD FORMATTING & TOKENS (PHASE 4)
===============================================================================
Design tokens, color constants, unit formats, and UI helper functions for the
Mission Control Dashboard.

SCIENTIFIC INTEGRITY NOTICE:
  Terminology strictly uses simulation and engineering indicators:
  - "SIMULATION HEALTH STATE", "SIMULATION CONDITION", "MODEL-BASED RUL"
  - ZERO false claims of flight certification (DO-178C/DO-254) or aircraft dispatch.
===============================================================================
"""

from typing import Any, Optional

# Operational State Colors (Hex)
STATE_COLORS = {
    "HEALTHY": "#2ecc71",     # Crisp Green
    "DEGRADED": "#f39c12",    # Amber / Orange
    "CRITICAL": "#e74c3c",    # High-Visibility Red
    "UNKNOWN": "#95a5a6",     # Neutral Grey
}

# Telemetry Quality Colors
TELEMETRY_COLORS = {
    "VALID": "#2ecc71",
    "DEGRADED": "#f39c12",
    "INVALID": "#e74c3c",
}

# Redline / Physical Boundary Colors
REDLINE_COLORS = {
    "NORMAL": "#2ecc71",
    "CAUTION": "#f1c40f",
    "ALERT": "#e67e22",
    "REDLINE": "#e74c3c",
}

# Residual Anomaly Colors
RESIDUAL_COLORS = {
    "NORMAL": "#2ecc71",
    "CAUTION": "#f1c40f",
    "ALERT": "#e67e22",
    "ANOMALY": "#e67e22",
}


def get_state_color(state_str: str) -> str:
    """Returns the hex color code for an engine health state."""
    return STATE_COLORS.get(state_str.upper(), "#95a5a6")


def get_telemetry_color(quality_str: str) -> str:
    """Returns the hex color code for telemetry quality."""
    return TELEMETRY_COLORS.get(quality_str.upper(), "#95a5a6")


def get_redline_color(status_str: str) -> str:
    """Returns the hex color code for redline status."""
    return REDLINE_COLORS.get(status_str.upper(), "#2ecc71")


def format_hours(val: Optional[float]) -> str:
    """Formats RUL hours value safely."""
    if val is None:
        return "RUL UNAVAILABLE"
    try:
        f = float(val)
        return f"{f:.1f} h"
    except (ValueError, TypeError):
        return "RUL UNAVAILABLE"


def format_temp(val: Optional[float]) -> str:
    """Formats temperature in degrees Celsius."""
    if val is None:
        return "N/A"
    try:
        return f"{float(val):.1f} °C"
    except (ValueError, TypeError):
        return "N/A"


def format_press(val: Optional[float]) -> str:
    """Formats pressure in bar."""
    if val is None:
        return "N/A"
    try:
        return f"{float(val):.2f} bar"
    except (ValueError, TypeError):
        return "N/A"


def format_rpm(val: Optional[float]) -> str:
    """Formats shaft RPM."""
    if val is None:
        return "N/A"
    try:
        return f"{float(val):.0f} RPM"
    except (ValueError, TypeError):
        return "N/A"


def format_pct(val: Optional[float]) -> str:
    """Formats percentage value."""
    if val is None:
        return "N/A"
    try:
        return f"{float(val):.1f}%"
    except (ValueError, TypeError):
        return "N/A"


def format_fuel_flow(val: Optional[float]) -> str:
    """Formats fuel flow in grams per second."""
    if val is None:
        return "N/A"
    try:
        return f"{float(val):.3f} g/s"
    except (ValueError, TypeError):
        return "N/A"


def format_latency(val: Optional[float]) -> str:
    """Formats processing latency in milliseconds."""
    if val is None:
        return "N/A"
    try:
        return f"{float(val):.1f} ms"
    except (ValueError, TypeError):
        return "N/A"


def format_health_index(val: Optional[float]) -> str:
    """Formats simulation health index [0.0, 1.0] as 0-100 score."""
    if val is None:
        return "N/A"
    try:
        idx = int(round(float(val) * 100))
        return f"{idx} / 100"
    except (ValueError, TypeError):
        return "N/A"
