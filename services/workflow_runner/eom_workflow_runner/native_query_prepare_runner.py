"""Explicit reference/private Runner composition, never source or execution authorization."""

from typing import Literal

from eom_workflow_runner.engine import WorkflowRunner
from eom_workflow_runner.private_chat_query_owner_admission import (
    CatalogPrivateChatQueryOwnerAdmission,
)
from eom_workflow_runner.reference_query_owner_admission import CatalogReferenceQueryOwnerAdmission
from eom_workflow_runner.repository import CommandExecutionFamily, NativeCommandActorSelection

type NativeQueryDriveOffer = Literal["STARTED", "ALREADY_ACTIVE", "BUSY", "UNAVAILABLE"]


def require_reference_query_prepare_runner(runner: WorkflowRunner) -> None:
    """Preserve reference composition; every actual claim still needs current authority."""
    if type(runner) is not WorkflowRunner:
        raise ValueError("REFERENCE_QUERY_PREPARE_RUNNER_INVALID")
    owner = runner.reference_query_owner
    if (
        type(owner) is not CatalogReferenceQueryOwnerAdmission
        or runner.reference_query_executor is None
        or runner.engine is not owner.catalog.engine
        or runner.command_families != frozenset({CommandExecutionFamily.REFERENCE_QUERY})
        or runner.command_actor_selection
        != NativeCommandActorSelection("human", owner.identity.capture.operator_id)
        or runner.available_roles
        or runner.executor is not None
    ):
        raise ValueError("REFERENCE_QUERY_PREPARE_RUNNER_INVALID")


def require_private_chat_query_prepare_runner(
    runner: WorkflowRunner,
) -> NativeCommandActorSelection:
    """Queue selection only; the live Chat/Identity owners separately authorize the actor."""
    if type(runner) is not WorkflowRunner:
        raise ValueError("PRIVATE_CHAT_QUERY_PREPARE_RUNNER_INVALID")
    owner, actor = runner.private_chat_query_owner, runner.command_actor_selection
    if (
        type(owner) is not CatalogPrivateChatQueryOwnerAdmission
        or runner.private_chat_query_executor is None
        or runner.engine is not owner.catalog.engine
        or runner.command_families != frozenset({CommandExecutionFamily.PRIVATE_CHAT_QUERY})
        or type(actor) is not NativeCommandActorSelection
        or actor.actor_type != "human"
        or runner.available_roles
        or runner.executor is not None
    ):
        raise ValueError("PRIVATE_CHAT_QUERY_PREPARE_RUNNER_INVALID")
    actor.__post_init__()
    return actor
