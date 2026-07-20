#!/usr/bin/env bash
set -euo pipefail

# Build and push all custom images for amd64 + arm64, then publish a unified
# multi-arch latest tag for each service.
#
# Usage:
#   ./push_all_images.sh <dockerhub_username> [tag]
#
# Example:
#   ./push_all_images.sh yourdockerhubuser latest

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_ROOT"

DOCKERHUB_USERNAME="${1:-${DOCKERHUB_USERNAME:-anlamntc}}"
IMAGE_TAG="${2:-${IMAGE_TAG:-latest}}"

if [[ -z "$DOCKERHUB_USERNAME" ]]; then
  echo "ERROR: Missing Docker Hub username."
  echo "Usage: ./push_all_images.sh <dockerhub_username> [tag]"
  exit 1
fi

if ! command -v docker >/dev/null 2>&1; then
  echo "ERROR: Docker CLI is not installed."
  exit 1
fi

# Ensure buildx builder exists and is selected.
BUILDER_NAME="rag-chatbot-multiarch-builder"
if ! docker buildx inspect "$BUILDER_NAME" >/dev/null 2>&1; then
  docker buildx create --name "$BUILDER_NAME" --use
else
  docker buildx use "$BUILDER_NAME"
fi

docker buildx inspect --bootstrap >/dev/null

SERVICES=(
  backend
  frontend
  marker
  bge
  prometheus_collector
  vllm
)

for service in "${SERVICES[@]}"; do
  AMD_DOCKERFILE="docker/rag_chatbot_server_${service}_amd.Dockerfile"
  ARM_DOCKERFILE="docker/rag_chatbot_server_${service}_arm.Dockerfile"

  if [[ ! -f "$AMD_DOCKERFILE" || ! -f "$ARM_DOCKERFILE" ]]; then
    echo "ERROR: Missing Dockerfile for service '$service'"
    echo "  - $AMD_DOCKERFILE"
    echo "  - $ARM_DOCKERFILE"
    exit 1
  fi

  REPO_SUFFIX="$service"
  if [[ "$service" == "prometheus_collector" ]]; then
    REPO_SUFFIX="prometheus-collector"
  fi

  REPO="${DOCKERHUB_USERNAME}/rag-chatbot-server-${REPO_SUFFIX}"
  AMD_TAG="${REPO}:amd64-${IMAGE_TAG}"
  ARM_TAG="${REPO}:arm64-${IMAGE_TAG}"
  LATEST_TAG="${REPO}:${IMAGE_TAG}"

  echo
  echo "=== Building $service (amd64) -> $AMD_TAG ==="
  docker buildx build \
    --platform linux/amd64 \
    -f "$AMD_DOCKERFILE" \
    -t "$AMD_TAG" \
    --push \
    .

  echo "=== Building $service (arm64) -> $ARM_TAG ==="
  docker buildx build \
    --platform linux/arm64 \
    -f "$ARM_DOCKERFILE" \
    -t "$ARM_TAG" \
    --push \
    .

  echo "=== Creating multi-arch manifest -> $LATEST_TAG ==="
  docker buildx imagetools create \
    -t "$LATEST_TAG" \
    "$AMD_TAG" \
    "$ARM_TAG"

  echo "=== Inspect manifest: $LATEST_TAG ==="
  docker buildx imagetools inspect "$LATEST_TAG" >/dev/null
done

echo
echo "Done. Published multi-arch images with tag '$IMAGE_TAG' for all services."
