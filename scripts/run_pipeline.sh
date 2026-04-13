#!/bin/bash
# Exit on any error
set -e

if [ -z "$1" ]; then
    echo "Usage: ./run_pipeline.sh \"Your prompt describing the scene\""
    exit 1
fi

PROMPT=$1

echo "========================================"
echo " Starting Generation Pipeline"
echo " Prompt: $PROMPT"
echo "========================================"

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

# Patch Isaac Sim fast_importer to handle None submodule_search_locations
# https://github.com/NVIDIA-Omniverse/Isaac-Sim/issues/XXX
FAST_IMPORTER="/isaac-sim/kit/kernel/py/omni/ext/_impl/fast_importer.py"
if [ -f "$FAST_IMPORTER" ]; then
    sed -i 's/for p in spec_default.submodule_search_locations:/for p in (spec_default.submodule_search_locations or []):/' "$FAST_IMPORTER"
    echo "[OK] Patched fast_importer.py"
else
    echo "[WARN] fast_importer.py not found at $FAST_IMPORTER, skipping patch"
fi

# Step 1: Generate config from prompt
echo "[1/8] Running LLM Config Generator..."
python3 "$PROJECT_ROOT/llm_pipeline/generator.py" --prompt "$PROMPT" --output "$PROJECT_ROOT/configs/current_scene.json"

# Step 2: Clear old fast-disk data
echo "[2/8] Cleaning up old dataset..."
rm -rf /tmp/dataset

# Step 3: Run Isaac Sim Headless Replicator Generation
echo "[3/8] Generating dataset via Isaac Sim..."
/isaac-sim/python.sh "$PROJECT_ROOT/isaac_backend/main.py" \
    --config "$PROJECT_ROOT/configs/current_scene.json" \
    --library "$PROJECT_ROOT/assets/library.json"

# Step 4: Convert COCO annotations to YOLO format
echo "[4/8] Converting COCO to YOLO..."
python3 "$PROJECT_ROOT/scripts/coco_to_yolo.py" --dir /tmp/dataset --masks

# Step 5: Generate dataset.yaml for YOLO training
echo "[5/8] Generating dataset.yaml..."
python3 "$PROJECT_ROOT/scripts/gen_dataset_yaml.py" \
    --dir /tmp/dataset \
    --output /tmp/dataset/dataset.yaml

# Step 6: Report class balance
echo "[6/8] Analyzing class balance..."
python3 "$PROJECT_ROOT/scripts/class_balance.py" --dir /tmp/dataset

# Step 7: Generate Video
echo "[7/8] Generating video from frames..."
"$PROJECT_ROOT/scripts/make_video.sh" /tmp/dataset /tmp/dataset/output.mp4

# Step 8: Archive and move to persistent storage
TIMESTAMP=$(date +%s)
ARCHIVE_NAME="$PROJECT_ROOT/dataset_${TIMESTAMP}.tar.gz"

echo "[8/8] Archiving output to $ARCHIVE_NAME..."
tar -czf $ARCHIVE_NAME -C /tmp dataset/

echo "========================================"
echo " Pipeline Complete!"
echo " Output Archive: $ARCHIVE_NAME"
echo "========================================"
