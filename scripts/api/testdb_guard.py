"""Pure safety guards for disposable Application API PostgreSQL databases."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

DATABASE_PREFIX = "eom_api_test_"
OWNER_PREFIX = "eom_api_test_owner_"
RUNTIME_PREFIX = "eom_api_test_runtime_"
STATE_PREFIX = "eom-api-testdb-"
MARKER_PREFIX = "EOM_API_DISPOSABLE_TEST_DB:"
PROTECTED_DATABASES = frozenset({"eom", "postgres", "template0", "template1"})
IDENTIFIER_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,62}$")
TEST_ID_PATTERN = re.compile(r"^[0-9]{14}_[a-f0-9]{8}$")


class TestDatabaseGuardError(ValueError):
    """The disposable database identity does not satisfy cleanup guards."""


@dataclass(frozen=True)
class TestDatabaseManifest:
    test_id: str
    database: str
    owner_role: str
    runtime_role: str

    @classmethod
    def create(cls, test_id: str) -> TestDatabaseManifest:
        if not TEST_ID_PATTERN.fullmatch(test_id):
            raise TestDatabaseGuardError("invalid disposable database test ID")
        suffix = test_id.replace("_", "")
        return cls(
            test_id=test_id,
            database=f"{DATABASE_PREFIX}{suffix}",
            owner_role=f"{OWNER_PREFIX}{suffix}",
            runtime_role=f"{RUNTIME_PREFIX}{suffix}",
        ).validated()

    @classmethod
    def load(cls, path: Path) -> TestDatabaseManifest:
        try:
            payload = json.loads(path.read_text(encoding="ascii"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise TestDatabaseGuardError("invalid disposable database manifest") from exc
        if not isinstance(payload, dict) or set(payload) != {
            "database",
            "owner_role",
            "runtime_role",
            "test_id",
        }:
            raise TestDatabaseGuardError("unexpected disposable database manifest fields")
        return cls(
            test_id=str(payload["test_id"]),
            database=str(payload["database"]),
            owner_role=str(payload["owner_role"]),
            runtime_role=str(payload["runtime_role"]),
        ).validated()

    def validated(self) -> TestDatabaseManifest:
        if not TEST_ID_PATTERN.fullmatch(self.test_id):
            raise TestDatabaseGuardError("invalid disposable database test ID")
        if not self._is_expected():
            raise TestDatabaseGuardError("disposable database names do not match the test ID")
        for identifier in (self.database, self.owner_role, self.runtime_role):
            if not IDENTIFIER_PATTERN.fullmatch(identifier):
                raise TestDatabaseGuardError("unsafe PostgreSQL identifier")
        if self.database in PROTECTED_DATABASES:
            raise TestDatabaseGuardError("protected PostgreSQL database")
        return self

    def _is_expected(self) -> bool:
        suffix = self.test_id.replace("_", "")
        return (
            self.database == f"{DATABASE_PREFIX}{suffix}"
            and self.owner_role == f"{OWNER_PREFIX}{suffix}"
            and self.runtime_role == f"{RUNTIME_PREFIX}{suffix}"
        )

    @property
    def marker(self) -> str:
        return f"{MARKER_PREFIX}{self.test_id}"

    def to_json(self) -> str:
        return (
            json.dumps(
                {
                    "database": self.database,
                    "owner_role": self.owner_role,
                    "runtime_role": self.runtime_role,
                    "test_id": self.test_id,
                },
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n"
        )


def validate_state_directory(path: Path) -> Path:
    try:
        resolved = path.resolve(strict=True)
    except OSError as exc:
        raise TestDatabaseGuardError("test database state is unavailable") from exc
    if path.is_symlink() or resolved.parent != Path("/tmp"):
        raise TestDatabaseGuardError("test database state must be a direct /tmp child")
    if not resolved.name.startswith(STATE_PREFIX):
        raise TestDatabaseGuardError("test database state prefix mismatch")
    return resolved


def validate_catalog_metadata(
    manifest: TestDatabaseManifest,
    *,
    database_owner: str | None,
    database_comment: str | None,
    owner_comment: str | None,
    runtime_comment: str | None = None,
    require_runtime: bool,
) -> None:
    manifest.validated()
    if database_owner != manifest.owner_role:
        raise TestDatabaseGuardError("disposable database owner mismatch")
    if database_comment != manifest.marker or owner_comment != manifest.marker:
        raise TestDatabaseGuardError("disposable database marker mismatch")
    if require_runtime and runtime_comment != manifest.marker:
        raise TestDatabaseGuardError("disposable runtime role marker mismatch")


def validate_application_schema_metadata(
    manifest: TestDatabaseManifest,
    *,
    schema_owner: str | None,
    schema_comment: str | None,
    effective_search_path: tuple[str, ...],
    has_usage: bool,
    has_create: bool,
) -> None:
    """Validate the production-equivalent migration schema prerequisite."""

    manifest.validated()
    if schema_owner != manifest.owner_role:
        raise TestDatabaseGuardError("disposable app schema owner mismatch")
    if schema_comment != manifest.marker:
        raise TestDatabaseGuardError("disposable app schema marker mismatch")
    if effective_search_path != ("app", "public"):
        raise TestDatabaseGuardError("disposable migration owner search path mismatch")
    if not has_usage or not has_create:
        raise TestDatabaseGuardError("disposable migration owner schema privilege mismatch")
