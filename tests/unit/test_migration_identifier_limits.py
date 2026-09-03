from __future__ import annotations

import re
from importlib import import_module
from typing import Protocol, cast

import pytest
import sqlalchemy as sa

POSTGRESQL_IDENTIFIER_MAX_BYTES = 63
MIGRATION_MODULES = (
    "migrations.versions.20260901_0024_item_origin_occurrence",
    "migrations.versions.20260901_0025_legacy_assessment_bundle",
    "migrations.versions.20260903_0026_legacy_item_editorial_compatibility",
    "migrations.versions.20260903_0027_legacy_item_extraction_batches",
)


class _MigrationModule(Protocol):
    op: object

    def upgrade(self) -> None: ...

    def downgrade(self) -> None: ...


class _MigrationOperationRecorder:
    def __init__(self) -> None:
        self.identifiers: list[tuple[str, str]] = []

    def _record(self, kind: str, name: object) -> None:
        if name is not None:
            self.identifiers.append((kind, str(name)))

    def create_table(self, name: str, *elements: object, **_: object) -> None:
        self._record("table", name)
        for element in elements:
            if isinstance(element, sa.Column):
                self._record("column", element.name)
            elif isinstance(element, sa.Constraint):
                self._record("constraint", element.name)

    def create_unique_constraint(self, name: str, *_: object, **__: object) -> None:
        self._record("constraint", name)

    def create_foreign_key(self, name: str, *_: object, **__: object) -> None:
        self._record("constraint", name)

    def create_index(self, name: str, *_: object, **__: object) -> None:
        self._record("index", name)

    def drop_index(self, name: str, *_: object, **__: object) -> None:
        self._record("index", name)

    def drop_constraint(self, name: str, *_: object, **__: object) -> None:
        self._record("constraint", name)

    def drop_table(self, name: str, *_: object, **__: object) -> None:
        self._record("table", name)

    def execute(self, statement: object) -> None:
        for action, kind, name in re.findall(
            r"\b(CREATE|DROP)\s+(FUNCTION|TRIGGER)\s+"
            r"(?:IF\s+EXISTS\s+)?([A-Za-z_][A-Za-z0-9_]*)",
            str(statement),
            flags=re.IGNORECASE,
        ):
            self._record(f"{action.lower()}_{kind.lower()}", name)


@pytest.mark.parametrize("module_name", MIGRATION_MODULES)
def test_explicit_postgresql_migration_identifiers_fit_server_limit(
    module_name: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = cast(_MigrationModule, import_module(module_name))
    recorder = _MigrationOperationRecorder()
    monkeypatch.setattr(module, "op", recorder)

    module.upgrade()
    module.downgrade()

    too_long = [
        (kind, name, len(name.encode("utf-8")))
        for kind, name in recorder.identifiers
        if len(name.encode("utf-8")) > POSTGRESQL_IDENTIFIER_MAX_BYTES
    ]
    assert not too_long
    for kind in ("function", "trigger"):
        created = {name for action, name in recorder.identifiers if action == f"create_{kind}"}
        dropped = {name for action, name in recorder.identifiers if action == f"drop_{kind}"}
        assert created == dropped
