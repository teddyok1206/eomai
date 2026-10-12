"""One acknowledged disposable owner-only fence profile; never production/bootstrap."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import pwd
import re
import signal
import stat
import subprocess
import sys
from contextlib import ExitStack, suppress
from dataclasses import dataclass, field
from pathlib import Path
from threading import Event, Timer
from typing import Any
from urllib.parse import unquote, urlsplit

import psycopg
from eom_identity_service import (
    OPERATOR_AUTHORIZATION_FENCE_BODY,
    OPERATOR_AUTHORIZATION_FENCE_BODY_SHA256,
    OPERATOR_AUTHORIZATION_FENCE_CREATE_SQL,
    OPERATOR_AUTHORIZATION_FENCE_REVOKE_PUBLIC_SQL,
)
from eom_orchestrator.migration import CURRENT_MIGRATION_REVISION
from psycopg import sql
from psycopg.rows import dict_row

from scripts.api.testdb_guard import TestDatabaseManifest, validate_state_directory

PROFILE = "OPERATOR_FENCE_LIMITED_TEMP/1.0"
_PYTHON = Path("/srv/eom/conda/envs/eom-api/bin/python")
_REPOSITORY = Path("/home/eom/EOM")
_RECEIPT = "operator-fence-profile.receipt"
_STARTED = ".operator-fence-profile.started"
_LOCK = ".operator-fence-profile.lock"
_IAM = (
    "operators",
    "roles",
    "permissions",
    "role_permissions",
    "operator_role_assignments",
    "operator_credentials",
    "api_sessions",
    "api_tokens",
    "operator_events",
)
_READ_IAM = _IAM[:5]
_MAX_FILE = 4096
_MAX_METADATA = 20000
_SOURCE_PATHS = (
    ".",
    "packages/protocol",
    "packages/identifiers",
    "packages/workflow",
    "packages/operator_identity",
    "packages/catalog_contracts",
    "services/orchestrator",
    "services/workflow_runner",
    "services/identity_service",
    "services/catalog_service",
    "packages/api_contracts",
    "apps/application_api",
    "packages/image_contracts",
    "packages/hwpx_contracts",
    "services/hwpx_manager",
    "packages/content_intake",
    "packages/content_pack",
    "packages/item_registry",
    "tools/dev_reporter",
)
type _Connection = psycopg.Connection[dict[str, Any]]


class FenceProfileError(ValueError):
    """Only closed content-free diagnostics leave the preparation boundary."""

    def __init__(self, code: str) -> None:
        super().__init__("OPERATOR_FENCE_TEST_" + code)
        self.code = "OPERATOR_FENCE_TEST_" + code


def _require(value: bool, code: str) -> None:
    if not value:
        raise FenceProfileError(code)


def _identity(value: os.stat_result) -> tuple[int, ...]:
    return (value.st_dev, value.st_ino, value.st_uid, value.st_gid, value.st_mode)


def _epoch(value: os.stat_result) -> tuple[int, ...]:
    return (*_identity(value), value.st_nlink, value.st_size, value.st_mtime_ns, value.st_ctime_ns)


@dataclass(frozen=True)
class _PinnedFile:
    descriptor: int
    name: str
    epoch: tuple[int, ...]
    raw: bytes = field(repr=False)

    @property
    def sha256(self) -> str:
        return "sha256:" + hashlib.sha256(self.raw).hexdigest()


class _State:
    """Held exact private inputs and one per-state mutex; no credential publication."""

    def __init__(self, path: Path, uid: int, gid: int, stack: ExitStack) -> None:
        self.path = validate_state_directory(path)
        _require(path == self.path, "STATE_INVALID")
        self.uid, self.gid = uid, gid
        self.expired = Event()
        self._stack = stack
        self._directories: list[tuple[int, int | None, str, tuple[int, ...]]] = []
        flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
        parent: int | None = None
        for index, name in enumerate(self.path.parts):
            descriptor = os.open(name, flags, dir_fd=parent)
            stack.callback(os.close, descriptor)
            value = os.fstat(descriptor)
            final = index == len(self.path.parts) - 1
            _require(stat.S_ISDIR(value.st_mode), "STATE_INVALID")
            if final:
                _require(
                    (value.st_uid, value.st_gid, stat.S_IMODE(value.st_mode)) == (uid, gid, 0o700),
                    "STATE_INVALID",
                )
            else:
                sticky_tmp = index == 1 and name == "tmp" and bool(value.st_mode & stat.S_ISVTX)
                _require(
                    value.st_uid == 0 and (not value.st_mode & 0o022 or sticky_tmp), "STATE_INVALID"
                )
            self._directories.append((descriptor, parent, name, _identity(value)))
            parent = descriptor
        assert parent is not None
        self.directory = parent
        self.inputs: list[_PinnedFile] = []
        self.manifest_file = self.read("manifest.json")
        self.owner_file, self.runtime_file = self.read("owner.env"), self.read("runtime.env")
        self.manifest = TestDatabaseManifest.from_json(self.manifest_file.raw.decode("ascii"))
        _require(
            self.manifest_file.raw == self.manifest.to_json().encode("ascii"), "MANIFEST_INVALID"
        )
        self.assert_current()

    def _metadata(self, value: os.stat_result, *, limit: int = _MAX_FILE) -> None:
        _require(
            stat.S_ISREG(value.st_mode)
            and value.st_nlink == 1
            and (value.st_uid, value.st_gid, stat.S_IMODE(value.st_mode))
            == (self.uid, self.gid, 0o600)
            and 0 <= value.st_size <= limit,
            "FILE_INVALID",
        )

    def read(self, name: str) -> _PinnedFile:
        descriptor = os.open(
            name,
            os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK,
            dir_fd=self.directory,
        )
        self._stack.callback(os.close, descriptor)
        value = os.fstat(descriptor)
        self._metadata(value)
        raw = os.pread(descriptor, value.st_size + 1, 0)
        _require(len(raw) == value.st_size, "FILE_CHANGED")
        pinned = _PinnedFile(descriptor, name, _epoch(value), raw)
        self.inputs.append(pinned)
        self.assert_current()
        return pinned

    def optional(self, name: str) -> _PinnedFile | None:
        try:
            return self.read(name)
        except FileNotFoundError:
            return None

    def assert_current(self) -> None:
        _require(not self.expired.is_set(), "TRANSACTION_UNCERTAIN")
        for descriptor, parent, name, identity in self._directories:
            _require(
                identity
                == _identity(os.fstat(descriptor))
                == _identity(os.stat(name, dir_fd=parent, follow_symlinks=False)),
                "STATE_CHANGED",
            )
        for value in self.inputs:
            _require(
                value.epoch
                == _epoch(os.fstat(value.descriptor))
                == _epoch(os.stat(value.name, dir_fd=self.directory, follow_symlinks=False)),
                "FILE_CHANGED",
            )

    def lock(self) -> None:
        self.assert_current()
        flags = os.O_RDWR | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK
        try:
            descriptor = os.open(
                _LOCK, flags | os.O_CREAT | os.O_EXCL, 0o600, dir_fd=self.directory
            )
        except FileExistsError:
            descriptor = os.open(_LOCK, flags, dir_fd=self.directory)
        self._stack.callback(os.close, descriptor)
        initial = os.fstat(descriptor)
        self._metadata(initial, limit=0)
        _require(
            _epoch(initial) == _epoch(os.stat(_LOCK, dir_fd=self.directory, follow_symlinks=False)),
            "FILE_CHANGED",
        )
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise FenceProfileError("BUSY") from None
        self.inputs.append(_PinnedFile(descriptor, _LOCK, _epoch(initial), b""))
        self.assert_current()

    def write_once(self, name: str, raw: bytes) -> None:
        self.assert_current()
        _require(0 < len(raw) <= 2048, "RECEIPT_INVALID")
        descriptor = os.open(
            name,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
            0o600,
            dir_fd=self.directory,
        )
        try:
            initial = os.fstat(descriptor)
            self._metadata(initial, limit=0)
            position = 0
            while position < len(raw):
                count = os.write(descriptor, raw[position:])
                _require(0 < count <= len(raw) - position, "RECEIPT_FAILED")
                position += count
            os.fsync(descriptor)
            final = os.fstat(descriptor)
            self._metadata(final)
            _require(
                _identity(initial) == _identity(final)
                and final.st_size == len(raw)
                and _epoch(final)
                == _epoch(os.stat(name, dir_fd=self.directory, follow_symlinks=False)),
                "RECEIPT_FAILED",
            )
            self.assert_current()
            os.fsync(self.directory)
        finally:
            os.close(descriptor)


@dataclass(frozen=True)
class _Urls:
    owner: str = field(repr=False)
    runtime: str = field(repr=False)


def _environment(raw: bytes, keys: set[str]) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in raw.decode("ascii").splitlines():
        key, separator, value = line.partition("=")
        _require(
            bool(separator) and key in keys and key not in values and bool(value), "ENV_INVALID"
        )
        _require(not any(ord(character) < 32 for character in value), "ENV_INVALID")
        values[key] = value
    _require(set(values) == keys, "ENV_INVALID")
    return values


def _urls(state: _State) -> _Urls:
    owner = _environment(state.owner_file.raw, {"EOM_DATABASE_URL"})["EOM_DATABASE_URL"]
    runtime = _environment(
        state.runtime_file.raw,
        {"EOM_API_DATABASE_URL", "EOM_API_TOKEN_HASH_KEY", "EOM_API_FINGERPRINT_KEY"},
    )["EOM_API_DATABASE_URL"]
    for value, role in ((owner, state.manifest.owner_role), (runtime, state.manifest.runtime_role)):
        parsed = urlsplit(value)
        _require(
            parsed.scheme == "postgresql+psycopg"
            and parsed.username == role
            and parsed.hostname == "127.0.0.1"
            and parsed.port == 5432
            and parsed.path == "/" + state.manifest.database
            and bool(parsed.password)
            and not parsed.query
            and not parsed.fragment
            and unquote(parsed.username or "") == role,
            "URL_INVALID",
        )
    return _Urls(owner.replace("postgresql+psycopg://", "postgresql://", 1), runtime)


_GUARD_SQL = """
SELECT d.oid::bigint AS database_oid, owner.oid::bigint AS owner_oid,
 runtime.oid::bigint AS runtime_oid, app.oid::bigint AS app_oid, public.oid::bigint AS public_oid,
 pg_catalog.current_database() AS database_name, CURRENT_USER AS current_role,
 pg_catalog.current_schemas(false) AS schemas, pg_catalog.pg_my_temp_schema() AS temp_schema,
 pg_catalog.current_setting('transaction_isolation') AS isolation,
 pg_catalog.current_setting('transaction_read_only') AS read_only,
 pg_catalog.shobj_description(d.oid, 'pg_database') AS database_marker,
 pg_catalog.shobj_description(owner.oid, 'pg_authid') AS owner_marker,
 pg_catalog.shobj_description(runtime.oid, 'pg_authid') AS runtime_marker,
 pg_catalog.obj_description(app.oid, 'pg_namespace') AS app_marker,
 (d.datdba=owner.oid AND app.nspowner=owner.oid) AS owners_ok,
 (runtime.rolcanlogin AND NOT runtime.rolsuper AND NOT runtime.rolcreatedb
  AND NOT runtime.rolcreaterole AND NOT runtime.rolinherit AND NOT runtime.rolreplication
  AND NOT runtime.rolbypassrls AND NOT EXISTS(SELECT 1 FROM pg_catalog.pg_auth_members
   WHERE member=runtime.oid OR roleid=runtime.oid)) AS role_ok,
 (SELECT count(*)=1 AND bool_and(setdatabase=0 AND
    setconfig=ARRAY['search_path=app, pg_catalog']::text[])
  FROM pg_catalog.pg_db_role_setting WHERE setrole=runtime.oid) AS runtime_path_ok,
 (pg_catalog.has_schema_privilege(CURRENT_USER, app.oid, 'USAGE')
  AND pg_catalog.has_schema_privilege(CURRENT_USER, app.oid, 'CREATE')
  AND pg_catalog.has_schema_privilege(CURRENT_USER, public.oid, 'CREATE')) AS owner_privileges_ok,
 (owner.rolcanlogin AND NOT owner.rolsuper AND NOT owner.rolcreatedb
  AND NOT owner.rolcreaterole AND NOT owner.rolinherit AND NOT owner.rolreplication
  AND NOT owner.rolbypassrls AND NOT EXISTS(SELECT 1 FROM pg_catalog.pg_auth_members
   WHERE member=owner.oid OR roleid=owner.oid)) AS owner_role_ok,
 NOT EXISTS(SELECT 1 FROM pg_catalog.aclexplode(COALESCE(app.nspacl,
   pg_catalog.acldefault('n',app.nspowner))) acl WHERE privilege_type='CREATE'
   AND grantee NOT IN(app.nspowner,owner.oid,d.datdba)) AS app_safe,
 NOT EXISTS(SELECT 1 FROM pg_catalog.aclexplode(COALESCE(public.nspacl,
   pg_catalog.acldefault('n',public.nspowner))) acl WHERE privilege_type='CREATE'
   AND grantee NOT IN(public.nspowner,owner.oid,d.datdba)) AS public_safe,
 (SELECT count(*)=9 AND bool_and(c.oid IS NOT NULL AND c.relowner=owner.oid
    AND c.relkind='r' AND NOT c.relrowsecurity AND NOT c.relforcerowsecurity)
  FROM (VALUES('operators'),('roles'),('permissions'),('role_permissions'),
    ('operator_role_assignments'),('operator_credentials'),('api_sessions'),
    ('api_tokens'),('operator_events')) iam(name)
  LEFT JOIN pg_catalog.pg_class c
   ON c.relnamespace=app.oid AND c.relname=iam.name) AS iam_objects_ok,
 ARRAY(SELECT c.oid::bigint FROM pg_catalog.pg_class c
  WHERE c.relnamespace=app.oid AND c.relname IN('operators','roles','permissions',
   'role_permissions','operator_role_assignments','operator_credentials','api_sessions',
   'api_tokens','operator_events') ORDER BY c.relname) AS iam_oids,
 (SELECT version_num FROM app.alembic_version) AS migration
FROM pg_catalog.pg_database d
JOIN pg_catalog.pg_roles owner ON owner.rolname=%s
JOIN pg_catalog.pg_roles runtime ON runtime.rolname=%s
JOIN pg_catalog.pg_namespace app ON app.nspname='app'
JOIN pg_catalog.pg_namespace public ON public.nspname='public'
WHERE d.datname=pg_catalog.current_database()
"""


@dataclass(frozen=True)
class _DatabasePin:
    database_oid: int
    owner_oid: int
    runtime_oid: int
    app_oid: int
    public_oid: int
    iam_oids: tuple[int, ...]


def _guard(connection: _Connection, state: _State, ack: str) -> _DatabasePin:
    state.assert_current()
    manifest = state.manifest
    _require(ack == PROFILE + ":" + manifest.test_id, "ACK_INVALID")
    row = connection.execute(_GUARD_SQL, (manifest.owner_role, manifest.runtime_role)).fetchone()
    _require(row is not None, "DATABASE_INVALID")
    assert row is not None
    _require(
        row["database_name"] == manifest.database
        and row["current_role"] == manifest.owner_role
        and row["schemas"] == ["app", "public"]
        and row["temp_schema"] == 0
        and row["isolation"] == "read committed"
        and row["read_only"] == "off"
        and all(
            row[name] == manifest.marker
            for name in ("database_marker", "owner_marker", "runtime_marker", "app_marker")
        )
        and all(
            row[name] is True
            for name in (
                "owners_ok",
                "role_ok",
                "owner_role_ok",
                "runtime_path_ok",
                "owner_privileges_ok",
                "app_safe",
                "public_safe",
                "iam_objects_ok",
            )
        )
        and row["migration"] == CURRENT_MIGRATION_REVISION,
        "DATABASE_INVALID",
    )
    names = ("database_oid", "owner_oid", "runtime_oid", "app_oid", "public_oid")
    _require(
        all(type(row[name]) is int and 0 < row[name] <= 2**32 - 1 for name in names),
        "DATABASE_INVALID",
    )
    _require(row["owner_oid"] != row["runtime_oid"], "DATABASE_INVALID")
    oids = row["iam_oids"]
    _require(
        type(oids) is list
        and len(oids) == 9
        and all(type(oid) is int and 0 < oid <= 2**32 - 1 for oid in oids)
        and len(set(oids)) == 9,
        "DATABASE_INVALID",
    )
    return _DatabasePin(
        row["database_oid"],
        row["owner_oid"],
        row["runtime_oid"],
        row["app_oid"],
        row["public_oid"],
        tuple(oids),
    )


def _waits(connection: _Connection, state: _State, ack: str, pin: _DatabasePin) -> None:
    row = connection.execute(
        "SELECT name, setting::bigint AS milliseconds FROM pg_catalog.pg_settings "
        "WHERE name IN ('lock_timeout','statement_timeout') AND unit='ms' ORDER BY name"
    ).fetchall()
    values = {value["name"]: value["milliseconds"] for value in row}
    _require(set(values) == {"lock_timeout", "statement_timeout"}, "TIMEOUT_INVALID")
    for name, cap in (("lock_timeout", 5000), ("statement_timeout", 10000)):
        current = values[name]
        _require(type(current) is int and current >= 0, "TIMEOUT_INVALID")
        milliseconds = cap if current == 0 else min(current, cap)
        _require(_guard(connection, state, ack) == pin, "DATABASE_CHANGED")
        connection.execute("SELECT pg_catalog.set_config(%s,%s,true)", (name, f"{milliseconds}ms"))


_COLUMNS_SQL = """
SELECT c.relname AS table_name, a.attname AS column_name,
 (c.relowner=%s AND c.relkind='r' AND NOT c.relrowsecurity AND NOT c.relforcerowsecurity) AS safe
FROM pg_catalog.pg_class c JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace
JOIN pg_catalog.pg_attribute a ON a.attrelid=c.oid AND a.attnum>0 AND NOT a.attisdropped
WHERE n.nspname='app' AND c.relname=ANY(%s) ORDER BY c.relname,a.attnum LIMIT 1025
"""


def _columns(connection: _Connection, pin: _DatabasePin) -> dict[str, tuple[str, ...]]:
    rows = connection.execute(_COLUMNS_SQL, (pin.owner_oid, list(_IAM))).fetchall()
    _require(0 < len(rows) <= 1024, "IAM_INVALID")
    columns: dict[str, list[str]] = {name: [] for name in _IAM}
    seen: dict[str, set[str]] = {name: set() for name in _IAM}
    for row in rows:
        table, column = row["table_name"], row["column_name"]
        _require(
            table in columns
            and type(column) is str
            and re.fullmatch(r"[a-z][a-z0-9_]{0,62}", column) is not None
            and row["safe"] is True
            and column not in seen[table],
            "IAM_INVALID",
        )
        columns[table].append(column)
        seen[table].add(column)
    _require(all(columns.values()), "IAM_INVALID")
    return {name: tuple(values) for name, values in columns.items()}


_NON_IAM_SQL = """
SELECT * FROM (
 SELECT 'TABLE' AS kind,n.nspname AS schema_name,c.oid::bigint AS object_oid,0 AS member,
 p.privilege,pg_catalog.has_table_privilege(%s,c.oid,p.privilege) AS allowed
 FROM pg_catalog.pg_class c JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace
 CROSS JOIN (VALUES('SELECT'),('INSERT'),('UPDATE'),('DELETE'),('TRUNCATE'),
  ('REFERENCES'),('TRIGGER'),('MAINTAIN')) p(privilege)
 WHERE n.nspname IN('app','public') AND c.relkind IN('r','p')
  AND NOT(n.nspname='app' AND c.relname=ANY(%s))
 UNION ALL
 SELECT 'COLUMN',n.nspname,c.oid::bigint,a.attnum,p.privilege,
 pg_catalog.has_column_privilege(%s,c.oid,a.attname,p.privilege)
 FROM pg_catalog.pg_class c JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace
 JOIN pg_catalog.pg_attribute a ON a.attrelid=c.oid AND a.attnum>0 AND NOT a.attisdropped
 CROSS JOIN (VALUES('SELECT'),('INSERT'),('UPDATE'),('REFERENCES')) p(privilege)
 WHERE n.nspname IN('app','public') AND c.relkind IN('r','p')
  AND NOT(n.nspname='app' AND c.relname=ANY(%s))
 UNION ALL
 SELECT 'SEQUENCE',n.nspname,c.oid::bigint,0,p.privilege,
 pg_catalog.has_sequence_privilege(%s,c.oid,p.privilege)
 FROM pg_catalog.pg_class c JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace
 CROSS JOIN (VALUES('SELECT'),('UPDATE'),('USAGE')) p(privilege)
 WHERE n.nspname IN('app','public') AND c.relkind='S'
 UNION ALL
 SELECT 'FUNCTION',n.nspname,p.oid::bigint,0,'EXECUTE',
 pg_catalog.has_function_privilege(%s,p.oid,'EXECUTE')
 FROM pg_catalog.pg_proc p JOIN pg_catalog.pg_namespace n ON n.oid=p.pronamespace
 WHERE n.nspname IN('app','public')
 AND NOT(n.nspname='public' AND p.proname='eom_fence_operator_authorization_v1')
) preserved ORDER BY kind,schema_name,object_oid,member,privilege LIMIT 20001
"""


def _non_iam_sha(connection: _Connection, pin: _DatabasePin) -> str:
    rows = connection.execute(
        _NON_IAM_SQL,
        (
            pin.runtime_oid,
            list(_IAM),
            pin.runtime_oid,
            list(_IAM),
            pin.runtime_oid,
            pin.runtime_oid,
        ),
    ).fetchall()
    _require(0 < len(rows) <= _MAX_METADATA, "METADATA_INVALID")
    values: list[tuple[object, ...]] = []
    for row in rows:
        _require(
            row["kind"] in {"TABLE", "COLUMN", "SEQUENCE", "FUNCTION"}
            and row["schema_name"] in {"app", "public"}
            and type(row["object_oid"]) is int
            and 0 < row["object_oid"] <= 2**32 - 1
            and type(row["member"]) is int
            and 0 <= row["member"] <= 32767
            and row["privilege"]
            in {
                "SELECT",
                "INSERT",
                "UPDATE",
                "DELETE",
                "TRUNCATE",
                "REFERENCES",
                "TRIGGER",
                "MAINTAIN",
                "USAGE",
                "EXECUTE",
            }
            and type(row["allowed"]) is bool,
            "METADATA_INVALID",
        )
        values.append(
            tuple(
                row[name]
                for name in ("kind", "schema_name", "object_oid", "member", "privilege", "allowed")
            )
        )
    _require(len(set(values)) == len(values), "METADATA_INVALID")
    raw = json.dumps(values, ensure_ascii=True, separators=(",", ":")).encode("ascii")
    return "sha256:" + hashlib.sha256(raw).hexdigest()


_ROUTINE_SQL = """
SELECT p.oid::bigint AS oid,
 (p.proowner=%s AND p.prokind='f' AND p.pronargs=1 AND p.proargtypes='25'::pg_catalog.oidvector
 AND p.prorettype='pg_catalog.void'::pg_catalog.regtype
 AND p.proargnames=ARRAY['requested_operator_id']::text[] AND p.proallargtypes IS NULL
 AND p.proargmodes IS NULL AND p.pronargdefaults=0 AND p.provariadic=0
 AND NOT p.proretset AND NOT p.proisstrict AND NOT p.proleakproof AND p.prosupport=0
 AND l.lanname='plpgsql' AND p.prosecdef AND p.provolatile='v' AND p.proparallel='u'
 AND p.proconfig=ARRAY['search_path=pg_catalog, pg_temp']::text[] AND p.prosrc=%s) AS exact,
 (SELECT count(*)=2 AND count(DISTINCT acl.grantee)=2 AND bool_and(
 acl.grantor=%s AND acl.grantee IN(%s,%s) AND acl.privilege_type='EXECUTE' AND NOT acl.is_grantable)
 FROM pg_catalog.aclexplode(COALESCE(p.proacl,pg_catalog.acldefault('f',p.proowner))) acl) AS acl_ok
FROM pg_catalog.pg_proc p JOIN pg_catalog.pg_namespace n ON n.oid=p.pronamespace
JOIN pg_catalog.pg_language l ON l.oid=p.prolang
WHERE n.nspname='public' AND p.proname='eom_fence_operator_authorization_v1' ORDER BY p.oid LIMIT 2
"""
_IAM_SQL = """
SELECT bool_and(c.oid IS NOT NULL AND pg_catalog.has_table_privilege(%s,c.oid,'SELECT')=iam.readable
 AND (iam.readable OR NOT pg_catalog.has_any_column_privilege(%s,c.oid,'SELECT'))
 AND NOT pg_catalog.has_table_privilege(%s,c.oid,
  'INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER,MAINTAIN')
 AND NOT pg_catalog.has_any_column_privilege(%s,c.oid,'INSERT,UPDATE,REFERENCES')) AS limited,
 pg_catalog.has_table_privilege(%s,'app.operators','INSERT,UPDATE') AS baseline_writes
FROM (VALUES('operators',true),('roles',true),('permissions',true),('role_permissions',true),
 ('operator_role_assignments',true),('operator_credentials',false),('api_sessions',false),
 ('api_tokens',false),('operator_events',false)) iam(table_name,readable)
LEFT JOIN pg_catalog.pg_class c ON c.relnamespace=%s AND c.relname=iam.table_name
"""
_SCHEMA_TEMP_SQL = """
SELECT pg_catalog.has_schema_privilege(%s,'app','USAGE')
 AND pg_catalog.has_schema_privilege(%s,'public','USAGE')
 AND NOT pg_catalog.has_schema_privilege(%s,'app','CREATE')
 AND NOT pg_catalog.has_schema_privilege(%s,'public','CREATE') AS schemas_ok,
 pg_catalog.has_database_privilege(%s,pg_catalog.current_database(),'TEMP') AS runtime_temp,
 NOT EXISTS(SELECT 1 FROM pg_catalog.pg_database d CROSS JOIN LATERAL pg_catalog.aclexplode(
 COALESCE(d.datacl,pg_catalog.acldefault('d',d.datdba))) acl
 WHERE d.datname=pg_catalog.current_database() AND acl.grantee=0
 AND acl.privilege_type='TEMPORARY') AS public_temp_denied
"""


def _routine(connection: _Connection, pin: _DatabasePin, *, absent: bool = False) -> None:
    rows = connection.execute(
        _ROUTINE_SQL,
        (
            pin.owner_oid,
            OPERATOR_AUTHORIZATION_FENCE_BODY,
            pin.owner_oid,
            pin.owner_oid,
            pin.runtime_oid,
        ),
    ).fetchall()
    _require(
        not rows
        if absent
        else len(rows) == 1 and rows[0]["exact"] is True and rows[0]["acl_ok"] is True,
        "ROUTINE_INVALID",
    )


def _profile(connection: _Connection, pin: _DatabasePin, *, baseline: bool = False) -> None:
    row = connection.execute(_IAM_SQL, (pin.runtime_oid,) * 5 + (pin.app_oid,)).fetchone()
    _require(row is not None, "IAM_INVALID")
    assert row is not None
    _require(row["baseline_writes"] is True if baseline else row["limited"] is True, "IAM_INVALID")
    schema = connection.execute(_SCHEMA_TEMP_SQL, (pin.runtime_oid,) * 5).fetchone()
    _require(schema is not None, "SCHEMA_INVALID")
    assert schema is not None
    _require(
        schema["schemas_ok"] is True
        and schema["public_temp_denied"] is True
        and schema["runtime_temp"] is (not baseline),
        "SCHEMA_INVALID",
    )
    if not baseline:
        _routine(connection, pin)


def _statements(
    manifest: TestDatabaseManifest, columns: dict[str, tuple[str, ...]]
) -> tuple[str | sql.SQL | sql.Composed, ...]:
    role = sql.Identifier(manifest.runtime_role)
    values: list[str | sql.SQL | sql.Composed] = []
    for table in _IAM:
        target = sql.Identifier("app", table)
        names = sql.SQL(", ").join(sql.Identifier(name) for name in columns[table])
        values.extend(
            (
                sql.SQL("REVOKE ALL PRIVILEGES ON TABLE {} FROM {}").format(target, role),
                sql.SQL(
                    "REVOKE SELECT ({0}), INSERT ({0}), UPDATE ({0}), REFERENCES ({0}) "
                    "ON TABLE {1} FROM {2}"
                ).format(names, target, role),
            )
        )
    values.extend(
        (
            sql.SQL("GRANT SELECT ON TABLE {} TO {}").format(
                sql.SQL(", ").join(sql.Identifier("app", name) for name in _READ_IAM), role
            ),
            sql.SQL("GRANT USAGE ON SCHEMA app, public TO {}").format(role),
            sql.SQL("GRANT TEMPORARY ON DATABASE {} TO {}").format(
                sql.Identifier(manifest.database), role
            ),
            OPERATOR_AUTHORIZATION_FENCE_CREATE_SQL,
            OPERATOR_AUTHORIZATION_FENCE_REVOKE_PUBLIC_SQL,
            sql.SQL(
                "GRANT EXECUTE ON FUNCTION public.eom_fence_operator_authorization_v1(text) TO {}"
            ).format(role),
        )
    )
    return tuple(values)


def _receipt(state: _State, pin: _DatabasePin, non_iam: str, *, phase: str) -> bytes:
    values = {
        "profile": PROFILE,
        "test_id": state.manifest.test_id,
        "manifest_sha256": state.manifest_file.sha256,
        "owner_env_sha256": state.owner_file.sha256,
        "runtime_env_sha256": state.runtime_file.sha256,
        "migration": CURRENT_MIGRATION_REVISION,
        "body_sha256": OPERATOR_AUTHORIZATION_FENCE_BODY_SHA256,
        "database_oid": str(pin.database_oid),
        "owner_oid": str(pin.owner_oid),
        "runtime_oid": str(pin.runtime_oid),
        "app_oid": str(pin.app_oid),
        "public_oid": str(pin.public_oid),
        "iam_oids": ",".join(str(value) for value in pin.iam_oids),
        "non_iam_sha256": non_iam,
        "phase": phase,
    }
    return "".join(f"{name}={values[name]}\n" for name in sorted(values)).encode("ascii")


def _transaction_phase(
    connection: _Connection,
    state: _State,
    ack: str,
    receipt: _PinnedFile | None,
    started: _PinnedFile | None,
) -> tuple[_DatabasePin, str]:
    commit_pending = False
    try:
        with connection.transaction():
            pin = _guard(connection, state, ack)
            _waits(connection, state, ack, pin)
            columns = _columns(connection, pin)
            non_iam = _non_iam_sha(connection, pin)
            if receipt is not None:
                _profile(connection, pin)
                _require(
                    receipt.raw == _receipt(state, pin, non_iam, phase="PREPARED"),
                    "RECEIPT_INVALID",
                )
                _require(
                    started is not None
                    and started.raw == _receipt(state, pin, non_iam, phase="STARTED"),
                    "RECEIPT_INVALID",
                )
            elif started is not None:
                # Never repair/reapply a committed or rolled-back partial attempt.
                _require(
                    started.raw == _receipt(state, pin, non_iam, phase="STARTED"),
                    "RECEIPT_INVALID",
                )
                try:
                    _profile(connection, pin)
                except FenceProfileError:
                    raise FenceProfileError("PREPARATION_PARTIAL") from None
                raise FenceProfileError("PREPARED_WITHOUT_RECEIPT")
            else:
                _routine(connection, pin, absent=True)
                _profile(connection, pin, baseline=True)
                state.assert_current()
                _require(_guard(connection, state, ack) == pin, "DATABASE_CHANGED")
                state.write_once(_STARTED, _receipt(state, pin, non_iam, phase="STARTED"))
                for statement in _statements(state.manifest, columns):
                    _require(_guard(connection, state, ack) == pin, "DATABASE_CHANGED")
                    connection.execute(statement)
                _profile(connection, pin)
                _require(_non_iam_sha(connection, pin) == non_iam, "NON_IAM_CHANGED")
            _require(_guard(connection, state, ack) == pin, "DATABASE_CHANGED")
            commit_pending = True
        return pin, non_iam
    except psycopg.Error:
        raise FenceProfileError(
            "COMMIT_UNCERTAIN" if commit_pending else "TRANSACTION_FAILED"
        ) from None


def _database_phase(state: _State, urls: _Urls, ack: str, *, prepare: bool) -> None:
    receipt, started = state.optional(_RECEIPT), state.optional(_STARTED)
    _require(receipt is None or started is not None, "RECEIPT_INVALID")
    _require(prepare or receipt is not None, "NOT_PREPARED")
    with psycopg.connect(
        urls.owner, connect_timeout=5, autocommit=False, row_factory=dict_row
    ) as connection:
        expired = Event()
        state.expired = expired

        def cancel_owned_query() -> None:
            # Includes the first catalog guard before transaction-local GUC caps exist.
            expired.set()
            with suppress(psycopg.Error):
                connection.cancel_safe(timeout=2)

        deadline = Timer(90, cancel_owned_query)
        deadline.daemon = True
        deadline.start()
        try:
            pin, non_iam = _transaction_phase(connection, state, ack, receipt, started)
            _require(not expired.is_set(), "TRANSACTION_UNCERTAIN")
        finally:
            deadline.cancel()
        # The transaction has committed. No false rollback/automatic repair after this point.
        if receipt is None:
            try:
                state.write_once(_RECEIPT, _receipt(state, pin, non_iam, phase="PREPARED"))
            except Exception:
                raise FenceProfileError("PREPARED_WITHOUT_RECEIPT") from None


def _run_cases(environment: dict[str, str]) -> None:
    process = subprocess.Popen(
        (
            str(_PYTHON),
            "-m",
            "pytest",
            "-q",
            "tests/integration/test_operator_authorization_fence.py",
        ),
        cwd=_REPOSITORY,
        env=environment,
        stdin=subprocess.DEVNULL,
        start_new_session=True,
    )
    try:
        code = process.wait(timeout=180)
    except BaseException:
        # Kill only the Popen-owned, still-unreaped private test session, including test children.
        with suppress(ProcessLookupError):
            os.killpg(process.pid, signal.SIGKILL)
        process.wait(timeout=5)
        raise FenceProfileError("TESTS_UNCERTAIN") from None
    _require(code == 0, "TESTS_FAILED")


def run(action: str, path: Path, ack: str) -> None:
    _require(action in {"operator-fence-prepare", "operator-fence-tests"}, "ARGS_INVALID")
    account = pwd.getpwnam("eom")
    _require(
        os.geteuid() == account.pw_uid
        and os.getegid() == account.pw_gid
        and Path(sys.executable) == _PYTHON,
        "CONTEXT_INVALID",
    )
    with ExitStack() as stack:
        state = _State(path, account.pw_uid, account.pw_gid, stack)
        _require(ack == PROFILE + ":" + state.manifest.test_id, "ACK_INVALID")
        state.lock()
        urls = _urls(state)
        _database_phase(state, urls, ack, prepare=action == "operator-fence-prepare")
        if action == "operator-fence-tests":
            state.assert_current()
            environment = {
                "PATH": "/usr/bin:/bin",
                "TZ": "UTC",
                "LANG": "C.UTF-8",
                "PYTHONPATH": ":".join(str(_REPOSITORY / path) for path in _SOURCE_PATHS),
                "EOM_DATABASE_URL": urls.owner.replace("postgresql://", "postgresql+psycopg://", 1),
                "EOM_API_TEST_STATE": str(state.path),
                "EOM_RUN_INTEGRATION": "1",
                "EOM_RUN_API_INTEGRATION": "1",
                "EOM_RUN_OPERATOR_FENCE_INTEGRATION": "1",
            }
            _run_cases(environment)
            state.assert_current()
            _database_phase(state, urls, ack, prepare=False)


def main() -> int:
    try:
        _require(len(sys.argv) == 4, "ARGS_INVALID")
        run(sys.argv[1], Path(sys.argv[2]), sys.argv[3])
        print("OPERATOR_FENCE_TEST_PROFILE=VERIFIED")
        return 0
    except Exception as error:
        code = (
            error.code
            if isinstance(error, FenceProfileError)
            else "OPERATOR_FENCE_TEST_UNAVAILABLE"
        )
        print(code, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
