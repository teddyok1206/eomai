"""Private typed API over existing Job history; caller owns current source/claim fences."""

from __future__ import annotations

from dataclasses import dataclass
from typing import cast

from eom_catalog_contracts.embedding_reference_query import raw_similarity_contract_value
from eom_workflow.native_private_chat_query_coordinator import NativePrivateChatQueryCheckpoint
from eom_workflow.private_chat_query_execution import PrivateChatQueryWorkflowRequest
from eom_workflow.private_chat_query_publication import PrivateChatQueryLaunchAssociation
from sqlalchemy.orm import Session

from eom_orchestrator.native_query_checkpoints import (
    NATIVE_PRIVATE_QUERY_COORDINATOR_PROTOCOL as NATIVE_PRIVATE_QUERY_COORDINATOR_PROTOCOL,
)
from eom_orchestrator.native_query_checkpoints import (
    NativeQueryCheckpointStore,
    NativeQueryHistory,
    NativeQueryHistoryError,
)


class NativePrivateQueryHistoryError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class NativePrivateChatQueryHistory:
    state: str
    launch: PrivateChatQueryLaunchAssociation
    records: tuple[NativePrivateChatQueryCheckpoint, ...]


class NativePrivateChatQueryCoordinator:
    def __init__(
        self, request: PrivateChatQueryWorkflowRequest, launch: PrivateChatQueryLaunchAssociation
    ) -> None:
        self.request = PrivateChatQueryWorkflowRequest.model_validate(
            raw_similarity_contract_value(request)
        )
        self.launch = PrivateChatQueryLaunchAssociation.model_validate(
            raw_similarity_contract_value(launch)
        )
        self._store = NativeQueryCheckpointStore(self.request, self.launch)

    def _history(self, value: NativeQueryHistory) -> NativePrivateChatQueryHistory:
        assert isinstance(value.launch, PrivateChatQueryLaunchAssociation)
        return NativePrivateChatQueryHistory(
            value.state,
            value.launch,
            cast(tuple[NativePrivateChatQueryCheckpoint, ...], value.records),
        )

    def read(self, session: Session) -> NativePrivateChatQueryHistory:
        try:
            return self._history(self._store.read(session))
        except NativeQueryHistoryError as error:
            raise NativePrivateQueryHistoryError(str(error)) from None

    def append(
        self, session: Session, record: NativePrivateChatQueryCheckpoint
    ) -> NativePrivateChatQueryHistory:
        try:
            return self._history(self._store.append(session, record))
        except NativeQueryHistoryError as error:
            raise NativePrivateQueryHistoryError(str(error)) from None

    def record_known_failure(self, session: Session) -> NativePrivateChatQueryHistory:
        try:
            return self._history(self._store.record_known_failure(session))
        except NativeQueryHistoryError as error:
            raise NativePrivateQueryHistoryError(str(error)) from None
