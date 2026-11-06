"""Publish exact uploaded-PDF figures through the existing file-set owner."""

from collections.abc import Callable, Mapping
from pathlib import Path
from types import MappingProxyType
from typing import Any, TypedDict

from eom_catalog_contracts.assessment_item import ImageBlock, MediaArtifactPointer
from eom_catalog_contracts.creative_source_draft import SourceImageBlock
from eom_catalog_contracts.creative_source_visuals import CREATIVE_SOURCE_VISUAL_IMAGE_REF
from eom_catalog_contracts.material_learning import (
    MaterialArtifactMember,
    MaterialExtractionResult,
    MaterialExtractionWork,
    SourceRole,
    validate_material_extraction,
)
from eom_catalog_contracts.material_learning_preparation import MaterialPreparedPage
from eom_catalog_contracts.material_source_visuals import (
    MATERIAL_VISUAL_SET_REF,
    MaterialPdfVisualSet,
)
from eom_identifiers import canonical_json_bytes, content_sha256, sha256_bytes, sha256_file
from eom_protocol.artifact_members import ArtifactMemberPointer

from eom_orchestrator.control_artifact_resolution import resolve_control_artifact_member
from eom_orchestrator.control_service import ControlPlaneError
from eom_orchestrator.external_item_learning_page_render import (
    MaterialPdfRenderSource,
    _trusted_executable,
    render_material_pdf_visual,
)
from eom_orchestrator.file_set_control_artifacts import (
    ControlFileSetMember,
    ControlFileSetPublisher,
)

_TYPE = "control_material_source_visuals"
_PRIMARY = "visual-set.json"


class MaterialVisualRecipe(TypedDict):
    source_region_id: str
    input_index: int
    source_role: SourceRole
    physical_page: int
    source_page: dict[str, Any]
    pdf: dict[str, Any]
    render_dpi: int
    pixel_box: list[int]
    member_path: str
    width_px: int
    height_px: int


def material_pdf_visual_recipes(
    work: MaterialExtractionWork,
    result: MaterialExtractionResult,
    pages: Mapping[tuple[SourceRole, int], MaterialPreparedPage],
) -> tuple[MaterialVisualRecipe, ...]:
    """O(pages + regions), preserve actual source role/page instead of input ordinal."""
    validate_material_extraction(result, work)
    if result.proposal is None:
        raise ValueError("MATERIAL_VISUAL_PROPOSAL_MISSING")
    selected = {
        block.source_region_id
        for block in result.proposal.content.body
        if isinstance(block, SourceImageBlock)
    }
    regions = {region.region_id: region for region in result.regions}
    input_pages = {page.input_index: page for page in work.pages}
    sources = {source.source_role: source for source in work.sources}
    recipes: list[MaterialVisualRecipe] = []
    for region_id in sorted(selected):
        region = regions[region_id]
        observed = input_pages[region.physical_page]
        source = sources[observed.source_role]
        page = pages[(observed.source_role, observed.physical_page)]
        if (
            source.actual_format != "PDF"
            or region.role != "TARGET_ITEM"
            or page.image.sha256 != observed.image.sha256
            or (page.width_pixels, page.height_pixels)
            != (observed.width_pixels, observed.height_pixels)
        ):
            raise ValueError("MATERIAL_VISUAL_PAGE_OR_ROLE_MISMATCH")
        box = region.bounding_box
        pixel_box = (
            box.left * page.width_pixels // 10000,
            box.top * page.height_pixels // 10000,
            (box.right * page.width_pixels + 9999) // 10000,
            (box.bottom * page.height_pixels + 9999) // 10000,
        )
        recipes.append(
            MaterialVisualRecipe(
                source_region_id=region_id,
                input_index=observed.input_index,
                source_role=observed.source_role,
                physical_page=observed.physical_page,
                source_page=observed.image.model_dump(mode="json"),
                pdf=source.pdf.model_dump(mode="json"),
                render_dpi=page.render_dpi,
                pixel_box=list(pixel_box),
                member_path=f"images/{region_id}.png",
                width_px=pixel_box[2] - pixel_box[0],
                height_px=pixel_box[3] - pixel_box[1],
            )
        )
    return tuple(recipes)


def publish_material_pdf_visuals(
    publisher: ControlFileSetPublisher,
    *,
    work: MaterialExtractionWork,
    result: MaterialExtractionResult,
    role_result: ArtifactMemberPointer,
    pages: Mapping[tuple[SourceRole, int], MaterialPreparedPage],
    read_source: Callable[[MaterialArtifactMember], bytes],
    authorize: Callable[[], None],
    workspace: Path,
    source_commit: str,
) -> Mapping[str, ImageBlock]:
    """Native Office input is rejected, never silently replaced with a PDF crop."""
    authorize()
    recipes = material_pdf_visual_recipes(work, result, pages)
    if not recipes:
        return MappingProxyType({})
    executable_sha = sha256_file(_trusted_executable(Path("/usr/bin/pdftoppm")))
    identity = dict(
        schema_version="material-learning-visual-set/1.0",
        input_sha256=work.input_sha256,
        result_sha256=content_sha256(result.model_dump(mode="json")),
        role_result=role_result.model_dump(mode="json"),
        pdftoppm_sha256=executable_sha,
    )
    key = "material-visuals:" + content_sha256(identity)[7:]
    try:
        published = publisher.find_published(idempotency_key=key, artifact_type=_TYPE)
    except ControlPlaneError as error:
        if error.code != "CONTROL_FILE_SET_INCOMPLETE":
            raise
        published = None
    if published is None:
        workspace.mkdir(mode=0o700)
        (workspace / "images").mkdir(mode=0o700)
        inputs: dict[SourceRole, MaterialPdfRenderSource] = {}
        members = []
        crops = []
        sources = {source.source_role: source for source in work.sources}
        for recipe in recipes:
            role = recipe["source_role"]
            source = sources[role]
            if role not in inputs:
                inputs[role] = MaterialPdfRenderSource(read_source(source.pdf), source.pdf.sha256)
            path = workspace / str(recipe["member_path"])
            digest, size = render_material_pdf_visual(
                inputs[role],
                physical_page=recipe["physical_page"],
                render_dpi=recipe["render_dpi"],
                pixel_box=(
                    recipe["pixel_box"][0],
                    recipe["pixel_box"][1],
                    recipe["pixel_box"][2],
                    recipe["pixel_box"][3],
                ),
                output=path,
            )
            crops.append({**recipe, "sha256": digest, "bytes": size})
            members.append(
                ControlFileSetMember(
                    str(recipe["member_path"]),
                    path,
                    digest,
                    size,
                    CREATIVE_SOURCE_VISUAL_IMAGE_REF,
                    "image/png",
                )
            )
        value = {**identity, "crops": crops}
        receipt = MaterialPdfVisualSet.model_validate(
            {**value, "manifest_sha256": content_sha256(value)}
        )
        payload = canonical_json_bytes(receipt.model_dump(mode="json"))
        path = workspace / _PRIMARY
        with path.open("xb") as stream:
            stream.write(payload)
        members.append(
            ControlFileSetMember(
                _PRIMARY,
                path,
                sha256_bytes(payload),
                len(payload),
                MATERIAL_VISUAL_SET_REF,
                "application/json",
            )
        )
        authorize()
        published = publisher.publish_first_observation(
            members=tuple(sorted(members, key=lambda member: member.file_name)),
            primary_file=_PRIMARY,
            artifact_type=_TYPE,
            manifest_version=receipt.schema_version,
            idempotency_key=key,
            source_commit=source_commit,
        )
    actual = publisher.read_published_revision(
        artifact_revision_id=published.artifact_revision_id, artifact_type=_TYPE
    )
    if actual != published or actual.primary_file != _PRIMARY:
        raise ValueError("MATERIAL_VISUAL_PUBLICATION_MISMATCH")
    raw = resolve_control_artifact_member(
        publisher.engine,
        ArtifactMemberPointer(
            artifact_id=actual.artifact_id,
            artifact_revision_id=actual.artifact_revision_id,
            member_path=_PRIMARY,
            schema_ref=MATERIAL_VISUAL_SET_REF,
            media_type="application/json",
            sha256=actual.primary_sha256,
        ),
        maximum_bytes=512 * 1024,
    )
    receipt = MaterialPdfVisualSet.model_validate_json(raw)
    if (
        receipt.model_dump(mode="json", exclude={"crops", "manifest_sha256"}) != identity
        or tuple(
            crop.model_dump(mode="json", exclude={"sha256", "bytes"}) for crop in receipt.crops
        )
        != recipes
    ):
        raise ValueError("MATERIAL_VISUAL_REPLAY_CONFLICT")
    authorize()
    crops_by_region = {crop.source_region_id: crop for crop in receipt.crops}
    assert result.proposal is not None
    return MappingProxyType(
        {
            block.block_id: ImageBlock(
                block_id=block.block_id,
                purpose=block.purpose,
                alt_text=block.alt_text,
                width_px=crops_by_region[block.source_region_id].width_px,
                height_px=crops_by_region[block.source_region_id].height_px,
                artifact=MediaArtifactPointer(
                    artifact_id=actual.artifact_id,
                    artifact_revision_id=actual.artifact_revision_id,
                    artifact_member=crops_by_region[block.source_region_id].member_path,
                    sha256=crops_by_region[block.source_region_id].sha256,
                    media_type="image/png",
                ),
            )
            for block in result.proposal.content.body
            if isinstance(block, SourceImageBlock)
        }
    )
