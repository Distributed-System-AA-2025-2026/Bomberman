#!/bin/bash
set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

echo -e "${YELLOW}Cleaning up Bomberman deployment...${NC}\n"

# Elimina namespace (elimina tutto)
if microk8s kubectl get namespace bomberman &>/dev/null; then
    echo -e "${YELLOW}Deleting namespace...${NC}"
    microk8s kubectl delete namespace bomberman --timeout=60s
    echo -e "${GREEN}[OK] Namespace deleted${NC}\n"
else
    echo -e "${YELLOW}[INFO] Namespace 'bomberman' not found${NC}\n"
fi

# Opzionale: rimuovi anche l'immagine da microk8s
read -p "Remove Docker image from microk8s? (y/N) " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    echo -e "${YELLOW}Removing image...${NC}"
    microk8s ctr images rm docker.io/library/bomberman-hub:latest || true
    echo -e "${GREEN}[OK] Image removed${NC}\n"
fi

echo -e "${GREEN}[OK] Cleanup completed${NC}\n"

echo -e "${BLUE}Microk8s status:${NC}"
microk8s status

echo -e "\n${YELLOW}To stop microk8s:${NC}"
echo "  microk8s stop"
echo -e "\n${YELLOW}To restart:${NC}"
echo "  microk8s start"