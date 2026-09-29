#!/usr/bin/env python3
"""
===============================================================================
AERO PISTON ENGINE DIGITAL TWIN: MISSION CONTROL DASHBOARD (PHASE 4)
===============================================================================
Main application entry point for the real-time mission control interface,
providing live telemetry visualization, fault injection controls, mission replay,
grounded causal explainability, and JSON state export.

SCIENTIFIC INTEGRITY & DESIGN PRINCIPLES:
  1. The UI is strictly an OBSERVATION & CONTROL SURFACE.
  2. The canonical DigitalTwinState is the single source of truth.
  3. ZERO duplicated physics calculations or diagnostic inferences in the UI.
  4. ZERO Large Language Models (LLMs) used for diagnosis or explanation.
  5. 100% read-only access to historical dataset files (data/*.csv).
  6. Zero false safety claims (no DO-178C/DO-254 or autonomous flight controls).
===============================================================================
"""

import os
import sys
import json
import streamlit as st

# Ensure project root is available in sys.path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from dashboard.session import (
    initialize_session_state,
    get_history,
    get_live_controller,
    get_replay_controller,
    update_latest_state,
)
from dashboard.components import (
    render_header,
    render_health_card,
    render_engine_parameters,
    render_rul_panel,
    render_residual_panel,
    render_fault_panel,
    render_explanation_panel,
    render_redline_panel,
    render_telemetry_health,
    render_timeline,
    render_charts,
    render_controls,
)


def apply_custom_styles():
    """Applies sleek aerospace mission-control dark mode styling."""
    st.markdown(
        """
        <style>
        /* Base page styling */
        .stApp {
            background-color: #0b1120;
            color: #f8fafc;
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
        }

        /* Sidebar styling */
        section[data-testid="stSidebar"] {
            background-color: #0f172a;
            border-right: 1px solid #1e293b;
        }

        /* Metric cards styling */
        div[data-testid="stMetric"] {
            background-color: #1e293b;
            border: 1px solid #334155;
            padding: 10px 14px;
            border-radius: 6px;
            box-shadow: 0 1px 3px rgba(0,0,0,0.2);
        }

        div[data-testid="stMetricLabel"] p {
            color: #94a3b8 !important;
            font-size: 0.78rem !important;
            font-weight: 600 !important;
            text-transform: uppercase !important;
            letter-spacing: 0.04em !important;
        }

        div[data-testid="stMetricValue"] div {
            color: #f8fafc !important;
            font-size: 1.3rem !important;
            font-weight: 700 !important;
            font-family: monospace !important;
        }

        /* Tabs styling */
        button[data-baseweb="tab"] {
            color: #94a3b8 !important;
            font-weight: 600 !important;
        }

        button[data-baseweb="tab"][aria-selected="true"] {
            color: #38bdf8 !important;
            border-bottom-color: #38bdf8 !important;
        }

        /* Buttons styling */
        .stButton > button {
            border-radius: 6px;
            font-weight: 600;
            transition: all 0.15s ease-in-out;
        }
        </style>
        """,
        unsafe_allow_html=True
    )


def main():
    st.set_page_config(
        page_title="Rotax 912 Mission Control",
        page_icon="✈️",
        layout="wide",
        initial_sidebar_state="expanded"
    )
    apply_custom_styles()
    initialize_session_state()

    # Sidebar: Mode Selector
    st.sidebar.markdown(
        """
        <div style="font-size: 0.85rem; font-weight: 700; color: #94a3b8; text-transform: uppercase; margin-bottom: 6px;">
            OPERATIONAL MODE
        </div>
        """,
        unsafe_allow_html=True
    )
    mode_options = ["Live Simulation (CAN/UDP Pipeline)", "Historical Mission Replay (Dataset CSV)"]
    current_mode_idx = 0 if st.session_state.mode == "LIVE" else 1
    selected_mode_label = st.sidebar.radio(
        "Mode",
        options=mode_options,
        index=current_mode_idx,
        label_visibility="collapsed"
    )
    new_mode = "LIVE" if "Live Simulation" in selected_mode_label else "REPLAY"
    if new_mode != st.session_state.mode:
        st.session_state.mode = new_mode
        st.rerun()

    mode = st.session_state.mode
    history = get_history()
    live_ctrl = get_live_controller()
    replay_ctrl = get_replay_controller()

    # Step Handlers
    def handle_live_step(count: int = 1):
        for _ in range(count):
            if live_ctrl.is_finished:
                break
            st_res = live_ctrl.step()
            if st_res is not None:
                update_latest_state(st_res)

    def handle_live_reset():
        history.clear()
        st.session_state.latest_state = None
        st.session_state.latest_adapted = None

    def handle_replay_step(count: int = 1):
        for _ in range(count):
            if replay_ctrl.is_finished:
                break
            st_res = replay_ctrl.step()
            if st_res is not None:
                update_latest_state(st_res)

    def handle_replay_load(filename: str):
        history.clear()
        st.session_state.latest_state = None
        st.session_state.latest_adapted = None

    def handle_replay_reset():
        history.clear()
        st.session_state.latest_state = None
        st.session_state.latest_adapted = None

    # Render Sidebar Controls
    render_controls(
        mode=mode,
        live_ctrl=live_ctrl,
        replay_ctrl=replay_ctrl,
        on_live_step=handle_live_step,
        on_live_reset=handle_live_reset,
        on_replay_step=handle_replay_step,
        on_replay_load=handle_replay_load,
        on_replay_reset=handle_replay_reset,
    )

    # Sidebar: JSON State Export & Inspection
    st.sidebar.markdown(
        """
        <div style="margin-top: 24px; padding-top: 14px; border-top: 1px solid #334155;">
            <div style="font-size: 0.85rem; font-weight: 700; color: #94a3b8; text-transform: uppercase; margin-bottom: 8px;">
                CANONICAL STATE EXPORT
            </div>
        </div>
        """,
        unsafe_allow_html=True
    )
    raw_state = st.session_state.latest_state
    if raw_state is not None:
        state_json = json.dumps(raw_state.to_dict(), indent=2)
        st.sidebar.download_button(
            label="💾 Download DigitalTwinState JSON",
            data=state_json,
            file_name=f"digital_twin_state_seq_{raw_state.sequence_number}.json",
            mime="application/json",
            use_container_width=True
        )
        with st.sidebar.expander("Inspect Raw JSON State", expanded=False):
            st.json(raw_state.to_dict())
    else:
        st.sidebar.caption("JSON export available when stream begins.")

    # Main Screen Rendering
    adapted_state = st.session_state.latest_adapted
    render_header(state=adapted_state, mode=mode)

    # Primary Health Card
    render_health_card(adapted_state)

    # 2-Column Split: Telemetry & Physical Boundaries (Left) | ML & Explainability (Right)
    left_col, right_col = st.columns([1, 1], gap="medium")

    with left_col:
        render_engine_parameters(adapted_state)
        st.markdown("<div style='height: 12px;'></div>", unsafe_allow_html=True)
        render_residual_panel(adapted_state)
        st.markdown("<div style='height: 12px;'></div>", unsafe_allow_html=True)
        render_redline_panel(adapted_state)

    with right_col:
        render_rul_panel(adapted_state)
        st.markdown("<div style='height: 12px;'></div>", unsafe_allow_html=True)
        render_fault_panel(adapted_state)
        st.markdown("<div style='height: 12px;'></div>", unsafe_allow_html=True)
        render_explanation_panel(adapted_state)
        st.markdown("<div style='height: 12px;'></div>", unsafe_allow_html=True)

        runtime_stats = None
        if mode == "LIVE" and live_ctrl.runtime:
            runtime_stats = {
                "frames_received": live_ctrl.runtime.total_frames_received,
                "frames_processed": live_ctrl.runtime.total_frames_processed,
                "invalid_frames": live_ctrl.runtime.total_invalid_frames,
                "sequence_gaps": live_ctrl.runtime.total_sequence_gaps,
                "avg_latency_ms": sum(live_ctrl.runtime.latencies_ms) / max(1, len(live_ctrl.runtime.latencies_ms))
            }
        elif mode == "REPLAY" and replay_ctrl.runtime:
            runtime_stats = {
                "frames_received": replay_ctrl.runtime.total_frames_received,
                "frames_processed": replay_ctrl.runtime.total_frames_processed,
                "invalid_frames": replay_ctrl.runtime.total_invalid_frames,
                "sequence_gaps": replay_ctrl.runtime.total_sequence_gaps,
                "avg_latency_ms": sum(replay_ctrl.runtime.latencies_ms) / max(1, len(replay_ctrl.runtime.latencies_ms))
            }
        render_telemetry_health(adapted_state, runtime_stats=runtime_stats)

    st.markdown("<div style='height: 18px;'></div>", unsafe_allow_html=True)

    # Full-Width Time-Series Charts & Chronological Timeline
    render_charts(history.to_dataframe())
    st.markdown("<div style='height: 14px;'></div>", unsafe_allow_html=True)
    render_timeline(history.get_timeline_events())


if __name__ == "__main__":
    main()
