"""Closed root installation input1.1, synthetic archive metadata, no native admission."""

from __future__ import annotations

import copy
from dataclasses import asdict
from pathlib import Path
from typing import Any, Literal

import pytest
from eom_catalog_contracts.embedding_host_configuration import parse_host_configuration_snapshot
from eom_catalog_contracts.validation import (
    CATALOG_SCHEMA_RESOURCES,
    load_schema,
    validate_contract,
)
from eom_catalog_service import embedding_host_configuration_capture as capture
from eom_catalog_service import embedding_runtime_prefix_closure as prefix
from eom_catalog_service.embedding_runtime_files import (
    InstalledRuntimeProofError,
    NumericalRuntimeFileSnapshots,
)
from eom_identifiers import canonical_json_bytes, content_sha256, sha256_bytes
from jsonschema import Draft202012Validator

from tests.unit.test_embedding_host_configuration_contracts import snapshot_body, snapshot_pointer
from tests.unit.test_embedding_runtime_prefix_closure import _fixture, _input

ROOT = Path(__file__).resolve().parents[2]
SCHEMA = "embedding-prefix-audit-input-v1.1"


@pytest.fixture(params=("CPU_INDEX_FP32", "CUDA_INDEX_FP32"))
def value(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, request: pytest.FixtureRequest
) -> dict[str, Any]:
    profile: Literal["CPU_INDEX_FP32", "CUDA_INDEX_FP32"] = request.param
    plan, _staged, owned, _helper, _locks = _fixture(tmp_path, monkeypatch, profile=profile)
    with owned:
        body = _input(plan)
    count = 55 if profile == "CPU_INDEX_FP32" else 70
    body["public_archives"].extend(
        {
            "filename": f"unused_{i:03d}-1.0-py3-none-any.whl",
            "size_bytes": 1,
            "sha256": "sha256:" + "a" * 64,
        }
        for i in range(count - len(body["public_archives"]))
    )
    body["public_archives"].sort(key=lambda item: item["filename"])
    monkeypatch.setattr(prefix, "_COUNTS", {"CPU_INDEX_FP32": 55, "CUDA_INDEX_FP32": 70})
    snapshot = parse_host_configuration_snapshot(snapshot_body())
    body.update(
        schema_version="embedding-prefix-audit-input/1.1",
        host_configuration=snapshot_pointer(snapshot).model_dump(mode="json"),
        host_seed_sha256=snapshot.host_seed_sha256,
    )
    body["bootstrap"] = [
        {"filename": name, "sha256": "sha256:" + "b" * 64, "size_bytes": 1}
        for name in sorted(prefix._SNAPSHOT_BOOTSTRAP)
    ]
    return body


def test_closed_schema_mirror_hash_and_318_predecessors_remain_frozen() -> None:
    schema = load_schema(SCHEMA)
    Draft202012Validator.check_schema(schema)
    assert schema["$id"] == "eom://schemas/knowledge/embedding-prefix-audit-input/1.1"
    assert schema["additionalProperties"] is False and "host_configuration" in schema["required"]
    resource = CATALOG_SCHEMA_RESOURCES[SCHEMA]
    raw = (ROOT / resource.canonical_path).read_bytes()
    assert (
        raw
        == (
            ROOT / "packages/catalog_contracts/eom_catalog_contracts" / resource.resource_path
        ).read_bytes()
    )
    assert sha256_bytes(raw) == resource.sha256
    previous = {
        name: item
        for name, item in CATALOG_SCHEMA_RESOURCES.items()
        if name
        not in {
            SCHEMA,
            "embedding-cuda-host-extension",
            "embedding-native-runtime-config-v1.2",
            "embedding-prefix-audit-input-v1.2",
            "embedding-cuda-host-extension-v1.1",
            "embedding-native-runtime-config-v1.3",
            "embedding-prefix-audit-input-v1.3",
            "embedding-native-cuda-probe",
            "embedding-native-cuda-probe-lease-ready",
            "system-rag-exam-observation",
            "system-rag-exam-observation-read",
            "system-rag-private-chat-similarity",
            "embedding-private-chat-query",
            "system-rag-private-chat-query-basis",
            # Additive contracts released after the pinned 318-schema baseline.
            "embedding-benchmark-cuda-ready",
            "general-chat-private-query-read",
            "system-rag-private-chat-query-prepare",
            "chat-private-query-scope",
        }
    }
    assert len(previous) == 318
    assert (
        content_sha256({name: asdict(item) for name, item in previous.items()})
        == "sha256:69baab14da4b9fca83ea011f3daef1b846115a9fcd946213db06e54ccb50a24c"
    )
    for item in previous.values():
        before = (ROOT / item.canonical_path).read_bytes()
        assert sha256_bytes(before) == item.sha256
        assert (
            before
            == (
                ROOT / "packages/catalog_contracts/eom_catalog_contracts" / item.resource_path
            ).read_bytes()
        )


def test_explicit_successor_has_seven_pins_and_strict_predecessor_still_requires_six(
    value: dict[str, Any],
) -> None:
    validate_contract(SCHEMA, value)
    selected = prefix.parse_installed_embedding_prefix_audit_input(canonical_json_bytes(value))
    assert selected.host_configuration is not None
    assert (
        selected.host_configuration.configuration_revision_id
        == value["host_configuration"]["configuration_revision_id"]
    )
    assert len(selected.bootstrap) == 7 and selected.plan.conda.profile == value["profile"]
    with pytest.raises(InstalledRuntimeProofError, match="INPUT_INVALID"):
        prefix.parse_embedding_prefix_audit_input(canonical_json_bytes(value))
    legacy = copy.deepcopy(value)
    legacy["schema_version"] = "embedding-prefix-audit-input/1.0"
    del legacy["host_configuration"]
    legacy["bootstrap"] = [
        item for item in legacy["bootstrap"] if item["filename"] in prefix._BOOTSTRAP
    ]
    raw = canonical_json_bytes(legacy)
    plan, seed, pins = prefix.parse_embedding_prefix_audit_input(raw)
    before = prefix.parse_installed_embedding_prefix_audit_input(raw)
    assert (plan, seed, pins) == (before.plan, before.host_seed_sha256, before.bootstrap)
    assert len(pins) == 6 and before.host_configuration is None


@pytest.mark.parametrize(
    "fault",
    (
        "unknown_version",
        "missing_snapshot",
        "unknown",
        "path",
        "bool",
        "module_missing",
        "module_duplicate",
        "module_unpinned",
        "legacy_smuggling",
        "count",
    ),
)
def test_invalid_version_pointer_or_bootstrap_never_falls_back_to_legacy(
    value: dict[str, Any], fault: str
) -> None:
    if fault == "unknown_version":
        value["schema_version"] = "embedding-prefix-audit-input/1.2"
    elif fault == "missing_snapshot":
        del value["host_configuration"]
    elif fault == "unknown":
        value["authority"] = "ROOT"
    elif fault == "path":
        value["host_configuration"]["path"] = "/tmp/untrusted"
    elif fault == "bool":
        value["host_configuration"]["manifest_byte_count"] = True
    elif fault == "module_missing":
        value["bootstrap"].pop()
    elif fault == "module_duplicate":
        value["bootstrap"][-1] = value["bootstrap"][0]
    elif fault == "module_unpinned":
        value["bootstrap"][1]["sha256"] = "version-only"
    elif fault == "legacy_smuggling":
        value["schema_version"] = "embedding-prefix-audit-input/1.0"
    else:
        value["public_archives"].pop()
    with pytest.raises(InstalledRuntimeProofError, match="INPUT_INVALID"):
        prefix.parse_installed_embedding_prefix_audit_input(canonical_json_bytes(value))


def test_host_capture_uses_snapshot_owner_once_without_legacy_fallback(
    value: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    selected = prefix.parse_installed_embedding_prefix_audit_input(canonical_json_bytes(value))
    files = NumericalRuntimeFileSnapshots(0)
    actual, mount, host = object(), object(), object()
    events: list[str] = []

    def resolve(pin: object) -> Any:
        assert pin is selected.host_configuration
        events.append("resolve")
        return actual

    def require_mount(config: object) -> Any:
        assert config is actual
        events.append("mount")
        return mount

    def capture_host(**kwargs: Any) -> Any:
        assert kwargs == {
            "expected_seed_sha256": selected.host_seed_sha256,
            "files": files,
            "snapshot_mount": mount,
        }
        events.append("capture")
        return host

    def denied(**kwargs: Any) -> Any:
        pytest.fail("snapshot failure must never use the old global-cache reader")

    monkeypatch.setattr(capture, "resolve_host_configuration_snapshot", resolve)
    monkeypatch.setattr(capture, "require_host_configuration_snapshot_mount", require_mount)
    monkeypatch.setattr(capture, "capture_snapshot_embedding_host", capture_host)
    monkeypatch.setattr(prefix, "capture_protected_embedding_host", denied)
    assert prefix.capture_prefix_audit_host(selected, files=files) is host
    assert events == ["resolve", "mount", "capture"]
