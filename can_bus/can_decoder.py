"""
===============================================================================
AERO PISTON ENGINE DIGITAL TWIN: CAN FRAME DECODER
===============================================================================
Receives raw 28-byte frame envelopes, validates transport integrity and CAN
frame structure, decodes DBC physical signals, and synthesizes complete
engine telemetry cycles for the Digital Twin diagnostic pipeline.

Validation Checks:
  1. Envelope length (exactly 28 bytes)
  2. Envelope magic number (0xCA4E)
  3. Envelope CRC-8 transport integrity
  4. Sequence continuity (duplicate, out-of-order, or skipped sequence detection)
  5. CAN arbitration ID validity (0x100..0x103)
  6. DLC and payload length (exactly 8 bytes)
  7. Engine Core Status (0x100) parity checksum and rolling counter verification
===============================================================================
"""

import os
import logging
from typing import Dict, Any, List, Optional, Tuple, Set

import cantools

try:
    from .frame_envelope import unpack_frame_envelope, ENVELOPE_SIZE
    from .exceptions import (
        FrameValidationError,
        SequenceError,
        DecodeError,
        TelemetryValidationError,
    )
except ImportError:
    from frame_envelope import unpack_frame_envelope, ENVELOPE_SIZE
    from exceptions import (
        FrameValidationError,
        SequenceError,
        DecodeError,
        TelemetryValidationError,
    )

logger = logging.getLogger("CAN_Decoder")
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DBC_PATH = os.path.join(SCRIPT_DIR, "engine_telemetry.dbc")


class EngineCANDecoder:
    """
    Decodes envelope-wrapped CAN frames, verifies structural & cryptographic integrity,
    and aggregates the 4-frame cycle into a synchronized telemetry dictionary.
    """

    EXPECTED_IDS: Set[int] = {0x100, 0x101, 0x102, 0x103}

    def __init__(self, dbc_file: str = DBC_PATH, strict_sequence: bool = False):
        if not os.path.exists(dbc_file):
            raise FileNotFoundError(f"DBC file not found at: {dbc_file}")
        self.dbc = cantools.database.load_file(dbc_file)
        self.strict_sequence = strict_sequence

        self.last_sequence: Optional[int] = None
        self.skipped_sequences_count: int = 0
        self.duplicate_sequences_count: int = 0
        self.out_of_order_count: int = 0

        # Cycle aggregation buffer
        self._current_cycle_data: Dict[str, Any] = {}
        self._current_cycle_received_ids: Set[int] = set()
        self._current_cycle_timestamp: float = 0.0
        self._current_cycle_last_seq: int = 0

    def reset(self):
        """Resets sequence tracking and cycle buffer."""
        self.last_sequence = None
        self.skipped_sequences_count = 0
        self.duplicate_sequences_count = 0
        self.out_of_order_count = 0
        self._current_cycle_data.clear()
        self._current_cycle_received_ids.clear()
        self._current_cycle_timestamp = 0.0
        self._current_cycle_last_seq = 0

    def decode_frame(self, raw_packet: bytes) -> Tuple[int, float, int, Dict[str, Any]]:
        """
        Validates envelope and decodes a single CAN frame.

        Args:
            raw_packet: 28 raw envelope bytes.

        Returns:
            Tuple of (sequence, timestamp, arbitration_id, decoded_signals_dict)

        Raises:
            FrameValidationError: If envelope size, magic, CRC, or payload length is invalid.
            SequenceError: If sequence number is duplicate or out of order.
            DecodeError: If arbitration ID is unexpected or DBC decode fails.
        """
        # Step 1: Unpack and validate envelope (checks size, CRC-8, magic, DLC)
        sequence, timestamp, arb_id, dlc, payload = unpack_frame_envelope(raw_packet)

        # Step 2: Validate sequence continuity
        if self.last_sequence is not None:
            if sequence == self.last_sequence:
                self.duplicate_sequences_count += 1
                raise SequenceError(
                    f"Duplicate frame sequence detected: seq={sequence}",
                    sequence=sequence, frame_id=arb_id, timestamp=timestamp
                )
            elif sequence < self.last_sequence:
                self.out_of_order_count += 1
                raise SequenceError(
                    f"Out-of-order frame sequence: received seq={sequence} after seq={self.last_sequence}",
                    sequence=sequence, frame_id=arb_id, timestamp=timestamp
                )
            elif sequence > self.last_sequence + 1:
                skipped = sequence - (self.last_sequence + 1)
                self.skipped_sequences_count += skipped
                if self.strict_sequence:
                    raise SequenceError(
                        f"Skipped {skipped} frame sequence(s): jumped from {self.last_sequence} to {sequence}",
                        sequence=sequence, frame_id=arb_id, timestamp=timestamp
                    )

        self.last_sequence = sequence

        # Step 3: Validate CAN arbitration ID
        if arb_id not in self.EXPECTED_IDS:
            raise DecodeError(
                f"Unexpected CAN arbitration ID: {arb_id:#x} (expected one of {[hex(i) for i in sorted(self.EXPECTED_IDS)]})",
                sequence=sequence, frame_id=arb_id, timestamp=timestamp
            )

        # Step 4: Decode DBC payload
        try:
            msg_def = self.dbc.get_message_by_frame_id(arb_id)
            decoded = msg_def.decode(payload)
        except Exception as e:
            raise DecodeError(
                f"DBC decoding failure for frame {arb_id:#x}: {e}",
                sequence=sequence, frame_id=arb_id, timestamp=timestamp
            )

        # Step 5: Check parity & rolling counter on ENGINE_CORE_STATUS (0x100)
        if arb_id == 0x100:
            rpm = decoded.get("Engine_RPM", 0.0)
            throttle = decoded.get("Throttle_Pct", 0.0)
            rolling_counter = decoded.get("Rolling_Counter", 0)
            actual_checksum = decoded.get("Checksum", 0)

            expected_checksum = (int(rolling_counter) ^ int(rpm) ^ int(throttle)) % 16
            if actual_checksum != expected_checksum:
                raise FrameValidationError(
                    f"ENGINE_CORE_STATUS checksum mismatch: expected {expected_checksum}, got {actual_checksum}",
                    sequence=sequence, frame_id=arb_id, timestamp=timestamp
                )

        return sequence, timestamp, arb_id, decoded

    def process_frame(self, raw_packet: bytes) -> Optional[Dict[str, Any]]:
        """
        Processes a single incoming frame and buffers signals.
        When all 4 messages of a cycle (0x100..0x103) are collected, returns
        the unified telemetry dictionary. Otherwise returns None.

        Returns:
            Synchronized telemetry dictionary on cycle completion, or None.
        """
        seq, ts, arb_id, signals = self.decode_frame(raw_packet)

        # If we see a frame ID we already have in this cycle, flush prior incomplete cycle
        if arb_id in self._current_cycle_received_ids:
            logger.debug(f"Cycle collision: duplicate frame {arb_id:#x} in current buffer. Starting fresh cycle.")
            self._current_cycle_data.clear()
            self._current_cycle_received_ids.clear()

        self._current_cycle_received_ids.add(arb_id)
        self._current_cycle_timestamp = ts
        self._current_cycle_last_seq = seq

        if arb_id == 0x100:  # ENGINE_CORE_STATUS
            self._current_cycle_data["rpm"] = round(float(signals["Engine_RPM"]), 2)
            self._current_cycle_data["throttle_pct"] = round(float(signals["Throttle_Pct"]), 1)
            self._current_cycle_data["fuel_flow_gps"] = round(float(signals["Fuel_Flow_gps"]), 3)
            self._current_cycle_data["status_flags"] = int(signals["Engine_Status_Flags"])
            self._current_cycle_data["rolling_counter"] = int(signals["Rolling_Counter"])

        elif arb_id == 0x101:  # ENGINE_CYL_EGT
            self._current_cycle_data["egt1"] = round(float(signals["EGT_Cyl1"]), 1)
            self._current_cycle_data["egt2"] = round(float(signals["EGT_Cyl2"]), 1)
            self._current_cycle_data["egt3"] = round(float(signals["EGT_Cyl3"]), 1)
            self._current_cycle_data["egt4"] = round(float(signals["EGT_Cyl4"]), 1)

        elif arb_id == 0x102:  # ENGINE_CYL_CHT
            self._current_cycle_data["cht1"] = round(float(signals["CHT_Cyl1"]), 1)
            self._current_cycle_data["cht2"] = round(float(signals["CHT_Cyl2"]), 1)
            self._current_cycle_data["cht3"] = round(float(signals["CHT_Cyl3"]), 1)
            self._current_cycle_data["cht4"] = round(float(signals["CHT_Cyl4"]), 1)

        elif arb_id == 0x103:  # ENGINE_LUBRICATION_FLIGHT
            self._current_cycle_data["oil_press_bar"] = round(float(signals["Oil_Pressure_bar"]), 3)
            self._current_cycle_data["oil_temp_c"] = round(float(signals["Oil_Temperature_C"]), 1)
            self._current_cycle_data["airspeed_mps"] = round(float(signals["Airspeed_mps"]), 1)
            self._current_cycle_data["altitude_m"] = round(float(signals["Altitude_m"]), 1)

        # Check if all 4 frames are received
        if self._current_cycle_received_ids == self.EXPECTED_IDS:
            full_cycle = dict(self._current_cycle_data)
            full_cycle["timestamp"] = self._current_cycle_timestamp
            full_cycle["sequence"] = self._current_cycle_last_seq

            # Reset buffer for next cycle
            self._current_cycle_data.clear()
            self._current_cycle_received_ids.clear()
            return full_cycle

        return None

    def decode_cycle(self, raw_packets: List[bytes]) -> Dict[str, Any]:
        """
        Convenience method to decode an entire 4-frame cycle at once.

        Args:
            raw_packets: List of exactly 4 envelope packets.

        Returns:
            Reconstructed telemetry dictionary.
        """
        cycle_result: Optional[Dict[str, Any]] = None
        for pkt in raw_packets:
            res = self.process_frame(pkt)
            if res is not None:
                cycle_result = res

        if cycle_result is None:
            raise FrameValidationError(
                f"Failed to assemble full cycle: received {len(raw_packets)} packets, expected 4 complete messages"
            )
        return cycle_result
