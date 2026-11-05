"""Build one bounded task from canonical chunk members, never copy a whole book."""

from bisect import bisect_left
from collections.abc import Callable

from eom_catalog_contracts.material_learning import (
    MaterialArtifactMember,
    MaterialDiscoveredUnit,
    MaterialDiscoveryWork,
    MaterialExtractionWork,
    MaterialInputPage,
    MaterialLearningWork,
    MaterialPageAddress,
    material_work_schema_ref,
)
from eom_catalog_contracts.material_learning_intake import MaterialLearningIntakeManifest
from eom_catalog_contracts.material_learning_preparation import (
    MaterialPageBundle,
    MaterialPageChunk,
    MaterialPreparedArtifact,
    material_chunk_member,
)
from eom_identifiers import content_sha256
from eom_workflow.material_learning_plan import MaterialDiscoveryWindow, PlannedMaterialUnit

from eom_catalog_service.artifacts import CatalogArtifactService
from eom_catalog_service.material_learning_artifacts import (
    publish_material_metadata,
    read_material_metadata,
)
from eom_catalog_service.settings import CatalogSettings


class MaterialLearningWorkService:
    def __init__(self, artifacts: CatalogArtifactService, settings: CatalogSettings) -> None:
        self.artifacts, self.settings = artifacts, settings

    def discovery(
        self,
        *,
        task_id: str,
        prepared: MaterialPreparedArtifact,
        intake: MaterialLearningIntakeManifest,
        window: MaterialDiscoveryWindow,
    ) -> MaterialDiscoveryWork:
        positions = tuple(
            MaterialPageAddress(source_role=window.source_role, physical_page=number)
            for number in range(window.first_input_page, window.last_input_page + 1)
        )
        body = {
            **self._common(task_id, prepared, intake, positions),
            "schema_version": "material-learning-discovery-work/1.0",
            "task_kind": "DISCOVER",
            "core_pages": [
                {"source_role": window.source_role, "physical_page": number}
                for number in range(window.first_core_page, window.last_core_page + 1)
            ],
        }
        return MaterialDiscoveryWork.model_validate({**body, "input_sha256": content_sha256(body)})

    def extraction(
        self,
        *,
        task_id: str,
        prepared: MaterialPreparedArtifact,
        intake: MaterialLearningIntakeManifest,
        question: PlannedMaterialUnit,
        solutions: tuple[MaterialDiscoveredUnit, ...],
    ) -> MaterialExtractionWork:
        order = {source.source_role: index for index, source in enumerate(prepared.sources)}
        positions = tuple(
            MaterialPageAddress(source_role=role, physical_page=page)
            for role, page in sorted(
                {
                    (anchor.source_role, anchor.physical_page)
                    for unit in (question.unit, *solutions)
                    for anchor in unit.anchors
                },
                key=lambda position: (order[position[0]], position[1]),
            )
        )
        body = {
            **self._common(task_id, prepared, intake, positions),
            "schema_version": "material-learning-extraction-work/1.0",
            "task_kind": "EXTRACT_ITEM",
            "unit_key": question.unit_key,
            "question": question.unit.model_dump(mode="json"),
            "solutions": [solution.model_dump(mode="json") for solution in solutions],
        }
        return MaterialExtractionWork.model_validate({**body, "input_sha256": content_sha256(body)})

    def _common(
        self,
        task_id: str,
        prepared: MaterialPreparedArtifact,
        intake: MaterialLearningIntakeManifest,
        positions: tuple[MaterialPageAddress, ...],
    ) -> dict[str, object]:
        if (
            not 1 <= len(positions) <= 32
            or prepared.material_id != intake.material_id
            or prepared.material_revision_id != intake.material_revision_id
        ):
            raise ValueError("MATERIAL_LEARNING_TASK_SOURCE_INVALID")
        return {
            "material_id": prepared.material_id,
            "material_revision_id": prepared.material_revision_id,
            "task_id": task_id,
            "sources": [source.model_dump(mode="json") for source in prepared.sources],
            "rights_attestation": intake.rights_attestation.model_dump(mode="json"),
            "pages": [page.model_dump(mode="json") for page in self.pages(prepared, positions)],
            "additional_instructions": intake.upload.additional_instructions,
        }

    def pages(
        self, prepared: MaterialPreparedArtifact, positions: tuple[MaterialPageAddress, ...]
    ) -> tuple[MaterialInputPage, ...]:
        """O(selected pages log chunks); parse each selected chunk once per task."""
        if not 1 <= len(positions) <= 32 or len(set(positions)) != len(positions):
            raise ValueError("MATERIAL_LEARNING_TASK_PAGE_COUNT_INVALID")
        sources = {source.source_role: source for source in prepared.sources}
        bundles: dict[str, MaterialPageBundle] = {}
        chunk_ends: dict[str, tuple[int, ...]] = {}
        chunks: dict[tuple[str, int], MaterialPageChunk] = {}
        pages = []
        for index, position in enumerate(positions, 1):
            source = sources[position.source_role]
            if position.physical_page > source.page_count:
                raise ValueError("MATERIAL_LEARNING_TASK_PAGE_OUTSIDE_SOURCE")
            if source.source_role not in bundles:
                bundles[source.source_role] = read_material_metadata(
                    self.artifacts,
                    source.page_bundle,
                    MaterialPageBundle,
                    schema_ref="eom://schemas/material-learning/page-bundle/1.0",
                    member_path=source.page_bundle.member_path,
                )
                chunk_ends[source.source_role] = tuple(
                    entry.last_physical_page for entry in bundles[source.source_role].chunks
                )
            bundle = bundles[source.source_role]
            if (
                bundle.document_id != source.document_id
                or bundle.document_revision_id != source.document_revision_id
                or bundle.source_role != source.source_role
                or bundle.pdf != source.pdf
                or bundle.original != source.original
                or bundle.profile.profile_sha256 != prepared.profile_sha256
                or bundle.page_count != source.page_count
                or bundle.office_catalog != source.office_catalog
            ):
                raise ValueError("MATERIAL_LEARNING_TASK_PAGE_BUNDLE_MISMATCH")
            chunk_index = bisect_left(chunk_ends[source.source_role], position.physical_page)
            reference = bundle.chunks[chunk_index]
            key = (source.source_role, chunk_index)
            if key not in chunks:
                chunks[key] = read_material_metadata(
                    self.artifacts,
                    reference.manifest,
                    MaterialPageChunk,
                    schema_ref=reference.manifest.schema_ref,
                    member_path=reference.manifest.member_path,
                )
            chunk = chunks[key]
            if (
                chunk.document_revision_id != source.document_revision_id
                or chunk.source_role != source.source_role
                or chunk.pdf_sha256 != source.pdf.sha256
                or chunk.profile_sha256 != prepared.profile_sha256
                or (chunk.first_physical_page, chunk.last_physical_page)
                != (
                    reference.first_physical_page,
                    reference.last_physical_page,
                )
            ):
                raise ValueError("MATERIAL_LEARNING_TASK_CHUNK_MISMATCH")
            page = chunk.pages[position.physical_page - chunk.first_physical_page]
            pages.append(
                MaterialInputPage(
                    input_index=index,
                    source_role=source.source_role,
                    physical_page=page.physical_page,
                    image=material_chunk_member(reference.manifest, page.image),
                    text=material_chunk_member(reference.manifest, page.text),
                    width_pixels=page.width_pixels,
                    height_pixels=page.height_pixels,
                )
            )
        return tuple(pages)

    def publish(
        self, work: MaterialLearningWork, *, authorize: Callable[[], None]
    ) -> MaterialArtifactMember:
        authorize()
        pointer = publish_material_metadata(
            self.artifacts,
            self.settings,
            work,
            member_path="material/work.json",
            schema_ref=material_work_schema_ref(work),
            artifact_type="material-learning-work",
            idempotency_key="material-task-input:" + work.task_id,
        )
        authorize()
        return pointer
