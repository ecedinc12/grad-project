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

VALID_SEMANTICS = {
    "person", "vehicle", "rack", "pallet", "box", "barrel",
    "cone", "fire_extinguisher", "cart", "sign", "pillar",
    "hazard_zone_warning", "hazard_zone_restricted", "hazard_zone_critical",
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
    """Strip ALL semantics from prims that are not in our valid set.

    Traverses the entire stage to clear labels like 'wall', 'floor',
    'ceiling', 'other', etc. that would create unwanted categories
    in CocoWriter. Only preserves labels in VALID_SEMANTICS.
    """
    cleared = 0
    for prim in stage.Traverse():
        semantic_data_attr = prim.GetAttribute("semantic:Semantics:params:semanticData")
        if not semantic_data_attr or not semantic_data_attr.HasAuthoredValue():
            continue
        label = str(semantic_data_attr.Get()).lower()
        if label not in VALID_SEMANTICS:
            semantic_data_attr.Clear()
            semantic_type_attr = prim.GetAttribute("semantic:Semantics:params:semanticType")
            if semantic_type_attr and semantic_type_attr.HasAuthoredValue():
                semantic_type_attr.Clear()
            cleared += 1

    print(f"[INFO] Cleared unwanted semantics from {cleared} prims (kept: {VALID_SEMANTICS}).")