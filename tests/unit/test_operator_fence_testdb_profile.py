"""Synthetic filesystem/SQL orchestration only; no database or root execution."""

from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
import tempfile
from collections.abc import Callable, Iterator
from contextlib import ExitStack, contextmanager
from pathlib import Path
from typing import Any, cast

import psycopg
import pytest
from eom_identity_service import (
    OPERATOR_AUTHORIZATION_FENCE_CREATE_SQL,
    OPERATOR_AUTHORIZATION_FENCE_REVOKE_PUBLIC_SQL,
)
from eom_orchestrator.migration import CURRENT_MIGRATION_REVISION
from psycopg import sql
from psycopg.rows import dict_row

from scripts.api import testdb_operator_fence as profile
from scripts.api.testdb_guard import TestDatabaseManifest as Manifest


@pytest.fixture
def state_path() -> Iterator[Path]:
    with tempfile.TemporaryDirectory(prefix="eom-api-testdb-") as value:
        path = Path(value)
        manifest = Manifest.create("20261012212033_1dde6544")
        files = {
            "manifest.json": manifest.to_json(),
            "owner.env": "EOM_DATABASE_URL=postgresql+psycopg://"
            + manifest.owner_role
            + ":synthetic-owner-password@127.0.0.1:5432/"
            + manifest.database
            + "\n",
            "runtime.env": "EOM_API_DATABASE_URL=postgresql+psycopg://"
            + manifest.runtime_role
            + ":synthetic-runtime-password@127.0.0.1:5432/"
            + manifest.database
            + "\nEOM_API_TOKEN_HASH_KEY=synthetic-key\n"
            + "EOM_API_FINGERPRINT_KEY=synthetic-key\n",
        }
        for name, raw in files.items():
            target = path / name
            target.write_text(raw, encoding="ascii")
            target.chmod(0o600)
        yield path


@contextmanager
def state(path: Path) -> Iterator[profile._State]:
    with ExitStack() as stack:
        yield profile._State(path, os.geteuid(), os.getegid(), stack)


class Rows:
    def __init__(self, values: list[dict[str, Any]]) -> None:
        self.values = values

    def fetchone(self) -> dict[str, Any] | None:
        return self.values[0] if self.values else None

    def fetchall(self) -> list[dict[str, Any]]:
        return self.values


class Database:
    """Closed inert statement fixture, never psycopg connection fallthrough."""

    def __init__(self) -> None:
        manifest = Manifest.create("20261012212033_1dde6544")
        self.guard: dict[str, Any] = {
            "database_oid": 11,
            "owner_oid": 12,
            "runtime_oid": 13,
            "app_oid": 14,
            "public_oid": 15,
            "database_name": manifest.database,
            "current_role": manifest.owner_role,
            "schemas": ["app", "public"],
            "temp_schema": 0,
            "isolation": "read committed",
            "read_only": "off",
            "database_marker": manifest.marker,
            "owner_marker": manifest.marker,
            "runtime_marker": manifest.marker,
            "app_marker": manifest.marker,
            "owners_ok": True,
            "role_ok": True,
            "owner_role_ok": True,
            "runtime_path_ok": True,
            "owner_privileges_ok": True,
            "app_safe": True,
            "public_safe": True,
            "iam_objects_ok": True,
            "iam_oids": list(range(101, 110)),
            "migration": CURRENT_MIGRATION_REVISION,
        }
        self.calls: list[tuple[str, tuple[object, ...]]] = []
        self.durable_writes: list[str] = []
        self.limited, self.temp, self.function, self.granted = False, False, False, False
        self.public_execute = False
        self.routine_exact = True
        self.schema_ok = True
        self.public_temp_denied = True
        self.column_rows = [
            {"table_name": name, "column_name": "id", "safe": True} for name in profile._IAM
        ]
        self.metadata_rows: list[dict[str, Any]] = [
            {
                "kind": "TABLE",
                "schema_name": "app",
                "object_oid": 21,
                "member": 0,
                "privilege": "INSERT",
                "allowed": True,
            }
        ]
        self.drift_after: int | None = None
        self.drift_iam = False
        self.metadata_drift = False
        self.fail_statement: int | None = None
        self.fail_commit = False
        self.committed, self.rolled_back = 0, 0
        self.timeouts = {"lock_timeout": 0, "statement_timeout": 0}

    def __enter__(self) -> Database:
        return self

    def __exit__(self, *arguments: object) -> None:
        pass

    @contextmanager
    def transaction(self) -> Iterator[None]:
        initial = (self.limited, self.temp, self.function, self.granted, self.public_execute)
        try:
            yield
            if self.fail_commit:
                raise psycopg.OperationalError("synthetic-private-error")
            self.committed += 1
        except BaseException:
            self.limited, self.temp, self.function, self.granted, self.public_execute = initial
            self.rolled_back += 1
            raise

    def execute(self, statement: str | sql.Composable, parameters: tuple[object, ...] = ()) -> Rows:
        raw = statement if isinstance(statement, str) else statement.as_string()
        self.calls.append((raw, parameters))
        if raw == profile._GUARD_SQL:
            row = dict(self.guard)
            if self.drift_after is not None and len(self.durable_writes) >= self.drift_after:
                if self.drift_iam:
                    row["iam_oids"] = list(range(201, 210))
                else:
                    row["runtime_oid"] = 999
            return Rows([row])
        if "SELECT name, setting::bigint" in raw:
            return Rows(
                [{"name": name, "milliseconds": value} for name, value in self.timeouts.items()]
            )
        if "SELECT pg_catalog.set_config" in raw:
            return Rows([])
        if raw == profile._COLUMNS_SQL:
            return Rows(self.column_rows)
        if raw == profile._NON_IAM_SQL:
            rows = [dict(row) for row in self.metadata_rows]
            if self.metadata_drift and self.durable_writes:
                rows[0]["allowed"] = False
            return Rows(rows)
        if raw == profile._IAM_SQL:
            return Rows([{"limited": self.limited, "baseline_writes": not self.limited}])
        if raw == profile._SCHEMA_TEMP_SQL:
            return Rows(
                [
                    {
                        "schemas_ok": self.schema_ok,
                        "runtime_temp": self.temp,
                        "public_temp_denied": self.public_temp_denied,
                    }
                ]
            )
        if raw == profile._ROUTINE_SQL:
            return Rows(
                [
                    {
                        "oid": 31,
                        "exact": self.routine_exact,
                        "acl_ok": self.granted and not self.public_execute,
                    }
                ]
                if self.function
                else []
            )
        assert raw.startswith(("REVOKE ", "GRANT ", "CREATE FUNCTION "))
        self.durable_writes.append(raw)
        if self.fail_statement == len(self.durable_writes):
            raise psycopg.OperationalError("synthetic-private-error")
        if raw.startswith("GRANT SELECT ON TABLE"):
            self.limited = True
        if raw.startswith("GRANT TEMPORARY"):
            self.temp = True
        if raw == OPERATOR_AUTHORIZATION_FENCE_CREATE_SQL:
            self.function, self.public_execute = True, True
        if raw == OPERATOR_AUTHORIZATION_FENCE_REVOKE_PUBLIC_SQL:
            self.public_execute = False
        if raw.startswith("GRANT EXECUTE"):
            self.granted = True
        return Rows([])


def connect(monkeypatch: pytest.MonkeyPatch, database: Database) -> None:
    def fake(*arguments: object, **keywords: object) -> Database:
        assert keywords == {
            "connect_timeout": 5,
            "autocommit": False,
            "row_factory": dict_row,
        }
        assert str(arguments[0]).startswith("postgresql://eom_api_test_owner_")
        return database

    monkeypatch.setattr(psycopg, "connect", fake)


def prepare(local: profile._State, database: Database, monkeypatch: pytest.MonkeyPatch) -> None:
    connect(monkeypatch, database)
    profile._database_phase(
        local, profile._urls(local), profile.PROFILE + ":" + local.manifest.test_id, prepare=True
    )


def test_prepare_exact_owner_transaction_and_readonly_replay(
    state_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database = Database()
    with state(state_path) as local:
        local.lock()
        prepare(local, database, monkeypatch)
    assert database.committed == 1 and database.rolled_back == 0
    assert database.limited and database.temp and database.function and database.granted
    writes = list(database.durable_writes)
    with state(state_path) as local:
        local.lock()
        prepare(local, database, monkeypatch)
    assert database.committed == 2 and database.durable_writes == writes
    raw = (state_path / profile._RECEIPT).read_bytes()
    assert b"synthetic" not in raw and b"password" not in raw and b"postgresql" not in raw
    assert b"owner_env_sha256=sha256:" in raw and b"runtime_env_sha256=sha256:" in raw
    assert stat.S_IMODE((state_path / profile._RECEIPT).stat().st_mode) == 0o600


def test_mutations_are_fixed_narrow_and_guarded_before_every_write(
    state_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database = Database()
    with state(state_path) as local:
        prepare(local, database, monkeypatch)
        role = local.manifest.runtime_role
    joined = "\n".join(database.durable_writes)
    assert len(database.durable_writes) == 24
    assert all(
        role in statement
        for statement in database.durable_writes
        if statement.startswith("GRANT ") or statement.startswith("REVOKE ALL PRIVILEGES ON TABLE")
    )
    assert 'GRANT TEMPORARY ON DATABASE "eom_api_test_' in joined
    assert "GRANT EXECUTE ON FUNCTION public.eom_fence_operator_authorization_v1(text)" in joined
    assert "eom_catalog_manager_runtime" not in joined
    assert "ALL TABLES IN SCHEMA" not in joined and "ALTER ROLE" not in joined
    assert "CREATE OR REPLACE" not in joined and "ALTER OWNER" not in joined
    assert "GRANT TEMPORARY ON DATABASE" not in joined.split("FROM PUBLIC")[-1]
    for index, (statement, _parameters) in enumerate(database.calls):
        if statement in database.durable_writes or statement.startswith(
            "SELECT pg_catalog.set_config"
        ):
            assert database.calls[index - 1][0] == profile._GUARD_SQL
    assert database.calls[-1][0] == profile._GUARD_SQL


@pytest.mark.parametrize(
    "key,value",
    [
        ("database_name", "eom"),
        ("current_role", "postgres"),
        ("schemas", ["public", "app"]),
        ("temp_schema", 4),
        ("isolation", "repeatable read"),
        ("read_only", "on"),
        ("database_marker", "foreign"),
        ("owner_marker", "foreign"),
        ("runtime_marker", "foreign"),
        ("app_marker", "foreign"),
        ("owners_ok", False),
        ("role_ok", False),
        ("owner_role_ok", False),
        ("runtime_path_ok", False),
        ("owner_privileges_ok", False),
        ("app_safe", False),
        ("public_safe", False),
        ("iam_objects_ok", False),
        ("iam_oids", [1] * 9),
        ("iam_oids", [True, *range(2, 10)]),
        ("iam_oids", list(range(1, 9))),
        ("migration", "foreign"),
        ("owner_oid", True),
        ("runtime_oid", "13"),
        ("database_oid", 0),
        ("app_oid", 2**32),
        ("public_oid", -1),
        ("owner_oid", 13),
    ],
)
def test_bad_current_database_guard_stops_before_writes(
    state_path: Path, monkeypatch: pytest.MonkeyPatch, key: str, value: object
) -> None:
    database = Database()
    database.guard[key] = value
    with (
        state(state_path) as local,
        pytest.raises(profile.FenceProfileError, match="DATABASE_INVALID"),
    ):
        prepare(local, database, monkeypatch)
    assert not database.durable_writes and database.rolled_back == 1
    assert not (state_path / profile._STARTED).exists()


def test_guard_oid_drift_between_writes_rolls_back_without_repair(
    state_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database = Database()
    database.drift_after = 2
    with (
        state(state_path) as local,
        pytest.raises(profile.FenceProfileError, match="DATABASE_CHANGED"),
    ):
        prepare(local, database, monkeypatch)
    assert len(database.durable_writes) == 2 and database.rolled_back == 1
    assert (state_path / profile._STARTED).exists() and not (state_path / profile._RECEIPT).exists()
    assert not database.limited and not database.temp and not database.function


def test_iam_named_table_recreation_epoch_between_writes_is_not_admitted(
    state_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = Database()
    database.drift_after, database.drift_iam = 2, True
    with (
        state(state_path) as local,
        pytest.raises(profile.FenceProfileError, match="DATABASE_CHANGED"),
    ):
        prepare(local, database, monkeypatch)
    assert len(database.durable_writes) == 2 and database.rolled_back == 1


def test_file_drift_stops_before_next_db_write(
    state_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database = Database()
    execute = database.execute

    def changed(statement: str | sql.Composable, parameters: tuple[object, ...] = ()) -> Rows:
        result = execute(statement, parameters)
        if len(database.durable_writes) == 1:
            with (state_path / "runtime.env").open("a") as stream:
                stream.write("UNTRUSTED=synthetic\n")
        return result

    monkeypatch.setattr(database, "execute", changed)
    with state(state_path) as local, pytest.raises(profile.FenceProfileError, match="FILE_CHANGED"):
        prepare(local, database, monkeypatch)
    assert len(database.durable_writes) == 1 and database.rolled_back == 1


@pytest.mark.parametrize("case", ["missing", "duplicate", "unsafe", "owner", "too_many"])
def test_iam_column_closure_is_bounded(
    state_path: Path, monkeypatch: pytest.MonkeyPatch, case: str
) -> None:
    database = Database()
    if case == "missing":
        database.column_rows.pop()
    elif case == "duplicate":
        database.column_rows.append(dict(database.column_rows[0]))
    elif case == "unsafe":
        database.column_rows[0]["column_name"] = "evil; SQL"
    elif case == "owner":
        database.column_rows[0]["safe"] = False
    else:
        database.column_rows *= 114
    with state(state_path) as local, pytest.raises(profile.FenceProfileError, match="IAM_INVALID"):
        prepare(local, database, monkeypatch)
    assert not database.durable_writes


@pytest.mark.parametrize("case", ["extra_function", "schema", "public_temp", "baseline_temp"])
def test_preflight_refuses_existing_function_or_schema_leak(
    state_path: Path, monkeypatch: pytest.MonkeyPatch, case: str
) -> None:
    database = Database()
    if case == "extra_function":
        database.function = True
    elif case == "schema":
        database.schema_ok = False
    elif case == "public_temp":
        database.public_temp_denied = False
    else:
        database.temp = True
    with state(state_path) as local, pytest.raises(profile.FenceProfileError):
        prepare(local, database, monkeypatch)
    assert not database.durable_writes and not (state_path / profile._STARTED).exists()


def test_non_iam_effective_grants_must_remain_exact(
    state_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database = Database()
    database.metadata_drift = True
    with (
        state(state_path) as local,
        pytest.raises(profile.FenceProfileError, match="NON_IAM_CHANGED"),
    ):
        prepare(local, database, monkeypatch)
    assert database.rolled_back == 1 and not database.function


@pytest.mark.parametrize(
    "case", ["empty", "duplicate", "huge", "bool_oid", "bad_kind", "bad_allowed"]
)
def test_non_iam_metadata_bounds_and_types(
    state_path: Path, monkeypatch: pytest.MonkeyPatch, case: str
) -> None:
    database = Database()
    if case == "empty":
        database.metadata_rows = []
    elif case == "duplicate":
        database.metadata_rows *= 2
    elif case == "huge":
        database.metadata_rows *= profile._MAX_METADATA + 1
    else:
        field, value = {
            "bool_oid": ("object_oid", True),
            "bad_kind": ("kind", "EVIL"),
            "bad_allowed": ("allowed", 1),
        }[case]
        database.metadata_rows[0][field] = value
    with (
        state(state_path) as local,
        pytest.raises(profile.FenceProfileError, match="METADATA_INVALID"),
    ):
        prepare(local, database, monkeypatch)
    assert not database.durable_writes


def test_timeout_caps_never_weaken_positive_owner_settings(
    state_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database = Database()
    database.timeouts = {"lock_timeout": 1000, "statement_timeout": 2000}
    with state(state_path) as local:
        prepare(local, database, monkeypatch)
    assert [
        parameters for raw, parameters in database.calls if "SELECT pg_catalog.set_config" in raw
    ] == [
        ("lock_timeout", "1000ms"),
        ("statement_timeout", "2000ms"),
    ]


@pytest.mark.parametrize("statement", [1, 19, 22, 24])
def test_db_failure_rolls_back_and_preserves_started_evidence(
    state_path: Path, monkeypatch: pytest.MonkeyPatch, statement: int
) -> None:
    database = Database()
    database.fail_statement = statement
    with (
        state(state_path) as local,
        pytest.raises(profile.FenceProfileError, match="TRANSACTION_FAILED"),
    ):
        prepare(local, database, monkeypatch)
    assert database.rolled_back == 1 and not database.function and not database.temp
    assert (state_path / profile._STARTED).exists() and not (state_path / profile._RECEIPT).exists()


def test_commit_failure_never_creates_success_receipt(
    state_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database = Database()
    database.fail_commit = True
    with (
        state(state_path) as local,
        pytest.raises(profile.FenceProfileError, match="COMMIT_UNCERTAIN"),
    ):
        prepare(local, database, monkeypatch)
    assert (state_path / profile._STARTED).exists() and not (state_path / profile._RECEIPT).exists()


def test_receipt_failure_after_commit_is_explicit_and_cannot_reapply(
    state_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database = Database()
    with state(state_path) as local:
        write = local.write_once

        def fail_receipt(name: str, raw: bytes) -> None:
            if name == profile._RECEIPT:
                raise OSError("synthetic-private-error")
            write(name, raw)

        monkeypatch.setattr(local, "write_once", fail_receipt)
        with pytest.raises(profile.FenceProfileError, match="PREPARED_WITHOUT_RECEIPT"):
            prepare(local, database, monkeypatch)
    writes = list(database.durable_writes)
    assert database.committed == 1 and database.function
    with (
        state(state_path) as local,
        pytest.raises(profile.FenceProfileError, match="PREPARED_WITHOUT_RECEIPT"),
    ):
        prepare(local, database, monkeypatch)
    assert database.durable_writes == writes and not (state_path / profile._RECEIPT).exists()


def test_receipt_replay_rechecks_actual_profile_and_env_raw_hash(
    state_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database = Database()
    with state(state_path) as local:
        prepare(local, database, monkeypatch)
    database.routine_exact = False
    with (
        state(state_path) as local,
        pytest.raises(profile.FenceProfileError, match="ROUTINE_INVALID"),
    ):
        prepare(local, database, monkeypatch)
    database.routine_exact = True
    raw = (state_path / "owner.env").read_text().replace("synthetic-owner-password", "different")
    (state_path / "owner.env").write_text(raw)
    with (
        state(state_path) as local,
        pytest.raises(profile.FenceProfileError, match="RECEIPT_INVALID"),
    ):
        prepare(local, database, monkeypatch)


@pytest.mark.parametrize(
    "case",
    [
        "file_mode",
        "directory_mode",
        "symlink",
        "hardlink",
        "fifo",
        "manifest_extra",
        "noncanonical",
    ],
)
def test_untrusted_state_inputs_fail_closed(state_path: Path, case: str) -> None:
    target = state_path / "manifest.json"
    if case == "file_mode":
        target.chmod(0o640)
    elif case == "directory_mode":
        state_path.chmod(0o750)
    elif case == "symlink":
        target.rename(state_path / "original")
        target.symlink_to(state_path / "original")
    elif case == "hardlink":
        os.link(target, state_path / "another")
    elif case == "fifo":
        target.unlink()
        os.mkfifo(target, 0o600)
    elif case == "manifest_extra":
        values = json.loads(target.read_text())
        values["authority"] = "ADMIN"
        target.write_text(json.dumps(values))
    else:
        target.write_text(json.dumps(json.loads(target.read_text()), indent=2))
    with pytest.raises((profile.FenceProfileError, OSError, ValueError)), state(state_path):
        pass


@pytest.mark.parametrize(
    "replacement",
    [
        "postgresql+psycopg://postgres",
        "postgresql+psycopg://foreign",
        "@localhost:5432/",
        "@127.0.0.1:5433/",
        "?options=unsafe",
        "#fragment",
    ],
)
def test_url_target_or_options_rejected(state_path: Path, replacement: str) -> None:
    target = state_path / "owner.env"
    raw = target.read_text()
    if replacement.startswith("postgresql"):
        raw = raw.replace(
            "postgresql+psycopg://" + Manifest.create("20261012212033_1dde6544").owner_role,
            replacement,
        )
    elif replacement.startswith("@"):
        raw = raw.replace("@127.0.0.1:5432/", replacement)
    else:
        raw = raw.rstrip("\n") + replacement + "\n"
    target.write_text(raw)
    with state(state_path) as local, pytest.raises(profile.FenceProfileError, match="URL_INVALID"):
        profile._urls(local)


@pytest.mark.parametrize("line", ["EOM_DATABASE_URL=duplicate", "EVIL=$(command)", "#!/bin/sh"])
def test_env_is_data_with_exact_keys_not_shell(state_path: Path, line: str) -> None:
    with (state_path / "owner.env").open("a") as stream:
        stream.write(line + "\n")
    with state(state_path) as local, pytest.raises(profile.FenceProfileError, match="ENV_INVALID"):
        profile._urls(local)


@pytest.mark.parametrize(
    "ack", ["", "OPERATOR_FENCE_LIMITED_TEMP/1.0:20261012212033_deadbeef", "ADMIN", profile.PROFILE]
)
def test_ack_is_exact_before_any_database_or_lock(
    state_path: Path, monkeypatch: pytest.MonkeyPatch, ack: str
) -> None:
    def forbidden(*arguments: object, **keywords: object) -> None:
        raise AssertionError("no database connection authorized")

    monkeypatch.setattr(psycopg, "connect", forbidden)
    with pytest.raises(profile.FenceProfileError, match="ACK_INVALID"):
        profile.run("operator-fence-prepare", state_path, ack)
    assert not (state_path / profile._LOCK).exists()


def test_root_or_wrong_interpreter_rejected_before_files(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(os, "geteuid", lambda: 0)
    with pytest.raises(profile.FenceProfileError, match="CONTEXT_INVALID"):
        profile.run("operator-fence-prepare", Path("/not/a/state"), "private-marker")


def test_real_independent_process_lock_contention_without_database(state_path: Path) -> None:
    source = """
import os, sys
from contextlib import ExitStack
from pathlib import Path
from scripts.api.testdb_operator_fence import _State, FenceProfileError
with ExitStack() as stack:
    try:
        _State(Path(sys.argv[1]), os.geteuid(), os.getegid(), stack).lock()
    except FenceProfileError as error:
        print(error.code)
        raise SystemExit(0 if error.code == 'OPERATOR_FENCE_TEST_BUSY' else 1)
raise SystemExit(2)
"""
    with state(state_path) as local:
        local.lock()
        result = subprocess.run(
            (sys.executable, "-c", source, str(state_path)),
            check=False,
            capture_output=True,
            timeout=10,
            env=dict(os.environ),
        )
        assert result.returncode == 0 and result.stdout == b"OPERATOR_FENCE_TEST_BUSY\n"
    with state(state_path) as local:
        local.lock()


@pytest.mark.parametrize("field", [4, 5])
def test_foreign_file_uid_or_gid_rejected_without_chown(
    state_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    field: int,
) -> None:
    original = os.fstat

    def foreign(descriptor: int) -> os.stat_result:
        value = original(descriptor)
        if stat.S_ISREG(value.st_mode):
            fields = list(value)
            fields[field] += 1
            return os.stat_result(fields)
        return value

    monkeypatch.setattr(os, "fstat", foreign)
    with pytest.raises(profile.FenceProfileError, match="FILE_INVALID"), state(state_path):
        pass


def test_named_directory_epoch_replacement_rejected(state_path: Path) -> None:
    with state(state_path) as local:
        renamed = state_path / "retained"
        # Substitute only the directory's named lookup, never mutate another filesystem subtree.
        with pytest.MonkeyPatch.context() as patcher:
            original = os.stat

            def drift(path: Any, *arguments: Any, **keywords: Any) -> os.stat_result:
                value = original(path, *arguments, **keywords)
                if path == state_path.name and keywords.get("dir_fd") is not None:
                    fields = list(value)
                    fields[1] += 1
                    return os.stat_result(fields)
                return value

            patcher.setattr(os, "stat", drift)
            with pytest.raises(profile.FenceProfileError, match="STATE_CHANGED"):
                local.assert_current()
        assert not renamed.exists()


def test_run_invokes_only_six_prepared_cases_with_closed_environment(
    state_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database = Database()
    with state(state_path) as local:
        prepare(local, database, monkeypatch)
    calls: list[tuple[object, dict[str, Any]]] = []

    class Completed:
        def wait(self, *, timeout: int) -> int:
            assert timeout == 180
            return 0

    def fake(arguments: object, **keywords: Any) -> Completed:
        calls.append((arguments, keywords))
        return Completed()

    monkeypatch.setattr(subprocess, "Popen", fake)
    monkeypatch.setenv("EOM_API_DATABASE_URL", "must-not-inherit-production")
    profile.run("operator-fence-tests", state_path, profile.PROFILE + ":20261012212033_1dde6544")
    assert len(calls) == 1
    arguments, keywords = calls[0]
    assert (
        cast(tuple[str, ...], arguments)[-1]
        == "tests/integration/test_operator_authorization_fence.py"
    )
    environment = keywords["env"]
    assert "EOM_API_DATABASE_URL" not in environment
    assert environment["EOM_RUN_OPERATOR_FENCE_INTEGRATION"] == "1"
    assert environment["EOM_DATABASE_URL"].startswith("postgresql+psycopg://eom_api_test_owner_")
    assert database.committed == 3  # preparation, pre-run and post-run read-only verification


def test_initial_catalog_deadline_cancels_only_owned_connection_before_mutation(
    state_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = Database()
    cancellations: list[int] = []
    monkeypatch.setattr(
        database, "cancel_safe", lambda *, timeout: cancellations.append(timeout), raising=False
    )

    class Immediate:
        daemon = False

        def __init__(self, seconds: int, callback: Callable[[], None]) -> None:
            assert seconds == 90
            self.callback = callback

        def start(self) -> None:
            self.callback()

        def cancel(self) -> None:
            pass

    monkeypatch.setattr(profile, "Timer", Immediate)
    with (
        state(state_path) as local,
        pytest.raises(profile.FenceProfileError, match="TRANSACTION_UNCERTAIN"),
    ):
        prepare(local, database, monkeypatch)
    assert cancellations == [2] and not database.calls and not database.durable_writes


def test_pytest_timeout_signals_only_popen_owned_private_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    waits: list[int] = []
    signals: list[tuple[int, int]] = []

    class TimedOut:
        pid = 987654321

        def wait(self, *, timeout: int) -> int:
            waits.append(timeout)
            if timeout == 180:
                raise subprocess.TimeoutExpired("fixed-test-command", timeout)
            return -9

    def owned(arguments: object, **keywords: Any) -> TimedOut:
        assert keywords["start_new_session"] is True
        return TimedOut()

    monkeypatch.setattr(subprocess, "Popen", owned)
    monkeypatch.setattr(os, "killpg", lambda pid, signal: signals.append((pid, signal)))
    with pytest.raises(profile.FenceProfileError, match="TESTS_UNCERTAIN"):
        profile._run_cases({})
    assert waits == [180, 5] and signals == [(TimedOut.pid, 9)]


def test_main_errors_are_content_free(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def fail(*arguments: object) -> None:
        raise OSError("synthetic-private-password")

    monkeypatch.setattr(profile, "run", fail)
    monkeypatch.setattr(sys, "argv", ["script", "action", "private-path", "private-ack"])
    assert profile.main() == 1
    assert capsys.readouterr().err == "OPERATOR_FENCE_TEST_UNAVAILABLE\n"


def test_shell_new_closed_branch_precedes_legacy_env_sourcing() -> None:
    raw = (profile._REPOSITORY / "scripts/api/testdb_run.sh").read_text()
    assert raw.count("SOURCE_PATHS=(") == 1 and raw.count("export PYTHONPATH=") == 1
    assert raw.index("export PYTHONPATH=") < raw.index("if (($# == 3))")
    assert "packages/catalog_contracts services/catalog_service apps/eomctl" in raw
    assert "packages/hwpx_contracts services/hwpx_manager" in raw
    assert raw.index("if (($# == 3))") < raw.index('source "${state_directory}/owner.env"')
    assert '"${REPOSITORY_ROOT}/scripts/api/testdb_operator_fence.py" "$1" "$2" "$3"' in raw
    assert "if (($# != 2))" in raw
    assert "bootstrap_runtime_role" not in Path(profile.__file__).read_text()


def test_actual_early_cli_imports_current_complete_source_and_never_sources_env(
    state_path: Path,
) -> None:
    marker = state_path / "must-not-create"
    with (state_path / "owner.env").open("a") as stream:
        stream.write(f"UNTRUSTED=$(touch {marker})\n")
    result = subprocess.run(
        (
            "/usr/bin/bash",
            str(profile._REPOSITORY / "scripts/api/testdb_run.sh"),
            "operator-fence-prepare",
            str(state_path),
            profile.PROFILE + ":20261012212033_1dde6544",
        ),
        cwd="/",
        check=False,
        capture_output=True,
        timeout=15,
        env={"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "TZ": "UTC"},
    )
    assert result.returncode == 1 and result.stderr == b"OPERATOR_FENCE_TEST_ENV_INVALID\n"
    assert not marker.exists() and not (state_path / profile._STARTED).exists()


def test_normal_two_argument_encoding_action_uses_existing_guard_without_fence_ack(
    state_path: Path,
    tmp_path: Path,
) -> None:
    """Inert interpreter consumes guard stdin; no Python/SQL fixture body executes."""
    interpreter = tmp_path / "inert-python"
    interpreter.write_text(
        "#!/usr/bin/env bash\n"
        "if [[ ${1:-} == -m ]]; then\n"
        "  printf 'PYTEST=%s FLAGS=%s:%s STATE=%s\\n' \"${4:-}\" "
        '"${EOM_RUN_INTEGRATION:-}" "${EOM_RUN_API_INTEGRATION:-}" "${EOM_API_TEST_STATE:-}"\n'
        "else\n  while IFS= read -r line; do :; done\nfi\n"
    )
    interpreter.chmod(0o700)
    raw = (profile._REPOSITORY / "scripts/api/testdb_run.sh").read_text()
    raw = raw.replace('REPOSITORY_ROOT="/home/eom/EOM"', f'REPOSITORY_ROOT="{tmp_path}"')
    raw = raw.replace('PYTHON="/srv/eom/conda/envs/eom-api/bin/python"', f'PYTHON="{interpreter}"')
    script = tmp_path / "testdb-run.sh"
    script.write_text(raw)
    result = subprocess.run(
        ("/usr/bin/bash", str(script), "embedding-encoding-tests", str(state_path)),
        check=False,
        capture_output=True,
        timeout=10,
        env={"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8"},
    )
    assert result.returncode == 0, result.stderr.decode()
    assert (
        b"PYTEST=tests/integration/test_embedding_encoding_reservations.py FLAGS=1:1 STATE="
        + str(state_path).encode()
        + b"\n"
    ) in result.stdout
    assert b"operator-fence" not in result.stdout
