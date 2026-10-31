"""The new source adapter composes existing authority, not worker-supplied grants."""

from types import SimpleNamespace as NS
from unittest.mock import Mock

import pytest
from eom_catalog_contracts.knowledge import ApprovedItemKnowledgeSourceV2
from eom_catalog_service import public_solution_source_capture as capture_module
from eom_catalog_service.creative_registered_report import RegisteredCreativeReport
from eom_catalog_service.creative_report_batch import CapturedRegisteredCreativeReport
from eom_catalog_service.public_solution_source_capture import CatalogPublicSolutionSourceCapture
from eom_catalog_service.solution_embedding_projection import project_public_solution_text
from eom_identifiers import canonical_json_bytes

from tests.unit.inference_transfer_fixtures import profile, report
from tests.unit.test_creative_registered_report import proposal
from tests.unit.test_public_solution_encoding import public_entry, public_recipe


def capture_case(monkeypatch, *, creative=False):
    basis = profile().source_basis
    source = basis.source
    original_report = report()
    registered = None
    if creative:
        resolved, lineage = proposal()
        value = source.model_dump(mode="json")
        value["source_class"] = "APPROVED_ITEM"
        value["artifact_member"]["sha256"] = lineage.registered_content_sha256
        source = ApprovedItemKnowledgeSourceV2.model_validate(value)
        original_report = resolved.role.output.learning_result
        registered = CapturedRegisteredCreativeReport(
            RegisteredCreativeReport(lineage, resolved),
            public_entry(creative=True).evidence.lineage,
        )
    candidate = NS(source=source, analysis_run_id=basis.solution_evidence.base_analysis_run_id)
    pool = NS(candidates=(candidate,), graph_snapshot=basis.graph_snapshot)
    scope = NS(
        access_policy_revision_id="accessrev_" + "a" * 32, access_policy_sha256="sha256:" + "b" * 64
    )
    session, fence, reader, command = Mock(), Mock(), Mock(), Mock()
    revision = NS(
        item_id=source.item_id,
        item_revision_id=source.item_revision_id,
        revision_state="APPROVED",
        metadata_json={"source_kind": "CREATIVE" if creative else "PAST_EXAM"},
    )
    session.scalars.return_value = (revision,)
    owner = object.__new__(CatalogPublicSolutionSourceCapture)
    owner.sources, owner.artifacts = Mock(), Mock()
    owner.sources.capture_public_solution_pool_in_session.return_value = scope, pool
    owner.sources.authorize_scope_in_session.return_value = scope
    solutions = Mock(
        return_value={}
        if creative
        else {
            candidate.analysis_run_id: NS(
                source=source, report=original_report, pointer=basis.solution_evidence
            )
        }
    )
    batches = Mock(return_value={source.item_revision_id: registered})
    monkeypatch.setattr(capture_module, "resolve_solution_evidence_by_base_run", solutions)
    monkeypatch.setattr(capture_module, "load_registered_creative_reports", batches)
    lineage_reader = Mock()
    reader_factory = Mock(return_value=lineage_reader)
    monkeypatch.setattr(capture_module, "PinnedArtifactReadContext", reader_factory)
    return NS(**locals())


def run(value):
    return value.owner.capture_in_session(
        value.session,
        value.command,
        public_recipe(),
        identity_fence=value.fence,
        artifact_reader=value.reader,
    )


@pytest.mark.parametrize("creative", [False, True])
def test_both_families_use_real_pool_pins_and_keep_original_public_content(monkeypatch, creative):
    value = capture_case(monkeypatch, creative=creative)
    before = canonical_json_bytes(value.original_report)
    result = run(value)
    assert result.source_revision_ids == (value.source.item_revision_id,)
    assert result.missing_report_revision_ids == () and len(result.entries) == 1
    entry = result.entries[0]
    assert entry.public_solution == project_public_solution_text(value.original_report)
    assert (
        entry.source == value.source
        and entry.base_analysis_run_id == value.candidate.analysis_run_id
    )
    assert entry.graph_snapshot == value.pool.graph_snapshot
    assert entry.policy_revision_id == value.scope.access_policy_revision_id
    assert entry.evidence.kind == (
        "REGISTERED_CREATIVE_SOURCE_REPORT" if creative else "ACCEPTED_SOLUTION_ANALYSIS"
    )
    assert canonical_json_bytes(value.original_report) == before
    value.reader.revalidate_provenance.assert_called_once()
    assert (
        value.owner.sources.authorize_scope_in_session.call_args.kwargs["identity_fence"]
        is value.fence
    )
    assert (
        value.owner.sources.capture_public_solution_pool_in_session.call_args.kwargs[
            "artifact_reader"
        ]
        is value.reader
    )
    if creative:
        value.batches.assert_called_once()
        value.reader_factory.assert_called_once_with(value.session, value.reader.settings)
        assert value.batches.call_args.kwargs["artifact_reader"] is value.lineage_reader
        value.lineage_reader.revalidate_provenance.assert_called_once()
    else:
        value.batches.assert_not_called()


def test_missing_ai_or_past_report_is_missing_not_editorial_or_review_fallback(monkeypatch):
    value = capture_case(monkeypatch)
    value.solutions.return_value = {}
    result = run(value)
    assert result.entries == () and result.missing_report_revision_ids == (
        value.source.item_revision_id,
    )
    value.batches.assert_not_called()


@pytest.mark.parametrize("source_kind", ["AI", "AI_GENERATED", "GENERATED"])
def test_ai_full_report_uses_the_same_public_encoder_text_as_past_exam(monkeypatch, source_kind):
    value = capture_case(monkeypatch)
    past = run(value).entries[0]
    source = ApprovedItemKnowledgeSourceV2.model_validate(
        value.source.model_dump(mode="json") | {"source_class": "APPROVED_ITEM"}
    )
    value.candidate.source = source
    value.revision.metadata_json = {"source_kind": source_kind}
    value.solutions.return_value[value.candidate.analysis_run_id].source = source
    ai = run(value).entries[0]
    assert ai.source.source_class == "APPROVED_ITEM"
    assert past.source.source_class == "PAST_EXAM"
    assert ai.public_solution == past.public_solution
    assert ai.recipe == past.recipe
    assert ai.evidence.kind == "ACCEPTED_SOLUTION_ANALYSIS"
    assert ai.entry_sha256 != past.entry_sha256
    value.batches.assert_not_called()


@pytest.mark.parametrize("change", ["revoked", "different_item", "missing", "duplicate"])
def test_current_source_eligibility_is_not_inferred_from_a_typed_candidate(monkeypatch, change):
    value = capture_case(monkeypatch)
    if change == "revoked":
        value.revision.revision_state = "REJECTED"
    elif change == "different_item":
        value.revision.item_id = "eom-item_" + "f" * 32
    elif change == "missing":
        value.session.scalars.return_value = ()
    else:
        value.pool.candidates *= 2
    with pytest.raises(ValueError, match="SOURCE_SET_INVALID"):
        run(value)


def test_actor_or_policy_change_after_materialization_aborts_capture(monkeypatch):
    value = capture_case(monkeypatch)
    value.owner.sources.authorize_scope_in_session.return_value = NS(
        access_policy_revision_id="changed"
    )
    with pytest.raises(ValueError, match="AUTHORITY_CHANGED"):
        run(value)


def test_creative_registered_content_hash_must_match_the_actual_graph_source(monkeypatch):
    value = capture_case(monkeypatch, creative=True)
    changed = value.source.model_dump(mode="json")
    changed["artifact_member"]["sha256"] = "sha256:" + "f" * 64
    value.candidate.source = ApprovedItemKnowledgeSourceV2.model_validate(changed)
    with pytest.raises(ValueError, match="SOURCE_POINTER_MISMATCH"):
        run(value)
