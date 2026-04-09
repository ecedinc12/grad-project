#!/bin/bash
set -e

DATASET_DIR=${1:-/tmp/dataset}
OUTPUT_FILE=${2:-$DATASET_DIR/output.mp4}
FPS=${3:-30}

echo "========================================"
echo " Generating Video from Dataset"
echo " Directory: $DATASET_DIR"
echo " Output: $OUTPUT_FILE"
echo " FPS: $FPS"
echo "========================================"

if [ ! -d "$DATASET_DIR" ]; then
    echo "Error: Directory $DATASET_DIR not found!"
    exit 1
fi

# Check if there are any png files first
count=$(find "$DATASET_DIR" -maxdepth 1 -name 'rgb_*.png' | wc -l)
if [ "$count" -eq 0 ]; then
    echo "Warning: No rgb_*.png files found in $DATASET_DIR. Skipping video generation."
    exit 0
fi

# Create zero-padded symlinks for reliable ffmpeg sequence input
FRAMES_DIR=$(mktemp -d /tmp/frames_XXXXXX)
trap "rm -rf $FRAMES_DIR" EXIT

i=0
while read f; do
    ln -s "$f" "$FRAMES_DIR/$(printf 'frame_%04d.png' $i)"
    i=$((i + 1))
done < <(find "$DATASET_DIR" -maxdepth 1 -name 'rgb_*.png' | sort -V)

# Use printf-style pattern (ffmpeg's most reliable input mode)
ffmpeg -y -framerate "$FPS" -i "$FRAMES_DIR/frame_%04d.png" \
    -c:v libx264 -pix_fmt yuv420p -movflags +faststart "$OUTPUT_FILE"

echo "========================================"
echo " Video generation complete!"
echo " Result: $OUTPUT_FILE"
echo "========================================"
