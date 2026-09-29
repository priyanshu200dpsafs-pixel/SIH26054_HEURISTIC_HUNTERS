#!/usr/bin/env python3
"""
Explainability & Grounded Evidence Component (Phase 4)
SIH26054 — Explainable Digital Twin for MALE UAV Aero Piston Powerplant
"""

import streamlit as st
from typing import Optional
from dashboard.state_adapter import DashboardState


def render_explanation_panel(state: Optional[DashboardState]):
    """
    Renders the grounded causal explanation panel displaying exact runtime EvidenceItems,
    multivariate physical couplings, and diagnostic basis without LLM generation.
    """
    st.markdown(
        """
        <div style="margin-bottom: 8px;">
            <span style="font-size: 0.95rem; font-weight: 700; color: #94a3b8; letter-spacing: 0.05em; text-transform: uppercase;">
                WHY WAS THIS DIAGNOSIS MADE? (EXPLAINABILITY)
            </span>
        </div>
        """,
        unsafe_allow_html=True
    )

    if state is None:
        st.info("Causal explanations awaiting telemetry frames...")
        return

    summary = state.explanation_summary
    evidence_items = state.evidence_items
    indicators = state.physics_indicators
    basis = state.diagnostic_basis

    # Summary box
    st.markdown(
        f"""
        <div style="background-color: #1e293b; padding: 14px 18px; border-radius: 6px;
                    border-left: 4px solid #3b82f6; margin-bottom: 12px;">
            <div style="font-size: 0.75rem; color: #94a3b8; text-transform: uppercase; font-weight: 600;">
                Diagnostic Summary
            </div>
            <div style="font-size: 1.05rem; font-weight: 600; color: #f8fafc; margin-top: 4px;">
                {summary}
            </div>
        </div>
        """,
        unsafe_allow_html=True
    )

    # Grounded Evidence Items
    if evidence_items:
        st.markdown(
            """
            <div style="font-size: 0.85rem; font-weight: 600; color: #cbd5e1; margin-bottom: 8px;">
                Causal Physical Evidence Items:
            </div>
            """,
            unsafe_allow_html=True
        )
        for idx, item in enumerate(evidence_items, 1):
            feat = item.get("feature", "unknown").replace("_", " ").upper()
            val = item.get("value", 0.0)
            unit = item.get("unit", "")
            direction = item.get("direction", "abnormal")

            sign = "+" if isinstance(val, (int, float)) and val > 0 else ""
            val_str = f"{sign}{val:.1f} {unit}".strip()

            st.markdown(
                f"""
                <div style="background-color: #0f172a; border: 1px solid #334155; padding: 10px 14px;
                            border-radius: 6px; margin-bottom: 6px; display: flex;
                            justify-content: space-between; align-items: center;">
                    <div>
                        <span style="color: #60a5fa; font-weight: 700; margin-right: 8px;">{idx}.</span>
                        <span style="color: #e2e8f0; font-weight: 600;">{feat}</span>
                        <span style="color: #94a3b8; font-size: 0.85rem; margin-left: 6px;">({direction})</span>
                    </div>
                    <div style="font-family: monospace; font-weight: 700; color: #f8fafc; font-size: 0.95rem;">
                        {val_str}
                    </div>
                </div>
                """,
                unsafe_allow_html=True
            )
    else:
        st.markdown(
            """
            <div style="background-color: #0f172a; padding: 10px 14px; border-radius: 6px;
                        border: 1px solid #334155; color: #94a3b8; font-size: 0.85rem;">
                No anomalous physical evidence detected. All observer residuals remain within baseline statistical bounds.
            </div>
            """,
            unsafe_allow_html=True
        )

    # Physical Indicators & Diagnostic Basis
    if indicators or basis:
        with st.expander("Physical Basis & Coupling Details", expanded=False):
            if basis:
                st.markdown(f"**Diagnostic Basis:** {basis}")
            if indicators:
                st.markdown("**Coupling Indicators:**")
                for ind in indicators:
                    st.markdown(f"- `{ind}`")
