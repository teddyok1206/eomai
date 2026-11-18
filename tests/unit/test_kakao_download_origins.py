"""Synthetic SDK events only; never browser cookies, live requests or source authority."""

from dataclasses import dataclass

import pytest
from eom_kakao_archive_collector.download_origins import (
    LIFETIME_SECONDS,
    MAX_REDIRECTS,
    MAX_REQUESTS,
    DownloadRequestOrigins,
    OriginCode,
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


def test_diagnostic_separates_absence_orphan_page_and_final_url():
    cache = DownloadRequestOrigins()
    assert cache.resolve("page", CDN, page_path=PAGE).code == OriginCode.FINAL_URL_NOT_OBSERVED
    cache.observe("page", Request(CDN), page_path=PAGE)
    assert (
        cache.resolve("page", CDN, page_path=PAGE).code
        == OriginCode.INITIAL_PHOTO_REQUEST_NOT_OBSERVED
    )
    cache.observe("page", Request(CDN, redirected_from=Request(SOURCE)), page_path=PAGE)
    assert (
        cache.resolve("page", CDN, page_path=PAGE).code == OriginCode.REDIRECT_PREDECESSOR_MISSING
    )
    redirect(cache, "opener")
    alternate = cache.resolve("page", CDN, page_path=PAGE)
    assert alternate.code == OriginCode.FINAL_URL_OBSERVED_ON_OTHER_PAGE
    assert alternate.target is None and alternate.final_url_on_other_page
    assert (
        cache.resolve("opener", CDN + "&different=1", page_path=PAGE).code
        == OriginCode.FINAL_URL_NOT_MATCHED
    )
    changed = cache.resolve("opener", CDN, page_path=PAGE + "-another")
    assert changed.code == OriginCode.DOWNLOAD_PAGE_CHANGED and changed.final_url_on_same_page


def test_unapproved_redirect_and_ambiguity_emit_only_fixed_diagnostic_values():
    cache = DownloadRequestOrigins()
    destination = "https://unsupported.example/private-image?token=NEVER_RECORD"
    redirect(cache, target=destination)
    rejected = cache.resolve("page", destination, page_path=PAGE)
    assert rejected.code == OriginCode.REQUEST_ORIGIN_NOT_ALLOWED
    assert (
        rejected.source_get_observed and rejected.final_url_on_same_page and rejected.target is None
    )
    assert rejected.safe_log("MANUAL") == (
        "KAKAO_DOWNLOAD_ORIGIN mode=MANUAL code=REQUEST_ORIGIN_NOT_ALLOWED candidates=0 "
        "source_get=OBSERVED final_same_page=1 final_other_page=0"
    )
    redirect(cache)
    redirect(cache)
    multiple = cache.resolve("page", CDN, page_path=PAGE)
    assert multiple.code == OriginCode.FINAL_URL_AMBIGUOUS
    assert multiple.target is None and multiple.candidates == 2
    assert "candidates=MULTIPLE" in multiple.safe_log("MANUAL")


def test_unrelated_requests_cannot_unbound_diagnostic_storage_and_expiry_is_distinct():
    clock = [100.0]
    cache = DownloadRequestOrigins(clock=lambda: clock[0])
    redirect(cache)
    clock[0] += LIFETIME_SECONDS
    assert cache.resolve("page", CDN, page_path=PAGE).code == OriginCode.REQUEST_EXPIRED
    for i in range(2 * MAX_REQUESTS):
        cache.observe("page", Request(f"https://business.kakao.com/chats/?{i}"), page_path=PAGE)
    assert not cache._rejections
    for i in range(2 * MAX_REQUESTS):
        cache.observe("page", Request(f"{CDN}&{i}"), page_path=PAGE)
    assert len(cache._rejections) == MAX_REQUESTS
    clock[0] += LIFETIME_SECONDS
    assert (
        cache.resolve("page", f"{CDN}&{2 * MAX_REQUESTS - 1}", page_path=PAGE).code
        == OriginCode.FINAL_URL_NOT_OBSERVED
    )
    assert not cache._rejections
