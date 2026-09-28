#!/usr/bin/env python3
"""
===============================================================================
AERO PISTON ENGINE DIGITAL TWIN: RUNTIME ORCHESTRATION ENGINE (PHASE 3B)
===============================================================================
Connects the live telemetry pipeline (CAN/transport/decoder) with the validated
PHM components into a single real-time, deterministic Digital Twin runtime.

Processing Pipeline:
  Telemetry (CAN/Sensors)
    ↓
  1. Telemetry Quality & Integrity Validation
    ↓
  2. Physics Observer (Nominal Thermodynamic Model)
    ↓
  3. Physics Residual Calculation (Raw & EWMA Filtered)
    ↓
  4. Redline / Physical Boundary Proximity Monitor
    ↓
  5. Fault Classification & Isolation (Multivariate Coupling)
    ↓
  6. Stateless Quantile RUL & Uncertainty Estimation
    ↓
  7. Early-Warning State Determination
    ↓
  8. Deterministic Health State Engine
    ↓
  9. Simulation Health Index Calculation
    ↓
  10. Evidence-Based Explainability Generation
    ↓
  Unified DigitalTwinState Record
===============================================================================
"""

import math
import time
from typing import Dict, Any, List, Optional, Tuple

import numpy as np

from digital_twin.state import (
    EngineHealthState,
    TelemetryQuality,
    RedlineStatus,
    ResidualStatus,
    Explanation,
    MeasuredTelemetry,
    PhysicsDerivedState,
    MLPredictionState,
    DigitalTwinState,
)
from digital_twin.health_state import HealthStateEngine
from digital_twin.explanation import generate_explanation, EvidenceItem
from ml_layer.physics_estimator import PhysicsExpectedEstimator
from ml_layer.residual_detector import ResidualAnomalyDetector
from ml_layer.fault_discriminator import FaultDiscriminator
from ml_layer.rul_estimator import RULEstimator, TemporalRULFilter
from plant_model.physics_core import EngineSpecs


class DigitalTwinRuntime:
    """
    Real-time Digital Twin execution engine for aero piston powerplants.
    Processes individual telemetry events, coordinates physics observers and ML models,
    maintains strictly causal history, and produces unified DigitalTwinState outputs.
    """

    def __init__(
        self,
        enable_temporal_filter: bool = False,
        ewma_alpha: float = 0.05,
        specs: Optional[EngineSpecs] = None
    ):
        self.specs = specs or EngineSpecs()
        self.enable_temporal_filter = enable_temporal_filter

        # Core PHM Components
        self.detector = ResidualAnomalyDetector(ewma_alpha=ewma_alpha)
        self.discriminator = FaultDiscriminator()
        self.rul_estimator = RULEstimator()
        self.temporal_filter = TemporalRULFilter() if enable_temporal_filter else None
        self.health_engine = HealthStateEngine()

        # Pre-load ML models
        try:
            self.rul_estimator.load_model()
            self.rul_model_available = True
        except Exception as e:
            self.rul_model_available = False
            self.model_load_error = str(e)

        # Operational & Performance Tracking
        self.last_sequence: Optional[int] = None
        self.expected_seq_delta: Optional[int] = None
        self.recent_history: List[Dict[str, float]] = []
        self.total_frames_received: int = 0
        self.total_frames_processed: int = 0
        self.total_invalid_frames: int = 0
        self.total_sequence_gaps: int = 0
        self.total_redline_events: int = 0
        self.latencies_ms: List[float] = []

        # Mission Diagnostic Timeline
        self.state_counts: Dict[EngineHealthState, int] = {
            EngineHealthState.HEALTHY: 0,
            EngineHealthState.DEGRADED: 0,
            EngineHealthState.CRITICAL: 0,
            EngineHealthState.UNKNOWN: 0
        }
        self.first_alert_time: Optional[float] = None
        self.first_redline_time: Optional[float] = None
        self.detected_fault_type: str = "nominal"
        self.min_rul_hours: Optional[float] = None

    def reset(self):
        """Resets runtime state between mission runs."""
        self.detector.reset()
        if self.temporal_filter:
            self.temporal_filter.reset()
        self.last_sequence = None
        self.expected_seq_delta = None
        self.recent_history.clear()
        self.total_frames_received = 0
        self.total_frames_processed = 0
        self.total_invalid_frames = 0
        self.total_sequence_gaps = 0
        self.total_redline_events = 0
        self.latencies_ms.clear()
        for k in self.state_counts:
            self.state_counts[k] = 0
        self.first_alert_time = None
        self.first_redline_time = None
        self.detected_fault_type = "nominal"
        self.min_rul_hours = None

    def validate_telemetry(self, telemetry: Dict[str, Any]) -> Tuple[TelemetryQuality, List[str]]:
        """
        Validates incoming decoded frame for completeness, numerical integrity,
        and physical sanity boundaries.
        """
        errors = []
        required_signals = [
            "rpm", "egt1", "egt2", "egt3", "egt4",
            "cht1", "cht2", "cht3", "cht4",
            "oil_press_bar", "oil_temp_c", "throttle_pct"
        ]

        # 1. Missing signal checks
        for sig in required_signals:
            if sig not in telemetry:
                errors.append(f"Missing required telemetry signal '{sig}'")

        if errors:
            return TelemetryQuality.INVALID, errors

        # 2. NaN / Inf validation
        for sig in required_signals:
            val = telemetry.get(sig)
            if not isinstance(val, (int, float)) or math.isnan(val) or math.isinf(val):
                errors.append(f"Invalid non-numeric value in signal '{sig}': {val}")

        if errors:
            return TelemetryQuality.INVALID, errors

        # 3. Gross physical impossibility checks
        rpm = float(telemetry["rpm"])
        oil_p = float(telemetry["oil_press_bar"])
        th = float(telemetry["throttle_pct"])

        if rpm < -10.0 or rpm > 12000.0:
            errors.append(f"RPM out of physically possible range: {rpm:.1f}")
        if oil_p < -1.0 or oil_p > 25.0:
            errors.append(f"Oil pressure out of physical range: {oil_p:.2f} bar")
        if th < -5.0 or th > 125.0:
            errors.append(f"Throttle setting out of physical range: {th:.1f}%")

        if errors:
            return TelemetryQuality.DEGRADED, errors

        return TelemetryQuality.VALID, []

    def check_redlines(self, telemetry: Dict[str, Any]) -> Tuple[RedlineStatus, Dict[str, Any]]:
        """Delegates redline evaluation to the single source of truth in HealthStateEngine."""
        return self.health_engine.check_redlines(telemetry)

    def process(self, telemetry: Dict[str, Any], dt: float = 0.1) -> DigitalTwinState:
        """
        Executes one complete Digital Twin diagnostic timestep.
        """
        t_start = time.perf_counter()
        self.total_frames_received += 1

        t_sim = float(telemetry.get("timestamp", telemetry.get("timestamp_sec", 0.0)))
        seq = int(telemetry.get("sequence", self.total_frames_received))
        cycle = int(telemetry.get("cycle_id", seq // 4))

        # ---------------------------------------------------------------------
        # 1. TELEMETRY QUALITY & SEQUENCE GAP VALIDATION
        # ---------------------------------------------------------------------
        quality, quality_errors = self.validate_telemetry(telemetry)
        if self.last_sequence is not None:
            seq_delta = seq - self.last_sequence
            if seq_delta <= 0:
                self.total_sequence_gaps += 1
                quality_errors.append(f"Non-monotonic sequence: received seq={seq} after {self.last_sequence}")
                if quality == TelemetryQuality.VALID:
                    quality = TelemetryQuality.DEGRADED
            elif self.expected_seq_delta is None:
                self.expected_seq_delta = seq_delta
            elif seq_delta > self.expected_seq_delta:
                missed = (seq_delta - self.expected_seq_delta) // max(1, self.expected_seq_delta)
                self.total_sequence_gaps += max(1, missed)
                quality_errors.append(f"Sequence gap detected: jumped from {self.last_sequence} to {seq} (Δ={seq_delta})")
                if quality == TelemetryQuality.VALID:
                    quality = TelemetryQuality.DEGRADED
        self.last_sequence = seq

        if quality == TelemetryQuality.INVALID:
            self.total_invalid_frames += 1
            self.state_counts[EngineHealthState.UNKNOWN] += 1
            proc_ms = (time.perf_counter() - t_start) * 1000.0
            self.latencies_ms.append(proc_ms)
            return DigitalTwinState(
                timestamp=t_sim,
                sequence_number=seq,
                cycle_id=cycle,
                telemetry_status=TelemetryQuality.INVALID,
                engine_state=EngineHealthState.UNKNOWN,
                health_score=None,
                fault_type="UNKNOWN",
                explanation=Explanation(
                    summary="Telemetry validation failure. Incomplete or corrupted sensor data frame.",
                    evidence=quality_errors
                ),
                processing_time_ms=proc_ms
            )

        # Build MeasuredTelemetry record
        meas = MeasuredTelemetry(
            rpm=float(telemetry.get("rpm", 0.0)),
            throttle_pct=float(telemetry.get("throttle_pct", 0.0)),
            fuel_flow_gps=float(telemetry.get("fuel_flow_gps", 0.0)),
            egt1=float(telemetry.get("egt1", 0.0)),
            egt2=float(telemetry.get("egt2", 0.0)),
            egt3=float(telemetry.get("egt3", 0.0)),
            egt4=float(telemetry.get("egt4", 0.0)),
            cht1=float(telemetry.get("cht1", 0.0)),
            cht2=float(telemetry.get("cht2", 0.0)),
            cht3=float(telemetry.get("cht3", 0.0)),
            cht4=float(telemetry.get("cht4", 0.0)),
            oil_press_bar=float(telemetry.get("oil_press_bar", 0.0)),
            oil_temp_c=float(telemetry.get("oil_temp_c", 0.0)),
            airspeed_mps=float(telemetry.get("airspeed_mps", 0.0)),
            altitude_m=float(telemetry.get("altitude_m", 0.0)),
            status_flags=int(telemetry.get("status_flags", 0)),
            rolling_counter=int(telemetry.get("rolling_counter", 0))
        )

        # ---------------------------------------------------------------------
        # 2 & 3. PHYSICS OBSERVER & RESIDUAL DETECTION
        # ---------------------------------------------------------------------
        det_out = self.detector.process_telemetry(dt=dt, telemetry=telemetry)
        raw_res = det_out["raw_residuals"]
        signed_res = det_out["signed_residuals"]
        ewma_res = det_out["ewma_residuals"]
        max_egt_r = float(det_out["max_egt_residual"])
        max_cht_r = float(det_out["max_cht_residual"])
        det_status_str = det_out["status"]  # 'NORMAL', 'CAUTION', 'ALERT'

        res_status = ResidualStatus(det_status_str)
        # Normalized residual severity index (1.0 = alert threshold reached)
        norm_res_mag = max(
            max_egt_r / 28.0,
            max_cht_r / 12.0,
            ewma_res.get("oil_press_bar", 0.0) / 0.40,
            ewma_res.get("rpm", 0.0) / 120.0
        )

        physics_state = PhysicsDerivedState(
            expected_values=det_out["expected"],
            raw_residuals=raw_res,
            signed_residuals=signed_res,
            ewma_residuals=ewma_res,
            max_egt_residual=max_egt_r,
            max_cht_residual=max_cht_r,
            residual_status=res_status,
            residual_magnitude=round(norm_res_mag, 2),
            anomaly_detected=(res_status != ResidualStatus.NORMAL),
            anomaly_duration_sec=float(det_out.get("anomaly_duration_sec", 0.0)),
            cumulative_stress=float(det_out.get("cumulative_stress", 0.0))
        )

        # ---------------------------------------------------------------------
        # 4. REDLINE / PHYSICAL BOUNDARY MONITOR
        # ---------------------------------------------------------------------
        redline_stat, redline_details = self.health_engine.check_redlines(telemetry)
        if redline_stat != RedlineStatus.NORMAL:
            self.total_redline_events += 1
        if redline_stat in (RedlineStatus.ALERT, RedlineStatus.REDLINE) and self.first_redline_time is None:
            self.first_redline_time = t_sim

        # ---------------------------------------------------------------------
        # 5. FAULT DISCRIMINATION (MULTIVARIATE PHYSICS COUPLING)
        # ---------------------------------------------------------------------
        pred_state = MLPredictionState()
        classif = {}
        try:
            classif = self.discriminator.classify_anomaly(det_out)
            is_plant_fault = (classif.get("classification") == "PLANT_FAULT")
            raw_sub = classif.get("fault_subtype", "NONE")
            pred_state.fault_type = raw_sub.lower() if raw_sub != "NONE" else "nominal"
            pred_state.fault_subtype = raw_sub
            pred_state.fault_confidence = float(classif.get("confidence", 1.0))
            pred_state.fault_location = classif.get("fault_location", "NONE")
            if pred_state.fault_type != "nominal":
                if self.first_alert_time is None:
                    self.first_alert_time = t_sim
                if self.detected_fault_type in ("nominal", "general_degradation") or (is_plant_fault and self.detected_fault_type == "sensor_drift"):
                    self.detected_fault_type = pred_state.fault_type
        except Exception as e:
            pred_state.fault_type = "UNKNOWN"
            pred_state.error_message = f"Fault discriminator failure: {e}"

        # ---------------------------------------------------------------------
        # 6. STATELESS RUL ESTIMATION & UNCERTAINTY
        # ---------------------------------------------------------------------
        self.recent_history.append({
            "timestamp_sec": t_sim,
            "max_egt_residual": max_egt_r
        })
        if len(self.recent_history) > 30:
            self.recent_history.pop(0)

        if self.rul_model_available:
            try:
                feat = self.rul_estimator.extract_features(telemetry, det_out, self.recent_history)
                raw_rul = self.rul_estimator.predict(feat)
                pred_state.rul_hours = raw_rul["rul_hours"]
                pred_state.rul_q10_hours = raw_rul["rul_lower_hours"]
                pred_state.rul_q50_hours = raw_rul["rul_hours"]
                pred_state.rul_q90_hours = raw_rul["rul_upper_hours"]
                pred_state.uncertainty_band_hours = raw_rul["uncertainty_band_hours"]

                if self.min_rul_hours is None or raw_rul["rul_hours"] < self.min_rul_hours:
                    self.min_rul_hours = raw_rul["rul_hours"]

                # Optional Decoupled Temporal Smoother
                if self.temporal_filter is not None:
                    is_fault = (pred_state.fault_type != "nominal")
                    filt_rul = self.temporal_filter.filter(raw_rul, is_active_fault=is_fault)
                    pred_state.filtered_rul_hours = filt_rul["rul_hours"]
            except Exception as e:
                pred_state.error_message = f"RUL estimation failure: {e}"
        else:
            pred_state.error_message = f"RUL model unavailable: {getattr(self, 'model_load_error', 'unloaded')}"

        # ---------------------------------------------------------------------
        # 7. EARLY WARNING ADVANTAGE DETERMINATION
        # ---------------------------------------------------------------------
        # Early warning active when DT flags alert while raw physical parameters are still safe
        early_warn = (res_status in (ResidualStatus.CAUTION, ResidualStatus.ALERT) and
                      redline_stat in (RedlineStatus.NORMAL, RedlineStatus.CAUTION))

        # ---------------------------------------------------------------------
        # 8. DETERMINISTIC ENGINE HEALTH STATE
        # ---------------------------------------------------------------------
        is_plant_fault = (classif.get("classification") == "PLANT_FAULT")
        eng_state = self.health_engine.determine_health_state(
            telemetry_quality=quality,
            redline_status=redline_stat,
            residual_status=res_status,
            fault_type=pred_state.fault_type,
            is_plant_fault=is_plant_fault,
            rul_hours=pred_state.rul_hours
        )
        self.state_counts[eng_state] += 1

        # ---------------------------------------------------------------------
        # 9. SIMULATION HEALTH INDEX [0.0, 1.0] (NOT CERTIFIED SAFETY PROBABILITY)
        # ---------------------------------------------------------------------
        health_idx = self.health_engine.calculate_health_score(
            engine_state=eng_state,
            fault_type=pred_state.fault_type,
            norm_residual_magnitude=norm_res_mag,
            redline_status=redline_stat
        )

        # ---------------------------------------------------------------------
        # 10. EVIDENCE-BASED EXPLANATION GENERATION
        # ---------------------------------------------------------------------
        explanation = generate_explanation(
            fault_type=pred_state.fault_type,
            fault_subtype=pred_state.fault_subtype,
            fault_location=pred_state.fault_location,
            signed_residuals=signed_res,
            ewma_residuals=ewma_res,
            detector_output=det_out,
            redline_status=redline_stat.value,
            redline_details=redline_details
        )
        if quality_errors:
            for q_err in quality_errors:
                explanation.evidence.append(EvidenceItem("telemetry_warning", 0.0, "", q_err))

        proc_ms = (time.perf_counter() - t_start) * 1000.0
        self.latencies_ms.append(proc_ms)
        self.total_frames_processed += 1

        # ---------------------------------------------------------------------
        # 11. UNIFIED DIGITAL TWIN STATE ASSEMBLY
        # ---------------------------------------------------------------------
        return DigitalTwinState(
            timestamp=t_sim,
            sequence_number=seq,
            cycle_id=cycle,
            telemetry_status=quality,
            engine_state=eng_state,
            health_score=health_idx,
            fault_type=pred_state.fault_type,
            fault_confidence=pred_state.fault_confidence,
            rul_hours=pred_state.rul_hours,
            rul_q10_hours=pred_state.rul_q10_hours,
            rul_q50_hours=pred_state.rul_q50_hours,
            rul_q90_hours=pred_state.rul_q90_hours,
            residual_status=res_status.value,
            residual_magnitude=round(norm_res_mag, 2),
            early_warning=early_warn,
            redline_status=redline_stat.value,
            redline_details=redline_details,
            explanation=explanation,
            telemetry=meas,
            physics=physics_state,
            predictions=pred_state,
            processing_time_ms=proc_ms
        )

    def get_mission_summary(self) -> Dict[str, Any]:
        """
        Calculates and returns complete mission-level performance and diagnostic metrics.
        """
        lats = np.array(self.latencies_ms) if self.latencies_ms else np.array([0.0])
        lead_time = None
        if self.first_alert_time is not None and self.first_redline_time is not None:
            if self.first_redline_time >= self.first_alert_time:
                lead_time = self.first_redline_time - self.first_alert_time

        return {
            "frames_received": self.total_frames_received,
            "frames_processed": self.total_frames_processed,
            "invalid_frames": self.total_invalid_frames,
            "dropped_frames": self.total_sequence_gaps,
            "latency_ms": {
                "mean": round(float(np.mean(lats)), 2),
                "p95": round(float(np.percentile(lats, 95)), 2),
                "max": round(float(np.max(lats)), 2)
            },
            "state_counts": {
                k.value: v for k, v in self.state_counts.items()
            },
            "fault_detected": self.detected_fault_type,
            "first_alert_time_sec": round(self.first_alert_time, 2) if self.first_alert_time is not None else None,
            "first_redline_time_sec": round(self.first_redline_time, 2) if self.first_redline_time is not None else None,
            "early_warning_lead_time_sec": round(lead_time, 2) if lead_time is not None else None,
            "redline_events": self.total_redline_events,
            "min_rul_hours": round(self.min_rul_hours, 2) if self.min_rul_hours is not None else None
        }

    def format_mission_summary(self) -> str:
        """Formats the terminal mission summary block matching Section 21 specification."""
        s = self.get_mission_summary()
        lat = s["latency_ms"]
        sc = s["state_counts"]
        first_det_str = f"{s['first_alert_time_sec']:.1f} s" if s['first_alert_time_sec'] is not None else "None"
        min_rul_str = f"{s['min_rul_hours']:.2f} h" if s['min_rul_hours'] is not None else "N/A"

        lines = [
            "========================================================",
            "DIGITAL TWIN MISSION SUMMARY",
            "========================================================",
            "",
            f"Frames received      : {s['frames_received']}",
            f"Frames processed     : {s['frames_processed']}",
            f"Invalid frames       : {s['invalid_frames']}",
            f"Dropped frames       : {s['dropped_frames']}",
            "",
            f"Mean latency         : {lat['mean']:.1f} ms",
            f"P95 latency          : {lat['p95']:.1f} ms",
            f"Max latency          : {lat['max']:.1f} ms",
            "",
            f"HEALTHY frames       : {sc.get('HEALTHY', 0)}",
            f"DEGRADED frames      : {sc.get('DEGRADED', 0)}",
            f"CRITICAL frames      : {sc.get('CRITICAL', 0)}",
            "",
            f"Fault detected       : {s['fault_detected']}",
            f"First detection      : {first_det_str}",
            "",
            f"Redline events       : {s['redline_events']}",
            f"Minimum RUL estimate : {min_rul_str}",
            "========================================================"
        ]
        return "\n".join(lines)
