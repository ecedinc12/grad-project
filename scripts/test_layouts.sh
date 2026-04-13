#!/bin/bash
# Test all 9 layout presets + 1 end-to-end LLM test
# Run on RunPod: bash scripts/test_layouts.sh
# Reduce frame count for faster validation (override with env var)

set -euo pipefail

FRAMES=${TEST_FRAMES:-10}
ISAAC_PYTHON="/isaac-sim/python.sh"
CONFIG_DIR="$(dirname "$0")/../configs/test_layouts"
SCRIPT_DIR="$(dirname "$0")"

echo "=========================================="
echo "  Layout Preset Tests (frame_count=$FRAMES)"
echo "=========================================="

# Temporarily patch main.py to use fewer frames for testing
MAIN_FILE="$(dirname "$0")/../isaac_backend/main.py"
ORIGINAL_NUM_FRAMES=$(grep -n 'num_frames = 200' "$MAIN_FILE" | head -1 | cut -d: -f1)

if [ -n "$ORIGINAL_NUM_FRAMES" ]; then
    sed -i "${ORIGINAL_NUM_FRAMES}s/num_frames = 200/num_frames = $FRAMES/" "$MAIN_FILE"
    echo "[SETUP] Patched num_frames to $FRAMES for testing"
fi

cleanup() {
    if [ -n "$ORIGINAL_NUM_FRAMES" ]; then
        sed -i "${ORIGINAL_NUM_FRAMES}s/num_frames = $FRAMES/num_frames = 200/" "$MAIN_FILE"
        echo "[CLEANUP] Restored num_frames to 200"
    fi
}
trap cleanup EXIT

PASS=0
FAIL=0

for config in standard_warehouse narrow_aisle open_floor cross_dock cold_storage loading_dock maintenance_bay storage_yard custom_override; do
    echo ""
    echo "------------------------------------------"
    echo "  TEST: $config"
    echo "------------------------------------------"
    rm -rf /tmp/dataset
    if $ISAAC_PYTHON isaac_backend/main.py --config "$CONFIG_DIR/${config}.json"; then
        FRAME_COUNT=$(ls /tmp/dataset/Replicator/rgb_*.png 2>/dev/null | wc -l)
        echo "[PASS] $config — $FRAME_COUNT frames generated"
        ((PASS++)) || true
    else
        echo "[FAIL] $config — main.py exited with error"
        ((FAIL++)) || true
    fi
done

echo ""
echo "=========================================="
echo "  RESULTS: $PASS passed, $FAIL failed"
echo "=========================================="

# Optional: end-to-end LLM test (requires GEMINI_API_KEY)
if [ -n "${GEMINI_API_KEY:-}" ]; then
    echo ""
    echo "------------------------------------------"
    echo "  E2E LLM TEST: narrow_aisle keyword match"
    echo "------------------------------------------"
    rm -rf /tmp/dataset
    ./scripts/run_pipeline.sh "cramped warehouse with tight aisles, forklift and 1 worker"
    echo "[DONE] E2E LLM test complete — check output above"
else
    echo ""
    echo "[SKIP] E2E LLM test (set GEMINI_API_KEY to enable)"
fi