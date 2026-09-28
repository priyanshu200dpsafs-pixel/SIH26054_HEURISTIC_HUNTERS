# Phase 3B Runtime Integration Report: Real-Time Intelligent Digital Twin

**Project:** SIH26054 — Explainable Digital Twin for MALE UAV Aero Piston Powerplant (Rotax 912-Class, ~100 HP)  
**Date:** 2026-09-29  
**Status:** PHASE 3B COMPLETE (100% Verified)

---

## 1. Status Overview

Phase 3B has successfully connected the validated Phase 2 live CAN telemetry pipeline to the validated Phase 3A PHM diagnostic components into a **single, deterministic, real-time Digital Twin runtime engine** (`DigitalTwinRuntime`).

- Single unified orchestrator processes one incoming telemetry frame at a time.
- Operates at 10 Hz with an average processing latency of **4.05 ms** (well within the 100 ms cycle budget).
- Produces the canonical `DigitalTwinState` dataclass distinguishing measured telemetry, physics residuals, ML predictions, operational health state, and causal evidence.
- Zero external UI, React, FastAPI, LLMs, or cloud infrastructure introduced.
- Protected 150-run research dataset and split manifest remain 100% untouched.

---

## 2. Actual Runtime Architecture

```text
                           ┌───────────────────────────┐
                           │        ENGINE PLANT       │
                           │      AeroEnginePlant      │
                           └─────────────┬─────────────┘
                                         │ sensor telemetry dict
                                         ▼
                           ┌───────────────────────────┐
                           │      CAN FRAME ENCODER    │
                           │      EngineCANEncoder     │
                           │   (DBC + 28B wire packet) │
                           └─────────────┬─────────────┘
                                         │ 4x 28B envelopes
                                         ▼
                           ┌───────────────────────────┐
                           │    LOCALHOST UDP IPC      │
                           │     LocalUDPTransport     │
                           │    (127.0.0.1:5555)       │
                           └─────────────┬─────────────┘
                                         │ UDP datagrams
                                         ▼
                           ┌───────────────────────────┐
                           │      CAN FRAME DECODER    │
                           │      EngineCANDecoder     │
                           │  (CRC-8, Seq, Parity, DBC)│
                           └─────────────┬─────────────┘
                                         │ decoded telemetry cycle
                                         ▼
                           ┌───────────────────────────┐
                           │    DIGITAL TWIN RUNTIME   │
                           │     DigitalTwinRuntime    │
                           └─────────────┬─────────────┘
                                         │
        ┌────────────────────────────────┼────────────────────────────────┐
        ▼                                ▼                                ▼
  [Step 1: Validate]            [Step 2: Physics Obs]          [Step 3: Residuals]
  Missing keys, NaN,            Independent analytic           Raw, Signed, EWMA,
  sequence gaps, ranges         expected model                 and 3-sigma limits
        │                                │                                │
        └────────────────────────────────┼────────────────────────────────┘
                                         ▼
        ┌────────────────────────────────┼────────────────────────────────┐
        ▼                                ▼                                ▼
  [Step 4: Limits]              [Step 5: Diagnostics]          [Step 6: RUL & Uncert]
  Redline & alert               Multivariate coupling          Stateless Quantile RF
  thresholds                    (Plant vs Sensor fault)        [Q10, Q50, Q90]
        │                                │                                │
        └────────────────────────────────┼────────────────────────────────┘
                                         ▼
        ┌────────────────────────────────┴────────────────────────────────┐
        ▼                                                                 ▼
  [Step 7 & 8: Health State]                                     [Step 9: Explanation]
  HEALTHY / DEGRADED / CRITICAL / UNKNOWN                        Causal evidence chain
  Simulation Health Index [0.0, 1.0]                             without hallucination
                                         │
                                         ▼
                           ┌───────────────────────────┐
                           │     DIGITAL TWIN STATE    │
                           │      DigitalTwinState     │
                           │ (Terminal Card / JSON-L)  │
                           └───────────────────────────┘
```

---

## 3. Files Created

1. [`digital_twin/__init__.py`](file:///c:/projects/sih/SIH26054_HEURISTIC_HUNTERS-main/SIH26054_HEURISTIC_HUNTERS-main/digital_twin/__init__.py): Exposes canonical state models, runtime engine, enums, and exceptions.
2. [`digital_twin/state.py`](file:///c:/projects/sih/SIH26054_HEURISTIC_HUNTERS-main/SIH26054_HEURISTIC_HUNTERS-main/digital_twin/state.py): Canonical strongly-typed `DigitalTwinState`, `MeasuredTelemetry`, `PhysicsDerivedState`, `MLPredictionState`, `Explanation`, and operational enums.
3. [`digital_twin/runtime.py`](file:///c:/projects/sih/SIH26054_HEURISTIC_HUNTERS-main/SIH26054_HEURISTIC_HUNTERS-main/digital_twin/runtime.py): Real-time `DigitalTwinRuntime` orchestrating the 10-step diagnostic execution per frame.
4. [`digital_twin/test_runtime.py`](file:///c:/projects/sih/SIH26054_HEURISTIC_HUNTERS-main/SIH26054_HEURISTIC_HUNTERS-main/digital_twin/test_runtime.py): Unit test suite covering Tests A through I.
5. [`run_digital_twin.py`](file:///c:/projects/sih/SIH26054_HEURISTIC_HUNTERS-main/SIH26054_HEURISTIC_HUNTERS-main/run_digital_twin.py): Main executable streaming live missions over CAN/UDP with CLI arguments.
6. [`tests/test_digital_twin_end_to_end.py`](file:///c:/projects/sih/SIH26054_HEURISTIC_HUNTERS-main/SIH26054_HEURISTIC_HUNTERS-main/tests/test_digital_twin_end_to_end.py): End-to-end integration test suite verifying all 5 fault scenarios over unmocked UDP IPC.
7. [`docs/phase3b_runtime_report.md`](file:///c:/projects/sih/SIH26054_HEURISTIC_HUNTERS-main/SIH26054_HEURISTIC_HUNTERS-main/docs/phase3b_runtime_report.md): This verification report.

---

## 4. Files Modified

1. [`README.md`](file:///c:/projects/sih/SIH26054_HEURISTIC_HUNTERS-main/SIH26054_HEURISTIC_HUNTERS-main/README.md): Added "Phase 3B: Real-Time Intelligent Digital Twin" section with execution commands, architecture, and scientific disclosures.

*(No modifications made to `data/` or dataset manifests).*

---

## 5. Runtime Pipeline Execution Order

For every received CAN cycle (4 aggregated CAN frames):

1. **Telemetry Quality Validation:** Validates presence of required signals (`rpm`, `egt1..4`, `cht1..4`, `oil_press_bar`, `oil_temp_c`, `throttle_pct`), rejects non-numeric or NaN values, verifies physical gross boundaries, and detects sequence continuity jumps or frame skips.
2. **Physics Observation:** Steps `PhysicsExpectedEstimator` based strictly on external controls (`throttle_pct`, `altitude_m`, `airspeed_mps`) to compute expected thermodynamic targets.
3. **Residual Tracking & Anomaly Detection:** Calculates raw residuals, signed directionalities, and EWMA smoothed residuals against calibrated 3-sigma variance thresholds.
4. **Physical Redline Boundary Monitor:** Evaluates actual telemetry against Rotax-912 operating limitations (EGT caution 880°C, alert 940°C, redline 950°C; CHT caution 200°C, alert 240°C, redline 250°C; Oil pressure 2.2 / 1.8 / 1.5 bar; Oil temp 110 / 118 / 125°C; RPM 5900).
5. **Multivariate Fault Discrimination:** Evaluates cross-channel thermodynamic coupling (e.g. single-cylinder EGT divergence + shaft RPM droop = injector clog; oil pressure loss + oil heating = oil leak; uncoupled single-sensor divergence = sensor drift).
6. **Stateless RUL Estimation & Uncertainty:** Evaluates pre-trained Quantile Random Forest model on 13-dimensional physics residual feature vector. Produces stateless point RUL (`rul_hours`) and calibrated prediction interval `[rul_q10_hours, rul_q90_hours]`.
7. **Early Warning Detection:** Determines whether a genuine fault is flagged by the residual detector while physical parameters are still well within conventional safe limits.
8. **Deterministic Engine Health State:** Assigns `HEALTHY`, `DEGRADED`, `CRITICAL`, or `UNKNOWN` state based strictly on physical evidence. Decouples telemetry corruption from engine health. Computes simulation health index `[0.0, 1.0]`.
9. **Evidence-Based Explainability:** Synthesizes human-readable and machine-parseable explanation citing actual calculated residuals (e.g. `EGT +62.4°C`, `RPM -108 RPM`).
10. **State Packaging:** Emits unified `DigitalTwinState` supporting terminal cards and JSON serialization.

---

## 6. Test Suite Results

### A. Runtime Unit Tests (`digital_twin/test_runtime.py`)

| Test | Objective | Result |
| :--- | :--- | :---: |
| **Test A: Nominal** | Validates baseline health, no false alarms, RUL > 100h | **PASS** |
| **Test B: Injector Clog** | EGT rise, RPM droop, degraded state, declining RUL, EGT evidence | **PASS** |
| **Test C: Oil Leak** | Oil pressure drop, oil heating, oil_leak diagnosis | **PASS** |
| **Test D: Sensor Drift** | Thermocouple offset isolated to instrument without shaft droop | **PASS** |
| **Test E: Cooling Blockage** | Verifies thermal dissipation impedance without crashing | **PASS** |
| **Test F: Invalid Telemetry** | Corrupted keys, NaN values handled gracefully -> UNKNOWN state | **PASS** |
| **Test G: Sequence Gap** | Dropped frames flagged as DEGRADED telemetry quality | **PASS** |
| **Test H: Stateless RUL** | Vector A -> B -> A determinism proves zero hidden state latching | **PASS** |
| **Test I: Explainability** | Evidence strictly references observed physical quantities | **PASS** |

### B. End-to-End Integration Tests (`tests/test_digital_twin_end_to_end.py`)

| Test | Pipeline Scope | Result |
| :--- | :--- | :---: |
| **test_01_nominal_pipeline** | Plant → CAN → UDP → Decoder → Event → Runtime (20 cycles) | **PASS** |
| **test_02_injector_clog_pipeline** | Injected combustion fault over live UDP transport (40 cycles) | **PASS** |
| **test_03_oil_leak_pipeline** | Injected lubrication failure over live UDP transport (80 cycles) | **PASS** |
| **test_04_sensor_drift_pipeline** | Injected instrument drift over live UDP transport (35 cycles) | **PASS** |
| **test_05_cooling_blockage_pipeline** | Injected airflow restriction over live UDP transport (35 cycles) | **PASS** |
| **test_06_json_schema_compliance** | Machine-readable streaming JSON schema validation | **PASS** |

---

## 7. Performance & Latency Benchmark

Benchmark performed over a full **30-second mission at 10 Hz** (300 cycles / 1,200 CAN envelopes) using `python run_digital_twin.py --duration 30 --rate 10 --fast`:

- **Frames Received:** 300
- **Frames Processed:** 300
- **Invalid Frames:** 0
- **Dropped Frames:** 0
- **Sequence Gaps:** 0
- **Mean Processing Latency:** **4.05 ms** per cycle
- **P95 Latency:** **5.76 ms** per cycle
- **Maximum Latency:** **11.16 ms** per cycle
- **Available Margin:** > 88% headroom relative to 10 Hz (100 ms) cycle budget.

---

## 8. Preserved Phase 3A Limitations

1. **Synthetic/Heuristic RUL Target:**  
   The RUL target in the underlying dataset represents an analytical countdown model based on thermal, mechanical, and cumulative operating stress. It is not an empirically validated physical fatigue measurement from physical aero engine test cells.
2. **Cooling Duct Blockage Weak Coupling:**  
   Under loiter cruise operating conditions, cowl ram-air restriction produces mild CHT increases (~3–6°C) that do not cross conservative caution thresholds. The system documents this weak coupling rather than manipulating thresholds.
3. **Discrete Simulation Timesteps:**  
   Inference executes on discrete 10 Hz time slices. Fast microsecond acoustic phenomena (e.g. detonation knock) are abstracted into mean thermodynamic cycle metrics.

---

## 9. Scientific & Operational Disclosures

- **Simulation-Only Prototype:** This software is an engineering demonstration prototype developed for SIH 2026. It is **NOT flight-certified** software (DO-178C / DO-254) and must not be used for direct flight control or real aircraft dispatch.
- **Evidence-Grounded Explanations:** Explanations cite only computed residuals and observed sensor values. No generative language models (LLMs) or black-box hallucinations are used.
- **Stateless Inference Integrity:** Core RUL predictions remain purely stateless. Historical smoothing, if desired by the operator, is provided solely via the optional `TemporalRULFilter`.

---

## 10. Complete Regression Verification

Every regression test across Phase 1, Phase 2, Phase 3A, and Phase 3B was executed on the current codebase:

| Phase | Test Command | Result |
| :--- | :--- | :---: |
| **Phase 1** | `python plant_model/test_plant.py` | **PASS** (6/6 tests) |
| **Phase 1** | `python plant_model/validate_phase1.py` | **PASS** (100% success) |
| **Phase 2** | `python can_bus/test_can_roundtrip.py` | **PASS** (60/60 signals, 100%) |
| **Phase 2** | `python can_bus/test_end_to_end_stream.py` | **PASS** (24/24 tests) |
| **Phase 3A** | `python ml_layer/validate_phase3.py` | **PASS** (4/4 tests) |
| **Phase 3A** | `python ml_layer/validate_phm.py` | **PASS** (100% integrity, R²=0.996) |
| **Phase 3B** | `python digital_twin/test_runtime.py` | **PASS** (9/9 tests) |
| **Phase 3B** | `python tests/test_digital_twin_end_to_end.py` | **PASS** (6/6 tests) |
