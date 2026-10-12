"""Synthetic image release admission; never run build/deploy/Git or mutate a runtime."""

from __future__ import annotations

import base64
import csv
import hashlib
import io
import json
import os
import py_compile
import re
import stat
import struct
import subprocess
import sys
import tarfile
import warnings
import zipfile
from dataclasses import replace
from pathlib import Path
from types import MappingProxyType

import pytest
from packaging.markers import default_environment

from scripts.image_provider import verify_release_dependency as verifier

ROOT = Path(__file__).resolve().parents[2]


def _digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _record_hash(value: bytes) -> str:
    return "sha256=" + base64.urlsafe_b64encode(hashlib.sha256(value).digest()).decode().rstrip("=")


def _project(source: Path, role: str, requirements: tuple[str, ...]) -> dict[str, bytes]:
    distribution, version, namespace, project = verifier.ROLE_INFO[role]
    assert project is not None
    root = source / project
    package = root / namespace
    package.mkdir(parents=True, mode=0o700)
    for ancestor in (package, root, root.parent):
        ancestor.chmod(0o700)
    metadata = (
        f'[project]\nname = "{distribution}"\nversion = "{version}"\n'
        'requires-python = ">=3.11,<3.13"\n'
        "dependencies = [" + ",".join(f'"{value}"' for value in requirements) + "]\n"
    )
    (root / "pyproject.toml").write_text(metadata)
    (root / "pyproject.toml").chmod(0o600)
    if role == "GPU_LEASE":
        payloads = {
            f"{namespace}/{name}": (ROOT / "packages/gpu_lease" / namespace / name).read_bytes()
            for name in ("__init__.py", "lease.py")
        }
    else:
        payloads = {f"{namespace}/__init__.py": b'VERSION = "0.1.0"\n'}
    for name, value in payloads.items():
        (root / name).write_bytes(value)
        (root / name).chmod(0o600)
    return payloads


def _wheel(
    directory: Path,
    role: str,
    payloads: dict[str, bytes],
    requirements: tuple[str, ...],
    *,
    mutation: dict[str, bytes] | None = None,
    bad_record: bool = False,
    duplicate: bool = False,
    version_override: str | None = None,
) -> verifier.WheelPin:
    distribution, version, namespace, _project_path = verifier.ROLE_INFO[role]
    version = version_override or version
    stem = distribution.replace("-", "_") + "-" + version
    info = stem + ".dist-info"
    members = payloads | {
        info + "/METADATA": (
            f"Metadata-Version: 2.1\nName: {distribution}\nVersion: {version}\n"
            "Requires-Python: >=3.11,<3.13\n"
            + "".join(f"Requires-Dist: {value}\n" for value in requirements)
        ).encode(),
        info + "/WHEEL": b"Wheel-Version: 1.0\nRoot-Is-Purelib: true\nTag: py3-none-any\n",
        info + "/top_level.txt": (namespace + "\n").encode(),
    }
    members.update(mutation or {})
    record = info + "/RECORD"
    rows = [[name, _record_hash(value), str(len(value))] for name, value in members.items()]
    rows.append([record, "", ""])
    if bad_record:
        rows[0][1] = "sha256=" + "A" * 43
    stream = io.StringIO(newline="")
    csv.writer(stream, lineterminator="\n").writerows(rows)
    members[record] = stream.getvalue().encode()
    path = directory / (stem + "-py3-none-any.whl")
    with zipfile.ZipFile(path, "w") as archive:
        for name, value in members.items():
            entry = zipfile.ZipInfo(name)
            entry.create_system = 3
            entry.external_attr = (stat.S_IFREG | 0o644) << 16
            archive.writestr(entry, value)
        if duplicate:
            name, value = next(iter(members.items()))
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", UserWarning)
                archive.writestr(name, value)
    path.chmod(0o600)
    return verifier.WheelPin(role, path, _digest(path.read_bytes()))


def _cohort(
    tmp_path: Path,
    *,
    profile: str = "provider",
    shared: bool = True,
) -> tuple[Path, tuple[verifier.WheelPin, ...]]:
    source, directory = tmp_path / "source", tmp_path / "dist"
    source.mkdir(mode=0o700)
    directory.mkdir(mode=0o700)
    roles = ("CONTRACT", "PROVIDER") + (("TRAINER",) if profile == "trainer" else ())
    if shared:
        roles += ("GPU_LEASE",)
    pins = []
    for role in roles:
        requirements = (
            ("eom-gpu-lease==0.1.0",) if shared and role in {"PROVIDER", "TRAINER"} else ()
        )
        payloads = _project(source, role, requirements)
        pins.append(_wheel(directory, role, payloads, requirements))
    return source, tuple(pins)


def _site(prefix: Path) -> Path:
    site = prefix / "lib/python3.11/site-packages"
    site.mkdir(mode=0o700, parents=True)
    for ancestor in (site, site.parent, site.parent.parent, prefix):
        ancestor.chmod(0o700)
    return site


def _install_simulation(site: Path, pin: verifier.WheelPin) -> None:
    with zipfile.ZipFile(pin.path) as archive:
        for info in archive.infolist():
            target = site / info.filename
            target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            target.write_bytes(archive.read(info))
            target.chmod(0o600)


def _runtime_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    environment = {str(key): str(value) for key, value in default_environment().items()}
    environment.update(
        python_version="3.11", python_full_version="3.11.15", extra="", _wheel_tags="py3-none-any"
    )
    monkeypatch.setattr(verifier, "_runtime_environment", lambda prefix: environment)


@pytest.mark.parametrize("profile", ["provider", "trainer"])
def test_closed_new_build_cohort_and_genuine_legacy_metadata_are_admitted(
    tmp_path: Path,
    profile: str,
) -> None:
    current = tmp_path / "current"
    current.mkdir(mode=0o700)
    source, pins = _cohort(current, profile=profile)
    assert len(verifier.verify_build_wheels(profile, source, pins)) == len(pins)
    legacy = tmp_path / "legacy"
    legacy.mkdir(mode=0o700)
    source, pins = _cohort(legacy, profile=profile, shared=False)
    assert all(
        wheel.distribution != "eom-gpu-lease"
        for wheel in verifier.verify_build_wheels(profile, source, pins)
    )


def test_missing_shared_wheel_and_extra_role_fail(tmp_path: Path) -> None:
    source, pins = _cohort(tmp_path)
    with pytest.raises(verifier.ImageReleaseError, match="LEASE_WHEEL_REQUIRED"):
        verifier.verify_build_wheels("provider", source, pins[:-1])
    with pytest.raises(verifier.ImageReleaseError, match="WHEEL_DUPLICATE_ROLE"):
        verifier.verify_build_wheels("provider", source, (*pins, pins[-1]))
    peft = _wheel(tmp_path / "dist", "PEFT", {"peft/__init__.py": b""}, ())
    with pytest.raises(verifier.ImageReleaseError, match="WHEEL_SET_INVALID"):
        verifier.verify_build_wheels("provider", source, (*pins, peft))


def test_new_lease_cannot_be_smuggled_into_genuine_legacy_cohort(tmp_path: Path) -> None:
    source, pins = _cohort(tmp_path, shared=False)
    payloads = _project(source, "GPU_LEASE", ())
    lease = _wheel(tmp_path / "dist", "GPU_LEASE", payloads, ())
    with pytest.raises(verifier.ImageReleaseError, match="LEASE_WHEEL_UNEXPECTED"):
        verifier.verify_build_wheels("provider", source, (*pins, lease))


@pytest.mark.parametrize(
    "case", ["hash", "record", "source", "duplicate", "version", "metadata", "entrypoint"]
)
def test_wrong_raw_record_source_identity_or_metadata_fails(tmp_path: Path, case: str) -> None:
    source, pins = _cohort(tmp_path)
    original = pins[-1]
    namespace = "eom_gpu_lease"
    payloads = {
        f"{namespace}/{name}": (source / "packages/gpu_lease" / namespace / name).read_bytes()
        for name in ("__init__.py", "lease.py")
    }
    if case == "hash":
        changed = replace(original, sha256="f" * 64)
    else:
        mutation: dict[str, bytes] = {}
        if case == "source":
            payloads[namespace + "/lease.py"] += b"\n# unexpected payload\n"
        if case == "metadata":
            mutation["eom_gpu_lease-0.1.0.dist-info/METADATA"] = (
                b"Metadata-Version: 2.1\nName: eom-gpu-lease\nVersion: 0.1.0\n"
                b"Requires-Python: >=3.11,<3.13\nRequires-Dist: requests==9.9.9\n"
            )
        if case == "entrypoint":
            mutation["eom_gpu_lease-0.1.0.dist-info/entry_points.txt"] = (
                b"[console_scripts]\nevil = eom_gpu_lease:acquire_shared_gpu_lease\n"
            )
        changed = _wheel(
            tmp_path / "dist",
            "GPU_LEASE",
            payloads,
            (),
            mutation=mutation,
            bad_record=case == "record",
            duplicate=case == "duplicate",
            version_override="0.2.0" if case == "version" else None,
        )
    with pytest.raises((verifier.ImageReleaseError, ValueError)):
        verifier.verify_build_wheels("provider", source, (*pins[:-1], changed))


def test_provider_cannot_own_standalone_lease_module_even_with_valid_record(tmp_path: Path) -> None:
    source, pins = _cohort(tmp_path)
    payloads = {"eom_image_provider/__init__.py": b'VERSION = "0.1.0"\n'}
    changed = _wheel(
        tmp_path / "dist",
        "PROVIDER",
        payloads,
        ("eom-gpu-lease==0.1.0",),
        mutation={"eom_gpu_lease/__init__.py": b""},
    )
    with pytest.raises(verifier.ImageReleaseError, match="MIXED_LEASE_OWNERSHIP"):
        verifier.verify_build_wheels("provider", source, (pins[0], changed, pins[-1]))


def test_declared_lease_omission_is_not_treated_as_legacy(tmp_path: Path) -> None:
    source, pins = _cohort(tmp_path)
    changed = _wheel(
        tmp_path / "dist",
        "PROVIDER",
        {"eom_image_provider/__init__.py": b'VERSION = "0.1.0"\n'},
        (),
    )
    with pytest.raises(verifier.ImageReleaseError, match="SOURCE_METADATA_MISMATCH"):
        verifier.verify_build_wheels("provider", source, (pins[0], changed))


@pytest.mark.parametrize("ownership", ["platform", "unowned", "drift"])
def test_installed_mixed_unowned_or_record_drift_fails(tmp_path: Path, ownership: str) -> None:
    _source, pins = _cohort(tmp_path)
    prefix = tmp_path / "runtime"
    site = _site(prefix)
    _install_simulation(site, pins[-1])
    if ownership == "platform":
        info = site / "eom_platform-0.1.0.dist-info"
        info.mkdir()
        (info / "METADATA").write_text("Name: eom-platform\nVersion: 0.1.0\n")
        (info / "RECORD").write_text("eom_gpu_lease/lease.py,,\n")
    elif ownership == "unowned":
        (site / "eom_gpu_lease/unowned.py").write_text("unknown = True\n")
    else:
        (site / "eom_gpu_lease/lease.py").write_text("drift = True\n")
    with pytest.raises(verifier.ImageReleaseError):
        verifier.verify_installed_lease_ownership(prefix)


def test_deploy_dependency_closure_and_installed_import_simulation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source, pins = _cohort(tmp_path)
    peft = _wheel(tmp_path / "dist", "PEFT", {"peft/__init__.py": b""}, ())
    prefix = tmp_path / "runtime"
    site = _site(prefix)
    _runtime_environment(monkeypatch)
    verified = verifier.verify_deploy_wheels("provider", source, (*pins, peft), prefix)
    assert len(verified) == 4
    for pin in (*pins, peft):
        _install_simulation(site, pin)
    verifier.verify_installed_release("provider", source, (*pins, peft), prefix)
    code = (
        "import pathlib, sys; sys.path.insert(0, sys.argv[1]); import eom_gpu_lease; "
        "assert pathlib.Path(eom_gpu_lease.__file__).is_relative_to(sys.argv[1]); "
        "assert not {'torch','transformers','diffusers','bitsandbytes'}.intersection(sys.modules); "
        "print('STANDALONE_IMPORT_PASS')"
    )
    result = subprocess.run(
        [sys.executable, "-I", "-B", "-c", code, str(site)],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "STANDALONE_IMPORT_PASS"
    assert not tuple((site / "eom_gpu_lease").rglob("*.pyc"))


def test_missing_installed_dependency_fails_before_any_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source, pins = _cohort(tmp_path)
    peft = _wheel(tmp_path / "dist", "PEFT", {"peft/__init__.py": b""}, ("safetensors>=0.6",))
    prefix = tmp_path / "runtime"
    _site(prefix)
    _runtime_environment(monkeypatch)
    with pytest.raises(verifier.ImageReleaseError, match="DEPENDENCY_CLOSURE_MISMATCH"):
        verifier.verify_deploy_wheels("provider", source, (*pins, peft), prefix)
    assert not (prefix / "lib/python3.11/site-packages/eom_gpu_lease").exists()


def test_quarantine_copy_rejects_mismatch_and_retains_original_input(tmp_path: Path) -> None:
    _source, pins = _cohort(tmp_path)
    quarantine = tmp_path / "quarantine"
    quarantine.mkdir(mode=0o700)
    copied = verifier._copy_pin(pins[-1], quarantine)
    assert copied.path.read_bytes() == pins[-1].path.read_bytes()
    assert copied.path.stat().st_mode & 0o777 == 0o600
    other = tmp_path / "other"
    other.mkdir(mode=0o700)
    with pytest.raises(verifier.ImageReleaseError, match="INPUT_HASH_MISMATCH"):
        verifier._copy_pin(replace(pins[-1], sha256="f" * 64), other)
    assert pins[-1].path.exists()


@pytest.mark.parametrize("member", ["METADATA", "lease.py", "lease_metadata"])
def test_conda_metadata_hardlink_is_allowed_but_lease_payload_is_single_link(
    tmp_path: Path, member: str
) -> None:
    _source, pins = _cohort(tmp_path)
    site = _site(tmp_path / "runtime")
    _install_simulation(site, pins[-1])
    if member == "METADATA":
        peft = _wheel(tmp_path / "dist", "PEFT", {"peft/__init__.py": b""}, ())
        _install_simulation(site, peft)
        target = site / "peft-0.17.1.dist-info/METADATA"
    elif member == "lease_metadata":
        target = site / "eom_gpu_lease-0.1.0.dist-info/METADATA"
    else:
        target = site / "eom_gpu_lease/lease.py"
    os.link(target, tmp_path / "protected-cache-copy")
    if member == "METADATA":
        assert verifier.verify_installed_lease_ownership(tmp_path / "runtime")["peft"] == "0.17.1"
    else:
        with pytest.raises(verifier.ImageReleaseError, match="FILE_INVALID"):
            verifier.verify_installed_lease_ownership(tmp_path / "runtime")


@pytest.mark.parametrize("violation", ["writable", "foreign_owner"])
def test_hardlinked_installed_metadata_still_requires_protected_owner_and_mode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, violation: str
) -> None:
    _source, _pins = _cohort(tmp_path)
    site = _site(tmp_path / "runtime")
    peft = _wheel(tmp_path / "dist", "PEFT", {"peft/__init__.py": b""}, ())
    _install_simulation(site, peft)
    target = site / "peft-0.17.1.dist-info/METADATA"
    os.link(target, tmp_path / "protected-cache-copy")
    if violation == "writable":
        target.chmod(0o660)
    else:
        original_lstat = Path.lstat

        def foreign_owner(path: Path) -> os.stat_result:
            value = original_lstat(path)
            if path == target:
                fields = list(value)
                fields[4] = 1
                return os.stat_result(fields)
            return value

        monkeypatch.setattr(Path, "lstat", foreign_owner)
    with pytest.raises(verifier.ImageReleaseError, match=r"PATH_(MODE|OWNER)_INVALID"):
        verifier.verify_installed_lease_ownership(tmp_path / "runtime")


def test_installed_editable_lease_is_not_release_ownership(tmp_path: Path) -> None:
    _source, pins = _cohort(tmp_path)
    site = _site(tmp_path / "runtime")
    _install_simulation(site, pins[-1])
    direct = site / "eom_gpu_lease-0.1.0.dist-info/direct_url.json"
    direct.write_text('{"dir_info":{"editable":true}}')
    direct.chmod(0o600)
    with pytest.raises(verifier.ImageReleaseError, match="INSTALLED_EDITABLE_LEASE"):
        verifier.verify_installed_lease_ownership(tmp_path / "runtime")


@pytest.mark.parametrize("case", ["good", "wrong_context", "duplicate_key", "path", "activation"])
def test_receipts_are_closed_pinned_and_nonactivating(tmp_path: Path, case: str) -> None:
    _source, pins = _cohort(tmp_path)
    verifier._receipt(tmp_path, "DEPLOY_ADMITTED", "provider", "a" * 40, pins)
    receipt = tmp_path / "deploy_admitted.json"
    value = json.loads(receipt.read_bytes())
    if case == "wrong_context":
        value["source_commit"] = "b" * 40
    elif case == "path":
        value["wheels"][0]["filename"] = "../../outside.whl"
    elif case == "activation":
        value["gpu_shared_lease_activation_verified"] = True
    payload = json.dumps(value).encode()
    if case == "duplicate_key":
        payload = payload[:-1] + b',"profile":"provider"}'
    receipt.write_bytes(payload)
    if case == "good":
        assert tuple(
            pin.role for pin in verifier._receipt_pins(tmp_path, "provider", "a" * 40)
        ) == ("CONTRACT", "PROVIDER", "GPU_LEASE")
    else:
        with pytest.raises(verifier.ImageReleaseError):
            verifier._receipt_pins(tmp_path, "provider", "a" * 40)


@pytest.mark.parametrize("kind", ["safe", "symlink", "outside", "duplicate"])
def test_source_archive_admits_only_selected_roots_and_parent_directories(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, kind: str
) -> None:
    _source, pins = _cohort(tmp_path)
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode="w") as archive:
        for directory in ("packages", "packages/gpu_lease"):
            member = tarfile.TarInfo(directory)
            member.type = tarfile.DIRTYPE
            archive.addfile(member)
        name = "unselected.txt" if kind == "outside" else "packages/gpu_lease/pyproject.toml"
        member = tarfile.TarInfo(name)
        if kind == "symlink":
            member.type = tarfile.SYMTYPE
            member.linkname = "/outside"
            archive.addfile(member)
        else:
            member.size = 1
            archive.addfile(member, io.BytesIO(b"x"))
            if kind == "duplicate":
                archive.addfile(member, io.BytesIO(b"x"))
    monkeypatch.setattr(
        verifier, "_git_archive_bytes", lambda repository, commit, paths: stream.getvalue()
    )
    staged = tmp_path / "quarantine"
    staged.mkdir(mode=0o700)
    prior_umask = os.umask(0o077)
    try:
        if kind == "safe":
            verifier._stage_source(ROOT, "a" * 40, staged / "source", (pins[-1],))
            assert (staged / "source/packages/gpu_lease/pyproject.toml").read_bytes() == b"x"
        else:
            with pytest.raises((verifier.ImageReleaseError, FileExistsError)):
                verifier._stage_source(ROOT, "a" * 40, staged / "source", (pins[-1],))
    finally:
        os.umask(prior_umask)


def test_external_dependency_cannot_embed_lease_or_relocation_payload(tmp_path: Path) -> None:
    source, _pins = _cohort(tmp_path)
    for name in ("eom_gpu_lease/lease.py", "peft.data/purelib/eom_gpu_lease/lease.py"):
        changed = _wheel(
            tmp_path / "dist", "PEFT", {"peft/__init__.py": b""}, (), mutation={name: b""}
        )
        with pytest.raises(verifier.ImageReleaseError):
            verifier.verify_wheel(changed, source)


@pytest.mark.parametrize("component,count", [("image_provider", 7), ("image_trainer", 11)])
@pytest.mark.parametrize("case", ["legacy", "successor", "wrong_flag", "missing", "wrong_sha"])
def test_actual_argument_preflight_snippet_has_no_runtime_side_effects(
    component: str, count: int, case: str
) -> None:
    source = (ROOT / "scripts" / component / "deploy_runtime.sh").read_text()
    snippet = source[source.index("if [[ $#") : source.index('[[ "${SOURCE_COMMIT}"')]
    arguments = ["unused"] * count
    if case != "legacy":
        arguments += [
            "--gpu-lease-wheel",
            f"/tmp/eom-{component.replace('_', '-')}-build/test/dist/"
            "eom_gpu_lease-0.1.0-py3-none-any.whl",
            "--gpu-lease-sha256",
            "a" * 64,
        ]
    if case == "wrong_flag":
        arguments[-4] = "--latest"
    elif case == "missing":
        arguments.pop()
    elif case == "wrong_sha":
        arguments[-1] = "invalid"
    result = subprocess.run(
        ("/bin/bash", "-c", "set -eu; fail() { exit 1; }; " + snippet, "synthetic", *arguments),
        capture_output=True,
        check=False,
        timeout=10,
    )
    assert (result.returncode == 0) == (case in {"legacy", "successor"})


def test_script_source_has_exact_helper_hash_and_preflight_before_every_mutation() -> None:
    helper_hash = _digest(
        (ROOT / "scripts/image_provider/verify_release_dependency.py").read_bytes()
    )
    for component in ("image_provider", "image_trainer"):
        build = (ROOT / "scripts" / component / "build_release.sh").read_text()
        deploy = (ROOT / "scripts" / component / "deploy_runtime.sh").read_text()
        assert f"DEPENDENCY_VERIFIER_SHA256={helper_hash}" in build
        assert f"DEPENDENCY_VERIFIER_SHA256={helper_hash}" in deploy
        assert "packages/gpu_lease" in build and "verify_release_dependency.py" in build
        assert "eom_gpu_lease-0.1.0-py3-none-any.whl" in build
        admission = deploy.index('"$API_PYTHON" -I -B "$release_helper" "${release_arguments[@]}"')
        for mutation in (
            "groupadd ",
            "useradd ",
            "usermod ",
            "install -d ",
            "-m pip install",
            " create --offline",
        ):
            if mutation in deploy:
                assert admission < deploy.index(mutation)
        assert "--no-index --no-deps --force-reinstall" in deploy
        assert "--no-index --no-deps --no-compile --force-reinstall" in deploy
        assert re.search(r" -I(?! -B)", build + deploy) is None
        assert deploy.index('"${release_helper}" installed') < deploy.index("runuser -u eom-image")
        assert "GPU_SHARED_LEASE_MIGRATION_VERIFIED=NO" in deploy
        assert "GPU_DEFAULT_ACTIVATION_VERIFIED=NO" in deploy
        assert "PY_IMAGE_RELEASE_BOOTSTRAP" in deploy
        assert deploy.index('"${release_helper}" installed') < deploy.index("RUNTIME_PREPARED=YES")
        assert "--gpu-lease-wheel" in deploy and "--gpu-lease-sha256" in deploy


def test_legacy_cli_positions_and_new_successor_are_explicit() -> None:
    provider = (ROOT / "scripts/image_provider/deploy_runtime.sh").read_text()
    trainer = (ROOT / "scripts/image_trainer/deploy_runtime.sh").read_text()
    assert "SOURCE_COMMIT=${7:-}" in provider and "SOURCE_COMMIT=${11:-}" in trainer
    assert "elif [[ $# -ne 7 ]]" in provider and "if [[ $# -eq 11 ]]" in provider
    assert "elif [[ $# -ne 11 ]]" in trainer and "if [[ $# -eq 15 ]]" in trainer
    assert re.search(r'"\$8" == --gpu-lease-wheel', provider)
    assert '"${12}" == --gpu-lease-wheel' in trainer


def _central_entry(*, extra: bytes = b"", comment: bytes = b"") -> bytes:
    header = bytearray(46)
    header[:4] = b"PK\x01\x02"
    struct.pack_into("<H", header, 6, 20)
    struct.pack_into("<3H", header, 28, 1, len(extra), len(comment))
    return bytes(header) + b"x" + extra + comment


@pytest.mark.parametrize(
    "case,code",
    [
        ("declared_count", "WHEEL_MEMBERS_INVALID"),
        ("actual_count", "WHEEL_MEMBERS_INVALID"),
        ("forged_count", "WHEEL_CENTRAL_COUNT_INVALID"),
        ("central_bytes", "WHEEL_CENTRAL_TOO_LARGE"),
        ("zip64_count", "WHEEL_ZIP64_UNSUPPORTED"),
        ("zip64_size", "WHEEL_ZIP64_UNSUPPORTED"),
        ("zip64_extra", "WHEEL_ZIP64_UNSUPPORTED"),
        ("zip64_version", "WHEEL_ZIP64_UNSUPPORTED"),
        ("zip64_locator", "WHEEL_ZIP64_UNSUPPORTED"),
        ("disk", "WHEEL_MULTIDISK_UNSUPPORTED"),
        ("member_disk", "WHEEL_MULTIDISK_UNSUPPORTED"),
        ("comment", "WHEEL_COMMENT_INVALID"),
        ("member_comment", "WHEEL_COMMENT_INVALID"),
        ("trailing_central", "WHEEL_CENTRAL_INVALID"),
        ("truncated_extra", "WHEEL_CENTRAL_INVALID"),
        ("trailing_archive", "WHEEL_ZIP_EOCD_INVALID"),
    ],
)
def test_zip_structure_limits_precede_zipfile_allocation_and_close_held_fd(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, case: str, code: str
) -> None:
    central, declared_count, declared_size, disk, comment = _central_entry(), 1, 47, 0, b""
    if case == "declared_count":
        declared_count = verifier.MAX_WHEEL_MEMBERS + 1
    elif case == "actual_count":
        central *= verifier.MAX_WHEEL_MEMBERS + 1
    elif case == "forged_count":
        declared_count = 2
    elif case == "central_bytes":
        declared_size = verifier.MAX_CENTRAL_BYTES + 1
    elif case == "zip64_count":
        declared_count = 0xFFFF
    elif case == "zip64_size":
        declared_size = 0xFFFFFFFF
    elif case == "zip64_extra":
        central = _central_entry(extra=struct.pack("<2H", 1, 0))
    elif case == "zip64_version":
        central = central[:6] + struct.pack("<H", 45) + central[8:]
    elif case == "zip64_locator":
        central += b"PK\x06\x07" + b"\x00" * 16
    elif case == "disk":
        disk = 1
    elif case == "member_disk":
        central = central[:34] + struct.pack("<H", 1) + central[36:]
    elif case == "comment":
        comment = b"unsupported"
    elif case == "member_comment":
        central = _central_entry(comment=b"unsupported")
    elif case == "trailing_central":
        central += b"unexpected"
    elif case == "truncated_extra":
        central = _central_entry(extra=struct.pack("<2H", 2, 5))
    if case not in {"central_bytes", "zip64_size"}:
        declared_size = len(central)
    payload = (
        central
        + struct.pack(
            "<4s4H2IH",
            b"PK\x05\x06",
            disk,
            0,
            declared_count,
            declared_count,
            declared_size,
            0,
            len(comment),
        )
        + comment
    )
    if case == "trailing_archive":
        payload += b"unexpected"
    path = tmp_path / "eom_gpu_lease-0.1.0-py3-none-any.whl"
    path.write_bytes(payload)
    path.chmod(0o600)
    pin = verifier.WheelPin("GPU_LEASE", path, _digest(payload))
    descriptors: set[int] = set()
    reads: list[int] = []
    original_pread = os.pread

    def observed_pread(descriptor: int, size: int, offset: int) -> bytes:
        descriptors.add(descriptor)
        reads.append(size)
        return original_pread(descriptor, size, offset)

    def deny_zipfile(*args: object, **kwargs: object) -> None:
        pytest.fail("ZipFile allocated before the bounded central-directory gate")

    monkeypatch.setattr(os, "pread", observed_pread)
    monkeypatch.setattr(zipfile, "ZipFile", deny_zipfile)
    with pytest.raises(verifier.ImageReleaseError, match=code):
        verifier.verify_wheel(pin, tmp_path)
    assert len(descriptors) == 1
    assert max(reads) <= verifier.MAX_CENTRAL_BYTES
    if case == "central_bytes":
        assert max(reads) <= 1024**2
    with pytest.raises(OSError):
        os.fstat(next(iter(descriptors)))


def test_wheel_path_epoch_change_is_denied_before_zipfile_allocation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source, pins = _cohort(tmp_path)
    pin = pins[-1]
    replacement = tmp_path / "replacement"
    replacement.write_bytes(pin.path.read_bytes())
    replacement.chmod(0o600)
    original_pread = os.pread
    replaced = False

    def changed_pread(descriptor: int, size: int, offset: int) -> bytes:
        nonlocal replaced
        raw = original_pread(descriptor, size, offset)
        if not replaced:
            replacement.replace(pin.path)
            replaced = True
        return raw

    def deny_zipfile(*args: object, **kwargs: object) -> None:
        pytest.fail("Changed wheel reached ZipFile")

    monkeypatch.setattr(os, "pread", changed_pread)
    monkeypatch.setattr(zipfile, "ZipFile", deny_zipfile)
    with pytest.raises(verifier.ImageReleaseError, match="WHEEL_CHANGED"):
        verifier.verify_wheel(pin, source)


@pytest.mark.parametrize("registered", [False, True])
@pytest.mark.parametrize(
    "location", ["__pycache__/lease.cpython-311.pyc", "lease.pyc", "lease.pyo"]
)
def test_registered_or_unregistered_unchecked_bytecode_is_rejected_without_deletion(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, registered: bool, location: str
) -> None:
    source, pins = _cohort(tmp_path)
    prefix = tmp_path / "runtime"
    site = _site(prefix)
    _install_simulation(site, pins[-1])
    bytecode = site / "eom_gpu_lease" / location
    bytecode.parent.mkdir(mode=0o700, exist_ok=True)
    hostile = tmp_path / "hostile.py"
    hostile.write_text("raise RuntimeError('must never import unchecked lease bytecode')\n")
    py_compile.compile(
        str(hostile),
        cfile=str(bytecode),
        doraise=True,
        invalidation_mode=py_compile.PycInvalidationMode.UNCHECKED_HASH,
    )
    bytecode.chmod(0o600)
    raw = bytecode.read_bytes()
    assert int.from_bytes(raw[4:8], "little") == 1
    if registered:
        record = site / "eom_gpu_lease-0.1.0.dist-info/RECORD"
        with record.open("a", newline="") as stream:
            csv.writer(stream, lineterminator="\n").writerow(
                [bytecode.relative_to(site).as_posix(), "", ""]
            )

    def deny_runtime_probe(prefix: Path) -> dict[str, str]:
        pytest.fail("Bytecode admission must precede the metadata/import subprocess")

    monkeypatch.setattr(verifier, "_runtime_environment", deny_runtime_probe)
    peft = _wheel(tmp_path / "dist", "PEFT", {"peft/__init__.py": b""}, ())
    with pytest.raises(verifier.ImageReleaseError, match="INSTALLED_LEASE_BYTECODE_FORBIDDEN"):
        verifier.verify_installed_release("provider", source, (*pins, peft), prefix)
    assert bytecode.read_bytes() == raw


def test_genuinely_absent_lease_retains_legacy_installed_admission(tmp_path: Path) -> None:
    prefix = tmp_path / "runtime"
    _site(prefix)
    assert verifier.verify_installed_lease_ownership(prefix) == {}


@pytest.mark.parametrize("name", ["eom_gpu_lease.pyc", "__pycache__/eom_gpu_lease.cpython-311.pyc"])
def test_unowned_sourceless_sibling_is_not_genuinely_absent_lease(
    tmp_path: Path, name: str
) -> None:
    prefix = tmp_path / "runtime"
    site = _site(prefix)
    bytecode = site / name
    bytecode.parent.mkdir(mode=0o700, exist_ok=True)
    bytecode.write_bytes(b"unowned lease bytecode")
    bytecode.chmod(0o600)
    with pytest.raises(verifier.ImageReleaseError, match="INSTALLED_LEASE_BYTECODE_FORBIDDEN"):
        verifier.verify_installed_lease_ownership(prefix)
    assert bytecode.exists()


@pytest.mark.parametrize(
    "case,code",
    [
        ("good", None),
        ("stderr", None),
        ("oversized", "RUNTIME_METADATA_TOO_LARGE"),
        ("timeout_read", "RUNTIME_METADATA_TIMEOUT"),
        ("timeout_wait", "RUNTIME_METADATA_TIMEOUT"),
        ("nonzero", "RUNTIME_METADATA_INVALID"),
    ],
)
def test_fixed_metadata_probe_bounds_reads_discards_stderr_and_reaps_closes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, case: str, code: str | None
) -> None:
    prefix = tmp_path / "runtime"
    prefix.mkdir(mode=0o700)
    (prefix / "bin").mkdir(mode=0o700)
    interpreter = prefix / "bin/python"
    interpreter.write_bytes(b"synthetic protected interpreter: intercepted, never executed")
    interpreter.chmod(0o600)
    monkeypatch.setattr(verifier, "PREFIXES", MappingProxyType({"provider": prefix}))
    monkeypatch.setattr(verifier, "RUNTIME_METADATA_TIMEOUT_SECONDS", 0.3)
    payload = json.dumps(
        {"prefix": str(prefix), "environment": {"python_version": "3.11"}, "tags": ["py3-none-any"]}
    ).encode()
    synthetic = "import os; os.write(1, " + repr(payload) + ")"
    if case == "stderr":
        synthetic = "import os; os.write(2, b'x' * 8 * 1024**2); os.write(1, " + repr(payload) + ")"
    elif case == "oversized":
        synthetic = "import os\nwhile True: os.write(1, b'x' * 65536)"
    elif case == "timeout_read":
        synthetic = "import time; time.sleep(30)"
    elif case == "timeout_wait":
        synthetic = "import os, time; os.close(1); time.sleep(30)"
    elif case == "nonzero":
        synthetic = "raise SystemExit(3)"
    processes: list[subprocess.Popen[bytes]] = []
    original_popen, original_read = subprocess.Popen, os.read
    read_sizes: list[int] = []
    output_bytes = 0

    def synthetic_popen(
        arguments: tuple[str, ...], *, stdin: int, stdout: int, stderr: int, env: dict[str, str]
    ) -> subprocess.Popen[bytes]:
        assert arguments[0] == str(interpreter)
        assert arguments[1:4] == ("-I", "-B", "-c")
        assert "packaging.markers" in arguments[4] and "packaging.tags" in arguments[4]
        assert not re.search(r"\b(?:torch|transformers|diffusers)\b", arguments[4])
        assert stdin == stderr == subprocess.DEVNULL and stdout == subprocess.PIPE
        assert env == {
            "PATH": "/usr/bin:/bin",
            "TZ": "UTC",
            "LANG": "C.UTF-8",
            "PYTHONNOUSERSITE": "1",
        }
        process = original_popen(
            (sys.executable, "-I", "-B", "-c", synthetic),
            stdin=stdin,
            stdout=stdout,
            stderr=stderr,
            env=env,
        )
        processes.append(process)
        return process

    def observed_read(descriptor: int, size: int) -> bytes:
        nonlocal output_bytes
        value = original_read(descriptor, size)
        if (
            processes
            and processes[0].stdout is not None
            and descriptor == processes[0].stdout.fileno()
        ):
            read_sizes.append(size)
            output_bytes += len(value)
        return value

    monkeypatch.setattr(subprocess, "Popen", synthetic_popen)
    monkeypatch.setattr(os, "read", observed_read)
    if code is None:
        assert verifier._runtime_environment(prefix) == {
            "python_version": "3.11",
            "extra": "",
            "_wheel_tags": "py3-none-any",
        }
    else:
        with pytest.raises(verifier.ImageReleaseError, match=code):
            verifier._runtime_environment(prefix)
    assert len(processes) == 1
    process = processes[0]
    assert process.poll() is not None
    assert process.stdout is not None and process.stdout.closed
    assert output_bytes <= verifier.MAX_METADATA_BYTES + 1
    assert not read_sizes or max(read_sizes) <= 65536
    if case in {"oversized", "timeout_read", "timeout_wait"}:
        assert process.returncode == -9


def test_metadata_probe_rejects_request_selected_prefix_before_subprocess(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def deny_popen(*args: object, **kwargs: object) -> None:
        pytest.fail("Unconfigured prefix reached subprocess")

    monkeypatch.setattr(subprocess, "Popen", deny_popen)
    with pytest.raises(verifier.ImageReleaseError, match="RUNTIME_PREFIX_INVALID"):
        verifier._runtime_environment(tmp_path / "unconfigured")


def test_metadata_probe_rejects_interpreter_escaping_fixed_prefix(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    prefix = tmp_path / "runtime"
    prefix.mkdir(mode=0o700)
    (prefix / "bin").mkdir(mode=0o700)
    outside = tmp_path / "outside-python"
    outside.write_bytes(b"must never execute")
    outside.chmod(0o600)
    (prefix / "bin/python").symlink_to(outside)
    monkeypatch.setattr(verifier, "PREFIXES", MappingProxyType({"provider": prefix}))

    def deny_popen(*args: object, **kwargs: object) -> None:
        pytest.fail("Escaped interpreter reached subprocess")

    monkeypatch.setattr(subprocess, "Popen", deny_popen)
    with pytest.raises(verifier.ImageReleaseError, match="RUNTIME_INTERPRETER_INVALID"):
        verifier._runtime_environment(prefix)
