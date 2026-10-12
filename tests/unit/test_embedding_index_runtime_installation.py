"""Synthetic bootstrap/temporary archives only; never root, package installation, ML or GPU."""

from __future__ import annotations

import ast
import fcntl
import hashlib
import io
import os
import re
import subprocess
import sys
import tarfile
import tempfile
import zipfile
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import cast

import pytest

from tests.unit.test_inference_transfer_cpu_installation import snapshot_helper

ROOT = Path(__file__).resolve().parents[2]
SHELL = ROOT / "scripts/embedding/install_index_runtime.sh"


@pytest.fixture
def helper(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    module = snapshot_helper()
    # Explicit synthetic ownership substitution, not a live root acceptance claim.
    monkeypatch.setattr(module, "_INDEX_UID", os.getuid())
    monkeypatch.setattr(module, "_INDEX_GID", os.getgid())
    archive = tmp_path / "archives"
    archive.mkdir(mode=0o755)
    monkeypatch.setattr(module, "_INDEX_ARCHIVE_ROOT", archive)

    def protected(path: Path, *, directory: bool = True) -> None:
        metadata = path.lstat()
        assert not path.is_symlink() and metadata.st_uid == os.getuid()
        assert not metadata.st_mode & 0o022 and path.is_dir() == directory

    monkeypatch.setattr(module, "require_root_path", protected)
    return module


def test_fixed_lock_graph_exact_unique_counts_and_torch_flavors(
    helper: ModuleType, tmp_path: Path
) -> None:
    locks = tmp_path / "locks"
    locks.mkdir()
    for name in helper._INDEX_LOCK_SHA:
        source = ROOT / ("infra/conda" if name.startswith("eom-") else "scripts/embedding") / name
        (locks / name).write_bytes(source.read_bytes())
        (locks / name).chmod(0o644)
    cpu = helper.index_runtime_locks(locks, "CPU_INDEX_FP32")
    cuda = helper.index_runtime_locks(locks, "CUDA_INDEX_FP32")
    assert len(cpu) == 55 and len(cuda) == 70
    assert cpu["torch"][0] == "2.7.1+cpu" and cuda["torch"][0] == "2.7.1+cu128"
    assert all(cuda[name] == value for name, value in cpu.items() if name != "torch")
    (locks / "common-numeric-runtime-wheels.lock").write_bytes(b"unreviewed")
    with pytest.raises(helper.SnapshotInstallError, match="LOCK_HASH_MISMATCH"):
        helper.index_runtime_locks(locks, "CPU_INDEX_FP32")


def test_retain_raw_archive_once_and_replay_never_reads_mutable_source(
    helper: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    with tempfile.TemporaryDirectory(prefix="eom-index-source-") as temporary:
        source = Path(temporary) / "fixture.whl"
        source.write_bytes(b"independently pinned fixture archive")
        digest = hashlib.sha256(source.read_bytes()).hexdigest()
        retained = helper.retain_index_archive(source, digest, source.name, maximum=1024)
        assert retained.read_bytes() == source.read_bytes()
        assert retained.stat().st_nlink == 1 and retained.stat().st_mode & 0o777 == 0o644
        assert retained.parent.stat().st_mode & 0o777 == 0o755
        monkeypatch.setattr(
            helper, "_index_source", lambda _source: pytest.fail("second source read")
        )
        assert helper.retain_index_archive(source, digest, source.name, maximum=1024) == retained


def test_shared_wheelhouse_map_rejects_unknown_duplicates_links_and_bounds(
    helper: ModuleType, tmp_path: Path
) -> None:
    first, second = tmp_path / "first", tmp_path / "second"
    first.mkdir()
    second.mkdir()
    (first / "fixture.whl").write_bytes(b"fixture")
    assert helper._index_wheelhouse_sources([first], {"fixture.whl"}) == {
        "fixture.whl": first / "fixture.whl"
    }
    for directories, known in [
        ([], {"fixture.whl"}),
        ([first] * 5, {"fixture.whl"}),
        ([first, first], {"fixture.whl"}),
        ([first], {"foreign.whl"}),
    ]:
        with pytest.raises(helper.SnapshotInstallError):
            helper._index_wheelhouse_sources(directories, known)
    (second / "fixture.whl").write_bytes(b"fixture")
    with pytest.raises(helper.SnapshotInstallError, match="INVENTORY_INVALID"):
        helper._index_wheelhouse_sources([first, second], {"fixture.whl"})
    linked = tmp_path / "linked"
    linked.symlink_to(first, target_is_directory=True)
    with pytest.raises(helper.SnapshotInstallError, match="WHEELHOUSE_INVALID"):
        helper._index_wheelhouse_sources([linked], {"fixture.whl"})


def test_new_public_archive_root_is_readable_under_private_bootstrap_umask(
    helper: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    archive = tmp_path / "new-archives"
    monkeypatch.setattr(helper, "_INDEX_ARCHIVE_ROOT", archive)
    previous = os.umask(0o077)
    try:
        helper._prepare_index_archive_root()
    finally:
        os.umask(previous)
    assert archive.stat().st_mode & 0o777 == 0o755
    helper._prepare_index_archive_root()


def test_existing_private_archive_root_is_not_silently_repaired(
    helper: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    archive = tmp_path / "old-archives"
    archive.mkdir(mode=0o700)
    monkeypatch.setattr(helper, "_INDEX_ARCHIVE_ROOT", archive)
    with pytest.raises(helper.SnapshotInstallError, match="ARCHIVE_ROOT_MODE_INVALID"):
        helper._prepare_index_archive_root()
    assert archive.stat().st_mode & 0o777 == 0o700


@pytest.mark.parametrize("failure", ["nonroot", "mutable_api", "new_prefix", "site", "version"])
def test_public_retention_context_refuses_before_lock_source_or_any_write(
    helper: ModuleType, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    executable = "/opt/eom/conda/envs/eom-embedding-experiment/bin/python3.12"
    if failure == "mutable_api":
        executable = "/srv/eom/conda/envs/eom-api/bin/python3.12"
    elif failure == "new_prefix":
        executable = "/opt/eom/conda/envs/eom-embedding-index-cpu/bin/python3.12"
    monkeypatch.setattr(
        helper,
        "sys",
        SimpleNamespace(
            argv=[
                "bootstrap.py",
                "--profile",
                "CPU_INDEX_FP32",
                "--lock-directory",
                "/tmp/eom-fixture/locks",
                "--wheelhouse",
                "/tmp/eom-fixture/wheels",
            ],
            flags=SimpleNamespace(
                isolated=True, no_site=failure != "site", dont_write_bytecode=True
            ),
            executable=executable,
            version_info=(3, 12, 12) if failure == "version" else (3, 12, 13),
            platform="linux",
            stderr=sys.stderr,
        ),
    )
    monkeypatch.setattr(helper.os, "geteuid", lambda: 1000 if failure == "nonroot" else 0)
    monkeypatch.setattr(
        helper, "index_runtime_locks", lambda *args: pytest.fail("read before context admission")
    )
    monkeypatch.setattr(
        helper, "retain_index_archive", lambda *args, **kwargs: pytest.fail("archive write")
    )
    assert helper.index_public_archives_main() == 1


def test_public_retention_uses_only_selected_profile_and_retained_not_installed_status(
    helper: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    wheels = tmp_path / "wheels"
    wheels.mkdir()
    cpu = wheels / "cpu.whl"
    cpu.write_bytes(b"public CPU fixture")
    cuda = wheels / "cuda.whl"
    cuda.write_bytes(b"public CUDA fixture")
    cpu_sha, cuda_sha = (hashlib.sha256(path.read_bytes()).hexdigest() for path in (cpu, cuda))
    monkeypatch.setattr(
        helper,
        "sys",
        SimpleNamespace(
            argv=[
                "bootstrap.py",
                "--profile",
                "CPU_INDEX_FP32",
                "--lock-directory",
                str(tmp_path / "locks"),
                "--wheelhouse",
                str(wheels),
            ],
            flags=SimpleNamespace(isolated=True, no_site=True, dont_write_bytecode=True),
            executable="/opt/eom/conda/envs/eom-embedding-experiment/bin/python3.12",
            version_info=(3, 12, 13),
            platform="linux",
            stderr=sys.stderr,
        ),
    )
    monkeypatch.setattr(helper.os, "geteuid", lambda: 0)
    monkeypatch.setattr(helper, "require_root_path", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        helper,
        "index_runtime_locks",
        lambda _directory, profile: {
            "fixture": ("1", cpu.name, cpu_sha)
            if profile == "CPU_INDEX_FP32"
            else ("1", cuda.name, cuda_sha)
        },
    )
    monkeypatch.setattr(helper, "_INDEX_PUBLIC_BYTES", {"CPU_INDEX_FP32": cpu.stat().st_size})
    retained: list[Path] = []

    def retain(source: Path, _sha: str, _basename: str, *, maximum: int) -> Path:
        assert maximum == 2 * 1024**3
        retained.append(source)
        return source

    monkeypatch.setattr(helper, "retain_index_archive", retain)
    assert helper.index_public_archives_main() == 0
    assert retained == [cpu]
    output = capsys.readouterr().out
    assert "RETAINED_NOT_INSTALLED" in output and "ACTIVE" not in output


@pytest.mark.parametrize("failure", ["hash", "growth", "write", "symlink", "hardlink"])
def test_retention_failure_preserves_private_incomplete_evidence_and_refuses_reset(
    helper: ModuleType, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    with tempfile.TemporaryDirectory(prefix="eom-index-source-") as temporary:
        source = Path(temporary) / "fixture.whl"
        source.write_bytes(b"pinned bytes")
        digest = hashlib.sha256(source.read_bytes()).hexdigest()
        if failure == "hash":
            source.write_bytes(b"changed bytes")
        elif failure == "symlink":
            target = source.with_name("target")
            source.rename(target)
            source.symlink_to(target)
        elif failure == "hardlink":
            os.link(source, source.with_name("second-link"))
        elif failure == "write":
            monkeypatch.setattr(helper.os, "write", lambda _descriptor, _payload: 0)
        else:
            original = helper.os.read
            changed = False

            def read(descriptor: int, size: int) -> bytes:
                nonlocal changed
                value = original(descriptor, size)
                if value and not changed:
                    changed = True
                    source.write_bytes(b"pinned bytes and concurrent growth")
                return cast(bytes, value)

            monkeypatch.setattr(helper.os, "read", read)
        with pytest.raises((helper.SnapshotInstallError, OSError)):
            helper.retain_index_archive(source, digest, source.name, maximum=1024)
        reservation = helper._INDEX_ARCHIVE_ROOT / digest
        assert reservation.is_dir() and reservation.stat().st_mode & 0o777 == 0o700
        with pytest.raises(helper.SnapshotInstallError, match="ARCHIVE_INCOMPLETE"):
            helper.retain_index_archive(source, digest, source.name, maximum=1024)


def test_source_file_fstat_failure_closes_all_held_descriptors(
    helper: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    with tempfile.TemporaryDirectory(prefix="eom-index-source-") as temporary:
        source = Path(temporary) / "fixture.whl"
        source.write_bytes(b"fixture")
        original = helper.os.fstat
        calls = 0

        def fail_fourth(descriptor: int) -> os.stat_result:
            nonlocal calls
            calls += 1
            if calls == 4:
                raise OSError("synthetic file fstat failure")
            return cast(os.stat_result, original(descriptor))

        before = set(os.listdir("/proc/self/fd"))
        monkeypatch.setattr(helper.os, "fstat", fail_fourth)
        with pytest.raises(OSError):
            helper._index_source(source)
        assert set(os.listdir("/proc/self/fd")) == before


def test_cleanup_attempts_every_descriptor_after_one_close_failure(
    helper: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    closed = []

    def close(descriptor: int) -> None:
        closed.append(descriptor)
        if descriptor == 2:
            raise OSError("synthetic close failure")

    monkeypatch.setattr(helper.os, "close", close)
    with pytest.raises(OSError):
        helper._index_close((1, 2, 3))
    assert closed == [1, 2, 3]


def _private_fixture(helper: ModuleType, root: Path) -> tuple[Path, Path, Path, str]:
    prefix, wheel, source = root / "prefix", root / "platform.whl", root / "source.tar"
    commit = "a" * 40
    with (
        tarfile.open(
            source, "w", format=tarfile.PAX_FORMAT, pax_headers={"comment": commit}
        ) as original,
        zipfile.ZipFile(wheel, "w") as installed,
    ):
        for number, (path, member) in enumerate(helper._INDEX_PRIVATE_SOURCES["eom-platform"]):
            raw = f"# synthetic current source leaf {number}\n".encode()
            entry = tarfile.TarInfo(path)
            entry.size = len(raw)
            original.addfile(entry, io.BytesIO(raw))
            installed.writestr(member, raw)
            target = prefix / "lib/python3.12/site-packages" / member
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(raw)
    return prefix, wheel, source, commit


def test_private_source_commit_and_current_leaves_cannot_use_historical_wheel(
    helper: ModuleType, tmp_path: Path
) -> None:
    prefix, wheel, source, commit = _private_fixture(helper, tmp_path)
    helper._index_private_source(prefix, wheel, source, commit, "eom-platform")
    with pytest.raises(helper.SnapshotInstallError, match="COMMIT_MISMATCH"):
        helper._index_private_source(prefix, wheel, source, "b" * 40, "eom-platform")
    with zipfile.ZipFile(wheel, "w") as historical:
        historical.writestr("eom_catalog_service/local_embedding_adapter.py", b"historical")
    with pytest.raises(helper.SnapshotInstallError, match="SOURCE_MISMATCH"):
        helper._index_private_source(prefix, wheel, source, commit, "eom-platform")


def test_current_source_leaf_with_changed_installed_bytes_is_refused(
    helper: ModuleType, tmp_path: Path
) -> None:
    prefix, wheel, source, commit = _private_fixture(helper, tmp_path)
    member = helper._INDEX_PRIVATE_SOURCES["eom-platform"][0][1]
    (prefix / "lib/python3.12/site-packages" / member).write_bytes(b"changed installed bytes")
    with pytest.raises(helper.SnapshotInstallError, match="INSTALLED_MISMATCH"):
        helper._index_private_source(prefix, wheel, source, commit, "eom-platform")


@pytest.mark.parametrize(
    "failure",
    [
        "declared_count",
        "actual_count",
        "central_bytes",
        "zip64",
        "extra_header",
        "multidisk",
        "archive_comment",
        "member_comment",
        "central_header",
        "local_header",
        "central_offset",
        "truncated",
    ],
)
def test_private_zip_preallocation_gate_refuses_before_any_zipfile_constructor(
    helper: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    prefix, wheel, source, commit = _private_fixture(helper, tmp_path)
    if failure == "actual_count":
        with zipfile.ZipFile(wheel, "w") as archive:
            for number in range(10001):
                archive.writestr(f"eom_fixture/{number}", b"")
    if failure in {"zip64", "extra_header"}:
        with zipfile.ZipFile(wheel, "w") as archive:
            info = zipfile.ZipInfo("eom_fixture/__init__.py")
            info.extra = (
                b"\x01\x00\x08\x00" + b"\x00" * 8 if failure == "zip64" else b"\x02\x00\x08\x00"
            )
            archive.writestr(info, b"fixture")
    if failure in {"archive_comment", "member_comment"}:
        with zipfile.ZipFile(wheel, "w") as archive:
            info = zipfile.ZipInfo("eom_fixture/__init__.py")
            if failure == "member_comment":
                info.comment = b"unaccepted"
            archive.writestr(info, b"fixture")
            if failure == "archive_comment":
                archive.comment = b"unaccepted"
    raw = bytearray(wheel.read_bytes())
    end = len(raw) - 22
    central = int.from_bytes(raw[end + 16 : end + 20], "little")
    if failure in {"actual_count", "declared_count"}:
        count = 1 if failure == "actual_count" else 10001
        raw[end + 8 : end + 12] = count.to_bytes(2, "little") * 2
    elif failure == "central_bytes":
        raw[end + 12 : end + 16] = (8 * 1024**2 + 1).to_bytes(4, "little")
    elif failure == "multidisk":
        raw[end + 4 : end + 6] = b"\x01\x00"
    elif failure == "central_header":
        raw[central] = 0
    elif failure == "local_header":
        raw[0] = 0
    elif failure == "central_offset":
        raw[end + 16 : end + 20] = b"\xff" * 4
    elif failure == "truncated":
        del raw[-1]
    wheel.write_bytes(raw)
    monkeypatch.setattr(
        helper.zipfile,
        "ZipFile",
        lambda *args, **kwargs: pytest.fail("untrusted ZipFile inventory allocated"),
    )
    with pytest.raises(helper.SnapshotInstallError, match="PRIVATE_WHEEL_INVALID"):
        helper._index_private_source(prefix, wheel, source, commit, "eom-platform")


def test_private_zip_gate_accepts_exact_actual_entry_boundary(
    helper: ModuleType, tmp_path: Path
) -> None:
    wheel = tmp_path / "boundary.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        for number in range(10000):
            archive.writestr(f"eom_fixture/{number}", b"")
    helper._index_private_zip32(wheel)


@pytest.mark.parametrize(
    "member",
    [
        "eom_orchestrator/unchecked.pyc",
        "eom_catalog_service/__pycache__/unchecked.cpython-312.pyc",
        "eom_gpu_lease/__pycache__/lease.cpython-312.pyc",
        "eom_unknown.pyc",
    ],
)
def test_installed_private_bytecode_is_denied_even_without_record_registration(
    helper: ModuleType, tmp_path: Path, member: str
) -> None:
    target = tmp_path / "lib/python3.12/site-packages" / member
    target.parent.mkdir(parents=True)
    target.write_bytes(b"unregistered bytecode")
    with pytest.raises(helper.SnapshotInstallError, match="PRIVATE_BYTECODE_FORBIDDEN"):
        helper._index_private_bytecode(tmp_path)


def test_private_wheel_bytecode_denied_before_zipfile_and_public_cache_is_not_private(
    helper: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    wheel = tmp_path / "private.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr("eom_gpu_lease/__pycache__/lease.cpython-312.pyc", b"unchecked")
    monkeypatch.setattr(
        helper.zipfile, "ZipFile", lambda *args, **kwargs: pytest.fail("ZipFile allocated")
    )
    with pytest.raises(helper.SnapshotInstallError, match="PRIVATE_BYTECODE_FORBIDDEN"):
        helper._index_private_zip32(wheel)
    public = tmp_path / "lib/python3.12/site-packages/pydantic/__pycache__/public.pyc"
    public.parent.mkdir(parents=True)
    public.write_bytes(b"public dependency inventory is a separate numerical owner gate")
    helper._index_private_bytecode(tmp_path)


def test_private_bytecode_scan_cannot_be_bypassed_with_internal_namespace_symlink(
    helper: ModuleType, tmp_path: Path
) -> None:
    site = tmp_path / "lib/python3.12/site-packages"
    target = site / "public_cache"
    target.mkdir(parents=True)
    (target / "unchecked.pyc").write_bytes(b"unregistered")
    (site / "eom_gpu_lease").symlink_to(target, target_is_directory=True)
    with pytest.raises(helper.SnapshotInstallError, match="PRIVATE_NAMESPACE_INVALID"):
        helper._index_private_bytecode(tmp_path)


def test_additive_branch_preflights_before_legacy_zip_and_checks_bytecode_before_status() -> None:
    tree = ast.parse((ROOT / "scripts/embedding/_install_experiment_snapshot.py").read_text())
    branch = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "index_runtime_main"
    )
    calls = {
        node.func.id: node.lineno
        for node in ast.walk(branch)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    assert calls["_index_private_zip32"] < calls["verify_platform_wheel"]
    status = next(
        node.lineno
        for node in ast.walk(branch)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "print"
        and node.args
        and isinstance(node.args[0], ast.Constant)
        and node.args[0].value == "EMBEDDING_INDEX_INSTALL_STATUS=INSTALLED_NOT_ADMITTED"
    )
    assert calls["_index_private_bytecode"] < status


def test_exact_distribution_inventory_excludes_historical_dev_and_api_extras(
    helper: ModuleType, tmp_path: Path
) -> None:
    site = tmp_path / "lib/python3.12/site-packages"
    metadata = site / "pydantic-2.13.4.dist-info/METADATA"
    metadata.parent.mkdir(parents=True)
    metadata.write_text("Name: pydantic\nVersion: 2.13.4\n")
    metadata.chmod(0o644)
    helper._index_inventory(tmp_path, {"pydantic": "2.13.4"})
    extra = site / "fastapi-0.141.1.dist-info/METADATA"
    extra.parent.mkdir()
    extra.write_text("Name: fastapi\nVersion: 0.141.1\n")
    extra.chmod(0o644)
    with pytest.raises(helper.SnapshotInstallError, match="CLOSURE_INVALID"):
        helper._index_inventory(tmp_path, {"pydantic": "2.13.4"})


def test_private_source_commit_is_mandatory_before_any_archive_operation(
    helper: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    arguments = [
        "install.py",
        "--profile",
        "CPU_INDEX_FP32",
        "--lock-directory",
        "/tmp/eom-f/locks",
        "--wheelhouse",
        "/tmp/eom-f/wheels",
        "--platform-wheel",
        "/tmp/eom-f/platform.whl",
        "--platform-wheel-sha256",
        "1" * 64,
        "--platform-source",
        "/tmp/eom-f/source.tar",
        "--platform-source-sha256",
        "2" * 64,
    ]
    monkeypatch.setattr(helper.sys, "argv", arguments)
    monkeypatch.setattr(
        helper, "retain_index_archive", lambda *args, **kwargs: pytest.fail("archive write")
    )
    with pytest.raises(SystemExit) as error:
        helper.index_runtime_main()
    assert error.value.code == 2


def test_nonroot_helper_context_refuses_before_retention(
    helper: ModuleType, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    arguments = [
        "install.py",
        "--profile",
        "CPU_INDEX_FP32",
        "--lock-directory",
        "/tmp/eom-f/locks",
        "--wheelhouse",
        "/tmp/eom-f/wheels",
        "--platform-wheel",
        "/tmp/eom-f/platform.whl",
        "--platform-wheel-sha256",
        "1" * 64,
        "--platform-source",
        "/tmp/eom-f/source.tar",
        "--platform-source-sha256",
        "2" * 64,
        "--platform-commit",
        "a" * 40,
    ]
    monkeypatch.setattr(helper.sys, "argv", arguments)
    monkeypatch.setattr(helper.os, "geteuid", lambda: 1000)
    monkeypatch.setattr(
        helper, "retain_index_archive", lambda *args, **kwargs: pytest.fail("archive write")
    )
    assert helper.index_runtime_main() == 1
    assert "SNAPSHOT_REJECTED" in capsys.readouterr().err


def _synthetic_shell(root: Path, *, interrupt: bool = False) -> tuple[Path, Path, list[str], Path]:
    """Same publication body, test-only path/UID substitutions and inert interpreter."""
    text = SHELL.read_text()
    prefix = root / "opt/eom/conda/envs/eom-embedding-index-cpu"
    prefix.mkdir(parents=True, mode=0o700)
    binary = prefix / "bin/python3.12"
    binary.parent.mkdir()
    binary.parent.chmod(0o755)
    marker = root / "interpreter-entered"
    binary.write_text(f"#!/usr/bin/bash\nprintf 'entered' > '{marker}'\n")
    binary.chmod(0o755)
    text = re.sub(r"/opt(?=/|\s)", str(root / "opt"), text)
    text = text.replace('"$EUID" == 0', f'"$EUID" == {os.getuid()}')
    text = text.replace(
        '"$(stat -c %u "$PUBLICATION_LOCK")" == 0',
        f'"$(stat -c %u "$PUBLICATION_LOCK")" == {os.getuid()}',
    )
    text = text.replace("chown -hR root:root", f"chown -hR {os.getuid()}:{os.getgid()}")
    text = text.replace(
        "install -d -o root -g root", f"install -d -o {os.getuid()} -g {os.getgid()}"
    )
    start, end = text.index("root_directory() {"), text.index("fixed_parents() {")
    text = text[:start] + 'root_directory() { [[ -d "$1" && ! -L "$1" ]]; }\n' + text[end:]
    if interrupt:
        text = text.replace(
            "record_phase PREFIX_ABSENT_RETAINED_QUARANTINE",
            "record_phase PREFIX_ABSENT_RETAINED_QUARANTINE\nexit 97",
        )
    script = root / "bootstrap.sh"
    script.write_text(text)
    helper_sha = hashlib.sha256(
        (ROOT / "scripts/embedding/_install_experiment_snapshot.py").read_bytes()
    ).hexdigest()
    args = [
        "publish",
        "CPU_INDEX_FP32",
        "",
        helper_sha,
        "/tmp/eom-source/platform.whl",
        "1" * 64,
        "a" * 40,
        "/tmp/eom-source/source.tar",
        "2" * 64,
        "-",
        "-",
        "-",
        "-",
        "-",
        "/tmp/eom-source",
    ]
    return script, prefix, args, marker


def test_synthetic_shell_snapshot_hash_precedes_first_interpreter_instruction(
    tmp_path: Path,
) -> None:
    script, prefix, args, marker = _synthetic_shell(tmp_path)
    # Temporary input-only wheelhouse placeholder; inert interpreter does not parse/install it.
    with tempfile.TemporaryDirectory(prefix="eom-index-source-") as temporary:
        args[-1] = temporary
        fingerprint = subprocess.run(
            ["/usr/bin/bash", str(script), "fingerprint", "CPU_INDEX_FP32"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        args[2] = "0" * 64
        result = subprocess.run(
            ["/usr/bin/bash", str(script), *args], capture_output=True, text=True, check=False
        )
        assert result.returncode != 0 and "TREE_HASH_MISMATCH" in result.stderr
        assert not marker.exists() and prefix.exists()
        args[2] = fingerprint
        result = subprocess.run(
            ["/usr/bin/bash", str(script), *args], capture_output=True, text=True, check=False
        )
        assert result.returncode == 0, result.stderr
        assert marker.exists() and "INSTALLED_NOT_ADMITTED" in result.stdout
        assert "NOT_PROBED" in result.stdout and "ACTIVE" not in result.stdout


def test_interrupted_prefix_replacement_retains_backup_and_quarantine_without_execution(
    tmp_path: Path,
) -> None:
    script, prefix, args, marker = _synthetic_shell(tmp_path, interrupt=True)
    with tempfile.TemporaryDirectory(prefix="eom-index-source-") as temporary:
        args[-1] = temporary
        args[2] = subprocess.run(
            ["/usr/bin/bash", str(script), "fingerprint", "CPU_INDEX_FP32"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        result = subprocess.run(
            ["/usr/bin/bash", str(script), *args], capture_output=True, text=True, check=False
        )
    assert result.returncode == 97 and not prefix.exists() and not marker.exists()
    parent = prefix.parent
    assert len(tuple(parent.glob(".embedding-index-prepublication-*"))) == 1
    assert len(tuple(parent.glob(".embedding-index-runtime-*"))) == 1
    receipt = next((tmp_path / "opt/eom").glob(".embedding-index-install-*/phase-receipt"))
    assert receipt.read_text().endswith("PREFIX_ABSENT_RETAINED_QUARANTINE\n")


def test_new_shell_fixed_boundaries_and_legacy_shell_bytes_are_preserved() -> None:
    subprocess.run(["/usr/bin/bash", "-n", str(SHELL)], check=True)
    text = SHELL.read_text()
    assert '"$PREFIX/bin/python3.12" -I -S -B' in text
    assert (
        text.index("TREE_HASH_MISMATCH")
        < text.index("RUNTIME_LINK_ESCAPE")
        < text.index('"$PREFIX/bin/python3.12" -I -S -B')
    )


def test_synthetic_publication_lock_refuses_concurrent_process_without_overwrite(
    tmp_path: Path,
) -> None:
    script, prefix, args, marker = _synthetic_shell(tmp_path)
    lock = prefix.parent / ".embedding-index-CPU_INDEX_FP32.lock"
    lock.write_bytes(b"")
    lock.chmod(0o600)
    with tempfile.TemporaryDirectory(prefix="eom-index-source-") as temporary:
        args[-1] = temporary
        args[2] = "0" * 64
        with lock.open("rb") as held:
            fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
            result = subprocess.run(
                ["/usr/bin/bash", str(script), *args], capture_output=True, text=True, check=False
            )
    assert result.returncode != 0 and "PUBLICATION_BUSY" in result.stderr
    assert prefix.exists() and not marker.exists()
    assert not tuple(prefix.parent.glob(".embedding-index-runtime-*"))
    text = SHELL.read_text()
    assert text.index("HELPER_HASH_MISMATCH") < text.index('"$PREFIX/bin/python3.12" -I -S -B')
    assert "flock -n" in text and "systemctl" not in text and "MODEL_STORE" not in text
    assert "conda create" not in text and "pip install" not in text and "groupadd" not in text
    assert (
        hashlib.sha256(
            (ROOT / "scripts/embedding/install_experiment_runtime.sh").read_bytes()
        ).hexdigest()
        == "1868abe6a1394bfaf05615ed4e349322105d4929d36cd76433d818865cd6ed87"
    )


def test_every_legacy_helper_function_and_constant_ast_is_unchanged() -> None:
    tree = ast.parse((ROOT / "scripts/embedding/_install_experiment_snapshot.py").read_text())
    historical: list[ast.stmt] = []
    for node in tree.body:
        if (
            isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and node.target.id == "_INDEX_PREFIXES"
        ):
            break
        if isinstance(node, (ast.FunctionDef, ast.Assign, ast.AnnAssign)):
            historical.append(node)
    digest = hashlib.sha256(
        ast.dump(ast.Module(body=historical, type_ignores=[]), include_attributes=False).encode()
    ).hexdigest()
    assert digest == "bd5a238bcc00585eaa267b172ea64c55e1aa9def5aae92b880aa63e09746ae4c"
