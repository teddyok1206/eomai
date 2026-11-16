"""Source-only installer tests; no host identity, package, unit or secret mutations."""

from __future__ import annotations

import ast
import fcntl
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/kakao/install_runtime.py"
spec = importlib.util.spec_from_file_location("kakao_runtime_install_test_subject", SCRIPT)
installer = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = installer
spec.loader.exec_module(installer)
SHA = "sha256:" + "a" * 64


@pytest.fixture
def local(monkeypatch):
    monkeypatch.setattr(installer, "ROOT_UID", os.getuid())
    monkeypatch.setattr(installer, "ROOT_GID", os.getgid())
    with tempfile.TemporaryDirectory(prefix="kakao-install-test-", dir=ROOT / "staging") as folder:
        yield Path(folder)


def put(path, data=b"synthetic", mode=0o644):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o755)
    path.write_bytes(data)
    path.chmod(mode)
    return path


def manifest():
    return {
        "schema_version": "kakao-runtime-install/1.0",
        "source_commit": "a" * 40,
        "profile_id": "kakaoprofile_" + "a" * 32,
        "runtime_sha256": dict.fromkeys(installer.PREFIXES, SHA),
        "browser_assets_sha256": SHA,
        "novnc_assets_sha256": SHA,
        "chromium_member": "chromium-1234/chrome-linux64/chrome",
        "xvnc_sha256": SHA,
        "renderer_release_sha256": SHA,
        "payload_sha256": dict.fromkeys(installer.PAYLOADS, SHA),
    }


def load(local, value):
    path = put(local / "manifest.json", json.dumps(value).encode())
    return installer.load_manifest(path, installer.digest(path))


def test_manifest_schema_matches_strict_local_parser(local):
    value = manifest()
    schema = json.loads(
        (ROOT / "schemas/kakao-archive/runtime-install-v1.schema.json").read_bytes()
    )
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(value)
    assert load(local, value) == value


@pytest.mark.parametrize(
    "mutation",
    [
        lambda v: v.update(command="/bin/bash"),
        lambda v: v.update(source_commit="latest"),
        lambda v: v.update(chromium_member="../../secret"),
        lambda v: v.update(chromium_member="chromium-12/chrome-linux64/chrome\n"),
        lambda v: v["runtime_sha256"].update(api=SHA),
        lambda v: v["payload_sha256"].update(extra=SHA),
        lambda v: v.update(xvnc_sha256=True),
    ],
)
def test_unknown_authority_or_paths_rejected(local, mutation):
    value = manifest()
    mutation(value)
    with pytest.raises(installer.InstallError, match="MANIFEST_INVALID"):
        load(local, value)
    schema = json.loads(
        (ROOT / "schemas/kakao-archive/runtime-install-v1.schema.json").read_bytes()
    )
    assert not Draft202012Validator(schema).is_valid(value)


def test_duplicate_manifest_and_hash_mismatch_are_rejected(local):
    path = put(local / "manifest.json", b'{"source_commit":1,"source_commit":2}')
    with pytest.raises(installer.InstallError, match="HASH_MISMATCH"):
        installer.load_manifest(path, SHA)
    with pytest.raises(installer.InstallError, match="DUPLICATE"):
        installer.load_manifest(path, installer.digest(path))


def test_tree_hash_is_deterministic_and_does_not_follow_links(local):
    directory = local / "runtime"
    directory.mkdir(mode=0o700)
    put(directory / "bin/python3.12", b"not-an-executable-runtime", 0o755)
    (directory / "bin/python").symlink_to("python3.12")
    first = installer.tree_digest(directory)
    assert installer.tree_digest(directory) == first
    put(directory / "new", b"changed")
    assert installer.tree_digest(directory) != first
    (directory / "bad").symlink_to(local / "outside")
    put(local / "outside")
    with pytest.raises(installer.InstallError, match="LINK_ESCAPE"):
        installer.tree_digest(directory)


@pytest.mark.parametrize("kind", ["writable", "hardlink", "fifo", "symlink"])
def test_protected_file_rejects_unsafe_types(local, kind):
    path = put(local / "member")
    if kind == "writable":
        path.chmod(0o666)
    elif kind == "hardlink":
        os.link(path, local / "alias")
    else:
        path.unlink()
        if kind == "fifo":
            os.mkfifo(path)
        else:
            path.symlink_to(put(local / "target"))
    with pytest.raises(installer.InstallError, match="UNTRUSTED"):
        installer.digest(path)


def test_layout_replay_preserves_bytes_and_inode_and_refuses_overwrite(local):
    entry = installer.Layout(local / "config", os.getuid(), os.getgid(), 0o640)
    installer.exact_layout(entry, create=True, content=b"original")
    before = entry.path.stat()
    installer.exact_layout(entry, create=True, content=b"original")
    assert entry.path.stat().st_ino == before.st_ino
    with pytest.raises(installer.InstallError, match="CONFLICT"):
        installer.exact_layout(entry, create=True, content=b"replacement")
    assert entry.path.read_bytes() == b"original"


def test_layout_refuses_symlink_parent_without_touching_target(local):
    target = local / "target"
    target.mkdir()
    alias = local / "alias"
    alias.symlink_to(target)
    entry = installer.Layout(alias / "config", os.getuid(), os.getgid(), 0o600)
    with pytest.raises(OSError):
        installer.exact_layout(entry, create=True, content=b"do-not-write")
    assert not (target / "config").exists()


def test_verify_missing_target_does_not_create(local):
    entry = installer.Layout(local / "missing", os.getuid(), os.getgid(), 0o700)
    with pytest.raises(installer.InstallError, match="MISSING"):
        installer.exact_layout(entry, create=False)
    assert not entry.path.exists()


def test_active_runtime_blocks_before_staging(monkeypatch):
    monkeypatch.setattr(
        installer, "run", lambda *a, **kw: b"eom-kakao-browser.service loaded active running\n"
    )
    with pytest.raises(installer.InstallError, match="ACTIVE_RUNTIME"):
        installer.require_stopped()


def test_queued_systemd_job_is_not_mistaken_for_idle(monkeypatch):
    monkeypatch.setattr(
        installer,
        "run",
        lambda argv, **kw: (
            b"17 eom-kakao-browser.service start waiting\n" if "list-jobs" in argv else b""
        ),
    )
    with pytest.raises(installer.InstallError, match="PENDING_SYSTEMD_JOB"):
        installer.require_stopped()


def test_existing_worker_in_sudo_group_is_not_silently_repaired(monkeypatch):
    user = SimpleNamespace(
        pw_uid=919, pw_gid=919, pw_dir="/nonexistent", pw_shell="/usr/sbin/nologin"
    )
    monkeypatch.setattr(installer.pwd, "getpwnam", lambda name: user)
    monkeypatch.setattr(installer.grp, "getgrnam", lambda name: SimpleNamespace(gr_gid=919))
    monkeypatch.setattr(installer.os, "getgrouplist", lambda *args: [919, 27])
    monkeypatch.setattr(
        installer.grp,
        "getgrgid",
        lambda gid: SimpleNamespace(gr_name="sudo" if gid == 27 else "eom-kakao"),
    )
    with pytest.raises(installer.InstallError, match="OVERPRIVILEGED"):
        installer.check_identities(required=False)


def test_dedicated_dependency_metadata_not_ambient_imports(local):
    prefix = local / "prefix"
    required = {
        "eom-kakao-archive-contracts": "0.1.0",
        "pydantic": "2.13.4",
        "jsonschema": "4.25.1",
        "eom-kakao-archive-collector": "0.1.0",
        "playwright": "1.65.2",
    }
    for name, version in required.items():
        put(
            prefix / f"lib/python3.12/site-packages/{name}-{version}.dist-info/METADATA",
            f"Metadata-Version: 2.1\nName: {name}\nVersion: {version}\n".encode(),
        )
    put(prefix / "bin/python3.12", b"not-executed", 0o755)
    (prefix / "bin/python").symlink_to("python3.12")
    put(prefix / "conda-meta/python-3.12.13-0.json", b'{"name":"python","version":"3.12.13"}')
    installer.check_versions("browser", prefix)
    put(
        prefix / "lib/python3.12/site-packages/playwright-1.65.2.dist-info/METADATA",
        b"Name: playwright\nVersion: 1.55.0\n",
    )
    with pytest.raises(installer.InstallError, match="DEPENDENCY_VERSION_MISMATCH"):
        installer.check_versions("browser", prefix)


def test_preflight_missing_runtime_is_not_ready(local, monkeypatch):
    payload = local / "payload"
    payload.mkdir(mode=0o700)
    for name in installer.PAYLOADS:
        put(payload / name)
    monkeypatch.setattr(installer, "PREFIXES", {"browser": local / "missing"})
    calls = Mock()
    monkeypatch.setattr(installer, "run", calls)
    with pytest.raises(FileNotFoundError):
        installer.preflight(manifest(), payload)
    calls.assert_not_called()


def test_installer_never_embeds_activation_or_secret_generation_commands():
    source = SCRIPT.read_text()
    tree = ast.parse(source)
    constants = {
        n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str)
    }
    forbidden = {
        "daemon-reload",
        "restart",
        "enable",
        "apt-get",
        "pip",
        "vncpasswd",
        "xauth",
    }
    assert not forbidden & constants
    assert "shell=True" not in source


def test_source_cli_is_fail_closed_and_secret_safe_without_root():
    result = subprocess.run(
        [
            sys.executable,
            "-I",
            "-S",
            "-B",
            str(SCRIPT),
            "preflight",
            "--manifest",
            "/private/token-do-not-print",
            "--manifest-sha256",
            SHA,
            "--payload",
            "/private/payload",
        ],
        capture_output=True,
        check=False,
        timeout=5,
    )
    assert result.returncode == 1 and not result.stdout
    assert result.stderr == b"KAKAO_INSTALL_PROTECTED_OPERATOR_REQUIRED\n"


def test_all_unreleased_kakao_prefixes_are_protected_opt_not_shared_srv():
    for filename in (
        "eom-kakao-browser.service",
        "eom-kakao-remote.service",
        "eom-kakao-pdf@.service",
    ):
        source = (ROOT / "infra/systemd" / filename).read_text()
        assert "/opt/eom/conda/envs/eom-kakao-" in source
        assert "/srv/eom/conda/envs/eom-kakao-" not in source


def test_polkit_grants_only_fixed_start_stop_to_catalog():
    source = (ROOT / "infra/polkit/46-eom-kakao-runtime.rules").read_text()
    assert 'subject.user !== "eom-catalog-manager"' in source
    assert '"^(start|stop)$"' not in source  # Regex literal, not a hidden arbitrary action list.
    assert "/^(start|stop)$/" in source and "[0-9a-f]{32}" in source
    assert "manage-unit-files" not in source and "set-property" not in source


def test_fresh_receipt_created_once_and_never_reissued_after_profile_use(local):
    folder = local / "profile"
    folder.mkdir(mode=0o700)
    receipt = local / "fresh-profile.json"
    profile_id = "kakaoprofile_" + "a" * 32
    installer.fresh_receipt(
        folder, receipt, profile_id=profile_id, manifest_sha256=SHA, created=True
    )
    original = receipt.read_bytes()
    schema = json.loads((ROOT / "schemas/kakao-archive/fresh-profile-v1.schema.json").read_bytes())
    Draft202012Validator(schema).validate(json.loads(original))
    put(folder / "browser-used", b"anonymous")
    installer.fresh_receipt(
        folder, receipt, profile_id=profile_id, manifest_sha256=SHA, created=False
    )
    installer.fresh_receipt(
        folder, receipt, profile_id=profile_id, manifest_sha256="sha256:" + "b" * 64, created=False
    )
    assert receipt.read_bytes() == original
    assert folder.stat().st_mtime_ns != json.loads(original)["profile_mtime_ns"]


@pytest.mark.parametrize("created,nonempty", [(False, False), (True, True)])
def test_missing_fresh_receipt_cannot_claim_existing_or_nonempty_profile(local, created, nonempty):
    folder = local / "profile"
    folder.mkdir(mode=0o700)
    if nonempty:
        put(folder / "existing")
    target = local / "fresh-profile.json"
    with pytest.raises(installer.InstallError, match=r"RECONCILE_REQUIRED|NOT_EMPTY"):
        installer.fresh_receipt(
            folder,
            target,
            profile_id="kakaoprofile_" + "a" * 32,
            manifest_sha256=SHA,
            created=created,
        )
    assert not target.exists()


def test_fresh_receipt_wrong_identity_is_not_overwritten(local):
    folder = local / "profile"
    folder.mkdir(mode=0o700)
    target = local / "fresh-profile.json"
    installer.fresh_receipt(
        folder, target, profile_id="kakaoprofile_" + "a" * 32, manifest_sha256=SHA, created=True
    )
    original = target.read_bytes()
    with pytest.raises(installer.InstallError, match="CONFLICT"):
        installer.fresh_receipt(
            folder,
            target,
            profile_id="kakaoprofile_" + "b" * 32,
            manifest_sha256=SHA,
            created=False,
        )
    assert target.read_bytes() == original


def test_installer_checks_real_profile_lock_before_any_mutation(local, monkeypatch):
    lock = put(local / "profile.lock", b"", 0o640)
    monkeypatch.setattr(installer, "RUNTIME_LOCKS", ((lock, "synthetic", 0o640),))
    monkeypatch.setattr(
        installer.pwd,
        "getpwnam",
        lambda name: SimpleNamespace(pw_uid=os.getuid(), pw_gid=os.getgid()),
    )
    with lock.open("rb") as held:
        fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with (
            pytest.raises(installer.InstallError, match="RUNTIME_BUSY"),
            installer.existing_runtime_locks(),
        ):
            pytest.fail("held profile allowed stage")
    with (
        installer.existing_runtime_locks(),
        lock.open("rb") as competing,
        pytest.raises(BlockingIOError),
    ):
        fcntl.flock(competing, fcntl.LOCK_EX | fcntl.LOCK_NB)
    assert lock.read_bytes() == b""
