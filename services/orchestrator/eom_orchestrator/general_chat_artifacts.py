"""Orchestrator-only chat evidence publication and bounded canonical resolution."""

from __future__ import annotations

import json
import tempfile
from datetime import datetime
from pathlib import Path
from threading import Lock
from typing import Protocol

from eom_catalog_contracts.chat_similarity_provenance import (
    CHAT_SIMILARITY_PROVENANCE_MEMBER,
    CHAT_SIMILARITY_PROVENANCE_REF,
    MAX_CHAT_SIMILARITY_PROVENANCE_BYTES,
    ChatSimilarityProvenance,
    ChatSimilarityProvenanceError,
    validate_chat_similarity_provenance,
)
from eom_identifiers import canonical_json_bytes, sha256_bytes
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
from eom_protocol.general_chat_rag_knowledge import read_rag
from eom_protocol.general_chat_rag_tools import RAG_TOOL_RECORD_SCHEMA, ChatToolRecordV2
from eom_protocol.general_chat_rag_turn import RAG_INPUT_SCHEMA, RAG_RESULT_SCHEMA
from sqlalchemy import Engine, select, tuple_

from eom_orchestrator.control_artifact_resolution import (
    BoundedControlArtifactRead,
    resolve_control_artifact_members,
)
from eom_orchestrator.control_artifacts import ControlArtifactPublisher
from eom_orchestrator.file_set_control_artifacts import (
    ControlFileSetMember,
    ControlFileSetPublisher,
)
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
        self.file_sets = ControlFileSetPublisher(publisher.engine, publisher.settings)
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

    def publish_similarity_record(
        self, record: ChatToolRecordV2, provenance: ChatSimilarityProvenance
    ) -> ArtifactMemberPointer:
        """One idempotent commit; the frozen V2 worker still receives its usual member."""
        provenance = validate_chat_similarity_provenance(record, provenance)
        payload = canonical_json_bytes(record.model_dump(mode="json"))
        companion = canonical_json_bytes(provenance.model_dump(mode="json"))
        if not 0 < len(payload) <= 256000:
            raise ChatSimilarityProvenanceError()
        staging = self.publisher.settings.staging_root
        staging.mkdir(parents=True, exist_ok=True)
        # This temporary materialization is local to the established commit owner.
        # The publisher owns persistent staging/crash recovery and the NAS commit.
        with (
            self._publication_lock,
            tempfile.TemporaryDirectory(prefix="chat-similarity-", dir=staging) as workspace,
        ):
            members = []
            for name, raw, schema in (
                (CHAT_MEMBER, payload, RAG_TOOL_RECORD_SCHEMA),
                (CHAT_SIMILARITY_PROVENANCE_MEMBER, companion, CHAT_SIMILARITY_PROVENANCE_REF),
            ):
                local = Path(workspace) / name
                local.parent.mkdir(parents=True, exist_ok=True)
                local.write_bytes(raw)
                local.chmod(0o600)
                members.append(
                    ControlFileSetMember(
                        file_name=name,
                        source=local,
                        sha256=sha256_bytes(raw),
                        bytes=len(raw),
                        schema_ref=schema,
                        media_type="application/json",
                    )
                )
            receipt = self.file_sets.publish_first_observation(
                members=tuple(members),
                primary_file=CHAT_MEMBER,
                artifact_type="control_general_chat_evidence",
                manifest_version="general-chat-tool-files/1.0",
                idempotency_key=f"chat-tool:{record.request.ticket.claim_id}:{record.request.sequence}",
                source_commit=self.source_commit,
            )
        if receipt.primary_file != CHAT_MEMBER or receipt.primary_sha256 != sha256_bytes(payload):
            raise ChatSimilarityProvenanceError()
        return ArtifactMemberPointer(
            artifact_id=receipt.artifact_id,
            artifact_revision_id=receipt.artifact_revision_id,
            member_path=CHAT_MEMBER,
            schema_ref=RAG_TOOL_RECORD_SCHEMA,
            media_type="application/json",
            sha256=receipt.primary_sha256,
        )

    def read_similarity_provenance(
        self, record_pointer: ArtifactMemberPointer
    ) -> ChatSimilarityProvenance | None:
        """Owner audit read, never private-claim reauthorization or a public citation."""
        if (
            record_pointer.member_path != CHAT_MEMBER
            or record_pointer.schema_ref != RAG_TOOL_RECORD_SCHEMA
            or record_pointer.media_type != "application/json"
        ):
            raise ChatSimilarityProvenanceError()
        raw = self.read((record_pointer,))[0]
        with self.engine.connect() as connection:
            manifest = connection.scalar(
                select(ArtifactRevisionRecord.manifest).where(
                    ArtifactRevisionRecord.logical_artifact_id == record_pointer.artifact_id,
                    ArtifactRevisionRecord.revision_id == record_pointer.artifact_revision_id,
                )
            )
        if not isinstance(manifest, dict):
            raise ChatSimilarityProvenanceError()
        files = manifest.get("files")
        if not isinstance(files, list):
            raise ChatSimilarityProvenanceError()
        matching = [
            member
            for member in files
            if isinstance(member, dict)
            and member.get("file_name") == CHAT_SIMILARITY_PROVENANCE_MEMBER
        ]
        if not matching:
            if manifest.get("manifest_version") == "general-chat-tool-files/1.0" or len(files) != 1:
                raise ChatSimilarityProvenanceError()
            return None  # A genuine legacy single-member tool record remains valid.
        if (
            len(matching) != 1
            or len(files) != 2
            or manifest.get("manifest_version") != "general-chat-tool-files/1.0"
            or manifest.get("primary_file") != CHAT_MEMBER
        ):
            raise ChatSimilarityProvenanceError()
        member = matching[0]
        if (
            member.get("schema_ref") != CHAT_SIMILARITY_PROVENANCE_REF
            or member.get("media_type") != "application/json"
        ):
            raise ChatSimilarityProvenanceError()
        pointer = ArtifactMemberPointer(
            artifact_id=record_pointer.artifact_id,
            artifact_revision_id=record_pointer.artifact_revision_id,
            member_path=CHAT_SIMILARITY_PROVENANCE_MEMBER,
            schema_ref=CHAT_SIMILARITY_PROVENANCE_REF,
            media_type="application/json",
            sha256=member["sha256"],
        )
        companion = resolve_control_artifact_members(
            self.engine,
            (
                BoundedControlArtifactRead(
                    pointer=pointer, maximum_bytes=MAX_CHAT_SIMILARITY_PROVENANCE_BYTES
                ),
            ),
        )[0]
        return validate_chat_similarity_provenance(
            read_rag("Record", json.loads(raw), ChatToolRecordV2), json.loads(companion)
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
