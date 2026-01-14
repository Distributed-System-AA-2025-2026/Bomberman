#!/bin/bash
set -euo pipefail

# Script per visualizzare lo status del deployment

BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "${YELLOW}========== Bomberman Deployment Status ==========${NC}\n"

echo -e "${BLUE}Namespace:${NC}"
microk8s kubectl get namespace bomberman 2>/dev/null || echo "Namespace not found"
echo ""

echo -e "${BLUE}Pods:${NC}"
microk8s kubectl get pods -n bomberman -o wide
echo ""

echo -e "${BLUE}Services:${NC}"
microk8s kubectl get svc -n bomberman
echo ""

echo -e "${BLUE}StatefulSet:${NC}"
microk8s kubectl get statefulset -n bomberman
echo ""

echo -e "${BLUE}ConfigMap:${NC}"
microk8s kubectl get configmap -n bomberman
echo ""

echo -e "${BLUE}Recent Events:${NC}"
microk8s kubectl get events -n bomberman --sort-by='.lastTimestamp' | tail -10