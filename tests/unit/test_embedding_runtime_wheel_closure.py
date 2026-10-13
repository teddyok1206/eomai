"""Stdlib mechanical parity and hostile pins; no installed runtime/model/device admission."""

from __future__ import annotations

import ast
import io
import json
import os
import stat
import struct
import subprocess
import sys
import zipfile
from collections.abc import Iterator
from dataclasses import FrozenInstanceError, replace
from pathlib import Path
from typing import Any, Literal

import pytest
from eom_catalog_contracts.embedding_installed_runtime_proof import (
    EmbeddingRuntimeProfile,
    InstalledNumericLibraryProof,
)
from eom_catalog_service import embedding_runtime_wheel_closure as core
from eom_catalog_service.embedding_runtime_distribution import (
    capture_installed_numeric_distribution,
    verify_installed_numeric_distribution,
)
from eom_catalog_service.embedding_runtime_files import (
    InstalledRuntimeProofError,
    NumericalRuntimeFileSnapshots,
)
from eom_catalog_service.embedding_runtime_wheel_closure import (
    RuntimeWheelArchivePin,
    RuntimeWheelConsoleScriptPin,
    RuntimeWheelInstallationPin,
    RuntimeWheelMemberPin,
    observe_runtime_wheel_installation,
    validate_runtime_console_wrapper,
    verify_installed_runtime_wheel,
)
from eom_identifiers import sha256_bytes

from tests.unit.embedding_installed_runtime_fixtures import (
    staged_runtime,
    synthetic_console_wrapper,
    synthetic_record,
    synthetic_wheel,
)


def wheel_pin(library: InstalledNumericLibraryProof) -> RuntimeWheelInstallationPin:
    return RuntimeWheelInstallationPin(
        name=library.name,
        version=library.version,
        archive=RuntimeWheelArchivePin(
            library.archive.wheel_filename, library.archive.sha256, library.archive.size_bytes
        ),
        installed_record=RuntimeWheelMemberPin(
            library.installed_record.sha256, library.installed_record.size_bytes
        ),
        requested=library.requested,
        direct_url=None
        if library.direct_url is None
        else RuntimeWheelMemberPin(library.direct_url.sha256, library.direct_url.size_bytes),
        console_scripts=tuple(
            RuntimeWheelConsoleScriptPin(value.name, value.sha256, value.size_bytes)
            for value in library.console_scripts
        ),
    )


def _rewrite_with_distinct_mtime(path: Path) -> None:
    """Synthetic epoch drift must not depend on two writes straddling a filesystem tick."""
    before = path.stat()
    path.write_bytes(path.read_bytes())
    os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns + 1_000_000_000))


@pytest.mark.parametrize("profile", ["CPU_INDEX_FP32", "CUDA_INDEX_FP32"])
@pytest.mark.parametrize("generated", [False, True])
@pytest.mark.parametrize("recipe", ["legacy", "modern", "removesuffix"])
def test_direct_core_and_typed_numeric_adapter_preserve_exact_member_and_value_closure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    profile: EmbeddingRuntimeProfile,
    generated: bool,
    recipe: Literal["legacy", "modern", "removesuffix"],
) -> None:
    staged = staged_runtime(
        tmp_path, monkeypatch, profile, with_generated=generated, console_recipe=recipe
    )
    core_files = NumericalRuntimeFileSnapshots(os.geteuid())
    numeric_files = NumericalRuntimeFileSnapshots(os.geteuid())
    core_roots: set[Path] = set()
    core_members: set[Path] = set()
    for library in staged.proof.numeric_libraries:
        core = verify_installed_runtime_wheel(
            wheel_pin(library),
            prefix=staged.prefix,
            archive_root=staged.archive_root,
            files=core_files,
        )
        typed = verify_installed_numeric_distribution(
            library,
            prefix=staged.prefix,
            archive_root=staged.archive_root,
            files=numeric_files,
        )
        assert (core.name, core.version, core.archive_sha256) == (
            typed.pin.name,
            typed.pin.version,
            typed.pin.distribution_sha256,
        )
        assert core.namespace_roots == typed.namespace_roots
        assert core.installed_members == typed.installed_members
        assert core.installed_members <= core.all_installed_members
        assert core.all_installed_members - core.installed_members == frozenset(
            staged.prefix / "bin" / script.name for script in library.console_scripts
        )
        assert core.archive_payload_members <= core.installed_members
        assert all(path.is_relative_to(staged.prefix) for path in core.all_installed_members)
        assert core.torch_version == typed.torch_version
        if library.name == "torch":
            assert core.torch_version == (
                library.version,
                "12.8" if profile == "CUDA_INDEX_FP32" else None,
            )
        core_roots.update(core.namespace_roots)
        core_members.update(core.installed_members)
    core_files.require_closed_namespaces(core_roots, core_members)
    core_files.assert_unchanged()
    numeric_files.assert_unchanged()


@pytest.mark.parametrize("profile", ["CPU_INDEX_FP32", "CUDA_INDEX_FP32"])
@pytest.mark.parametrize("generated", [False, True])
def test_public_wheel_observation_is_exact_and_then_source_verified(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    profile: EmbeddingRuntimeProfile,
    generated: bool,
) -> None:
    staged = staged_runtime(tmp_path, monkeypatch, profile, with_generated=generated)
    files = NumericalRuntimeFileSnapshots(os.geteuid())
    for library in staged.proof.numeric_libraries:
        expected = wheel_pin(library)
        observed = observe_runtime_wheel_installation(
            expected.archive, expected.name, expected.version, prefix=staged.prefix, files=files
        )
        assert observed == expected
        verified = verify_installed_runtime_wheel(
            observed, prefix=staged.prefix, archive_root=staged.archive_root, files=files
        )
        assert verified.all_installed_members == verified.installed_members | frozenset(
            staged.prefix / "bin" / script.name for script in expected.console_scripts
        )
        assert not any(
            path.name in {"INSTALLER", "REQUESTED", "direct_url.json", "RECORD"}
            for path in verified.archive_payload_members
        )
    files.assert_unchanged()


@pytest.mark.parametrize("profile", ["CPU_INDEX_FP32", "CUDA_INDEX_FP32"])
@pytest.mark.parametrize("generated", [False, True])
def test_numeric_capture_uses_actual_installation_and_existing_archive_verification(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    profile: EmbeddingRuntimeProfile,
    generated: bool,
) -> None:
    staged = staged_runtime(tmp_path, monkeypatch, profile, with_generated=generated)
    files = NumericalRuntimeFileSnapshots(os.geteuid())
    for expected in staged.proof.numeric_libraries:
        proof, verified = capture_installed_numeric_distribution(
            wheel_pin(expected).archive,
            expected.name,
            expected.version,
            prefix=staged.prefix,
            archive_root=staged.archive_root,
            files=files,
        )
        assert proof == expected
        assert verified.pin.name == expected.name
        assert verified.pin.distribution_sha256 == expected.archive.sha256
        assert verified.torch_version == (
            (expected.version, "12.8" if profile == "CUDA_INDEX_FP32" else None)
            if expected.name == "torch"
            else None
        )
    files.assert_unchanged()


@pytest.mark.parametrize("fault", ["record", "payload", "archive", "script", "url"])
def test_numeric_capture_cannot_turn_observed_tampering_into_a_verified_proof(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fault: str
) -> None:
    staged = staged_runtime(tmp_path, monkeypatch, with_generated=True)
    expected = staged.proof.numeric_libraries[0]
    dist = staged.dist_infos[expected.name]
    if fault == "record":
        target = dist / "RECORD"
    elif fault == "payload":
        target = staged.prefix / "lib/python3.12/site-packages/numpy/__init__.py"
    elif fault == "archive":
        target = staged.archives[expected.name]
    elif fault == "script":
        target = staged.prefix / "bin" / expected.console_scripts[0].name
    else:
        target = dist / "direct_url.json"
    target.write_bytes(target.read_bytes() + b"unaccepted change")
    with pytest.raises(InstalledRuntimeProofError):
        capture_installed_numeric_distribution(
            wheel_pin(expected).archive,
            expected.name,
            expected.version,
            prefix=staged.prefix,
            archive_root=staged.archive_root,
            files=NumericalRuntimeFileSnapshots(os.geteuid()),
        )


def test_core_imports_with_actual_file_adapter_under_isolated_no_site_no_bytecode_python() -> None:
    import eom_catalog_service.embedding_runtime_files as files
    import eom_catalog_service.embedding_runtime_wheel_closure as core

    source_root = Path(core.__file__).resolve().parent.parent
    code = """
import pathlib, sys
assert sys.flags.isolated and sys.flags.no_site and sys.flags.dont_write_bytecode
sys.path.insert(0, sys.argv[1])
import eom_catalog_service.embedding_runtime_wheel_closure as core
import eom_catalog_service.embedding_runtime_files as files
assert pathlib.Path(core.__file__).resolve() == pathlib.Path(sys.argv[2]).resolve()
assert pathlib.Path(files.__file__).resolve() == pathlib.Path(sys.argv[3]).resolve()
for forbidden in ('pydantic', 'jsonschema', 'eom_catalog_contracts', 'eom_identifiers',
                  'torch', 'transformers', 'numpy', 'safetensors', 'tokenizers'):
    assert not any(name == forbidden or name.startswith(forbidden + '.') for name in sys.modules)
member = core.RuntimeWheelMemberPin('sha256:' + 'a' * 64, 1)
archive = core.RuntimeWheelArchivePin('torch-2.7.1+cu128-cp312-cp312-linux_x86_64.whl',
                                    'sha256:' + 'b' * 64, 1)
core.RuntimeWheelInstallationPin('torch', '2.7.1+cu128', archive, member, False, None, ())
print('STDLIB_WHEEL_CLOSURE_IMPORT_PASS')
"""
    result = subprocess.run(
        [
            sys.executable,
            "-I",
            "-S",
            "-B",
            "-c",
            code,
            str(source_root),
            core.__file__,
            files.__file__,
        ],
        env={"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "TZ": "UTC"},
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == "STDLIB_WHEEL_CLOSURE_IMPORT_PASS\n"
    tree = ast.parse(Path(core.__file__).read_text())
    local_imports = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("eom_")
    }
    assert local_imports == {"eom_catalog_service.embedding_runtime_files"}


@pytest.mark.parametrize(
    "name,version,filename",
    [
        ("torch", "2.7.1+cpu", "torch-2.7.1+cpu-cp312-cp312-linux_x86_64.whl"),
        ("torch", "2.7.1+cu128", "torch-2.7.1+cu128-cp312-cp312-linux_x86_64.whl"),
        ("nvidia-cublas-cu12", "12.8.3.14", "nvidia_cublas_cu12-12.8.3.14-py3-none-any.whl"),
    ],
)
def test_real_flavor_and_normalized_name_pin_spellings_are_not_rejected(
    name: str, version: str, filename: str
) -> None:
    pin = RuntimeWheelInstallationPin(
        name,
        version,
        RuntimeWheelArchivePin(filename, "sha256:" + "1" * 64, 1),
        RuntimeWheelMemberPin("sha256:" + "2" * 64, 1),
        False,
        None,
        (),
    )
    with pytest.raises(FrozenInstanceError):
        pin.name = "changed"  # type: ignore[misc]


@pytest.mark.parametrize(
    "section,field,value",
    [
        ("pin", "name", True),
        ("pin", "name", "Torch"),
        ("pin", "name", "a" * 65),
        ("pin", "version", "latest"),
        ("pin", "version", "1" * 97),
        ("pin", "requested", 0),
        ("pin", "requested", 1),
        ("pin", "requested", None),
        ("pin", "console_scripts", []),
        ("pin", "console_scripts", (None,)),
        ("pin", "archive", None),
        ("pin", "installed_record", None),
        ("pin", "direct_url", {}),
        ("archive", "wheel_filename", "../unsafe.whl"),
        ("archive", "wheel_filename", "torch.tar"),
        ("archive", "wheel_filename", "a" * 256),
        ("archive", "sha256", "sha256:" + "A" * 64),
        ("archive", "size_bytes", True),
        ("archive", "size_bytes", 0),
        ("archive", "size_bytes", 2 * 1024**3 + 1),
        ("installed_record", "sha256", "a" * 64),
        ("installed_record", "size_bytes", 1.0),
        ("installed_record", "size_bytes", 8 * 1024**2 + 1),
        ("direct_url", "size_bytes", 128 * 1024 + 1),
        ("script", "name", "bad/name"),
        ("script", "sha256", "sha256:" + "0" * 63),
        ("script", "size_bytes", False),
        ("script", "size_bytes", 16 * 1024 + 1),
    ],
)
def test_mutated_frozen_direct_pin_is_revalidated_before_any_file_io(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    section: str,
    field: str,
    value: Any,
) -> None:
    staged = staged_runtime(tmp_path, monkeypatch, with_generated=True)
    pin = wheel_pin(staged.proof.numeric_libraries[0])
    target = pin.console_scripts[0] if section == "script" else getattr(pin, section, pin)
    object.__setattr__(target, field, value)
    files = NumericalRuntimeFileSnapshots(os.geteuid())

    def forbidden(*args: object, **kwargs: object) -> Any:
        raise AssertionError("invalid direct pin reached a file boundary")

    monkeypatch.setattr(files, "verified_open", forbidden)
    with pytest.raises(
        InstalledRuntimeProofError, match=r"^INSTALLED_RUNTIME_DISTRIBUTION_INVALID$"
    ):
        verify_installed_runtime_wheel(
            pin, prefix=staged.prefix, archive_root=staged.archive_root, files=files
        )


@pytest.mark.parametrize("fault", ["duplicate", "unsorted", "count"])
def test_console_pin_collection_remains_exact_sorted_unique_and_bounded(fault: str) -> None:
    first = RuntimeWheelConsoleScriptPin("a", "sha256:" + "1" * 64, 1)
    second = RuntimeWheelConsoleScriptPin("b", "sha256:" + "2" * 64, 1)
    scripts = {
        "duplicate": (first, first),
        "unsorted": (second, first),
        "count": tuple(
            RuntimeWheelConsoleScriptPin(f"script{number:02}", "sha256:" + "1" * 64, 1)
            for number in range(17)
        ),
    }[fault]
    with pytest.raises(
        InstalledRuntimeProofError, match=r"^INSTALLED_RUNTIME_DISTRIBUTION_INVALID$"
    ):
        RuntimeWheelInstallationPin(
            "numpy",
            "2.4.6",
            RuntimeWheelArchivePin("numpy-2.4.6-py3-none-any.whl", "sha256:" + "1" * 64, 1),
            RuntimeWheelMemberPin("sha256:" + "2" * 64, 1),
            False,
            None,
            scripts,
        )


def test_direct_pin_constructors_enforce_exact_types_and_hashes() -> None:
    with pytest.raises(InstalledRuntimeProofError):
        RuntimeWheelMemberPin("sha256:" + "1" * 64, True)
    with pytest.raises(InstalledRuntimeProofError):
        RuntimeWheelArchivePin("unsafe\\name.whl", "sha256:" + "1" * 64, 1)
    with pytest.raises(InstalledRuntimeProofError):
        RuntimeWheelConsoleScriptPin("script", "unhashed", 1)


@pytest.mark.parametrize("fault", ["central_count", "central_bytes"])
def test_direct_core_bounds_zip_before_zipfile_constructor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fault: str
) -> None:
    import zipfile

    staged = staged_runtime(tmp_path, monkeypatch)
    pin = wheel_pin(staged.proof.numeric_libraries[0])
    payload = bytearray(staged.archives["numpy"].read_bytes())
    if fault == "central_count":
        struct.pack_into("<HH", payload, len(payload) - 14, 20001, 20001)
    else:
        struct.pack_into("<L", payload, len(payload) - 10, 16 * 1024**2 + 1)
    raw = bytes(payload)
    digest = sha256_bytes(raw)
    target = staged.archive_root / digest[7:] / pin.archive.wheel_filename
    target.parent.mkdir(mode=0o700)
    target.write_bytes(raw)
    target.chmod(0o600)
    pin = replace(pin, archive=replace(pin.archive, sha256=digest, size_bytes=len(raw)))

    def forbidden(*args: object, **kwargs: object) -> Any:
        raise AssertionError("invalid ZIP metadata reached ZipFile allocation")

    monkeypatch.setattr(zipfile, "ZipFile", forbidden)
    with pytest.raises(InstalledRuntimeProofError, match="ZIP_DIRECTORY_INVALID"):
        verify_installed_runtime_wheel(
            pin,
            prefix=staged.prefix,
            archive_root=staged.archive_root,
            files=NumericalRuntimeFileSnapshots(os.geteuid()),
        )


@pytest.mark.parametrize("fault", ["duplicate", "foreign", "hash"])
def test_direct_and_numeric_adapter_keep_identical_record_errors_and_no_execution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fault: str
) -> None:
    staged = staged_runtime(tmp_path, monkeypatch)
    library = staged.proof.numeric_libraries[0]
    record = staged.dist_infos["numpy"] / "RECORD"
    raw = record.read_bytes()
    if fault == "duplicate":
        raw += raw.splitlines(keepends=True)[0]
    elif fault == "foreign":
        raw += b"numpy/unowned.py,sha256=" + b"a" * 43 + b",1\n"
    else:
        raw = raw.replace(b",4\n", b",5\n", 1)
    record.write_bytes(raw)
    body = library.model_dump(mode="json")
    body["installed_record"].update(sha256=sha256_bytes(raw), size_bytes=len(raw))
    changed = InstalledNumericLibraryProof.model_validate(body)
    with pytest.raises(InstalledRuntimeProofError) as core_error:
        verify_installed_runtime_wheel(
            wheel_pin(changed),
            prefix=staged.prefix,
            archive_root=staged.archive_root,
            files=NumericalRuntimeFileSnapshots(os.geteuid()),
        )
    with pytest.raises(InstalledRuntimeProofError) as numeric_error:
        verify_installed_numeric_distribution(
            changed,
            prefix=staged.prefix,
            archive_root=staged.archive_root,
            files=NumericalRuntimeFileSnapshots(os.geteuid()),
        )
    assert core_error.value.code == numeric_error.value.code


@pytest.mark.parametrize("recipe", ["legacy", "modern", "removesuffix"])
def test_public_core_owns_only_the_three_exact_wrapper_byte_recipes(
    recipe: Literal["legacy", "modern", "removesuffix"],
) -> None:
    prefix = Path("/opt/eom/conda/envs/eom-embedding-index-cpu")
    entry = "torch.distributed.run", "main"
    raw = synthetic_console_wrapper(prefix, entry, recipe)
    validate_runtime_console_wrapper(raw, prefix, entry)
    with pytest.raises(InstalledRuntimeProofError, match="CONSOLE_WRAPPER_INVALID"):
        validate_runtime_console_wrapper(raw + b"import os\n", prefix, entry)


def _pip_alias_fixture(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, fault: str | None = None
) -> tuple[Path, Path, RuntimeWheelArchivePin]:
    """Explicit synthetic source/archive pin substitution; no installed pip execution."""
    prefix, archives = tmp_path / "prefix", tmp_path / "archives"
    dist = "pip-26.1.2.dist-info"
    generation = b"# synthetic source generation owner, never executed\n"
    source_pin = core._PIP_GENERATION_SOURCE[0], sha256_bytes(generation), len(generation)
    members = {
        dist + "/METADATA": b"Metadata-Version: 2.1\nName: pip\nVersion: 26.1.2\n\n",
        dist + "/WHEEL": b"Wheel-Version: 1.0\nRoot-Is-Purelib: true\nTag: py3-none-any\n\n",
        dist + "/entry_points.txt": (
            b"[console_scripts]\npip=pip._internal.cli.main:main\n"
            b"pip3=pip._internal.cli.main:main\n\n"
        ),
        source_pin[0]: generation,
    }
    if fault == "source":
        members[source_pin[0]] += b"# unaccepted change\n"
    if fault == "target":
        members[dist + "/entry_points.txt"] = members[dist + "/entry_points.txt"].replace(
            b":main", b":other"
        )
    if fault == "source_missing":
        del members[source_pin[0]]
    record_name = dist + "/RECORD"
    raw = synthetic_wheel(members | {record_name: synthetic_record(members, record_name)})
    archive = RuntimeWheelArchivePin("pip-26.1.2-py3-none-any.whl", sha256_bytes(raw), len(raw))
    archive_path = archives / archive.sha256[7:] / archive.wheel_filename
    archive_path.parent.mkdir(parents=True, mode=0o700)
    archive_path.write_bytes(raw)
    archive_path.chmod(0o600)
    monkeypatch.setattr(core, "_PIP_GENERATION_SOURCE", source_pin)
    expected = "sha256:" + "0" * 64 if fault == "archive" else archive.sha256
    monkeypatch.setattr(
        core,
        "_PIP_GENERATION_ARCHIVE",
        (
            "different" if fault == "name" else "pip",
            "26.1.3" if fault == "version" else "26.1.2",
            "wrong-26.1.2-py3-none-any.whl" if fault == "filename" else archive.wheel_filename,
            expected,
        ),
    )
    installed = members | {dist + "/INSTALLER": b"pip\n"}
    wrapper = synthetic_console_wrapper(prefix, ("pip._internal.cli.main", "main"), "removesuffix")
    if fault == "shebang":
        wrapper = wrapper.replace(str(prefix).encode(), b"/unaccepted-prefix", 1)
    for script in ("pip", "pip3", "pip3.12"):
        installed["../../../bin/" + script] = wrapper
    if fault == "alias_body":
        installed["../../../bin/pip3.12"] += b"import os\n"
    if fault == "declared_body":
        installed["../../../bin/pip3"] += b"# changed\n"
    if fault == "missing":
        del installed["../../../bin/pip3.12"]
    if fault == "extra":
        installed["../../../bin/pip3.11"] = wrapper
    installed_record = synthetic_record(installed, record_name)
    if fault == "record_hash":
        lines = installed_record.splitlines(keepends=True)
        installed_record = b"".join(
            b"../../../bin/pip3.12,sha256=" + b"a" * 43 + b",1\n"
            if line.startswith(b"../../../bin/pip3.12,")
            else line
            for line in lines
        )
    if fault == "duplicate":
        installed_record += next(
            line
            for line in installed_record.splitlines(keepends=True)
            if line.startswith(b"../../../bin/pip3.12,")
        )
    for name, value in (installed | {record_name: installed_record}).items():
        path = (
            prefix / "bin" / Path(name).name
            if name.startswith("../../../bin/")
            else prefix / "lib/python3.12/site-packages" / name
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(value)
        path.chmod(0o600)
    for path in [tmp_path, *tmp_path.rglob("*")]:
        if path.is_dir():
            path.chmod(0o700)
    return prefix, archives, archive


def test_generated_pip_alias_is_verified_inventory_not_public_console_proof(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    prefix, archives, archive = _pip_alias_fixture(tmp_path, monkeypatch)
    files = NumericalRuntimeFileSnapshots(os.geteuid())
    observed = observe_runtime_wheel_installation(
        archive, "pip", "26.1.2", prefix=prefix, files=files
    )
    assert tuple(script.name for script in observed.console_scripts) == ("pip", "pip3")
    verified = verify_installed_runtime_wheel(
        observed, prefix=prefix, archive_root=archives, files=files
    )
    assert prefix / "bin/pip3.12" in verified.all_installed_members
    assert (
        prefix / "bin/pip3.12" not in verified.installed_members | verified.archive_payload_members
    )
    assert verified.all_installed_members - verified.installed_members == frozenset(
        prefix / "bin" / name for name in ("pip", "pip3", "pip3.12")
    )
    files.assert_unchanged()
    with pytest.raises(InstalledRuntimeProofError):
        RuntimeWheelConsoleScriptPin(
            "pip3.12", observed.console_scripts[0].sha256, observed.console_scripts[0].size_bytes
        )


@pytest.mark.parametrize(
    "fault",
    [
        "archive",
        "name",
        "version",
        "filename",
        "source",
        "source_missing",
        "target",
        "shebang",
        "alias_body",
        "declared_body",
        "missing",
        "extra",
        "record_hash",
        "duplicate",
    ],
)
def test_generated_alias_never_skips_source_record_body_or_entry_validation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fault: str
) -> None:
    prefix, archives, archive = _pip_alias_fixture(tmp_path, monkeypatch, fault=fault)
    files = NumericalRuntimeFileSnapshots(os.geteuid())
    with pytest.raises(InstalledRuntimeProofError):
        observed = observe_runtime_wheel_installation(
            archive, "pip", "26.1.2", prefix=prefix, files=files
        )
        verify_installed_runtime_wheel(observed, prefix=prefix, archive_root=archives, files=files)


def test_copied_pip_alias_public_pin_is_rejected_before_io(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    prefix, archives, archive = _pip_alias_fixture(tmp_path, monkeypatch)
    observed = observe_runtime_wheel_installation(
        archive, "pip", "26.1.2", prefix=prefix, files=NumericalRuntimeFileSnapshots(os.geteuid())
    )
    copied = replace(observed.console_scripts[0])
    object.__setattr__(copied, "name", "pip3.12")
    object.__setattr__(observed, "console_scripts", (copied,))
    files = NumericalRuntimeFileSnapshots(os.geteuid())
    monkeypatch.setattr(
        files, "verified_open", lambda *_a, **_k: pytest.fail("invalid public alias reached IO")
    )
    with pytest.raises(InstalledRuntimeProofError, match="DISTRIBUTION_INVALID"):
        verify_installed_runtime_wheel(observed, prefix=prefix, archive_root=archives, files=files)


@pytest.mark.parametrize("fault", ["rewrite", "symlink", "hardlink"])
def test_generated_alias_keeps_actual_nofollow_and_epoch_binding(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fault: str
) -> None:
    prefix, archives, archive = _pip_alias_fixture(tmp_path, monkeypatch)
    files = NumericalRuntimeFileSnapshots(os.geteuid())
    alias = prefix / "bin/pip3.12"
    if fault == "rewrite":
        observed = observe_runtime_wheel_installation(
            archive, "pip", "26.1.2", prefix=prefix, files=files
        )
        _rewrite_with_distinct_mtime(alias)
        with pytest.raises(InstalledRuntimeProofError, match="CHANGED"):
            verify_installed_runtime_wheel(
                observed, prefix=prefix, archive_root=archives, files=files
            )
    else:
        alias.rename(alias.with_name("original"))
        if fault == "symlink":
            alias.symlink_to(alias.with_name("original"))
        else:
            os.link(alias.with_name("original"), alias)
        with pytest.raises(InstalledRuntimeProofError):
            observe_runtime_wheel_installation(archive, "pip", "26.1.2", prefix=prefix, files=files)


def _vendored_dist_info_fixture(
    tmp_path: Path,
    *,
    vendored: bool = True,
    fault: str | None = None,
    version: str = "83.0.0",
    direct_url: str | None = None,
    legacy_archive_hash: bool = False,
    entry_points: bytes | None = None,
    top_level_member: str | None = None,
) -> tuple[Path, Path, RuntimeWheelInstallationPin, Path]:
    """Small pinned payload; nested metadata/RECORD is never imported or installed separately."""
    prefix, archives = tmp_path / "prefix", tmp_path / "archives"
    dist = f"setuptools-{version}.dist-info"
    nested = "setuptools/_vendor/vendor0-1.0.dist-info/METADATA"
    members = {
        "setuptools/__init__.py": b"# synthetic package; never imported\n",
        dist
        + "/METADATA": f"Metadata-Version: 2.1\nName: setuptools\nVersion: {version}\n\n".encode(),
        dist + "/WHEEL": b"Wheel-Version: 1.0\nRoot-Is-Purelib: true\nTag: py3-none-any\n\n",
    }
    if entry_points is not None:
        members[dist + "/entry_points.txt"] = entry_points
    if top_level_member is not None:
        members[top_level_member] = b"# synthetic top-level payload; never executed\n"
    if vendored:
        for number in range(12):
            vendor = f"setuptools/_vendor/vendor{number}-1.0.dist-info"
            members[vendor + "/METADATA"] = (
                f"Metadata-Version: 2.1\nName: vendor{number}\nVersion: 1.0\n\n".encode()
            )
            members[vendor + "/WHEEL"] = b"nested WHEEL is ordinary source payload\n"
            members[vendor + "/RECORD"] = b"nested RECORD is ordinary source payload\n"
    if fault == "root_name":
        members[dist + "/METADATA"] = members[dist + "/METADATA"].replace(
            b"Name: setuptools", b"Name: foreign"
        )
    elif fault == "root_version":
        members[dist + "/METADATA"] = members[dist + "/METADATA"].replace(
            b"Version: 83.0.0", b"Version: 83.0.1"
        )
    elif fault == "root_duplicate_name":
        members[dist + "/METADATA"] = b"Name: setuptools\n" + members[dist + "/METADATA"]
    elif fault == "root_duplicate_version":
        members[dist + "/METADATA"] = b"Version: 83.0.0\n" + members[dist + "/METADATA"]
    elif fault == "root_missing":
        del members[dist + "/METADATA"]
    elif fault == "root_multiple":
        members["foreign-1.0.dist-info/METADATA"] = b"Name: foreign\nVersion: 1.0\n\n"
    elif fault == "root_namespace":
        members["foreign-1.0.dist-info/unrelated.txt"] = b"second top-level namespace"
    elif fault == "root_filename":
        changed = "setuptools-83.0.1.dist-info"
        members = {name.replace(dist, changed, 1): raw for name, raw in members.items()}
        dist = changed
    record_name = dist + "/RECORD"
    archive_members = dict(members)
    record = synthetic_record(members, record_name)
    if fault in {"nested_record_hash", "nested_record_size"}:
        lines = record.splitlines(keepends=True)
        record = b"".join(
            (nested + ",sha256=" + "A" * 43 + ",1\n").encode()
            if fault == "nested_record_hash" and line.startswith((nested + ",").encode())
            else line
            for line in lines
        )
        if fault == "nested_record_size":
            record = b"".join(
                line.rsplit(b",", 1)[0] + b",999\n"
                if line.startswith((nested + ",").encode())
                else line
                for line in record.splitlines(keepends=True)
            )
    elif fault == "nested_record_missing":
        record = b"".join(
            line
            for line in record.splitlines(keepends=True)
            if not line.startswith((nested + ",").encode())
        )
    elif fault == "nested_record_extra":
        record += b"setuptools/_vendor/unowned.py,sha256=" + b"A" * 43 + b",1\n"
    elif fault == "nested_record_duplicate":
        record += next(
            line
            for line in record.splitlines(keepends=True)
            if line.startswith((nested + ",").encode())
        )
    elif fault == "nested_archive_bytes":
        archive_members[nested] += b"unaccepted original bytes\n"
    raw = synthetic_wheel(archive_members | {record_name: record})
    archive = RuntimeWheelArchivePin(
        f"setuptools-{version}-py3-none-any.whl", sha256_bytes(raw), len(raw)
    )
    archive_path = archives / archive.sha256[7:] / archive.wheel_filename
    archive_path.parent.mkdir(parents=True, mode=0o700)
    archive_path.write_bytes(raw)
    archive_path.chmod(0o600)
    installed = members | {dist + "/INSTALLER": b"pip\n"}
    url_pin = None
    if direct_url is not None:
        uri = archive_path.as_uri()
        url = {
            "percent": uri,
            "literal": uri.replace("%2B", "+"),
            "lower_percent": uri.replace("%2B", "%2b"),
            "host": uri.replace("file:///", "file://localhost/"),
            "query": uri + "?accepted=true",
            "fragment": uri + "#archive",
            "other_path": uri.replace("/archives/", "/other-archives/"),
            "double_encoded": uri.replace("%2B", "%252B"),
        }.get(direct_url, uri)
        digest = "0" * 64 if direct_url == "wrong_hash" else archive.sha256[7:]
        info: dict[str, Any] = {"hashes": {"sha256": digest}}
        if legacy_archive_hash:
            info["hash"] = "sha256=" + digest
        if direct_url == "extra_field":
            info["accepted"] = True
        url_raw = json.dumps({"url": url, "archive_info": info}, separators=(",", ":")).encode()
        installed[dist + "/direct_url.json"] = url_raw
        url_pin = RuntimeWheelMemberPin(sha256_bytes(url_raw), len(url_raw))
    installed_record = synthetic_record(installed, record_name)
    if fault == "installed_record_missing":
        installed_record = b"".join(
            line
            for line in installed_record.splitlines(keepends=True)
            if not line.startswith((nested + ",").encode())
        )
    elif fault == "installed_record_extra":
        installed_record += b"setuptools/_vendor/unowned.py,sha256=" + b"A" * 43 + b",1\n"
    for name, value in (installed | {record_name: installed_record}).items():
        target = prefix / "lib/python3.12/site-packages" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(value)
        target.chmod(0o600)
    nested_path = prefix / "lib/python3.12/site-packages" / nested
    if fault == "installed_bytes":
        nested_path.write_bytes(b"X" + nested_path.read_bytes()[1:])
    elif fault == "installed_missing":
        nested_path.unlink()
    elif fault == "installed_extra":
        extra = nested_path.parent / "unowned.py"
        extra.write_bytes(b"unowned installed payload")
        extra.chmod(0o600)
    for path in [tmp_path, *tmp_path.rglob("*")]:
        if path.is_dir():
            path.chmod(0o700)
    return (
        prefix,
        archives,
        RuntimeWheelInstallationPin(
            "setuptools",
            version,
            archive,
            RuntimeWheelMemberPin(sha256_bytes(installed_record), len(installed_record)),
            False,
            url_pin,
            (),
        ),
        nested_path,
    )


@pytest.mark.parametrize("vendored", [False, True])
def test_root_metadata_alone_defines_identity_and_vendored_metadata_remains_complete_payload(
    tmp_path: Path, vendored: bool
) -> None:
    prefix, archives, pin, nested = _vendored_dist_info_fixture(tmp_path, vendored=vendored)
    files = NumericalRuntimeFileSnapshots(os.geteuid())
    observed = observe_runtime_wheel_installation(
        pin.archive, pin.name, pin.version, prefix=prefix, files=files
    )
    assert observed == pin
    verified = verify_installed_runtime_wheel(
        pin, prefix=prefix, archive_root=archives, files=files
    )
    assert (verified.name, verified.version) == ("setuptools", "83.0.0")
    site = prefix / "lib/python3.12/site-packages"
    assert verified.namespace_roots == frozenset(
        {site / "setuptools", site / "setuptools-83.0.0.dist-info"}
    )
    assert (nested in verified.archive_payload_members) is vendored
    assert (nested in verified.installed_members) is vendored
    assert len([path for path in verified.archive_payload_members if path.name == "METADATA"]) == (
        13 if vendored else 1
    )
    files.require_closed_namespaces(set(verified.namespace_roots), set(verified.installed_members))
    files.assert_unchanged()


@pytest.mark.parametrize(
    "fault,code",
    [
        ("root_name", "DISTRIBUTION_NAME_MISMATCH"),
        ("root_version", "DISTRIBUTION_VERSION_MISMATCH"),
        ("root_duplicate_name", "DISTRIBUTION_NAME_MISMATCH"),
        ("root_duplicate_version", "DISTRIBUTION_VERSION_MISMATCH"),
        ("root_missing", "METADATA_IDENTITY_INVALID"),
        ("root_multiple", "METADATA_IDENTITY_INVALID"),
        ("root_namespace", "METADATA_IDENTITY_INVALID"),
        ("root_filename", "WHEEL_FILENAME_IDENTITY_INVALID"),
        ("nested_archive_bytes", "WHEEL_RECORD_HASH_MISMATCH"),
        ("nested_record_hash", "WHEEL_RECORD_HASH_MISMATCH"),
        ("nested_record_size", "WHEEL_RECORD_HASH_MISMATCH"),
        ("nested_record_missing", "WHEEL_RECORD_SET_INVALID"),
        ("nested_record_extra", "WHEEL_RECORD_SET_INVALID"),
        ("nested_record_duplicate", "RECORD_ROW_INVALID"),
        ("installed_bytes", "FILE_HASH_MISMATCH"),
        ("installed_missing", "FILE_UNAVAILABLE"),
        ("installed_record_missing", "INSTALLED_RECORD_SET_MISMATCH"),
        ("installed_record_extra", "INSTALLED_RECORD_SET_MISMATCH"),
    ],
)
def test_vendored_payload_does_not_weaken_root_identity_record_or_installed_checks(
    tmp_path: Path, fault: str, code: str
) -> None:
    prefix, archives, pin, _nested = _vendored_dist_info_fixture(tmp_path, fault=fault)
    with pytest.raises(InstalledRuntimeProofError, match=code):
        verify_installed_runtime_wheel(
            pin,
            prefix=prefix,
            archive_root=archives,
            files=NumericalRuntimeFileSnapshots(os.geteuid()),
        )


def test_vendored_namespace_still_rejects_unregistered_installed_payload(tmp_path: Path) -> None:
    prefix, archives, pin, _nested = _vendored_dist_info_fixture(tmp_path, fault="installed_extra")
    files = NumericalRuntimeFileSnapshots(os.geteuid())
    verified = verify_installed_runtime_wheel(
        pin, prefix=prefix, archive_root=archives, files=files
    )
    with pytest.raises(InstalledRuntimeProofError, match="NAMESPACE_SET_MISMATCH"):
        files.require_closed_namespaces(
            set(verified.namespace_roots), set(verified.installed_members)
        )


@pytest.mark.parametrize("fault", ["rewrite", "replace", "symlink", "hardlink"])
def test_vendored_metadata_is_bound_to_actual_protected_file_epochs(
    tmp_path: Path, fault: str
) -> None:
    prefix, archives, pin, nested = _vendored_dist_info_fixture(tmp_path)
    files = NumericalRuntimeFileSnapshots(os.geteuid())
    verify_installed_runtime_wheel(pin, prefix=prefix, archive_root=archives, files=files)
    raw = nested.read_bytes()
    if fault == "rewrite":
        _rewrite_with_distinct_mtime(nested)
    elif fault == "replace":
        replacement = nested.with_name("replacement")
        replacement.write_bytes(raw)
        replacement.chmod(0o600)
        replacement.replace(nested)
    else:
        original = nested.with_name("original")
        nested.rename(original)
        if fault == "symlink":
            nested.symlink_to(original)
        else:
            os.link(original, nested)
    with pytest.raises(InstalledRuntimeProofError, match="CHANGED"):
        files.assert_unchanged()


def _fixture_zip_attributes(
    archives: Path, pin: RuntimeWheelInstallationPin, mode: int, *, directory: bool = False
) -> RuntimeWheelInstallationPin:
    original = archives / pin.archive.sha256[7:] / pin.archive.wheel_filename
    output = io.BytesIO()
    with zipfile.ZipFile(original) as source, zipfile.ZipFile(output, "w") as target:
        for info in source.infolist():
            raw = source.read(info)
            if info.filename == "setuptools/__init__.py" and not directory:
                info.create_system = 3
                info.external_attr = mode << 16
            target.writestr(info, raw)
        if directory:
            entry = zipfile.ZipInfo("setuptools/")
            entry.create_system = 3
            entry.external_attr = mode << 16
            target.writestr(entry, b"")
    raw = output.getvalue()
    archive = replace(pin.archive, sha256=sha256_bytes(raw), size_bytes=len(raw))
    path = archives / archive.sha256[7:] / archive.wheel_filename
    path.parent.mkdir(mode=0o700, exist_ok=True)
    path.write_bytes(raw)
    path.chmod(0o600)
    return replace(pin, archive=archive)


@pytest.mark.parametrize("mode", [0o644, 0o755, stat.S_IFREG | 0o644])
def test_archive_regular_file_accepts_only_bare_permissions_or_explicit_regular_type(
    tmp_path: Path, mode: int
) -> None:
    prefix, archives, pin, _nested = _vendored_dist_info_fixture(tmp_path)
    pin = _fixture_zip_attributes(archives, pin, mode)
    files = NumericalRuntimeFileSnapshots(os.geteuid())
    verify_installed_runtime_wheel(pin, prefix=prefix, archive_root=archives, files=files)
    files.assert_unchanged()


@pytest.mark.parametrize(
    "kind", [stat.S_IFLNK, stat.S_IFDIR, stat.S_IFSOCK, stat.S_IFIFO, stat.S_IFCHR, stat.S_IFBLK]
)
def test_archive_explicit_special_types_remain_forbidden(tmp_path: Path, kind: int) -> None:
    prefix, archives, pin, _nested = _vendored_dist_info_fixture(tmp_path)
    pin = _fixture_zip_attributes(archives, pin, kind | 0o644)
    with pytest.raises(InstalledRuntimeProofError, match="ZIP_MEMBER_INVALID"):
        verify_installed_runtime_wheel(
            pin,
            prefix=prefix,
            archive_root=archives,
            files=NumericalRuntimeFileSnapshots(os.geteuid()),
        )


@pytest.mark.parametrize("mode", [0o755, stat.S_IFREG | 0o755, stat.S_IFLNK | 0o755])
def test_zip_directory_still_requires_explicit_directory_type(tmp_path: Path, mode: int) -> None:
    prefix, archives, pin, _nested = _vendored_dist_info_fixture(tmp_path)
    pin = _fixture_zip_attributes(archives, pin, mode, directory=True)
    with pytest.raises(InstalledRuntimeProofError, match="ZIP_DIRECTORY_MEMBER_INVALID"):
        verify_installed_runtime_wheel(
            pin,
            prefix=prefix,
            archive_root=archives,
            files=NumericalRuntimeFileSnapshots(os.geteuid()),
        )


@pytest.mark.parametrize("spelling", ["percent", "literal"])
@pytest.mark.parametrize("legacy_archive_hash", [False, True])
def test_direct_url_accepts_only_two_canonical_plus_spellings_and_existing_hash_shapes(
    tmp_path: Path, spelling: str, legacy_archive_hash: bool
) -> None:
    prefix, archives, pin, _nested = _vendored_dist_info_fixture(
        tmp_path,
        version="83.0.0+fixture",
        direct_url=spelling,
        legacy_archive_hash=legacy_archive_hash,
    )
    files = NumericalRuntimeFileSnapshots(os.geteuid())
    observed = observe_runtime_wheel_installation(
        pin.archive, pin.name, pin.version, prefix=prefix, files=files
    )
    assert observed == pin
    verify_installed_runtime_wheel(pin, prefix=prefix, archive_root=archives, files=files)
    files.assert_unchanged()


@pytest.mark.parametrize(
    "fault",
    [
        "lower_percent",
        "host",
        "query",
        "fragment",
        "other_path",
        "double_encoded",
        "wrong_hash",
        "extra_field",
    ],
)
def test_direct_url_plus_compatibility_never_normalizes_location_or_hash(
    tmp_path: Path, fault: str
) -> None:
    prefix, archives, pin, _nested = _vendored_dist_info_fixture(
        tmp_path, version="83.0.0+fixture", direct_url=fault
    )
    with pytest.raises(InstalledRuntimeProofError, match="DIRECT_URL_INVALID"):
        verify_installed_runtime_wheel(
            pin,
            prefix=prefix,
            archive_root=archives,
            files=NumericalRuntimeFileSnapshots(os.geteuid()),
        )


def _relocated_payload_fixture(
    tmp_path: Path, package: str, *, fault: str | None = None, directories: bool = False
) -> tuple[Path, Path, RuntimeWheelInstallationPin, Path]:
    prefix, archives = tmp_path / "prefix", tmp_path / "archives"
    version, role, remainder, size = (
        ("3.5.5", "headers", "greenlet.h", 4755)
        if package == "greenlet"
        else ("1.14.0", "data", "share/man/man1/isympy.1", 6659)
    )
    dist = f"{package}-{version}.dist-info"
    relocation = f"{package}-{version}.data/{role}/{remainder}"
    payload = b"synthetic relocated source\n" + b"x" * (size - 27)
    assert len(payload) == size
    target = (
        prefix / "include/python3.12/greenlet/greenlet.h"
        if package == "greenlet"
        else prefix / "share/man/man1/isympy.1"
    )
    members = {
        package + "/__init__.py": b"# synthetic source; never imported\n",
        dist + "/METADATA": f"Name: {package}\nVersion: {version}\n\n".encode(),
        dist + "/WHEEL": b"Wheel-Version: 1.0\nRoot-Is-Purelib: true\nTag: py3-none-any\n\n",
        relocation: payload,
    }
    archive_members = dict(members)
    if fault in {"role", "foreign_root", "version", "nested_data", "traversal", "empty"}:
        changed = {
            "role": relocation.replace(f".data/{role}/", ".data/scripts/"),
            "foreign_root": relocation.replace(package + "-", "foreign-", 1),
            "version": relocation.replace(version + ".data", "0.1.data", 1),
            "nested_data": relocation.replace(f".data/{role}/", f".data/{role}/nested.data/"),
            "traversal": relocation.replace(f".data/{role}/", f".data/{role}/../"),
            "empty": relocation.split("/", 2)[0] + "/" + role,
        }[fault]
        archive_members[changed] = archive_members.pop(relocation)
    elif fault == "ordinary_collision":
        archive_members[
            f"{package}-{version}.data/data/lib/python3.12/site-packages/{package}/__init__.py"
        ] = b"collision"
    elif fault == "relocated_collision":
        archive_members[f"{package}-{version}.data/data/include/python3.12/greenlet/greenlet.h"] = (
            payload
        )
    elif fault == "file_parent_collision":
        archive_members[f"{package}-{version}.data/data/share"] = b"not a directory"
    elif fault == "mapped_parent_collision":
        archive_members[f"{package}-{version}.data/data/lib/python3.12/site-packages/{package}"] = (
            b"not a directory"
        )
    elif fault == "generated_collision":
        archive_members[
            f"{package}-{version}.data/data/lib/python3.12/site-packages/{dist}/INSTALLER"
        ] = b"pip\n"
    record_name = dist + "/RECORD"
    record = synthetic_record(archive_members, record_name)
    if fault == "archive_hash":
        archive_members[relocation] = b"X" + archive_members[relocation][1:]
    elif fault == "record_missing":
        record = b"".join(
            row
            for row in record.splitlines(keepends=True)
            if not row.startswith((relocation + ",").encode())
        )
    raw = synthetic_wheel(archive_members | {record_name: record})
    if directories:
        buffer = io.BytesIO()
        with zipfile.ZipFile(io.BytesIO(raw)) as source, zipfile.ZipFile(buffer, "w") as archive:
            for entry in source.infolist():
                archive.writestr(entry, source.read(entry))
            parts = relocation.split("/")[:-1]
            for count in range(1, len(parts) + 1):
                entry = zipfile.ZipInfo("/".join(parts[:count]) + "/")
                entry.external_attr = (stat.S_IFDIR | 0o755) << 16
                archive.writestr(entry, b"")
        raw = buffer.getvalue()
    archive_pin = RuntimeWheelArchivePin(
        f"{package}-{version}-py3-none-any.whl", sha256_bytes(raw), len(raw)
    )
    archive_path = archives / archive_pin.sha256[7:] / archive_pin.wheel_filename
    archive_path.parent.mkdir(parents=True, mode=0o700)
    archive_path.write_bytes(raw)
    archive_path.chmod(0o600)
    site = prefix / "lib/python3.12/site-packages"
    relative = "../../../" + target.relative_to(prefix).as_posix()
    if fault == "wrong_header_scheme":
        relative = "../../../include/site/python3.12/greenlet/greenlet.h"
    installed = {name: value for name, value in members.items() if name != relocation}
    installed[relative] = payload
    installed[dist + "/INSTALLER"] = b"pip\n"
    if fault == "generated_collision":
        # Actual protected bytes agree; archive ownership must still not collide with pip additions.
        installed[dist + "/INSTALLER"] = b"pip\n"
    installed_record = synthetic_record(installed, record_name)
    if fault == "installed_record_extra":
        installed_record += b"../../../share/unowned.txt,sha256=" + b"A" * 43 + b",1\n"
    for name, value in (installed | {record_name: installed_record}).items():
        path = prefix / name[9:] if name.startswith("../../../") else site / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(value)
        path.chmod(0o600)
    if fault == "installed_missing":
        target.unlink()
    elif fault == "installed_hash":
        target.write_bytes(b"X" + target.read_bytes()[1:])
    for path in [tmp_path, *tmp_path.rglob("*")]:
        if path.is_dir():
            path.chmod(0o700)
    return (
        prefix,
        archives,
        RuntimeWheelInstallationPin(
            package,
            version,
            archive_pin,
            RuntimeWheelMemberPin(sha256_bytes(installed_record), len(installed_record)),
            False,
            None,
            (),
        ),
        target,
    )


@pytest.mark.parametrize("package", ["greenlet", "sympy"])
@pytest.mark.parametrize("directories", [False, True])
def test_exact_headers_and_man_data_relocations_are_complete_verified_inventory(
    tmp_path: Path, package: str, directories: bool
) -> None:
    prefix, archives, pin, target = _relocated_payload_fixture(
        tmp_path, package, directories=directories
    )
    files = NumericalRuntimeFileSnapshots(os.geteuid())
    observed = observe_runtime_wheel_installation(
        pin.archive, pin.name, pin.version, prefix=prefix, files=files
    )
    assert observed == pin
    verified = verify_installed_runtime_wheel(
        pin, prefix=prefix, archive_root=archives, files=files
    )
    assert target in verified.all_installed_members & verified.archive_payload_members
    assert target not in verified.installed_members
    assert all(
        path.is_relative_to(prefix / "lib/python3.12/site-packages")
        for path in verified.namespace_roots
    )
    files.require_closed_namespaces(set(verified.namespace_roots), set(verified.installed_members))
    files.assert_unchanged()


@pytest.mark.parametrize(
    "package,fault,code",
    [
        ("greenlet", "role", "WHEEL_DATA_LAYOUT_UNSUPPORTED"),
        ("greenlet", "foreign_root", "WHEEL_DATA_LAYOUT_UNSUPPORTED"),
        ("greenlet", "version", "WHEEL_DATA_LAYOUT_UNSUPPORTED"),
        ("greenlet", "nested_data", "WHEEL_DATA_LAYOUT_UNSUPPORTED"),
        ("greenlet", "traversal", "MEMBER_PATH_INVALID"),
        ("greenlet", "empty", "WHEEL_DATA_LAYOUT_UNSUPPORTED"),
        ("greenlet", "ordinary_collision", "WHEEL_MAPPED_TARGET_COLLISION"),
        ("greenlet", "relocated_collision", "WHEEL_MAPPED_TARGET_COLLISION"),
        ("sympy", "file_parent_collision", "ZIP_FILE_DIRECTORY_COLLISION"),
        ("greenlet", "mapped_parent_collision", "WHEEL_MAPPED_TARGET_COLLISION"),
        ("greenlet", "generated_collision", "WHEEL_GENERATED_TARGET_COLLISION"),
        ("greenlet", "wrong_header_scheme", "FILE_UNAVAILABLE"),
        ("sympy", "archive_hash", "WHEEL_RECORD_HASH_MISMATCH"),
        ("sympy", "record_missing", "WHEEL_RECORD_SET_INVALID"),
        ("greenlet", "installed_missing", "FILE_UNAVAILABLE"),
        ("sympy", "installed_hash", "FILE_HASH_MISMATCH"),
        ("sympy", "installed_record_extra", "INSTALLED_RECORD_SET_MISMATCH"),
    ],
)
def test_data_relocation_keeps_closed_scheme_source_record_target_and_protection(
    tmp_path: Path, package: str, fault: str, code: str
) -> None:
    prefix, archives, pin, _target = _relocated_payload_fixture(tmp_path, package, fault=fault)
    with pytest.raises(InstalledRuntimeProofError, match=code):
        verify_installed_runtime_wheel(
            pin,
            prefix=prefix,
            archive_root=archives,
            files=NumericalRuntimeFileSnapshots(os.geteuid()),
        )


@pytest.mark.parametrize("package", ["greenlet", "sympy"])
def test_relocated_payload_stays_bound_to_protected_epochs(tmp_path: Path, package: str) -> None:
    prefix, archives, pin, target = _relocated_payload_fixture(tmp_path, package)
    files = NumericalRuntimeFileSnapshots(os.geteuid())
    verify_installed_runtime_wheel(pin, prefix=prefix, archive_root=archives, files=files)
    _rewrite_with_distinct_mtime(target)
    with pytest.raises(InstalledRuntimeProofError, match="CHANGED"):
        files.assert_unchanged()


@pytest.mark.parametrize(
    "raw",
    [
        b"[console_scripts]\n",
        b"[console_scripts]\n[gui_scripts]\n",
        b"[console_scripts]\n\n[gui_scripts]\n# no executable GUI entry\n; empty metadata\n",
        b"  [console_scripts]  \n\n  [gui_scripts]  \n \t\n",
    ],
)
def test_absent_and_effectively_empty_gui_section_keeps_full_archive_and_installed_association(
    tmp_path: Path, raw: bytes
) -> None:
    prefix, archives, pin, _nested = _vendored_dist_info_fixture(tmp_path, entry_points=raw)
    files = NumericalRuntimeFileSnapshots(os.geteuid())
    observed = observe_runtime_wheel_installation(
        pin.archive, pin.name, pin.version, prefix=prefix, files=files
    )
    assert observed == pin
    verified = verify_installed_runtime_wheel(
        pin, prefix=prefix, archive_root=archives, files=files
    )
    member = prefix / "lib/python3.12/site-packages/setuptools-83.0.0.dist-info/entry_points.txt"
    assert member in verified.archive_payload_members & verified.installed_members
    assert observed.console_scripts == ()
    files.require_closed_namespaces(set(verified.namespace_roots), set(verified.installed_members))
    files.assert_unchanged()


@pytest.mark.parametrize(
    "raw,code",
    [
        (b"[gui_scripts]\nrun=example.gui:main\n", "GUI_SCRIPTS_FORBIDDEN"),
        (b"[gui_scripts]\nrun=\n", "GUI_SCRIPTS_FORBIDDEN"),
        (b"[DEFAULT]\nrun=example.gui:main\n[gui_scripts]\n", "GUI_SCRIPTS_FORBIDDEN"),
        (b"[DEFAULT]\nrun=\n[gui_scripts]\n", "GUI_SCRIPTS_FORBIDDEN"),
        (b"[gui_scripts]\n[gui_scripts]\n", "DISTRIBUTION_INVALID"),
        (b"[gui_scripts]\nrun=example.gui:main\nrun=other.gui:main\n", "DISTRIBUTION_INVALID"),
        (b"[gui_scripts]\nrun\n", "DISTRIBUTION_INVALID"),
        (b"unsectioned invalid metadata\n", "DISTRIBUTION_INVALID"),
        (b"[console_scripts]\nrun=not a callable\n[gui_scripts]\n", "ENTRY_POINT_INVALID"),
    ],
)
def test_empty_gui_compatibility_never_admits_effective_entries_or_malformed_metadata(
    tmp_path: Path, raw: bytes, code: str
) -> None:
    prefix, archives, pin, _nested = _vendored_dist_info_fixture(tmp_path, entry_points=raw)
    with pytest.raises(InstalledRuntimeProofError, match=code):
        verify_installed_runtime_wheel(
            pin,
            prefix=prefix,
            archive_root=archives,
            files=NumericalRuntimeFileSnapshots(os.geteuid()),
        )


@pytest.mark.parametrize("member", ["distutils-precedence.pth", "exam_helper.py"])
def test_single_file_namespace_keeps_full_wheel_record_byte_and_epoch_closure(
    tmp_path: Path, member: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    prefix, archives, pin, _nested = _vendored_dist_info_fixture(tmp_path, top_level_member=member)
    files = NumericalRuntimeFileSnapshots(os.geteuid())
    observed = observe_runtime_wheel_installation(
        pin.archive, pin.name, pin.version, prefix=prefix, files=files
    )
    assert observed == pin
    verified = verify_installed_runtime_wheel(
        observed, prefix=prefix, archive_root=archives, files=files
    )
    target = prefix / "lib/python3.12/site-packages" / member
    assert target in verified.namespace_roots
    assert target in verified.archive_payload_members & verified.installed_members
    raw = target.read_bytes()
    monkeypatch.setattr(
        files, "verified_open", lambda *_a, **_k: pytest.fail("namespace closure must not rehash")
    )
    files.require_closed_namespaces(set(verified.namespace_roots), set(verified.installed_members))
    files.verify(target, sha256=sha256_bytes(raw), size=len(raw), maximum=1024)
    files.assert_unchanged()


def test_verified_regular_only_namespace_preserves_its_byte_epoch_without_rehash(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "single_module.py"
    raw = b"# synthetic module; never imported\n"
    target.write_bytes(raw)
    target.chmod(0o600)
    files = NumericalRuntimeFileSnapshots(os.geteuid())
    files.verify(target, sha256=sha256_bytes(raw), size=len(raw), maximum=1024)
    monkeypatch.setattr(
        files, "verified_open", lambda *_a, **_k: pytest.fail("namespace closure must not rehash")
    )
    files.require_closed_namespaces({target}, {target})
    files.verify(target, sha256=sha256_bytes(raw), size=len(raw), maximum=1024)
    files.assert_unchanged()


@pytest.mark.parametrize(
    "shape", ["unexpected_file", "missing_file", "unexpected_directory_member"]
)
def test_file_and_directory_roots_keep_exact_missing_extra_set_equality(
    tmp_path: Path, shape: str
) -> None:
    target = tmp_path / "single.py"
    target.write_bytes(b"# synthetic file\n")
    target.chmod(0o600)
    directory = tmp_path / "package"
    directory.mkdir(mode=0o700)
    member = directory / "__init__.py"
    member.write_bytes(b"# synthetic package\n")
    member.chmod(0o600)
    roots = {target, directory}
    expected = {target, member}
    if shape == "unexpected_file":
        expected.remove(target)
    elif shape == "missing_file":
        roots.remove(target)
    else:
        expected.remove(member)
    files = NumericalRuntimeFileSnapshots(os.geteuid())
    with pytest.raises(InstalledRuntimeProofError, match="NAMESPACE_SET_MISMATCH"):
        files.require_closed_namespaces(roots, expected)


@pytest.mark.parametrize(
    "fault,code",
    [
        ("missing", "NAMESPACE_UNAVAILABLE"),
        ("symlink", "NAMESPACE_LINK"),
        ("hardlink", "FILE_UNPROTECTED"),
        ("writable", "FILE_UNPROTECTED"),
        ("fifo", "NAMESPACE_UNPROTECTED"),
        ("directory_writable", "NAMESPACE_UNPROTECTED"),
        ("owner", "ANCESTOR_UNPROTECTED"),
    ],
)
def test_regular_namespace_root_retains_protected_type_mode_owner_and_single_link(
    tmp_path: Path, fault: str, code: str
) -> None:
    target = tmp_path / "single.py"
    target.write_bytes(b"# synthetic file\n")
    target.chmod(0o600)
    owner = os.geteuid()
    if fault == "missing":
        target.unlink()
    elif fault in {"symlink", "hardlink"}:
        original = target.with_name("original.py")
        target.rename(original)
        if fault == "symlink":
            target.symlink_to(original)
        else:
            os.link(original, target)
    elif fault == "writable":
        target.chmod(0o622)
    elif fault == "fifo":
        target.unlink()
        os.mkfifo(target, mode=0o600)
    elif fault == "directory_writable":
        target.unlink()
        target.mkdir(mode=0o722)
        target.chmod(0o722)
    else:
        # The actual protected-open walk rejects this different owner at the
        # user-owned pytest ancestor before reaching the member itself.
        owner += 1
    files = NumericalRuntimeFileSnapshots(owner)
    with pytest.raises(InstalledRuntimeProofError, match=code):
        files.require_closed_namespaces({target}, {target})


@pytest.mark.parametrize("fault", ["rewrite", "replace", "symlink", "hardlink", "delete"])
@pytest.mark.parametrize("after_namespace", [False, True])
def test_regular_namespace_keeps_original_verified_epoch_before_and_after_observation(
    tmp_path: Path, fault: str, after_namespace: bool
) -> None:
    target = tmp_path / "single.py"
    raw = b"# synthetic file; never executed\n"
    target.write_bytes(raw)
    target.chmod(0o600)
    files = NumericalRuntimeFileSnapshots(os.geteuid())
    files.verify(target, sha256=sha256_bytes(raw), size=len(raw), maximum=1024)
    if after_namespace:
        files.require_closed_namespaces({target}, {target})
    if fault == "rewrite":
        _rewrite_with_distinct_mtime(target)
    elif fault == "delete":
        target.unlink()
    else:
        original = target.with_name("original.py")
        target.rename(original)
        if fault == "replace":
            target.write_bytes(raw)
            target.chmod(0o600)
        elif fault == "symlink":
            target.symlink_to(original)
        else:
            os.link(original, target)
    with pytest.raises(InstalledRuntimeProofError):
        if after_namespace:
            files.assert_unchanged()
        else:
            files.require_closed_namespaces({target}, {target})


def test_empty_directory_root_is_still_bound_when_walk_yields_no_rows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    directory = tmp_path / "empty"
    directory.mkdir(mode=0o700)
    files = NumericalRuntimeFileSnapshots(os.geteuid())
    monkeypatch.setattr("eom_catalog_service.embedding_runtime_files.os.walk", lambda *_a, **_k: ())
    files.require_closed_namespaces({directory}, set())
    # Keep the old inode live so this test does not rely on filesystem reuse.
    directory.rename(directory.with_name("retired-empty"))
    directory.mkdir(mode=0o700)
    with pytest.raises(InstalledRuntimeProofError, match="NAMESPACE_CHANGED"):
        files.assert_unchanged()


@pytest.mark.parametrize("timing", ["before_walk", "between_calls"])
def test_directory_root_epoch_cannot_be_refreshed_by_walk_or_repeated_observation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, timing: str
) -> None:
    directory = tmp_path / "empty"
    directory.mkdir(mode=0o700)
    files = NumericalRuntimeFileSnapshots(os.geteuid())

    def replace_directory() -> None:
        original_inode = directory.stat().st_ino
        directory.rename(directory.with_name("retired-empty"))
        directory.mkdir(mode=0o700)
        assert directory.stat().st_ino != original_inode

    if timing == "before_walk":
        original_walk = os.walk

        def replacing_walk(
            root: Path, *, followlinks: bool
        ) -> Iterator[tuple[str, list[str], list[str]]]:
            replace_directory()
            yield from original_walk(root, followlinks=followlinks)

        monkeypatch.setattr("eom_catalog_service.embedding_runtime_files.os.walk", replacing_walk)
    else:
        files.require_closed_namespaces({directory}, set())
        replace_directory()
    with pytest.raises(InstalledRuntimeProofError, match="NAMESPACE_CHANGED"):
        files.require_closed_namespaces({directory}, set())


def test_unchanged_directory_root_can_be_closed_twice_in_the_same_snapshot(tmp_path: Path) -> None:
    directory = tmp_path / "empty"
    directory.mkdir(mode=0o700)
    files = NumericalRuntimeFileSnapshots(os.geteuid())
    files.require_closed_namespaces({directory}, set())
    files.require_closed_namespaces({directory}, set())
    files.assert_unchanged()
