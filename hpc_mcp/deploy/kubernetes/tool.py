import json
import os
import re
import shutil
import subprocess
import tempfile
from typing import Annotated, Any, Dict, List, Optional, TypedDict, Union

AutoscalerConfigResult = Annotated[
    Dict[str, Any],
    "A structured report containing the discovered autoscaler type, "
    "the raw configuration data, and a list of potential instance types if found.",
]


class KubeResourceResponse(TypedDict):
    success: Annotated[bool, "Whether the kubectl command executed successfully."]
    data: Annotated[
        Union[List[Dict[str, Any]], str],
        "The retrieved resource data (list of objects) or string output.",
    ]
    error: Annotated[Optional[str], "The error message if success is False, otherwise None."]


class KubeActionResponse(TypedDict):
    success: Annotated[bool, "Whether the command executed with a zero exit code."]
    output: Annotated[str, "The stdout or stderr of the command."]
    exit_code: Annotated[int, "The process exit code."]


KubeResult = Annotated[
    Dict[str, Any],
    "A structured result containing 'success' (bool), 'data' (parsed JSON or string), "
    "and 'error' (str or None) if the command failed.",
]


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
        elif any(x in r_type for x in ["deployment", "replicaset", "statefulset"]):
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
                    "ports": spec.get("ports"),
                }
            )
        elif "event" in r_type:
            base = {
                "lastTimestamp": item.get("lastTimestamp") or item.get("eventTime"),
                "type": item.get("type"),
                "reason": item.get("reason"),
                "object": item.get("involvedObject", {}).get("name"),
                "message": item.get("message"),
            }
        else:
            base["status"] = status.get("phase") or "N/A"

        summary.append(base)
    return summary


def run_kubectl(args: List[str], json_output: bool = False) -> subprocess.CompletedProcess:
    """
    Executes a kubectl command using subprocess.
    """
    kubectl_bin = shutil.which("kubectl")
    if not kubectl_bin:
        raise FileNotFoundError("kubectl executable not found on system path.")
    cmd = [kubectl_bin] + args
    if json_output:
        cmd.extend(["-o", "json"])
    return subprocess.run(cmd, capture_output=True, text=True, check=False)


def kubectl_get(
    resource_type: Annotated[
        str,
        "The type of Kubernetes resource to fetch. Examples: 'pods', 'nodes', 'deployments', 'services', 'configmaps'.",
    ],
    name: Annotated[
        Optional[str],
        "Specific name of the resource instance to fetch. If omitted, lists all resources of this type.",
    ] = None,
    namespace: Annotated[
        Optional[str],
        "Namespace scope. Use 'all' for all namespaces. If omitted, uses the current context namespace.",
    ] = None,
    label_selector: Annotated[
        Optional[str], "Kubernetes label selector query string, e.g., 'app=nginx,tier=frontend'."
    ] = None,
    verbose: Annotated[
        bool,
        "If True, returns the full raw JSON. If False, returns a summarized version to save tokens.",
    ] = False,
) -> Annotated[
    KubeResourceResponse,
    "Dictionary containing success status and list of summarized or full resource data.",
]:
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
    resource_type: Annotated[
        str, "The type of resource to describe (e.g., 'pod', 'node', 'deployment')."
    ],
    name: Annotated[str, "The name of the specific resource instance."],
    namespace: Annotated[Optional[str], "The namespace of the resource."] = None,
    verbose: Annotated[
        bool, "If False, returns only the first 50 lines. Use True for the full text."
    ] = False,
) -> Annotated[
    KubeResourceResponse,
    "Dictionary containing success status and the human-readable description string.",
]:
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


def kubectl_label(
    resource_type: Annotated[str, "Resource type (e.g., 'node')."],
    name: Annotated[str, "Name of the resource."],
    labels: Annotated[Dict[str, str], "A dictionary of labels to apply."],
    namespace: Annotated[Optional[str], "Namespace scope."] = None,
    overwrite: Annotated[bool, "Whether to overwrite existing labels."] = True,
) -> KubeActionResponse:
    """
    Adds or updates labels on a Kubernetes resource.

    Args:
        resource_type: Category (pod, node, etc.).
        name: Target name.
        labels: Key-value pairs to set.
        overwrite: If True, replaces existing keys.
    """
    label_strings = [f"{k}={v}" for k, v in labels.items()]
    args = ["label", resource_type, name] + label_strings
    if namespace:
        args.extend(["-n", namespace])
    if overwrite:
        args.append("--overwrite")

    result = run_kubectl(args)
    return {
        "success": result.returncode == 0,
        "output": result.stdout.strip() if result.returncode == 0 else result.stderr.strip(),
        "exit_code": result.returncode,
    }


def kubectl_unique_logs(
    pod_name: Annotated[str, "The name of the pod to fetch logs from."],
    namespace: Annotated[Optional[str], "Namespace of the pod."] = None,
    container: Annotated[
        Optional[str], "Specific container name for pods with multiple containers."
    ] = None,
) -> Annotated[
    KubeResourceResponse, "Dictionary containing success status and the log string data."
]:
    """
    Fetches the logs for a specific pod or container, but only unique lines to reduce size.

    Args:
        pod_name: Target pod name.
        namespace: Namespace scope.
        container: Specific container.
        tail: Number of lines to fetch.

    Guidance for LLM Agent:
        - Use this to diagnose application-level crashes or errors.
        - Remember that lines may appear again, but have been filtered.
        - Frequency of lines are not meaningful
    """
    logs = kubectl_logs(pod_name, namespace, container)
    lines = (logs.get("data") or "").split("\n")
    ordered_set_keys = dict.fromkeys(lines)
    # Get the elements as an iterable of keys
    logs["data"] = "\n".join(list(ordered_set_keys.keys()))
    return logs


def kubectl_logs(
    pod_name: Annotated[str, "The name of the pod to fetch logs from."],
    namespace: Annotated[Optional[str], "Namespace of the pod."] = None,
    container: Annotated[
        Optional[str], "Specific container name for pods with multiple containers."
    ] = None,
    tail: Annotated[int, "Number of lines to fetch from the end of the logs. Default 100."] = 100,
    verbose: Annotated[bool, "If True, ignores 'tail' and returns up to 1000 lines."] = False,
) -> Annotated[
    KubeResourceResponse, "Dictionary containing success status and the log string data."
]:
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
    namespace: Annotated[
        Optional[str], "Namespace to filter by. Use 'all' for cluster-wide events."
    ] = None,
    verbose: Annotated[bool, "If False, returns a summary of the 10 most recent events."] = False,
) -> Annotated[
    KubeResourceResponse, "Dictionary containing success status and a list of event objects."
]:
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


def kubectl_explain(
    resource_path: Annotated[
        str,
        "The resource or field to explain (e.g., 'pod', 'deployment.spec.template.spec.containers').",
    ],
    recursive: Annotated[bool, "If True, shows documentation for all nested child fields."] = False,
) -> KubeResult:
    """
    Provides detailed documentation and schema definitions for Kubernetes resources and fields.

    Use this tool when you need to understand the structure of a specific resource,
    discover which fields are available in a spec, or verify the data type required
    for a manifest property.

    Args:
        resource_path: The dot-notation path to the resource or field of interest.
        recursive: Whether to expand all sub-fields in the documentation output.

    Returns:
        A dictionary containing:
            - 'success' (bool): True if the explanation was retrieved.
            - 'data' (str): The documentation text provided by the Kubernetes API.
            - 'error' (str, optional): Error message if the resource path is invalid.
    """
    args = ["explain", resource_path]
    if recursive:
        args.append("--recursive")

    try:
        # explain does not support -o json, so we treat it as raw text
        result = run_kubectl(args)
        if result.returncode != 0:
            return {"success": False, "data": "", "error": result.stderr.strip()}

        return {"success": True, "data": result.stdout.strip(), "error": None}
    except Exception as e:
        return {"success": False, "data": "", "error": str(e)}


def kubectl_exec(
    pod_name: Annotated[str, "The name of the pod to execute the command in."],
    command: Annotated[
        List[str], "The command to run, as a list of strings. Example: ['ls', '-l']."
    ],
    namespace: Annotated[Optional[str], "Namespace of the pod."] = None,
    container: Annotated[
        Optional[str], "The specific container to target if the pod has multiple containers."
    ] = None,
    verbose: Annotated[bool, "If False, truncates result output to 1000 characters."] = False,
) -> Annotated[
    KubeActionResponse, "Dictionary containing the command output, success status, and exit code."
]:
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
    manifest: Annotated[
        str, "A valid Kubernetes YAML or JSON string containing resource definitions."
    ],
    verbose: Annotated[
        bool, "Whether to return the full detailed status of the apply operation."
    ] = False,
) -> Annotated[KubeActionResponse, "Dictionary containing the outcome of the apply operation."]:
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


def kubectl_apply_file(
    path: Annotated[str, "A local or URL reference to a Kubernetes manifest to apply."],
) -> KubeActionResponse:
    """
    Applies a local or remote file (manifest) to the cluster (equivalent to kubectl apply -f).

    Args:
        path: The local or URL path to apply.

    Returns:
        The result of the apply operation, including success status and CLI output.
    """
    try:
        result = run_kubectl(["apply", "-f", path])
        return {
            "success": result.returncode == 0,
            "output": result.stdout.strip() if result.returncode == 0 else result.stderr.strip(),
            "exit_code": result.returncode,
        }
    except Exception as e:
        return {
            "success": False,
            "output": f"Error applying manifest: {e}",
            "exit_code": -1,
        }


def kubectl_delete(
    resource_type: Annotated[str, "The type of resource to delete (e.g., 'pod', 'service')."],
    name: Annotated[str, "The specific name of the resource to delete."],
    namespace: Annotated[Optional[str], "Namespace where the resource is located."] = None,
) -> Annotated[KubeActionResponse, "Dictionary containing the outcome of the deletion operation."]:
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


def kubectl_top_nodes(
    verbose: Annotated[bool, "If True, shows specific percentages and raw values."] = False,
) -> KubeResult:
    """
    Retrieves CPU and Memory usage for all nodes in the cluster.

    Args:
        verbose: Toggle for detailed vs summarized output.

    Guidance for LLM Agent:
        - Use this to check if the cluster is out of capacity or if certain nodes are hotspots.
    """
    args = ["top", "node"]
    result = run_kubectl(args)
    if result.returncode != 0:
        return {"success": False, "data": "", "error": result.stderr.strip()}

    output = result.stdout.strip()
    return {"success": True, "data": output, "error": None}


def kubectl_top_pods(
    namespace: Annotated[Optional[str], "Namespace scope. 'all' for all namespaces."] = None,
    containers: Annotated[
        bool, "If True, shows usage for individual containers within pods."
    ] = False,
) -> KubeResult:
    """
    Retrieves CPU and Memory usage for pods.

    Args:
        namespace: Target namespace.
        containers: Whether to break down usage by container.

    Guidance for LLM Agent:
        - Use this to find 'noisy neighbors' or pods consuming more resources than requested.
    """
    args = ["top", "pod"]
    if namespace == "all":
        args.append("--all-namespaces")
    elif namespace:
        args.extend(["-n", namespace])
    if containers:
        args.append("--containers")

    result = run_kubectl(args)
    if result.returncode != 0:
        return {"success": False, "data": "", "error": result.stderr.strip()}

    return {"success": True, "data": result.stdout.strip(), "error": None}


def kubectl_rollout_status(
    resource_type: Annotated[str, "Type of resource (e.g., 'deployment', 'statefulset')."],
    name: Annotated[str, "Name of the resource."],
    namespace: Annotated[Optional[str], "Namespace of the resource."] = None,
    timeout: Annotated[str, "How long to wait for the rollout (e.g., '60s')."] = "30s",
) -> KubeActionResponse:
    """
    Watches the status of a rollout until it completes or times out.

    Args:
        resource_type: Category (deployment/statefulset/daemonset).
        name: Instance name.
        namespace: Target namespace.
        timeout: Wait duration.

    Guidance for LLM Agent:
        - Use this after 'kubectl_apply' to verify the new version of an app is actually running.
    """
    args = ["rollout", "status", f"{resource_type}/{name}", f"--timeout={timeout}"]
    if namespace:
        args.extend(["-n", namespace])

    result = run_kubectl(args)
    return {
        "success": result.returncode == 0,
        "output": result.stdout.strip() if result.returncode == 0 else result.stderr.strip(),
        "exit_code": result.returncode,
    }


def kubectl_crds() -> KubeActionResponse:
    """
    kubectl get crds
    """
    args = ["get", "crds", "-o", "json"]
    result = run_kubectl(args)
    return {
        "success": result.returncode == 0,
        "output": result.stdout.strip() if result.returncode == 0 else result.stderr.strip(),
        "exit_code": result.returncode,
    }


def kubectl_wait(
    resource_type: Annotated[str, "Type of resource."],
    name: Annotated[str, "Name of the resource."],
    condition: Annotated[
        str, "The condition to wait for (e.g., 'condition=Ready', 'condition=available')."
    ],
    namespace: Annotated[Optional[str], "Namespace scope."] = None,
    timeout: Annotated[str, "Max time to wait (e.g., '30s')."] = "30s",
) -> KubeActionResponse:
    """
    Blocks until a specific condition is met for a resource.

    Args:
        resource_type: Resource category.
        name: Resource name.
        condition: The state to wait for.
        namespace: Target namespace.
        timeout: Timeout duration.

    Guidance for LLM Agent:
        - Essential for workflows where you create a resource and must wait for it to be ready before the next step.
    """
    args = ["wait", f"--for={condition}", f"{resource_type}/{name}", f"--timeout={timeout}"]
    if namespace:
        args.extend(["-n", namespace])

    result = run_kubectl(args)
    return {
        "success": result.returncode == 0,
        "output": result.stdout.strip() if result.returncode == 0 else result.stderr.strip(),
        "exit_code": result.returncode,
    }


def kubectl_patch(
    resource_type: Annotated[str, "Type of resource."],
    name: Annotated[str, "Name of the resource."],
    patch_data: Annotated[Dict[str, Any], "The JSON/YAML patch to apply."],
    namespace: Annotated[Optional[str], "Namespace scope."] = None,
    patch_type: Annotated[str, "Type of patch: 'strategic', 'merge', or 'json'."] = "strategic",
) -> KubeActionResponse:
    """
    Apply a strategic merge or JSON patch to a resource.

    Args:
        resource_type: Resource category.
        name: Resource name.
        patch_data: Dictionary containing the changes.
        namespace: Target namespace.
        patch_type: Methodology for the patch.

    Guidance for LLM Agent:
        - Use this for minor changes (like scaling replicas or changing an image) without re-applying a full manifest.
    """
    patch_json = json.dumps(patch_data)
    args = ["patch", resource_type, name, "-p", patch_json, "--type", patch_type]
    if namespace:
        args.extend(["-n", namespace])

    result = run_kubectl(args)
    return {
        "success": result.returncode == 0,
        "output": result.stdout.strip() if result.returncode == 0 else result.stderr.strip(),
        "exit_code": result.returncode,
    }


def kubectl_get_resource_quota(
    namespace: Annotated[str, "The namespace to check quotas for."],
) -> KubeResult:
    """
    Retrieves the ResourceQuotas for a namespace.

    Quotas define the 'hard' limits for a namespace. Even if the cluster can
    scale, the namespace might be restricted from using more than X cores or Y GPUs.

    Args:
        namespace: The target namespace.

    Returns:
        List of ResourceQuota objects showing used vs hard limits.
    """
    return kubectl_get("resourcequotas", namespace=namespace)


def kubectl_get_priority_classes() -> KubeResult:
    """
    Lists PriorityClasses in the cluster.

    Priority determines which pods get scheduled first or can preempt others
    during an upscale event. Higher priority pods trigger the autoscaler faster.
    """
    return kubectl_get("priorityclasses")


def kubectl_get_autoscaler_info() -> AutoscalerConfigResult:
    """
    Attempts to identify the cluster autoscaler and retrieve its configuration.

    This tool scans the cluster for common autoscalers (Karpenter, Cluster-Autoscaler,
    or Cluster API) and extracts metadata about which node types are allowed
    to be provisioned, even if those nodes aren't currently active.

    Returns:
        A dictionary containing:
            - 'success' (bool): True if an autoscaler was identified and queried.
            - 'autoscaler_type' (str): One of 'karpenter', 'cluster-autoscaler', or 'unknown'.
            - 'potential_instances' (list): Known allowed instance types or node groups.
            - 'raw_config' (dict): The underlying ConfigMap or CRD data.
    """
    # Karpenter defines potential nodes in NodePools
    try:
        res = run_kubectl(["get", "nodepools.karpenter.sh"], json_output=True)
        if res.returncode == 0:
            data = json.loads(res.stdout)
            items = data.get("items", [])
            instance_types = []
            for item in items:
                # Extract allowed requirements (like instance-type)
                requirements = (
                    item.get("spec", {}).get("template", {}).get("spec", {}).get("requirements", [])
                )
                for req in requirements:
                    if (
                        req.get("key") == "node.kubernetes.io/instance-type"
                        or req.get("key") == "karpenter.k8s.aws/instance-type"
                    ):
                        instance_types.extend(req.get("values", []))

            return {
                "success": True,
                "autoscaler_type": "karpenter",
                "potential_instances": list(set(instance_types)),
                "raw_config": items,
            }
    except Exception:
        pass

    # Standard CA writes its state to a ConfigMap called cluster-autoscaler-status
    try:
        res = run_kubectl(
            ["get", "configmap", "cluster-autoscaler-status", "-n", "kube-system"], json_output=True
        )
        if res.returncode == 0:
            data = json.loads(res.stdout)
            status_text = data.get("data", {}).get("status", "")

            # The status text is a custom format. We look for NodeGroups.
            # Example: "NodeGroups: Name: group-1, Name: group-2"
            node_groups = re.findall(r"Name:\s+([^\s,]+)", status_text)

            return {
                "success": True,
                "autoscaler_type": "cluster-autoscaler",
                "potential_instances": node_groups,
                "raw_config": {"status": status_text},
            }
    except Exception:
        pass

    # Cluster API is common in hybrid/multi-cloud setups
    try:
        res = run_kubectl(["get", "machinesets"], namespace="all", json_output=True)
        if res.returncode == 0:
            data = json.loads(res.stdout)
            items = data.get("items", [])
            machine_types = [
                item.get("spec", {})
                .get("template", {})
                .get("spec", {})
                .get("providerSpec", {})
                .get("value", {})
                .get("instanceType")
                for item in items
            ]
            return {
                "success": True,
                "autoscaler_type": "cluster-api",
                "potential_instances": [m for m in machine_types if m],
                "raw_config": items,
            }
    except Exception:
        pass

    return {
        "success": False,
        "autoscaler_type": "unknown",
        "potential_instances": [],
        "error": "No recognizable autoscaler configuration (Karpenter, CA, or CAPI) found.",
    }


def kubectl_get_current_context() -> KubeResult:
    """
    Returns the name of the current active cluster context and current namespace.

    Guidance for LLM Agent:
        - Use this tool at the very beginning of a session to ensure you are operating on the correct cluster.
    """
    try:
        ctx_res = run_kubectl(["config", "current-context"])
        ns_res = run_kubectl(["config", "view", "--minify", "-o", "jsonpath={..namespace}"])

        data = {"context": ctx_res.stdout.strip(), "namespace": ns_res.stdout.strip() or "default"}
        return {"success": True, "data": data, "error": None}
    except Exception as e:
        return {"success": False, "data": {}, "error": str(e)}


def kubectl_api_versions(
    verbose: Annotated[
        bool,
        "If False, returns a summarized list of major API groups. If True, returns every single version string.",
    ] = False,
) -> Annotated[KubeResult, "A structured result containing a list of supported API versions."]:
    """
    Lists the API versions supported by the cluster.

    Args:
        verbose: Toggle between a summarized list and the full API list.

    Guidance for LLM Agent:
        - Use this to determine the correct 'apiVersion' string to use at the top
          of a YAML manifest (e.g., 'apps/v1' vs 'batch/v1').
        - Start with verbose=False to see common groups.
    """
    try:
        result = run_kubectl(["api-versions"])
        if result.returncode != 0:
            return {"success": False, "data": [], "error": result.stderr.strip()}

        versions = [v.strip() for v in result.stdout.splitlines() if v.strip()]

        if not verbose and len(versions) > 20:
            # Filter for common/stable versions as a summary
            stable = [v for v in versions if "/v1" in v and "beta" not in v and "alpha" not in v]
            versions = stable if stable else versions[:20]

        return {"success": True, "data": versions, "error": None}
    except Exception as e:
        return {"success": False, "data": [], "error": str(e)}


def kubectl_api_resources(
    namespaced: Annotated[
        Optional[bool], "If True, only list resources that belong to namespaces."
    ] = None,
    api_group: Annotated[
        Optional[str], "Limit results to a specific API group (e.g., 'apps')."
    ] = None,
    verbose: Annotated[
        bool, "If False, returns only common resource types to save tokens."
    ] = False,
) -> KubeResult:
    """
    Lists the full set of resource types available on the server with detailed descriptions.

    Args:
        namespaced: Filter by namespaced/non-namespaced resources.
        api_group: Specific API group to query.
        verbose: If True, returns the full raw table. If False, returns a high-level list.

    Guidance for LLM Agent:
        - Use this to discover which resources (like 'pods', 'jobs', 'configmaps') the
          cluster supports and what their short-names are.
    """
    args = ["api-resources"]
    if namespaced is True:
        args.append("--namespaced=true")
    elif namespaced is False:
        args.append("--namespaced=false")
    if api_group:
        args.extend(["--api-group", api_group])

    try:
        result = run_kubectl(args)
        if result.returncode != 0:
            return {"success": False, "data": "", "error": result.stderr.strip()}

        output = result.stdout.strip()
        if not verbose:
            # Simple heuristic: showing the first 20 resources is usually enough for discovery
            lines = output.splitlines()
            if len(lines) > 20:
                output = (
                    "\n".join(lines[:20]) + "\n... [Truncated. Use verbose=True for full list] ..."
                )

        return {"success": True, "data": output, "error": None}
    except Exception as e:
        return {"success": False, "data": "", "error": str(e)}
