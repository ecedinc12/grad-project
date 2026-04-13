import json
import os
import glob
import argparse
import numpy as np
from PIL import Image

CLASS_MAP = {
    "person": 0, "vehicle": 1, "hardhat": 2, "vest": 3,
    "rack": 4, "pallet": 5, "box": 6, "barrel": 7,
    "cone": 8, "pillar": 9, "sign": 10, "fire_extinguisher": 11,
    "cart": 12,
    "hazard_zone_warning": 13, "hazard_zone_restricted": 14, "hazard_zone_critical": 15,
}

REVERSE_CLASS_MAP = {v: k for k, v in CLASS_MAP.items()}


def _coco_categories_to_id_map(categories):
    return {cat["id"]: cat["name"] for cat in categories}


def convert_coco_to_yolo(dataset_dir="/tmp/dataset"):
    annotations_path = os.path.join(dataset_dir, "annotations.json")

    if not os.path.exists(annotations_path):
        print(f"Warning: No annotations.json found in {dataset_dir}. Ensure CocoWriter has written output.")
        return

    with open(annotations_path, "r") as f:
        coco_data = json.load(f)

    cat_id_to_name = _coco_categories_to_id_map(coco_data.get("categories", []))
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

    for img_id, img_info in images.items():
        file_name = img_info["file_name"]
        img_width = img_info["width"]
        img_height = img_info["height"]

        frame_str = os.path.splitext(file_name)[0]

        rgb_path = os.path.join(dataset_dir, file_name)
        if not os.path.exists(rgb_path):
            print(f"Warning: RGB image not found for frame {frame_str}, skipping.")
            continue

        txt_path = os.path.join(dataset_dir, f"{frame_str}.txt")
        anns = image_annotations.get(img_id, [])

        with open(txt_path, "w") as txt_f:
            for ann in anns:
                total_bboxes += 1
                cat_id = ann["category_id"]
                class_name = cat_id_to_name.get(cat_id, "")
                class_id = CLASS_MAP.get(class_name.lower(), -1)

                if class_id == -1:
                    skipped_bboxes += 1
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


def convert_instance_masks(dataset_dir="/tmp/dataset"):
    seg_files = sorted(glob.glob(os.path.join(dataset_dir, "instance_segmentation_*.png")))
    if not seg_files:
        print("Warning: No instance segmentation files found. Skipping mask conversion.")
        return 0

    colors_json = os.path.join(dataset_dir, "instance_segmentation_colors.json")
    color_to_class_id = _colors_json_to_label_map(colors_json)
    if not color_to_class_id:
        print("Warning: No valid color-to-class mapping found. Skipping mask conversion.")
        return 0

    converted = 0
    for seg_path in seg_files:
        basename = os.path.splitext(os.path.basename(seg_path))[0]
        frame_str = basename.split("_")[-1]

        rgb_path = os.path.join(dataset_dir, f"rgb_{frame_str}.png")
        if not os.path.exists(rgb_path):
            continue

        with Image.open(rgb_path) as img:
            img_width, img_height = img.size

        seg_img = Image.open(seg_path).convert("RGB")
        seg_array = np.array(seg_img)

        mask_dir = os.path.join(dataset_dir, "masks")
        os.makedirs(mask_dir, exist_ok=True)

        mask_txt = os.path.join(mask_dir, f"rgb_{frame_str}.txt")

        found_instances = {}
        for color, class_id in color_to_class_id.items():
            match = (seg_array[:, :, 0] == color[0]) & \
                    (seg_array[:, :, 1] == color[1]) & \
                    (seg_array[:, :, 2] == color[2])
            if np.any(match):
                found_instances[class_id] = match

        if not found_instances:
            converted += 1
            continue

        with open(mask_txt, "w") as f:
            for class_id, match in found_instances.items():
                class_name = REVERSE_CLASS_MAP[class_id]
                mask_filename = f"{class_name}_{class_id:02d}_{frame_str}.png"
                mask_path = os.path.join(mask_dir, mask_filename)

                mask = (match * 255).astype(np.uint8)
                mask_img = Image.fromarray(mask, mode="L")
                mask_img.save(mask_path)

                coords = np.column_stack(np.where(match))
                if len(coords) > 0:
                    y_min, x_min = coords.min(axis=0)
                    y_max, x_max = coords.max(axis=0)
                    x_center = (x_min + x_max) / 2.0 / img_width
                    y_center = (y_min + y_max) / 2.0 / img_height
                    width = (x_max - x_min) / img_width
                    height = (y_max - y_min) / img_height
                    f.write(f"{class_id} {x_center:.6f} {y_center:.6f} {width:.6f} {height:.6f} {mask_filename}\n")

        converted += 1

    print(f"Successfully converted {converted} frames to YOLO instance masks in {dataset_dir}/masks/")
    return converted


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Convert CocoWriter output to YOLO format.")
    parser.add_argument("--dir", type=str, default="/tmp/dataset", help="Directory containing CocoWriter output.")
    parser.add_argument("--masks", action="store_true", help="Also convert instance segmentation to YOLO mask format.")
    args = parser.parse_args()
    convert_coco_to_yolo(args.dir)
    if args.masks:
        convert_instance_masks(args.dir)
