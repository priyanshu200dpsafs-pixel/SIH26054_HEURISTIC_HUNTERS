# Phase 4 Completion Report: Mission Control Dashboard, Real-Time Visualization & Mission Replay

**Project:** SIH26054 — Explainable Digital Twin for MALE UAV Aero Piston Powerplant (Rotax 912-class, ~100 HP)  
**Date:** September 2026  
**Status:** COMPLETE & VERIFIED  

---

## 1. Objective

Phase 4 transforms the Phase 3B real-time Intelligent Digital Twin runtime into a professional, aerospace-grade engineering observation interface: the **Rotax 912 Mission Control Dashboard & Mission Replay Engine**.

### Core Constraints & Invariants
1. **Single Source of Truth:** The canonical `DigitalTwinState` produced by `DigitalTwinRuntime` is the sole diagnostic authority.
2. **Observation Surface Only:** The dashboard contains zero physics calculations, zero fault classification heuristics, and zero RUL model inference.
3. **Authentic Telemetry Transport:** Live simulation executes strictly across `AeroEnginePlant -> EngineCANEncoder (DBC / 28B wire envelopes) -> LocalUDPTransport -> EngineCANDecoder -> TelemetryEvent -> DigitalTwinRuntime -> DigitalTwinState -> DashboardStateAdapter`.
4. **Mission Replay Consistency:** Historical flight replay from `data/*.csv` feeds directly into the same `DigitalTwinRuntime` to guarantee identical diagnostic behavior.
5. **Strict Immutability:** 100% read-only access to `data/` and `ml_layer/models/`. Zero modifications or model retrainings.
6. **No Artificial Intelligence Hallucinations:** Zero Large Language Models (LLMs) used for diagnosis or explanation.
7. **No Autonomous Flight Control:** The interface is strictly an observation and simulation surface. No autopilot, actuator, return-to-base, or flight-termination commands are issued.

---

## 2. Architecture

```text
                  SIMULATION / REPLAY
                          │
                          ▼
                      TELEMETRY
                          │
                          ▼
                   EXISTING CAN/UDP
                          │
                          ▼
                   TELEMETRY EVENT
                          │
                          ▼
               ┌──────────────────────┐
               │ DIGITAL TWIN RUNTIME │
               │                      │
               │ Physics              │
               │ Residuals            │
               │ Fault Diagnosis      │
               │ RUL                  │
               │ Uncertainty          │
               │ Health               │
               │ Redlines             │
               │ Explainability       │
               └──────────┬───────────┘
                          │
                          ▼
                  DIGITAL TWIN STATE
                          │
                 ┌────────┴────────┐
                 ▼                 ▼
             DASHBOARD        JSON EXPORT
                 │
           ┌─────┼───────────┐
           ▼     ▼           ▼
        Health  RUL      Explainability
           │     │           │
           └─────┼───────────┘
                 ▼
            MISSION CONTROL
```

### Module Breakdown
* `dashboard/app.py`: Streamlit entrypoint coordinating UI layout, dark-mode design tokens, mode switching, and JSON state export.
* `dashboard/state_adapter.py`: Stateless `DashboardStateAdapter` transforming canonical `DigitalTwinState` records into presentation-ready `DashboardState` structures.
* `dashboard/formatting.py`: Centralized visual tokens, operational state colors (`HEALTHY`: `#2ecc71`, `DEGRADED`: `#f39c12`, `CRITICAL`: `#e74c3c`, `UNKNOWN`: `#95a5a6`), and engineering unit formatters.
* `dashboard/telemetry_history.py`: Fixed-size sliding window `TelemetryHistoryBuffer` (`max_history_points=300`) with automatic milestone event detection (`MISSION_START`, `RESIDUAL_ANOMALY`, `STATE_TRANSITION`, `FAULT_CLASSIFIED`, `REDLINE_BREACH`).
* `dashboard/mission_controller.py`: `LiveMissionController` driving simulation over unmocked CAN/UDP localhost transport.
* `dashboard/replay.py`: `MissionReplayController` providing strictly read-only playback of dataset sorties through `DigitalTwinRuntime`.
* `dashboard/session.py`: Coordination container managing Streamlit session state.
* `dashboard/components/`: Modular presentation components for headers, primary health cards, engine telemetry, RUL prognostics, physics residuals, redlines, explainability, system health, timeline, charts, and controls.

---

## 3. Dashboard Components

| Component | Module | Key Features & Authority |
| :--- | :--- | :--- |
| **Header Banner** | `components/header.py` | Rotax 912 identity, simulation prototype badge, active mode, non-certified disclaimer |
| **Primary Health Card** | `components/health_card.py` | Health state (`HEALTHY`, `DEGRADED`, `CRITICAL`, `UNKNOWN`), Health Index score (0–100), active fault, sequence integrity |
| **Engine Telemetry** | `components/engine_parameters.py` | RPM, throttle, fuel flow, 4x EGT, 4x CHT, oil pressure, oil temperature, altitude, airspeed |
| **Prognostics Panel** | `components/rul_panel.py` | Point RUL, calibrated [Q10, Q90] bounds, damage state, Category C scientific disclosure |
| **Physics Residuals** | `components/residual_panel.py` | Max EGT/CHT residuals, oil pressure/RPM residuals, EWMA anomaly status vs 3-sigma thresholds |
| **Physical Limits** | `components/redline_panel.py` | Authoritative Rotax 912 limits from `HealthStateEngine` (Normal, Caution, Alert, Redline) |
| **Fault Isolation** | `components/fault_panel.py` | Multi-channel coupling discriminator isolating plant anomalies from sensor drifts |
| **Explainability** | `components/explanation_panel.py` | Deterministic `EvidenceItem` causal chain, physical coupling indicators, diagnostic basis |
| **Telemetry Health** | `components/telemetry_health.py` | Frames received, processed, invalid, sequence gaps, and runtime compute latency |
| **Mission Timeline** | `components/timeline.py` | Chronological log of detected milestone events with precise timestamps |
| **Time-Series Charts** | `components/charts.py` | Real-time line plots for RPM, EGT, CHT, oil pressure, oil temp, RUL, Health Index, and residuals |
| **Mission Controls** | `components/controls.py` | Fault scenario selection, severity slider, duration/rate config, step/run/reset controls, sortie selector |

---

## 4. Live Telemetry Integration

Live telemetry is driven by `LiveMissionController`:
1. **Dynamic Mission Profile:** Generates altitude, airspeed, and throttle trajectories (`climb`, `patrol_cruise`).
2. **Plant Simulation:** Steps `AeroEnginePlant` with ISA atmospheric lapse and thermodynamic combustion equations at 10.0 Hz.
3. **CAN 2.0B Encoding:** `EngineCANEncoder` packs signals into DBC messages and 28-byte wire envelopes with CRC-8 and frame counters.
4. **Localhost UDP Transport:** `LocalUDPTransport` transmits frames over an ephemeral localhost UDP port.
5. **Decoding & Verification:** `EngineCANDecoder` unpacks frames, validates CRC-8, sequence continuity, and arbitration IDs.
6. **Digital Twin Runtime:** `DigitalTwinRuntime` evaluates physics observer expected values, computes EWMA residuals, executes fault discrimination, evaluates stateless RUL, and compiles causal evidence.
7. **Canonical State:** `DigitalTwinState` is emitted and adapted for visualization with zero redundant computation.

---

## 5. Fault Injection

The dashboard supports user-controlled live fault injection into the physical plant model:
* **Nominal Flight:** Zero degradation. Powerplant operates within baseline limits.
* **Injector Clog (Cylinder 2):** Restricts fuel flow to target cylinder. Generates lean combustion, elevates localized EGT (+80–110°C), droops shaft RPM (-150–300 RPM), triggers `DEGRADED` health state, accelerates RUL consumption, and generates causal evidence.
* **Oil System Leak:** Reduces oil pump circuit pressure (<1.8 bar caution, <1.5 bar redline), elevates oil sump temperature, triggers `CRITICAL` state, and collapses RUL.
* **Thermocouple Sensor Drift (EGT2):** Injects non-physical instrument bias (+30–50°C). Discriminator identifies absence of engine RPM droop and classifies as `SENSOR_FAULT` without falsely degrading mechanical health.
* **Cooling Duct Blockage:** Simulates aerodynamic ram-air restriction over cowling cooling ducts, elevating global CHTs.

---

## 6. Mission Replay

Historical flight replay is managed by `MissionReplayController`:
* **Read-Only Manifest Loading:** Automatically indexes all 150 historical sorties recorded in `data/dataset_manifest.json`.
* **Zero Modification Guarantee:** Replay reads CSV rows using standard read-only file streams.
* **Authentic Runtime Feed:** Each row is decoded into a telemetry dictionary and fed directly into `DigitalTwinRuntime.process(telemetry, dt)`.
* **Identical State Progression:** Guarantees that historical replay produces identical health states, RUL predictions, residuals, and explanations as live simulation.
* **Playback Controls:** Play, pause, step (1 frame / 10 frames), seek, and reset.

---

## 7. Explainability

In strict accordance with project rules, zero natural language models or generative LLMs are employed.
Diagnostic explanations are compiled deterministically by `digital_twin/explanation.py` into structured `EvidenceItem` records:
* **Residual Verification:** Direct numeric residuals against physics observer expected values (e.g. `egt_residual: +88.7 °C`).
* **Cross-Channel Coupling:** Physical correlation verification (e.g., thermal spike accompanied by crankshaft deceleration confirms combustion fault vs. sensor drift).
* **Machine-Readable Structure:** Formatted with feature name, signed value, engineering unit, and physical departure direction.

---

## 8. Performance Benchmark

A continuous 30-second live simulation benchmark (300 cycles @ 10 Hz) was executed using `tests/benchmark_phase4.py`:

```text
==============================================================================
PHASE 4 BENCHMARK: 30-SECOND LIVE SIMULATION (300 CYCLES @ 10 HZ)
==============================================================================
Target Mission Cycles: 300 (Rate: 10.0 Hz, Duration: 30.0 s)

BENCHMARK RESULTS:
------------------------------------------------------------------------------
Frames Sent / Profile Cycles:    300
Frames Received & Decoded:      300
Dropped Frames:                 0 (0.00%)
Invalid Frames:                 0
Total Execution Wall Clock:     7.794 s
Effective Telemetry Rate:       38.5 Hz (as fast as possible)
History Buffer Size:            300 / 300 (Bounded: True)
Timeline Milestone Events:      5 logged
Peak Memory Allocated:          15.86 MB
Current Memory Allocated:       0.82 MB

LATENCY DISTRIBUTION (End-to-End Pipeline: Plant + CAN + UDP + Decode + DT Runtime):
  Min Latency:                  19.284 ms
  Mean Latency:                 25.350 ms
  Median (p50):                 24.131 ms
  95th Percentile (p95):        35.302 ms
  99th Percentile (p99):        50.408 ms
  Max Latency:                  56.750 ms
  Available Budget per Frame:   100.0 ms (@ 10 Hz) -> Headroom: 64.7 ms

DASHBOARD STATE ADAPTATION OVERHEAD:
  Mean Adaptation Time:         0.175 ms
  95th Percentile:              0.272 ms
------------------------------------------------------------------------------
VERDICT: PASS — Pipeline comfortably meets 10 Hz real-time constraint with >64% headroom.
==============================================================================
```

---

## 9. Test Results

### Phase 4 Test Suite (`tests/test_dashboard.py`)
All 15 rigorous acceptance tests passed completely:

| Test ID | Objective | Result |
| :--- | :--- | :--- |
| **Test A** | Dashboard imports and component module resolution | **PASS** |
| **Test B** | State adaptation from `DigitalTwinState` to `DashboardState` | **PASS** |
| **Test C** | No diagnosis duplication (adapter strictly projects canonical state) | **PASS** |
| **Test D** | Nominal state display representation | **PASS** |
| **Test E** | Injector clog representation and progressive degradation | **PASS** |
| **Test F** | Oil leak representation and critical lubrication alert | **PASS** |
| **Test G** | Sensor drift representation and instrument isolation | **PASS** |
| **Test H** | Cooling duct blockage representation | **PASS** |
| **Test I** | UNKNOWN state handling on invalid telemetry | **PASS** |
| **Test J** | Sequence gap detection and degraded transport status | **PASS** |
| **Test K** | RUL, Q10, and Q90 passthrough numerical integrity | **PASS** |
| **Test L** | Explainability causal grounding (`EvidenceItem` tracking) | **PASS** |
| **Test M** | Replay controller instantiates and invokes genuine `DigitalTwinRuntime` | **PASS** |
| **Test N** | Dataset integrity verification (zero modifications to `data/`) | **PASS** |
| **Test O** | Full E2E unmocked simulation pipeline across all 5 fault scenarios | **PASS** |

### Complete Regression Baseline
All prior phase regression suites were executed and verified:
* `python plant_model/test_plant.py` $\rightarrow$ **6/6 PASS**
* `python plant_model/validate_phase1.py` $\rightarrow$ **100% PASS**
* `python can_bus/test_can_roundtrip.py` $\rightarrow$ **60/60 signals (100.0%) PASS**
* `python can_bus/test_end_to_end_stream.py` $\rightarrow$ **24/24 PASS**
* `python ml_layer/validate_phase3.py` $\rightarrow$ **4/4 PASS**
* `python ml_layer/validate_phm.py` $\rightarrow$ **100% integrity ($R^2=0.996$, MAE 1.09h) PASS**
* `python digital_twin/test_runtime.py` $\rightarrow$ **9/9 PASS**
* `python tests/test_digital_twin_end_to_end.py` $\rightarrow$ **6/6 PASS**
* `python tests/test_dashboard.py` $\rightarrow$ **15/15 PASS**

---

## 10. Dataset Integrity

* `data/dataset_manifest.json` SHA-256 before testing: `VERIFIED UNCHANGED`
* `data/*.csv` files (150 runs): `VERIFIED UNCHANGED`
* `git diff -- data/`: **Clean (0 bytes modified)**

---

## 11. Model Integrity

* `ml_layer/models/rul_models.joblib`: `VERIFIED UNCHANGED`
* Zero model retraining performed during Phase 4.
* `git diff -- ml_layer/models/`: **Clean (0 bytes modified)**

---

## 12. Known Limitations & Scientific Disclosures

1. **Category C RUL Target Disclosure:**
   The RUL target in this prototype is a **Category C — Hybrid Heuristic/Synthetic Degradation Countdown** computed from physical stress and temperature-pressure margins. It is **not** empirical metallurgical wear-life data from destroyed engine components.
2. **Weak Cooling Blockage Coupling:**
   As verified in Phase 3A, cooling duct blockage exhibits weak convective thermal coupling under typical UAV cruise conditions. The system honestly documents this physical reality rather than inflating detection metrics artificially.
3. **Engineering Prototype Scope:**
   This system is an engineering research prototype running on virtual telemetry transports. It is **not** certified flight software (DO-178C / DO-254) and generates no autonomous flight-control commands.

---

## 13. Reproducibility Instructions

### Startup Command
```bash
# Launch Mission Control Dashboard
streamlit run dashboard/app.py
```

### Demonstration Procedure
1. **Nominal Engine Baseline:**
   - Select `Live Simulation` mode in the sidebar.
   - Scenario: `Nominal Flight`.
   - Click `▶ Step 10 Frames` or `⚡ Run Full Mission`.
   - Observe `HEALTHY` green state, normal residuals, and stable ~150h RUL.
2. **Injector Clog Combustion Anomaly:**
   - Select `Injector Clog (Cyl 2)` with Severity `0.60`.
   - Click `🔄 Apply Config & Reset`, then `⚡ Run Full Mission`.
   - Observe: Cylinder 2 EGT rises to ~920°C, RPM droops by ~250 RPM, health transitions to `DEGRADED`, RUL drops to ~38h, and Explainability displays exact causal residuals.
3. **Oil Leak Lubrication Failure:**
   - Select `Oil System Leak` with Severity `0.70`.
   - Click `🔄 Apply Config & Reset`, then `⚡ Run Full Mission`.
   - Observe: Oil pressure drops below 1.5 bar redline, health transitions to `CRITICAL`, and physical boundary panel flags redline breach.
4. **Historical Sortie Replay:**
   - Select `Historical Mission Replay (Dataset CSV)` mode in the sidebar.
   - Choose any sortie (e.g. `run_001_injector_clog_cyl1_sev49.csv`).
   - Click `⏩ Step 10 Rows` or `⚡ Replay Entire Sortie`.
   - Observe historical telemetry and diagnostic evolution processed through the authentic `DigitalTwinRuntime`.
5. **Canonical JSON State Export:**
   - Click `💾 Download DigitalTwinState JSON` in the sidebar or expand `Inspect Raw JSON State` to view the canonical data model.
