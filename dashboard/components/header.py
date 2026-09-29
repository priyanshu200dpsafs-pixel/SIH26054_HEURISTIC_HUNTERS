#!/usr/bin/env python3
"""
Header Component (Phase 4)
SIH26054 — Explainable Digital Twin for MALE UAV Aero Piston Powerplant
"""

import streamlit as st
from typing import Optional
from dashboard.state_adapter import DashboardState


def render_header(state: Optional[DashboardState] = None, mode: str = "LIVE"):
    """
    Renders the Mission Control header banner with engine identification,
    simulation mode badge, and non-certified engineering prototype disclosure.
    """
    st.markdown(
        """
        <div style="background: linear-gradient(135deg, #1e293b 0%, #0f172a 100%);
                    padding: 18px 24px; border-radius: 8px; border-left: 6px solid #3b82f6;
                    margin-bottom: 20px; box-shadow: 0 4px 6px -1px rgba(0,0,0,0.3);">
            <div style="display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap;">
                <div>
                    <h2 style="color: #f8fafc; margin: 0; font-size: 1.6rem; letter-spacing: 0.05em; font-weight: 700;">
                        ROTAX 912 DIGITAL TWIN
                    </h2>
                    <div style="color: #94a3b8; font-size: 0.95rem; font-weight: 500; margin-top: 4px;">
                        REAL-TIME MISSION CONTROL & SCIENTIFIC PHM
                    </div>
                </div>
                <div style="text-align: right; margin-top: 8px;">
                    <span style="background-color: #1e3a8a; color: #93c5fd; padding: 5px 12px;
                                 border-radius: 4px; font-size: 0.85rem; font-weight: 600; letter-spacing: 0.05em;
                                 border: 1px solid #3b82f6;">
                        SIMULATION PROTOTYPE
                    </span>
                    <span style="background-color: #334155; color: #e2e8f0; padding: 5px 10px;
                                 border-radius: 4px; font-size: 0.85rem; margin-left: 8px; font-weight: 500;">
                        MODE: """ + mode + """
                    </span>
                </div>
            </div>
            <div style="margin-top: 12px; padding-top: 8px; border-top: 1px solid #334155;
                        color: #64748b; font-size: 0.75rem; letter-spacing: 0.02em;">
                SCIENTIFIC NOTICE: Software engineering prototype for research & validation.
                Not certified flight software (DO-178C / DO-254). Does not issue autonomous flight-control commands.
            </div>
        </div>
        """,
        unsafe_allow_html=True
    )
