"""Synthetic SDK events only; never browser cookies, live requests or source authority."""

from dataclasses import dataclass

import pytest
from eom_kakao_archive_collector.download_origins import (
    LIFETIME_SECONDS,
    MAX_REDIRECTS,
    MAX_REQUESTS,
    DownloadRequestOrigins,
)

PAGE = "/space/example/channel/example/chats/room"
SOURCE = "https://business.kakao.com/api/profiles/p/chats/r/message/photo/image"
CDN = "https://k.kakaocdn.net/test/photo.jpg?signature=NEVER_RECORD"


@dataclass
class Request:
    url: str
    method: str = "GET"
    redirected_from: "Request | None" = None


def redirect(cache, page="page", *, source=SOURCE, target=CDN):
    first = Request(source)
    final = Request(target, redirected_from=first)
    cache.observe(page, first, page_path=PAGE)
    cache.observe(page, final, page_path=PAGE)
    return first, final


def test_actual_chain_is_page_local_once_and_never_retains_signed_url():
    cache = DownloadRequestOrigins()
    first, final = redirect(cache)
    assert len(cache) == 1
    cache.observe("page", final, page_path=PAGE)  # A duplicate SDK event is not a new chain.
    result = cache.consume("page", CDN, page_path=PAGE)
    assert result is not None and result.kind == "SAME_ORIGIN_PATH"
    assert result.path == "/api/profiles/p/chats/r/message/photo/image"
    assert "NEVER_RECORD" not in result.model_dump_json()
    assert len(cache) == 0
    assert cache.consume("page", CDN, page_path=PAGE) is None
    assert first.url == SOURCE and final.url == CDN  # No mutation of SDK data.


@pytest.mark.parametrize(
    "source,method,target",
    [
        ("https://business.kakao.com/login", "GET", CDN),
        ("https://business.kakao.com/api/account", "GET", CDN),
        (SOURCE, "POST", CDN),
        (SOURCE, "PUT", CDN),
        (SOURCE, "GET", "https://evil.example/photo"),
        (SOURCE, "GET", "http://k.kakaocdn.net/photo"),
        (SOURCE, "GET", "https://user:secret@k.kakaocdn.net/photo"),
        (SOURCE, "GET", "https://k.kakaocdn.net:444/photo"),
        (SOURCE, "GET", "https://k.kakaocdn.net:invalid/photo"),
        (SOURCE, "GET", "https://k.kakaocdn.net/" + "x" * 8192),
        ("https://business.kakao.com.attacker.test/api/profiles/p/chats/r/m/i/image", "GET", CDN),
    ],
)
def test_non_image_credential_mutation_or_unsupported_redirect_is_not_associated(
    source, method, target
):
    cache = DownloadRequestOrigins()
    first = Request(source, method)
    final = Request(target, redirected_from=first)
    cache.observe("page", first, page_path=PAGE)
    cache.observe("page", final, page_path=PAGE)
    assert cache.consume("page", target, page_path=PAGE) is None


@pytest.mark.parametrize("change", ["other_page", "navigate", "unsupported_page", "orphan"])
def test_other_page_or_lost_predecessor_cannot_relabel_the_source(change):
    cache = DownloadRequestOrigins()
    first = Request(SOURCE)
    cache.observe("page", first, page_path=PAGE)
    final = Request(CDN, redirected_from=first)
    page, path = "page", PAGE
    if change == "other_page":
        page = "other"
    elif change == "navigate":
        path += "-other-room"
    elif change == "unsupported_page":
        path = None
    else:
        final.redirected_from = Request(SOURCE)  # Same URL is not request identity.
    cache.observe(page, final, page_path=path)
    assert cache.consume(page, CDN, page_path=path) is None


def test_initial_cdn_request_does_not_prove_an_original_source_link():
    cache = DownloadRequestOrigins()
    cache.observe("page", Request(CDN), page_path=PAGE)
    assert cache.consume("page", CDN, page_path=PAGE) is None
    assert len(cache) == 0


def test_expiry_capacity_and_clear_update_both_indices():
    clock = [100.0]
    cache = DownloadRequestOrigins(clock=lambda: clock[0])
    first, _ = redirect(cache)
    clock[0] += LIFETIME_SECONDS
    assert cache.consume("page", CDN, page_path=PAGE) is None
    for i in range(MAX_REQUESTS + 10):
        cache.observe("page", Request(SOURCE + "?n=" + str(i)), page_path=PAGE)
    assert len(cache) == MAX_REQUESTS
    assert sum(len(keys) for keys in cache._targets.values()) == MAX_REQUESTS
    assert cache.consume("page", SOURCE + "?n=0", page_path=PAGE) is None
    cache.clear()
    assert len(cache) == 0 and cache._targets == {}
    assert first.url == SOURCE


def test_redirect_chain_is_bounded_and_does_not_fall_back_to_an_older_leg():
    cache = DownloadRequestOrigins()
    previous = Request(SOURCE)
    cache.observe("page", previous, page_path=PAGE)
    for i in range(MAX_REDIRECTS + 1):
        final = Request(CDN + "&leg=" + str(i), redirected_from=previous)
        cache.observe("page", final, page_path=PAGE)
        previous = final
    assert cache.consume("page", previous.url, page_path=PAGE) is None and len(cache) == 0


def test_two_same_asset_redirects_are_ambiguous_not_guessed_or_reused():
    cache = DownloadRequestOrigins()
    redirect(cache, source=SOURCE)
    redirect(cache, source=SOURCE.replace("/message/", "/other-message/"))
    assert len(cache) == 2
    assert cache.consume("page", CDN, page_path=PAGE) is None
    assert cache.consume("page", CDN, page_path=PAGE) is None
    assert len(cache) == 0
    redirect(cache)
    assert cache.consume("page", CDN, page_path=PAGE) is not None


def test_page_navigation_at_download_event_invalidates_even_a_valid_prior_chain():
    cache = DownloadRequestOrigins()
    redirect(cache)
    assert cache.consume("page", CDN, page_path=PAGE + "-other") is None
    assert cache.consume("page", CDN, page_path=PAGE) is None


def test_missing_page_scope_consumes_the_event_without_enabling_a_later_relabel():
    cache = DownloadRequestOrigins()
    redirect(cache)
    assert cache.consume("page", CDN, page_path=None) is None
    assert cache.consume("page", CDN, page_path=PAGE) is None


def test_optional_sdk_metadata_error_is_not_read_as_credentials_or_authority():
    class Missing:
        @property
        def url(self):
            raise RuntimeError("never expose private SDK detail")

    cache = DownloadRequestOrigins()
    cache.observe("page", Missing(), page_path=PAGE)
    assert len(cache) == 0
