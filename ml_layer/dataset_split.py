#!/usr/bin/env python3
"""
===============================================================================
SCIENTIFIC DATASET SPLIT: MISSION/SORTIE GROUPED STRATIFIED PARTITION
===============================================================================
Enforces the fundamental PHM validation rule:
The evaluation unit is a complete MISSION/SORTIE, not an individual timestep.

Guarantees:
  1. Stratified allocation across all 5 fault categories:
     - nominal
     - injector_clog
     - sensor_drift
     - oil_leak
     - cooling_duct_blockage
  2. Strict disjoint separation:
     Train: 70% (105 sorties)
     Validation: 15% (22 sorties)
     Test: 15% (23 sorties)
  3. Absolute zero sortie overlap across splits:
     Train ∩ Val = ∅, Train ∩ Test = ∅, Val ∩ Test = ∅
  4. Fully deterministic via seed=42.
===============================================================================
"""

import os
import json
import random
from typing import Dict, Any, List, Set, Tuple


def get_grouped_splits(
    data_dir: str,
    manifest_path: str = None,
    seed: int = 42,
    train_ratio: float = 0.70,
    val_ratio: float = 0.15
) -> Dict[str, Any]:
    """
    Constructs a deterministic, stratified group-based partition of the 150-run dataset.

    Returns:
      Dict with keys:
        - 'train': List of run metadata dicts (105 runs)
        - 'val': List of run metadata dicts (22 runs)
        - 'test': List of run metadata dicts (23 runs)
        - 'train_ids': Set of run IDs
        - 'val_ids': Set of run IDs
        - 'test_ids': Set of run IDs
        - 'summary': Summary table by fault category
    """
    if manifest_path is None:
        manifest_path = os.path.join(data_dir, "dataset_manifest.json")

    if not os.path.exists(manifest_path):
        raise FileNotFoundError(f"Manifest not found: {manifest_path}")

    with open(manifest_path, "r", encoding="utf-8") as f:
        manifest = json.load(f)

    runs = manifest["runs"]

    # Categorize runs by fault scenario
    by_category: Dict[str, List[Dict[str, Any]]] = {}
    for r in runs:
        fdetails = r.get("fault_details", [])
        if not fdetails:
            category = "nominal"
        else:
            raw_type = fdetails[0].get("type", "nominal")
            if raw_type in ("cooling_blockage", "cooling_duct_blockage"):
                category = "cooling_duct_blockage"
            else:
                category = raw_type

        # Attach normalized category
        r_copy = dict(r)
        r_copy["category"] = category
        by_category.setdefault(category, []).append(r_copy)

    rng = random.Random(seed)
    train_runs: List[Dict[str, Any]] = []
    val_runs: List[Dict[str, Any]] = []
    test_runs: List[Dict[str, Any]] = []

    category_breakdown: Dict[str, Dict[str, int]] = {}

    for cat in sorted(by_category.keys()):
        items = list(by_category[cat])
        rng.shuffle(items)
        n = len(items)

        n_train = int(round(n * train_ratio))
        n_val = int(round(n * val_ratio))
        n_test = n - n_train - n_val

        # Ensure at least 1 test sample if category is non-empty
        if n_test <= 0 and n >= 3:
            n_train -= 1
            n_test += 1

        tr = items[:n_train]
        va = items[n_train:n_train + n_val]
        te = items[n_train + n_val:]

        train_runs.extend(tr)
        val_runs.extend(va)
        test_runs.extend(te)

        category_breakdown[cat] = {
            "total": n,
            "train": len(tr),
            "val": len(va),
            "test": len(te)
        }

    train_ids = set(r["run_id"] for r in train_runs)
    val_ids = set(r["run_id"] for r in val_runs)
    test_ids = set(r["run_id"] for r in test_runs)

    # Formal Leakage Verification Check
    overlap_tv = train_ids & val_ids
    overlap_tt = train_ids & test_ids
    overlap_vt = val_ids & test_ids

    assert len(overlap_tv) == 0, f"Train-Val Sortie Leakage detected: {overlap_tv}"
    assert len(overlap_tt) == 0, f"Train-Test Sortie Leakage detected: {overlap_tt}"
    assert len(overlap_vt) == 0, f"Val-Test Sortie Leakage detected: {overlap_vt}"
    assert len(train_ids) + len(val_ids) + len(test_ids) == len(runs), "Sortie count mismatch!"

    return {
        "seed": seed,
        "total_runs": len(runs),
        "train": train_runs,
        "val": val_runs,
        "test": test_runs,
        "train_ids": sorted(list(train_ids)),
        "val_ids": sorted(list(val_ids)),
        "test_ids": sorted(list(test_ids)),
        "summary": category_breakdown
    }


if __name__ == "__main__":
    script_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.abspath(os.path.join(script_dir, ".."))
    data_dir = os.path.join(project_root, "data")

    splits = get_grouped_splits(data_dir=data_dir, seed=42)
    print("\n" + "="*75)
    print("MISSION-GROUPED STRATIFIED DATASET SPLIT (SEED=42)")
    print("="*75)
    print(f"Total Sorties: {splits['total_runs']}")
    print(f"  - Train:      {len(splits['train'])} sorties ({len(splits['train'])/splits['total_runs']*100:.1f}%)")
    print(f"  - Validation: {len(splits['val'])} sorties ({len(splits['val'])/splits['total_runs']*100:.1f}%)")
    print(f"  - Test:       {len(splits['test'])} sorties ({len(splits['test'])/splits['total_runs']*100:.1f}%)")
    print("\nCategory Breakdown:")
    for cat, counts in splits["summary"].items():
        print(f"  {cat:26s} | Total: {counts['total']:2d} | Train: {counts['train']:2d} | Val: {counts['val']:2d} | Test: {counts['test']:2d}")
    print("="*75 + "\n")
