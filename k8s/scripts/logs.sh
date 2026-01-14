#!/bin/bash
set -euo pipefail

# Script per visualizzare i logs di tutti i pod hub

BLUE='\033[0;34m'
NC='\033[0m'

POD_NAME=${1:-hub-0}

echo -e "${BLUE}Showing logs for pod: ${POD_NAME}${NC}\n"

microk8s kubectl logs -f ${POD_NAME} -n bomberman