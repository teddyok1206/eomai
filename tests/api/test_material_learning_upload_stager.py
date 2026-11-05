"""The new upload route detects actual bytes; legacy review remains strict."""

import asyncio

import pytest
from eom_api.errors import ApiError
from eom_api.services.pdf_upload_stager import PdfUploadStager
from starlette.requests import Request


def request_for(body):
    messages = iter(
        [
            {"type": "http.request", "body": body[:5], "more_body": True},
            {"type": "http.request", "body": body[5:], "more_body": False},
        ]
    )

    async def receive():
        return next(messages)

    return Request({"type": "http", "method": "POST", "path": "/"}, receive)


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        (b"%PDF-1.7\ntest", "PDF"),
        (bytes.fromhex("d0cf11e0a1b11ae1") + b"test", "HWP"),
        (b"PK\x03\x04test-payload", "HWPX"),
    ],
)
def test_detected_upload_stream_and_cleanup(tmp_path, body, expected):
    tmp_path.chmod(0o700)
    stager = PdfUploadStager(tmp_path, maximum_bytes=1024)

    async def check():
        async with stager.stage_detected(request_for(body), declared_length=len(body)) as result:
            assert result.source_format == expected
            assert result.path.read_bytes() == body
            assert result.path.stat().st_mode & 0o777 == 0o600
        assert not result.path.exists()

    asyncio.run(check())


def test_unknown_signature_fails_and_leaves_no_file(tmp_path):
    tmp_path.chmod(0o700)
    stager = PdfUploadStager(tmp_path, maximum_bytes=1024)

    async def check():
        with pytest.raises(ApiError, match="Only PDF"):
            async with stager.stage_detected(request_for(b"not-a-doc"), declared_length=9):
                pytest.fail("invalid input yielded")

    asyncio.run(check())
    assert not list(tmp_path.iterdir())


def test_legacy_declared_review_does_not_silently_change_format(tmp_path):
    tmp_path.chmod(0o700)
    stager = PdfUploadStager(tmp_path, maximum_bytes=1024)

    async def check():
        with pytest.raises(ApiError):
            async with stager.stage(request_for(b"PK\x03\x04test-payload"), declared_length=16):
                pytest.fail("declared PDF accepted HWPX bytes")

    asyncio.run(check())
    assert not list(tmp_path.iterdir())
