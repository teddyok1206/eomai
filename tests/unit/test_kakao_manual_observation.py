"""Closed local document evidence and source-bound reads, not provider identity proof."""

from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from eom_kakao_archive_collector import manual_observation as observer
from eom_kakao_archive_contracts.manual_download import ManualDownloadStart
from eom_kakao_archive_contracts.manual_observation import (
    SCHEMA_SHA256,
    ManualPageObservation,
)
from eom_kakao_archive_contracts.render import canonical_bytes, sha256
from eom_orchestrator.kakao_download_inputs import (
    KakaoDownloadInputError,
    read_received_kakao_download,
)

from tests.unit.test_kakao_download_inputs import received as received
from tests.unit.test_kakao_manual_browser_driver import fence
from tests.unit.test_kakao_manual_download import download_root, drain, results, transfer


def start():
    return ManualDownloadStart(
        capture_id="kakaodownload_" + "c" * 32,
        profile_id=fence().profile_id,
        browser_run_id=fence().browser_run_id,
        fence_epoch=fence().fence_epoch,
        page_instance_id="kakaopage_" + "d" * 32,
        started_at=datetime.now(UTC),
    )


def document():
    return dict(
        origin=observer.ORIGIN,
        path="/space/synthetic/channel/example/chats/room",
        truncated=False,
        nodes=[
            dict(
                index=0,
                parent_index=None,
                tag="a",
                classes=["download"],
                role=None,
                label="사진 다운로드",
                text=None,
                link_path="/api/profiles/example/chats/room/logs/id/image",
                identities={
                    key: None
                    for key in ("data-id", "data-chat-id", "data-message-id", "data-log-id")
                },
                is_image=False,
            )
        ],
    )


def observation_value(started=None):
    value = started or start()
    return dict(
        **value.model_dump(mode="json", exclude={"phase", "schema_version", "started_at"}),
        observed_at=value.started_at,
        status="OBSERVED",
        target=dict(kind="BLOB", path=None),
        document=document(),
        error_code=None,
    )


def test_schema_mirror_hash_and_frozen_observation_values():
    root = Path(__file__).resolve().parents[2]
    name = "manual-page-observation-v1.schema.json"
    raw = (root / "schemas/kakao-archive" / name).read_bytes()
    assert sha256(raw) == SCHEMA_SHA256
    assert (
        raw
        == (
            root / "packages/kakao_archive_contracts/eom_kakao_archive_contracts/schemas" / name
        ).read_bytes()
    )
    value = ManualPageObservation.model_validate(observation_value())
    assert ManualPageObservation.model_validate_json(value.model_dump_json()) == value
    assert value.document is not None
    assert value.document.nodes[0].identities.data_id is None
    with pytest.raises(ValueError):
        value.document.nodes[0].identities.data_id = "mutable"
    assert (
        ManualPageObservation.model_validate_json(
            canonical_bytes(value.model_dump(mode="json", by_alias=True))
        )
        == value
    )


@pytest.mark.parametrize(
    "change",
    [
        lambda v: v.update(click=True),
        lambda v: v.update(source_url="https://private/?credential=secret"),
        lambda v: v.update(document=v["document"] | {"cookies": "secret"}),
        lambda v: v["document"].update(origin="https://accounts.kakao.com"),
        lambda v: v["document"].update(path="/path?credential=secret"),
        lambda v: v["document"]["nodes"][0].update(value="password"),
        lambda v: v["document"]["nodes"][0].update(index=True),
        lambda v: v["document"]["nodes"][0].update(parent_index=0),
        lambda v: v["document"]["nodes"][0].update(index=1),
        lambda v: v["document"]["nodes"][0]["identities"].update({"data-token": "secret"}),
        lambda v: v["document"]["nodes"][0]["identities"].update({"data-log-id": "../../file"}),
        lambda v: v["document"]["nodes"][0].update(link_path="https://outside/path"),
        lambda v: v.update(status="UNAVAILABLE"),
        lambda v: v.update(error_code="private traceback"),
        lambda v: v.update(target=dict(kind="BLOB", path="/opaque-value")),
    ],
)
def test_untrusted_observation_is_closed_and_not_a_control_contract(change):
    value = observation_value()
    change(value)
    with pytest.raises(ValueError):
        ManualPageObservation.model_validate(value)


def test_total_text_and_ordered_parent_bounds():
    value = observation_value()
    node = value["document"]["nodes"][0]
    value["document"]["nodes"] = [node | dict(index=i, text="문" * 8192) for i in range(9)]
    with pytest.raises(ValueError, match="TEXT_LIMIT"):
        ManualPageObservation.model_validate(value)
    value["document"]["nodes"] = [node, node | dict(index=1, parent_index=0)]
    assert ManualPageObservation.model_validate(value)


@pytest.mark.parametrize(
    "url,kind,path",
    [
        (
            "https://business.kakao.com/api/profiles/id/chats/room/logs/id/image?credential=secret#token",
            "SAME_ORIGIN_PATH",
            "/api/profiles/id/chats/room/logs/id/image",
        ),
        ("blob:https://business.kakao.com/opaque", "BLOB", None),
        ("https://k.kakaocdn.net/file?credential=secret", "UNAVAILABLE", None),
        ("https://business.kakao.com.evil.invalid/path", "UNAVAILABLE", None),
        ("https://business.kakao.com:444/path", "UNAVAILABLE", None),
        ("https://username:secret@business.kakao.com/path", "UNAVAILABLE", None),
        ("javascript:send()", "UNAVAILABLE", None),
    ],
)
def test_download_target_never_retains_signed_queries_credentials_or_cdn_url(url, kind, path):
    target = observer.download_target(url)
    assert target.kind == kind and target.path == path
    assert "secret" not in target.model_dump_json() and "opaque" not in target.model_dump_json()


def test_fixed_read_only_evaluate_and_exact_capture_identity():
    started = start()
    page = SimpleNamespace(
        url=observer.ORIGIN + document()["path"], evaluate=AsyncMock(return_value=document())
    )
    result = asyncio.run(
        observer.observe_download_page(
            page,
            started,
            download_url="blob:https://business.kakao.com/opaque",
            event_path=observer.download_page_path(page),
        )
    )
    assert result.status == "OBSERVED" and result.capture_id == started.capture_id
    assert result.page_instance_id == started.page_instance_id
    page.evaluate.assert_awaited_once_with(observer.DOCUMENT_EXPRESSION)
    assert result.document and not result.document.truncated
    assert not any(hasattr(page, name) for name in ("click", "press", "fill", "keyboard"))


def test_query_changes_are_not_identity_or_persisted_credentials():
    page = SimpleNamespace(url=observer.ORIGIN + document()["path"] + "?token=secret#credential")
    event_path = observer.download_page_path(page)
    assert event_path == document()["path"]

    async def evaluate(_expression):
        page.url = observer.ORIGIN + document()["path"] + "?token=changed#new-credential"
        return document()

    page.evaluate = AsyncMock(side_effect=evaluate)
    result = asyncio.run(
        observer.observe_download_page(
            page,
            start(),
            download_url="blob:" + observer.ORIGIN + "/opaque",
            event_path=event_path,
        )
    )
    assert result.status == "OBSERVED" and result.document
    assert not any(part in result.model_dump_json() for part in ("secret", "credential", "token"))


def test_unsupported_event_origin_cannot_become_supported_by_later_navigation():
    page = SimpleNamespace(
        url="https://accounts.kakao.com/login?credential=secret",
        evaluate=AsyncMock(return_value=document()),
    )
    event_path = observer.download_page_path(page)
    page.url = observer.ORIGIN + document()["path"]
    result = asyncio.run(
        observer.observe_download_page(
            page,
            start(),
            download_url="blob:" + observer.ORIGIN + "/opaque",
            event_path=event_path,
        )
    )
    assert result.status == "UNAVAILABLE" and result.error_code == "UNSUPPORTED_ORIGIN"
    assert result.document is None and "secret" not in result.model_dump_json()
    page.evaluate.assert_not_awaited()


@pytest.mark.parametrize(
    "case,error",
    [
        ("different_origin", "UNSUPPORTED_ORIGIN"),
        ("exception", "OBSERVATION_FAILED"),
        ("timeout", "OBSERVATION_TIMEOUT"),
        ("invalid", "OBSERVATION_INVALID"),
        ("navigated", "UNSUPPORTED_ORIGIN"),
    ],
)
def test_observer_failures_are_explicit_without_raw_private_payload(case, error):
    page = SimpleNamespace(
        url=observer.ORIGIN + document()["path"], evaluate=AsyncMock(return_value=document())
    )
    if case == "different_origin":
        page.url = "https://accounts.kakao.com/login?password=secret"
    elif case == "exception":
        page.evaluate.side_effect = RuntimeError("private url credential secret")
    elif case == "timeout":
        page.evaluate.side_effect = TimeoutError()
    elif case == "invalid":
        page.evaluate.return_value = document() | dict(secret="private")
    else:
        page.evaluate.return_value = None
    result = asyncio.run(
        observer.observe_download_page(
            page,
            start(),
            download_url="https://k.kakaocdn.net/?credential=secret",
            event_path=observer.download_page_path(page),
        )
    )
    assert result.status == "UNAVAILABLE" and result.error_code == error
    assert result.document is None and "secret" not in result.model_dump_json()
    if case == "different_origin":
        page.evaluate.assert_not_awaited()


def test_download_callback_writes_one_private_observation_and_owner_reads_it():
    from eom_kakao_archive_collector.manual_download import ManualDownloads

    async def run(root):
        callbacks = {}
        page = SimpleNamespace(
            url=observer.ORIGIN + document()["path"],
            evaluate=AsyncMock(return_value=document()),
            on=lambda key, handler: callbacks.update({key: handler}),
        )
        manager = ManualDownloads(fence(), root=root)
        manager.subscribe(page)
        manager.subscribe(page)
        download = transfer(manager)
        download.url = "blob:https://business.kakao.com/private"
        callbacks["download"](download)
        callbacks["download"](download)
        await drain(manager)
        (receipt,) = results(manager)
        assert receipt.phase == "RECEIVED" and manager.failure is None
        page.evaluate.assert_awaited_once()
        path = manager.run / receipt.capture_id / "page-observation.json"
        assert path.stat().st_mode & 0o777 == 0o640
        result = read_received_kakao_download(
            root=root,
            fence=fence(),
            capture_id=receipt.capture_id,
            worker_uid=os.getuid(),
            control_gid=os.getgid(),
        )
        assert result.observation and result.observation.status == "OBSERVED"
        assert result.observation.page_instance_id == receipt.page_instance_id
        await manager.close()
        assert path.is_file()

    with download_root() as root:
        asyncio.run(run(root))


def test_observer_timeout_does_not_discard_successful_download_bytes():
    from eom_kakao_archive_collector.manual_download import ManualDownloads

    async def run(root):
        page = SimpleNamespace(
            url="https://business.kakao.com/page", evaluate=AsyncMock(side_effect=TimeoutError())
        )
        manager = ManualDownloads(fence(), root=root)
        download = transfer(manager)
        download.url = "blob:https://business.kakao.com/example"
        manager.receive(download, "kakaopage_" + "d" * 32, page=page)
        await drain(manager)
        (receipt,) = results(manager)
        assert receipt.phase == "RECEIVED" and manager.failure is None
        result = read_received_kakao_download(
            root=root,
            fence=fence(),
            capture_id=receipt.capture_id,
            worker_uid=os.getuid(),
            control_gid=os.getgid(),
        )
        assert result.observation and result.observation.error_code == "OBSERVATION_TIMEOUT"
        assert result.payload
        await manager.close()

    with download_root() as root:
        asyncio.run(run(root))


def test_redirected_photo_uses_only_the_observed_same_page_request_path():
    from eom_kakao_archive_collector.manual_download import ManualDownloads

    async def run(root):
        callbacks = {}
        page = SimpleNamespace(
            url=observer.ORIGIN + document()["path"],
            evaluate=AsyncMock(return_value=document()),
            on=lambda name, callback: callbacks.update({name: callback}),
        )
        manager = ManualDownloads(fence(), root=root)
        manager.subscribe(page)
        source = SimpleNamespace(
            url=observer.ORIGIN + document()["nodes"][0]["link_path"],
            method="GET",
            redirected_from=None,
        )
        final = SimpleNamespace(
            url="https://k.kakaocdn.net/test/image?signature=NEVER_RECORD",
            method="GET",
            redirected_from=source,
        )
        callbacks["request"](source)
        callbacks["request"](final)
        download = transfer(manager, raw=b"synthetic image bytes", filename="same.jpg")
        download.url = final.url
        callbacks["download"](download)
        await drain(manager)
        (receipt,) = results(manager)
        assert receipt.phase == "RECEIVED" and manager.failure is None
        raw = (manager.run / receipt.capture_id / "page-observation.json").read_bytes()
        observed = ManualPageObservation.model_validate_json(raw)
        assert observed.target.path == document()["nodes"][0]["link_path"]
        assert observed.target.kind == "SAME_ORIGIN_PATH"
        assert b"NEVER_RECORD" not in raw and b"k.kakaocdn.net" not in raw
        await manager.close()
        callbacks["request"](source)
        assert len(manager._origins) == 0

    with download_root() as root:
        asyncio.run(run(root))


@pytest.mark.parametrize("navigation", ["before_observer", "during_observer", "document_only"])
def test_room_navigation_does_not_relabel_a_received_file(navigation):
    from eom_kakao_archive_collector.manual_download import ManualDownloads

    async def run(root):
        original_path = document()["path"]
        other_path = original_path + "-other-room"
        page = SimpleNamespace(url=observer.ORIGIN + original_path)

        async def evaluate(_expression):
            if navigation == "during_observer":
                page.url = observer.ORIGIN + other_path
            path = (
                other_path if navigation in {"before_observer", "document_only"} else original_path
            )
            return document() | dict(path=path)

        page.evaluate = AsyncMock(side_effect=evaluate)
        manager = ManualDownloads(fence(), root=root)
        raw = b"original download, not another room's document"
        download = transfer(manager, raw)
        download.url = "blob:" + observer.ORIGIN + "/opaque"
        manager.receive(download, "kakaopage_" + "d" * 32, page=page)
        if navigation == "before_observer":
            # Real SDK callbacks are synchronous; the observation coroutine runs later.
            page.url = observer.ORIGIN + other_path
        await drain(manager)
        (receipt,) = results(manager)
        assert receipt.phase == "RECEIVED" and manager.failure is None
        result = read_received_kakao_download(
            root=root,
            fence=fence(),
            capture_id=receipt.capture_id,
            worker_uid=os.getuid(),
            control_gid=os.getgid(),
        )
        assert result.payload == raw
        assert result.observation and result.observation.status == "UNAVAILABLE"
        assert result.observation.error_code == "OBSERVATION_INVALID"
        assert result.observation.document is None
        if navigation == "before_observer":
            page.evaluate.assert_not_awaited()
        await manager.close()

    with download_root() as root:
        asyncio.run(run(root))


@pytest.mark.parametrize(
    "changed", ["capture_id", "page_instance_id", "fence_epoch", "observed_at"]
)
def test_owner_rejects_observation_from_another_capture_or_time(received, changed):
    arguments, _, capture, _ = received
    started = ManualDownloadStart.model_validate_json((capture / "started.json").read_bytes())
    value = observation_value(started)
    value[changed] = (
        2
        if changed == "fence_epoch"
        else datetime.now(UTC) + timedelta(days=1)
        if changed == "observed_at"
        else ("kakaodownload_" if changed == "capture_id" else "kakaopage_") + "e" * 32
    )
    path = capture / "page-observation.json"
    path.write_bytes(
        canonical_bytes(
            ManualPageObservation.model_validate(value).model_dump(mode="json", by_alias=True)
        )
    )
    path.chmod(0o640)
    with pytest.raises(KakaoDownloadInputError, match="OBSERVATION_STALE"):
        read_received_kakao_download(**arguments)


def test_owner_does_not_ignore_present_corrupt_observation(received):
    arguments, _, capture, _ = received
    path = capture / "page-observation.json"
    path.write_bytes(b'{"untrusted":"secret"}')
    path.chmod(0o640)
    with pytest.raises(KakaoDownloadInputError, match="OBSERVATION_INVALID") as error:
        read_received_kakao_download(**arguments)
    assert "secret" not in str(error.value)


def test_actual_observation_timeout_cancels_and_reaps_read(monkeypatch):
    cancelled = []

    async def slow(_expression):
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.append(True)

    monkeypatch.setattr(observer, "OBSERVATION_SECONDS", 0.01)
    page = SimpleNamespace(url="https://business.kakao.com/page", evaluate=slow)
    result = asyncio.run(
        observer.observe_download_page(
            page,
            start(),
            download_url="blob:https://business.kakao.com/example",
            event_path=observer.download_page_path(page),
        )
    )
    assert result.error_code == "OBSERVATION_TIMEOUT" and cancelled == [True]


def test_stop_during_observation_preserves_cancelled_download_history():
    from eom_kakao_archive_collector.manual_download import ManualDownloads

    async def run(root):
        entered = asyncio.Event()

        async def evaluate(_expression):
            entered.set()
            await asyncio.Event().wait()

        manager = ManualDownloads(fence(), root=root)
        page = SimpleNamespace(url="https://business.kakao.com/page", evaluate=evaluate)
        download = transfer(manager)
        download.url = "blob:https://business.kakao.com/example"
        manager.receive(download, "kakaopage_" + "d" * 32, page=page)
        await asyncio.wait_for(entered.wait(), 1)
        await manager.close()
        (result,) = results(manager)
        assert result.phase == "FAILED" and result.error_code == "DOWNLOAD_CANCELLED"
        assert (manager.run / result.capture_id / "started.json").is_file()
        assert not (manager.run / result.capture_id / "payload.bin").exists()

    with download_root() as root:
        asyncio.run(run(root))
