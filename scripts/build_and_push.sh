#!/bin/bash
# Build and push the project Docker image to Docker Hub.
# Run from the project root after fetch_assets.py has populated assets/usd_cache/.
set -e

DOCKER_USER="${DOCKER_USER:-[username]}"
IMAGE_NAME="grad-project"
TAG="${1:-latest}"
FULL_IMAGE="docker.io/$DOCKER_USER/$IMAGE_NAME:$TAG"

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_ROOT"

# Sanity check — make sure assets were fetched
if [ ! -d "assets/usd_cache" ] || [ -z "$(ls -A assets/usd_cache 2>/dev/null)" ]; then
    echo "ERROR: assets/usd_cache is empty."
    echo "Run this first:"
    echo "  /path/to/isaac-sim/python.sh scripts/fetch_assets.py --dest ./assets/usd_cache"
    exit 1
fi

echo "Building $FULL_IMAGE ..."
docker build -t "$FULL_IMAGE" .

echo "Pushing $FULL_IMAGE ..."
docker push "$FULL_IMAGE"

echo ""
echo "Done. Use this image in RunPod:"
echo "  $FULL_IMAGE"
