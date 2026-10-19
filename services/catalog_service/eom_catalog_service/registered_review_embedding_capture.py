"""Fresh same-root registered REVIEW additions to an officially admitted pool.

No pool/source grant, analysis creation, model execution or persistent cache.
Indexed bounded sets classify provenance; supported grounded sources must pass
the public all-or-error registered/receipt owner. Historical unsupported sources
remain missing. Mutable parent locks and retained immutable leaves belong only
to the caller's original SQL root.
"""

from __future__ import annotations

import re
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import NoReturn

from eom_catalog_contracts.embedding_reference_query import raw_similarity_contract_value
from eom_catalog_contracts.inference_transfer_experiment import (
    ExperimentViewRecipe,
    PopulationSource,
    StagedExperimentEntry,
)
from eom_catalog_contracts.knowledge import (
    ApprovedItemKnowledgeSourceV2,
    KnowledgeGraphSnapshotPointer,
    same_approved_item_source_identity,
)
from eom_catalog_contracts.mixed_embedding_index import (
    RegisteredReviewEmbeddingEntry,
    SupportedEmbeddingEntry,
    parse_supported_embedding_entry,
)
from eom_catalog_contracts.registered_review_profile import RegisteredReviewSourceBasis
from eom_identifiers import content_sha256
from eom_orchestrator.control_models import ResolvedExecutionPlanRecord
from eom_orchestrator.control_service import compute_control_document_hash
from eom_workflow import ResolvedExecutionPlan, ResolvedExecutionPlanV18, ResolvedExecutionPlanV20
from eom_workflow_runner.models import WorkflowDefinitionRecord, WorkflowInstanceRecord
from eom_workflow_runner.repository import (
    load_persisted_workflow_request,
    workflow_business_fingerprint,
)
from pydantic import TypeAdapter
from sqlalchemy import select
from sqlalchemy.orm import Session, SessionTransaction

from eom_catalog_service.artifacts import CatalogArtifactService
from eom_catalog_service.embedding_registry_ports import EmbeddingRegistryError
from eom_catalog_service.evidence_usage_receipts import BatchEvidenceUsageReceiptResolver
from eom_catalog_service.inference_transfer_item_projection import (
    ItemProjectionUnavailable,
    extract_original_item_metadata,
    render_no_solution_item_text,
)
from eom_catalog_service.inference_transfer_service import AdmittedInferenceTransferSource
from eom_catalog_service.item_content_contract import canonical_content_team_item_materialization
from eom_catalog_service.models import ItemComponentRecord, ItemRevisionRecord
from eom_catalog_service.registered_item_review_solution_resolver import (
    lock_registered_item_review_sources,
    resolve_registered_item_review_solutions,
)
from eom_catalog_service.registered_review_projection import project_registered_review_solution

_GROUND_PLAN_SCHEMAS = frozenset(
    f"resolved-execution-plan/{version}.0" for version in (11, 12, 16, 17, 19, 23, 24)
)
_UNGROUNDED_PLAN_TYPES: dict[str, type[ResolvedExecutionPlan]] = {
    "resolved-execution-plan/1.0": ResolvedExecutionPlan,
    "resolved-execution-plan/18.0": ResolvedExecutionPlanV18,
    "resolved-execution-plan/20.0": ResolvedExecutionPlanV20,
}
_REVIEW_ROLE_SCHEMAS = frozenset(
    {"authoring-result@11.0", "authoring-result@12.0", "review-result@11.0", "review-result@12.0"}
)


def _fail() -> NoReturn:
    raise EmbeddingRegistryError("EMBEDDING_REGISTRY_REGISTERED_REVIEW_SOURCE_INVALID")


@dataclass(frozen=True, slots=True)
class RegisteredReviewEmbeddingCapture:
    entries: tuple[SupportedEmbeddingEntry, ...]
    missing_source_revision_ids: tuple[str, ...]
    base_analysis_run_ids: tuple[tuple[str, str], ...]
    limitations: tuple[tuple[str, str], ...]
    _session: Session = field(repr=False, compare=False)
    _root: SessionTransaction = field(repr=False, compare=False)
    _nested: SessionTransaction | None = field(repr=False, compare=False)
    _thread: int = field(repr=False, compare=False)
    _retained: tuple[object, ...] = field(repr=False, compare=False)

    def assert_current(self, session: Session) -> None:
        if (
            session is not self._session
            or threading.get_ident() != self._thread
            or session.get_transaction() is not self._root
            or not self._root.is_active
            or session.get_nested_transaction() is not self._nested
            or (self._nested is not None and not self._nested.is_active)
        ):
            _fail()


def _grounded_candidates(
    session: Session,
    sources: tuple[ApprovedItemKnowledgeSourceV2, ...],
) -> tuple[
    tuple[ApprovedItemKnowledgeSourceV2, ...], tuple[object, ...], tuple[tuple[str, str], ...]
]:
    if not sources:
        return (), (), ()
    revisions = tuple(
        session.scalars(
            select(ItemRevisionRecord)
            .where(
                ItemRevisionRecord.item_revision_id.in_(
                    tuple(row.item_revision_id for row in sources)
                )
            )
            .order_by(ItemRevisionRecord.item_revision_id)
            .with_for_update(read=True)
            .execution_options(populate_existing=True)
        )
    )
    by_revision = {row.item_revision_id: row for row in revisions}
    if set(by_revision) != {row.item_revision_id for row in sources}:
        _fail()
    workflows = tuple(
        session.scalars(
            select(WorkflowInstanceRecord)
            .where(
                WorkflowInstanceRecord.workflow_id.in_(
                    tuple(row.workflow_id for row in revisions if row.workflow_id)
                )
            )
            .order_by(WorkflowInstanceRecord.workflow_id)
            .with_for_update(read=True)
            .execution_options(populate_existing=True)
        )
    )
    by_workflow = {row.workflow_id: row for row in workflows}
    components = tuple(
        session.scalars(
            select(ItemComponentRecord)
            .where(
                ItemComponentRecord.item_revision_id.in_(
                    tuple(row.item_revision_id for row in sources)
                ),
                ItemComponentRecord.component_type.in_(("UPPER_STEM", "REVIEW_REPORT")),
                ItemComponentRecord.ordinal == 0,
            )
            .limit(2 * len(sources) + 1)
            .execution_options(populate_existing=True)
        )
    )
    if len(components) > 2 * len(sources):
        _fail()
    components_by_revision: dict[str, list[ItemComponentRecord]] = {}
    for row in components:
        components_by_revision.setdefault(row.item_revision_id, []).append(row)
    plans = tuple(
        session.scalars(
            select(ResolvedExecutionPlanRecord)
            .where(ResolvedExecutionPlanRecord.workflow_id.in_(tuple(by_workflow)))
            .execution_options(populate_existing=True)
        )
    )
    by_plan = {row.workflow_id: row for row in plans}
    definitions = tuple(
        session.scalars(
            select(WorkflowDefinitionRecord)
            .where(
                WorkflowDefinitionRecord.definition_id.in_(
                    tuple(row.definition_id for row in workflows)
                )
            )
            .execution_options(populate_existing=True)
        )
    )
    by_definition = {row.definition_id: row for row in definitions}
    selected = []
    limitations = []
    for source in sources:
        revision = by_revision[source.item_revision_id]
        workflow = by_workflow.get(revision.workflow_id)
        role_components = components_by_revision.get(source.item_revision_id, ())
        if revision.item_id != source.item_id or revision.revision_state != "APPROVED":
            _fail()
        if workflow is None or workflow.role_schema_version not in {
            "workflow-role/1.23.0",
            "workflow-role/1.24.0",
        }:
            if any(row.schema_ref in _REVIEW_ROLE_SCHEMAS for row in role_components):
                _fail()
            limitations.append(
                (source.item_revision_id, "REGISTERED_REVIEW_UNSUPPORTED_HISTORICAL_FAMILY")
            )
            continue
        definition = by_definition.get(workflow.definition_id)
        record = by_plan.get(workflow.workflow_id)
        if (
            definition is None
            or record is None
            or workflow.definition_key != "generic-item-development"
            or workflow.definition_version != revision.workflow_definition_version
            or workflow.state != "COMPLETED"
            or workflow.initial_request != workflow.request_payload
            or workflow.definition_key != definition.definition_key
            or workflow.definition_version != definition.definition_version
            or workflow.definition_hash != definition.definition_hash
            or definition.definition_hash != content_sha256(definition.canonical_definition)
        ):
            _fail()
        assert definition is not None and record is not None
        request = load_persisted_workflow_request(workflow.initial_request)
        if workflow.request_hash != workflow_business_fingerprint(definition, request):
            _fail()
        body = record.canonical_document
        if (
            body.get("workflow_id") != workflow.workflow_id
            or body.get("workflow_definition_key") != workflow.definition_key
            or body.get("workflow_definition_version") != workflow.definition_version
            or body.get("workflow_definition_sha256") != workflow.definition_hash
            or record.plan_sha256 != body.get("plan_sha256")
            or record.plan_sha256 != compute_control_document_hash(body, "plan_sha256")
        ):
            _fail()
        schema = body.get("schema_version")
        if request.educational_retrieval is None:
            model = _UNGROUNDED_PLAN_TYPES.get(str(schema))
            if model is None:
                _fail()
            assert model is not None
            ungrounded = model.model_validate(body)
            if (
                ungrounded.graph_snapshot_revision_id is not None
                or ungrounded.evidence_bundle_revision_id is not None
                or record.graph_snapshot_revision_id is not None
                or record.evidence_bundle_revision_id is not None
                or any(
                    row.metadata_json.get("evidence_usage_validation_receipt_sha256") is not None
                    for row in role_components
                )
            ):
                _fail()
            limitations.append(
                (source.item_revision_id, "REGISTERED_REVIEW_NO_GROUNDED_RECEIPT_PLAN")
            )
            continue
        if schema not in _GROUND_PLAN_SCHEMAS:
            _fail()
        selected.append(source)
    return (
        tuple(selected),
        (revisions, workflows, components, plans, definitions),
        tuple(limitations),
    )


def capture_registered_review_embedding_entries(
    session: Session,
    *,
    admitted_sources: tuple[AdmittedInferenceTransferSource, ...],
    existing_entries: tuple[SupportedEmbeddingEntry, ...],
    graph_snapshot: KnowledgeGraphSnapshotPointer,
    recipe: ExperimentViewRecipe,
    artifacts: CatalogArtifactService,
    receipts: BatchEvidenceUsageReceiptResolver,
    authorize_source: Callable[[ApprovedItemKnowledgeSourceV2], None],
) -> RegisteredReviewEmbeddingCapture:
    """Add only genuine grounded registered review sources; old profile1 stays exact."""
    if (
        type(admitted_sources) is not tuple
        or len(admitted_sources) > 1024
        or type(existing_entries) is not tuple
        or len(existing_entries) > len(admitted_sources)
        or session.new
        or session.dirty
        or session.deleted
    ):
        _fail()
    nested = session.get_nested_transaction()
    graph = KnowledgeGraphSnapshotPointer.model_validate(
        raw_similarity_contract_value(graph_snapshot)
    )
    checked_recipe = ExperimentViewRecipe.model_validate(raw_similarity_contract_value(recipe))
    admitted = {}
    for row in admitted_sources:
        if (
            type(row) is not AdmittedInferenceTransferSource
            or type(row.analysis_run_id) is not str
            or re.fullmatch(r"analysisrun_[0-9a-f]{32}", row.analysis_run_id) is None
        ):
            _fail()
        source: PopulationSource = TypeAdapter(PopulationSource).validate_python(
            raw_similarity_contract_value(row.source)
        )
        if source.item_revision_id in admitted:
            _fail()
        admitted[source.item_revision_id] = (row.analysis_run_id, source)
    if len({row[0] for row in admitted.values()}) != len(admitted):
        _fail()
    entries: dict[str, SupportedEmbeddingEntry] = {}
    for value in existing_entries:
        entry = parse_supported_embedding_entry(value)
        basis = entry.profile.source_basis
        expected = admitted.get(basis.source.item_revision_id)
        if (
            expected is None
            or not same_approved_item_source_identity(basis.source, expected[1])
            or basis.graph_snapshot != graph
            or basis.source.item_revision_id in entries
            or (
                isinstance(entry, StagedExperimentEntry)
                and entry.profile.source_basis.solution_evidence.base_analysis_run_id != expected[0]
            )
        ):
            _fail()
        entries[basis.source.item_revision_id] = entry
    possible = tuple(
        source
        for _run_id, source in admitted.values()
        if source.source_class == "APPROVED_ITEM"
        and not isinstance(entries.get(source.item_revision_id), StagedExperimentEntry)
    )
    for source in possible:
        authorize_source(source)
    selected, retained, limitations = _grounded_candidates(session, possible)
    selected_ids = {row.item_revision_id for row in selected}
    if any(
        isinstance(value, RegisteredReviewEmbeddingEntry) and revision not in selected_ids
        for revision, value in entries.items()
    ):
        _fail()
    status = set(limitations)
    held = None
    if selected:
        held = lock_registered_item_review_sources(session, sources=selected)
        resolved = resolve_registered_item_review_solutions(
            session,
            sources=selected,
            artifacts=artifacts,
            receipts=receipts,
            authorize_source=authorize_source,
        )
        if len(resolved) != len(selected):
            _fail()
        for source, proof in zip(selected, resolved, strict=True):
            if proof.evidence.source != source:
                _fail()
            profile = project_registered_review_solution(
                source_basis=RegisteredReviewSourceBasis(
                    source=source, graph_snapshot=graph, review_evidence=proof.evidence
                ),
                authoring=proof.authoring,
                review=proof.review,
                created_at=proof.review_completed_at,
            )
            # The public resolver already proved this exact canonical registration
            # projection equal to the actual ITEM_CONTENT member bytes.
            item = canonical_content_team_item_materialization(proof.draft)
            try:
                content = render_no_solution_item_text(
                    item=item, original_source=source.artifact_member, recipe=checked_recipe
                )
            except ItemProjectionUnavailable as exc:
                content = None
                status.add((source.item_revision_id, exc.code))
            metadata = extract_original_item_metadata(
                item=item, original_source=source.artifact_member
            )
            if not metadata.fields:
                status.add(
                    (source.item_revision_id, "REGISTERED_REVIEW_ORIGINAL_METADATA_UNAVAILABLE")
                )
            entries[source.item_revision_id] = RegisteredReviewEmbeddingEntry(
                profile=profile, content=content, metadata=metadata.fields
            )
        held.assert_current(session)
    for source in possible:
        authorize_source(source)
    root = session.get_transaction()
    if root is None or not root.is_active:
        _fail()
    capture = RegisteredReviewEmbeddingCapture(
        entries=tuple(
            entries[row.source.item_revision_id]
            for row in admitted_sources
            if row.source.item_revision_id in entries
        ),
        missing_source_revision_ids=tuple(sorted(set(admitted) - set(entries))),
        base_analysis_run_ids=tuple(
            sorted((revision, row[0]) for revision, row in admitted.items())
        ),
        limitations=tuple(sorted(status)),
        _session=session,
        _root=root,
        _nested=nested,
        _thread=threading.get_ident(),
        _retained=(admitted_sources, *retained, held),
    )
    capture.assert_current(session)
    return capture
