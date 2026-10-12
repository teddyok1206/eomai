"""Stdlib mechanical parity and hostile pins; no installed runtime/model/device admission."""

from __future__ import annotations

import ast
import os
import struct
import subprocess
import sys
from dataclasses import FrozenInstanceError, replace
from pathlib import Path
from typing import Any, Literal

import pytest
from eom_catalog_contracts.embedding_installed_runtime_proof import (
    EmbeddingRuntimeProfile,
    InstalledNumericLibraryProof,
)
from eom_catalog_service.embedding_runtime_distribution import verify_installed_numeric_distribution
from eom_catalog_service.embedding_runtime_files import (
    InstalledRuntimeProofError,
    NumericalRuntimeFileSnapshots,
)
from eom_catalog_service.embedding_runtime_wheel_closure import (
    RuntimeWheelArchivePin,
    RuntimeWheelConsoleScriptPin,
    RuntimeWheelInstallationPin,
    RuntimeWheelMemberPin,
    validate_runtime_console_wrapper,
    verify_installed_runtime_wheel,
)
from eom_identifiers import sha256_bytes

from tests.unit.embedding_installed_runtime_fixtures import (
    staged_runtime,
    synthetic_console_wrapper,
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
