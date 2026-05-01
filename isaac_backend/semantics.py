"""
USD Semantic Label Applicator

Applies/clears USD-level semantic attributes so Replicator writers can
resolve class names for bounding boxes and segmentation outputs.

Attributes written:
  semantic:class:params:semanticType — always "class"
  semantic:class:params:semanticData — class name (e.g. "person")
"""

import omni.usd
from pxr import Semantics

VALID_SEMANTICS = {
    "person", "vehicle", "rack", "pallet", "box", "box_small", "box_large",
    "barrel", "drum", "crate", "cone", "fire_extinguisher", "cart", "sign",
    "pillar", "hazard_zone_warning", "hazard_zone_restricted",
    "hazard_zone_critical", "hardhat", "vest",
}

HAZARD_LABELS = {"hazard_zone_warning", "hazard_zone_restricted", "hazard_zone_critical"}

def _clear_semantic(prim):
    """Clear both old and new semantic attribute schemas."""
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

_LABEL_ATTRS = (
    ("semantics:labels:class", True),                       # new schema, VtArray
    ("semantic:Semantics:params:semanticData", False),      # old schema, "Semantics" instance
    ("semantic:class:params:semanticData", False),          # old schema, "class" instance
)


def _get_label(prim):
    """Return raw label string from whichever schema is authored, else None."""
    for attr_name, is_array in _LABEL_ATTRS:
        attr = prim.GetAttribute(attr_name)
        if not (attr and attr.HasAuthoredValue()):
            continue
        val = attr.Get()
        if is_array:
            if not val or len(val) == 0:
                continue
            return str(val[0])
        return str(val)
    return None


def clear_unwanted_warehouse_semantics(stage):
    """Strip ALL semantics from prims not in VALID_SEMANTICS.

    Traverses entire stage. Clears labels like 'wall', 'floor', 'ceiling'
    that would create unwanted COCO categories. Normalizes kept labels
    to lowercase so they match category keys.
    """
    cleared = 0
    normalized = 0
    for prim in stage.Traverse():
        raw_label = _get_label(prim)
        if raw_label is None:
            continue
        label = raw_label.lower()
        if label not in VALID_SEMANTICS:
            _clear_semantic(prim)
            cleared += 1
        elif raw_label != label:
            _clear_semantic(prim)
            apply_usd_semantics(prim, label)
            normalized += 1

    print(f"[INFO] Cleared unwanted semantics from {cleared} prims, normalized {normalized} prims (kept: {VALID_SEMANTICS}).")
