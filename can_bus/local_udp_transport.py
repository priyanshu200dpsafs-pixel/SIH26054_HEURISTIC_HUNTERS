"""
===============================================================================
AERO PISTON ENGINE DIGITAL TWIN: LOCALHOST UDP TRANSPORT
===============================================================================
Cross-platform UDP loopback transport implementation of FrameTransport.

Properties:
  - Cross-platform: fully compatible with Windows, Linux, and macOS without root/admin privileges.
  - Zero-hardware dependency: runs over standard OS network stack loopback (127.0.0.1).
  - Clean lifecycle: deterministic timeout handling, no busy loops, graceful shutdown.
  - Configurable endpoints: supports both unified loopback (same socket sends and receives)
    and decoupled sender/receiver configurations.
===============================================================================
"""

import socket
import select
from typing import Optional, Tuple

try:
    from .transport import FrameTransport
    from .exceptions import TransportError
except ImportError:
    from transport import FrameTransport
    from exceptions import TransportError


class LocalUDPTransport(FrameTransport):
    """
    Localhost UDP socket implementation of FrameTransport.
    """

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 5005,
        bind_port: Optional[int] = None,
        target_port: Optional[int] = None,
        buffer_size: int = 2048,
        default_timeout: float = 1.0,
    ):
        """
        Initializes the local UDP transport.

        Args:
            host: IP address to bind/send (default 127.0.0.1).
            port: Default port if bind_port or target_port is not explicitly set.
            bind_port: Local port to bind for incoming frames. Defaults to `port`.
                       Set to None to create a send-only socket.
                       Set to 0 to bind to an OS-assigned ephemeral port.
            target_port: Remote port to send outgoing frames to. Defaults to `port`.
            buffer_size: Max datagram buffer size in bytes (default 2048).
            default_timeout: Default receive timeout in seconds (default 1.0).
        """
        self.host = host
        self.buffer_size = buffer_size
        self.default_timeout = default_timeout
        self.is_closed = False

        self._bind_port = port if bind_port is None else bind_port
        self._target_port = port if target_port is None else target_port

        try:
            self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            
            # Enable address reuse where supported (safe for rapid restart on same port)
            try:
                self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            except (OSError, AttributeError):
                pass

            if self._bind_port is not None:
                self._sock.bind((self.host, self._bind_port))
                self.local_address: Tuple[str, int] = self._sock.getsockname()
            else:
                self.local_address = ("", 0)

            self.target_address: Tuple[str, int] = (self.host, self._target_port)
            self._sock.settimeout(self.default_timeout)

        except OSError as e:
            self.is_closed = True
            raise TransportError(f"Failed to initialize UDP socket on {self.host}:{self._bind_port}: {e}")

    @property
    def bound_port(self) -> int:
        """Returns the actual bound local port (useful when bound to ephemeral port 0)."""
        return self.local_address[1]

    def send(self, frame: bytes) -> None:
        """
        Transmits raw frame bytes to target_address.
        """
        if self.is_closed:
            raise TransportError("Cannot send: LocalUDPTransport is closed.")
        if not isinstance(frame, (bytes, bytearray)):
            raise TransportError(f"Expected bytes-like object, got {type(frame).__name__}")

        try:
            bytes_sent = self._sock.sendto(frame, self.target_address)
            if bytes_sent != len(frame):
                raise TransportError(
                    f"Truncated UDP transmission: sent {bytes_sent} of {len(frame)} bytes."
                )
        except OSError as e:
            if self.is_closed:
                raise TransportError("Cannot send: LocalUDPTransport is closed.")
            raise TransportError(f"UDP transmission error to {self.target_address}: {e}")

    def receive(self, timeout: Optional[float] = None) -> Optional[bytes]:
        """
        Receives raw frame bytes from the bound socket.

        Args:
            timeout: Maximum seconds to wait. None uses default_timeout. 0.0 is non-blocking.

        Returns:
            Raw frame bytes, or None if timeout expired.
        """
        if self.is_closed:
            raise TransportError("Cannot receive: LocalUDPTransport is closed.")
        if self._bind_port is None:
            raise TransportError("Cannot receive: transport is configured in send-only mode (no bind_port).")

        eff_timeout = self.default_timeout if timeout is None else timeout

        try:
            if eff_timeout == 0.0:
                self._sock.setblocking(False)
            else:
                self._sock.settimeout(eff_timeout)

            data, _addr = self._sock.recvfrom(self.buffer_size)
            return data

        except (socket.timeout, TimeoutError):
            return None
        except BlockingIOError:
            return None
        except OSError as e:
            if self.is_closed:
                return None
            raise TransportError(f"UDP reception error on {self.local_address}: {e}")

    def close(self) -> None:
        """
        Closes socket and releases resources. Idempotent.
        """
        if not self.is_closed:
            self.is_closed = True
            try:
                self._sock.close()
            except Exception:
                pass


def create_local_udp_pair(
    host: str = "127.0.0.1",
    port_a: int = 0,
    port_b: int = 0
) -> Tuple[LocalUDPTransport, LocalUDPTransport]:
    """
    Creates a cross-linked pair of LocalUDPTransports (e.g. for testing producer-consumer).
    Transport A sends to B's bound port; Transport B sends to A's bound port.
    """
    transport_a = LocalUDPTransport(host=host, bind_port=port_a, target_port=1)
    actual_a_port = transport_a.bound_port

    transport_b = LocalUDPTransport(host=host, bind_port=port_b, target_port=actual_a_port)
    actual_b_port = transport_b.bound_port

    # Retarget A to B's port
    transport_a.target_address = (host, actual_b_port)
    transport_a._target_port = actual_b_port

    return transport_a, transport_b
