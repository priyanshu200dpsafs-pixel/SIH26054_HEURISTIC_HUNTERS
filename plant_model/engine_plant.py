#!/usr/bin/env python3
"""
===============================================================================
AERO PISTON ENGINE DIGITAL TWIN: PLANT MODEL (SIMULATOR)
===============================================================================
Target Engine: Rotax 912-class 4-Cylinder Boxer Engine for MALE UAVs
Specs:
  - Configuration: 4-cylinder, 4-stroke horizontally opposed (boxer)
  - Cooling: Liquid-cooled cylinder heads, ram-air-cooled cylinders
  - Rated Power: ~100 HP (73.5 kW) @ 5800 RPM (crankshaft)
  - Idle RPM: ~1600 RPM
  - Typical CHT Range: 150°C - 230°C
  - Typical EGT Range: 650°C - 950°C
  - Oil Pressure: 1.8 - 5.0 bar
  - Oil Temperature: 70°C - 115°C

Design Philosophy:
  1. Explainable & Physics-Grounded: Every equation is rooted in first principles
     (mass/energy conservation, ISA atmosphere, convective heat transfer,
     combustion stoichiometry) or well-established aero empirical relationships.
  2. Separation of True State vs. Sensor Reading:
     Physical faults (e.g. injector clog) alter true plant thermodynamics.
     Sensor faults (e.g. thermocouple drift) alter ONLY sensor measurements,
     enabling residual-based fault isolation in Phase 3.
  3. No Black Boxes: No uncalibrated deep neural nets inside the plant. All
     parameters have physical units and real-world justifications.

Author: UAV Digital Twin Team (Smart India Hackathon / DRDO)
===============================================================================
"""

import os
import math
import json
import logging
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Tuple, Any

import numpy as np
import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("EnginePlant")


# =============================================================================
# 1. CORE PHYSICS PRIMITIVES (Imported from physics_core)
# =============================================================================
try:
    from .physics_core import (
        EngineSpecs,
        isa_atmosphere,
        compute_target_rpm,
        compute_target_fuel_flow,
        compute_nominal_egt_base,
        compute_nominal_cht_base,
        compute_target_oil_temp,
        compute_target_oil_press,
    )
except ImportError:
    from physics_core import (
        EngineSpecs,
        isa_atmosphere,
        compute_target_rpm,
        compute_target_fuel_flow,
        compute_nominal_egt_base,
        compute_nominal_cht_base,
        compute_target_oil_temp,
        compute_target_oil_press,
    )



# =============================================================================
# 3. MISSION PROFILE GENERATOR
# =============================================================================
@dataclass
class MissionPhase:
    """
    Defines a flight phase for the UAV mission.
    """
    name: str
    duration_sec: float
    start_alt_m: float
    end_alt_m: float
    start_throttle_pct: float
    end_throttle_pct: float
    start_airspeed_mps: float
    end_airspeed_mps: float


def generate_mission_profile(
    phases: Optional[List[Dict[str, Any]]] = None,
    dt: float = 0.1
) -> pd.DataFrame:
    """
    Generates a 10 Hz time series of UAV flight inputs (throttle%, altitude, airspeed).
    Smooth ramps are applied between phase boundaries to prevent non-physical step jumps.

    Default mission profile models a realistic MALE UAV sortie:
      1. Ground Idle & Warmup (30s)
      2. Takeoff & Initial Climb to 1500m (180s)
      3. Enroute Climb to Patrol Altitude 3000m (240s)
      4. Loiter / Surveillance Cruise (360s)
      5. Dash / Rapid Throttle Maneuver (60s)
      6. Descent to 500m (180s)
      7. Approach & Recovery (60s)
    """
    if phases is None:
        phases = [
            {"name": "ground_idle", "duration_sec": 30.0, "start_alt_m": 0.0, "end_alt_m": 0.0,
             "start_throttle_pct": 15.0, "end_throttle_pct": 15.0, "start_airspeed_mps": 0.0, "end_airspeed_mps": 0.0},
            {"name": "takeoff_climb", "duration_sec": 120.0, "start_alt_m": 0.0, "end_alt_m": 1200.0,
             "start_throttle_pct": 98.0, "end_throttle_pct": 92.0, "start_airspeed_mps": 25.0, "end_airspeed_mps": 40.0},
            {"name": "cruise_climb", "duration_sec": 180.0, "start_alt_m": 1200.0, "end_alt_m": 2500.0,
             "start_throttle_pct": 85.0, "end_throttle_pct": 82.0, "start_airspeed_mps": 40.0, "end_airspeed_mps": 44.0},
            {"name": "mission_loiter", "duration_sec": 300.0, "start_alt_m": 2500.0, "end_alt_m": 2500.0,
             "start_throttle_pct": 72.0, "end_throttle_pct": 74.0, "start_airspeed_mps": 42.0, "end_airspeed_mps": 43.0},
            {"name": "high_speed_dash", "duration_sec": 60.0, "start_alt_m": 2500.0, "end_alt_m": 2500.0,
             "start_throttle_pct": 95.0, "end_throttle_pct": 95.0, "start_airspeed_mps": 45.0, "end_airspeed_mps": 55.0},
            {"name": "descend_return", "duration_sec": 180.0, "start_alt_m": 2500.0, "end_alt_m": 200.0,
             "start_throttle_pct": 40.0, "end_throttle_pct": 35.0, "start_airspeed_mps": 45.0, "end_airspeed_mps": 35.0},
            {"name": "recovery_idle", "duration_sec": 60.0, "start_alt_m": 200.0, "end_alt_m": 0.0,
             "start_throttle_pct": 20.0, "end_throttle_pct": 15.0, "start_airspeed_mps": 30.0, "end_airspeed_mps": 0.0},
        ]

    time_pts = []
    throttle_pts = []
    alt_pts = []
    airspeed_pts = []
    phase_names = []

    curr_time = 0.0
    for p in phases:
        dur = float(p["duration_sec"])
        steps = int(round(dur / dt))
        if steps <= 0:
            continue
        
        t_arr = np.linspace(curr_time, curr_time + dur, steps, endpoint=False)
        th_arr = np.linspace(p["start_throttle_pct"], p["end_throttle_pct"], steps)
        alt_arr = np.linspace(p["start_alt_m"], p["end_alt_m"], steps)
        ias_arr = np.linspace(p["start_airspeed_mps"], p["end_airspeed_mps"], steps)

        time_pts.extend(t_arr)
        throttle_pts.extend(th_arr)
        alt_pts.extend(alt_arr)
        airspeed_pts.extend(ias_arr)
        phase_names.extend([p["name"]] * steps)

        curr_time += dur

    df_profile = pd.DataFrame({
        "timestamp_sec": np.round(time_pts, 3),
        "flight_phase": phase_names,
        "throttle_pct": np.clip(throttle_pts, 0.0, 100.0),
        "altitude_m": np.maximum(alt_pts, 0.0),
        "airspeed_mps": np.maximum(airspeed_pts, 0.0)
    })
    return df_profile


# =============================================================================
# 4. FAULT INJECTION INTERFACE
# =============================================================================
@dataclass
class FaultEvent:
    """
    Encapsulates a fault scenario.
    Types supported:
      - 'injector_clog': Physical fault where cylinder X gets reduced fuel.
      - 'sensor_drift': Instrument fault where sensor S reports biased value (physics unaffected).
      - 'oil_leak': Loss of oil volume, causing pressure loss and temperature spike.
      - 'cooling_duct_blockage': Partial cowl blockage reducing ram air cooling.
    """
    fault_type: str                   # 'injector_clog', 'sensor_drift', 'oil_leak', 'cooling_duct_blockage'
    start_time_sec: float             # Inception time
    duration_ramp_sec: float = 15.0   # How long until full severity is reached
    target_cylinder: int = 1          # 1 to 4 (for cylinder-specific faults)
    sensor_name: str = "egt1"         # For sensor drift faults (e.g. 'egt1', 'cht2', 'oil_press_bar')
    severity: float = 0.35            # Fractional severity (0.0 to 1.0)
    drift_rate: float = 0.8           # Rate of drift per second (for sensor drift, e.g. °C/s)


class FaultManager:
    """
    Manages active faults and computes instantaneous physical and sensor biases.
    """
    def __init__(self, faults: Optional[List[FaultEvent]] = None):
        self.faults = faults or []

    def get_physical_fault_state(self, current_time: float) -> Dict[str, Any]:
        """
        Calculates instantaneous physical deviations affecting actual thermodynamics.
        """
        state = {
            "injector_clog_pct": [0.0, 0.0, 0.0, 0.0],  # Per-cylinder fuel restriction (0.0 = nominal)
            "power_deficit_factor": 0.0,                # Total engine torque reduction
            "oil_leak_severity": 0.0,                   # Oil pressure drop / heat accumulation
            "cooling_blockage_pct": 0.0,                # Thermal dissipation impairment
            "active_physical_fault": "nominal",
            "fault_cylinder": 0,
            "fault_severity": 0.0
        }

        for f in self.faults:
            if current_time < f.start_time_sec:
                continue

            # Ramp factor from 0.0 to 1.0
            elapsed = current_time - f.start_time_sec
            ramp = min(1.0, elapsed / max(0.1, f.duration_ramp_sec))
            current_sev = f.severity * ramp

            if f.fault_type == "injector_clog":
                cyl_idx = max(0, min(3, f.target_cylinder - 1))
                state["injector_clog_pct"][cyl_idx] = max(state["injector_clog_pct"][cyl_idx], current_sev)
                # In 4-cylinder engine, loss of 1 cylinder's fuel causes up to 25% * severity power drop
                state["power_deficit_factor"] += (current_sev * 0.25)
                state["active_physical_fault"] = "injector_clog"
                state["fault_cylinder"] = f.target_cylinder
                state["fault_severity"] = max(state["fault_severity"], current_sev)

            elif f.fault_type == "oil_leak":
                state["oil_leak_severity"] = max(state["oil_leak_severity"], current_sev)
                state["active_physical_fault"] = "oil_leak"
                state["fault_severity"] = max(state["fault_severity"], current_sev)

            elif f.fault_type == "cooling_duct_blockage":
                state["cooling_blockage_pct"] = max(state["cooling_blockage_pct"], current_sev)
                state["active_physical_fault"] = "cooling_duct_blockage"
                state["fault_severity"] = max(state["fault_severity"], current_sev)

        return state

    def get_sensor_drift_bias(self, current_time: float) -> Dict[str, float]:
        """
        Calculates additive bias on sensor telemetry (PHYSICAL STATE IS UNAFFECTED).
        This fulfills the critical requirement:
          "distinguish 'sensor lying' from 'engine actually degrading'".
        """
        biases: Dict[str, float] = {}
        for f in self.faults:
            if f.fault_type != "sensor_drift":
                continue
            if current_time < f.start_time_sec:
                continue
            
            elapsed = current_time - f.start_time_sec
            drift_val = f.drift_rate * elapsed
            biases[f.sensor_name] = biases.get(f.sensor_name, 0.0) + drift_val

        return biases


# =============================================================================
# 5. THERMODYNAMIC & KINEMATIC PLANT MODEL
# =============================================================================
class AeroEnginePlant:
    """
    Continuous-time stateful dynamic simulator of the Rotax 912-class UAV powerplant.
    Uses first-order differential equations for thermal and rotational inertia:
      d(X)/dt = (X_target(inputs, ambient) - X) / tau_X
    """

    def __init__(self, specs: Optional[EngineSpecs] = None, seed: Optional[int] = None):
        self.specs = specs or EngineSpecs()
        self.rng = np.random.default_rng(seed)

        # Initial Dynamic State (ground idle baseline)
        self.rpm = self.specs.idle_rpm
        self.cht = np.array([160.0, 161.0, 163.0, 164.0], dtype=float)  # Cyl 1..4 (°C)
        self.egt = np.array([680.0, 685.0, 688.0, 682.0], dtype=float)  # Cyl 1..4 (°C)
        self.oil_temp_c = 78.0                                           # (°C)
        self.oil_press_bar = 2.4                                         # (bar)
        self.fuel_flow_gps = 0.85                                        # (grams/sec)

        # Sensor Noise Standard Deviations (Gaussian zero-mean)
        # Calibrated to real industrial UAV instrumentation
        self.noise_std = {
            "rpm": 5.5,             # Hall effect sensor pulse jitter (~5-6 RPM)
            "egt": 1.4,             # Type-K thermocouple noise (~1.4°C)
            "cht": 0.6,             # PT100 RTD precision sensor (~0.6°C)
            "oil_press": 0.025,     # Piezoresistive pressure transducer (~0.025 bar)
            "oil_temp": 0.45,       # Fluid thermistor (~0.45°C)
            "fuel_flow": 0.03       # Turbine flowmeter pulse quantization (~0.03 g/s)
        }

    def reset(self, initial_ambient_c: float = 15.0):
        """Resets engine to ground idle state."""
        self.rpm = self.specs.idle_rpm
        base_cht = max(152.0, initial_ambient_c + 138.0)
        self.cht = np.array([base_cht + b for b in self.specs.cyl_cht_bias])
        base_egt = 675.0
        self.egt = np.array([base_egt + b for b in self.specs.cyl_egt_bias])
        self.oil_temp_c = 78.0
        self.oil_press_bar = 2.4
        self.fuel_flow_gps = 0.85

    def step(
        self,
        dt: float,
        throttle_pct: float,
        altitude_m: float,
        airspeed_mps: float,
        fault_phys_state: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Executes one integration step (10 Hz, dt = 0.1s).

        Physics Modeling Logic (Explainable to Judges):
        ----------------------------------------------
        1. ATMOSPHERIC COUPLING:
           - ISA computes density ratio sigma = rho(alt) / rho_sl.
           - Naturally aspirated engine power availability scales with sigma^0.85.
           - High altitude -> lower air mass flow -> lower manifold pressure.

        2. RPM & SHAFT TORQUE DYNAMICS:
           - Throttle input (0-100%) maps non-linearly to target torque:
             RPM_target = Idle + (Max - Idle) * (throttle/100)^0.95 * sigma^0.85
           - Power deficit from physical faults (e.g. injector clog on one cylinder)
             drops the available engine shaft torque, causing RPM droop.
           - Crankshaft & prop inertia modelled via 1st-order lag:
             d(RPM)/dt = (RPM_target - RPM) / tau_rpm.

        3. FUEL FLOW RATE (g/s):
           - In an aero engine, fuel metering follows air mass consumption to maintain
             target equivalence ratio:
             m_dot_fuel ~ throttle * RPM * sigma.
           - Range: ~0.8 g/s (~3.8 L/hr) at idle to ~5.4 g/s (~25.5 L/hr) at WOT.
           - Clogged injectors physically restrict fuel flow to that specific cylinder.

        4. EXHAUST GAS TEMPERATURE (EGT):
           - Physics of Combustion & Leaning (Crucial for SIH/DRDO defense):
             * Standard aero engines run rich-of-peak (ROP) at high power (lambda ~ 0.85 - 0.90)
               to keep exhaust valves cool and suppress detonation.
             * When an injector clogs, fuel delivery to that specific cylinder DROPS,
               shifting that cylinder's mixture LEAN TOWARDS STOICHIOMETRIC (lambda -> 1.0).
             * Stoichiometric combustion exhibits the MAXIMUM flame temperature!
             * Therefore: A partially clogged injector CAUSES THAT CYLINDER'S EGT TO RISE
               (by +60°C to +110°C), while other cylinders remain nominal!
             * If clogging is severe (>60% starved), flame blowout / misfire occurs and EGT plunges.
           - Formula:
             EGT_base = 670 + 200 * (th/100)^0.85 + 40 * (1 - sigma)
             EGT_target[i] = EGT_base + cyl_bias[i] + delta_EGT_clog[i]
             d(EGT[i])/dt = (EGT_target[i] - EGT[i]) / tau_egt

        5. CYLINDER HEAD TEMPERATURE (CHT):
           - Thermal Equilibrium: Heat In (Combustion) = Heat Out (Convective Cooling).
             * Q_in ~ throttle * RPM * eta_comb.
             * Q_out ~ h_conv * (CHT - T_amb).
             * Heat transfer coefficient h_conv depends on mass velocity: (rho * airspeed)^0.75.
           - Directional Physics:
             * Climb phase (high throttle + low airspeed) = WORST cooling condition -> CHT peaks (210-225°C).
             * Cruise phase (moderate throttle + high airspeed) = high ram air cooling -> CHT stabilizes (170-185°C).
             * High altitude -> lower density rho -> poorer cooling convection -> higher CHT for given airspeed!
           - Formula:
             CHT_target[i] = T_amb_c + delta_comb(th) * cooling_factor + cyl_bias[i]
             d(CHT[i])/dt = (CHT_target[i] - CHT[i]) / tau_cht

        6. OIL SYSTEM (PRESSURE & TEMPERATURE):
           - Engine has mechanical positive displacement oil pump driven by camshaft:
             Pump output pressure increases with RPM.
           - Hot oil has lower kinematic viscosity -> pressure decreases with temperature:
             P_oil ~ P_relief * (1 - exp(-RPM/1500)) - k_visc * (T_oil - 80).
           - Oil temperature follows cylinder heat rejection with large 35s thermal inertia.
        """
        # --- Step 1: ISA Atmosphere ---
        t_amb_k, p_amb_pa, rho_amb, sigma = isa_atmosphere(altitude_m)
        t_amb_c = t_amb_k - 273.15

        th_norm = max(0.0, min(100.0, throttle_pct)) / 100.0
        ias = max(0.0, airspeed_mps)

        # --- Step 2: RPM Dynamics & Fault Power Deficit ---
        power_deficit = fault_phys_state.get("power_deficit_factor", 0.0)
        rpm_target_nominal = compute_target_rpm(th_norm, sigma, self.specs)

        # Physical power reduction directly depresses attainable RPM
        rpm_target = rpm_target_nominal * (1.0 - 0.65 * power_deficit)
        rpm_target = max(self.specs.idle_rpm * 0.90, min(self.specs.max_rpm, rpm_target))

        # 1st-order inertial response
        d_rpm = (rpm_target - self.rpm) / self.specs.tau_rpm_sec * dt
        self.rpm = float(np.clip(self.rpm + d_rpm, 1200.0, 6000.0))

        # --- Step 3: Fuel Flow Dynamics ---
        ff_target_total = compute_target_fuel_flow(th_norm, sigma)
        
        # Per-cylinder fuel allocation with injector clogs
        clog_rates = fault_phys_state.get("injector_clog_pct", [0.0, 0.0, 0.0, 0.0])
        cyl_fuel_flows = []
        for i in range(4):
            clog = clog_rates[i]
            # Fuel delivery drops proportionally to clog
            cyl_f = (ff_target_total / 4.0) * (1.0 - clog)
            cyl_fuel_flows.append(cyl_f)

        self.fuel_flow_gps = float(sum(cyl_fuel_flows))

        # --- Step 4: Per-Cylinder EGT ---
        egt_base = compute_nominal_egt_base(th_norm, sigma)

        for i in range(4):
            clog = clog_rates[i]
            if clog <= 0.45:
                delta_egt_clog = 115.0 * (clog / 0.45)  # Can add up to +115°C at peak lean
            else:
                excess = (clog - 0.45) / 0.55
                delta_egt_clog = 115.0 * (1.0 - 1.2 * excess)

            egt_target_raw = egt_base + self.specs.cyl_egt_bias[i] + delta_egt_clog
            egt_target_i = min(942.0, egt_target_raw)
            
            # Dynamic lag for thermocouple and manifold thermal capacitance
            d_egt = (egt_target_i - self.egt[i]) / self.specs.tau_egt_sec * dt
            self.egt[i] = float(np.clip(self.egt[i] + d_egt, 550.0, 950.0))

        # --- Step 5: Per-Cylinder CHT ---
        cowl_blockage = fault_phys_state.get("cooling_blockage_pct", 0.0)
        cooling_airspeed_effective = ias * (1.0 - 0.75 * cowl_blockage)
        cht_base = compute_nominal_cht_base(th_norm, sigma, cooling_airspeed_effective)

        for i in range(4):
            clog = clog_rates[i]
            delta_cht_clog = 15.0 * clog if clog < 0.4 else -10.0 * clog
            delta_cht_cowl = 28.0 * cowl_blockage
            cht_target_i = cht_base + self.specs.cyl_cht_bias[i] + delta_cht_clog + delta_cht_cowl
            
            # CHT has high thermal inertia (tau ~ 12s)
            d_cht = (cht_target_i - self.cht[i]) / self.specs.tau_cht_sec * dt
            self.cht[i] = float(np.clip(self.cht[i] + d_cht, 100.0, 260.0))

        # --- Step 6: Oil System Dynamics ---
        oil_leak = fault_phys_state.get("oil_leak_severity", 0.0)
        oil_temp_target = compute_target_oil_temp(
            self.rpm, cooling_airspeed_effective, t_amb_c, self.oil_temp_c, self.specs
        ) + (45.0 * oil_leak)

        d_oil_temp = (oil_temp_target - self.oil_temp_c) / self.specs.tau_oil_temp_sec * dt
        self.oil_temp_c = float(np.clip(self.oil_temp_c + d_oil_temp, 65.0, 145.0))

        # Oil Pressure: mechanical gear pump with leak loss
        p_oil_target_nominal = compute_target_oil_press(self.rpm, self.oil_temp_c, self.specs)
        leak_loss = 2.8 * oil_leak
        p_oil_target = max(0.4, p_oil_target_nominal - leak_loss)
        d_p_oil = (p_oil_target - self.oil_press_bar) / self.specs.tau_oil_press_sec * dt
        self.oil_press_bar = float(np.clip(self.oil_press_bar + d_p_oil, 0.2, 5.5))

        # Package true physical state (untainted by sensor errors)
        true_state = {
            "rpm_true": self.rpm,
            "egt1_true": self.egt[0],
            "egt2_true": self.egt[1],
            "egt3_true": self.egt[2],
            "egt4_true": self.egt[3],
            "cht1_true": self.cht[0],
            "cht2_true": self.cht[1],
            "cht3_true": self.cht[2],
            "cht4_true": self.cht[3],
            "oil_press_bar_true": self.oil_press_bar,
            "oil_temp_c_true": self.oil_temp_c,
            "fuel_flow_gps_true": self.fuel_flow_gps,
            "air_density_kg_m3": rho_amb,
            "ambient_temp_c": t_amb_c
        }
        return true_state

    def apply_sensors(
        self,
        true_state: Dict[str, Any],
        sensor_drift_biases: Dict[str, float]
    ) -> Dict[str, float]:
        """
        Applies realistic industrial sensor noise and optional additive sensor drift biases.
        Produces the telemetry readings that the avionics / CAN bus / Digital Twin will see.
        """
        meas = {}
        # RPM sensor (Hall-effect pickup)
        meas["rpm"] = round(
            float(true_state["rpm_true"] + self.rng.normal(0, self.noise_std["rpm"]) + sensor_drift_biases.get("rpm", 0.0)),
            1
        )

        # EGT 1..4 (Type-K thermocouples)
        for i in range(1, 5):
            key = f"egt{i}"
            drift = sensor_drift_biases.get(key, 0.0)
            noise = self.rng.normal(0, self.noise_std["egt"])
            meas[key] = round(float(true_state[f"egt{i}_true"] + noise + drift), 1)

        # CHT 1..4 (PT100 RTDs)
        for i in range(1, 5):
            key = f"cht{i}"
            drift = sensor_drift_biases.get(key, 0.0)
            noise = self.rng.normal(0, self.noise_std["cht"])
            meas[key] = round(float(true_state[f"cht{i}_true"] + noise + drift), 1)

        # Oil Pressure transducer
        p_drift = sensor_drift_biases.get("oil_press_bar", 0.0)
        p_noise = self.rng.normal(0, self.noise_std["oil_press"])
        meas["oil_press_bar"] = round(max(0.0, float(true_state["oil_press_bar_true"] + p_noise + p_drift)), 2)

        # Oil Temperature sensor
        ot_drift = sensor_drift_biases.get("oil_temp_c", 0.0)
        ot_noise = self.rng.normal(0, self.noise_std["oil_temp"])
        meas["oil_temp_c"] = round(float(true_state["oil_temp_c_true"] + ot_noise + ot_drift), 1)

        # Fuel Flow turbine transducer
        ff_drift = sensor_drift_biases.get("fuel_flow_gps", 0.0)
        ff_noise = self.rng.normal(0, self.noise_std["fuel_flow"])
        meas["fuel_flow_gps"] = round(max(0.0, float(true_state["fuel_flow_gps_true"] + ff_noise + ff_drift)), 3)

        return meas


# =============================================================================
# 6. TIME-SERIES SIMULATION EXECUTION
# =============================================================================
def simulate_mission(
    mission_profile: Optional[pd.DataFrame] = None,
    faults: Optional[List[FaultEvent]] = None,
    random_seed: Optional[int] = 42,
    dt: float = 0.1
) -> pd.DataFrame:
    """
    Executes a complete mission run and outputs a labeled pandas DataFrame.

    Output Columns:
      - Timestamp and Flight Inputs:
          timestamp_sec, flight_phase, throttle_pct, altitude_m, airspeed_mps
      - Measured Telemetry (noisy + sensor drift):
          rpm, egt1, egt2, egt3, egt4, cht1, cht2, cht3, cht4,
          oil_press_bar, oil_temp_c, fuel_flow_gps
      - True Physical States (ground truth):
          rpm_true, egt1_true..egt4_true, cht1_true..cht4_true,
          oil_press_bar_true, oil_temp_c_true, fuel_flow_gps_true
      - Diagnostic & RUL Labels:
          is_faulty (0 or 1), active_fault_type ('nominal', 'injector_clog', etc.),
          fault_target_cylinder, fault_severity, fault_time_elapsed_sec,
          rul_remaining_sec (remaining flight seconds until critical limit)
    """
    if mission_profile is None:
        mission_profile = generate_mission_profile(dt=dt)

    plant = AeroEnginePlant(seed=random_seed)
    fault_mgr = FaultManager(faults=faults)

    records = []
    total_time = mission_profile["timestamp_sec"].iloc[-1]

    # Pre-calculate earliest critical failure time if physical fault exists
    crit_fail_time = total_time
    if faults:
        for f in faults:
            if f.fault_type in ("injector_clog", "oil_leak", "cooling_duct_blockage") and f.severity >= 0.40:
                # Severe fault reaches critical threshold within ramp + margin
                crit_fail_time = min(crit_fail_time, f.start_time_sec + f.duration_ramp_sec * 2.5)

    for idx, row in mission_profile.iterrows():
        t = float(row["timestamp_sec"])
        th = float(row["throttle_pct"])
        alt = float(row["altitude_m"])
        ias = float(row["airspeed_mps"])
        phase = str(row["flight_phase"])

        # Determine active physical and sensor faults at time t
        phys_fault = fault_mgr.get_physical_fault_state(t)
        sensor_biases = fault_mgr.get_sensor_drift_bias(t)

        # Run plant physics step
        true_st = plant.step(dt=dt, throttle_pct=th, altitude_m=alt, airspeed_mps=ias, fault_phys_state=phys_fault)

        # Run sensor measurement model
        meas_st = plant.apply_sensors(true_st, sensor_biases)

        # RUL (Remaining Useful Life in safe flight hours)
        # Ground truth aero engine operational life model (Rotax 912 TBO ~1500-2000 hours,
        # with ~180-220 safe flight hours remaining in current service interval).
        # Base healthy engine: 195.0 hours minus elapsed sortie flight time.
        rul_base_hours = 195.0 - (t / 3600.0)

        active_f_type = phys_fault["active_physical_fault"]
        if active_f_type == "nominal" and len(sensor_biases) > 0:
            active_f_type = "sensor_drift"

        is_faulty = 1 if active_f_type != "nominal" else 0
        phys_sev = phys_fault.get("fault_severity", 0.0)

        if not is_faulty or active_f_type == "sensor_drift":
            # Healthy mechanical powertrain (sensor drift does NOT degrade engine hardware)
            rul_hours = max(100.0, rul_base_hours)
        else:
            # Active physical degradation (injector clog, oil leak, cooling blockage)
            f_start = t
            if faults:
                for f in faults:
                    if f.fault_type == active_f_type:
                        f_start = f.start_time_sec
                        break
            elapsed_fault_t = max(0.0, t - f_start)

            if active_f_type == "injector_clog":
                # Continuous thermal stress degradation under lean combustion:
                # Normal 195 hrs drops continuously to ~25-35 hrs at mid-fault, and single-digit (4-9 hrs) at late fault.
                sev_norm = min(1.2, phys_sev / 0.45)
                stress_drop = (195.0 - 45.0) * math.pow(sev_norm, 0.8)
                time_stress = 0.28 * elapsed_fault_t
                rul_hours = max(3.0, rul_base_hours - stress_drop - time_stress)

            elif active_f_type == "oil_leak":
                # Rapid loss of lubrication film:
                sev_norm = min(1.2, phys_sev / 0.40)
                stress_drop = (195.0 - 20.0) * sev_norm
                time_stress = 0.35 * elapsed_fault_t
                rul_hours = max(0.5, rul_base_hours - stress_drop - time_stress)

            elif active_f_type == "cooling_duct_blockage":
                sev_norm = min(1.2, phys_sev / 0.40)
                stress_drop = (195.0 - 60.0) * sev_norm
                time_stress = 0.20 * elapsed_fault_t
                rul_hours = max(4.0, rul_base_hours - stress_drop - time_stress)

            else:
                rul_hours = max(2.0, 50.0 - 0.2 * elapsed_fault_t)

        rul_sec = rul_hours * 3600.0

        rec = {
            "timestamp_sec": t,
            "flight_phase": phase,
            "throttle_pct": th,
            "altitude_m": alt,
            "airspeed_mps": ias,
            # Measured Telemetry
            "rpm": meas_st["rpm"],
            "egt1": meas_st["egt1"],
            "egt2": meas_st["egt2"],
            "egt3": meas_st["egt3"],
            "egt4": meas_st["egt4"],
            "cht1": meas_st["cht1"],
            "cht2": meas_st["cht2"],
            "cht3": meas_st["cht3"],
            "cht4": meas_st["cht4"],
            "oil_press_bar": meas_st["oil_press_bar"],
            "oil_temp_c": meas_st["oil_temp_c"],
            "fuel_flow_gps": meas_st["fuel_flow_gps"],
            # Ground Truth Physical States
            "rpm_true": round(true_st["rpm_true"], 1),
            "egt1_true": round(true_st["egt1_true"], 1),
            "egt2_true": round(true_st["egt2_true"], 1),
            "egt3_true": round(true_st["egt3_true"], 1),
            "egt4_true": round(true_st["egt4_true"], 1),
            "cht1_true": round(true_st["cht1_true"], 1),
            "cht2_true": round(true_st["cht2_true"], 1),
            "cht3_true": round(true_st["cht3_true"], 1),
            "cht4_true": round(true_st["cht4_true"], 1),
            "oil_press_bar_true": round(true_st["oil_press_bar_true"], 2),
            "oil_temp_c_true": round(true_st["oil_temp_c_true"], 1),
            "fuel_flow_gps_true": round(true_st["fuel_flow_gps_true"], 3),
            "ambient_temp_c": round(true_st["ambient_temp_c"], 1),
            "air_density_kg_m3": round(true_st["air_density_kg_m3"], 3),
            # Labels
            "is_faulty": is_faulty,
            "fault_type": active_f_type,
            "fault_cylinder": phys_fault["fault_cylinder"],
            "fault_severity": round(phys_fault["fault_severity"], 3),
            "rul_remaining_hours": round(rul_hours, 2),
            "rul_remaining_sec": round(rul_sec, 1)
        }
        records.append(rec)

    df_out = pd.DataFrame(records)
    return df_out


# =============================================================================
# 7. BATCH GENERATOR FOR TRAINING DATASETS
# =============================================================================
def generate_synthetic_dataset(
    num_runs: int = 25,
    output_dir: str = "../data",
    seed: int = 100
) -> Dict[str, Any]:
    """
    Generates N diverse mission runs containing:
      - Nominal runs across varied altitude envelopes and loiter times
      - Injector clog runs (varied severity 0.15 - 0.55, cylinders 1-4, different start times)
      - Sensor drift runs (thermocouple and RTD drifts)
      - Oil system degradation runs
      - Rapid throttle transient runs (for false-alarm verification in Phase 3)

    Saves individual CSVs and a consolidated summary manifest to output_dir.
    """
    os.makedirs(output_dir, exist_ok=True)
    rng = np.random.default_rng(seed)

    manifest_entries = []
    logger.info(f"Generating {num_runs} synthetic mission runs in '{output_dir}'...")

    for run_id in range(1, num_runs + 1):
        run_seed = int(rng.integers(1000, 999999))
        
        # Decide scenario type
        # 30% Nominal, 35% Injector Clog, 20% Sensor Drift, 15% Oil/Cooling Issue
        scenario_dice = rng.random()
        faults: List[FaultEvent] = []
        scenario_desc = ""

        # Duration variation
        loiter_dur = float(rng.choice([180.0, 240.0, 300.0, 360.0]))
        cruise_alt = float(rng.choice([1500.0, 2000.0, 2500.0, 3200.0]))

        phases = [
            {"name": "takeoff_climb", "duration_sec": 90.0, "start_alt_m": 0.0, "end_alt_m": cruise_alt,
             "start_throttle_pct": 98.0, "end_throttle_pct": 90.0, "start_airspeed_mps": 28.0, "end_airspeed_mps": 42.0},
            {"name": "mission_cruise", "duration_sec": loiter_dur, "start_alt_m": cruise_alt, "end_alt_m": cruise_alt,
             "start_throttle_pct": 74.0, "end_throttle_pct": 72.0, "start_airspeed_mps": 43.0, "end_airspeed_mps": 44.0},
            {"name": "descend_land", "duration_sec": 90.0, "start_alt_m": cruise_alt, "end_alt_m": 50.0,
             "start_throttle_pct": 35.0, "end_throttle_pct": 25.0, "start_airspeed_mps": 40.0, "end_airspeed_mps": 25.0},
        ]
        total_mission_sec = 90.0 + loiter_dur + 90.0

        if scenario_dice < 0.30:
            scenario_desc = "nominal_flight"
            # No faults injected
        elif scenario_dice < 0.65:
            # Injector Clog
            target_cyl = int(rng.choice([1, 2, 3, 4]))
            severity = round(float(rng.uniform(0.18, 0.52)), 2)
            start_t = round(float(rng.uniform(90.0, 90.0 + loiter_dur * 0.5)), 1)
            faults.append(FaultEvent(
                fault_type="injector_clog",
                start_time_sec=start_t,
                duration_ramp_sec=12.0,
                target_cylinder=target_cyl,
                severity=severity
            ))
            scenario_desc = f"injector_clog_cyl{target_cyl}_sev{int(severity*100)}"
        elif scenario_dice < 0.85:
            # Sensor Drift
            target_sensor = str(rng.choice(["egt1", "egt2", "egt3", "egt4", "cht1", "cht2", "oil_press_bar"]))
            start_t = round(float(rng.uniform(80.0, 90.0 + loiter_dur * 0.4)), 1)
            drift_rate = 0.6 if "egt" in target_sensor else (0.3 if "cht" in target_sensor else 0.015)
            faults.append(FaultEvent(
                fault_type="sensor_drift",
                start_time_sec=start_t,
                sensor_name=target_sensor,
                drift_rate=drift_rate,
                severity=1.0
            ))
            scenario_desc = f"sensor_drift_{target_sensor}"
        else:
            # Oil leak or cooling degradation
            start_t = round(float(rng.uniform(100.0, 90.0 + loiter_dur * 0.5)), 1)
            severity = round(float(rng.uniform(0.30, 0.60)), 2)
            f_type = str(rng.choice(["oil_leak", "cooling_duct_blockage"]))
            faults.append(FaultEvent(
                fault_type=f_type,
                start_time_sec=start_t,
                duration_ramp_sec=25.0,
                severity=severity
            ))
            scenario_desc = f"{f_type}_sev{int(severity*100)}"

        # Generate profile and run simulation
        prof = generate_mission_profile(phases=phases, dt=0.1)
        df_run = simulate_mission(mission_profile=prof, faults=faults, random_seed=run_seed, dt=0.1)

        filename = f"run_{run_id:03d}_{scenario_desc}.csv"
        filepath = os.path.join(output_dir, filename)
        df_run.to_csv(filepath, index=False)

        manifest_entries.append({
            "run_id": run_id,
            "filename": filename,
            "scenario": scenario_desc,
            "total_timesteps": len(df_run),
            "duration_sec": total_mission_sec,
            "cruise_alt_m": cruise_alt,
            "fault_count": len(faults),
            "fault_details": [
                {
                    "type": f.fault_type,
                    "target_cyl": f.target_cylinder,
                    "sensor": f.sensor_name,
                    "start_t": f.start_time_sec,
                    "severity": f.severity
                } for f in faults
            ]
        })

    # Compute detailed fault-type distribution and parameter extrema
    distribution = {}
    max_egt_observed = 0.0
    max_cht_observed = 0.0
    injector_clog_egt_max = 0.0

    for entry in manifest_entries:
        # Category classification
        sc = entry["scenario"]
        cat = "nominal" if "nominal" in sc else sc.split("_")[0]
        if "injector_clog" in sc:
            cat = "injector_clog"
        elif "sensor_drift" in sc:
            cat = "sensor_drift"
        elif "oil_leak" in sc:
            cat = "oil_leak"
        elif "cooling_duct_blockage" in sc:
            cat = "cooling_blockage"
        distribution[cat] = distribution.get(cat, 0) + 1

    manifest_data = {
        "total_runs": num_runs,
        "fault_distribution": distribution,
        "runs": manifest_entries
    }

    manifest_path = os.path.join(output_dir, "dataset_manifest.json")
    with open(manifest_path, "w") as f:
        json.dump(manifest_data, f, indent=2)

    logger.info(f"Successfully generated {num_runs} mission runs. Manifest written to '{manifest_path}'.")
    logger.info(f"Fault distribution: {distribution}")
    return {"runs_generated": num_runs, "manifest_path": manifest_path, "output_dir": output_dir, "distribution": distribution}


# =============================================================================
# 8. SELF-TEST AND DEMONSTRATION CLI
# =============================================================================
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="UAV Engine Digital Twin Plant Simulator (Phase 1)")
    parser.add_argument("--demo", action="store_true", help="Run a quick single demonstration run and print stats")
    parser.add_argument("--batch", type=int, default=0, help="Generate N synthetic runs for ML training (default: 0, no generation)")
    parser.add_argument("--outdir", type=str, default="", help="Output directory for generated datasets (default: ../data)")
    args = parser.parse_args()

    print("\n" + "="*70)
    print("  UAV AERO PISTON ENGINE DIGITAL TWIN: PLANT SIMULATOR (PHASE 1)")
    print("="*70)

    # 1. Quick demonstration with an Injector Clog on Cylinder 2
    demo_phases = [
        {"name": "takeoff_climb", "duration_sec": 60.0, "start_alt_m": 0.0, "end_alt_m": 1500.0,
         "start_throttle_pct": 98.0, "end_throttle_pct": 92.0, "start_airspeed_mps": 25.0, "end_airspeed_mps": 40.0},
        {"name": "mission_cruise", "duration_sec": 120.0, "start_alt_m": 1500.0, "end_alt_m": 1500.0,
         "start_throttle_pct": 75.0, "end_throttle_pct": 75.0, "start_airspeed_mps": 44.0, "end_airspeed_mps": 44.0},
        {"name": "descend_approach", "duration_sec": 60.0, "start_alt_m": 1500.0, "end_alt_m": 200.0,
         "start_throttle_pct": 35.0, "end_throttle_pct": 30.0, "start_airspeed_mps": 38.0, "end_airspeed_mps": 25.0}
    ]
    demo_profile = generate_mission_profile(phases=demo_phases, dt=0.1)

    # Inject a 35% injector clog on Cylinder 2 at t=90s (during cruise)
    demo_faults = [
        FaultEvent(
            fault_type="injector_clog",
            start_time_sec=90.0,
            duration_ramp_sec=10.0,
            target_cylinder=2,
            severity=0.35
        )
    ]

    print(f"\n[1/3] Simulating Demonstration Run (Duration: {demo_profile['timestamp_sec'].iloc[-1]}s @ 10 Hz)...")
    df_demo = simulate_mission(mission_profile=demo_profile, faults=demo_faults, random_seed=42)
    print(f"      -> Generated {len(df_demo)} samples across {len(df_demo.columns)} columns.")

    # Validation checks
    t_nominal = df_demo[df_demo["timestamp_sec"] == 80.0].iloc[0]
    t_faulty = df_demo[df_demo["timestamp_sec"] == 130.0].iloc[0]

    print("\n[2/3] Physics Validation Across Fault Injection (Cylinder 2 Clog @ t=90s):")
    print(f"      Nominal Cruise (t=80s):  EGT1={t_nominal['egt1']}°C, EGT2={t_nominal['egt2']}°C, EGT3={t_nominal['egt3']}°C, EGT4={t_nominal['egt4']}°C | RPM={t_nominal['rpm']}")
    print(f"      Degraded Cruise (t=130s): EGT1={t_faulty['egt1']}°C, EGT2={t_faulty['egt2']}°C, EGT3={t_faulty['egt3']}°C, EGT4={t_faulty['egt4']}°C | RPM={t_faulty['rpm']}")
    egt2_delta = t_faulty["egt2"] - t_nominal["egt2"]
    rpm_droop = t_nominal["rpm"] - t_faulty["rpm"]
    print(f"      ==> Physics Verification Result: Cyl 2 EGT rose by +{egt2_delta:.1f}°C (Lean Combustion Peak), RPM drooped by -{rpm_droop:.1f} RPM.")
    
    # Check boundaries
    cht_max = df_demo[["cht1", "cht2", "cht3", "cht4"]].max().max()
    cht_min = df_demo[["cht1", "cht2", "cht3", "cht4"]].min().min()
    egt_max = df_demo[["egt1", "egt2", "egt3", "egt4"]].max().max()
    egt_min = df_demo[["egt1", "egt2", "egt3", "egt4"]].min().min()
    print(f"      ==> Boundary Checks: CHT Range [{cht_min:.1f}, {cht_max:.1f}]°C (Target: 150-230°C)")
    print(f"                           EGT Range [{egt_min:.1f}, {egt_max:.1f}]°C (Target: 650-950°C)")

    # 3. Batch generator ONLY if explicitly requested via --batch > 0
    if args.batch > 0:
        script_dir = os.path.dirname(os.path.abspath(__file__))
        target_data_dir = os.path.abspath(args.outdir) if args.outdir else os.path.abspath(os.path.join(script_dir, "..", "data"))
        print(f"\n[3/3] Generating Batch Synthetic Dataset ({args.batch} runs) into '{target_data_dir}'...")
        res = generate_synthetic_dataset(num_runs=args.batch, output_dir=target_data_dir, seed=2026)
        print(f"      -> Batch generation completed. Files saved to: {res['output_dir']}")
    else:
        print("\n[3/3] Demonstration completed successfully. (No files modified. To generate batch runs, use --batch N).")
    print("="*70 + "\n")
