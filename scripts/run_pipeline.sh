#!/bin/bash

if [ -z "$1" ]; then
    echo "Usage: ./run_pipeline.sh \"prompt\" [frames] [generate_video] [annotation_format]"
    exit 1
fi

PROMPT=$1
FRAMES=${2:-100}
GENERATE_VIDEO=${3:-true}
ANNOTATION_FORMAT=${4:-both}   # coco | yolo | both

echo "========================================"
echo " Starting Generation Pipeline"
echo " Prompt: $PROMPT"
echo " Frames: $FRAMES"
echo " Video: $GENERATE_VIDEO"
echo " Format: $ANNOTATION_FORMAT"
echo "========================================"

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
FAILED=0

if [ -x "$PROJECT_ROOT/.venv/bin/python" ]; then
    ANNOTATE_PY="$PROJECT_ROOT/.venv/bin/python"
else
    ANNOTATE_PY=python3
fi

FAST_IMPORTER="/isaac-sim/kit/kernel/py/omni/ext/_impl/fast_importer.py"
if [ -f "$FAST_IMPORTER" ]; then
    sed -i 's/for p in spec_default.submodule_search_locations:/for p in (spec_default.submodule_search_locations or []):/' "$FAST_IMPORTER"
    echo "[OK] Patched fast_importer.py"
else
    echo "[WARN] fast_importer.py not found at $FAST_IMPORTER, skipping patch"
fi

echo "[1/9] Running LLM Config Generator..."
python3 "$PROJECT_ROOT/llm_pipeline/generator.py" --prompt "$PROMPT" --output "$PROJECT_ROOT/configs/current_scene.json" --nim-api-key "${NIM_API_KEY:-}"
if [ $? -ne 0 ]; then echo "[ERROR] Step 1 failed"; FAILED=1; fi

echo "[2/9] Cleaning up old dataset..."
rm -rf /tmp/dataset

echo "[3/9] Generating dataset via Isaac Sim..."
/isaac-sim/python.sh "$PROJECT_ROOT/isaac_backend/main.py" \
    --config "$PROJECT_ROOT/configs/current_scene.json" \
    --library "$PROJECT_ROOT/assets/library.json" \
    --frames "$FRAMES"
ISAAC_EXIT=$?
if [ $ISAAC_EXIT -ne 0 ]; then
    echo "[ERROR] Isaac Sim exited with code $ISAAC_EXIT"
    FAILED=1
fi

if [ "$ANNOTATION_FORMAT" != "coco" ]; then
    echo "[4/9] Converting COCO to YOLO..."
    python3 "$PROJECT_ROOT/scripts/coco_to_yolo.py" --dir /tmp/dataset --masks
    if [ $? -ne 0 ]; then echo "[ERROR] Step 4 failed"; FAILED=1; fi
else
    echo "[4/9] Skipping YOLO conversion (format=coco)"
fi

echo "[5/9] Generating dataset.yaml..."
python3 "$PROJECT_ROOT/scripts/gen_dataset_yaml.py" \
    --dir /tmp/dataset \
    --output /tmp/dataset/dataset.yaml
if [ $? -ne 0 ]; then echo "[ERROR] Step 5 failed"; FAILED=1; fi

echo "[6/9] Analyzing class balance..."
python3 "$PROJECT_ROOT/scripts/class_balance.py" --dir /tmp/dataset

if [ "$GENERATE_VIDEO" = "true" ]; then
    echo "[7/9] Generating video from frames..."
    "$PROJECT_ROOT/scripts/make_video.sh" /tmp/dataset /tmp/dataset/output.mp4

    echo "[8/9] Generating annotated video with worker labels..."
    "$ANNOTATE_PY" "$PROJECT_ROOT/scripts/annotate_video.py" --dir /tmp/dataset --output /tmp/dataset/output_annotated.mp4
else
    echo "[7/9] Skipping video generation"
    echo "[8/9] Skipping annotated video generation"
fi

echo "[9/9] Archiving output to persistent storage..."
TIMESTAMP=$(date +%s)
ARCHIVE_NAME="$PROJECT_ROOT/dataset_${TIMESTAMP}.tar.gz"
tar -czf "$ARCHIVE_NAME" -C /tmp dataset/

echo "========================================"
if [ $FAILED -ne 0 ]; then
    echo " Pipeline completed WITH ERRORS"
    echo " Check logs above for details"
else
    echo " Pipeline Complete!"
fi
echo " Output Archive: $ARCHIVE_NAME"
echo "========================================"
