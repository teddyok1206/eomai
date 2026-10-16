"""Synthetic quarantine files and inert pip double; no root, real install or GPU."""

from __future__ import annotations

import base64
import csv
import hashlib
import io
import json
import os
import subprocess
import tempfile
import zipfile
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

from tests.unit.test_embedding_index_runtime_installation import _synthetic_shell
from tests.unit.test_embedding_index_runtime_installation import helper as helper


def _wheel(path: Path, package: str, *, extra: str | None = None) -> Path:
    dist = f"{package}-0.1.0.dist-info"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(f"{package}/__init__.py", b"# new pinned private source\n")
        archive.writestr(
            f"{dist}/METADATA",
            f"Metadata-Version: 2.1\nName: {package.replace('_', '-')}\nVersion: 0.1.0\n",
        )
        archive.writestr(
            f"{dist}/WHEEL", b"Wheel-Version: 1.0\nRoot-Is-Purelib: true\nTag: py3-none-any\n"
        )
        archive.writestr(f"{dist}/RECORD", b"")
        if package == "eom_platform":
            archive.writestr(
                f"{dist}/entry_points.txt", b"[console_scripts]\neomctl = eomctl.cli:app\n"
            )
        if extra is not None:
            archive.writestr(extra, b"untrusted extra")
    return path


@pytest.fixture
def overlay(
    helper: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[ModuleType, Path, Path, tuple[Path, Path], list[list[str]]]:
    candidate, workspace = tmp_path / "candidate", tmp_path / "workspace"
    old_site = candidate / "lib/python3.12/site-packages"
    old_site.mkdir(parents=True)
    (candidate / "bin").mkdir()
    for package in ("eom_platform", "eom_gpu_lease"):
        dist = old_site / f"{package}-0.1.0.dist-info"
        dist.mkdir()
        if package == "eom_platform":
            (dist / "entry_points.txt").write_text(
                "[console_scripts]\neomctl = eomctl.cli:app\neom-old = eomctl.cli:app\n"
            )
    for name in ("eom_retired", "torch"):
        (old_site / name).mkdir()
        (old_site / name / "__init__.py").write_bytes(b"# retained old bytes\n")
    for name in ("eomctl", "eom-old"):
        (candidate / "bin" / name).write_bytes(b"# retained old wrapper\n")
    workspace.mkdir(mode=0o700)
    wheels = (
        _wheel(tmp_path / "platform.whl", "eom_platform"),
        _wheel(tmp_path / "lease.whl", "eom_gpu_lease"),
    )
    calls: list[list[str]] = []

    def pip(command: list[str], **options: object) -> None:
        calls.append(command)
        assert options["cwd"] == workspace and options["timeout"] == 120
        assert options["check"] is True
        assert options["env"] == {"PATH": "/usr/bin:/bin", "TZ": "UTC", "LANG": "C.UTF-8"}
        assert command[:5] == [helper.sys.executable, "-I", "-B", "-m", "pip"]
        assert {
            "--no-deps",
            "--no-index",
            "--no-compile",
            "--no-cache-dir",
            "--only-binary=:all:",
        } <= set(command)
        site = Path(command[command.index("--target") + 1])
        site.mkdir(parents=True)
        for wheel, package in zip(wheels, ("eom_platform", "eom_gpu_lease"), strict=True):
            with zipfile.ZipFile(wheel) as archive:
                for row in archive.infolist():
                    target = site / row.filename
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(archive.read(row))
            dist = site / f"{package}-0.1.0.dist-info"
            (dist / "INSTALLER").write_bytes(b"pip\n")
            (dist / "REQUESTED").write_bytes(b"")
            (dist / "direct_url.json").write_text(json.dumps({"url": wheel.as_uri()}))
        (site / "bin").mkdir()
        (site / "bin/eomctl").write_bytes(
            b"#!/accepted/OLD/python3.12\nimport sys\nfrom eomctl.cli import app\n"
            b"if __name__ == '__main__':\n    sys.argv[0] = sys.argv[0].removesuffix('.exe')\n"
            b"    sys.exit(app())\n"
        )

    def synthetic_protected(root: Path) -> None:
        assert all(not path.is_symlink() for path in (root, *root.rglob("*")))

    monkeypatch.setattr(subprocess, "run", pip)
    monkeypatch.setattr(helper, "validate_runtime_tree", synthetic_protected)
    return helper, candidate, workspace, wheels, calls


def test_overlay_replaces_only_private_roots_retains_originals_and_repins_records(overlay) -> None:
    module, candidate, workspace, wheels, calls = overlay
    public = candidate / "lib/python3.12/site-packages/torch/__init__.py"
    epoch, raw = public.stat(), public.read_bytes()
    module._index_prepare_private_overlay(candidate, workspace, wheels)
    assert len(calls) == 1
    assert public.stat() == epoch and public.read_bytes() == raw
    assert (candidate / "lib/python3.12/site-packages/eom_platform").stat().st_mode & 0o777 == 0o755
    assert (
        candidate / "lib/python3.12/site-packages/eom_platform/__init__.py"
    ).stat().st_mode & 0o777 == 0o444
    assert (candidate / "bin/eomctl").stat().st_mode & 0o777 == 0o555
    backup = workspace / "prior-private-overlay"
    assert (backup / "site/eom_retired/__init__.py").read_bytes() == b"# retained old bytes\n"
    assert (backup / "bin/eomctl").read_bytes() == b"# retained old wrapper\n"
    assert (backup / "bin/eom-old").exists() and not (candidate / "bin/eom-old").exists()
    assert not (candidate / "lib/python3.12/site-packages/eom_retired").exists()
    wrapper = candidate / "bin/eomctl"
    assert wrapper.read_bytes().startswith(
        b"#!/opt/eom/conda/envs/eom-embedding-cuda/bin/python3.12\n"
    )
    for name in ("eom_platform", "eom_gpu_lease"):
        site = candidate / "lib/python3.12/site-packages"
        record = site / f"{name}-0.1.0.dist-info/RECORD"
        rows = list(csv.reader(io.StringIO(record.read_text())))
        assert rows[-1] == [f"{name}-0.1.0.dist-info/RECORD", "", ""]
        assert len(rows) == len({row[0] for row in rows})
        for path, digest, size in rows[:-1]:
            target = site / path
            assert target.is_file() and digest.startswith("sha256=")
            assert target.stat().st_size == int(size)
            assert digest == "sha256=" + base64.urlsafe_b64encode(
                hashlib.sha256(target.read_bytes()).digest()
            ).decode().rstrip("=")
    with pytest.raises(FileExistsError):
        module._index_prepare_private_overlay(candidate, workspace, wheels)
    assert len(calls) == 1


@pytest.mark.parametrize(
    "extra",
    [
        "../escape.py",
        "torch/hook.py",
        "eom_platform/../escape.py",
        "eom_platform/hook.pyc",
        "eom_platform\\hook.py",
        "sitecustomize.py",
    ],
)
def test_bad_wheel_is_rejected_before_pip_or_old_private_moves(overlay, extra: str) -> None:
    module, candidate, workspace, wheels, calls = overlay
    _wheel(wheels[0], "eom_platform", extra=extra)
    with pytest.raises(module.SnapshotInstallError):
        module._index_prepare_private_overlay(candidate, workspace, wheels)
    assert calls == [] and not (workspace / "prior-private-overlay").exists()
    assert (candidate / "bin/eomctl").read_bytes() == b"# retained old wrapper\n"


def test_pip_failure_preserves_partial_stage_and_never_moves_old_files(
    overlay, monkeypatch: pytest.MonkeyPatch
) -> None:
    module, candidate, workspace, wheels, _calls = overlay

    def failed(*args, **kwargs):
        raise subprocess.CalledProcessError(1, ["inert-pip"])

    monkeypatch.setattr(subprocess, "run", failed)
    with pytest.raises(subprocess.CalledProcessError):
        module._index_prepare_private_overlay(candidate, workspace, wheels)
    assert (workspace / "private-successor").is_dir()
    assert not (workspace / "prior-private-overlay").exists()
    assert (candidate / "bin/eomctl").read_bytes() == b"# retained old wrapper\n"


@pytest.mark.parametrize(
    "fault", ["nonroot", "candidate_python", "site", "wrong_candidate", "wrong_workspace"]
)
def test_entry_context_rejects_before_any_archive_or_filesystem_mutation(
    helper: ModuleType, monkeypatch: pytest.MonkeyPatch, fault: str
) -> None:
    arguments = [
        "bootstrap",
        "--candidate",
        "/opt/eom/conda/envs/.embedding-index-runtime-abcdefgh",
        "--workspace",
        "/opt/eom/.embedding-index-install-abcdefgh",
    ]
    if fault == "wrong_candidate":
        arguments[2] = "/tmp/foreign"
    if fault == "wrong_workspace":
        arguments[4] = "/tmp/foreign"
    for name in ("platform", "lease"):
        for field in ("wheel", "wheel-sha256", "source", "source-sha256", "commit"):
            arguments.extend((f"--{name}-{field}", "unused"))
    monkeypatch.setattr(
        helper,
        "sys",
        SimpleNamespace(
            argv=arguments,
            executable=str(helper.PREFIX / "bin/python3.12")
            if fault != "candidate_python"
            else "/opt/eom/conda/envs/eom-embedding-cuda/bin/python3.12",
            flags=SimpleNamespace(isolated=True, no_site=fault != "site", dont_write_bytecode=True),
            version_info=(3, 12, 13),
            platform="linux",
            stderr=io.StringIO(),
        ),
    )
    monkeypatch.setattr(os, "geteuid", lambda: 1000 if fault == "nonroot" else 0)
    monkeypatch.setattr(
        helper,
        "require_root_path",
        lambda *args, **kwargs: pytest.fail("filesystem before context"),
    )
    monkeypatch.setattr(
        helper,
        "retain_index_archive",
        lambda *args, **kwargs: pytest.fail("archive before context"),
    )
    assert helper.index_private_successor_main() == 1


def test_successor_shell_stops_before_candidate_instruction_and_retains_predecessor(
    tmp_path: Path,
) -> None:
    script, prefix, args, marker = _synthetic_shell(tmp_path, profile="CUDA_INDEX_FP32")
    prefix.chmod(0o755)
    args[0] = "publish-private-successor"
    owner = Path(args[14])
    owner.write_bytes(b'{"schema_version":"embedding-prefix-audit-input/1.2"}')
    args[15] = hashlib.sha256(owner.read_bytes()).hexdigest()
    old = tmp_path / "opt/eom/conda/envs/eom-embedding-experiment/bin/python3.12"
    text = old.read_text()
    text = text.replace(
        "#!/usr/bin/bash\n",
        "#!/usr/bin/bash\nif [[ \"$5\" == index-private-successor ]]; then printf 'PRIVATE\\n' >> '"
        + str(tmp_path / "execution-order")
        + "'; exit 0; fi\n",
        1,
    )
    old.write_text(text)
    with tempfile.TemporaryDirectory(prefix="eom-index-source-") as temporary:
        args[-1] = temporary
        args[2] = subprocess.run(
            ["/usr/bin/bash", str(script), "fingerprint", "CUDA_INDEX_FP32"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        result = subprocess.run(
            ["/usr/bin/bash", str(script), *args], capture_output=True, text=True
        )
    assert result.returncode == 0, result.stderr
    assert not marker.exists()
    assert (tmp_path / "execution-order").read_text().splitlines() == ["HOST", "PRIVATE", "OLD"]
    assert "BYTE_AUDITED_NOT_ADMITTED" in result.stdout and "NOT_PROBED" in result.stdout
    backup = Path(
        next(
            line.split("=", 1)[1]
            for line in result.stdout.splitlines()
            if line.startswith("runtime_backup=")
        )
    )
    assert backup.is_dir() and (backup / "bin/python3.12").exists()
    assert prefix.is_dir() and backup.stat().st_ino != prefix.stat().st_ino


def test_successor_mode_rejects_cpu_before_copy_or_interpreter(tmp_path: Path) -> None:
    script, prefix, args, marker = _synthetic_shell(tmp_path)
    args[0] = "publish-private-successor"
    result = subprocess.run(["/usr/bin/bash", str(script), *args], capture_output=True, text=True)
    assert result.returncode != 0 and "SUCCESSOR_PROFILE_INVALID" in result.stderr
    assert prefix.is_dir() and not marker.exists()
    assert not tuple(prefix.parent.glob(".embedding-index-runtime-*"))


@pytest.mark.parametrize("fault", ["private_failure", "audit_failure", "missing_input12"])
def test_successor_failure_preserves_original_or_backup_and_never_enters_candidate(
    tmp_path: Path, fault: str
) -> None:
    script, prefix, args, marker = _synthetic_shell(
        tmp_path,
        profile="CUDA_INDEX_FP32",
        audit_fault="nonzero" if fault == "audit_failure" else None,
    )
    prefix.chmod(0o755)
    original = prefix.stat().st_ino
    args[0] = "publish-private-successor"
    owner = Path(args[14])
    if fault != "missing_input12":
        owner.write_bytes(b'{"schema_version":"embedding-prefix-audit-input/1.2"}')
        args[15] = hashlib.sha256(owner.read_bytes()).hexdigest()
    old = tmp_path / "opt/eom/conda/envs/eom-embedding-experiment/bin/python3.12"
    old.write_text(
        old.read_text().replace(
            "#!/usr/bin/bash\n",
            '#!/usr/bin/bash\nif [[ "$5" == index-private-successor ]]; then exit '
            + ("17" if fault == "private_failure" else "0")
            + "; fi\n",
            1,
        )
    )
    with tempfile.TemporaryDirectory(prefix="eom-index-source-") as temporary:
        args[-1] = temporary
        args[2] = subprocess.run(
            ["/usr/bin/bash", str(script), "fingerprint", "CUDA_INDEX_FP32"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        result = subprocess.run(
            ["/usr/bin/bash", str(script), *args], capture_output=True, text=True
        )
    assert result.returncode != 0 and not marker.exists()
    if fault == "audit_failure":
        backups = tuple(prefix.parent.glob(".embedding-index-prepublication-CUDA_INDEX_FP32-*"))
        assert len(backups) == 1 and backups[0].stat().st_ino == original
        assert prefix.stat().st_ino != original
    else:
        assert prefix.stat().st_ino == original
        assert tuple(prefix.parent.glob(".embedding-index-runtime-*"))
        assert not tuple(prefix.parent.glob(".embedding-index-prepublication-*"))
    private = next((tmp_path / "opt/eom").glob(".embedding-index-install-*"))
    assert (private / "phase-receipt").exists()
    assert "PREFIX_BYTES_AUDITED_NOT_ADMITTED" not in (private / "phase-receipt").read_text()


@pytest.mark.skipif(
    os.environ.get("EOM_RUN_NATIVE_PRIVATE_WHEEL_ASSEMBLY") != "1",
    reason="opt-in real protected OLD pip with tiny synthetic wheels; no root/GPU/model",
)
def test_real_old_pip_assembles_only_tiny_synthetic_private_wheels(
    helper: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Actual offline toolchain, test-only ownership substitute; not native admission."""
    candidate, workspace = tmp_path / "candidate", tmp_path / "workspace"
    site = candidate / "lib/python3.12/site-packages"
    site.mkdir(parents=True)
    (candidate / "bin").mkdir()
    for name in ("eom_platform", "eom_gpu_lease"):
        (site / f"{name}-0.1.0.dist-info").mkdir()
    workspace.mkdir(mode=0o700)
    wheels = (
        _wheel(tmp_path / "eom_platform-0.1.0-py3-none-any.whl", "eom_platform"),
        _wheel(tmp_path / "eom_gpu_lease-0.1.0-py3-none-any.whl", "eom_gpu_lease"),
    )
    monkeypatch.setattr(
        helper,
        "sys",
        SimpleNamespace(executable="/opt/eom/conda/envs/eom-embedding-experiment/bin/python3.12"),
    )

    def synthetic_owner(root: Path) -> None:
        assert root.is_dir() and not any(path.is_symlink() for path in root.rglob("*"))

    monkeypatch.setattr(helper, "validate_runtime_tree", synthetic_owner)
    previous = os.umask(0o077)
    try:
        helper._index_prepare_private_overlay(candidate, workspace, wheels)
    finally:
        os.umask(previous)
    assert (
        (candidate / "bin/eomctl")
        .read_bytes()
        .startswith(b"#!/opt/eom/conda/envs/eom-embedding-cuda/bin/python3.12\n")
    )
    assert (candidate / "bin/eomctl").stat().st_mode & 0o777 == 0o555
    assert (workspace / "prior-private-overlay/site/eom_platform-0.1.0.dist-info").is_dir()
    helper.verify_platform_wheel(
        candidate, wheels[0], hashlib.sha256(wheels[0].read_bytes()).hexdigest()
    )
