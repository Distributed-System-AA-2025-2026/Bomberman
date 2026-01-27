#!/bin/bash
set -euo pipefail

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

echo -e "${YELLOW}Quick rebuild and redeploy...${NC}\n"

IMAGE_NAME="bomberman-hub"
IMAGE_TAG="latest"

# Build
echo -e "${YELLOW}1. Building image...${NC}"
docker build -t "${IMAGE_NAME}:${IMAGE_TAG}" -f docker/Dockerfile.hub .

if [ $? -ne 0 ]; then
    echo -e "${RED}[ERROR] Build failed${NC}"
    exit 1
fi

# Import to microk8s
echo -e "${YELLOW}2. Importing to microk8s...${NC}"
docker save "${IMAGE_NAME}:${IMAGE_TAG}" | microk8s ctr image import -

if [ $? -ne 0 ]; then
    echo -e "${RED}[ERROR] Import failed${NC}"
    exit 1
fi

# Restart pods
echo -e "${YELLOW}3. Restarting pods...${NC}"
microk8s kubectl rollout restart statefulset/hub -n bomberman

# Wait
echo -e "${YELLOW}4. Waiting for rollout...${NC}"
microk8s kubectl rollout status statefulset/hub -n bomberman --timeout=300s

echo -e "\n${GREEN}[OK] Done!${NC}\n"
microk8s kubectl get pods -n bomberman