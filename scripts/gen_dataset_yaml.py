import os
import glob
import argparse
import yaml

CLASS_NAMES = ["Person", "Vehicle", "Hardhat", "Vest", "Clutter"]


def gen_yaml(dataset_dir, output_path):
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
        "nc": len(CLASS_NAMES),
        "names": CLASS_NAMES,
    }
    with open(output_path, "w") as f:
        yaml.dump(data, f, default_flow_style=False)
    print(f"Wrote {output_path}  ({len(train_imgs)} train / {len(val_imgs)} val images)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate dataset.yaml for YOLO training.")
    parser.add_argument("--dir", type=str, default="/tmp/dataset", help="Directory containing converted dataset.")
    parser.add_argument("--output", type=str, default="/tmp/dataset/dataset.yaml", help="Output path for dataset.yaml.")
    args = parser.parse_args()
    gen_yaml(args.dir, args.output)
