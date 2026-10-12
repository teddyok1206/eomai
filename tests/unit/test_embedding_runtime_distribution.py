from __future__ import annotations

import io
import os
import stat
import struct
import zipfile
from contextlib import nullcontext
from pathlib import Path

import pytest
from eom_catalog_contracts.embedding_installed_runtime_proof import InstalledNumericLibraryProof
from eom_catalog_service.embedding_runtime_distribution import (
    validate_numeric_console_wrapper,
    verify_installed_numeric_distribution,
)
from eom_catalog_service.embedding_runtime_files import (
    InstalledRuntimeProofError,
    NumericalRuntimeFileSnapshots,
)
from eom_identifiers import sha256_bytes

from tests.unit.embedding_installed_runtime_fixtures import (
    StagedSyntheticRuntime,
    staged_runtime,
    synthetic_record,
    synthetic_wheel,
)


def _numpy_archive_members(staged: StagedSyntheticRuntime) -> dict[str, bytes]:
    with zipfile.ZipFile(io.BytesIO(staged.archives["numpy"].read_bytes())) as archive:
        return {info.filename: archive.read(info) for info in archive.infolist()}


def _repacked_numpy_library(
    staged: StagedSyntheticRuntime, payload: bytes
) -> InstalledNumericLibraryProof:
    original = staged.proof.numeric_libraries[0]
    digest = sha256_bytes(payload)
    target = staged.archive_root / digest[7:] / original.archive.wheel_filename
    target.parent.mkdir(mode=0o700)
    target.write_bytes(payload)
    target.chmod(0o600)
    body = original.model_dump(mode="json")
    body["archive"].update(sha256=digest, size_bytes=len(payload))
    return InstalledNumericLibraryProof.model_validate(body)


def _directory_entry(name: str, mode: int = stat.S_IFDIR | 0o755) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name)
    info.create_system = 3
    info.external_attr = mode << 16
    return info


def _wheel_with_directories(
    members: dict[str, bytes],
    directories: tuple[tuple[zipfile.ZipInfo, bytes], ...],
    *,
    directories_first: bool = False,
) -> bytes:
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:

        def add_directories() -> None:
            for info, raw in directories:
                archive.writestr(info, raw)

        if directories_first:
            add_directories()
        for name, raw in members.items():
            info = zipfile.ZipInfo(name)
            info.external_attr = (stat.S_IFREG | 0o644) << 16
            archive.writestr(info, raw)
        if not directories_first:
            add_directories()
    return stream.getvalue()


@pytest.mark.parametrize("directories_first", [False, True])
def test_zero_byte_ancestor_directories_preserve_exact_file_and_installed_closure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, directories_first: bool
) -> None:
    staged = staged_runtime(tmp_path, monkeypatch)
    members = _numpy_archive_members(staged)
    dist = "numpy-2.4.6.dist-info"
    payload = _wheel_with_directories(
        members,
        ((_directory_entry("numpy/"), b""), (_directory_entry(dist + "/"), b"")),
        directories_first=directories_first,
    )
    library = _repacked_numpy_library(staged, payload)
    snapshots = NumericalRuntimeFileSnapshots(os.geteuid())
    verified = verify_installed_numeric_distribution(
        library, prefix=staged.prefix, archive_root=staged.archive_root, files=snapshots
    )
    site = staged.prefix / "lib/python3.12/site-packages"
    assert verified.installed_members == frozenset(
        site / name for name in (*members, dist + "/INSTALLER")
    )
    assert verified.namespace_roots == frozenset((site / "numpy", site / dist))
    assert verified.pin.distribution_sha256 == sha256_bytes(payload)
    snapshots.assert_unchanged()


@pytest.mark.parametrize("count", [33, 492])
def test_bounded_directory_coverage_at_actual_triton_and_torch_counts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, count: int
) -> None:
    """Synthetic namespace scale only, not proof of the real CUDA wheels or an installation."""
    staged = staged_runtime(tmp_path, monkeypatch)
    members = _numpy_archive_members(staged)
    record_name = "numpy-2.4.6.dist-info/RECORD"
    members.pop(record_name)
    additions = {f"numpy/branch_{index}/value.py": b"# never imported\n" for index in range(count)}
    members.update(additions)
    members[record_name] = synthetic_record(members, record_name)
    payload = _wheel_with_directories(
        members, tuple((_directory_entry(f"numpy/branch_{index}/"), b"") for index in range(count))
    )
    library = _repacked_numpy_library(staged, payload)
    site = staged.prefix / "lib/python3.12/site-packages"
    for name, raw in additions.items():
        target = site / name
        target.parent.mkdir(mode=0o700)
        target.write_bytes(raw)
        target.chmod(0o600)
    installed = {name: raw for name, raw in members.items() if name != record_name}
    installed["numpy-2.4.6.dist-info/INSTALLER"] = b"pip\n"
    record = synthetic_record(installed, record_name)
    (site / record_name).write_bytes(record)
    body = library.model_dump(mode="json")
    body["installed_record"].update(sha256=sha256_bytes(record), size_bytes=len(record))
    library = InstalledNumericLibraryProof.model_validate(body)
    result = verify_installed_numeric_distribution(
        library,
        prefix=staged.prefix,
        archive_root=staged.archive_root,
        files=NumericalRuntimeFileSnapshots(os.geteuid()),
    )
    assert len(result.installed_members) == len(members) + 1


@pytest.mark.parametrize(
    "fault,code",
    [
        ("duplicate", "ZIP_MEMBER_DUPLICATE_TARGET"),
        ("symlink", "ZIP_DIRECTORY_MEMBER_INVALID"),
        ("regular_mode", "ZIP_DIRECTORY_MEMBER_INVALID"),
        ("missing_directory_type", "ZIP_DIRECTORY_MEMBER_INVALID"),
        ("nonzero", "ZIP_DIRECTORY_MEMBER_INVALID"),
        ("noncanonical", "MEMBER_PATH_INVALID"),
        ("traversal", "MEMBER_PATH_INVALID"),
        ("empty", "ZIP_DIRECTORY_UNRELATED"),
        ("unrelated", "ZIP_DIRECTORY_UNRELATED"),
        ("data", "WHEEL_DATA_LAYOUT_UNSUPPORTED"),
        ("file_directory", "ZIP_MEMBER_DUPLICATE_TARGET"),
        ("file_ancestor", "ZIP_FILE_DIRECTORY_COLLISION"),
        ("record_directory", "WHEEL_RECORD_SET_INVALID"),
        ("record_missing_file", "WHEEL_RECORD_SET_INVALID"),
        ("record_wrong_file_hash", "WHEEL_RECORD_HASH_MISMATCH"),
    ],
)
def test_directory_compatibility_does_not_relax_paths_types_or_record_closure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fault: str, code: str
) -> None:
    staged = staged_runtime(tmp_path, monkeypatch)
    members = _numpy_archive_members(staged)
    record_name = "numpy-2.4.6.dist-info/RECORD"
    entry, raw = _directory_entry("numpy/"), b""
    if fault == "symlink":
        entry = _directory_entry("numpy/", stat.S_IFLNK | 0o777)
    elif fault == "regular_mode":
        entry = _directory_entry("numpy/", stat.S_IFREG | 0o644)
    elif fault == "missing_directory_type":
        entry = _directory_entry("numpy/", 0o755)
    elif fault == "nonzero":
        raw = b"not a zero-byte directory"
    elif fault == "noncanonical":
        entry = _directory_entry("numpy//")
    elif fault == "traversal":
        entry = _directory_entry("numpy/../")
    elif fault == "empty":
        entry = _directory_entry("numpy/empty/")
    elif fault == "unrelated":
        entry = _directory_entry("unrelated/")
    elif fault == "data":
        entry = _directory_entry("numpy-2.4.6.data/")
    elif fault in {"file_directory", "file_ancestor"}:
        members["numpy"] = b"a file cannot also be a directory or ancestor"
    elif fault == "record_directory":
        members[record_name] += b"numpy/,,\n"
    elif fault == "record_missing_file":
        members[record_name] = b"".join(
            row
            for row in members[record_name].splitlines(keepends=True)
            if not row.startswith(b"numpy/__init__.py,")
        )
    elif fault == "record_wrong_file_hash":
        hashed = {name: raw for name, raw in members.items() if name != record_name}
        hashed["numpy/__init__.py"] = b"not the archive bytes"
        members[record_name] = synthetic_record(hashed, record_name)
    entries = ((entry, raw),) * (2 if fault == "duplicate" else 1)
    if fault == "file_ancestor":
        entries = ()
    with pytest.warns(UserWarning) if fault == "duplicate" else nullcontext():
        payload = _wheel_with_directories(members, entries)
    library = _repacked_numpy_library(staged, payload)
    with pytest.raises(InstalledRuntimeProofError, match=code):
        verify_installed_numeric_distribution(
            library,
            prefix=staged.prefix,
            archive_root=staged.archive_root,
            files=NumericalRuntimeFileSnapshots(os.geteuid()),
        )


@pytest.mark.parametrize(
    "fault",
    [
        "path",
        "duplicate",
        "link",
        "encrypted",
        "central_count",
        "central_size",
        "zip_comment",
        "data_layout",
        "record_duplicate",
        "record_set",
        "record_hash",
        "bytecode",
        "tag",
        "metadata",
    ],
)
def test_direct_archive_parser_rejects_malformed_trusted_raw_pin(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fault: str,
) -> None:
    staged = staged_runtime(tmp_path, monkeypatch)
    original = staged.proof.numeric_libraries[0]
    raw = staged.archives["numpy"].read_bytes()
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        members = {info.filename: archive.read(info) for info in archive.infolist()}
    record_name = next(name for name in members if name.endswith("/RECORD"))
    if fault == "path":
        members["../escape.py"] = b"must not extract"
    elif fault == "data_layout":
        members["numpy-2.4.6.data/purelib/extra.py"] = b"unreviewed mapping"
    elif fault == "record_duplicate":
        members[record_name] += members[record_name].splitlines(keepends=True)[0]
    elif fault == "record_set":
        members[record_name] = b"missing,,\n"
    elif fault == "record_hash":
        members[record_name] = members[record_name].replace(b"sha256=", b"sha256=A", 1)
    elif fault == "bytecode":
        members["numpy/__pycache__/evil.pyc"] = b"unregistered executable bytes"
    elif fault == "tag":
        name = next(name for name in members if name.endswith("/WHEEL"))
        members[name] = members[name].replace(b"py3-none-any", b"cp311-cp311-linux_aarch64")
        members[record_name] = synthetic_record(
            {name: raw for name, raw in members.items() if name != record_name}, record_name
        )
    elif fault == "metadata":
        name = next(name for name in members if name.endswith("/METADATA"))
        members[name] = members[name].replace(b"numpy", b"other")
        members[record_name] = synthetic_record(
            {name: raw for name, raw in members.items() if name != record_name}, record_name
        )
    payload = synthetic_wheel(members)
    if fault in {"duplicate", "link", "zip_comment"}:
        stream = io.BytesIO(payload)
        with zipfile.ZipFile(stream, "a") as archive:
            if fault == "zip_comment":
                archive.comment = b"unsupported"
            else:
                info = zipfile.ZipInfo(
                    "numpy/__init__.py" if fault == "duplicate" else "numpy/link"
                )
                info.external_attr = (
                    (stat.S_IFREG if fault == "duplicate" else stat.S_IFLNK) | 0o644
                ) << 16
                with pytest.warns(UserWarning) if fault == "duplicate" else nullcontext():
                    archive.writestr(info, b"untrusted")
        payload = stream.getvalue()
    elif fault in {"encrypted", "central_count", "central_size"}:
        changed = bytearray(payload)
        if fault == "encrypted":
            index = changed.find(b"PK\x01\x02")
            struct.pack_into("<H", changed, index + 8, 1)
        elif fault == "central_count":
            struct.pack_into("<HH", changed, len(changed) - 14, 65535, 65535)
        else:
            struct.pack_into("<L", changed, len(changed) - 10, 16 * 1024**2 + 1)
        payload = bytes(changed)
    digest = sha256_bytes(payload)
    target = staged.archive_root / digest[7:] / original.archive.wheel_filename
    target.parent.mkdir(mode=0o700)
    target.write_bytes(payload)
    target.chmod(0o600)
    body = original.model_dump(mode="json")
    body["archive"].update(sha256=digest, size_bytes=len(payload))
    admitted_shape = InstalledNumericLibraryProof.model_validate(body)
    with pytest.raises(InstalledRuntimeProofError):
        verify_installed_numeric_distribution(
            admitted_shape,
            prefix=staged.prefix,
            archive_root=staged.archive_root,
            files=NumericalRuntimeFileSnapshots(os.geteuid()),
        )


def test_console_script_name_does_not_authorize_arbitrary_code_or_shebang(tmp_path: Path) -> None:
    prefix = tmp_path / "prefix"
    with pytest.raises(InstalledRuntimeProofError, match="CONSOLE_WRAPPER_INVALID"):
        validate_numeric_console_wrapper(b"#!/bin/sh\nmalicious\n", prefix, ("numpy.fake", "main"))
    legitimate = (
        f"#!{prefix / 'bin/python3.12'}\nimport sys\nfrom numpy.fake import main\n"
        "if __name__ == '__main__':\n    if sys.argv[0].endswith('.exe'):\n"
        "        sys.argv[0] = sys.argv[0][:-4]\n    sys.exit(main())\n"
    ).encode()
    validate_numeric_console_wrapper(legitimate, prefix, ("numpy.fake", "main"))
    with pytest.raises(InstalledRuntimeProofError, match="CONSOLE_WRAPPER_INVALID"):
        validate_numeric_console_wrapper(
            legitimate + b"import os\nos.system('bad')\n", prefix, ("numpy.fake", "main")
        )
