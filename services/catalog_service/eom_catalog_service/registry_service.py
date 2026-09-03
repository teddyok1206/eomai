"""Logical Item and immutable Item Revision application service."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import stat
from collections.abc import Generator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, BinaryIO, Literal, cast

from eom_catalog_contracts import (
    CATALOG_ITEM_MEDIA_MAX_BYTES,
    AssessmentItemContent,
    AssessmentItemContentContract,
    AssessmentItemContentV2,
    ImageBlock,
    MediaArtifactPointer,
    validate_contract,
)
from eom_identifiers import canonical_json_bytes, content_sha256, sha256_file
from eom_item_registry import (
    ComponentPointer,
    ItemRevisionState,
    ItemState,
    RegistrationRequest,
    RegistryError,
    RegistryErrorCode,
    new_item_component_id,
    new_item_id,
    new_item_metadata_id,
    new_item_provenance_id,
    new_item_revision_id,
)
from eom_orchestrator.database import build_session_factory, transaction
from eom_orchestrator.models import ArtifactRecord, ArtifactRevisionRecord
from eom_workflow_runner.models import WorkflowInstanceRecord, WorkflowStepRunRecord
from jsonschema import Draft202012Validator
from sqlalchemy import Engine, and_, or_, select
from sqlalchemy.orm import Session

from eom_catalog_service.artifacts import CatalogArtifactService
from eom_catalog_service.item_repository import append_item_event
from eom_catalog_service.models import (
    ContentIntakeBatchRecord,
    ContentPackRecord,
    ContentPackReleaseRecord,
    ItemComponentRecord,
    ItemMetadataSnapshotRecord,
    ItemProvenanceRecord,
    ItemRecord,
    ItemRelationshipRecord,
    ItemRevisionRecord,
    UsageRecord,
)
from eom_catalog_service.pack_resources import PackResourceResolver
from eom_catalog_service.settings import CatalogSettings
from eom_catalog_service.staging import stage_registry_manifest


@dataclass(frozen=True)
class ResolvedItemMedia:
    """Validated descriptor for one pinned image block; storage paths stay private."""

    stream: BinaryIO
    media_type: Literal["image/png", "image/jpeg"]
    content_length: int
    sha256: str

    def iter_chunks(self) -> Generator[bytes, None, None]:
        try:
            while chunk := self.stream.read(1024 * 1024):
                yield chunk
        finally:
            self.stream.close()


class RegistryService:
    def __init__(self, engine: Engine, settings: CatalogSettings | None = None) -> None:
        self.settings = settings or CatalogSettings.from_environment()
        self.sessions = build_session_factory(engine)
        self.artifacts = CatalogArtifactService(engine, self.settings)
        self.pack_resources = PackResourceResolver()

    def register(self, request: RegistrationRequest) -> ItemRevisionRecord:
        with self.sessions() as session:
            existing = session.scalar(
                select(ItemRevisionRecord).where(
                    ItemRevisionRecord.registration_key == request.registration_key
                )
            )
            if existing is not None:
                session.expunge(existing)
                return existing
            pack, pack_record, workflow = self._validate_registration_references(session, request)
            self._validate_metadata(session, pack, request.metadata)
            self._validate_components(session, request)
            if request.mode == "CREATE_ITEM":
                item_id = new_item_id()
                revision_number = 1
            else:
                if request.item_id is None or request.base_revision_id is None:
                    raise RegistryError(
                        RegistryErrorCode.ITEM_REVISION_CONFLICT,
                        "revision registration requires item and base revision pointers",
                    )
                item = session.get(ItemRecord, request.item_id)
                if item is None or item.current_revision_id != request.base_revision_id:
                    raise RegistryError(
                        RegistryErrorCode.ITEM_REVISION_CONFLICT,
                        "base revision is stale",
                    )
                base = session.get(ItemRevisionRecord, request.base_revision_id)
                if base is None or base.revision_state != ItemRevisionState.APPROVED.value:
                    raise RegistryError(
                        RegistryErrorCode.ITEM_REVISION_NOT_APPROVED,
                        "base revision is not approved",
                    )
                item_id = item.item_id
                revision_number = base.revision_number + 1
            pack_key = pack_record.pack_key

        revision_id = new_item_revision_id()
        metadata_hash = content_sha256(request.metadata)
        manifest = self._manifest(
            request,
            item_id=item_id,
            revision_id=revision_id,
            revision_number=revision_number,
            pack=pack,
            pack_key=pack_key,
            metadata_hash=metadata_hash,
            created_at=workflow.created_at,
        )
        validate_contract("item-revision-manifest", manifest)
        manifest_path = self._stage_registration_manifest(request.registration_key, manifest)
        artifact = self.artifacts.commit_file_set(
            files={"item-revision-manifest.json": manifest_path},
            primary_file="item-revision-manifest.json",
            artifact_type="item-revision-manifest",
            idempotency_key=f"item-registration:{request.registration_key}",
            request={"registration_key": request.registration_key},
            result={"item_id": item_id, "item_revision_id": revision_id},
        )

        with transaction(self.sessions) as session:
            existing = session.scalar(
                select(ItemRevisionRecord).where(
                    ItemRevisionRecord.registration_key == request.registration_key
                )
            )
            if existing is not None:
                session.expunge(existing)
                return existing
            if request.mode == "CREATE_ITEM":
                item = ItemRecord(
                    item_id=item_id,
                    human_reference_code=None,
                    lifecycle_state=ItemState.ACTIVE.value,
                    current_revision_id=None,
                    created_by=request.created_by,
                    lock_version=1,
                )
                session.add(item)
                session.flush()
            else:
                assert request.item_id is not None and request.base_revision_id is not None
                item = session.execute(
                    select(ItemRecord)
                    .where(ItemRecord.item_id == request.item_id)
                    .with_for_update()
                ).scalar_one()
                if item.current_revision_id != request.base_revision_id:
                    raise RegistryError(
                        RegistryErrorCode.CATALOG_CONCURRENCY_CONFLICT,
                        "current item revision changed during registration",
                    )
                base = session.execute(
                    select(ItemRevisionRecord)
                    .where(ItemRevisionRecord.item_revision_id == request.base_revision_id)
                    .with_for_update()
                ).scalar_one()
                if base.revision_state != ItemRevisionState.APPROVED.value:
                    raise RegistryError(
                        RegistryErrorCode.ITEM_REVISION_NOT_APPROVED,
                        "base revision is no longer approved",
                    )
            revision = ItemRevisionRecord(
                item_revision_id=revision_id,
                item_id=item.item_id,
                revision_number=revision_number,
                revision_state=ItemRevisionState.APPROVED.value,
                registration_key=request.registration_key,
                content_pack_release_id=request.content_pack_release_id,
                workflow_id=request.workflow_id,
                workflow_definition_version=request.workflow_definition_version,
                source_workflow_step_run_id=request.source_workflow_step_run_id,
                manifest_artifact_id=artifact.artifact_id,
                manifest_artifact_revision_id=artifact.revision_id,
                manifest_sha256=artifact.content_hash,
                item_type_key=request.item_type_key,
                primary_taxonomy_ref=request.primary_taxonomy_ref,
                difficulty_band=request.difficulty_band,
                metadata_json=request.metadata,
                metadata_sha256=metadata_hash,
                created_by=request.created_by,
                approved_at=datetime.now(UTC),
                approved_by=request.created_by,
                lock_version=1,
            )
            session.add(revision)
            session.flush()
            self._add_revision_children(session, revision, request, metadata_hash)
            prior_revision = item.current_revision_id
            if prior_revision is not None:
                base = session.get(ItemRevisionRecord, prior_revision)
                assert base is not None
                base.revision_state = ItemRevisionState.SUPERSEDED.value
                base.superseded_at = datetime.now(UTC)
                base.superseded_by_revision_id = revision.item_revision_id
                base.lock_version += 1
            item.current_revision_id = revision.item_revision_id
            item.lock_version += 1
            append_item_event(
                session,
                item,
                item_revision_id=revision.item_revision_id,
                event_type=("ITEM_CREATED" if prior_revision is None else "ITEM_REVISED"),
                prior_state=None if prior_revision is None else ItemRevisionState.APPROVED.value,
                new_state=ItemRevisionState.APPROVED.value,
                actor_id=request.created_by,
                source="REGISTRATION_SERVICE",
                idempotency_key=request.registration_key,
                payload={"revision_number": revision_number},
            )
            session.flush()
            session.expunge(revision)
            return revision

    def _stage_registration_manifest(
        self,
        registration_key: str,
        manifest: dict[str, Any],
    ) -> Path:
        return stage_registry_manifest(self.settings, registration_key, manifest)

    def list_items(
        self,
        *,
        limit: int = 50,
        cursor: str | None = None,
        unused_only: bool = False,
        item_state: str | None = None,
        revision_state: str | None = None,
        item_type_key: str | None = None,
    ) -> dict[str, Any]:
        if not 1 <= limit <= 200:
            raise RegistryError(RegistryErrorCode.CATALOG_QUERY_INVALID, "invalid page size")
        with self.sessions() as session:
            query = select(ItemRecord, ItemRevisionRecord).join(
                ItemRevisionRecord,
                ItemRevisionRecord.item_revision_id == ItemRecord.current_revision_id,
            )
            if item_state is not None:
                query = query.where(ItemRecord.lifecycle_state == item_state)
            if revision_state is not None:
                query = query.where(ItemRevisionRecord.revision_state == revision_state)
            if item_type_key is not None:
                query = query.where(ItemRevisionRecord.item_type_key == item_type_key)
            if unused_only:
                query = query.where(
                    ~select(UsageRecord.usage_record_id)
                    .where(UsageRecord.item_id == ItemRecord.item_id)
                    .exists()
                )
            if cursor:
                created_at, item_id = self._decode_cursor(cursor)
                query = query.where(
                    or_(
                        ItemRecord.created_at < created_at,
                        and_(ItemRecord.created_at == created_at, ItemRecord.item_id < item_id),
                    )
                )
            rows = session.execute(
                query.order_by(ItemRecord.created_at.desc(), ItemRecord.item_id.desc()).limit(
                    limit + 1
                )
            ).all()
            page = rows[:limit]
            next_cursor = None
            if len(rows) > limit and page:
                next_cursor = self._encode_cursor(page[-1][0])
            return {
                "items": [self.item_dict(item, revision) for item, revision in page],
                "next_cursor": next_cursor,
            }

    def inspect_item(self, item_id: str) -> dict[str, Any]:
        with self.sessions() as session:
            item = session.get(ItemRecord, item_id)
            if item is None:
                raise RegistryError(RegistryErrorCode.ITEM_NOT_FOUND, "item not found")
            current = (
                session.get(ItemRevisionRecord, item.current_revision_id)
                if item.current_revision_id
                else None
            )
            revisions = list(
                session.scalars(
                    select(ItemRevisionRecord)
                    .where(ItemRevisionRecord.item_id == item_id)
                    .order_by(ItemRevisionRecord.revision_number)
                )
            )
            return self.item_dict(item, current) | {
                "revisions": [self.revision_dict(revision) for revision in revisions]
            }

    def inspect_revision(self, revision_id: str) -> dict[str, Any]:
        with self.sessions() as session:
            revision = session.get(ItemRevisionRecord, revision_id)
            if revision is None:
                raise RegistryError(
                    RegistryErrorCode.ITEM_REVISION_NOT_FOUND, "item revision not found"
                )
            components = list(
                session.scalars(
                    select(ItemComponentRecord)
                    .where(ItemComponentRecord.item_revision_id == revision_id)
                    .order_by(ItemComponentRecord.component_type, ItemComponentRecord.ordinal)
                )
            )
            return self.revision_dict(revision) | {
                "components": [self.component_dict(item) for item in components]
            }

    def load_item_content(self, revision_id: str) -> AssessmentItemContentContract:
        """Resolve and validate the exact canonical content pinned by one revision."""

        with self.sessions() as session:
            return self._load_item_content(session, revision_id)

    def load_item_media(self, revision_id: str, block_id: str) -> ResolvedItemMedia:
        """Open exactly one image block after revalidating its immutable pointer and bytes."""

        with self.sessions() as session:
            revision = session.get(ItemRevisionRecord, revision_id)
            if revision is None:
                raise RegistryError(
                    RegistryErrorCode.ITEM_REVISION_NOT_FOUND,
                    "item revision not found",
                )
            if revision.revision_state != ItemRevisionState.APPROVED.value:
                raise RegistryError(
                    RegistryErrorCode.ITEM_REVISION_NOT_APPROVED,
                    "item revision is not approved",
                )
            content = self._load_item_content(session, revision_id)
            matches = [
                block
                for block in (content.body if isinstance(content, AssessmentItemContent) else ())
                if isinstance(block, ImageBlock) and block.block_id == block_id
            ]
            if len(matches) != 1:
                raise RegistryError(
                    RegistryErrorCode.ITEM_COMPONENT_INVALID,
                    "item media block does not resolve",
                )
            pointer = matches[0].artifact
            path = self._resolve_media_file(session, pointer)
            return self._open_validated_media(path, pointer)

    @staticmethod
    def _open_validated_media(
        path: Path,
        pointer: MediaArtifactPointer,
    ) -> ResolvedItemMedia:
        descriptor = -1
        stream: BinaryIO | None = None
        try:
            descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
            stream = os.fdopen(descriptor, "rb")
            metadata = os.fstat(stream.fileno())
            if (
                not stat.S_ISREG(metadata.st_mode)
                or metadata.st_size < 1
                or metadata.st_size > CATALOG_ITEM_MEDIA_MAX_BYTES
            ):
                raise ValueError("item media size or type is outside the delivery contract")
            digest = hashlib.sha256()
            while chunk := stream.read(1024 * 1024):
                digest.update(chunk)
            if "sha256:" + digest.hexdigest() != pointer.sha256:
                raise ValueError("item media changed after pointer validation")
            stream.seek(0)
        except (OSError, ValueError) as exc:
            if stream is not None:
                stream.close()
            elif descriptor >= 0:
                os.close(descriptor)
            raise RegistryError(
                RegistryErrorCode.ITEM_COMPONENT_INVALID,
                "item media is unavailable or stale",
            ) from exc
        assert stream is not None
        return ResolvedItemMedia(
            stream=stream,
            media_type=pointer.media_type,
            content_length=metadata.st_size,
            sha256=pointer.sha256,
        )

    @staticmethod
    def _load_item_content(session: Session, revision_id: str) -> AssessmentItemContentContract:
        revision = session.get(ItemRevisionRecord, revision_id)
        if revision is None:
            raise RegistryError(
                RegistryErrorCode.ITEM_REVISION_NOT_FOUND,
                "item revision not found",
            )
        component = session.scalar(
            select(ItemComponentRecord).where(
                ItemComponentRecord.item_revision_id == revision_id,
                ItemComponentRecord.component_type == "ITEM_CONTENT",
                ItemComponentRecord.ordinal == 0,
            )
        )
        if component is None:
            raise RegistryError(
                RegistryErrorCode.ITEM_COMPONENT_INVALID,
                "item revision has no canonical content component",
            )
        artifact_revision = session.get(
            ArtifactRevisionRecord,
            component.artifact_revision_id,
        )
        if (
            artifact_revision is None
            or artifact_revision.logical_artifact_id != component.artifact_id
            or artifact_revision.content_hash != component.sha256
            or not artifact_revision.approved
        ):
            raise RegistryError(
                RegistryErrorCode.ITEM_COMPONENT_INVALID,
                "item content component pointer does not resolve",
            )
        pointer = ComponentPointer(
            component_type="ITEM_CONTENT",
            ordinal=component.ordinal,
            schema_ref=component.schema_ref,
            media_type=component.media_type,
            artifact_id=component.artifact_id,
            artifact_revision_id=component.artifact_revision_id,
            sha256=component.sha256,
            logical_name=component.logical_name,
            required=component.required,
            metadata=component.metadata_json,
        )
        return RegistryService._validate_item_content_component(session, pointer, artifact_revision)

    def relationships(self, item_id: str) -> list[dict[str, Any]]:
        with self.sessions() as session:
            if session.get(ItemRecord, item_id) is None:
                raise RegistryError(RegistryErrorCode.ITEM_NOT_FOUND, "item not found")
            rows = session.scalars(
                select(ItemRelationshipRecord)
                .where(
                    or_(
                        ItemRelationshipRecord.source_item_id == item_id,
                        ItemRelationshipRecord.target_item_id == item_id,
                    )
                )
                .order_by(ItemRelationshipRecord.created_at)
            )
            return [
                {
                    "item_relationship_id": row.item_relationship_id,
                    "source_item_id": row.source_item_id,
                    "target_item_id": row.target_item_id,
                    "relationship_type": row.relationship_type,
                    "created_at": row.created_at,
                }
                for row in rows
            ]

    def retire(self, item_id: str, *, actor_id: str, reason: str) -> ItemRecord:
        with transaction(self.sessions) as session:
            item = session.execute(
                select(ItemRecord).where(ItemRecord.item_id == item_id).with_for_update()
            ).scalar_one_or_none()
            if item is None:
                raise RegistryError(RegistryErrorCode.ITEM_NOT_FOUND, "item not found")
            if item.lifecycle_state == ItemState.RETIRED.value:
                session.expunge(item)
                return item
            prior = item.lifecycle_state
            item.lifecycle_state = ItemState.RETIRED.value
            item.retired_at = datetime.now(UTC)
            item.retirement_reason = reason
            item.lock_version += 1
            append_item_event(
                session,
                item,
                item_revision_id=item.current_revision_id,
                event_type="ITEM_RETIRED",
                prior_state=prior,
                new_state=ItemState.RETIRED.value,
                actor_id=actor_id,
                source="EOMCTL",
            )
            session.flush()
            session.expunge(item)
            return item

    def _validate_registration_references(
        self, session: Session, request: RegistrationRequest
    ) -> tuple[ContentPackReleaseRecord, ContentPackRecord, WorkflowInstanceRecord]:
        pack = session.get(ContentPackReleaseRecord, request.content_pack_release_id)
        if pack is None or pack.state not in {"RELEASED", "DEPRECATED"}:
            raise RegistryError(
                RegistryErrorCode.ITEM_REGISTRATION_FAILED,
                "content pack release is not eligible",
            )
        pack_record = session.get(ContentPackRecord, pack.content_pack_id)
        workflow = session.get(WorkflowInstanceRecord, request.workflow_id)
        step = session.get(WorkflowStepRunRecord, request.source_workflow_step_run_id)
        if (
            pack_record is None
            or workflow is None
            or step is None
            or step.workflow_id != workflow.workflow_id
            or workflow.definition_key != request.workflow_definition_key
            or workflow.definition_version != request.workflow_definition_version
        ):
            raise RegistryError(
                RegistryErrorCode.ITEM_REGISTRATION_FAILED,
                "workflow or pack pointer does not resolve",
            )
        compatible = any(
            item.get("key") == workflow.definition_key
            and workflow.definition_version in item.get("versions", [])
            for item in pack.compatibility_json.get("workflow_definitions", [])
            if isinstance(item, dict)
        )
        if not compatible:
            raise RegistryError(
                RegistryErrorCode.ITEM_REGISTRATION_FAILED,
                "content pack is incompatible with the pinned workflow definition",
            )
        batches = list(
            session.scalars(
                select(ContentIntakeBatchRecord).where(
                    ContentIntakeBatchRecord.intake_batch_id.in_(request.source_intake_batch_ids)
                )
            )
        )
        if len(batches) != len(set(request.source_intake_batch_ids)) or any(
            batch.state not in {"ACCEPTED", "IMPORTED"} for batch in batches
        ):
            raise RegistryError(
                RegistryErrorCode.ITEM_REGISTRATION_FAILED,
                "source Intake pointer does not resolve",
            )
        return pack, pack_record, workflow

    def _validate_metadata(
        self,
        session: Session,
        pack: ContentPackReleaseRecord,
        metadata: dict[str, Any],
    ) -> None:
        schema_bytes = self.pack_resources.read(
            session, pack, "metadata-schemas/item-metadata.schema.json"
        )
        schema = cast(dict[str, Any], json.loads(schema_bytes))
        Draft202012Validator(schema).validate(metadata)

    @staticmethod
    def _validate_components(session: Session, request: RegistrationRequest) -> None:
        positions: set[tuple[str, int]] = set()
        for pointer in request.components:
            position = (pointer.component_type, pointer.ordinal)
            if position in positions:
                raise RegistryError(
                    RegistryErrorCode.ITEM_COMPONENT_DUPLICATE,
                    "duplicate item component position",
                )
            positions.add(position)
            revision = session.get(ArtifactRevisionRecord, pointer.artifact_revision_id)
            if (
                revision is None
                or revision.logical_artifact_id != pointer.artifact_id
                or revision.content_hash != pointer.sha256
                or not revision.approved
            ):
                raise RegistryError(
                    RegistryErrorCode.ITEM_COMPONENT_INVALID,
                    "component artifact pointer does not resolve",
                )
            if pointer.component_type == "ITEM_CONTENT":
                RegistryService._validate_item_content_component(session, pointer, revision)

    @staticmethod
    def _validate_item_content_component(
        session: Session,
        pointer: ComponentPointer,
        revision: ArtifactRevisionRecord,
    ) -> AssessmentItemContentContract:
        schema_name: str
        model: type[AssessmentItemContent] | type[AssessmentItemContentV2]
        if pointer.schema_ref in {
            "eom.assessment.item-content/1.0",
            "eom://schemas/item-registry/assessment-item-content-v1",
        }:
            schema_name, model = "assessment-item-content", AssessmentItemContent
        elif pointer.schema_ref in {
            "eom.assessment.item-content/2.0",
            "eom://schemas/item-registry/assessment-item-content-v2",
        }:
            schema_name, model = "assessment-item-content-v2", AssessmentItemContentV2
        else:
            schema_name, model = "", AssessmentItemContent
        if pointer.ordinal != 0 or not schema_name or pointer.media_type != "application/json":
            raise RegistryError(
                RegistryErrorCode.ITEM_COMPONENT_INVALID,
                "canonical item content component identity is invalid",
            )
        primary = RegistryService._artifact_primary_file(revision)
        try:
            raw: object = json.loads(primary.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                raise ValueError("item content is not an object")
            validate_contract(schema_name, raw)
            content = model.model_validate(raw)
        except (OSError, UnicodeError, ValueError) as exc:
            raise RegistryError(
                RegistryErrorCode.ITEM_COMPONENT_INVALID,
                "canonical item content artifact is invalid",
            ) from exc

        for block in getattr(content, "body", ()):
            artifact_pointer = getattr(block, "artifact", None)
            if artifact_pointer is None:
                continue
            RegistryService._resolve_media_file(session, artifact_pointer)
        return content

    @staticmethod
    def _resolve_media_file(session: Session, pointer: MediaArtifactPointer) -> Path:
        artifact = session.get(ArtifactRecord, pointer.artifact_id)
        media_revision = session.get(ArtifactRevisionRecord, pointer.artifact_revision_id)
        if (
            artifact is None
            or media_revision is None
            or not artifact.approved
            or not media_revision.approved
            or media_revision.logical_artifact_id != pointer.artifact_id
        ):
            raise RegistryError(
                RegistryErrorCode.ITEM_COMPONENT_INVALID,
                "item content media pointer does not resolve",
            )
        media_primary = RegistryService._artifact_member_file(
            media_revision,
            pointer.artifact_member,
            pointer.sha256,
        )
        RegistryService._validate_media_file(media_primary, pointer.media_type)
        return media_primary

    @staticmethod
    def _artifact_primary_file(revision: ArtifactRevisionRecord) -> Path:
        primary_name = revision.manifest.get("primary_file")
        if not isinstance(primary_name, str):
            raise RegistryError(
                RegistryErrorCode.ITEM_COMPONENT_INVALID,
                "component artifact has no typed primary file",
            )
        return RegistryService._artifact_member_file(
            revision,
            primary_name,
            revision.content_hash,
        )

    @staticmethod
    def _artifact_member_file(
        revision: ArtifactRevisionRecord,
        member_name: str,
        expected_sha256: str,
    ) -> Path:
        files = revision.manifest.get("files")
        entries = (
            [
                entry
                for entry in files
                if isinstance(entry, dict) and entry.get("file_name") == member_name
            ]
            if isinstance(files, list)
            else []
        )
        if len(entries) != 1 or entries[0].get("sha256") != expected_sha256:
            raise RegistryError(
                RegistryErrorCode.ITEM_COMPONENT_INVALID,
                "component artifact member is missing or stale",
            )
        relative = Path(member_name)
        root = Path(revision.nas_path)
        candidate = root / relative
        if relative.is_absolute() or ".." in relative.parts or "\\" in member_name:
            raise RegistryError(
                RegistryErrorCode.ITEM_COMPONENT_INVALID,
                "component artifact member is unsafe or stale",
            )
        try:
            root_metadata = root.lstat()
            if not stat.S_ISDIR(root_metadata.st_mode) or root.is_symlink():
                raise ValueError("component artifact root is unsafe")
            resolved_root = root.resolve(strict=True)
            current = root
            for component in relative.parts:
                current = current / component
                metadata = current.lstat()
                if stat.S_ISLNK(metadata.st_mode):
                    raise ValueError("component path contains a symlink")
            metadata = candidate.lstat()
            if (
                not stat.S_ISREG(metadata.st_mode)
                or not candidate.resolve(strict=True).is_relative_to(resolved_root)
                or sha256_file(candidate) != expected_sha256
                or entries[0].get("bytes") != metadata.st_size
            ):
                raise ValueError("component file is stale or unsafe")
        except (OSError, ValueError) as exc:
            raise RegistryError(
                RegistryErrorCode.ITEM_COMPONENT_INVALID,
                "component artifact member is unsafe or stale",
            ) from exc
        return candidate

    @staticmethod
    def _validate_media_file(path: Path, media_type: str) -> None:
        try:
            with path.open("rb") as stream:
                prefix = stream.read(12)
                stream.seek(-2, 2)
                suffix = stream.read(2)
        except OSError as exc:
            raise RegistryError(
                RegistryErrorCode.ITEM_COMPONENT_INVALID,
                "item content media artifact is unreadable",
            ) from exc
        valid = (
            media_type == "image/png"
            and path.suffix.casefold() == ".png"
            and prefix.startswith(b"\x89PNG\r\n\x1a\n")
        ) or (
            media_type == "image/jpeg"
            and path.suffix.casefold() in {".jpg", ".jpeg"}
            and prefix.startswith(b"\xff\xd8\xff")
            and suffix == b"\xff\xd9"
        )
        if not valid:
            raise RegistryError(
                RegistryErrorCode.ITEM_COMPONENT_INVALID,
                "item content media type does not match pinned artifact bytes",
            )

    @staticmethod
    def _manifest(
        request: RegistrationRequest,
        *,
        item_id: str,
        revision_id: str,
        revision_number: int,
        pack: ContentPackReleaseRecord,
        pack_key: str,
        metadata_hash: str,
        created_at: datetime,
    ) -> dict[str, Any]:
        return {
            "schema_version": "1.0",
            "item_id": item_id,
            "item_revision_id": revision_id,
            "revision_number": revision_number,
            "content_pack": {
                "release_id": pack.content_pack_release_id,
                "pack_key": pack_key,
                "version": pack.version,
                "sha256": pack.bundle_sha256,
            },
            "source_intake": {"batch_ids": sorted(request.source_intake_batch_ids)},
            "workflow": {
                "workflow_id": request.workflow_id,
                "definition_key": request.workflow_definition_key,
                "definition_version": request.workflow_definition_version,
            },
            "components": [
                {
                    "component_type": component.component_type,
                    "ordinal": component.ordinal,
                    "schema_ref": component.schema_ref,
                    "media_type": component.media_type,
                    "artifact_id": component.artifact_id,
                    "artifact_revision_id": component.artifact_revision_id,
                    "sha256": component.sha256,
                    "logical_name": component.logical_name,
                    "required": component.required,
                }
                for component in sorted(
                    request.components, key=lambda item: (item.component_type, item.ordinal)
                )
            ],
            "metadata": {"schema_ref": request.metadata_schema_ref, "sha256": metadata_hash},
            "provenance": [
                {"type": "MANUAL_EXTERNAL_SOURCE", "intake_batch_id": batch_id}
                for batch_id in sorted(request.source_intake_batch_ids)
            ],
            "created_at": created_at.astimezone(UTC).isoformat().replace("+00:00", "Z"),
        }

    @staticmethod
    def _add_revision_children(
        session: Session,
        revision: ItemRevisionRecord,
        request: RegistrationRequest,
        metadata_hash: str,
    ) -> None:
        for pointer in request.components:
            session.add(
                ItemComponentRecord(
                    item_component_id=new_item_component_id(),
                    item_revision_id=revision.item_revision_id,
                    component_type=pointer.component_type,
                    ordinal=pointer.ordinal,
                    schema_ref=pointer.schema_ref,
                    media_type=pointer.media_type,
                    artifact_id=pointer.artifact_id,
                    artifact_revision_id=pointer.artifact_revision_id,
                    sha256=pointer.sha256,
                    logical_name=pointer.logical_name,
                    required=pointer.required,
                    metadata_json=pointer.metadata,
                )
            )
        session.add(
            ItemMetadataSnapshotRecord(
                item_metadata_snapshot_id=new_item_metadata_id(),
                item_revision_id=revision.item_revision_id,
                schema_ref=request.metadata_schema_ref,
                schema_version="1.0",
                taxonomy_refs=(
                    [request.primary_taxonomy_ref] if request.primary_taxonomy_ref else []
                ),
                tag_keys=list(request.tag_keys),
                difficulty_band=request.difficulty_band or "PLACEHOLDER_DIFFICULTY",
                item_type_key=request.item_type_key,
                estimated_time_seconds=request.estimated_time_seconds,
                metadata_json=request.metadata,
                metadata_sha256=metadata_hash,
            )
        )
        for batch_id in request.source_intake_batch_ids:
            session.add(
                ItemProvenanceRecord(
                    item_provenance_id=new_item_provenance_id(),
                    item_revision_id=revision.item_revision_id,
                    provenance_type="MANUAL_EXTERNAL_SOURCE",
                    source_key=batch_id,
                    source_reference=batch_id,
                    source_intake_batch_id=batch_id,
                    source_file_id=None,
                    source_artifact_id=None,
                    source_artifact_revision_id=None,
                    source_sha256=None,
                    notes=None,
                )
            )

    @staticmethod
    def item_dict(item: ItemRecord, revision: ItemRevisionRecord | None) -> dict[str, Any]:
        return {
            "item_id": item.item_id,
            "human_reference_code": item.human_reference_code,
            "lifecycle_state": item.lifecycle_state,
            "current_revision_id": item.current_revision_id,
            "created_at": item.created_at,
            "created_by": item.created_by,
            "current_revision": RegistryService.revision_dict(revision) if revision else None,
        }

    @staticmethod
    def revision_dict(revision: ItemRevisionRecord) -> dict[str, Any]:
        return {
            "item_revision_id": revision.item_revision_id,
            "item_id": revision.item_id,
            "revision_number": revision.revision_number,
            "revision_state": revision.revision_state,
            "content_pack_release_id": revision.content_pack_release_id,
            "workflow_id": revision.workflow_id,
            "manifest_artifact_id": revision.manifest_artifact_id,
            "manifest_artifact_revision_id": revision.manifest_artifact_revision_id,
            "manifest_sha256": revision.manifest_sha256,
            "item_type_key": revision.item_type_key,
            "primary_taxonomy_ref": revision.primary_taxonomy_ref,
            "difficulty_band": revision.difficulty_band,
            "metadata_sha256": revision.metadata_sha256,
            "created_at": revision.created_at,
            "approved_at": revision.approved_at,
            "superseded_by_revision_id": revision.superseded_by_revision_id,
        }

    @staticmethod
    def component_dict(component: ItemComponentRecord) -> dict[str, Any]:
        return {
            "item_component_id": component.item_component_id,
            "component_type": component.component_type,
            "ordinal": component.ordinal,
            "schema_ref": component.schema_ref,
            "media_type": component.media_type,
            "artifact_id": component.artifact_id,
            "artifact_revision_id": component.artifact_revision_id,
            "sha256": component.sha256,
            "logical_name": component.logical_name,
            "required": component.required,
        }

    @staticmethod
    def _encode_cursor(item: ItemRecord) -> str:
        value = canonical_json_bytes(
            {"created_at": item.created_at.isoformat(), "item_id": item.item_id}
        )
        return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")

    @staticmethod
    def _decode_cursor(value: str) -> tuple[datetime, str]:
        try:
            padded = value + "=" * (-len(value) % 4)
            raw = json.loads(base64.urlsafe_b64decode(padded))
            created_at = datetime.fromisoformat(raw["created_at"])
            item_id = str(raw["item_id"])
            if created_at.tzinfo is None or not item_id.startswith("item_"):
                raise ValueError
            return created_at, item_id
        except (ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
            raise RegistryError(
                RegistryErrorCode.CATALOG_CURSOR_INVALID, "invalid catalog cursor"
            ) from exc
