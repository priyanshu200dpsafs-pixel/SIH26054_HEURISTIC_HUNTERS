"""
===============================================================================
AERO PISTON ENGINE DIGITAL TWIN: CAN BUS & TRANSPORT PACKAGE
===============================================================================
"""

from .exceptions import (
    TelemetryPipelineError,
    TransportError,
    FrameValidationError,
    SequenceError,
    DecodeError,
    TelemetryValidationError,
    DiagnosticError,
)
from .frame_envelope import (
    ENVELOPE_MAGIC,
    ENVELOPE_SIZE,
    compute_crc8,
    pack_frame_envelope,
    unpack_frame_envelope,
)
from .transport import FrameTransport
from .local_udp_transport import LocalUDPTransport, create_local_udp_pair
from .can_encoder import EngineCANEncoder
from .can_decoder import EngineCANDecoder
from .telemetry_event import TelemetryEvent

__all__ = [
    "TelemetryPipelineError",
    "TransportError",
    "FrameValidationError",
    "SequenceError",
    "DecodeError",
    "TelemetryValidationError",
    "DiagnosticError",
    "ENVELOPE_MAGIC",
    "ENVELOPE_SIZE",
    "compute_crc8",
    "pack_frame_envelope",
    "unpack_frame_envelope",
    "FrameTransport",
    "LocalUDPTransport",
    "create_local_udp_pair",
    "EngineCANEncoder",
    "EngineCANDecoder",
    "TelemetryEvent",
]
