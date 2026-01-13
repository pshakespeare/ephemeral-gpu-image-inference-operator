# Documentation

This directory contains detailed documentation for the Ephemeral GPU Image Inference Operator.

## Available Documentation

- **[Sequence Diagram](sequence-diagram.md)** - Complete lifecycle flow diagram showing how EphemeralAccelerationJobs are created, executed, and cleaned up

## Main Documentation

- **[Main README](../README.md)** - Project overview, quick start guide, and usage examples
- **[CLI Documentation](../src/cli/README.md)** - Complete CLI tool reference and usage guide

## Key Concepts

### Architecture
The operator uses a Kubernetes-native architecture:
- **Custom Resource Definition (CRD)**: `EphemeralAccelerationJob` defines the desired state
- **Operator (Kopf)**: Watches CRDs and reconciles the actual state
- **CLI Tool**: Provides intuitive interface for job management
- **TTL-based Cleanup**: Automatic resource cleanup based on configurable time-to-live

### Workflow
1. User creates an `EphemeralAccelerationJob` via CLI or kubectl
2. Operator watches for new/updated jobs
3. Operator creates PVC for artifact storage
4. Operator creates GPU pod with PVC mounted
5. Pod executes inference and writes results to PVC
6. Operator updates job status
7. TTL-based cleanup removes resources automatically

See the [Sequence Diagram](sequence-diagram.md) for detailed flow.
