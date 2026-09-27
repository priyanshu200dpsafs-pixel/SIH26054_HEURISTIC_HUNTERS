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
  - Physics-grounded simulator: [`plant_model/engine_plant.py`](file:///Users/priyanshu/Desktop/uav-digital-twin/plant_model/engine_plant.py)
  - Validation test suite: [`plant_model/test_plant.py`](file:///Users/priyanshu/Desktop/uav-digital-twin/plant_model/test_plant.py)
  - 150-run labeled synthetic dataset: [`data/`](file:///Users/priyanshu/Desktop/uav-digital-twin/data/) and [`data/dataset_manifest.json`](file:///Users/priyanshu/Desktop/uav-digital-twin/data/dataset_manifest.json)
  - Engineering Notes: [`docs/PHASE_1_NOTES.md`](file:///Users/priyanshu/Desktop/uav-digital-twin/docs/PHASE_1_NOTES.md)

- **Phase 2: CAN Bus Layer (Complete & Validated)**
  - CAN DBC Message Matrix: [`can_bus/engine_telemetry.dbc`](file:///Users/priyanshu/Desktop/uav-digital-twin/can_bus/engine_telemetry.dbc)
  - Telemetry Packager / Broadcaster: [`can_bus/can_pack.py`](file:///Users/priyanshu/Desktop/uav-digital-twin/can_bus/can_pack.py)
  - Telemetry Listener / Decoder: [`can_bus/can_listen.py`](file:///Users/priyanshu/Desktop/uav-digital-twin/can_bus/can_listen.py)
  - Automated Round-Trip Accuracy Test: [`can_bus/test_can_roundtrip.py`](file:///Users/priyanshu/Desktop/uav-digital-twin/can_bus/test_can_roundtrip.py) (100% PASS)
  - Protocol Specification: [`docs/PHASE_2_NOTES.md`](file:///Users/priyanshu/Desktop/uav-digital-twin/docs/PHASE_2_NOTES.md)

- **Phase 3: ML / Residual + RUL Layer (Complete & Validated)**
  - Physics Expected State Estimator: [`ml_layer/physics_estimator.py`](file:///Users/priyanshu/Desktop/uav-digital-twin/ml_layer/physics_estimator.py)
  - EWMA Residual & Anomaly Detector: [`ml_layer/residual_detector.py`](file:///Users/priyanshu/Desktop/uav-digital-twin/ml_layer/residual_detector.py)
  - Sensor vs Plant Fault Discriminator: [`ml_layer/fault_discriminator.py`](file:///Users/priyanshu/Desktop/uav-digital-twin/ml_layer/fault_discriminator.py)
  - Quantile RUL Regressor with Uncertainty: [`ml_layer/rul_estimator.py`](file:///Users/priyanshu/Desktop/uav-digital-twin/ml_layer/rul_estimator.py)
  - Trained RUL Models: [`ml_layer/models/rul_models.joblib`](file:///Users/priyanshu/Desktop/uav-digital-twin/ml_layer/models/rul_models.joblib)
  - Automated 4-Test Verification Suite: [`ml_layer/validate_phase3.py`](file:///Users/priyanshu/Desktop/uav-digital-twin/ml_layer/validate_phase3.py) (All 4 tests PASS)
  - Core Defense Guide for Judges: [`docs/PHASE_3_NOTES.md`](file:///Users/priyanshu/Desktop/uav-digital-twin/docs/PHASE_3_NOTES.md)

---

## Verification & Quick Start

```bash
# 1. Run Phase 1 Physics & Unit Validation
python3 plant_model/test_plant.py
python3 plant_model/validate_phase1.py

# 2. Run Phase 2 CAN Bus Round-Trip Accuracy Check
python3 can_bus/test_can_roundtrip.py

# 3. Run Phase 3 Digital Twin & RUL Self-Validation Suite
python3 ml_layer/validate_phase3.py
```
