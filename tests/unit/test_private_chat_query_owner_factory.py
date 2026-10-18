"""Concrete private composition; live source/runtime observations are declared fixtures."""

from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from eom_catalog_contracts.private_chat_query_read import ChatPrivateQueryOrigin
from eom_identity_service.operator_authorization_fence_sql import OperatorAuthorizationFenceOwnerPin
from eom_identity_service.owned_operator_authorization_fence import OwnedOperatorAuthorizationFence
from eom_orchestrator.general_chat_private_query_client import GeneralChatPrivateQueryClient
from eom_orchestrator.general_chat_state import ChatError
from eom_orchestrator.native_private_chat_query_systemd import FixedNativePrivateQueryLauncher
from eom_workflow_runner import private_chat_query_owner_factory as module
from eom_workflow_runner.native_query_prepare_driver import NativeQueryPrepareDriver
from eom_workflow_runner.repository import CommandExecutionFamily

from tests.unit.inference_transfer_embedding_fixtures import seal
from tests.unit.test_private_chat_query_source_owner import source as source


@pytest.fixture
def factory(source, monkeypatch):
    chat = GeneralChatPrivateQueryClient()
    authorize = Mock(side_effect=source.owner.chat.authorize)
    monkeypatch.setattr(chat, "authorize", authorize)
    observed = []
    monkeypatch.setattr(
        FixedNativePrivateQueryLauncher,
        "assert_current_runtime",
        lambda actual: observed.append(actual),
    )
    launcher = FixedNativePrivateQueryLauncher("1" * 64, "2" * 64, lambda: None)
    driver = NativeQueryPrepareDriver()
    value = module.PrivateChatQueryOwnerFactory(
        source.publisher.engine,
        source.publisher,
        source.owner.settings,
        source.owner.configuration,
        source.policy.spaces,
        OperatorAuthorizationFenceOwnerPin("eom_app", 42),
        chat,
        launcher,
        driver,
        "a" * 40,
        lambda: None,
    )
    try:
        yield SimpleNamespace(factory=value, source=source, observed=observed, authorize=authorize)
    finally:
        driver.close()


def test_each_original_gets_distinct_actual_private_owners_and_one_shared_finite_driver(factory):
    value = factory
    origin = value.source.projection.origin
    first = value.factory.application(origin).application
    second = value.factory.application(origin).application
    assert first.owner is not second.owner and first.executor is not second.executor
    assert first.runner is not second.runner
    assert first.driver is second.driver is value.factory.driver
    assert first.owner.sources.chat is second.owner.sources.chat is value.factory.chat
    identity = first.owner.sources.identity
    assert type(identity) is OwnedOperatorAuthorizationFence
    assert (
        identity.operator_id == origin.actor_id and identity.owner == value.factory.operator_owner
    )
    assert not hasattr(identity, "capture") and not hasattr(value.factory, "capture")
    assert first.runner.command_actor_selection.actor_id == origin.actor_id
    assert first.runner.command_families == frozenset({CommandExecutionFamily.PRIVATE_CHAT_QUERY})
    assert not first.runner.available_roles and first.runner.executor is None
    assert not first.runner.readiness.evaluate().ready
    assert first.owner.catalog.engine is first.runner.engine is value.factory.engine
    assert first.executor.publisher is value.source.publisher
    assert first.executor.launcher is value.factory.launcher
    assert len(value.observed) == 4 and value.authorize.call_count == 2
    assert not value.factory.driver.observe().active


@pytest.mark.parametrize(
    "fault",
    (
        "source_denied",
        "origin_changed",
        "runtime_changed",
        "configuration_changed",
        "late_configuration_changed",
    ),
)
def test_current_origin_or_runtime_failure_never_constructs_executor_or_runner(
    factory, monkeypatch, fault
):
    value = factory
    origin = value.source.projection.origin
    executor = Mock(side_effect=AssertionError("must not reach executor"))
    monkeypatch.setattr(module, "CatalogNativePrivateChatQueryExecutor", executor)
    if fault == "source_denied":
        value.authorize.side_effect = ChatError("GENERAL_CHAT_FORBIDDEN")
        expected = ChatError
    elif fault == "origin_changed":
        value.authorize.side_effect = None
        value.authorize.return_value = ChatPrivateQueryOrigin.model_validate(
            seal(
                origin.model_dump(mode="json") | {"runtime_id": "chatrt_" + "f" * 32},
                "origin_sha256",
            )
        )
        expected = ValueError
    elif fault == "configuration_changed":
        value.factory = replace(
            value.factory,
            configuration_guard=Mock(side_effect=ValueError("synthetic configuration replaced")),
        )
        expected = ValueError
    elif fault == "late_configuration_changed":
        value.factory = replace(
            value.factory,
            configuration_guard=Mock(
                side_effect=[None, ValueError("synthetic configuration replaced")]
            ),
        )
        expected = ValueError
    else:

        def reject(_actual):
            raise ValueError("PRIVATE_RUNTIME_CHANGED")

        monkeypatch.setattr(FixedNativePrivateQueryLauncher, "assert_current_runtime", reject)
        expected = ValueError
    with pytest.raises(expected):
        value.factory.application(origin)
    executor.assert_not_called()
    assert not value.factory.driver.observe().active


@pytest.mark.parametrize(
    "fault", ("engine", "driver", "launcher", "chat", "source", "space", "configuration_guard")
)
def test_mixed_composition_is_rejected_before_source_rpc(factory, fault):
    value = factory
    if fault == "engine":
        changes = {"engine": object()}
    elif fault == "source":
        changes = {"source_commit": "invalid"}
    elif fault == "space":
        changes = {
            "spaces": value.factory.spaces.model_copy(
                update={"document": value.factory.spaces.query}
            )
        }
    else:
        changes = {fault: object()}
    value.authorize.reset_mock()
    with pytest.raises(ValueError):
        replace(value.factory, **changes)
    value.authorize.assert_not_called()
    assert not value.factory.driver.observe().active
