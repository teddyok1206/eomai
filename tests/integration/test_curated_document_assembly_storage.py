"""Guarded PostgreSQL checks for immutable mixed-source assembly storage."""

from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier
from urllib.parse import unquote, urlsplit
from uuid import uuid4

import pytest
from eom_orchestrator.database import build_engine
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError

from scripts.api.testdb_guard import TestDatabaseManifest as DisposableManifest
from scripts.api.testdb_guard import validate_state_directory

pytestmark = [pytest.mark.integration, pytest.mark.api_integration]


def test_pinned_assembly_revision_is_immutable_and_idempotency_is_unique() -> None:
    if os.environ.get("EOM_RUN_API_INTEGRATION") != "1":
        pytest.skip("use guarded testdb_run.sh external-item-tests")
    state = validate_state_directory(Path(os.environ["EOM_EXTERNAL_ITEM_TEST_STATE"]))
    disposable = DisposableManifest.load(state / "manifest.json")
    parsed = urlsplit(os.environ["EOM_DATABASE_URL"])
    assert parsed.username == disposable.owner_role
    assert unquote(parsed.path.removeprefix("/")) == disposable.database

    engine = build_engine(os.environ["EOM_DATABASE_URL"])
    assembly_id = "assembly_" + "a" * 32
    revision_id = "assemblyrev_" + "a" * 32
    hash_value = "sha256:" + "a" * 64
    try:
        with engine.connect() as connection:
            outer = connection.begin()
            try:
                connection.execute(
                    text(
                        "INSERT INTO app.curated_document_assemblies "
                        "(assembly_id,created_by) VALUES (:assembly,:actor)"
                    ),
                    {"assembly": assembly_id, "actor": "operator-test"},
                )
                connection.execute(
                    text(
                        "INSERT INTO app.curated_document_assembly_revisions "
                        "(assembly_revision_id,assembly_id,revision_number,revision_state,"
                        "selection_sha256,request_sha256,manifest_sha256,canonical_document,"
                        "idempotency_key,created_by,created_at) "
                        "VALUES (:revision,:assembly,1,'INPUT_PINNED',:hash,:hash,:hash,"
                        "CAST(:manifest AS jsonb),'test-replay-key','operator-test',now())"
                    ),
                    {
                        "revision": revision_id,
                        "assembly": assembly_id,
                        "hash": hash_value,
                        "manifest": "{}",
                    },
                )
                connection.execute(
                    text(
                        "UPDATE app.curated_document_assemblies "
                        "SET current_revision_id=:revision WHERE assembly_id=:assembly"
                    ),
                    {"revision": revision_id, "assembly": assembly_id},
                )

                with pytest.raises(DBAPIError) as duplicate, connection.begin_nested():
                    connection.execute(
                        text(
                            "INSERT INTO app.curated_document_assembly_revisions "
                            "(assembly_revision_id,assembly_id,revision_number,"
                            "revision_state,selection_sha256,request_sha256,"
                            "manifest_sha256,canonical_document,idempotency_key,"
                            "created_by,created_at) VALUES (:revision,:assembly,2,"
                            "'INPUT_PINNED',:hash,:hash,:hash,CAST(:manifest AS jsonb),"
                            "'test-replay-key','operator-test',now())"
                        ),
                        {
                            "revision": "assemblyrev_" + "b" * 32,
                            "assembly": assembly_id,
                            "hash": hash_value,
                            "manifest": "{}",
                        },
                    )
                assert duplicate.value.orig.sqlstate == "23505"

                with pytest.raises(DBAPIError) as immutable, connection.begin_nested():
                    connection.execute(
                        text(
                            "UPDATE app.curated_document_assembly_revisions "
                            "SET revision_state='INPUT_PINNED' "
                            "WHERE assembly_revision_id=:revision"
                        ),
                        {"revision": revision_id},
                    )
                assert immutable.value.orig.sqlstate == "23514"

                with pytest.raises(DBAPIError) as deleted, connection.begin_nested():
                    connection.execute(
                        text(
                            "DELETE FROM app.curated_document_assembly_revisions "
                            "WHERE assembly_revision_id=:revision"
                        ),
                        {"revision": revision_id},
                    )
                assert deleted.value.orig.sqlstate == "23514"

                with pytest.raises(DBAPIError) as invalid_pointer, connection.begin_nested():
                    connection.execute(
                        text(
                            "INSERT INTO app.curated_document_assembly_placements "
                            "(assembly_revision_id,position,placement_kind) "
                            "VALUES (:revision,1,'EXTERNAL_SOURCE_DOCUMENT')"
                        ),
                        {"revision": revision_id},
                    )
                assert invalid_pointer.value.orig.sqlstate == "23514"
            finally:
                outer.rollback()
    finally:
        engine.dispose()


def test_concurrent_same_actor_and_key_accepts_one_revision() -> None:
    if os.environ.get("EOM_RUN_API_INTEGRATION") != "1":
        pytest.skip("use guarded testdb_run.sh external-item-tests")
    state = validate_state_directory(Path(os.environ["EOM_EXTERNAL_ITEM_TEST_STATE"]))
    disposable = DisposableManifest.load(state / "manifest.json")
    parsed = urlsplit(os.environ["EOM_DATABASE_URL"])
    assert parsed.username == disposable.owner_role
    assert unquote(parsed.path.removeprefix("/")) == disposable.database

    engine = build_engine(os.environ["EOM_DATABASE_URL"])
    suffix = uuid4().hex
    actor = "operator-" + suffix
    key = "concurrent-" + suffix
    barrier = Barrier(2)
    hash_value = "sha256:" + "a" * 64

    def insert(index: int) -> str:
        assembly_id = "assembly_" + f"{index:x}" + suffix[1:]
        revision_id = "assemblyrev_" + f"{index:x}" + suffix[1:]
        try:
            with engine.begin() as connection:
                connection.execute(text("SET LOCAL statement_timeout = '15s'"))
                connection.execute(
                    text(
                        "INSERT INTO app.curated_document_assemblies "
                        "(assembly_id,created_by) VALUES (:assembly,:actor)"
                    ),
                    {"assembly": assembly_id, "actor": actor},
                )
                barrier.wait(timeout=10)
                connection.execute(
                    text(
                        "INSERT INTO app.curated_document_assembly_revisions "
                        "(assembly_revision_id,assembly_id,revision_number,revision_state,"
                        "selection_sha256,request_sha256,manifest_sha256,canonical_document,"
                        "idempotency_key,created_by,created_at) "
                        "VALUES (:revision,:assembly,1,'INPUT_PINNED',:hash,:hash,:hash,"
                        "CAST(:manifest AS jsonb),:key,:actor,now())"
                    ),
                    {
                        "revision": revision_id,
                        "assembly": assembly_id,
                        "hash": hash_value,
                        "manifest": "{}",
                        "key": key,
                        "actor": actor,
                    },
                )
            return "COMMITTED"
        except IntegrityError as exc:
            assert exc.orig.sqlstate == "23505"
            return "DUPLICATE"

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = tuple(pool.map(insert, (1, 2)))
        assert sorted(outcomes) == ["COMMITTED", "DUPLICATE"]
        with engine.connect() as connection:
            assert (
                connection.execute(
                    text(
                        "SELECT count(*) FROM app.curated_document_assembly_revisions "
                        "WHERE created_by=:actor AND idempotency_key=:key"
                    ),
                    {"actor": actor, "key": key},
                ).scalar_one()
                == 1
            )
    finally:
        engine.dispose()
