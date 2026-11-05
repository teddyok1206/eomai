"""One bounded page/chunk resolver shared by learning and knowledge analysis.

This is not an authority grant: its application caller authorizes the actual
source/operator before resolving these exact canonical pointers.
"""

from bisect import bisect_left
from dataclasses import dataclass

from eom_catalog_contracts.material_learning import (
    MaterialArtifactMember,
    MaterialInputPage,
    MaterialPreparedSource,
    SourceRole,
)
from eom_catalog_contracts.material_learning_preparation import (
    MaterialDocumentRevision,
    MaterialPageBundle,
    MaterialPageChunk,
    MaterialPreparedPage,
    material_chunk_member,
)

from eom_catalog_service.artifacts import CatalogArtifactService
from eom_catalog_service.material_learning_artifacts import read_material_metadata
from eom_catalog_service.material_learning_source import MaterialLearningSourceError


@dataclass(frozen=True, slots=True)
class ResolvedMaterialPage:
    chunk_manifest: MaterialArtifactMember
    page: MaterialPreparedPage

    def input_page(self, *, input_index: int, source_role: SourceRole) -> MaterialInputPage:
        return MaterialInputPage(
            input_index=input_index,
            source_role=source_role,
            physical_page=self.page.physical_page,
            image=material_chunk_member(self.chunk_manifest, self.page.image),
            text=material_chunk_member(self.chunk_manifest, self.page.text),
            width_pixels=self.page.width_pixels,
            height_pixels=self.page.height_pixels,
        )


@dataclass(frozen=True, slots=True)
class ResolvedMaterialPages:
    bundle: MaterialPageBundle
    chunk_manifests: tuple[MaterialArtifactMember, ...]
    pages: tuple[ResolvedMaterialPage, ...]


def read_material_source_pages(
    artifacts: CatalogArtifactService,
    source: MaterialPreparedSource | MaterialDocumentRevision,
    physical_pages: tuple[int, ...],
) -> ResolvedMaterialPages:
    """O(chunks + selected pages log chunks), one parse per selected chunk; <=32 pages."""
    page_count = (
        source.source_page_count
        if isinstance(source, MaterialDocumentRevision)
        else source.page_count
    )
    bundle_pointer = (
        source.analysis_bundle_manifest
        if isinstance(source, MaterialDocumentRevision)
        else source.page_bundle
    )
    pdf = source.source if isinstance(source, MaterialDocumentRevision) else source.pdf
    if (
        len(physical_pages) > 32
        or physical_pages != tuple(sorted(set(physical_pages)))
        or any(type(page) is not int or not 1 <= page <= page_count for page in physical_pages)
    ):
        raise MaterialLearningSourceError("MATERIAL_LEARNING_TASK_PAGE_COUNT_INVALID")
    bundle = read_material_metadata(
        artifacts,
        bundle_pointer,
        MaterialPageBundle,
        schema_ref="eom://schemas/material-learning/page-bundle/1.0",
        member_path="analysis/manifest.json",
    )
    if (
        bundle.document_id != source.document_id
        or bundle.document_revision_id != source.document_revision_id
        or bundle.source_role != source.source_role
        or bundle.pdf != pdf
        or bundle.original != source.original
        or bundle.page_count != page_count
        or (
            isinstance(source, MaterialPreparedSource)
            and bundle.office_catalog != source.office_catalog
        )
    ):
        raise MaterialLearningSourceError("MATERIAL_LEARNING_PAGE_BUNDLE_MISMATCH")
    ends = tuple(chunk.last_physical_page for chunk in bundle.chunks)
    selected: dict[int, MaterialPageChunk] = {}
    pages = []
    for number in physical_pages:
        index = bisect_left(ends, number)
        reference = bundle.chunks[index]
        if index not in selected:
            chunk = read_material_metadata(
                artifacts,
                reference.manifest,
                MaterialPageChunk,
                schema_ref="eom://schemas/material-learning/page-chunk/1.0",
                member_path="analysis/chunk.json",
            )
            if (
                chunk.document_id != source.document_id
                or chunk.document_revision_id != source.document_revision_id
                or chunk.source_role != source.source_role
                or chunk.pdf_sha256 != pdf.sha256
                or chunk.profile_sha256 != bundle.profile.profile_sha256
                or (chunk.first_physical_page, chunk.last_physical_page)
                != (reference.first_physical_page, reference.last_physical_page)
                or reference.content_bytes
                != reference.manifest.bytes
                + sum(page.text.bytes + page.image.bytes for page in chunk.pages)
            ):
                raise MaterialLearningSourceError("MATERIAL_LEARNING_PAGE_CHUNK_MISMATCH")
            selected[index] = chunk
        chunk = selected[index]
        pages.append(
            ResolvedMaterialPage(
                reference.manifest, chunk.pages[number - chunk.first_physical_page]
            )
        )
    return ResolvedMaterialPages(
        bundle=bundle,
        chunk_manifests=tuple(bundle.chunks[index].manifest for index in selected),
        pages=tuple(pages),
    )
