"""
===============================================================================
AERO PISTON ENGINE DIGITAL TWIN: CAN FRAME ENCODER
===============================================================================
Encodes raw plant/sensor telemetry dictionaries into standardized aerospace
CAN frames (DBC-compliant) wrapped in 28-byte simulation transport envelopes.

Architecture:
  sensor dictionary
        ↓
  DBC signal & range validation (fail loudly on malformed/out-of-range data)
        ↓
  CAN message encoding (cantools, engine_telemetry.dbc)
        ↓
  28-byte binary frame envelopes (pack_frame_envelope)
===============================================================================
"""

import os
import math
from typing import Dict, Any, List, Optional, Tuple

import cantools
import numpy as np

try:
    from .frame_envelope import pack_frame_envelope
    from .exceptions import TelemetryValidationError, FrameValidationError
except ImportError:
    from frame_envelope import pack_frame_envelope
    from exceptions import TelemetryValidationError, FrameValidationError

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DBC_PATH = os.path.join(SCRIPT_DIR, "engine_telemetry.dbc")


# Signal definitions, acceptable input keys, and valid physical ranges from DBC
SIGNAL_SPEC = {
    "rpm": {
        "aliases": ["Engine_RPM", "rpm"],
        "min": 0.0,
        "max": 8000.0,
        "unit": "rpm",
        "dbc_name": "Engine_RPM"
    },
    "throttle_pct": {
        "aliases": ["Throttle_Pct", "throttle_pct", "throttle"],
        "min": 0.0,
        "max": 100.0,
        "unit": "%",
        "dbc_name": "Throttle_Pct"
    },
    "fuel_flow_gps": {
        "aliases": ["Fuel_Flow_gps", "fuel_flow_gps", "fuel_flow"],
        "min": 0.0,
        "max": 20.0,
        "unit": "g/s",
        "dbc_name": "Fuel_Flow_gps"
    },
    "egt1": {"aliases": ["EGT_Cyl1", "egt1"], "min": 0.0, "max": 1200.0, "unit": "degC", "dbc_name": "EGT_Cyl1"},
    "egt2": {"aliases": ["EGT_Cyl2", "egt2"], "min": 0.0, "max": 1200.0, "unit": "degC", "dbc_name": "EGT_Cyl2"},
    "egt3": {"aliases": ["EGT_Cyl3", "egt3"], "min": 0.0, "max": 1200.0, "unit": "degC", "dbc_name": "EGT_Cyl3"},
    "egt4": {"aliases": ["EGT_Cyl4", "egt4"], "min": 0.0, "max": 1200.0, "unit": "degC", "dbc_name": "EGT_Cyl4"},
    "cht1": {"aliases": ["CHT_Cyl1", "cht1"], "min": 0.0, "max": 400.0, "unit": "degC", "dbc_name": "CHT_Cyl1"},
    "cht2": {"aliases": ["CHT_Cyl2", "cht2"], "min": 0.0, "max": 400.0, "unit": "degC", "dbc_name": "CHT_Cyl2"},
    "cht3": {"aliases": ["CHT_Cyl3", "cht3"], "min": 0.0, "max": 400.0, "unit": "degC", "dbc_name": "CHT_Cyl3"},
    "cht4": {"aliases": ["CHT_Cyl4", "cht4"], "min": 0.0, "max": 400.0, "unit": "degC", "dbc_name": "CHT_Cyl4"},
    "oil_press_bar": {
        "aliases": ["Oil_Pressure_bar", "oil_press_bar", "oil_press"],
        "min": 0.0,
        "max": 10.0,
        "unit": "bar",
        "dbc_name": "Oil_Pressure_bar"
    },
    "oil_temp_c": {
        "aliases": ["Oil_Temperature_C", "oil_temp_c", "oil_temp"],
        "min": -40.0,
        "max": 200.0,
        "unit": "degC",
        "dbc_name": "Oil_Temperature_C"
    },
    "airspeed_mps": {
        "aliases": ["Airspeed_mps", "airspeed_mps", "airspeed"],
        "min": 0.0,
        "max": 150.0,
        "unit": "m/s",
        "dbc_name": "Airspeed_mps"
    },
    "altitude_m": {
        "aliases": ["Altitude_m", "altitude_m", "altitude"],
        "min": 0.0,
        "max": 10000.0,
        "unit": "m",
        "dbc_name": "Altitude_m"
    },
}


class EngineCANEncoder:
    """
    Validates sensor telemetry and encodes it into 4 CAN frames enclosed
    in 28-byte binary simulation envelopes.
    """

    def __init__(self, dbc_file: str = DBC_PATH):
        if not os.path.exists(dbc_file):
            raise FileNotFoundError(f"DBC file not found at: {dbc_file}")
        self.dbc = cantools.database.load_file(dbc_file)
        self.msg_core = self.dbc.get_message_by_name("ENGINE_CORE_STATUS")
        self.msg_egt = self.dbc.get_message_by_name("ENGINE_CYL_EGT")
        self.msg_cht = self.dbc.get_message_by_name("ENGINE_CYL_CHT")
        self.msg_lube = self.dbc.get_message_by_name("ENGINE_LUBRICATION_FLIGHT")
        
        self.frame_sequence: int = 0
        self.rolling_counter: int = 0

    def reset(self, start_sequence: int = 0):
        """Resets sequence and rolling counter."""
        self.frame_sequence = start_sequence
        self.rolling_counter = 0

    def validate_and_normalize_telemetry(self, telemetry: Dict[str, Any]) -> Dict[str, float]:
        """
        Validates telemetry dictionary:
          - Confirms all required signals exist.
          - Checks types are numeric, non-NaN, non-Inf.
          - Checks physical ranges against DBC bounds.
        Returns a normalized dict with canonical signal names.
        """
        if not isinstance(telemetry, dict):
            raise TelemetryValidationError(f"Expected telemetry dict, got {type(telemetry).__name__}")

        normalized: Dict[str, float] = {}

        for canonical_name, spec in SIGNAL_SPEC.items():
            val = None
            for alias in spec["aliases"]:
                if alias in telemetry and telemetry[alias] is not None:
                    val = telemetry[alias]
                    break

            if val is None:
                raise TelemetryValidationError(
                    f"Missing required telemetry signal '{canonical_name}' (aliases checked: {spec['aliases']})"
                )

            # Check numeric type
            if not isinstance(val, (int, float, np.number)) or isinstance(val, bool):
                raise TelemetryValidationError(
                    f"Signal '{canonical_name}' must be numeric, got {type(val).__name__} ({val})"
                )

            fval = float(val)
            if math.isnan(fval) or math.isinf(fval):
                raise TelemetryValidationError(
                    f"Signal '{canonical_name}' has non-finite value: {fval}"
                )

            # Validate range
            if not (spec["min"] <= fval <= spec["max"]):
                raise TelemetryValidationError(
                    f"Signal '{canonical_name}' value {fval:.3f} {spec['unit']} out of range [{spec['min']}, {spec['max']}]"
                )

            normalized[canonical_name] = fval

        return normalized

    def encode_telemetry_cycle(
        self,
        telemetry: Dict[str, Any],
        timestamp: float
    ) -> List[bytes]:
        """
        Encodes a single time-slice of engine telemetry into 4 envelope-wrapped CAN frames.

        Args:
            telemetry: Raw sensor dictionary.
            timestamp: Monotonic simulation elapsed seconds.

        Returns:
            List of 4 raw envelope bytes (28 bytes each), ready for transport transmission.
            Frames emitted:
              1. 0x100 ENGINE_CORE_STATUS
              2. 0x101 ENGINE_CYL_EGT
              3. 0x102 ENGINE_CYL_CHT
              4. 0x103 ENGINE_LUBRICATION_FLIGHT
        """
        data = self.validate_and_normalize_telemetry(telemetry)

        # Quantize to DBC resolutions before integer parity calculation:
        # Engine_RPM resolution is 0.25, Throttle_Pct resolution is 0.5
        q_rpm = round(data["rpm"] / 0.25) * 0.25
        q_th = round(data["throttle_pct"] / 0.5) * 0.5
        counter_4bit = self.rolling_counter % 16
        checksum_4bit = (counter_4bit ^ int(q_rpm) ^ int(q_th)) % 16

        # Determine status flags
        status_flags = 0
        max_egt = max(data["egt1"], data["egt2"], data["egt3"], data["egt4"])
        max_cht = max(data["cht1"], data["cht2"], data["cht3"], data["cht4"])
        oil_p = data["oil_press_bar"]

        if max_egt >= 880.0 or max_cht >= 210.0 or oil_p < 2.0:
            status_flags |= 0x01
        if max_egt >= 940.0 or max_cht >= 225.0 or oil_p < 1.4:
            status_flags |= 0x02

        # 1. 0x100 ENGINE_CORE_STATUS
        payload_core = self.msg_core.encode({
            "Engine_RPM": data["rpm"],
            "Throttle_Pct": data["throttle_pct"],
            "Fuel_Flow_gps": data["fuel_flow_gps"],
            "Engine_Status_Flags": int(status_flags),
            "Rolling_Counter": int(counter_4bit),
            "Checksum": int(checksum_4bit)
        })

        # 2. 0x101 ENGINE_CYL_EGT
        payload_egt = self.msg_egt.encode({
            "EGT_Cyl1": data["egt1"],
            "EGT_Cyl2": data["egt2"],
            "EGT_Cyl3": data["egt3"],
            "EGT_Cyl4": data["egt4"]
        })

        # 3. 0x102 ENGINE_CYL_CHT
        payload_cht = self.msg_cht.encode({
            "CHT_Cyl1": data["cht1"],
            "CHT_Cyl2": data["cht2"],
            "CHT_Cyl3": data["cht3"],
            "CHT_Cyl4": data["cht4"]
        })

        # 4. 0x103 ENGINE_LUBRICATION_FLIGHT
        payload_lube = self.msg_lube.encode({
            "Oil_Pressure_bar": data["oil_press_bar"],
            "Oil_Temperature_C": data["oil_temp_c"],
            "Airspeed_mps": data["airspeed_mps"],
            "Altitude_m": data["altitude_m"]
        })

        # Pack each into 28-byte binary envelope with unique monotonic sequence
        packets: List[bytes] = []
        messages = [
            (self.msg_core.frame_id, payload_core),
            (self.msg_egt.frame_id, payload_egt),
            (self.msg_cht.frame_id, payload_cht),
            (self.msg_lube.frame_id, payload_lube)
        ]

        for arb_id, payload in messages:
            envelope_bytes = pack_frame_envelope(
                sequence=self.frame_sequence,
                timestamp=timestamp,
                arbitration_id=arb_id,
                payload=payload
            )
            packets.append(envelope_bytes)
            self.frame_sequence += 1

        self.rolling_counter = (self.rolling_counter + 1) % 16
        return packets
