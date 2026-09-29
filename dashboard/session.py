#!/usr/bin/env python3
"""
===============================================================================
AERO PISTON ENGINE DIGITAL TWIN: SESSION STATE MANAGER (PHASE 4)
===============================================================================
Coordinates Streamlit session state, controllers, and history buffers.
Guarantees reliable state persistence across Streamlit execution cycles.
===============================================================================
"""

from typing import Optional
import streamlit as st

from dashboard.mission_controller import LiveMissionController
from dashboard.replay import MissionReplayController
from dashboard.telemetry_history import TelemetryHistoryBuffer
from dashboard.state_adapter import DashboardStateAdapter, DashboardState
from digital_twin.state import DigitalTwinState


def initialize_session_state():
    """Initializes Streamlit session state containers if not yet allocated."""
    if "mode" not in st.session_state:
        st.session_state.mode = "LIVE"  # "LIVE" or "REPLAY"

    if "history" not in st.session_state:
        st.session_state.history = TelemetryHistoryBuffer(max_history_points=300)

    if "live_controller" not in st.session_state:
        st.session_state.live_controller = LiveMissionController(
            fault_type="nominal",
            fault_severity=0.5,
            duration_sec=30.0,
            rate_hz=10.0,
            random_seed=42
        )

    if "replay_controller" not in st.session_state:
        st.session_state.replay_controller = MissionReplayController()

    if "is_simulating" not in st.session_state:
        st.session_state.is_simulating = False

    if "latest_state" not in st.session_state:
        st.session_state.latest_state = None

    if "latest_adapted" not in st.session_state:
        st.session_state.latest_adapted = None


def get_history() -> TelemetryHistoryBuffer:
    """Returns the active TelemetryHistoryBuffer."""
    return st.session_state.history


def get_live_controller() -> LiveMissionController:
    """Returns the active LiveMissionController."""
    return st.session_state.live_controller


def get_replay_controller() -> MissionReplayController:
    """Returns the active MissionReplayController."""
    return st.session_state.replay_controller


def update_latest_state(state: DigitalTwinState):
    """Updates latest state in session and appends to history buffer."""
    st.session_state.latest_state = state
    st.session_state.latest_adapted = DashboardStateAdapter.adapt(state)
    st.session_state.history.add(state)
