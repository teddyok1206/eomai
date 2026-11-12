"""Immutable curriculum initialization must precede accepting user requests."""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from typing import cast
from unittest.mock import Mock

import pytest
from eom_api import lifespan as lifecycle
from eom_catalog_contracts import load_integrated_science_editorial_outline
from fastapi import FastAPI


def _services() -> tuple[lifecycle.AppServices, Mock]:
    dispose = Mock()
    services = cast(lifecycle.AppServices, SimpleNamespace(engine=SimpleNamespace(dispose=dispose)))
    return services, dispose


def test_curriculum_is_ready_before_application_accepts_requests(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    services, dispose = _services()
    monkeypatch.setattr(
        lifecycle, "load_integrated_science_editorial_outline", lambda: events.append("prepared")
    )

    async def run() -> None:
        async with lifecycle.lifespan_for(services)(FastAPI()):
            assert events == ["prepared"]
            dispose.assert_not_called()
            events.append("accepted")

    asyncio.run(run())
    assert events == ["prepared", "accepted"]
    dispose.assert_called_once_with()


def test_invalid_curriculum_fails_startup_and_disposes_engine(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    services, dispose = _services()
    failure = ValueError("synthetic immutable-resource verification failure")
    monkeypatch.setattr(
        lifecycle, "load_integrated_science_editorial_outline", Mock(side_effect=failure)
    )

    async def run() -> None:
        with pytest.raises(ValueError) as raised:
            async with lifecycle.lifespan_for(services)(FastAPI()):
                pytest.fail("invalid curriculum must not expose a ready application")
        assert raised.value is failure

    asyncio.run(run())
    dispose.assert_called_once_with()


def test_concurrent_request_reads_reuse_the_startup_validated_outline() -> None:
    services, dispose = _services()
    load_integrated_science_editorial_outline.cache_clear()

    async def run() -> None:
        async with lifecycle.lifespan_for(services)(FastAPI()):
            ready = load_integrated_science_editorial_outline.cache_info()
            assert ready.misses == 1
            with ThreadPoolExecutor(max_workers=2) as pool:
                results = tuple(
                    pool.map(lambda _: load_integrated_science_editorial_outline(), range(2))
                )
            assert results[0] is results[1]
            assert len(results[0].units) == 41
            after = load_integrated_science_editorial_outline.cache_info()
            assert after.misses == ready.misses
            assert after.hits == ready.hits + 2

    try:
        asyncio.run(run())
        dispose.assert_called_once_with()
    finally:
        load_integrated_science_editorial_outline.cache_clear()
