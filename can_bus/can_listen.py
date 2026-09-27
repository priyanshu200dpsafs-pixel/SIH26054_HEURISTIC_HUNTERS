#!/usr/bin/env python3
"""
===============================================================================
CAN BUS LISTENER & TELEMETRY DECODER (PHASE 2)
===============================================================================
Receives raw CAN frames from the virtual/SocketCAN bus and decodes them back
into engineering physical quantities using engine_telemetry.dbc.

Reconstructs the full 10 Hz UAV engine telemetry stream:
  - Engine RPM, Throttle %, Fuel Flow (g/s)
  - Exhaust Gas Temperatures (EGT Cyl 1..4 in °C)
  - Cylinder Head Temperatures (CHT Cyl 1..4 in °C)
  - Oil Pressure (bar), Oil Temperature (°C)
  - Airspeed (m/s), Altitude (m)
===============================================================================
"""

import os
import sys
import time
import logging
import argparse
from typing import Dict, Any, Optional, Callable, List

import can
import cantools
import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("CAN_Listener")

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DBC_PATH = os.path.join(SCRIPT_DIR, "engine_telemetry.dbc")


def load_engine_dbc(dbc_path: str = DBC_PATH) -> cantools.database.can.Database:
    """Loads and compiles the engine telemetry DBC database."""
    if not os.path.exists(dbc_path):
        raise FileNotFoundError(f"DBC file not found at: {dbc_path}")
    return cantools.database.load_file(dbc_path)


def get_can_bus(
    channel: str = "vcan0",
    bustype: Optional[str] = None
) -> can.BusABC:
    """Initializes CAN bus receiver matching broadcaster environment."""
    if bustype is not None:
        try:
            return can.Bus(channel=channel, interface=bustype)
        except Exception as e:
            logger.warning(f"Failed to open '{bustype}' bus on '{channel}': {e}. Falling back to virtual.")

    if sys.platform.startswith("linux"):
        try:
            bus = can.Bus(channel=channel, interface="socketcan")
            logger.info(f"Listening on Linux SocketCAN bus '{channel}'...")
            return bus
        except Exception as e:
            logger.warning(f"SocketCAN not accessible on '{channel}': {e}. Using virtual bus.")

    bus = can.Bus(channel=channel, interface="virtual")
    logger.info(f"Listening on python-can Virtual bus '{channel}'...")
    return bus


class EngineCANTelemetryDecoder:
    """
    Decodes asynchronous CAN frames into a unified, synchronized engine state.
    """
    def __init__(self, db: cantools.database.can.Database):
        self.db = db
        self.current_state: Dict[str, Any] = {
            "rpm": 0.0,
            "throttle_pct": 0.0,
            "fuel_flow_gps": 0.0,
            "status_flags": 0,
            "rolling_counter": 0,
            "egt1": 0.0, "egt2": 0.0, "egt3": 0.0, "egt4": 0.0,
            "cht1": 0.0, "cht2": 0.0, "cht3": 0.0, "cht4": 0.0,
            "oil_press_bar": 0.0,
            "oil_temp_c": 0.0,
            "airspeed_mps": 0.0,
            "altitude_m": 0.0,
            "last_update_ts": 0.0
        }
        self.msg_id_map = {
            256: "ENGINE_CORE_STATUS",
            257: "ENGINE_CYL_EGT",
            258: "ENGINE_CYL_CHT",
            259: "ENGINE_LUBRICATION_FLIGHT"
        }

    def decode_frame(self, frame: can.Message) -> Optional[Dict[str, Any]]:
        """
        Decodes a single incoming CAN frame and updates current state.
        Returns the decoded signal dictionary or None if unknown frame ID.
        """
        if frame.arbitration_id not in self.msg_id_map:
            return None

        msg_def = self.db.get_message_by_frame_id(frame.arbitration_id)
        decoded = msg_def.decode(frame.data)
        self.current_state["last_update_ts"] = frame.timestamp or time.time()

        if frame.arbitration_id == 256:  # ENGINE_CORE_STATUS
            self.current_state["rpm"] = round(float(decoded["Engine_RPM"]), 2)
            self.current_state["throttle_pct"] = round(float(decoded["Throttle_Pct"]), 1)
            self.current_state["fuel_flow_gps"] = round(float(decoded["Fuel_Flow_gps"]), 3)
            self.current_state["status_flags"] = int(decoded["Engine_Status_Flags"])
            self.current_state["rolling_counter"] = int(decoded["Rolling_Counter"])

        elif frame.arbitration_id == 257:  # ENGINE_CYL_EGT
            self.current_state["egt1"] = round(float(decoded["EGT_Cyl1"]), 1)
            self.current_state["egt2"] = round(float(decoded["EGT_Cyl2"]), 1)
            self.current_state["egt3"] = round(float(decoded["EGT_Cyl3"]), 1)
            self.current_state["egt4"] = round(float(decoded["EGT_Cyl4"]), 1)

        elif frame.arbitration_id == 258:  # ENGINE_CYL_CHT
            self.current_state["cht1"] = round(float(decoded["CHT_Cyl1"]), 1)
            self.current_state["cht2"] = round(float(decoded["CHT_Cyl2"]), 1)
            self.current_state["cht3"] = round(float(decoded["CHT_Cyl3"]), 1)
            self.current_state["cht4"] = round(float(decoded["CHT_Cyl4"]), 1)

        elif frame.arbitration_id == 259:  # ENGINE_LUBRICATION_FLIGHT
            self.current_state["oil_press_bar"] = round(float(decoded["Oil_Pressure_bar"]), 3)
            self.current_state["oil_temp_c"] = round(float(decoded["Oil_Temperature_C"]), 1)
            self.current_state["airspeed_mps"] = round(float(decoded["Airspeed_mps"]), 1)
            self.current_state["altitude_m"] = round(float(decoded["Altitude_m"]), 1)

        return decoded

    def get_snapshot(self) -> Dict[str, Any]:
        """Returns a copy of the current reconstructed telemetry state."""
        return dict(self.current_state)


def listen_and_decode(
    bus: can.BusABC,
    db: cantools.database.can.Database,
    max_frames: Optional[int] = None,
    timeout_sec: float = 5.0,
    callback: Optional[Callable[[Dict[str, Any]], None]] = None
) -> List[Dict[str, Any]]:
    """
    Listens for CAN frames on the bus, decodes them, and accumulates telemetry snapshots.
    """
    decoder = EngineCANTelemetryDecoder(db)
    received_snapshots = []
    frame_count = 0
    cycle_counter = 0

    logger.info("Awaiting CAN frames...")
    while True:
        if max_frames and frame_count >= max_frames:
            break

        msg = bus.recv(timeout=timeout_sec)
        if msg is None:
            logger.info("CAN receive timeout reached (no further messages on bus).")
            break

        decoded = decoder.decode_frame(msg)
        if decoded:
            frame_count += 1
            # Every 4 frames = 1 full telemetry cycle (0x100, 0x101, 0x102, 0x103)
            if frame_count % 4 == 0:
                cycle_counter += 1
                snapshot = decoder.get_snapshot()
                snapshot["cycle_id"] = cycle_counter
                received_snapshots.append(snapshot)
                if callback:
                    callback(snapshot)

    logger.info(f"Completed reception: {frame_count} frames decoded ({len(received_snapshots)} complete cycles).")
    return received_snapshots


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="UAV Engine CAN Bus Listener & Decoder")
    parser.add_argument("--channel", type=str, default="vcan0", help="CAN channel name (e.g. vcan0)")
    parser.add_argument("--interface", type=str, default=None, help="python-can interface (socketcan, virtual)")
    parser.add_argument("--count", type=int, default=40, help="Max frames to receive (default: 40 frames = 10 cycles)")
    parser.add_argument("--timeout", type=float, default=3.0, help="Timeout in seconds")
    args = parser.parse_args()

    db = load_engine_dbc()
    bus = get_can_bus(channel=args.channel, bustype=args.interface)

    def print_telemetry(st: Dict[str, Any]):
        print(f"Cycle {st.get('cycle_id', 0):03d} | "
              f"RPM: {st['rpm']:6.1f} | Th: {st['throttle_pct']:4.1f}% | "
              f"EGT: [{st['egt1']:5.1f}, {st['egt2']:5.1f}, {st['egt3']:5.1f}, {st['egt4']:5.1f}]°C | "
              f"CHT: [{st['cht1']:5.1f}, {st['cht2']:5.1f}, {st['cht3']:5.1f}, {st['cht4']:5.1f}]°C | "
              f"OilP: {st['oil_press_bar']:4.2f} bar | Alt: {st['altitude_m']:5.0f}m")

    snapshots = listen_and_decode(bus, db, max_frames=args.count, timeout_sec=args.timeout, callback=print_telemetry)
