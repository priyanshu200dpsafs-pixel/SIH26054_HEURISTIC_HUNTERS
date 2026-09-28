"""
===============================================================================
AERO PISTON ENGINE DIGITAL TWIN: SIMULATION FRAME ENVELOPE
===============================================================================
Encapsulates a standard 8-byte CAN frame into a deterministic 28-byte binary
wire envelope for localhost IPC (UDP/TCP) transport.

Wire Format Specification (28 bytes total, Big-Endian / Network Order):
  - Offset  0..1  (2 bytes): Magic identifier (0xCA4E = 'CAN')
  - Offset  2..5  (4 bytes): Envelope frame sequence number (uint32)
  - Offset  6..13 (8 bytes): Simulation timestamp in seconds (IEEE 754 float64)
  - Offset 14..17 (4 bytes): CAN Arbitration ID (uint32, e.g. 0x100..0x103)
  - Offset 18     (1 byte) : Data Length Code (uint8, exactly 8)
  - Offset 19..26 (8 bytes): CAN data payload (8 raw bytes)
  - Offset 27     (1 byte) : CRC-8 Checksum over bytes 0..26 (uint8, poly 0x07)

Note: This envelope provides simulation transport integrity across network
sockets and does NOT alter the underlying CAN payload or DBC signal matrix.
===============================================================================
"""

import struct
from typing import Tuple

try:
    from .exceptions import FrameValidationError
except ImportError:
    from exceptions import FrameValidationError

# Constants
ENVELOPE_MAGIC = 0xCA4E
ENVELOPE_FORMAT = "!H I d I B 8s B"
ENVELOPE_SIZE = struct.calcsize(ENVELOPE_FORMAT)  # exactly 28 bytes
ENVELOPE_HEADER_PAYLOAD_FORMAT = "!H I d I B 8s"


def compute_crc8(data: bytes) -> int:
    """
    Computes an 8-bit CRC over input bytes using polynomial 0x07 (initial 0x00).
    Deterministic, fast, and pure-Python.
    """
    crc = 0x00
    for byte in data:
        crc ^= byte
        for _ in range(8):
            if crc & 0x80:
                crc = ((crc << 1) ^ 0x07) & 0xFF
            else:
                crc = (crc << 1) & 0xFF
    return crc


def pack_frame_envelope(
    sequence: int,
    timestamp: float,
    arbitration_id: int,
    payload: bytes
) -> bytes:
    """
    Packs a CAN frame into a 28-byte binary envelope with CRC-8 integrity.

    Args:
      sequence: Monotonically increasing frame sequence number (0 to 2^32 - 1)
      timestamp: Simulation elapsed seconds
      arbitration_id: CAN message identifier (e.g. 0x100, 0x101, etc.)
      payload: Exactly 8 bytes of CAN data payload

    Returns:
      28 raw bytes ready for transport transmission.
    """
    if len(payload) != 8:
        raise FrameValidationError(
            f"CAN payload length must be exactly 8 bytes, got {len(payload)}",
            sequence=sequence, frame_id=arbitration_id, timestamp=timestamp
        )

    seq_uint32 = int(sequence) & 0xFFFFFFFF
    arb_id_uint32 = int(arbitration_id) & 0xFFFFFFFF
    ts_float64 = float(timestamp)
    dlc = 8

    # Pack bytes 0..26
    raw_header_payload = struct.pack(
        ENVELOPE_HEADER_PAYLOAD_FORMAT,
        ENVELOPE_MAGIC,
        seq_uint32,
        ts_float64,
        arb_id_uint32,
        dlc,
        payload
    )

    crc = compute_crc8(raw_header_payload)
    return raw_header_payload + bytes([crc])


def unpack_frame_envelope(packet_bytes: bytes) -> Tuple[int, float, int, int, bytes]:
    """
    Validates and unpacks a 28-byte binary frame envelope.

    Args:
      packet_bytes: 28 raw bytes received from transport

    Returns:
      (sequence, timestamp, arbitration_id, dlc, payload_8_bytes)

    Raises:
      FrameValidationError if packet length is invalid, magic is wrong, or CRC fails.
    """
    if len(packet_bytes) != ENVELOPE_SIZE:
        raise FrameValidationError(
            f"Invalid frame envelope size: expected {ENVELOPE_SIZE} bytes, got {len(packet_bytes)}"
        )

    # Validate CRC
    computed_crc = compute_crc8(packet_bytes[:27])
    expected_crc = packet_bytes[27]
    if computed_crc != expected_crc:
        raise FrameValidationError(
            f"Frame envelope CRC mismatch: computed {computed_crc:#04x}, expected {expected_crc:#04x}"
        )

    magic, sequence, timestamp, arbitration_id, dlc, payload = struct.unpack(
        ENVELOPE_HEADER_PAYLOAD_FORMAT, packet_bytes[:27]
    )

    if magic != ENVELOPE_MAGIC:
        raise FrameValidationError(
            f"Invalid frame envelope magic: expected {ENVELOPE_MAGIC:#06x}, got {magic:#06x}",
            sequence=sequence, frame_id=arbitration_id, timestamp=timestamp
        )

    if dlc != 8:
        raise FrameValidationError(
            f"Invalid DLC: expected 8 bytes, got {dlc}",
            sequence=sequence, frame_id=arbitration_id, timestamp=timestamp
        )

    return sequence, timestamp, arbitration_id, dlc, payload
