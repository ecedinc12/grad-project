"""
Annotate video frames with COCO bounding boxes and labels.

Reads COCO annotations from the dataset directory, draws class-colored
bounding boxes (translucent fills for hazard zones), and pipes frames
directly to ffmpeg as output_annotated.mp4.
"""

import os
import re
import sys
import json
import glob
import argparse
import subprocess
import multiprocessing as mp
from functools import partial
from PIL import Image, ImageDraw, ImageFont

PERSON_KEYWORDS = {"person"}
HAZARD_KEYWORDS = {"hazard_zone_warning", "hazard_zone_restricted", "hazard_zone_critical"}
PPE_KEYWORDS = {"hardhat", "vest"}
VEHICLE_KEYWORDS = {"vehicle", "cart"}

DEFAULT_CLASS_COLORS = {
    "person":                  (0, 180, 0),
    "vehicle":                 (255, 105, 180),
    "cart":                    (160, 82, 45),
    "hardhat":                 (255, 255, 0),
    "vest":                    (0, 255, 127),
    "rack":                    (139, 69, 19),
    "pallet":                  (210, 180, 140),
    "box":                     (188, 143, 143),
    "barrel":                  (128, 0, 128),
    "cone":                    (255, 140, 0),
    "fire_extinguisher":       (255, 0, 0),
    "sign":                    (255, 255, 0),
    "pillar":                  (169, 169, 169),
    "hazard_zone_warning":     (255, 255, 0),
    "hazard_zone_restricted":  (255, 165, 0),
    "hazard_zone_critical":    (255, 0, 0),
}

HAZARD_FILL_ALPHA = 64

LABEL_PADDING_RATIO = 0.0025
DEFAULT_FONT_DIVISOR = 40
DEFAULT_BOX_DIVISOR = 360
MIN_FONT = 14
MIN_BOX_W = 2
MIN_AREA_PX = 16
DROP_LOG_LIMIT = 10
MISSING_FRAME_THRESHOLD = 0.10


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
    candidates = (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
    )
    for path in candidates:
        try:
            return ImageFont.truetype(path, size)
        except (OSError, IOError):
            continue
    return ImageFont.load_default()


def _filter_categories(coco_data, requested):
    target_ids = set()
    for cat in coco_data.get("categories", []):
        name = cat.get("name", "").lower()
        if requested == "all" or name in requested:
            target_ids.add(cat["id"])
    return target_ids


def _resolve_classes(arg):
    if not arg or arg.strip().lower() == "all":
        return "all"
    return {c.strip().lower() for c in arg.split(",") if c.strip()}


def _file_name_sort_key(name):
    digits = re.findall(r"\d+", name or "")
    return (int(digits[-1]) if digits else 0, name or "")


def _resolve_frame_path(dataset_dir, session_dir, file_name, img_id):
    for candidate in (
        os.path.join(dataset_dir, file_name) if file_name else None,
        os.path.join(session_dir, file_name) if file_name else None,
        os.path.join(dataset_dir, f"rgb_{img_id:04d}.png"),
        os.path.join(session_dir, f"rgb_{img_id:04d}.png"),
    ):
        if candidate and os.path.exists(candidate):
            return candidate
    return None


def _color_for(cat_name):
    return DEFAULT_CLASS_COLORS.get(cat_name, (0, 200, 255))


def _text_color_for(box_color):
    r, g, b = box_color
    luminance = 0.299 * r + 0.587 * g + 0.114 * b
    return (0, 0, 0) if luminance > 140 else (255, 255, 255)


def _render_frame(args):
    (
        rgb_path,
        anns,
        cat_id_to_name,
        out_path,
        frame_idx,
        total_frames,
        show_hud,
    ) = args

    img = Image.open(rgb_path).convert("RGBA")
    W, H = img.size

    font_size = max(MIN_FONT, H // DEFAULT_FONT_DIVISOR)
    box_w = max(MIN_BOX_W, H // DEFAULT_BOX_DIVISOR)
    pad = max(2, int(H * LABEL_PADDING_RATIO))
    font = _get_font(font_size)

    overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    odraw = ImageDraw.Draw(overlay, "RGBA")
    base_draw = ImageDraw.Draw(img, "RGBA")

    drawn = 0
    for ann in anns:
        x_min, y_min, bbox_w, bbox_h = ann["bbox"]
        if bbox_w * bbox_h < MIN_AREA_PX:
            continue
        x_max = x_min + bbox_w
        y_max = y_min + bbox_h

        cat_name = cat_id_to_name.get(ann["category_id"], "unknown")
        score = ann.get("score")
        label = cat_name.upper() if score is None else f"{cat_name.upper()} {score:.2f}"

        box_color = _color_for(cat_name)
        text_color = _text_color_for(box_color)
        is_hazard = cat_name in HAZARD_KEYWORDS

        if is_hazard:
            odraw.rectangle(
                [(x_min, y_min), (x_max, y_max)],
                fill=(*box_color, HAZARD_FILL_ALPHA),
                outline=(*box_color, 255),
                width=box_w,
            )
        else:
            base_draw.rectangle(
                [(x_min, y_min), (x_max, y_max)],
                outline=box_color,
                width=box_w,
            )

        text_bbox = base_draw.textbbox((0, 0), label, font=font)
        text_w = text_bbox[2] - text_bbox[0]
        text_h = text_bbox[3] - text_bbox[1]

        label_w = text_w + 2 * pad
        label_h = text_h + 2 * pad
        label_x = max(0, min(int(x_min), W - label_w))
        label_y = int(y_min) - label_h - 2
        if label_y < 0:
            label_y = min(int(y_min) + box_w, H - label_h)

        base_draw.rectangle(
            [(label_x, label_y), (label_x + label_w, label_y + label_h)],
            fill=box_color,
        )
        base_draw.text(
            (label_x + pad, label_y + pad - text_bbox[1]),
            label,
            fill=text_color,
            font=font,
        )
        drawn += 1

    composed = Image.alpha_composite(img, overlay).convert("RGB")

    if show_hud:
        hud_draw = ImageDraw.Draw(composed)
        hud = f"frame {frame_idx + 1}/{total_frames}  dets {drawn}"
        hb = hud_draw.textbbox((0, 0), hud, font=font)
        hud_draw.rectangle(
            [(0, 0), (hb[2] - hb[0] + 2 * pad, hb[3] - hb[1] + 2 * pad)],
            fill=(0, 0, 0),
        )
        hud_draw.text((pad, pad - hb[1]), hud, fill=(255, 255, 255), font=font)

    composed.save(out_path, format="PNG", compress_level=1)
    return drawn


def _render_for_pipe(args):
    drawn = _render_frame(args)
    return args[3], drawn  # out_path, count


def annotate_video(
    dataset_dir,
    output_path,
    fps=30,
    classes="all",
    show_hud=False,
    workers=None,
    pipe=True,
):
    annotations_path = _find_annotations(dataset_dir)
    if not annotations_path:
        print(f"Error: No COCO annotations found in {dataset_dir}")
        sys.exit(1)

    with open(annotations_path, "r") as f:
        coco_data = json.load(f)

    requested = _resolve_classes(classes)
    target_cat_ids = _filter_categories(coco_data, requested)
    if not target_cat_ids:
        print(f"Warning: No categories match filter '{classes}'.")

    cat_id_to_name = {cat["id"]: cat["name"] for cat in coco_data.get("categories", [])}
    images = {img["id"]: img for img in coco_data.get("images", [])}

    image_annotations = {}
    for ann in coco_data.get("annotations", []):
        if ann["category_id"] in target_cat_ids:
            image_annotations.setdefault(ann["image_id"], []).append(ann)

    session_dir = _find_session_dir(dataset_dir)

    sorted_img_ids = sorted(
        images.keys(),
        key=lambda i: _file_name_sort_key(images[i].get("file_name", "")),
    )
    total = len(sorted_img_ids)
    if total < 2:
        print(f"Error: Need at least 2 images in COCO; found {total}.")
        sys.exit(1)

    resolved = []
    dropped = []
    for img_id in sorted_img_ids:
        info = images[img_id]
        path = _resolve_frame_path(dataset_dir, session_dir, info.get("file_name", ""), img_id)
        if path is None:
            dropped.append((img_id, info.get("file_name", "")))
            continue
        resolved.append((img_id, path))

    if dropped:
        print(f"Warning: {len(dropped)} of {total} frames missing on disk.")
        for img_id, fname in dropped[:DROP_LOG_LIMIT]:
            print(f"  dropped image_id={img_id} file_name={fname!r}")
        if len(dropped) > DROP_LOG_LIMIT:
            print(f"  ... {len(dropped) - DROP_LOG_LIMIT} more")
        if len(dropped) / max(total, 1) > MISSING_FRAME_THRESHOLD:
            print(
                f"Error: dropped fraction {len(dropped)/total:.2%} exceeds "
                f"{MISSING_FRAME_THRESHOLD:.0%}; refusing to encode."
            )
            sys.exit(1)

    if len(resolved) < 2:
        print("Error: Need at least 2 resolvable frames.")
        sys.exit(1)

    workers = workers or max(1, (os.cpu_count() or 2) - 1)

    if pipe:
        return _encode_via_pipe(
            resolved, image_annotations, cat_id_to_name,
            output_path, fps, show_hud, workers,
        )
    return _encode_via_tempdir(
        resolved, image_annotations, cat_id_to_name,
        output_path, fps, show_hud, workers,
    )


def _encode_via_pipe(resolved, image_annotations, cat_id_to_name,
                     output_path, fps, show_hud, workers):
    cmd = [
        "ffmpeg", "-y",
        "-f", "image2pipe",
        "-framerate", str(fps),
        "-i", "-",
        "-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2",
        "-r", str(fps),
        "-c:v", "libx264",
        "-pix_fmt", "yuv420p",
        "-preset", "medium",
        "-crf", "23",
        "-movflags", "+faststart",
        output_path,
    ]
    print(f"Encoding {len(resolved)} frames via stdin pipe to {output_path}...")
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE)

    total_frames = len(resolved)
    total_drawn = 0
    try:
        with mp.Pool(processes=workers) as pool:
            tasks = (
                _build_render_args(
                    rgb_path, image_annotations.get(img_id, []),
                    cat_id_to_name, None, idx, total_frames, show_hud,
                )
                for idx, (img_id, rgb_path) in enumerate(resolved)
            )
            for idx, drawn_count in enumerate(pool.imap(_render_to_bytes, tasks, chunksize=4)):
                buf, count = drawn_count
                proc.stdin.write(buf)
                total_drawn += count
                if (idx + 1) % 50 == 0 or idx == total_frames - 1:
                    print(f"  Encoded {idx + 1}/{total_frames}")
        proc.stdin.close()
    except BrokenPipeError:
        pass

    rc = proc.wait()
    if rc != 0:
        err = proc.stderr.read().decode("utf-8", "replace")
        print(f"ffmpeg error:\n{err}")
        sys.exit(1)
    print(f"Annotated {total_drawn} bboxes across {total_frames} frames.")
    print(f"Annotated video saved to {output_path}")


def _encode_via_tempdir(resolved, image_annotations, cat_id_to_name,
                        output_path, fps, show_hud, workers):
    import tempfile
    import shutil

    frames_dir = tempfile.mkdtemp(prefix="annotated_frames_")
    total_frames = len(resolved)
    try:
        tasks = []
        for out_idx, (img_id, rgb_path) in enumerate(resolved):
            out_path = os.path.join(frames_dir, f"frame_{out_idx:06d}.png")
            tasks.append(_build_render_args(
                rgb_path, image_annotations.get(img_id, []),
                cat_id_to_name, out_path, out_idx, total_frames, show_hud,
            ))

        total_drawn = 0
        with mp.Pool(processes=workers) as pool:
            for idx, (out_path, count) in enumerate(pool.imap(_render_for_pipe, tasks, chunksize=4)):
                total_drawn += count
                if (idx + 1) % 50 == 0 or idx == total_frames - 1:
                    print(f"  Rendered {idx + 1}/{total_frames}")

        cmd = [
            "ffmpeg", "-y",
            "-framerate", str(fps),
            "-i", os.path.join(frames_dir, "frame_%06d.png"),
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
        print(f"Annotated {total_drawn} bboxes across {total_frames} frames.")
        print(f"Annotated video saved to {output_path}")
    finally:
        shutil.rmtree(frames_dir, ignore_errors=True)


def _build_render_args(rgb_path, anns, cat_id_to_name, out_path, idx, total, show_hud):
    return (rgb_path, anns, cat_id_to_name, out_path, idx, total, show_hud)


def _render_to_bytes(args):
    import io
    rgb_path, anns, cat_id_to_name, _out, idx, total, show_hud = args
    new_args = (rgb_path, anns, cat_id_to_name, None, idx, total, show_hud)
    img_buf = io.BytesIO()
    drawn = _render_into_buffer(new_args, img_buf)
    return img_buf.getvalue(), drawn


def _render_into_buffer(args, buf):
    rgb_path, anns, cat_id_to_name, _out, idx, total, show_hud = args

    img = Image.open(rgb_path).convert("RGBA")
    W, H = img.size
    font_size = max(MIN_FONT, H // DEFAULT_FONT_DIVISOR)
    box_w = max(MIN_BOX_W, H // DEFAULT_BOX_DIVISOR)
    pad = max(2, int(H * LABEL_PADDING_RATIO))
    font = _get_font(font_size)

    overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    odraw = ImageDraw.Draw(overlay, "RGBA")
    base_draw = ImageDraw.Draw(img, "RGBA")

    drawn = 0
    for ann in anns:
        x_min, y_min, bbox_w, bbox_h = ann["bbox"]
        if bbox_w * bbox_h < MIN_AREA_PX:
            continue
        x_max = x_min + bbox_w
        y_max = y_min + bbox_h
        cat_name = cat_id_to_name.get(ann["category_id"], "unknown")
        score = ann.get("score")
        label = cat_name.upper() if score is None else f"{cat_name.upper()} {score:.2f}"
        box_color = _color_for(cat_name)
        text_color = _text_color_for(box_color)

        if cat_name in HAZARD_KEYWORDS:
            odraw.rectangle(
                [(x_min, y_min), (x_max, y_max)],
                fill=(*box_color, HAZARD_FILL_ALPHA),
                outline=(*box_color, 255),
                width=box_w,
            )
        else:
            base_draw.rectangle(
                [(x_min, y_min), (x_max, y_max)],
                outline=box_color,
                width=box_w,
            )

        text_bbox = base_draw.textbbox((0, 0), label, font=font)
        text_w = text_bbox[2] - text_bbox[0]
        text_h = text_bbox[3] - text_bbox[1]
        label_w = text_w + 2 * pad
        label_h = text_h + 2 * pad
        label_x = max(0, min(int(x_min), W - label_w))
        label_y = int(y_min) - label_h - 2
        if label_y < 0:
            label_y = min(int(y_min) + box_w, H - label_h)

        base_draw.rectangle(
            [(label_x, label_y), (label_x + label_w, label_y + label_h)],
            fill=box_color,
        )
        base_draw.text(
            (label_x + pad, label_y + pad - text_bbox[1]),
            label,
            fill=text_color,
            font=font,
        )
        drawn += 1

    composed = Image.alpha_composite(img, overlay).convert("RGB")

    if show_hud:
        hud_draw = ImageDraw.Draw(composed)
        hud = f"frame {idx + 1}/{total}  dets {drawn}"
        hb = hud_draw.textbbox((0, 0), hud, font=font)
        hud_draw.rectangle(
            [(0, 0), (hb[2] - hb[0] + 2 * pad, hb[3] - hb[1] + 2 * pad)],
            fill=(0, 0, 0),
        )
        hud_draw.text((pad, pad - hb[1]), hud, fill=(255, 255, 255), font=font)

    composed.save(buf, format="PNG", compress_level=1)
    return drawn


def main():
    parser = argparse.ArgumentParser(description="Annotate video frames with COCO bounding boxes.")
    parser.add_argument("--dir", type=str, default="/tmp/dataset",
                        help="Dataset directory containing COCO annotations and RGB frames.")
    parser.add_argument("--output", type=str, default=None,
                        help="Output MP4 path (default: <dir>/output_annotated.mp4)")
    parser.add_argument("--fps", type=int, default=30, help="Output framerate.")
    parser.add_argument("--classes", type=str, default="person,hazard_zone_warning,hazard_zone_restricted,hazard_zone_critical,hardhat,vest,vehicle,cart",
                        help="Comma-separated category names, or 'all'.")
    parser.add_argument("--hud", action="store_true", help="Draw frame counter and detection count.")
    parser.add_argument("--workers", type=int, default=None, help="Parallel render workers.")
    parser.add_argument("--no-pipe", action="store_true",
                        help="Write PNG temp files instead of piping to ffmpeg.")
    args = parser.parse_args()

    output = args.output or os.path.join(args.dir, "output_annotated.mp4")
    annotate_video(
        args.dir, output,
        fps=args.fps,
        classes=args.classes,
        show_hud=args.hud,
        workers=args.workers,
        pipe=not args.no_pipe,
    )


if __name__ == "__main__":
    main()
