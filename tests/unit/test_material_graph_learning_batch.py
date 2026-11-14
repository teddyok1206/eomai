"""Bounded Material batches retain exact accepted/source gates and publication replay."""

from contextlib import nullcontext
from dataclasses import FrozenInstanceError
from types import SimpleNamespace as NS
from unittest.mock import Mock

import pytest
from eom_catalog_contracts import ApprovedItemKnowledgeSourceV2
from eom_catalog_service import material_graph_learning as owner
from eom_catalog_service.automatic_item_graph_publication_service import AutomaticItemGraphCandidate
from eom_catalog_service.knowledge_graph_publication_service import KnowledgeGraphPublicationError
from eom_catalog_service.material_learning_models import MaterialLearningTaskRecord
from eom_catalog_service.material_task_history import MaterialTaskHistory

ACTOR = "operator_" + "a" * 32
GRAPH = "graphrev_" + "b" * 32
NEXT_GRAPH = "graphrev_" + "c" * 32


def identity(prefix, number):
    return prefix + f"{number:032x}"


def case(monkeypatch, count=2, included=()):
    targets = tuple(
        owner.MaterialItemGraphPublicationTarget(
            identity("materialtask_", index),
            identity("analysisrun_", index),
            identity("itemrev_", index),
        )
        for index in range(1, count + 1)
    )
    tasks = {
        target.task_id: MaterialLearningTaskRecord(
            task_id=target.task_id,
            item_revision_id=target.item_revision_id,
            analysis_run_id=target.analysis_run_id,
        )
        for target in targets
    }
    analyses = {
        target.analysis_run_id: NS(
            analysis_run_id=target.analysis_run_id,
            source=ApprovedItemKnowledgeSourceV2(
                source_class="APPROVED_ITEM",
                item_id=identity("item_", index),
                item_revision_id=target.item_revision_id,
                artifact_member=dict(
                    artifact_id=identity("artifact_", index),
                    artifact_revision_id=identity("rev_", index),
                    member_path="assessment-item-content.json",
                    materialized_path="source/item.json",
                    sha256="sha256:" + "1" * 64,
                    bytes=100,
                    schema_ref="eom.assessment.item-content/1.0",
                    media_type="application/json",
                    logical_name="item.json",
                ),
            ),
        )
        for index, target in enumerate(targets, 1)
    }
    session = NS(
        scalars=Mock(side_effect=lambda _statement: tuple(reversed(tuple(tasks.values())))),
        get=Mock(side_effect=AssertionError("Material batch must not do scalar task lookups")),
    )
    service = object.__new__(owner.MaterialGraphLearningService)
    service.sessions = lambda: nullcontext(session)
    service.artifacts = Mock()
    service.sources = Mock()
    service._authorize_publication = Mock()
    service.publication = Mock()
    service.publication.current_structure_context.return_value = NS(
        graph_snapshot_revision_id=GRAPH,
        accepted_analysis_run_ids=tuple(targets[index].analysis_run_id for index in included),
    )

    def resolve(_session, run_ids):
        assert len(run_ids) <= 3
        return {key: NS(analysis=analyses[key]) for key in run_ids}

    service.publication.resolve_accepted_analyses.side_effect = resolve
    service.automatic = Mock()
    receipt = NS(graph_publication=NS(graph_snapshot=NS(graph_snapshot_revision_id=NEXT_GRAPH)))

    def publish(candidates, **kwargs):
        kwargs["analysis_validator"](
            session, tuple(analyses[candidate.analysis_run_id] for candidate in candidates)
        )
        return receipt

    service.automatic.publish.side_effect = publish
    resolver = Mock(side_effect=lambda *_args, task_id, **_kwargs: NS(work=NS(task_id=task_id)))
    monkeypatch.setattr(owner, "resolve_completed_material_task", resolver)
    histories = {key: MaterialTaskHistory((task,)) for key, task in tasks.items()}
    history_reader = Mock(
        side_effect=lambda _session, rows: {row.task_id: histories[row.task_id] for row in rows}
    )
    monkeypatch.setattr(owner, "read_material_task_histories", history_reader)
    return NS(**locals())


def test_target_is_a_small_frozen_value_without_mutable_attributes():
    target = owner.MaterialItemGraphPublicationTarget(
        identity("materialtask_", 1), identity("analysisrun_", 1), identity("itemrev_", 1)
    )
    assert not hasattr(target, "__dict__")
    with pytest.raises(FrozenInstanceError):
        target.task_id = identity("materialtask_", 2)


@pytest.mark.parametrize("attribute", ["task_id", "analysis_run_id", "item_revision_id"])
@pytest.mark.parametrize("invalid", ["", "unrelated_" + "1" * 32, 1])
def test_target_rejects_invalid_identity(attribute, invalid):
    fields = dict(
        task_id=identity("materialtask_", 1),
        analysis_run_id=identity("analysisrun_", 1),
        item_revision_id=identity("itemrev_", 1),
    )
    fields[attribute] = invalid
    with pytest.raises(ValueError, match="MATERIAL_GRAPH_ITEM_TARGET_INVALID"):
        owner.MaterialItemGraphPublicationTarget(**fields)


@pytest.mark.parametrize("count", [1, 2, 25])
def test_exact_batch_uses_one_shared_publication_and_bounded_accepted_reads(monkeypatch, count):
    value = case(monkeypatch, count)
    assert value.service.publish_items(targets=value.targets, operator_id=ACTOR) == NEXT_GRAPH
    value.service.automatic.publish.assert_called_once()
    call = value.service.automatic.publish.call_args
    assert call.args == (
        tuple(AutomaticItemGraphCandidate(t.analysis_run_id, ACTOR, GRAPH) for t in value.targets),
    )
    assert call.kwargs["required_source_class"] == "APPROVED_ITEM"
    assert call.kwargs["retrieval_idempotency_namespace"] == "material-item-align"
    assert call.kwargs["publication_idempotency_namespace"] == "material-item-graph"
    reads = value.service.publication.resolve_accepted_analyses.call_args_list
    assert len(reads) == (count + 2) // 3
    assert tuple(key for read in reads for key in read.args[1]) == tuple(
        target.analysis_run_id for target in value.targets
    )
    assert value.resolver.call_count == value.service.sources.reauthorize.call_count == count * 2
    assert value.history_reader.call_count == 2
    assert value.session.scalars.call_count == 2
    value.session.get.assert_not_called()
    for read in value.session.scalars.call_args_list:
        statement = read.args[0]
        assert statement.get_execution_options()["populate_existing"] is True
        assert statement.compile().params == {
            "task_id_1": [target.task_id for target in value.targets]
        }
    for read in value.history_reader.call_args_list:
        assert tuple(task.task_id for task in read.args[1]) == tuple(
            target.task_id for target in value.targets
        )


@pytest.mark.parametrize("kind", ["empty", "too_many", "list", "wrong_type"])
def test_invalid_batch_is_rejected_before_io(monkeypatch, kind):
    value = case(monkeypatch, 26)
    targets = {
        "empty": (),
        "too_many": value.targets,
        "list": list(value.targets[:1]),
        "wrong_type": (NS(),),
    }[kind]
    with pytest.raises(ValueError, match="MATERIAL_GRAPH_ITEM_TARGETS_INVALID"):
        value.service.publish_items(targets=targets, operator_id=ACTOR)
    value.service.publication.current_structure_context.assert_not_called()
    value.resolver.assert_not_called()


@pytest.mark.parametrize("attribute", ["task_id", "analysis_run_id", "item_revision_id"])
def test_duplicate_identity_is_rejected_before_io(monkeypatch, attribute):
    value = case(monkeypatch)
    fields = {
        field: getattr(value.targets[1], field)
        for field in ("task_id", "analysis_run_id", "item_revision_id")
    }
    fields[attribute] = getattr(value.targets[0], attribute)
    duplicate = owner.MaterialItemGraphPublicationTarget(**fields)
    with pytest.raises(ValueError, match="MATERIAL_GRAPH_ITEM_TARGETS_INVALID"):
        value.service.publish_items(targets=(value.targets[0], duplicate), operator_id=ACTOR)
    value.service.publication.current_structure_context.assert_not_called()


def test_single_api_delegates_to_the_same_exact_batch_owner(monkeypatch):
    value = case(monkeypatch, 1)
    value.service.publish_items = Mock(return_value=NEXT_GRAPH)
    target = value.targets[0]
    assert (
        value.service.publish_item(
            task_id=target.task_id,
            analysis_run_id=target.analysis_run_id,
            item_revision_id=target.item_revision_id,
            operator_id=ACTOR,
        )
        == NEXT_GRAPH
    )
    value.service.publish_items.assert_called_once_with(targets=value.targets, operator_id=ACTOR)


def test_all_membership_replay_reauthorizes_every_source_without_publishing(monkeypatch):
    value = case(monkeypatch, 3, included=(0, 1, 2))
    assert value.service.publish_items(targets=value.targets, operator_id=ACTOR) == GRAPH
    assert value.resolver.call_count == value.service.sources.reauthorize.call_count == 3
    value.service.automatic.publish.assert_not_called()


def test_partial_membership_publishes_only_pending_but_reauthorizes_all(monkeypatch):
    value = case(monkeypatch, 3, included=(0,))
    assert value.service.publish_items(targets=value.targets, operator_id=ACTOR) == NEXT_GRAPH
    candidates = value.service.automatic.publish.call_args.args[0]
    assert tuple(row.analysis_run_id for row in candidates) == tuple(
        target.analysis_run_id for target in value.targets[1:]
    )
    assert value.resolver.call_count == value.service.sources.reauthorize.call_count == 6


@pytest.mark.parametrize("fault", ["wrong_item", "wrong_base", "missing_task", "no_base"])
def test_current_task_and_effective_analysis_pin_must_match(monkeypatch, fault):
    value = case(monkeypatch, 1)
    task = value.tasks[value.targets[0].task_id]
    if fault == "wrong_item":
        task.item_revision_id = identity("itemrev_", 20)
    elif fault == "wrong_base":
        task.analysis_run_id = identity("analysisrun_", 20)
    elif fault == "missing_task":
        value.tasks.clear()
    else:
        task.analysis_run_id = None
    with pytest.raises(ValueError, match="MATERIAL_GRAPH_ITEM_SOURCE_MISMATCH"):
        value.service.publish_items(targets=value.targets, operator_id=ACTOR)
    value.service.automatic.publish.assert_not_called()


def test_exact_inherited_analysis_pin_is_reused_without_new_report(monkeypatch):
    value = case(monkeypatch, 1)
    target = value.targets[0]
    task = value.tasks[target.task_id]
    task.analysis_run_id = None
    prior = MaterialLearningTaskRecord(
        task_id=identity("materialtask_", 20),
        item_revision_id=target.item_revision_id,
        analysis_run_id=target.analysis_run_id,
    )
    value.histories[target.task_id] = MaterialTaskHistory((task, prior))
    assert value.service.publish_items(targets=value.targets, operator_id=ACTOR) == NEXT_GRAPH


@pytest.mark.parametrize("fault", ["wrong_revision", "wrong_class", "untyped_source"])
def test_accepted_source_is_exactly_the_requested_approved_item(monkeypatch, fault):
    value = case(monkeypatch, 1)
    analysis = value.analyses[value.targets[0].analysis_run_id]
    if fault == "wrong_revision":
        analysis.source = analysis.source.model_copy(
            update={"item_revision_id": identity("itemrev_", 20)}
        )
    elif fault == "wrong_class":
        analysis.source = analysis.source.model_copy(update={"source_class": "PAST_EXAM"})
    else:
        analysis.source = NS(
            item_revision_id=value.targets[0].item_revision_id, source_class="APPROVED_ITEM"
        )
    with pytest.raises(ValueError, match="MATERIAL_GRAPH_ITEM_SOURCE_MISMATCH"):
        value.service.publish_items(targets=value.targets, operator_id=ACTOR)
    value.service.automatic.publish.assert_not_called()


def test_replay_does_not_bypass_operator_permission_or_source_revocation(monkeypatch):
    value = case(monkeypatch, 1, included=(0,))
    value.service._authorize_publication.side_effect = ValueError("MATERIAL_PERMISSION_DENIED")
    with pytest.raises(ValueError, match="MATERIAL_PERMISSION_DENIED"):
        value.service.publish_items(targets=value.targets, operator_id=ACTOR)
    value.service._authorize_publication.side_effect = None
    value.service.sources.reauthorize.side_effect = ValueError("MATERIAL_SOURCE_REVOKED")
    with pytest.raises(ValueError, match="MATERIAL_SOURCE_REVOKED"):
        value.service.publish_items(targets=value.targets, operator_id=ACTOR)
    value.service.automatic.publish.assert_not_called()


def test_final_pending_validator_rechecks_an_already_member_source(monkeypatch):
    value = case(monkeypatch, 2, included=(0,))

    def publish(candidates, **kwargs):
        def reauthorize(_session, *, operator_id, work):
            assert operator_id == ACTOR
            if work.task_id == value.targets[0].task_id:
                raise ValueError("MATERIAL_SOURCE_REVOKED")

        value.service.sources.reauthorize.side_effect = reauthorize
        kwargs["analysis_validator"](
            value.session, tuple(value.analyses[c.analysis_run_id] for c in candidates)
        )
        return value.receipt

    value.service.automatic.publish.side_effect = publish
    with pytest.raises(ValueError, match="MATERIAL_SOURCE_REVOKED"):
        value.service.publish_items(targets=value.targets, operator_id=ACTOR)


@pytest.mark.parametrize("fault", ["missing", "duplicate", "already_included", "swapped_item"])
def test_final_callback_requires_the_exact_pending_analysis_set(monkeypatch, fault):
    value = case(monkeypatch, 3, included=(0,))

    def publish(_candidates, **kwargs):
        pending = tuple(value.analyses[t.analysis_run_id] for t in value.targets[1:])
        if fault == "missing":
            provided = pending[:1]
        elif fault == "duplicate":
            provided = (pending[0], pending[0])
        elif fault == "already_included":
            provided = (value.analyses[value.targets[0].analysis_run_id], *pending)
        else:
            provided = (
                NS(analysis_run_id=pending[0].analysis_run_id, source=pending[1].source),
                pending[1],
            )
        kwargs["analysis_validator"](value.session, provided)
        return value.receipt

    value.service.automatic.publish.side_effect = publish
    with pytest.raises(ValueError, match="MATERIAL_GRAPH_ITEM_SOURCE_MISMATCH"):
        value.service.publish_items(targets=value.targets, operator_id=ACTOR)


def test_cas_retry_uses_the_new_exact_context_and_only_remaining_candidates(monkeypatch):
    value = case(monkeypatch, 2)
    value.service.publication.current_structure_context.side_effect = [
        NS(graph_snapshot_revision_id=GRAPH, accepted_analysis_run_ids=()),
        NS(
            graph_snapshot_revision_id=NEXT_GRAPH,
            accepted_analysis_run_ids=(value.targets[0].analysis_run_id,),
        ),
    ]
    real_publish = value.publish
    calls = []

    def publish(candidates, **kwargs):
        calls.append(candidates)
        if len(calls) == 1:
            raise KnowledgeGraphPublicationError("KNOWLEDGE_GRAPH_STALE_CURRENT", "raced")
        return real_publish(candidates, **kwargs)

    value.service.automatic.publish.side_effect = publish
    assert value.service.publish_items(targets=value.targets, operator_id=ACTOR) == NEXT_GRAPH
    assert len(calls) == 2
    assert calls[1] == (
        AutomaticItemGraphCandidate(value.targets[1].analysis_run_id, ACTOR, NEXT_GRAPH),
    )
    assert value.resolver.call_count == 6


def test_cas_retry_that_finds_all_members_does_not_republish(monkeypatch):
    value = case(monkeypatch, 1)
    value.service.publication.current_structure_context.side_effect = [
        NS(graph_snapshot_revision_id=GRAPH, accepted_analysis_run_ids=()),
        NS(
            graph_snapshot_revision_id=NEXT_GRAPH,
            accepted_analysis_run_ids=(value.targets[0].analysis_run_id,),
        ),
    ]
    value.service.automatic.publish.side_effect = KnowledgeGraphPublicationError(
        "KNOWLEDGE_GRAPH_STALE_CURRENT", "raced"
    )
    assert value.service.publish_items(targets=value.targets, operator_id=ACTOR) == NEXT_GRAPH
    value.service.automatic.publish.assert_called_once()
    assert value.resolver.call_count == 2


@pytest.mark.parametrize("stale", [True, False])
def test_only_cas_failures_retry_and_the_bound_stays_three(monkeypatch, stale):
    value = case(monkeypatch, 1)
    code = "KNOWLEDGE_GRAPH_STALE_CURRENT" if stale else "KNOWLEDGE_GRAPH_SOURCE_REVOKED"
    value.service.automatic.publish.side_effect = KnowledgeGraphPublicationError(code, "failure")
    with pytest.raises(
        ValueError if stale else KnowledgeGraphPublicationError,
        match="MATERIAL_GRAPH_PUBLICATION_BUSY" if stale else "failure",
    ):
        value.service.publish_items(targets=value.targets, operator_id=ACTOR)
    assert value.service.automatic.publish.call_count == (3 if stale else 1)
