#!/bin/bash
set -euo pipefail

# Colori
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

echo -e "${GREEN}╔════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║   Bomberman Hub - Microk8s Deployment     ║${NC}"
echo -e "${GREEN}╚════════════════════════════════════════════╝${NC}\n"

# Verifica microk8s
if ! command -v microk8s &> /dev/null; then
    echo -e "${RED} Microk8s non installato${NC}"
    echo "Installalo con: sudo snap install microk8s --classic"
    exit 1
fi

if ! microk8s status --wait-ready &> /dev/null; then
    echo -e "${RED} Microk8s non è running${NC}"
    echo "Avvialo con: microk8s start"
    exit 1
fi

echo -e "${GREEN} Microk8s ready${NC}\n"

# Setup alias
alias kubectl='microk8s kubectl'

# Variabili
REGISTRY="localhost:32000"
IMAGE_NAME="bomberman-hub"
IMAGE_TAG="latest"
FULL_IMAGE="${REGISTRY}/${IMAGE_NAME}:${IMAGE_TAG}"

echo -e "${YELLOW}━━━ Step 1: Building Docker image ━━━${NC}"
echo -e "${BLUE}Image: ${FULL_IMAGE}${NC}\n"

# Build immagine
docker build -t "${IMAGE_NAME}:${IMAGE_TAG}" -f docker/Dockerfile.hub .

# Tag per registry locale microk8s
docker tag "${IMAGE_NAME}:${IMAGE_TAG}" "${FULL_IMAGE}"

# Push al registry locale
echo -e "\n${YELLOW}Pushing to microk8s registry...${NC}"
docker push "${FULL_IMAGE}"

echo -e "${GREEN} Image built and pushed${NC}\n"

echo -e "${YELLOW}━━━ Step 2: Creating namespace ━━━${NC}"
microk8s kubectl apply -f k8s/base/namespace.yaml
echo -e "${GREEN} Namespace created${NC}\n"

echo -e "${YELLOW}━━━ Step 3: Applying ConfigMap ━━━${NC}"
microk8s kubectl apply -f k8s/base/hub/configmap.yaml
echo -e "${GREEN} ConfigMap applied${NC}\n"

echo -e "${YELLOW}━━━ Step 4: Deploying Hub StatefulSet ━━━${NC}"
microk8s kubectl apply -f k8s/base/hub/statefulset.yaml
microk8s kubectl apply -f k8s/base/hub/service.yaml
echo -e "${GREEN} Hub deployed${NC}\n"

echo -e "${YELLOW}━━━ Step 5: Waiting for pods ━━━${NC}"
echo "This may take a minute..."

# Attendi che i pod siano ready
microk8s kubectl wait --for=condition=ready pod \
  -l component=hub \
  -n bomberman \
  --timeout=300s

echo -e "${GREEN} All pods ready${NC}\n"

echo -e "${YELLOW}━━━ Deployment Status ━━━${NC}"
microk8s kubectl get pods -n bomberman -o wide
echo ""
microk8s kubectl get svc -n bomberman

echo -e "\n${GREEN}╔════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║         Deployment completed!              ║${NC}"
echo -e "${GREEN}╚════════════════════════════════════════════╝${NC}\n"

# Info utili
NODE_IP=$(microk8s kubectl get nodes -o jsonpath='{.items[0].status.addresses[?(@.type=="InternalIP")].address}')
NODE_PORT=$(microk8s kubectl get svc hub-api -n bomberman -o jsonpath='{.spec.ports[0].nodePort}')

echo -e "${BLUE} Access Hub API:${NC}"
echo -e "   http://${NODE_IP}:${NODE_PORT}"
echo -e "   curl http://${NODE_IP}:${NODE_PORT}/health\n"

echo -e "${BLUE} View logs:${NC}"
echo -e "   microk8s kubectl logs -f hub-0 -n bomberman"
echo -e "   microk8s kubectl logs -f hub-1 -n bomberman"
echo -e "   microk8s kubectl logs -f hub-2 -n bomberman\n"

echo -e "${BLUE} Debug:${NC}"
echo -e "   microk8s kubectl describe pod hub-0 -n bomberman"
echo -e "   microk8s kubectl get events -n bomberman --sort-by='.lastTimestamp'\n"

echo -e "${BLUE} Test gossip:${NC}"
echo -e "   microk8s kubectl exec -it hub-0 -n bomberman -- env | grep HOSTNAME"
echo -e "   microk8s kubectl exec -it hub-0 -n bomberman -- nslookup hub-service.bomberman.svc.cluster.local\n"

echo -e "${BLUE}📺 Dashboard:${NC}"
echo -e "   microk8s dashboard-proxy\n"