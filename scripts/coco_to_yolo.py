import os
import glob
import argparse
import numpy as np
from PIL import Image


def convert_npy_to_yolo(dataset_dir="/tmp/dataset"):
    npy_files = sorted(glob.glob(os.path.join(dataset_dir, "bounding_box_2d_tight_*.npy")))

    if not npy_files:
        print(f"Warning: No .npy files found in {dataset_dir}. Ensure BasicWriter has written output.")
        return

    converted = 0
    for npy_path in npy_files:
        basename = os.path.splitext(os.path.basename(npy_path))[0]
        # e.g. bounding_box_2d_tight_0000 -> 0000
        frame_str = basename.split("_")[-1]

        rgb_path = os.path.join(dataset_dir, f"rgb_{frame_str}.png")
        if not os.path.exists(rgb_path):
            print(f"Warning: RGB image not found for frame {frame_str}, skipping.")
            continue

        with Image.open(rgb_path) as img:
            img_width, img_height = img.size

        bboxes = np.load(npy_path, allow_pickle=True)

        txt_path = os.path.join(dataset_dir, f"rgb_{frame_str}.txt")
        with open(txt_path, "w") as txt_f:
            for row in bboxes:
                x_min = float(row["x_min"])
                y_min = float(row["y_min"])
                x_max = float(row["x_max"])
                y_max = float(row["y_max"])
                class_id = int(row["semanticId"])

                x_center = (x_min + x_max) / 2.0 / img_width
                y_center = (y_min + y_max) / 2.0 / img_height
                width = (x_max - x_min) / img_width
                height = (y_max - y_min) / img_height

                txt_f.write(f"{class_id} {x_center:.6f} {y_center:.6f} {width:.6f} {height:.6f}\n")

        converted += 1

    print(f"Successfully converted {converted} frames to YOLO format in {dataset_dir}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Convert BasicWriter numpy bbox output to YOLO format.")
    parser.add_argument("--dir", type=str, default="/tmp/dataset", help="Directory containing BasicWriter output.")
    args = parser.parse_args()
    convert_npy_to_yolo(args.dir)
