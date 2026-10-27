"""Studio exposes a compact save receipt and preserves the same retry key."""

from __future__ import annotations

import asyncio
from types import MethodType

import httpx
import pytest
from eom_web_gui.gateways import GatewayError, HttpApplicationGateway

from tests.unit.test_curated_document_assembly_manifest import _manifest
from tests.unit.test_curated_document_assembly_resolution import _draft


def _gateway(payload: dict[str, object]) -> tuple[HttpApplicationGateway, list[dict[str, object]]]:
    gateway = object.__new__(HttpApplicationGateway)
    calls: list[dict[str, object]] = []

    async def authorized(self, _session, method, path, **kwargs):
        calls.append({"method": method, "path": path, **kwargs})
        return httpx.Response(201, json={"data": payload})

    gateway._authorized = MethodType(authorized, gateway)
    return gateway, calls


def test_save_uses_exact_draft_key_and_returns_only_compact_receipt() -> None:
    gateway, calls = _gateway(_manifest())
    draft = _draft().model_dump(mode="json")
    receipt = asyncio.run(gateway.save_curated_assembly(None, draft, "curated-web-key-1"))
    assert receipt.assembly_revision_id == "assemblyrev_" + "2" * 32
    assert receipt.placement_count == 3
    assert receipt.state == "INPUT_PINNED"
    assert "source_file_id" not in receipt.model_dump()
    assert calls == [
        {
            "method": "POST",
            "path": "/api/v1/item-db/assemblies",
            "json": draft,
            "headers": {"Idempotency-Key": "curated-web-key-1"},
            "timeout": 135.0,
        }
    ]


def test_save_rejects_unexpected_upstream_shape() -> None:
    gateway, _ = _gateway({"assembly_revision_id": "assemblyrev_" + "2" * 32})
    with pytest.raises(GatewayError) as captured:
        asyncio.run(gateway.save_curated_assembly(None, {}, "curated-web-key-1"))
    assert captured.value.code == "ITEM_DB_ASSEMBLY_RESPONSE_INVALID"
