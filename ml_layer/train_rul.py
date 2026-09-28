#!/usr/bin/env python3
"""
Training script for the RUL Quantile Estimator using strictly TRAIN sorties
from the mission-grouped stratified dataset partition.
Run: python ml_layer/train_rul.py
"""

import os
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, ".."))
DATA_DIR = os.path.join(PROJECT_ROOT, "data")
sys.path.insert(0, SCRIPT_DIR)

from rul_estimator import RULEstimator
from dataset_split import get_grouped_splits

if __name__ == "__main__":
    print("\n" + "="*75)
    print("TRAINING QUANTILE RUL ESTIMATOR (HELD-IN TRAIN SORTIES ONLY)")
    print("="*75)

    splits = get_grouped_splits(data_dir=DATA_DIR, seed=42)
    train_files = [r["filename"] for r in splits["train"]]
    print(f"Total dataset: {splits['total_runs']} sorties.")
    print(f"Ingesting:     {len(train_files)} TRAIN sorties (Held-out Val: {len(splits['val'])}, Held-out Test: {len(splits['test'])})")

    estimator = RULEstimator()
    res = estimator.train_on_dataset(
        data_directory=DATA_DIR,
        run_files=train_files,
        subsample_step=10,
        random_seed=42
    )
    print(f"\nTraining Complete: {res['train_samples']} samples processed from {res['train_sorties']} train sorties.")
    print(f"Model successfully saved to: {res['model_path']}")
    print("="*75 + "\n")
