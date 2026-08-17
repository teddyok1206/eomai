from __future__ import annotations

from datetime import UTC, datetime

import pytest
from eom_api.errors import ApiError
from eom_api.services.query_adapter import CursorCodec


def test_cursor_is_opaque_typed_and_tamper_evident() -> None:
    codec = CursorCodec(b"c" * 32)
    timestamp = datetime.now(UTC)
    cursor = codec.encode("item", timestamp, "item_" + "a" * 32)
    decoded_time, decoded_id = codec.decode(cursor, "item")
    assert decoded_time == timestamp
    assert decoded_id == "item_" + "a" * 32
    with pytest.raises(ApiError) as wrong_resource:
        codec.decode(cursor, "workflow")
    assert wrong_resource.value.error_code == "API_CURSOR_INVALID"
    position = len(cursor) // 2
    tampered = (
        cursor[:position] + ("A" if cursor[position] != "A" else "B") + cursor[position + 1 :]
    )
    with pytest.raises(ApiError):
        codec.decode(tampered, "item")
