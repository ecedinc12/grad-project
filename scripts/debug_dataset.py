import numpy as np
import glob
import os
import json

dataset_dir = "/tmp/dataset"

# Check bounding box NPX files
npy_files = sorted(glob.glob(os.path.join(dataset_dir, "bounding_box_2d_tight_*.npy")))
print(f"=== Bounding Box NPX Files ===")
print(f"Total files: {len(npy_files)}")

if npy_files:
    f = npy_files[0]
    data = np.load(f, allow_pickle=True)
    print(f"\nSample: {os.path.basename(f)}")
    print(f"  BBox count: {len(data)}")
    if len(data) > 0:
        row = data[0]
        print(f"  Keys: {list(row.dtype.names if hasattr(row, 'dtype') else row.keys())}")
        print(f"  First entry: {dict(row)}")
        # Collect unique semanticIds from first frame
        sids = set()
        for row in data:
            sids.add(int(row["semanticId"]))
        print(f"\n  Unique semanticIds in this frame: {sorted(sids)}")
    else:
        print("  EMPTY — no bounding boxes!")

    # Check all files for total bbox count
    total_bboxes = 0
    all_sids = set()
    empty_count = 0
    for f in npy_files:
        data = np.load(f, allow_pickle=True)
        if len(data) == 0:
            empty_count += 1
        else:
            total_bboxes += len(data)
            for row in data:
                all_sids.add(int(row["semanticId"]))
    print(f"\n  Total bboxes across all frames: {total_bboxes}")
    print(f"  Empty frames: {empty_count}/{len(npy_files)}")
    print(f"  All unique semanticIds: {sorted(all_sids)}")
else:
    print("NO NPX FILES FOUND")

# Check JSON mapping files
print(f"\n=== Mapping Files ===")
for jf in ["semantic_id_to_labels.json", "instance_segmentation_colors.json"]:
    path = os.path.join(dataset_dir, jf)
    if os.path.exists(path):
        raw = json.load(open(path))
        print(f"{jf}: EXISTS ({len(raw)} entries)")
        if len(raw) > 0:
            if isinstance(raw, dict):
                for k, v in list(raw.items())[:3]:
                    print(f"  {k}: {v}")
            elif isinstance(raw, list):
                for v in raw[:3]:
                    print(f"  {v}")
    else:
        print(f"{jf}: MISSING")

# Check segmentation files
seg_files = glob.glob(os.path.join(dataset_dir, "instance_segmentation_*.png"))
print(f"\n=== Instance Segmentation ===")
print(f"PNG files: {len(seg_files)}")

# Check RGB
rgb_files = glob.glob(os.path.join(dataset_dir, "rgb_*.png"))
print(f"\n=== RGB Frames ===")
print(f"PNG files: {len(rgb_files)}")
