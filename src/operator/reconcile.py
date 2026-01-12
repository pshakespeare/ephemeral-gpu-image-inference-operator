"""Core reconciliation logic."""

import logging
from datetime import datetime
from kubernetes.client.rest import ApiException

from . import crd
from .k8s import get_clients, get_pod_status, get_pod_logs
from .templates import create_pvc_manifest, create_pod_manifest

logger = logging.getLogger(__name__)


def ensure_pvc(v1, pvc_name, namespace, storage_class, size, owner_refs=None):
    """Ensure PVC exists, create if not."""
    try:
        pvc = v1.read_namespaced_persistent_volume_claim(
            name=pvc_name, namespace=namespace
        )
        logger.info(f"PVC {pvc_name} already exists")
        
        # Update owner references if not set (for existing PVCs)
        if owner_refs and (not pvc.metadata.owner_references or len(pvc.metadata.owner_references) == 0):
            try:
                # Create patch for owner references
                patch = {
                    "metadata": {
                        "ownerReferences": [
                            {
                                "apiVersion": ref.api_version,
                                "kind": ref.kind,
                                "name": ref.name,
                                "uid": ref.uid,
                                "controller": ref.controller,
                                "blockOwnerDeletion": ref.block_owner_deletion,
                            }
                            for ref in owner_refs
                        ]
                    }
                }
                v1.patch_namespaced_persistent_volume_claim(
                    name=pvc_name, namespace=namespace, body=patch
                )
                logger.info(f"Updated PVC {pvc_name} with owner references")
            except Exception as e:
                logger.warning(f"Could not update PVC owner references: {e}")
        
        return True
    except ApiException as e:
        if e.status == 404:
            logger.info(f"Creating PVC {pvc_name}")
            pvc = create_pvc_manifest(pvc_name, namespace, storage_class, size, owner_refs)
            try:
                v1.create_namespaced_persistent_volume_claim(
                    namespace=namespace, body=pvc
                )
                logger.info(f"PVC {pvc_name} created")
                return True
            except Exception as create_error:
                logger.error(f"Failed to create PVC: {create_error}")
                raise
        else:
            logger.error(f"Error checking PVC: {e}")
            raise


def ensure_pod(v1, pod_name, namespace, job_name, uid, spec, pvc_name, image):
    """Ensure pod exists, create if not."""
    try:
        v1.read_namespaced_pod(name=pod_name, namespace=namespace)
        logger.info(f"Pod {pod_name} already exists")
        return True
    except ApiException as e:
        if e.status == 404:
            logger.info(f"Creating pod {pod_name}")
            
            model = spec.get("model", "resnet50")
            input_path = spec.get("input", {}).get("path", "/artifacts/input.jpg")
            output_path = spec.get("output", {}).get("path", "/artifacts/output.json")
            gpu_count = spec.get("resources", {}).get("gpu", 1)
            
            pod = create_pod_manifest(
                pod_name=pod_name,
                namespace=namespace,
                job_name=job_name,
                uid=uid,
                model=model,
                input_path=input_path,
                output_path=output_path,
                gpu_count=gpu_count,
                image=image,
                pvc_name=pvc_name,
            )
            
            try:
                v1.create_namespaced_pod(namespace=namespace, body=pod)
                logger.info(f"Pod {pod_name} created")
                return True
            except Exception as create_error:
                logger.error(f"Failed to create pod: {create_error}")
                raise
        else:
            logger.error(f"Error checking pod: {e}")
            raise


def reconcile_gpujob(spec, status, name, namespace, uid, **kwargs):
    """Reconcile EphemeralAccelerationJob resource."""
    v1, custom_api = get_clients()
    
    # Validate spec
    model = spec.get("model", "resnet50")
    if model not in crd.ALLOWED_MODELS:
        raise ValueError(f"Invalid model: {model}. Allowed: {crd.ALLOWED_MODELS}")
    
    current_phase = status.get("phase", crd.PHASE_PENDING)
    pvc_name = f"artifacts-{name}"
    pod_name = f"ephemeralaccelerationjob-{name}"
    
    # Get configuration from spec or use defaults
    storage_class = spec.get("storageClass", "local-path")
    pvc_size = spec.get("pvcSize", "1Gi")
    image = spec.get("image", "gpu-job-inference:latest")
    
    # Create owner references for cascade deletion (optional - allows manual PVC retention)
    from kubernetes.client import V1OwnerReference
    owner_refs = None
    if uid:
        owner_refs = [
            V1OwnerReference(
                api_version="gpu.yourdomain.io/v1alpha1",
                kind="EphemeralAccelerationJob",
                name=name,
                uid=uid,
                controller=True,
                block_owner_deletion=False,  # Don't block deletion, allow manual PVC retention
            )
        ]
    
    # Phase: Pending -> Running
    if current_phase == crd.PHASE_PENDING:
        logger.info(f"EphemeralAccelerationJob {name} is Pending, setting up resources")
        
        # Ensure PVC exists with owner references
        ensure_pvc(v1, pvc_name, namespace, storage_class, pvc_size, owner_refs)
        
        # Create pod
        ensure_pod(v1, pod_name, namespace, name, uid, spec, pvc_name, image)
        
        # Update status to Running
        return {
            "phase": crd.PHASE_RUNNING,
            "startedAt": datetime.utcnow().isoformat() + "Z",
            "podName": pod_name,
            "message": "Pod created and starting",
        }
    
    # Phase: Running -> Check pod status
    elif current_phase == crd.PHASE_RUNNING:
        pod_status = get_pod_status(v1, pod_name, namespace)
        
        if pod_status is None:
            logger.warning(f"Pod {pod_name} not found, recreating")
            ensure_pod(v1, pod_name, namespace, name, uid, spec, pvc_name, image)
            return {
                "message": "Pod recreated",
            }
        
        pod_phase = pod_status["phase"]
        
        # Pod succeeded
        if pod_phase == "Succeeded":
            output_path = spec.get("output", {}).get("path", "/artifacts/output.json")
            ttl = spec.get("ttlSecondsAfterFinished", 0)
            
            status_update = {
                "phase": crd.PHASE_SUCCEEDED,
                "finishedAt": datetime.utcnow().isoformat() + "Z",
                "artifactPath": output_path,
                "message": "Job completed successfully",
            }
            
            # Delete pod if TTL is 0
            if ttl == 0:
                try:
                    v1.delete_namespaced_pod(
                        name=pod_name,
                        namespace=namespace,
                        grace_period_seconds=0,
                    )
                    logger.info(f"Deleted pod {pod_name} (TTL=0)")
                    status_update["message"] = "Job completed, pod deleted"
                except ApiException as e:
                    if e.status != 404:
                        logger.error(f"Error deleting pod: {e}")
            
            return status_update
        
        # Pod failed
        elif pod_phase == "Failed":
            logs = get_pod_logs(v1, pod_name, namespace, tail_lines=20)
            error_message = "Job failed"
            if logs:
                error_message = f"Job failed. Last logs:\n{logs[-500:]}"  # Last 500 chars
            
            status_update = {
                "phase": crd.PHASE_FAILED,
                "finishedAt": datetime.utcnow().isoformat() + "Z",
                "message": error_message,
            }
            
            # Delete pod (ephemeral)
            try:
                v1.delete_namespaced_pod(
                    name=pod_name,
                    namespace=namespace,
                    grace_period_seconds=0,
                )
                logger.info(f"Deleted failed pod {pod_name}")
            except ApiException as e:
                if e.status != 404:
                    logger.error(f"Error deleting pod: {e}")
            
            return status_update
        
        # Pod still running
        else:
            return {
                "message": f"Pod is {pod_phase}",
            }
    
    # Phase: Succeeded or Failed - check PVC TTL
    elif current_phase in [crd.PHASE_SUCCEEDED, crd.PHASE_FAILED]:
        finished_at = status.get("finishedAt")
        pvc_ttl = spec.get("pvcTTLSecondsAfterFinished", 3600)  # Default: 1 hour
        
        # If PVC TTL is 0, delete immediately
        if pvc_ttl == 0:
            try:
                v1.delete_namespaced_persistent_volume_claim(
                    name=pvc_name, namespace=namespace
                )
                logger.info(f"Deleted PVC {pvc_name} (PVC TTL=0)")
                return {"message": "PVC deleted (TTL=0)"}
            except ApiException as e:
                if e.status != 404:
                    logger.error(f"Error deleting PVC: {e}")
        
        # Check if PVC TTL has passed
        elif finished_at and pvc_ttl > 0:
            try:
                finished_time = datetime.fromisoformat(finished_at.replace("Z", "+00:00"))
                if finished_time.tzinfo:
                    utc_offset = finished_time.utcoffset()
                    finished_time = (finished_time - utc_offset).replace(tzinfo=None)
                
                elapsed = (datetime.utcnow() - finished_time).total_seconds()
                
                if elapsed >= pvc_ttl:
                    try:
                        v1.delete_namespaced_persistent_volume_claim(
                            name=pvc_name, namespace=namespace
                        )
                        logger.info(f"Deleted PVC {pvc_name} (PVC TTL expired: {elapsed:.0f}s >= {pvc_ttl}s)")
                        return {"message": f"PVC deleted (TTL expired)"}
                    except ApiException as e:
                        if e.status != 404:
                            logger.error(f"Error deleting PVC: {e}")
            except Exception as e:
                logger.warning(f"Could not check PVC TTL: {e}")
        
        return None
    
    # Unknown phase
    else:
        return None
