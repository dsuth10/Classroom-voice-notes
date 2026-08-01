"""Task Adapter Protocol and Registry for remote agent task execution."""

from typing import Any, Dict, Optional, Protocol, runtime_checkable

from app.destinations.openclaw_adapter import OpenClawAdapter
from app.worker.errors import InvalidTaskPayload, UnsupportedTargetAgent


@runtime_checkable
class TaskAdapter(Protocol):
    """Protocol for target-specific task execution adapters."""

    def validate_task(self, payload: Dict[str, Any]) -> None:
        """Validates task payload structure before execution."""
        ...

    def convert_task(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Converts task payload into target agent request format."""
        ...

    def execute(
        self, request: Dict[str, Any], timeout_seconds: int = 300
    ) -> Dict[str, Any]:
        """Executes task request against the target agent gateway."""
        ...

    def validate_response(self, response: Dict[str, Any]) -> Dict[str, Any]:
        """Validates target agent response structure."""
        ...


class HermesAdapter:
    """Task adapter for Hermes agent tasks."""

    def validate_task(self, payload: Dict[str, Any]) -> None:
        target = payload.get("target_agent", "")
        if target and target != "hermes" and target != "auto":
            raise InvalidTaskPayload(
                f"HermesAdapter received invalid target_agent '{target}'"
            )

    def convert_task(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        raise UnsupportedTargetAgent(
            "Hermes task execution is currently unavailable (no active Hermes"
            " execution gateway)."
        )

    def execute(
        self, request: Dict[str, Any], timeout_seconds: int = 300
    ) -> Dict[str, Any]:
        raise UnsupportedTargetAgent(
            "Hermes task execution is currently unavailable (no active Hermes"
            " execution gateway)."
        )

    def validate_response(self, response: Dict[str, Any]) -> Dict[str, Any]:
        raise UnsupportedTargetAgent(
            "Hermes task execution is currently unavailable (no active Hermes"
            " execution gateway)."
        )


class AdapterRegistry:
    """Registry mapping target agent identifiers to TaskAdapter implementations."""

    def __init__(self) -> None:
        self._adapters: Dict[str, TaskAdapter] = {}

    def register(self, target_agent: str, adapter: TaskAdapter) -> None:
        self._adapters[target_agent.lower()] = adapter

    def get_adapter(self, target_agent: str) -> TaskAdapter:
        agent_key = target_agent.lower()
        if agent_key not in self._adapters:
            raise UnsupportedTargetAgent(
                f"No registered TaskAdapter for target agent '{target_agent}'."
            )
        return self._adapters[agent_key]


def get_default_registry(
    config: Optional[Dict[str, Any]] = None, gateway_token: str = ""
) -> AdapterRegistry:
    """Factory creating default registry with OpenClaw and Hermes adapters registered."""
    registry = AdapterRegistry()
    if config is not None:
        registry.register("openclaw", OpenClawAdapter(config, gateway_token))
    registry.register("hermes", HermesAdapter())
    return registry
