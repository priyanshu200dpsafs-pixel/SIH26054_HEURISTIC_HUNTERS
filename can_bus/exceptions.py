"""
===============================================================================
AERO PISTON ENGINE DIGITAL TWIN: TELEMETRY & CAN EXCEPTIONS
===============================================================================
Defines domain-specific exceptions for transport, encoding, decoding, validation,
and diagnostic operations.
===============================================================================
"""

class TelemetryPipelineError(Exception):
    """Base class for all telemetry and digital twin pipeline errors."""
    def __init__(self, message: str, sequence: int = None, frame_id: int = None, timestamp: float = None):
        super().__init__(message)
        self.message = message
        self.sequence = sequence
        self.frame_id = frame_id
        self.timestamp = timestamp

    def __str__(self):
        ctx = []
        if self.sequence is not None:
            ctx.append(f"seq={self.sequence}")
        if self.frame_id is not None:
            ctx.append(f"frame_id={self.frame_id:#x}")
        if self.timestamp is not None:
            ctx.append(f"ts={self.timestamp:.3f}")
        ctx_str = f" [{', '.join(ctx)}]" if ctx else ""
        return f"{self.message}{ctx_str}"


class TransportError(TelemetryPipelineError):
    """Raised when frame transmission or reception fails over the transport layer."""
    pass


class FrameValidationError(TelemetryPipelineError):
    """Raised when an incoming raw frame fails structural, magic, CRC, or length validation."""
    pass


class SequenceError(FrameValidationError):
    """Raised when a frame sequence number is duplicate, skipped, or out-of-order."""
    pass


class DecodeError(TelemetryPipelineError):
    """Raised when DBC signal decoding fails or binary payload cannot be unpacked."""
    pass


class TelemetryValidationError(TelemetryPipelineError):
    """Raised when input sensor telemetry is missing required fields, non-numeric, or invalid."""
    pass


class DiagnosticError(TelemetryPipelineError):
    """Raised when physics observer, residual detector, or fault isolation fails."""
    pass
