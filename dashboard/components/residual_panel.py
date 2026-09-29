#!/usr/bin/env python3
"""
Physics Residuals Component (Phase 4)
SIH26054 — Explainable Digital Twin for MALE UAV Aero Piston Powerplant
"""

import streamlit as st
from typing import Optional
from dashboard.state_adapter import DashboardState


def render_residual_panel(state: Optional[DashboardState]):
    """
    Renders the physics observer residual panel showing discrepancies between
    first-principles physics predictions and observed sensor values.
    """
    st.markdown(
        """
        <div style="margin-bottom: 8px;">
            <span style="font-size: 0.95rem; font-weight: 700; color: #94a3b8; letter-spacing: 0.05em; text-transform: uppercase;">
                PHYSICS OBSERVER RESIDUALS
            </span>
        </div>
        """,
        unsafe_allow_html=True
    )

    if state is None:
        st.info("Physics observer residuals awaiting incoming stream...")
        return

    res_stat = state.residual_status
    early_warn = state.early_warning
    res_mag = state.residual_magnitude

    status_colors = {
        "NORMAL": "#2ecc71",
        "CAUTION": "#f1c40f",
        "ALERT": "#e67e22",
        "ANOMALY": "#e74c3c",
    }
    s_col = status_colors.get(res_stat, "#2ecc71")

    # Residual Status Header
    c1, c2 = st.columns([1, 1])
    with c1:
        st.markdown(
            f"""
            <div style="background-color: #1e293b; padding: 12px 16px; border-radius: 6px;
                        border-left: 4px solid {s_col}; margin-bottom: 10px;">
                <div style="font-size: 0.75rem; color: #94a3b8; text-transform: uppercase;">Residual Status</div>
                <div style="font-size: 1.2rem; font-weight: 700; color: {s_col};">{res_stat}</div>
            </div>
            """,
            unsafe_allow_html=True
        )
    with c2:
        warn_text = "ACTIVE" if early_warn else "CLEARED"
        warn_col = "#e67e22" if early_warn else "#2ecc71"
        st.markdown(
            f"""
            <div style="background-color: #1e293b; padding: 12px 16px; border-radius: 6px;
                        border-left: 4px solid {warn_col}; margin-bottom: 10px;">
                <div style="font-size: 0.75rem; color: #94a3b8; text-transform: uppercase;">Early Warning (EWMA)</div>
                <div style="font-size: 1.2rem; font-weight: 700; color: {warn_col};">{warn_text}</div>
            </div>
            """,
            unsafe_allow_html=True
        )

    # Key Residual Channels
    r_cols = st.columns(4)
    with r_cols[0]:
        st.metric(
            label="Max EGT Residual",
            value=f"{state.max_egt_residual:+.1f} °C",
            help="Thermal departure from physics observer (Threshold: ±25.0 °C)"
        )
    with r_cols[1]:
        st.metric(
            label="Max CHT Residual",
            value=f"{state.max_cht_residual:+.1f} °C",
            help="Cylinder head temperature residual (Threshold: ±15.0 °C)"
        )
    with r_cols[2]:
        p_res = state.signed_residuals.get("oil_press_bar", 0.0)
        st.metric(
            label="Oil Press Residual",
            value=f"{p_res:+.2f} bar",
            help="Lubrication pressure residual (Threshold: ±0.40 bar)"
        )
    with r_cols[3]:
        rpm_res = state.signed_residuals.get("rpm", 0.0)
        st.metric(
            label="RPM Residual",
            value=f"{rpm_res:+.0f} RPM",
            help="Power delivery speed residual (Threshold: ±120 RPM)"
        )
