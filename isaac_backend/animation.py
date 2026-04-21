"""
animation.py — re-export shim

This module is kept for backward compatibility. New code should import directly
from the focused modules:
  - isaac_backend.ira_setup      (extensions, navmesh, biped, behaviors, animgraph)
  - isaac_backend.command_injection (command building and AgentManager injection)
  - isaac_backend.vehicle_animation (VehicleAnimator)
"""

from isaac_backend.ira_setup import (
    AgentManager,
    BehaviorScriptPaths,
    PrimPaths,
    CharacterUtil,
    _HAS_IRA_CORE,
    _HAS_IRA_BEHAVIOR,
    _HAS_KIT_COMMANDS,
    Sdf,
    _refresh_ira_state,
    enable_behavior_extensions,
    bake_navmesh,
    ensure_biped_setup,
    create_character_wrapper_usd,
    setup_all_behaviors_async,
    link_workers_to_animation_graph,
)
from isaac_backend.command_injection import (
    WAREHOUSE_X_RANGE,
    WAREHOUSE_Y_RANGE,
    inject_commands_after_play,
    reinject_random_commands,
)
from isaac_backend.vehicle_animation import VehicleAnimator

import sys
import time


def _progress(msg):
    print(f"[PROGRESS] [{time.strftime('%H:%M:%S')}] {msg}")
    sys.stdout.flush()


__all__ = [
    "AgentManager", "BehaviorScriptPaths", "PrimPaths", "CharacterUtil",
    "_HAS_IRA_CORE", "_HAS_IRA_BEHAVIOR", "_HAS_KIT_COMMANDS", "Sdf",
    "_refresh_ira_state", "enable_behavior_extensions", "bake_navmesh",
    "ensure_biped_setup", "create_character_wrapper_usd",
    "setup_all_behaviors_async", "link_workers_to_animation_graph",
    "WAREHOUSE_X_RANGE", "WAREHOUSE_Y_RANGE",
    "inject_commands_after_play", "reinject_random_commands",
    "VehicleAnimator", "_progress",
]
