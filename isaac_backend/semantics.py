"""
USD Semantic Label Applicator

Applies/clears USD-level semantic attributes so Replicator writers can
resolve class names for bounding boxes and segmentation outputs.

Attributes written:
  semantic:class:params:semanticType — always "class"
  semantic:class:params:semanticData — class name (e.g. "person")
"""

import omni.usd
from pxr import Sdf, Semantics

VALID_SEMANTICS = {
    "person", "vehicle", "rack", "pallet", "box", "box_small", "box_large",
    "barrel", "drum", "crate", "cone", "fire_extinguisher", "cart", "sign",
    "pillar", "hazard_zone_warning", "hazard_zone_restricted",
    "hazard_zone_critical", "hardhat", "vest",
}

HAZARD_LABELS = {"hazard_zone_warning", "hazard_zone_restricted", "hazard_zone_critical"}

def _clear_semantic(prim):
    """Clear both old and new semantic attribute schemas."""
    # Only clear if we don't already have a valid label we want to keep
    has_valid = False
    for attr_name in ("semantics:labels:class", "semantic:Semantics:params:semanticData", "semantic:class:params:semanticData"):
        attr = prim.GetAttribute(attr_name)
        if attr and attr.HasAuthoredValue():
            val = attr.Get()
            if isinstance(val, (list, tuple)) and len(val) > 0:
                val = str(val[0])
            if str(val).lower() in VALID_SEMANTICS:
                has_valid = True
                break
    
    if has_valid:
        return # Skip clearing if we already have a valid label

    for attr_name in (
        "semantics:labels:class",
        "semantic:Semantics:params:semanticData",
        "semantic:Semantics:params:semanticType",
        "semantic:class:params:semanticData",
        "semantic:class:params:semanticType",
    ):
        attr = prim.GetAttribute(attr_name)
        if attr and attr.HasAuthoredValue():
            attr.Clear()

def apply_usd_semantics(prim, class_name):
    """Apply semantics directly via standard USD API."""
    if prim and prim.IsValid():
        sem_api = Semantics.SemanticsAPI.Apply(prim, "class")
        sem_api.CreateSemanticTypeAttr().Set("class")
        sem_api.CreateSemanticDataAttr().Set(class_name)

def clear_unwanted_warehouse_semantics(stage):
    """Strip ALL semantics from prims that are not in our valid set.

    Traverses the entire stage to clear labels like 'wall', 'floor',
    'ceiling', 'other', etc. that would create unwanted categories
    in CocoWriter. Only preserves labels in VALID_SEMANTICS. Also
    normalizes valid labels to lowercase so they match COCO category keys.
    """
    cleared = 0
    normalized = 0
    for prim in stage.Traverse():
        # Check new schema (semantics:labels:class VtArray)
        attr = prim.GetAttribute("semantics:labels:class")
        if attr and attr.HasAuthoredValue():
            labels = attr.Get()
            if labels and len(labels) > 0:
                raw_label = str(labels[0])
                label = raw_label.lower()
                if label not in VALID_SEMANTICS:
                    _clear_semantic(prim)
                    cleared += 1
                elif raw_label != label:
                    _clear_semantic(prim)
                    apply_usd_semantics(prim, label)
                    normalized += 1
                continue

        # Check old schema with "Semantics" instance name
        semantic_data_attr = prim.GetAttribute("semantic:Semantics:params:semanticData")
        if semantic_data_attr and semantic_data_attr.HasAuthoredValue():
            raw_label = str(semantic_data_attr.Get())
            label = raw_label.lower()
            if label not in VALID_SEMANTICS:
                _clear_semantic(prim)
                cleared += 1
            elif raw_label != label:
                _clear_semantic(prim)
                apply_usd_semantics(prim, label)
                normalized += 1
            continue

        # Check old schema with "class" instance name (written by apply_usd_semantics)
        class_data_attr = prim.GetAttribute("semantic:class:params:semanticData")
        if class_data_attr and class_data_attr.HasAuthoredValue():
            raw_label = str(class_data_attr.Get())
            label = raw_label.lower()
            if label not in VALID_SEMANTICS:
                _clear_semantic(prim)
                cleared += 1
            elif raw_label != label:
                apply_usd_semantics(prim, label)
                normalized += 1

    print(f"[INFO] Cleared unwanted semantics from {cleared} prims, normalized {normalized} prims (kept: {VALID_SEMANTICS}).")
