import numpy as np
import glob
import os
import json

dataset_dir = "/tmp/dataset"

# Check bounding box TXT files
txt_files = sorted(glob.glob(os.path.join(dataset_dir, "rgb_*.txt")))
print(f"=== Bounding Box TXT Files (YOLO) ===")
print(f"Total files: {len(txt_files)}")

if txt_files:
    f = txt_files[0]
    with open(f, 'r') as file:
        data = file.readlines()
    print(f"\nSample: {os.path.basename(f)}")
    print(f"  BBox count: {len(data)}")
    if len(data) > 0:
        print(f"  First entry: {data[0].strip()}")
        # Collect unique class IDs from first frame
        sids = set()
        for row in data:
            parts = row.strip().split()
            if parts:
                sids.add(int(parts[0]))
        print(f"\n  Unique class IDs in this frame: {sorted(sids)}")
    else:
        print("  EMPTY — no bounding boxes!")

    # Check all files for total bbox count
    total_bboxes = 0
    all_sids = set()
    empty_count = 0
    for f in txt_files:
        with open(f, 'r') as file:
            data = file.readlines()
        if len(data) == 0:
            empty_count += 1
        else:
            total_bboxes += len(data)
            for row in data:
                parts = row.strip().split()
                if parts:
                    all_sids.add(int(parts[0]))
    print(f"\n  Total bboxes across all frames: {total_bboxes}")
    print(f"  Empty frames: {empty_count}/{len(txt_files)}")
    print(f"  All unique class IDs: {sorted(all_sids)}")
else:
    print("NO TXT FILES FOUND")

# Check Dataset YAML file
print(f"\n=== Dataset Config ===")
yaml_path = os.path.join(dataset_dir, "dataset.yaml")
if os.path.exists(yaml_path):
    print("dataset.yaml: EXISTS")
    with open(yaml_path, 'r') as f:
        print(f.read())
else:
    print("dataset.yaml: MISSING")

# Check segmentation files
seg_files = glob.glob(os.path.join(dataset_dir, "instance_segmentation_*.png"))
print(f"\n=== Instance Segmentation ===")
print(f"PNG files: {len(seg_files)}")

# Check RGB
rgb_files = glob.glob(os.path.join(dataset_dir, "rgb_*.png"))
print(f"\n=== RGB Frames ===")
print(f"PNG files: {len(rgb_files)}")
