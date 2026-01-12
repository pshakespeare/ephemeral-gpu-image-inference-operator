"""Kubernetes client helpers."""

import logging
from kubernetes import client, config
from kubernetes.client.rest import ApiException

logger = logging.getLogger(__name__)

# Initialize clients
_v1 = None
_custom_api = None


def init_clients():
    """Initialize Kubernetes clients."""
    global _v1, _custom_api
    
    try:
        config.load_incluster_config()
        logger.info("Loaded in-cluster Kubernetes config")
    except:
        config.load_kube_config()
        logger.info("Loaded kubeconfig")
    
    _v1 = client.CoreV1Api()
    _custom_api = client.CustomObjectsApi()
    
    return _v1, _custom_api


def get_clients():
    """Get initialized Kubernetes clients."""
    global _v1, _custom_api
    if _v1 is None or _custom_api is None:
        init_clients()
    return _v1, _custom_api


def get_pod_status(v1, pod_name, namespace):
    """Get pod status."""
    try:
        pod = v1.read_namespaced_pod(name=pod_name, namespace=namespace)
        return {
            "phase": pod.status.phase,
            "ready": any(
                c.type == "Ready" and c.status == "True"
                for c in (pod.status.conditions or [])
            ),
            "container_statuses": [
                {
                    "name": cs.name,
                    "ready": cs.ready,
                    "state": _get_container_state(cs),
                }
                for cs in (pod.status.container_statuses or [])
            ],
        }
    except ApiException as e:
        if e.status == 404:
            return None
        logger.error(f"Error getting pod status: {e}")
        raise


def _get_container_state(container_status):
    """Get container state string."""
    if container_status.state.running:
        return "Running"
    elif container_status.state.waiting:
        return f"Waiting: {container_status.state.waiting.reason}"
    elif container_status.state.terminated:
        return f"Terminated: {container_status.state.terminated.reason}"
    return "Unknown"


def get_pod_logs(v1, pod_name, namespace, tail_lines=50):
    """Get pod logs."""
    try:
        logs = v1.read_namespaced_pod_log(
            name=pod_name,
            namespace=namespace,
            tail_lines=tail_lines,
        )
        return logs
    except ApiException as e:
        if e.status == 404:
            return None
        logger.error(f"Error getting pod logs: {e}")
        return None
