"""Orchestrator-only chat evidence publication and bounded canonical resolution."""

from __future__ import annotations

from datetime import datetime
from threading import Lock
from typing import Protocol

from eom_protocol.artifact_members import ArtifactMemberPointer
from eom_protocol.general_chat import (
    CHAT_INPUT_SCHEMA,
    CHAT_MEMBER,
    CHAT_MESSAGE_SCHEMA,
    CHAT_RESULT_SCHEMA,
)
from eom_protocol.general_chat_dispatch import CHAT_DISPATCH_SCHEMA
from eom_protocol.general_chat_evidence_families import chat_evidence_schema_family
from eom_protocol.general_chat_grounding import (
    AGENT_INPUT_SCHEMA,
    AGENT_RESULT_SCHEMA,
    GROUNDED_INPUT_SCHEMA,
    GROUNDED_MESSAGE_SCHEMA,
    GROUNDED_RESULT_SCHEMA,
)
from eom_protocol.general_chat_rag_tools import RAG_TOOL_RECORD_SCHEMA
from eom_protocol.general_chat_rag_turn import RAG_INPUT_SCHEMA, RAG_RESULT_SCHEMA
from sqlalchemy import Engine, select, tuple_

from eom_orchestrator.control_artifact_resolution import (
    BoundedControlArtifactRead,
    resolve_control_artifact_members,
)
from eom_orchestrator.control_artifacts import ControlArtifactPublisher
from eom_orchestrator.models import ArtifactRevisionRecord


class ChatEvidencePort(Protocol):
    def publish(
        self,
        *,
        payload: bytes,
        schema_ref: str,
        intent: str,
        created_at: datetime,
    ) -> ArtifactMemberPointer: ...

    def read(self, pointers: tuple[ArtifactMemberPointer, ...]) -> tuple[bytes, ...]: ...

    def resolve_family(
        self, pointers: tuple[ArtifactMemberPointer, ...]
    ) -> tuple[ArtifactMemberPointer, ...]: ...


class GeneralChatArtifactStore:
    """Reuse the sole resumable Artifact commit owner; never called in the API process."""

    def __init__(
        self,
        engine: Engine,
        publisher: ControlArtifactPublisher,
        *,
        source_commit: str,
    ) -> None:
        if len(source_commit) != 40 or any(c not in "0123456789abcdef" for c in source_commit):
            raise ValueError("chat evidence requires an installed source identity")
        self.engine = engine
        if publisher.engine.pool is engine.pool:
            raise ValueError("chat publication requires an independent connection pool")
        self.publisher = publisher
        self.source_commit = source_commit
        # Waiting intent/conversation transactions can fill the metadata pool.
        # One publication uses its own two-connection pool (advisory lock + commit),
        # so it cannot deadlock behind the requests it must unblock.
        self._publication_lock = Lock()

    def publish(
        self,
        *,
        payload: bytes,
        schema_ref: str,
        intent: str,
        created_at: datetime,
    ) -> ArtifactMemberPointer:
        if schema_ref not in {
            CHAT_MESSAGE_SCHEMA,
            CHAT_INPUT_SCHEMA,
            CHAT_RESULT_SCHEMA,
            CHAT_DISPATCH_SCHEMA,
            GROUNDED_MESSAGE_SCHEMA,
            GROUNDED_INPUT_SCHEMA,
            GROUNDED_RESULT_SCHEMA,
            "eom://schemas/general-chat/dispatch/2.0",
            AGENT_INPUT_SCHEMA,
            AGENT_RESULT_SCHEMA,
            "eom://schemas/general-chat/dispatch/3.0",
            "eom://schemas/general-chat/tool-record/1.0",
            RAG_INPUT_SCHEMA,
            RAG_RESULT_SCHEMA,
            "eom://schemas/general-chat/dispatch/4.0",
            "eom://schemas/general-chat/dispatch/5.0",
            RAG_TOOL_RECORD_SCHEMA,
        }:
            raise ValueError("unsupported chat evidence schema")
        if not 0 < len(payload) <= 256000:
            raise ValueError("chat evidence exceeds materialization budget")
        with self._publication_lock:
            receipt = self.publisher.publish_bytes(
                payload=payload,
                logical_name=CHAT_MEMBER,
                schema_ref=schema_ref,
                media_type="application/json",
                artifact_type="control_general_chat_evidence",
                idempotency_key=intent,
                created_at=created_at,
                source_commit=self.source_commit,
            )
        pointer = receipt.pointer
        return ArtifactMemberPointer(
            artifact_id=pointer.artifact_id,
            artifact_revision_id=pointer.artifact_revision_id,
            member_path=pointer.logical_name,
            schema_ref=pointer.schema_ref,
            media_type=pointer.media_type,
            sha256=pointer.sha256,
        )

    def read(self, pointers: tuple[ArtifactMemberPointer, ...]) -> tuple[bytes, ...]:
        if not pointers:
            return ()
        return tuple(
            payload
            for offset in range(0, len(pointers), 128)
            for payload in resolve_control_artifact_members(
                self.engine,
                tuple(
                    BoundedControlArtifactRead(pointer=p, maximum_bytes=256000)
                    for p in pointers[offset : offset + 128]
                ),
            )
        )

    def resolve_family(
        self, pointers: tuple[ArtifactMemberPointer, ...]
    ) -> tuple[ArtifactMemberPointer, ...]:
        """Resolve only registered schemas in a closed family, never infer from JSON."""
        if not pointers:
            return ()
        if len(pointers) > 150:
            raise ValueError("chat pointer budget exceeded")
        keys = {(p.artifact_id, p.artifact_revision_id) for p in pointers}
        with self.engine.connect() as connection:
            rows = connection.execute(
                select(
                    ArtifactRevisionRecord.logical_artifact_id,
                    ArtifactRevisionRecord.revision_id,
                    ArtifactRevisionRecord.manifest,
                ).where(
                    tuple_(
                        ArtifactRevisionRecord.logical_artifact_id,
                        ArtifactRevisionRecord.revision_id,
                    ).in_(keys)
                )
            ).all()
        manifests = {(a, r): m for a, r, m in rows}
        result = []
        for pointer in pointers:
            manifest = manifests.get((pointer.artifact_id, pointer.artifact_revision_id))
            files = manifest.get("files") if isinstance(manifest, dict) else None
            matching = (
                [m for m in files if isinstance(m, dict) and m.get("file_name") == CHAT_MEMBER]
                if isinstance(files, list)
                else []
            )
            if (
                len(matching) != 1
                or matching[0].get("schema_ref")
                not in chat_evidence_schema_family(pointer.schema_ref)
                or matching[0].get("sha256") != pointer.sha256
                or matching[0].get("media_type") != "application/json"
            ):
                raise ValueError("registered chat evidence family differs")
            result.append(pointer.model_copy(update={"schema_ref": matching[0]["schema_ref"]}))
        return tuple(result)
