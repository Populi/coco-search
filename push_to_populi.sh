#!/usr/bin/env bash
set -euo pipefail

IMAGE="populi/cocosearch:latest"

echo "Building app service..."
docker compose build app

echo "Tagging as $IMAGE..."
docker tag docker.io/library/coco-search-app  "$IMAGE"

echo "Pushing $IMAGE..."
docker push "$IMAGE"

echo "Done."
