"""Publish the existing C1 inputs for a manually verified, already accepted room."""

import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from uuid import UUID, uuid5

from eom_catalog_contracts.kakao_collection_attempt import KakaoCollectionAttempt
from eom_catalog_contracts.kakao_source import CAPTURE_REF
from eom_identifiers import canonical_json_bytes, sha256_bytes
from eom_kakao_archive_contracts.capture import (
    CaptureCommand,
    CaptureInventory,
    InventoryRoom,
    InventoryScope,
    validate_capture_inputs,
)
from eom_kakao_archive_contracts.execution import WorkerExecution
from eom_kakao_archive_contracts.render import LocalMember
from eom_orchestrator.file_set_control_artifacts import (
    ControlFileSetMember,
    ControlFileSetPublisher,
)
from eom_protocol.artifact_members import ArtifactMemberPointer

from .kakao_archive_authorization import KakaoArchiveError
from .kakao_capability_service import PinnedManualRoomInput
from .kakao_collection_attempt_service import KakaoCollectionAttemptService
from .kakao_collection_service import KakaoCollectionService, StoredKakaoCollectionIntent

_SCOPE = "MANUAL_SELECTED_ROOM"
_EVIDENCE = "outputs/selected-room.json"
_ARTIFACT_TYPE = "control_kakao_capture_inputs"
_POINTER_REF = "eom://schemas/artifact-member/1.0"
_NAMESPACE = UUID("67f9586e-97fd-4503-8fc4-e625cce24b64")


@dataclass(frozen=True, slots=True)
class PreparedKakaoRoom:
    attempt: KakaoCollectionAttempt
    room: tuple[str, str] = field(repr=False)
    space_key: str = field(repr=False)


def _member(name: str, raw: bytes) -> LocalMember:
    return LocalMember(
        relative_path=name,
        size_bytes=len(raw),
        sha256=sha256_bytes(raw),
        media_type="application/json",
    )


def read_registered_collection_room(
    collections: KakaoCollectionService, run_id: str
) -> tuple[StoredKakaoCollectionIntent, PinnedManualRoomInput]:
    stored = collections.read_background_intent(run_id)
    request = stored.accepted.request
    resolved = collections.capabilities.read_pinned_manual_room(
        stored.capability_manifest,
        binding=request.source_binding_id,
        room=request.room_id,
        revision=request.capability_revision_id,
    )
    if (
        resolved.capability.visible_scope_ids != (_SCOPE,)
        or resolved.capability.room_identity != "manual_binding"
    ):
        raise KakaoArchiveError("KAKAO_ARCHIVE_COLLECTION_CAPABILITY_MISMATCH")
    return stored, resolved


def prepare_kakao_registered_room(
    collections: KakaoCollectionService,
    attempts: KakaoCollectionAttemptService,
    attempt: KakaoCollectionAttempt,
    *,
    publisher: ControlFileSetPublisher,
    source_commit: str,
) -> PreparedKakaoRoom:
    stored, resolved = read_registered_collection_room(collections, attempt.run_id)
    accepted = stored.accepted
    request = accepted.request
    persisted = attempts.get_attempt(attempt.attempt_id)
    if (
        (attempt.task_id, attempt.room_id, attempt.source_binding_id)
        != (accepted.task_id, request.room_id, request.source_binding_id)
        or persisted != attempt.model_copy(update={"state": persisted.state})
        or persisted.state == "RESULT_ACCEPTED"
    ):
        raise KakaoArchiveError("KAKAO_ARCHIVE_CAPTURE_IDENTITY_MISMATCH")

    capability = resolved.capability
    proof = resolved.proof
    selection = canonical_json_bytes(stored.capability_manifest.model_dump(mode="json"))
    evidence = _member(_EVIDENCE, selection)
    execution = WorkerExecution(
        **{name: getattr(attempt, name) for name in WorkerExecution.model_fields}
    )
    inventory = CaptureInventory(
        execution=execution,
        run_id=attempt.run_id,
        source_binding_id=attempt.source_binding_id,
        inventory_revision_id="kakaoinventoryrev_" + uuid5(_NAMESPACE, attempt.attempt_id).hex,
        inventory_started_at=proof.observed_at,
        inventory_finished_at=proof.observed_at,
        reconciliation_pass_at=None,
        scopes=(
            InventoryScope(
                scope_id=_SCOPE,
                filters_cleared=False,
                end_reached=False,
                pending_loading=False,
                stabilization_completed=False,
                new_rooms_on_stabilization=0,
                evidence=evidence,
            ),
        ),
        rooms=(
            InventoryRoom(
                room_id=attempt.room_id,
                scope_ids=(_SCOPE,),
                identity_level="manual_binding",
                evidence=evidence,
            ),
        ),
        unresolved=(),
        inventory_complete=False,
    )
    inv_raw = canonical_json_bytes(inventory.model_dump(mode="json"))
    cap_raw = canonical_json_bytes(capability.model_dump(mode="json"))
    command = CaptureCommand(
        execution=execution,
        run_id=attempt.run_id,
        source_binding_id=attempt.source_binding_id,
        profile_id=attempt.profile_id,
        browser_run_id=attempt.browser_run_id,
        adapter_release_sha256=capability.adapter_release_sha256,
        capability_revision_id=capability.capability_revision_id,
        capability=_member("inputs/capability.json", cap_raw),
        issued_at=attempt.created_at,
        operation="CAPTURE_ROOM",
        requested_scope_ids=(_SCOPE,),
        inventory_revision_id=inventory.inventory_revision_id,
        inventory=_member("inputs/inventory.json", inv_raw),
        room_id=attempt.room_id,
        snapshot_revision_id=attempt.snapshot_revision_id,
        normalization_revision_id=attempt.normalization_revision_id,
    )
    validate_capture_inputs(command, capability, inventory)
    cmd_raw = canonical_json_bytes(command.model_dump(mode="json"))
    key = "kakao:capture-inputs:" + attempt.attempt_id
    current = collections.read_background_intent(attempt.run_id)
    if (current.accepted, current.capability_manifest) != (accepted, stored.capability_manifest):
        raise KakaoArchiveError("KAKAO_ARCHIVE_PRECONDITION_FAILED")
    pointer = publisher.find_published_primary_member(
        idempotency_key=key, artifact_type=_ARTIFACT_TYPE
    )
    if pointer is None:
        with tempfile.TemporaryDirectory(
            prefix="kakao-capture-inputs.", dir=attempts.artifacts.settings.staging_root
        ) as temporary:
            members = []
            for index, (name, raw, ref) in enumerate(
                (
                    ("command.json", cmd_raw, CAPTURE_REF),
                    ("inventory.json", inv_raw, CAPTURE_REF),
                    (_EVIDENCE, selection, _POINTER_REF),
                )
            ):
                path = Path(temporary) / str(index)
                with path.open("xb") as stream:
                    stream.write(raw)
                members.append(
                    ControlFileSetMember(
                        name, path, sha256_bytes(raw), len(raw), ref, "application/json"
                    )
                )
            published = publisher.publish_first_observation(
                members=tuple(members),
                primary_file="command.json",
                artifact_type=_ARTIFACT_TYPE,
                manifest_version="catalog-file-set/1.0",
                idempotency_key=key,
                source_commit=source_commit,
            )
        pointer = ArtifactMemberPointer(
            artifact_id=published.artifact_id,
            artifact_revision_id=published.artifact_revision_id,
            member_path=published.primary_file,
            schema_ref=CAPTURE_REF,
            media_type="application/json",
            sha256=published.primary_sha256,
        )
    if (pointer.member_path, pointer.sha256) != ("command.json", sha256_bytes(cmd_raw)):
        raise KakaoArchiveError("KAKAO_ARCHIVE_CAPTURE_IDENTITY_MISMATCH")
    inventory_pointer = ArtifactMemberPointer(
        artifact_id=pointer.artifact_id,
        artifact_revision_id=pointer.artifact_revision_id,
        member_path="inventory.json",
        schema_ref=CAPTURE_REF,
        media_type="application/json",
        sha256=sha256_bytes(inv_raw),
    )
    pinned = attempts.pin_command(attempt.attempt_id, pointer, inventory_pointer=inventory_pointer)
    return PreparedKakaoRoom(
        pinned,
        (proof.confirmation.expected_channel_key, proof.confirmation.expected_room_key),
        resolved.space_key,
    )
