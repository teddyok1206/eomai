"""Synthetic protected-reader composition; not a live owner seal or runtime admission."""

from __future__ import annotations

import ast
import grp
import inspect
import json
import os
import pwd
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from eom_catalog_contracts.embedding_installed_runtime_proof import installed_runtime_proof_bytes
from eom_catalog_contracts.embedding_native_installation_evidence import (
    RootLocalNativeConfigurationPin,
    parse_rootlocal_native_admission_receipt_metadata,
    parse_rootlocal_prefix_inventory_candidate,
    rootlocal_native_admission_receipt_metadata_bytes,
    rootlocal_prefix_inventory_candidate_bytes,
)
from eom_catalog_contracts.embedding_native_runtime_config import (
    embedding_native_runtime_config_bytes,
)
from eom_catalog_contracts.embedding_runtime_bundle import embedding_runtime_bundle_bytes
from eom_catalog_service import embedding_native_installation_admission as admission
from eom_catalog_service.embedding_native_installation_admission import (
    NativeInstallationAdmissionError,
    ProtectedNativeEmbeddingInstallationAdmission,
)
from eom_catalog_service.embedding_runtime_prefix_closure import PrefixRuntimeInventory
from eom_identifiers import canonical_json_bytes, sha256_bytes

from tests.unit.embedding_native_runtime_config_fixtures import native_config_metadata
from tests.unit.inference_transfer_embedding_fixtures import seal
from tests.unit.test_embedding_native_installation_evidence import (
    INVENTORY_DRAFT,
    RECEIPT_DRAFT,
    inventory_body,
    receipt_body,
)

PREFIX = Path("/opt/eom/conda/envs/eom-embedding-index-cpu")


@dataclass
class Scenario:
    configuration: RootLocalNativeConfigurationPin
    receipt_pin: str
    files: dict[Path, bytes]
    boot: str
    uid: int = 2013
    gid: int = 2013
    primary_gid: int = 2013
    groups: tuple[int, ...] = (2013,)
    broken: str | None = None
    events: list[str] = field(default_factory=list)
    reads: list[Path] = field(default_factory=list)
    host_closes: int = 0

    def capture(self) -> ProtectedNativeEmbeddingInstallationAdmission:
        return ProtectedNativeEmbeddingInstallationAdmission(
            self.configuration, expected_receipt_raw_sha256=self.receipt_pin
        )

    def assert_current(
        self, captured: ProtectedNativeEmbeddingInstallationAdmission, **changes: Any
    ) -> None:
        arguments: dict[str, Any] = {
            "profile": "CPU_INDEX_FP32",
            "configuration_id": self.configuration.configuration_id,
            "configuration_revision_id": self.configuration.configuration_revision_id,
            "configuration_raw_sha256": self.configuration.configuration_raw_sha256,
        } | changes
        check: Callable[..., object] = captured.assert_current
        assert check(**arguments) is None


@pytest.fixture
def state(monkeypatch: pytest.MonkeyPatch) -> Scenario:
    config, bundle, proof = native_config_metadata()
    candidate = parse_rootlocal_prefix_inventory_candidate(
        canonical_json_bytes(inventory_body()), schema_raw=INVENTORY_DRAFT.read_bytes()
    )
    body = receipt_body(candidate, config)
    body["unit_probe"]["unit_template_sha256"] = sha256_bytes(b"synthetic fixed unit")
    body["unit_probe"]["probe_code_sha256"] = sha256_bytes(b"synthetic fixed probe")
    receipt = parse_rootlocal_native_admission_receipt_metadata(
        canonical_json_bytes(seal(body, "receipt_sha256")), schema_raw=RECEIPT_DRAFT.read_bytes()
    )
    raw = rootlocal_native_admission_receipt_metadata_bytes(receipt)
    base = admission._EVIDENCE_ROOT / config.configuration_id / config.configuration_revision_id
    files = {
        base / "receipt.json": raw,
        base / "inventory.json": rootlocal_prefix_inventory_candidate_bytes(candidate),
        admission._EVIDENCE_ROOT
        / "schemas/admission-receipt-v1.schema.json": RECEIPT_DRAFT.read_bytes(),
        admission._EVIDENCE_ROOT
        / "schemas/prefix-inventory-v1.schema.json": INVENTORY_DRAFT.read_bytes(),
        admission._CONFIG_ROOT
        / config.configuration_id
        / config.configuration_revision_id
        / "config.json": embedding_native_runtime_config_bytes(config),
        admission._PROOF_ROOT
        / proof.proof_id
        / proof.proof_revision_id
        / "proof.json": installed_runtime_proof_bytes(proof),
        admission._BUNDLE_ROOT
        / bundle.bundle_id
        / bundle.bundle_revision_id
        / "bundle.json": embedding_runtime_bundle_bytes(bundle),
        admission._UNIT_PATH: b"synthetic fixed unit",
        PREFIX / admission._PROBE_MEMBER: b"synthetic fixed probe",
    }
    value = Scenario(receipt.configuration, sha256_bytes(raw), files, candidate.boot_id)

    class Files:
        def __init__(self, owner_uid: int) -> None:
            assert owner_uid == 0

        def read(self, path: Path, *, sha256: str, maximum: int) -> bytes:
            value.reads.append(path)
            payload = value.files[path]
            if not 0 < len(payload) <= maximum or sha256_bytes(payload) != sha256:
                raise ValueError("synthetic protected file hash/size failure")
            return payload

        def assert_unchanged(self) -> None:
            value.events.append("file-epochs")
            if value.broken == "files":
                raise ValueError("synthetic file/ancestor/ACL drift")

    class Host:
        def assert_current(self) -> None:
            value.events.append("host-epochs")
            if value.broken == "host":
                raise ValueError("synthetic host epoch drift")

        def close(self) -> None:
            value.host_closes += 1
            if value.broken == "close":
                raise ValueError("synthetic host cleanup failure")

    def host(*, expected_seed_sha256: str, files: object) -> Host:
        value.events.append("host-capture")
        assert expected_seed_sha256 == candidate.host_seed_sha256 and isinstance(files, Files)
        return Host()

    def prefix_current(current: PrefixRuntimeInventory) -> None:
        value.events.append("prefix-epochs")
        assert current.prefix == PREFIX and current.owner_uid == 0
        assert tuple(e.relative_member for e in current.entries) == tuple(
            e.relative_member for e in candidate.entries
        )
        if value.broken == "prefix":
            raise ValueError("synthetic full-prefix drift")

    def interpreter(path: Path) -> str:
        assert path == PREFIX
        value.events.append("interpreter")
        if value.broken == "interpreter":
            raise ValueError("synthetic wrong installed interpreter")
        return "3.12.13"

    def boot(path: Path, *, maximum: int, owner_uid: int) -> bytes:
        assert path == Path("/proc/sys/kernel/random/boot_id") and maximum == 64 and owner_uid == 0
        value.events.append("boot")
        return (value.boot + "\n").encode("ascii")

    def user(name: str) -> SimpleNamespace:
        assert name == "eom-embedding-index-cpu"
        return SimpleNamespace(pw_uid=value.uid, pw_gid=value.primary_gid)

    def group(name: str) -> SimpleNamespace:
        assert name == "eom-embedding-index-cpu"
        return SimpleNamespace(gr_gid=value.gid)

    monkeypatch.setattr(admission, "NumericalRuntimeFileSnapshots", Files)
    monkeypatch.setattr(admission, "capture_protected_embedding_host", host)
    monkeypatch.setattr(admission, "require_native_runtime_interpreter", interpreter)
    monkeypatch.setattr(admission, "read_live_runtime_os_file", boot)
    monkeypatch.setattr(pwd, "getpwnam", user)
    monkeypatch.setattr(grp, "getgrnam", group)
    monkeypatch.setattr(os, "getgrouplist", lambda *_args: list(value.groups))
    monkeypatch.setattr(PrefixRuntimeInventory, "assert_unchanged", prefix_current)
    return value


def test_reads_exact_metadata_once_then_only_checks_current_epochs(
    state: Scenario,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with state.capture() as captured:
        expected = len(state.files)
        assert len(state.reads) == expected and len(set(state.reads)) == expected

        def never_parse(*_args: object, **_kwargs: object) -> None:
            pytest.fail("repeated admission must not parse or hash immutable metadata")

        for name in (
            "parse_rootlocal_native_admission_receipt_metadata",
            "parse_rootlocal_prefix_inventory_candidate",
            "validate_rootlocal_native_installation_metadata_references",
            "parse_embedding_native_runtime_config_bytes",
            "parse_installed_runtime_proof",
            "parse_embedding_runtime_bundle",
        ):
            monkeypatch.setattr(admission, name, never_parse)
        for _ in range(5):
            state.assert_current(captured)
        assert len(state.reads) == expected
        assert state.events.count("host-capture") == 1
        assert all(
            state.events.count(kind) >= 6
            for kind in ("prefix-epochs", "file-epochs", "host-epochs", "boot")
        )
    assert state.host_closes == 1
    with pytest.raises(NativeInstallationAdmissionError, match="NATIVE_INSTALLATION_CHANGED"):
        state.assert_current(captured)
    captured.close()
    assert state.host_closes == 1


@pytest.mark.parametrize(
    "field,value",
    [
        ("profile", "CUDA_INDEX_FP32"),
        ("configuration_id", "embeddingnativeconfig_" + "a" * 32),
        ("configuration_revision_id", "embeddingnativeconfigrev_" + "b" * 32),
        ("configuration_raw_sha256", "sha256:" + "c" * 64),
    ],
)
def test_exact_capture_rejects_profile_latest_or_alternate_configuration(
    state: Scenario,
    field: str,
    value: str,
) -> None:
    with (
        state.capture() as captured,
        pytest.raises(
            NativeInstallationAdmissionError, match="NATIVE_INSTALLATION_CAPTURE_MISMATCH"
        ),
    ):
        state.assert_current(captured, **{field: value})


@pytest.mark.parametrize(
    "suffix",
    [
        "receipt.json",
        "inventory.json",
        "config.json",
        "proof.json",
        "bundle.json",
        "admission-receipt-v1.schema.json",
        "prefix-inventory-v1.schema.json",
        "eom-embedding-native-cpu-probe@.service",
        "embedding_native_cpu_probe.py",
    ],
)
@pytest.mark.parametrize("failure", ["missing", "hash"])
def test_missing_or_changed_metadata_never_substitutes_latest(
    state: Scenario,
    suffix: str,
    failure: str,
) -> None:
    (path,) = [path for path in state.files if path.name == suffix]
    if failure == "missing":
        del state.files[path]
    else:
        state.files[path] += b"changed"
    with pytest.raises(
        NativeInstallationAdmissionError, match="NATIVE_INSTALLATION_CAPTURE_INVALID"
    ):
        state.capture()
    assert state.host_closes == 0


@pytest.mark.parametrize("broken", ["files", "prefix", "host", "interpreter"])
def test_current_drift_rejects_and_closes_the_same_capture(state: Scenario, broken: str) -> None:
    captured = state.capture()
    state.broken = broken
    with pytest.raises(NativeInstallationAdmissionError, match="NATIVE_INSTALLATION_CHANGED"):
        state.assert_current(captured)
    with pytest.raises(NativeInstallationAdmissionError, match="NATIVE_INSTALLATION_CHANGED"):
        captured.close()
    assert state.host_closes == 1
    state.broken = None
    with pytest.raises(NativeInstallationAdmissionError, match="NATIVE_INSTALLATION_CHANGED"):
        state.assert_current(captured)


@pytest.mark.parametrize(
    "field,value",
    [
        ("boot", "00000000-0000-0000-0000-000000000000"),
        ("uid", 0),
        ("gid", 0),
        ("primary_gid", 7),
        ("groups", (2013, 0)),
        ("groups", ()),
    ],
)
def test_current_account_groups_or_boot_change_is_explicit(
    state: Scenario, field: str, value: Any
) -> None:
    captured = state.capture()
    setattr(state, field, value)
    with pytest.raises(NativeInstallationAdmissionError, match="NATIVE_INSTALLATION_CHANGED"):
        state.assert_current(captured)
    with pytest.raises(NativeInstallationAdmissionError, match="NATIVE_INSTALLATION_CHANGED"):
        captured.close()
    assert state.host_closes == 1


def test_failed_context_entry_still_releases_descriptors(state: Scenario) -> None:
    captured = state.capture()
    state.broken = "prefix"
    with pytest.raises(NativeInstallationAdmissionError), captured:
        pytest.fail("changed prefix must not enter")
    assert state.host_closes == 1


def test_constructor_final_check_failure_releases_host_once(state: Scenario) -> None:
    state.broken = "prefix"
    with pytest.raises(
        NativeInstallationAdmissionError, match="NATIVE_INSTALLATION_CAPTURE_INVALID"
    ):
        state.capture()
    assert state.host_closes == 1


def test_cleanup_failure_is_uncertain_and_capture_cannot_be_reused(state: Scenario) -> None:
    captured = state.capture()
    state.broken = "close"
    with pytest.raises(
        NativeInstallationAdmissionError, match="NATIVE_INSTALLATION_CAPTURE_CLEANUP_UNCERTAIN"
    ):
        captured.close()
    assert state.host_closes == 1
    state.broken = None
    with pytest.raises(NativeInstallationAdmissionError, match="NATIVE_INSTALLATION_CHANGED"):
        state.assert_current(captured)


def test_sealed_metadata_is_not_accepted_without_the_independent_raw_pin(state: Scenario) -> None:
    state.receipt_pin = "sha256:" + "f" * 64
    with pytest.raises(
        NativeInstallationAdmissionError, match="NATIVE_INSTALLATION_CAPTURE_INVALID"
    ):
        state.capture()
    assert not state.events.count("host-capture")


def test_rehashed_receipt_cannot_change_the_separately_captured_config(state: Scenario) -> None:
    (path,) = [path for path in state.files if path.name == "receipt.json"]
    body = json.loads(state.files[path])
    body["configuration"]["configuration_raw_sha256"] = "sha256:" + "f" * 64
    state.files[path] = canonical_json_bytes(seal(body, "receipt_sha256"))
    state.receipt_pin = sha256_bytes(state.files[path])
    with pytest.raises(
        NativeInstallationAdmissionError, match="NATIVE_INSTALLATION_CAPTURE_INVALID"
    ):
        state.capture()
    assert len(state.reads) == 2


@pytest.mark.parametrize("field", ["inventory", "bundle", "installed_proof"])
def test_rehashed_cross_reference_disagreement_is_not_an_execution_grant(
    state: Scenario, field: str
) -> None:
    (path,) = [path for path in state.files if path.name == "receipt.json"]
    body = json.loads(state.files[path])
    inner = {
        "inventory": "inventory_sha256",
        "bundle": "bundle_sha256",
        "installed_proof": "proof_sha256",
    }[field]
    body[field][inner] = "sha256:" + "e" * 64
    state.files[path] = canonical_json_bytes(seal(body, "receipt_sha256"))
    state.receipt_pin = sha256_bytes(state.files[path])
    with pytest.raises(
        NativeInstallationAdmissionError, match="NATIVE_INSTALLATION_CAPTURE_INVALID"
    ):
        state.capture()
    assert state.events.count("host-capture") == 0


@pytest.mark.parametrize("value", [True, None, 7, [], {}])
def test_nonstrict_caller_identity_values_are_rejected_without_path_resolution(
    state: Scenario,
    value: Any,
) -> None:
    with state.capture() as captured:
        before = len(state.reads)
        with pytest.raises(
            NativeInstallationAdmissionError, match="NATIVE_INSTALLATION_CAPTURE_MISMATCH"
        ):
            state.assert_current(captured, configuration_id=value)
        assert len(state.reads) == before


def test_no_authority_mint_write_database_process_or_optional_model_import() -> None:
    source = inspect.getsource(admission)
    tree = ast.parse(source)
    imports = {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)} | {
        name.name for node in ast.walk(tree) if isinstance(node, ast.Import) for name in node.names
    }
    assert not any(
        name
        and name.startswith(
            (
                "eom_orchestrator",
                "eom_api",
                "sqlalchemy",
                "subprocess",
                "torch",
                "transformers",
                "tokenizers",
                "numpy",
            )
        )
        for name in imports
    )
    assert all(
        name not in source
        for name in ("write_bytes(", "write_text(", "O_CREAT", "chmod(", "publish(", "seal(")
    )
