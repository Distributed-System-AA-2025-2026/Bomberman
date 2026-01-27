#!/bin/bash
set -euo pipefail

# Colori
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}  Bomberman Hub - Microk8s Deployment  ${NC}"
echo -e "${GREEN}========================================${NC}\n"

# Verifica microk8s
if ! command -v microk8s &> /dev/null; then
    echo -e "${RED}[ERROR] Microk8s non installato${NC}"
    echo "Installalo con: sudo snap install microk8s --classic"
    exit 1
fi

if ! microk8s status --wait-ready &> /dev/null; then
    echo -e "${RED}[ERROR] Microk8s non e' running${NC}"
    echo "Avvialo con: microk8s start"
    exit 1
fi

echo -e "${GREEN}[OK] Microk8s ready${NC}\n"

# Variabili
HUB_IMAGE_NAME="bomberman-hub"
ROOM_IMAGE_NAME="bomberman-room"
IMAGE_TAG="latest"

echo -e "${YELLOW}--- Step 1: Building Docker images ---${NC}"

# Build Hub
echo -e "${BLUE}Building Hub image: ${HUB_IMAGE_NAME}:${IMAGE_TAG}${NC}"
docker build -t "${HUB_IMAGE_NAME}:${IMAGE_TAG}" -f docker/Dockerfile.hub .

if [ $? -ne 0 ]; then
    echo -e "${RED}[ERROR] Hub Docker build failed${NC}"
    exit 1
fi
echo -e "${GREEN}[OK] Hub image built${NC}\n"

# Build Room
echo -e "${BLUE}Building Room image: ${ROOM_IMAGE_NAME}:${IMAGE_TAG}${NC}"
docker build -t "${ROOM_IMAGE_NAME}:${IMAGE_TAG}" -f docker/Dockerfile.room .

if [ $? -ne 0 ]; then
    echo -e "${RED}[ERROR] Room Docker build failed${NC}"
    exit 1
fi
echo -e "${GREEN}[OK] Room image built${NC}\n"

# Importa le immagini in microk8s
echo -e "${YELLOW}--- Step 2: Importing images to microk8s ---${NC}"

echo -e "${BLUE}Importing Hub image...${NC}"
docker save "${HUB_IMAGE_NAME}:${IMAGE_TAG}" | microk8s ctr image import -
if [ $? -ne 0 ]; then
    echo -e "${RED}[ERROR] Hub image import failed${NC}"
    exit 1
fi

echo -e "${BLUE}Importing Room image...${NC}"
docker save "${ROOM_IMAGE_NAME}:${IMAGE_TAG}" | microk8s ctr image import -
if [ $? -ne 0 ]; then
    echo -e "${RED}[ERROR] Room image import failed${NC}"
    exit 1
fi

# Verifica immagini
echo -e "${BLUE}Verifying images...${NC}"
microk8s ctr images ls | grep -i bomberman || true
echo -e "${GREEN}[OK] Images imported${NC}\n"

echo -e "${YELLOW}--- Step 3: Creating namespace ---${NC}"
microk8s kubectl apply -f k8s/base/namespace.yaml
echo -e "${GREEN}[OK] Namespace created${NC}\n"

echo -e "${YELLOW}--- Step 4: Applying ConfigMap ---${NC}"
microk8s kubectl apply -f k8s/base/hub/configmap.yaml
echo -e "${GREEN}[OK] ConfigMap applied${NC}\n"

echo -e "${YELLOW}--- Step 5: Applying RBAC ---${NC}"
microk8s kubectl apply -f k8s/base/hub/rbac.yaml
echo -e "${GREEN}[OK] RBAC applied${NC}\n"

echo -e "${YELLOW}--- Step 6: Deploying Hub StatefulSet ---${NC}"
microk8s kubectl apply -f k8s/base/hub/statefulset.yaml
microk8s kubectl apply -f k8s/base/hub/service.yaml
echo -e "${GREEN}[OK] Hub deployed${NC}\n"

echo -e "${YELLOW}--- Step 7: Deploying Ingress ---${NC}"
microk8s kubectl apply -f k8s/base/hub/ingress.yaml
echo -e "${GREEN}[OK] Ingress deployed${NC}\n"

echo -e "${YELLOW}--- Step 8: Waiting for pods ---${NC}"
echo "This may take a minute..."

# Attendi che i pod siano ready (con timeout più lungo)
if ! microk8s kubectl wait --for=condition=ready pod \
  -l component=hub \
  -n bomberman \
  --timeout=300s 2>/dev/null; then

    echo -e "${RED}[ERROR] Pods failed to become ready${NC}"
    echo -e "${YELLOW}Checking pod status...${NC}\n"

    microk8s kubectl get pods -n bomberman
    echo ""

    echo -e "${YELLOW}Pod descriptions:${NC}"
    microk8s kubectl describe pods -n bomberman
    echo ""

    echo -e "${YELLOW}Recent events:${NC}"
    microk8s kubectl get events -n bomberman --sort-by='.lastTimestamp' | tail -20

    exit 1
fi

echo -e "${GREEN}[OK] All pods ready${NC}\n"

echo -e "${YELLOW}--- Deployment Status ---${NC}"
microk8s kubectl get pods -n bomberman -o wide
echo ""
microk8s kubectl get svc -n bomberman

echo -e "\n${GREEN}========================================${NC}"
echo -e "${GREEN}      Deployment completed!             ${NC}"
echo -e "${GREEN}========================================${NC}\n"

# Info utili
NODE_IP=$(microk8s kubectl get nodes -o jsonpath='{.items[0].status.addresses[?(@.type=="InternalIP")].address}')
NODE_PORT=$(microk8s kubectl get svc hub-api -n bomberman -o jsonpath='{.spec.ports[0].nodePort}' 2>/dev/null || echo "N/A")

if [ "$NODE_PORT" != "N/A" ]; then
    echo -e "${BLUE}Access Hub API:${NC}"
    echo -e "   http://${NODE_IP}:${NODE_PORT}"
    echo -e "   curl http://${NODE_IP}:${NODE_PORT}/health\n"
else
    echo -e "${YELLOW}[WARNING] NodePort service not found. Check service configuration.${NC}\n"
fi

echo -e "${BLUE}View logs:${NC}"
echo -e "   microk8s kubectl logs -f hub-0 -n bomberman"
echo -e "   microk8s kubectl logs -f hub-1 -n bomberman"
echo -e "   microk8s kubectl logs -f hub-2 -n bomberman\n"

echo -e "${BLUE}Debug:${NC}"
echo -e "   microk8s kubectl describe pod hub-0 -n bomberman"
echo -e "   microk8s kubectl get events -n bomberman --sort-by='.lastTimestamp'\n"

echo -e "${BLUE}Test environment variables:${NC}"
echo -e "   microk8s kubectl exec -it hub-0 -n bomberman -- env | grep -E 'HOSTNAME|PORT|POD_NAME'\n"

echo -e "${BLUE}Test DNS:${NC}"
echo -e "   microk8s kubectl exec -it hub-0 -n bomberman -- nslookup hub-service.bomberman.svc.cluster.local\n"

echo -e "${BLUE}Dashboard:${NC}"
echo -e "   microk8s dashboard-proxy\n"

echo -e "${BLUE}Access via Ingress:${NC}"
echo -e "   curl http://hub.bomberman.local/health"
echo -e "   curl http://hub.bomberman.local/debug/\n"

echo -e "${BLUE}Note:${NC}"
echo -e "   Room pods are spawned dynamically by Hub when needed."
echo -e "   Room image (${ROOM_IMAGE_NAME}:${IMAGE_TAG}) is pre-loaded and ready.\n"