"""
Plant Model Package: Aero Engine Physics Simulator & ISA Atmosphere.
"""
from .physics_core import (
    EngineSpecs,
    isa_atmosphere,
    compute_target_rpm,
    compute_target_fuel_flow,
    compute_nominal_egt_base,
    compute_nominal_egt_targets,
    compute_nominal_cht_base,
    compute_nominal_cht_targets,
    compute_target_oil_temp,
    compute_target_oil_press,
)

__all__ = [
    "EngineSpecs",
    "isa_atmosphere",
    "compute_target_rpm",
    "compute_target_fuel_flow",
    "compute_nominal_egt_base",
    "compute_nominal_egt_targets",
    "compute_nominal_cht_base",
    "compute_nominal_cht_targets",
    "compute_target_oil_temp",
    "compute_target_oil_press",
]
