"""Synthetic local files/fake owner ports only; never root, DB, credentials or release execution."""

from __future__ import annotations

import hashlib
import io
import json
import os
import stat
import subprocess
import sys
import tarfile
import zipfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import Mock

import pytest
from jsonschema import Draft202012Validator

from scripts.api import release_operator_runtime as operator


def _hash(raw: bytes) -> str:
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _json(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode() + b"\n"


def _context_value() -> dict[str, Any]:
    return {
        "schema_version": "release-operator-context/1.0",
        "source_commit": "a" * 40,
        "source_tree": "b" * 40,
        "source_archive_sha256": "sha256:" + "c" * 64,
        "source_snapshot_sha256": "sha256:" + "d" * 64,
        "runtime_prefix": "/opt/eom/conda/envs/eom-embedding-experiment",
        "runtime_tree_sha256": "sha256:" + "e" * 64,
        "wheels": {
            key: {"name": name + "-0.1.0-py3-none-any.whl", "sha256": "sha256:" + "f" * 64}
            for key, name in (
                ("platform", "eom_platform"),
                ("api_contracts", "eom_api_contracts"),
                ("api", "eom_application_api"),
            )
        },
    }


@pytest.fixture
def schema() -> dict[str, Any]:
    value = json.loads(Path("scripts/api/release_operator_context.schema.json").read_bytes())
    assert isinstance(value, dict)
    Draft202012Validator.check_schema(value)
    return value


def test_actual_schema_accepts_normal_paths_and_wheel_names(schema: dict[str, Any]) -> None:
    Draft202012Validator(schema).validate(_context_value())
    assert _hash(Path("scripts/api/release_operator_context.schema.json").read_bytes()) == (
        operator._SCHEMA_SHA256
    )


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("runtime_prefix", "relative/path"),
        ("runtime_prefix", "/"),
        ("runtime_prefix", "/opt/eom\n"),
        ("runtime_prefix", "/opt/\x00/eom"),
        ("source_commit", "a" * 40 + "\n"),
        ("source_tree", "b" * 40 + "\n"),
        ("source_archive_sha256", "sha256:" + "c" * 64 + "\n"),
        ("schema_version", "release-operator-context/2.0"),
    ),
)
def test_schema_rejects_unknown_or_noncanonical_values(
    schema: dict[str, Any], field: str, value: str
) -> None:
    original = _context_value()
    original[field] = value
    assert not Draft202012Validator(schema).is_valid(original)


@pytest.mark.parametrize("name", ("x.whl", "eom_platform-0xwhl", "eom_platform-0.whl\n"))
def test_schema_wheel_regex_is_not_overescaped(schema: dict[str, Any], name: str) -> None:
    original = _context_value()
    original["wheels"]["platform"]["name"] = name
    assert not Draft202012Validator(schema).is_valid(original)


@pytest.mark.parametrize("field", ("actor_id", "database_url", "command", "secret_path"))
def test_schema_has_no_authority_or_arbitrary_callback_override(
    schema: dict[str, Any], field: str
) -> None:
    original = _context_value()
    original[field] = "not accepted"
    assert not Draft202012Validator(schema).is_valid(original)


@pytest.fixture
def synthetic_stage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[Path, operator.OperatorContext, str]:
    # This fixture admits synthetic input for function tests only. It cannot prove root protection.
    # The 1.0 context models an archived 0051 wheel, not the current source head.
    from eom_orchestrator import migration

    monkeypatch.setattr(migration, "CURRENT_MIGRATION_REVISION", "20261010_0051")
    monkeypatch.setattr(operator, "require_root", lambda: None)
    monkeypatch.setattr(operator, "protected_path", lambda _path: None)
    monkeypatch.setattr(operator, "check_tree", lambda _path: None)
    monkeypatch.setattr(operator, "check_postgres_environment", lambda: None)
    (tmp_path / "source/pkg").mkdir(parents=True)
    (tmp_path / "source/pkg/module.py").write_bytes(b"# synthetic reviewed source\n")
    (tmp_path / "source/pkg/empty.py").write_bytes(b"")
    archive_bytes = io.BytesIO()
    with tarfile.open(fileobj=archive_bytes, mode="w:") as archive:
        for member in sorted((tmp_path / "source").rglob("*")):
            archive.add(member, arcname=member.relative_to(tmp_path / "source"), recursive=False)
    (tmp_path / "source.tar").write_bytes(archive_bytes.getvalue())
    (tmp_path / "dist").mkdir()
    (tmp_path / "site-packages").mkdir()
    (tmp_path / "runtime/bin").mkdir(parents=True)
    (tmp_path / "runtime/bin/python").write_bytes(b"synthetic interpreter identity, never run")
    value = _context_value()
    value["runtime_prefix"] = str(tmp_path / "runtime")
    value["source_archive_sha256"] = _hash(archive_bytes.getvalue())
    value["source_snapshot_sha256"] = operator.tree_sha256(tmp_path / "source")
    for index, (key, pin) in enumerate(value["wheels"].items()):
        payloads = {f"pkg{index}/empty.py": b"", f"dist{index}.dist-info/RECORD": b"synthetic\n"}
        wheel = tmp_path / "dist" / pin["name"]
        with zipfile.ZipFile(wheel, "w") as zipped:
            for package_member, data in payloads.items():
                zipped.writestr(package_member, data)
                target = tmp_path / "site-packages" / package_member
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)
        value["wheels"][key]["sha256"] = _hash(wheel.read_bytes())
    context_path = tmp_path / "operator-context.json"
    context_path.write_bytes(_json(value))
    context_hash = _hash(context_path.read_bytes())
    return context_path, operator.load_context(context_path, context_hash, "a" * 40), context_hash


def test_source_wheels_and_empty_files_are_exactly_verified(
    synthetic_stage: tuple[Path, operator.OperatorContext, str],
) -> None:
    path, context, digest = synthetic_stage
    operator.verify_source_archive(path.parent, context)
    operator.verify_wheels(path.parent, context)
    operator.admit(path, context, digest)
    operator.verify_admission(path, context, digest)
    with pytest.raises(FileExistsError):
        operator.admit(path, context, digest)


@pytest.mark.parametrize("change", ("source", "archive", "wheel", "package", "extra-package"))
def test_admission_rejects_exact_source_and_package_drift(
    synthetic_stage: tuple[Path, operator.OperatorContext, str], change: str
) -> None:
    path, context, digest = synthetic_stage
    if change == "source":
        (path.parent / "source/pkg/module.py").write_bytes(b"changed\n")
    elif change == "archive":
        (path.parent / "source.tar").write_bytes(b"not reviewed archive")
    elif change == "wheel":
        (path.parent / "dist" / context.wheels[0].name).write_bytes(b"not reviewed wheel")
    elif change == "package":
        (path.parent / "site-packages/dist0.dist-info/RECORD").write_bytes(b"altered RECORD")
    else:
        (path.parent / "site-packages/unreviewed.py").write_bytes(b"unexpected")
    with pytest.raises(operator.OperatorRuntimeError):
        operator.admit(path, context, digest)
    assert not (path.parent / "operator-admission.json").exists()


def test_archive_does_not_allow_independently_pinned_but_different_extracted_source(
    synthetic_stage: tuple[Path, operator.OperatorContext, str],
) -> None:
    path, context, _digest = synthetic_stage
    (path.parent / "source/pkg/module.py").write_bytes(b"another pinned but wrong source\n")
    with pytest.raises(operator.OperatorRuntimeError, match="SOURCE_CHANGED"):
        operator.verify_source_archive(path.parent, context)


@pytest.mark.parametrize("prefix", ("/opt/../eom", "/opt/./eom", "/opt//eom"))
def test_context_rejects_lexical_path_aliases_before_interpreter_resolution(
    synthetic_stage: tuple[Path, operator.OperatorContext, str], prefix: str
) -> None:
    path, _context, _digest = synthetic_stage
    value = json.loads(path.read_bytes())
    value["runtime_prefix"] = prefix
    path.write_bytes(_json(value))
    with pytest.raises(operator.OperatorRuntimeError, match="PATH_INVALID"):
        operator.load_context(path, _hash(path.read_bytes()), "a" * 40)


def test_stale_receipt_and_context_hash_are_not_replayed(
    synthetic_stage: tuple[Path, operator.OperatorContext, str],
) -> None:
    path, context, digest = synthetic_stage
    operator.admit(path, context, digest)
    receipt_path = path.parent / "operator-admission.json"
    receipt = json.loads(receipt_path.read_bytes())
    receipt["context_identity"][1] += 1
    receipt_path.write_bytes(_json(receipt))
    with pytest.raises(operator.OperatorRuntimeError, match="ADMISSION_CHANGED"):
        operator.verify_admission(path, context, digest)
    with pytest.raises(operator.OperatorRuntimeError, match="CONTEXT_CHANGED"):
        operator.load_context(path, "sha256:" + "0" * 64, "a" * 40)


def test_json_duplicate_and_nonfinite_values_fail_closed(
    synthetic_stage: tuple[Path, operator.OperatorContext, str],
) -> None:
    for raw in (b'{"a":1,"a":2}', b'{"a":NaN}'):
        with pytest.raises(operator.OperatorRuntimeError, match="JSON_INVALID"):
            operator._json(raw)


def test_nonroot_denial_precedes_any_file_engine_or_secret_access(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(os, "geteuid", lambda: 1001)
    forbidden = Mock(side_effect=AssertionError("must not read any file"))
    monkeypatch.setattr(operator, "load_context", forbidden)
    assert operator.main(["EXECUTE"] * 7) == 1
    forbidden.assert_not_called()
    assert capsys.readouterr().err.strip() == "RELEASE_OPERATOR_ROOT_REQUIRED"


def test_uncontrolled_error_or_secret_is_never_rendered(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(operator, "require_root", lambda: None)
    monkeypatch.setattr(
        operator, "load_context", Mock(side_effect=ValueError("private credential"))
    )
    assert operator.main(["EXECUTE"] * 7) == 1
    output = capsys.readouterr()
    assert output.err.strip() == "RELEASE_OPERATOR_RUNTIME_REJECTED"
    assert "private credential" not in output.out + output.err


@pytest.mark.parametrize("mode", (stat.S_IFLNK | 0o777, stat.S_IFREG | 0o666))
def test_protected_path_rejects_links_or_writable_metadata(
    monkeypatch: pytest.MonkeyPatch, mode: int
) -> None:
    metadata = os.stat_result((mode, 1, 1, 1, 0, 0, 1, 0, 0, 0))
    monkeypatch.setattr(Path, "lstat", lambda _self: metadata)
    with pytest.raises(operator.OperatorRuntimeError, match="PATH_INVALID"):
        operator.protected_path(Path("/fixed/owner"))


@pytest.mark.parametrize("node", ("fifo", "hardlink", "large", "symlink"))
def test_nofollow_bounded_fd_checks_reject_special_or_changed_file_inputs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, node: str
) -> None:
    monkeypatch.setattr(operator, "protected_path", lambda _path: None)
    target = tmp_path / "node"
    if node == "fifo":
        os.mkfifo(target)
    elif node == "hardlink":
        target.write_bytes(b"bytes")
        os.link(target, tmp_path / "alias")
    elif node == "large":
        target.write_bytes(b"too long")
    else:
        (tmp_path / "real").write_bytes(b"bytes")
        target.symlink_to(tmp_path / "real")
    with pytest.raises((operator.OperatorRuntimeError, OSError)):
        operator.read_protected(target, maximum=4)


def test_read_file_detects_name_replacement_during_materialization(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(operator, "protected_path", lambda _path: None)
    target = tmp_path / "file"
    target.write_bytes(b"exact bytes")
    original = os.read

    def changing_read(descriptor: int, amount: int) -> bytes:
        raw = original(descriptor, amount)
        target.rename(tmp_path / "old")
        target.write_bytes(raw)
        return raw

    monkeypatch.setattr(os, "read", changing_read)
    with pytest.raises(operator.OperatorRuntimeError, match="FILE_CHANGED"):
        operator.read_protected(target, maximum=100)


class FakeEngine:
    def __init__(self, revision: str, *, owner: bool = True) -> None:
        self.revision = revision
        self.owner = owner
        self.disposed = False
        self.owner_query = False

    @contextmanager
    def connect(self) -> Iterator[FakeEngine]:
        yield self

    def exec_driver_sql(self, command: str) -> FakeEngine:
        self.owner_query = "current_user" in command
        return self

    def one(self) -> tuple[str, str, bool, tuple[str, str]]:
        assert self.owner_query
        return (
            "native-owner",
            "native-owner" if self.owner else "another",
            True,
            ("app", "public"),
        )

    def scalar_one(self) -> str:
        return self.revision

    def dispose(self) -> None:
        self.disposed = True


@pytest.mark.parametrize(
    ("callback", "revision", "owner", "succeeds", "upgrade_count"),
    (
        (operator.Callback.MIGRATION_UPGRADE_0051, "20261009_0050", True, True, 1),
        (operator.Callback.MIGRATION_UPGRADE_0051, "20261010_0051", True, True, 0),
        (operator.Callback.MIGRATION_VERIFY, "20261010_0051", True, True, 0),
        (operator.Callback.MIGRATION_VERIFY, "20261009_0050", True, False, 0),
        (operator.Callback.MIGRATION_UPGRADE_0051, "unexpected", True, False, 0),
        (operator.Callback.MIGRATION_UPGRADE_0051, "20261009_0050", False, False, 0),
    ),
)
def test_native_migration_callback_has_only_exact_0051_upgrade_and_owner_guard(
    synthetic_stage: tuple[Path, operator.OperatorContext, str],
    monkeypatch: pytest.MonkeyPatch,
    callback: operator.Callback,
    revision: str,
    owner: bool,
    succeeds: bool,
    upgrade_count: int,
) -> None:
    from alembic import command
    from alembic.config import Config
    from eom_api import build_info
    from eom_orchestrator import database

    path, context, _digest = synthetic_stage
    monkeypatch.setenv("EOM_DATABASE_URL", "not accepted ambient override")
    monkeypatch.setenv("EOM_POSTGRES_ENV", "not accepted alternate secret")
    monkeypatch.setenv("PGOPTIONS", "not accepted unlimited options")
    monkeypatch.setenv("PGCONNECT_TIMEOUT", "0")
    monkeypatch.setattr(
        build_info,
        "get_build_info",
        lambda: SimpleNamespace(
            source_commit=context.source_commit,
            source_tree=context.source_tree,
            source_archive_sha256=context.source_archive_sha256,
        ),
    )
    engine = FakeEngine(revision, owner=owner)
    monkeypatch.setattr(database, "build_engine", lambda: engine)
    configurations: list[Config] = []

    def upgrade(configuration: Config, requested: str) -> None:
        assert requested == "20261010_0051"
        configurations.append(configuration)
        engine.revision = requested

    monkeypatch.setattr(command, "upgrade", upgrade)
    if succeeds:
        operator.run_callback(path.parent, context, callback)
    else:
        with pytest.raises(operator.OperatorRuntimeError):
            operator.run_callback(path.parent, context, callback)
    assert len(configurations) == upgrade_count and engine.disposed
    for configuration in configurations:
        assert configuration.get_main_option("script_location") == str(
            path.parent / "source/migrations"
        )
        assert configuration.get_main_option("prepend_sys_path") == ""
    assert "EOM_DATABASE_URL" not in os.environ
    assert os.environ["EOM_POSTGRES_ENV"] == "/etc/eom/secrets/postgres.env"
    assert os.environ["PGCONNECT_TIMEOUT"] == "15"
    assert os.environ["PGOPTIONS"] == "-c lock_timeout=5000 -c statement_timeout=120000"


def test_role_child_keeps_existing_script_but_closes_ambient_python_and_cwd(
    synthetic_stage: tuple[Path, operator.OperatorContext, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    from eom_api import build_info

    path, context, _digest = synthetic_stage
    monkeypatch.setattr(
        build_info,
        "get_build_info",
        lambda: SimpleNamespace(
            source_commit=context.source_commit,
            source_tree=context.source_tree,
            source_archive_sha256=context.source_archive_sha256,
        ),
    )
    child = Mock(return_value=SimpleNamespace(returncode=0))
    monkeypatch.setattr(subprocess, "run", child)
    operator.run_callback(path.parent, context, operator.Callback.API_ROLE_BOOTSTRAP)
    args, keywords = child.call_args
    assert args[0] == (
        "/usr/bin/bash",
        str(path.parent / "source/scripts/api/bootstrap_runtime_role.sh"),
    )
    assert keywords["cwd"] == path.parent / "source" and keywords["timeout"] == 150
    assert keywords["env"]["EOM_API_PYTHON"] == str(context.runtime_prefix / "bin/python")
    for key in ("PYTHONSAFEPATH", "PYTHONNOUSERSITE", "PYTHONDONTWRITEBYTECODE"):
        assert keywords["env"][key] == "1"
    assert "PYTHONPATH" not in keywords["env"] and "EOM_DATABASE_URL" not in keywords["env"]
    original = Path("scripts/api/bootstrap_runtime_role.sh").read_text()
    assert "exec \"${PYTHON}\" <<'PY'" in original and original.rstrip().endswith("PY")
    assert (
        'print("Runtime database role and protected environment file are reconciled.")' in original
    )


@pytest.mark.parametrize("mode", (0o600, 0o640, 0o666))
def test_owner_secret_metadata_is_fixed_checked_in_callback_not_developer_wrapper(
    monkeypatch: pytest.MonkeyPatch,
    mode: int,
) -> None:
    monkeypatch.setattr(operator, "require_root", lambda: None)
    monkeypatch.setattr(operator, "protected_path", lambda _path: None)
    metadata = os.stat_result((stat.S_IFREG | mode, 1, 1, 1, 0, 0, 1, 0, 0, 0))
    paths: list[Path] = []

    def fake_lstat(path: Path) -> os.stat_result:
        paths.append(path)
        return metadata

    monkeypatch.setattr(Path, "lstat", fake_lstat)
    if mode == 0o666:
        with pytest.raises(operator.OperatorRuntimeError, match="POSTGRES_ENVIRONMENT_INVALID"):
            operator.check_postgres_environment()
    else:
        operator.check_postgres_environment()
    assert paths == [Path("/etc/eom/secrets/postgres.env")]


@pytest.mark.parametrize("returncode", (124, 137))
def test_child_group_timeout_is_unknown_state_not_automatic_retry(
    synthetic_stage: tuple[Path, operator.OperatorContext, str],
    monkeypatch: pytest.MonkeyPatch,
    returncode: int,
) -> None:
    from eom_api import build_info

    path, context, _digest = synthetic_stage
    monkeypatch.setattr(
        build_info,
        "get_build_info",
        lambda: SimpleNamespace(
            source_commit=context.source_commit,
            source_tree=context.source_tree,
            source_archive_sha256=context.source_archive_sha256,
        ),
    )
    child = Mock(return_value=SimpleNamespace(returncode=returncode))
    monkeypatch.setattr(subprocess, "run", child)
    with pytest.raises(operator.OperatorRuntimeError, match="TIMEOUT_STATE_UNKNOWN"):
        operator.run_callback(path.parent, context, operator.Callback.API_ROLE_BOOTSTRAP)
    assert child.call_count == 1


def _pretend_root_regular_metadata(monkeypatch: pytest.MonkeyPatch) -> None:
    # Synthetic local metadata only, not a root/installed filesystem acceptance.
    original_fstat, original_stat = os.fstat, os.stat

    def root_file(value: os.stat_result) -> os.stat_result:
        if not stat.S_ISREG(value.st_mode):
            return value
        return cast(
            os.stat_result,
            SimpleNamespace(
                st_dev=value.st_dev,
                st_ino=value.st_ino,
                st_mode=value.st_mode,
                st_uid=0,
                st_gid=0,
                st_nlink=value.st_nlink,
                st_size=value.st_size,
                st_mtime_ns=value.st_mtime_ns,
                st_ctime_ns=value.st_ctime_ns,
            ),
        )

    monkeypatch.setattr(os, "fstat", lambda fd: root_file(original_fstat(fd)))
    monkeypatch.setattr(
        os, "stat", lambda *args, **kwargs: root_file(original_stat(*args, **kwargs))
    )


@pytest.mark.parametrize("action", ("unchanged", "symlink", "parent-replaced"))
def test_native_api_file_comparison_is_data_only_and_rechecks_parent_path_epoch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, action: str
) -> None:
    prefix = tmp_path / "api"
    prefix.mkdir()
    target = prefix / "native.so"
    target.write_bytes(b"known admitted reference payload")
    target.chmod(0o644)
    monkeypatch.setattr(operator, "API_PREFIX", prefix)
    _pretend_root_regular_metadata(monkeypatch)
    if action == "unchanged":
        assert operator.read_api_native_data(target, maximum=100) == target.read_bytes()
    elif action == "symlink":
        target.rename(prefix / "real")
        target.symlink_to(prefix / "real")
        with pytest.raises(OSError):
            operator.read_api_native_data(target, maximum=100)
    else:
        original_read = os.read

        def changing_read(descriptor: int, amount: int) -> bytes:
            payload = original_read(descriptor, amount)
            prefix.rename(tmp_path / "old-api")
            prefix.mkdir()
            target.write_bytes(payload)
            return payload

        monkeypatch.setattr(os, "read", changing_read)
        with pytest.raises(operator.OperatorRuntimeError, match="PDF_RUNTIME_INVALID"):
            operator.read_api_native_data(target, maximum=100)


@pytest.mark.parametrize(
    ("member", "mode", "accepted"),
    (
        ("lib/python3.12/site-packages/pymupdf/_extra.so", 0o644, True),
        ("lib/python3.12/site-packages/pymupdf/_extra.so", 0o755, True),
        ("lib/python3.12/site-packages/pymupdf/_extra.so", 0o664, False),
        ("lib/python3.12/site-packages/pymupdf/_extra.so", 0o775, False),
        ("lib/python3.12/site-packages/pymupdf/_extra.so", 0o777, False),
        ("lib/python3.12/site-packages/pymupdf/_extra.so", 0o4755, False),
        ("lib/python3.12/site-packages/pymupdf/__init__.py", 0o644, True),
        ("lib/python3.12/site-packages/pymupdf/__init__.py", 0o755, False),
        ("lib/python3.12/site-packages/pymupdf/__init__.py", 0o664, False),
        ("lib/python3.12/site-packages/other/_extra.so", 0o755, False),
        ("lib/python3.12/site-packages/pymupdf/_extra.backup.so", 0o755, False),
    ),
)
def test_native_data_reader_allows_755_only_for_exact_nonwritable_native_member(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    member: str,
    mode: int,
    accepted: bool,
) -> None:
    prefix = tmp_path / "api"
    target = prefix / member
    target.parent.mkdir(parents=True)
    target.write_bytes(b"synthetic native/text comparison bytes")
    target.chmod(mode)
    monkeypatch.setattr(operator, "API_PREFIX", prefix)
    _pretend_root_regular_metadata(monkeypatch)
    if accepted:
        assert operator.read_api_native_data(target, maximum=100) == target.read_bytes()
    else:
        with pytest.raises(operator.OperatorRuntimeError, match="PDF_RUNTIME_INVALID"):
            operator.read_api_native_data(target, maximum=100)


@pytest.mark.parametrize("alias", ("symlink", "hardlink"))
def test_native_755_exception_does_not_allow_aliases_or_multiple_links(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, alias: str
) -> None:
    prefix = tmp_path / "api"
    target = prefix / "lib/python3.12/site-packages/pymupdf/_extra.so"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"synthetic fixed native bytes")
    target.chmod(0o755)
    other = target.with_name("other.so")
    if alias == "symlink":
        target.rename(other)
        target.symlink_to(other)
    else:
        os.link(target, other)
    monkeypatch.setattr(operator, "API_PREFIX", prefix)
    _pretend_root_regular_metadata(monkeypatch)
    if alias == "symlink":
        with pytest.raises(OSError):
            operator.read_api_native_data(target, maximum=100)
    else:
        with pytest.raises(operator.OperatorRuntimeError, match="PDF_RUNTIME_INVALID"):
            operator.read_api_native_data(target, maximum=100)


def test_closed_callback_enum_and_bootstrap_relative_source_are_not_generic_framework() -> None:
    assert {member.value for member in operator.Callback} == {
        "MIGRATION_VERIFY",
        "MIGRATION_UPGRADE_0051",
        "MIGRATION_VERIFY_0052",
        "MIGRATION_UPGRADE_0052",
        "MIGRATION_VERIFY_0053",
        "MIGRATION_UPGRADE_0053",
        "MIGRATION_VERIFY_0054",
        "MIGRATION_UPGRADE_0054",
        "MIGRATION_VERIFY_0055",
        "MIGRATION_UPGRADE_0055",
        "MIGRATION_VERIFY_0056",
        "MIGRATION_UPGRADE_0056",
        "MIGRATION_VERIFY_0057",
        "MIGRATION_UPGRADE_0057",
        "MIGRATION_VERIFY_0058",
        "MIGRATION_UPGRADE_0058",
        "MIGRATION_VERIFY_0059",
        "MIGRATION_UPGRADE_0059",
        "MIGRATION_VERIFY_0060",
        "MIGRATION_UPGRADE_0060",
        "MIGRATION_VERIFY_0061",
        "MIGRATION_UPGRADE_0061",
        "MIGRATION_VERIFY_0062",
        "MIGRATION_UPGRADE_0062",
        "MIGRATION_VERIFY_0063",
        "MIGRATION_UPGRADE_0063",
        "MIGRATION_VERIFY_0064",
        "MIGRATION_UPGRADE_0064",
        "MIGRATION_UPGRADE_0064_FROM_0062",
        "API_ROLE_BOOTSTRAP",
        "CATALOG_ROLE_RECONCILE",
        "HWPX_ROLE_RECONCILE",
        "PDF_RUNTIME_VERIFY",
        "API_ISOLATION_VERIFY",
    }
    for relative in (
        "scripts/catalog/bootstrap_runtime_role.py",
        "scripts/hwpx/bootstrap_manager_runtime_role.py",
    ):
        source = Path(relative).read_text()
        assert "REPOSITORY = Path(__file__).resolve().parents[2]" in source
        assert 'Path("/home/eom/EOM")' not in source


def test_metadata_scan_uses_one_native_predicate_pass_not_per_member_stat_forks() -> None:
    source = Path("scripts/api/release_operator_runtime.sh").read_text()
    start = source.index("invalid=$(find -P")
    stop = source.index('[[ -x "$PREFIX/bin/python"', start)
    metadata_scan = source[start:stop]
    assert "-uid 0" in metadata_scan and "-perm /6022" in metadata_scan
    assert "! -links 1" in metadata_scan and "-printf x -quit" in metadata_scan
    assert "stat " not in metadata_scan
    assert 'find -P "$PREFIX" -type l -print0' in metadata_scan
    assert "/usr/bin/timeout --signal=TERM --kill-after=10s 180s" in source


@pytest.mark.parametrize("outcome", ("pass", "native-failure", "invalid-return", "build-drift"))
def test_api_isolation_uses_public_staged_verifier_without_database_or_root_api_child(
    synthetic_stage: tuple[Path, operator.OperatorContext, str],
    monkeypatch: pytest.MonkeyPatch,
    outcome: str,
) -> None:
    from eom_api import build_info, runtime_isolation_verifier
    from eom_orchestrator import database

    path, context, _digest = synthetic_stage
    monkeypatch.setattr(
        build_info,
        "get_build_info",
        lambda: SimpleNamespace(
            source_commit="f" * 40 if outcome == "build-drift" else context.source_commit,
            source_tree=context.source_tree,
            source_archive_sha256=context.source_archive_sha256,
        ),
    )
    forbidden_secret_read = Mock(side_effect=AssertionError("no database secret read"))
    forbidden_engine = Mock(side_effect=AssertionError("no database connection"))
    forbidden_child = Mock(side_effect=AssertionError("no mutable root interpreter"))
    monkeypatch.setattr(operator, "check_postgres_environment", forbidden_secret_read)
    monkeypatch.setattr(database, "build_engine", forbidden_engine)
    monkeypatch.setattr(subprocess, "run", forbidden_child)
    verifier = Mock(
        return_value=(
            object()
            if outcome == "invalid-return"
            else runtime_isolation_verifier.VerificationReport(())
        ),
    )
    if outcome == "native-failure":
        verifier.side_effect = RuntimeError("uncontrolled native exception must not escape")
    monkeypatch.setattr(runtime_isolation_verifier, "verify_runtime_isolation", verifier)
    if outcome == "pass":
        operator.run_callback(path.parent, context, operator.Callback.API_ISOLATION_VERIFY)
    else:
        code = "BUILD_MISMATCH" if outcome == "build-drift" else "API_ISOLATION_INVALID"
        with pytest.raises(operator.OperatorRuntimeError, match=code):
            operator.run_callback(path.parent, context, operator.Callback.API_ISOLATION_VERIFY)
    assert sys.path[0] == str(path.parent / "site-packages")
    if outcome == "build-drift":
        verifier.assert_not_called()
    else:
        verifier.assert_called_once_with()
    forbidden_secret_read.assert_not_called()
    forbidden_engine.assert_not_called()
    forbidden_child.assert_not_called()


def test_api_isolation_callback_sanitizes_uncontrolled_failure_output(
    synthetic_stage: tuple[Path, operator.OperatorContext, str],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    path, context, digest = synthetic_stage
    monkeypatch.setattr(operator, "verify_admission", lambda *_args: None)
    monkeypatch.setattr(sys, "prefix", str(context.runtime_prefix))

    def fail(*_args: object) -> None:
        raise operator.OperatorRuntimeError("RELEASE_OPERATOR_API_ISOLATION_INVALID") from (
            RuntimeError("uncontrolled child/native failure payload")
        )

    monkeypatch.setattr(operator, "run_callback", fail)
    result = operator.main(
        [
            "EXECUTE",
            str(context.runtime_prefix),
            context.runtime_tree_sha256,
            str(path),
            digest,
            "API_ISOLATION_VERIFY",
            context.source_commit,
        ]
    )
    output = capsys.readouterr()
    assert result == 1 and output.out == ""
    assert output.err == "RELEASE_OPERATOR_API_ISOLATION_INVALID\n"
