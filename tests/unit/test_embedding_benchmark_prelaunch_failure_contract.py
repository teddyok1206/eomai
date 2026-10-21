"""Additive protocol validation; synthetic proof values never authorize failure or compute."""

from pathlib import Path

import pytest
from eom_catalog_contracts.embedding_benchmark_prelaunch_failure import (
    MAX_PRELAUNCH_FAILURE_BYTES,
    PRELAUNCH_FAILURE_SCHEMA,
    BenchmarkPrelaunchFailureDecision,
    BenchmarkPrelaunchObservation,
    BenchmarkPrelaunchPredecessorReference,
    benchmark_prelaunch_failure_bytes,
    parse_benchmark_prelaunch_failure,
)
from eom_catalog_contracts.validation import CATALOG_SCHEMA_RESOURCES, load_schema
from eom_identifiers import canonical_json_bytes, sha256_bytes
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError as SchemaError

from tests.unit.embedding_benchmark_prelaunch_failure_fixtures import decision, observation
from tests.unit.inference_transfer_embedding_fixtures import seal

INVALID = (ValueError, TypeError, SchemaError)


def test_additive_schema_pin_mirror_and_three_canonical_kinds():
    root = Path(__file__).resolve().parents[2]
    resource = CATALOG_SCHEMA_RESOURCES[PRELAUNCH_FAILURE_SCHEMA]
    raw = (root / resource.canonical_path).read_bytes()
    assert sha256_bytes(raw) == resource.sha256
    assert (
        raw
        == (
            root / "packages/catalog_contracts/eom_catalog_contracts" / resource.resource_path
        ).read_bytes()
    )
    Draft202012Validator.check_schema(load_schema(PRELAUNCH_FAILURE_SCHEMA))
    values = (
        observation(),
        decision(),
        BenchmarkPrelaunchPredecessorReference.from_decision(decision(), event_sequence=7),
    )
    for value in values:
        raw = benchmark_prelaunch_failure_bytes(value)
        assert len(raw) < MAX_PRELAUNCH_FAILURE_BYTES
        assert parse_benchmark_prelaunch_failure(raw) == value
        assert not hasattr(value, "assert_current") and not hasattr(value, "capture")


@pytest.mark.parametrize("field", ("launch_ordinal", "output_count"))
@pytest.mark.parametrize("bad", (True, False, 1.0, "1", None))
def test_observation_counts_are_raw_strict_not_coerced(field, bad):
    body = observation().model_dump(mode="json")
    body[field] = bad
    with pytest.raises(INVALID):
        BenchmarkPrelaunchObservation.model_validate(seal(body, "observation_sha256"))


@pytest.mark.parametrize("fault", ("CUDA", "later", "extra", "hash", "timezone", "controller"))
def test_observation_is_narrow_pinned_and_utc(fault):
    body = observation().model_dump(mode="json")
    if fault == "CUDA":
        body["device"] = "CUDA"
    elif fault == "later":
        body["launch_ordinal"] = 2
    elif fault == "extra":
        body["permission"] = "ADMIN"
    elif fault == "timezone":
        body["observed_at"] = "2026-10-21T21:00:00+09:00"
    elif fault == "controller":
        body["controller"]["unit"] = "unrelated.service"
    else:
        body["snapshot_sha256"] = "sha256:" + "f" * 64
    value = body if fault == "hash" else seal(body, "observation_sha256")
    with pytest.raises(INVALID):
        BenchmarkPrelaunchObservation.model_validate(value)


@pytest.mark.parametrize("field", ("job_id", "execution_id", "request_sha256", "invocation_sha256"))
def test_resealed_decision_cannot_reference_another_observation(field):
    body = decision().model_dump(mode="json")
    prefix = "job_" if field == "job_id" else "sha256:" if field.endswith("sha256") else ""
    body[field] = prefix + "f" * (64 if field.endswith("sha256") else 32)
    with pytest.raises(INVALID):
        BenchmarkPrelaunchFailureDecision.model_validate(seal(body, "decision_sha256"))


@pytest.mark.parametrize("sequence", (True, 6, 33, "7"))
def test_predecessor_points_to_a_bounded_post_reservation_event(sequence):
    with pytest.raises(INVALID):
        BenchmarkPrelaunchPredecessorReference.from_decision(decision(), event_sequence=sequence)


def test_parser_rejects_noncanonical_duplicate_oversized_and_constructed_extras():
    value = observation()
    raw = benchmark_prelaunch_failure_bytes(value)
    for changed in (
        raw + b"\n",
        b" " * (MAX_PRELAUNCH_FAILURE_BYTES + 1),
        raw.replace(b"{", b'{"kind":"ROOT_OBSERVATION",', 1),
    ):
        with pytest.raises(INVALID):
            parse_benchmark_prelaunch_failure(changed)
    changed = value.model_copy(update={"rogue": "not part of protocol"})
    with pytest.raises(INVALID):
        benchmark_prelaunch_failure_bytes(changed)
    assert b'"text"' not in canonical_json_bytes(decision().model_dump(mode="json"))
