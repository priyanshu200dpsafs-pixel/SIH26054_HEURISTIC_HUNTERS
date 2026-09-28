"""
===============================================================================
AERO PISTON ENGINE DIGITAL TWIN: TRANSPORT ABSTRACTION
===============================================================================
Defines the abstract interface for CAN frame byte transport.
Decouples the CAN encoding/decoding and diagnostic pipeline from physical or
virtual networking mechanisms (localhost UDP, SocketCAN, serial, or hardware).
===============================================================================
"""

from abc import ABC, abstractmethod
from typing import Optional


class FrameTransport(ABC):
    """
    Abstract base class for raw CAN frame transport.
    Transports transmit and receive opaque binary frame envelopes.
    """

    @abstractmethod
    def send(self, frame: bytes) -> None:
        """
        Transmits raw frame envelope bytes over the transport medium.

        Args:
            frame: Raw binary frame bytes.

        Raises:
            TransportError: If transmission fails or transport is closed.
        """
        pass

    @abstractmethod
    def receive(self, timeout: Optional[float] = None) -> Optional[bytes]:
        """
        Receives raw frame envelope bytes from the transport medium.

        Args:
            timeout: Maximum seconds to wait for a frame.
                     None means wait indefinitely or use transport default.
                     0.0 means non-blocking.

        Returns:
            Raw frame bytes, or None if timeout expired without data.

        Raises:
            TransportError: If reception encounters an unrecoverable I/O error.
        """
        pass

    @abstractmethod
    def close(self) -> None:
        """
        Closes the transport and releases underlying sockets, handles, or channels.
        Subsequent calls to send() or receive() must raise TransportError.
        """
        pass

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
