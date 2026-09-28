# UAV Aero Piston Engine Digital Twin
**Smart India Hackathon / DRDO Problem Statement: Explainable Digital Twin for MALE UAV Propulsion**

A physics-grounded, explainable, real-time digital twin for a 4-cylinder aero piston powerplant (Rotax 912-class, ~100 HP, air/liquid-cooled).

---

## Architecture Overview

```
uav-digital-twin/
├── plant_model/          # Phase 1: Physics simulation, ISA atmosphere & fault injection
├── can_bus/              # Phase 2: CAN bus DBC matrix, frame packing & virtual CAN transceiver
├── ml_layer/             # Phase 3: Physics-expected estimator, residual tracker & RUL model
├── dashboard/            # Phase 4: Ground Control Station (GCS) telemetry & health UI
├── data/                 # Generated synthetic mission runs & dataset manifest
├── docs/                 # Engineering notes, physics defense guides, and architecture specs
└── README.md
```

---

## Project Status

- **Phase 1: Plant Model (Complete & Validated)**
  - Core Physics Primitives (Single Source of Truth): [`plant_model/physics_core.py`](plant_model/physics_core.py)
  - Physics-grounded simulator: [`plant_model/engine_plant.py`](plant_model/engine_plant.py)
  - Validation test suite: [`plant_model/test_plant.py`](plant_model/test_plant.py)
  - 150-run labeled synthetic dataset: [`data/`](data/) and [`data/dataset_manifest.json`](data/dataset_manifest.json)
  - Engineering Notes: [`docs/PHASE_1_NOTES.md`](docs/PHASE_1_NOTES.md)

- **Phase 2: Live End-to-End Telemetry Integration (Complete & Validated)**
  - Orchestrator Entrypoint: [`run_mission_stream.py`](run_mission_stream.py)
  - Transport Abstraction: [`can_bus/transport.py`](can_bus/transport.py)
  - Localhost UDP Transport: [`can_bus/local_udp_transport.py`](can_bus/local_udp_transport.py)
  - Simulation Wire Envelope & CRC-8: [`can_bus/frame_envelope.py`](can_bus/frame_envelope.py)
  - CAN Frame Encoder: [`can_bus/can_encoder.py`](can_bus/can_encoder.py)
  - CAN Frame Decoder: [`can_bus/can_decoder.py`](can_bus/can_decoder.py)
  - Telemetry Event Model: [`can_bus/telemetry_event.py`](can_bus/telemetry_event.py)
  - End-to-End Verification Test Suite: [`can_bus/test_end_to_end_stream.py`](can_bus/test_end_to_end_stream.py) (24/24 PASS)
  - Legacy DBC Round-Trip Check: [`can_bus/test_can_roundtrip.py`](can_bus/test_can_roundtrip.py) (100% PASS)

- **Phase 3: ML / Residual + RUL Layer (Complete & Validated)**
  - Physics Expected State Estimator: [`ml_layer/physics_estimator.py`](ml_layer/physics_estimator.py)
  - EWMA Residual & Anomaly Detector: [`ml_layer/residual_detector.py`](ml_layer/residual_detector.py)
  - Sensor vs Plant Fault Discriminator: [`ml_layer/fault_discriminator.py`](ml_layer/fault_discriminator.py)
  - Quantile RUL Regressor with Uncertainty: [`ml_layer/rul_estimator.py`](ml_layer/rul_estimator.py)
  - Trained RUL Models: [`ml_layer/models/rul_models.joblib`](ml_layer/models/rul_models.joblib)
  - Automated 4-Test Verification Suite: [`ml_layer/validate_phase3.py`](ml_layer/validate_phase3.py) (All 4 tests PASS)
  - Core Defense Guide for Judges: [`docs/PHASE_3_NOTES.md`](docs/PHASE_3_NOTES.md)

---

## Phase 2: Live Telemetry Pipeline Architecture

```text
                    ┌────────────────────────┐
                    │      ENGINE PLANT      │
                    │   AeroEnginePlant      │
                    └───────────┬────────────┘
                                │ sensor telemetry dict
                                ▼
                    ┌────────────────────────┐
                    │    CAN FRAME ENCODER   │
                    │   EngineCANEncoder     │
                    │  (DBC + 28B envelope)  │
                    └───────────┬────────────┘
                                │ 4x 28B wire envelopes
                                ▼
                    ┌────────────────────────┐
                    │  TRANSPORT ABSTRACTION │
                    │    LocalUDPTransport   │
                    │  (127.0.0.1:<port>)    │
                    └───────────┬────────────┘
                                │ UDP datagrams
                                ▼
                    ┌────────────────────────┐
                    │    CAN FRAME DECODER   │
                    │   EngineCANDecoder     │
                    │ (CRC8, seq, DBC, 0x100)│
                    └───────────┬────────────┘
                                │ validated decoded telemetry
                                ▼
                    ┌────────────────────────┐
                    │    PHYSICS OBSERVER    │
                    │ PhysicsExpectedEstimator│
                    └───────────┬────────────┘
                                │ expected values
                                ▼
                    ┌────────────────────────┐
                    │   RESIDUAL DETECTOR    │
                    │ ResidualAnomalyDetector│
                    │ (EWMA + 3-sigma check) │
                    └───────────┬────────────┘
                                │ residuals & status
                                ▼
                    ┌────────────────────────┐
                    │  FAULT DISCRIMINATOR   │
                    │   FaultDiscriminator   │
                    │ (coupling vs. sensor)  │
                    └───────────┬────────────┘
                                │ classification
                                ▼
                    ┌────────────────────────┐
                    │     RUL ESTIMATOR      │
                    │      RULEstimator      │
                    │  (Quantile RF model)   │
                    └───────────┬────────────┘
                                │ RUL hours & intervals
                                ▼
                    ┌────────────────────────┐
                    │    TELEMETRY EVENT     │
                    │     TelemetryEvent     │
                    │  (Console / JSON line) │
                    └────────────────────────┘
```

> **IMPORTANT NOTICE REGARDING TRANSPORT LAYER:**
> The localhost UDP socket (`127.0.0.1:<port>`) is a **software simulation IPC transport** designed for zero-privilege cross-platform execution on Windows, Linux, and macOS without requiring physical CAN adapters or kernel modules.
> It encapsulates standard 8-byte CAN payloads inside a 28-byte wire envelope with CRC-8 and sequence numbers.
> This transport envelope is strictly for simulation telemetry integrity and must **NOT** be confused with physical aircraft CAN-bus hardware (e.g. ISO 11898, ARINC 825, or SocketCAN hardware interfaces).

---

## Verification & Quick Start

```bash
# 0. Install Dependencies
pip install -r requirements.txt

# 1. Run Phase 1 Physics & Unit Validation
python plant_model/test_plant.py
python plant_model/validate_phase1.py

# 2. Run Phase 2 CAN Bus Regression Check
python can_bus/test_can_roundtrip.py

# 3. Run Phase 2 Comprehensive End-to-End Test Suite (24 tests)
python can_bus/test_end_to_end_stream.py

# 4. Run Phase 3 Digital Twin & RUL Self-Validation Suite
python ml_layer/validate_phase3.py
```

### Running the Live Telemetry Stream

```bash
# Nominal flight stream (10 Hz, 30s)
python run_mission_stream.py --duration 30 --rate 10

# Injector clog fault on Cylinder 3 (35% severity)
python run_mission_stream.py --duration 30 --rate 10 --fault injector_clog --severity 0.35 --seed 42

# Sensor drift fault on EGT Sensor 1
python run_mission_stream.py --duration 30 --rate 10 --fault sensor_drift --sensor egt1 --severity 0.50

# Oil leak fault (pressure collapse & friction heating)
python run_mission_stream.py --duration 30 --rate 10 --fault oil_leak --severity 0.55

# Cooling duct blockage (cowl airflow restriction)
python run_mission_stream.py --duration 30 --rate 10 --fault cooling_blockage --severity 0.50

# Fast simulation mode (max CPU throughput for batch testing)
python run_mission_stream.py --duration 30 --rate 10 --fast

# Machine-readable JSON output (streamed per timestep)
python run_mission_stream.py --duration 5 --rate 10 --json
```

---

## Phase 3B: Real-Time Intelligent Digital Twin

Phase 3B integrates the live CAN telemetry pipeline with the scientific PHM subsystem into a **single unified real-time runtime engine** (`DigitalTwinRuntime`).

### Real-Time Runtime Pipeline

```text
       PLANT (Rotax 912 Dynamic Simulator)
         ↓
       CAN ENCODER (DBC packing + 28-byte wire envelope)
         ↓
       TRANSPORT (Localhost UDP IPC loopback)
         ↓
       CAN DECODER (CRC-8, sequence continuity, 0x100 parity)
         ↓
       TELEMETRY EVENT (Validated sensor dictionary)
         ↓
       PHYSICS OBSERVER (Analytical expected model)
         ↓
       RESIDUAL DETECTION (EWMA + 3-sigma statistical thresholds)
         ↓
       FAULT CLASSIFICATION (Multivariate cross-channel coupling)
         ↓
       RUL ESTIMATION (Stateless Quantile Random Forest)
         ↓
       UNCERTAINTY CALIBRATION (Calibrated [Q10, Q90] prediction intervals)
         ↓
       EXPLAINABILITY (Evidence-based physical causal reasoning)
         ↓
       UNIFIED DIGITAL TWIN STATE (DigitalTwinState)
         ↓
       STRUCTURED OUTPUT (Terminal Diagnostic Cards / Streaming JSON)
```

### Running the Digital Twin Runtime

#### 1. Nominal Flight Run
```bash
python run_digital_twin.py --duration 30 --rate 10 --seed 42
```

#### 2. Injected Fault Run (Cylinder 2 Injector Clog)
```bash
python run_digital_twin.py \
    --fault injector_clog \
    --severity 0.6 \
    --duration 30 \
    --rate 10 \
    --seed 42
```

#### 3. Machine-Readable JSON Streaming
```bash
python run_digital_twin.py \
    --fault injector_clog \
    --severity 0.6 \
    --duration 30 \
    --rate 10 \
    --json
```

#### 4. Verbose Diagnostic Terminal Cards
```bash
python run_digital_twin.py \
    --fault oil_leak \
    --severity 0.6 \
    --duration 20 \
    --rate 10 \
    --verbose
```

### Running the Test Suites

```bash
# Phase 3B Runtime Unit Tests (Tests A through I)
python digital_twin/test_runtime.py

# Phase 3B Full End-to-End Pipeline Integration Tests
python tests/test_digital_twin_end_to_end.py
```

### Scientific Honesty & Known Limitations

1. **Simulation RUL Target Disclosure:**
   The RUL target in this prototype represents a **hybrid heuristic/synthetic degradation countdown** calibrated to simulated thermal, mechanical, and cumulative operating stress. It must **NOT** be claimed as certified or empirically validated remaining engine life.
2. **Cooling Duct Blockage Limitation:**
   As verified in Phase 3A held-out evaluation, cooling duct blockage exhibits weak CHT coupling under typical UAV loiter cruise airflows (residual magnitude remains below caution thresholds). The system documents this known limitation rather than fabricating false certainty.
3. **Simulation-Only Environment:**
   This system is an engineering research prototype running over virtual simulation transports. It is **not** certified for autonomous aircraft flight control, safety-critical decision making, or real aircraft dispatch without formal DO-178C / DO-254 qualification.
4. **No LLM / No Black-Box Hallucinations:**
   Explanations are deterministically compiled from real physics residuals, cross-channel coupling metrics, and redline checks. No generative language models or ungrounded statistics are involved.
