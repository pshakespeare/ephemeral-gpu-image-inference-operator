# Ephemeral GPU Job CLI

A command-line interface that makes EphemeralAccelerationJob resources feel like native Kubernetes primitives.

## Installation

```bash
# Install the package
pip install -e .

# Or install just CLI dependencies
pip install kubernetes
```

The CLI is available as `egpu` after installation, or run directly:

```bash
python -m cli.main
```

## Usage

### Create an EphemeralAccelerationJob

**Basic usage:**
```bash
egpu create my-job --project-dir ./my-code --input-path /artifacts/image.jpg
```

**With custom settings:**
```bash
egpu create training-job \
  --namespace gpu-demo \
  --model resnet50 \
  --gpu 1 \
  --input-path /artifacts/input.jpg \
  --output-path /artifacts/results.json \
  --project-dir ./ml-project \
  --ttl 3600 \
  --storage-class local-path \
  --pvc-size 5Gi
```

**Create PVC without uploading files:**
```bash
egpu create my-job --create-pvc --pvc-size 10Gi
```

### Get Job Status

```bash
# Human-readable format
egpu get my-job

# JSON format
egpu get my-job --output json
```

### List All Jobs

```bash
# All namespaces
egpu list

# Specific namespace
egpu list --namespace gpu-demo
```

### Watch Job Status

```bash
egpu watch my-job
```

### Delete Job

```bash
# Delete job only
egpu delete my-job

# Delete job and PVC
egpu delete my-job --delete-pvc

# Delete job (auto-deletes PVC if TTL has passed)
egpu delete my-job --delete-pvc
```

### Cleanup PVCs Based on TTL

```bash
# Clean up all PVCs for finished jobs where TTL has passed
egpu cleanup

# Clean up in specific namespace
egpu cleanup --namespace gpu-demo

# Verbose output
egpu cleanup --verbose
```

## Workflow Example

```bash
# 1. Create job with project directory
egpu create inference-job \
  --project-dir ./my-ml-code \
  --input-path /artifacts/test-image.jpg \
  --model resnet50

# 2. Watch job progress
egpu watch inference-job

# 3. Get final status
egpu get inference-job

# 4. Retrieve artifacts (using kubectl)
kubectl run debug --rm -i --tty --image=busybox --restart=Never \
  --overrides='{"spec":{"volumes":[{"name":"artifacts","persistentVolumeClaim":{"claimName":"artifacts-inference-job"}}],"containers":[{"name":"debug","image":"busybox","volumeMounts":[{"name":"artifacts","mountPath":"/mnt"}]}]}}' \
  -- sh -c "cat /mnt/output.json"

# 5. Clean up
egpu delete inference-job --delete-pvc
```

## Key Features

- **Intuitive**: Works like `kubectl` commands
- **Automatic PVC Management**: Creates and manages PVCs automatically
- **Project Upload**: Easily upload project directories to PVCs
- **Status Tracking**: Watch jobs in real-time
- **Native Feel**: EphemeralAccelerationJobs feel like built-in Kubernetes resources

## Command Reference

### `create`

Creates an EphemeralAccelerationJob resource with optional project directory upload.

**Required:**
- `name` - EphemeralAccelerationJob name

**Optional:**
- `--namespace, -n` - Kubernetes namespace (default: default)
- `--model` - Model to use: resnet50 or mobilenet_v3_small (default: resnet50)
- `--input-path` - Input image path in PVC (default: /artifacts/input.jpg)
- `--output-path` - Output JSON path in PVC (default: /artifacts/output.json)
- `--gpu` - Number of GPUs (default: 1)
- `--ttl` - TTL in seconds after finished, 0 = delete immediately (default: 0)
- `--project-dir` - Local directory to copy into PVC
- `--create-pvc` - Create PVC even without project-dir
- `--pvc-name` - Custom PVC name (default: artifacts-<job-name>)
- `--storage-class` - Storage class for PVC (default: local-path)
- `--pvc-size` - PVC size (default: 1Gi)
- `--image` - Job container image (default: gpu-job-inference:latest)
- `--command` - Custom command to run (space-separated)

### `get`

Gets EphemeralAccelerationJob status and details.

**Required:**
- `name` - EphemeralAccelerationJob name

**Optional:**
- `--namespace, -n` - Kubernetes namespace (default: default)
- `--output, -o` - Output format: json or wide (default: wide)

### `list`

Lists all EphemeralAccelerationJobs.

**Optional:**
- `--namespace, -n` - Filter by namespace (all namespaces if not specified)

### `watch`

Watches EphemeralAccelerationJob status in real-time.

**Required:**
- `name` - EphemeralAccelerationJob name

**Optional:**
- `--namespace, -n` - Kubernetes namespace (default: default)

### `delete`

Deletes an EphemeralAccelerationJob.

**Required:**
- `name` - EphemeralAccelerationJob name

**Optional:**
- `--namespace, -n` - Kubernetes namespace (default: default)
- `--delete-pvc` - Also delete associated PVC (or auto-delete if TTL has passed)
- `--pvc-name` - PVC name to delete (default: artifacts-<job-name>)

### `cleanup`

Cleans up PVCs for finished jobs based on TTL. Scans all EphemeralAccelerationJobs and deletes PVCs where the TTL has expired.

**Optional:**
- `--namespace, -n` - Filter by namespace (all namespaces if not specified)
- `--verbose, -v` - Show detailed output for each job

## Comparison with kubectl

**Before (complex kubectl overrides):**
```bash
kubectl run copy-pod --rm -i --tty --image=busybox --restart=Never \
  --overrides='{"spec":{"volumes":[...],"containers":[...]}}' -- sh
```

**After (intuitive CLI):**
```bash
egpu create my-job --project-dir ./my-code
```

The CLI handles all the complexity of PVC creation, file copying, and resource management automatically.

## PVC Management

The CLI can manage PVCs using the Kubernetes Python client:

- **Automatic TTL cleanup**: When deleting a job with `--delete-pvc`, the CLI checks if the TTL has passed and automatically deletes the PVC
- **Bulk cleanup**: Use `egpu cleanup` to scan all finished jobs and delete PVCs where TTL has expired
- **Manual deletion**: Use `egpu delete <job> --delete-pvc` to force delete PVC regardless of TTL

All PVC operations use the Kubernetes Python client's `CoreV1Api().delete_namespaced_persistent_volume_claim()` method.
