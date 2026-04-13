"""
Config Loader — Load SceneConfig JSON and asset library JSON.

Pure Python — no Isaac Sim dependencies.
"""

import sys
import json


def load_config(config_path="configs/current_scene.json", library_path="assets/library.json", simulation_app=None):
    """Load and return (scene_config, asset_library) from JSON files.

    On failure, closes simulation_app (if provided) and exits.
    """
    try:
        with open(config_path, "r") as f:
            scene_config = json.load(f)
        with open(library_path, "r") as f:
            asset_library = json.load(f)
        return scene_config, asset_library
    except Exception as e:
        print(f"Failed to load configs from {config_path} or {library_path}: {e}")
        if simulation_app:
            simulation_app.close()
        sys.exit(1)
