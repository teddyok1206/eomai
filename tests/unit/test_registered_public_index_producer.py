"""Canonical control publication with synthetic source authority, never a model invocation."""

from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest
from eom_catalog_contracts.registered_public_solution_index import (
    REGISTERED_PUBLIC_SOLUTION_INDEX_SCHEMA_REF,
)
from eom_catalog_contracts.registered_public_solution_similarity import (
    public_solution_reference_for_entry,
)
from eom_catalog_service.embedding_index_refresh_plan import (
    public_index_membership_refresh_reason,
    registered_public_index_membership_refresh_reason,
)
from eom_catalog_service.embedding_registry_ports import (
    EmbeddingRegistryLookup,
    MissingEmbeddingBindings,
    PreparedEmbeddingBindingLookup,
    PublicSolutionEmbeddingBindingLookupKey,
    ResolvedEmbeddingLookup,
)
from eom_identifiers import content_sha256, sha256_bytes
from eom_workflow.embedding_batch_plan_family import (
    embedding_batch_plan_schema_identity,
    embedding_batch_selection_read_maximum,
    parse_embedding_batch_plan_request,
    parse_embedding_batch_selection,
    validate_embedding_batch_plan_controls,
)
from eom_workflow.embedding_batch_plan_v11 import MAX_BULK_BATCH_SELECTION_BYTES
from eom_workflow.embedding_batch_plan_v13 import EmbeddingBatchSelectionV13
from eom_workflow.embedding_batch_plan_v16 import (
    BATCH_PLAN_V16_PROTOCOL,
    BATCH_PLAN_V16_SCHEMA_SHA256,
    EmbeddingBatchSelectionV16,
)
from eom_workflow.local_embedding_request_v4 import LocalEmbeddingWorkflowRequestV4
from eom_workflow.local_embedding_source_plan_v4 import parse_local_embedding_source_plan_v4
from eom_workflow_runner import local_embedding_service_reconciliation as preparation
from eom_workflow_runner.document_embedding_parent_preparation import (
    prepare_document_embedding_parent,
)

from tests.unit.document_embedding_parent_fixtures import parent_case as parent_case
from tests.unit.inference_transfer_embedding_fixtures import seal
from tests.unit.test_local_embedding_source_plan_v4 import entries, plan_value
from tests.unit.test_local_indexing_routed_sources import routed as routed
from tests.unit.test_local_indexing_routed_sources import routed_publisher as routed_publisher
from tests.unit.test_public_solution_batch_plan import public_case
from tests.unit.test_registered_public_solution_index import successor


@pytest.mark.parametrize("routed", ["registered_public"], indirect=True)
def test_registered_original_source_pins_all_three_reports_and_replays_exact_parent(
    parent_case, monkeypatch
):
    value = parent_case
    parent = prepare_document_embedding_parent(
        value.pair, value.request, value.sources.configuration
    )
    replay = prepare_document_embedding_parent(
        value.pair, value.request, value.sources.configuration
    )
    assert parent.request == replay.request
    assert parent.allocation != replay.allocation
    assert parent.request.parent_request_sha256 == value.request.request_sha256
    assert embedding_batch_plan_schema_identity(parent.request) == (
        BATCH_PLAN_V16_PROTOCOL,
        BATCH_PLAN_V16_SCHEMA_SHA256,
    )
    assert parse_embedding_batch_plan_request(parent.request) == parent.request
    assert embedding_batch_selection_read_maximum(parent.request) == MAX_BULK_BATCH_SELECTION_BYTES
    with (
        value.routed.publisher.sessions.begin() as session,
        parent.operation.admission.admit(session, parent.request) as admitted,
    ):
        selection = admitted.selection
        assert parse_embedding_batch_selection(selection) == selection
        assert {anchor.evidence.kind for anchor in selection.anchors} == {
            "ACCEPTED_SOLUTION_ANALYSIS",
            "REGISTERED_CREATIVE_SOURCE_REPORT",
            "ACCEPTED_REGISTERED_SOLUTION_ANALYSIS",
        }
        assert tuple(anchor.source for anchor in selection.anchors) == value.plan.sources
        validate_embedding_batch_plan_controls(parent.request, selection, admitted.policy)
        with pytest.raises(ValueError):
            EmbeddingBatchSelectionV13.model_validate(selection.model_dump(mode="json"))
    monkeypatch.setattr(
        preparation,
        "admitted_workflow_definition",
        lambda *_args, **_kwargs: SimpleNamespace(definition_hash="sha256:" + "9" * 64),
    )
    matched = value.pair.cpu.prepare_matching(value.pair.cuda, value.request)
    assert isinstance(matched, LocalEmbeddingWorkflowRequestV4)
    assert matched.space.runtime.device == "CPU"
    assert matched.graph_snapshot == value.request.graph_snapshot
    assert matched.source_plan.schema_ref.endswith("/4.0")


@pytest.mark.parametrize("routed", ["registered_public"], indirect=True)
def test_new_discovery_prepares_request4_and_fences_after_canonical_publication(
    parent_case, monkeypatch
):
    value = parent_case
    with value.routed.publisher.sessions.begin() as session:
        original = value.pair.cuda.owner.resolve_sources(session, value.request)
    # Matching already exercises actual plan4 construction/publication and final
    # authority fences. Force discovery's default, rather than the replay override.
    query = EmbeddingRegistryLookup(
        value.request.corpus_id,
        value.request.namespace,
        value.request.graph_snapshot,
        value.request.access_policy_revision_id,
        value.request.access_policy_sha256,
        value.pair.maximum_sources,
    )
    captured = ResolvedEmbeddingLookup(
        query.corpus_id,
        value.request.space,
        original.admission.plan.recipe,
        original.admission.plan.sources,
        original.entries,
        base_analysis_run_ids=tuple(
            (e.source.item_revision_id, e.base_analysis_run_id) for e in original.entries
        ),
    )
    monkeypatch.setattr(
        preparation,
        "admitted_workflow_definition",
        lambda *_args, **_kwargs: SimpleNamespace(definition_hash="sha256:" + "9" * 64),
    )
    keys = tuple(
        PublicSolutionEmbeddingBindingLookupKey(
            demand.source_revision_id,
            query.graph_snapshot.graph_snapshot_revision_id,
            query.policy_revision_id,
            captured.recipe.recipe_sha256,
            query.namespace.view,
            query.namespace.projection_version,
            demand.base_analysis_run_id,
            demand.profile.profile_revision_id,
            demand.encoding.encoding_sha256,
            content_sha256(demand.evidence),
        )
        for demand in value.plan.demands
    )
    monkeypatch.setattr(
        value.pair.cuda.owner, "current_reconciliation_lookup", lambda session: query
    )
    monkeypatch.setattr(
        preparation,
        "prepare_missing_embedding_bindings",
        lambda *_args: PreparedEmbeddingBindingLookup(
            MissingEmbeddingBindings(keys, (), len(captured.sources), len(captured.entries)),
            captured,
            (),
        ),
    )
    prepared = value.pair.cuda.prepare_once()
    request = prepared.request
    assert prepared.observed.selected_target_count == len(captured.sources)
    assert isinstance(request, LocalEmbeddingWorkflowRequestV4)
    assert request.source_plan.schema_ref.endswith("/4.0")
    assert request.source_plan_sha256 == value.plan.plan_sha256
    original_publish = value.pair.cuda.controls.publish_observed_source_plan_v4

    def revoke_after_publication(plan, *, idempotency_key):
        published = original_publish(plan, idempotency_key=idempotency_key)
        value.routed.current.deny = True
        return published

    monkeypatch.setattr(
        value.pair.cuda.controls, "publish_observed_source_plan_v4", revoke_after_publication
    )
    with pytest.raises(PermissionError):
        value.pair.cuda.prepare_once()


def test_registered_membership_uses_exact_original_index_family_and_never_widens_old_reader():
    parent, index, pointer, _shards = successor()
    parent_sources = tuple(binding.source for binding in parent.bindings)
    assert (
        registered_public_index_membership_refresh_reason(
            eligible_sources=parent_sources,
            available_bindings=parent.bindings,
            previous=(pointer, parent),
        )
        == "INDEX_MEMBERSHIP_CHANGED"
    )
    assert (
        public_index_membership_refresh_reason(
            eligible_sources=parent_sources,
            available_bindings=parent.bindings,
            previous=(pointer, parent),
        )
        is None
    )
    pointer = type(pointer).model_validate(
        pointer.model_dump(mode="json")
        | {
            "schema_ref": REGISTERED_PUBLIC_SOLUTION_INDEX_SCHEMA_REF,
            "sha256": content_sha256(index.model_dump(mode="json")),
        }
    )
    bindings = index.bindings
    sources = tuple(b.source for b in bindings)
    assert (
        registered_public_index_membership_refresh_reason(
            eligible_sources=sources, available_bindings=bindings[::-1], previous=(pointer, index)
        )
        is None
    )
    assert (
        registered_public_index_membership_refresh_reason(
            eligible_sources=sources, available_bindings=bindings, previous=None
        )
        == "MISSING_NAMESPACE_INDEX"
    )
    with pytest.raises(ValueError):
        public_index_membership_refresh_reason(
            eligible_sources=sources, available_bindings=bindings, previous=(pointer, index)
        )
    wrong = pointer.model_copy(update={"sha256": "sha256:" + "0" * 64})
    with pytest.raises(ValueError):
        registered_public_index_membership_refresh_reason(
            eligible_sources=sources, available_bindings=bindings, previous=(wrong, index)
        )


def test_index16_schema_mirror_and_original13_bytes_preserved():
    root = Path(__file__).resolve().parents[2]
    for name, digest in (
        ("embedding-batch-plan-v1.6.schema.json", BATCH_PLAN_V16_SCHEMA_SHA256),
        (
            "embedding-batch-plan-v1.3.schema.json",
            "sha256:472609d692c7a373d05ddac44ab0d3fc66f10d460b4566ab699182df476a3084",
        ),
    ):
        raw = (root / "schemas/workflow" / name).read_bytes()
        assert raw == (root / "packages/workflow/eom_workflow/resources" / name).read_bytes()
        assert sha256_bytes(raw) == digest


@pytest.mark.parametrize("fault", ["duplicate", "purpose", "extra", "hash", "foreign_profile"])
def test_index16_is_closed_and_keeps_exact_registered_anchor_proof(fault):
    selection, _request, _policy, _resolved = public_case()
    value = selection.model_dump(mode="json")
    value.update(
        schema_version=BATCH_PLAN_V16_PROTOCOL,
        anchors=[
            public_solution_reference_for_entry(e).model_dump(mode="json")
            for e in entries(parse_local_embedding_source_plan_v4(plan_value()))
        ],
    )
    checked = EmbeddingBatchSelectionV16.model_validate(seal(value, "selection_sha256"))
    body = deepcopy(checked.model_dump(mode="json"))
    if fault == "duplicate":
        body["anchors"].append(deepcopy(body["anchors"][0]))
    elif fault == "purpose":
        body["purpose"] = "REFERENCE_QUERY"
    elif fault == "extra":
        body["execute_as_admin"] = True
    elif fault == "foreign_profile":
        registered = next(
            anchor
            for anchor in body["anchors"]
            if anchor["evidence"]["kind"] == "ACCEPTED_REGISTERED_SOLUTION_ANALYSIS"
        )
        registered["profile"]["schema_ref"] = (
            "eom://schemas/knowledge/public-solution-embedding-entry/1.0"
        )
    body = seal(body, "selection_sha256")
    if fault == "hash":
        body["selection_sha256"] = "sha256:" + "0" * 64
    with pytest.raises(ValueError):
        EmbeddingBatchSelectionV16.model_validate(body)
