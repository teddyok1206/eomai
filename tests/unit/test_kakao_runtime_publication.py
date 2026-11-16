"""Unprivileged synthetic fixed-prefix publication; no real /opt, users or units."""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
from contextlib import nullcontext
from pathlib import Path
from unittest.mock import Mock

import packaging
import pytest
from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[2]


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    sys.modules[name] = value
    spec.loader.exec_module(value)
    return value


publisher = module("kakao_publication_test_subject", ROOT / "scripts/kakao/publish_runtime.py")
installer = module(
    "kakao_publication_install_test_subject", ROOT / "scripts/kakao/install_runtime.py"
)
SHA = "sha256:" + "a" * 64


def put(path, data=b"fixture", mode=0o644):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o755)
    path.write_bytes(data)
    path.chmod(mode)
    return path


@pytest.fixture
def local(monkeypatch):
    for target in (publisher, installer):
        monkeypatch.setattr(target, "ROOT_UID", os.getuid())
        monkeypatch.setattr(target, "ROOT_GID", os.getgid())
    with tempfile.TemporaryDirectory(
        prefix="kakao-publication-test-", dir=ROOT / "staging"
    ) as name:
        root = Path(name)
        root.chmod(0o700)
        monkeypatch.setattr(publisher, "PUBLISH_ROOT", root)
        monkeypatch.setattr(publisher, "RECEIPT", root / "receipt.json")
        monkeypatch.setattr(publisher, "LOCK", root / "locks/install.lock")
        monkeypatch.setattr(
            installer, "PREFIXES", {role: root / "fixed" / role for role in publisher.ROLE_NAMES}
        )
        monkeypatch.setattr(installer, "BROWSER", root / "assets/playwright")
        monkeypatch.setattr(installer, "NOVNC", root / "assets/noVNC")
        previous_mask = os.umask(0o022)
        try:
            yield root
        finally:
            os.umask(previous_mask)


def plan():
    return {
        "schema_version": "kakao-runtime-publication/1.0",
        "install_manifest_sha256": SHA,
        "source_uid": os.getuid(),
        "dependency_lock": {role: {"package": "1.0"} for role in publisher.ROLE_NAMES},
    }


def load(local, value):
    path = put(local / "publication.json", json.dumps(value).encode(), mode=0o600)
    return publisher.load_plan(path, installer.digest(path))


def test_plan_schema_and_bootstrap_parser_agree(local):
    schema = json.loads(
        (ROOT / "schemas/kakao-archive/runtime-publication-v1.schema.json").read_bytes()
    )
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(plan())
    assert load(local, plan()) == plan()


@pytest.mark.parametrize(
    "change",
    [
        lambda p: p.update(target="/tmp/elsewhere"),
        lambda p: p.update(source_uid=0),
        lambda p: p.update(source_uid=True),
        lambda p: p.update(install_manifest_sha256="latest"),
        lambda p: p["dependency_lock"].update(api={"package": "1"}),
        lambda p: p["dependency_lock"].update(browser={}),
        lambda p: p["dependency_lock"]["browser"].update(Package="1"),
        lambda p: p["dependency_lock"]["browser"].update(package="1\n"),
    ],
)
def test_plan_rejects_authority_paths_or_inexact_locks(local, change):
    value = plan()
    change(value)
    with pytest.raises(publisher.PublicationError):
        load(local, value)


def test_root_input_rejects_wrong_hash_duplicate_key_and_alias(local):
    path = put(local / "publication.json", b'{"schema_version":1,"schema_version":2}', mode=0o600)
    with pytest.raises(publisher.PublicationError, match="HASH_MISMATCH"):
        publisher.load_plan(path, SHA)
    with pytest.raises(publisher.PublicationError, match="DUPLICATE_KEY"):
        publisher.load_plan(path, installer.digest(path))
    os.link(path, local / "alias")
    with pytest.raises(publisher.PublicationError, match="INPUT_UNTRUSTED"):
        publisher.load_plan(path, SHA)


def test_copy_has_new_inodes_no_hardlinks_and_same_reviewed_tree(local):
    source = local / "source"
    original = put(source / "lib/file")
    os.link(original, source / "lib/shared")
    (source / "current").symlink_to("lib/file")
    fingerprint = publisher.snapshot(source, None, source_uid=os.getuid())
    output = local / "quarantine"
    assert publisher.snapshot(source, output, source_uid=os.getuid()) == fingerprint
    assert installer.tree_digest(output) == fingerprint
    assert (output / "lib/file").stat().st_ino != original.stat().st_ino
    assert (output / "lib/file").stat().st_ino != (output / "lib/shared").stat().st_ino
    assert (output / "lib/file").stat().st_nlink == 1
    assert (output / "current").is_symlink()


@pytest.mark.parametrize(
    "kind", ["fifo", "escaping-link", "absolute-link", "writable", "suid", "control-name"]
)
def test_untrusted_source_members_never_reach_publication(local, kind):
    source = local / "source"
    source.mkdir()
    if kind == "fifo":
        os.mkfifo(source / "member")
    elif kind == "escaping-link":
        (source / "member").symlink_to("../outside")
    elif kind == "absolute-link":
        (source / "member").symlink_to("/etc/passwd")
    else:
        put(
            source / ("bad\nname" if kind == "control-name" else "member"),
            mode=0o666 if kind == "writable" else 0o4755 if kind == "suid" else 0o644,
        )
    with pytest.raises(publisher.PublicationError):
        publisher.snapshot(source, local / "quarantine", source_uid=os.getuid())


def candidates(local):
    trees = {}
    for name, target in publisher.targets(installer).items():
        put(target / "bin/python3.12", b"inert fixture", mode=0o755)
        trees[name] = publisher.snapshot(target, None, source_uid=os.getuid())
    return {
        "runtime_sha256": {role: trees[role] for role in publisher.ROLE_NAMES},
        "browser_assets_sha256": trees["playwright"],
        "novnc_assets_sha256": trees["novnc"],
    }


def test_all_snapshots_published_before_any_candidate_interpreter_and_exact_replay(
    local, monkeypatch
):
    manifest = candidates(local)
    old_inodes = {
        name: target.stat().st_ino for name, target in publisher.targets(installer).items()
    }
    versions = Mock()
    monkeypatch.setattr(installer, "check_versions", versions)
    observations = []

    def run(argv, *, capture=False):
        for name, target in publisher.targets(installer).items():
            assert target.stat().st_ino != old_inodes[name]
            assert installer.tree_digest(target) == publisher.expected_trees(manifest)[name]
        assert argv[1:5] == ["-I", "-S", "-B", "-c"] and capture
        assert Path(argv[0]).parent.parent in installer.PREFIXES.values()
        observations.append(argv[0])
        return b'{"package":"1.0"}'

    monkeypatch.setattr(installer, "run", run)
    quarantine = publisher.publish(installer, manifest, plan(), SHA)
    assert len(observations) == 3 and versions.call_count == 3
    assert quarantine.is_dir()
    assert len(list(quarantine.glob("*-builder-backup"))) == 5
    assert (quarantine / "phase-receipt").read_text().endswith("VERIFIED_NOT_ACTIVATED\n")
    assert publisher.publish(installer, manifest, plan(), SHA) is None
    assert len(observations) == 6


def test_wrong_tree_never_moves_source_or_executes_candidate(local, monkeypatch):
    manifest = candidates(local)
    manifest["novnc_assets_sha256"] = SHA
    execute = Mock()
    monkeypatch.setattr(installer, "run", execute)
    before = {name: target.stat().st_ino for name, target in publisher.targets(installer).items()}
    with pytest.raises(publisher.PublicationError, match="TREE_HASH_MISMATCH"):
        publisher.publish(installer, manifest, plan(), SHA)
    assert before == {
        name: target.stat().st_ino for name, target in publisher.targets(installer).items()
    }
    assert not publisher.RECEIPT.exists()
    execute.assert_not_called()
    assert list(local.glob(".kakao-runtime-publish-*"))  # Failed evidence retained.


def test_dependency_failure_retains_staged_state_and_no_success_receipt(local, monkeypatch):
    manifest = candidates(local)
    monkeypatch.setattr(installer, "check_versions", Mock())
    monkeypatch.setattr(installer, "run", Mock(return_value=b'{"package":"2.0"}'))
    with pytest.raises(publisher.PublicationError, match="DEPENDENCY_LOCK_MISMATCH"):
        publisher.publish(installer, manifest, plan(), SHA)
    assert not publisher.RECEIPT.exists()
    quarantine = next(local.glob(".kakao-runtime-publish-*"))
    assert (quarantine / "phase-receipt").read_text().endswith("STAGED_NOT_ACTIVATED\n")
    assert len(list(quarantine.glob("*-builder-backup"))) == 5


def test_probe_mutation_cannot_leave_a_success_receipt(local, monkeypatch):
    manifest = candidates(local)
    monkeypatch.setattr(installer, "check_versions", Mock())

    def mutate(argv, *, capture):
        put(installer.PREFIXES["browser"] / "unexpected")
        return b'{"package":"1.0"}'

    monkeypatch.setattr(installer, "run", mutate)
    with pytest.raises(publisher.PublicationError, match="PROBE_MUTATED_RUNTIME"):
        publisher.publish(installer, manifest, plan(), SHA)
    assert not publisher.RECEIPT.exists()


def test_prepare_is_fixed_empty_initial_only_and_does_not_execute(local, monkeypatch):
    execute = Mock()
    monkeypatch.setattr(installer, "run", execute)

    def protected_fixture_parent(path, *, directory):
        # /home fixture ancestors may be either actual root or the test UID;
        # no operational path or permission is changed by this privilege seam.
        assert directory and path.is_dir() and not path.is_symlink()
        info = path.stat()
        assert info.st_uid in {0, os.getuid()} and not info.st_mode & 0o022
        return info

    monkeypatch.setattr(installer, "protected", protected_fixture_parent)
    publisher.prepare(installer, source_uid=os.getuid(), source_gid=os.getgid())
    assert all(
        target.is_dir() and not list(target.iterdir())
        for target in publisher.targets(installer).values()
    )
    with pytest.raises(publisher.PublicationError, match="TARGET_EXISTS"):
        publisher.prepare(installer, source_uid=os.getuid(), source_gid=os.getgid())
    execute.assert_not_called()


def test_publication_uses_same_exclusive_install_lock_and_no_service_start(local, monkeypatch):
    monkeypatch.setattr(installer, "require_stopped", Mock())
    monkeypatch.setattr(installer, "existing_runtime_locks", lambda: nullcontext())
    with (
        publisher.publication_lock(installer),
        pytest.raises(BlockingIOError),
        publisher.publication_lock(installer),
    ):
        pytest.fail("simultaneous publication acquired fixed installation lock")
    installer.require_stopped.assert_called_once()


def test_existing_unowned_target_is_not_an_upgrade_input(local, monkeypatch):
    manifest = candidates(local)
    invalid = plan()
    invalid["source_uid"] += 1
    execute = Mock()
    monkeypatch.setattr(installer, "run", execute)
    with pytest.raises(publisher.PublicationError, match="INITIAL_ONLY_RECONCILE_REQUIRED"):
        publisher.publish(installer, manifest, invalid, SHA)
    execute.assert_not_called()
    assert not list(local.glob(".kakao-runtime-publish-*"))


def test_bootstrap_helper_is_loaded_only_from_verified_bytes(local):
    path = put(local / "install_runtime.py", b'BOUNDARY="checked-bytes"\n', mode=0o600)
    with pytest.raises(publisher.PublicationError, match="HASH_MISMATCH"):
        publisher.load_installer(path, SHA)
    assert publisher.load_installer(path, installer.digest(path)).BOUNDARY == "checked-bytes"


def distribution(prefix, name, version="1.0", *, requirements=(), editable=False):
    metadata = f"Metadata-Version: 2.1\nName: {name}\nVersion: {version}\nRequires-Python: >=3.12\n"
    metadata += "".join("Requires-Dist: " + requirement + "\n" for requirement in requirements)
    directory = prefix / "lib/python3.12/site-packages" / (name + ".dist-info")
    put(directory / "METADATA", metadata.encode())
    if editable:
        put(directory / "direct_url.json", b'{"dir_info":{"editable":true},"url":"file:///no"}')


@pytest.mark.parametrize("fault", [None, "missing", "version", "extra", "editable", "direct"])
def test_actual_isolated_dependency_closure_probe(local, fault):
    prefix = local / "prefix"
    required = "dep[required]>=1.0" if fault == "extra" else "dep>=1.0"
    if fault == "direct":
        required = "dep @ https://invalid.example/dep.whl"
    distribution(prefix, "entry", requirements=(required,), editable=fault == "editable")
    if fault != "missing":
        distribution(
            prefix,
            "dep",
            "0.5" if fault == "version" else "1.0",
            requirements=('absent; extra == "required"',) if fault == "extra" else (),
        )
    # Inert fixture prefix aliases only in this unprivileged subprocess. Production
    # BOOTSTRAP still requires the actual final Conda prefix before imports.
    fixture = (
        "import sys; sys.prefix=sys.exec_prefix=sys.argv[1]; sys.path.insert(0,"
        + repr(str(Path(packaging.__file__).parent.parent))
        + ");\n"
    )
    result = subprocess.run(
        [sys.executable, "-I", "-S", "-B", "-c", fixture + publisher.BOOTSTRAP, str(prefix)],
        capture_output=True,
        timeout=10,
        check=False,
    )
    assert (result.returncode == 0) is (fault is None)
    if fault is None:
        assert json.loads(result.stdout) == {"entry": "1.0", "dep": "1.0"}
