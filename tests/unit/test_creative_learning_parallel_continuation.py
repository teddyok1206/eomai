"""Three report workers reuse one original cohort and exact serial predecessor."""

from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import Mock

import pytest
from eom_catalog_contracts.creative_learning_continuation import (
    CREATIVE_CONTINUATION_REF,
    CreativeLearningExecutionScope,
    CreativeLearningParallelContinuation,
    validate_creative_parallel_predecessor,
)
from eom_catalog_service.creative_learning_cohort import read_creative_execution_scope
from eom_identifiers import canonical_json_bytes, content_sha256, sha256_bytes
from eom_protocol.artifact_members import ArtifactMemberPointer
from jsonschema import ValidationError as SchemaError

from tests.unit.test_creative_learning_continuation import continuation_case


def parallel_case():
    cohort, parent, serial = continuation_case()
    predecessor = CreativeLearningExecutionScope(cohort, serial)
    pointer = ArtifactMemberPointer(
        artifact_id="artifact_" + "7" * 32,
        artifact_revision_id="rev_" + "8" * 32,
        member_path="continuation.json",
        schema_ref=CREATIVE_CONTINUATION_REF,
        media_type="application/json",
        sha256=sha256_bytes(canonical_json_bytes(serial.model_dump(mode="json"))),
    )
    body = {
        "schema_version": "creative-learning-continuation/1.1",
        "cohort_id": "creativecohort_" + "1" * 32,
        "parent_cohort": parent.model_dump(mode="json"),
        "predecessor_execution": pointer.model_dump(mode="json"),
        "requested_by_operator_id": cohort.requested_by_operator_id,
        "target_set_sha256": cohort.target_set_sha256,
        "source_commit": "f" * 40,
        "workflow_definition_version": predecessor.workflow_definition_version,
        "workflow_definition_sha256": predecessor.workflow_definition_sha256,
        "content_pack_release_id": predecessor.content_pack_release_id,
        "extraction_preset": {
            "preset_id": "execpreset_" + "4" * 32,
            "preset_revision_id": "execpresetrev_" + "5" * 32,
            "sha256": "sha256:" + "6" * 64,
        },
        "analysis_preset": {
            "preset_id": "execpreset_" + "7" * 32,
            "preset_revision_id": "execpresetrev_" + "8" * 32,
            "sha256": "sha256:" + "9" * 64,
        },
        "extraction_preset_key": "creative-source-learning-parallel",
        "analysis_preset_key": "creative-knowledge-analysis-parallel",
        "capacity_policy": {
            "capacity_policy_id": "capacity_" + "d" * 32,
            "capacity_policy_revision_id": "capacityrev_" + "e" * 32,
            "schema_ref": "eom://schemas/workflow/worker-capacity-policy/1.4",
            "sha256": "sha256:" + "f" * 64,
        },
        "max_in_flight_sources": 6,
        "max_report_workers": 3,
        "graph_publication_batch_size": 3,
        "continuation_reason": "THREE_SLOT_REPORT_CAPACITY_SUCCESSOR",
    }
    value = {**body, "cohort_sha256": content_sha256(body)}
    return predecessor, pointer, value


def reseal(value):
    value["cohort_sha256"] = content_sha256(
        {k: v for k, v in value.items() if k != "cohort_sha256"}
    )


def test_new_scope_keeps_targets_reports_and_original_execution_pins_immutable():
    predecessor, pointer, value = parallel_case()
    original = predecessor.cohort.model_dump(mode="json")
    parallel = CreativeLearningParallelContinuation.model_validate(value)
    validate_creative_parallel_predecessor(parallel, predecessor, pointer)
    scope = CreativeLearningExecutionScope(predecessor.cohort, parallel, predecessor)
    assert scope.cohort.targets is predecessor.cohort.targets
    assert scope.predecessor_scope is predecessor
    assert scope.analysis_preset == parallel.analysis_preset
    assert scope.capacity_policy_revision_id == parallel.capacity_policy.capacity_policy_revision_id
    assert scope.max_in_flight_sources == 6 and parallel.max_report_workers == 3
    assert predecessor.max_in_flight_sources == 1
    assert predecessor.analysis_preset == predecessor.cohort.analysis_preset
    assert predecessor.cohort.model_dump(mode="json") == original
    assert "targets" not in parallel.model_dump(mode="json")
    assert len(parallel.model_dump_json()) < 8192
    assert (
        CreativeLearningParallelContinuation.model_validate_json(parallel.model_dump_json())
        == parallel
    )


def test_schema_mirror_and_old_continuation_bytes_stay_separate():
    root = Path(__file__).resolve().parents[2]
    name = "external-item/creative-learning-parallel-continuation-v1.schema.json"
    assert (root / "schemas" / name).read_bytes() == (
        root / "packages/catalog_contracts/eom_catalog_contracts/resources" / name
    ).read_bytes()
    _, _, old = continuation_case()
    with pytest.raises(ValueError):
        CreativeLearningParallelContinuation.model_validate(old.model_dump(mode="json"))


@pytest.mark.parametrize(
    "field",
    [
        "owner",
        "targets",
        "pack",
        "workflow",
        "parent",
        "same_id",
        "old_capacity",
        "old_extraction",
        "old_analysis",
    ],
)
def test_successor_cannot_change_source_or_steal_existing_control_identity(field):
    predecessor, pointer, value = parallel_case()
    value = deepcopy(value)
    if field == "owner":
        value["requested_by_operator_id"] = "operator_" + "0" * 32
    elif field == "targets":
        value["target_set_sha256"] = "sha256:" + "0" * 64
    elif field == "pack":
        value["content_pack_release_id"] = "packrel_" + "0" * 32
    elif field == "workflow":
        value["workflow_definition_sha256"] = "sha256:" + "0" * 64
    elif field == "parent":
        value["parent_cohort"]["sha256"] = "sha256:" + "0" * 64
    elif field == "same_id":
        value["cohort_id"] = predecessor.cohort_id
    elif field == "old_capacity":
        value["capacity_policy"]["capacity_policy_revision_id"] = (
            predecessor.capacity_policy_revision_id
        )
    elif field == "old_extraction":
        value["extraction_preset"] = predecessor.extraction_preset.model_dump(mode="json")
    else:
        value["analysis_preset"] = predecessor.analysis_preset.model_dump(mode="json")
    reseal(value)
    parallel = CreativeLearningParallelContinuation.model_validate(value)
    with pytest.raises(ValueError, match="PARENT_MISMATCH"):
        validate_creative_parallel_predecessor(parallel, predecessor, pointer)
    with pytest.raises(ValueError):
        CreativeLearningExecutionScope(predecessor.cohort, parallel, predecessor)


@pytest.mark.parametrize(
    "field", ["workers", "window", "batch", "predecessor_family", "capacity_family", "hash"]
)
def test_protocol_limits_and_family_mismatch_fail_closed(field):
    _, _, value = parallel_case()
    if field == "workers":
        value["max_report_workers"] = 4
    elif field == "window":
        value["max_in_flight_sources"] = 100
    elif field == "batch":
        value["graph_publication_batch_size"] = 4
    elif field == "predecessor_family":
        value["predecessor_execution"]["member_path"] = "cohort.json"
    elif field == "capacity_family":
        value["capacity_policy"]["schema_ref"] = "eom://schemas/workflow/worker-capacity-policy/1.3"
    else:
        value["cohort_sha256"] = "sha256:" + "0" * 64
    if field != "hash":
        reseal(value)
    with pytest.raises((ValueError, SchemaError)):
        CreativeLearningParallelContinuation.model_validate(value)


def test_actual_pointer_must_match_and_missing_predecessor_never_grants_scope():
    predecessor, pointer, value = parallel_case()
    parallel = CreativeLearningParallelContinuation.model_validate(value)
    with pytest.raises(ValueError):
        validate_creative_parallel_predecessor(
            parallel, predecessor, pointer.model_copy(update={"sha256": "sha256:" + "0" * 64})
        )
    with pytest.raises(ValueError):
        CreativeLearningExecutionScope(predecessor.cohort, parallel)


def read_case():
    predecessor, pointer, value = parallel_case()
    serial = predecessor.continuation
    rows = {}
    payloads = {}
    for artifact, revision, path, document in (
        (
            serial.parent_cohort.artifact_id,
            serial.parent_cohort.artifact_revision_id,
            "cohort.json",
            predecessor.cohort,
        ),
        (pointer.artifact_id, pointer.artifact_revision_id, "continuation.json", serial),
        (
            "artifact_" + "9" * 32,
            "rev_" + "a" * 32,
            "parallel-continuation.json",
            CreativeLearningParallelContinuation.model_validate(value),
        ),
    ):
        payload = canonical_json_bytes(document.model_dump(mode="json"))
        payloads[revision] = payload
        rows[revision] = NS(
            artifact_id=artifact,
            artifact_revision_id=revision,
            primary_file=path,
            primary_sha256=sha256_bytes(payload),
        )
    publisher = NS(
        read_published_revision=Mock(
            side_effect=lambda **kwargs: rows[kwargs["artifact_revision_id"]]
        )
    )

    def member(**kwargs):
        payload = payloads[kwargs["revision_id"]]
        assert sha256_bytes(payload) == kwargs["sha256"]
        assert rows[kwargs["revision_id"]].artifact_id == kwargs["artifact_id"]
        return payload

    artifacts = NS(read_member=Mock(side_effect=member))
    return artifacts, publisher, rows, payloads


def test_actual_control_reader_resolves_exact_parallel_serial_base_chain():
    artifacts, publisher, _, _ = read_case()
    scope, _ = read_creative_execution_scope(artifacts, publisher, "rev_" + "a" * 32)
    assert scope.max_in_flight_sources == 6
    assert scope.cohort.targets is scope.predecessor_scope.cohort.targets
    assert scope.predecessor_scope.max_in_flight_sources == 1
    assert {call.kwargs["schema_ref"] for call in artifacts.read_member.call_args_list} == {
        "eom://schemas/external-item/creative-learning-continuation/1.1",
        "eom://schemas/external-item/creative-learning-continuation/1.0",
        "eom://schemas/external-item/creative-learning-cohort/1.0",
    }


def test_parallel_predecessor_cannot_point_back_to_another_parallel_owner():
    artifacts, publisher, rows, payloads = read_case()
    revision = "rev_" + "a" * 32
    value = CreativeLearningParallelContinuation.model_validate_json(payloads[revision]).model_dump(
        mode="json"
    )
    value["predecessor_execution"]["artifact_revision_id"] = revision
    value["predecessor_execution"]["artifact_id"] = rows[revision].artifact_id
    reseal(value)
    payloads[revision] = canonical_json_bytes(value)
    rows[revision].primary_sha256 = sha256_bytes(payloads[revision])
    with pytest.raises(ValueError, match="PARENT_MISMATCH"):
        read_creative_execution_scope(artifacts, publisher, revision)
    assert artifacts.read_member.call_count == 1
