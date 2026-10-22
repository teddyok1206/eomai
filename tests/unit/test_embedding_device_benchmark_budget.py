"""Budget successor metadata only; no authentication, model, unit or deployment effects."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from eom_catalog_contracts.embedding_device_benchmark import (
    EMBEDDING_DEVICE_BENCHMARK_SCHEMA,
    EMBEDDING_DEVICE_BENCHMARK_SCHEMA_REF,
    EMBEDDING_DEVICE_BENCHMARK_V11_SCHEMA,
    EMBEDDING_DEVICE_BENCHMARK_V11_SCHEMA_REF,
    BenchmarkExecutionPolicy,
    BenchmarkOwnerRequest,
    BenchmarkWorkerInvocation,
    benchmark_policy_schema_ref,
    benchmark_timeout_seconds,
    embedding_device_benchmark_bytes,
    parse_embedding_device_benchmark,
    parse_embedding_device_benchmark_bytes,
    validate_benchmark_invocation,
    validate_benchmark_staged_inputs,
)
from eom_catalog_contracts.validation import (
    CATALOG_SCHEMA_RESOURCES,
    catalog_schema_registry,
    load_schema,
    validate_contract,
)
from eom_identifiers import canonical_json_bytes, sha256_bytes
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError as SchemaError

from tests.unit.embedding_device_benchmark_fixtures import (
    benchmark_policy,
    owner_request,
    staged_inputs,
    worker_invocation,
    worker_result,
)
from tests.unit.inference_transfer_embedding_fixtures import seal

ROOT = Path(__file__).resolve().parents[2]


def successor_policy() -> BenchmarkExecutionPolicy:
    body = benchmark_policy().model_dump(mode="json")
    body.update(
        schema_version="embedding-device-benchmark-policy/1.1",
        policy_revision_id="embeddingbenchmarkpolicyrev_" + "8" * 32,
        timeout_seconds=600,
    )
    return BenchmarkExecutionPolicy.model_validate(seal(body, "policy_sha256"))


def successor_request() -> BenchmarkOwnerRequest:
    body = owner_request().model_dump(mode="json")
    body.update(
        schema_version="embedding-device-benchmark-request/1.1",
        execution_policy=successor_policy().model_dump(mode="json"),
    )
    return BenchmarkOwnerRequest.model_validate(seal(body, "request_sha256"))


def successor_invocation(ordinal: int = 1) -> BenchmarkWorkerInvocation:
    request = successor_request()
    body = worker_invocation(ordinal).model_dump(mode="json")
    body.update(
        schema_version="embedding-device-benchmark-invocation/1.1",
        owner_request_sha256=request.request_sha256,
        execution_policy=request.execution_policy.model_dump(mode="json"),
    )
    return BenchmarkWorkerInvocation.model_validate(seal(body, "invocation_sha256"))


def test_budget_successor_schema_mirror_pin_and_references_preserve_predecessor() -> None:
    old = CATALOG_SCHEMA_RESOURCES[EMBEDDING_DEVICE_BENCHMARK_SCHEMA]
    old_pin = "sha256:c8105987d684f6a276fe92361b830663487bdaa5df47c1eb47b6407dd1ee07ad"
    assert old.sha256 == sha256_bytes((ROOT / old.canonical_path).read_bytes()) == old_pin
    assert (
        sha256_bytes(
            (
                ROOT / "packages/catalog_contracts/eom_catalog_contracts" / old.resource_path
            ).read_bytes()
        )
        == old_pin
    )
    resource = CATALOG_SCHEMA_RESOURCES[EMBEDDING_DEVICE_BENCHMARK_V11_SCHEMA]
    canonical = (ROOT / resource.canonical_path).read_bytes()
    packaged = (
        ROOT / "packages/catalog_contracts/eom_catalog_contracts" / resource.resource_path
    ).read_bytes()
    assert canonical == packaged
    assert sha256_bytes(canonical) == resource.sha256
    schema = load_schema(EMBEDDING_DEVICE_BENCHMARK_V11_SCHEMA)
    Draft202012Validator.check_schema(schema)
    assert schema["$id"] == EMBEDDING_DEVICE_BENCHMARK_V11_SCHEMA_REF
    assert set(schema["$defs"]) == {"policy", "request", "invocation"}
    resolver = catalog_schema_registry().resolver()
    for family, definition in schema["$defs"].items():
        assert definition["additionalProperties"] is False
        assert set(definition["required"]) == set(definition["properties"])
        for name, field in definition["properties"].items():
            if name in {"schema_version", "timeout_seconds"}:
                continue
            expected = (
                "#/$defs/policy"
                if name == "execution_policy"
                else f"{EMBEDDING_DEVICE_BENCHMARK_SCHEMA_REF}#/$defs/{family}/properties/{name}"
            )
            assert field == {"$ref": expected}
            resolver.lookup(
                EMBEDDING_DEVICE_BENCHMARK_V11_SCHEMA_REF + expected
                if expected.startswith("#")
                else expected
            )


@pytest.mark.parametrize(
    "factory,expected_sha",
    (
        (
            benchmark_policy,
            "sha256:fc1dd8edf1f96621d1ba86e3ed5cdfca695eb065af09f82e4d48adece6630c84",
        ),
        (owner_request, "sha256:a709c69b6edffc5b9e9553554d12ba14ca15ac6052fea0c25ed5357ea45d8eeb"),
        (
            worker_invocation,
            "sha256:a493bf6d6fe6ed106c8cb83f3928cc5892aaee0ef49ef7847ff3d8657a07d0bc",
        ),
    ),
)
def test_original_default_construction_and_serialized_bytes_are_unchanged(
    factory: Any, expected_sha: str
) -> None:
    # Pins were independently read from the installed predecessor before source tests.
    value = factory()
    assert value.schema_version.endswith("/1.0")
    assert sha256_bytes(embedding_device_benchmark_bytes(value)) == expected_sha
    policy = value if isinstance(value, BenchmarkExecutionPolicy) else value.execution_policy
    assert benchmark_timeout_seconds(policy) == 180


@pytest.mark.parametrize("factory", (successor_policy, successor_request, successor_invocation))
def test_explicit_budget_successor_roundtrips_without_reinterpreting_common_leaves(
    factory: Any,
) -> None:
    value = factory()
    body = value.model_dump(mode="json")
    validate_contract(EMBEDDING_DEVICE_BENCHMARK_V11_SCHEMA, body)
    raw = embedding_device_benchmark_bytes(value)
    assert raw == canonical_json_bytes(body)
    assert parse_embedding_device_benchmark_bytes(raw) == value
    with pytest.raises((ValueError, SchemaError)):
        validate_contract(EMBEDDING_DEVICE_BENCHMARK_SCHEMA, body)
    policy = value if isinstance(value, BenchmarkExecutionPolicy) else value.execution_policy
    assert benchmark_timeout_seconds(policy) == 600
    assert policy.policy_sha256 != benchmark_policy().policy_sha256


@pytest.mark.parametrize("ordinal", range(1, 7))
def test_budget_successor_preserves_same_input_model_recipe_order_and_numerical_values(
    ordinal: int,
) -> None:
    request, invocation, inputs = (
        successor_request(),
        successor_invocation(ordinal),
        staged_inputs(),
    )
    validate_benchmark_staged_inputs(request, inputs)
    validate_benchmark_invocation(request, invocation, inputs)
    original_request, original_invocation = owner_request(), worker_invocation(ordinal)
    assert request.model_dump(exclude={"schema_version", "execution_policy", "request_sha256"}) == (
        original_request.model_dump(
            exclude={"schema_version", "execution_policy", "request_sha256"}
        )
    )
    assert invocation.model_dump(
        exclude={"schema_version", "execution_policy", "owner_request_sha256", "invocation_sha256"}
    ) == original_invocation.model_dump(
        exclude={"schema_version", "execution_policy", "owner_request_sha256", "invocation_sha256"}
    )


@pytest.mark.parametrize("version,timeout", (("1.0", 600), ("1.1", 180)))
def test_policy_rejects_timeout_borrowed_from_the_other_version(version: str, timeout: int) -> None:
    body = benchmark_policy().model_dump(mode="json")
    body.update(
        schema_version=f"embedding-device-benchmark-policy/{version}", timeout_seconds=timeout
    )
    body = seal(body, "policy_sha256")
    with pytest.raises(ValueError, match="timeout differs"):
        BenchmarkExecutionPolicy.model_validate(body)
    with pytest.raises((ValueError, SchemaError)):
        parse_embedding_device_benchmark(body)


@pytest.mark.parametrize("timeout", (True, False, 180.0, 600.0, "600", 599, 601, 900))
def test_policy_budget_requires_exact_declared_integer(timeout: Any) -> None:
    body = successor_policy().model_dump(mode="json")
    body["timeout_seconds"] = timeout
    if not isinstance(timeout, float):
        body = seal(body, "policy_sha256")
    with pytest.raises((ValueError, SchemaError)):
        BenchmarkExecutionPolicy.model_validate(body)
    with pytest.raises((ValueError, SchemaError)):
        parse_embedding_device_benchmark(body)


@pytest.mark.parametrize("family", ("request", "invocation"))
@pytest.mark.parametrize("version", ("1.0", "1.1"))
def test_envelopes_reject_mixed_execution_policy_versions(family: str, version: str) -> None:
    value = owner_request() if family == "request" else worker_invocation()
    model = BenchmarkOwnerRequest if family == "request" else BenchmarkWorkerInvocation
    body = value.model_dump(mode="json")
    body["schema_version"] = f"embedding-device-benchmark-{family}/{version}"
    body["execution_policy"] = (
        successor_policy() if version == "1.0" else benchmark_policy()
    ).model_dump(mode="json")
    body = seal(body, f"{family}_sha256")
    with pytest.raises(ValueError, match="versions differ"):
        model.model_validate(body)
    with pytest.raises((ValueError, SchemaError)):
        parse_embedding_device_benchmark(body)


def test_invocation_cannot_use_a_different_version_request_with_a_resealed_hash() -> None:
    body = successor_invocation().model_dump(mode="json")
    body["owner_request_sha256"] = owner_request().request_sha256
    invocation = BenchmarkWorkerInvocation.model_validate(seal(body, "invocation_sha256"))
    with pytest.raises((ValueError, SchemaError)):
        validate_benchmark_invocation(owner_request(), invocation, staged_inputs())


@pytest.mark.parametrize("mutation", ("hash", "timeout", "version", "extra"))
def test_public_budget_selection_revalidates_copied_or_constructed_policy(mutation: str) -> None:
    changes: dict[str, Any] = {
        "hash": {"policy_sha256": "sha256:" + "f" * 64},
        "timeout": {"timeout_seconds": 180},
        "version": {"schema_version": "embedding-device-benchmark-policy/9.0"},
        "extra": {"administrator": "invented"},
    }
    with pytest.raises((ValueError, SchemaError)):
        benchmark_timeout_seconds(successor_policy().model_copy(update=changes[mutation]))


def test_public_budget_selection_rejects_raw_bool_before_serializing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    value = successor_policy().model_copy(update={"timeout_seconds": True})

    def forbidden(*args: object, **kwargs: object) -> object:
        raise AssertionError("raw bool must be rejected before model serialization")

    monkeypatch.setattr(BenchmarkExecutionPolicy, "model_dump", forbidden)
    with pytest.raises((ValueError, SchemaError)):
        benchmark_timeout_seconds(value)


def test_policy_hash_is_not_recomputed_or_repaired_by_successor_validation() -> None:
    body = successor_policy().model_dump(mode="json")
    body["policy_sha256"] = benchmark_policy().policy_sha256
    with pytest.raises(ValueError, match="canonical benchmark content"):
        parse_embedding_device_benchmark(body)


def test_policy_artifact_schema_selection_is_exact_and_revalidates_the_policy() -> None:
    assert benchmark_policy_schema_ref(benchmark_policy()) == (
        EMBEDDING_DEVICE_BENCHMARK_SCHEMA_REF + "#/$defs/policy"
    )
    assert benchmark_policy_schema_ref(successor_policy()) == (
        EMBEDDING_DEVICE_BENCHMARK_V11_SCHEMA_REF + "#/$defs/policy"
    )
    with pytest.raises(ValueError):
        benchmark_policy_schema_ref(successor_policy().model_copy(update={"timeout_seconds": 180}))


@pytest.mark.parametrize("factory", (staged_inputs, worker_result))
def test_common_leaf_families_remain_v1_and_have_no_implicit_successor(factory: Any) -> None:
    body = factory().model_dump(mode="json")
    assert parse_embedding_device_benchmark(body) == factory()
    body["schema_version"] = body["schema_version"].removesuffix("1.0") + "1.1"
    with pytest.raises((ValueError, SchemaError)):
        parse_embedding_device_benchmark(body)


@pytest.mark.parametrize("version", ("embedding-device-benchmark-policy/1.2", [], {}, None))
def test_parser_has_no_latest_or_shape_based_budget_fallback(version: Any) -> None:
    body = successor_policy().model_dump(mode="json")
    body["schema_version"] = version
    with pytest.raises((ValueError, SchemaError)):
        parse_embedding_device_benchmark(body)
