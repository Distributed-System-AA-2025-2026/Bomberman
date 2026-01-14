#!/bin/bash
set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "${YELLOW}Cleaning up Bomberman deployment...${NC}\n"

# Elimina namespace (elimina tutto)
microk8s kubectl delete namespace bomberman --ignore-not-found=true --timeout=60s

echo -e "${GREEN} Cleanup completed${NC}\n"

echo -e "${YELLOW}Microk8s status:${NC}"
microk8s status

echo -e "\n${BLUE}To stop microk8s:${NC}"
echo "  microk8s stop"
echo -e "\n${BLUE}To restart:${NC}"
echo "  microk8s start"