import json
import os
import re
import shutil
import subprocess
import tempfile
from typing import Annotated, Any, Dict, List, Optional, Union


def _summarize_resource_data(
    items: List[Dict[str, Any]], resource_type: str
) -> List[Dict[str, Any]]:
    """
    Internal helper to strip 90% of Kubernetes metadata (managedFields, ownerReferences,
    finalizers, etc.) to keep token counts low for the LLM.
    """
    summary = []
    r_type = resource_type.lower()

    for item in items:
        meta = item.get("metadata", {})
        status = item.get("status", {})
        spec = item.get("spec", {})

        base = {
            "name": meta.get("name"),
            "namespace": meta.get("namespace"),
            "creationTimestamp": meta.get("creationTimestamp"),
        }

        if "pod" in r_type:
            container_statuses = status.get("containerStatuses", [{}])
            base.update(
                {
                    "phase": status.get("phase"),
                    "podIP": status.get("podIP"),
                    "node": spec.get("nodeName"),
                    "restarts": sum(c.get("restartCount", 0) for c in container_statuses),
                    "containers": [c.get("name") for c in spec.get("containers", [])],
                }
            )
        elif "node" in r_type:
            conds = status.get("conditions", [])
            ready = next((c.get("status") for c in conds if c.get("type") == "Ready"), "Unknown")
            base.update(
                {
                    "ready": ready,
                    "instance_type": meta.get("labels", {}).get("node.kubernetes.io/instance-type"),
                    "cpu": status.get("capacity", {}).get("cpu"),
                    "memory": status.get("capacity", {}).get("memory"),
                }
            )
        elif "deployment" in r_type or "replicaset" in r_type or "statefulset" in r_type:
            base.update(
                {
                    "replicas_desired": spec.get("replicas"),
                    "replicas_ready": status.get("readyReplicas", 0),
                    "replicas_updated": status.get("updatedReplicas", 0),
                }
            )
        elif "service" in r_type:
            base.update(
                {
                    "type": spec.get("type"),
                    "clusterIP": spec.get("clusterIP"),
                    "externalIP": status.get("loadBalancer", {}).get("ingress", [{}])[0].get("ip"),
                    "ports": spec.get("ports"),
                }
            )
        elif "event" in r_type:
            base = {
                "lastTimestamp": item.get("lastTimestamp"),
                "type": item.get("type"),
                "reason": item.get("reason"),
                "object": item.get("involvedObject", {}).get("name"),
                "message": item.get("message"),
            }
        else:
            # Generic fallback for less common types
            base["status"] = status.get("phase") or "N/A"

        summary.append(base)
    return summary


def run_kubectl(args: List[str], json_output: bool = False) -> subprocess.CompletedProcess:
    """Executes a kubectl command safely using subprocess."""
    kubectl_bin = shutil.which("kubectl")
    if not kubectl_bin:
        raise FileNotFoundError("kubectl executable not found on system path.")
    cmd = [kubectl_bin] + args
    if json_output:
        cmd.extend(["-o", "json"])
    return subprocess.run(cmd, capture_output=True, text=True, check=False)


def kubectl_get(
    resource_type: Annotated[str, "The type of resource (e.g., 'pods', 'nodes', 'deployments')."],
    name: Annotated[Optional[str], "Specific name of the resource instance."] = None,
    namespace: Annotated[Optional[str], "Namespace scope. Use 'all' for all namespaces."] = None,
    label_selector: Annotated[Optional[str], "Filter by labels (e.g., 'app=nginx')."] = None,
    verbose: Annotated[
        bool, "If True, returns the full raw JSON. If False, returns a summarized version."
    ] = False,
) -> KubeResult:
    """
    Retrieves information about Kubernetes resources.

    Args:
        resource_type: The Kubernetes resource category.
        name: Optional name of a specific resource.
        namespace: The namespace to query. Defaults to current context.
        label_selector: Kubernetes label query string.
        verbose: Toggle between a token-efficient summary and full resource data.

    Guidance for LLM Agent:
        - ALWAYS start with verbose=False. This provides the 'vital signs' of a resource.
        - Only switch to verbose=True if you need to see deep spec details, like environment variables,
          volume mounts, or exact affinity rules that are not in the summary.
    """
    args = ["get", resource_type]
    if namespace == "all":
        args.append("--all-namespaces")
    elif namespace:
        args.extend(["-n", namespace])
    if label_selector:
        args.extend(["-l", label_selector])
    if name:
        args.append(name)

    try:
        result = run_kubectl(args, json_output=True)
        if result.returncode != 0:
            return {"success": False, "data": [], "error": result.stderr.strip()}

        data = json.loads(result.stdout)
        items = data.get("items", []) if "items" in data else [data]

        if not verbose:
            data = _summarize_resource_data(items, resource_type)
        else:
            data = items

        return {"success": True, "data": data, "error": None}
    except Exception as e:
        return {"success": False, "data": [], "error": str(e)}


def kubectl_describe(
    resource_type: Annotated[str, "Resource type (e.g., 'pod')."],
    name: Annotated[str, "Name of the resource."],
    namespace: Annotated[Optional[str], "Namespace of the resource."] = None,
    verbose: Annotated[
        bool, "If False, returns only the first 50 lines (usually enough for errors)."
    ] = False,
) -> KubeResult:
    """
    Provides a human-readable, detailed description of a resource.

    Args:
        resource_type: Resource category.
        name: Name of the instance.
        namespace: Target namespace.
        verbose: Whether to return the full description or a truncated version.

    Guidance for LLM Agent:
        - Use this tool when you see a resource in a 'Pending' or 'Failed' state from 'kubectl_get'.
        - 'describe' is better for seeing event history and 'Reason' codes for failures.
        - Use verbose=True if the error message in the first 50 lines is cut off.
    """
    args = ["describe", resource_type, name]
    if namespace:
        args.extend(["-n", namespace])

    result = run_kubectl(args)
    if result.returncode != 0:
        return {"success": False, "data": "", "error": result.stderr.strip()}

    output = result.stdout.strip()
    if not verbose:
        lines = output.splitlines()
        if len(lines) > 50:
            output = (
                "\n".join(lines[:50])
                + "\n... [Output Truncated. Use verbose=True for full text] ..."
            )

    return {"success": True, "data": output, "error": None}


def kubectl_logs(
    pod_name: Annotated[str, "Name of the pod."],
    namespace: Annotated[Optional[str], "Namespace of the pod."] = None,
    container: Annotated[Optional[str], "Container name for multi-container pods."] = None,
    tail: Annotated[int, "Lines from the end of the logs."] = 100,
    verbose: Annotated[
        bool, "If True, ignores the 'tail' limit and returns more context (max 1000 lines)."
    ] = False,
) -> KubeResult:
    """
    Fetches the logs for a specific pod or container.

    Args:
        pod_name: Target pod name.
        namespace: Namespace scope.
        container: Specific container.
        tail: Number of lines to fetch.
        verbose: Set to True to fetch a larger window of logs (1000 lines).

    Guidance for LLM Agent:
        - Use this to diagnose application-level crashes or errors.
        - Start with the default tail=100.
        - Only use verbose=True or a high tail count if you are searching for a specific stack trace
          that occurred further back in time.
    """
    line_count = 1000 if verbose else tail
    args = ["logs", pod_name, f"--tail={line_count}"]
    if namespace:
        args.extend(["-n", namespace])
    if container:
        args.extend(["-c", container])

    result = run_kubectl(args)
    if result.returncode != 0:
        return {"success": False, "data": "", "error": result.stderr.strip()}

    return {"success": True, "data": result.stdout.strip(), "error": None}


def kubectl_get_events(
    namespace: Annotated[Optional[str], "Namespace or 'all'."] = None,
    verbose: Annotated[
        bool, "If False, returns only the 10 most recent events summarized."
    ] = False,
) -> KubeResult:
    """
    Retrieves cluster events to diagnose scheduling or lifecycle issues.

    Args:
        namespace: Target namespace or 'all'.
        verbose: Whether to show all fields and more events.

    Guidance for LLM Agent:
        - This is the first tool you should use if a pod is stuck in 'ImagePullBackOff', 'Pending', or 'CrashLoopBackOff'.
        - verbose=False (default) provides a high-level summary of the most recent 10 events.
    """
    args = ["get", "events", "--sort-by=.lastTimestamp"]
    if namespace == "all":
        args.append("--all-namespaces")
    elif namespace:
        args.extend(["-n", namespace])

    try:
        result = run_kubectl(args, json_output=True)
        data = json.loads(result.stdout)
        items = data.get("items", [])

        # Events are sorted by time; we usually only want the newest
        if not verbose:
            items = _summarize_resource_data(items[-10:], "event")

        return {"success": True, "data": items, "error": None}
    except Exception as e:
        return {"success": False, "data": [], "error": str(e)}


def kubectl_exec(
    pod_name: Annotated[str, "Name of the pod."],
    command: Annotated[List[str], "Command as list, e.g., ['ls', '-l']."],
    namespace: Annotated[Optional[str], "Namespace scope."] = None,
    container: Annotated[Optional[str], "Target container."] = None,
    verbose: Annotated[bool, "If False, truncates output to 1000 characters."] = False,
) -> KubeActionResponse:
    """
    Executes a command inside a running container.

    Args:
        pod_name: Target pod.
        command: Command and arguments.
        namespace: Target namespace.
        container: Specific container.
        verbose: Toggle for full output vs. truncated output.

    Guidance for LLM Agent:
        - Use this for deep inspection (e.g., 'cat' a config file, 'curl' a local endpoint).
        - Be cautious: commands like 'top' or long-running processes will fail or hang.
    """
    args = ["exec", pod_name]
    if namespace:
        args.extend(["-n", namespace])
    if container:
        args.extend(["-c", container])
    args.append("--")
    args.extend(command)

    result = run_kubectl(args)
    output = result.stdout.strip() if result.returncode == 0 else result.stderr.strip()

    if not verbose and len(output) > 1000:
        output = output[:1000] + "\n... [Output Truncated. Use verbose=True for full output] ..."

    return {
        "success": result.returncode == 0,
        "output": output,
        "exit_code": result.returncode,
    }


def kubectl_apply(
    manifest: Annotated[str, "A valid Kubernetes YAML or JSON string."],
    verbose: Annotated[bool, "Whether to return the full detailed status of the apply."] = False,
) -> KubeActionResponse:
    """
    Applies a configuration to a resource from a manifest string.

    Args:
        manifest: The YAML/JSON content to apply.
        verbose: If True, provides extra output details if available.

    Guidance for LLM Agent:
        - Use this to create or update resources (Deployments, Services, etc.).
        - Ensure the manifest is properly formatted YAML.
    """
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        f.write(manifest)
        temp_path = f.name
    try:
        result = run_kubectl(["apply", "-f", temp_path])
        return {
            "success": result.returncode == 0,
            "output": result.stdout.strip() if result.returncode == 0 else result.stderr.strip(),
            "exit_code": result.returncode,
        }
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)


def kubectl_delete(
    resource_type: Annotated[str, "Type of resource."],
    name: Annotated[str, "Name of the resource."],
    namespace: Annotated[Optional[str], "Namespace scope."] = None,
) -> KubeActionResponse:
    """
    Deletes a specific resource from the cluster.

    Args:
        resource_type: Category (pod, svc, etc.).
        name: Instance name.
        namespace: Target namespace.

    Guidance for LLM Agent:
        - Use this to remove resources. Be careful deleting namespaces or critical system pods.
    """
    args = ["delete", resource_type, name]
    if namespace:
        args.extend(["-n", namespace])
    result = run_kubectl(args)
    return {
        "success": result.returncode == 0,
        "output": result.stdout.strip() if result.returncode == 0 else result.stderr.strip(),
        "exit_code": result.returncode,
    }
