"""
Worker Spawner — Spawn worker characters as Xform prims with USD references + semantics.

omni.anim.people handles animation internally — no AnimationGraph setup needed.
"""

import random
from pxr import Gf, Usd, UsdGeom
import omni.usd
from isaac_backend.semantics import apply_usd_semantics, _set_semantic

_PPE_KEYS = ["worker_with_ppe", "worker_with_ppe_alt"]
_NO_PPE_KEYS = ["worker_no_ppe"]


def _find_skelroot(prim):
    """Find the first SkelRoot descendant of a prim (inside referenced USD)."""
    for child in Usd.PrimRange(prim):
        if child.GetTypeName() == "SkelRoot":
            return child
    return None


def _wait_for_skelroot(prim_path, stage, simulation_app, max_ticks=240):
    """Poll until the SkelRoot descendant appears inside a referenced character USD.

    S3-hosted USD assets load asynchronously. After AddReference(), the
    SkelRoot inside the reference is not immediately reachable via
    Usd.PrimRange. This function ticks the simulation app and re-checks
    until the SkelRoot resolves or the timeout expires.
    """
    for tick in range(max_ticks):
        prim = stage.GetPrimAtPath(prim_path)
        skelroot = _find_skelroot(prim) if prim and prim.IsValid() else None
        if skelroot is not None:
            print(f"[INFO] SkelRoot resolved for {prim_path} after {tick + 1} ticks")
            return skelroot
        simulation_app.update()
        if tick > 0 and tick % 60 == 0:
            print(f"[INFO] Still waiting for SkelRoot at {prim_path} ({tick}/{max_ticks} ticks)...")
    print(f"[ERROR] SkelRoot never appeared for {prim_path} after {max_ticks} ticks")
    return None


def select_worker_usd(ppe_state, asset_library):
    """Return the worker USD path based on PPE state."""
    if ppe_state.get("hardhat", False) or ppe_state.get("vest", False):
        key = random.choice(_PPE_KEYS)
    else:
        key = random.choice(_NO_PPE_KEYS)
    return asset_library[key]


def spawn_workers(workers, worker_behaviors, asset_library, stage, simulation_app=None):
    """Spawn workers as Xform prims with USD references and semantics.

    Returns a set of spawned worker names (e.g. {"worker_01", "worker_02"}).
    """
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

        apply_usd_semantics(prim_path, "person")
        for child in Usd.PrimRange(prim):
            _set_semantic(child, "person")
        spawned_names.add(name)

        print(f"[INFO] Spawned {name} @ ({spawn_x:.2f}, {spawn_y:.2f}, 0.0) ppe={ppe_state}")

    # Wait for SkelRoots to resolve (needed for behavior script attachment)
    if simulation_app is not None and workers:
        for worker_idx, entity in enumerate(workers, 1):
            name = f"worker_{worker_idx:02d}"
            prim_path = f"/World/Characters/{name}"
            skelroot = _wait_for_skelroot(prim_path, stage, simulation_app)
            if skelroot is None:
                print(f"[ERROR] SkelRoot not found for {name} after timeout.")
    else:
        for worker_idx, entity in enumerate(workers, 1):
            name = f"worker_{worker_idx:02d}"
            prim_path = f"/World/Characters/{name}"
            prim = stage.GetPrimAtPath(prim_path)
            skelroot = _find_skelroot(prim) if prim and prim.IsValid() else None
            if skelroot is None:
                print(f"[WARN] SkelRoot not found for {name} (no simulation_app for async wait).")

    print(f"[INFO] Spawned {len(spawned_names)} workers: {sorted(spawned_names)}")
    return spawned_names