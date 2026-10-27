"""Closed, removable operator adapter; no worker/HTTP/queue or arbitrary commands.

The independently checked shell admits the interpreter before importing this file.
Root-only immutable staging is a trust boundary, not caller-supplied permission.
"""

from __future__ import annotations

import hashlib
import json
import os
import runpy
import stat
import subprocess
import sys
import tarfile
import zipfile
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from types import MappingProxyType
from typing import Any

from jsonschema import Draft202012Validator

MAX_CONTEXT_BYTES = 32 * 1024
MIGRATION_REVISION = "20261010_0051"
MIGRATION_REVISION_0052 = "20261012_0052"
MIGRATION_REVISION_0053 = "20261012_0053"
MIGRATION_REVISION_0054 = "20261013_0054"
MIGRATION_REVISION_0055 = "20261014_0055"
MIGRATION_REVISION_0056 = "20261017_0056"
MIGRATION_REVISION_0057 = "20261017_0057"
MIGRATION_REVISION_0058 = "20261019_0058"
MIGRATION_REVISION_0059 = "20261026_0059"
MIGRATION_REVISION_0060 = "20261027_0060"
POSTGRES_ENV = "/etc/eom/secrets/postgres.env"
API_PREFIX = Path("/srv/eom/conda/envs/eom-api")
API_NATIVE_MEMBER = Path("lib/python3.12/site-packages/pymupdf/_extra.so")
_CLEAN_ENV = {"PATH": "/usr/sbin:/usr/bin:/sbin:/bin", "TZ": "UTC", "LANG": "C.UTF-8"}
_CLEAN_ENV.update(
    PYTHONSAFEPATH="1",
    PYTHONNOUSERSITE="1",
    PYTHONDONTWRITEBYTECODE="1",
    PGCONNECT_TIMEOUT="15",
    PGOPTIONS="-c lock_timeout=5000 -c statement_timeout=120000",
)
_SCHEMA_SHA256 = "sha256:5a60d4ec278f4d1200abfff99525cea4654bdbbcba0f86e801de669637e33c8a"
_SCHEMA_V1_1_SHA256 = "sha256:3fbe06b5c74a74f46f98fb14813c48d1ede8e95be786061510eb0956ddce5eba"
_SCHEMA_V1_2_SHA256 = "sha256:53de686b2042795a2b53c9073a12f9a7746709825c1b95a8e5d39ff2618a4398"
_SCHEMA_V1_3_SHA256 = "sha256:72b64319f143b4937db222c039a858edc802e6f713079bb888b7b6ef1b4b449d"
_SCHEMA_V1_4_SHA256 = "sha256:af03ddeccb0cab48f60341121c987e05733e18aba1986c06408d835953eacb79"
_SCHEMA_V1_5_SHA256 = "sha256:7638d38a5d951aadde9d14c1d5b0eea1128f54b42fac72e94583d401633daccf"
_SCHEMA_V1_6_SHA256 = "sha256:0eab84c5f1e7a374a437fbccea372158b40ec822e745719d385506a95025c2f4"
_SCHEMA_V1_7_SHA256 = "sha256:6cbf0efad7da8d81da7e3e9cc5453e67611a0188d246ec0a8b8c2d42b3207250"
_SCHEMA_V1_8_SHA256 = "sha256:4de834abbbb627ef70f59b2a62ae91d86c7091a1c7385c0d72d7cab7a4c31dcf"
_SCHEMA_V1_9_SHA256 = "sha256:4feb20407cf016126ec06b6f2333084facca6ef8b17fbdd18969ef2b06c9f543"
ERROR_CODES = frozenset(
    {
        "RELEASE_OPERATOR_ROOT_REQUIRED",
        "RELEASE_OPERATOR_PATH_INVALID",
        "RELEASE_OPERATOR_FILE_INVALID",
        "RELEASE_OPERATOR_FILE_CHANGED",
        "RELEASE_OPERATOR_JSON_INVALID",
        "RELEASE_OPERATOR_SCHEMA_CHANGED",
        "RELEASE_OPERATOR_CONTEXT_INVALID",
        "RELEASE_OPERATOR_CONTEXT_CHANGED",
        "RELEASE_OPERATOR_SOURCE_MISMATCH",
        "RELEASE_OPERATOR_WHEEL_INVALID",
        "RELEASE_OPERATOR_STAGE_INVALID",
        "RELEASE_OPERATOR_WHEEL_CHANGED",
        "RELEASE_OPERATOR_INSTALLED_PAYLOAD_CHANGED",
        "RELEASE_OPERATOR_RUNTIME_INVALID",
        "RELEASE_OPERATOR_SOURCE_CHANGED",
        "RELEASE_OPERATOR_SOURCE_ARCHIVE_INVALID",
        "RELEASE_OPERATOR_RECEIPT_WRITE_FAILED",
        "RELEASE_OPERATOR_ADMISSION_CHANGED",
        "RELEASE_OPERATOR_BUILD_MISMATCH",
        "RELEASE_OPERATOR_REVISION_UNSUPPORTED",
        "RELEASE_OPERATOR_DATABASE_OWNER_INVALID",
        "RELEASE_OPERATOR_MIGRATION_HEAD_MISMATCH",
        "RELEASE_OPERATOR_CALLBACK_FAILED",
        "RELEASE_OPERATOR_PDF_RUNTIME_INVALID",
        "RELEASE_OPERATOR_CALLBACK_INVALID",
        "RELEASE_OPERATOR_ARGUMENTS_INVALID",
        "RELEASE_OPERATOR_RUNTIME_MISMATCH",
        "RELEASE_OPERATOR_TIMEOUT_STATE_UNKNOWN",
        "RELEASE_OPERATOR_POSTGRES_ENVIRONMENT_INVALID",
        "RELEASE_OPERATOR_API_ISOLATION_INVALID",
    }
)


class OperatorRuntimeError(ValueError):
    """Stable redacted operator error; never carry source/credential output."""


class Callback(StrEnum):
    MIGRATION_VERIFY = "MIGRATION_VERIFY"
    MIGRATION_UPGRADE_0051 = "MIGRATION_UPGRADE_0051"
    MIGRATION_VERIFY_0052 = "MIGRATION_VERIFY_0052"
    MIGRATION_UPGRADE_0052 = "MIGRATION_UPGRADE_0052"
    MIGRATION_VERIFY_0053 = "MIGRATION_VERIFY_0053"
    MIGRATION_UPGRADE_0053 = "MIGRATION_UPGRADE_0053"
    MIGRATION_VERIFY_0054 = "MIGRATION_VERIFY_0054"
    MIGRATION_UPGRADE_0054 = "MIGRATION_UPGRADE_0054"
    MIGRATION_VERIFY_0055 = "MIGRATION_VERIFY_0055"
    MIGRATION_UPGRADE_0055 = "MIGRATION_UPGRADE_0055"
    MIGRATION_VERIFY_0056 = "MIGRATION_VERIFY_0056"
    MIGRATION_UPGRADE_0056 = "MIGRATION_UPGRADE_0056"
    MIGRATION_VERIFY_0057 = "MIGRATION_VERIFY_0057"
    MIGRATION_UPGRADE_0057 = "MIGRATION_UPGRADE_0057"
    MIGRATION_VERIFY_0058 = "MIGRATION_VERIFY_0058"
    MIGRATION_UPGRADE_0058 = "MIGRATION_UPGRADE_0058"
    MIGRATION_VERIFY_0059 = "MIGRATION_VERIFY_0059"
    MIGRATION_UPGRADE_0059 = "MIGRATION_UPGRADE_0059"
    MIGRATION_VERIFY_0060 = "MIGRATION_VERIFY_0060"
    MIGRATION_UPGRADE_0060 = "MIGRATION_UPGRADE_0060"
    API_ROLE_BOOTSTRAP = "API_ROLE_BOOTSTRAP"
    CATALOG_ROLE_RECONCILE = "CATALOG_ROLE_RECONCILE"
    HWPX_ROLE_RECONCILE = "HWPX_ROLE_RECONCILE"
    PDF_RUNTIME_VERIFY = "PDF_RUNTIME_VERIFY"
    API_ISOLATION_VERIFY = "API_ISOLATION_VERIFY"


_MIGRATION_CALLBACKS = MappingProxyType(
    {
        Callback.MIGRATION_VERIFY: (MIGRATION_REVISION, None),
        Callback.MIGRATION_UPGRADE_0051: (MIGRATION_REVISION, "20261009_0050"),
        Callback.MIGRATION_VERIFY_0052: (MIGRATION_REVISION_0052, None),
        Callback.MIGRATION_UPGRADE_0052: (MIGRATION_REVISION_0052, MIGRATION_REVISION),
        Callback.MIGRATION_VERIFY_0053: (MIGRATION_REVISION_0053, None),
        Callback.MIGRATION_UPGRADE_0053: (MIGRATION_REVISION_0053, MIGRATION_REVISION_0052),
        Callback.MIGRATION_VERIFY_0054: (MIGRATION_REVISION_0054, None),
        Callback.MIGRATION_UPGRADE_0054: (MIGRATION_REVISION_0054, MIGRATION_REVISION_0053),
        Callback.MIGRATION_VERIFY_0055: (MIGRATION_REVISION_0055, None),
        Callback.MIGRATION_UPGRADE_0055: (MIGRATION_REVISION_0055, MIGRATION_REVISION_0054),
        Callback.MIGRATION_VERIFY_0056: (MIGRATION_REVISION_0056, None),
        Callback.MIGRATION_UPGRADE_0056: (MIGRATION_REVISION_0056, MIGRATION_REVISION_0055),
        Callback.MIGRATION_VERIFY_0057: (MIGRATION_REVISION_0057, None),
        Callback.MIGRATION_UPGRADE_0057: (MIGRATION_REVISION_0057, MIGRATION_REVISION_0056),
        Callback.MIGRATION_VERIFY_0058: (MIGRATION_REVISION_0058, None),
        Callback.MIGRATION_UPGRADE_0058: (MIGRATION_REVISION_0058, MIGRATION_REVISION_0057),
        Callback.MIGRATION_VERIFY_0059: (MIGRATION_REVISION_0059, None),
        Callback.MIGRATION_UPGRADE_0059: (MIGRATION_REVISION_0059, MIGRATION_REVISION_0058),
        Callback.MIGRATION_VERIFY_0060: (MIGRATION_REVISION_0060, None),
        Callback.MIGRATION_UPGRADE_0060: (MIGRATION_REVISION_0060, MIGRATION_REVISION_0059),
    }
)


@dataclass(frozen=True)
class WheelPin:
    name: str
    sha256: str


@dataclass(frozen=True)
class OperatorContext:
    source_commit: str
    source_tree: str
    source_archive_sha256: str
    source_snapshot_sha256: str
    runtime_prefix: Path
    runtime_tree_sha256: str
    wheels: tuple[WheelPin, WheelPin, WheelPin]
    schema_version: str = "release-operator-context/1.0"
    migration_revision: str = MIGRATION_REVISION


def require_root() -> None:
    if os.geteuid() != 0:
        raise OperatorRuntimeError("RELEASE_OPERATOR_ROOT_REQUIRED")


def identity(value: os.stat_result) -> tuple[int, ...]:
    return (
        value.st_dev,
        value.st_ino,
        value.st_mode,
        value.st_uid,
        value.st_gid,
        value.st_nlink,
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
    )


def protected_path(path: Path) -> None:
    if not path.is_absolute() or ".." in path.parts or path == Path("/"):
        raise OperatorRuntimeError("RELEASE_OPERATOR_PATH_INVALID")
    for member in (path, *path.parents):
        try:
            value = member.lstat()
        except OSError as exc:
            raise OperatorRuntimeError("RELEASE_OPERATOR_PATH_INVALID") from exc
        if stat.S_ISLNK(value.st_mode) or value.st_uid != 0 or value.st_mode & 0o022:
            raise OperatorRuntimeError("RELEASE_OPERATOR_PATH_INVALID")


def read_protected(path: Path, *, maximum: int, allow_empty: bool = False) -> bytes:
    protected_path(path)
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
    except OSError as exc:
        raise OperatorRuntimeError("RELEASE_OPERATOR_FILE_INVALID") from exc
    try:
        before = os.fstat(descriptor)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_nlink != 1
            or not (0 if allow_empty else 1) <= before.st_size <= maximum
        ):
            raise OperatorRuntimeError("RELEASE_OPERATOR_FILE_INVALID")
        raw = os.read(descriptor, before.st_size + 1)
        if (
            len(raw) != before.st_size
            or identity(before) != identity(os.fstat(descriptor))
            or identity(before) != identity(path.lstat())
        ):
            raise OperatorRuntimeError("RELEASE_OPERATOR_FILE_CHANGED")
        return raw
    finally:
        os.close(descriptor)


def _unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    output: dict[str, Any] = {}
    for key, value in pairs:
        if key in output:
            raise OperatorRuntimeError("RELEASE_OPERATOR_JSON_INVALID")
        output[key] = value
    return output


def _invalid_constant(_value: str) -> Any:
    raise OperatorRuntimeError("RELEASE_OPERATOR_JSON_INVALID")


def _json(raw: bytes) -> dict[str, Any]:
    try:
        value = json.loads(raw, object_pairs_hook=_unique, parse_constant=_invalid_constant)
    except (ValueError, UnicodeError) as exc:
        raise OperatorRuntimeError("RELEASE_OPERATOR_JSON_INVALID") from exc
    if not isinstance(value, dict):
        raise OperatorRuntimeError("RELEASE_OPERATOR_JSON_INVALID")
    version = value.get("schema_version")
    if version in ("release-operator-context/1.0", "release-operator-admission/1.0"):
        schema_name, expected_schema_sha = "release_operator_context.schema.json", _SCHEMA_SHA256
    elif version in ("release-operator-context/1.1", "release-operator-admission/1.1"):
        schema_name, expected_schema_sha = (
            "release_operator_context_v1_1.schema.json",
            _SCHEMA_V1_1_SHA256,
        )
    elif version in ("release-operator-context/1.2", "release-operator-admission/1.2"):
        schema_name, expected_schema_sha = (
            "release_operator_context_v1_2.schema.json",
            _SCHEMA_V1_2_SHA256,
        )
    elif version in ("release-operator-context/1.3", "release-operator-admission/1.3"):
        schema_name, expected_schema_sha = (
            "release_operator_context_v1_3.schema.json",
            _SCHEMA_V1_3_SHA256,
        )
    elif version in ("release-operator-context/1.4", "release-operator-admission/1.4"):
        schema_name, expected_schema_sha = (
            "release_operator_context_v1_4.schema.json",
            _SCHEMA_V1_4_SHA256,
        )
    elif version in ("release-operator-context/1.5", "release-operator-admission/1.5"):
        schema_name, expected_schema_sha = (
            "release_operator_context_v1_5.schema.json",
            _SCHEMA_V1_5_SHA256,
        )
    elif version in ("release-operator-context/1.6", "release-operator-admission/1.6"):
        schema_name, expected_schema_sha = (
            "release_operator_context_v1_6.schema.json",
            _SCHEMA_V1_6_SHA256,
        )
    elif version in ("release-operator-context/1.7", "release-operator-admission/1.7"):
        schema_name, expected_schema_sha = (
            "release_operator_context_v1_7.schema.json",
            _SCHEMA_V1_7_SHA256,
        )
    elif version in ("release-operator-context/1.8", "release-operator-admission/1.8"):
        schema_name, expected_schema_sha = (
            "release_operator_context_v1_8.schema.json",
            _SCHEMA_V1_8_SHA256,
        )
    elif version in ("release-operator-context/1.9", "release-operator-admission/1.9"):
        schema_name, expected_schema_sha = (
            "release_operator_context_v1_9.schema.json",
            _SCHEMA_V1_9_SHA256,
        )
    else:
        raise OperatorRuntimeError("RELEASE_OPERATOR_JSON_INVALID")
    schema_bytes = read_protected(Path(__file__).with_name(schema_name), maximum=16 * 1024)
    if _sha(schema_bytes) != expected_schema_sha:
        raise OperatorRuntimeError("RELEASE_OPERATOR_SCHEMA_CHANGED")
    schema = json.loads(schema_bytes)
    validator = Draft202012Validator(schema)
    if not validator.is_valid(value):
        raise OperatorRuntimeError("RELEASE_OPERATOR_JSON_INVALID")
    return value


def _sha(raw: bytes) -> str:
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def load_context(path: Path, expected_sha256: str, expected_commit: str) -> OperatorContext:
    if path.name != "operator-context.json":
        raise OperatorRuntimeError("RELEASE_OPERATOR_CONTEXT_INVALID")
    raw = read_protected(path, maximum=MAX_CONTEXT_BYTES)
    if _sha(raw) != expected_sha256:
        raise OperatorRuntimeError("RELEASE_OPERATOR_CONTEXT_CHANGED")
    value = _json(raw)
    if (
        value["schema_version"]
        not in (
            "release-operator-context/1.0",
            "release-operator-context/1.1",
            "release-operator-context/1.2",
            "release-operator-context/1.3",
            "release-operator-context/1.4",
            "release-operator-context/1.5",
            "release-operator-context/1.6",
            "release-operator-context/1.7",
            "release-operator-context/1.8",
            "release-operator-context/1.9",
        )
        or value["source_commit"] != expected_commit
    ):
        raise OperatorRuntimeError("RELEASE_OPERATOR_SOURCE_MISMATCH")
    prefix = Path(value["runtime_prefix"])
    if str(prefix) != value["runtime_prefix"] or ".." in prefix.parts:
        raise OperatorRuntimeError("RELEASE_OPERATOR_PATH_INVALID")
    wheels = tuple(WheelPin(**value["wheels"][key]) for key in ("platform", "api_contracts", "api"))
    expected_names = ("eom_platform-", "eom_api_contracts-", "eom_application_api-")
    if any(
        not pin.name.startswith(prefix) for pin, prefix in zip(wheels, expected_names, strict=True)
    ):
        raise OperatorRuntimeError("RELEASE_OPERATOR_WHEEL_INVALID")
    return OperatorContext(
        source_commit=value["source_commit"],
        source_tree=value["source_tree"],
        source_archive_sha256=value["source_archive_sha256"],
        source_snapshot_sha256=value["source_snapshot_sha256"],
        runtime_prefix=Path(value["runtime_prefix"]),
        runtime_tree_sha256=value["runtime_tree_sha256"],
        wheels=(wheels[0], wheels[1], wheels[2]),
        schema_version=value["schema_version"],
        migration_revision=(
            MIGRATION_REVISION
            if value["schema_version"] == "release-operator-context/1.0"
            else value["migration_revision"]
        ),
    )


def _context_migration_revision(context: OperatorContext) -> str:
    if (context.schema_version, context.migration_revision) == (
        "release-operator-context/1.0",
        MIGRATION_REVISION,
    ):
        return MIGRATION_REVISION
    if (context.schema_version, context.migration_revision) == (
        "release-operator-context/1.1",
        MIGRATION_REVISION_0052,
    ):
        return MIGRATION_REVISION_0052
    if (context.schema_version, context.migration_revision) == (
        "release-operator-context/1.2",
        MIGRATION_REVISION_0053,
    ):
        return MIGRATION_REVISION_0053
    if (context.schema_version, context.migration_revision) == (
        "release-operator-context/1.3",
        MIGRATION_REVISION_0054,
    ):
        return MIGRATION_REVISION_0054
    if (context.schema_version, context.migration_revision) == (
        "release-operator-context/1.4",
        MIGRATION_REVISION_0055,
    ):
        return MIGRATION_REVISION_0055
    if (context.schema_version, context.migration_revision) == (
        "release-operator-context/1.5",
        MIGRATION_REVISION_0056,
    ):
        return MIGRATION_REVISION_0056
    if (context.schema_version, context.migration_revision) == (
        "release-operator-context/1.6",
        MIGRATION_REVISION_0057,
    ):
        return MIGRATION_REVISION_0057
    if (context.schema_version, context.migration_revision) == (
        "release-operator-context/1.7",
        MIGRATION_REVISION_0058,
    ):
        return MIGRATION_REVISION_0058
    if (context.schema_version, context.migration_revision) == (
        "release-operator-context/1.8",
        MIGRATION_REVISION_0059,
    ):
        return MIGRATION_REVISION_0059
    if (context.schema_version, context.migration_revision) == (
        "release-operator-context/1.9",
        MIGRATION_REVISION_0060,
    ):
        return MIGRATION_REVISION_0060
    raise OperatorRuntimeError("RELEASE_OPERATOR_CONTEXT_INVALID")


def _admission_document(
    path: Path, context: OperatorContext, context_sha256: str
) -> dict[str, Any]:
    revision = _context_migration_revision(context)
    document = {
        "schema_version": "release-operator-admission/1.0",
        "context_sha256": context_sha256,
        "runtime_prefix": str(context.runtime_prefix),
        "runtime_tree_sha256": context.runtime_tree_sha256,
        "source_snapshot_sha256": context.source_snapshot_sha256,
        "context_identity": list(identity(path.lstat())),
        "interpreter_identity": list(identity(_interpreter(context).lstat())),
    }
    if revision == MIGRATION_REVISION_0052:
        document["schema_version"] = "release-operator-admission/1.1"
        document["migration_revision"] = MIGRATION_REVISION_0052
    elif revision == MIGRATION_REVISION_0053:
        document["schema_version"] = "release-operator-admission/1.2"
        document["migration_revision"] = MIGRATION_REVISION_0053
    elif revision == MIGRATION_REVISION_0054:
        document["schema_version"] = "release-operator-admission/1.3"
        document["migration_revision"] = MIGRATION_REVISION_0054
    elif revision == MIGRATION_REVISION_0055:
        document["schema_version"] = "release-operator-admission/1.4"
        document["migration_revision"] = MIGRATION_REVISION_0055
    elif revision == MIGRATION_REVISION_0056:
        document["schema_version"] = "release-operator-admission/1.5"
        document["migration_revision"] = MIGRATION_REVISION_0056
    elif revision == MIGRATION_REVISION_0057:
        document["schema_version"] = "release-operator-admission/1.6"
        document["migration_revision"] = MIGRATION_REVISION_0057
    elif revision == MIGRATION_REVISION_0058:
        document["schema_version"] = "release-operator-admission/1.7"
        document["migration_revision"] = MIGRATION_REVISION_0058
    elif revision == MIGRATION_REVISION_0059:
        document["schema_version"] = "release-operator-admission/1.8"
        document["migration_revision"] = MIGRATION_REVISION_0059
    elif revision == MIGRATION_REVISION_0060:
        document["schema_version"] = "release-operator-admission/1.9"
        document["migration_revision"] = MIGRATION_REVISION_0060
    return document


def check_tree(root: Path) -> None:
    """Metadata only after admission: protected source trees never execute escaping links."""
    protected_path(root)
    if not root.is_dir():
        raise OperatorRuntimeError("RELEASE_OPERATOR_STAGE_INVALID")
    for parent, directories, files in os.walk(root, followlinks=False):
        for name in (*directories, *files):
            path = Path(parent) / name
            value = path.lstat()
            if stat.S_ISLNK(value.st_mode) or value.st_uid != 0 or value.st_mode & 0o6022:
                raise OperatorRuntimeError("RELEASE_OPERATOR_STAGE_INVALID")
            if not stat.S_ISDIR(value.st_mode) and not (
                stat.S_ISREG(value.st_mode) and value.st_nlink == 1
            ):
                raise OperatorRuntimeError("RELEASE_OPERATOR_STAGE_INVALID")


def tree_sha256(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*"), key=lambda member: member.relative_to(root).as_posix()):
        relative = "./" + path.relative_to(root).as_posix()
        if any(ord(char) < 32 for char in relative):
            raise OperatorRuntimeError("RELEASE_OPERATOR_STAGE_INVALID")
        if path.is_dir():
            digest.update(b"D\0" + relative.encode() + b"\0")
        else:
            payload = read_protected(path, maximum=64 * 1024**2, allow_empty=True)
            digest.update(
                b"F\0"
                + relative.encode()
                + b"\0"
                + hashlib.sha256(payload).hexdigest().encode()
                + b"\0"
            )
    return "sha256:" + digest.hexdigest()


def verify_wheels(stage: Path, context: OperatorContext) -> None:
    """Recheck small installed release payloads/RECORD, never rehash the multi-GB interpreter."""
    package_root = stage / "site-packages"
    check_tree(package_root)
    seen: set[str] = set()
    for pin in context.wheels:
        wheel = stage / "dist" / pin.name
        raw = read_protected(wheel, maximum=64 * 1024**2)
        if _sha(raw) != pin.sha256:
            raise OperatorRuntimeError("RELEASE_OPERATOR_WHEEL_CHANGED")
        with zipfile.ZipFile(wheel) as archive:
            if len(archive.infolist()) > 30000:
                raise OperatorRuntimeError("RELEASE_OPERATOR_WHEEL_INVALID")
            wheel_members: set[str] = set()
            expanded_size = 0
            for member in archive.infolist():
                relative = Path(member.filename)
                if (
                    relative.is_absolute()
                    or any(
                        part in ("..", ".") or part.endswith(".data")
                        for part in member.filename.rstrip("/").split("/")
                    )
                    or member.filename in wheel_members
                    or stat.S_ISLNK(member.external_attr >> 16)
                ):
                    raise OperatorRuntimeError("RELEASE_OPERATOR_WHEEL_INVALID")
                wheel_members.add(member.filename)
                if member.is_dir():
                    continue
                if member.filename in seen:
                    raise OperatorRuntimeError("RELEASE_OPERATOR_WHEEL_INVALID")
                seen.add(member.filename)
                expanded_size += member.file_size
                if member.file_size > 64 * 1024**2 or expanded_size > 128 * 1024**2:
                    raise OperatorRuntimeError("RELEASE_OPERATOR_WHEEL_INVALID")
                installed = read_protected(
                    package_root / relative, maximum=64 * 1024**2, allow_empty=True
                )
                if installed != archive.read(member):
                    raise OperatorRuntimeError("RELEASE_OPERATOR_INSTALLED_PAYLOAD_CHANGED")
    actual = {
        path.relative_to(package_root).as_posix()
        for path in package_root.rglob("*")
        if path.is_file()
    }
    if actual != seen:
        raise OperatorRuntimeError("RELEASE_OPERATOR_INSTALLED_PAYLOAD_CHANGED")


def verify_source_archive(stage: Path, context: OperatorContext) -> None:
    """Bind the protected extracted source to the exact reviewed Git archive, once."""
    import io

    raw = read_protected(stage / "source.tar", maximum=128 * 1024**2)
    if _sha(raw) != context.source_archive_sha256:
        raise OperatorRuntimeError("RELEASE_OPERATOR_SOURCE_CHANGED")
    expected: set[str] = set()
    names: set[str] = set()
    with tarfile.open(fileobj=io.BytesIO(raw), mode="r:") as archive:
        for number, member in enumerate(archive):
            name = member.name.rstrip("/")
            if (
                number >= 70000
                or not name
                or any(part in ("", ".", "..") for part in name.split("/"))
                or name.startswith("/")
                or any(ord(char) < 32 for char in name)
                or name in names
            ):
                raise OperatorRuntimeError("RELEASE_OPERATOR_SOURCE_ARCHIVE_INVALID")
            names.add(name)
            if member.isdir():
                if not (stage / "source" / name).is_dir():
                    raise OperatorRuntimeError("RELEASE_OPERATOR_SOURCE_CHANGED")
                continue
            if not member.isfile() or member.size > 64 * 1024**2:
                raise OperatorRuntimeError("RELEASE_OPERATOR_SOURCE_ARCHIVE_INVALID")
            payload = archive.extractfile(member)
            if payload is None:
                raise OperatorRuntimeError("RELEASE_OPERATOR_SOURCE_ARCHIVE_INVALID")
            with payload:
                actual = read_protected(
                    stage / "source" / name, maximum=64 * 1024**2, allow_empty=True
                )
                if actual != payload.read(member.size + 1):
                    raise OperatorRuntimeError("RELEASE_OPERATOR_SOURCE_CHANGED")
            expected.add(name)
    if expected != {
        member.relative_to(stage / "source").as_posix()
        for member in (stage / "source").rglob("*")
        if member.is_file()
    }:
        raise OperatorRuntimeError("RELEASE_OPERATOR_SOURCE_CHANGED")


def _interpreter(context: OperatorContext) -> Path:
    try:
        interpreter = (context.runtime_prefix / "bin/python").resolve(strict=True)
    except OSError as exc:
        raise OperatorRuntimeError("RELEASE_OPERATOR_RUNTIME_INVALID") from exc
    if not interpreter.is_relative_to(context.runtime_prefix):
        raise OperatorRuntimeError("RELEASE_OPERATOR_RUNTIME_INVALID")
    protected_path(interpreter)
    return interpreter


def read_api_native_data(path: Path, *, maximum: int) -> bytes:
    """Read fixed API native files as data, never execute their mutable-parent interpreter.

    Parent directories may retain existing eom ownership. Every path component is
    opened without following links. Targets stay root:root/single-link and 0644;
    only the fixed native member also accepts its standard non-writable 0755.
    Equality to the admitted reference bytes is checked by the caller.
    """
    if not path.is_relative_to(API_PREFIX) or ".." in path.parts:
        raise OperatorRuntimeError("RELEASE_OPERATOR_PDF_RUNTIME_INVALID")
    allowed_modes = (
        (0o644, 0o755) if path.relative_to(API_PREFIX) == API_NATIVE_MEMBER else (0o644,)
    )
    parent = os.open("/", os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    descriptor = -1
    directory_pins = [identity(os.fstat(parent))[:5]]
    try:
        for part in path.parts[1:-1]:
            child = os.open(
                part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=parent
            )
            os.close(parent)
            parent = child
            directory_pins.append(identity(os.fstat(parent))[:5])
        descriptor = os.open(
            path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC, dir_fd=parent
        )
        before = os.fstat(descriptor)
        if (
            not stat.S_ISREG(before.st_mode)
            or (before.st_uid, before.st_gid, before.st_nlink) != (0, 0, 1)
            or stat.S_IMODE(before.st_mode) not in allowed_modes
            or not 0 < before.st_size <= maximum
        ):
            raise OperatorRuntimeError("RELEASE_OPERATOR_PDF_RUNTIME_INVALID")
        raw = os.read(descriptor, before.st_size + 1)
        after_name = os.stat(path.name, dir_fd=parent, follow_symlinks=False)
        if (
            len(raw) != before.st_size
            or identity(before) != identity(os.fstat(descriptor))
            or identity(before) != identity(after_name)
        ):
            raise OperatorRuntimeError("RELEASE_OPERATOR_PDF_RUNTIME_INVALID")
        # Rewalk the actual pathname after the data read. An old FD can remain
        # valid after a developer-owned ancestor was replaced or renamed.
        current_parent = os.open("/", os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
        try:
            if identity(os.fstat(current_parent))[:5] != directory_pins[0]:
                raise OperatorRuntimeError("RELEASE_OPERATOR_PDF_RUNTIME_INVALID")
            for index, part in enumerate(path.parts[1:-1], start=1):
                child = os.open(
                    part,
                    os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                    dir_fd=current_parent,
                )
                os.close(current_parent)
                current_parent = child
                if identity(os.fstat(current_parent))[:5] != directory_pins[index]:
                    raise OperatorRuntimeError("RELEASE_OPERATOR_PDF_RUNTIME_INVALID")
            if identity(
                os.stat(path.name, dir_fd=current_parent, follow_symlinks=False)
            ) != identity(before):
                raise OperatorRuntimeError("RELEASE_OPERATOR_PDF_RUNTIME_INVALID")
        finally:
            os.close(current_parent)
        return raw
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        os.close(parent)


def admit(path: Path, context: OperatorContext, context_sha256: str) -> None:
    require_root()
    stage = path.parent
    check_tree(stage / "source")
    if tree_sha256(stage / "source") != context.source_snapshot_sha256:
        raise OperatorRuntimeError("RELEASE_OPERATOR_SOURCE_CHANGED")
    verify_source_archive(stage, context)
    verify_wheels(stage, context)
    body = _admission_document(path, context, context_sha256)
    raw = json.dumps(body, sort_keys=True, separators=(",", ":")).encode() + b"\n"
    target = stage / "operator-admission.json"
    descriptor = os.open(
        target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600
    )
    try:
        if os.write(descriptor, raw) != len(raw):
            raise OperatorRuntimeError("RELEASE_OPERATOR_RECEIPT_WRITE_FAILED")
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def verify_admission(path: Path, context: OperatorContext, context_sha256: str) -> None:
    require_root()
    value = _json(
        read_protected(path.parent / "operator-admission.json", maximum=MAX_CONTEXT_BYTES)
    )
    expected = _admission_document(path, context, context_sha256)
    if value != expected:
        raise OperatorRuntimeError("RELEASE_OPERATOR_ADMISSION_CHANGED")
    check_tree(path.parent / "source")
    verify_wheels(path.parent, context)


@contextmanager
def _quiet_callbacks() -> Iterator[None]:
    # Native/DB exceptions must not copy credentials or uncontrolled diagnostics to stdout.
    originals = (os.dup(1), os.dup(2))
    sink = os.open(os.devnull, os.O_WRONLY | os.O_CLOEXEC)
    try:
        sys.stdout.flush()
        sys.stderr.flush()
        os.dup2(sink, 1)
        os.dup2(sink, 2)
        yield
    finally:
        sys.stdout.flush()
        sys.stderr.flush()
        os.dup2(originals[0], 1)
        os.dup2(originals[1], 2)
        os.close(sink)
        os.close(originals[0])
        os.close(originals[1])


def run_callback(stage: Path, context: OperatorContext, callback: Callback) -> None:
    require_root()
    sys.path.insert(0, str(stage / "site-packages"))
    from eom_api.build_info import get_build_info
    from eom_orchestrator.migration import CURRENT_MIGRATION_REVISION

    build = get_build_info()
    if (build.source_commit, build.source_tree, build.source_archive_sha256) != (
        context.source_commit,
        context.source_tree,
        context.source_archive_sha256,
    ):
        raise OperatorRuntimeError("RELEASE_OPERATOR_BUILD_MISMATCH")
    target_revision = _context_migration_revision(context)
    if callback in _MIGRATION_CALLBACKS:
        callback_revision, _ = _MIGRATION_CALLBACKS[callback]
        if callback_revision != target_revision:
            raise OperatorRuntimeError("RELEASE_OPERATOR_REVISION_UNSUPPORTED")
    if target_revision != CURRENT_MIGRATION_REVISION:
        raise OperatorRuntimeError("RELEASE_OPERATOR_REVISION_UNSUPPORTED")
    source = stage / "source"
    if callback not in (Callback.PDF_RUNTIME_VERIFY, Callback.API_ISOLATION_VERIFY):
        check_postgres_environment()
    # Fixed libpq limits reach both the owner preflight and native Alembic's
    # separately created connection; no DB/session setting or role is persisted.
    os.environ.pop("EOM_DATABASE_URL", None)
    os.environ["EOM_POSTGRES_ENV"] = POSTGRES_ENV
    os.environ["PGCONNECT_TIMEOUT"] = _CLEAN_ENV["PGCONNECT_TIMEOUT"]
    os.environ["PGOPTIONS"] = _CLEAN_ENV["PGOPTIONS"]
    if callback in _MIGRATION_CALLBACKS:
        from alembic import command
        from alembic.config import Config
        from eom_orchestrator.database import build_engine

        _, allowed_predecessor = _MIGRATION_CALLBACKS[callback]
        engine = build_engine()
        try:
            with engine.connect() as connection:
                owner = connection.exec_driver_sql(
                    "SELECT current_user, pg_get_userbyid(nspowner), "
                    "has_schema_privilege(current_user, 'app', 'CREATE'), current_schemas(false) "
                    "FROM pg_namespace WHERE nspname='app'"
                ).one()
                current = connection.exec_driver_sql(
                    "SELECT version_num FROM app.alembic_version"
                ).scalar_one()
            if owner[0] != owner[1] or owner[2] is not True or "app" not in owner[3]:
                raise OperatorRuntimeError("RELEASE_OPERATOR_DATABASE_OWNER_INVALID")
            if allowed_predecessor is not None and current == allowed_predecessor:
                configuration = Config(str(source / "alembic.ini"))
                configuration.set_main_option("script_location", str(source / "migrations"))
                configuration.set_main_option("prepend_sys_path", "")
                command.upgrade(configuration, target_revision)
                with engine.connect() as connection:
                    current = connection.exec_driver_sql(
                        "SELECT version_num FROM app.alembic_version"
                    ).scalar_one()
            if current != target_revision:
                raise OperatorRuntimeError("RELEASE_OPERATOR_MIGRATION_HEAD_MISMATCH")
        finally:
            engine.dispose()
    elif callback == Callback.API_ROLE_BOOTSTRAP:
        try:
            result = subprocess.run(
                ("/usr/bin/bash", str(source / "scripts/api/bootstrap_runtime_role.sh")),
                cwd=source,
                env={**_CLEAN_ENV, "EOM_API_PYTHON": str(_interpreter(context))},
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
                timeout=150,
            )
        except subprocess.TimeoutExpired as exc:
            raise OperatorRuntimeError("RELEASE_OPERATOR_TIMEOUT_STATE_UNKNOWN") from exc
        if result.returncode in (124, 137):
            raise OperatorRuntimeError("RELEASE_OPERATOR_TIMEOUT_STATE_UNKNOWN")
        if result.returncode:
            raise OperatorRuntimeError("RELEASE_OPERATOR_CALLBACK_FAILED")
    elif callback in (Callback.CATALOG_ROLE_RECONCILE, Callback.HWPX_ROLE_RECONCILE):
        scripts = {
            Callback.CATALOG_ROLE_RECONCILE: "scripts/catalog/bootstrap_runtime_role.py",
            Callback.HWPX_ROLE_RECONCILE: "scripts/hwpx/bootstrap_manager_runtime_role.py",
        }
        sys.argv = [str(source / scripts[callback])]
        try:
            runpy.run_path(sys.argv[0], run_name="__main__")
        except SystemExit as exc:
            if exc.code not in (None, 0):
                raise OperatorRuntimeError("RELEASE_OPERATOR_CALLBACK_FAILED") from exc
    elif callback == Callback.PDF_RUNTIME_VERIFY:
        import importlib.metadata
        from importlib import import_module

        pymupdf = import_module("pymupdf")
        native = import_module("pymupdf._extra")

        if (
            importlib.metadata.version("PyMuPDF") != "1.26.7"
            or str(pymupdf.__version__) != "1.26.7"
        ):
            raise OperatorRuntimeError("RELEASE_OPERATOR_PDF_RUNTIME_INVALID")
        for origin in (pymupdf.__file__, native.__file__):
            reference = Path(str(origin))
            target = API_PREFIX / reference.relative_to(context.runtime_prefix)
            if read_protected(reference, maximum=128 * 1024**2) != read_api_native_data(
                target, maximum=128 * 1024**2
            ):
                raise OperatorRuntimeError("RELEASE_OPERATOR_PDF_RUNTIME_INVALID")
    elif callback == Callback.API_ISOLATION_VERIFY:
        from eom_api.runtime_isolation_verifier import (
            VerificationReport,
            verify_runtime_isolation,
        )

        # The public verifier owns exact pidfd/namespace/probe validation. Its
        # fixed child drops to the service UID before touching the API Python.
        try:
            report = verify_runtime_isolation()
        except Exception as exc:
            raise OperatorRuntimeError("RELEASE_OPERATOR_API_ISOLATION_INVALID") from exc
        if not isinstance(report, VerificationReport):
            raise OperatorRuntimeError("RELEASE_OPERATOR_API_ISOLATION_INVALID")
    else:
        raise OperatorRuntimeError("RELEASE_OPERATOR_CALLBACK_INVALID")


def check_postgres_environment() -> None:
    """The existing fixed owner secret is checked only within the protected root callback."""
    require_root()
    path = Path(POSTGRES_ENV)
    try:
        protected_path(path)
        value = path.lstat()
    except (OSError, OperatorRuntimeError) as exc:
        raise OperatorRuntimeError("RELEASE_OPERATOR_POSTGRES_ENVIRONMENT_INVALID") from exc
    if (
        not stat.S_ISREG(value.st_mode)
        or value.st_uid != 0
        or value.st_nlink != 1
        or stat.S_IMODE(value.st_mode) not in (0o600, 0o640)
    ):
        raise OperatorRuntimeError("RELEASE_OPERATOR_POSTGRES_ENVIRONMENT_INVALID")


def main(argv: list[str] | None = None) -> int:
    try:
        require_root()
        values = sys.argv[1:] if argv is None else argv
        if len(values) != 7:
            raise OperatorRuntimeError("RELEASE_OPERATOR_ARGUMENTS_INVALID")
        mode, prefix, runtime_sha, context_file, context_sha, action, expected_commit = values
        if mode not in ("ADMIT", "EXECUTE"):
            raise OperatorRuntimeError("RELEASE_OPERATOR_ARGUMENTS_INVALID")
        path = Path(context_file)
        context = load_context(path, context_sha, expected_commit)
        if (
            context.runtime_prefix != Path(prefix)
            or context.runtime_tree_sha256 != runtime_sha
            or Path(sys.prefix) != context.runtime_prefix
        ):
            raise OperatorRuntimeError("RELEASE_OPERATOR_RUNTIME_MISMATCH")
        if mode == "ADMIT":
            if action != "ADMIT":
                raise OperatorRuntimeError("RELEASE_OPERATOR_CALLBACK_INVALID")
            admit(path, context, context_sha)
        else:
            try:
                callback = Callback(action)
            except ValueError as exc:
                raise OperatorRuntimeError("RELEASE_OPERATOR_CALLBACK_INVALID") from exc
            verify_admission(path, context, context_sha)
            with _quiet_callbacks():
                run_callback(path.parent, context, callback)
        print(f"release_operator={mode}_PASS callback={action}")
        return 0
    except OperatorRuntimeError as exc:
        code = str(exc)
        if code in ERROR_CODES:
            print(code, file=sys.stderr)
        else:
            print("RELEASE_OPERATOR_RUNTIME_REJECTED", file=sys.stderr)
        return 1
    except Exception:
        print("RELEASE_OPERATOR_RUNTIME_REJECTED", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
