"""An explicit four-report successor reuses one admitted source set and its history."""

from copy import deepcopy
from types import SimpleNamespace as NS

import pytest
from eom_catalog_contracts.creative_learning_continuation import (
    CREATIVE_PARALLEL_CONTINUATION_REF,
    CreativeLearningExecutionScope,
    CreativeLearningOfficeContinuation,
    CreativeLearningParallelContinuation,
    validate_creative_office_predecessor,
)
from eom_catalog_service.creative_learning_cohort import read_creative_execution_scope
from eom_identifiers import canonical_json_bytes, content_sha256, sha256_bytes
from eom_protocol.artifact_members import ArtifactMemberPointer

from tests.unit.test_creative_learning_parallel_continuation import parallel_case, read_case


def office_continuation_case():
    serial, _pointer, raw_parallel = parallel_case()
    parallel = CreativeLearningParallelContinuation.model_validate(raw_parallel)
    previous = CreativeLearningExecutionScope(serial.cohort, parallel, serial)
    pointer = ArtifactMemberPointer(
        artifact_id="artifact_" + "9" * 32,
        artifact_revision_id="rev_" + "a" * 32,
        member_path="parallel-continuation.json",
        schema_ref=CREATIVE_PARALLEL_CONTINUATION_REF,
        media_type="application/json",
        sha256=sha256_bytes(canonical_json_bytes(parallel.model_dump(mode="json"))),
    )
    raw = parallel.model_dump(mode="json", exclude={"cohort_sha256"})
    raw.update(
        schema_version="creative-learning-continuation/1.2",
        cohort_id="creativecohort_" + "5" * 32,
        predecessor_execution=pointer.model_dump(mode="json"),
        workflow_definition_version="3.0.0",
        workflow_definition_sha256="sha256:" + "b" * 64,
        max_in_flight_sources=8,
        max_report_workers=4,
        graph_publication_batch_size=4,
        continuation_reason="NATIVE_OFFICE_FOUR_SLOT_SUCCESSOR",
        extraction_preset_key="creative-office-learning-four",
        analysis_preset_key="creative-knowledge-analysis-office-four",
    )
    raw["capacity_policy"].update(
        capacity_policy_revision_id="capacityrev_" + "1" * 32,
        capacity_policy_id="capacity_" + "2" * 32,
        schema_ref="eom://schemas/workflow/worker-capacity-policy/1.5",
    )
    for index, field in enumerate(("extraction_preset", "analysis_preset")):
        raw[field].update(
            preset_id="execpreset_" + str(index + 2) * 32,
            preset_revision_id="execpresetrev_" + str(index + 2) * 32,
        )
    value = CreativeLearningOfficeContinuation.model_validate(
        {**raw, "cohort_sha256": content_sha256(raw)}
    )
    return previous, pointer, value


def test_office_successor_keeps_targets_and_all_prior_execution_scopes():
    previous, pointer, value = office_continuation_case()
    validate_creative_office_predecessor(value, previous, pointer)
    scope = CreativeLearningExecutionScope(previous.cohort, value, previous)
    assert scope.cohort.targets is previous.cohort.targets
    assert scope.workflow_definition_version == "3.0.0" and scope.max_in_flight_sources == 8
    assert scope.analysis_preset_key == "creative-knowledge-analysis-office-four"
    assert len(scope.history_scopes) == 4
    assert scope.history_scopes[1:] == previous.history_scopes


@pytest.mark.parametrize(
    "change", ["owner", "targets", "parent", "same-id", "capacity", "extraction", "analysis"]
)
def test_office_successor_cannot_steal_owner_target_or_existing_policy(change):
    previous, pointer, value = office_continuation_case()
    raw = deepcopy(value.model_dump(mode="json"))
    if change == "owner":
        raw["requested_by_operator_id"] = "operator_" + "0" * 32
    elif change == "targets":
        raw["target_set_sha256"] = "sha256:" + "0" * 64
    elif change == "parent":
        raw["parent_cohort"]["sha256"] = "sha256:" + "0" * 64
    elif change == "same-id":
        raw["cohort_id"] = previous.cohort_id
    elif change == "capacity":
        raw["capacity_policy"]["capacity_policy_revision_id"] = previous.capacity_policy_revision_id
    else:
        field = change + "_preset"
        raw[field] = getattr(previous, field).model_dump(mode="json")
    raw["cohort_sha256"] = content_sha256({k: v for k, v in raw.items() if k != "cohort_sha256"})
    changed = CreativeLearningOfficeContinuation.model_validate(raw)
    with pytest.raises(ValueError, match="PARENT_MISMATCH"):
        CreativeLearningExecutionScope(previous.cohort, changed, previous)


def test_reader_closes_exact_office_parallel_serial_base_chain():
    artifacts, publisher, rows, payloads = read_case()
    _previous, _pointer, value = office_continuation_case()
    raw = canonical_json_bytes(value.model_dump(mode="json"))
    revision = "rev_" + "d" * 32
    rows[revision] = NS(
        artifact_id="artifact_" + "c" * 32,
        artifact_revision_id=revision,
        primary_file="office-continuation.json",
        primary_sha256=sha256_bytes(raw),
    )
    payloads[revision] = raw
    scope, _ = read_creative_execution_scope(artifacts, publisher, revision)
    assert scope.max_in_flight_sources == 8 and len(scope.history_scopes) == 4
    assert artifacts.read_member.call_count == 4
