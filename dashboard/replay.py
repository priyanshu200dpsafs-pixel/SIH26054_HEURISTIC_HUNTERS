#!/usr/bin/env python3
"""
===============================================================================
AERO PISTON ENGINE DIGITAL TWIN: MISSION REPLAY ENGINE (PHASE 4)
===============================================================================
Enables historical flight replay of existing dataset sorties.
Feeds historical flight data row-by-row strictly through the authentic
`DigitalTwinRuntime` to produce identical, reproducible DigitalTwinStates.

STRICT DATASET INTEGRITY NOTICE:
  - 100% READ-ONLY access to `data/*.csv` and `data/dataset_manifest.json`.
  - NEVER writes, alters, creates, or overwrites any files in `data/`.
===============================================================================
"""

import os
import json
from typing import Dict, Any, List, Optional
import pandas as pd

from digital_twin.runtime import DigitalTwinRuntime
from digital_twin.state import DigitalTwinState


class MissionReplayController:
    """
    Manages loading and playback of historical mission sorties from the dataset.
    Feeds row data directly into DigitalTwinRuntime for deterministic replay.
    """

    def __init__(self, data_dir: Optional[str] = None):
        if data_dir is None:
            # Default to <project_root>/data
            self.data_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
        else:
            self.data_dir = data_dir

        self.manifest: List[Dict[str, Any]] = []
        self._load_manifest()

        # Playback session state
        self.selected_filename: Optional[str] = None
        self.selected_metadata: Optional[Dict[str, Any]] = None
        self.df_data: Optional[pd.DataFrame] = None
        self.runtime: Optional[DigitalTwinRuntime] = None
        self.current_idx: int = 0
        self.is_playing: bool = False
        self.is_paused: bool = False
        self.is_finished: bool = False
        self.playback_speed: float = 1.0  # 0.5x, 1x, 2x, 5x, 10x
        self.latest_state: Optional[DigitalTwinState] = None

    def _load_manifest(self):
        """Loads dataset_manifest.json in strictly read-only mode."""
        manifest_path = os.path.join(self.data_dir, "dataset_manifest.json")
        if os.path.exists(manifest_path):
            with open(manifest_path, "r", encoding="utf-8") as f:
                content = json.load(f)
                if isinstance(content, dict):
                    self.manifest = content.get("runs", [])
                elif isinstance(content, list):
                    self.manifest = content
                else:
                    self.manifest = []
        else:
            self.manifest = []

    def get_available_sorties(self) -> List[Dict[str, Any]]:
        """Returns sorted list of available historical sorties."""
        if self.manifest:
            def sort_key(x):
                r_id = x.get("run_id", 0)
                try:
                    return int(r_id)
                except (ValueError, TypeError):
                    return str(r_id)
            return sorted(self.manifest, key=sort_key)
        # Fallback to scanning CSV files in data/
        files = []
        if os.path.exists(self.data_dir):
            for f in sorted(os.listdir(self.data_dir)):
                if f.endswith(".csv") and f.startswith("run_"):
                    files.append({
                        "filename": f,
                        "run_id": f.replace("run_", "").replace(".csv", ""),
                        "category": "flight_sortie"
                    })
        return files

    def load_sortie(self, filename: str) -> bool:
        """
        Loads a sortie CSV file in strictly read-only mode and initializes
        the DigitalTwinRuntime.
        """
        fpath = os.path.join(self.data_dir, filename)
        if not os.path.exists(fpath):
            return False

        # Read strictly read-only
        self.df_data = pd.read_csv(fpath)
        self.selected_filename = filename

        # Find metadata
        self.selected_metadata = next((m for m in self.manifest if m.get("filename") == filename), None)

        # Initialize fresh DigitalTwinRuntime
        self.runtime = DigitalTwinRuntime(ewma_alpha=0.05)
        self.current_idx = 0
        self.is_playing = False
        self.is_paused = False
        self.is_finished = False
        self.latest_state = None
        return True

    def step(self) -> Optional[DigitalTwinState]:
        """
        Processes the next row through DigitalTwinRuntime.
        """
        if self.df_data is None or self.runtime is None:
            return None

        if self.current_idx >= len(self.df_data):
            self.is_finished = True
            self.is_playing = False
            return self.latest_state

        row = self.df_data.iloc[self.current_idx]
        telem = row.to_dict()

        # Compute dt if consecutive rows exist
        dt = 0.1
        if self.current_idx > 0:
            prev_t = float(self.df_data.iloc[self.current_idx - 1]["timestamp_sec"])
            cur_t = float(row["timestamp_sec"])
            dt = max(0.01, cur_t - prev_t)

        dt_state = self.runtime.process(telemetry=telem, dt=dt)
        self.latest_state = dt_state
        self.current_idx += 1

        if self.current_idx >= len(self.df_data):
            self.is_finished = True
            self.is_playing = False

        return dt_state

    def play(self):
        """Starts or resumes playback."""
        if self.is_finished:
            self.reset()
        self.is_playing = True
        self.is_paused = False

    def pause(self):
        """Pauses playback."""
        self.is_playing = False
        self.is_paused = True

    def stop(self):
        """Stops playback and resets index to 0."""
        self.reset()

    def reset(self):
        """Resets playback to the beginning of the loaded sortie."""
        self.current_idx = 0
        self.is_playing = False
        self.is_paused = False
        self.is_finished = False
        if self.runtime:
            self.runtime.reset()
        self.latest_state = None

    def seek(self, target_idx: int):
        """
        Fast-forwards replay state to target index to ensure deterministic state.
        """
        if self.df_data is None:
            return
        target_idx = max(0, min(target_idx, len(self.df_data) - 1))
        self.reset()
        while self.current_idx <= target_idx:
            self.step()

    @property
    def progress_fraction(self) -> float:
        """Returns progress fraction [0.0, 1.0]."""
        if self.df_data is None or len(self.df_data) == 0:
            return 0.0
        return min(1.0, float(self.current_idx) / float(len(self.df_data)))

    @property
    def total_rows(self) -> int:
        return len(self.df_data) if self.df_data is not None else 0

    @property
    def current_time_sec(self) -> float:
        if self.latest_state:
            return self.latest_state.timestamp
        return 0.0
