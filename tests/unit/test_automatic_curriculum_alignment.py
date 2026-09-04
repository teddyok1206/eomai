from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import Mock

import pytest
from eom_catalog_service.automatic_curriculum_alignment import (
    AUTOMATIC_ITEM_ALIGNMENT_EVIDENCE_BUDGET,
    AUTOMATIC_ITEM_ALIGNMENT_POLICY_SHA256,
    AutomaticCurriculumAlignmentError,
    automatic_item_alignment_topic_keys,
    derive_automatic_item_curriculum_unit_ids,
)
from eom_catalog_service.knowledge_graph_publication_service import (
    CurrentKnowledgeGraphStructure,
    KnowledgeGraphPublicationError,
    KnowledgeGraphPublicationService,
)
from eom_catalog_service.legacy_item_graph_learning_service import (
    LegacyItemGraphCandidate,
    LegacyItemGraphLearningService,
)


def test_topic_selection_is_deduplicated_bounded_and_excludes_item_nodes() -> None:
    nodes = [
        ("ITEM_REVISION", "item.revision"),
        ("CONCEPT", "topic.beta"),
        ("CONCEPT", "topic.alpha"),
        ("CLAIM", "topic.alpha"),
        ("ASSESSMENT_PATTERN", "pattern.choice"),
    ]

    assert automatic_item_alignment_topic_keys(nodes) == ("topic.alpha", "topic.beta")


def test_topic_selection_falls_back_to_semantic_item_nodes() -> None:
    assert automatic_item_alignment_topic_keys(
        (
            ("ITEM_REVISION", "item_revision:ignored"),
            ("ITEM_ELEMENT", "item_element:spectral-stimulus"),
            ("ASSESSMENT_PATTERN", "assessment_pattern:comparison"),
        )
    ) == (
        "assessment_pattern:comparison",
        "item_element:spectral-stimulus",
    )


def test_topic_selection_uses_item_revision_as_the_last_resort() -> None:
    assert automatic_item_alignment_topic_keys(
        (("ITEM_REVISION", "item_revision:genetics-abo-item-16"),)
    ) == ("item_revision:genetics-abo-item-16",)


def test_topic_selection_rejects_proposals_without_nodes() -> None:
    with pytest.raises(AutomaticCurriculumAlignmentError, match="no controlled topic"):
        automatic_item_alignment_topic_keys(())


def test_alignment_walk_is_multi_source_bounded_and_returns_minor_units() -> None:
    first_seed = "knode_" + "1" * 32
    second_seed = "knode_" + "2" * 32
    shared = "knode_" + "3" * 32
    second_hop = "knode_" + "4" * 32
    first_unit_id = "currunit_" + "a" * 32
    second_unit_id = "currunit_" + "b" * 32
    session = Mock()
    session.scalars.side_effect = [
        (first_seed, second_seed),
        (),
        (SimpleNamespace(curriculum_unit_id=first_unit_id, node_id=shared),),
        (SimpleNamespace(curriculum_unit_id=second_unit_id, node_id=second_hop),),
        (),
    ]
    session.execute.side_effect = [
        ((first_seed, shared), (second_seed, shared)),
        ((shared, second_hop),),
        (),
    ]

    result = derive_automatic_item_curriculum_unit_ids(
        session,
        graph_snapshot_revision_id="graphrev_" + "9" * 32,
        evidence_node_ids=(first_seed, second_seed),
    )

    assert result == (first_unit_id, second_unit_id)
    assert session.execute.call_count == 3


def test_alignment_walk_rejects_dangling_evidence_nodes() -> None:
    evidence_node_id = "knode_" + "1" * 32
    session = Mock()
    session.scalars.return_value = ()

    with pytest.raises(AutomaticCurriculumAlignmentError, match="do not resolve"):
        derive_automatic_item_curriculum_unit_ids(
            session,
            graph_snapshot_revision_id="graphrev_" + "9" * 32,
            evidence_node_ids=(evidence_node_id,),
        )


def test_legacy_graph_retrieval_command_pins_policy_snapshot_and_budget() -> None:
    service = object.__new__(LegacyItemGraphLearningService)
    service.access_policy_revision_id = "accessrev_" + "a" * 32
    context = CurrentKnowledgeGraphStructure(
        corpus_key="integrated-science-textbooks",
        display_name="통합과학 지식 그래프",
        graph_snapshot_revision_id="graphrev_" + "b" * 32,
        accepted_analysis_run_ids=(),
        structure=cast(Any, object()),
    )
    candidate = LegacyItemGraphCandidate(
        analysis_run_id="analysisrun_" + "c" * 32,
        requested_by_operator_id="operator_" + "d" * 32,
        graph_snapshot_revision_id=context.graph_snapshot_revision_id,
    )

    command = service._retrieval_command(
        context=context,
        candidate=candidate,
        topic_keys=("claim.energy", "concept.energy"),
    )
    replay = service._retrieval_command(
        context=context,
        candidate=candidate,
        topic_keys=("claim.energy", "concept.energy"),
    )

    assert command == replay
    assert command.graph_snapshot_revision_id == context.graph_snapshot_revision_id
    assert command.access_policy_revision_id == service.access_policy_revision_id
    assert command.evidence_budget.model_dump(mode="json") == (
        AUTOMATIC_ITEM_ALIGNMENT_EVIDENCE_BUDGET
    )
    assert AUTOMATIC_ITEM_ALIGNMENT_POLICY_SHA256.startswith("sha256:")


def test_legacy_graph_retrieval_rejects_a_stale_candidate_before_writing_evidence() -> None:
    service = object.__new__(LegacyItemGraphLearningService)
    service.access_policy_revision_id = "accessrev_" + "a" * 32
    context = CurrentKnowledgeGraphStructure(
        corpus_key="integrated-science-textbooks",
        display_name="통합과학 지식 그래프",
        graph_snapshot_revision_id="graphrev_" + "b" * 32,
        accepted_analysis_run_ids=(),
        structure=cast(Any, object()),
    )
    stale = LegacyItemGraphCandidate(
        analysis_run_id="analysisrun_" + "c" * 32,
        requested_by_operator_id="operator_" + "d" * 32,
        graph_snapshot_revision_id="graphrev_" + "e" * 32,
    )

    with pytest.raises(ValueError, match="stale"):
        service._retrieval_command(
            context=context,
            candidate=stale,
            topic_keys=("concept.energy",),
        )


def test_graph_snapshot_ancestry_accepts_a_contiguous_immutable_chain() -> None:
    first = "graphrev_" + "1" * 32
    second = "graphrev_" + "2" * 32
    third = "graphrev_" + "3" * 32
    snapshots = {
        first: SimpleNamespace(
            state="PUBLISHED",
            graph_id="graph_" + "a" * 32,
            revision_number=1,
            previous_graph_snapshot_revision_id=None,
        ),
        second: SimpleNamespace(
            state="PUBLISHED",
            graph_id="graph_" + "a" * 32,
            revision_number=2,
            previous_graph_snapshot_revision_id=first,
        ),
        third: SimpleNamespace(
            state="PUBLISHED",
            graph_id="graph_" + "a" * 32,
            revision_number=3,
            previous_graph_snapshot_revision_id=second,
        ),
    }
    session = Mock()
    session.get.side_effect = lambda _model, revision_id: snapshots.get(revision_id)

    assert KnowledgeGraphPublicationService._snapshot_ancestor_ids(session, third) == frozenset(
        snapshots
    )


def test_graph_snapshot_ancestry_rejects_a_revision_gap() -> None:
    first = "graphrev_" + "1" * 32
    third = "graphrev_" + "3" * 32
    snapshots = {
        first: SimpleNamespace(
            state="PUBLISHED",
            graph_id="graph_" + "a" * 32,
            revision_number=1,
            previous_graph_snapshot_revision_id=None,
        ),
        third: SimpleNamespace(
            state="PUBLISHED",
            graph_id="graph_" + "a" * 32,
            revision_number=3,
            previous_graph_snapshot_revision_id=first,
        ),
    }
    session = Mock()
    session.get.side_effect = lambda _model, revision_id: snapshots.get(revision_id)

    with pytest.raises(KnowledgeGraphPublicationError, match="non-contiguous"):
        KnowledgeGraphPublicationService._snapshot_ancestor_ids(session, third)
