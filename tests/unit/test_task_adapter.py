"""Unit tests for TaskAdapter protocol, HermesAdapter, and AdapterRegistry."""
import pytest
from app.destinations.openclaw_adapter import OpenClawAdapter
from app.worker.errors import UnsupportedTargetAgent
from app.worker.task_adapter import (
    AdapterRegistry,
    HermesAdapter,
    TaskAdapter,
    get_default_registry,
)


def test_registry_registration_and_lookup() -> None:
    registry = AdapterRegistry()
    hermes = HermesAdapter()
    registry.register("hermes", hermes)

    resolved = registry.get_adapter("hermes")
    assert resolved is hermes
    assert isinstance(resolved, TaskAdapter)


def test_registry_unknown_agent_raises_unsupported() -> None:
    registry = AdapterRegistry()
    with pytest.raises(UnsupportedTargetAgent, match="No registered TaskAdapter"):
        registry.get_adapter("unknown_agent")


def test_hermes_adapter_raises_unavailable() -> None:
    adapter = HermesAdapter()
    adapter.validate_task({"target_agent": "hermes"})

    with pytest.raises(
        UnsupportedTargetAgent, match="currently unavailable"
    ):
        adapter.convert_task({"target_agent": "hermes"})

    with pytest.raises(
        UnsupportedTargetAgent, match="currently unavailable"
    ):
        adapter.execute({})


def test_default_registry_factory() -> None:
    registry = get_default_registry({"gateway_url": "http://127.0.0.1:18789"}, "token")
    openclaw = registry.get_adapter("openclaw")
    hermes = registry.get_adapter("hermes")

    assert isinstance(openclaw, OpenClawAdapter)
    assert isinstance(hermes, HermesAdapter)
