#!/usr/bin/env python3
"""
Primary Health Card Component (Phase 4)
SIH26054 — Explainable Digital Twin for MALE UAV Aero Piston Powerplant
"""

import streamlit as st
from typing import Optional
from dashboard.state_adapter import DashboardState


def render_health_card(state: Optional[DashboardState]):
    """
    Renders the primary mission health card with current operational condition,
    health index score, active fault, telemetry validity, and sequence integrity.
    """
    if state is None:
        st.markdown(
            """
            <div style="background-color: #1e293b; padding: 20px; border-radius: 8px;
                        border-left: 6px solid #95a5a6; color: #f8fafc; margin-bottom: 16px;">
                <h3 style="margin: 0 0 10px 0; font-size: 1.1rem; color: #94a3b8; text-transform: uppercase; letter-spacing: 0.05em;">
                    Engine Health
                </h3>
                <div style="font-size: 2rem; font-weight: 800; color: #95a5a6; margin-bottom: 12px;">
                    DIGITAL TWIN OFFLINE
                </div>
                <div style="color: #cbd5e1; font-size: 0.9rem;">Waiting for incoming telemetry stream...</div>
            </div>
            """,
            unsafe_allow_html=True
        )
        return

    # Extract state fields
    eng_state = state.engine_state
    state_color = state.engine_state_color
    health_index_disp = state.health_score_display
    fault_disp = state.fault_display
    telem_status = state.telemetry_status
    telem_color = state.telemetry_status_color
    seq_ok = state.sequence_ok
    seq_disp = "OK" if seq_ok else "GAPS DETECTED"
    seq_color = "#2ecc71" if seq_ok else "#e74c3c"
    ts_sec = state.timestamp_sec
    seq_num = state.sequence_number

    st.markdown(
        f"""
        <div style="background-color: #1e293b; padding: 22px 24px; border-radius: 8px;
                    border-left: 8px solid {state_color}; box-shadow: 0 4px 6px -1px rgba(0,0,0,0.3);
                    margin-bottom: 16px;">
            <div style="display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 12px;">
                <span style="font-size: 0.9rem; font-weight: 700; color: #94a3b8; letter-spacing: 0.08em; text-transform: uppercase;">
                    SIMULATION HEALTH STATE
                </span>
                <span style="font-size: 0.8rem; color: #64748b; font-family: monospace;">
                    T={ts_sec:.1f}s | SEQ #{seq_num}
                </span>
            </div>
            <div style="font-size: 2.4rem; font-weight: 800; color: {state_color}; letter-spacing: 0.04em; margin-bottom: 18px;">
                {eng_state}
            </div>
            <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap: 14px;
                        border-top: 1px solid #334155; padding-top: 16px;">
                <div>
                    <div style="font-size: 0.75rem; color: #94a3b8; text-transform: uppercase; font-weight: 600;">Health Index</div>
                    <div style="font-size: 1.25rem; font-weight: 700; color: #f8fafc; font-family: monospace;">{health_index_disp}</div>
                </div>
                <div>
                    <div style="font-size: 0.75rem; color: #94a3b8; text-transform: uppercase; font-weight: 600;">Active Fault</div>
                    <div style="font-size: 1.15rem; font-weight: 700; color: {'#e2e8f0' if eng_state == 'HEALTHY' else state_color};">
                        {fault_disp}
                    </div>
                </div>
                <div>
                    <div style="font-size: 0.75rem; color: #94a3b8; text-transform: uppercase; font-weight: 600;">Telemetry</div>
                    <div style="font-size: 1.15rem; font-weight: 700; color: {telem_color};">{telem_status}</div>
                </div>
                <div>
                    <div style="font-size: 0.75rem; color: #94a3b8; text-transform: uppercase; font-weight: 600;">Sequence</div>
                    <div style="font-size: 1.15rem; font-weight: 700; color: {seq_color}; font-family: monospace;">{seq_disp}</div>
                </div>
            </div>
        </div>
        """,
        unsafe_allow_html=True
    )
