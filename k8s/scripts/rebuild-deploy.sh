#!/bin/bash
set -euo pipefail

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "${YELLOW}Quick rebuild and redeploy...${NC}\n"

REGISTRY="localhost:32000"
IMAGE_NAME="bomberman-hub"
IMAGE_TAG="latest"
FULL_IMAGE="${REGISTRY}/${IMAGE_NAME}:${IMAGE_TAG}"

# Build
echo "Building..."
docker build -t "${IMAGE_NAME}:${IMAGE_TAG}" -f Dockerfile.hub .
docker tag "${IMAGE_NAME}:${IMAGE_TAG}" "${FULL_IMAGE}"
docker push "${FULL_IMAGE}"

echo "Restarting pods..."
microk8s kubectl rollout restart statefulset/hub -n bomberman

echo "Waiting for rollout..."
microk8s kubectl rollout status statefulset/hub -n bomberman --timeout=300s

echo -e "${GREEN} Done!${NC}\n"
microk8s kubectl get pods -n bomberman