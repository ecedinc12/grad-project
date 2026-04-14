# IRA (Isaac Replicator Agent) — People Animation Guide

## Overview

IRA (`isaacsim.replicator.agent`) is Isaac Sim 5.1's built-in system for controlling human characters and robots during data generation. It handles navmesh navigation, animation blending, obstacle avoidance, and command sequencing automatically.

**Key extensions:**
- `isaacsim.replicator.agent.core` — Core agent management, command injection, simulation loop
- `isaacsim.replicator.agent.ui` — UI panels (command editor, command injection, settings)
- `isaacsim.replicator.behavior` — BehaviorScript framework for attaching scripts to prims
- `omni.anim.people` — Character animation engine (SkelRoot, animation graphs, walk/idle/look animations)

---

## Architecture

### Extension Locations (on RunPod)

```
/isaac-sim/exts/isaacsim.replicator.behavior/
  isaacsim/replicator/behavior/
    base_behavior.py          — BaseBehavior class (extends BehaviorScript)
    behavior_utils.py         — add_behavior_script(), add_behavior_script_with_parameters_async()
    behaviors/                — Built-in behaviors (light_randomizer, look_at_behavior, etc.)
    global_variables.py       — EXPOSED_ATTR_NS = "exposedVar"

/isaac-sim/extscache/isaacsim.replicator.agent.core-VERSION/
  isaacsim/replicator/agent/core/
    agent_manager.py          — AgentManager singleton: register_agent(), inject_command()
    settings.py               — BehaviorScriptPaths, PrimPaths, CommandSetting
    stage_util.py             — CharacterUtil, RobotUtil, CameraUtil
    simulation.py             — Simulation setup/teardown
    randomization/
      character_randomizer.py — Randomizes character commands

/isaac-sim/extscache/isaacsim.replicator.agent.ui-VERSION/
  isaacsim/replicator/agent/ui/
    agent_sdg/command_manager.py  — CharacterCommandManager, RobotCommandManager
    command_injection/inject_panel.py — Command injection UI
```

### Built-in Character Behavior Script

The default character behavior script lives at:
```
<omni.anim.people extension path>/omni/anim/people/scripts/character_behavior.py
```

Resolved programmatically via:
```python
from isaacsim.replicator.agent.core.settings import BehaviorScriptPaths
script_path = BehaviorScriptPaths.behavior_script_path()
```

This script handles GoTo, Idle, LookAround, Sit, Queue commands internally using `Omni.Anim.People`.

---

## How IRA Processes Commands

### Command Format

All commands follow the pattern: `agent_name command params`

```
Character_01 GoTo 10 10 0 90      # x, y, z, rotation (degrees)
Character_01 Idle 5               # duration in seconds
Character_01 LookAround 3         # duration in seconds (head animation)
Character_01 GoTo 10 10 0 _       # _ = no rotation change
Character_01 GoTo 5 5 0 0 8 8 0 90  # sequence of waypoints
```

### Command Flow

1. **Behavior Script Attachment**: Script attached to character's SkelRoot via ScriptingAPI
2. **Agent Registration**: When timeline plays, behavior script's `on_play()` fires, agent registers with `AgentManager` via `AgentEvent.AgentRegistered` event
3. **Command Processing**: Behavior script reads commands from its internal command list and executes them
4. **Command Injection**: `AgentManager.inject_command()` can override current commands at runtime

---

## Programmatic API Reference

### 1. Attaching the Built-in Behavior Script

```python
from isaacsim.replicator.agent.core.settings import BehaviorScriptPaths
from isaacsim.replicator.agent.core.stage_util import CharacterUtil

# Get the path to IRA's built-in character behavior script
script_path = BehaviorScriptPaths.behavior_script_path()
# Returns: <omni.anim.people>/omni/anim/people/scripts/character_behavior.py

# Get all character SkelRoots in the stage
skelroots = CharacterUtil.get_characters_in_stage()

# Attach the behavior script to all characters
CharacterUtil.setup_python_scripts_to_character(skelroots, script_path)
```

**What `setup_python_scripts_to_character` does:**
```python
def setup_python_scripts_to_character(character_skelroot_list, python_script_path):
    paths = [Sdf.Path(prim.GetPrimPath()) for prim in character_skelroot_list]
    omni.kit.commands.execute("RemoveScriptingAPICommand", paths=paths)
    omni.kit.commands.execute("ApplyScriptingAPICommand", paths=paths)
    for prim in character_skelroot_list:
        attr = prim.GetAttribute("omni:scripting:scripts")
        attr.Set([python_script_path])
```

### 2. Alternative: Using behavior_utils.py

```python
from isaacsim.replicator.behavior.utils.behavior_utils import (
    add_behavior_script,
    add_behavior_script_with_parameters_async,
)

# Simple attachment (sync)
add_behavior_script(prim, script_path)

# Attachment with exposed variables (async)
await add_behavior_script_with_parameters_async(
    prim,
    script_path,
    exposed_variables={
        "exposedVar:workerPatrol:waypoints:csv": "10,10,0,90;5,5,0,0",
        "exposedVar:workerPatrol:speed": 1.0,
    }
)
```

### 3. Injecting Commands (After Agent Registration)

```python
from isaacsim.replicator.agent.core.agent_manager import AgentManager

# Get the singleton instance
agent_manager = AgentManager.get_instance()

# Check if agent is registered
is_registered = agent_manager.agent_registered("worker_01")

# Inject commands to a specific agent
agent_manager.inject_command(
    agent_name="worker_01",
    command_list=[
        "GoTo 10 10 0 90",
        "Idle 5",
        "LookAround 3",
        "GoTo 5 5 0 0",
    ],
    force_inject=True,    # Interrupt current command immediately
    instant=True,         # Execute immediately
)

# Inject commands to ALL agents at once
agent_manager.inject_command_for_all_agents(
    [
        "worker_01 GoTo 10 10 0 90",
        "worker_01 Idle 5",
        "worker_02 GoTo 5 5 0 0",
        "worker_02 LookAround 3",
    ],
    force_inject=True,
)

# Replace commands (without force interrupt)
agent_manager.replace_command(
    agent_name="worker_01",
    command_list=["GoTo 0 0 0 0", "Idle 10"],
)
```

### 4. Agent Registration Timing

Agents register AFTER `timeline.play()` fires. You must wait:

```python
omni.timeline.get_timeline_interface().play()

# Wait for agent registration (minimum 2 update cycles)
await omni.kit.app.get_app().next_update_async()
await omni.kit.app.get_app().next_update_async()

# Now agents are registered, inject commands
agent_manager = AgentManager.get_instance()
agent_manager.inject_command(...)
```

### 5. Querying Agent State

```python
from isaacsim.replicator.agent.core.agent_manager import AgentManager
from isaacsim.replicator.agent.core.stage_util import CharacterUtil

agent_manager = AgentManager.get_instance()

# Get all registered agent names
all_names = agent_manager.get_all_agent_names()

# Get agent position by name
position = agent_manager.get_agent_position("worker_01")

# Get agent script instance by name
script_inst = agent_manager.get_agent_script_instance_by_name("worker_01")

# Get all character SkelRoots
skelroots = CharacterUtil.get_characters_in_stage()

# Get character position
position = CharacterUtil.get_character_pos(skelroot_prim)

# Get character name
name = CharacterUtil.get_character_name(skelroot_prim)
```

---

## Carb Settings

### Behavior Script Paths

```python
import carb.settings

settings = carb.settings.get_settings()

# Override character behavior script path
settings.set(
    "/exts/isaacsim/replicator.agent/behavior_script_settings/behavior_script_path",
    "/path/to/custom_behavior.py"
)

# Override Nova Carter behavior script path
settings.set(
    "/exts/isaacsim/replicator.agent/behavior_script_settings/nova_carter_behavior_script_path",
    "/path/to/carter_behavior.py"
)

# Override iw.hub behavior script path
settings.set(
    "/exts/isaacsim/replicator.agent/behavior_script_settings/iw_hub_behavior_script_path",
    "/path/to/iw_hub_behavior.py"
)
```

### Prim Paths

```python
# Default character parent path: /World/Characters
# Default robot parent path: /World/Robots
# Default camera parent path: /World/Cameras

settings.set(
    "/exts/isaacsim.replicator.agent/characters_parent_prim_path",
    "/World/Characters"
)
```

### Command Distance Settings

```python
# GoTo min/max distance for random command generation
settings.set("/persistent/exts/isaacsim.replicator.agent/character_goto_min_distance", 5.0)
settings.set("/persistent/exts/isaacsim.replicator.agent/character_goto_max_distance", 20.0)

# Root path for interactable objects (Sit, TimingToObject)
settings.set("/persistent/exts/isaacsim.replicator.agent/character_interact_object_root_path", "/World")
```

---

## Custom Behavior Scripts

### Subclassing BehaviorScript

```python
from omni.behavior.scripting.core import BehaviorScript
from pxr import Sdf

class MyBehavior(BehaviorScript):
    BEHAVIOR_NS = "myBehavior"

    VARIABLES_TO_EXPOSE = [
        {"attr_name": "myParam", "attr_type": Sdf.ValueTypeNames.Float, "default_value": 1.0},
    ]

    def on_init(self):
        # Called when script is assigned to a prim
        self.my_param = 1.0

    def on_play(self):
        # Called when timeline plays
        self.my_param = self._get_exposed_variable("myParam")

    def on_update(self, current_time, delta_time):
        # Called every frame during playback
        pass

    def on_stop(self):
        # Called when timeline stops
        pass

    def on_destroy(self):
        # Called when script is removed from prim
        pass

    def _get_exposed_variable(self, attr_name):
        from isaacsim.replicator.behavior.utils.behavior_utils import get_exposed_variable
        from isaacsim.replicator.behavior.global_variables import EXPOSED_ATTR_NS
        full_name = f"{EXPOSED_ATTR_NS}:{self.BEHAVIOR_NS}:{attr_name}"
        return get_exposed_variable(self.prim, full_name)
```

### Exposed Variables

Exposed variables are USD attributes prefixed with `exposedVar:{behavior_ns}:`:

```python
from isaacsim.replicator.behavior.global_variables import EXPOSED_ATTR_NS  # "exposedVar"

# Full attribute name: "exposedVar:workerPatrol:waypoints:csv"
full_name = f"{EXPOSED_ATTR_NS}:{behavior_ns}:{attr_name}"
```

---

## Complete Workflow (Headless)

```python
from omni.isaac.kit import SimulationApp
simulation_app = SimulationApp({"headless": True})

import omni.timeline
import omni.usd
from isaacsim.core.api import World
from isaacsim.replicator.agent.core.agent_manager import AgentManager
from isaacsim.replicator.agent.core.settings import BehaviorScriptPaths
from isaacsim.replicator.agent.core.stage_util import CharacterUtil

# 1. Create world and stage
world = World()
stage = omni.usd.get_context().get_stage()

# 2. Spawn characters (Xform + USD reference + semantics + AnimationGraphAPI)
# ... your spawning code ...

# 3. Attach IRA's built-in behavior script to all character SkelRoots
script_path = BehaviorScriptPaths.behavior_script_path()
skelroots = CharacterUtil.get_characters_in_stage()
CharacterUtil.setup_python_scripts_to_character(skelroots, script_path)

# 4. Play timeline (triggers agent registration)
omni.timeline.get_timeline_interface().play()

# 5. Wait for agent registration (minimum 2 update cycles)
for _ in range(10):
    simulation_app.update()

# 6. Inject commands via AgentManager
agent_manager = AgentManager.get_instance()
agent_manager.inject_command(
    agent_name="worker_01",
    command_list=["GoTo 10 10 0 90", "Idle 5", "LookAround 3"],
    force_inject=True,
    instant=True,
)

# 7. Run Replicator generation loop
# ... your Replicator code ...

# 8. Teardown
rep.orchestrator.stop()
writer.detach()
world.clear()
simulation_app.close()
```

---

## Gotchas

1. **Agent names**: IRA uses the prim name (`worker_01`), NOT the full path (`/World/Characters/worker_01`)

2. **Registration timing**: Agents register AFTER `timeline.play()` — inject commands only after waiting 2+ update cycles

3. **Character parent path**: Must be `/World/Characters` (or matching `PrimPaths.characters_parent_path()`) for IRA to recognize them

4. **SkelRoot required**: Behavior scripts attach to SkelRoot prims, not the Xform parent. Use `CharacterUtil.get_characters_in_stage()` which returns SkelRoots.

5. **AnimationGraph**: Characters must have AnimationGraphAPI applied and linked to an AnimationGraph prim for animations to work

6. **Navmesh**: GoTo uses navmesh navigation. If characters clip through obstacles, rebuild navmesh with higher agent radius

7. **Dynamic avoidance**: Best-effort only. With static + dynamic obstacles together, characters may behave erratically

8. **Command injection**: Only works for individual agents. Global commands like Queue will NOT work via injection

9. **Sit command**: Requires seat prim with `walk_to_offset` and `interact_offset` child Xforms

10. **Force inject**: `force_inject=True` interrupts current command immediately. If character is Sitting, they stand up first

---

## File Reference

| File | Purpose |
|------|---------|
| `behavior_utils.py` | `add_behavior_script()`, `add_behavior_script_with_parameters_async()`, exposed variable helpers |
| `base_behavior.py` | `BaseBehavior` class — template for custom behavior scripts |
| `agent_manager.py` | `AgentManager` singleton — agent registry, command injection |
| `settings.py` | `BehaviorScriptPaths`, `PrimPaths`, `CommandSetting` — all carb setting keys |
| `stage_util.py` | `CharacterUtil`, `RobotUtil`, `CameraUtil` — stage manipulation utilities |
| `command_manager.py` | `CharacterCommandManager`, `RobotCommandManager` — command parsing/formatting |
| `character_randomizer.py` | Randomizes character command sequences |
