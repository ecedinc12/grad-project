import os
import glob
import argparse
import yaml

REVERSE_CLASS_MAP = {
    0: "Person", 1: "Vehicle", 2: "Hardhat", 3: "Vest",
    4: "Rack", 5: "Pallet", 6: "Box", 7: "Barrel",
    8: "Cone", 9: "Pillar", 10: "Sign", 11: "FireExtinguisher",
    12: "Cart",
    13: "HazardZoneWarning", 14: "HazardZoneRestricted", 15: "HazardZoneCritical",
}


def gen_yaml(dataset_dir, output_path):
    txt_files = sorted(glob.glob(os.path.join(dataset_dir, "rgb_*.txt")))
    if not txt_files:
        print(f"Warning: No YOLO .txt files found in {dataset_dir}. Ensure coco_to_yolo.py has run.")
        return

    present_ids = set()
    for txt_path in txt_files:
        with open(txt_path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                class_id = int(line.split()[0])
                present_ids.add(class_id)

    present_ids = sorted(present_ids)
    class_names = [REVERSE_CLASS_MAP.get(cid, f"unknown_{cid}") for cid in present_ids]

    images = sorted(glob.glob(os.path.join(dataset_dir, "rgb_*.png")))
    split = int(len(images) * 0.8)
    train_imgs = images[:split]
    val_imgs = images[split:]

    train_list = os.path.join(dataset_dir, "train.txt")
    val_list = os.path.join(dataset_dir, "val.txt")
    open(train_list, "w").write("\n".join(train_imgs))
    open(val_list, "w").write("\n".join(val_imgs))

    data = {
        "path": os.path.abspath(dataset_dir),
        "train": "train.txt",
        "val": "val.txt",
        "nc": len(class_names),
        "names": class_names,
    }
    with open(output_path, "w") as f:
        yaml.dump(data, f, default_flow_style=False)
    print(f"Wrote {output_path}  ({len(train_imgs)} train / {len(val_imgs)} val images, {len(class_names)} classes)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate dataset.yaml for YOLO training.")
    parser.add_argument("--dir", type=str, default="/tmp/dataset", help="Directory containing converted dataset.")
    parser.add_argument("--output", type=str, default="/tmp/dataset/dataset.yaml", help="Output path for dataset.yaml.")
    args = parser.parse_args()
    gen_yaml(args.dir, args.output)
