#!/usr/bin/env python3
"""
Telemetry & System Health Component (Phase 4)
SIH26054 — Explainable Digital Twin for MALE UAV Aero Piston Powerplant
"""

import streamlit as st
from typing import Optional, Dict, Any
from dashboard.state_adapter import DashboardState


def render_telemetry_health(
    state: Optional[DashboardState],
    runtime_stats: Optional[Dict[str, Any]] = None
):
    """
    Renders telemetry transport and processing health counters:
    frames received, processed, invalid, sequence continuity, and compute latency.
    """
    st.markdown(
        """
        <div style="margin-bottom: 8px;">
            <span style="font-size: 0.95rem; font-weight: 700; color: #94a3b8; letter-spacing: 0.05em; text-transform: uppercase;">
                TELEMETRY & RUNTIME HEALTH
            </span>
        </div>
        """,
        unsafe_allow_html=True
    )

    if state is None:
        st.info("System health awaiting active telemetry connection...")
        return

    # Extract statistics if available
    stats = runtime_stats or {}
    frames_rx = stats.get("frames_received", state.sequence_number)
    frames_proc = stats.get("frames_processed", state.cycle_id or state.sequence_number)
    invalid_frames = stats.get("invalid_frames", 0 if state.sequence_ok else 1)
    seq_gaps = stats.get("sequence_gaps", 0)
    avg_latency = stats.get("avg_latency_ms", state.processing_time_ms)

    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.metric(
            label="Frames Received",
            value=f"{frames_rx:,}",
            help="Total CAN/UDP frames captured by transport"
        )
    with c2:
        st.metric(
            label="Frames Processed",
            value=f"{frames_proc:,}",
            help="Total frames processed through DigitalTwinRuntime"
        )
    with c3:
        st.metric(
            label="Sequence Gaps",
            value=f"{seq_gaps}",
            delta="Normal" if seq_gaps == 0 else "Gaps Detected",
            delta_color="normal" if seq_gaps == 0 else "inverse",
            help="Discontinuities detected in CAN sequence counter"
        )
    with c4:
        st.metric(
            label="Processing Latency",
            value=f"{state.processing_time_ms:.1f} ms",
            help=f"Runtime processing cycle execution time (Mean: {avg_latency:.1f} ms)"
        )

    # Telemetry Quality Banner
    t_status = state.telemetry_status
    t_color = state.telemetry_status_color
    st.markdown(
        f"""
        <div style="background-color: #0f172a; padding: 8px 12px; border-radius: 4px;
                    border: 1px solid #334155; margin-top: 8px; display: flex;
                    justify-content: space-between; font-size: 0.8rem;">
            <span style="color: #94a3b8;">Transport Quality: <strong style="color: {t_color};">{t_status}</strong></span>
            <span style="color: #94a3b8;">Invalid Frame Count: <strong style="color: {'#2ecc71' if invalid_frames == 0 else '#e74c3c'};">{invalid_frames}</strong></span>
            <span style="color: #94a3b8;">Deterministic Rate: <strong style="color: #f8fafc;">10.0 Hz</strong></span>
        </div>
        """,
        unsafe_allow_html=True
    )
