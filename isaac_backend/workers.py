import random
from pxr import Gf, UsdGeom
import omni.usd
import omni.replicator.core as rep
from isaac_backend.semantics import apply_semantics

_PPE_KEYS = ["worker_with_ppe", "worker_with_ppe_alt"]
_NO_PPE_KEYS = ["worker_no_ppe"]


def select_worker_usd(ppe_state, asset_library):
    if ppe_state.get("hardhat", False) or ppe_state.get("vest", False):
        key = random.choice(_PPE_KEYS)
    else:
        key = random.choice(_NO_PPE_KEYS)
    return asset_library[key]


def spawn_workers(workers, worker_behaviors, asset_library, stage):
    def _initial_pos(worker_id):
        for wb in worker_behaviors:
            if wb.get("worker_id") == worker_id:
                for cmd in wb.get("commands", []):
                    if cmd.get("command") == "GoTo":
                        return cmd.get("x", 0.0), cmd.get("y", 0.0)
        return random.uniform(-5.0, 5.0), random.uniform(-1.5, 1.5)

    if workers:
        stage.DefinePrim("/World/Characters", "Xform")

    spawned_names = set()
    worker_idx = 0
    for entity in workers:
        worker_idx += 1
        name = f"worker_{worker_idx:02d}"
        prim_path = f"/World/Characters/{name}"

        ppe_state = entity.get("ppe_state") or {}
        usd_path = select_worker_usd(ppe_state, asset_library)

        prim = stage.DefinePrim(prim_path, "Xform")
        prim.GetReferences().AddReference(usd_path)

        spawn_x, spawn_y = _initial_pos(name)
        xf = UsdGeom.Xformable(prim)
        xf.ClearXformOpOrder()
        xf.AddTranslateOp().Set(Gf.Vec3d(spawn_x, spawn_y, 0.0))

        apply_semantics(prim_path, "person")
        spawned_names.add(name)

        print(f"[INFO] Spawned {name} @ ({spawn_x:.2f}, {spawn_y:.2f}, 0.0) ppe={ppe_state}")

    print(f"[INFO] Spawned {len(spawned_names)} workers: {sorted(spawned_names)}")
    return spawned_names