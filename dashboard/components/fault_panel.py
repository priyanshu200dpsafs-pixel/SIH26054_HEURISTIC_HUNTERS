#!/usr/bin/env python3
"""
Fault Isolation & Diagnosis Component (Phase 4)
SIH26054 — Explainable Digital Twin for MALE UAV Aero Piston Powerplant
"""

import streamlit as st
from typing import Optional
from dashboard.state_adapter import DashboardState


def render_fault_panel(state: Optional[DashboardState]):
    """
    Renders the fault diagnosis panel showing isolated powerplant anomaly,
    discriminator confidence score, affected subsystem/cylinder, and severity.
    """
    st.markdown(
        """
        <div style="margin-bottom: 8px;">
            <span style="font-size: 0.95rem; font-weight: 700; color: #94a3b8; letter-spacing: 0.05em; text-transform: uppercase;">
                FAULT ISOLATION & CLASSIFICATION
            </span>
        </div>
        """,
        unsafe_allow_html=True
    )

    if state is None:
        st.info("Diagnostic subsystem awaiting incoming telemetry...")
        return

    fault_name = state.fault_display
    conf_pct = state.fault_confidence_pct
    subtype = state.fault_subtype
    location = state.fault_location
    is_fault = (state.fault_type != "nominal")

    badge_color = "#e74c3c" if is_fault else "#2ecc71"

    st.markdown(
        f"""
        <div style="background-color: #1e293b; padding: 18px 20px; border-radius: 8px;
                    border-left: 6px solid {badge_color}; margin-bottom: 12px;">
            <div style="display: flex; justify-content: space-between; align-items: baseline; margin-bottom: 6px;">
                <span style="font-size: 0.8rem; font-weight: 600; color: #94a3b8; text-transform: uppercase;">
                    ISOLATED POWERPLANT CONDITION
                </span>
                <span style="font-size: 0.8rem; font-weight: 700; color: {badge_color};">
                    {'ANOMALY DETECTED' if is_fault else 'NOMINAL OPERATION'}
                </span>
            </div>
            <div style="font-size: 1.8rem; font-weight: 800; color: {badge_color}; margin-bottom: 14px;">
                {fault_name}
            </div>
            <div style="display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px;
                        border-top: 1px solid #334155; padding-top: 12px;">
                <div>
                    <div style="font-size: 0.75rem; color: #94a3b8; text-transform: uppercase;">Discriminator Confidence</div>
                    <div style="font-size: 1.15rem; font-weight: 700; color: #f8fafc; font-family: monospace;">{conf_pct}</div>
                </div>
                <div>
                    <div style="font-size: 0.75rem; color: #94a3b8; text-transform: uppercase;">Fault Subtype</div>
                    <div style="font-size: 1.05rem; font-weight: 600; color: #cbd5e1;">{subtype}</div>
                </div>
                <div>
                    <div style="font-size: 0.75rem; color: #94a3b8; text-transform: uppercase;">Affected Location</div>
                    <div style="font-size: 1.05rem; font-weight: 600; color: #cbd5e1;">{location}</div>
                </div>
            </div>
        </div>
        """,
        unsafe_allow_html=True
    )
