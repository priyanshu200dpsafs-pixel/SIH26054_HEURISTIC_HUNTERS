#!/usr/bin/env python3
"""
===============================================================================
AERO PISTON ENGINE DIGITAL TWIN: CORE PHYSICS PRIMITIVES (SINGLE SOURCE OF TRUTH)
===============================================================================
Provides shared physical constants, specifications, standard atmosphere models,
and nominal thermodynamic relationships for the Rotax 912-class UAV engine.

Architectural Rule:
  - Both the simulator (plant_model/engine_plant.py) and the analytical
    observer (ml_layer/physics_estimator.py) import their nominal physics from
    this module.
  - The analytical observer must remain independent: it consumes ONLY flight
    operational inputs (throttle, altitude, airspeed) and evaluates nominal
    healthy-engine physics without knowledge of injected physical faults.
===============================================================================
"""

import math
from dataclasses import dataclass
from typing import Tuple, Dict
import numpy as np


# =============================================================================
# 1. ENGINE SPECIFICATIONS & PHYSICAL CONSTANTS
# =============================================================================
@dataclass
class EngineSpecs:
    """
    Physical and operational specifications for a Rotax 912 ULS-class UAV engine.
    Calibrated against standard aero piston technical documentation.
    """
    engine_name: str = "Rotax 912-Class Aero Boxer 4-Cylinder"
    num_cylinders: int = 4
    displacement_cc: float = 1211.0          # 1.211 Liters
    max_power_hp: float = 100.0              # 73.5 kW at sea-level WOT
    idle_rpm: float = 1600.0                 # Minimum ground/flight idle
    max_rpm: float = 5800.0                  # Maximum takeoff continuous RPM
    cruise_rpm: float = 5000.0               # Standard 75% throttle cruise RPM

    # Nominal Thermal Boundaries (Rotax operating limits)
    cht_min_c: float = 150.0                 # Normal minimum operating CHT
    cht_max_c: float = 230.0                 # Redline cylinder head temperature
    egt_min_c: float = 650.0                 # Normal low-throttle EGT
    egt_max_c: float = 950.0                 # Upper safety redline EGT
    
    oil_press_min_bar: float = 1.8           # Low idle limit
    oil_press_max_bar: float = 5.0           # Relief valve regulated pressure
    oil_temp_min_c: float = 70.0             # Normal minimum warm oil temp
    oil_temp_max_c: float = 115.0            # High continuous limit

    # Time Constants (Thermal & Mechanical Inertia)
    # Reflects rotational inertia and finite heat capacities (m * Cp)
    tau_rpm_sec: float = 0.55                # Crankshaft & propeller inertia
    tau_egt_sec: float = 1.8                 # Gas flow velocity & thermocouple lag
    tau_cht_sec: float = 12.0                # Large thermal inertia of aluminum cylinder head
    tau_oil_temp_sec: float = 35.0           # Thermal mass of 3.5L circulating oil sump
    tau_oil_press_sec: float = 0.4           # Hydraulic propagation time

    # Cylinder-to-Cylinder Geometry Biases (°C)
    # Rear cylinders (3 & 4) receive pre-warmed cowl ram air in a boxer engine layout
    cyl_cht_bias: Tuple[float, ...] = (-2.5, -1.0, +2.5, +3.5)
    cyl_egt_bias: Tuple[float, ...] = (-5.0, +3.0, +6.0, -4.0)

    # Sensor Noise Standard Deviations (Gaussian zero-mean)
    noise_std: Dict[str, float] = None

    def __post_init__(self):
        if self.noise_std is None:
            self.noise_std = {
                "rpm": 5.5,             # Hall effect sensor pulse jitter (~5-6 RPM)
                "egt": 1.4,             # Type-K thermocouple noise (~1.4°C)
                "cht": 0.6,             # PT100 RTD precision sensor (~0.6°C)
                "oil_press": 0.025,     # Piezoresistive pressure transducer (~0.025 bar)
                "oil_temp": 0.45,       # Fluid thermistor (~0.45°C)
                "fuel_flow": 0.03       # Turbine flowmeter pulse quantization (~0.03 g/s)
            }


# =============================================================================
# 2. ATMOSPHERIC MODEL (ISA: International Standard Atmosphere)
# =============================================================================
def isa_atmosphere(altitude_m: float) -> Tuple[float, float, float, float]:
    """
    Computes ambient temperature, pressure, density, and relative density
    at a given geopotential altitude using standard ISA tropospheric equations.

    Returns:
      (T_amb_k, P_amb_pa, rho_amb_kg_m3, sigma)
      where sigma = rho / rho_0 (sea-level density ratio).
    """
    T0 = 288.15          # Sea-level standard temp in Kelvin (15°C)
    P0 = 101325.0        # Sea-level standard pressure in Pascals
    rho0 = 1.225         # Sea-level air density in kg/m^3
    lapse_rate = 0.0065   # Troposphere lapse rate: 6.5 K per 1000m
    g0 = 9.80665         # Gravitational acceleration m/s^2
    R_air = 287.05       # Specific gas constant for dry air J/(kg*K)

    alt = max(0.0, min(float(altitude_m), 10000.0))

    T_amb_k = T0 - lapse_rate * alt
    exponent = g0 / (R_air * lapse_rate)  # ~5.25588
    P_amb_pa = P0 * math.pow(T_amb_k / T0, exponent)
    rho_amb = P_amb_pa / (R_air * T_amb_k)
    sigma = rho_amb / rho0

    return T_amb_k, P_amb_pa, rho_amb, sigma


# =============================================================================
# 3. CORE NOMINAL THERMODYNAMIC & KINEMATIC RELATIONSHIPS
# =============================================================================
def compute_target_rpm(
    throttle_norm: float,
    sigma: float,
    specs: EngineSpecs = None
) -> float:
    """
    Computes nominal target engine shaft RPM for a healthy engine given
    normalized throttle [0.0 - 1.0] and atmospheric density ratio sigma.
    """
    if specs is None:
        specs = EngineSpecs()
    th_norm = max(0.0, min(1.0, float(throttle_norm)))
    th_curve = 0.20 * th_norm + 0.80 * math.pow(th_norm, 0.85)
    rpm_target = specs.idle_rpm + (
        specs.max_rpm - specs.idle_rpm
    ) * th_curve * math.pow(sigma, 0.70)
    return float(max(specs.idle_rpm * 0.90, min(specs.max_rpm, rpm_target)))


def compute_target_fuel_flow(
    throttle_norm: float,
    sigma: float
) -> float:
    """
    Computes nominal total fuel mass flow rate (g/s).
    Baseline: ~0.85 g/s at idle (~3.8 L/hr) to ~5.60 g/s at sea-level WOT (~25.5 L/hr).
    """
    th_norm = max(0.0, min(1.0, float(throttle_norm)))
    ff_idle = 0.85
    ff_max = 5.60
    return float(ff_idle + (ff_max - ff_idle) * math.pow(th_norm, 1.1) * sigma)


def compute_nominal_egt_base(
    throttle_norm: float,
    sigma: float
) -> float:
    """
    Computes baseline nominal Exhaust Gas Temperature (°C) before cylinder biases.
    Rich-of-peak baseline: ~675°C at low power to ~880-900°C at full throttle.
    """
    th_norm = max(0.0, min(1.0, float(throttle_norm)))
    return float(675.0 + 195.0 * math.pow(th_norm, 0.85) + 30.0 * (1.0 - sigma))


def compute_nominal_egt_targets(
    throttle_norm: float,
    sigma: float,
    specs: EngineSpecs = None
) -> np.ndarray:
    """
    Computes nominal target EGT array (°C) for all 4 cylinders in a healthy engine.
    """
    if specs is None:
        specs = EngineSpecs()
    egt_base = compute_nominal_egt_base(throttle_norm, sigma)
    targets = [min(942.0, egt_base + bias) for bias in specs.cyl_egt_bias]
    return np.array(targets, dtype=float)


def compute_nominal_cht_base(
    throttle_norm: float,
    sigma: float,
    effective_ias: float
) -> float:
    """
    Computes baseline Cylinder Head Temperature (°C) balancing combustion heat flux
    with convective ram-air cooling and density altitude penalty.
    """
    th_norm = max(0.0, min(1.0, float(throttle_norm)))
    ias = max(0.0, float(effective_ias))
    cht_baseline_c = 154.0
    delta_cht_comb = 62.0 * math.pow(th_norm, 0.85)
    mass_airflow_cooling = sigma * ias
    ram_air_cooling = 1.0 / (1.0 + 0.0075 * mass_airflow_cooling)
    altitude_cooling_penalty = 1.0 + 0.12 * (1.0 - sigma)
    return float(cht_baseline_c + (delta_cht_comb * altitude_cooling_penalty * ram_air_cooling))


def compute_nominal_cht_targets(
    throttle_norm: float,
    sigma: float,
    effective_ias: float,
    specs: EngineSpecs = None
) -> np.ndarray:
    """
    Computes nominal target CHT array (°C) for all 4 cylinders in a healthy engine.
    """
    if specs is None:
        specs = EngineSpecs()
    cht_base = compute_nominal_cht_base(throttle_norm, sigma, effective_ias)
    targets = [cht_base + bias for bias in specs.cyl_cht_bias]
    return np.array(targets, dtype=float)


def compute_target_oil_temp(
    rpm: float,
    effective_ias: float,
    t_amb_c: float,
    current_oil_temp_c: float,
    specs: EngineSpecs = None
) -> float:
    """
    Computes target oil temperature (°C) with Rotax thermostatic cooler bypass logic.
    """
    if specs is None:
        specs = EngineSpecs()
    ias = max(0.0, float(effective_ias))
    oil_cooler_flow = ias if current_oil_temp_c > 78.0 else 0.0
    oil_temp_target = max(74.0, t_amb_c + 60.0 + 30.0 * (rpm / specs.max_rpm))
    oil_temp_target /= (1.0 + 0.005 * oil_cooler_flow)
    return float(oil_temp_target)


def compute_target_oil_press(
    rpm: float,
    oil_temp_c: float,
    specs: EngineSpecs = None
) -> float:
    """
    Computes nominal oil pressure target (bar) from camshaft mechanical pump
    and thermal oil viscosity reduction.
    """
    if specs is None:
        specs = EngineSpecs()
    p_oil_nominal = 1.8 + (specs.oil_press_max_bar - 1.8) * (
        1.0 - math.exp(-max(0.0, rpm - 1000.0) / 1600.0)
    )
    viscosity_loss = 0.016 * max(0.0, oil_temp_c - 80.0)
    return float(max(0.4, p_oil_nominal - viscosity_loss))
