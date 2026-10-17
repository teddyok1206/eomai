"""Closed schema/model/canonical closure; parsed cleanup is explicitly not actual proof."""

import json
from importlib.resources import files
from pathlib import Path

import pytest
from eom_workflow.embedding_benchmark_launch_control import (
    BenchmarkLaunchAssociation,
    BenchmarkLaunchControlError,
    benchmark_launch_control_bytes,
    parse_benchmark_launch_control,
    parse_benchmark_launch_control_bytes,
    validate_benchmark_control_reply,
    validate_benchmark_launch_association,
)
from eom_workflow.schemas import load_local_embedding_admission_schema
from jsonschema import Draft202012Validator

from tests.unit.embedding_benchmark_control_fixtures import (
    association,
    completed,
    prepared,
    uncertain,
)
from tests.unit.embedding_device_benchmark_fixtures import (
    owner_request,
    staged_inputs,
    worker_invocation,
)
from tests.unit.inference_transfer_embedding_fixtures import seal


def test_schema_source_and_installed_resource_have_identical_bytes():
    packaged = (
        files("eom_workflow")
        .joinpath("resources/embedding-benchmark-launch-control-v1.schema.json")
        .read_bytes()
    )
    source = Path("schemas/workflow/embedding-benchmark-launch-control-v1.schema.json").read_bytes()
    assert packaged == source


@pytest.mark.parametrize("ordinal", range(1, 7))
def test_all_frozen_devices_close_original_members_and_replies(ordinal):
    value = association(ordinal)
    before, failure = prepared(value), uncertain(value)
    after = completed(value, before)
    validate_benchmark_launch_association(
        value, owner_request(), worker_invocation(ordinal), staged_inputs()
    )
    for message in (value, before, after, failure):
        raw = benchmark_launch_control_bytes(message)
        assert parse_benchmark_launch_control_bytes(raw) == message
        if message is not value:
            validate_benchmark_control_reply(value, message, prepared=before)
    Draft202012Validator.check_schema(
        load_local_embedding_admission_schema("benchmark-launch-control")
    )


@pytest.mark.parametrize("fault", ("extra", "bool", "float", "missing", "actor", "hash"))
def test_malformed_or_authority_claims_do_not_become_valid_contracts(fault):
    value = association().model_dump(mode="json")
    if fault == "extra":
        value["new_key"] = "unexpected"
    elif fault == "bool":
        value["owner_pid"] = True
    elif fault == "float":
        value["expires_ns"] = 1.0
    elif fault == "missing":
        del value["schema_version"]
    elif fault == "actor":
        value["role"] = "ADMIN"
    else:
        value["association_sha256"] = "sha256:" + "0" * 64
    with pytest.raises(BenchmarkLaunchControlError):
        parse_benchmark_launch_control(value)


def test_nested_construct_and_noncanonical_bytes_are_revalidated():
    original = association()
    bad = original.model_copy(update={"owner_pid": True})
    with pytest.raises(ValueError):
        benchmark_launch_control_bytes(bad)
    with pytest.raises(ValueError):
        parse_benchmark_launch_control_bytes(
            json.dumps(original.model_dump(mode="json"), indent=2).encode()
        )


def test_foreign_prepared_cannot_be_used_to_validate_a_completion():
    value, other = association(), association(2)
    before = prepared(other)
    body = completed(value, prepared(value)).model_dump(mode="json")
    body["prepared_sha256"] = before.prepared_sha256
    after = parse_benchmark_launch_control(seal(body, "completion_sha256"))
    with pytest.raises(ValueError):
        validate_benchmark_control_reply(value, after, prepared=before)


def test_staged_input_hash_or_ordinal_cannot_be_reinterpreted():
    value = association()
    body = value.model_dump(mode="json")
    body["inputs"]["sha256"] = "sha256:" + "0" * 64
    bad = BenchmarkLaunchAssociation.model_validate(seal(body, "association_sha256"))
    with pytest.raises(ValueError):
        validate_benchmark_launch_association(
            bad, owner_request(), worker_invocation(), staged_inputs()
        )
