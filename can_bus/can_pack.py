#!/usr/bin/env python3
"""
===============================================================================
CAN BUS TRANSMITTER & TELEMETRY PACKAGER (PHASE 2)
===============================================================================
Packs time-series telemetry from the aero engine plant model into standardized
aerospace CAN frames using cantools and python-can.

CAN Messages Encoded (defined in engine_telemetry.dbc):
  1. 0x100 (256): ENGINE_CORE_STATUS      (RPM, Throttle, Fuel Flow, Status, Counter)
  2. 0x101 (257): ENGINE_CYL_EGT          (EGT Cyl 1..4)
  3. 0x102 (258): ENGINE_CYL_CHT          (CHT Cyl 1..4)
  4. 0x103 (259): ENGINE_LUBRICATION_FLIGHT (Oil Press, Oil Temp, Airspeed, Altitude)

Bus Compatibility:
  - Linux / WSL2: native SocketCAN 'vcan0'
  - macOS / Windows: python-can 'virtual' bus interface
===============================================================================
"""

import os
import sys
import time
import logging
import argparse
from typing import Dict, Any, List, Tuple, Optional

import can
import cantools
import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("CAN_Packer")

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
    """
    Initializes a python-can bus instance.
    Auto-detects environment:
      - If bustype is specified, uses that bustype.
      - On Linux with SocketCAN available, tries socketcan.
      - On macOS / Windows / fallback, uses python-can's internal virtual bus.
    """
    if bustype is not None:
        try:
            return can.Bus(channel=channel, interface=bustype)
        except Exception as e:
            logger.warning(f"Failed to open '{bustype}' bus on '{channel}': {e}. Falling back to virtual.")

    # Try SocketCAN first if on Linux
    if sys.platform.startswith("linux"):
        try:
            bus = can.Bus(channel=channel, interface="socketcan")
            logger.info(f"Connected to Linux SocketCAN bus on channel '{channel}'.")
            return bus
        except Exception as e:
            logger.warning(f"SocketCAN not accessible on '{channel}': {e}. Using virtual bus.")

    # macOS / Windows or fallback virtual bus
    bus = can.Bus(channel=channel, interface="virtual")
    logger.info(f"Connected to python-can Virtual bus on channel '{channel}'.")
    return bus


def pack_telemetry_dict(
    telemetry: Dict[str, Any],
    db: cantools.database.can.Database,
    rolling_counter: int = 0
) -> List[can.Message]:
    """
    Encodes a single time-slice of engine telemetry into 4 CAN frames.

    Args:
      telemetry: Dict containing:
        rpm, throttle_pct, fuel_flow_gps,
        egt1, egt2, egt3, egt4,
        cht1, cht2, cht3, cht4,
        oil_press_bar, oil_temp_c, airspeed_mps, altitude_m
      db: compiled cantools database
      rolling_counter: 0..15 sequence counter

    Returns:
      List of 4 can.Message instances ready for transmission.
    """
    counter_4bit = int(rolling_counter) % 16
    checksum_4bit = (counter_4bit ^ int(telemetry.get("rpm", 0)) ^ int(telemetry.get("throttle_pct", 0))) % 16

    # Determine status flags
    # Bit 0: Warning active (EGT > 880 or CHT > 210 or OilP < 2.0)
    # Bit 1: Redline reached (EGT >= 940 or CHT >= 225)
    status_flags = 0
    egt_max = max(telemetry.get("egt1", 0), telemetry.get("egt2", 0), telemetry.get("egt3", 0), telemetry.get("egt4", 0))
    cht_max = max(telemetry.get("cht1", 0), telemetry.get("cht2", 0), telemetry.get("cht3", 0), telemetry.get("cht4", 0))
    oil_p = telemetry.get("oil_press_bar", 3.0)

    if egt_max >= 880.0 or cht_max >= 210.0 or oil_p < 2.0:
        status_flags |= 0x01
    if egt_max >= 940.0 or cht_max >= 225.0 or oil_p < 1.4:
        status_flags |= 0x02

    # Message 1: 0x100 ENGINE_CORE_STATUS
    msg_core = db.get_message_by_name("ENGINE_CORE_STATUS")
    data_core = msg_core.encode({
        "Engine_RPM": float(telemetry.get("rpm", 0.0)),
        "Throttle_Pct": float(telemetry.get("throttle_pct", 0.0)),
        "Fuel_Flow_gps": float(telemetry.get("fuel_flow_gps", 0.0)),
        "Engine_Status_Flags": int(status_flags),
        "Rolling_Counter": int(counter_4bit),
        "Checksum": int(checksum_4bit)
    })
    frame_core = can.Message(
        arbitration_id=msg_core.frame_id,
        data=data_core,
        is_extended_id=False
    )

    # Message 2: 0x101 ENGINE_CYL_EGT
    msg_egt = db.get_message_by_name("ENGINE_CYL_EGT")
    data_egt = msg_egt.encode({
        "EGT_Cyl1": float(telemetry.get("egt1", 0.0)),
        "EGT_Cyl2": float(telemetry.get("egt2", 0.0)),
        "EGT_Cyl3": float(telemetry.get("egt3", 0.0)),
        "EGT_Cyl4": float(telemetry.get("egt4", 0.0))
    })
    frame_egt = can.Message(
        arbitration_id=msg_egt.frame_id,
        data=data_egt,
        is_extended_id=False
    )

    # Message 3: 0x102 ENGINE_CYL_CHT
    msg_cht = db.get_message_by_name("ENGINE_CYL_CHT")
    data_cht = msg_cht.encode({
        "CHT_Cyl1": float(telemetry.get("cht1", 0.0)),
        "CHT_Cyl2": float(telemetry.get("cht2", 0.0)),
        "CHT_Cyl3": float(telemetry.get("cht3", 0.0)),
        "CHT_Cyl4": float(telemetry.get("cht4", 0.0))
    })
    frame_cht = can.Message(
        arbitration_id=msg_cht.frame_id,
        data=data_cht,
        is_extended_id=False
    )

    # Message 4: 0x103 ENGINE_LUBRICATION_FLIGHT
    msg_lube = db.get_message_by_name("ENGINE_LUBRICATION_FLIGHT")
    data_lube = msg_lube.encode({
        "Oil_Pressure_bar": float(telemetry.get("oil_press_bar", 0.0)),
        "Oil_Temperature_C": float(telemetry.get("oil_temp_c", 0.0)),
        "Airspeed_mps": float(telemetry.get("airspeed_mps", 0.0)),
        "Altitude_m": float(telemetry.get("altitude_m", 0.0))
    })
    frame_lube = can.Message(
        arbitration_id=msg_lube.frame_id,
        data=data_lube,
        is_extended_id=False
    )

    return [frame_core, frame_egt, frame_cht, frame_lube]


def transmit_run_dataframe(
    df: pd.DataFrame,
    bus: can.BusABC,
    db: cantools.database.can.Database,
    realtime_delay: bool = False,
    max_frames: Optional[int] = None
) -> int:
    """
    Transmits a pandas DataFrame of plant telemetry over the CAN bus.
    """
    total_sent = 0
    start_t = time.time()
    dt = 0.1  # 10 Hz

    for idx, row in df.iterrows():
        if max_frames and total_sent >= max_frames:
            break

        row_dict = row.to_dict()
        frames = pack_telemetry_dict(row_dict, db, rolling_counter=idx)

        for frame in frames:
            bus.send(frame)
            total_sent += 1

        if realtime_delay:
            # Emulate real-time 10 Hz spacing
            time.sleep(dt)

    elapsed = time.time() - start_t
    logger.info(f"Transmitted {total_sent} CAN frames ({total_sent // 4} cycles) in {elapsed:.2f}s.")
    return total_sent


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="UAV Engine CAN Bus Telemetry Packager")
    parser.add_argument("--csv", type=str, default="", help="Path to run CSV file to replay over CAN")
    parser.add_argument("--channel", type=str, default="vcan0", help="CAN channel name (e.g. vcan0)")
    parser.add_argument("--interface", type=str, default=None, help="python-can interface (socketcan, virtual)")
    parser.add_argument("--realtime", action="store_true", help="Transmit in real-time 10 Hz rate")
    parser.add_argument("--limit", type=int, default=100, help="Max cycles to transmit (default: 100 cycles = 400 frames)")
    args = parser.parse_args()

    db = load_engine_dbc()
    bus = get_can_bus(channel=args.channel, bustype=args.interface)

    if args.csv and os.path.exists(args.csv):
        df_input = pd.read_csv(args.csv)
        logger.info(f"Replaying {len(df_input)} timesteps from '{args.csv}'...")
    else:
        # Default: generate a quick 10s flight segment live from plant model
        sys.path.insert(0, os.path.join(SCRIPT_DIR, "..", "plant_model"))
        from engine_plant import generate_mission_profile, simulate_mission
        prof = generate_mission_profile(phases=[
            {"name": "test_climb", "duration_sec": 10.0, "start_alt_m": 100.0, "end_alt_m": 500.0,
             "start_throttle_pct": 80.0, "end_throttle_pct": 85.0, "start_airspeed_mps": 35.0, "end_airspeed_mps": 40.0}
        ], dt=0.1)
        df_input = simulate_mission(mission_profile=prof, faults=[], random_seed=42, dt=0.1)
        logger.info(f"Simulated {len(df_input)} live timesteps for CAN transmission.")

    if args.limit:
        df_input = df_input.iloc[:args.limit]

    transmit_run_dataframe(df_input, bus, db, realtime_delay=args.realtime)
    logger.info("CAN broadcast demonstration completed.")
