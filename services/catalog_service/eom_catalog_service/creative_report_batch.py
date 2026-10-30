"""Batch IO for authorized creative reports, reusing the original report validator."""

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

from eom_catalog_contracts.creative_source_lineage import CreativeSourceLineage
from eom_protocol.artifact_members import ArtifactMemberPointer
from sqlalchemy import select
from sqlalchemy.orm import Session

from eom_catalog_service.artifacts import CatalogArtifactService, CatalogJsonRevisionRequest
from eom_catalog_service.creative_learning_proposal import (
    resolve_completed_creative_learning_proposal,
)
from eom_catalog_service.creative_proposal_read_set import (
    MAX_CREATIVE_REPORT_CAPTURE,
    capture_creative_proposal_read_set,
)
from eom_catalog_service.creative_registered_report import (
    RegisteredCreativeReport,
    creative_report_components,
    validate_creative_report_lineage,
    validate_registered_creative_report,
)
from eom_catalog_service.models import ItemComponentRecord, ItemRevisionRecord


@dataclass(frozen=True, slots=True)
class CapturedRegisteredCreativeReport:
    report: RegisteredCreativeReport
    lineage_pointer: ArtifactMemberPointer


@dataclass(frozen=True, slots=True)
class _CapturedJsonPrimaries:
    """Actual checked primaries, not a reserialization masquerading as original bytes."""

    requests: Mapping[str, CatalogJsonRevisionRequest]
    documents: Mapping[str, dict[str, Any]]

    def load_json_revision(
        self, *, artifact_id: str, revision_id: str, content_hash: str, max_bytes: int = 1_048_576
    ) -> dict[str, Any]:
        request = self.requests.get(revision_id)
        if (
            request is None
            or request.artifact_id != artifact_id
            or request.content_hash != content_hash
            or max_bytes < request.max_bytes
        ):
            raise ValueError("CREATIVE_REPORT_BATCH_POINTER_INVALID")
        return self.documents[revision_id]


def load_registered_creative_reports(
    session: Session,
    artifacts: CatalogArtifactService,
    revisions: tuple[ItemRevisionRecord, ...],
) -> dict[str, CapturedRegisteredCreativeReport]:
    """Caller admits Item/Graph access first. Constant SQL count per <=16 sources.

    One component query, one primary materialization query and five ordered
    Workflow/plan/Job queries replace per-Item metadata lookups. Original hashes,
    lineage checks, result-schema checks and source warnings are not weakened.
    """
    if not revisions:
        return {}
    keys = tuple(row.item_revision_id for row in revisions)
    if (
        type(revisions) is not tuple
        or len(keys) > MAX_CREATIVE_REPORT_CAPTURE
        or len(set(keys)) != len(keys)
        or session.in_nested_transaction()
    ):
        raise ValueError("CREATIVE_REPORT_BATCH_SELECTION_INVALID")
    components: dict[str, list[ItemComponentRecord]] = {key: [] for key in keys}
    for row in session.scalars(
        select(ItemComponentRecord)
        .where(ItemComponentRecord.item_revision_id.in_(keys))
        .order_by(
            ItemComponentRecord.item_revision_id,
            ItemComponentRecord.component_type,
            ItemComponentRecord.ordinal,
        )
        # Approved children are trigger-immutable. FOR SHARE would require an
        # unnecessary UPDATE grant on this read-only canonical component table.
        .execution_options(populate_existing=True)
    ):
        components[row.item_revision_id].append(row)
    selected = {
        revision.item_revision_id: creative_report_components(
            revision, tuple(components[revision.item_revision_id])
        )
        for revision in revisions
    }
    requests: dict[str, CatalogJsonRevisionRequest] = {}
    for _content, lineage_component, report in selected.values():
        for component, limit in ((lineage_component, 64 * 1024), (report, 4 * 1024 * 1024)):
            request = CatalogJsonRevisionRequest(
                component.artifact_id, component.artifact_revision_id, component.sha256, limit
            )
            previous = requests.get(request.revision_id)
            if previous is not None and previous != request:
                raise ValueError("CREATIVE_REPORT_BATCH_POINTER_INVALID")
            requests[request.revision_id] = request
    documents = artifacts.load_json_revisions(tuple(requests.values()))
    if set(documents) != set(requests):
        raise ValueError("CREATIVE_REPORT_BATCH_POINTER_INVALID")
    lineages = {}
    for revision in revisions:
        content, lineage_component, report = selected[revision.item_revision_id]
        lineage = CreativeSourceLineage.model_validate(
            documents[lineage_component.artifact_revision_id]
        )
        validate_creative_report_lineage(revision, content, report, lineage)
        lineages[revision.item_revision_id] = lineage
    read_set = capture_creative_proposal_read_set(
        session, tuple(lineage.selection for lineage in lineages.values())
    )
    reader = _CapturedJsonPrimaries(MappingProxyType(requests), MappingProxyType(documents))
    result = {}
    for revision_id, lineage in lineages.items():
        resolved = resolve_completed_creative_learning_proposal(
            session, reader, lineage.selection, read_set=read_set
        )
        _content, component, _report = selected[revision_id]
        result[revision_id] = CapturedRegisteredCreativeReport(
            validate_registered_creative_report(lineage, resolved),
            ArtifactMemberPointer(
                artifact_id=component.artifact_id,
                artifact_revision_id=component.artifact_revision_id,
                member_path="lineage.json",
                schema_ref=component.schema_ref,
                media_type=component.media_type,
                sha256=component.sha256,
            ),
        )
    return result
