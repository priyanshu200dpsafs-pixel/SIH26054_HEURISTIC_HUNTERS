# Phase 3B Runtime Integration Report: Real-Time Intelligent Digital Twin

**Project:** SIH26054 — Explainable Digital Twin for MALE UAV Aero Piston Powerplant (Rotax 912-Class, ~100 HP)  
**Date:** 2026-09-29  
**Status:** PHASE 3B COMPLETE (100% Verified)

---

## A. Implementation Status

Phase 3B has successfully connected the verified Phase 2 live CAN telemetry pipeline (`AeroEnginePlant -> EngineCANEncoder -> LocalUDPTransport -> EngineCANDecoder -> TelemetryEvent`) with the verified Phase 3A PHM diagnostic components into a **single, deterministic, real-time Digital Twin runtime engine** (`DigitalTwinRuntime`).

- Single unified orchestrator processes one incoming telemetry frame at a time.
- Operates at 10 Hz with an average processing latency of **3.9 ms** (well within the 100 ms cycle budget).
- Produces the canonical `DigitalTwinState` dataclass distinguishing measured telemetry, physics residuals, ML predictions, operational health state, and causal evidence.
- Zero external UI, React, FastAPI, LLMs, or cloud infrastructure introduced.
- Protected 150-run research dataset and split manifest remain 100% untouched (`git diff -- data/` is empty).

---

## B. Architecture

```text
                            ┌───────────────────────────┐
                            │        ENGINE PLANT       │
                            │      AeroEnginePlant      │
                            │  (physics + fault inject) │
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
                            │    CROSS-PLATFORM TRANS   │
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
                            │      TELEMETRY EVENT      │
                            │       TelemetryEvent      │
                            └─────────────┬─────────────┘
                                          │
         ┌────────────────────────────────┼────────────────────────────────┐
         ▼                                ▼                                ▼
   Physics Observer               Residual Detector                     Fault ML
  PhysicsExpectedEstimator     ResidualAnomalyDetector             FaultDiscriminator
  (Expected EGT, CHT, RPM)     (Raw, Signed, EWMA, 3-sigma)        (Plant vs Sensor coupling)
         │                                │                                │
         └────────────────────────────────┼────────────────────────────────┘
                                          ▼
                               ┌─────────────────────┐
                               │    RUL ESTIMATOR    │
                               │     RULEstimator    │
                               │ (Stateless Quantile)│
                               └──────────┬──────────┘
                                          │
                                          ▼
                            ┌───────────────────────────┐
                            │    DIGITAL TWIN STATE     │
                            │     DigitalTwinState      │
                            │                           │
                            │  * health state           │
                            │  * fault & confidence     │
                            │  * RUL & uncertainty      │
                            │  * residuals              │
                            │  * physical limits        │
                            │  * explanation            │
                            │  * telemetry quality      │
                            └───────────────────────────┘
```

---

## C. Files Created

1. [`digital_twin/__init__.py`](file:///c:/projects/sih/SIH26054_HEURISTIC_HUNTERS-main/SIH26054_HEURISTIC_HUNTERS-main/digital_twin/__init__.py): Exposes canonical state models, runtime engine, enums, and exceptions.
2. [`digital_twin/state.py`](file:///c:/projects/sih/SIH26054_HEURISTIC_HUNTERS-main/SIH26054_HEURISTIC_HUNTERS-main/digital_twin/state.py): Canonical strongly-typed `DigitalTwinState`, `MeasuredTelemetry`, `PhysicsDerivedState`, `MLPredictionState`, `Explanation`, and operational enums.
3. [`digital_twin/health_state.py`](file:///c:/projects/sih/SIH26054_HEURISTIC_HUNTERS-main/SIH26054_HEURISTIC_HUNTERS-main/digital_twin/health_state.py): Deterministic operational health state evaluation, simulation health index, and Rotax 912 physical limit boundary monitoring.
4. [`digital_twin/explanation.py`](file:///c:/projects/sih/SIH26054_HEURISTIC_HUNTERS-main/SIH26054_HEURISTIC_HUNTERS-main/digital_twin/explanation.py): Grounded physical explainability engine producing machine-readable `EvidenceItem` records from actual telemetry and residuals with zero LLMs.
5. [`digital_twin/runtime.py`](file:///c:/projects/sih/SIH26054_HEURISTIC_HUNTERS-main/SIH26054_HEURISTIC_HUNTERS-main/digital_twin/runtime.py): Real-time `DigitalTwinRuntime` orchestrating the 10-step diagnostic execution per frame.
6. [`digital_twin/test_runtime.py`](file:///c:/projects/sih/SIH26054_HEURISTIC_HUNTERS-main/SIH26054_HEURISTIC_HUNTERS-main/digital_twin/test_runtime.py): Unit test suite covering Tests A through I.
7. [`run_digital_twin.py`](file:///c:/projects/sih/SIH26054_HEURISTIC_HUNTERS-main/SIH26054_HEURISTIC_HUNTERS-main/run_digital_twin.py): Main executable streaming live missions over CAN/UDP with CLI arguments.
8. [`tests/test_digital_twin_end_to_end.py`](file:///c:/projects/sih/SIH26054_HEURISTIC_HUNTERS-main/SIH26054_HEURISTIC_HUNTERS-main/tests/test_digital_twin_end_to_end.py): End-to-end integration test suite verifying all 5 fault scenarios over unmocked UDP IPC.
9. [`docs/phase3b_runtime_report.md`](file:///c:/projects/sih/SIH26054_HEURISTIC_HUNTERS-main/SIH26054_HEURISTIC_HUNTERS-main/docs/phase3b_runtime_report.md): This verification report.

---

## D. Files Modified

1. [`README.md`](file:///c:/projects/sih/SIH26054_HEURISTIC_HUNTERS-main/SIH26054_HEURISTIC_HUNTERS-main/README.md): Added "Phase 3B: Real-Time Intelligent Digital Twin" section with execution commands, architecture, and scientific disclosures.

*(Zero modifications to `data/` or dataset manifests).*

---

## E. Runtime Pipeline

For every received CAN cycle (4 aggregated CAN frames):

```text
Telemetry validation
        ↓
Physics observation
        ↓
Residual calculation
        ↓
Anomaly detection
        ↓
Fault classification
        ↓
RUL inference
        ↓
Uncertainty extraction
        ↓
Health-state determination
        ↓
Redline evaluation
        ↓
Explainability
        ↓
DigitalTwinState
```

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

## F. Test Results

| Test | Result |
| :--- | :---: |
| **Nominal** | **PASS** |
| **Injector clog** | **PASS** |
| **Oil leak** | **PASS** |
| **Sensor drift** | **PASS** |
| **Cooling blockage** | **PASS** |
| **Invalid telemetry** | **PASS** |
| **Sequence gap** | **PASS** |
| **Stateless RUL** | **PASS** |
| **Explainability** | **PASS** |
| **Full E2E** | **PASS** |

---

## G. Performance

Benchmark measured over a full **30-second mission at 10 Hz** (300 cycles / 1,200 CAN envelopes) using `python run_digital_twin.py --duration 30 --rate 10 --fast`:

- **Frames received:** 300
- **Frames processed:** 300
- **Frames dropped:** 0
- **Invalid frames:** 0
- **Mean latency:** **3.9 ms**
- **P95 latency:** **4.8 ms**
- **Max latency:** **6.6 ms**

Processing latency consumes < 5% of the 100 ms cycle budget available at 10 Hz.

---

## H. Scientific Limitations

1. **Synthetic/Heuristic RUL Target:**  
   The RUL target in the underlying dataset represents an analytical countdown model based on thermal, mechanical, and cumulative operating stress (Category C — Hybrid Heuristic/Synthetic Degradation Countdown). It is **not** an empirically validated physical fatigue measurement from physical metallurgical aero engine test cells.
2. **Cooling Duct Blockage Weak Coupling:**  
   Under loiter cruise operating conditions, cowl ram-air restriction produces mild CHT increases (~3–7°C) that remain near caution boundaries. The system honestly preserves and documents this known limitation from Phase 3A rather than fabricating artificial certainty.
3. **Simulation-Only Prototype:**  
   This software is an engineering research prototype running over virtual simulation transports. It is **NOT** flight-certified software (DO-178C / DO-254) and must not be used for direct flight control or real aircraft dispatch.
4. **No Autonomous Aircraft Control:**  
   The Digital Twin strictly outputs diagnostics and prognostic health assessments. It performs zero aircraft control, issues no RTB or flight termination commands, and controls no actuators.

---

## I. Regression Status

Every regression test across Phase 1, Phase 2, Phase 3A, and Phase 3B was executed on the active codebase with 100% success:

| Phase | Test Command | Result |
| :--- | :--- | :---: |
| **Phase 1** | `python plant_model/test_plant.py` | **PASS** (6/6 tests) |
| **Phase 1** | `python plant_model/validate_phase1.py` | **PASS** (100% physics checks) |
| **Phase 2** | `python can_bus/test_can_roundtrip.py` | **PASS** (60/60 signals, 100%) |
| **Phase 2** | `python can_bus/test_end_to_end_stream.py` | **PASS** (24/24 tests) |
| **Phase 3A** | `python ml_layer/validate_phase3.py` | **PASS** (4/4 tests) |
| **Phase 3A** | `python ml_layer/validate_phm.py` | **PASS** (100% integrity, R²=0.996) |
| **Phase 3B** | `python digital_twin/test_runtime.py` | **PASS** (9/9 tests) |
| **Phase 3B** | `python tests/test_digital_twin_end_to_end.py` | **PASS** (6/6 tests) |
