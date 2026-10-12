"""Protected synthetic wheels/OS surrogates only; no installed runtime or GPU execution."""

from __future__ import annotations

import ast
import base64
import csv
import hashlib
import importlib
import io
import json
import os
from pathlib import Path
from typing import Any

import pytest
from eom_catalog_contracts.embedding_installed_runtime_proof import (
    EmbeddingInstalledRuntimeProof,
    EmbeddingRuntimeProfile,
    installed_runtime_proof_bytes,
)
from eom_catalog_service.embedding_installed_runtime_observer import (
    ConfiguredInstalledRuntimeProof,
    ProtectedInstalledEmbeddingRuntimeObserver,
)
from eom_catalog_service.embedding_runtime_files import (
    InstalledRuntimeProofError,
    NumericalRuntimeFileSnapshots,
)
from eom_identifiers import canonical_json_bytes, sha256_bytes

from tests.unit.embedding_installed_runtime_fixtures import (
    StagedSyntheticRuntime,
    proof_pointer,
    staged_runtime,
    synthetic_record,
)
from tests.unit.embedding_native_backend_fixtures import FakeOwnership
from tests.unit.inference_transfer_embedding_fixtures import seal


def _observer(staged: StagedSyntheticRuntime) -> ProtectedInstalledEmbeddingRuntimeObserver:
    return ProtectedInstalledEmbeddingRuntimeObserver(
        ConfiguredInstalledRuntimeProof(proof_pointer(staged.proof)),
        cuda_ownership=FakeOwnership() if staged.proof.profile == "CUDA_INDEX_FP32" else None,
    )


def test_verified_proof_metadata_accessor_rechecks_and_reuses_one_initial_byte_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    staged = staged_runtime(tmp_path, monkeypatch)
    actual_read = NumericalRuntimeFileSnapshots.read
    reads = 0

    def counted(self: NumericalRuntimeFileSnapshots, path: Path, **kwargs: Any) -> bytes:
        nonlocal reads
        if path == staged.proof_path:
            reads += 1
        return actual_read(self, path, **kwargs)

    monkeypatch.setattr(NumericalRuntimeFileSnapshots, "read", counted)
    observer = _observer(staged)
    first = observer.verified_proof_metadata
    second = observer.verified_proof_metadata
    assert first.proof == staged.proof and first.raw == installed_runtime_proof_bytes(staged.proof)
    assert first.raw is second.raw and first.proof is second.proof and reads == 1
    staged.proof_path.write_bytes(first.raw)
    with pytest.raises(InstalledRuntimeProofError):
        _ = observer.verified_proof_metadata
    assert reads == 1


@pytest.mark.parametrize("fault", ("mode", "replace", "symlink", "missing", "ancestor"))
def test_metadata_only_member_observation_captures_strong_epoch_without_hash(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fault: str
) -> None:
    member = tmp_path / "member"
    member.write_bytes(b"synthetic immutable bytes")
    member.chmod(0o600)
    files = NumericalRuntimeFileSnapshots(os.geteuid())
    monkeypatch.setattr(os, "pread", lambda *_args: pytest.fail("metadata cannot repeat bytes"))
    files.observe_protected_member_identity(member)
    files.observe_protected_member_identity(member)
    files.assert_unchanged()
    if fault == "mode":
        member.chmod(0o660)
    elif fault == "missing":
        member.unlink()
    elif fault == "replace":
        replacement = tmp_path / "replacement"
        replacement.write_bytes(b"synthetic immutable bytes")
        replacement.chmod(0o600)
        replacement.replace(member)
    elif fault == "symlink":
        member.unlink()
        member.symlink_to(tmp_path / "absent")
    else:
        tmp_path.chmod(0o770)
    with pytest.raises(InstalledRuntimeProofError):
        files.assert_unchanged()


@pytest.mark.parametrize("profile", ["CPU_INDEX_FP32", "CUDA_INDEX_FP32"])
def test_actual_archives_installed_members_and_live_os_form_independent_observation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    profile: EmbeddingRuntimeProfile,
) -> None:
    staged = staged_runtime(tmp_path, monkeypatch, profile)
    monkeypatch.setattr(importlib, "import_module", lambda *_a, **_k: pytest.fail("no ML import"))
    observer = _observer(staged)
    actual = observer.observe()
    assert actual.python_version == "3.12.13"
    assert actual.device == staged.proof.device_capture.numeric_device
    assert tuple((pin.name, pin.version) for pin in actual.libraries) == tuple(
        (pin.name, pin.version) for pin in staged.proof.numeric_libraries
    )
    assert tuple(pin.distribution_sha256 for pin in actual.libraries) == tuple(
        library.archive.sha256 for library in staged.proof.numeric_libraries
    )
    assert actual.torch_build_cuda_version == ("12.8" if profile == "CUDA_INDEX_FP32" else None)


def test_closed_generated_metadata_and_derived_console_wrapper_are_accepted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    staged = staged_runtime(tmp_path, monkeypatch, with_generated=True)
    assert len(_observer(staged).observe().libraries) == 5


@pytest.mark.parametrize(
    "fault",
    [
        "quarantine_url",
        "editable",
        "url_unknown",
        "url_hash",
        "installer",
        "requested",
        "script_statement",
        "script_shebang",
    ],
)
def test_even_repinned_closed_additions_cannot_relax_generated_semantics(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fault: str,
) -> None:
    staged = staged_runtime(tmp_path, monkeypatch, with_generated=True)
    dist = staged.dist_infos["numpy"]
    direct = dist / "direct_url.json"
    if fault in {"quarantine_url", "editable", "url_unknown", "url_hash"}:
        target = direct
        value = json.loads(target.read_bytes())
        if fault == "quarantine_url":
            value["url"] = "file:///tmp/mutable-quarantine/numpy.whl"
        elif fault == "editable":
            value["dir_info"] = {"editable": True}
        elif fault == "url_unknown":
            value["unregistered"] = True
        else:
            value["archive_info"]["hashes"]["sha256"] = "f" * 64
        target.write_bytes(canonical_json_bytes(value))
    elif fault == "installer":
        target = dist / "INSTALLER"
        target.write_bytes(b"bad\n")
    elif fault == "requested":
        target = dist / "REQUESTED"
        target.write_bytes(b"not empty")
    else:
        target = staged.prefix / "bin/synthetic-numeric"
        raw = target.read_bytes()
        target.write_bytes(
            raw + b"import os\n"
            if fault == "script_statement"
            else raw.replace(str(staged.prefix / "bin/python3.12").encode(), b"/bin/sh")
        )
    record_path = dist / "RECORD"
    rows = list(csv.reader(io.StringIO(record_path.read_text(), newline="")))
    for row in rows:
        if (
            Path(os.path.normpath(staged.prefix / "lib/python3.12/site-packages" / row[0]))
            == target
        ):
            raw = target.read_bytes()
            row[1] = "sha256=" + base64.urlsafe_b64encode(
                hashlib.sha256(raw).digest()
            ).decode().rstrip("=")
            row[2] = str(len(raw))
    stream = io.StringIO(newline="")
    csv.writer(stream, lineterminator="\n").writerows(rows)
    record = stream.getvalue().encode()
    record_path.write_bytes(record)
    body = staged.proof.model_dump(mode="json")
    library = body["numeric_libraries"][0]
    library["installed_record"] = {"sha256": sha256_bytes(record), "size_bytes": len(record)}
    if target == direct:
        library["direct_url"] = {
            "sha256": sha256_bytes(target.read_bytes()),
            "size_bytes": target.stat().st_size,
        }
    elif target.parent == staged.prefix / "bin":
        library["console_scripts"][0].update(
            sha256=sha256_bytes(target.read_bytes()), size_bytes=target.stat().st_size
        )
    proof = EmbeddingInstalledRuntimeProof.model_validate(seal(body, "proof_sha256"))
    staged.proof_path.write_bytes(installed_runtime_proof_bytes(proof))
    with pytest.raises(InstalledRuntimeProofError):
        ProtectedInstalledEmbeddingRuntimeObserver(
            ConfiguredInstalledRuntimeProof(proof_pointer(proof))
        )


@pytest.mark.parametrize(
    "fault",
    [
        "archive_hash",
        "archive_missing",
        "installed_hash",
        "record_hash",
        "metadata_version",
        "symlink",
        "hardlink",
        "mode",
        "unknown_namespace",
        "pyc",
        "proof_raw",
        "prefix",
    ],
)
def test_archive_installed_record_and_permission_faults_fail_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fault: str,
) -> None:
    staged = staged_runtime(tmp_path, monkeypatch)
    member = staged.prefix / "lib/python3.12/site-packages/numpy/__init__.py"
    if fault == "archive_hash":
        path = staged.archives["numpy"]
        path.write_bytes(path.read_bytes() + b"x")
    elif fault == "archive_missing":
        staged.archives["numpy"].unlink()
    elif fault == "installed_hash":
        member.write_bytes(member.read_bytes().replace(b"synthetic", b"malicious"))
    elif fault == "record_hash":
        path = staged.dist_infos["numpy"] / "RECORD"
        path.write_bytes(path.read_bytes() + b"changed")
    elif fault == "metadata_version":
        path = staged.dist_infos["numpy"] / "METADATA"
        path.write_bytes(path.read_bytes().replace(b"2.4.6", b"9.9.9"))
    elif fault == "symlink":
        member.unlink()
        member.symlink_to(staged.dist_infos["numpy"] / "METADATA")
    elif fault == "hardlink":
        os.link(member, member.with_name("duplicate"))
    elif fault == "mode":
        member.chmod(0o660)
    elif fault in {"unknown_namespace", "pyc"}:
        path = member.with_name("unregistered.pyc" if fault == "pyc" else "unregistered.py")
        path.write_bytes(b"unregistered code")
        path.chmod(0o600)
    elif fault == "proof_raw":
        staged.proof_path.write_bytes(staged.proof_path.read_bytes() + b"\n")
    else:
        import sys

        monkeypatch.setattr(sys, "prefix", "/untrusted")
    with pytest.raises(InstalledRuntimeProofError):
        _observer(staged)


def test_rewritten_installed_record_does_not_authorize_changed_package_bytes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    staged = staged_runtime(tmp_path, monkeypatch)
    member = staged.prefix / "lib/python3.12/site-packages/numpy/__init__.py"
    member.write_bytes(b"x" * member.stat().st_size)
    dist = staged.dist_infos["numpy"]
    site = staged.prefix / "lib/python3.12/site-packages"
    members = {
        path.relative_to(site).as_posix(): path.read_bytes()
        for path in (member, dist / "METADATA", dist / "WHEEL", dist / "INSTALLER")
    }
    record = synthetic_record(members, (dist / "RECORD").relative_to(site).as_posix())
    (dist / "RECORD").write_bytes(record)
    body = staged.proof.model_dump(mode="json")
    body["numeric_libraries"][0]["installed_record"] = {
        "sha256": sha256_bytes(record),
        "size_bytes": len(record),
    }
    proof = EmbeddingInstalledRuntimeProof.model_validate(seal(body, "proof_sha256"))
    staged.proof_path.write_bytes(installed_runtime_proof_bytes(proof))
    with pytest.raises(InstalledRuntimeProofError, match="HASH_MISMATCH"):
        ProtectedInstalledEmbeddingRuntimeObserver(
            ConfiguredInstalledRuntimeProof(proof_pointer(proof))
        )


@pytest.mark.parametrize("target", ["archive", "member", "record", "namespace", "ancestor"])
def test_snapshot_epoch_change_is_rejected_after_initial_verification(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    target: str,
) -> None:
    staged = staged_runtime(tmp_path, monkeypatch)
    observer = _observer(staged)
    if target == "ancestor":
        moved = staged.prefix.with_name("moved-prefix")
        staged.prefix.rename(moved)
        staged.prefix.symlink_to(moved, target_is_directory=True)
    elif target == "namespace":
        path = staged.prefix / "lib/python3.12/site-packages/numpy/new.py"
        path.write_bytes(b"new file")
    else:
        path = (
            staged.archives["numpy"]
            if target == "archive"
            else staged.dist_infos["numpy"] / "RECORD"
            if target == "record"
            else staged.prefix / "lib/python3.12/site-packages/numpy/__init__.py"
        )
        path.write_bytes(path.read_bytes() + b"x")
    with pytest.raises(InstalledRuntimeProofError):
        observer.observe()


def test_immutable_distribution_bytes_are_read_only_once_then_epochs_checked(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    staged = staged_runtime(tmp_path, monkeypatch)
    observer = _observer(staged)
    monkeypatch.setattr(
        NumericalRuntimeFileSnapshots,
        "verified_open",
        lambda *_a, **_k: pytest.fail("no repeated immutable read/hash"),
    )
    assert observer.observe() == observer.observe()


@pytest.mark.parametrize("fault", ["driver", "uuid", "pci", "minor", "boot", "model"])
def test_cuda_live_os_identity_is_not_a_root_receipt_claim_echo(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fault: str,
) -> None:
    staged = staged_runtime(tmp_path, monkeypatch, "CUDA_INDEX_FP32")
    observer = _observer(staged)
    if fault == "driver":
        path = staged.proc_root / "driver/nvidia/version"
        path.write_bytes(path.read_bytes().replace(b"580.126.09", b"999.999.99"))
    elif fault == "boot":
        (staged.proc_root / "sys/kernel/random/boot_id").write_bytes(
            b"aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee\n"
        )
    else:
        path = staged.proc_root / "driver/nvidia/gpus/0000:01:00.0/information"
        before, after = {
            "uuid": (b"GPU-11111111", b"GPU-aaaaaaaa"),
            "pci": (b"0000:01:00.0", b"0000:02:00.0"),
            "minor": (b"Device Minor: 0", b"Device Minor: 1"),
            "model": (b"RTX 5080", b"RTX 4090"),
        }[fault]
        path.write_bytes(path.read_bytes().replace(before, after))
    with pytest.raises(InstalledRuntimeProofError):
        observer.observe()


def test_cuda_missing_ownership_denies_before_files_or_live_os_observation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    staged = staged_runtime(tmp_path, monkeypatch, "CUDA_INDEX_FP32")
    monkeypatch.setattr(
        NumericalRuntimeFileSnapshots, "read", lambda *_a, **_k: pytest.fail("no file read")
    )
    with pytest.raises(InstalledRuntimeProofError, match="CUDA_OWNERSHIP_REQUIRED"):
        ProtectedInstalledEmbeddingRuntimeObserver(
            ConfiguredInstalledRuntimeProof(proof_pointer(staged.proof))
        )


def test_cpu_heterogeneity_live_readback_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    staged = staged_runtime(tmp_path, monkeypatch)
    observer = _observer(staged)
    path = staged.proc_root / "cpuinfo"
    path.write_bytes(path.read_bytes().replace(b"model : 143", b"model : 142", 1))
    with pytest.raises(InstalledRuntimeProofError, match="CPU_HETEROGENEOUS"):
        observer.observe()


def test_observer_modules_have_no_ml_or_source_script_imports() -> None:
    root = Path(__file__).resolve().parents[2]
    for name in (
        "embedding_runtime_files",
        "embedding_runtime_distribution",
        "embedding_runtime_os_identity",
        "embedding_installed_runtime_observer",
    ):
        tree = ast.parse(
            (root / "services/catalog_service/eom_catalog_service" / f"{name}.py").read_text()
        )
        names = {
            alias.name.split(".")[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        } | {
            (node.module or "").split(".")[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
        }
        assert not names & {
            "torch",
            "transformers",
            "numpy",
            "subprocess",
            "urllib",
            "requests",
            "scripts",
            "sqlalchemy",
        }
