"""
Annotate video frames with worker bounding boxes and labels.

Reads COCO annotations from the dataset directory, draws green bounding
boxes with green labels on person/worker detections, and encodes the
result as output_annotated.mp4.
"""

import os
import sys
import json
import glob
import argparse
import subprocess
import tempfile
import shutil
from PIL import Image, ImageDraw, ImageFont

PERSON_CATEGORY_KEYWORDS = {"person"}
HAZARD_CATEGORY_KEYWORDS = {"hazard_zone_warning", "hazard_zone_restricted", "hazard_zone_critical"}

# Color definitions (RGB for PIL)
BOX_COLOR_PERSON = (0, 180, 0)       # Green
TEXT_COLOR_PERSON = (0, 0, 0)        # Black text on green box

BOX_COLORS_HAZARD = {
    "hazard_zone_warning": (255, 255, 0),     # Yellow
    "hazard_zone_restricted": (255, 165, 0),  # Orange
    "hazard_zone_critical": (255, 0, 0),      # Red
}

TEXT_COLORS_HAZARD = {
    "hazard_zone_warning": (0, 0, 0),         # Black text on yellow box
    "hazard_zone_restricted": (0, 0, 0),      # Black text on orange box
    "hazard_zone_critical": (255, 255, 255),  # White text on red box
}

BOX_WIDTH = 3
FONT_SIZE = 24
LABEL_PADDING = 4


def _find_annotations(dataset_dir):
    matches = sorted(glob.glob(os.path.join(dataset_dir, "coco_annotations_*.json")))
    if not matches:
        alt = os.path.join(dataset_dir, "annotations.json")
        if os.path.isfile(alt):
            return alt
    return matches[-1] if matches else None


def _find_session_dir(dataset_dir):
    replicator = os.path.join(dataset_dir, "Replicator")
    if os.path.isdir(replicator):
        return replicator
    return dataset_dir


def _get_font(size):
    try:
        return ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", size)
    except (OSError, IOError):
        try:
            return ImageFont.truetype("/usr/share/fonts/TTF/DejaVuSans-Bold.ttf", size)
        except (OSError, IOError):
            try:
                return ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", size)
            except (OSError, IOError):
                return ImageFont.load_default()


def _target_category_ids(coco_data):
    target_ids = set()
    for cat in coco_data.get("categories", []):
        name = cat.get("name", "").lower()
        if name in PERSON_CATEGORY_KEYWORDS or name in HAZARD_CATEGORY_KEYWORDS:
            target_ids.add(cat["id"])
    return target_ids


def annotate_video(dataset_dir, output_path, fps=30):
    annotations_path = _find_annotations(dataset_dir)
    if not annotations_path:
        print(f"Error: No COCO annotations found in {dataset_dir}")
        sys.exit(1)

    with open(annotations_path, "r") as f:
        coco_data = json.load(f)

    target_cat_ids = _target_category_ids(coco_data)
    if not target_cat_ids:
        print("Warning: No 'person' or 'hazard_zone' categories found in COCO annotations.")

    cat_id_to_name = {cat["id"]: cat["name"] for cat in coco_data.get("categories", [])}
    images = {img["id"]: img for img in coco_data.get("images", [])}

    image_annotations = {}
    for ann in coco_data.get("annotations", []):
        if ann["category_id"] in target_cat_ids:
            img_id = ann["image_id"]
            if img_id not in image_annotations:
                image_annotations[img_id] = []
            image_annotations[img_id].append(ann)

    session_dir = _find_session_dir(dataset_dir)
    font = _get_font(FONT_SIZE)

    frames_dir = tempfile.mkdtemp(prefix="annotated_frames_")
    try:
        sorted_img_ids = sorted(images.keys())
        total = len(sorted_img_ids)
        annotated_count = 0
        # ffmpeg frame_%04d.png needs contiguous names from 0000 when some COCO rows lack files
        out_idx = 0

        for idx, img_id in enumerate(sorted_img_ids):
            img_info = images[img_id]
            file_name = img_info.get("file_name", "")
            rgb_path = os.path.join(dataset_dir, file_name)
            if not os.path.exists(rgb_path):
                rgb_path = os.path.join(session_dir, file_name)
            if not os.path.exists(rgb_path):
                rgb_path = os.path.join(dataset_dir, f"rgb_{img_id:04d}.png")

            if not os.path.exists(rgb_path):
                continue

            img = Image.open(rgb_path).convert("RGB")
            draw = ImageDraw.Draw(img)

            anns = image_annotations.get(img_id, [])
            for ann in anns:
                x_min, y_min, bbox_w, bbox_h = ann["bbox"]
                x_max = x_min + bbox_w
                y_max = y_min + bbox_h

                cat_name = cat_id_to_name.get(ann["category_id"], "person")
                label = cat_name.upper()

                if cat_name in HAZARD_CATEGORY_KEYWORDS:
                    box_color = BOX_COLORS_HAZARD.get(cat_name, (255, 255, 0))
                    text_color = TEXT_COLORS_HAZARD.get(cat_name, (0, 0, 0))
                else:
                    box_color = BOX_COLOR_PERSON
                    text_color = TEXT_COLOR_PERSON

                draw.rectangle(
                    [(x_min, y_min), (x_max, y_max)],
                    outline=box_color,
                    width=BOX_WIDTH,
                )

                text_bbox = draw.textbbox((x_min, y_min), label, font=font)
                text_w = text_bbox[2] - text_bbox[0]
                text_h = text_bbox[3] - text_bbox[1]

                label_y = max(y_min - text_h - 2 * LABEL_PADDING, 0)
                draw.rectangle(
                    [(x_min, label_y), (x_min + text_w + 2 * LABEL_PADDING, label_y + text_h + 2 * LABEL_PADDING)],
                    fill=box_color,
                )
                draw.text(
                    (x_min + LABEL_PADDING, label_y + LABEL_PADDING),
                    label,
                    fill=text_color,
                    font=font,
                )

                annotated_count += 1

            frame_path = os.path.join(frames_dir, f"frame_{out_idx:04d}.png")
            img.save(frame_path)
            out_idx += 1

            if out_idx % 50 == 0 or idx == total - 1:
                print(f"  Annotated {out_idx} saved / {idx + 1} scanned (COCO images: {total})...")

        print(f"Annotated {annotated_count} bounding boxes (workers/zones) across {total} frames.")

        num_frames = len(glob.glob(os.path.join(frames_dir, "frame_*.png")))
        if num_frames < 2:
            print("Error: Need at least 2 annotated frames to create a video.")
            sys.exit(1)

        print(f"Encoding {num_frames} annotated frames to {output_path}...")
        cmd = [
            "ffmpeg", "-y",
            "-framerate", str(fps),
            "-i", os.path.join(frames_dir, "frame_%04d.png"),
            "-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2",
            "-r", str(fps),
            "-c:v", "libx264",
            "-pix_fmt", "yuv420p",
            "-preset", "medium",
            "-crf", "23",
            "-movflags", "+faststart",
            output_path,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            print(f"ffmpeg error:\n{result.stderr}")
            sys.exit(1)

        print(f"Annotated video saved to {output_path}")

    finally:
        shutil.rmtree(frames_dir, ignore_errors=True)


def main():
    parser = argparse.ArgumentParser(description="Annotate video frames with worker bounding boxes.")
    parser.add_argument("--dir", type=str, default="/tmp/dataset", help="Dataset directory containing COCO annotations and RGB frames.")
    parser.add_argument("--output", type=str, default=None, help="Output MP4 path (default: <dir>/output_annotated.mp4)")
    parser.add_argument("--fps", type=int, default=30, help="Output framerate.")
    args = parser.parse_args()

    output = args.output or os.path.join(args.dir, "output_annotated.mp4")
    annotate_video(args.dir, output, fps=args.fps)


if __name__ == "__main__":
    main()