"""CRD schema constants and helpers."""

# CRD Group, Version, and Kind
GROUP = "gpu.yourdomain.io"
VERSION = "v1alpha1"
PLURAL = "ephemeralaccelerationjobs"
KIND = "EphemeralAccelerationJob"

# API version string
API_VERSION = f"{GROUP}/{VERSION}"

# Status phases
PHASE_PENDING = "Pending"
PHASE_RUNNING = "Running"
PHASE_SUCCEEDED = "Succeeded"
PHASE_FAILED = "Failed"

# Allowed model types
ALLOWED_MODELS = ["resnet50", "mobilenet_v3_small"]
