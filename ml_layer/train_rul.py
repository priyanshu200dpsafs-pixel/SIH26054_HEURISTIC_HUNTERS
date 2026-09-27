#!/usr/bin/env python3
"""
Training script for the RUL Quantile Estimator using the 150-run synthetic dataset.
Run: python3 ml_layer/train_rul.py
"""

import os
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, ".."))
DATA_DIR = os.path.join(PROJECT_ROOT, "data")
sys.path.insert(0, SCRIPT_DIR)

from rul_estimator import RULEstimator

if __name__ == "__main__":
    print("\n" + "="*75)
    print("TRAINING QUANTILE RUL ESTIMATOR ON 150-RUN SYNTHETIC DATASET")
    print("="*75)

    estimator = RULEstimator()
    res = estimator.train_on_dataset(data_directory=DATA_DIR, max_runs_to_use=150, subsample_step=15)
    print(f"\nTraining Complete: {res['train_samples']} samples processed.")
    print(f"Model successfully saved to: {res['model_path']}")
    print("="*75 + "\n")
