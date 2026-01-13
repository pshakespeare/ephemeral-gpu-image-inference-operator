# Ephemeral GPU Image Inference Operator

A Kubernetes operator that manages ephemeral GPU jobs for image inference tasks.

## Overview

This operator allows you to run GPU-backed image inference jobs that:
- Automatically create and manage GPU pods
- Mount persistent storage for input images and output artifacts
- Clean up pods automatically after completion (ephemeral)
- Automatically clean up PVCs based on configurable TTL
- Track job status and provide artifact paths
- Provide intuitive CLI for job management

## Architecture

```mermaid
graph TD
    USER[User]
    CLI[CLI Tool<br/>egpu]
    CR[EphemeralAccelerationJob<br/>Custom Resource CRD]
    OP[Operator<br/>Kopf]
    K8S[Kubernetes API]
    PVC[PVC<br/>Longhorn Storage]
    GPU_POD[GPU Pod<br/>Inference Execution]
    DEBUG_POD[Debug Pod<br/>Artifact Access]
    COPY_POD[Copy Pod<br/>File Upload/Download]
    TIMER[Timer<br/>Reconciliation & Cleanup]
    
    USER -->|create/get/watch/delete| CLI
    CLI -->|Creates/Manages| CR
    CLI -->|Creates| COPY_POD
    CLI -->|Creates| DEBUG_POD
    CLI -->|Queries| K8S
    
    CR -->|Watches| OP
    OP -->|Reconciles via| K8S
    OP -->|Creates| PVC
    OP -->|Creates| GPU_POD
    OP -->|Updates| CR
    
    TIMER -->|Periodic checks| OP
    OP -->|TTL cleanup| GPU_POD
    OP -->|TTL cleanup| PVC
    
    GPU_POD -->|Reads/Writes| PVC
    DEBUG_POD -->|Accesses| PVC
    COPY_POD -->|Uploads/Downloads| PVC
    
    PVC -->|Backed by| K8S
    
    style USER fill:#e1f5ff
    style CLI fill:#c8e6c9
    style OP fill:#fff9c4
    style GPU_POD fill:#ffccbc
    style PVC fill:#f3e5f5
```

## Sequence Diagram

See [Sequence Diagram](docs/sequence-diagram.md) for the complete lifecycle flow of an EphemeralAccelerationJob.

## Prerequisites

### Required
- **Kubernetes cluster** (k3s, kind, or cloud) with:
  - NVIDIA GPU support
  - NVIDIA Container Toolkit installed
  - NVIDIA device plugin running
- **kubectl** configured with cluster access
- **Docker** for building images
- **Helm 3** for operator installation
- **Python 3.12+** (for local development)

### Verify Prerequisites

```bash
# Check cluster access
kubectl cluster-info

# Check GPU nodes
kubectl get nodes -o wide | grep "nvidia.com/gpu.count"

# Check NVIDIA device plugin
kubectl get pods -n gpu-operator
NAME                                                          READY   STATUS      RESTARTS   AGE
gpu-feature-discovery-vz9lr                                   1/1     Running     0          4d3h
gpu-operator-7569f8b499-2ctcj                                 1/1     Running     0          4d3h
gpu-operator-node-feature-discovery-gc-55ffc49ccc-kss46       1/1     Running     0          4d3h
gpu-operator-node-feature-discovery-master-6b5787f695-ztbqs   1/1     Running     0          4d3h
gpu-operator-node-feature-discovery-worker-sjj9s              1/1     Running     0          4d3h
nvidia-container-toolkit-daemonset-6wnpq                      1/1     Running     0          4d3h
nvidia-cuda-validator-fh88b                                   0/1     Completed   0          4d2h
nvidia-dcgm-exporter-ssl29                                    1/1     Running     0          4d3h
nvidia-device-plugin-daemonset-fwc8c                          1/1     Running     0          4d3h
nvidia-operator-validator-vs75n                               1/1     Running     0          4d3h

# Check storage class (should show "longhorn" for Longhorn clusters)
kubectl get storageclass
```

## CLI Tool

The project includes a CLI tool that makes EphemeralAccelerationJobs feel like native Kubernetes resources. The CLI handles PVC creation, file uploads, and resource management automatically.

### Installation

```bash
# Install CLI
pip install -e .
# Or: make cli
```

### Quick Examples

```bash
# Create a job with project directory (handles PVC creation and file upload)
egpu create my-job --project-dir ./my-code --input-path /artifacts/image.jpg

# Create with custom PVC TTL (24 hours retention)
egpu create training-job \
  --project-dir ./ml-project \
  --input-path /artifacts/input.jpg \
  --pvc-ttl 86400

# Download a file from URL into PVC
egpu copy-file my-job https://example.com/image.jpg --target-path /artifacts/input.jpg

# Create debug pod for interactive access to PVC
egpu debug my-job
# Then: kubectl exec -it debug-my-job-<timestamp> -n default -- sh

# Watch job status
egpu watch my-job

# Get job details
egpu get my-job

# List all jobs
egpu list

# Clean up PVCs for finished jobs (based on TTL)
egpu cleanup

# Delete job and PVC
egpu delete my-job --delete-pvc
```

### Key Features

- **Automatic PVC Management**: Creates and manages PVCs automatically
- **Project Upload**: Easily upload entire project directories to PVCs
- **TTL-based Cleanup**: Automatic PVC cleanup based on configurable TTL
- **Native Feel**: Works like `kubectl get`, `kubectl create`, etc.


## Quick Start

### 1. Build Images

```bash
make build
```

This builds:
- `ephemeral-gpu-operator:latest` - The operator container
- `gpu-job-inference:latest` - The inference job container

### 2. Load Images (for local clusters)

If using k3s or kind, load images into the cluster:

```bash
make load
```

For k3s, you may need to import images manually:
```bash
sudo k3s ctr images import < operator.tar
sudo k3s ctr images import < job.tar
```

### 3. Install Operator

```bash
make install
```

This installs the operator via Helm, including:
- CRD definition
- RBAC (ServiceAccount, ClusterRole, ClusterRoleBinding)
- Operator Deployment

### 4. Run Example Job

**Option A: Using CLI (Recommended)**

```bash
# Create job with project directory (automatically handles PVC and file upload)
egpu create sample-inference \
  --project-dir ./resources \
  --input-path /artifacts/sample.jpg \
  --model resnet50

# Watch job
egpu watch sample-inference
```


**Option B**

```bash
make example
```

## Running a Job

The CLI handles everything automatically:

```bash
# Create job with project directory
# - Automatically creates PVC
# - Uploads project directory to PVC
# - Creates EphemeralAccelerationJob
egpu create my-inference \
  --project-dir ./my-ml-project \
  --input-path /artifacts/input.jpg \
  --model resnet50 \
  --pvc-ttl 3600  # Keep PVC for 1 hour (default)

# Watch job progress
egpu watch my-inference

# Get final status
egpu get my-inference

# Retrieve artifacts (see below)
```

### Using CLI

**Step 1: Copy Input Image to PVC**

Before creating the EphemeralAccelerationJob, you need to copy your input image into the PVC. The operator will create a PVC named `artifacts-<job-name>`.

**Option A: Using CLI (Recommended)**
```bash
# Apply EphemeralAccelerationJob (operator creates PVC)
kubectl apply -f resources/ephemeralaccelerationjob.yaml

# Wait for PVC to be created
kubectl wait --for=condition=Bound pvc/artifacts-sample-inference --timeout=60s

# Download file using CLI
egpu copy-file sample-inference https://example.com/image.jpg --target-path /artifacts/input.jpg
```

**Step 2: Watch Status**

```bash
# Watch EphemeralAccelerationJob
kubectl get ephemeralaccelerationjobs -w

# Describe for details
kubectl describe ephemeralaccelerationjob sample-inference

# Watch pod
kubectl get pods -w

# Check logs
kubectl logs -l app=gpu-job --tail=50
```

**Step 3: Retrieve Artifacts**

After the job completes, retrieve the output:

```bash
# Using CLI (easiest)
egpu get sample-inference  # Shows artifact path

# Create debug pod using CLI
egpu debug sample-inference
# Then exec into it:
kubectl exec -it debug-sample-inference-<timestamp> -n default -- sh

# Inside pod, check artifacts (PVC mounted at /mnt)
cat /mnt/output.json
ls -la /mnt/
```

## EphemeralAccelerationJob Resource Specification

```yaml
apiVersion: gpu.yourdomain.io/v1alpha1
kind: EphemeralAccelerationJob
metadata:
  name: my-inference-job
  namespace: default
spec:
  model: resnet50                    # resnet50 or mobilenet_v3_small
  input:
    type: image
    path: /artifacts/input.jpg        # Path inside PVC
  output:
    path: /artifacts/output.json      # Output JSON path
  resources:
    gpu: 1                            # Number of GPUs
  ttlSecondsAfterFinished: 0         # Pod TTL: 0 = delete immediately, >0 = keep for N seconds
  pvcTTLSecondsAfterFinished: 3600   # PVC TTL: 0 = delete immediately, default: 3600 (1 hour)
  storageClass: longhorn              # PVC storage class (use "longhorn" for Longhorn clusters)
  pvcSize: 1Gi                        # PVC size
  image: gpu-job-inference:latest     # Job container image
```

### TTL Configuration

The operator supports separate TTLs for pods and PVCs:

- **`ttlSecondsAfterFinished`**: Controls when the pod is deleted
  - `0` = Delete pod immediately after completion (default)
  - `> 0` = Keep pod for N seconds after completion
  
- **`pvcTTLSecondsAfterFinished`**: Controls when the PVC is deleted
  - `0` = Delete PVC immediately after job completion
  - `3600` = Keep PVC for 1 hour (default) - allows artifact retrieval
  - `> 0` = Keep PVC for N seconds after completion

**Best Practice**: Use separate TTLs to balance cost (delete pods quickly) with usability (keep PVCs for artifact retrieval). See [PVC-LIFECYCLE.md](PVC-LIFECYCLE.md) for details.

### Status Fields

```yaml
status:
  phase: Succeeded                    # Pending | Running | Succeeded | Failed
  message: "Job completed successfully"
  startedAt: "2024-01-01T12:00:00Z"
  finishedAt: "2024-01-01T12:01:30Z"
  podName: "ephemeralaccelerationjob-my-inference-job"
  artifactPath: "/artifacts/output.json"
```

## Output Format

The inference job writes a JSON file with:

```json
{
  "model": "resnet50",
  "top5": [
    {"label": "class_285", "probability": 0.8234},
    {"label": "class_123", "probability": 0.1234},
    ...
  ],
  "elapsed_ms": 45.23,
  "device": "cuda",
  "timestamp": "2024-01-01T12:01:30Z"
}
```

## Makefile Commands

```bash
make build          # Build operator and job images
make load           # Load images into local cluster
make install        # Install operator via Helm
make cli            # Install CLI tool
make example        # Apply example EphemeralAccelerationJob and watch
make logs           # Show operator and job logs
make status         # Show EphemeralAccelerationJob status
make artifacts      # Instructions for accessing artifacts
make clean          # Uninstall operator and clean up
```

## Development

### Local Development

```bash
# Install dependencies
pip install -e .

# Run operator locally (requires kubeconfig)
python -m operator.main

# In another terminal, apply EphemeralAccelerationJob
kubectl apply -f resources/ephemeralaccelerationjob.yaml
```

### Project Structure

```
.
├── src/
│   ├── operator/          # Operator code
│   │   ├── main.py        # Kopf entrypoint
│   │   ├── crd.py         # CRD constants
│   │   ├── k8s.py         # K8s client helpers
│   │   ├── reconcile.py   # Reconciliation logic
│   │   └── templates.py   # Resource templates
│   ├── job_image_infer/  # Job container code
│   │   └── run_infer.py   # Inference script
│   └── cli/               # CLI tool
│       └── main.py        # CLI implementation
├── runtimes/              # Dockerfiles
├── charts/                # Helm chart
├── resources/             # Example resources and sample files
└── scripts/               # Utility scripts
```




## PVC Lifecycle Management

The operator automatically manages PVC lifecycle based on TTL:

- **Pod TTL**: Pods are deleted based on `ttlSecondsAfterFinished` (default: 0 = immediate)
- **PVC TTL**: PVCs are deleted based on `pvcTTLSecondsAfterFinished` (default: 3600 = 1 hour)
- **Automatic Cleanup**: Operator timer checks and deletes PVCs when TTL expires
- **Owner References**: PVCs have owner references for cascade deletion

**What happens when a job expires:**
1. Pod is deleted immediately (if `ttlSecondsAfterFinished: 0`)
2. PVC is kept for artifact retrieval (default: 1 hour)
3. Operator automatically deletes PVC after PVC TTL expires
4. No manual cleanup required


## Cleanup

### Using CLI

```bash
# Delete job and PVC
egpu delete sample-inference --delete-pvc

# Clean up all PVCs where TTL has expired
egpu cleanup

# Clean up in specific namespace
egpu cleanup --namespace gpu-demo
```

### Using kubectl

```bash
# Remove example job
kubectl delete ephemeralaccelerationjob sample-inference

# PVC will be automatically deleted after TTL expires
# Or delete manually:
kubectl delete pvc artifacts-sample-inference
```

### Uninstall Operator

```bash
make clean

# Or manually
helm uninstall gpu-operator
kubectl delete crd ephemeralaccelerationjobs.gpu.yourdomain.io
```

## Key Features

### Operator Features
-  **Automatic Resource Management**: Creates and manages PVCs and Pods
-  **TTL-based Cleanup**: Separate TTLs for pods and PVCs
-  **Status Tracking**: Real-time job status with artifact paths
-  **Error Handling**: Graceful error handling and retry logic
-  **Reconciliation**: Timer-based reconciliation ensures desired state

### CLI Features
-  **Intuitive Interface**: Works like native Kubernetes commands
-  **Automatic PVC Management**: Creates and manages PVCs automatically
-  **Project Upload**: Easily upload project directories to PVCs
-  **File Download**: Download files from URLs directly into PVCs
-  **Debug Pods**: Create debug pods for interactive PVC access
-  **TTL-based Cleanup**: Automatic PVC cleanup based on TTL
-  **Status Monitoring**: Real-time job status watching
