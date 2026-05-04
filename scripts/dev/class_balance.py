import os
import glob
import argparse

CLASS_NAMES = {
    0: "Person", 1: "Vehicle", 2: "Hardhat", 3: "Vest",
    4: "Rack", 5: "Pallet", 6: "Box", 7: "Barrel",
    8: "Cone", 9: "Pillar", 10: "Sign", 11: "FireExtinguisher",
    12: "Cart",
    13: "HazardZoneWarning", 14: "HazardZoneRestricted", 15: "HazardZoneCritical",
}

UNDERREPRESENTED_THRESHOLD = 0.01


def report_balance(dataset_dir="/tmp/dataset"):
    txt_files = sorted(glob.glob(os.path.join(dataset_dir, "rgb_*.txt")))
    if not txt_files:
        print(f"Warning: No YOLO .txt files found in {dataset_dir}.")
        return

    counts = {}
    total = 0
    for txt_path in txt_files:
        with open(txt_path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                parts = line.split()
                class_id = int(parts[0])
                counts[class_id] = counts.get(class_id, 0) + 1
                total += 1

    if total == 0:
        print("No bounding boxes found in dataset.")
        return

    print(f"\n{'='*60}")
    print(f"  Class Balance Report  ({len(txt_files)} frames, {total} total bboxes)")
    print(f"{'='*60}")
    print(f"{'Class ID':<10} {'Class Name':<25} {'Count':<10} {'% of Total':<12} {'Status'}")
    print(f"{'-'*60}")

    warnings = []
    for cid in sorted(counts.keys()):
        name = CLASS_NAMES.get(cid, f"unknown_{cid}")
        count = counts[cid]
        pct = count / total
        status = "OK" if pct >= UNDERREPRESENTED_THRESHOLD else "UNDERREPRESENTED"
        if status == "UNDERREPRESENTED":
            warnings.append(f"  ! {name} (ID {cid}): {pct*100:.2f}% of annotations")
        print(f"{cid:<10} {name:<25} {count:<10} {pct*100:<12.2f} {status}")

    print(f"{'-'*60}")
    print(f"  Total: {total} bounding boxes across {len(counts)} classes")
    print(f"{'='*60}\n")

    if warnings:
        print("UNDERREPRESENTED CLASSES (<1%):")
        for w in warnings:
            print(w)
        print()
    else:
        print("All classes meet minimum representation threshold.\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Report class balance for YOLO dataset.")
    parser.add_argument("--dir", type=str, default="/tmp/dataset", help="Directory containing YOLO .txt files.")
    args = parser.parse_args()
    report_balance(args.dir)
