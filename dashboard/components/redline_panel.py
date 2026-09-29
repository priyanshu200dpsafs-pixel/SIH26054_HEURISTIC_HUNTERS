#!/usr/bin/env python3
"""
Physical Operating Limits & Redlines Component (Phase 4)
SIH26054 — Explainable Digital Twin for MALE UAV Aero Piston Powerplant
"""

import streamlit as st
from typing import Optional
from dashboard.state_adapter import DashboardState


def render_redline_panel(state: Optional[DashboardState]):
    """
    Renders physical boundary status using authoritative Rotax 912 limits from
    the HealthStateEngine runtime (Normal, Caution, Alert, Redline).
    """
    st.markdown(
        """
        <div style="margin-bottom: 8px;">
            <span style="font-size: 0.95rem; font-weight: 700; color: #94a3b8; letter-spacing: 0.05em; text-transform: uppercase;">
                PHYSICAL OPERATING BOUNDARIES (ROTAX 912)
            </span>
        </div>
        """,
        unsafe_allow_html=True
    )

    if state is None:
        st.info("Physical operating boundaries awaiting telemetry stream...")
        return

    redline_stat = state.redline_status
    stat_color = state.redline_status_color
    details = state.redline_details or {}

    st.markdown(
        f"""
        <div style="background-color: #1e293b; padding: 14px 18px; border-radius: 6px;
                    border-left: 6px solid {stat_color}; margin-bottom: 12px;
                    display: flex; justify-content: space-between; align-items: center;">
            <div>
                <span style="font-size: 0.8rem; color: #94a3b8; text-transform: uppercase; font-weight: 600;">
                    Overall Boundary Status:
                </span>
                <span style="font-size: 1.15rem; font-weight: 700; color: {stat_color}; margin-left: 8px;">
                    {redline_stat}
                </span>
            </div>
            <div style="font-size: 0.85rem; color: #cbd5e1;">
                {'Breaches: ' + ', '.join(f'{k}: {v:.1f}' for k, v in details.items()) if details else 'All parameters within operational envelope'}
            </div>
        </div>
        """,
        unsafe_allow_html=True
    )

    # Comparison Grid: Parameter | Current | Caution | Alert | Redline | Status
    params = [
        {
            "name": "Exhaust Gas Temp (Max EGT)",
            "current": f"{state.max_egt:.1f} °C",
            "caution": "880.0 °C",
            "alert": "940.0 °C",
            "redline": "950.0 °C",
            "breached": "egt_redline" in details or "egt_alert" in details or "egt_caution" in details,
            "status": "REDLINE" if state.max_egt >= 950 else ("ALERT" if state.max_egt >= 940 else ("CAUTION" if state.max_egt >= 880 else "NORMAL"))
        },
        {
            "name": "Cylinder Head Temp (Max CHT)",
            "current": f"{state.max_cht:.1f} °C",
            "caution": "200.0 °C",
            "alert": "240.0 °C",
            "redline": "250.0 °C",
            "breached": "cht_redline" in details or "cht_alert" in details or "cht_caution" in details,
            "status": "REDLINE" if state.max_cht >= 250 else ("ALERT" if state.max_cht >= 240 else ("CAUTION" if state.max_cht >= 200 else "NORMAL"))
        },
        {
            "name": "Oil Pressure (Minimum)",
            "current": f"{state.oil_press_bar:.2f} bar",
            "caution": "2.20 bar",
            "alert": "1.80 bar",
            "redline": "1.50 bar",
            "breached": "oil_press_redline" in details or "oil_press_alert" in details or "oil_press_caution" in details,
            "status": "REDLINE" if state.oil_press_bar <= 1.50 else ("ALERT" if state.oil_press_bar <= 1.80 else ("CAUTION" if state.oil_press_bar <= 2.20 else "NORMAL"))
        },
        {
            "name": "Oil Temperature (Maximum)",
            "current": f"{state.oil_temp_c:.1f} °C",
            "caution": "110.0 °C",
            "alert": "118.0 °C",
            "redline": "125.0 °C",
            "breached": "oil_temp_redline" in details or "oil_temp_alert" in details or "oil_temp_caution" in details,
            "status": "REDLINE" if state.oil_temp_c >= 125.0 else ("ALERT" if state.oil_temp_c >= 118.0 else ("CAUTION" if state.oil_temp_c >= 110.0 else "NORMAL"))
        },
        {
            "name": "Crankshaft Speed (RPM)",
            "current": f"{state.rpm:.0f} RPM",
            "caution": "5500 RPM",
            "alert": "5800 RPM",
            "redline": "5900 RPM",
            "breached": "rpm_redline" in details,
            "status": "REDLINE" if state.rpm >= 5900 else ("ALERT" if state.rpm >= 5800 else ("CAUTION" if state.rpm >= 5500 else "NORMAL"))
        }
    ]

    col_colors = {
        "NORMAL": "#2ecc71",
        "CAUTION": "#f1c40f",
        "ALERT": "#e67e22",
        "REDLINE": "#e74c3c"
    }

    # Format into a clean table
    rows_html = ""
    for p in params:
        c_code = col_colors.get(p["status"], "#2ecc71")
        rows_html += f"""
        <tr style="border-bottom: 1px solid #334155;">
            <td style="padding: 8px 12px; color: #f8fafc; font-weight: 500;">{p['name']}</td>
            <td style="padding: 8px 12px; font-family: monospace; font-weight: 700; color: #f8fafc;">{p['current']}</td>
            <td style="padding: 8px 12px; color: #94a3b8; font-size: 0.85rem;">{p['caution']}</td>
            <td style="padding: 8px 12px; color: #94a3b8; font-size: 0.85rem;">{p['alert']}</td>
            <td style="padding: 8px 12px; color: #f87171; font-size: 0.85rem; font-weight: 600;">{p['redline']}</td>
            <td style="padding: 8px 12px;">
                <span style="background-color: rgba(255,255,255,0.06); color: {c_code}; padding: 2px 8px;
                             border-radius: 4px; font-size: 0.75rem; font-weight: 700; border: 1px solid {c_code};">
                    {p['status']}
                </span>
            </td>
        </tr>
        """

    st.markdown(
        f"""
        <div style="background-color: #0f172a; border-radius: 6px; border: 1px solid #334155; overflow-x: auto;">
            <table style="width: 100%; border-collapse: collapse; text-align: left; font-size: 0.85rem;">
                <thead>
                    <tr style="background-color: #1e293b; color: #94a3b8; text-transform: uppercase; font-size: 0.75rem;">
                        <th style="padding: 10px 12px;">Parameter</th>
                        <th style="padding: 10px 12px;">Current</th>
                        <th style="padding: 10px 12px;">Caution</th>
                        <th style="padding: 10px 12px;">Alert</th>
                        <th style="padding: 10px 12px;">Redline</th>
                        <th style="padding: 10px 12px;">Condition</th>
                    </tr>
                </thead>
                <tbody>
                    {rows_html}
                </tbody>
            </table>
        </div>
        """,
        unsafe_allow_html=True
    )
