"""Main operator entrypoint using Kopf."""

import logging
import kopf
from kubernetes import config

from . import crd
from .reconcile import reconcile_gpujob

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# Initialize Kubernetes clients
try:
    config.load_incluster_config()
    logger.info("Loaded in-cluster Kubernetes config")
except:
    config.load_kube_config()
    logger.info("Loaded kubeconfig")


@kopf.on.create(crd.GROUP, crd.VERSION, crd.PLURAL)
@kopf.on.update(crd.GROUP, crd.VERSION, crd.PLURAL)
def gpujob_handler(spec, status, name, namespace, uid, **kwargs):
    """Handle EphemeralAccelerationJob create/update events."""
    logger.info(f"Handling EphemeralAccelerationJob {name} in namespace {namespace}")
    
    try:
        result = reconcile_gpujob(spec, status, name, namespace, uid, **kwargs)
        if result:
            return result
    except ValueError as e:
        logger.error(f"Validation error: {e}")
        raise kopf.PermanentError(str(e))
    except Exception as e:
        logger.error(f"Reconciliation error: {e}", exc_info=True)
        raise kopf.TemporaryError(f"Reconciliation failed: {e}", delay=30)


@kopf.timer(crd.GROUP, crd.VERSION, crd.PLURAL, interval=30)
def gpujob_timer(spec, status, name, namespace, uid, **kwargs):
    """Periodic reconciliation timer."""
    current_phase = status.get("phase", crd.PHASE_PENDING)
    
    # Reconcile for all phases (including Succeeded/Failed for PVC cleanup)
    logger.debug(f"Timer reconciliation for EphemeralAccelerationJob {name} (phase: {current_phase})")
    try:
        result = reconcile_gpujob(spec, status, name, namespace, uid, **kwargs)
        if result:
            return result
    except Exception as e:
        logger.error(f"Timer reconciliation error: {e}", exc_info=True)


@kopf.on.delete(crd.GROUP, crd.VERSION, crd.PLURAL)
def gpujob_delete(name, namespace, **kwargs):
    """Handle EphemeralAccelerationJob deletion."""
    logger.info(f"EphemeralAccelerationJob {name} deleted, cleaning up resources")
    # Kubernetes owner references will handle pod deletion
    # PVC deletion is controlled by owner references (blockOwnerDeletion=False allows manual retention)


if __name__ == "__main__":
    kopf.run()
