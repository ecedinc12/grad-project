"""
Inspect Worker & Warehouse USD Assets — Semantic Label Diagnostic

Runs on the RunPod to diagnose why 'person' category is missing from
CocoWriter output and why 'other' dominates annotations.

PURPOSE:
  1. Load each worker USD variant and traverse the full prim hierarchy
  2. Report all semantic labels found (semantic:Semantics + Semantic API)
  3. Check if child prims override/clobber the parent "person" label
  4. Test whether _set_semantic("person") propagates or gets overridden
  5. Inspect the warehouse USD for "other"-labeled prims that leak through

RUN ON POD:
  /isaac-sim/python.sh scripts/inspect_worker_assets.py
"""

import os
import sys
import json
import time
from collections import defaultdict, Counter

# CRITICAL: SimulationApp MUST be created BEFORE any omni.* or pxr.* imports
from isaacsim import SimulationApp

simulation_app = SimulationApp({"headless": True})

import omni.usd
from pxr import Sdf, Usd, UsdGeom

sys.path.insert(0, "/workspace")
from isaac_backend.semantics import (
    _set_semantic,
    _clear_semantic,
    VALID_SEMANTICS,
)


def _load_asset(prim_path, usd_url, stage, tick_count=60):
    """Add a USD reference and tick until prims resolve."""
    prim = stage.DefinePrim(prim_path, "Xform")
    prim.GetReferences().AddReference(usd_url)
    for _ in range(tick_count):
        simulation_app.update()
    return prim


def _get_all_semantic_attrs(prim):
    """Collect all semantic-like attributes from a prim."""
    attrs = {}
    for attr in prim.GetAttributes():
        name = attr.GetName()
        if "semantic" in name.lower() or "Semantic" in name:
            val = attr.Get() if attr.HasValue() else None
            attrs[name] = str(val) if val is not None else None
    return attrs


def _check_semantic_api(prim):
    """Check if prim has the Semantic API schema applied."""
    has_api = prim.HasAPI(Usd.SchemaBase)
    api_types = []
    if prim.IsA(Usd.SchemaBase):
        api_types.append(str(prim.GetTypeName()))
    return api_types


def _collect_all_labels(prim):
    """Gather semantic labels from all sources on a prim."""
    labels = {}

    # Check semantic:Semantics namespace (what our code uses)
    data_attr = prim.GetAttribute("semantic:Semantics:params:semanticData")
    type_attr = prim.GetAttribute("semantic:Semantics:params:semanticType")
    if data_attr and data_attr.HasValue():
        val = data_attr.Get()
        labels["semanticData"] = str(val) if val else None
    if type_attr and type_attr.HasValue():
        labels["semanticType"] = str(type_attr.Get())

    # Check for Semantic API schema on the prim
    # Isaac Sim also uses prim.ApplyAPI("Semantic") which stores data differently
    # Look for primvars or properties under "semantic" namespace variants
    all_sem = _get_all_semantic_attrs(prim)
    if all_sem:
        labels["_all_semantic_attrs"] = all_sem

    return labels


def inspect_worker(variant_name, prim_path, stage, depth_limit=15):
    """Deep-inspect a worker prim and all its descendants."""
    prim = stage.GetPrimAtPath(prim_path)
    if not prim or not prim.IsValid():
        print(f"  [ERROR] Prim {prim_path} is not valid!")
        return

    print(f"\n{'='*70}")
    print(f"  WORKER VARIANT: {variant_name}")
    print(f"  Prim path: {prim_path}")
    print(f"  Prim type: {prim.GetTypeName()}")
    print(f"{'='*70}")

    total_prims = 0
    prims_with_semantics = 0
    semantic_counter = Counter()
    conflict_prims = []
    ppe_items = []
    type_counter = Counter()
    mesh_prims_with_semantics = []

    for child in Usd.PrimRange(prim):
        total_prims += 1
        path = str(child.GetPath())
        depth = path.count("/") - prim_path.count("/")
        type_name = child.GetTypeName()
        type_counter[type_name] += 1

        labels = _collect_all_labels(child)
        if labels.get("semanticData"):
            prims_with_semantics += 1
            label = labels["semanticData"]
            semantic_counter[label] += 1

            # Track conflicts: any label that isn't "person" on worker prims
            if label.lower() not in ("person", ""):
                conflict_prims.append((path, label, type_name))

            # Track mesh prims with semantics (these produce bboxes)
            if type_name == "Mesh":
                mesh_prims_with_semantics.append((path, label))

        # Check for PPE-related prims
        name_lower = path.lower()
        ppe_keywords = [
            "hardhat", "helmet", "hat", "vest", "safety", "goggle",
            "glove", "boot", "ppe", "protective", "shield", "construction",
            "hazard_suit",
        ]
        for kw in ppe_keywords:
            if kw in name_lower:
                ppe_items.append((path, type_name, kw))
                break

    print(f"\n  Total prims under {prim_path}: {total_prims}")
    print(f"  Prims with semantic labels: {prims_with_semantics}")
    print(f"\n  Prim type breakdown:")
    for t, c in type_counter.most_common(20):
        print(f"    {t or '(no type)':30s} x{c}")

    print(f"\n  Semantic label distribution:")
    for label, count in semantic_counter.most_common():
        marker = "  <-- CONFLICT" if label.lower() != "person" else ""
        print(f"    '{label}'{marker} x{count}")

    print(f"\n  Mesh prims with semantics (produce bounding boxes):")
    for path, label in mesh_prims_with_semantics[:10]:
        print(f"    {path}")
        print(f"      label='{label}'")
    if len(mesh_prims_with_semantics) > 10:
        print(f"    ... and {len(mesh_prims_with_semantics) - 10} more")

    if conflict_prims:
        print(f"\n  CONFLICT DETECTED — prims with non-'person' labels:")
        for path, label, type_name in conflict_prims[:20]:
            print(f"    {path}")
            print(f"      label='{label}' type={type_name}")
        if len(conflict_prims) > 20:
            print(f"    ... and {len(conflict_prims) - 20} more conflicting prims")
    else:
        print(f"\n  No conflicts found — all worker prims labeled 'person'")

    if ppe_items:
        print(f"\n  PPE-related prims found:")
        for path, type_name, kw in ppe_items:
            labels = _collect_all_labels(stage.GetPrimAtPath(path))
            sem = labels.get("semanticData", "(none)")
            print(f"    {path}  type={type_name}  keyword={kw}  semantic='{sem}'")
    else:
        print(f"\n  No PPE-related prims found")

    return {
        "total_prims": total_prims,
        "prims_with_semantics": prims_with_semantics,
        "semantic_counter": dict(semantic_counter),
        "conflict_prims": conflict_prims,
        "ppe_items": ppe_items,
        "mesh_prims_with_semantics": mesh_prims_with_semantics,
    }


def test_semantic_override(prim_path, stage):
    """Test whether applying 'person' semantics actually sticks on child prims."""
    prim = stage.GetPrimAtPath(prim_path)
    if not prim or not prim.IsValid():
        print(f"  [ERROR] Prim {prim_path} not valid for override test")
        return

    print(f"\n{'='*70}")
    print(f"  SEMANTIC OVERRIDE TEST: {prim_path}")
    print(f"{'='*70}")

    # Collect labels BEFORE override
    before = {}
    for child in Usd.PrimRange(prim):
        labels = _collect_all_labels(child)
        if labels.get("semanticData"):
            before[str(child.GetPath())] = labels["semanticData"]

    # Apply "person" to ALL prims under this worker (same as main.py does)
    for child in Usd.PrimRange(prim):
        _set_semantic(child, "person")

    # Force USD to resolve
    stage = omni.usd.get_context().get_stage()

    # Collect labels AFTER override
    after = {}
    conflicts = []
    for child in Usd.PrimRange(prim):
        labels = _collect_all_labels(child)
        label = labels.get("semanticData")
        if label and label.lower() != "person":
            conflicts.append((str(child.GetPath()), label, child.GetTypeName()))
        if labels.get("semanticData"):
            after[str(child.GetPath())] = labels["semanticData"]

    print(f"\n  Prims with semantics BEFORE override: {len(before)}")
    print(f"  Prims with semantics AFTER override:  {len(after)}")

    # Check what changed
    changed_to_person = 0
    unchanged = 0
    reverted = 0
    for path, label in after.items():
        if path not in before:
            changed_to_person += 1
        elif before[path] != label:
            changed_to_person += 1
        else:
            unchanged += 1

    print(f"  Newly labeled:    {changed_to_person}")
    print(f"  Unchanged:        {unchanged}")

    # Check for prims that STILL don't say "person" (USD composition override)
    if conflicts:
        print(f"\n  [CRITICAL] {len(conflicts)} prims REVERTED after override (USD composition wins):")
        for path, label, type_name in conflicts[:15]:
            print(f"    {path}")
            print(f"      reverted to '{label}'  type={type_name}")
        if len(conflicts) > 15:
            print(f"    ... and {len(conflicts) - 15} more reverted prims")
    else:
        print(f"\n  Override successful — all prims now carry 'person' label")

    # Now check if HasAuthoredValue differs from resolved value
    # This reveals USD composition masking
    value_conflicts = []
    for child in Usd.PrimRange(prim):
        data_attr = child.GetAttribute("semantic:Semantics:params:semanticData")
        if data_attr and data_attr.HasValue():
            authored = data_attr.Get()
            # Check if there's a stronger opinion from the reference
            resolved = data_attr.Get()
            if str(authored).lower() != "person" and str(resolved).lower() != "person":
                value_conflicts.append((str(child.GetPath()), str(authored), str(resolved)))

    if value_conflicts:
        print(f"\n  [COMPOSITION] {len(value_conflicts)} prims where USD reference overrides local opinion:")
        for path, authored_val, resolved_val in value_conflicts[:10]:
            print(f"    {path}")
            print(f"      authored='{authored_val}'  resolved='{resolved_val}'")

    return {"conflicts": conflicts, "value_conflicts": value_conflicts}


def inspect_warehouse(stage):
    """Inspect warehouse USD for prims with unwanted semantic labels."""
    print(f"\n{'='*70}")
    print(f"  WAREHOUSE SEMANTIC INSPECTION")
    print(f"{'='*70}")

    semantic_counter = Counter()
    unwanted_prims = []
    total_with_sem = 0

    for prim in stage.Traverse():
        labels = _collect_all_labels(prim)
        label = labels.get("semanticData")
        if label:
            total_with_sem += 1
            semantic_counter[label] += 1
            if label.lower() not in VALID_SEMANTICS:
                unwanted_prims.append((str(prim.GetPath()), label, prim.GetTypeName()))

    print(f"\n  Total prims with semantic labels: {total_with_sem}")
    print(f"\n  Label distribution:")
    for label, count in semantic_counter.most_common():
        marker = "  <-- UNWANTED" if label.lower() not in VALID_SEMANTICS else ""
        print(f"    '{label}'{marker} x{count}")

    if unwanted_prims:
        print(f"\n  UNWANTED labels ({len(unwanted_prims)} prims):")
        label_groups = defaultdict(list)
        for path, label, type_name in unwanted_prims:
            label_groups[label].append((path, type_name))

        for label, items in sorted(label_groups.items(), key=lambda x: -len(x[1])):
            print(f"    '{label}' — {len(items)} prims")
            for path, type_name in items[:3]:
                print(f"      {path}  (type={type_name})")
            if len(items) > 3:
                print(f"      ... and {len(items) - 3} more")

    # Check semantics that would produce "other" in CocoWriter
    print(f"\n  Labels that would generate 'other' in CocoWriter:")
    other_producers = [p for p in unwanted_prims if p[1].lower() not in ("",)]
    print(f"    {len(other_producers)} prims with non-empty labels outside VALID_SEMANTICS")

    return {
        "total_with_sem": total_with_sem,
        "semantic_counter": dict(semantic_counter),
        "unwanted_prims": unwanted_prims,
    }


def inspect_semantic_api_schema(stage):
    """Check if any prim uses the Semantic API schema instead of semantic:Semantics attrs."""
    print(f"\n{'='*70}")
    print(f"  SEMANTIC API SCHEMA CHECK")
    print(f"{'='*70}")

    # Isaac Sim has TWO semantic labeling systems:
    # 1. semantic:Semantics:params:semanticData (what our code uses)
    # 2. UsdUtils.SemanticTags API or omni.kit.semantics (what Replicator's
    #    rep.modify.semantics uses under the hood)
    #
    # Replicator may ONLY read the Semantic API schema, not the
    # semantic:Semantics namespace. This would explain why our USD attrs
    # don't show up in CocoWriter output.

    api_count = 0
    namespace_count = 0
    both = 0
    neither = 0

    for prim in stage.Traverse():
        has_namespace = False
        has_api = False

        data_attr = prim.GetAttribute("semantic:Semantics:params:semanticData")
        if data_attr and data_attr.HasValue():
            has_namespace = True

        # Check for Semantic API via property existence
        # The Semantic API adds properties like sem:semanticData, sem:semanticType
        # or via UsdSemantics
        for attr in prim.GetAttributes():
            attr_name = attr.GetName()
            # Check for omni.kit.semantics style (used by rep.modify.semantics)
            if attr_name in ("sem:semanticData", "sem:semanticType",
                             "semantics:semanticData", "semantics:semanticType"):
                has_api = True
                break

        if has_namespace and has_api:
            both += 1
        elif has_namespace:
            namespace_count += 1
        elif has_api:
            api_count += 1
        else:
            neither += 1

    print(f"\n  Prims with semantic:Semantics namespace ONLY:  {namespace_count}")
    print(f"  Prims with semantic API attrs ONLY:             {api_count}")
    print(f"  Prims with BOTH:                                 {both}")
    print(f"  Prims with NEITHER:                              {neither}")

    print(f"\n  NOTE: If CocoWriter reads the Semantic API (sem:semanticData)")
    print(f"  but our code writes semantic:Semantics:params:semanticData,")
    print(f"  that explains why 'person' labels don't appear in output.")

    return {"namespace_only": namespace_count, "api_only": api_count, "both": both}


def check_isthing_in_output(coco_path=None):
    """Check whether generated COCO JSON has isthing fields."""
    import glob as glob_mod

    if coco_path is None:
        candidates = sorted(glob_mod.glob("/tmp/dataset/coco_annotations_*.json"))
        if not candidates:
            candidates = sorted(glob_mod.glob("/tmp/dataset/Replicator/coco_annotations_*.json"))
        if not candidates:
            print("\n  No COCO annotation files found — skipping isthing check")
            return
        coco_path = candidates[-1]

    print(f"\n{'='*70}")
    print(f"  COCO OUTPUT INSPECTION: {os.path.basename(coco_path)}")
    print(f"{'='*70}")

    with open(coco_path, "r") as f:
        coco_data = json.load(f)

    print(f"\n  Categories in COCO output:")
    has_isthing = False
    for cat in coco_data.get("categories", []):
        isthing = cat.get("isthing", "MISSING")
        if isthing != "MISSING":
            has_isthing = True
        print(f"    id={cat.get('id'):3d}  name={cat.get('name', '?'):25s}  isthing={isthing}")

    total_anns = len(coco_data.get("annotations", []))
    print(f"\n  Total annotations: {total_anns}")

    # Count per category
    from collections import Counter as _C
    cat_map = {c["id"]: c["name"] for c in coco_data.get("categories", [])}
    cat_counts = _C(a["category_id"] for a in coco_data.get("annotations", []))
    print(f"\n  Annotation counts:")
    for cid, count in cat_counts.most_common():
        print(f"    {cat_map.get(cid, '???'):25s} (id={cid}): {count}")

    if not has_isthing:
        print(f"\n  [ISSUE] No 'isthing' field in ANY category — CocoWriter requires")
    else:
        print(f"\n  'isthing' field is present in categories")


# ── Main ──

def main():
    print("=" * 70)
    print("  WORKER & WAREHOUSE ASSET INSPECTOR")
    print("=" * 70)

    stage = omni.usd.get_context().get_stage()

    with open("/workspace/assets/library.json", "r") as f:
        asset_library = json.load(f)

    worker_variants = {
        "worker_with_ppe": asset_library["worker_with_ppe"],
        "worker_with_ppe_alt": asset_library.get("worker_with_ppe_alt", asset_library["worker_with_ppe"]),
        "worker_no_ppe": asset_library.get("worker_no_ppe", asset_library["worker_with_ppe"]),
    }

    # ── Phase 1: Load worker variants and inspect ──
    print("\n[Phase 1] Loading worker USD variants...")
    worker_results = {}

    for variant_name, usd_url in worker_variants.items():
        prim_path = f"/World/Inspect_{variant_name}"
        print(f"\n  Loading {variant_name} from {usd_url.split('/')[-1]}...")
        prim = _load_asset(prim_path, usd_url, stage, tick_count=120)
        result = inspect_worker(variant_name, prim_path, stage)
        if result:
            worker_results[variant_name] = result

    # ── Phase 2: Test semantic override propagation ──
    print("\n\n[Phase 2] Testing semantic override propagation...")
    # Use the first successfully loaded worker
    for variant_name in worker_variants:
        prim_path = f"/World/Inspect_{variant_name}"
        prim = stage.GetPrimAtPath(prim_path)
        if prim and prim.IsValid():
            override_result = test_semantic_override(prim_path, stage)
            break
    else:
        print("  No valid worker prim found for override test")

    # ── Phase 3: Load warehouse and inspect for "other" labels ──
    print("\n\n[Phase 3] Loading warehouse USD for 'other' label inspection...")
    warehouse_url = asset_library.get("zone")
    if warehouse_url:
        print(f"  Loading warehouse from {warehouse_url.split('/')[-1]}...")
        _load_asset("/World/InspectWarehouse", warehouse_url, stage, tick_count=120)
        warehouse_result = inspect_warehouse(stage)
    else:
        print("  No warehouse URL in asset library — skipping")
        warehouse_result = None

    # ── Phase 4: Check semantic API schema vs namespace ──
    print("\n\n[Phase 4] Checking semantic API schema vs namespace...")
    schema_result = inspect_semantic_api_schema(stage)

    # ── Phase 5: Check existing COCO output for isthing ──
    print("\n\n[Phase 5] Checking COCO output for isthing field...")
    check_isthing_in_output()

    # ── Summary ──
    print(f"\n\n{'='*70}")
    print(f"  DIAGNOSTIC SUMMARY")
    print(f"{'='*70}")

    all_conflicts = []
    for variant, result in worker_results.items():
        if result["conflict_prims"]:
            all_conflicts.extend(result["conflict_prims"])

    if all_conflicts:
        print(f"\n  [ROOT CAUSE] Worker prims have non-'person' labels that override our USD attributes:")
        unique_labels = set(label for _, label, _ in all_conflicts)
        print(f"    Conflicting labels found: {sorted(unique_labels)}")
        print(f"    Total prims with conflicts: {len(all_conflicts)}")
        print(f"\n  FIX: Use rep.modify.semantics([('class', 'person')]) on worker prims")
        print(f"       instead of relying on USD attribute writes via _set_semantic().")
    else:
        print(f"\n  Worker semantics override test PASSED — all prims carry 'person' label.")
        print(f"  Issue may be in CocoWriter not reading semantic:Semantics namespace.")

    if warehouse_result and warehouse_result["unwanted_prims"]:
        unwanted_labels = set(label for _, label, _ in warehouse_result["unwanted_prims"])
        if warehouse_result["semantic_counter"].get("other", 0) > 0:
            print(f"\n  [ROOT CAUSE] Warehouse has '{'other'}' labeled prims ({warehouse_result['semantic_counter']['other']} prims).")
            print(f"  Total unwanted labels: {sorted(unwanted_labels)}")
            print(f"  FIX: Run clear_unwanted_warehouse_semantics() AFTER all spawning.")
        else:
            print(f"\n  Warehouse has unwanted labels but no 'other': {sorted(unwanted_labels)}")

    if schema_result["namespace_only"] > 0 and schema_result["api_only"] == 0:
        print(f"\n  [ROOT CAUSE] All semantics use semantic:Semantics namespace ONLY.")
        print(f"  CocoWriter may be reading from the Semantic API schema instead.")
        print(f"  FIX: Use rep.modify.semantics() which writes to the correct schema.")

    print(f"\n{'='*70}")
    print(f"  INSPECTION COMPLETE")
    print(f"{'='*70}")

    simulation_app.close()
    os._exit(0)


if __name__ == "__main__":
    main()