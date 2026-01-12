.PHONY: build load install example logs clean help

# Image names
OPERATOR_IMAGE ?= ephemeral-gpu-operator:latest
JOB_IMAGE ?= gpu-job-inference:latest

# Helm release name
RELEASE_NAME ?= gpu-operator
NAMESPACE ?= default

help: ## Show this help message
	@echo 'Usage: make [target]'
	@echo ''
	@echo 'Available targets:'
	@awk 'BEGIN {FS = ":.*?## "} /^[a-zA-Z_-]+:.*?## / {printf "  %-15s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

cli: ## Install CLI tool
	@echo "Installing CLI..."
	@pip install -e . || echo "Note: Install dependencies first: pip install kubernetes"
	@echo "✓ CLI installed. Use 'egpu' command or 'python -m cli.main'"

build: ## Build both operator and job images
	@echo "Building operator image..."
	docker build -f docker/operator.Dockerfile -t $(OPERATOR_IMAGE) .
	@echo "Building job image..."
	docker build -f docker/job.Dockerfile -t $(JOB_IMAGE) .
	@echo "✓ Images built: $(OPERATOR_IMAGE), $(JOB_IMAGE)"

load: ## Load images into local cluster (k3s/kind)
	@echo "Loading images into local cluster..."
	@if command -v k3d >/dev/null 2>&1; then \
		k3d image import $(OPERATOR_IMAGE) || true; \
		k3d image import $(JOB_IMAGE) || true; \
	elif command -v kind >/dev/null 2>&1; then \
		kind load docker-image $(OPERATOR_IMAGE) || true; \
		kind load docker-image $(JOB_IMAGE) || true; \
	else \
		echo "Note: k3d or kind not found. Images must be available in cluster."; \
	fi
	@echo "✓ Images loaded (if applicable)"

install: ## Install operator via Helm
	@echo "Installing operator via Helm..."
	helm upgrade --install $(RELEASE_NAME) ./charts/ephemeral-gpu-image-inference-operator \
		--namespace $(NAMESPACE) \
		--create-namespace \
		--set operator.image.repository=ephemeral-gpu-operator \
		--set operator.image.tag=latest \
		--set job.image.repository=gpu-job-inference \
		--set job.image.tag=latest \
		--set storage.storageClass=longhorn
	@echo "✓ Operator installed"
	@echo "Waiting for operator to be ready..."
	@kubectl wait --for=condition=available --timeout=120s \
		deployment/$(RELEASE_NAME)-ephemeral-gpu-image-inference-operator -n $(NAMESPACE) || true

example: ## Apply example EphemeralAccelerationJob and watch status
	@echo "Applying example EphemeralAccelerationJob..."
	@kubectl apply -f examples/ephemeralaccelerationjob.yaml
	@echo "✓ EphemeralAccelerationJob applied"
	@echo ""
	@echo "Watching EphemeralAccelerationJob status (Ctrl+C to stop)..."
	@kubectl get ephemeralaccelerationjob sample-inference -w || true

logs: ## Show operator and job pod logs
	@echo "=== Operator Logs ==="
	@kubectl logs -l app=ephemeral-gpu-image-inference-operator -n $(NAMESPACE) --tail=50 || echo "No operator logs found"
	@echo ""
	@echo "=== Job Pod Logs ==="
	@kubectl logs -l app=gpu-job -n $(NAMESPACE) --tail=50 || echo "No job pod logs found"

clean: ## Uninstall operator and clean up resources
	@echo "Cleaning up..."
	@kubectl delete ephemeralaccelerationjob sample-inference --ignore-not-found=true
	@helm uninstall $(RELEASE_NAME) -n $(NAMESPACE) || true
	@kubectl delete pvc artifacts-sample-inference --ignore-not-found=true
	@echo "✓ Cleanup complete"

status: ## Show EphemeralAccelerationJob status
	@kubectl get ephemeralaccelerationjobs
	@echo ""
	@kubectl describe ephemeralaccelerationjob sample-inference || true

artifacts: ## Show artifacts from PVC
	@echo "Creating debug pod to access artifacts..."
	@kubectl run debug-pod --rm -i --tty --image=busybox --restart=Never -- \
		sh -c "echo 'Mount PVC and check /mnt/artifacts' || kubectl exec -it debug-pod -- ls -la /mnt/artifacts || echo 'PVC not mounted'"
	@echo "To manually access artifacts:"
	@echo "  kubectl run debug-pod --rm -i --tty --image=busybox --restart=Never --overrides='{\"spec\":{\"volumes\":[{\"name\":\"artifacts\",\"persistentVolumeClaim\":{\"claimName\":\"artifacts-sample-inference\"}}],\"containers\":[{\"name\":\"debug\",\"image\":\"busybox\",\"volumeMounts\":[{\"name\":\"artifacts\",\"mountPath\":\"/mnt\"}]}]}}' -- sh"
