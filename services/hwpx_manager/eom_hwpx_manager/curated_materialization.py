"""Materialize pinned saved-assembly inputs at the existing Manager/Builder boundary."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, NoReturn, Protocol

from eom_catalog_contracts import AssessmentItemContent
from eom_catalog_contracts.creative_bitmap_presentation import read_visual_presentation_manifest
from eom_catalog_contracts.creative_visual_derivation import derive_creative_visual_content
from eom_catalog_service.item_content_contract import read_item_content
from eom_hwpx_contracts import (
    ContentTeamImageSource,
    serialize_content_team_markdown,
    validate_content_team_image_bindings,
)
from eom_hwpx_contracts.curated_build import (
    CuratedArtifactMember,
    CuratedHwpxBuildInput,
    CuratedNativeDocumentInput,
    CuratedRegisteredItemInput,
)
from eom_hwpx_contracts.curated_mixed import (
    CuratedCanonicalSegment,
    CuratedEditorialImage,
    CuratedEditorialSegment,
    CuratedMixedRenderRequest,
    CuratedNativeSegment,
)
from eom_hwpx_contracts.native_item import NativeItemRenderRequest
from eom_hwpx_contracts.validation import parse_json_object, validate_contract
from eom_identifiers import content_sha256, sha256_bytes
from eom_protocol.artifact_members import ArtifactMemberPointer as SourceMember

from eom_hwpx_manager.adapter import read_stable_regular_file
from eom_hwpx_manager.application_adapter import FixedCuratedBuilderAdapter
from eom_hwpx_manager.application_service import HwpxApplicationService, ItemRevisionResolver
from eom_hwpx_manager.content_team_output_acceptance import ContentTeamOutputExpectation
from eom_hwpx_manager.content_team_service import (
    HANDOFF_MEDIA_TYPE,
    HANDOFF_MEMBER,
    HANDOFF_SCHEMA_REF,
    ArtifactMemberPointer,
)
from eom_hwpx_manager.errors import HwpxManagerError, HwpxManagerErrorCode
from eom_hwpx_manager.native_item_projection import project_native_item


class CuratedArtifactMembers(Protocol):
    def resolve_members(self, pointers: tuple[ArtifactMemberPointer, ...]) -> tuple[Path, ...]: ...


@dataclass(frozen=True)
class CuratedMaterialization:
    request: CuratedMixedRenderRequest
    canonical_items: tuple[NativeItemRenderRequest, ...]
    editorial_items: tuple[ContentTeamOutputExpectation, ...]


@dataclass(frozen=True)
class _EditorialStage:
    placement: CuratedRegisteredItemInput
    version: Literal["2.0", "3.0"]
    json_file: str
    markdown_file: str
    images: tuple[tuple[ContentTeamImageSource, str, ArtifactMemberPointer], ...]


def _invalid(message: str) -> NoReturn:
    raise HwpxManagerError(HwpxManagerErrorCode.HWPX_KORDOC_SOURCE_INVALID, message)


def _member(pointer: CuratedArtifactMember, maximum: int) -> ArtifactMemberPointer:
    return ArtifactMemberPointer(
        artifact_id=pointer.artifact_id,
        revision_id=pointer.artifact_revision_id,
        member_name=pointer.member_path,
        expected_sha256=pointer.sha256,
        schema_ref=pointer.schema_ref,
        media_type=pointer.media_type,
        max_bytes=maximum,
    )


def _read(path: Path, pointer: ArtifactMemberPointer) -> bytes:
    raw = read_stable_regular_file(path, max_bytes=pointer.max_bytes)
    if sha256_bytes(raw) != pointer.expected_sha256:
        _invalid("curated source changed between pointer resolution and materialization")
    return raw


class CuratedInputMaterializer:
    """Two batched pointer phases, ordered projection and content-addressed image staging.

    Assembly/actor authorization belongs to the application/Catalog owner. This
    adapter rechecks exact Item components and Artifact bytes; it never grants
    permission, reads latest content or persists full Item bodies in a build row.
    """

    def __init__(
        self,
        *,
        members: CuratedArtifactMembers,
        registry: ItemRevisionResolver,
        adapter: FixedCuratedBuilderAdapter,
    ) -> None:
        self.members = members
        self.registry = registry
        self.adapter = adapter

    def stage(
        self, workspace: Path, *, build_id: str, inputs: CuratedHwpxBuildInput
    ) -> CuratedMaterialization:
        validate_contract("curated-build-input", inputs.model_dump(mode="json"))
        items = tuple(
            row for row in inputs.placements if isinstance(row, CuratedRegisteredItemInput)
        )
        revisions = (
            self.registry.inspect_revisions(tuple(row.item_revision_id for row in items))
            if items
            else ()
        )
        by_id = {row["item_revision_id"]: row for row in revisions}
        if len(by_id) != len(items):
            _invalid("curated Item Revision set is incomplete or repeated")
        pointers: list[ArtifactMemberPointer] = []
        for placement in inputs.placements:
            if isinstance(placement, CuratedNativeDocumentInput):
                if placement.size_bytes > 50 * 1024 * 1024:
                    _invalid("native source exceeds the supported per-document render bound")
                pointers.append(_member(placement.document, 50 * 1024 * 1024))
                continue
            revision = by_id[placement.item_revision_id]
            if (
                revision.get("item_id") != placement.item_id
                or revision.get("manifest_sha256") != placement.item_manifest_sha256
                or revision.get("revision_state") not in {"APPROVED", "SUPERSEDED"}
            ):
                _invalid("curated Item Revision differs from the saved input plan")
            components = [
                row
                for row in revision.get("components", ())
                if row.get("component_type") == "ITEM_CONTENT" and row.get("ordinal") == 0
            ]
            if (
                len(components) != 1
                or self._component_pointer(components[0]) != placement.source_content
            ):
                _invalid("curated source content differs from its exact Item Revision")
            pointers.extend(
                (
                    _member(placement.source_content, 2 * 1024 * 1024),
                    _member(placement.display_content, 2 * 1024 * 1024),
                )
            )
            if placement.recovery_manifest is not None:
                pointers.append(_member(placement.recovery_manifest, 256 * 1024))
            if placement.editorial_markdown is not None:
                pointers.append(_member(placement.editorial_markdown, 1024 * 1024))
        if inputs.handoff is not None:
            pointers.append(
                ArtifactMemberPointer(
                    artifact_id=inputs.handoff.artifact_id,
                    revision_id=inputs.handoff.artifact_revision_id,
                    member_name=HANDOFF_MEMBER,
                    expected_sha256=inputs.handoff.archive_sha256,
                    schema_ref=HANDOFF_SCHEMA_REF,
                    media_type=HANDOFF_MEDIA_TYPE,
                    max_bytes=64 * 1024 * 1024,
                )
            )
        # Ordered dict removes repeated identical pointers, not different provenance
        # which happens to have the same hash. Every distinct pointer is resolved.
        unique = tuple(dict.fromkeys(pointers))
        paths = self.members.resolve_members(unique)
        if len(paths) != len(unique):
            _invalid("curated Artifact member resolution is incomplete")
        resolved = dict(zip(unique, paths, strict=True))
        segments: list[CuratedNativeSegment | CuratedCanonicalSegment | _EditorialStage] = []
        canonical: list[NativeItemRenderRequest] = []
        editorial: list[ContentTeamOutputExpectation] = []
        image_stage: list[tuple[str, ArtifactMemberPointer]] = []
        if inputs.handoff is not None:
            pointer = pointers[-1]
            self.adapter.stage_file(
                workspace,
                inputs.handoff.archive_file,
                resolved[pointer],
                expected_sha256=pointer.expected_sha256,
            )
        for placement in inputs.placements:
            position = placement.position
            if isinstance(placement, CuratedNativeDocumentInput):
                pointer = _member(placement.document, 50 * 1024 * 1024)
                name = f"inputs/{position:03d}.{placement.source_format.lower()}"
                target = self.adapter.stage_file(
                    workspace, name, resolved[pointer], expected_sha256=pointer.expected_sha256
                )
                if target.stat().st_size != placement.size_bytes:
                    _invalid("native source size differs from its saved input")
                segments.append(
                    CuratedNativeSegment(
                        position=position,
                        local_file=name,
                        source_format=placement.source_format,
                        sha256=pointer.expected_sha256,
                        size_bytes=placement.size_bytes,
                    )
                )
                continue
            display_pointer = _member(placement.display_content, 2 * 1024 * 1024)
            content = read_item_content(
                placement.display_content.schema_ref,
                parse_json_object(_read(resolved[display_pointer], display_pointer)),
            )
            if isinstance(content, AssessmentItemContent):
                if placement.recovery_manifest is not None:
                    self._verify_recovery(
                        placement, by_id[placement.item_revision_id], content, resolved
                    )
                projection = project_native_item(
                    content,
                    build_id=build_id,
                    item_revision_id=placement.item_revision_id,
                    source_sha256=placement.source_content.sha256,
                    effective_content_sha256=placement.display_content.sha256,
                    item_number=position,
                )
                canonical.append(projection.document)
                name = f"input/items/{position:03d}/native-item.json"
                target = self.adapter.write_json(
                    workspace, name, projection.document.model_dump(mode="json")
                )
                raw = read_stable_regular_file(target, max_bytes=2 * 1024 * 1024)
                segments.append(
                    CuratedCanonicalSegment(
                        position=position,
                        item_revision_id=placement.item_revision_id,
                        source_sha256=placement.source_content.sha256,
                        effective_content_sha256=placement.display_content.sha256,
                        blueprint_file=name,
                        blueprint_sha256=sha256_bytes(raw),
                        blueprint_size_bytes=len(raw),
                    )
                )
                for native_image in projection.images:
                    image_stage.append(
                        (
                            native_image.image.local_file,
                            ArtifactMemberPointer(
                                artifact_id=native_image.source.artifact_id,
                                revision_id=native_image.source.artifact_revision_id,
                                member_name=native_image.source.artifact_member,
                                expected_sha256=native_image.source.sha256,
                                schema_ref=None,
                                media_type=native_image.source.media_type,
                                max_bytes=20 * 1024 * 1024,
                            ),
                        )
                    )
                continue
            assert placement.editorial_markdown is not None
            markdown_pointer = _member(placement.editorial_markdown, 1024 * 1024)
            markdown = _read(resolved[markdown_pointer], markdown_pointer)
            if markdown != serialize_content_team_markdown(content):
                _invalid("editorial Markdown differs from the pinned canonical content")
            bindings = tuple(
                ContentTeamImageSource.model_validate(row)
                for row in HwpxApplicationService.content_team_image_sources(
                    by_id[placement.item_revision_id]
                )
            )
            validate_content_team_image_bindings(content, bindings)
            editorial.append(
                ContentTeamOutputExpectation(
                    position=position,
                    item_revision_id=placement.item_revision_id,
                    draft=content,
                    images=bindings,
                )
            )
            local_images: list[tuple[ContentTeamImageSource, str, ArtifactMemberPointer]] = []
            for image in bindings:
                name = f"images/{image.sha256[7:]}.png"
                pointer = ArtifactMemberPointer(
                    artifact_id=image.artifact_id,
                    revision_id=image.artifact_revision_id,
                    member_name=image.artifact_member,
                    expected_sha256=image.sha256,
                    schema_ref=image.schema_ref,
                    media_type=image.media_type,
                    max_bytes=2 * 1024 * 1024,
                )
                image_stage.append((name, pointer))
                local_images.append((image, name, pointer))
            prefix = f"input/items/{position:03d}"
            json_file, markdown_file = (
                f"{prefix}/item-content.json",
                f"{prefix}/content-team-item.md",
            )
            self.adapter.stage_file(
                workspace,
                json_file,
                resolved[display_pointer],
                expected_sha256=placement.display_content.sha256,
            )
            self.adapter.stage_file(
                workspace,
                markdown_file,
                resolved[markdown_pointer],
                expected_sha256=placement.editorial_markdown.sha256,
            )
            # The next phase resolves exact PNG metadata before constructing the
            # size-bounded editorial segment. No image bytes enter this value.
            segments.append(
                _EditorialStage(
                    placement, content.schema_version, json_file, markdown_file, tuple(local_images)
                )
            )
        image_pointers = tuple(dict.fromkeys(pointer for _name, pointer in image_stage))
        image_paths = self.members.resolve_members(image_pointers)
        if len(image_paths) != len(image_pointers):
            _invalid("curated image member resolution is incomplete")
        images = dict(zip(image_pointers, image_paths, strict=True))
        staged: set[str] = set()
        for name, pointer in image_stage:
            if name not in staged:
                self.adapter.stage_file(
                    workspace, name, images[pointer], expected_sha256=pointer.expected_sha256
                )
                staged.add(name)
        finished: list[
            CuratedNativeSegment | CuratedCanonicalSegment | CuratedEditorialSegment
        ] = []
        for segment in segments:
            if not isinstance(segment, _EditorialStage):
                finished.append(segment)
                continue
            placement = segment.placement
            assert placement.editorial_markdown is not None
            finished.append(
                CuratedEditorialSegment(
                    position=placement.position,
                    item_revision_id=placement.item_revision_id,
                    source_schema_ref=(
                        "eom.assessment.item-content/2.0"
                        if segment.version == "2.0"
                        else "eom.assessment.item-content/3.0"
                    ),
                    json_file=segment.json_file,
                    source_sha256=placement.source_content.sha256,
                    json_size_bytes=(workspace / segment.json_file).stat().st_size,
                    markdown_file=segment.markdown_file,
                    markdown_sha256=placement.editorial_markdown.sha256,
                    markdown_size_bytes=(workspace / segment.markdown_file).stat().st_size,
                    images=tuple(
                        CuratedEditorialImage(
                            binding=image,
                            local_file=name,
                            size_bytes=images[pointer].stat().st_size,
                        )
                        for image, name, pointer in segment.images
                    ),
                )
            )
        request = CuratedMixedRenderRequest(
            build_id=build_id,
            assembly_revision_id=inputs.assembly_revision_id,
            assembly_manifest_sha256=inputs.assembly_manifest_sha256,
            input_plan_sha256=content_sha256(inputs.model_dump(mode="json")),
            segments=tuple(finished),
            handoff=inputs.handoff,
            converter=inputs.converter,
        )
        validate_contract("curated-render-request-v3", request.model_dump(mode="json"))
        return CuratedMaterialization(request, tuple(canonical), tuple(editorial))

    @staticmethod
    def _component_pointer(component: dict[str, Any]) -> CuratedArtifactMember:
        return CuratedArtifactMember(
            artifact_id=component["artifact_id"],
            artifact_revision_id=component["artifact_revision_id"],
            member_path=component["logical_name"],
            schema_ref=component["schema_ref"],
            media_type=component["media_type"],
            sha256=component["sha256"],
        )

    @staticmethod
    def _verify_recovery(
        placement: CuratedRegisteredItemInput,
        revision: dict[str, Any],
        displayed: AssessmentItemContent,
        resolved: dict[ArtifactMemberPointer, Path],
    ) -> None:
        source_pointer = _member(placement.source_content, 2 * 1024 * 1024)
        source = read_item_content(
            placement.source_content.schema_ref,
            parse_json_object(_read(resolved[source_pointer], source_pointer)),
        )
        if not isinstance(source, AssessmentItemContent):
            _invalid("visual recovery requires canonical Item/1.0 content")
        assert placement.recovery_manifest is not None
        recovery_pointer = _member(placement.recovery_manifest, 256 * 1024)
        manifest = read_visual_presentation_manifest(
            parse_json_object(_read(resolved[recovery_pointer], recovery_pointer)),
            placement.recovery_manifest.schema_ref,
        )
        reports = [
            row
            for row in revision.get("components", ())
            if row.get("component_type") == "REVIEW_REPORT" and row.get("ordinal") == 0
        ]
        if (
            manifest.item_id != placement.item_id
            or manifest.item_revision_id != placement.item_revision_id
            or manifest.canonical_content
            != SourceMember.model_validate(placement.source_content.model_dump())
            or len(reports) != 1
            or manifest.role_result
            != SourceMember.model_validate(
                CuratedInputMaterializer._component_pointer(reports[0]).model_dump()
            )
        ):
            _invalid("visual presentation proof differs from the pinned Item/solution report")
        expected = derive_creative_visual_content(
            source,
            manifest,
            artifact_id=placement.display_content.artifact_id,
            artifact_revision_id=placement.display_content.artifact_revision_id,
        )
        if (
            expected != displayed
            or content_sha256(expected.model_dump(mode="json")) != manifest.content_sha256
        ):
            _invalid("effective Item content differs from its source-bound visual proof")
