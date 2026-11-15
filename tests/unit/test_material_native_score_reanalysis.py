"""Exact repair proofs and lineage are closed values, not runtime authority."""

from copy import deepcopy
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from eom_catalog_contracts.material_item_lineage import (
    MaterialItemLineageV4,
    parse_material_item_lineage,
)
from eom_catalog_contracts.material_learning import MaterialArtifactMember
from eom_catalog_contracts.material_native_score_reanalysis import (
    NATIVE_SCORE_REANALYSIS_MEMBER,
    NATIVE_SCORE_REANALYSIS_REF,
    NativeScoreReanalysisTarget,
    ReanalyzeNativeMaterialScoresCommand,
    native_score_reanalysis_run_id,
    native_score_reanalysis_target_key,
)
from eom_catalog_contracts.validation import validate_contract
from eom_catalog_service import material_item_registration as registration
from eom_catalog_service import material_native_score_reanalysis as score_owner
from eom_catalog_service.material_native_score_reanalysis import ResolvedNativeScoreTarget
from eom_identifiers import content_sha256
from jsonschema import ValidationError as SchemaError

from tests.unit.test_material_item_registration_versions import resolved_case
from tests.unit.test_material_learning_contracts import member, rehash
from tests.unit.test_material_native_files import MaterialNativeItemBinding, binding_data
from tests.unit.test_material_native_score import Reader, bound_question, package, section


def command():
    return ReanalyzeNativeMaterialScoresCommand(
        actor_id="operator_" + "a" * 32,
        idempotency_key="native-score-proof-test-001",
        run_id="materialrun_" + "b" * 32,
        expected_updated_at=datetime(2026, 11, 15, tzinfo=UTC),
    )


def target_data(request=None):
    request = request or command()
    binding = binding_data()
    work = member("material/work.json", "application/json", "material-learning/extraction-work/1.0")
    result = {
        key: value
        for key, value in member("result.json", "application/json").items()
        if key != "bytes"
    }
    result["schema_ref"] = "material-learning-result@2.0"
    content = deepcopy(result)
    content.update(
        schema_ref="eom.assessment.item-content/1.0", member_path="assessment-item-content.json"
    )
    return rehash(
        dict(
            schema_version="material-native-score-reanalysis-target/1.0",
            command=request.model_dump(mode="json"),
            material_id=binding["material_id"],
            material_revision_id=binding["material_revision_id"],
            successor_run_id=native_score_reanalysis_run_id(request),
            prepared=member(
                "prepared.json", "application/json", "material-learning/native-visual-prepared/3.0"
            ),
            source_tasks_sha256="sha256:" + "c" * 64,
            source_task_id="materialtask_" + "d" * 32,
            unit_key=binding["unit_key"],
            native_binding_sha256=binding["binding_sha256"],
            question=binding["question"]["document"],
            expected_score=dict(state="PRINTED", points="1.5"),
            source_work=work,
            source_result=result,
            prior_item=dict(
                item_id="item_" + "e" * 32,
                item_revision_id="itemrev_" + "f" * 32,
                manifest_sha256="sha256:" + "e" * 64,
                content=content,
                points=0,
            ),
            reason="REGISTERED_SCORE_MISMATCH",
        ),
        "target_sha256",
    )


def resolved_target(request=None):
    target = NativeScoreReanalysisTarget.model_validate(target_data(request))
    pointer = member(NATIVE_SCORE_REANALYSIS_MEMBER, "application/json")
    pointer["schema_ref"] = NATIVE_SCORE_REANALYSIS_REF
    return ResolvedNativeScoreTarget(target, MaterialArtifactMember.model_validate(pointer))


def test_exact_repair_command_and_target_validate_both_schema_and_models():
    request = command()
    value = target_data(request)
    validate_contract("material-native-score-reanalysis-v1", value)
    target = NativeScoreReanalysisTarget.model_validate(value)
    assert target.expected_score.points == "1.5"
    assert target.target_sha256 == content_sha256(
        target.model_dump(mode="json", exclude={"target_sha256"})
    )
    assert native_score_reanalysis_run_id(request) == native_score_reanalysis_run_id(
        ReanalyzeNativeMaterialScoresCommand.model_validate(request.model_dump(mode="json"))
    )
    other = request.model_copy(update={"idempotency_key": "native-score-proof-test-002"})
    assert native_score_reanalysis_run_id(other) != target.successor_run_id
    assert native_score_reanalysis_target_key(
        target.successor_run_id, target.source_task_id
    ) != native_score_reanalysis_target_key(target.successor_run_id, "materialtask_" + "1" * 32)


@pytest.mark.parametrize(
    "fault",
    [
        "hash",
        "new_result",
        "question_media",
        "work_path",
        "same_points",
        "reason",
        "unknown",
        "successor",
        "float",
    ],
)
def test_invalid_or_unnecessary_repair_proof_fails_closed(fault):
    data = target_data()
    if fault == "hash":
        data["target_sha256"] = "sha256:" + "0" * 64
    elif fault == "new_result":
        data["source_result"]["schema_ref"] = "material-learning-result@3.0"
    elif fault == "question_media":
        data["question"]["media_type"] = "application/pdf"
    elif fault == "work_path":
        data["source_work"]["member_path"] = "other.json"
    elif fault == "same_points":
        data["prior_item"]["points"] = "1.5"
    elif fault == "reason":
        data["reason"] = "LEGACY_SCORE_CONTRACT"
    elif fault == "unknown":
        data["authority"] = "ADMIN"
    elif fault == "successor":
        data["successor_run_id"] = "materialrun_" + "0" * 32
    else:
        data["expected_score"]["points"] = 1.5
    if fault not in {"hash", "float"}:
        rehash(data, "target_sha256")
    with pytest.raises((ValueError, SchemaError)):
        NativeScoreReanalysisTarget.model_validate(data)


def test_legacy_refusal_has_no_invented_registered_item():
    data = target_data()
    data.update(prior_item=None, reason="LEGACY_SCORE_CONTRACT")
    target = NativeScoreReanalysisTarget.model_validate(rehash(data, "target_sha256"))
    assert target.prior_item is None


def test_successor_lineage_pins_repair_proof_without_changing_normal_family(monkeypatch):
    resolved, content = resolved_case(monkeypatch, exact_score=True)
    proof = resolved_target()
    value = registration.material_item_lineage(resolved, content, reanalysis=proof)
    assert isinstance(value, MaterialItemLineageV4)
    assert value.native_score_reanalysis == proof.evidence
    assert parse_material_item_lineage(value.model_dump(mode="json")) == value
    assert value.role_result == resolved.result_pointer
    assert value.registered_content_sha256 == content.registered_content_sha256
    assert registration.material_item_lineage(resolved, content).schema_version.endswith("/3.0")
    changed = value.model_dump(mode="json")
    changed["native_score_reanalysis"]["member_path"] = "wrong.json"
    rehash(changed, "lineage_sha256")
    with pytest.raises((ValueError, SchemaError)):
        parse_material_item_lineage(changed)


def test_legacy_result_cannot_be_relabelled_as_corrected_result(monkeypatch):
    resolved, content = resolved_case(monkeypatch)
    with pytest.raises(ValueError, match="RESULT_REQUIRED"):
        registration.material_item_lineage(resolved, content, reanalysis=resolved_target())


@pytest.mark.parametrize("prior_points,expected_count", [(0, 1), (15, 1), ("2.5", 1), ("1.5", 0)])
def test_capture_selects_only_actual_registered_score_mismatches(
    monkeypatch, prior_points, expected_count
):
    """Synthetic completed-work/binding ports, real bounded native score reader."""
    resolved, _ = resolved_case(monkeypatch)
    request = command().model_copy(update={"actor_id": resolved.operator_id})
    raw = package(section("[1.5점]"))
    native = binding_data()
    native["question"]["document"] = bound_question(raw).document.model_dump(mode="json")
    binding = MaterialNativeItemBinding.model_validate(rehash(native, "binding_sha256"))
    row = SimpleNamespace(**{name: None for name in score_owner._TASK_FIELDS})
    row.task_id, row.task_kind, row.unit_key = resolved.task_id, "QUESTION", resolved.unit_key
    row.item_revision_id = "itemrev_" + "f" * 32
    service = object.__new__(score_owner.NativeMaterialScoreReanalysisService)
    prepared = MaterialArtifactMember.model_validate(target_data()["prepared"])
    source = SimpleNamespace(
        material_revision_id=resolved.work.material_revision_id,
        prepared_artifact_id=prepared.artifact_id,
        prepared_artifact_revision_id=prepared.artifact_revision_id,
        prepared_sha256=prepared.sha256,
    )
    service._source = lambda *_a: (source, SimpleNamespace(material_id=resolved.work.material_id))
    service._tasks = lambda *_a: (row,)
    service.artifacts = Reader(raw, binding.question)
    service.sources = SimpleNamespace(reauthorize=lambda *_a, **_k: None)
    prior = score_owner.NativeScorePriorItem.model_validate(
        {**target_data()["prior_item"], "points": prior_points}
    )
    service._prior_item = lambda *_a: prior
    monkeypatch.setattr(score_owner, "material_prepared_pointer", lambda *_a, **_k: prepared)
    monkeypatch.setattr(score_owner, "resolve_completed_material_task", lambda *_a, **_k: resolved)
    monkeypatch.setattr(
        score_owner, "resolve_native_material_registration_binding", lambda *_a, **_k: binding
    )
    if expected_count:
        snapshot = service._capture(SimpleNamespace(), request)
        assert len(snapshot.targets) == 1
        target = snapshot.targets[0]
        assert target.expected_score.points == "1.5" and target.prior_item == prior
        assert target.source_work == resolved.work_pointer
        assert target.source_result == resolved.result_pointer
        assert target.reason == "REGISTERED_SCORE_MISMATCH"
    else:
        with pytest.raises(ValueError, match="NO_TARGETS"):
            service._capture(SimpleNamespace(), request)
    assert len(service.artifacts.calls) == 1


def test_checkpoint_hash_detects_independent_error_change():
    task = SimpleNamespace(**{name: None for name in score_owner._TASK_FIELDS})
    before = score_owner.native_score_task_checkpoint_sha256((task,))
    task.error_code = "MATERIAL_ITEM_SOURCE_UNREADABLE"
    assert score_owner.native_score_task_checkpoint_sha256((task,)) != before
