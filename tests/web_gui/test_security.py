from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

import pytest
from eom_web_gui.contracts import ExplorerQuery
from eom_web_gui.gateways import GatewayError
from eom_web_gui.services import validate_download_request
from eom_web_gui.sessions import ApiTokens, SessionStore, WebSession


@pytest.mark.parametrize(
    "build_id",
    ("../item.hwpx", "nested/item.hwpx", "nested\\item.hwpx", "item.txt", "..hwpx"),
)
def test_hwpx_download_rejects_path_traversal_and_non_build_ids(build_id: str) -> None:
    with pytest.raises(GatewayError):
        validate_download_request(build_id)


def test_hwpx_download_accepts_only_fixed_build_identity() -> None:
    validate_download_request("hwpxbuild_" + "a" * 32)
    with pytest.raises(GatewayError):
        validate_download_request("../../root")


def test_session_cookie_material_is_opaque_and_server_side() -> None:
    now = datetime(2026, 8, 21, tzinfo=UTC)
    store = SessionStore(ttl_seconds=300, maximum_sessions=2, maximum_drafts=2)
    session = store.create(
        operator={"roles": ["ADMIN"]},
        tokens=ApiTokens(
            "TEST_ACCESS", "TEST_REFRESH", now + timedelta(minutes=2), now + timedelta(hours=1)
        ),
        now=now,
    )
    assert session.session_id.startswith("websession_")
    assert "TEST_ACCESS" not in session.session_id
    assert store.get(session.session_id, now=now) is session


def test_concurrent_users_receive_isolated_server_side_sessions() -> None:
    now = datetime(2026, 10, 2, tzinfo=UTC)
    store = SessionStore(ttl_seconds=300, maximum_sessions=64, maximum_drafts=2)

    def create(index: int) -> WebSession:
        return store.create(
            operator={"operator_id": f"operator_{index:032x}", "roles": ["AUTHOR"]},
            tokens=ApiTokens(
                f"TEST_ACCESS_{index}",
                f"TEST_REFRESH_{index}",
                now + timedelta(minutes=2),
                now + timedelta(hours=1),
            ),
            now=now,
        )

    with ThreadPoolExecutor(max_workers=8) as executor:
        sessions = tuple(executor.map(create, range(32)))

    assert len({session.session_id for session in sessions}) == 32
    assert len({session.csrf_token for session in sessions}) == 32
    for index, session in enumerate(sessions):
        assert store.get(session.session_id, now=now) is session
        assert session.operator["operator_id"] == f"operator_{index:032x}"
        assert session.tokens.access_token == f"TEST_ACCESS_{index}"


def test_credential_change_removes_only_other_sessions_for_same_operator() -> None:
    now = datetime(2026, 10, 2, tzinfo=UTC)
    store = SessionStore(ttl_seconds=300, maximum_sessions=8, maximum_drafts=2)

    def create(operator_id: str, suffix: str) -> WebSession:
        return store.create(
            operator={"operator_id": operator_id, "roles": ["AUTHOR"]},
            tokens=ApiTokens(
                f"TEST_ACCESS_{suffix}",
                f"TEST_REFRESH_{suffix}",
                now + timedelta(minutes=2),
                now + timedelta(hours=1),
            ),
            now=now,
        )

    operator_id = "operator_" + "1" * 32
    current = create(operator_id, "CURRENT")
    stale = create(operator_id, "STALE")
    other = create("operator_" + "2" * 32, "OTHER")

    assert (
        store.delete_other_operator_sessions(
            operator_id,
            except_session_id=current.session_id,
        )
        == 1
    )
    assert store.get(current.session_id, now=now) is current
    assert store.get(stale.session_id, now=now) is None
    assert store.get(other.session_id, now=now) is other


def test_explorer_contract_has_no_sql_or_join_fields() -> None:
    query = ExplorerQuery(entity="workflows")
    assert set(query.model_dump()) == {
        "schema_version",
        "entity",
        "exact_id",
        "status",
        "date_from",
        "date_to",
        "sort",
        "cursor",
        "limit",
    }
