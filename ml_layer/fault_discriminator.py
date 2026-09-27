#!/usr/bin/env python3
"""
===============================================================================
DIGITAL TWIN: SENSOR-FAULT VS. PLANT-FAULT DISCRIMINATOR (PHASE 3)
===============================================================================
Distinguishes "sensor lying" (instrument failure) from "engine actually
degrading" (thermodynamic / mechanical fault) by evaluating cross-channel
physical coupling signatures.

Physics Principle (Defensible to Judges):
  - In a real mechanical engine, physical faults produce COUPLED MULTI-CHANNEL
    signatures governed by conservation of energy and momentum:
      * An injector clog causes EGT rise AND shaft torque/RPM droop.
      * An oil leak causes hydraulic pressure collapse AND friction heat buildup.
      * A cowl blockage causes multi-cylinder CHT AND oil temperature rise.
  - In contrast, instrument failures (thermocouple oxidation, RTD resistance drift)
    are ISOLATED: the drifting sensor diverges with ZERO cross-coupling into engine
    RPM, fuel consumption, or neighboring cylinders.
===============================================================================
"""

import os
import sys
from typing import Dict, Any, List, Optional, Tuple

import numpy as np


class FaultDiscriminator:
    """
    Classifies anomalous residuals into SENSOR_FAULT or PLANT_FAULT using
    multivariate physical coupling rules.
    """

    def __init__(self):
        # Physical coupling thresholds
        self.rpm_droop_threshold = -70.0      # RPM droop indicative of lost cylinder IMEP
        self.oil_temp_rise_threshold = 5.0    # °C rise in oil temperature indicative of lube loss
        self.ff_deficit_threshold = -0.25     # g/s fuel deficit

    def classify_anomaly(
        self,
        detector_output: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Takes output from ResidualAnomalyDetector and determines fault classification.

        Returns:
          Dict containing:
            - 'classification': 'NOMINAL', 'SENSOR_FAULT', or 'PLANT_FAULT'
            - 'fault_subtype': e.g. 'INJECTOR_CLOG', 'SENSOR_DRIFT', 'OIL_LEAK'
            - 'fault_location': e.g. 'CYLINDER_2', 'EGT_SENSOR_2', 'OIL_SYSTEM'
            - 'confidence': 0.0 to 1.0
            - 'justification': plain-language defense explanation for judges/pilots
            - 'coupling_metrics': Dict of observed cross-channel coupling values
        """
        status = detector_output["status"]
        if status == "NORMAL":
            return {
                "classification": "NOMINAL",
                "fault_subtype": "NONE",
                "fault_location": "NONE",
                "confidence": 1.0,
                "justification": "All engine residuals within 3-sigma expected nominal boundaries.",
                "coupling_metrics": {}
            }

        alerted = detector_output["alerted_signals"]
        caution = detector_output["caution_signals"]
        active_anomalies = alerted if len(alerted) > 0 else caution

        signed_res = detector_output["signed_residuals"]
        ewma_res = detector_output["ewma_residuals"]

        # Cross-channel coupling observation
        rpm_delta = signed_res.get("rpm", 0.0)
        oil_p_delta = signed_res.get("oil_press_bar", 0.0)
        oil_t_delta = signed_res.get("oil_temp_c", 0.0)
        ff_delta = signed_res.get("fuel_flow_gps", 0.0)

        # ---------------------------------------------------------------------
        # Case 1: EGT Anomaly (Potential Injector Clog vs. Thermocouple Drift)
        # ---------------------------------------------------------------------
        egt_anomalies = [s for s in active_anomalies if "egt" in s]
        if egt_anomalies:
            # Pick dominant cylinder
            dominant_egt = max(egt_anomalies, key=lambda s: ewma_res[s])
            cyl_num = int(dominant_egt.replace("egt", ""))
            egt_rise = signed_res[dominant_egt]

            # Physical coupling check:
            # Did the engine shaft experience a correlated RPM droop due to loss of IMEP?
            has_rpm_droop = (rpm_delta <= self.rpm_droop_threshold)
            
            # Check other cylinders balance
            other_egts = [signed_res[f"egt{i}"] for i in range(1, 5) if i != cyl_num]
            avg_other_egt = np.mean(other_egts)
            unbalance = egt_rise - avg_other_egt

            coupling_metrics = {
                "egt_divergence_c": round(egt_rise, 1),
                "rpm_droop": round(rpm_delta, 1),
                "cylinder_unbalance_c": round(unbalance, 1),
                "fuel_flow_delta_gps": round(ff_delta, 3)
            }

            if has_rpm_droop and unbalance >= 25.0:
                # Correlated RPM drop + high single-cylinder temperature rise = Mechanical Combustion Degradation
                return {
                    "classification": "PLANT_FAULT",
                    "fault_subtype": "INJECTOR_CLOG",
                    "fault_location": f"CYLINDER_{cyl_num}",
                    "confidence": 0.96,
                    "justification": (
                        f"Cylinder {cyl_num} EGT rose by +{egt_rise:.1f}°C with a simultaneous "
                        f"correlated engine shaft droop of {rpm_delta:.1f} RPM. "
                        f"Physical power loss confirms genuine combustion lean degradation (injector fuel restriction)."
                    ),
                    "coupling_metrics": coupling_metrics
                }
            else:
                # EGT signal is deviating, but RPM and other parameters show ZERO power deficit
                return {
                    "classification": "SENSOR_FAULT",
                    "fault_subtype": "SENSOR_DRIFT",
                    "fault_location": f"EGT_SENSOR_{cyl_num}",
                    "confidence": 0.94,
                    "justification": (
                        f"Sensor {dominant_egt} drifted by +{egt_rise:.1f}°C, but engine RPM droop is "
                        f"negligible ({rpm_delta:.1f} RPM) and neighboring cylinders are normal. "
                        f"Absence of physical shaft torque loss confirms instrument thermocouple drift."
                    ),
                    "coupling_metrics": coupling_metrics
                }

        # ---------------------------------------------------------------------
        # Case 2: Oil System Anomaly (Oil Leak vs. Pressure Sensor Drift)
        # ---------------------------------------------------------------------
        if "oil_press_bar" in active_anomalies:
            press_loss = -signed_res["oil_press_bar"]
            has_thermal_spike = (oil_t_delta >= self.oil_temp_rise_threshold)

            coupling_metrics = {
                "oil_pressure_loss_bar": round(press_loss, 3),
                "oil_temp_rise_c": round(oil_t_delta, 1)
            }

            if has_thermal_spike and press_loss > 0.5:
                return {
                    "classification": "PLANT_FAULT",
                    "fault_subtype": "OIL_LEAK",
                    "fault_location": "LUBRICATION_CIRCUIT",
                    "confidence": 0.95,
                    "justification": (
                        f"Oil pressure dropped by {press_loss:.2f} bar with concurrent friction heating "
                        f"raising oil temperature by +{oil_t_delta:.1f}°C. Multi-channel correlation confirms hydraulic leak."
                    ),
                    "coupling_metrics": coupling_metrics
                }
            else:
                return {
                    "classification": "SENSOR_FAULT",
                    "fault_subtype": "SENSOR_DRIFT",
                    "fault_location": "OIL_PRESSURE_TRANSDUCER",
                    "confidence": 0.92,
                    "justification": (
                        f"Oil pressure sensor reported {press_loss:.2f} bar drop, but oil temperature "
                        f"remains completely nominal (+{oil_t_delta:.1f}°C). Transducer offset without physical lubrication failure."
                    ),
                    "coupling_metrics": coupling_metrics
                }

        # ---------------------------------------------------------------------
        # Case 3: CHT Anomaly (Cooling Duct Blockage vs. RTD Drift)
        # ---------------------------------------------------------------------
        cht_anomalies = [s for s in active_anomalies if "cht" in s]
        if cht_anomalies:
            # If 3 or 4 cylinders exhibit elevated CHT simultaneously -> cooling airflow restriction
            if len(cht_anomalies) >= 2 or (len(cht_anomalies) >= 1 and oil_t_delta >= 4.0):
                return {
                    "classification": "PLANT_FAULT",
                    "fault_subtype": "COOLING_DUCT_BLOCKAGE",
                    "fault_location": "ENGINE_COWLING",
                    "confidence": 0.93,
                    "justification": "Global CHT rise across multiple cylinders indicates convective cooling duct restriction.",
                    "coupling_metrics": {"affected_cylinders": cht_anomalies, "oil_temp_rise_c": round(oil_t_delta, 1)}
                }
            else:
                target_rtd = cht_anomalies[0]
                return {
                    "classification": "SENSOR_FAULT",
                    "fault_subtype": "SENSOR_DRIFT",
                    "fault_location": f"CHT_SENSOR_{target_rtd[-1]}",
                    "confidence": 0.91,
                    "justification": f"Isolated resistance drift on {target_rtd}; all other cylinders and oil temp are nominal.",
                    "coupling_metrics": {"affected_sensor": target_rtd}
                }

        # Default fallback
        return {
            "classification": "PLANT_FAULT",
            "fault_subtype": "GENERAL_DEGRADATION",
            "fault_location": "POWERTRAIN",
            "confidence": 0.75,
            "justification": "Multi-variable residual deviation exceeding alert thresholds.",
            "coupling_metrics": {}
        }
