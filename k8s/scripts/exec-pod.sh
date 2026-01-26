#!/bin/bash
set -euo pipefail

# Script per fare exec in un pod

POD_NAME=${1:-hub-0}

echo "Executing shell in pod: ${POD_NAME}"
echo ""

microk8s kubectl exec -it ${POD_NAME} -n bomberman -- /bin/bash