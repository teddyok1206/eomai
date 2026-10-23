"""Additive CPU1 terminal failure protocol; synthetic values never authorize cleanup/retry."""

from pathlib import Path

import pytest
from eom_catalog_contracts.embedding_benchmark_budget1200_failure import (
    BenchmarkBudget1200FailureDecision,
    BenchmarkBudget1200PoststartObservation,
    BenchmarkBudget1200PredecessorReference,
    benchmark_budget1200_failure_bytes,
    parse_benchmark_budget1200_failure,
)
from eom_catalog_contracts.embedding_benchmark_poststart_failure import (
    MAX_POSTSTART_FAILURE_BYTES,
    POSTSTART_FAILURE_SCHEMA,
    BenchmarkPoststartFailureDecision,
    BenchmarkPoststartObservation,
    BenchmarkPoststartPredecessorReference,
    benchmark_poststart_failure_bytes,
    parse_benchmark_poststart_failure,
)
from eom_catalog_contracts.embedding_benchmark_prelaunch_failure import (
    parse_benchmark_prelaunch_failure,
)
from eom_catalog_contracts.validation import CATALOG_SCHEMA_RESOURCES, load_schema
from eom_identifiers import canonical_json_bytes, sha256_bytes
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError as SchemaError

from tests.unit.embedding_benchmark_poststart_failure_fixtures import decision, observation
from tests.unit.inference_transfer_embedding_fixtures import seal

INVALID = (ValueError, TypeError, SchemaError)


def test_additive_schema_pin_mirror_and_three_canonical_kinds():
    root = Path(__file__).resolve().parents[2]
    resource = CATALOG_SCHEMA_RESOURCES[POSTSTART_FAILURE_SCHEMA]
    raw = (root / resource.canonical_path).read_bytes()
    assert sha256_bytes(raw) == resource.sha256
    assert (
        raw
        == (
            root / "packages/catalog_contracts/eom_catalog_contracts" / resource.resource_path
        ).read_bytes()
    )
    Draft202012Validator.check_schema(load_schema(POSTSTART_FAILURE_SCHEMA))
    for value in (
        observation(),
        decision(),
        BenchmarkPoststartPredecessorReference.from_decision(decision(), event_sequence=8),
    ):
        raw = benchmark_poststart_failure_bytes(value)
        assert len(raw) < MAX_POSTSTART_FAILURE_BYTES
        assert parse_benchmark_poststart_failure(raw) == value
        assert not hasattr(value, "assert_current") and not hasattr(value, "capture")
        with pytest.raises(INVALID):
            parse_benchmark_prelaunch_failure(raw)


def test_budget1200_failure_successor_has_its_own_exact_terminal_identity_and_schema():
    root = Path(__file__).resolve().parents[2]
    resource = CATALOG_SCHEMA_RESOURCES["embedding-benchmark-poststart-failure-v1.2"]
    canonical = (root / resource.canonical_path).read_bytes()
    packaged = (
        root / "packages/catalog_contracts/eom_catalog_contracts" / resource.resource_path
    ).read_bytes()
    assert canonical == packaged and sha256_bytes(canonical) == resource.sha256
    schema = load_schema("embedding-benchmark-poststart-failure-v1.2")
    Draft202012Validator.check_schema(schema)

    body = observation().model_dump(mode="json")
    body["schema_version"] = "embedding-benchmark-poststart-failure/1.2"
    prefix = "eom-embedding-benchmark-cpu-budget1200@" + body["execution_id"]
    body["terminal"]["native_service"] = prefix + ".service"
    body["terminal"]["native_socket"] = prefix + ".socket"
    value = BenchmarkBudget1200PoststartObservation.model_validate(seal(body, "observation_sha256"))
    raw = benchmark_budget1200_failure_bytes(value)
    assert parse_benchmark_budget1200_failure(raw) == value
    assert len(raw) < MAX_POSTSTART_FAILURE_BYTES
    with pytest.raises(INVALID):
        BenchmarkBudget1200PoststartObservation.model_validate(
            seal(
                body
                | {
                    "terminal": body["terminal"]
                    | {"native_service": prefix.replace("budget1200", "budget600") + ".service"}
                },
                "observation_sha256",
            )
        )

    decision_body = {
        "schema_version": "embedding-benchmark-poststart-failure/1.2",
        "kind": "FAILURE_DECISION",
        "job_id": value.job_id,
        "execution_id": value.execution_id,
        "request_sha256": value.request_sha256,
        "invocation_sha256": value.invocation_sha256,
        "from_state": "RUNNING",
        "to_state": "FAILED",
        "error_code": "BENCHMARK_POSTSTART_EXECUTION_FAILED",
        "observation": value.model_dump(mode="json"),
        "actor_id": "operator_test",
        "decided_at": "2026-10-23T12:00:01Z",
    }
    decision_value = BenchmarkBudget1200FailureDecision.model_validate(
        seal(decision_body, "decision_sha256")
    )
    reference = BenchmarkBudget1200PredecessorReference.from_decision(
        decision_value, event_sequence=8
    )
    assert reference.schema_version == "embedding-benchmark-poststart-failure/1.2"


@pytest.mark.parametrize("field", ("launch_ordinal", "started_ns", "completed_ns"))
@pytest.mark.parametrize("bad", (True, False, 1.0, "1", None))
def test_observation_raw_counts_are_strict_not_coerced(field, bad):
    body = observation().model_dump(mode="json")
    body[field] = bad
    with pytest.raises(INVALID):
        BenchmarkPoststartObservation.model_validate(seal(body, "observation_sha256"))


@pytest.mark.parametrize(
    ("field", "bad"),
    (
        ("device", "CUDA"),
        ("launch_ordinal", 2),
        ("original_outcome", "SUCCEEDED"),
        ("cleanup", "UNCERTAIN"),
        ("started_ns", 0),
        ("completed_ns", 99),
        ("completed_ns", 100),
        ("observed_at", "2026-10-22T21:00:00+09:00"),
        ("permission", "ADMIN"),
    ),
)
def test_only_actual_started_cpu_first_failed_confirmed_facts_are_representable(field, bad):
    body = observation().model_dump(mode="json")
    body[field] = bad
    with pytest.raises(INVALID):
        BenchmarkPoststartObservation.model_validate(seal(body, "observation_sha256"))


@pytest.mark.parametrize(
    ("field", "bad"),
    (
        ("main_pid", 1),
        ("main_pid", False),
        ("control_pid", 1),
        ("control_pid", False),
        ("descriptor_store_count", 1),
        ("descriptor_store_count", False),
        ("cgroup_empty", False),
        ("cgroup_empty", 1),
        ("socket_inactive", False),
        ("socket_inactive", 1),
        ("retirement", "UNCERTAIN"),
        ("native_service", "unrelated.service"),
        ("native_socket", "unrelated.socket"),
        ("native_invocation_id", "unrelated"),
        ("retirement_raw_sha256", "not a content hash"),
    ),
)
def test_live_or_uncertain_terminal_metadata_is_rejected(field, bad):
    body = observation().model_dump(mode="json")
    body["terminal"][field] = bad
    with pytest.raises(INVALID):
        BenchmarkPoststartObservation.model_validate(seal(body, "observation_sha256"))


@pytest.mark.parametrize("field", ("native_service", "native_socket"))
def test_terminal_native_identity_cannot_point_to_another_execution(field):
    body = observation().model_dump(mode="json")
    body["terminal"][field] = body["terminal"][field].replace(body["execution_id"], "f" * 32)
    with pytest.raises(INVALID):
        BenchmarkPoststartObservation.model_validate(seal(body, "observation_sha256"))


@pytest.mark.parametrize("field", ("unit", "invocation_id", "source_commit"))
def test_controller_identity_is_exact_typed_metadata(field):
    body = observation().model_dump(mode="json")
    body["controller"][field] = "unrelated"
    with pytest.raises(INVALID):
        BenchmarkPoststartObservation.model_validate(seal(body, "observation_sha256"))


@pytest.mark.parametrize(
    "fault",
    (
        "duplicate",
        "missing",
        "reordered",
        "extra",
        "path",
        "bytes",
        "empty-hash",
        "all-empty",
        "total",
    ),
)
def test_partial_members_are_closed_unique_ordered_bounded_metadata(fault):
    body = observation().model_dump(mode="json")
    members = body["outputs"]
    if fault == "duplicate":
        members[1] = dict(members[0])
    elif fault == "missing":
        members.pop()
    elif fault == "reordered":
        members.reverse()
    elif fault == "extra":
        members.append(dict(members[0]))
    elif fault == "path":
        members[0]["member_name"] = "../cold-documents.f32"
    elif fault == "bytes":
        members[0]["contents"] = "private bytes are not metadata"
    elif fault == "empty-hash":
        members[1]["raw_sha256"] = "sha256:" + "f" * 64
    elif fault == "all-empty":
        members[0].update(byte_count=0, raw_sha256=sha256_bytes(b""))
    else:
        members[0]["byte_count"] = 16 * 1024**2
        members[1].update(byte_count=1, raw_sha256="sha256:" + "f" * 64)
    with pytest.raises(INVALID):
        BenchmarkPoststartObservation.model_validate(seal(body, "observation_sha256"))


@pytest.mark.parametrize("bad", (True, False, -1, 1.0, "1", 16 * 1024**2 + 1))
def test_partial_member_byte_counts_are_raw_strict_and_bounded(bad):
    body = observation().model_dump(mode="json")
    body["outputs"][0]["byte_count"] = bad
    with pytest.raises(INVALID):
        BenchmarkPoststartObservation.model_validate(seal(body, "observation_sha256"))


@pytest.mark.parametrize("field", ("job_id", "execution_id", "request_sha256", "invocation_sha256"))
def test_resealed_decision_cannot_reference_another_observation(field):
    body = decision().model_dump(mode="json")
    prefix = "job_" if field == "job_id" else "sha256:" if field.endswith("sha256") else ""
    body[field] = prefix + "f" * (64 if field.endswith("sha256") else 32)
    with pytest.raises(INVALID):
        BenchmarkPoststartFailureDecision.model_validate(seal(body, "decision_sha256"))


@pytest.mark.parametrize(
    ("field", "bad"),
    (
        ("from_state", "VALIDATED"),
        ("to_state", "SUCCEEDED"),
        ("error_code", "BENCHMARK_PRELAUNCH_PREPARATION_FAILED"),
        ("decided_at", "2026-10-22T11:59:59Z"),
    ),
)
def test_decision_is_only_append_only_failed_transition_after_observation(field, bad):
    body = decision().model_dump(mode="json")
    body[field] = bad
    with pytest.raises(INVALID):
        BenchmarkPoststartFailureDecision.model_validate(seal(body, "decision_sha256"))


@pytest.mark.parametrize("sequence", (True, 6, 33, "7"))
def test_predecessor_points_to_bounded_post_reservation_event(sequence):
    with pytest.raises(INVALID):
        BenchmarkPoststartPredecessorReference.from_decision(decision(), event_sequence=sequence)


@pytest.mark.parametrize("kind", ("observation", "decision"))
def test_hash_change_without_reseal_is_rejected(kind):
    value = observation() if kind == "observation" else decision()
    body = value.model_dump(mode="json")
    body["request_sha256"] = "sha256:" + "f" * 64
    with pytest.raises(INVALID):
        parse_benchmark_poststart_failure(canonical_json_bytes(body))


def test_parser_rejects_noncanonical_duplicate_oversized_and_constructed_extras():
    value = observation()
    raw = benchmark_poststart_failure_bytes(value)
    for changed in (
        raw + b"\n",
        b" " * (MAX_POSTSTART_FAILURE_BYTES + 1),
        raw.replace(b"{", b'{"kind":"ROOT_OBSERVATION",', 1),
    ):
        with pytest.raises(INVALID):
            parse_benchmark_poststart_failure(changed)
    changed = value.model_copy(update={"rogue": "not part of protocol"})
    with pytest.raises(INVALID):
        benchmark_poststart_failure_bytes(changed)
    changed = value.model_copy(
        update={"terminal": value.terminal.model_copy(update={"main_pid": False})}
    )
    with pytest.raises(INVALID):
        benchmark_poststart_failure_bytes(changed)
    changed = value.model_copy(
        update={
            "outputs": (
                value.outputs[0].model_copy(update={"private_bytes": "never accepted"}),
                *value.outputs[1:],
            )
        }
    )
    with pytest.raises(INVALID):
        benchmark_poststart_failure_bytes(changed)
    assert b'"text"' not in canonical_json_bytes(decision().model_dump(mode="json"))
    assert b'"vectors"' not in raw


def test_metadata_models_are_immutable():
    value = observation()
    for target, field in (
        (value, "execution_id"),
        (value.terminal, "main_pid"),
        (value.outputs[0], "byte_count"),
    ):
        with pytest.raises(ValueError):
            setattr(target, field, 1)
