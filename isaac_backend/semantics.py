"""
USD Semantic Label Applicator

Applies/clears USD-level semantic attributes so Replicator writers can
resolve class names for bounding boxes and segmentation outputs.

Attributes written:
  semantic:Semantics:params:semanticData — class name (e.g. "person")
  semantic:Semantics:params:semanticType — always "class"
"""

import omni.usd
from pxr import Sdf

KEEP_SEMANTICS = {
    "rack", "pallet",
    "pillar", "cone", "sign",
    "fire_extinguisher", "cart",
}


def apply_usd_semantics(prim_path, class_name):
    """Apply USD-level semantics to a prim for Replicator writer resolution."""
    stage = omni.usd.get_context().get_stage()
    prim = stage.GetPrimAtPath(prim_path)
    if not prim.IsValid():
        print(f"[WARN] Cannot apply semantics: prim '{prim_path}' is not valid.")
        return

    data_attr_name = "semantic:Semantics:params:semanticData"
    type_attr_name = "semantic:Semantics:params:semanticType"

    if not prim.HasAttribute(data_attr_name):
        prim.CreateAttribute(data_attr_name, Sdf.ValueTypeNames.Token, True).Set(class_name)
    else:
        prim.GetAttribute(data_attr_name).Set(class_name)

    if not prim.HasAttribute(type_attr_name):
        prim.CreateAttribute(type_attr_name, Sdf.ValueTypeNames.Token, True).Set("class")
    else:
        prim.GetAttribute(type_attr_name).Set("class")


def clear_unwanted_warehouse_semantics(stage):
    """Strip pre-existing semantics from warehouse USD structural prims,
    keeping only rack/pallet so their bounding boxes are preserved."""
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
    """Remove semantics from a prim if its label is not in KEEP_SEMANTICS."""
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
