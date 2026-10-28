"""Historical curriculum review survives account retirement without new authority."""

from types import SimpleNamespace as NS
from unittest.mock import Mock

import pytest
from eom_catalog_service.curriculum_graph_structure import (
    CurriculumGraphStructureError,
    build_integrated_science_structure_manifest,
    extend_integrated_science_structure_manifest_with_automatic_item_alignments,
    validate_inherited_automatic_structure_review,
)
from eom_catalog_service.knowledge_graph_publication_service import (
    KnowledgeGraphPublicationError,
    KnowledgeGraphPublicationService,
)
from eom_catalog_service.knowledge_retrieval_service import (
    KnowledgeRetrievalApplicationService,
    KnowledgeRetrievalServiceError,
)
from eom_identifiers import content_sha256

from tests.unit.test_curriculum_graph_structure import (
    NOW,
    OPERATOR_ID,
    _approved_item_analysis,
    _automatic_item_alignment,
    _complete_analyses,
)


def extension():
    base = build_integrated_science_structure_manifest(
        _complete_analyses(), reviewed_by_operator_id=OPERATOR_ID, created_at=NOW
    )
    unit = next(
        unit.curriculum_unit_id for unit in base.curriculum_units if unit.unit_level == "MINOR"
    )
    binding = _automatic_item_alignment(_approved_item_analysis(), unit)
    candidate = extend_integrated_science_structure_manifest_with_automatic_item_alignments(
        base, (binding,), created_at=NOW
    )
    return base, candidate, binding.prior_graph_snapshot_revision_id


def test_inherited_review_preserves_exact_outline_and_old_reviewer():
    base, candidate, snapshot_id = extension()
    validate_inherited_automatic_structure_review(
        base, candidate, base_snapshot_revision_id=snapshot_id
    )
    assert candidate.reviewed_by_operator_id == base.reviewed_by_operator_id
    assert candidate.curriculum_units == base.curriculum_units
    assert candidate.analysis_curriculum_bindings == base.analysis_curriculum_bindings


@pytest.mark.parametrize(
    "field,value",
    [
        ("reviewed_by_operator_id", "operator_" + "f" * 32),
        ("outline_sha256", "sha256:" + "f" * 64),
    ],
)
def test_modified_review_or_outline_is_not_grandfathered(field, value):
    base, candidate, snapshot_id = extension()
    document = candidate.model_dump(mode="json")
    document[field] = value
    document["manifest_sha256"] = content_sha256(
        {k: v for k, v in document.items() if k != "manifest_sha256"}
    )
    changed = type(candidate).model_validate(document)
    with pytest.raises(CurriculumGraphStructureError):
        validate_inherited_automatic_structure_review(
            base, changed, base_snapshot_revision_id=snapshot_id
        )


def test_different_base_snapshot_cannot_satisfy_inherited_review():
    base, candidate, _ = extension()
    with pytest.raises(CurriculumGraphStructureError, match="different base"):
        validate_inherited_automatic_structure_review(
            base, candidate, base_snapshot_revision_id="graphrev_" + "f" * 32
        )


@pytest.mark.parametrize("operator", [None, NS(status="DISABLED")])
def test_retired_reviewer_reuses_only_exact_pinned_published_base(operator):
    base, candidate, snapshot_id = extension()
    service = object.__new__(KnowledgeGraphPublicationService)
    service.structure_context_for_snapshot = Mock(return_value=NS(structure=base))
    session = Mock()
    session.get.return_value = operator
    service._require_structure_review(session, candidate, snapshot_id)
    service.structure_context_for_snapshot.assert_called_once_with(snapshot_id)
    session.add.assert_not_called()
    with pytest.raises(KnowledgeGraphPublicationError, match="absent or inactive"):
        service._require_structure_review(session, candidate, None)


def test_existing_active_reviewer_path_needs_no_historical_lookup():
    _, candidate, _ = extension()
    service = object.__new__(KnowledgeGraphPublicationService)
    service.structure_context_for_snapshot = Mock()
    session = Mock()
    session.get.return_value = NS(status="ACTIVE")
    service._require_structure_review(session, candidate, None)
    service.structure_context_for_snapshot.assert_not_called()


def test_published_alignment_membership_is_exact_and_read_once_per_publication():
    _, candidate, snapshot_id = extension()
    service = object.__new__(KnowledgeGraphPublicationService)
    service.structure_context_for_snapshot = Mock(return_value=NS(structure=candidate))
    contains = service._published_alignment_membership_checker(snapshot_id)
    binding = candidate.automatic_item_curriculum_bindings[0]
    assert contains(binding.alignment_sha256)
    assert not contains("sha256:" + "f" * 64)
    assert contains(binding.alignment_sha256)
    service.structure_context_for_snapshot.assert_called_once_with(snapshot_id)


@pytest.mark.parametrize("inherited", [False, True])
def test_retired_alignment_requester_needs_published_proof_and_does_not_skip_evidence(inherited):
    from eom_identity_service.models import OperatorRecord

    _, candidate, snapshot_id = extension()
    service = object.__new__(KnowledgeGraphPublicationService)
    service.structure_context_for_snapshot = Mock(return_value=NS(structure=candidate))
    session = Mock()
    session.get.side_effect = lambda model, _identity: (
        NS(status="DISABLED") if model is OperatorRecord else None
    )
    session.scalars.return_value = ()
    contains = service._published_alignment_membership_checker(snapshot_id) if inherited else None
    with pytest.raises(KnowledgeGraphPublicationError) as caught:
        service._validate_automatic_item_curriculum_bindings(
            session,
            candidate,
            (_approved_item_analysis(),),
            expected_snapshot_revision_id=snapshot_id,
            ancestor_snapshot_ids=frozenset({snapshot_id}),
            inherited_binding=contains,
        )
    assert caught.value.code == (
        "KNOWLEDGE_GRAPH_AUTOMATIC_ALIGNMENT_EVIDENCE_INVALID"
        if inherited
        else "KNOWLEDGE_GRAPH_AUTOMATIC_ALIGNMENT_SOURCE_INVALID"
    )


def test_policy_metadata_preflight_rejects_a_different_policy_family():
    from contextlib import nullcontext

    service = object.__new__(KnowledgeRetrievalApplicationService)
    session = Mock()
    session.get.return_value = NS(
        state="RELEASED", canonical_document={"schema_version": "mixed/1.0"}
    )
    service.sessions = lambda: nullcontext(session)
    with pytest.raises(KnowledgeRetrievalServiceError, match="document is invalid"):
        service.read_released_access_policy("accessrev_" + "a" * 32)
    session.add.assert_not_called()
