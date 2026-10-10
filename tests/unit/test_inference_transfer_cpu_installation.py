"""Source/fake verification only: never starts a service, installs, or runs a model."""

from __future__ import annotations

import errno
import hashlib
import importlib.util
import os
import subprocess
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest
from eom_catalog_service import inference_transfer_cpu_verifier as probe
from eom_identifiers import canonical_json_bytes
from eom_orchestrator import inference_transfer_cpu_installation as installation
from eom_orchestrator import inference_transfer_cpu_systemd as cpu

from tests.unit.inference_transfer_fixtures import embedding_model

ROOT = Path(__file__).resolve().parents[2]


def snapshot_helper() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "snapshot_installer", ROOT / "scripts/embedding/_install_experiment_snapshot.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def properties(template: str, *, root: bool = False) -> dict[str, str]:
    result = dict.fromkeys(installation._SANDBOX, "")
    result.update(
        {
            "FragmentPath": "/etc/systemd/system/" + template,
            "NeedDaemonReload": "no",
            "User": "root" if root else "eom-embedding-experiment",
            "Group": "root" if root else "eom-embedding-experiment",
            "NoNewPrivileges": "yes",
            "PrivateNetwork": "yes",
            "PrivateDevices": "yes",
            "ProtectSystem": "strict",
            "RestrictAddressFamilies": "AF_UNIX",
        }
    )
    if root:
        result.update(
            {
                "CapabilityBoundingSet": "cap_chown cap_dac_read_search",
                "ReadWritePaths": "/run/eom-embedding-experiments",
            }
        )
    return result


def test_effective_probe_policy_matches_main_and_root_prepare_is_separate() -> None:
    installation.validate_effective_policies(
        properties(cpu.CPU_TEMPLATE),
        properties(installation.PROBE),
        properties(cpu.PREPARE_TEMPLATE, root=True),
    )


@pytest.mark.parametrize(
    "key,value",
    [
        ("DropInPaths", "/etc/override.conf"),
        ("NeedDaemonReload", "yes"),
        ("PrivateNetwork", "no"),
        ("ProtectSystem", "full"),
        ("CapabilityBoundingSet", "cap_sys_admin"),
        ("SupplementaryGroups", "eom"),
        ("User", "eom"),
        ("BindPaths", "/mnt/nas"),
        ("ReadWritePaths", "/"),
    ],
)
def test_effective_policy_drift_rejects(key: str, value: str) -> None:
    observed = properties(installation.PROBE) | {key: value}
    with pytest.raises(ValueError, match="POLICY"):
        installation.validate_effective_policies(
            properties(cpu.CPU_TEMPLATE), observed, properties(cpu.PREPARE_TEMPLATE, root=True)
        )


@pytest.mark.parametrize(
    "key,value",
    [
        ("CapabilityBoundingSet", "cap_sys_admin"),
        ("User", "eom"),
        ("ReadWritePaths", "/mnt/nas"),
        ("SupplementaryGroups", "docker"),
    ],
)
def test_prepare_privileged_effective_policy_rejects(key: str, value: str) -> None:
    with pytest.raises(ValueError, match="PREPARE_POLICY"):
        installation.validate_effective_policies(
            properties(cpu.CPU_TEMPLATE),
            properties(installation.PROBE),
            properties(cpu.PREPARE_TEMPLATE, root=True) | {key: value},
        )


def test_probe_main_security_directives_identical_and_fixed_conda_paths() -> None:
    def parse(path: Path) -> dict[str, tuple[str, ...]]:
        rows: dict[str, list[str]] = {}
        for line in path.read_text().splitlines():
            key, delimiter, value = line.partition("=")
            if delimiter:
                rows.setdefault(key, []).append(value)
        return {key: tuple(value) for key, value in rows.items()}

    main = parse(ROOT / "infra/systemd" / cpu.CPU_TEMPLATE)
    verifier = parse(ROOT / "infra/systemd" / installation.PROBE)
    intentional = {
        "Description",
        "Requires",
        "After",
        "ExecStart",
        "StandardInput",
        "StandardOutput",
    }
    assert {key: value for key, value in main.items() if key not in intentional} == {
        key: value for key, value in verifier.items() if key not in intentional
    }
    assert str(cpu.CPU_PYTHON) in main["ExecStart"][0]
    assert cpu.CPU_PYTHON == cpu.PREPARE_PYTHON
    assert "/opt/eom/embedding-models" in main["ReadOnlyPaths"]
    assert (
        hashlib.sha256((ROOT / "infra/systemd" / installation.PROBE).read_bytes()).hexdigest()
        == installation.PROBE_SHA256
    )
    assert (
        hashlib.sha256((ROOT / "infra/polkit/50-eom-worker-units.rules").read_bytes()).hexdigest()
        == installation.POLKIT_SHA256
    )


def test_probe_never_reads_forbidden_opened_bytes(monkeypatch: pytest.MonkeyPatch) -> None:
    opened: list[str] = []
    closed: list[int] = []
    monkeypatch.setattr(probe.os, "open", lambda path, flags: opened.append(str(path)) or 73)
    monkeypatch.setattr(probe.os, "close", closed.append)
    monkeypatch.setattr(probe.os, "read", lambda *_a: pytest.fail("no forbidden content read"))
    with pytest.raises(ValueError, match="FORBIDDEN_ACCESS"):
        probe.denied_file(Path("/etc/eom"))
    assert opened == ["/etc/eom"] and closed == [73]


@pytest.mark.parametrize(
    "exception,expected", [(PermissionError, "DENIED"), (FileNotFoundError, "ABSENT_IN_SANDBOX")]
)
def test_absence_is_not_falsely_called_permission_denial(
    monkeypatch: pytest.MonkeyPatch, exception: type[OSError], expected: str
) -> None:
    def denied(*_a: Any) -> Any:
        raise exception()

    monkeypatch.setattr(probe.os, "open", denied)
    assert probe.denied_file(Path("/dev/nvidia0")) == expected


@pytest.mark.parametrize(
    "code,accepted",
    [
        (errno.EAFNOSUPPORT, True),
        (errno.EPERM, True),
        (errno.EACCES, True),
        (errno.EMFILE, False),
        (errno.ENOMEM, False),
    ],
)
def test_network_negative_requires_policy_errno_not_resource_failure(
    monkeypatch: pytest.MonkeyPatch, code: int, accepted: bool
) -> None:
    monkeypatch.setattr(probe.os, "listdir", lambda _p: ["lo"])

    def denied(*_a: Any, **_k: Any) -> Any:
        raise OSError(code, "not emitted")

    monkeypatch.setattr(probe.socket, "socket", denied)
    if accepted:
        probe.verify_no_network()
    else:
        with pytest.raises(ValueError, match="NETWORK_CHECK_FAILED"):
            probe.verify_no_network()


def test_probe_manifest_materialization_bounded_and_no_follow(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    spec = embedding_model("intfloat/multilingual-e5-small")
    path = tmp_path / "manifest.json"
    path.write_bytes(canonical_json_bytes(spec.model_dump(mode="json")))
    monkeypatch.setattr(probe, "_protected", lambda value: value)
    assert probe.read_cpu_model_spec(tmp_path) == spec
    path.write_bytes(b"x" * (128 * 1024 + 1))
    with pytest.raises(ValueError, match="MODEL_MISMATCH"):
        probe.read_cpu_model_spec(tmp_path)
    path.unlink()
    os.mkfifo(path, 0o600)
    with pytest.raises(ValueError, match="MODEL_MISMATCH"):
        probe.read_cpu_model_spec(tmp_path)
    path.unlink()
    path.symlink_to(tmp_path / "missing")
    with pytest.raises(OSError):
        probe.read_cpu_model_spec(tmp_path)


def test_probe_failure_redacts_private_exception(
    monkeypatch: pytest.MonkeyPatch, capfd: pytest.CaptureFixture[str]
) -> None:
    def fail() -> Any:
        print("private runtime diagnostic")
        raise ValueError("secret request content")

    monkeypatch.setattr(probe, "run_probe", fail)
    assert probe.main() == 1
    captured = capfd.readouterr()
    assert captured.out == "INFERENCE_CPU_ISOLATION_PROBE_REJECTED\n" and captured.err == ""


def test_fixed_polkit_probe_tests_scope_without_unit_mutation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, ...]] = []

    def run(argv: tuple[str, ...], **_kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 0 if len(calls) == 1 else 1)

    monkeypatch.setattr(installation.subprocess, "run", run)
    installation.verify_polkit_scope()
    assert len(calls) == 6 and all("pkcheck" in call[6] for call in calls)
    assert all(call[0] == "/usr/sbin/runuser" and "systemctl" not in repr(call) for call in calls)


def test_no_privileged_probe_or_source_execution_in_unit_tests(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(installation.os, "geteuid", lambda: 1000)
    monkeypatch.setattr(
        installation.subprocess, "run", lambda *_a, **_k: pytest.fail("no root bypass")
    )
    with pytest.raises(ValueError, match="ROOT_REQUIRED"):
        installation.verify_fixed_cpu_installation()


def test_source_installer_independent_hash_precedes_first_interpreter_and_no_system_python() -> (
    None
):
    source = (ROOT / "scripts/embedding/install_experiment_runtime.sh").read_text()
    first = source.index('"$PREFIX/bin/python" -I -S -B')
    assert source.index('tree_digest "$QUARANTINE"') < first
    assert source.index("EMBEDDING_RUNTIME_LINK_ESCAPE") < first
    assert source.index("EMBEDDING_INSTALLER_HASH_MISMATCH") < first
    assert "--no-preserve=links,ownership,xattr,context" in source and "cp -a" in source
    assert (
        "/usr/bin/python" not in source
        and "conda create" not in source
        and "pip install" not in source
    )
    assert 'mv -T -- "$PREFIX" "$BACKUP"' in source and 'mv -T -- "$QUARANTINE" "$PREFIX"' in source
    assert source.index('mv -T -- "$QUARANTINE" "$PREFIX"') < first
    assert source.index("record_phase STAGED_NOT_ACTIVATED") < first
    assert "rm -" not in source and "reset-failed" not in source
    subprocess.run(
        ("/bin/bash", "-n", str(ROOT / "scripts/embedding/install_experiment_runtime.sh")),
        check=True,
    )


def run_fingerprint_function(
    tmp_path: Path, *, define_only: bool = False
) -> subprocess.CompletedProcess[str]:
    """Exercise real non-root Bash parsing/behavior without fixed-prefix/privileged mutation."""
    if os.geteuid() == 0:
        pytest.skip("non-root fingerprint regression requires an unprivileged test process")
    source = (ROOT / "scripts/embedding/install_experiment_runtime.sh").read_text()
    function = source[source.index("tree_digest() {") : source.index("\nmode=${1:-}")]
    invocation = "declare -F tree_digest >/dev/null" if define_only else 'tree_digest "$1"'
    script = (
        'set -euo pipefail\nfail() { printf "%s\\n" "$1" >&2; exit 1; }\n'
        + function
        + "\n"
        + invocation
    )
    return subprocess.run(
        ("/bin/bash", "-c", script, "fingerprint-test", str(tmp_path)),
        text=True,
        capture_output=True,
        timeout=10,
        check=False,
        env={"PATH": "/usr/bin:/bin", "LC_ALL": "C", "TZ": "UTC"},
    )


def test_real_nonroot_bash_fingerprint_definition_has_no_output(tmp_path: Path) -> None:
    result = run_fingerprint_function(tmp_path, define_only=True)
    assert result.returncode == 0 and result.stdout == "" and result.stderr == ""


def test_real_nonroot_bash_fingerprint_matches_sorted_independent_records(tmp_path: Path) -> None:
    (tmp_path / "dir").mkdir()
    (tmp_path / "dir/file").write_bytes(b"reviewed data")
    (tmp_path / "link").symlink_to("dir/file")
    digest = hashlib.sha256(b"reviewed data").hexdigest().encode("ascii")
    expected = hashlib.sha256(
        b"D\0./dir\0F\0./dir/file\0" + digest + b"\0L\0./link\0dir/file\0"
    ).hexdigest()
    result = run_fingerprint_function(tmp_path)
    assert result.returncode == 0 and result.stdout == expected + "\n" and result.stderr == ""


@pytest.mark.parametrize("kind", ["fifo", "hardlink", "control_name"])
def test_real_nonroot_bash_fingerprint_rejects_untrusted_fixture(tmp_path: Path, kind: str) -> None:
    if kind == "fifo":
        os.mkfifo(tmp_path / "fifo", 0o600)
    elif kind == "hardlink":
        (tmp_path / "file").write_bytes(b"shared inode")
        os.link(tmp_path / "file", tmp_path / "link")
    else:
        (tmp_path / "bad\nname").write_bytes(b"invalid name")
    result = run_fingerprint_function(tmp_path)
    assert result.returncode != 0 and "EMBEDDING_RUNTIME_" in result.stderr


def test_installer_fixed_reviewed_model_pins_match_acquisition_module() -> None:
    helper = snapshot_helper()
    spec = importlib.util.spec_from_file_location(
        "model_acquisition", ROOT / "scripts/embedding/acquire_e5_small_probe.py"
    )
    assert spec and spec.loader
    acquisition = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(acquisition)
    assert {name: (size, digest) for name, size, digest in acquisition.FILES} == {
        name: value for name, value in helper.MODEL_MEMBERS.items() if name != "manifest.json"
    }


def test_snapshot_hash_rejects_link_hardlink_and_renamed_inode(tmp_path: Path) -> None:
    helper = snapshot_helper()
    target = tmp_path / "file"
    target.write_bytes(b"reviewed bytes")
    assert helper._hash(target) == hashlib.sha256(b"reviewed bytes").hexdigest()
    link = tmp_path / "link"
    link.symlink_to(target)
    with pytest.raises(OSError):
        helper._hash(link)
    hardlink = tmp_path / "hardlink"
    os.link(target, hardlink)
    with pytest.raises(ValueError, match="FILE_INVALID"):
        helper._hash(target)


def model_source(tmp_path: Path, helper: ModuleType) -> tuple[Path, Path]:
    store = tmp_path / "source"
    source = store / helper.MODEL_ID / helper.MODEL_REVISION
    source.mkdir(parents=True, mode=0o700)
    for directory in (store, source.parent, source):
        directory.chmod(0o700)
    (source / "1_Pooling").mkdir(mode=0o700)
    payloads = {"manifest.json": b"TEST_ONLY", "1_Pooling/config.json": b"{}"}
    helper.MODEL_MEMBERS = {
        name: (len(raw), hashlib.sha256(raw).hexdigest()) for name, raw in payloads.items()
    }
    for name, raw in payloads.items():
        (source / name).write_bytes(raw)
        (source / name).chmod(0o600)
    target_parent = tmp_path / "target"
    target_parent.mkdir(mode=0o700)
    return source, target_parent / helper.MODEL_REVISION


def test_model_handoff_copy_uses_new_inodes_and_independent_pins_fake_ownership(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    helper = snapshot_helper()
    source, target = model_source(tmp_path, helper)
    monkeypatch.setattr(helper, "require_root_path", lambda *_a, **_k: None)
    monkeypatch.setattr(helper.os, "chown", lambda *_a, **_k: None)
    helper.copy_reviewed_model(source, target, source_uid=os.geteuid(), cpu_gid=os.getegid())
    assert (target / "manifest.json").read_bytes() == b"TEST_ONLY"
    assert (target / "manifest.json").stat().st_ino != (source / "manifest.json").stat().st_ino
    assert (target / "manifest.json").stat().st_mode & 0o777 == 0o440
    with pytest.raises(ValueError, match="TARGET_EXISTS"):
        helper.copy_reviewed_model(source, target, source_uid=os.geteuid(), cpu_gid=os.getegid())


@pytest.mark.parametrize("mutation", ["symlink", "hash", "extra", "hardlink", "fifo"])
def test_model_handoff_rejects_untrusted_member_or_extra_file_preserves_partial(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mutation: str
) -> None:
    helper = snapshot_helper()
    source, target = model_source(tmp_path, helper)
    monkeypatch.setattr(helper, "require_root_path", lambda *_a, **_k: None)
    monkeypatch.setattr(helper.os, "chown", lambda *_a, **_k: None)
    if mutation == "symlink":
        (source / "manifest.json").unlink()
        (source / "manifest.json").symlink_to(source / "1_Pooling/config.json")
    elif mutation == "hash":
        (source / "manifest.json").write_bytes(b"WRONG_RAW")
    elif mutation == "extra":
        (source / "extra").write_bytes(b"unlisted")
    elif mutation == "fifo":
        (source / "manifest.json").unlink()
        os.mkfifo(source / "manifest.json", 0o600)
    else:
        os.link(source / "manifest.json", tmp_path / "hardlink")
    with pytest.raises((ValueError, OSError)):
        helper.copy_reviewed_model(source, target, source_uid=os.geteuid(), cpu_gid=os.getegid())
    assert (source / "manifest.json").exists()
    if target.exists():
        assert target.stat().st_mode & 0o777 == 0o700


def test_model_handoff_zero_write_fails_without_infinite_loop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    helper = snapshot_helper()
    source, target = model_source(tmp_path, helper)
    monkeypatch.setattr(helper, "require_root_path", lambda *_a, **_k: None)
    monkeypatch.setattr(helper.os, "write", lambda *_a, **_k: 0)
    with pytest.raises(ValueError, match="OUTPUT_WRITE_FAILED"):
        helper.copy_reviewed_model(source, target, source_uid=os.geteuid(), cpu_gid=os.getegid())


def test_shared_ancestor_atime_and_content_change_not_selected_directory_identity() -> None:
    helper = snapshot_helper()
    before = SimpleNamespace(
        st_dev=1,
        st_ino=2,
        st_mode=0o41777,
        st_uid=0,
        st_gid=0,
        st_nlink=3,
        st_size=100,
        st_mtime_ns=1,
        st_ctime_ns=1,
    )
    changed = SimpleNamespace(
        **(vars(before) | {"st_nlink": 4, "st_size": 200, "st_mtime_ns": 2, "st_ctime_ns": 2})
    )
    assert helper._ancestor_identity(before) == helper._ancestor_identity(changed)
    assert helper._epoch(before) != helper._epoch(changed)


@pytest.mark.parametrize("existing", [False, True])
def test_owner_workspace_fixed_child_creation_or_exact_reuse_fake_owner(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, existing: bool
) -> None:
    helper = snapshot_helper()
    parent = tmp_path / "owner"
    parent.mkdir(mode=0o700)
    child = parent / "inference-transfer-experiments"
    if existing:
        child.mkdir(mode=0o700)
        (child / "preserved-marker").write_bytes(b"history")
    monkeypatch.setattr(
        helper,
        "Path",
        lambda value: parent if value == "/var/lib/eom-workflow-runner" else Path(value),
    )
    monkeypatch.setattr(helper, "require_root_path", lambda *_a, **_k: None)
    monkeypatch.setattr(
        helper.pwd,
        "getpwnam",
        lambda _name: SimpleNamespace(pw_uid=os.geteuid(), pw_gid=os.getegid()),
    )
    monkeypatch.setattr(helper.os, "fchown", lambda *_a, **_k: None)
    helper.ensure_owner_workspace()
    assert child.stat().st_mode & 0o777 == 0o700
    if existing:
        assert (child / "preserved-marker").read_bytes() == b"history"


@pytest.mark.parametrize("kind", ["symlink", "wrong_mode"])
def test_owner_workspace_rejects_link_or_relaxed_existing_metadata_without_fixup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, kind: str
) -> None:
    helper = snapshot_helper()
    parent = tmp_path / "owner"
    parent.mkdir(mode=0o700)
    child = parent / "inference-transfer-experiments"
    if kind == "symlink":
        child.symlink_to(tmp_path, target_is_directory=True)
    else:
        child.mkdir(mode=0o755)
    monkeypatch.setattr(
        helper,
        "Path",
        lambda value: parent if value == "/var/lib/eom-workflow-runner" else Path(value),
    )
    monkeypatch.setattr(helper, "require_root_path", lambda *_a, **_k: None)
    monkeypatch.setattr(
        helper.pwd,
        "getpwnam",
        lambda _name: SimpleNamespace(pw_uid=os.geteuid(), pw_gid=os.getegid()),
    )
    monkeypatch.setattr(helper.os, "fchown", lambda *_a, **_k: pytest.fail("no metadata repair"))
    with pytest.raises((ValueError, OSError)):
        helper.ensure_owner_workspace()
    if kind == "wrong_mode":
        assert child.stat().st_mode & 0o777 == 0o755


def test_snapshot_mechanical_helper_failure_redacts_raw_validation(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    helper = snapshot_helper()
    monkeypatch.setattr(
        sys := helper.sys,
        "argv",
        [
            "installer",
            "--runtime",
            "/invalid",
            "--wheel",
            "/invalid",
            "--wheel-sha256",
            "0" * 64,
            "--model-source",
            "/invalid",
            "--source-uid",
            "1000",
            "--cpu-gid",
            "997",
        ],
    )
    monkeypatch.setattr(helper.os, "geteuid", lambda: 1000)
    assert helper.main() == 1
    assert capsys.readouterr().err == "EMBEDDING_RUNTIME_PUBLICATION_REJECTED\n"
    assert sys is helper.sys
