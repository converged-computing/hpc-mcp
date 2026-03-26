import asyncio
import uuid
from typing import Any, Awaitable, Callable, Dict

from kubernetes_asyncio import client, config, watch


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
            "name": "kubernetes_events",
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
        task = asyncio.create_task(self._watch_loop(sub_id, params, callback))
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

    async def _watch_loop(self, sub_id: str, params: Dict[str, Any], callback: Callable):
        """
        The internal async loop that communicates with the K8s API.
        """
        resource_type = params.get("resource_type", "pods")
        namespace = params.get("namespace", "default")

        # Dynamic API selection based on resource type
        v1 = client.CoreV1Api()
        w = watch.Watch()

        try:
            # Note: This is an example for Pods.
            # You would extend this to support Deployments/Flux CRDs.
            method = getattr(v1, f"list_namespaced_{resource_type}")

            async with w.stream(
                method,
                namespace=namespace,
                label_selector=params.get("label_selector", ""),
                field_selector=params.get("field_selector", ""),
            ) as stream:
                async for event in stream:
                    # Clean up the object for the LLM to save tokens
                    obj = event["raw_object"]
                    event_data = {
                        "type": event["type"],
                        "name": obj["metadata"]["name"],
                        "status": obj.get("status", {}),
                        "resource": resource_type,
                    }

                    # Push notification to MCP client via the provided callback
                    await callback(sub_id, event_data)

        except asyncio.CancelledError:
            # Clean exit on unsubscribe
            pass
        except Exception as e:
            # Notify the agent that the watch failed
            await callback(sub_id, {"error": str(e), "status": "failed"})
        finally:
            w.stop()
