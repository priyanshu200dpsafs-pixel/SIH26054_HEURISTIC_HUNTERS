#!/usr/bin/env python3
"""
Time-Series Visualization Charts Component (Phase 4)
SIH26054 — Explainable Digital Twin for MALE UAV Aero Piston Powerplant
"""

import streamlit as st
import pandas as pd


def render_charts(df_history: pd.DataFrame):
    """
    Renders real-time telemetry, prognostic, and physics residual charts.
    All charts consume existing history buffer without recomputing physics or ML.
    """
    st.markdown(
        """
        <div style="margin-bottom: 8px;">
            <span style="font-size: 0.95rem; font-weight: 700; color: #94a3b8; letter-spacing: 0.05em; text-transform: uppercase;">
                REAL-TIME TELEMETRY & PROGNOSTIC TIME-SERIES
            </span>
        </div>
        """,
        unsafe_allow_html=True
    )

    if df_history.empty or len(df_history) < 2:
        st.info("Accumulating telemetry data points for time-series charts...")
        return

    # Use timestamp as index for smooth time-series plotting
    df_plot = df_history.copy()
    df_plot = df_plot.set_index("timestamp")

    # Tabs for organized viewing
    tab1, tab2, tab3 = st.tabs([
        "Core Engine Telemetry",
        "Prognostics & Health Index",
        "Physics Observer Residuals"
    ])

    with tab1:
        # 1. RPM & Oil Pressure
        c1, c2 = st.columns(2)
        with c1:
            st.caption("Engine Speed (RPM)")
            st.line_chart(df_plot[["rpm"]], height=220)
        with c2:
            st.caption("Oil Pressure (bar)")
            st.line_chart(df_plot[["oil_press_bar"]], height=220)

        # 2. Exhaust Gas Temperatures (EGT)
        st.caption("Exhaust Gas Temperatures (°C) — Cylinders 1-4 & Max")
        egt_cols = [c for c in ["egt1", "egt2", "egt3", "egt4", "max_egt"] if c in df_plot.columns]
        st.line_chart(df_plot[egt_cols], height=240)

        # 3. Cylinder Head Temperatures & Oil Temp
        c3, c4 = st.columns(2)
        with c3:
            st.caption("Cylinder Head Temperatures (°C)")
            cht_cols = [c for c in ["cht1", "cht2", "cht3", "cht4"] if c in df_plot.columns]
            st.line_chart(df_plot[cht_cols], height=220)
        with c4:
            st.caption("Oil Temperature (°C)")
            st.line_chart(df_plot[["oil_temp_c"]], height=220)

    with tab2:
        # Prognostics & Health
        p1, p2 = st.columns(2)
        with p1:
            st.caption("Remaining Useful Life (RUL hours) & Uncertainty")
            rul_cols = [c for c in ["rul_hours", "rul_q10", "rul_q90"] if c in df_plot.columns and df_plot[c].notna().any()]
            if rul_cols:
                st.line_chart(df_plot[rul_cols], height=240)
            else:
                st.caption("RUL data unavailable or uninitialized.")
        with p2:
            st.caption("Simulation Health Index (0 - 100)")
            if "health_index" in df_plot.columns and df_plot["health_index"].notna().any():
                st.line_chart(df_plot[["health_index"]], height=240)
            else:
                st.caption("Health index uninitialized.")

    with tab3:
        # Residuals
        r1, r2 = st.columns(2)
        with r1:
            st.caption("Thermal Residuals (°C) — Max EGT & Max CHT")
            res_thermal = [c for c in ["max_egt_residual", "max_cht_residual"] if c in df_plot.columns]
            st.line_chart(df_plot[res_thermal], height=240)
        with r2:
            st.caption("Mechanical Residuals — Oil Press & RPM")
            res_mech = [c for c in ["oil_press_residual", "rpm_residual"] if c in df_plot.columns]
            st.line_chart(df_plot[res_mech], height=240)
