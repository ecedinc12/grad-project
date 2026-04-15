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

HAZARD_LABELS = {"hazard_zone_warning", "hazard_zone_restricted", "hazard_zone_critical"}


def _set_semantic(prim, class_name):
    data_attr = "semantic:Semantics:params:semanticData"
    type_attr = "semantic:Semantics:params:semanticType"
    if not prim.HasAttribute(data_attr):
        prim.CreateAttribute(data_attr, Sdf.ValueTypeNames.Token, True).Set(class_name)
    else:
        prim.GetAttribute(data_attr).Set(class_name)
    if not prim.HasAttribute(type_attr):
        prim.CreateAttribute(type_attr, Sdf.ValueTypeNames.Token, True).Set("class")
    else:
        prim.GetAttribute(type_attr).Set("class")


def _clear_semantic(prim):
    for attr_name in ("semantic:Semantics:params:semanticData", "semantic:Semantics:params:semanticType"):
        attr = prim.GetAttribute(attr_name)
        if attr and attr.HasAuthoredValue():
            attr.Clear()


def apply_usd_semantics(prim_path, class_name):
    """Apply USD-level semantics to a prim for Replicator writer resolution."""
    stage = omni.usd.get_context().get_stage()
    prim = stage.GetPrimAtPath(prim_path)
    if not prim.IsValid():
        print(f"[WARN] Cannot apply semantics: prim '{prim_path}' is not valid.")
        return
    _set_semantic(prim, class_name)


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
            _clear_semantic(prim)
            cleared += 1

    print(f"[INFO] Cleared unwanted semantics from {cleared} prims (kept: {VALID_SEMANTICS}).")


def apply_scene_semantics(stage, spawned_asset_ids, workers):
    """Walk the stage and apply/correct USD-level semantics.

    1. Force-set semantics on spawned assets (vehicles, equipment) by path match.
    2. Force-set 'person' on all worker Xform and SkelRoot prims.
    3. Force-set hazard zone semantics from /World/HazardZones/.
    4. Strip any semantic labels not in VALID_SEMANTICS to prevent 'other' category.

    Returns (applied, cleared) counts.
    """
    import os

    applied = 0
    cleared = 0

    for asset_id, semantic_class in spawned_asset_ids:
        target_name = os.path.basename(asset_id)
        for prim in stage.Traverse():
            path = str(prim.GetPath())
            if not prim.IsValid():
                continue
            if target_name in path:
                _set_semantic(prim, semantic_class)
                applied += 1
                print(f"[INFO] Applied semantics '{semantic_class}' to {path}")
                break

    if workers:
        for prim in stage.Traverse():
            path = str(prim.GetPath())
            if path.startswith("/World/Characters/") and prim.GetTypeName() in ("Xform", "SkelRoot"):
                _set_semantic(prim, "person")
                applied += 1
                print(f"[INFO] Applied semantics 'person' to {path}")

    for prim in stage.Traverse():
        path = str(prim.GetPath())
        if path.startswith("/World/HazardZones/"):
            data_attr = prim.GetAttribute("semantic:Semantics:params:semanticData")
            if data_attr and data_attr.HasAuthoredValue():
                label = str(data_attr.Get())
                if label in HAZARD_LABELS:
                    _set_semantic(prim, label)
                    applied += 1

    for prim in stage.Traverse():
        data_attr = prim.GetAttribute("semantic:Semantics:params:semanticData")
        if not data_attr or not data_attr.HasAuthoredValue():
            continue
        label = data_attr.Get()
        if label and str(label).lower() not in VALID_SEMANTICS:
            _clear_semantic(prim)
            cleared += 1

    print(f"[PROGRESS] Semantics: {applied} applied, {cleared} unwanted cleared")
    return applied, cleared