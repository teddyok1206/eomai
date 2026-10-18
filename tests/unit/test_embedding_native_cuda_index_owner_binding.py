"""Pure owner-binding schema/model parity only; no root or actual process authority."""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any

import pytest
from eom_catalog_contracts.embedding_native_cuda_index_owner_binding import (
    MAX_NATIVE_CUDA_INDEX_OWNER_BINDING_BYTES,
    NATIVE_CUDA_INDEX_OWNER_BINDING_SCHEMA,
    NativeCudaIndexOwnerBinding,
    native_cuda_index_owner_binding_bytes,
    parse_native_cuda_index_owner_binding,
)
from eom_catalog_contracts.validation import CATALOG_SCHEMA_RESOURCES, load_schema
from eom_identifiers import canonical_json_bytes, content_sha256, sha256_bytes
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError as SchemaError

INVALID = (ValueError, TypeError, SchemaError)


def body() -> dict[str, Any]:
    value = {
        "schema_version": "embedding-native-cuda-index-owner-binding/1.0",
        "execution_id": "a" * 32,
        "launch_association_sha256": "sha256:" + "b" * 64,
        "owner_pid": 1234,
        "owner_start_ticks": 5678,
    }
    return value | {"binding_sha256": content_sha256(value)}


def test_schema_mirror_loader_hash_and_frozen_round_trip() -> None:
    root = Path(__file__).resolve().parents[2]
    resource = CATALOG_SCHEMA_RESOURCES[NATIVE_CUDA_INDEX_OWNER_BINDING_SCHEMA]
    raw = (root / resource.canonical_path).read_bytes()
    assert sha256_bytes(raw) == resource.sha256
    assert (
        raw
        == (
            root / "packages/catalog_contracts/eom_catalog_contracts" / resource.resource_path
        ).read_bytes()
    )
    schema = load_schema(NATIVE_CUDA_INDEX_OWNER_BINDING_SCHEMA)
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(body())
    value = NativeCudaIndexOwnerBinding.model_validate(body())
    encoded = native_cuda_index_owner_binding_bytes(value)
    assert len(encoded) < MAX_NATIVE_CUDA_INDEX_OWNER_BINDING_BYTES
    assert parse_native_cuda_index_owner_binding(encoded) == value
    assert set(NativeCudaIndexOwnerBinding.model_fields) == set(body())
    assert not any(
        hasattr(value, name)
        for name in ("job_id", "request", "backend", "device", "root_ack", "source_grant")
    )
    with pytest.raises(ValueError):
        value.owner_pid = 2


@pytest.mark.parametrize(
    "field,value",
    (
        ("schema_version", "embedding-benchmark-owner/1.0"),
        ("execution_id", "../a"),
        ("execution_id", "a" * 32 + "\n"),
        ("launch_association_sha256", "sha256:" + "B" * 64),
        ("owner_pid", True),
        ("owner_pid", 0),
        ("owner_pid", 2147483648),
        ("owner_pid", "1234"),
        ("owner_start_ticks", False),
        ("owner_start_ticks", 0),
        ("owner_start_ticks", 2**64),
        ("owner_start_ticks", "5678"),
        ("root_ack", True),
        ("device", "CUDA"),
        ("backend", "CPU"),
        ("job_id", "job_" + "c" * 32),
    ),
)
def test_wire_and_model_refuse_coercion_extra_authority_and_other_identity(
    field: str, value: Any
) -> None:
    changed = body() | {field: value}
    with pytest.raises(INVALID):
        NativeCudaIndexOwnerBinding.model_validate(changed)
    with pytest.raises(SchemaError):
        Draft202012Validator(load_schema(NATIVE_CUDA_INDEX_OWNER_BINDING_SCHEMA)).validate(changed)


@pytest.mark.parametrize("field", ("owner_pid", "owner_start_ticks"))
def test_integral_float_lexemes_are_rejected_before_schema_coercion(field: str) -> None:
    changed = body()
    changed[field] = float(changed[field])
    # JSON Schema's integer is mathematical; the canonical wire/parser and strict
    # model additionally reject a floating lexeme rather than claiming otherwise.
    Draft202012Validator(load_schema(NATIVE_CUDA_INDEX_OWNER_BINDING_SCHEMA)).validate(changed)
    with pytest.raises(INVALID):
        NativeCudaIndexOwnerBinding.model_validate(changed)


@pytest.mark.parametrize(
    "field", ("owner_pid", "owner_start_ticks", "execution_id", "launch_association_sha256")
)
def test_semantic_hash_binds_each_original_value(field: str) -> None:
    changed = body()
    changed[field] = (
        changed[field] + 1
        if isinstance(changed[field], int)
        else ("d" * 32 if field == "execution_id" else "sha256:" + "d" * 64)
    )
    with pytest.raises(ValueError, match="HASH_INVALID"):
        NativeCudaIndexOwnerBinding.model_validate(changed)


@pytest.mark.parametrize("fault", ("extra_copy", "bool_copy", "missing_construct"))
def test_copied_or_constructed_models_are_revalidated(fault: str) -> None:
    value = NativeCudaIndexOwnerBinding.model_validate(body())
    if fault == "extra_copy":
        value = value.model_copy(update={"root_ack": True})
    elif fault == "bool_copy":
        value = value.model_copy(update={"owner_pid": True})
    else:
        value = NativeCudaIndexOwnerBinding.model_construct(
            **{k: v for k, v in body().items() if k != "owner_pid"}
        )
    with pytest.raises(INVALID):
        native_cuda_index_owner_binding_bytes(value)


@pytest.mark.parametrize("fault", ("duplicate", "trailing", "oversize", "nonbytes", "float"))
def test_raw_parser_is_unique_canonical_and_bounded(fault: str) -> None:
    raw: Any = canonical_json_bytes(body())
    if fault == "duplicate":
        raw = b'{"owner_pid":9,' + raw[1:]
    elif fault == "trailing":
        raw += b"\n"
    elif fault == "oversize":
        raw = b"x" * (MAX_NATIVE_CUDA_INDEX_OWNER_BINDING_BYTES + 1)
    elif fault == "nonbytes":
        raw = raw.decode()
    else:
        raw = raw.replace(b'"owner_pid":1234', b'"owner_pid":1234.0')
    with pytest.raises(INVALID):
        parse_native_cuda_index_owner_binding(raw)


def test_contract_has_no_runtime_workflow_or_infrastructure_dependency() -> None:
    import eom_catalog_contracts.embedding_native_cuda_index_owner_binding as contract

    modules = [
        node.module or ""
        for node in ast.walk(ast.parse(Path(contract.__file__).read_text()))
        if isinstance(node, ast.ImportFrom)
    ]
    assert not any(
        name.startswith(("eom_catalog_service", "eom_orchestrator", "eom_workflow"))
        for name in modules
    )
