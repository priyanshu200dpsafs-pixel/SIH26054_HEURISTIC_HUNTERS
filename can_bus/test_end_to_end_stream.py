#!/usr/bin/env python3
"""
===============================================================================
PHASE 2: LIVE END-TO-END TELEMETRY VERIFICATION TEST SUITE
===============================================================================
Comprehensive test suite validating:
  1. Transport Abstraction & Localhost UDP (send/receive, timeout, shutdown, pairs)
  2. Simulation Wire Envelope & CRC-8 Integrity (packing, tampering detection)
  3. CAN Frame Encoder (validation of types, ranges, missing keys)
  4. CAN Frame Decoder (DBC decoding, 0x100 parity, sequence detection: dup/out-of-order/skip)
  5. End-to-End Stream (>100 CAN frames through Plant -> CAN -> Transport -> Decoder -> Twin)
  6. Fault Propagation Across All 5 Scenarios:
     - nominal
     - injector_clog
     - sensor_drift
     - oil_leak
     - cooling_duct_blockage
  7. Determinism: identical seed produces identical output events
===============================================================================
"""

import os
import sys
import unittest
import copy
import warnings
from pathlib import Path

warnings.filterwarnings("ignore", category=UserWarning)

# Resolve import paths
TEST_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = TEST_DIR.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "plant_model"))
sys.path.insert(0, str(PROJECT_ROOT / "can_bus"))
sys.path.insert(0, str(PROJECT_ROOT / "ml_layer"))

from can_bus.exceptions import (
    TransportError,
    FrameValidationError,
    SequenceError,
    DecodeError,
    TelemetryValidationError,
)
from can_bus.frame_envelope import (
    ENVELOPE_SIZE,
    ENVELOPE_MAGIC,
    compute_crc8,
    pack_frame_envelope,
    unpack_frame_envelope,
)
from can_bus.local_udp_transport import LocalUDPTransport, create_local_udp_pair
from can_bus.can_encoder import EngineCANEncoder
from can_bus.can_decoder import EngineCANDecoder
from can_bus.telemetry_event import TelemetryEvent
from run_mission_stream import MissionStreamOrchestrator


def get_nominal_telemetry_dict() -> dict:
    """Returns a valid nominal sensor telemetry dictionary."""
    return {
        "rpm": 5150.0,
        "throttle_pct": 75.0,
        "fuel_flow_gps": 2.65,
        "egt1": 710.0,
        "egt2": 715.0,
        "egt3": 718.0,
        "egt4": 712.0,
        "cht1": 162.0,
        "cht2": 163.0,
        "cht3": 165.0,
        "cht4": 164.0,
        "oil_press_bar": 2.65,
        "oil_temp_c": 82.0,
        "airspeed_mps": 42.0,
        "altitude_m": 1500.0,
    }


class TestTransport(unittest.TestCase):
    """Verifies the LocalUDPTransport layer."""

    def test_udp_send_and_receive_loopback(self):
        transport = LocalUDPTransport(port=50061, default_timeout=1.0)
        try:
            payload = b"TEST_CAN_FRAME_ENVELOPE_DATA"
            transport.send(payload)
            received = transport.receive(timeout=1.0)
            self.assertEqual(received, payload)
        finally:
            transport.close()

    def test_udp_receive_timeout(self):
        transport = LocalUDPTransport(port=50062, default_timeout=0.1)
        try:
            received = transport.receive(timeout=0.05)
            self.assertIsNone(received)
        finally:
            transport.close()

    def test_udp_shutdown(self):
        transport = LocalUDPTransport(port=50063)
        transport.close()
        self.assertTrue(transport.is_closed)
        with self.assertRaises(TransportError):
            transport.send(b"data")
        # Idempotent close
        transport.close()

    def test_udp_pair_communication(self):
        t_a, t_b = create_local_udp_pair()
        try:
            t_a.send(b"FROM_A_TO_B")
            self.assertEqual(t_b.receive(timeout=1.0), b"FROM_A_TO_B")

            t_b.send(b"FROM_B_TO_A")
            self.assertEqual(t_a.receive(timeout=1.0), b"FROM_B_TO_A")
        finally:
            t_a.close()
            t_b.close()


class TestFrameEnvelope(unittest.TestCase):
    """Verifies binary envelope packing, unpacking, and CRC-8 integrity."""

    def test_pack_unpack_roundtrip(self):
        payload_8b = bytes([0x11, 0x22, 0x33, 0x44, 0x55, 0x66, 0x77, 0x88])
        packet = pack_frame_envelope(
            sequence=12345,
            timestamp=45.678,
            arbitration_id=0x100,
            payload=payload_8b,
        )
        self.assertEqual(len(packet), ENVELOPE_SIZE)

        seq, ts, arb_id, dlc, payload = unpack_frame_envelope(packet)
        self.assertEqual(seq, 12345)
        self.assertAlmostEqual(ts, 45.678, places=3)
        self.assertEqual(arb_id, 0x100)
        self.assertEqual(dlc, 8)
        self.assertEqual(payload, payload_8b)

    def test_crc_tamper_rejection(self):
        packet = bytearray(pack_frame_envelope(1, 0.1, 0x100, b"12345678"))
        # Corrupt CRC byte
        packet[-1] ^= 0xFF
        with self.assertRaises(FrameValidationError) as ctx:
            unpack_frame_envelope(bytes(packet))
        self.assertIn("CRC mismatch", str(ctx.exception))

    def test_magic_rejection(self):
        packet = bytearray(pack_frame_envelope(1, 0.1, 0x100, b"12345678"))
        # Corrupt magic bytes 0..1
        packet[0] = 0x00
        packet[1] = 0x00
        # Recompute CRC so magic check triggers
        packet[-1] = compute_crc8(packet[:-1])
        with self.assertRaises(FrameValidationError) as ctx:
            unpack_frame_envelope(bytes(packet))
        self.assertIn("magic", str(ctx.exception).lower())

    def test_invalid_payload_length(self):
        with self.assertRaises(FrameValidationError):
            pack_frame_envelope(1, 0.1, 0x100, b"short")


class TestCANEncoder(unittest.TestCase):
    """Verifies signal validation and DBC encoding."""

    def setUp(self):
        self.encoder = EngineCANEncoder()

    def test_encoder_valid_signals(self):
        data = get_nominal_telemetry_dict()
        packets = self.encoder.encode_telemetry_cycle(data, timestamp=1.5)
        self.assertEqual(len(packets), 4)
        for pkt in packets:
            self.assertEqual(len(pkt), ENVELOPE_SIZE)

    def test_encoder_missing_signals(self):
        data = get_nominal_telemetry_dict()
        del data["rpm"]
        with self.assertRaises(TelemetryValidationError) as ctx:
            self.encoder.validate_and_normalize_telemetry(data)
        self.assertIn("Missing required telemetry signal 'rpm'", str(ctx.exception))

    def test_encoder_non_numeric_signal(self):
        data = get_nominal_telemetry_dict()
        data["throttle_pct"] = "seventy"
        with self.assertRaises(TelemetryValidationError) as ctx:
            self.encoder.validate_and_normalize_telemetry(data)
        self.assertIn("must be numeric", str(ctx.exception))

    def test_encoder_out_of_range_signal(self):
        data = get_nominal_telemetry_dict()
        data["oil_press_bar"] = 15.0  # DBC max is 10.0
        with self.assertRaises(TelemetryValidationError) as ctx:
            self.encoder.validate_and_normalize_telemetry(data)
        self.assertIn("out of range", str(ctx.exception))


class TestCANDecoder(unittest.TestCase):
    """Verifies frame decoding, 0x100 parity, and sequence error detection."""

    def setUp(self):
        self.encoder = EngineCANEncoder()
        self.decoder = EngineCANDecoder(strict_sequence=True)

    def test_decode_cycle(self):
        data = get_nominal_telemetry_dict()
        packets = self.encoder.encode_telemetry_cycle(data, timestamp=5.0)
        decoded = self.decoder.decode_cycle(packets)

        self.assertAlmostEqual(decoded["rpm"], data["rpm"], delta=1.0)
        self.assertAlmostEqual(decoded["throttle_pct"], data["throttle_pct"], delta=0.5)
        self.assertAlmostEqual(decoded["egt1"], data["egt1"], delta=0.5)
        self.assertAlmostEqual(decoded["cht1"], data["cht1"], delta=0.5)
        self.assertAlmostEqual(decoded["oil_press_bar"], data["oil_press_bar"], delta=0.01)

    def test_invalid_arbitration_id(self):
        # Pack frame with unknown ID 0x999
        bad_packet = pack_frame_envelope(10, 1.0, 0x999, b"12345678")
        with self.assertRaises(DecodeError) as ctx:
            self.decoder.decode_frame(bad_packet)
        self.assertIn("Unexpected CAN arbitration ID", str(ctx.exception))

    def test_duplicate_sequence_rejection(self):
        data = get_nominal_telemetry_dict()
        packets = self.encoder.encode_telemetry_cycle(data, timestamp=1.0)

        # First frame ok
        self.decoder.decode_frame(packets[0])
        # Re-sending same frame with same sequence must fail
        with self.assertRaises(SequenceError) as ctx:
            self.decoder.decode_frame(packets[0])
        self.assertIn("Duplicate frame sequence", str(ctx.exception))

    def test_out_of_order_sequence_rejection(self):
        data = get_nominal_telemetry_dict()
        packets = self.encoder.encode_telemetry_cycle(data, timestamp=1.0)

        self.decoder.decode_frame(packets[1])  # seq=1
        with self.assertRaises(SequenceError) as ctx:
            self.decoder.decode_frame(packets[0])  # seq=0 (out of order)
        self.assertIn("Out-of-order", str(ctx.exception))

    def test_skipped_sequence_detection(self):
        data = get_nominal_telemetry_dict()
        packets = self.encoder.encode_telemetry_cycle(data, timestamp=1.0)

        self.decoder.decode_frame(packets[0])  # seq=0
        # If strict sequence is True, skipping seq=1 to seq=2 must raise SequenceError
        with self.assertRaises(SequenceError) as ctx:
            self.decoder.decode_frame(packets[2])
        self.assertIn("Skipped", str(ctx.exception))


class TestEndToEndStream(unittest.TestCase):
    """
    Executes at least 100 CAN frames (25 full cycles = 100 frames) through the
    complete end-to-end pipeline without shortcuts.
    """

    def test_stream_at_least_100_frames(self):
        # 30 cycles @ 10 Hz = 120 CAN frames
        orchestrator = MissionStreamOrchestrator(
            duration_sec=3.0,
            rate_hz=10.0,
            fault_type="nominal",
            port=50070,
            realtime=False,
            json_output=False,
            quiet=True,
        )
        events = orchestrator.run()

        self.assertEqual(len(events), 30)
        self.assertEqual(orchestrator.total_frames_sent, 120)
        self.assertEqual(orchestrator.total_frames_received, 120)
        self.assertGreaterEqual(orchestrator.total_frames_sent, 100)

        # Validate that diagnostic outputs exist on each event
        for ev in events:
            self.assertTrue(ev.transport_ok)
            self.assertTrue(ev.frame_ok)
            self.assertGreater(ev.rpm, 1500.0)
            self.assertIn("rpm_exp", ev.observer_values)
            self.assertIn("rpm", ev.residuals)
            self.assertIn("rpm", ev.ewma_residuals)
            self.assertIsNotNone(ev.rul_hours)
            self.assertEqual(ev.fault_status, "NORMAL")


class TestFaultPropagation(unittest.TestCase):
    """
    Tests fault injection and verifies that:
      plant changes -> telemetry changes -> CAN carries changes -> decoder decodes ->
      observer responds -> residuals spike -> fault discriminator classifies.
    """

    def test_fault_nominal(self):
        orchestrator = MissionStreamOrchestrator(
            duration_sec=5.0,
            rate_hz=10.0,
            fault_type="nominal",
            port=50071,
            realtime=False,
            quiet=True,
        )
        events = orchestrator.run()
        # Nominal must maintain NORMAL status
        for ev in events:
            self.assertEqual(ev.fault_status, "NORMAL")
            self.assertEqual(ev.fault_classification, "NOMINAL")

    def test_fault_injector_clog(self):
        orchestrator = MissionStreamOrchestrator(
            duration_sec=15.0,
            rate_hz=10.0,
            fault_type="injector_clog",
            fault_severity=0.35,
            fault_cylinder=3,
            fault_start_sec=2.0,
            port=50072,
            realtime=False,
            quiet=True,
        )
        events = orchestrator.run()

        # Check that fault was detected
        final_events = events[-20:]
        alert_events = [ev for ev in final_events if ev.fault_status in ("CAUTION", "ALERT")]
        self.assertGreater(len(alert_events), 0, "Injector clog must trigger CAUTION or ALERT")

        last_event = events[-1]
        self.assertEqual(last_event.fault_classification, "PLANT_FAULT")
        self.assertEqual(last_event.fault_subtype, "INJECTOR_CLOG")
        self.assertEqual(last_event.fault_location, "CYLINDER_3")
        self.assertLess(last_event.rul_hours, 150.0, "RUL must degrade under active injector clog")

    def test_fault_sensor_drift(self):
        orchestrator = MissionStreamOrchestrator(
            duration_sec=20.0,
            rate_hz=10.0,
            fault_type="sensor_drift",
            fault_sensor="egt1",
            fault_severity=0.50,
            fault_start_sec=2.0,
            port=50073,
            realtime=False,
            quiet=True,
        )
        events = orchestrator.run()

        alert_events = [ev for ev in events if ev.fault_status in ("CAUTION", "ALERT")]
        self.assertGreater(len(alert_events), 0, "Sensor drift must trigger CAUTION or ALERT")

        last_event = events[-1]
        self.assertEqual(last_event.fault_classification, "SENSOR_FAULT")
        self.assertEqual(last_event.fault_subtype, "SENSOR_DRIFT")
        self.assertEqual(last_event.fault_location, "EGT_SENSOR_1")

    def test_fault_oil_leak(self):
        orchestrator = MissionStreamOrchestrator(
            duration_sec=20.0,
            rate_hz=10.0,
            fault_type="oil_leak",
            fault_severity=0.55,
            fault_start_sec=2.0,
            port=50074,
            realtime=False,
            quiet=True,
        )
        events = orchestrator.run()

        alert_events = [ev for ev in events if ev.fault_status in ("CAUTION", "ALERT")]
        self.assertGreater(len(alert_events), 0, "Oil leak must trigger CAUTION or ALERT")

        # In late phase of active leak with thermal spike, must isolate to OIL_LEAK
        oil_leak_events = [ev for ev in alert_events if ev.fault_subtype == "OIL_LEAK"]
        self.assertGreater(len(oil_leak_events), 0, "Multi-channel correlation must isolate OIL_LEAK")
        self.assertEqual(oil_leak_events[-1].fault_classification, "PLANT_FAULT")

    def test_fault_cooling_blockage(self):
        orchestrator = MissionStreamOrchestrator(
            duration_sec=20.0,
            rate_hz=10.0,
            fault_type="cooling_blockage",
            fault_severity=0.55,
            fault_start_sec=2.0,
            port=50075,
            realtime=False,
            quiet=True,
        )
        events = orchestrator.run()

        alert_events = [ev for ev in events if ev.fault_status in ("CAUTION", "ALERT")]
        self.assertGreater(len(alert_events), 0, "Cooling blockage must trigger CAUTION or ALERT")

        last_event = events[-1]
        self.assertEqual(last_event.fault_classification, "PLANT_FAULT")
        self.assertEqual(last_event.fault_subtype, "COOLING_DUCT_BLOCKAGE")


class TestDeterminism(unittest.TestCase):
    """Verifies that the same seed produces identical telemetry and diagnostic events."""

    def test_deterministic_seed_produces_identical_output(self):
        orch1 = MissionStreamOrchestrator(
            duration_sec=3.0,
            rate_hz=10.0,
            fault_type="injector_clog",
            fault_severity=0.35,
            random_seed=123,
            port=50076,
            realtime=False,
            quiet=True,
        )
        events1 = orch1.run()

        orch2 = MissionStreamOrchestrator(
            duration_sec=3.0,
            rate_hz=10.0,
            fault_type="injector_clog",
            fault_severity=0.35,
            random_seed=123,
            port=50077,
            realtime=False,
            quiet=True,
        )
        events2 = orch2.run()

        self.assertEqual(len(events1), len(events2))
        for e1, e2 in zip(events1, events2):
            self.assertEqual(e1.timestamp, e2.timestamp)
            self.assertEqual(e1.sequence, e2.sequence)
            self.assertEqual(e1.rpm, e2.rpm)
            self.assertEqual(e1.egt3, e2.egt3)
            self.assertEqual(e1.fault_status, e2.fault_status)
            self.assertEqual(e1.rul_hours, e2.rul_hours)


if __name__ == "__main__":
    unittest.main(verbosity=2)
