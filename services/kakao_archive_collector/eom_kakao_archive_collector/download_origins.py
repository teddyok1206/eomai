"""Bounded page-local GET redirect correlation. No cookies, headers, requests or I/O."""

from __future__ import annotations

import re
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass, field
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
            self._remove(key)

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
        if method != "GET" or not _allowed_url(url) or page_path is None:
            return
        if previous is None:
            target = download_target(url)
            if target.path is None or _IMAGE_PATH.fullmatch(target.path) is None:
                return
            source_path, redirects = target.path, 0
        else:
            if (
                prior is None
                or prior.request is not previous
                or prior.page_path != page_path
                or prior.redirects >= MAX_REDIRECTS
            ):
                return
            source_path, redirects = prior.source_path, prior.redirects + 1
        if len(self._entries) >= MAX_REQUESTS:
            self._remove(next(iter(self._entries)))
        entry = _Origin(
            request, sha256(url.encode()).digest(), source_path, page_path, now, redirects
        )
        self._entries[key] = entry
        self._targets.setdefault((page_id, entry.url_hash), set()).add(key)

    def consume(
        self, page_id: str, url: str, *, page_path: str | None
    ) -> ManualDownloadTarget | None:
        self._expire(self._clock())
        if not _allowed_url(url):
            return None
        keys = tuple(self._targets.get((page_id, sha256(url.encode()).digest()), ()))
        entries = tuple(self._remove(key) for key in keys)
        if (
            page_path is None
            or len(entries) != 1
            or entries[0] is None
            or entries[0].page_path != page_path
        ):
            return None  # Consume ambiguous candidates together; never guess on the next event.
        return ManualDownloadTarget(kind="SAME_ORIGIN_PATH", path=entries[0].source_path)

    def clear(self) -> None:
        self._entries.clear()
        self._targets.clear()

    def __len__(self) -> int:
        return len(self._entries)
