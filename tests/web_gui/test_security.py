from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from eom_web_gui.contracts import ExplorerQuery
from eom_web_gui.gateways import GatewayError
from eom_web_gui.services import validate_download_request
from eom_web_gui.sessions import ApiTokens, SessionStore


@pytest.mark.parametrize(
    "filename",
    ("../item.hwpx", "nested/item.hwpx", "nested\\item.hwpx", "item.txt", "..hwpx"),
)
def test_hwpx_download_rejects_path_traversal_and_non_hwpx(filename: str) -> None:
    with pytest.raises(GatewayError):
        validate_download_request("hwpxbuild_test0001", filename)


def test_hwpx_download_accepts_only_fixed_identity_and_safe_name() -> None:
    validate_download_request("hwpxbuild_test0001", "physics-item.hwpx")
    with pytest.raises(GatewayError):
        validate_download_request("../../root", "physics-item.hwpx")


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
