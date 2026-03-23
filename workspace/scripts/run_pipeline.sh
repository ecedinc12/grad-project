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

# Step 1: Generate config from prompt
echo "[1/5] Running LLM Config Generator..."
python3 /workspace/llm_pipeline/generator.py --prompt "$PROMPT"

# Step 2: Clear old fast-disk data
echo "[2/5] Cleaning up old dataset..."
rm -rf /tmp/dataset

# Step 3: Run Isaac Sim Headless Replicator Generation
echo "[3/5] Generating dataset via Isaac Sim..."
/isaac-sim/python.sh /workspace/isaac_backend/main.py

# Step 4: Convert COCO annotations to YOLO format
echo "[4/5] Converting COCO to YOLO..."
python3 /workspace/scripts/coco_to_yolo.py --dir /tmp/dataset

# Step 5: Archive and move to persistent storage
TIMESTAMP=$(date +%s)
ARCHIVE_NAME="/workspace/dataset_${TIMESTAMP}.tar.gz"

echo "[5/5] Archiving output to $ARCHIVE_NAME..."
tar -czf $ARCHIVE_NAME -C /tmp dataset/

echo "========================================"
echo " Pipeline Complete!"
echo " Output Archive: $ARCHIVE_NAME"
echo "========================================"
