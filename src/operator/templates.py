"""Kubernetes resource templates."""

from kubernetes import client
from datetime import datetime


def create_pvc_manifest(pvc_name, namespace, storage_class="local-path", size="1Gi", owner_refs=None):
    """Create PVC manifest with optional owner references."""
    metadata = client.V1ObjectMeta(
        name=pvc_name,
        namespace=namespace,
        owner_references=owner_refs if owner_refs else None,
    )
    
    return client.V1PersistentVolumeClaim(
        metadata=metadata,
        spec=client.V1PersistentVolumeClaimSpec(
            access_modes=["ReadWriteOnce"],
            storage_class_name=storage_class,
            resources=client.V1ResourceRequirements(
                requests={"storage": size}
            ),
        ),
    )


def create_pod_manifest(
    pod_name,
    namespace,
    job_name,
    uid,
    model,
    input_path,
    output_path,
    gpu_count,
    image,
    pvc_name,
):
    """Create GPU job pod manifest."""
    return client.V1Pod(
        metadata=client.V1ObjectMeta(
            name=pod_name,
            namespace=namespace,
            labels={
                "app": "gpu-job",
                "ephemeralaccelerationjob": job_name,
            },
            owner_references=[
                {
                    "apiVersion": "gpu.yourdomain.io/v1alpha1",
                    "kind": "EphemeralAccelerationJob",
                    "name": job_name,
                    "uid": uid,
                    "controller": True,
                    "blockOwnerDeletion": True,
                }
            ],
        ),
        spec=client.V1PodSpec(
            restart_policy="Never",
            containers=[
                client.V1Container(
                    name="inference",
                    image=image,
                    command=["python", "-m", "job_image_infer.run_infer"],
                    args=[
                        "--model",
                        model,
                        "--input",
                        input_path,
                        "--output",
                        output_path,
                    ],
                    resources=client.V1ResourceRequirements(
                        requests={
                            "nvidia.com/gpu": str(gpu_count),
                        },
                        limits={
                            "nvidia.com/gpu": str(gpu_count),
                        },
                    ),
                    volume_mounts=[
                        client.V1VolumeMount(
                            name="artifacts",
                            mount_path="/artifacts",
                        )
                    ],
                )
            ],
            volumes=[
                client.V1Volume(
                    name="artifacts",
                    persistent_volume_claim=client.V1PersistentVolumeClaimVolumeSource(
                        claim_name=pvc_name
                    ),
                )
            ],
        ),
    )
