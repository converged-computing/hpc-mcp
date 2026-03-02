import json
import os
import re
import shutil
import subprocess
import tempfile
from typing import Annotated, Any, Dict, List, Optional, Union

AutoscalerConfigResult = Annotated[
    Dict[str, Any],
    "A structured report containing the discovered autoscaler type, "
    "the raw configuration data, and a list of potential instance types if found.",
]


KubeResult = Annotated[
    Dict[str, Any],
    "A structured result containing 'success' (bool), 'data' (parsed JSON or string), "
    "and 'error' (str or None) if the command failed.",
]

KubeActionResponse = Annotated[
    Dict[str, Any],
    "A response from a state-changing command (apply/delete) containing 'success' (bool), "
    "the raw 'output' string, and 'exit_code' (int).",
]


def run_kubectl(args: List[str], json_output: bool = False) -> subprocess.CompletedProcess:
    """
    Executes a kubectl command safely using subprocess.

    Args:
        args: List of command arguments.
        json_output: If True, appends '-o json' to the command.
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
        str, "The type of resource to get (e.g., 'pods', 'nodes', 'services', 'deployments')."
    ],
    namespace: Annotated[
        Optional[str], "The namespace scope. If None, uses default. Use 'all' for all namespaces."
    ] = None,
    label_selector: Annotated[Optional[str], "Filter results by label (e.g., 'app=nginx')."] = None,
) -> KubeResult:
    """
    Retrieves a list of Kubernetes resources in JSON format.

    Args:
        resource_type: The Kubernetes resource category.
        namespace: The namespace to query. 'all' triggers --all-namespaces.
        label_selector: Optional k8s label query string.

    Returns:
        A dictionary containing the 'success' flag and a 'data' list of resource objects.
    """
    args = ["get", resource_type]

    if namespace == "all":
        args.append("--all-namespaces")
    elif namespace:
        args.extend(["-n", namespace])

    if label_selector:
        args.extend(["-l", label_selector])

    try:
        result = run_kubectl(args, json_output=True)
        if result.returncode != 0:
            return {"success": False, "data": [], "error": result.stderr.strip()}

        data = json.loads(result.stdout)
        # Kubernetes returns a 'List' kind; we extract the 'items'
        items = data.get("items", [])
        return {"success": True, "data": items, "error": None}
    except Exception as e:
        return {"success": False, "data": [], "error": str(e)}


def kubectl_describe(
    resource_type: Annotated[str, "Resource type (e.g., 'pod')."],
    name: Annotated[str, "The name of the specific resource."],
    namespace: Annotated[Optional[str], "The namespace of the resource."] = None,
) -> KubeResult:
    """
    Retrieves a detailed, human-readable description of a specific resource.

    Args:
        resource_type: Resource category.
        name: Name of the resource instance.
        namespace: Target namespace.

    Returns:
        A dictionary containing the descriptive text in the 'data' field.
    """
    args = ["describe", resource_type, name]
    if namespace:
        args.extend(["-n", namespace])

    result = run_kubectl(args)
    if result.returncode != 0:
        return {"success": False, "data": "", "error": result.stderr.strip()}

    return {"success": True, "data": result.stdout.strip(), "error": None}


def kubectl_logs(
    pod_name: Annotated[str, "The name of the pod to fetch logs from."],
    namespace: Annotated[Optional[str], "The namespace of the pod."] = None,
    container: Annotated[
        Optional[str], "Specific container name if the pod is multi-container."
    ] = None,
    tail: Annotated[int, "Number of lines from the end of the logs to show."] = 100,
) -> KubeResult:
    """
    Fetches the logs from a specific pod or container.

    Args:
        pod_name: Target pod.
        namespace: Pod namespace.
        container: Target container within the pod.
        tail: Limit output to the most recent N lines.

    Returns:
        A dictionary containing the log text.
    """
    args = ["logs", pod_name, f"--tail={tail}"]
    if namespace:
        args.extend(["-n", namespace])
    if container:
        args.extend(["-c", container])

    result = run_kubectl(args)
    if result.returncode != 0:
        return {"success": False, "data": "", "error": result.stderr.strip()}

    return {"success": True, "data": result.stdout.strip(), "error": None}


def kubectl_apply(
    manifest: Annotated[str, "A valid Kubernetes YAML or JSON manifest string."],
) -> KubeActionResponse:
    """
    Applies a configuration to a resource from a manifest string (equivalent to kubectl apply -f).

    Args:
        manifest: The raw string content of the Kubernetes configuration.

    Returns:
        The result of the apply operation, including success status and CLI output.
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
    resource_type: Annotated[str, "Type of resource (e.g., 'pod')."],
    name: Annotated[str, "Name of the resource to delete."],
    namespace: Annotated[Optional[str], "The namespace scope."] = None,
) -> KubeActionResponse:
    """
    Deletes a specific resource from the cluster.

    Args:
        resource_type: Resource category.
        name: Name of the instance.
        namespace: Target namespace.
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


def kubectl_get_events(
    namespace: Annotated[
        Optional[str], "Namespace to fetch events for. 'all' for all namespaces."
    ] = None,
) -> KubeResult:
    """
    Retrieves cluster events, sorted by time. Essential for diagnosing scheduling failures.

    Args:
        namespace: Target namespace or 'all'.

    Returns:
        A list of event objects containing reason, message, and source.
    """
    args = ["get", "events", "--sort-by=.lastTimestamp"]
    if namespace == "all":
        args.append("--all-namespaces")
    elif namespace:
        args.extend(["-n", namespace])

    try:
        result = run_kubectl(args, json_output=True)
        data = json.loads(result.stdout)
        return {"success": True, "data": data.get("items", []), "error": None}
    except Exception as e:
        return {"success": False, "data": [], "error": str(e)}


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


def kubectl_exec(
    pod_name: Annotated[str, "Name of the pod."],
    command: Annotated[List[str], "Command and arguments to run (e.g., ['ls', '/'])."],
    namespace: Annotated[Optional[str], "Namespace of the pod."] = None,
    container: Annotated[Optional[str], "Target container name."] = None,
) -> KubeActionResponse:
    """
    Executes a command inside a running container. Equivalent to 'kubectl exec'.

    Args:
        pod_name: Target pod.
        command: List of command components.
        namespace: Target namespace.
        container: Specific container in the pod.

    Returns:
        The output of the command execution.
    """
    args = ["exec", pod_name]
    if namespace:
        args.extend(["-n", namespace])
    if container:
        args.extend(["-c", container])

    args.append("--")
    args.extend(command)

    result = run_kubectl(args)
    return {
        "success": result.returncode == 0,
        "output": result.stdout.strip() if result.returncode == 0 else result.stderr.strip(),
        "exit_code": result.returncode,
    }


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


def kubectl_api_resources() -> KubeResult:
    """
    Lists the full set of resource types available on the server.

    Use this to discover which resources (like 'pods', 'jobs', 'configmaps') the
    cluster supports, their associated API groups, and their short names.

    Returns:
        A dictionary containing:
            - 'success' (bool): True if the discovery succeeded.
            - 'data' (str): A formatted table of available API resources.
            - 'error' (str, optional): Error details if the query failed.
    """
    try:
        # api-resources does not support -o json, so we return the formatted table
        result = run_kubectl(["api-resources"])
        if result.returncode != 0:
            return {"success": False, "data": "", "error": result.stderr.strip()}

        return {"success": True, "data": result.stdout.strip(), "error": None}
    except Exception as e:
        return {"success": False, "data": "", "error": str(e)}


def kubectl_api_versions() -> KubeResult:
    """
    Lists the API versions supported by the cluster.

    Use this to determine the correct 'apiVersion' string to use at the top
    of a YAML manifest (e.g., 'apps/v1' vs 'batch/v1').

    Returns:
        A dictionary containing:
            - 'success' (bool): True if the versions were retrieved.
            - 'data' (list[str]): A list of supported API version strings.
            - 'error' (str, optional): Error details.
    """
    try:
        result = run_kubectl(["api-versions"])
        if result.returncode != 0:
            return {"success": False, "data": [], "error": result.stderr.strip()}

        # Split output into a list of versions
        versions = [v.strip() for v in result.stdout.splitlines() if v.strip()]
        return {"success": True, "data": versions, "error": None}
    except Exception as e:
        return {"success": False, "data": [], "error": str(e)}


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
