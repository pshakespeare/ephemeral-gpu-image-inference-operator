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
  --storage-class longhorn \
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

# 4. Download a file into PVC (alternative to project-dir)
egpu copy-file inference-job https://example.com/test-image.jpg --target-path /artifacts/test-image.jpg

# 5. Access artifacts using debug pod
egpu debug inference-job
# Then: kubectl exec -it debug-inference-job-<timestamp> -n default -- sh

# 6. Clean up
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
- `--storage-class` - Storage class for PVC (default: longhorn)
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

### `copy-file`

Downloads a file from a URL into a PVC using a temporary pod. This replaces the need for complex kubectl commands.

**Required:**
- `job_name` - Job name (used to determine PVC name: artifacts-<job-name>)
- `url` - URL to download from

**Optional:**
- `--namespace, -n` - Kubernetes namespace (default: default)
- `--pvc-name` - PVC name (default: artifacts-<job-name>)
- `--target-path` - Target path in PVC (default: /artifacts/input.jpg)

**Example:**
```bash
egpu copy-file my-job https://example.com/image.jpg --target-path /artifacts/input.jpg
```

### `debug`

Creates a debug pod with PVC mounted for interactive access. This replaces the need for complex kubectl pod creation commands.

**Required:**
- `job_name` - Job name (used to determine PVC name: artifacts-<job-name>)

**Optional:**
- `--namespace, -n` - Kubernetes namespace (default: default)
- `--pvc-name` - PVC name (default: artifacts-<job-name>)
- `--pod-name` - Pod name (default: debug-<job-name>-<timestamp>)
- `--image` - Container image (default: busybox:latest)
- `--exec` - Attempt to exec into pod (may not work for interactive TTY)
- `--keep` - Keep pod running (default: show instructions to delete)

**Example:**
```bash
# Create debug pod
egpu debug my-job

# Access the pod (PVC mounted at /mnt)
kubectl exec -it debug-my-job-<timestamp> -n default -- sh
```

## Comparison with kubectl

**Before (complex kubectl overrides):**
```bash
# Download file
kubectl run copy-pod --rm -i --tty --image=busybox --restart=Never \
  --overrides='{"spec":{"volumes":[{"name":"artifacts","persistentVolumeClaim":{"claimName":"artifacts-sample-inference"}}],"containers":[{"name":"copy","image":"busybox","command":["sh"],"volumeMounts":[{"name":"artifacts","mountPath":"/mnt"}]}]}}' \
  -- sh -c "wget -O /mnt/input.jpg https://example.com/image.jpg"

# Debug pod
kubectl run debug-pod --rm -i --tty --image=busybox --restart=Never \
  --overrides='{"spec":{"volumes":[{"name":"artifacts","persistentVolumeClaim":{"claimName":"artifacts-sample-inference"}}],"containers":[{"name":"debug","image":"busybox","command":["sh"],"volumeMounts":[{"name":"artifacts","mountPath":"/mnt"}]}]}}' \
  -- sh
```

**After (intuitive CLI):**
```bash
# Download file
egpu copy-file my-job https://example.com/image.jpg --target-path /artifacts/input.jpg

# Debug pod
egpu debug my-job
```

The CLI handles all the complexity of PVC creation, file copying, pod management, and resource cleanup automatically using the Kubernetes Python client.

## PVC Management

The CLI can manage PVCs using the Kubernetes Python client:

- **Automatic TTL cleanup**: When deleting a job with `--delete-pvc`, the CLI checks if the TTL has passed and automatically deletes the PVC
- **Bulk cleanup**: Use `egpu cleanup` to scan all finished jobs and delete PVCs where TTL has expired
- **Manual deletion**: Use `egpu delete <job> --delete-pvc` to force delete PVC regardless of TTL

All PVC operations use the Kubernetes Python client's `CoreV1Api().delete_namespaced_persistent_volume_claim()` method.
