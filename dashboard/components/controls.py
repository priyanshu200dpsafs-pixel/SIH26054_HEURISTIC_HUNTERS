#!/usr/bin/env python3
"""
Simulation & Mission Replay Controls Component (Phase 4)
SIH26054 — Explainable Digital Twin for MALE UAV Aero Piston Powerplant
"""

import streamlit as st
from typing import Callable, Optional
from dashboard.mission_controller import LiveMissionController
from dashboard.replay import MissionReplayController


def render_controls(
    mode: str,
    live_ctrl: LiveMissionController,
    replay_ctrl: MissionReplayController,
    on_live_step: Optional[Callable[[int], None]] = None,
    on_live_reset: Optional[Callable[[], None]] = None,
    on_replay_step: Optional[Callable[[int], None]] = None,
    on_replay_load: Optional[Callable[[str], None]] = None,
    on_replay_reset: Optional[Callable[[], None]] = None,
):
    """
    Renders simulation fault injection parameters and mission replay controls.
    """
    st.sidebar.markdown(
        """
        <div style="padding-bottom: 12px; border-bottom: 1px solid #334155; margin-bottom: 16px;">
            <h3 style="color: #f8fafc; font-size: 1.15rem; margin: 0 0 6px 0;">MISSION CONTROLS</h3>
            <div style="color: #94a3b8; font-size: 0.8rem;">Configuration & Pipeline Driver</div>
        </div>
        """,
        unsafe_allow_html=True
    )

    if mode == "LIVE":
        st.sidebar.markdown("#### ⚡ Fault Injection Simulation")

        # Scenario selection
        scenarios = {
            "Nominal Flight": "nominal",
            "Injector Clog (Cyl 2)": "injector_clog",
            "Oil System Leak": "oil_leak",
            "EGT Sensor Drift (Cyl 2)": "sensor_drift",
            "Cooling Duct Blockage": "cooling_duct_blockage",
        }
        selected_label = st.sidebar.selectbox(
            "Fault Scenario",
            options=list(scenarios.keys()),
            index=0,
            help="Select failure mode injected into physical powerplant plant model"
        )
        target_scenario = scenarios[selected_label]

        # Severity slider
        sev = st.sidebar.slider(
            "Fault Severity",
            min_value=0.0,
            max_value=1.0,
            value=float(live_ctrl.fault_severity),
            step=0.05,
            disabled=(target_scenario == "nominal"),
            help="Physical fault parameter scale [0.0 - 1.0]"
        )

        # Duration & Rate
        dur = st.sidebar.selectbox(
            "Mission Duration",
            options=[10.0, 20.0, 30.0, 60.0],
            index=2,
            format_func=lambda x: f"{int(x)} seconds ({int(x * 10)} cycles @ 10Hz)"
        )

        col_a, col_b = st.sidebar.columns(2)
        with col_a:
            if st.button("▶ Step 1 Frame", use_container_width=True):
                if on_live_step:
                    on_live_step(1)
        with col_b:
            if st.button("⏩ Step 10 Frames", use_container_width=True):
                if on_live_step:
                    on_live_step(10)

        if st.sidebar.button("⚡ Run Full Mission", type="primary", use_container_width=True):
            if on_live_step:
                remaining = len(live_ctrl.profile) - live_ctrl.current_step_idx
                on_live_step(max(1, remaining))

        if st.sidebar.button("🔄 Apply Config & Reset", use_container_width=True):
            live_ctrl.reset(
                fault_type=target_scenario,
                fault_severity=sev,
                duration_sec=dur,
                rate_hz=10.0
            )
            if on_live_reset:
                on_live_reset()
            st.rerun()

        # Display progress
        prog = live_ctrl.progress_fraction
        st.sidebar.progress(prog, text=f"Simulation Progress: {int(prog * 100)}% ({live_ctrl.current_step_idx}/{len(live_ctrl.profile)})")

    elif mode == "REPLAY":
        st.sidebar.markdown("#### 📼 Historical Mission Replay")

        # Available sorties from dataset
        sorties = replay_ctrl.get_available_sorties()
        if not sorties:
            st.sidebar.warning("No sortie CSV files found in data/")
            return

        file_opts = [s.get("filename") for s in sorties]
        current_file = replay_ctrl.selected_filename or file_opts[0]
        sel_idx = file_opts.index(current_file) if current_file in file_opts else 0

        chosen_file = st.sidebar.selectbox(
            "Select Sortie",
            options=file_opts,
            index=sel_idx,
            help="Historical mission flight records from data/ repository"
        )

        if chosen_file != replay_ctrl.selected_filename:
            replay_ctrl.load_sortie(chosen_file)
            if on_replay_load:
                on_replay_load(chosen_file)
            st.rerun()

        # Metadata
        if replay_ctrl.selected_metadata:
            meta = replay_ctrl.selected_metadata
            st.sidebar.caption(
                f"Sortie Type: **{meta.get('fault_type', 'unknown').upper()}** | "
                f"Split: **{meta.get('split', 'N/A')}** | "
                f"Duration: **{meta.get('duration_sec', 'N/A')}s**"
            )

        c1, c2 = st.sidebar.columns(2)
        with c1:
            if st.button("▶ Step 1 Row", use_container_width=True):
                if on_replay_step:
                    on_replay_step(1)
        with c2:
            if st.button("⏩ Step 10 Rows", use_container_width=True):
                if on_replay_step:
                    on_replay_step(10)

        if st.sidebar.button("⚡ Replay Entire Sortie", type="primary", use_container_width=True):
            if on_replay_step:
                rem = replay_ctrl.total_rows - replay_ctrl.current_idx
                on_replay_step(max(1, rem))

        if st.sidebar.button("🔄 Reset Replay", use_container_width=True):
            replay_ctrl.reset()
            if on_replay_reset:
                on_replay_reset()
            st.rerun()

        # Replay Progress
        r_prog = replay_ctrl.progress_fraction
        st.sidebar.progress(r_prog, text=f"Replay: {int(r_prog * 100)}% ({replay_ctrl.current_idx}/{replay_ctrl.total_rows})")
