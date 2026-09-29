#!/usr/bin/env python3
"""
Engine Telemetry Parameters Component (Phase 4)
SIH26054 — Explainable Digital Twin for MALE UAV Aero Piston Powerplant
"""

import streamlit as st
from typing import Optional
from dashboard.state_adapter import DashboardState


def render_engine_parameters(state: Optional[DashboardState]):
    """
    Renders live engine telemetry grid with actual supported channels,
    engineering units, and physical redline limit status.
    """
    st.markdown(
        """
        <div style="margin-bottom: 8px;">
            <span style="font-size: 0.95rem; font-weight: 700; color: #94a3b8; letter-spacing: 0.05em; text-transform: uppercase;">
                MEASURED ENGINE TELEMETRY
            </span>
        </div>
        """,
        unsafe_allow_html=True
    )

    if state is None:
        st.info("Awaiting telemetry data...")
        return

    # Row 1: Primary Operating State (RPM, Throttle, Fuel Flow)
    c1, c2, c3 = st.columns(3)
    with c1:
        st.metric(
            label="Engine Speed (RPM)",
            value=f"{state.rpm:.0f} RPM",
            help="Crankshaft rotational speed (Redline: 5800/5900 RPM)"
        )
    with c2:
        st.metric(
            label="Throttle Command",
            value=f"{state.throttle_pct:.1f} %",
            help="Commanded throttle position percentage"
        )
    with c3:
        st.metric(
            label="Fuel Mass Flow",
            value=f"{state.fuel_flow_gps:.3f} g/s",
            help="Total fuel consumption rate"
        )

    # Row 2: Lubrication System (Oil Pressure, Oil Temperature)
    c4, c5 = st.columns(2)
    with c4:
        # Check oil pressure status
        p_val = state.oil_press_bar
        p_color = "#2ecc71"
        if p_val < 1.5 or p_val > 7.0:
            p_color = "#e74c3c"
        elif p_val < 2.0:
            p_color = "#f39c12"

        st.metric(
            label="Oil Pressure (bar)",
            value=f"{p_val:.2f} bar",
            delta="Normal" if p_color == "#2ecc71" else ("Low Alert" if p_val < 1.5 else "Caution"),
            delta_color="normal" if p_color == "#2ecc71" else "inverse",
            help="Engine lubrication pressure (Normal: 2.2-5.0 bar, Redline: < 1.5 bar)"
        )
    with c5:
        t_val = state.oil_temp_c
        t_color = "#2ecc71"
        if t_val >= 125.0:
            t_color = "#e74c3c"
        elif t_val >= 118.0:
            t_color = "#f39c12"

        st.metric(
            label="Oil Temperature (°C)",
            value=f"{t_val:.1f} °C",
            delta="Normal" if t_color == "#2ecc71" else ("High Alert" if t_val >= 125.0 else "Caution"),
            delta_color="normal" if t_color == "#2ecc71" else "inverse",
            help="Oil sump temperature (Normal: < 110°C, Redline: >= 125°C)"
        )

    # Row 3: Exhaust Gas Temperatures (EGT 1 - 4 & Max)
    st.markdown(
        """
        <div style="font-size: 0.85rem; font-weight: 600; color: #94a3b8; margin-top: 10px; margin-bottom: 4px;">
            EXHAUST GAS TEMPERATURES (EGT)
        </div>
        """,
        unsafe_allow_html=True
    )
    e1, e2, e3, e4, e_max = st.columns(5)
    with e1:
        st.metric(label="Cylinder 1", value=f"{state.egt1:.1f} °C")
    with e2:
        st.metric(label="Cylinder 2", value=f"{state.egt2:.1f} °C")
    with e3:
        st.metric(label="Cylinder 3", value=f"{state.egt3:.1f} °C")
    with e4:
        st.metric(label="Cylinder 4", value=f"{state.egt4:.1f} °C")
    with e_max:
        st.metric(
            label="Max EGT",
            value=f"{state.max_egt:.1f} °C",
            delta="Redline >=950°C" if state.max_egt >= 950 else None,
            delta_color="inverse"
        )

    # Row 4: Cylinder Head Temperatures (CHT 1 - 4 & Max)
    st.markdown(
        """
        <div style="font-size: 0.85rem; font-weight: 600; color: #94a3b8; margin-top: 10px; margin-bottom: 4px;">
            CYLINDER HEAD TEMPERATURES (CHT)
        </div>
        """,
        unsafe_allow_html=True
    )
    ch1, ch2, ch3, ch4, ch_max = st.columns(5)
    with ch1:
        st.metric(label="Cylinder 1", value=f"{state.cht1:.1f} °C")
    with ch2:
        st.metric(label="Cylinder 2", value=f"{state.cht2:.1f} °C")
    with ch3:
        st.metric(label="Cylinder 3", value=f"{state.cht3:.1f} °C")
    with ch4:
        st.metric(label="Cylinder 4", value=f"{state.cht4:.1f} °C")
    with ch_max:
        st.metric(
            label="Max CHT",
            value=f"{state.max_cht:.1f} °C",
            delta="Redline >=250°C" if state.max_cht >= 250 else None,
            delta_color="inverse"
        )

    # Row 5: Flight Environment (Altitude, Airspeed)
    fl1, fl2 = st.columns(2)
    with fl1:
        st.metric(label="Barometric Altitude", value=f"{state.altitude_m:.1f} m")
    with fl2:
        st.metric(label="True Airspeed", value=f"{state.airspeed_mps:.1f} m/s")
