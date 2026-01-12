# k3s/kind Setup Notes

This document assumes you already have k3s or kind running with NVIDIA GPU support.

## k3s Setup

### Prerequisites
- k3s installed with NVIDIA Container Runtime
- NVIDIA drivers installed on host
- NVIDIA device plugin configured

### Verify Setup

```bash
# Check k3s is running
sudo systemctl status k3s

# Check GPU nodes
kubectl get nodes -o jsonpath='{range .items[*]}{.metadata.name}{"\t"}{.status.capacity.nvidia\.com/gpu}{"\n"}{end}'

# Check storage class (should have local-path)
kubectl get storageclass
```

### Loading Images

k3s uses containerd. To load images:

```bash
# Save images
docker save ephemeral-gpu-operator:latest > operator.tar
docker save gpu-job-inference:latest > job.tar

# Load into k3s
sudo k3s ctr images import operator.tar
sudo k3s ctr images import job.tar

# Verify
sudo k3s ctr images list | grep -E "(ephemeral-gpu|gpu-job)"
```

Or use `k3d` if available:
```bash
k3d image import ephemeral-gpu-operator:latest
k3d image import gpu-job-inference:latest
```

## kind Setup

### Prerequisites
- kind cluster created with GPU support
- NVIDIA device plugin installed

### Loading Images

```bash
kind load docker-image ephemeral-gpu-operator:latest
kind load docker-image gpu-job-inference:latest
```

## Common Issues

### Images not found
- Ensure images are loaded into cluster
- Check image pull policy (should be `IfNotPresent` or `Never`)

### Storage class not found
- For k3s: Install local-path provisioner if not present
- For kind: May need to configure storage class

### GPU not available
- Verify NVIDIA device plugin is running
- Check node labels and taints
- Ensure GPU nodes are properly configured
