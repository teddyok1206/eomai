"""Protocol-only device selection; no installation, model, authority or live admission."""

from __future__ import annotations

import ast
import io
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import eom_workflow
import pytest
from eom_identifiers import canonical_json_bytes, content_sha256, sha256_bytes
from eom_workflow.local_embedding_execution_policy import LocalEmbeddingServiceExecutionPolicy
from eom_workflow.local_indexing_owner_configuration import (
    LOCAL_INDEXING_MULTIVIEW_OWNER_SCHEMA_SHA256,
    LOCAL_INDEXING_NATIVE_OWNER_SCHEMA_SHA256,
    LOCAL_INDEXING_OWNER_SCHEMA_SHA256,
    LocalIndexingMultiviewOwnerConfiguration,
    LocalIndexingNativeOwnerConfiguration,
    LocalIndexingOwnerConfiguration,
    LocalIndexingOwnerConfigurationError,
    LocalIndexingRuntimeVerifierPin,
    local_indexing_native_owner_configuration_schema,
    local_indexing_owner_configuration_bytes,
    local_indexing_owner_configuration_schema,
    parse_local_indexing_owner_configuration,
    parse_supported_local_indexing_owner_configuration,
    require_native_index_owner_policy,
)
from eom_workflow.native_embedding_backend_selection import (
    NATIVE_EMBEDDING_BACKEND_SELECTION_SCHEMA_REF,
    NATIVE_EMBEDDING_BACKEND_SELECTION_SCHEMA_SHA256,
    NativeCpuBackendSelection,
    NativeCudaBackendSelection,
    NativeEmbeddingBackendSelection,
    NativeEmbeddingBackendSelectionError,
    native_embedding_backend_selection_bytes,
    native_embedding_backend_selection_schema,
    parse_native_embedding_backend_selection,
    select_native_index_runtime_profile,
)
from eom_workflow.schemas import local_embedding_admission_schema_registry
from jsonschema import Draft202012Validator

from tests.unit.local_embedding_admission_fixtures import native_fixture, runtime_profile
from tests.unit.local_embedding_service_fixtures import service_fixture
from tests.unit.test_local_indexing_multiview_owner import multiview_document
from tests.unit.test_local_indexing_owner_configuration import document

ROOT = Path(__file__).resolve().parents[2]


def backend_document(device="CPU", purpose="INDEX"):
    if device == "CPU":
        backend = {
            "device": device,
            "runtime_verifier": {
                "source_commit": "2" * 40,
                "script_raw_sha256": "sha256:" + "3" * 64,
            },
            "cpu_environment_raw_sha256": "sha256:" + "4" * 64,
        }
    else:
        backend = {
            "device": device,
            "configuration": {
                "configuration_id": "embeddingnativeconfig_" + "5" * 32,
                "configuration_revision_id": "embeddingnativeconfigrev_" + "6" * 32,
                "configuration_raw_sha256": "sha256:" + "7" * 64,
                "configuration_sha256": "sha256:" + "8" * 64,
            },
            "receipt_raw_sha256": "sha256:" + "9" * 64,
            "cuda_environment_raw_sha256": "sha256:" + "a" * 64,
        }
    return {
        "schema_version": "native-embedding-backend-selection/1.0",
        "purpose": purpose,
        "backend": backend,
    }


def owner_document(device="CPU", *, multiview=False):
    c = service_fixture(base=native_fixture(device=device))
    body = document() | {
        "schema_version": "local-indexing-owner-configuration/3.0",
        "namespace": c.request.namespace.model_dump(mode="json"),
        "recipe": c.base.plan.recipe.model_dump(mode="json"),
        "native_execution_policy": c.request.native_execution_policy.model_dump(mode="json"),
        "native_execution_policy_sha256": c.policy.policy_sha256,
        "runtime_profile": c.policy.profiles[0].model_dump(mode="json"),
        "native_backend": backend_document(device),
    }
    del body["runtime_verifier"], body["cpu_environment_raw_sha256"]
    body["additional_namespaces"] = (
        [body["namespace"] | {"view": view} for view in ("CONCRETE_FACETS", "METADATA_ONLY")]
        if multiview
        else []
    )
    return body, c.policy


def test_schema_first_mirrors_hashes_and_public_values_do_not_admit_a_runtime():
    for name, expected, loader in (
        (
            "native-embedding-backend-selection-v1.schema.json",
            NATIVE_EMBEDDING_BACKEND_SELECTION_SCHEMA_SHA256,
            native_embedding_backend_selection_schema,
        ),
        (
            "local-indexing-owner-configuration-v3.schema.json",
            LOCAL_INDEXING_NATIVE_OWNER_SCHEMA_SHA256,
            local_indexing_native_owner_configuration_schema,
        ),
    ):
        raw = (ROOT / "schemas/workflow" / name).read_bytes()
        assert raw == (ROOT / "packages/workflow/eom_workflow/resources" / name).read_bytes()
        assert sha256_bytes(raw) == expected
        schema = loader()
        Draft202012Validator.check_schema(schema)
        assert set(schema["required"]) == set(schema["properties"])
        schema["properties"].clear()
        assert loader()["properties"]
    backend = native_embedding_backend_selection_schema()
    assert (
        backend["$defs"]["runtimeVerifier"]
        == local_indexing_owner_configuration_schema()["properties"]["runtime_verifier"]
    )
    for name, model in (("cpu", NativeCpuBackendSelection), ("cuda", NativeCudaBackendSelection)):
        assert set(backend["$defs"][name]["required"]) == set(model.model_fields)
    assert eom_workflow.NativeEmbeddingBackendSelection is NativeEmbeddingBackendSelection
    assert eom_workflow.LocalIndexingRuntimeVerifierPin is LocalIndexingRuntimeVerifierPin
    assert (
        eom_workflow.LocalIndexingNativeOwnerConfiguration is LocalIndexingNativeOwnerConfiguration
    )
    # Pure deployment parsing is deliberately not Workflow/runtime admission registration.
    assert (
        NATIVE_EMBEDDING_BACKEND_SELECTION_SCHEMA_REF
        not in local_embedding_admission_schema_registry()
    )


@pytest.mark.parametrize("family", ["backend", "owner"])
def test_changed_packaged_schema_cannot_become_a_valid_source_contract(monkeypatch, family):
    from eom_workflow import local_indexing_owner_configuration as owner
    from eom_workflow import native_embedding_backend_selection as backend

    module, cache, loader, error = (
        (
            backend,
            backend._schema_raw,
            backend.native_embedding_backend_selection_schema,
            NativeEmbeddingBackendSelectionError,
        )
        if family == "backend"
        else (
            owner,
            owner._native_schema_raw,
            owner.local_indexing_native_owner_configuration_schema,
            LocalIndexingOwnerConfigurationError,
        )
    )
    original = canonical_json_bytes(loader())
    poisoned = SimpleNamespace(open=lambda _mode: io.BytesIO(original + b"\nchanged"))
    resource = SimpleNamespace(joinpath=lambda *_parts: poisoned)
    cache.cache_clear()
    try:
        with monkeypatch.context() as patch:
            patch.setattr(module, "files", lambda _: resource)
            with pytest.raises(error):
                loader()
    finally:
        cache.cache_clear()


@pytest.mark.parametrize("device", ["CPU", "CUDA"])
@pytest.mark.parametrize("purpose", ["INDEX", "REFERENCE_QUERY", "PRIVATE_CHAT_QUERY"])
def test_closed_backend_canonical_roundtrip_and_explicit_purposes(device, purpose):
    body = backend_document(device, purpose)
    value = NativeEmbeddingBackendSelection.model_validate(body)
    assert value.device == device and value.purpose == purpose
    assert value.model_dump(mode="json") == body
    raw = native_embedding_backend_selection_bytes(value)
    assert raw == canonical_json_bytes(body)
    assert parse_native_embedding_backend_selection(raw) == value


@pytest.mark.parametrize(
    "fault",
    (
        "auto",
        "benchmark",
        "raw_hash",
        "revision",
        "receipt",
        "missing_receipt",
        "cpu_field",
        "cuda_field",
        "path",
        "authority",
        "history",
        "verifier_bool",
        "verifier_path",
        "hidden_configuration",
    ),
)
def test_backend_denies_cross_family_latest_authority_and_coercion(fault):
    body = backend_document("CUDA")
    backend = body["backend"]
    if fault == "auto":
        backend["device"] = "AUTO"
    elif fault == "benchmark":
        body["purpose"] = "BENCHMARK"
    elif fault in {"raw_hash", "revision", "hidden_configuration"}:
        key, value = {
            "raw_hash": ("configuration_raw_sha256", "f" * 64),
            "revision": ("configuration_revision_id", "latest"),
            "hidden_configuration": ("operator_id", "operator_" + "1" * 32),
        }[fault]
        backend["configuration"][key] = value
    elif fault == "receipt":
        backend["receipt_raw_sha256"] = True
    elif fault == "missing_receipt":
        del backend["receipt_raw_sha256"]
    elif fault == "cpu_field":
        backend["cpu_environment_raw_sha256"] = "sha256:" + "0" * 64
    elif fault in {"cuda_field", "verifier_bool", "verifier_path"}:
        body = backend_document()
        if fault == "cuda_field":
            body["backend"]["receipt_raw_sha256"] = "sha256:" + "0" * 64
        else:
            body["backend"]["runtime_verifier"]["source_commit"] = (
                True if fault == "verifier_bool" else "/tmp/untrusted.py"
            )
    elif fault == "path":
        backend["socket"] = "/tmp/untrusted.sock"
    elif fault == "authority":
        body["roles"] = ["ADMIN"]
    else:
        body["retained_cpu_reads"] = []
    with pytest.raises(ValueError, match="NATIVE_EMBEDDING_BACKEND_SELECTION_INVALID"):
        NativeEmbeddingBackendSelection.model_validate(body)


@pytest.mark.parametrize("fault", ["extra", "device", "configuration", "missing"])
def test_backend_serializer_revalidates_forged_frozen_copies(fault):
    value = NativeEmbeddingBackendSelection.model_validate(backend_document("CUDA"))
    if fault == "extra":
        value = value.model_copy(update={"operator_id": "operator_" + "1" * 32})
    elif fault == "device":
        value = value.model_copy(
            update={"backend": value.backend.model_copy(update={"device": "CPU"})}
        )
    elif fault == "configuration":
        value = value.model_copy(
            update={"backend": value.backend.model_copy(update={"configuration": {}})}
        )
    else:
        value = NativeEmbeddingBackendSelection.model_construct(purpose="INDEX")
    with pytest.raises(NativeEmbeddingBackendSelectionError):
        native_embedding_backend_selection_bytes(value)


@pytest.mark.parametrize("fault", ["duplicate", "newline", "float", "oversized", "not_bytes"])
def test_backend_wire_parser_never_repairs_external_bytes(fault):
    raw = canonical_json_bytes(backend_document())
    if fault == "duplicate":
        raw = raw.replace(b'"purpose":"INDEX"', b'"purpose":"INDEX","purpose":"INDEX"')
    elif fault == "newline":
        raw += b"\n"
    elif fault == "float":
        raw = raw.replace(b'"purpose":"INDEX"', b'"purpose":1.0')
    elif fault == "oversized":
        raw = b" " * (16 * 1024 + 1)
    else:
        raw = raw.decode()
    with pytest.raises(NativeEmbeddingBackendSelectionError):
        parse_native_embedding_backend_selection(raw)


@pytest.mark.parametrize("device", ["CPU", "CUDA"])
@pytest.mark.parametrize("multiview", [False, True])
def test_index_successor_matches_device_and_resolved_policy_without_runtime_admission(
    device, multiview
):
    body, policy = owner_document(device, multiview=multiview)
    value = LocalIndexingNativeOwnerConfiguration.model_validate(body)
    assert len(value.namespaces) == (3 if multiview else 1)
    raw = local_indexing_owner_configuration_bytes(value)
    assert parse_supported_local_indexing_owner_configuration(raw) == value
    assert (
        select_native_index_runtime_profile(value.native_backend, policy) == value.runtime_profile
    )
    require_native_index_owner_policy(value, policy)
    # Executable CPU-only owners retain their old parser, including for CPU-flavored v3.
    with pytest.raises(LocalIndexingOwnerConfigurationError):
        parse_local_indexing_owner_configuration(raw)


@pytest.mark.parametrize(
    "fault",
    (
        "purpose",
        "device",
        "space",
        "recipe",
        "population",
        "projection",
        "partition",
        "duplicate",
        "too_many",
        "authority",
        "cpu_top_level",
        "old_policy",
        "maximum",
    ),
)
def test_index_successor_rejects_mixed_selection_or_weakened_existing_rules(fault):
    body, _ = owner_document("CUDA", multiview=True)
    if fault == "purpose":
        body["native_backend"]["purpose"] = "PRIVATE_CHAT_QUERY"
    elif fault == "device":
        body["native_backend"] = backend_document("CPU")
    elif fault in {"space", "recipe"}:
        body["additional_namespaces"][0][fault + "_sha256"] = "sha256:" + "f" * 64
    elif fault in {"population", "projection", "partition"}:
        key, value = {
            "population": ("population_scope", "OCCURRENCE_BACKED_PAST_EXAM"),
            "projection": ("projection_version", "latest"),
            "partition": ("storage_partition", "another-partition"),
        }[fault]
        body["additional_namespaces"][0][key] = value
    elif fault == "duplicate":
        body["additional_namespaces"][0] = deepcopy(body["namespace"])
    elif fault == "too_many":
        body["additional_namespaces"].append(deepcopy(body["namespace"]))
    elif fault == "authority":
        body["actor"] = "ADMIN"
    elif fault == "cpu_top_level":
        body["cpu_environment_raw_sha256"] = "sha256:" + "f" * 64
    elif fault == "old_policy":
        body["native_execution_policy"]["schema_ref"] = (
            "eom://schemas/workflow/local-embedding-execution-policy/1.0"
        )
    else:
        body["maximum_targets"] = body["maximum_sources"] + 1
    with pytest.raises(ValueError, match="LOCAL_INDEXING_OWNER_CONFIGURATION_INVALID"):
        LocalIndexingNativeOwnerConfiguration.model_validate(body)


@pytest.mark.parametrize("fault", ["default", "profile", "hash", "forged_policy", "forged_owner"])
def test_resolved_service_policy_default_profile_and_semantic_hash_must_match(fault):
    body, policy = owner_document("CUDA")
    value = LocalIndexingNativeOwnerConfiguration.model_validate(body)
    if fault == "default":
        policy = service_fixture().policy
        body["native_execution_policy_sha256"] = policy.policy_sha256
        value = LocalIndexingNativeOwnerConfiguration.model_validate(body)
    elif fault == "profile":
        changed = policy.model_dump(mode="json")
        resource = changed["profiles"][0]["resource_profile"]
        resource["timeout_seconds"] += 1
        resource["resource_profile_sha256"] = content_sha256(
            {key: val for key, val in resource.items() if key != "resource_profile_sha256"}
        )
        changed["policy_sha256"] = content_sha256(
            {key: val for key, val in changed.items() if key != "policy_sha256"}
        )
        policy = LocalEmbeddingServiceExecutionPolicy.model_validate(changed)
        body["native_execution_policy_sha256"] = policy.policy_sha256
        value = LocalIndexingNativeOwnerConfiguration.model_validate(body)
    elif fault == "hash":
        value = value.model_copy(update={"native_execution_policy_sha256": "sha256:" + "f" * 64})
    elif fault == "forged_policy":
        policy = policy.model_copy(update={"default_device": "AUTO"})
    else:
        value = value.model_copy(update={"roles": ["ADMIN"]})
    with pytest.raises(LocalIndexingOwnerConfigurationError):
        require_native_index_owner_policy(value, policy)


@pytest.mark.parametrize("fault", ["extra", "nested_extra", "missing", "device"])
def test_index_successor_serializer_revalidates_forged_models(fault):
    value = LocalIndexingNativeOwnerConfiguration.model_validate(owner_document("CUDA")[0])
    if fault == "extra":
        value = value.model_copy(update={"permissions": ["ADMIN"]})
    elif fault == "nested_extra":
        value = value.model_copy(
            update={"native_backend": value.native_backend.model_copy(update={"socket": "/tmp/a"})}
        )
    elif fault == "missing":
        value = LocalIndexingNativeOwnerConfiguration.model_construct(
            schema_version="local-indexing-owner-configuration/3.0"
        )
    else:
        value = value.model_copy(
            update={
                "native_backend": NativeEmbeddingBackendSelection.model_validate(backend_document())
            }
        )
    with pytest.raises(LocalIndexingOwnerConfigurationError):
        local_indexing_owner_configuration_bytes(value)


@pytest.mark.parametrize("fault", ["duplicate", "newline", "boolean", "oversized", "not_bytes"])
def test_supported_owner_parser_keeps_existing_exact_canonical_boundary(fault):
    raw = canonical_json_bytes(owner_document()[0])
    if fault == "duplicate":
        raw = raw.replace(b'"maximum_targets":64', b'"maximum_targets":64,"maximum_targets":64')
    elif fault == "newline":
        raw += b"\n"
    elif fault == "boolean":
        raw = raw.replace(b'"maximum_targets":64', b'"maximum_targets":true')
    elif fault == "oversized":
        raw = b" " * (64 * 1024 + 1)
    else:
        raw = raw.decode()
    with pytest.raises(LocalIndexingOwnerConfigurationError):
        parse_supported_local_indexing_owner_configuration(raw)


def test_default_dispatch_rule_is_explicit_and_never_borrows_query_or_benchmark_purpose():
    body, _ = owner_document("CPU")
    policy = service_fixture().policy.model_dump(mode="json")
    policy["profiles"] = [runtime_profile(d).model_dump(mode="json") for d in ("CPU", "CUDA")]
    policy["policy_sha256"] = content_sha256(
        {key: value for key, value in policy.items() if key != "policy_sha256"}
    )
    parsed = LocalEmbeddingServiceExecutionPolicy.model_validate(policy)
    cpu = NativeEmbeddingBackendSelection.model_validate(body["native_backend"])
    assert select_native_index_runtime_profile(cpu, parsed).resource_profile.device == "CPU"
    for selection in (
        backend_document("CUDA"),
        backend_document("CPU", "REFERENCE_QUERY"),
        backend_document("CPU", "PRIVATE_CHAT_QUERY"),
    ):
        with pytest.raises(NativeEmbeddingBackendSelectionError):
            select_native_index_runtime_profile(
                NativeEmbeddingBackendSelection.model_validate(selection), parsed
            )


def test_legacy_cpu_schema_bytes_verifier_identity_and_wire_meaning_stay_exact():
    for version, expected, body, model in (
        (1, LOCAL_INDEXING_OWNER_SCHEMA_SHA256, document(), LocalIndexingOwnerConfiguration),
        (
            2,
            LOCAL_INDEXING_MULTIVIEW_OWNER_SCHEMA_SHA256,
            multiview_document(),
            LocalIndexingMultiviewOwnerConfiguration,
        ),
    ):
        name = f"local-indexing-owner-configuration-v{version}.schema.json"
        raw = (ROOT / "schemas/workflow" / name).read_bytes()
        assert sha256_bytes(raw) == expected
        assert raw == (ROOT / "packages/workflow/eom_workflow/resources" / name).read_bytes()
        encoded = canonical_json_bytes(body)
        legacy = parse_local_indexing_owner_configuration(encoded)
        assert type(legacy) is model
        assert legacy.model_dump(mode="json") == body
        assert type(legacy.runtime_verifier) is LocalIndexingRuntimeVerifierPin
        assert local_indexing_owner_configuration_bytes(legacy) == encoded
        assert parse_supported_local_indexing_owner_configuration(encoded) == legacy


@pytest.mark.parametrize("device", ["CPU", "CUDA"])
def test_unchanged_runtime_rejects_successor_before_engine_or_queue_claim(monkeypatch, device):
    from eom_identity_service.local_indexing_runtime import (
        AuthenticatedLocalIndexingRuntime,
        LocalIndexingRuntimePin,
    )
    from eom_workflow_runner import local_indexing_service_runtime as composition

    raw = canonical_json_bytes(owner_document(device)[0])
    # IO is deliberately replaced only at the protected read seam, not at the parser.
    capture = object.__new__(AuthenticatedLocalIndexingRuntime)
    pin = object.__new__(LocalIndexingRuntimePin)
    monkeypatch.setattr(
        AuthenticatedLocalIndexingRuntime, "read_owner_configuration", lambda _: raw
    )
    engine = Mock(side_effect=AssertionError("unsupported schema must precede DB/claim"))
    monkeypatch.setattr(composition, "build_native_embedding_controller_engine", engine)
    with pytest.raises(LocalIndexingOwnerConfigurationError):
        composition.build_local_indexing_service_runtime(capture, pin)
    engine.assert_not_called()


def test_contract_dependency_direction_has_no_device_or_storage_adapter():
    path = ROOT / "packages/workflow/eom_workflow/native_embedding_backend_selection.py"
    tree = ast.parse(path.read_text())
    roots = {
        node.module.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    }
    assert not roots & {
        "eom_catalog_service",
        "eom_orchestrator",
        "eom_identity_service",
        "eom_workflow_runner",
        "sqlalchemy",
        "subprocess",
        "torch",
        "transformers",
        "httpx",
    }
    # Shared CUDA installation pins come from the contract package, not the infra DTO.
    assert "embedding_native_backend_pins" not in path.read_text()
