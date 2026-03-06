#!/usr/bin/env bash
set -euo pipefail

IMAGE="populi/cocosearch:latest"

v0docker buildx build --platform linux/amd64 --tag populi/cocosearch:latest-amd64 --push .

docker buildx build --platform linux/arm64 --tag populi/cocosearch:latest-arm64 --push .

docker manifest create populi/cocosearch:latest \
  populi/cocosearch:latest-amd64 \
  populi/cocosearch:latest-arm64

docker manifest push --purge populi/cocosearch:latest

echo "Done."
