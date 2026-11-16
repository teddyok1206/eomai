from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "web_wheel_closure", ROOT / "scripts/web_gui/wheel_closure.py"
)
assert SPEC is not None and SPEC.loader is not None
closure = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = closure
SPEC.loader.exec_module(closure)
COMMIT = "a" * 40
PINS = {"eom-web-gui": "0.1.0", "eom-kakao-archive-contracts": "0.1.0", "jsonschema": "4.26.0"}


def wheel(
    directory: Path, name: str, version: str, *, tag: str = "py3", requires: str = ""
) -> Path:
    escaped = name.replace("-", "_")
    path = directory / f"{escaped}-{version}-{tag}-none-any.whl"
    metadata_root = f"{escaped}-{version}.dist-info"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(
            f"{metadata_root}/METADATA",
            f"Metadata-Version: 2.1\nName: {name}\nVersion: {version}\n{requires}",
        )
        archive.writestr(
            f"{metadata_root}/WHEEL",
            "Wheel-Version: 1.0\nGenerator: closure-test\n"
            "Root-Is-Purelib: true\nTag: py3-none-any\n",
        )
        archive.writestr(f"{metadata_root}/RECORD", "")
        if name == "eom-web-gui":
            archive.writestr("eom_web_gui/build-info.json", json.dumps({"source_commit": COMMIT}))
    return path


@pytest.fixture
def bundle(tmp_path: Path):
    source, destination = tmp_path / "source", tmp_path / "private"
    source.mkdir()
    destination.mkdir(mode=0o700)
    for name, version in PINS.items():
        wheel(source, name, version)
    wheels = closure.read_wheels(source, PINS)
    lock = closure.locked_bytes(wheels)
    (source / closure.LOCK_NAME).write_bytes(lock)
    return (
        source,
        destination,
        {
            "expected_lock_sha256": hashlib.sha256(lock).hexdigest(),
            "expected_web_sha256": wheels["eom-web-gui"].sha256,
            "expected_commit": COMMIT,
        },
    )


def test_complete_closure_copied_to_private_staging_before_execution(bundle) -> None:
    source, destination, expected = bundle
    closure.stage_closure(source, destination, PINS, **expected)
    assert {path.name for path in source.iterdir()} == {path.name for path in destination.iterdir()}
    for original in source.iterdir():
        staged = destination / original.name
        assert original.read_bytes() == staged.read_bytes()
        assert staged.stat().st_mode & 0o777 == 0o600
    # Source is no longer the input to pip; changing it cannot change approved staged bytes.
    original = source / "jsonschema-4.26.0-py3-none-any.whl"
    staged_bytes = (destination / original.name).read_bytes()
    original.write_bytes(b"changed after stage")
    assert (destination / original.name).read_bytes() == staged_bytes


@pytest.mark.parametrize(
    "field,value,code",
    [
        ("expected_lock_sha256", "b" * 64, "LOCK_SHA_MISMATCH"),
        ("expected_web_sha256", "b" * 64, "WEB_SHA_MISMATCH"),
        ("expected_commit", "b" * 40, "SOURCE_COMMIT_MISMATCH"),
        ("expected_lock_sha256", "--index-url", "LOCK_SHA_INVALID"),
    ],
)
def test_approved_identity_mismatch_never_stages_anything(bundle, field, value, code) -> None:
    source, destination, expected = bundle
    expected[field] = value
    with pytest.raises(closure.ClosureError, match=code):
        closure.stage_closure(source, destination, PINS, **expected)
    assert list(destination.iterdir()) == []


@pytest.mark.parametrize(
    "mutation,code",
    [
        ("missing", "INCOMPLETE_WHEEL_CLOSURE"),
        ("extra", "UNEXPECTED_WHEEL_VERSION"),
        ("duplicate", "DUPLICATE_WHEEL"),
        ("renamed", "WHEEL_FILENAME_MISMATCH"),
        ("tampered", "WHEEL_HASH_CLOSURE_MISMATCH"),
        ("unknown", "UNEXPECTED_WHEELHOUSE_ENTRY"),
    ],
)
def test_exact_wheel_set_and_bytes_are_required(bundle, mutation, code) -> None:
    source, destination, expected = bundle
    target = source / "jsonschema-4.26.0-py3-none-any.whl"
    if mutation == "missing":
        target.unlink()
    elif mutation == "extra":
        wheel(source, "unapproved-package", "1.0.0")
    elif mutation == "duplicate":
        wheel(source, "jsonschema", "4.26.0", tag="py2")
    elif mutation == "renamed":
        target.rename(source / "jsonschema-9.0-py3-none-any.whl")
    elif mutation == "tampered":
        with zipfile.ZipFile(target, "a") as archive:
            archive.writestr("unapproved.py", "raise RuntimeError")
    else:
        (source / "unexpected.txt").write_text("not a wheel")
    with pytest.raises(closure.ClosureError, match=code):
        closure.stage_closure(source, destination, PINS, **expected)
    assert list(destination.iterdir()) == []


@pytest.mark.parametrize("kind", ["symlink", "hardlink", "fifo"])
def test_source_links_and_special_files_are_rejected(bundle, tmp_path, kind) -> None:
    source, destination, expected = bundle
    target = source / "jsonschema-4.26.0-py3-none-any.whl"
    saved = tmp_path / "original.whl"
    target.rename(saved)
    if kind == "symlink":
        target.symlink_to(saved)
    elif kind == "hardlink":
        os.link(saved, target)
    else:
        os.mkfifo(target)
    with pytest.raises((closure.ClosureError, OSError)):
        closure.stage_closure(source, destination, PINS, **expected)
    assert list(destination.iterdir()) == []


@pytest.mark.parametrize("kind", ["public", "nonempty", "symlink"])
def test_staging_must_be_new_private_directory(bundle, tmp_path, kind) -> None:
    source, destination, expected = bundle
    if kind == "public":
        destination.chmod(0o755)
    elif kind == "nonempty":
        (destination / "preexisting").write_text("retain")
    else:
        link = tmp_path / "stage-link"
        link.symlink_to(destination)
        destination = link
    with pytest.raises(closure.ClosureError, match="PRIVATE_EMPTY_STAGING_REQUIRED"):
        closure.stage_closure(source, destination, PINS, **expected)


def test_pin_file_rejects_duplicate_and_nonexact_requirements(tmp_path) -> None:
    path = tmp_path / "pins"
    for bad_line in (
        "jsonschema>=4",
        "--extra-index-url https://example.invalid",
        "jsonschema==4.26.0",
    ):
        path.write_text(
            "".join(f"{name}=={version}\n" for name, version in PINS.items()) + bad_line
        )
        with pytest.raises(closure.ClosureError):
            closure.read_pins(path)


def test_offline_resolver_rejects_missing_transitive_dependency_even_if_installed(tmp_path) -> None:
    # Real pip, no installation and no network. --ignore-installed prevents the API interpreter's
    # jsonschema from concealing the missing wheel, as the old build simulation did.
    wheel(tmp_path, "eom-web-gui", "0.1.0", requires="Requires-Dist: jsonschema==4.26.0\n")
    wheel(tmp_path, "eom-kakao-archive-contracts", "0.1.0")
    pins = {name: PINS[name] for name in closure.LOCAL_NAMES}
    lock = tmp_path / closure.LOCK_NAME
    lock.write_bytes(closure.locked_bytes(closure.read_wheels(tmp_path, pins)))
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "--isolated",
            "--disable-pip-version-check",
            "install",
            "--dry-run",
            "--ignore-installed",
            "--no-index",
            "--only-binary=:all:",
            "--require-hashes",
            "--find-links",
            str(tmp_path),
            "--requirement",
            str(lock),
        ],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode != 0
    assert "No matching distribution found for jsonschema==4.26.0" in result.stderr


def test_shell_scripts_are_syntactically_valid() -> None:
    for name in ("build_release.sh", "install_release.sh"):
        subprocess.run(["bash", "-n", str(ROOT / "scripts/web_gui" / name)], check=True)


def _check_protected_member(path: Path, sha256: str) -> subprocess.CompletedProcess[str]:
    source = (ROOT / "scripts/web_gui/install_release.sh").read_text()
    start = source.index("verify_protected_member() {")
    end = source.index('\n[[ "$(id -u)"', start)
    # Exercise only the real read-only guard; never invoke an installer or privileged operation.
    script = (
        'set -euo pipefail\nfail() { printf "%s\\n" "$1" >&2; exit 1; }\n'
        + source[start:end]
        + '\nverify_protected_member "$1" "$2"\n'
    )
    return subprocess.run(
        ["bash", "-c", script, "protected-member-test", str(path), sha256],
        text=True,
        capture_output=True,
        check=False,
        timeout=10,
    )


def test_protected_source_guard_accepts_only_exact_root_owned_bytes() -> None:
    member = Path("/usr/bin/true")
    expected = hashlib.sha256(member.read_bytes()).hexdigest()
    assert _check_protected_member(member, expected).returncode == 0
    denied = _check_protected_member(member, "0" * 64)
    assert denied.returncode != 0
    assert "SHA-256 mismatch" in denied.stderr


def test_protected_source_guard_denies_mutable_checkout_before_helper_execution(tmp_path) -> None:
    member = tmp_path / "helper.py"
    member.write_text("raise SystemExit('must not execute')\n")
    denied = _check_protected_member(member, hashlib.sha256(member.read_bytes()).hexdigest())
    assert denied.returncode != 0
    assert "root-protected snapshot" in denied.stderr
    link = tmp_path / "helper-link.py"
    link.symlink_to(member)
    assert _check_protected_member(link, "0" * 64).returncode != 0
