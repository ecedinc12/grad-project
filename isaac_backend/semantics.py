import omni.replicator.core as rep
import omni.usd

KEEP_SEMANTICS = {
    "rack", "pallet",
    "pillar", "cone", "sign",
    "fire_extinguisher", "cart",
}

def apply_semantics(prim_path, class_name):
    """Applies semantic class to a given prim path using Replicator."""
    with rep.get.prims(path_pattern=prim_path):
        rep.modify.semantics([("class", class_name)])

def clear_unwanted_warehouse_semantics():
    """Strip pre-existing semantics from warehouse USD structural prims,
    keeping only rack and pallet so their bounding boxes are preserved."""
    stage = omni.usd.get_context().get_stage()
    warehouse_root = stage.GetPrimAtPath("/Replicator/Ref_Xform")
    if not warehouse_root.IsValid():
        print("[WARN] Warehouse root /Replicator/Ref_Xform not found — skipping semantic cleanup.")
        return

    cleared = 0
    for prim in warehouse_root.GetChildren():
        for child in prim.GetAllChildren():
            cleared += _clear_semantics_if_needed(child)

    print(f"[INFO] Cleared unwanted semantics from {cleared} warehouse prims (kept rack/pallet).")

def _clear_semantics_if_needed(prim):
    """Remove semantics from a prim if its label is not in KEEP_SEMANTICS. Returns 1 if cleared, 0 otherwise."""
    semantic_data_attr = prim.GetAttribute("semantic:Semantics:params:semanticData")
    if not semantic_data_attr or not semantic_data_attr.HasAuthoredValue():
        return 0

    label = semantic_data_attr.Get()
    if label.lower() in KEEP_SEMANTICS:
        return 0

    semantic_data_attr.Clear()
    semantic_type_attr = prim.GetAttribute("semantic:Semantics:params:semanticType")
    if semantic_type_attr and semantic_type_attr.HasAuthoredValue():
        semantic_type_attr.Clear()
    return 1
