"""DB-owner transaction adapter for the exact prelaunch reset application.

No runtime API role, model DTO or worker can grant this authority. Named owner
adapters select their own tables/triggers; identifiers are never accepted over HTTP.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterator
from contextlib import contextmanager

import psycopg
from psycopg import sql


class MetadataResetTransaction:
    def __init__(self, cursor: psycopg.Cursor[tuple[object, ...]]) -> None:
        self.cursor = cursor
        self.counts: dict[str, int] = {}
        self._mutation_tables: frozenset[str] = frozenset()

    def require_owner(self, tables: tuple[str, ...]) -> None:
        self.cursor.execute(
            "SELECT session_user,current_user,r.rolsuper,"
            "current_setting('transaction_read_only') FROM pg_roles r WHERE "
            "r.rolname=current_user"
        )
        row = self.cursor.fetchone()
        if row is None or row[0] != row[1] or row[3] != "off":
            raise ValueError("ITEM_RESET_OWNER_REQUIRED")
        self.cursor.execute(
            (
                "SELECT c.relname,pg_get_userbyid(c.relowner) FROM pg_class c JOIN "
                "pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='app' AND "
                "c.relkind='r' AND c.relname=ANY(%s)"
            ),
            (list(tables),),
        )
        owners = self.cursor.fetchall()
        if len(owners) != len(tables) or (not row[2] and any(x[1] != row[0] for x in owners)):
            raise ValueError("ITEM_RESET_OWNER_REQUIRED")

    def freeze_writes(self) -> None:
        self.require_owner(("jobs", "artifacts", "artifact_revisions"))
        self.cursor.execute(
            "SELECT pg_try_advisory_xact_lock(hashtextextended('eom:prelaunch-reset:20261028',0))"
        )
        if self.cursor.fetchone() != (True,):
            raise ValueError("ITEM_RESET_BUSY")
        self.cursor.execute(
            "SELECT c.relname FROM pg_class c JOIN pg_namespace n ON "
            "n.oid=c.relnamespace WHERE n.nspname='app' AND c.relkind IN ('r','p') ORDER "
            "BY c.relname"
        )
        names = tuple(str(row[0]) for row in self.cursor.fetchall())
        self.cursor.execute(
            sql.SQL("LOCK TABLE {} IN SHARE ROW EXCLUSIVE MODE NOWAIT").format(
                sql.SQL(",").join(sql.Identifier("app", name) for name in names)
            )
        )

    @contextmanager
    def owner_mutations(
        self, tables: tuple[str, ...], triggers: tuple[tuple[str, str], ...]
    ) -> Iterator[None]:
        self.require_owner(tables)
        for table, trigger in triggers:
            if table not in tables:
                raise ValueError("ITEM_RESET_TRIGGER_OWNER_MISMATCH")
            self.cursor.execute(
                "SELECT tgenabled FROM pg_trigger WHERE tgrelid=%s::regclass AND tgname=%s",
                (f"app.{table}", trigger),
            )
            if self.cursor.fetchone() != ("O",):
                raise ValueError("ITEM_RESET_TRIGGER_STATE_INVALID")
            self.cursor.execute(
                sql.SQL("ALTER TABLE {} DISABLE TRIGGER {}").format(
                    sql.Identifier("app", table), sql.Identifier(trigger)
                )
            )
        previous = self._mutation_tables
        self._mutation_tables = previous | frozenset(tables)
        try:
            yield
        except BaseException:
            # PostgreSQL rolls the trigger DDL back with this root. Do not mask
            # the original failure by issuing more SQL in an aborted transaction.
            raise
        else:
            for table, trigger in reversed(triggers):
                self.cursor.execute(
                    sql.SQL("ALTER TABLE {} ENABLE TRIGGER {}").format(
                        sql.Identifier("app", table), sql.Identifier(trigger)
                    )
                )
        finally:
            self._mutation_tables = previous

    def require_component(self, tables: tuple[str, ...]) -> None:
        if not set(tables).issubset(self._mutation_tables):
            raise ValueError("ITEM_RESET_COMPONENT_SCOPE_REQUIRED")
        self.require_owner(tables)

    def record(self, label: str, count: int) -> None:
        self.counts[label] = self.counts.get(label, 0) + count

    def execute(self, query: str | sql.SQL | sql.Composed, params: tuple[object, ...] = ()) -> None:
        self.cursor.execute(query, params)

    def fetchone(self) -> tuple[object, ...] | None:
        return self.cursor.fetchone()

    def fetchall(self) -> list[tuple[object, ...]]:
        return self.cursor.fetchall()

    def fetchmany(self, size: int) -> list[tuple[object, ...]]:
        return self.cursor.fetchmany(size)

    @property
    def rowcount(self) -> int:
        return self.cursor.rowcount


def reset_read_value(
    cursor: MetadataResetTransaction, query: str, params: tuple[object, ...]
) -> object:
    cursor.cursor.execute(query, params)
    row = cursor.cursor.fetchone()
    if row is None:
        raise ValueError("ITEM_RESET_EXPECTED_ROW_MISSING")
    return row[0]


def reset_delete(
    cursor: MetadataResetTransaction, label: str, query: str, params: tuple[object, ...]
) -> None:
    cursor.cursor.execute(query, params)
    cursor.record(label, cursor.cursor.rowcount)


def reset_rows_digest(
    cursor: MetadataResetTransaction,
    queries: tuple[tuple[str, tuple[object, ...]], ...],
) -> str:
    """Hash stable ordered metadata without retaining/copying complete payloads."""
    digest = hashlib.sha256()
    for query, parameters in queries:
        digest.update(query.encode())
        cursor.execute(query, parameters)
        while rows := cursor.fetchmany(128):
            for row in rows:
                if len(row) != 1 or not isinstance(row[0], str):
                    raise ValueError("ITEM_RESET_FINGERPRINT_QUERY_INVALID")
                data = row[0].encode()
                digest.update(len(data).to_bytes(8, "big"))
                digest.update(data)
    return digest.hexdigest()
