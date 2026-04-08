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

# Step 1: Generate config from prompt
echo "[1/6] Running LLM Config Generator..."
python3 "$PROJECT_ROOT/llm_pipeline/generator.py" --prompt "$PROMPT" --output "$PROJECT_ROOT/configs/current_scene.json"

# Step 2: Clear old fast-disk data
echo "[2/6] Cleaning up old dataset..."
rm -rf /tmp/dataset

# Step 3: Run Isaac Sim Headless Replicator Generation
echo "[3/6] Generating dataset via Isaac Sim..."
/isaac-sim/python.sh "$PROJECT_ROOT/isaac_backend/main.py" --config "$PROJECT_ROOT/configs/current_scene.json" --library "$PROJECT_ROOT/assets/library.json"

# Step 4: Convert COCO annotations to YOLO format
echo "[4/6] Converting COCO to YOLO..."
python3 "$PROJECT_ROOT/scripts/coco_to_yolo.py" --dir /tmp/dataset

# Step 5: Generate dataset.yaml for YOLO training
echo "[5/6] Generating dataset.yaml..."
python3 "$PROJECT_ROOT/scripts/gen_dataset_yaml.py" \
    --dir /tmp/dataset \
    --output /tmp/dataset/dataset.yaml

# Step 6: Generate Video
echo "[6/7] Generating video from frames..."
"$PROJECT_ROOT/scripts/make_video.sh" /tmp/dataset /tmp/dataset/output.mp4

# Step 7: Archive and move to persistent storage
TIMESTAMP=$(date +%s)
ARCHIVE_NAME="$PROJECT_ROOT/dataset_${TIMESTAMP}.tar.gz"

echo "[7/7] Archiving output to $ARCHIVE_NAME..."
tar -czf $ARCHIVE_NAME -C /tmp dataset/

echo "========================================"
echo " Pipeline Complete!"
echo " Output Archive: $ARCHIVE_NAME"
echo "========================================"
