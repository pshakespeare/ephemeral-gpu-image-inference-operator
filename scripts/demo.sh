#!/bin/bash
set -e

echo "=== Ephemeral GPU Image Inference Operator Demo ==="
echo ""

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# Configuration
NAMESPACE=${NAMESPACE:-default}
JOB_NAME="sample-inference"

echo -e "${YELLOW}Step 1: Building images...${NC}"
make build
echo ""

echo -e "${YELLOW}Step 2: Loading images into cluster...${NC}"
make load || echo "Note: Image loading skipped (may need manual import)"
echo ""

echo -e "${YELLOW}Step 3: Installing operator...${NC}"
make install
echo ""

echo -e "${YELLOW}Step 4: Waiting for operator to be ready...${NC}"
kubectl wait --for=condition=available --timeout=120s \
    deployment/gpu-operator-ephemeral-gpu-image-inference-operator -n ${NAMESPACE} || true
echo ""

echo -e "${YELLOW}Step 5: Applying example EphemeralAccelerationJob...${NC}"
kubectl apply -f examples/ephemeralaccelerationjob.yaml
echo ""

echo -e "${YELLOW}Step 6: Waiting for PVC to be created...${NC}"
kubectl wait --for=condition=Bound pvc/artifacts-${JOB_NAME} --timeout=60s || true
echo ""

echo -e "${YELLOW}Step 7: EphemeralAccelerationJob status:${NC}"
kubectl get ephemeralaccelerationjob ${JOB_NAME} -w &
WATCH_PID=$!

# Wait a bit for status updates
sleep 10

echo ""
echo -e "${YELLOW}Step 8: Checking pod status...${NC}"
kubectl get pods -l app=gpu-job

echo ""
echo -e "${GREEN}Demo setup complete!${NC}"
echo ""
echo "Next steps:"
echo "  1. Copy input image to PVC (see README)"
echo "  2. Watch job: kubectl get ephemeralaccelerationjob ${JOB_NAME} -w"
echo "  3. Check logs: kubectl logs -l app=gpu-job"
echo "  4. Retrieve artifacts: make artifacts"
echo ""
echo "To stop watching, press Ctrl+C"
wait $WATCH_PID 2>/dev/null || true
