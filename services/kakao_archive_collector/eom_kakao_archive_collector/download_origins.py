"""Bounded page-local GET redirect correlation. No cookies, headers, requests or I/O."""

from __future__ import annotations

import re
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
from hashlib import sha256
from time import monotonic
from typing import Protocol
from urllib.parse import urlsplit

from eom_kakao_archive_contracts.manual_observation import ManualDownloadTarget

from .manual_observation import download_target

MAX_REQUESTS = 64
LIFETIME_SECONDS = 60.0
MAX_REDIRECTS = 8
_IMAGE_PATH = re.compile(
    r"^/api/profiles/[A-Za-z0-9_-]{1,128}/chats/[A-Za-z0-9_-]{1,128}/"
    r"[A-Za-z0-9_-]{1,128}/[A-Za-z0-9_-]{1,128}/image$"
)


class OriginCode(StrEnum):
    VERIFIED = "VERIFIED"
    SDK_DOWNLOAD_METADATA_MISSING = "SDK_DOWNLOAD_METADATA_MISSING"
    DOWNLOAD_PAGE_CHANGED = "DOWNLOAD_PAGE_CHANGED"
    DOWNLOAD_ORIGIN_NOT_ALLOWED = "DOWNLOAD_ORIGIN_NOT_ALLOWED"
    REQUEST_ORIGIN_NOT_ALLOWED = "REQUEST_ORIGIN_NOT_ALLOWED"
    REQUEST_METHOD_NOT_GET = "REQUEST_METHOD_NOT_GET"
    REQUEST_PAGE_UNKNOWN = "REQUEST_PAGE_UNKNOWN"
    SOURCE_PATH_UNRECOGNIZED = "SOURCE_PATH_UNRECOGNIZED"
    INITIAL_PHOTO_REQUEST_NOT_OBSERVED = "INITIAL_PHOTO_REQUEST_NOT_OBSERVED"
    REDIRECT_PREDECESSOR_MISSING = "REDIRECT_PREDECESSOR_MISSING"
    REDIRECT_PAGE_CHANGED = "REDIRECT_PAGE_CHANGED"
    REDIRECT_LIMIT = "REDIRECT_LIMIT"
    REQUEST_EXPIRED = "REQUEST_EXPIRED"
    REQUEST_EVICTED = "REQUEST_EVICTED"
    FINAL_URL_OBSERVED_ON_OTHER_PAGE = "FINAL_URL_OBSERVED_ON_OTHER_PAGE"
    FINAL_URL_NOT_MATCHED = "FINAL_URL_NOT_MATCHED"
    FINAL_URL_NOT_OBSERVED = "FINAL_URL_NOT_OBSERVED"
    FINAL_URL_AMBIGUOUS = "FINAL_URL_AMBIGUOUS"


@dataclass(frozen=True, slots=True)
class OriginDecision:
    code: OriginCode
    target: ManualDownloadTarget | None = field(default=None, repr=False)
    candidates: int = 0
    source_get_observed: bool = False
    final_url_on_same_page: bool = False
    final_url_on_other_page: bool = False

    def safe_log(self, mode: str) -> str:
        assert mode in {"MANUAL", "ONE_ROOM"}
        count = "MULTIPLE" if self.candidates > 1 else str(self.candidates)
        source = "OBSERVED" if self.source_get_observed else "NOT_CONFIRMED"
        return (
            f"KAKAO_DOWNLOAD_ORIGIN mode={mode} code={self.code} candidates={count} "
            f"source_get={source} final_same_page={int(self.final_url_on_same_page)} "
            f"final_other_page={int(self.final_url_on_other_page)}"
        )


class DownloadRequest(Protocol):
    @property
    def url(self) -> str: ...

    @property
    def method(self) -> str: ...

    @property
    def redirected_from(self) -> DownloadRequest | None: ...


@dataclass(frozen=True, slots=True)
class _Origin:
    request: DownloadRequest = field(repr=False)
    url_hash: bytes = field(repr=False)
    source_path: str
    page_path: str
    observed_at: float
    redirects: int


def _allowed_url(url: str) -> bool:
    try:
        if not isinstance(url, str) or not 0 < len(url) <= 8192:
            return False
        value = urlsplit(url)
        return (
            value.scheme == "https"
            and value.hostname in {"business.kakao.com", "k.kakaocdn.net"}
            and value.port in {None, 443}
            and value.username is None
            and value.password is None
        )
    except ValueError:
        return False


class DownloadRequestOrigins:
    """One run's short-lived metadata, consumed once for an unambiguous SDK event."""

    def __init__(self, *, clock: Callable[[], float] = monotonic) -> None:
        self._clock = clock
        self._entries: OrderedDict[tuple[str, int], _Origin] = OrderedDict()
        self._targets: dict[tuple[str, bytes], set[tuple[str, int]]] = {}
        self._rejections: OrderedDict[tuple[str, bytes], tuple[float, OriginCode, bool]] = (
            OrderedDict()
        )

    def _remember(
        self, key: tuple[str, bytes], now: float, code: OriginCode, source_get: bool
    ) -> None:
        self._rejections.pop(key, None)
        if len(self._rejections) >= MAX_REQUESTS:
            self._rejections.popitem(last=False)
        self._rejections[key] = (now, code, source_get)

    def _remove(self, key: tuple[str, int]) -> _Origin | None:
        entry = self._entries.pop(key, None)
        if entry is not None:
            target = (key[0], entry.url_hash)
            self._targets[target].remove(key)
            if not self._targets[target]:
                del self._targets[target]
        return entry

    def _expire(self, now: float) -> None:
        while self._entries:
            key = next(iter(self._entries))
            if self._entries[key].observed_at > now - LIFETIME_SECONDS:
                break
            entry = self._remove(key)
            if entry is not None:
                self._remember((key[0], entry.url_hash), now, OriginCode.REQUEST_EXPIRED, True)
        while self._rejections:
            rejected_key = next(iter(self._rejections))
            if self._rejections[rejected_key][0] > now - LIFETIME_SECONDS:
                break
            del self._rejections[rejected_key]

    def observe(self, page_id: str, request: DownloadRequest, *, page_path: str | None) -> None:
        now = self._clock()
        self._expire(now)
        key = (page_id, id(request))
        if key in self._entries:
            return
        try:
            url, method, previous = request.url, request.method, request.redirected_from
        except Exception:
            return  # Missing optional SDK metadata never fabricates a source link.
        prior = None if previous is None else self._remove((page_id, id(previous)))
        if not isinstance(url, str) or not 0 < len(url) <= 8192:
            return
        allowed = _allowed_url(url)
        target = download_target(url) if allowed else None
        path = target.path if target is not None else None
        source = path is not None and _IMAGE_PATH.fullmatch(path) is not None
        candidate = (
            source
            or prior is not None
            or (
                allowed
                and (
                    path is None or (path.startswith("/api/profiles/") and path.endswith("/image"))
                )
            )
        )
        if not candidate:
            return  # No diagnostics for ordinary non-image page requests.
        try:
            target_key = (page_id, sha256(url.encode()).digest())
        except UnicodeError:
            return  # Unusable SDK metadata must not interfere with payload retention.

        def reject(code: OriginCode) -> None:
            self._remember(target_key, now, code, prior is not None or (source and method == "GET"))

        if not allowed:
            reject(OriginCode.REQUEST_ORIGIN_NOT_ALLOWED)
            return
        if method != "GET":
            reject(OriginCode.REQUEST_METHOD_NOT_GET)
            return
        if page_path is None:
            reject(OriginCode.REQUEST_PAGE_UNKNOWN)
            return
        if previous is None:
            if not source or path is None:
                reject(
                    OriginCode.INITIAL_PHOTO_REQUEST_NOT_OBSERVED
                    if path is None
                    else OriginCode.SOURCE_PATH_UNRECOGNIZED
                )
                return
            source_path, redirects = path, 0
        else:
            if prior is None or prior.request is not previous:
                reject(OriginCode.REDIRECT_PREDECESSOR_MISSING)
                return
            if prior.page_path != page_path:
                reject(OriginCode.REDIRECT_PAGE_CHANGED)
                return
            if prior.redirects >= MAX_REDIRECTS:
                reject(OriginCode.REDIRECT_LIMIT)
                return
            source_path, redirects = prior.source_path, prior.redirects + 1
        if len(self._entries) >= MAX_REQUESTS:
            oldest = next(iter(self._entries))
            evicted = self._remove(oldest)
            if evicted is not None:
                self._remember((oldest[0], evicted.url_hash), now, OriginCode.REQUEST_EVICTED, True)
        entry = _Origin(request, target_key[1], source_path, page_path, now, redirects)
        self._entries[key] = entry
        self._targets.setdefault(target_key, set()).add(key)
        self._rejections.pop(target_key, None)

    def consume(
        self, page_id: str, url: str, *, page_path: str | None
    ) -> ManualDownloadTarget | None:
        return self.resolve(page_id, url, page_path=page_path).target

    def resolve(self, page_id: str, url: str, *, page_path: str | None) -> OriginDecision:
        self._expire(self._clock())
        if not isinstance(url, str) or not url:
            return OriginDecision(OriginCode.SDK_DOWNLOAD_METADATA_MISSING)
        try:
            digest = sha256(url.encode()).digest() if len(url) <= 8192 else b""
        except UnicodeError:
            return OriginDecision(OriginCode.SDK_DOWNLOAD_METADATA_MISSING)
        key = (page_id, digest)
        rejected = self._rejections.pop(key, None)
        if not _allowed_url(url):
            if rejected is not None:
                return OriginDecision(
                    rejected[1], source_get_observed=rejected[2], final_url_on_same_page=True
                )
            return OriginDecision(OriginCode.DOWNLOAD_ORIGIN_NOT_ALLOWED)
        keys = tuple(self._targets.get(key, ()))
        entries = tuple(self._remove(key) for key in keys)
        if len(entries) > 1:
            return OriginDecision(
                OriginCode.FINAL_URL_AMBIGUOUS,
                candidates=len(entries),
                source_get_observed=True,
                final_url_on_same_page=True,
            )
        if entries and (entry := entries[0]) is not None:
            if page_path is None or entry.page_path != page_path:
                return OriginDecision(
                    OriginCode.DOWNLOAD_PAGE_CHANGED,
                    candidates=1,
                    source_get_observed=True,
                    final_url_on_same_page=True,
                )
            target = ManualDownloadTarget(kind="SAME_ORIGIN_PATH", path=entry.source_path)
            return OriginDecision(OriginCode.VERIFIED, target, 1, True, True)
        if rejected is not None:
            return OriginDecision(
                rejected[1], source_get_observed=rejected[2], final_url_on_same_page=True
            )
        if any(other != page_id and url_hash == digest for other, url_hash in self._targets):
            return OriginDecision(
                OriginCode.FINAL_URL_OBSERVED_ON_OTHER_PAGE, final_url_on_other_page=True
            )
        if any(other == page_id for other, _ in self._targets):
            return OriginDecision(OriginCode.FINAL_URL_NOT_MATCHED)
        return OriginDecision(OriginCode.FINAL_URL_NOT_OBSERVED)

    def clear(self) -> None:
        self._entries.clear()
        self._targets.clear()
        self._rejections.clear()

    def __len__(self) -> int:
        return len(self._entries)
