import asyncio
import uuid
from typing import Any, Awaitable, Callable, Dict

from kubernetes_asyncio import client, config, watch
from kubernetes_asyncio.client import ApiClient


class KubernetesEvents:
    """
    Handles Kubernetes resource watching for the MCP server.
    This class is dynamically loaded by mcpserver if defined in config.
    """

    def __init__(self):
        self._active_watches: Dict[str, asyncio.Task] = {}
        try:
            config.load_incluster_config()
        except config.ConfigException:
            asyncio.run(config.load_kube_config())

    def get_metadata(self) -> Dict[str, Any]:
        """
        Returns static discovery info for the Agent.
        The Agent uses this to know what parameters to send.
        """
        return {
            "name": "KubernetesEvents",
            "description": "Subscribe to events for Kubernetes resources (Pods, Deployments, etc.)",
            "parameters": {
                "resource_type": "string (e.g., pods, deployments, kustomizations)",
                "namespace": "string",
                "label_selector": "string (optional)",
                "field_selector": "string (optional)",
            },
        }

    async def subscribe(
        self, params: Dict[str, Any], callback: Callable[[str, Dict[str, Any]], Awaitable[None]]
    ) -> str:
        """
        Starts a Kubernetes watch task in the background.
        """
        sub_id = f"k8s_{uuid.uuid4().hex[:8]}"

        # Spin up the background listener
        task = asyncio.create_task(self.watch_loop(sub_id, params, callback))
        self._active_watches[sub_id] = task
        return sub_id

    async def unsubscribe(self, sub_id: str) -> bool:
        """
        Stops a specific watch task.
        """
        task = self._active_watches.pop(sub_id, None)
        if task:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            return True
        return False

    async def watch_loop(self, sub_id: str, params: Dict[str, Any], callback: Callable):
        """
        The internal async loop that communicates with the K8s API.
        """
        resource_type = params.get("resource_type", "pod").lower()
        namespace = params.get("namespace", "default")
        is_custom = params.get("is_custom_resource", False)
        only_completed = params.get("only_completed", True)
        name_pattern = params.get("name_pattern")
        label_selector = params.get("label_selector", "")
        field_selector = params.get("field_selector", "")
        w = watch.Watch()

        try:
            if is_custom:
                api_client_inst = client.CustomObjectsApi()
                group = params.get("group")
                version = params.get("version")
                plural = params.get("plural", resource_type + "s")
                if not group or not version:
                    raise ValueError("Both 'group' and 'version' are required.")

                method = api_client_inst.list_namespaced_custom_object
                stream_args = {
                    "group": group,
                    "version": version,
                    "namespace": namespace,
                    "plural": plural,
                }
            else:
                if resource_type == "job":
                    api_client_inst = client.BatchV1Api()
                else:
                    api_client_inst = client.CoreV1Api()

                method = getattr(api_client_inst, f"list_namespaced_{resource_type}")
                stream_args = {
                    "namespace": namespace,
                }

            stream_args["label_selector"] = label_selector
            stream_args["field_selector"] = field_selector

            async with w.stream(method, **stream_args) as stream:
                sanitizer = ApiClient()
                async for event in stream:
                    obj = sanitizer.sanitize_for_serialization(event["object"])

                    # Filter based on name
                    metadata = obj.get("metadata", {})
                    name = metadata.get("name", "")
                    if name_pattern and name_pattern not in name:
                        continue

                    event_data = {
                        "type": event["type"],
                        "name": name,
                        "resource": resource_type,
                        "creation_timestamp": obj["metadata"].get("creationTimestamp"),
                    }

                    status_block = obj.get("status", {})
                    state = "Unknown"
                    is_completed = False

                    if resource_type == "pod":
                        state = status_block.get("phase", "Unknown")
                        is_completed = state in ["Succeeded", "Failed"]

                    if resource_type == "pod":
                        event_data["status"] = status_block.get("phase", "Unknown")

                    elif resource_type == "job":
                        event_data["status"] = {
                            "active": int(status_block.get("active", 0)),
                            "succeeded": int(status_block.get("succeeded", 0)),
                            "failed": int(status_block.get("failed", 0)),
                            "start_time": status_block.get("startTime"),
                        }
                        completions = obj.get("spec", {}).get("completions", 1)
                        if event_data["status"]["succeeded"] >= completions:
                            event_data["state"] = "Succeeded"
                            is_completed = True
                        elif event_data["status"]["failed"] > 0:
                            event_data["state"] = "Failed"
                            is_completed = True
                        else:
                            event_data["state"] = "Running"
                    else:
                        event_data["status"] = status_block
                        state = status_block.get("state", "Unknown")
                        is_completed = state in ["Succeeded", "Failed", "Completed", "Finished"]

                    if is_custom and "state" in status_block:
                        event_data["state"] = status_block["state"]
                    if only_completed and not is_completed:
                        continue

                    try:
                        safe_event_data = json.loads(json.dumps(event_data, default=str))
                    except:
                        safe_event_data = event_data

                    print(f"📡 {sub_id}: {safe_event_data['name']} -> {event['type']}")
                    await callback(sub_id, safe_event_data)

        except asyncio.CancelledError:
            print(f"🛑 Stopping watcher for {sub_id}...")
        except Exception as e:
            print(f"❌ Watch failed for subscription {sub_id}: {e}")
            import traceback

            traceback.print_exc()
        finally:
            w.stop()
