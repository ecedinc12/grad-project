"""Diagnostic: find which warehouse prims have SemanticsSchema attached."""
"""Diagnostic: find which warehouse prims have SemanticsSchema attached."""
from isaacsim import SimulationApp
sim = SimulationApp({"headless": True})

import json
import omni.replicator.core as rep
from pxr import UsdSemantics
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
    has_sem = prim.HasAPI(UsdSemantics.SemanticsSchema)
    if has_sem:
        schema = UsdSemantics.SemanticsSchema(prim)
        sem_data = dict(schema.GetSemanticsData())
        print(f"[SEM] {path:60s}  {sem_data}")

print("[DONE]")
sim.close()
