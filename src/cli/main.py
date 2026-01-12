#!/usr/bin/env python3
"""
Ephemeral GPU Job CLI

A command-line interface for managing ephemeral GPU inference jobs.
Makes EphemeralAccelerationJob resources feel like native Kubernetes primitives.
"""

import argparse
import json
import os
import sys
import subprocess
import tarfile
import tempfile
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from kubernetes import client, config
from kubernetes.client.rest import ApiException


def load_kubeconfig():
    """Load Kubernetes configuration."""
    try:
        config.load_incluster_config()
        return True
    except:
        try:
            config.load_kube_config()
            return True
        except Exception as e:
            print(f"Error loading Kubernetes config: {e}", file=sys.stderr)
            return False


def create_pvc(v1, name, namespace, storage_class="longhorn", size="1Gi"):
    """Create a PVC if it doesn't exist."""
    try:
        v1.read_namespaced_persistent_volume_claim(name=name, namespace=namespace)
        print(f"PVC '{name}' already exists")
        return True
    except ApiException as e:
        if e.status == 404:
            print(f"Creating PVC '{name}'...")
            pvc = client.V1PersistentVolumeClaim(
                metadata=client.V1ObjectMeta(name=name, namespace=namespace),
                spec=client.V1PersistentVolumeClaimSpec(
                    access_modes=["ReadWriteOnce"],
                    storage_class_name=storage_class,
                    resources=client.V1ResourceRequirements(
                        requests={"storage": size}
                    ),
                ),
            )
            try:
                v1.create_namespaced_persistent_volume_claim(
                    namespace=namespace, body=pvc
                )
                print(f"✓ PVC '{name}' created")
                return True
            except Exception as create_error:
                print(f"✗ Failed to create PVC: {create_error}", file=sys.stderr)
                return False
        else:
            print(f"✗ Error checking PVC: {e}", file=sys.stderr)
            return False


def copy_to_pvc(v1, pvc_name, namespace, source_path, target_path="/artifacts"):
    """Copy files/directories from local filesystem into PVC."""
    source = Path(source_path)
    if not source.exists():
        print(f"✗ Source path does not exist: {source_path}", file=sys.stderr)
        return False

    print(f"Copying '{source_path}' to PVC '{pvc_name}' at '{target_path}'...")

    # Create a temporary tar file
    with tempfile.NamedTemporaryFile(suffix=".tar", delete=False) as tar_file:
        tar_path = tar_file.name

    try:
        # Create tar archive
        with tarfile.open(tar_path, "w") as tar:
            if source.is_file():
                tar.add(source, arcname=source.name)
            else:
                for root, dirs, files in os.walk(source):
                    for file in files:
                        file_path = os.path.join(root, file)
                        arcname = os.path.relpath(file_path, source.parent)
                        tar.add(file_path, arcname=arcname)

        # Create a pod to copy the tar into PVC
        pod_name = f"copy-to-pvc-{pvc_name}"
        
        # Delete any existing copy pod
        try:
            v1.delete_namespaced_pod(name=pod_name, namespace=namespace, grace_period_seconds=0)
        except ApiException:
            pass

        # Create copy pod
        copy_pod = client.V1Pod(
            metadata=client.V1ObjectMeta(name=pod_name, namespace=namespace),
            spec=client.V1PodSpec(
                restart_policy="Never",
                containers=[
                    client.V1Container(
                        name="copy",
                        image="busybox:latest",
                        command=["sh", "-c", "sleep 3600"],
                        volume_mounts=[
                            client.V1VolumeMount(
                                name="artifacts", mount_path="/mnt"
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

        v1.create_namespaced_pod(namespace=namespace, body=copy_pod)

        # Wait for pod to be ready
        for _ in range(30):
            try:
                pod = v1.read_namespaced_pod(name=pod_name, namespace=namespace)
                if pod.status.phase == "Running":
                    break
            except ApiException:
                pass
            time.sleep(1)
        else:
            print("✗ Copy pod did not become ready", file=sys.stderr)
            return False

        # Use kubectl cp to copy tar file (most reliable method)
        import subprocess
        try:
            result = subprocess.run(
                [
                    "kubectl",
                    "cp",
                    tar_path,
                    f"{namespace}/{pod_name}:/tmp/data.tar",
                ],
                check=True,
                capture_output=True,
                text=True,
            )
        except FileNotFoundError:
            print(
                "✗ kubectl not found. Please install kubectl or copy files manually.",
                file=sys.stderr,
            )
            print(
                f"  You can copy files manually using: kubectl cp {tar_path} {namespace}/{pod_name}:/tmp/data.tar",
                file=sys.stderr,
            )
            # Clean up and return
            try:
                v1.delete_namespaced_pod(name=pod_name, namespace=namespace, grace_period_seconds=0)
            except:
                pass
            return False
        except subprocess.CalledProcessError as e:
            print(f"✗ Failed to copy files: {e.stderr}", file=sys.stderr)
            # Clean up and return
            try:
                v1.delete_namespaced_pod(name=pod_name, namespace=namespace, grace_period_seconds=0)
            except:
                pass
            return False

        # Extract tar in pod
        exec_command = [
            "sh",
            "-c",
            f"cd {target_path} && tar -xf /tmp/data.tar && rm /tmp/data.tar && ls -la",
        ]
        exec_response = v1.connect_get_namespaced_pod_exec(
            name=pod_name,
            namespace=namespace,
            command=exec_command,
            stdout=True,
            stderr=True,
            tty=False,
        )
        if exec_response:
            print(exec_response)

        # Clean up pod
        try:
            v1.delete_namespaced_pod(name=pod_name, namespace=namespace, grace_period_seconds=0)
        except ApiException:
            pass

        print(f"✓ Files copied to PVC")
        return True

    except Exception as e:
        print(f"✗ Error copying to PVC: {e}", file=sys.stderr)
        return False
    finally:
        # Clean up tar file
        try:
            os.unlink(tar_path)
        except:
            pass


def create_gpujob(
    custom_api,
    name,
    namespace,
    model="resnet50",
    input_path="/artifacts/input.jpg",
    output_path="/artifacts/output.json",
    gpu=1,
    ttl=0,
    pvc_ttl=3600,
    storage_class="longhorn",
    pvc_size="1Gi",
    image="gpu-job-inference:latest",
    command=None,
    pvc_name=None,
):
    """Create an EphemeralAccelerationJob resource."""
    if pvc_name is None:
        pvc_name = f"artifacts-{name}"

    spec = {
        "model": model,
        "input": {"type": "image", "path": input_path},
        "output": {"path": output_path},
        "resources": {"gpu": gpu},
        "ttlSecondsAfterFinished": ttl,
        "pvcTTLSecondsAfterFinished": pvc_ttl,
        "storageClass": storage_class,
        "pvcSize": pvc_size,
        "image": image,
    }

    if command:
        spec["command"] = command if isinstance(command, list) else command.split()

    body = {
        "apiVersion": "gpu.yourdomain.io/v1alpha1",
        "kind": "EphemeralAccelerationJob",
        "metadata": {"name": name, "namespace": namespace},
        "spec": spec,
    }

    try:
        custom_api.create_namespaced_custom_object(
            group="gpu.yourdomain.io",
            version="v1alpha1",
            namespace=namespace,
            plural="ephemeralaccelerationjobs",
            body=body,
        )
        print(f"✓ EphemeralAccelerationJob '{name}' created")
        return True
    except ApiException as e:
        if e.status == 409:
            print(f"✗ EphemeralAccelerationJob '{name}' already exists", file=sys.stderr)
        else:
            print(f"✗ Failed to create EphemeralAccelerationJob: {e}", file=sys.stderr)
            if e.body:
                try:
                    error_body = json.loads(e.body)
                    if "message" in error_body:
                        print(f"  {error_body['message']}", file=sys.stderr)
                except:
                    pass
        return False


def cmd_create(args):
    """Create an EphemeralAccelerationJob with optional project directory upload."""
    if not load_kubeconfig():
        sys.exit(1)

    v1 = client.CoreV1Api()
    custom_api = client.CustomObjectsApi()

    pvc_name = args.pvc_name or f"artifacts-{args.name}"

    # Create PVC if needed
    if args.project_dir or args.create_pvc:
        if not create_pvc(v1, pvc_name, args.namespace, args.storage_class, args.pvc_size):
            sys.exit(1)

        # Wait for PVC to be bound
        for _ in range(30):
            try:
                pvc = v1.read_namespaced_persistent_volume_claim(
                    name=pvc_name, namespace=args.namespace
                )
                if pvc.status.phase == "Bound":
                    break
            except ApiException:
                pass
            time.sleep(1)

    # Copy project directory if specified
    if args.project_dir:
        if not copy_to_pvc(v1, pvc_name, args.namespace, args.project_dir):
            sys.exit(1)

    # Create EphemeralAccelerationJob
    command = args.command.split() if args.command else None
    pvc_ttl = getattr(args, "pvc_ttl", 3600)  # Default 1 hour if not specified
    if not create_gpujob(
        custom_api,
        args.name,
        args.namespace,
        model=args.model,
        input_path=args.input_path,
        output_path=args.output_path,
        gpu=args.gpu,
        ttl=args.ttl,
        pvc_ttl=pvc_ttl,
        storage_class=args.storage_class,
        pvc_size=args.pvc_size,
        image=args.image,
        command=command,
        pvc_name=pvc_name,
    ):
        sys.exit(1)

    print(f"\nEphemeralAccelerationJob '{args.name}' is being processed.")
    print(f"Watch status: kubectl get ephemeralaccelerationjob {args.name} -n {args.namespace} -w")
    print(f"Check logs: kubectl logs -l app=gpu-job -n {args.namespace}")


def cmd_get(args):
    """Get EphemeralAccelerationJob status."""
    if not load_kubeconfig():
        sys.exit(1)

    custom_api = client.CustomObjectsApi()

    try:
        job = custom_api.get_namespaced_custom_object(
            group="gpu.yourdomain.io",
            version="v1alpha1",
            namespace=args.namespace,
            plural="ephemeralaccelerationjobs",
            name=args.name,
        )

        if args.output == "json":
            print(json.dumps(job, indent=2))
        else:
            spec = job.get("spec", {})
            status = job.get("status", {})

            print(f"EphemeralAccelerationJob: {args.name}")
            print(f"Namespace: {args.namespace}")
            print(f"\nSpec:")
            print(f"  Model: {spec.get('model', 'N/A')}")
            print(f"  Input: {spec.get('input', {}).get('path', 'N/A')}")
            print(f"  Output: {spec.get('output', {}).get('path', 'N/A')}")
            print(f"  GPU: {spec.get('resources', {}).get('gpu', 'N/A')}")
            print(f"  Image: {spec.get('image', 'N/A')}")

            print(f"\nStatus:")
            print(f"  Phase: {status.get('phase', 'Unknown')}")
            print(f"  Message: {status.get('message', 'N/A')}")
            if status.get("startedAt"):
                print(f"  Started: {status.get('startedAt')}")
            if status.get("finishedAt"):
                print(f"  Finished: {status.get('finishedAt')}")
            if status.get("artifactPath"):
                print(f"  Artifact: {status.get('artifactPath')}")
            if status.get("podName"):
                print(f"  Pod: {status.get('podName')}")

    except ApiException as e:
        if e.status == 404:
            print(f"✗ EphemeralAccelerationJob '{args.name}' not found", file=sys.stderr)
        else:
            print(f"✗ Error: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_list(args):
    """List EphemeralAccelerationJobs."""
    if not load_kubeconfig():
        sys.exit(1)

    custom_api = client.CustomObjectsApi()

    try:
        if args.namespace:
            response = custom_api.list_namespaced_custom_object(
                group="gpu.yourdomain.io",
                version="v1alpha1",
                namespace=args.namespace,
                plural="ephemeralaccelerationjobs",
            )
        else:
            response = custom_api.list_cluster_custom_object(
                group="gpu.yourdomain.io",
                version="v1alpha1",
                plural="ephemeralaccelerationjobs",
            )

        items = response.get("items", [])
        if not items:
            print("No EphemeralAccelerationJobs found.")
            return

        print(f"{'NAME':<30} {'NAMESPACE':<20} {'PHASE':<15} {'GPU':<5} {'MODEL':<20}")
        print("-" * 90)

        for item in items:
            metadata = item.get("metadata", {})
            spec = item.get("spec", {})
            status = item.get("status", {})

            name = metadata.get("name", "N/A")
            namespace = metadata.get("namespace", "N/A")
            phase = status.get("phase", "Unknown")
            gpu = spec.get("resources", {}).get("gpu", "N/A")
            model = spec.get("model", "N/A")

            print(f"{name:<30} {namespace:<20} {phase:<15} {gpu:<5} {model:<20}")

    except ApiException as e:
        print(f"✗ Error: {e}", file=sys.stderr)
        sys.exit(1)


def delete_pvc(v1, pvc_name, namespace):
    """Delete a PVC using Kubernetes client."""
    try:
        v1.delete_namespaced_persistent_volume_claim(
            name=pvc_name, namespace=namespace
        )
        print(f"✓ PVC '{pvc_name}' deleted")
        return True
    except ApiException as e:
        if e.status == 404:
            print(f"⚠ PVC '{pvc_name}' not found (may already be deleted)")
            return False
        else:
            print(f"✗ Error deleting PVC: {e}", file=sys.stderr)
            return False


def cmd_delete(args):
    """Delete an EphemeralAccelerationJob."""
    if not load_kubeconfig():
        sys.exit(1)

    custom_api = client.CustomObjectsApi()
    v1 = client.CoreV1Api()

    try:
        # Get job first to check TTL and status
        try:
            job = custom_api.get_namespaced_custom_object(
                group="gpu.yourdomain.io",
                version="v1alpha1",
                namespace=args.namespace,
                plural="ephemeralaccelerationjobs",
                name=args.name,
            )
            
            spec = job.get("spec", {})
            status = job.get("status", {})
            finished_at = status.get("finishedAt")
            ttl = spec.get("ttlSecondsAfterFinished", 0)
            
            # Check if TTL has passed and job is finished
            should_delete_pvc = False
            if finished_at and ttl > 0:
                try:
                    # Parse ISO format timestamp
                    finished_str = finished_at.replace("Z", "+00:00")
                    finished_time = datetime.fromisoformat(finished_str)
                    # Convert to UTC naive datetime
                    if finished_time.tzinfo:
                        utc_offset = finished_time.utcoffset()
                        finished_time = (finished_time - utc_offset).replace(tzinfo=None)
                    
                    elapsed = (datetime.utcnow() - finished_time).total_seconds()
                    if elapsed >= ttl:
                        should_delete_pvc = True
                        print(f"ℹ TTL ({ttl}s) has passed since job finished, PVC will be deleted")
                except Exception as e:
                    if args.delete_pvc:
                        print(f"⚠ Could not parse finishedAt time, will delete PVC anyway: {e}")
                    should_delete_pvc = args.delete_pvc
            
        except ApiException:
            pass  # Job might not exist, continue with deletion
        
        # Delete the job
        custom_api.delete_namespaced_custom_object(
            group="gpu.yourdomain.io",
            version="v1alpha1",
            namespace=args.namespace,
            plural="ephemeralaccelerationjobs",
            name=args.name,
        )
        print(f"✓ EphemeralAccelerationJob '{args.name}' deleted")

        # Delete PVC if requested or if TTL has passed
        if args.delete_pvc or should_delete_pvc:
            pvc_name = args.pvc_name or f"artifacts-{args.name}"
            delete_pvc(v1, pvc_name, args.namespace)

    except ApiException as e:
        if e.status == 404:
            print(f"✗ EphemeralAccelerationJob '{args.name}' not found", file=sys.stderr)
        else:
            print(f"✗ Error: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_watch(args):
    """Watch EphemeralAccelerationJob status."""
    if not load_kubeconfig():
        sys.exit(1)

    custom_api = client.CustomObjectsApi()

    print(f"Watching EphemeralAccelerationJob '{args.name}' (Ctrl+C to stop)...")
    print()

    try:
        while True:
            try:
                job = custom_api.get_namespaced_custom_object(
                    group="gpu.yourdomain.io",
                    version="v1alpha1",
                    namespace=args.namespace,
                    plural="ephemeralaccelerationjobs",
                    name=args.name,
                )

                status = job.get("status", {})
                phase = status.get("phase", "Unknown")
                message = status.get("message", "")

                print(f"\r[{phase}] {message}", end="", flush=True)

                if phase in ["Succeeded", "Failed"]:
                    print()
                    break

            except ApiException as e:
                if e.status == 404:
                    print(f"\n✗ EphemeralAccelerationJob '{args.name}' not found", file=sys.stderr)
                    break

            time.sleep(2)

    except KeyboardInterrupt:
        print("\nStopped watching.")


def cmd_cleanup(args):
    """Clean up PVCs for finished jobs based on TTL."""
    if not load_kubeconfig():
        sys.exit(1)

    custom_api = client.CustomObjectsApi()
    v1 = client.CoreV1Api()

    try:
        # Get all jobs
        if args.namespace:
            response = custom_api.list_namespaced_custom_object(
                group="gpu.yourdomain.io",
                version="v1alpha1",
                namespace=args.namespace,
                plural="ephemeralaccelerationjobs",
            )
        else:
            response = custom_api.list_cluster_custom_object(
                group="gpu.yourdomain.io",
                version="v1alpha1",
                plural="ephemeralaccelerationjobs",
            )

        items = response.get("items", [])
        if not items:
            print("No EphemeralAccelerationJobs found.")
            return

        now = datetime.utcnow()
        deleted_count = 0
        skipped_count = 0

        print(f"Checking {len(items)} job(s) for PVC cleanup...")
        print()

        for item in items:
            metadata = item.get("metadata", {})
            spec = item.get("spec", {})
            status = item.get("status", {})

            name = metadata.get("name")
            namespace = metadata.get("namespace", "default")
            phase = status.get("phase")
            finished_at = status.get("finishedAt")
            ttl = spec.get("ttlSecondsAfterFinished", 0)

            # Only process finished jobs
            if phase not in ["Succeeded", "Failed"]:
                if args.verbose:
                    print(f"⏭ {name}: Job not finished (phase: {phase})")
                skipped_count += 1
                continue

            # If TTL is 0, skip (no automatic cleanup)
            if ttl == 0:
                if args.verbose:
                    print(f"⏭ {name}: TTL is 0 (no automatic cleanup)")
                skipped_count += 1
                continue

            # Check if TTL has passed
            if not finished_at:
                if args.verbose:
                    print(f"⏭ {name}: No finishedAt timestamp")
                skipped_count += 1
                continue

            try:
                finished_time = datetime.fromisoformat(finished_at.replace("Z", "+00:00"))
                if finished_time.tzinfo:
                    finished_time = finished_time.replace(tzinfo=None) - finished_time.utcoffset()
                
                elapsed = (now - finished_time).total_seconds()
                
                if elapsed >= ttl:
                    pvc_name = f"artifacts-{name}"
                    print(f"🗑 {name}: TTL expired ({elapsed:.0f}s >= {ttl}s), deleting PVC '{pvc_name}'...")
                    
                    if delete_pvc(v1, pvc_name, namespace):
                        deleted_count += 1
                else:
                    remaining = ttl - elapsed
                    if args.verbose:
                        print(f"⏳ {name}: TTL not yet met ({remaining:.0f}s remaining)")
                    skipped_count += 1

            except Exception as e:
                print(f"✗ {name}: Error processing: {e}", file=sys.stderr)
                skipped_count += 1

        print()
        print(f"Summary: {deleted_count} PVC(s) deleted, {skipped_count} skipped")

    except ApiException as e:
        print(f"✗ Error: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_copy_file(args):
    """Copy a file from URL into PVC using a temporary pod."""
    if not load_kubeconfig():
        sys.exit(1)

    v1 = client.CoreV1Api()
    
    pvc_name = args.pvc_name or f"artifacts-{args.job_name}"
    pod_name = f"copy-file-{args.job_name}-{int(time.time())}"
    
    # Verify PVC exists
    try:
        pvc = v1.read_namespaced_persistent_volume_claim(
            name=pvc_name, namespace=args.namespace
        )
        if pvc.status.phase != "Bound":
            print(f"⚠ PVC '{pvc_name}' exists but is not bound yet", file=sys.stderr)
    except ApiException as e:
        if e.status == 404:
            print(f"✗ PVC '{pvc_name}' not found. Create it first or specify --pvc-name", file=sys.stderr)
            sys.exit(1)
        else:
            print(f"✗ Error checking PVC: {e}", file=sys.stderr)
            sys.exit(1)
    
    # Determine target path
    target_path = args.target_path
    if not target_path.startswith("/"):
        target_path = f"/artifacts/{target_path}"
    
    print(f"Downloading '{args.url}' to PVC '{pvc_name}' at '{target_path}'...")
    
    # Create pod with PVC mount
    copy_pod = client.V1Pod(
        metadata=client.V1ObjectMeta(name=pod_name, namespace=args.namespace),
        spec=client.V1PodSpec(
            restart_policy="Never",
            containers=[
                client.V1Container(
                    name="copy",
                    image="busybox:latest",
                    command=["sh", "-c", f"wget -O {target_path} {args.url} && ls -lh {target_path}"],
                    volume_mounts=[
                        client.V1VolumeMount(
                            name="artifacts", mount_path="/artifacts"
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
    
    try:
        # Create pod
        v1.create_namespaced_pod(namespace=args.namespace, body=copy_pod)
        print(f"Created pod '{pod_name}'...")
        
        # Wait for pod to complete
        for _ in range(60):
            try:
                pod = v1.read_namespaced_pod(name=pod_name, namespace=args.namespace)
                phase = pod.status.phase
                
                if phase == "Succeeded":
                    # Get pod logs to show the result
                    logs = v1.read_namespaced_pod_log(
                        name=pod_name, namespace=args.namespace
                    )
                    if logs:
                        print(logs)
                    print(f"✓ File downloaded successfully to '{target_path}'")
                    break
                elif phase == "Failed":
                    # Get pod logs for error
                    try:
                        logs = v1.read_namespaced_pod_log(
                            name=pod_name, namespace=args.namespace
                        )
                        print(f"✗ Pod failed: {logs}", file=sys.stderr)
                    except:
                        print(f"✗ Pod failed", file=sys.stderr)
                    sys.exit(1)
            except ApiException:
                pass
            time.sleep(1)
        else:
            print("✗ Pod did not complete in time", file=sys.stderr)
            sys.exit(1)
    
    except Exception as e:
        print(f"✗ Error: {e}", file=sys.stderr)
        sys.exit(1)
    finally:
        # Clean up pod
        try:
            v1.delete_namespaced_pod(name=pod_name, namespace=args.namespace, grace_period_seconds=0)
        except ApiException:
            pass


def cmd_debug(args):
    """Create a debug pod with PVC mounted for interactive access."""
    if not load_kubeconfig():
        sys.exit(1)

    v1 = client.CoreV1Api()
    
    pvc_name = args.pvc_name or f"artifacts-{args.job_name}"
    pod_name = args.pod_name or f"debug-{args.job_name}-{int(time.time())}"
    
    # Verify PVC exists
    try:
        pvc = v1.read_namespaced_persistent_volume_claim(
            name=pvc_name, namespace=args.namespace
        )
        if pvc.status.phase != "Bound":
            print(f"⚠ PVC '{pvc_name}' exists but is not bound yet", file=sys.stderr)
    except ApiException as e:
        if e.status == 404:
            print(f"✗ PVC '{pvc_name}' not found. Create it first or specify --pvc-name", file=sys.stderr)
            sys.exit(1)
        else:
            print(f"✗ Error checking PVC: {e}", file=sys.stderr)
            sys.exit(1)
    
    # Check if pod already exists
    try:
        existing_pod = v1.read_namespaced_pod(name=pod_name, namespace=args.namespace)
        if existing_pod.status.phase in ["Running", "Pending"]:
            print(f"Pod '{pod_name}' already exists. Use --pod-name to specify a different name.")
            print(f"To exec into existing pod: kubectl exec -it {pod_name} -n {args.namespace} -- sh")
            sys.exit(1)
    except ApiException:
        pass  # Pod doesn't exist, continue
    
    print(f"Creating debug pod '{pod_name}' with PVC '{pvc_name}' mounted at '/mnt'...")
    
    # Create debug pod
    debug_pod = client.V1Pod(
        metadata=client.V1ObjectMeta(name=pod_name, namespace=args.namespace),
        spec=client.V1PodSpec(
            restart_policy="Never",
            containers=[
                client.V1Container(
                    name="debug",
                    image=args.image,
                    command=["sh"],
                    stdin=True,
                    tty=True,
                    volume_mounts=[
                        client.V1VolumeMount(
                            name="artifacts", mount_path="/mnt"
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
    
    try:
        # Create pod
        v1.create_namespaced_pod(namespace=args.namespace, body=debug_pod)
        print(f"✓ Pod '{pod_name}' created")
        
        # Wait for pod to be ready
        print("Waiting for pod to be ready...")
        for _ in range(30):
            try:
                pod = v1.read_namespaced_pod(name=pod_name, namespace=args.namespace)
                if pod.status.phase == "Running":
                    break
            except ApiException:
                pass
            time.sleep(1)
        else:
            print("⚠ Pod may not be ready yet")
        
        print(f"\n✓ Debug pod is ready!")
        print(f"\nTo access the pod, run:")
        print(f"  kubectl exec -it {pod_name} -n {args.namespace} -- sh")
        print(f"\nThe PVC is mounted at /mnt")
        
        if args.exec:
            # Attempt to exec into the pod
            print(f"\nAttempting to exec into pod...")
            print("Note: Interactive TTY may not work perfectly. If it doesn't, use kubectl exec manually.")
            try:
                exec_response = v1.connect_get_namespaced_pod_exec(
                    name=pod_name,
                    namespace=args.namespace,
                    command=["sh"],
                    stdout=True,
                    stderr=True,
                    stdin=True,
                    tty=True,
                )
                # Note: The Python client's exec doesn't provide true interactive TTY
                # So we just print instructions
                print("For full interactive access, use: kubectl exec -it ...")
            except Exception as e:
                print(f"Note: Direct exec not available. Use kubectl: {e}")
        
        if not args.keep:
            print(f"\nNote: Pod will remain running. Delete it with:")
            print(f"  kubectl delete pod {pod_name} -n {args.namespace}")
            print(f"Or use --keep flag to keep it running")
    
    except Exception as e:
        print(f"✗ Error: {e}", file=sys.stderr)
        sys.exit(1)


def main():
    """Main CLI entrypoint."""
    parser = argparse.ArgumentParser(
        description="Ephemeral GPU Job CLI - Manage EphemeralAccelerationJob resources like native K8s resources",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Create a job with project directory
  %(prog)s create my-job --project-dir ./my-code --input-path /artifacts/image.jpg

  # Create a job with custom settings
  %(prog)s create training --model resnet50 --gpu 1 --ttl 3600

  # Download a file into PVC
  %(prog)s copy-file my-job https://example.com/image.jpg --target-path /artifacts/input.jpg

  # Create debug pod for interactive access
  %(prog)s debug my-job

  # Watch job status
  %(prog)s watch my-job

  # Get job details
  %(prog)s get my-job

  # List all jobs
  %(prog)s list

  # Delete job and PVC
  %(prog)s delete my-job --delete-pvc

  # Clean up PVCs for all finished jobs (based on TTL)
  %(prog)s cleanup

  # Clean up PVCs in specific namespace
  %(prog)s cleanup --namespace gpu-demo --verbose
        """,
    )

    subparsers = parser.add_subparsers(dest="command", help="Command to execute")

    # Create command
    create_parser = subparsers.add_parser("create", help="Create an EphemeralAccelerationJob")
    create_parser.add_argument("name", help="EphemeralAccelerationJob name")
    create_parser.add_argument(
        "--namespace", "-n", default="default", help="Kubernetes namespace"
    )
    create_parser.add_argument(
        "--model",
        choices=["resnet50", "mobilenet_v3_small"],
        default="resnet50",
        help="Model to use (default: resnet50)",
    )
    create_parser.add_argument(
        "--input-path",
        default="/artifacts/input.jpg",
        help="Input image path in PVC (default: /artifacts/input.jpg)",
    )
    create_parser.add_argument(
        "--output-path",
        default="/artifacts/output.json",
        help="Output JSON path in PVC (default: /artifacts/output.json)",
    )
    create_parser.add_argument(
        "--gpu", type=int, default=1, help="Number of GPUs (default: 1)"
    )
    create_parser.add_argument(
        "--ttl",
        type=int,
        default=0,
        help="TTL in seconds after finished for pod (0 = delete immediately, default: 0)",
    )
    create_parser.add_argument(
        "--pvc-ttl",
        type=int,
        default=3600,
        help="TTL in seconds after finished for PVC (0 = delete immediately, default: 3600 = 1 hour)",
    )
    create_parser.add_argument(
        "--project-dir",
        help="Local directory to copy into PVC (creates PVC if needed)",
    )
    create_parser.add_argument(
        "--create-pvc",
        action="store_true",
        help="Create PVC even if project-dir is not specified",
    )
    create_parser.add_argument(
        "--pvc-name", help="PVC name (default: artifacts-<job-name>)"
    )
    create_parser.add_argument(
        "--storage-class",
        default="longhorn",
        help="Storage class for PVC (default: longhorn)",
    )
    create_parser.add_argument(
        "--pvc-size", default="1Gi", help="PVC size (default: 1Gi)"
    )
    create_parser.add_argument(
        "--image",
        default="gpu-job-inference:latest",
        help="Job container image (default: gpu-job-inference:latest)",
    )
    create_parser.add_argument(
        "--command", help="Command to run (space-separated, optional)"
    )
    create_parser.set_defaults(func=cmd_create)

    # Get command
    get_parser = subparsers.add_parser("get", help="Get EphemeralAccelerationJob status")
    get_parser.add_argument("name", help="EphemeralAccelerationJob name")
    get_parser.add_argument(
        "--namespace", "-n", default="default", help="Kubernetes namespace"
    )
    get_parser.add_argument(
        "--output", "-o", choices=["json", "wide"], default="wide", help="Output format"
    )
    get_parser.set_defaults(func=cmd_get)

    # List command
    list_parser = subparsers.add_parser("list", help="List EphemeralAccelerationJobs")
    list_parser.add_argument(
        "--namespace", "-n", help="Filter by namespace (all namespaces if not specified)"
    )
    list_parser.set_defaults(func=cmd_list)

    # Watch command
    watch_parser = subparsers.add_parser("watch", help="Watch EphemeralAccelerationJob status")
    watch_parser.add_argument("name", help="EphemeralAccelerationJob name")
    watch_parser.add_argument(
        "--namespace", "-n", default="default", help="Kubernetes namespace"
    )
    watch_parser.set_defaults(func=cmd_watch)

    # Delete command
    delete_parser = subparsers.add_parser("delete", help="Delete an EphemeralAccelerationJob")
    delete_parser.add_argument("name", help="EphemeralAccelerationJob name")
    delete_parser.add_argument(
        "--namespace", "-n", default="default", help="Kubernetes namespace"
    )
    delete_parser.add_argument(
        "--delete-pvc",
        action="store_true",
        help="Also delete associated PVC (or auto-delete if TTL has passed)",
    )
    delete_parser.add_argument(
        "--pvc-name", help="PVC name to delete (default: artifacts-<job-name>)"
    )
    delete_parser.set_defaults(func=cmd_delete)

    # Cleanup command
    cleanup_parser = subparsers.add_parser(
        "cleanup", help="Clean up PVCs for finished jobs based on TTL"
    )
    cleanup_parser.add_argument(
        "--namespace", "-n", help="Filter by namespace (all namespaces if not specified)"
    )
    cleanup_parser.add_argument(
        "--verbose", "-v", action="store_true", help="Show detailed output"
    )
    cleanup_parser.set_defaults(func=cmd_cleanup)

    # Copy-file command
    copy_file_parser = subparsers.add_parser(
        "copy-file", help="Download a file from URL into PVC"
    )
    copy_file_parser.add_argument(
        "job_name", help="Job name (used to determine PVC name: artifacts-<job-name>)"
    )
    copy_file_parser.add_argument(
        "url", help="URL to download from"
    )
    copy_file_parser.add_argument(
        "--namespace", "-n", default="default", help="Kubernetes namespace"
    )
    copy_file_parser.add_argument(
        "--pvc-name", help="PVC name (default: artifacts-<job-name>)"
    )
    copy_file_parser.add_argument(
        "--target-path", default="/artifacts/input.jpg",
        help="Target path in PVC (default: /artifacts/input.jpg)"
    )
    copy_file_parser.set_defaults(func=cmd_copy_file)

    # Debug command
    debug_parser = subparsers.add_parser(
        "debug", help="Create a debug pod with PVC mounted for interactive access"
    )
    debug_parser.add_argument(
        "job_name", help="Job name (used to determine PVC name: artifacts-<job-name>)"
    )
    debug_parser.add_argument(
        "--namespace", "-n", default="default", help="Kubernetes namespace"
    )
    debug_parser.add_argument(
        "--pvc-name", help="PVC name (default: artifacts-<job-name>)"
    )
    debug_parser.add_argument(
        "--pod-name", help="Pod name (default: debug-<job-name>-<timestamp>)"
    )
    debug_parser.add_argument(
        "--image", default="busybox:latest",
        help="Container image (default: busybox:latest)"
    )
    debug_parser.add_argument(
        "--exec", action="store_true",
        help="Attempt to exec into pod (may not work for interactive TTY)"
    )
    debug_parser.add_argument(
        "--keep", action="store_true",
        help="Keep pod running (default: show instructions to delete)"
    )
    debug_parser.set_defaults(func=cmd_debug)

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    args.func(args)


if __name__ == "__main__":
    main()
