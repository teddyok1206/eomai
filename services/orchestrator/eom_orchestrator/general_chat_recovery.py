"""Read-only worker recovery followed by supported exact-claim completion."""

from __future__ import annotations

from typing import Protocol

from eom_protocol.general_chat import ChatTurnResult
from eom_protocol.general_chat_dispatch import ChatDispatchReceipt
from eom_protocol.general_chat_worker_messages import (
    ChatWorkerOutput,
    ChatWorkerTicket,
    require_chat_ticket_result,
)

from eom_orchestrator.general_chat_execution import ChatClaim
from eom_orchestrator.general_chat_state import ChatError


class ChatRecoveryExecutionPort(Protocol):
    def active_claim(self) -> ChatClaim | None: ...
    def execution_receipt(self, claim: ChatClaim) -> ChatDispatchReceipt: ...
    def reconcile_known_result(self, claim: ChatClaim, result: ChatTurnResult) -> None: ...


class ChatRecoveryWorkerPort(Protocol):
    def lookup(self, ticket: ChatWorkerTicket) -> ChatWorkerOutput: ...


def recover_known_chat_turn(
    execution: ChatRecoveryExecutionPort, worker: ChatRecoveryWorkerPort
) -> ChatClaim | None:
    """Never invokes generation, admission, enrollment or a new claim.

    The execution application owns quiescence/claim/lease and canonical pointers;
    the worker lookup port owns exact local handoff identity. An absent marker or
    unknown output is not proof that a turn did not run.
    """
    claim = execution.active_claim()
    if claim is None:
        return None
    receipt = execution.execution_receipt(claim)
    output = worker.lookup(receipt.ticket)
    if output.state != "KNOWN" or output.result is None:
        raise ChatError("GENERAL_CHAT_RECONCILIATION_REQUIRED")
    require_chat_ticket_result(receipt.ticket, output.result)
    execution.reconcile_known_result(claim, output.result)
    return claim
