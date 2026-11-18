"""Adopt observed manual-room capability through existing private Artifact publication.

This deliberately does not launch a browser, invent measured capabilities, activate
a binding or create a second task queue. A collection owner must pin this exact
receipt and its installed adapter before it can issue a future capture command.
"""

from __future__ import annotations

import re
import tempfile
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid5

from eom_catalog_contracts.kakao_capability import (
    CAPABILITY_VERIFICATION_REF,
    CAPABILITY_VERIFICATION_REFS,
    CSV_POPUP_CAPABILITY_VERIFICATION_REF,
    CapabilityVerification,
    ConfirmKakaoCapability,
    KakaoCapabilityVerification,
    KakaoCsvPopupCapabilityVerification,
    capability_verification_type,
)
from eom_catalog_contracts.kakao_room_intake import (
    MANUAL_ROOM_EVIDENCE_REFS,
    KakaoCsvPopupRoomEvidence,
    ManualRoomEvidence,
    manual_channel_identity_sha256,
    manual_room_evidence_type,
    observed_manual_room_keys,
)
from eom_catalog_contracts.kakao_rooms import ROOM_OBSERVATION_REF, KakaoRoomObservation
from eom_catalog_contracts.kakao_source import CAPTURE_REF
from eom_identifiers import canonical_json_bytes, sha256_bytes
from eom_kakao_archive_contracts.capture import CaptureCapability, validate_capture_contract
from eom_kakao_archive_contracts.manual_observation import (
    MANUAL_PAGE_OBSERVATION_REF,
    MAX_OBSERVATION_BYTES,
    ManualPageObservation,
)
from eom_kakao_archive_contracts.render import LocalMember
from eom_operator_identity import ActorContext, PermissionKey
from eom_orchestrator.database import build_session_factory
from eom_orchestrator.repository import IdempotencyConflict
from eom_protocol.artifact_members import ArtifactMemberPointer
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from .artifacts import CatalogArtifactService
from .kakao_archive_authorization import (
    KakaoArchiveError,
    authorize_kakao_actor,
    authorize_kakao_room_scope,
)
from .kakao_archive_commands import (
    kakao_command_sha256,
    lock_kakao_intent,
    validate_kakao_idempotency_key,
)
from .kakao_archive_models import KakaoChannelBindingRecord
from .kakao_capability_models import KakaoCapabilityAcceptanceRecord as Receipt
from .kakao_manual_capture_access import authorize_owned_manual_capture
from .kakao_room_csv_identity import observed_csv_popup_room_keys
from .kakao_room_intake_models import KakaoManualChannelPinRecord
from .kakao_source_pointers import (
    resolve_pinned_kakao_json_member,
    validate_source_pointer_metadata_batch,
)

_REVISION_NAMESPACE = UUID("5fcc213e-63b5-4b07-bb2c-23305307f966")
_INVALID = "KAKAO_ARCHIVE_CAPABILITY_EVIDENCE_INVALID"
_OBSERVED_FIELDS = (
    "message_identity",
    "csv_scope",
    "csv_order",
    "source_timezone",
    "direction_evidence",
    "album_enumeration",
    "original_download",
    "opening_marks_read",
)


@dataclass(frozen=True, slots=True)
class _RoomScope:
    owner: str
    binding_version: int
    observation: ArtifactMemberPointer
    identity_sha256: str
    channel_sha256: str


@dataclass(frozen=True, slots=True)
class _Receipt:
    owner: str
    binding: str
    room: str
    revision: str
    key: str
    request_sha256: str
    adapter_sha256: str
    manifest: ArtifactMemberPointer
    accepted_at: datetime


@dataclass(frozen=True, slots=True)
class AcceptedKakaoCapability:
    verification: CapabilityVerification
    capability: CaptureCapability
    manifest: ArtifactMemberPointer
    capability_pointer: ArtifactMemberPointer
    accepted_at: datetime
    replayed: bool


@dataclass(frozen=True, slots=True)
class PinnedManualRoomInput:
    capability: CaptureCapability
    proof: ManualRoomEvidence = field(repr=False)
    space_key: str = field(repr=False)


def _reserved_revision(owner: str, binding: str, key: str) -> str:
    # Identity is stable for a command, not derived from file bytes or a mutable latest value.
    name = canonical_json_bytes(dict(owner=owner, binding=binding, key=key)).decode("utf-8")
    return "kakaocapabilityrev_" + uuid5(_REVISION_NAMESPACE, name).hex


def manual_room_capability(
    proof: ManualRoomEvidence, proof_bytes: bytes, *, revision: str, adapter_sha256: str
) -> CaptureCapability:
    """Project previously authorized evidence; this value grants no execution permission."""
    if len(proof_bytes) > 32768 or type(proof).model_validate_json(proof_bytes) != proof:
        raise ValueError(_INVALID)
    value = CaptureCapability(
        source_binding_id=proof.confirmation.source_binding_id,
        capability_revision_id=revision,
        adapter_release_sha256=adapter_sha256,
        observed_at=proof.observed_at,
        channel_verified=True,
        room_identity="manual_binding",
        message_identity="unknown",
        csv_scope="unknown",
        csv_order="unknown",
        source_timezone="unknown",
        direction_evidence="unknown",
        album_enumeration="unknown",
        original_download="unknown",
        opening_marks_read="unknown",
        visible_scope_ids=("MANUAL_SELECTED_ROOM",),
        evidence=(
            LocalMember(
                relative_path="inputs/manual-room-proof.json",
                media_type="application/json",
                size_bytes=len(proof_bytes),
                sha256=sha256_bytes(proof_bytes),
            ),
        ),
    )
    validate_capture_contract("capability", value.model_dump(mode="json"))
    return value


def capability_within_observed_evidence(
    claimed: CaptureCapability, supported: CaptureCapability
) -> bool:
    # Learning to recognize more source metadata must not rewrite or invalidate
    # a historical UNKNOWN. Exact identity/evidence pins are never substituted.
    conservative = {
        name: getattr(supported, name)
        for name in _OBSERVED_FIELDS
        if getattr(claimed, name) == "unknown"
    }
    return claimed.model_copy(update=conservative) == supported


class KakaoCapabilityService:
    def __init__(
        self, engine: Engine, *, artifacts: CatalogArtifactService, adapter_release_sha256: str
    ) -> None:
        # A composition-owned installed release pin, never a public request/worker assertion.
        if re.fullmatch(r"sha256:[0-9a-f]{64}", adapter_release_sha256) is None:
            raise ValueError("KAKAO_ARCHIVE_CAPABILITY_ADAPTER_INVALID")
        self._sessions = build_session_factory(engine)
        self.artifacts, self.adapter_sha256 = artifacts, adapter_release_sha256

    def _scope(
        self, session: Session, actor: ActorContext, binding: str, room_id: str, *, mutate: bool
    ) -> _RoomScope:
        permission = (
            PermissionKey.KAKAO_ARCHIVE_COLLECT if mutate else PermissionKey.KAKAO_ARCHIVE_READ
        )
        owner = authorize_kakao_actor(
            session, actor, permission, now=datetime.now(UTC), admin_only=mutate
        )
        _, room = authorize_kakao_room_scope(
            session, actor, binding, room_id, permission, lock=mutate
        )
        pin = session.get(KakaoManualChannelPinRecord, binding)
        if (
            pin is None
            or pin.owner_operator_id != owner
            or room.identity_level != "MANUAL_CONFIRMED"
        ):
            raise KakaoArchiveError("KAKAO_ARCHIVE_CAPABILITY_UNVERIFIED")
        current_binding = session.get(KakaoChannelBindingRecord, binding)
        if current_binding is None:
            raise KakaoArchiveError("KAKAO_ARCHIVE_RESOURCE_NOT_FOUND")
        observation = ArtifactMemberPointer(
            artifact_id=room.evidence_artifact_id,
            artifact_revision_id=room.evidence_artifact_revision_id,
            member_path="observation.json",
            media_type="application/json",
            schema_ref=ROOM_OBSERVATION_REF,
            sha256=room.evidence_sha256,
        )
        resolve_pinned_kakao_json_member(
            session,
            artifact_id=pin.evidence_artifact_id,
            revision_id=pin.evidence_artifact_revision_id,
            member_path="proof.json",
            sha256=pin.evidence_sha256,
            permitted_schemas=MANUAL_ROOM_EVIDENCE_REFS,
        )
        validate_source_pointer_metadata_batch(session, (observation,))
        return _RoomScope(
            owner,
            current_binding.resource_version,
            observation,
            room.source_identity_sha256,
            pin.channel_key_sha256,
        )

    def _read(self, pointer: ArtifactMemberPointer, schema: str, *, maximum: int = 32768) -> bytes:
        if pointer.schema_ref != schema or pointer.media_type != "application/json":
            raise KakaoArchiveError(_INVALID)
        try:
            opened = self.artifacts.open_verified_member(
                artifact_id=pointer.artifact_id,
                revision_id=pointer.artifact_revision_id,
                member_path=pointer.member_path,
                sha256=pointer.sha256,
                schema_ref=schema,
                media_type="application/json",
                max_bytes=maximum,
            )
            with opened.stream as stream:
                raw = stream.read(maximum + 1)
            if len(raw) != opened.content_length or sha256_bytes(raw) != pointer.sha256:
                raise ValueError(_INVALID)
            return raw
        except (OSError, ValueError):
            raise KakaoArchiveError(_INVALID) from None

    def _room_evidence(
        self, context: _RoomScope
    ) -> tuple[KakaoRoomObservation, ManualRoomEvidence, bytes]:
        try:
            observation = KakaoRoomObservation.model_validate_json(
                self._read(context.observation, ROOM_OBSERVATION_REF)
            )
            schema = observation.source_evidence.schema_ref
            proof_type = manual_room_evidence_type(schema)
            raw = self._read(observation.source_evidence, schema)
            proof = proof_type.model_validate_json(raw)
            return observation, proof, raw
        except ValueError:
            raise KakaoArchiveError(_INVALID) from None

    def read_pinned_manual_room(
        self, pointer: ArtifactMemberPointer, *, binding: str, room: str, revision: str
    ) -> PinnedManualRoomInput:
        """Artifact proof reader for an already reauthorized, accepted collection intent."""
        try:
            manifest = self._read_verification(pointer)
            if (
                manifest.request.source_binding_id,
                manifest.request.room_id,
                manifest.capability_revision_id,
                manifest.adapter_release_sha256,
            ) != (binding, room, revision, self.adapter_sha256):
                raise ValueError(_INVALID)
            observation = KakaoRoomObservation.model_validate_json(
                self._read(manifest.room_observation, ROOM_OBSERVATION_REF)
            )
            schema = manifest.manual_proof.schema_ref
            proof_type = manual_room_evidence_type(schema)
            proof_raw = self._read(manifest.manual_proof, schema)
            proof = proof_type.model_validate_json(proof_raw)
            if (
                observation.source_evidence != manifest.manual_proof
                or observation.source_binding_id != binding
                or observation.identity_level != "MANUAL_CONFIRMED"
                or observation.source_identity_sha256 != proof.source_identity_sha256
                or observation.observed_at != proof.observed_at
                or proof.confirmation.source_binding_id != binding
                or proof.owner_operator_id != manifest.created_by
            ):
                raise ValueError(_INVALID)
            # Reconstruct only the supported observation bounds; the accepted
            # capability may intentionally claim fewer. Its artifact remains canonical.
            supported = manual_room_capability(
                proof, proof_raw, revision=revision, adapter_sha256=self.adapter_sha256
            )
            cap_pointer = ArtifactMemberPointer(
                artifact_id=pointer.artifact_id,
                artifact_revision_id=pointer.artifact_revision_id,
                member_path="capability.json",
                schema_ref=CAPTURE_REF,
                media_type="application/json",
                sha256=manifest.capability_sha256,
            )
            capability = CaptureCapability.model_validate_json(self._read(cap_pointer, CAPTURE_REF))
            if sha256_bytes(
                canonical_json_bytes(capability.model_dump(mode="json"))
            ) != cap_pointer.sha256 or not capability_within_observed_evidence(
                capability, supported
            ):
                raise ValueError(_INVALID)
            page_pointer = ArtifactMemberPointer(
                artifact_id=manifest.manual_proof.artifact_id,
                artifact_revision_id=manifest.manual_proof.artifact_revision_id,
                member_path="page-observation.json",
                schema_ref=MANUAL_PAGE_OBSERVATION_REF,
                media_type="application/json",
                sha256=proof.observation_sha256,
            )
            page = ManualPageObservation.model_validate_json(
                self._read(
                    page_pointer,
                    MANUAL_PAGE_OBSERVATION_REF,
                    maximum=MAX_OBSERVATION_BYTES,
                )
            )
            if (
                page.status != "OBSERVED"
                or page.document is None
                or page.capture_id != proof.confirmation.capture_id
                or any(
                    getattr(page, name) != getattr(proof, name)
                    for name in (
                        "profile_id",
                        "browser_run_id",
                        "fence_epoch",
                        "page_instance_id",
                        "observed_at",
                    )
                )
            ):
                raise ValueError(_INVALID)
            keys = (
                observed_csv_popup_room_keys(page)
                if isinstance(proof, KakaoCsvPopupRoomEvidence)
                else observed_manual_room_keys(page.document.path, page.target.path or "")
                if page.target.kind == "SAME_ORIGIN_PATH"
                else None
            )
            if keys != (
                proof.confirmation.expected_channel_key,
                proof.confirmation.expected_room_key,
            ):
                raise ValueError(_INVALID)
            return PinnedManualRoomInput(capability, proof, page.document.path.split("/")[2])
        except ValueError:
            raise KakaoArchiveError(_INVALID) from None

    def _validate(
        self,
        session: Session,
        actor: ActorContext,
        command: ConfirmKakaoCapability,
        observation: KakaoRoomObservation,
        proof: ManualRoomEvidence,
        *,
        mutate: bool,
    ) -> _RoomScope:
        context = self._scope(
            session, actor, command.source_binding_id, command.room_id, mutate=mutate
        )
        if (
            proof.owner_operator_id != context.owner
            or observation.source_binding_id != command.source_binding_id
            or proof.confirmation.source_binding_id != command.source_binding_id
            or observation.identity_level != "MANUAL_CONFIRMED"
            or observation.source_identity_sha256 != context.identity_sha256
            or proof.source_identity_sha256 != context.identity_sha256
            or observation.observed_at != proof.observed_at
            or context.channel_sha256
            != manual_channel_identity_sha256(proof.confirmation.expected_channel_key)
            or sha256_bytes(canonical_json_bytes(observation.model_dump(mode="json")))
            != context.observation.sha256
        ):
            raise KakaoArchiveError(_INVALID)
        if mutate:
            # Check the original owner/window without renewing its remote session.
            authorize_owned_manual_capture(session, actor, proof.confirmation).validate_evidence(
                proof
            )
        validate_source_pointer_metadata_batch(session, (observation.source_evidence,))
        return context

    @staticmethod
    def _receipt(session: Session, row: Receipt) -> _Receipt:
        return _Receipt(
            row.owner_operator_id,
            row.source_binding_id,
            row.room_id,
            row.capability_revision_id,
            row.idempotency_key,
            row.request_sha256,
            row.adapter_release_sha256,
            resolve_pinned_kakao_json_member(
                session,
                artifact_id=row.manifest_artifact_id,
                revision_id=row.manifest_artifact_revision_id,
                member_path="verification.json",
                sha256=row.manifest_sha256,
                permitted_schemas=CAPABILITY_VERIFICATION_REFS,
            ),
            row.accepted_at,
        )

    def _read_verification(self, pointer: ArtifactMemberPointer) -> CapabilityVerification:
        model = capability_verification_type(pointer.schema_ref)
        return model.model_validate_json(self._read(pointer, pointer.schema_ref))

    def _resolve(
        self, actor: ActorContext, stored: _Receipt, *, replayed: bool
    ) -> AcceptedKakaoCapability:
        try:
            verification = self._read_verification(stored.manifest)
            command = verification.request
            if (
                verification.created_by,
                verification.capability_revision_id,
                verification.request_sha256,
                verification.adapter_release_sha256,
                command.source_binding_id,
                command.room_id,
            ) != (
                stored.owner,
                stored.revision,
                stored.request_sha256,
                stored.adapter_sha256,
                stored.binding,
                stored.room,
            ) or stored.revision != _reserved_revision(stored.owner, stored.binding, stored.key):
                raise ValueError(_INVALID)
            capability_pointer = ArtifactMemberPointer(
                artifact_id=stored.manifest.artifact_id,
                artifact_revision_id=stored.manifest.artifact_revision_id,
                member_path="capability.json",
                schema_ref=CAPTURE_REF,
                media_type="application/json",
                sha256=verification.capability_sha256,
            )
            raw = self._read(capability_pointer, CAPTURE_REF)
            capability = CaptureCapability.model_validate_json(raw)
            validate_capture_contract("capability", capability.model_dump(mode="json"))
            with self._sessions.begin() as session:
                context = self._scope(
                    session, actor, command.source_binding_id, command.room_id, mutate=False
                )
            if context.observation != verification.room_observation:
                raise ValueError(_INVALID)
            observation, proof, proof_bytes = self._room_evidence(context)
            if (
                observation.source_evidence != verification.manual_proof
                or not capability_within_observed_evidence(
                    capability,
                    manual_room_capability(
                        proof,
                        proof_bytes,
                        revision=stored.revision,
                        adapter_sha256=stored.adapter_sha256,
                    ),
                )
            ):
                raise ValueError(_INVALID)
        except ValueError as error:
            if isinstance(error, KakaoArchiveError):
                raise
            raise KakaoArchiveError(_INVALID) from None
        with self._sessions.begin() as session:
            self._validate(session, actor, command, observation, proof, mutate=False)
            row = session.get(Receipt, stored.revision, populate_existing=True)
            if row is None or self._receipt(session, row) != stored:
                raise KakaoArchiveError(_INVALID)
            validate_source_pointer_metadata_batch(session, (stored.manifest, capability_pointer))
        return AcceptedKakaoCapability(
            verification,
            capability,
            stored.manifest,
            capability_pointer,
            stored.accepted_at,
            replayed,
        )

    def get_capability(
        self, actor: ActorContext, binding: str, revision: str
    ) -> AcceptedKakaoCapability:
        if re.fullmatch(r"kakaocapabilityrev_[0-9a-f]{32}", revision) is None:
            raise KakaoArchiveError("KAKAO_ARCHIVE_REQUEST_INVALID")
        with self._sessions.begin() as session:
            owner = authorize_kakao_actor(
                session, actor, PermissionKey.KAKAO_ARCHIVE_READ, now=datetime.now(UTC)
            )
            row = session.scalar(
                select(Receipt).where(
                    Receipt.capability_revision_id == revision,
                    Receipt.source_binding_id == binding,
                    Receipt.owner_operator_id == owner,
                )
            )
            if row is None:
                raise KakaoArchiveError("KAKAO_ARCHIVE_RESOURCE_NOT_FOUND")
            self._scope(session, actor, binding, row.room_id, mutate=False)
            stored = self._receipt(session, row)
        return self._resolve(actor, stored, replayed=False)

    def confirm_capability(
        self, actor: ActorContext, command: ConfirmKakaoCapability, *, idempotency_key: str
    ) -> AcceptedKakaoCapability:
        command = ConfirmKakaoCapability.model_validate(command.model_dump(mode="json"))
        key, digest = validate_kakao_idempotency_key(idempotency_key), kakao_command_sha256(command)
        with self._sessions.begin() as session:
            context = self._scope(
                session, actor, command.source_binding_id, command.room_id, mutate=True
            )
            prior = session.scalar(
                select(Receipt).where(
                    Receipt.owner_operator_id == context.owner,
                    Receipt.source_binding_id == command.source_binding_id,
                    Receipt.idempotency_key == key,
                )
            )
            stored = self._receipt(session, prior) if prior is not None else None
        if stored is not None:
            if stored.request_sha256 != digest:
                raise KakaoArchiveError("KAKAO_ARCHIVE_IDEMPOTENCY_CONFLICT")
            return self._resolve(actor, stored, replayed=True)
        if context.binding_version != command.expected_binding_version:
            raise KakaoArchiveError("KAKAO_ARCHIVE_PRECONDITION_FAILED")
        observation, proof, proof_bytes = self._room_evidence(context)

        def authorize() -> None:
            with self._sessions.begin() as session:
                current = self._validate(session, actor, command, observation, proof, mutate=True)
                if (
                    current.binding_version != command.expected_binding_version
                    or current.observation != context.observation
                ):
                    raise KakaoArchiveError("KAKAO_ARCHIVE_PRECONDITION_FAILED")

        authorize()
        revision = _reserved_revision(context.owner, command.source_binding_id, key)
        capability = manual_room_capability(
            proof, proof_bytes, revision=revision, adapter_sha256=self.adapter_sha256
        )
        cap_raw = canonical_json_bytes(capability.model_dump(mode="json"))
        csv_proof = isinstance(proof, KakaoCsvPopupRoomEvidence)
        verification_type = (
            KakaoCsvPopupCapabilityVerification if csv_proof else KakaoCapabilityVerification
        )
        verification_ref = (
            CSV_POPUP_CAPABILITY_VERIFICATION_REF if csv_proof else CAPABILITY_VERIFICATION_REF
        )
        verification = verification_type(
            request=command,
            request_sha256=digest,
            created_by=context.owner,
            capability_revision_id=revision,
            adapter_release_sha256=self.adapter_sha256,
            room_observation=context.observation,
            manual_proof=observation.source_evidence,
            capability_sha256=sha256_bytes(cap_raw),
        )
        proof_raw = canonical_json_bytes(verification.model_dump(mode="json"))
        scope = sha256_bytes(
            canonical_json_bytes(
                dict(owner=context.owner, binding=command.source_binding_id, key=key)
            )
        )[7:]
        try:
            with tempfile.TemporaryDirectory(
                prefix="kakao-capability.", dir=self.artifacts.settings.staging_root
            ) as folder:
                paths = {
                    name: Path(folder) / name for name in ("capability.json", "verification.json")
                }
                paths["capability.json"].write_bytes(cap_raw)
                paths["verification.json"].write_bytes(proof_raw)
                authorize()
                artifact = self.artifacts.commit_file_set(
                    files=paths,
                    primary_file="verification.json",
                    artifact_type="kakao-capability-verification",
                    idempotency_key="kakao:capability:" + scope,
                    request=dict(
                        owner=context.owner,
                        request_sha256=digest,
                        adapter_release_sha256=self.adapter_sha256,
                    ),
                    result=dict(sha256=sha256_bytes(proof_raw)),
                    file_metadata={
                        name: dict(schema_ref=schema, media_type="application/json")
                        for name, schema in (
                            ("capability.json", CAPTURE_REF),
                            ("verification.json", verification_ref),
                        )
                    },
                    expected_file_sha256={
                        "capability.json": sha256_bytes(cap_raw),
                        "verification.json": sha256_bytes(proof_raw),
                    },
                )
        except IdempotencyConflict:
            raise KakaoArchiveError("KAKAO_ARCHIVE_IDEMPOTENCY_CONFLICT") from None
        if artifact.content_hash != sha256_bytes(proof_raw):
            raise KakaoArchiveError(_INVALID)
        with self._sessions.begin() as session:
            lock_kakao_intent(
                session, context.owner, "capability/" + command.source_binding_id, key
            )
            current = self._validate(session, actor, command, observation, proof, mutate=True)
            prior = session.scalar(
                select(Receipt).where(
                    Receipt.owner_operator_id == current.owner,
                    Receipt.source_binding_id == command.source_binding_id,
                    Receipt.idempotency_key == key,
                )
            )
            if prior is not None:
                if prior.request_sha256 != digest:
                    raise KakaoArchiveError("KAKAO_ARCHIVE_IDEMPOTENCY_CONFLICT")
                stored, replayed = self._receipt(session, prior), True
            else:
                if (
                    current.binding_version != command.expected_binding_version
                    or current.observation != context.observation
                ):
                    raise KakaoArchiveError("KAKAO_ARCHIVE_PRECONDITION_FAILED")
                row = Receipt(
                    capability_revision_id=revision,
                    owner_operator_id=current.owner,
                    source_binding_id=command.source_binding_id,
                    room_id=command.room_id,
                    idempotency_key=key,
                    request_sha256=digest,
                    manifest_artifact_id=artifact.artifact_id,
                    manifest_artifact_revision_id=artifact.revision_id,
                    manifest_sha256=artifact.content_hash,
                    adapter_release_sha256=self.adapter_sha256,
                    accepted_at=datetime.now(UTC),
                )
                stored = self._receipt(session, row)
                session.add(row)
                replayed = False
        return self._resolve(actor, stored, replayed=replayed)
