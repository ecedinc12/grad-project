"""Diagnostic: find which warehouse prims have semantics attached."""
from isaacsim import SimulationApp
sim = SimulationApp({"headless": True})

import json
import os
import omni.replicator.core as rep
import omni.usd
import omni.kit.commands

OUTPUT_FILE = "/workspace/grad-project/debug_output/warehouse_semantics.txt"

with open("assets/library.json") as f:
    library = json.load(f)

rep.create.from_usd(library["zone"])

stage = omni.usd.get_context().get_stage()
os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)

with open(OUTPUT_FILE, "w") as f:
    f.write(f"Stage: {stage.GetRootLayer().identifier}\n")
    if stage.GetDefaultPrim().IsValid():
        f.write(f"Default prim: {stage.GetDefaultPrim().GetPath()}\n")
    f.write("\n")

    for prim in stage.Traverse():
        path = str(prim.GetPath())
        for attr in prim.GetAttributes():
            attr_name = attr.GetName()
            if "semantic" in attr_name.lower():
                f.write(f"[SEM] {path:60s}  {attr_name} = {attr.Get()}\n")

    f.write("\n[DONE]\n")

print(f"[INFO] Output written to {OUTPUT_FILE}")
sim.close()
