#!/usr/bin/env python3
"""
Remaining Useful Life (RUL) Prognostics Component (Phase 4)
SIH26054 — Explainable Digital Twin for MALE UAV Aero Piston Powerplant
"""

import streamlit as st
from typing import Optional
from dashboard.state_adapter import DashboardState


def render_rul_panel(state: Optional[DashboardState]):
    """
    Renders the dedicated prognostics panel with point RUL estimate,
    Q10/Q90 uncertainty bounds, prognostic damage state, and required
    scientific Category C heuristic/synthetic degradation disclosure.
    """
    st.markdown(
        """
        <div style="margin-bottom: 8px;">
            <span style="font-size: 0.95rem; font-weight: 700; color: #94a3b8; letter-spacing: 0.05em; text-transform: uppercase;">
                PROGNOSTICS & REMAINING USEFUL LIFE (RUL)
            </span>
        </div>
        """,
        unsafe_allow_html=True
    )

    if state is None:
        st.info("Prognostic estimations awaiting runtime stream...")
        return

    rul_disp = state.rul_display
    q10_disp = state.rul_q10_display
    q90_disp = state.rul_q90_display
    damage_state = state.damage_state

    # Visual damage state badge color
    damage_colors = {
        "HEALTHY": "#2ecc71",
        "INCIPIENT_DEGRADATION": "#f1c40f",
        "PROGRESSIVE_DEGRADATION": "#f39c12",
        "CRITICAL_CONDITION": "#e74c3c",
        "UNKNOWN": "#95a5a6",
    }
    dmg_color = damage_colors.get(damage_state, "#95a5a6")

    # Display primary RUL box
    st.markdown(
        f"""
        <div style="background-color: #1e293b; padding: 18px 20px; border-radius: 8px;
                    border: 1px solid #334155; margin-bottom: 12px;">
            <div style="display: flex; justify-content: space-between; align-items: baseline; margin-bottom: 8px;">
                <span style="font-size: 0.8rem; font-weight: 600; color: #94a3b8; text-transform: uppercase;">
                    POINT ESTIMATE (RUL)
                </span>
                <span style="font-size: 0.8rem; font-weight: 700; color: {dmg_color}; padding: 2px 8px;
                             border-radius: 4px; background-color: rgba(255,255,255,0.06); border: 1px solid {dmg_color};">
                    {damage_state.replace('_', ' ')}
                </span>
            </div>
            <div style="font-size: 2.2rem; font-weight: 800; color: #f8fafc; font-family: monospace; margin-bottom: 12px;">
                {rul_disp}
            </div>
            <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 10px;
                        border-top: 1px solid #334155; padding-top: 10px;">
                <div>
                    <span style="font-size: 0.75rem; color: #94a3b8;">10th Percentile (Q10):</span>
                    <span style="font-size: 0.95rem; font-weight: 700; color: #cbd5e1; font-family: monospace; margin-left: 6px;">
                        {q10_disp}
                    </span>
                </div>
                <div>
                    <span style="font-size: 0.75rem; color: #94a3b8;">90th Percentile (Q90):</span>
                    <span style="font-size: 0.95rem; font-weight: 700; color: #cbd5e1; font-family: monospace; margin-left: 6px;">
                        {q90_disp}
                    </span>
                </div>
            </div>
        </div>
        <div style="background-color: #0f172a; padding: 10px 14px; border-radius: 6px;
                    border-left: 3px solid #64748b; font-size: 0.75rem; color: #94a3b8; line-height: 1.4;">
            <strong>SCIENTIFIC BASIS (Category C):</strong> RUL is a model-based estimate under simulated
            degradation conditions (hybrid heuristic/synthetic degradation countdown);
            it is not an empirical metallurgical wear-life measurement or certified component retirement limit.
        </div>
        """,
        unsafe_allow_html=True
    )
