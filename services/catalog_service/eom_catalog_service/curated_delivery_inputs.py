"""Catalog-owned, metadata-only pinning for a saved assembly's editable delivery."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, NoReturn

from eom_catalog_contracts.creative_visual_presentation import (
    VISUAL_PRESENTATION_ARTIFACT_TYPE,
    VISUAL_PRESENTATION_CONTENT_MEMBER,
    VISUAL_PRESENTATION_CONTENT_SCHEMA_REF,
    VISUAL_PRESENTATION_MEMBER,
    VISUAL_PRESENTATION_SCHEMA_REFS,
    visual_presentation_key,
)
from eom_catalog_contracts.curated_document_slots import (
    CuratedDeliveryManifest,
    CuratedDocumentAssemblyManifestV2,
    RegisteredSlotTarget,
    ResolvedExternalSlotTarget,
    iter_curated_delivery_positions,
)
from eom_hwpx_contracts.curated_build import (
    CuratedArtifactMember,
    CuratedHwpxBuildInput,
    CuratedNativeDocumentInput,
    CuratedRegisteredItemInput,
)
from eom_hwpx_contracts.curated_document import CuratedHwpConverterSnapshot
from eom_hwpx_contracts.curated_occurrences import (
    CuratedBuildInput,
    CuratedHwpxBuildInputV2,
    CuratedNativeOccurrenceInput,
    CuratedRegisteredOccurrenceInput,
    parse_curated_build_input,
)
from eom_hwpx_contracts.models import ContentTeamHandoffSnapshot
from eom_identifiers import content_sha256
from eom_operator_identity import ActorContext
from eom_orchestrator.database import build_session_factory
from eom_orchestrator.models import ArtifactRecord, ArtifactRevisionRecord, JobRecord
from sqlalchemy import Engine, select

from eom_catalog_service.item_content_contract import ITEM_CONTENT_SCHEMAS
from eom_catalog_service.models import ItemComponentRecord, ItemRecord, ItemRevisionRecord

if TYPE_CHECKING:
    from eom_catalog_service.curated_document_assembly_service import CuratedDocumentAssemblyService


class CuratedDeliveryInputError(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _invalid() -> NoReturn:
    raise CuratedDeliveryInputError("CURATED_DELIVERY_INPUT_POINTER_INVALID")


def _component(value: ItemComponentRecord) -> CuratedArtifactMember:
    return CuratedArtifactMember(
        artifact_id=value.artifact_id,
        artifact_revision_id=value.artifact_revision_id,
        member_path=value.logical_name,
        schema_ref=value.schema_ref,
        media_type=value.media_type,
        sha256=value.sha256,
    )


class CuratedDeliveryInputs:
    """Indexed batch metadata reads, no NAS paths, bodies, conversion or image decoding.

    The exact accepted visual publication is pinned once. Actual source-bound
    derivation and member bytes are checked by Manager materialization. Missing
    publication is canonical content; an incomplete/revoked publication is an
    explicit error, never permission to fall back to an old clipped picture.
    """

    def __init__(
        self,
        engine: Engine,
        *,
        assemblies: CuratedDocumentAssemblyService,
        handoff: ContentTeamHandoffSnapshot,
        converter: CuratedHwpConverterSnapshot,
    ) -> None:
        self.sessions = build_session_factory(engine)
        self.assemblies = assemblies
        self.handoff = handoff
        self.converter = converter

    def pin_inputs(
        self, manifest: CuratedDeliveryManifest, *, actor: ActorContext
    ) -> CuratedBuildInput:
        authorized = self.assemblies.authorize_delivery_build(
            manifest.assembly_id,
            assembly_revision_id=manifest.assembly_revision_id,
            manifest_sha256=manifest.manifest_sha256,
            actor=actor,
        )
        if authorized != manifest:
            _invalid()
        positions = tuple(iter_curated_delivery_positions(manifest))
        selected = tuple(row for _, _, row in positions if isinstance(row, RegisteredSlotTarget))
        ids = tuple(dict.fromkeys(row.item_revision_id for row in selected))
        with self.sessions() as session:
            rows = (
                session.execute(
                    select(ItemRevisionRecord, ItemRecord)
                    .join(ItemRecord, ItemRecord.item_id == ItemRevisionRecord.item_id)
                    .where(ItemRevisionRecord.item_revision_id.in_(ids))
                ).all()
                if ids
                else ()
            )
            revisions = {revision.item_revision_id: revision for revision, _item in rows}
            if len(revisions) != len(ids) or any(
                item.lifecycle_state != "ACTIVE" for _revision, item in rows
            ):
                _invalid()
            components = (
                tuple(
                    session.scalars(
                        select(ItemComponentRecord).where(
                            ItemComponentRecord.item_revision_id.in_(ids),
                            ItemComponentRecord.component_type == "ITEM_CONTENT",
                            ItemComponentRecord.ordinal == 0,
                        )
                    )
                )
                if ids
                else ()
            )
            by_revision = {row.item_revision_id: row for row in components}
            if len(components) != len(ids) or len(by_revision) != len(ids):
                _invalid()
            for selection in selected:
                revision = revisions.get(selection.item_revision_id)
                if (
                    revision is None
                    or revision.item_id != selection.item_id
                    or revision.manifest_sha256 != selection.item_manifest_sha256
                    or revision.revision_state not in {"APPROVED", "SUPERSEDED"}
                ):
                    _invalid()
            keys = {
                visual_presentation_key(row.item_revision_id): row.item_revision_id
                for row in selected
                if revisions[row.item_revision_id].metadata_json.get("source_kind") == "CREATIVE"
                and by_revision[row.item_revision_id].schema_ref
                in {
                    "eom.assessment.item-content/1.0",
                    "eom://schemas/item-registry/assessment-item-content-v1",
                }
            }
            visual_jobs = (
                tuple(
                    session.scalars(
                        select(JobRecord).where(JobRecord.idempotency_key.in_(tuple(keys)))
                    )
                )
                if keys
                else ()
            )
            publications = {keys[job.idempotency_key]: job for job in visual_jobs}
            if len(publications) != len(visual_jobs):
                _invalid()
            identities = {(row.artifact_id, row.artifact_revision_id) for row in components}
            for _, _, row in positions:
                if isinstance(row, ResolvedExternalSlotTarget):
                    identities.add(
                        (
                            row.document_artifact.artifact_id,
                            row.document_artifact.artifact_revision_id,
                        )
                    )
            identities.update((job.logical_artifact_id, job.revision_id) for job in visual_jobs)
            if selected:
                identities.add((self.handoff.artifact_id, self.handoff.artifact_revision_id))
            artifacts = {
                row.logical_artifact_id: row
                for row in session.scalars(
                    select(ArtifactRecord).where(
                        ArtifactRecord.logical_artifact_id.in_(
                            tuple(sorted({key[0] for key in identities}))
                        )
                    )
                )
            }
            artifact_revisions = {
                row.revision_id: row
                for row in session.scalars(
                    select(ArtifactRevisionRecord).where(
                        ArtifactRevisionRecord.revision_id.in_(
                            tuple(sorted({key[1] for key in identities}))
                        )
                    )
                )
            }
            producer_ids = {row.job_id for row in artifact_revisions.values()}
            producers = {
                row.job_id: row
                for row in session.scalars(
                    select(JobRecord).where(JobRecord.job_id.in_(tuple(sorted(producer_ids))))
                )
            }
            members: dict[str, dict[str, tuple[dict[str, Any], ...]]] = {}
            for artifact_id, revision_id in identities:
                artifact, revision = artifacts.get(artifact_id), artifact_revisions.get(revision_id)
                job = producers.get(revision.job_id) if revision is not None else None
                if (
                    artifact is None
                    or revision is None
                    or job is None
                    or not artifact.approved
                    or not revision.approved
                    or revision.logical_artifact_id != artifact_id
                    or job.status != "SUCCEEDED"
                    or job.logical_artifact_id != artifact_id
                    or job.revision_id != revision_id
                    or revision.manifest_hash != content_sha256(revision.manifest)
                    or revision.manifest.get("logical_artifact_id") != artifact_id
                    or revision.manifest.get("revision_id") != revision_id
                    or revision.manifest.get("job_id") != job.job_id
                ):
                    _invalid()
                files = revision.manifest.get("files")
                if not isinstance(files, list):
                    _invalid()
                groups: dict[str, list[dict[str, Any]]] = {}
                for entry in files:
                    if not isinstance(entry, dict) or not isinstance(
                        name := entry.get("file_name"), str
                    ):
                        _invalid()
                    groups.setdefault(name, []).append(entry)
                members[revision_id] = {name: tuple(values) for name, values in groups.items()}
            placements: list[CuratedNativeDocumentInput | CuratedRegisteredItemInput] = []
            for position, placement_id, row in positions:
                occurrence = {} if placement_id is None else {"placement_id": placement_id}
                native_type = (
                    CuratedNativeDocumentInput
                    if placement_id is None
                    else CuratedNativeOccurrenceInput
                )
                item_type = (
                    CuratedRegisteredItemInput
                    if placement_id is None
                    else CuratedRegisteredOccurrenceInput
                )
                if isinstance(row, ResolvedExternalSlotTarget):
                    if row.document_size_bytes > 50 * 1024 * 1024:
                        raise CuratedDeliveryInputError("CURATED_DELIVERY_DOCUMENT_TOO_LARGE")
                    pointer = CuratedArtifactMember.model_validate(
                        row.document_artifact.model_dump()
                    )
                    self._require_member(
                        pointer,
                        members,
                        max_bytes=50 * 1024 * 1024,
                        expected_size=row.document_size_bytes,
                    )
                    placements.append(
                        native_type.model_validate(
                            dict(
                                **occurrence,
                                position=position,
                                source_format=row.source_format,
                                document=pointer,
                                size_bytes=row.document_size_bytes,
                            )
                        )
                    )
                    continue
                component = by_revision[row.item_revision_id]
                source = _component(component)
                if (
                    source.schema_ref not in ITEM_CONTENT_SCHEMAS
                    or source.media_type != "application/json"
                    or component.required is not True
                ):
                    _invalid()
                self._require_member(source, members, max_bytes=2 * 1024 * 1024)
                display, recovery, markdown = source, None, None
                schema, _model = ITEM_CONTENT_SCHEMAS[source.schema_ref]
                if schema != "assessment-item-content":
                    metadata = component.metadata_json
                    expected_schema = (
                        "eom://schemas/hwpx/content-team-editorial-markdown/2.0"
                        if schema == "assessment-item-content-v3"
                        else "eom://schemas/hwpx/content-team-editorial-markdown/1.0"
                    )
                    if (
                        metadata.get("editorial_markdown_member") != "content-team-item.md"
                        or metadata.get("editorial_markdown_schema_ref", expected_schema)
                        != expected_schema
                    ):
                        _invalid()
                    markdown = CuratedArtifactMember(
                        artifact_id=source.artifact_id,
                        artifact_revision_id=source.artifact_revision_id,
                        member_path="content-team-item.md",
                        schema_ref=expected_schema,
                        media_type="text/markdown",
                        sha256=metadata["editorial_markdown_sha256"],
                    )
                    self._require_member(markdown, members, max_bytes=1024 * 1024)
                if (job := publications.get(row.item_revision_id)) is not None:
                    published, artifact = (
                        artifact_revisions[job.revision_id],
                        artifacts[job.logical_artifact_id],
                    )
                    if (
                        job.protocol_version != "control-file-set/1.0"
                        or job.task_type != VISUAL_PRESENTATION_ARTIFACT_TYPE
                        or job.worker_slot_id is not None
                        or artifact.artifact_type != VISUAL_PRESENTATION_ARTIFACT_TYPE
                        or published.job_id != job.job_id
                        or published.manifest.get("primary_file")
                        != VISUAL_PRESENTATION_CONTENT_MEMBER
                    ):
                        _invalid()
                    display = CuratedArtifactMember(
                        artifact_id=job.logical_artifact_id,
                        artifact_revision_id=job.revision_id,
                        member_path=VISUAL_PRESENTATION_CONTENT_MEMBER,
                        schema_ref=VISUAL_PRESENTATION_CONTENT_SCHEMA_REF,
                        media_type="application/json",
                        sha256=published.content_hash,
                    )
                    self._require_member(
                        display,
                        members,
                        max_bytes=2 * 1024 * 1024,
                        expected_size=published.content_bytes,
                    )
                    proof = members[job.revision_id].get(VISUAL_PRESENTATION_MEMBER, ())
                    if (
                        len(proof) != 1
                        or proof[0].get("schema_ref") not in VISUAL_PRESENTATION_SCHEMA_REFS
                    ):
                        _invalid()
                    recovery = CuratedArtifactMember(
                        artifact_id=job.logical_artifact_id,
                        artifact_revision_id=job.revision_id,
                        member_path=VISUAL_PRESENTATION_MEMBER,
                        schema_ref=proof[0]["schema_ref"],
                        media_type="application/json",
                        sha256=proof[0]["sha256"],
                    )
                    self._require_member(recovery, members, max_bytes=256 * 1024)
                placements.append(
                    item_type.model_validate(
                        dict(
                            **occurrence,
                            position=position,
                            item_id=row.item_id,
                            item_revision_id=row.item_revision_id,
                            item_manifest_sha256=row.item_manifest_sha256,
                            source_content=source,
                            display_content=display,
                            recovery_manifest=recovery,
                            editorial_markdown=markdown,
                        )
                    )
                )
            if selected:
                self._require_member(
                    CuratedArtifactMember(
                        artifact_id=self.handoff.artifact_id,
                        artifact_revision_id=self.handoff.artifact_revision_id,
                        member_path="handoff-source.zip",
                        schema_ref="eom://schemas/hwpx/content-team-handoff-archive/1.0",
                        media_type="application/zip",
                        sha256=self.handoff.archive_sha256,
                    ),
                    members,
                    max_bytes=64 * 1024 * 1024,
                )
            result_type = (
                CuratedHwpxBuildInputV2
                if isinstance(manifest, CuratedDocumentAssemblyManifestV2)
                else CuratedHwpxBuildInput
            )
            result = result_type.model_validate(
                dict(
                    assembly_id=manifest.assembly_id,
                    assembly_revision_id=manifest.assembly_revision_id,
                    assembly_manifest_sha256=manifest.manifest_sha256,
                    handoff=self.handoff if selected else None,
                    converter=self.converter
                    if any(
                        isinstance(row, CuratedNativeDocumentInput) and row.source_format == "HWP"
                        for row in placements
                    )
                    else None,
                    placements=tuple(placements),
                )
            )
            parse_curated_build_input(result.model_dump(mode="json"))
            return result

    @staticmethod
    def _require_member(
        pointer: CuratedArtifactMember,
        members: dict[str, dict[str, tuple[dict[str, Any], ...]]],
        *,
        max_bytes: int,
        expected_size: int | None = None,
    ) -> None:
        entries = members.get(pointer.artifact_revision_id, {}).get(pointer.member_path, ())
        if len(entries) != 1:
            _invalid()
        entry = entries[0]
        size = entry.get("bytes")
        if (
            entry.get("sha256") != pointer.sha256
            or entry.get("schema_ref") != pointer.schema_ref
            or entry.get("media_type") != pointer.media_type
            or type(size) is not int
            or not 0 < size <= max_bytes
            or (expected_size is not None and size != expected_size)
        ):
            _invalid()
