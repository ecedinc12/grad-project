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

# Find all rgb_*.png files, sort them numerically, and cat them into ffmpeg
# We use sort -V to ensure rgb_2.png comes before rgb_10.png
find "$DATASET_DIR" -maxdepth 1 -name 'rgb_*.png' | \
    sort -V | \
    xargs cat | \
    ffmpeg -y -framerate "$FPS" -f image2pipe -vcodec png -i - \
    -c:v libx264 -pix_fmt yuv420p "$OUTPUT_FILE"

echo "========================================"
echo " Video generation complete!"
echo " Result: $OUTPUT_FILE"
echo "========================================"
