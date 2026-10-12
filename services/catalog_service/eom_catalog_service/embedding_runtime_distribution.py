"""Exact retained numerical wheel ↔ installed RECORD/member closure; no package execution."""

from __future__ import annotations

import ast
import base64
import configparser
import csv
import hashlib
import io
import itertools
import json
import os
import re
import stat
import struct
import zipfile
from dataclasses import dataclass
from email.parser import BytesParser
from pathlib import Path, PurePosixPath
from typing import Any

from eom_catalog_contracts.embedding_installed_runtime_proof import InstalledNumericLibraryProof
from eom_catalog_contracts.embedding_runtime_bundle import EmbeddingNumericLibraryPin
from eom_identifiers import sha256_bytes

from eom_catalog_service.embedding_runtime_files import (
    InstalledRuntimeProofError,
    NumericalRuntimeFileSnapshots,
)
from eom_catalog_service.embedding_runtime_files import (
    require_runtime_proof as _require,
)

_MAX_MEMBER = 2 * 1024**3
_MAX_RECORD = 8 * 1024**2
_MAX_METADATA = 128 * 1024
_MAX_CENTRAL = 16 * 1024**2


@dataclass(frozen=True, slots=True)
class VerifiedInstalledNumericDistribution:
    pin: EmbeddingNumericLibraryPin
    namespace_roots: frozenset[Path]
    installed_members: frozenset[Path]
    torch_version: tuple[str, str | None] | None


def _safe_member(name: str) -> None:
    _require(
        bool(name)
        and len(name.encode()) <= 512
        and not name.startswith("/")
        and "\\" not in name
        and all(ord(c) >= 32 for c in name)
        and all(part not in {"", ".", ".."} for part in name.split("/"))
        and PurePosixPath(name).as_posix() == name,
        "MEMBER_PATH_INVALID",
    )
    _require(
        "__pycache__" not in name.split("/") and not name.endswith((".pyc", ".pyo")),
        "BYTECODE_FORBIDDEN",
    )


def _bounded_zip_directory(descriptor: int, size: int) -> None:
    tail = os.pread(descriptor, min(size, 65557), max(0, size - 65557))
    index = tail.rfind(b"PK\x05\x06")
    _require(index >= 0 and index + 22 == len(tail), "ZIP_END_INVALID")
    end = struct.unpack("<4s4H2LH", tail[index : index + 22])
    _require(
        end[1] == end[2] == end[7] == 0
        and end[3] == end[4]
        and 0 < end[4] <= 20000
        and 0 < end[5] <= _MAX_CENTRAL
        and end[6] + end[5] == size - 22,
        "ZIP_DIRECTORY_INVALID",
    )
    central = os.pread(descriptor, end[5], end[6])
    _require(len(central) == end[5], "ZIP_DIRECTORY_INVALID")
    offset = 0
    for _ in range(end[4]):
        _require(
            offset + 46 <= len(central) and central[offset : offset + 4] == b"PK\x01\x02",
            "ZIP_DIRECTORY_INVALID",
        )
        lengths = struct.unpack_from("<3H", central, offset + 28)
        _require(
            0 < lengths[0] <= 512 and lengths[1] <= 4096 and lengths[2] == 0,
            "ZIP_DIRECTORY_INVALID",
        )
        offset += 46 + sum(lengths)
    _require(offset == len(central), "ZIP_DIRECTORY_INVALID")


def _zip_member(
    archive: zipfile.ZipFile, info: zipfile.ZipInfo, retain: bool
) -> tuple[str, int, bytes]:
    digest = hashlib.sha256()
    count = 0
    chunks: list[bytes] = []
    limit = (
        _MAX_RECORD
        if info.filename.endswith("/RECORD")
        else _MAX_METADATA
        if retain
        else _MAX_MEMBER
    )
    _require(info.file_size <= limit, "ZIP_MEMBER_TOO_LARGE")
    with archive.open(info) as stream:
        while chunk := stream.read(min(1024**2, limit + 1 - count)):
            count += len(chunk)
            _require(count <= limit, "ZIP_MEMBER_TOO_LARGE")
            digest.update(chunk)
            if retain:
                chunks.append(chunk)
    _require(count == info.file_size, "ZIP_MEMBER_SIZE_MISMATCH")
    return "sha256:" + digest.hexdigest(), count, b"".join(chunks)


def _record(raw: bytes) -> dict[str, tuple[str, int | None]]:
    _require(len(raw) <= _MAX_RECORD, "RECORD_TOO_LARGE")
    records: dict[str, tuple[str, int | None]] = {}
    for row in csv.reader(io.StringIO(raw.decode("utf-8"), newline=""), strict=True):
        _require(
            len(row) == 3 and row[0] not in records and len(records) < 20000, "RECORD_ROW_INVALID"
        )
        name, digest, size = row
        if not digest and not size:
            records[name] = "", None
        else:
            _require(
                re.fullmatch(r"sha256=[A-Za-z0-9_-]{43}", digest) is not None
                and re.fullmatch(r"0|[1-9][0-9]{0,19}", size) is not None,
                "RECORD_VALUE_INVALID",
            )
            decoded = base64.urlsafe_b64decode(digest[7:] + "=")
            _require(
                len(decoded) == 32
                and base64.urlsafe_b64encode(decoded).decode().rstrip("=") == digest[7:],
                "RECORD_VALUE_INVALID",
            )
            records[name] = "sha256:" + decoded.hex(), int(size)
    return records


def _installed_target(prefix: Path, name: str) -> Path:
    _require(
        bool(name)
        and len(name.encode()) <= 512
        and not name.startswith("/")
        and "\\" not in name
        and all(ord(c) >= 32 for c in name)
        and all(part not in {"", "."} for part in name.split("/")),
        "RECORD_PATH_INVALID",
    )
    site = prefix / "lib/python3.12/site-packages"
    path = Path(os.path.normpath(site / name))
    _require(
        path.is_relative_to(prefix)
        and path != prefix
        and "__pycache__" not in path.parts
        and not path.name.endswith((".pyc", ".pyo")),
        "RECORD_PATH_INVALID",
    )
    return path


class _ConsoleEntryMetadata(configparser.ConfigParser):
    def optionxform(self, optionstr: str) -> str:
        return optionstr


def _entries(raw: bytes) -> dict[str, tuple[str, str]]:
    parser = _ConsoleEntryMetadata(interpolation=None, strict=True)
    parser.read_string(raw.decode("utf-8"))
    _require(not parser.has_section("gui_scripts"), "GUI_SCRIPTS_FORBIDDEN")
    result: dict[str, tuple[str, str]] = {}
    for name, value in (
        parser.items("console_scripts") if parser.has_section("console_scripts") else ()
    ):
        match = re.fullmatch(
            r"([A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*):([A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*)", value
        )
        _require(
            re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,95}", name) is not None and match is not None,
            "ENTRY_POINT_INVALID",
        )
        assert match is not None
        result[name] = match[1], match[2]
    return result


def validate_numeric_console_wrapper(raw: bytes, prefix: Path, entry: tuple[str, str]) -> None:
    """Two fixed distlib wrapper recipes; no arbitrary AST statements or execution."""
    module, function = entry
    first = function.split(".", 1)[0]
    head = f"#!{prefix / 'bin/python3.12'}\n"
    legacy = (
        head
        + "# -*- coding: utf-8 -*-\nimport re\nimport sys\n"
        + f"from {module} import {first}\n"
        + "if __name__ == '__main__':\n"
        + "    sys.argv[0] = re.sub(r'(-script\\.pyw?|\\.exe)?$', '', sys.argv[0])\n"
        + f"    sys.exit({function}())\n"
    )
    modern = (
        head
        + "import sys\n"
        + f"from {module} import {first}\n"
        + "if __name__ == '__main__':\n    if sys.argv[0].endswith('.exe'):\n"
        + "        sys.argv[0] = sys.argv[0][:-4]\n"
        + f"    sys.exit({function}())\n"
    )
    _require(raw in (legacy.encode(), modern.encode()), "CONSOLE_WRAPPER_INVALID")


def _unique_json(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        _require(key not in result, "JSON_DUPLICATE_KEY")
        result[key] = value
    return result


def _torch_constants(raw: bytes) -> tuple[str, str | None]:
    values: dict[str, str | None] = {}
    for node in ast.parse(raw.decode("utf-8")).body:
        value: ast.expr | None
        if (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
        ):
            name, value = node.targets[0].id, node.value
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            name, value = node.target.id, node.value
        else:
            continue
        if name in {"__version__", "cuda"}:
            _require(
                name not in values
                and isinstance(value, ast.Constant)
                and (value.value is None or isinstance(value.value, str)),
                "TORCH_BUILD_INVALID",
            )
            assert isinstance(value, ast.Constant)
            constant = value.value
            assert constant is None or isinstance(constant, str)
            values[name] = constant
    _require(
        set(values) == {"__version__", "cuda"} and isinstance(values["__version__"], str),
        "TORCH_BUILD_INVALID",
    )
    version = values["__version__"]
    assert isinstance(version, str)
    return version, values["cuda"]


def _expanded_wheel_tags(values: tuple[str, ...]) -> set[str]:
    """PEP 425 compressed triples, bounded before either Cartesian expansion."""
    _require(0 < len(values) <= 64, "WHEEL_TAG_LIMIT_EXCEEDED")
    prepared: list[tuple[tuple[str, ...], ...]] = []
    seen_raw: set[str] = set()
    aggregate = 0
    for value in values:
        _require(isinstance(value, str) and 0 < len(value) <= 255, "WHEEL_TAG_LIMIT_EXCEEDED")
        _require(value not in seen_raw, "WHEEL_TAG_DUPLICATE")
        seen_raw.add(value)
        parts = value.split("-")
        _require(len(parts) == 3, "WHEEL_TAG_INVALID")
        dimensions = tuple(tuple(part.split(".")) for part in parts)
        product_size = 1
        for dimension in dimensions:
            _require(0 < len(dimension) <= 16, "WHEEL_TAG_LIMIT_EXCEEDED")
            _require(
                all(re.fullmatch(r"[a-z0-9_]{1,64}", atom) is not None for atom in dimension),
                "WHEEL_TAG_INVALID",
            )
            _require(len(dimension) == len(set(dimension)), "WHEEL_TAG_DUPLICATE")
            product_size *= len(dimension)
        aggregate += product_size
        _require(aggregate <= 128, "WHEEL_TAG_LIMIT_EXCEEDED")
        prepared.append(dimensions)
    result: set[str] = set()
    for dimensions in prepared:
        expanded = {"-".join(tag) for tag in itertools.product(*dimensions)}
        _require(result.isdisjoint(expanded), "WHEEL_TAG_DUPLICATE")
        result.update(expanded)
    return result


def _validate_wheel_identity(
    library: InstalledNumericLibraryProof, dist_info: str, metadata: Any
) -> None:
    parts = library.archive.wheel_filename[:-4].split("-")
    _require(
        len(parts) == 5
        and parts[0] == library.name.replace("-", "_")
        and parts[1] == library.version
        and dist_info == f"{parts[0]}-{parts[1]}.dist-info",
        "WHEEL_FILENAME_IDENTITY_INVALID",
    )
    tags = _expanded_wheel_tags(("-".join(parts[2:]),))
    _require(
        _expanded_wheel_tags(tuple(metadata.get_all("Tag", []))) == tags,
        "WHEEL_TAG_IDENTITY_INVALID",
    )
    compatible = False
    for tag in tags:
        python, abi, platform_tag = tag.split("-")
        platform_ok = platform_tag == "any" or (
            platform_tag.endswith("_x86_64") and platform_tag.startswith(("manylinux", "linux"))
        )
        python_ok = (python in {"py3", "py312", "cp312"} and abi in {"none", "cp312"}) or (
            re.fullmatch(r"cp3[0-9]{1,2}", python) is not None
            and int(python[2:]) <= 312
            and abi == "abi3"
        )
        compatible |= platform_ok and python_ok
    _require(compatible, "WHEEL_TARGET_UNSUPPORTED")


def _verify_installed_numeric_distribution(
    library: InstalledNumericLibraryProof,
    *,
    prefix: Path,
    archive_root: Path,
    files: NumericalRuntimeFileSnapshots,
) -> VerifiedInstalledNumericDistribution:
    archive_path = archive_root / library.archive.sha256[7:] / library.archive.wheel_filename
    site = prefix / "lib/python3.12/site-packages"
    with files.verified_open(
        archive_path,
        sha256=library.archive.sha256,
        size=library.archive.size_bytes,
        maximum=2 * 1024**3,
    ) as (descriptor, _raw):
        _bounded_zip_directory(descriptor, library.archive.size_bytes)
        with os.fdopen(os.dup(descriptor), "rb") as stream, zipfile.ZipFile(stream) as archive:
            infos = archive.infolist()
            names: dict[str, zipfile.ZipInfo] = {}
            member_targets: set[str] = set()
            pending_directories: set[str] = set()
            expanded = 0
            for info in infos:
                directory = info.is_dir()
                target_name = info.filename[:-1] if directory else info.filename
                _safe_member(target_name)
                _require(target_name not in member_targets, "ZIP_MEMBER_DUPLICATE_TARGET")
                member_targets.add(target_name)
                mode = info.external_attr >> 16
                _require(
                    not info.flag_bits & 1
                    and info.compress_type in {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED}
                    and info.file_size <= _MAX_MEMBER
                    and info.file_size <= max(1, info.compress_size) * 100,
                    "ZIP_MEMBER_INVALID",
                )
                _require(
                    not any(part.endswith(".data") for part in target_name.split("/")),
                    "WHEEL_DATA_LAYOUT_UNSUPPORTED",
                )
                expanded += info.file_size
                _require(expanded <= 4 * 1024**3, "ZIP_EXPANDED_TOO_LARGE")
                if directory:
                    _require(
                        info.orig_filename == info.filename
                        and stat.S_ISDIR(mode)
                        and info.file_size == 0
                        and info.CRC == 0,
                        "ZIP_DIRECTORY_MEMBER_INVALID",
                    )
                    pending_directories.add(target_name)
                else:
                    _require(not mode or stat.S_ISREG(mode), "ZIP_MEMBER_INVALID")
                    names[info.filename] = info
            for name in names:
                parent = name.rpartition("/")[0]
                while parent:
                    _require(parent not in names, "ZIP_FILE_DIRECTORY_COLLISION")
                    pending_directories.discard(parent)
                    parent = parent.rpartition("/")[0]
            _require(not pending_directories, "ZIP_DIRECTORY_UNRELATED")
            metadata_names = [name for name in names if name.endswith(".dist-info/METADATA")]
            _require(len(metadata_names) == 1, "METADATA_IDENTITY_INVALID")
            dist_info = metadata_names[0].rsplit("/", 1)[0]
            _require(
                {name.split("/", 1)[0] for name in names if ".dist-info/" in name} == {dist_info},
                "METADATA_IDENTITY_INVALID",
            )
            record_name = dist_info + "/RECORD"
            _require(record_name in names and dist_info + "/WHEEL" in names, "WHEEL_RECORD_MISSING")
            _sha, _count, record_raw = _zip_member(archive, names[record_name], True)
            records = _record(record_raw)
            _require(
                set(records) == set(names) and records[record_name] == ("", None),
                "WHEEL_RECORD_SET_INVALID",
            )
            wheel_pins: dict[Path, tuple[str, int]] = {}
            roots: set[Path] = set()
            metadata: dict[str, bytes] = {}
            torch_version = None
            for name, info in names.items():
                if name == record_name:
                    continue
                retain = name in {
                    metadata_names[0],
                    dist_info + "/WHEEL",
                    dist_info + "/entry_points.txt",
                    "torch/version.py",
                }
                sha, size, raw = _zip_member(archive, info, retain)
                _require(records[name] == (sha, size), "WHEEL_RECORD_HASH_MISMATCH")
                target = site / name
                wheel_pins[target] = sha, size
                roots.add(site / name.split("/", 1)[0])
                if name == "torch/version.py":
                    actual = files.read(target, sha256=sha, size=size, maximum=_MAX_METADATA)
                    torch_version = _torch_constants(actual)
                else:
                    files.verify(target, sha256=sha, size=size, maximum=_MAX_MEMBER)
                if retain:
                    metadata[name] = raw
            parsed = BytesParser().parsebytes(metadata[metadata_names[0]])
            _require(
                parsed.get_all("Name", []) == [library.name]
                or (
                    len(parsed.get_all("Name", [])) == 1
                    and re.sub(r"[-_.]+", "-", parsed["Name"]).lower() == library.name
                ),
                "DISTRIBUTION_NAME_MISMATCH",
            )
            _require(
                parsed.get_all("Version", []) == [library.version], "DISTRIBUTION_VERSION_MISMATCH"
            )
            wheel_metadata = BytesParser().parsebytes(metadata[dist_info + "/WHEEL"])
            wheel_tags = wheel_metadata.get_all("Tag") or []
            _require(
                wheel_metadata.get_all("Wheel-Version", []) == ["1.0"] and bool(wheel_tags),
                "WHEEL_METADATA_INVALID",
            )
            _validate_wheel_identity(library, dist_info, wheel_metadata)
            entries = _entries(metadata.get(dist_info + "/entry_points.txt", b""))
            _require(
                tuple(sorted(entries)) == tuple(script.name for script in library.console_scripts),
                "CONSOLE_SCRIPT_SET_MISMATCH",
            )
            additions: dict[Path, tuple[str, int]] = {
                site / dist_info / "INSTALLER": (sha256_bytes(b"pip\n"), 4)
            }
            if library.requested:
                additions[site / dist_info / "REQUESTED"] = sha256_bytes(b""), 0
            if library.direct_url is not None:
                additions[site / dist_info / "direct_url.json"] = (
                    library.direct_url.sha256,
                    library.direct_url.size_bytes,
                )
            for script in library.console_scripts:
                additions[prefix / "bin" / script.name] = script.sha256, script.size_bytes
            installed_record = site / record_name
            raw = files.read(
                installed_record,
                sha256=library.installed_record.sha256,
                size=library.installed_record.size_bytes,
                maximum=_MAX_RECORD,
            )
            installed: dict[Path, tuple[str, int | None]] = {}
            for name, value in _record(raw).items():
                target = _installed_target(prefix, name)
                _require(target not in installed, "INSTALLED_RECORD_DUPLICATE_TARGET")
                installed[target] = value
            expected = wheel_pins | additions
            _require(
                set(installed) == set(expected) | {installed_record}
                and installed[installed_record] == ("", None),
                "INSTALLED_RECORD_SET_MISMATCH",
            )
            for target, value in expected.items():
                _require(installed[target] == value, "INSTALLED_RECORD_VALUE_MISMATCH")
            for target, (sha, size) in additions.items():
                if target.name == "direct_url.json":
                    value = json.loads(
                        files.read(target, sha256=sha, size=size, maximum=_MAX_METADATA),
                        object_pairs_hook=_unique_json,
                    )
                    digest = library.archive.sha256[7:]
                    _require(
                        value
                        in (
                            {
                                "url": archive_path.as_uri(),
                                "archive_info": {
                                    "hash": "sha256=" + digest,
                                    "hashes": {"sha256": digest},
                                },
                            },
                            {
                                "url": archive_path.as_uri(),
                                "archive_info": {"hashes": {"sha256": digest}},
                            },
                        ),
                        "DIRECT_URL_INVALID",
                    )
                elif target.parent == prefix / "bin":
                    wrapper = files.read(target, sha256=sha, size=size, maximum=16 * 1024)
                    validate_numeric_console_wrapper(wrapper, prefix, entries[target.name])
                else:
                    files.verify(target, sha256=sha, size=size, maximum=_MAX_METADATA)
            return VerifiedInstalledNumericDistribution(
                EmbeddingNumericLibraryPin(
                    name=library.name,
                    version=library.version,
                    distribution_sha256=library.archive.sha256,
                ),
                frozenset(roots),
                frozenset(
                    target
                    for target in set(expected) | {installed_record}
                    if target.is_relative_to(site)
                ),
                torch_version,
            )


def verify_installed_numeric_distribution(
    library: InstalledNumericLibraryProof,
    *,
    prefix: Path,
    archive_root: Path,
    files: NumericalRuntimeFileSnapshots,
) -> VerifiedInstalledNumericDistribution:
    """One closed external-input boundary; parser diagnostics never leave as error labels."""
    try:
        return _verify_installed_numeric_distribution(
            library, prefix=prefix, archive_root=archive_root, files=files
        )
    except InstalledRuntimeProofError:
        raise
    except Exception as exc:
        raise InstalledRuntimeProofError("INSTALLED_RUNTIME_DISTRIBUTION_INVALID") from exc
