import json
import os
import glob
import shutil
import argparse
from collections import Counter
from PIL import Image

CLASS_MAP = {
    "person": 0, "vehicle": 1, "hardhat": 2, "vest": 3,
    "rack": 4, "pallet": 5, "box": 6, "barrel": 7,
    "cone": 8, "pillar": 9, "sign": 10, "fire_extinguisher": 11,
    "cart": 12,
    "hazard_zone_warning": 13, "hazard_zone_restricted": 14, "hazard_zone_critical": 15,
}

ALIAS_MAP = {
    "worker": "person",
    "human": "person",
    "man": "person",
    "woman": "person",
    "forklift": "vehicle",
    "truck": "vehicle",
    "cart_trolley": "cart",
    "trolley": "cart",
    "safety_cone": "cone",
    "traffic_cone": "cone",
    "extinguisher": "fire_extinguisher",
    "fire_ext": "fire_extinguisher",
    "column": "pillar",
    "post": "pillar",
    "rack_shelf": "rack",
    "shelf": "rack",
    "storage_rack": "rack",
    "pallet_box": "box",
    "other": None,
    "wall": None,
    "floor": None,
    "ceiling": None,
    "roof": None,
    "ground": None,
    "light": None,
    "door": None,
    "window": None,
}

REVERSE_CLASS_MAP = {v: k for k, v in CLASS_MAP.items()}


def _resolve_class(raw_name):
    name = raw_name.lower().strip()
    if name in CLASS_MAP:
        return CLASS_MAP[name]
    if name in ALIAS_MAP:
        mapped = ALIAS_MAP[name]
        if mapped is None:
            return -1
        return CLASS_MAP.get(mapped, -1)
    return -1


def _find_annotations(dataset_dir):
    matches = glob.glob(os.path.join(dataset_dir, "coco_annotations_*.json"))
    if not matches:
        matches = glob.glob(os.path.join(dataset_dir, "Replicator", "coco_annotations_*.json"))
    if not matches:
        matches = glob.glob(os.path.join(dataset_dir, "annotations.json"))
    return matches[0] if matches else None


def _find_session_dir(dataset_dir):
    replicator = os.path.join(dataset_dir, "Replicator")
    if os.path.isdir(replicator):
        return replicator
    return dataset_dir


def convert_coco_to_yolo(dataset_dir="/tmp/dataset"):
    annotations_path = _find_annotations(dataset_dir)
    if not annotations_path or not os.path.exists(annotations_path):
        print(f"Warning: No coco_annotations_*.json found in {dataset_dir}. Ensure CocoWriter has written output.")
        return

    session_dir = _find_session_dir(dataset_dir)
    print(f"[INFO] COCO annotations: {annotations_path}")
    print(f"[INFO] Session dir: {session_dir}")

    with open(annotations_path, "r") as f:
        coco_data = json.load(f)

    cat_id_to_name = {cat["id"]: cat["name"] for cat in coco_data.get("categories", [])}
    print(f"[INFO] COCO categories: {cat_id_to_name}")

    images = {img["id"]: img for img in coco_data.get("images", [])}
    annotations = coco_data.get("annotations", [])

    image_annotations = {}
    for ann in annotations:
        img_id = ann["image_id"]
        if img_id not in image_annotations:
            image_annotations[img_id] = []
        image_annotations[img_id].append(ann)

    converted = 0
    total_bboxes = 0
    skipped_bboxes = 0
    skipped_names = Counter()

    for img_id, img_info in images.items():
        file_name = img_info["file_name"]
        img_width = img_info["width"]
        img_height = img_info["height"]

        src_rgb = os.path.join(dataset_dir, file_name)
        if not os.path.exists(src_rgb):
            src_rgb = os.path.join(session_dir, file_name)
        if not os.path.exists(src_rgb):
            print(f"Warning: RGB image not found for {file_name}, skipping.")
            continue

        frame_num = img_id
        dst_name = f"rgb_{frame_num:04d}.png"
        dst_rgb = os.path.join(dataset_dir, dst_name)
        if not os.path.exists(dst_rgb):
            shutil.copy2(src_rgb, dst_rgb)

        txt_path = os.path.join(dataset_dir, f"rgb_{frame_num:04d}.txt")
        anns = image_annotations.get(img_id, [])

        with open(txt_path, "w") as txt_f:
            for ann in anns:
                total_bboxes += 1
                cat_id = ann["category_id"]
                class_name = cat_id_to_name.get(cat_id, "")
                class_id = _resolve_class(class_name)

                if class_id == -1:
                    skipped_bboxes += 1
                    skipped_names[class_name] += 1
                    continue

                x_min, y_min, bbox_w, bbox_h = ann["bbox"]

                x_center = (x_min + bbox_w / 2.0) / img_width
                y_center = (y_min + bbox_h / 2.0) / img_height
                norm_w = bbox_w / img_width
                norm_h = bbox_h / img_height

                txt_f.write(f"{class_id} {x_center:.6f} {y_center:.6f} {norm_w:.6f} {norm_h:.6f}\n")

        converted += 1

    print(f"Successfully converted {converted} frames to YOLO format in {dataset_dir}")
    print(f"  Total bounding boxes: {total_bboxes}, Skipped (unresolved class): {skipped_bboxes}")
    if skipped_names:
        print(f"  Skipped class breakdown:")
        for name, count in skipped_names.most_common():
            print(f"    '{name}': {count}")


def convert_instance_masks(dataset_dir="/tmp/dataset"):
    seg_files = sorted(glob.glob(os.path.join(dataset_dir, "panoptic_*.png")))
    if not seg_files:
        seg_files = sorted(glob.glob(os.path.join(dataset_dir, "Replicator", "panoptic_*.png")))
    if not seg_files:
        print("Warning: No panoptic segmentation files found. Skipping mask conversion.")
        return 0

    print(f"Found {len(seg_files)} panoptic files. Instance mask conversion from panoptic not yet implemented.")
    return len(seg_files)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Convert CocoWriter output to YOLO format.")
    parser.add_argument("--dir", type=str, default="/tmp/dataset", help="Directory containing CocoWriter output.")
    parser.add_argument("--masks", action="store_true", help="Also convert instance segmentation to YOLO mask format.")
    args = parser.parse_args()
    convert_coco_to_yolo(args.dir)
    if args.masks:
        convert_instance_masks(args.dir)