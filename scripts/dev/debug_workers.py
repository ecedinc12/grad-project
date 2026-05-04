"""
Debug script to diagnose worker T-posing on RunPod.

Run: /isaac-sim/python.sh /tmp/debug_workers.py
"""

from isaacsim import SimulationApp
simulation_app = SimulationApp({"headless": True})

import omni.usd
import omni.timeline
from pxr import Usd

stage = omni.usd.get_context().get_stage()

print("=== Prims under /World/Characters ===")
for prim in stage.Traverse():
    path = str(prim.GetPath())
    if path.startswith("/World/Characters"):
        print(f"  {path}  type={prim.GetTypeName()}")

print("\n=== SkelRoot details ===")
for prim in stage.Traverse():
    if prim.GetTypeName() == "SkelRoot":
        path = str(prim.GetPath())
        print(f"\n  SkelRoot: {path}")
        for child in Usd.PrimRange(prim):
            print(f"    {child.GetPath()}  type={child.GetTypeName()}")
            if child.GetTypeName() == "AnimationGraph":
                print(f"      >> FOUND AnimationGraph at {child.GetPath()}")
                enabled = child.GetAttribute("enabled")
                if enabled:
                    print(f"      >> enabled = {enabled.Get()}")

import AnimGraphSchema

print("\n=== AnimationGraphAPI on SkelRoots ===")
for prim in stage.Traverse():
    if prim.GetTypeName() == "SkelRoot":
        has_api = prim.HasAPI(AnimGraphSchema.AnimationGraphAPI)
        print(f"  {prim.GetPath()}: Has AnimationGraphAPI = {has_api}")
        if has_api:
            api = AnimGraphSchema.AnimationGraphAPI(prim)
            rel = api.GetAnimationGraphRel()
            targets = rel.GetTargets()
            print(f"    -> AnimationGraphRel targets: {targets}")

print("\n=== Scripting attributes (IRA behavior) ===")
for prim in stage.Traverse():
    if prim.GetTypeName() == "SkelRoot":
        path = str(prim.GetPath())
        scripts_attr = prim.GetAttribute("omni:scripting:scripts")
        if scripts_attr:
            print(f"  {path}: omni:scripting:scripts = {scripts_attr.Get()}")
        else:
            print(f"  {path}: NO scripting attribute")

print("\n=== AgentManager state (before play) ===")
try:
    from isaacsim.replicator.agent.core.agent_manager import AgentManager
    if AgentManager.has_instance():
        am = AgentManager.get_instance()
        names = am.get_all_agent_names()
        print(f"  Registered agents: {names}")
    else:
        print("  AgentManager: no instance")
except ImportError:
    print("  isaacsim.replicator.agent.core not available")
except Exception as e:
    print(f"  AgentManager check failed: {e}")

print("\n=== After timeline.play() ===")
timeline = omni.timeline.get_timeline_interface()
timeline.play()
for _ in range(30):
    simulation_app.update()

try:
    from isaacsim.replicator.agent.core.agent_manager import AgentManager
    if AgentManager.has_instance():
        am = AgentManager.get_instance()
        names = am.get_all_agent_names()
        print(f"  Registered agents: {names}")
        for name in names:
            try:
                pos = am.get_agent_position(name)
                print(f"    {name}: position = {pos}")
            except Exception as e:
                print(f"    {name}: position query failed: {e}")
    else:
        print("  AgentManager: no instance after play")
except ImportError:
    print("  isaacsim.replicator.agent.core not available")
except Exception as e:
    print(f"  Post-play check failed: {e}")

print("\n=== Re-check scripting attributes after play ===")
for prim in stage.Traverse():
    if prim.GetTypeName() == "SkelRoot":
        path = str(prim.GetPath())
        scripts_attr = prim.GetAttribute("omni:scripting:scripts")
        if scripts_attr:
            print(f"  {path}: omni:scripting:scripts = {scripts_attr.Get()}")

simulation_app.close()
