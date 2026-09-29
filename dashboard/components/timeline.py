#!/usr/bin/env python3
"""
Mission Timeline Component (Phase 4)
SIH26054 — Explainable Digital Twin for MALE UAV Aero Piston Powerplant
"""

import streamlit as st
from typing import List, Dict, Any


def render_timeline(events: List[Dict[str, Any]]):
    """
    Renders chronological mission milestone timeline with actual runtime
    state transitions, anomalies, and fault isolation events.
    """
    st.markdown(
        """
        <div style="margin-bottom: 8px;">
            <span style="font-size: 0.95rem; font-weight: 700; color: #94a3b8; letter-spacing: 0.05em; text-transform: uppercase;">
                MISSION CHRONOLOGY & EVENT TIMELINE
            </span>
        </div>
        """,
        unsafe_allow_html=True
    )

    if not events:
        st.markdown(
            """
            <div style="background-color: #0f172a; padding: 12px 16px; border-radius: 6px;
                        border: 1px solid #334155; color: #94a3b8; font-size: 0.85rem;">
                No mission events logged yet. Start a simulation or replay to observe diagnostic milestones.
            </div>
            """,
            unsafe_allow_html=True
        )
        return

    type_colors = {
        "MISSION_START": "#3b82f6",
        "RESIDUAL_ANOMALY": "#f1c40f",
        "STATE_TRANSITION": "#f39c12",
        "FAULT_CLASSIFIED": "#e74c3c",
        "REDLINE_BREACH": "#dc2626",
    }

    # Render events in a neat scrollable container
    event_rows = ""
    for ev in reversed(events[-12:]):  # Show latest 12 events
        ev_type = ev.get("type", "EVENT")
        t_str = ev.get("time_str", "00:00.0")
        desc = ev.get("description", "")
        col = type_colors.get(ev_type, "#94a3b8")

        event_rows += f"""
        <div style="display: flex; align-items: baseline; padding: 8px 12px;
                    border-bottom: 1px solid #334155; font-size: 0.85rem;">
            <span style="font-family: monospace; font-weight: 700; color: #93c5fd; min-width: 65px;">
                {t_str}
            </span>
            <span style="background-color: rgba(255,255,255,0.06); color: {col}; padding: 1px 6px;
                         border-radius: 4px; font-size: 0.72rem; font-weight: 700; border: 1px solid {col};
                         margin: 0 10px; min-width: 110px; text-align: center;">
                {ev_type.replace('_', ' ')}
            </span>
            <span style="color: #e2e8f0; flex-grow: 1;">
                {desc}
            </span>
        </div>
        """

    st.markdown(
        f"""
        <div style="background-color: #0f172a; border-radius: 6px; border: 1px solid #334155;
                    max-height: 240px; overflow-y: auto;">
            {event_rows}
        </div>
        """,
        unsafe_allow_html=True
    )
