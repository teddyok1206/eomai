"""Disposable-only PostgreSQL history/owner/CAS tests, with no model or NAS access."""

import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier
from urllib.parse import unquote, urlsplit
from uuid import uuid4

import pytest
from eom_api.errors import ApiError
from eom_api.item_db_similarity_models import ItemDbSimilaritySearchRecord
from eom_api.services.item_db_similarity_state import item_db_search_operation_id
from eom_api.services.item_db_similarity_store import ItemDbSimilaritySearchStore
from eom_api_contracts.item_db_similarity import ItemDbSimilarityListInput
from eom_catalog_contracts.reference_query_prepare import ReferenceQueryPrepareRequestV4
from eom_identifiers import content_sha256
from eom_identity_service.models import OperatorRecord
from eom_orchestrator.database import build_engine
from sqlalchemy import delete, func, inspect, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from scripts.api.testdb_guard import TestDatabaseManifest as DisposableManifest
from scripts.api.testdb_guard import validate_state_directory
from tests.unit.test_item_db_similarity_application import query_reply
from tests.unit.test_item_db_similarity_selection import selected_case

pytestmark = [pytest.mark.integration, pytest.mark.api_integration]


@pytest.fixture
def database():
    if os.environ.get("EOM_RUN_API_INTEGRATION") != "1":
        pytest.skip("use guarded item-db-search-tests disposable purpose")
    directory = validate_state_directory(Path(os.environ["EOM_ITEM_DB_SEARCH_TEST_STATE"]))
    manifest = DisposableManifest.load(directory / "manifest.json")
    parsed = urlsplit(os.environ["EOM_DATABASE_URL"])
    assert parsed.username == manifest.owner_role
    assert unquote(parsed.path.removeprefix("/")) == manifest.database
    engine = build_engine(os.environ["EOM_DATABASE_URL"])
    actors = ("operator_" + uuid4().hex, "operator_" + uuid4().hex)
    with Session(engine) as session, session.begin():
        session.add_all(
            OperatorRecord(
                operator_id=actor,
                username=actor,
                normalized_username=actor,
                display_name="합성 검증 계정",
                status="ACTIVE",
                must_change_password=False,
                created_by="synthetic-disposable-test",
                role_version=1,
            )
            for actor in actors
        )
    store = ItemDbSimilaritySearchStore(engine, b"synthetic-disposable-cursor-key-32")
    try:
        yield engine, store, actors
    finally:
        with Session(engine) as session, session.begin():
            session.execute(
                delete(ItemDbSimilaritySearchRecord).where(
                    ItemDbSimilaritySearchRecord.operator_id.in_(actors)
                )
            )
            session.execute(delete(OperatorRecord).where(OperatorRecord.operator_id.in_(actors)))
        engine.dispose()


def prepared(store, actor, key="synthetic-owned-search-key"):
    value = selected_case()
    body = ItemDbSimilarityListInput(selections=(value.selection,))
    record = store.admit(actor, key, body)
    raw = value.query.model_dump(mode="json", exclude={"request_sha256"})
    raw.update(operation_id=item_db_search_operation_id(actor, key), idempotency_key=key)
    query = ReferenceQueryPrepareRequestV4.model_validate(
        raw | {"request_sha256": content_sha256(raw)}
    )
    return value, body, store.latch_query(actor, record.search_id, query)


def test_same_key_concurrency_creates_one_intent_and_replay_has_same_identity(database):
    engine, store, actors = database
    body = ItemDbSimilarityListInput(selections=(selected_case().selection,))
    barrier = Barrier(4)

    def admit(_ordinal):
        barrier.wait(timeout=10)
        return store.admit(actors[0], "synthetic-concurrent-search-key", body)

    with ThreadPoolExecutor(max_workers=4) as pool:
        rows = tuple(pool.map(admit, range(4)))
    assert len({row.search_id for row in rows}) == 1
    with Session(engine) as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(ItemDbSimilaritySearchRecord)
                .where(ItemDbSimilaritySearchRecord.operator_id == actors[0])
            )
            == 1
        )
    assert store.admit(actors[0], "synthetic-concurrent-search-key", body) == rows[0]
    with pytest.raises(ApiError) as raised:
        store.admit(
            actors[0], "synthetic-concurrent-search-key", body.model_copy(update={"top_k": 8})
        )
    assert raised.value.error_code == "ITEM_DB_SIMILARITY_REQUEST_CONFLICT"


def test_other_owner_has_no_history_or_result_selector_access(database):
    _engine, store, actors = database
    _value, _body, record = prepared(store, actors[0])
    with pytest.raises(ApiError) as raised:
        store.get(actors[1], record.search_id)
    assert raised.value.status == 404
    assert store.list_recent(actors[1], limit=20, cursor=None).data == ()


def test_complete_selector_survives_late_pending_and_query_pin_is_first_write(database):
    _engine, store, actors = database
    value, _body, record = prepared(store, actors[0])
    reply = query_reply(value, ready=True)
    reply = reply.model_copy(
        update={
            "operation_id": record.query.operation_id,
            "request_sha256": record.query.request_sha256,
        }
    )
    ready = store.observe(actors[0], record.search_id, reply)
    assert ready.state == "READY" and ready.children[0].selection is not None
    pending = reply.model_copy(
        update={
            "status": "PENDING",
            "selection": None,
            "children": tuple(
                child.model_copy(update={"state": "PENDING", "selection": None})
                for child in reply.children
            ),
        }
    )
    assert store.observe(actors[0], record.search_id, pending).children == ready.children
    assert store.get(actors[0], record.search_id).state == "READY"
    raw = record.query.model_dump(mode="json", exclude={"request_sha256"})
    raw["policy_sha256"] = "sha256:" + "f" * 64
    alternate = ReferenceQueryPrepareRequestV4.model_validate(
        raw | {"request_sha256": content_sha256(raw)}
    )
    assert store.latch_query(actors[0], record.search_id, alternate).query == record.query


def test_recent_history_keyset_is_stable_and_cross_owner_cursor_is_rejected(database):
    _engine, store, actors = database
    records = [
        prepared(store, actors[0], f"synthetic-history-key-{ordinal}")[2] for ordinal in range(3)
    ]
    page1 = store.list_recent(actors[0], limit=2, cursor=None)
    page2 = store.list_recent(actors[0], limit=2, cursor=page1.next_cursor)
    assert page1.has_more and not page2.has_more
    assert {value.search_id for value in (*page1.data, *page2.data)} == {
        value.search_id for value in records
    }
    with pytest.raises(ApiError) as raised:
        store.list_recent(actors[1], limit=2, cursor=page1.next_cursor)
    assert raised.value.error_code == "API_CURSOR_INVALID"


def test_table_contains_only_small_metadata_and_has_owner_key_indexes(database):
    engine, store, actors = database
    _value, _body, record = prepared(store, actors[0])
    indexes = {
        index["name"]
        for index in inspect(engine).get_indexes("item_db_similarity_searches", schema="app")
    }
    assert "ix_item_db_search_owner_recent" in indexes
    columns = inspect(engine).get_columns("item_db_similarity_searches", schema="app")
    assert not any("BYTEA" in str(column["type"]) for column in columns)
    with Session(engine) as session:
        row = session.get(ItemDbSimilaritySearchRecord, record.search_id)
        assert set(row.input_json) == {"schema_version", "selections", "top_k"}
        assert set(row.input_json["selections"][0]) == set(selected_case().selection.model_dump())
        assert (
            session.scalar(
                text(
                    "SELECT max(pg_column_size(input_json)) "
                    "FROM app.item_db_similarity_searches WHERE operator_id=:actor"
                ),
                {"actor": actors[0]},
            )
            < 65536
        )


def test_runtime_can_read_and_lock_history_but_cannot_rewrite_its_input_or_owner(database):
    _engine, store, actors = database
    _value, _body, record = prepared(store, actors[0])
    directory = validate_state_directory(Path(os.environ["EOM_ITEM_DB_SEARCH_TEST_STATE"]))
    private_env = directory / "runtime.env"
    if not private_env.exists():
        pytest.fail("reconcile the disposable runtime role before its privilege test")
    # Read the guarded private file as data; never echo or shell-evaluate credentials.
    assignments = dict(
        line.split("=", 1)
        for line in private_env.read_text().splitlines()
        if line and not line.startswith("#") and "=" in line
    )
    runtime_url = assignments["EOM_API_DATABASE_URL"]
    parsed = urlsplit(runtime_url)
    manifest = DisposableManifest.load(directory / "manifest.json")
    assert parsed.username == manifest.runtime_role
    assert unquote(parsed.path.removeprefix("/")) == manifest.database
    runtime = build_engine(runtime_url)
    try:
        with runtime.connect() as connection:
            transaction = connection.begin()
            try:
                assert (
                    connection.scalar(
                        text(
                            "SELECT search_id FROM app.item_db_similarity_searches "
                            "WHERE search_id=:id FOR UPDATE"
                        ),
                        {"id": record.search_id},
                    )
                    == record.search_id
                )
                for column in ("operator_id", "input_json", "intent_sha256", "idempotency_key"):
                    with pytest.raises(DBAPIError) as denied, connection.begin_nested():
                        connection.execute(
                            text(
                                f"UPDATE app.item_db_similarity_searches SET {column}={column} "
                                "WHERE search_id=:id"
                            ),
                            {"id": record.search_id},
                        )
                    assert denied.value.orig.sqlstate == "42501"
            finally:
                transaction.rollback()
    finally:
        runtime.dispose()
