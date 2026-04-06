"""Diagnostic: find which warehouse prims have semantics attached."""
from isaacsim import SimulationApp
sim = SimulationApp({"headless": True})

import json
import omni.replicator.core as rep
import omni.usd
import omni.kit.commands

with open("assets/library.json") as f:
    library = json.load(f)

rep.create.from_usd(library["zone"])

stage = omni.usd.get_context().get_stage()
print(f"Stage: {stage.GetRootLayer().identifier}")
print(f"Default prim: {stage.GetDefaultPrim().GetPath()}")
print()

for prim in stage.Traverse():
    path = str(prim.GetPath())
    for attr in prim.GetAttributes():
        attr_name = attr.GetName()
        if "semantic" in attr_name.lower():
            print(f"[SEM] {path:60s}  {attr_name} = {attr.Get()}")

print("[DONE]")
sim.close()
