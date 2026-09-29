"""Bounded Wikimedia Commons acquisition for visual-reference conditioning."""

from __future__ import annotations

import hashlib
import html
import ipaddress
import json
import os
import re
import shutil
import socket
import stat
import tempfile
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol, cast
from urllib.error import HTTPError
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit
from urllib.request import (
    HTTPRedirectHandler,
    OpenerDirector,
    ProxyHandler,
    Request,
    build_opener,
)

from eom_image_contracts import (
    LocalImageVisualReferenceAcquisitionCommand,
    LocalImageVisualReferenceAcquisitionResult,
    LocalImageVisualReferenceBundle,
    LocalImageVisualReferenceDiscoveryCommand,
    LocalImageVisualReferenceDiscoveryResult,
    LocalImageVisualReferenceIntent,
    NormalizedVisualReferenceMember,
    VisualReferenceAcquisitionOutputFile,
    VisualReferenceIntentCandidate,
    VisualReferenceSource,
    content_json_bytes,
    content_sha256,
    validate_contract,
    validate_visual_reference_acquisition,
    validate_visual_reference_discovery,
)

COMMONS_API = "https://commons.wikimedia.org/w/api.php"
COMMONS_HOST = "commons.wikimedia.org"
UPLOAD_HOST = "upload.wikimedia.org"
USER_AGENT = "EOMVisualReferenceBot/1.1 (https://eomai.duckdns.org/)"
MAX_RATE_LIMIT_RETRIES = 2
MAX_RETRY_AFTER_SECONDS = 30
MAX_API_BYTES = 2 * 1024 * 1024
MAX_IMAGE_PIXELS = 40_000_000
NORMALIZED_WIDTH = 800
NORMALIZED_HEIGHT = 504
RESULT_MEMBER = "result.json"
BUNDLE_MEMBER = "manifests/visual-reference-bundle.json"
REFERENCE_MEMBER = "references/primary.png"
_SAFE_ERROR_CODES = frozenset(
    {
        "VISUAL_REFERENCE_INPUT_INVALID",
        "VISUAL_REFERENCE_SOURCE_UNAVAILABLE",
        "VISUAL_REFERENCE_SOURCE_REJECTED",
        "VISUAL_REFERENCE_LICENSE_REJECTED",
        "VISUAL_REFERENCE_IMAGE_INVALID",
        "VISUAL_REFERENCE_OUTPUT_INVALID",
    }
)
_HTML_TAG = re.compile(r"<[^>]+>")
_MULTI_SUBJECT_TITLE_MARKERS = (
    " collage",
    " collection",
    " comparison",
    " display",
    " exhibit",
    " group",
    " montage",
    " multiple",
    " plate",
    " specimens",
    " cast",
    " with cast",
)
_SINGLE_SUBJECT_EXCLUSION_MARKERS = (
    " collage",
    " collection",
    " comparison",
    " display",
    " exhibit",
    " group",
    " montage",
    " multiple",
    " pavement",
    " plate",
    " specimens",
)
_VIEWPOINT_TITLE_MARKERS = ("dorsal", "front", "rear", "side", "top")
_REFERENCE_QUERY_MODIFIERS = re.compile(
    r"\b(?:seen from above|viewed from above|from above|top view|dorsal view|side view|"
    r"front view|rear view|isolated on (?:a )?white(?: background)?)\b",
    re.IGNORECASE,
)


class VisualReferenceAcquisitionError(RuntimeError):
    """Stable, content-free reference-acquisition error."""

    def __init__(self, code: str) -> None:
        if code not in _SAFE_ERROR_CODES:
            raise ValueError("unknown visual-reference error code")
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class AcquiredReference:
    source: VisualReferenceSource
    original_bytes: bytes


@dataclass(frozen=True, slots=True)
class VisualReferenceAcquisitionOutput:
    result: LocalImageVisualReferenceAcquisitionResult
    output_directory: Path
    bundle_path: Path | None
    reference_path: Path | None
    result_path: Path


@dataclass(frozen=True, slots=True)
class VisualReferenceDiscoveryOutput:
    result: LocalImageVisualReferenceDiscoveryResult
    output_directory: Path
    result_path: Path


class HttpResponse(Protocol):
    headers: Any

    def read(self, amount: int = -1) -> bytes: ...

    def close(self) -> None: ...

    def geturl(self) -> str: ...


class _RestrictedRedirectHandler(HTTPRedirectHandler):
    def __init__(self, hosts: frozenset[str]) -> None:
        self.hosts = hosts

    def redirect_request(
        self,
        req: Request,
        fp: object,
        code: int,
        msg: str,
        headers: object,
        newurl: str,
    ) -> Request | None:
        target = _require_https_url(urljoin(req.full_url, newurl), hosts=self.hosts)
        return super().redirect_request(req, fp, code, msg, headers, target)  # type: ignore[arg-type]


class WikimediaCommonsClient:
    """Verify worker-proposed Commons candidates against official typed metadata."""

    def __init__(
        self,
        *,
        opener: OpenerDirector | None = None,
        address_resolver: Callable[..., list[tuple[Any, ...]]] = socket.getaddrinfo,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        self.allowed_hosts = frozenset({COMMONS_HOST, UPLOAD_HOST})
        # Do not inherit ambient proxy variables.  The acquisition unit is allowed to
        # reach only the explicitly reviewed Wikimedia hosts.
        self.opener = opener or build_opener(
            ProxyHandler({}), _RestrictedRedirectHandler(self.allowed_hosts)
        )
        self.address_resolver = address_resolver
        self.sleeper = sleeper

    def acquire(
        self,
        intent: LocalImageVisualReferenceIntent,
        *,
        maximum_bytes: int,
        timeout_seconds: int,
    ) -> tuple[AcquiredReference, ...]:
        pages = self._load_pages(intent, timeout_seconds=timeout_seconds)
        acquired: list[AcquiredReference] = []
        for candidate in intent.candidates:
            page = pages.get(candidate.page_id)
            if page is None:
                raise VisualReferenceAcquisitionError("VISUAL_REFERENCE_SOURCE_REJECTED")
            metadata = _verified_page(candidate, page)
            original = self._download(
                metadata["original_file_url"],
                expected_media_type=metadata["original_media_type"],
                expected_size=metadata["original_size_bytes"],
                maximum_bytes=maximum_bytes,
                timeout_seconds=timeout_seconds,
            )
            digest = "sha256:" + hashlib.sha256(original).hexdigest()
            reference_id = (
                "imgref_"
                + content_sha256(
                    {
                        "provider": "WIKIMEDIA_COMMONS",
                        "page_id": candidate.page_id,
                        "page_revision_id": metadata["page_revision_id"],
                        "original_sha256": digest,
                    }
                ).removeprefix("sha256:")[:32]
            )
            source = VisualReferenceSource.model_validate(
                {
                    "reference_id": reference_id,
                    "rank": candidate.rank,
                    "provider": "WIKIMEDIA_COMMONS",
                    "page_id": candidate.page_id,
                    "page_revision_id": metadata["page_revision_id"],
                    "file_title": candidate.file_title,
                    "canonical_page_url": candidate.canonical_page_url,
                    "original_file_url": metadata["original_file_url"],
                    "original_media_type": metadata["original_media_type"],
                    "original_size_bytes": len(original),
                    "original_sha256": digest,
                    "original_width_px": metadata["original_width_px"],
                    "original_height_px": metadata["original_height_px"],
                    "license_id": metadata["license_id"],
                    "license_url": metadata["license_url"],
                    "license_short_name": metadata["license_short_name"],
                    "attribution_required": False,
                    "intended_use": "SUBJECT_MORPHOLOGY_REFERENCE",
                    "disposition": (
                        "PRIMARY_CONDITIONING"
                        if candidate.page_id == intent.primary_candidate_page_id
                        else "VERIFIED_ALTERNATE"
                    ),
                }
            )
            acquired.append(AcquiredReference(source=source, original_bytes=original))
        hashes = tuple(value.source.original_sha256 for value in acquired)
        if len(hashes) != len(set(hashes)):
            raise VisualReferenceAcquisitionError("VISUAL_REFERENCE_SOURCE_REJECTED")
        return tuple(acquired)

    def discover_candidates(
        self,
        *,
        subject: str,
        query_terms: tuple[str, ...],
        candidate_limit: int,
        timeout_seconds: int,
    ) -> tuple[VisualReferenceIntentCandidate, ...]:
        """Return a stable ordered subset of official, license-compatible Commons files."""

        if (
            not 3 <= len(subject) <= 180
            or not 1 <= len(query_terms) <= 8
            or query_terms != tuple(sorted(set(query_terms)))
            or any(not 1 <= len(value) <= 80 for value in query_terms)
            or not 1 <= candidate_limit <= 5
        ):
            raise VisualReferenceAcquisitionError("VISUAL_REFERENCE_INPUT_INVALID")
        ordered_query_terms = tuple(
            sorted(
                query_terms,
                key=lambda value: (not value.casefold().endswith(" illustration"), value),
            )
        )
        query = ordered_query_terms[0]
        selected_query = query
        discovered: list[tuple[int, VisualReferenceIntentCandidate]] = []
        for query in ordered_query_terms:
            for selected_query in _reference_discovery_queries(query):
                raw_pages = self._load_discovery_pages(
                    selected_query,
                    timeout_seconds=timeout_seconds,
                )
                discovered = self._verified_discovery_candidates(
                    raw_pages,
                    candidate_limit=candidate_limit,
                )
                if discovered:
                    break
            if discovered:
                break
        if not discovered:
            raise VisualReferenceAcquisitionError("VISUAL_REFERENCE_SOURCE_REJECTED")
        ranked = sorted(
            tuple(
                value
                for value in discovered
                if not (
                    _subject_requests_one(subject)
                    and _title_has_marker(value[1].file_title, _SINGLE_SUBJECT_EXCLUSION_MARKERS)
                )
            ),
            key=lambda value: _reference_candidate_order(
                value[1], query=query, official_rank=value[0]
            ),
        )[:candidate_limit]
        if not ranked:
            raise VisualReferenceAcquisitionError("VISUAL_REFERENCE_SOURCE_REJECTED")
        used_fallback = selected_query != query
        used_illustration_query = query.casefold().endswith(" illustration")
        return tuple(
            VisualReferenceIntentCandidate.model_validate(
                {
                    **candidate.model_dump(mode="json"),
                    "rank": rank,
                    "selection_rationale": (
                        "Official Commons result selected by stable morphology suitability "
                        "ranking; a clean illustration query is preferred when declared, "
                        "explicit aggregate titles are excluded for one-subject requests, and "
                        "other montage-like file titles are deprioritized"
                        + (
                            " after one bounded subject-only query fallback."
                            if used_fallback
                            else (
                                " using the bounded illustration query."
                                if used_illustration_query
                                else "."
                            )
                        )
                    ),
                }
            )
            for rank, (_official_rank, candidate) in enumerate(ranked, start=1)
        )

    def _load_discovery_pages(
        self,
        query: str,
        *,
        timeout_seconds: int,
    ) -> list[object]:
        parameters = urlencode(
            {
                "action": "query",
                "format": "json",
                "formatversion": "2",
                "generator": "search",
                "gsrsearch": query,
                "gsrnamespace": "6",
                "gsrlimit": "20",
                "gsrwhat": "text",
                "prop": "info|revisions|imageinfo",
                "inprop": "url",
                "rvprop": "ids",
                "iiprop": "url|size|mime|extmetadata",
                "maxlag": "5",
            }
        )
        request_url = f"{COMMONS_API}?{parameters}"
        response = self._open(request_url, timeout_seconds=timeout_seconds)
        try:
            if response.geturl() != request_url:
                raise VisualReferenceAcquisitionError("VISUAL_REFERENCE_SOURCE_REJECTED")
            media_type = response.headers.get_content_type()
            raw = response.read(MAX_API_BYTES + 1)
        except OSError as exc:
            raise VisualReferenceAcquisitionError("VISUAL_REFERENCE_SOURCE_UNAVAILABLE") from exc

        finally:
            response.close()
        if media_type not in {"application/json", "text/json"} or len(raw) > MAX_API_BYTES:
            raise VisualReferenceAcquisitionError("VISUAL_REFERENCE_SOURCE_REJECTED")
        try:
            value = json.loads(raw, object_pairs_hook=_unique_object)
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise VisualReferenceAcquisitionError("VISUAL_REFERENCE_SOURCE_REJECTED") from exc
        raw_pages = _mapping(value, "query").get("pages")
        if not isinstance(raw_pages, list):
            raise VisualReferenceAcquisitionError("VISUAL_REFERENCE_SOURCE_REJECTED")
        return raw_pages

    @staticmethod
    def _verified_discovery_candidates(
        raw_pages: list[object],
        *,
        candidate_limit: int,
    ) -> list[tuple[int, VisualReferenceIntentCandidate]]:
        ordered_pages = sorted(raw_pages, key=_discovery_page_order)
        discovered: list[tuple[int, VisualReferenceIntentCandidate]] = []
        seen_page_ids: set[int] = set()
        seen_titles: set[str] = set()
        for raw_page in ordered_pages:
            if not isinstance(raw_page, dict):
                raise VisualReferenceAcquisitionError("VISUAL_REFERENCE_SOURCE_REJECTED")
            page_id = raw_page.get("pageid")
            title = raw_page.get("title")
            canonical_url = raw_page.get("canonicalurl")
            if (
                not isinstance(page_id, int)
                or page_id in seen_page_ids
                or not isinstance(title, str)
                or title in seen_titles
                or not isinstance(canonical_url, str)
            ):
                raise VisualReferenceAcquisitionError("VISUAL_REFERENCE_SOURCE_REJECTED")
            seen_page_ids.add(page_id)
            seen_titles.add(title)
            candidate = VisualReferenceIntentCandidate.model_validate(
                {
                    "rank": len(discovered) + 1,
                    "provider": "WIKIMEDIA_COMMONS",
                    "page_id": page_id,
                    "file_title": title,
                    "canonical_page_url": canonical_url,
                    "selection_rationale": (
                        "Official Commons result selected for the exact morphology subject."
                    ),
                    "intended_use": "SUBJECT_MORPHOLOGY_REFERENCE",
                    "license_expectation": "PUBLIC_DOMAIN_OR_CC0",
                }
            )
            try:
                _verified_page(candidate, raw_page)
            except VisualReferenceAcquisitionError as exc:
                if exc.code not in {
                    "VISUAL_REFERENCE_SOURCE_REJECTED",
                    "VISUAL_REFERENCE_LICENSE_REJECTED",
                }:
                    raise
                continue
            discovered.append((len(discovered), candidate))
            if len(discovered) == candidate_limit:
                break
        return discovered

    def _load_pages(
        self,
        intent: LocalImageVisualReferenceIntent,
        *,
        timeout_seconds: int,
    ) -> dict[int, dict[str, object]]:
        parameters = urlencode(
            {
                "action": "query",
                "format": "json",
                "formatversion": "2",
                "pageids": "|".join(str(candidate.page_id) for candidate in intent.candidates),
                "prop": "info|revisions|imageinfo",
                "inprop": "url",
                "rvprop": "ids",
                "iiprop": "url|size|mime|extmetadata",
                "maxlag": "5",
            }
        )
        response = self._open(f"{COMMONS_API}?{parameters}", timeout_seconds=timeout_seconds)
        try:
            if response.geturl() != f"{COMMONS_API}?{parameters}":
                raise VisualReferenceAcquisitionError("VISUAL_REFERENCE_SOURCE_REJECTED")
            media_type = response.headers.get_content_type()
            raw = response.read(MAX_API_BYTES + 1)
        except OSError as exc:
            raise VisualReferenceAcquisitionError("VISUAL_REFERENCE_SOURCE_UNAVAILABLE") from exc
        finally:
            response.close()
        if media_type not in {"application/json", "text/json"} or len(raw) > MAX_API_BYTES:
            raise VisualReferenceAcquisitionError("VISUAL_REFERENCE_SOURCE_REJECTED")
        try:
            value = json.loads(raw, object_pairs_hook=_unique_object)
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise VisualReferenceAcquisitionError("VISUAL_REFERENCE_SOURCE_REJECTED") from exc
        query = _mapping(value, "query")
        raw_pages = query.get("pages")
        if not isinstance(raw_pages, list) or len(raw_pages) != len(intent.candidates):
            raise VisualReferenceAcquisitionError("VISUAL_REFERENCE_SOURCE_REJECTED")
        pages: dict[int, dict[str, object]] = {}
        for raw_page in raw_pages:
            if not isinstance(raw_page, dict):
                raise VisualReferenceAcquisitionError("VISUAL_REFERENCE_SOURCE_REJECTED")
            page_id = raw_page.get("pageid")
            if not isinstance(page_id, int) or page_id in pages:
                raise VisualReferenceAcquisitionError("VISUAL_REFERENCE_SOURCE_REJECTED")
            pages[page_id] = raw_page
        return pages

    def _download(
        self,
        url: object,
        *,
        expected_media_type: object,
        expected_size: object,
        maximum_bytes: int,
        timeout_seconds: int,
    ) -> bytes:
        if (
            not isinstance(url, str)
            or not isinstance(expected_media_type, str)
            or not isinstance(expected_size, int)
            or not 1 <= expected_size <= maximum_bytes
        ):
            raise VisualReferenceAcquisitionError("VISUAL_REFERENCE_SOURCE_REJECTED")
        response = self._open(url, timeout_seconds=timeout_seconds)
        try:
            resolved = _require_https_url(response.geturl(), hosts=frozenset({UPLOAD_HOST}))
            if resolved != url or response.headers.get_content_type() != expected_media_type:
                raise VisualReferenceAcquisitionError("VISUAL_REFERENCE_SOURCE_REJECTED")
            declared = response.headers.get("Content-Length")
            if declared is not None and (
                not declared.isdigit()
                or int(declared) != expected_size
                or int(declared) > maximum_bytes
            ):
                raise VisualReferenceAcquisitionError("VISUAL_REFERENCE_SOURCE_REJECTED")
            raw = response.read(maximum_bytes + 1)
        except VisualReferenceAcquisitionError:
            raise
        except OSError as exc:
            raise VisualReferenceAcquisitionError("VISUAL_REFERENCE_SOURCE_UNAVAILABLE") from exc
        finally:
            response.close()
        if len(raw) != expected_size or len(raw) > maximum_bytes:
            raise VisualReferenceAcquisitionError("VISUAL_REFERENCE_SOURCE_REJECTED")
        return raw

    def _open(self, url: str, *, timeout_seconds: int) -> HttpResponse:
        normalized = _require_https_url(url, hosts=self.allowed_hosts, allow_query=True)
        host = cast(str, urlsplit(normalized).hostname)
        _require_public_addresses(host, self.address_resolver)
        request = Request(
            normalized,
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "application/json,image/jpeg,image/png,image/webp;q=0.9,*/*;q=0.1",
            },
        )
        for retry in range(MAX_RATE_LIMIT_RETRIES + 1):
            try:
                return cast(HttpResponse, self.opener.open(request, timeout=timeout_seconds))
            except HTTPError as exc:
                if exc.code != 429 or retry == MAX_RATE_LIMIT_RETRIES:
                    exc.close()
                    raise VisualReferenceAcquisitionError(
                        "VISUAL_REFERENCE_SOURCE_UNAVAILABLE"
                    ) from exc
                retry_after = exc.headers.get("Retry-After")
                exc.close()
                if retry_after is None or not retry_after.isdigit():
                    raise VisualReferenceAcquisitionError(
                        "VISUAL_REFERENCE_SOURCE_UNAVAILABLE"
                    ) from exc
                delay = int(retry_after)
                if not 1 <= delay <= MAX_RETRY_AFTER_SECONDS:
                    raise VisualReferenceAcquisitionError(
                        "VISUAL_REFERENCE_SOURCE_UNAVAILABLE"
                    ) from exc
                self.sleeper(float(delay))
            except OSError as exc:
                raise VisualReferenceAcquisitionError(
                    "VISUAL_REFERENCE_SOURCE_UNAVAILABLE"
                ) from exc
        raise AssertionError("unreachable rate-limit retry state")


def run_visual_reference_discovery(
    *,
    command: LocalImageVisualReferenceDiscoveryCommand,
    workspace: Path,
    client: WikimediaCommonsClient | None = None,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
    monotonic_ns: Callable[[], int] = time.monotonic_ns,
) -> VisualReferenceDiscoveryOutput:
    """Resolve a subject-only command into bounded, metadata-verified candidate identities."""

    _require_workspace(workspace)
    output = workspace / "output"
    if output.exists() or output.is_symlink():
        raise VisualReferenceAcquisitionError("VISUAL_REFERENCE_OUTPUT_INVALID")
    started_at = now()
    started_clock = monotonic_ns()
    resolved_client = client or WikimediaCommonsClient()
    try:
        candidates = resolved_client.discover_candidates(
            subject=command.subject,
            query_terms=command.query_terms,
            candidate_limit=command.candidate_limit,
            timeout_seconds=command.timeout_seconds,
        )
        status = "SUCCEEDED"
        error_code = None
    except VisualReferenceAcquisitionError as exc:
        candidates = ()
        status = "FAILED"
        error_code = exc.code
    completed_at = now()
    duration_ms = min(max(1, (monotonic_ns() - started_clock) // 1_000_000), 180_000)
    body = {
        "schema_version": "local-image-visual-reference-discovery-result/1.0",
        "command_id": command.command_id,
        "command_sha256": command.command_sha256,
        "status": status,
        "candidates": [value.model_dump(mode="json") for value in candidates],
        "error_code": error_code,
        "started_at": started_at.isoformat().replace("+00:00", "Z"),
        "completed_at": completed_at.isoformat().replace("+00:00", "Z"),
        "duration_ms": duration_ms,
    }
    try:
        result = LocalImageVisualReferenceDiscoveryResult.model_validate(
            {**body, "result_sha256": content_sha256(body)}
        )
        validate_contract("visual-reference-discovery-result", result.model_dump(mode="json"))
        validate_visual_reference_discovery(command, result)
    except Exception as exc:
        raise VisualReferenceAcquisitionError("VISUAL_REFERENCE_OUTPUT_INVALID") from exc
    _publish_output(
        workspace,
        {RESULT_MEMBER: content_json_bytes(result.model_dump(mode="json"))},
    )
    return VisualReferenceDiscoveryOutput(
        result=result,
        output_directory=output,
        result_path=output / RESULT_MEMBER,
    )


def run_visual_reference_acquisition(
    *,
    command: LocalImageVisualReferenceAcquisitionCommand,
    intent: LocalImageVisualReferenceIntent,
    workspace: Path,
    client: WikimediaCommonsClient | None = None,
    normalizer: Callable[[bytes, str, int, int], bytes] | None = None,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
    monotonic_ns: Callable[[], int] = time.monotonic_ns,
) -> VisualReferenceAcquisitionOutput:
    """Acquire and atomically materialize one exact visual-reference result."""

    _require_workspace(workspace)
    output = workspace / "output"
    if output.exists() or output.is_symlink():
        raise VisualReferenceAcquisitionError("VISUAL_REFERENCE_OUTPUT_INVALID")
    started_at = now()
    started_clock = monotonic_ns()
    resolved_client = client or WikimediaCommonsClient()
    resolved_normalizer = normalizer or normalize_reference_image
    try:
        acquired = resolved_client.acquire(
            intent,
            maximum_bytes=command.max_original_bytes,
            timeout_seconds=command.timeout_seconds,
        )
        primary = acquired[0]
        normalized = resolved_normalizer(
            primary.original_bytes,
            primary.source.original_media_type,
            primary.source.original_width_px,
            primary.source.original_height_px,
        )
        normalized_hash = "sha256:" + hashlib.sha256(normalized).hexdigest()
        normalized_member = NormalizedVisualReferenceMember(
            size_bytes=len(normalized),
            sha256=normalized_hash,
        )
        identity = content_sha256(
            {
                "intent": command.intent.model_dump(mode="json"),
                "intent_subject": intent.subject,
                "provider_api_revision": "wikimedia-commons-api/1.0",
                "sources": [value.source.model_dump(mode="json") for value in acquired],
                "normalization_policy": "reference-raster-normalization/1.0",
                "normalized_member": normalized_member.model_dump(mode="json"),
            }
        ).removeprefix("sha256:")
        bundle_body = {
            "schema_version": "local-image-visual-reference-bundle/1.0",
            "bundle_id": "imgrefbundle_" + identity[:32],
            "bundle_revision_id": "imgrefbundlerev_" + identity[32:],
            "state": "APPROVED",
            "intent": command.intent.model_dump(mode="json"),
            "subject": intent.subject,
            "provider_api_revision": "wikimedia-commons-api/1.0",
            "observed_at": command.observed_at.isoformat().replace("+00:00", "Z"),
            "sources": [value.source.model_dump(mode="json") for value in acquired],
            "primary_reference_id": primary.source.reference_id,
            "normalization_policy": "reference-raster-normalization/1.0",
            "normalized_member": normalized_member.model_dump(mode="json"),
        }
        bundle = LocalImageVisualReferenceBundle.model_validate(
            {**bundle_body, "bundle_sha256": content_sha256(bundle_body)}
        )
        validate_contract("visual-reference-bundle", bundle.model_dump(mode="json"))
        bundle_bytes = content_json_bytes(bundle.model_dump(mode="json"))
        output_files = (
            VisualReferenceAcquisitionOutputFile.model_validate(
                {
                    "member_path": BUNDLE_MEMBER,
                    "schema_ref": (
                        "eom://schemas/image-provider/local-image-visual-reference-bundle/1.0"
                    ),
                    "media_type": "application/json",
                    "size_bytes": len(bundle_bytes),
                    "sha256": "sha256:" + hashlib.sha256(bundle_bytes).hexdigest(),
                }
            ),
            VisualReferenceAcquisitionOutputFile.model_validate(
                {
                    "member_path": REFERENCE_MEMBER,
                    "schema_ref": ("eom://schemas/image-provider/normalized-visual-reference/1.0"),
                    "media_type": "image/png",
                    "size_bytes": len(normalized),
                    "sha256": normalized_hash,
                }
            ),
        )
        completed_at = now()
        duration_ms = max(1, (monotonic_ns() - started_clock) // 1_000_000)
        result = _build_result(
            command=command,
            status="SUCCEEDED",
            bundle=bundle,
            output_files=output_files,
            error_code=None,
            started_at=started_at,
            completed_at=completed_at,
            duration_ms=duration_ms,
        )
        validate_visual_reference_acquisition(command, intent, result)
        result_bytes = content_json_bytes(result.model_dump(mode="json"))
        _publish_output(
            workspace,
            {
                BUNDLE_MEMBER: bundle_bytes,
                REFERENCE_MEMBER: normalized,
                RESULT_MEMBER: result_bytes,
            },
        )
        return VisualReferenceAcquisitionOutput(
            result=result,
            output_directory=output,
            bundle_path=output / BUNDLE_MEMBER,
            reference_path=output / REFERENCE_MEMBER,
            result_path=output / RESULT_MEMBER,
        )
    except VisualReferenceAcquisitionError as exc:
        completed_at = now()
        duration_ms = max(1, (monotonic_ns() - started_clock) // 1_000_000)
        result = _build_result(
            command=command,
            status="FAILED",
            bundle=None,
            output_files=(),
            error_code=exc.code,
            started_at=started_at,
            completed_at=completed_at,
            duration_ms=min(duration_ms, 180_000),
        )
        result_bytes = content_json_bytes(result.model_dump(mode="json"))
        _publish_output(workspace, {RESULT_MEMBER: result_bytes})
        return VisualReferenceAcquisitionOutput(
            result=result,
            output_directory=output,
            bundle_path=None,
            reference_path=None,
            result_path=output / RESULT_MEMBER,
        )


def normalize_reference_image(
    raw: bytes,
    media_type: str,
    expected_width: int,
    expected_height: int,
) -> bytes:
    """Decode, orient, and deterministically fit one untrusted raster to the fixed canvas."""

    try:
        import io
        import warnings

        from PIL import Image, ImageOps  # type: ignore[import-not-found]
    except ImportError as exc:
        raise VisualReferenceAcquisitionError("VISUAL_REFERENCE_IMAGE_INVALID") from exc
    expected_format = {
        "image/jpeg": "JPEG",
        "image/png": "PNG",
        "image/webp": "WEBP",
    }.get(media_type)
    if expected_format is None:
        raise VisualReferenceAcquisitionError("VISUAL_REFERENCE_IMAGE_INVALID")
    try:
        Image.MAX_IMAGE_PIXELS = MAX_IMAGE_PIXELS
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(raw)) as source:
                if (
                    source.format != expected_format
                    or getattr(source, "is_animated", False)
                    or source.width * source.height > MAX_IMAGE_PIXELS
                ):
                    raise VisualReferenceAcquisitionError("VISUAL_REFERENCE_IMAGE_INVALID")
                oriented = ImageOps.exif_transpose(source)
                if (
                    oriented.size != (expected_width, expected_height)
                    or oriented.width * oriented.height > MAX_IMAGE_PIXELS
                ):
                    raise VisualReferenceAcquisitionError("VISUAL_REFERENCE_IMAGE_INVALID")
                converted = oriented.convert("RGB")
                converted.thumbnail(
                    (NORMALIZED_WIDTH, NORMALIZED_HEIGHT),
                    resample=Image.Resampling.LANCZOS,
                    reducing_gap=3.0,
                )
                canvas = Image.new("RGB", (NORMALIZED_WIDTH, NORMALIZED_HEIGHT), "white")
                left = (NORMALIZED_WIDTH - converted.width) // 2
                top = (NORMALIZED_HEIGHT - converted.height) // 2
                canvas.paste(converted, (left, top))
                output = io.BytesIO()
                canvas.save(output, format="PNG", optimize=False, compress_level=9)
                return output.getvalue()
    except VisualReferenceAcquisitionError:
        raise
    except Exception as exc:
        raise VisualReferenceAcquisitionError("VISUAL_REFERENCE_IMAGE_INVALID") from exc


def load_acquisition_inputs(
    *,
    command_path: Path,
    workspace: Path,
) -> tuple[LocalImageVisualReferenceAcquisitionCommand, LocalImageVisualReferenceIntent]:
    """Load canonical command and intent bytes without following mutable links."""

    _require_workspace(workspace)
    command_value, _ = _load_canonical_json(command_path, maximum_bytes=256 * 1024)
    try:
        validate_contract("visual-reference-acquisition-command", command_value)
        command = LocalImageVisualReferenceAcquisitionCommand.model_validate(command_value)
    except Exception as exc:
        raise VisualReferenceAcquisitionError("VISUAL_REFERENCE_INPUT_INVALID") from exc
    intent_path = workspace / command.intent_member_path
    intent_value, intent_raw = _load_canonical_json(intent_path, maximum_bytes=256 * 1024)
    if (
        len(intent_raw) != command.intent.size_bytes
        or "sha256:" + hashlib.sha256(intent_raw).hexdigest() != command.intent.sha256
    ):
        raise VisualReferenceAcquisitionError("VISUAL_REFERENCE_INPUT_INVALID")
    try:
        validate_contract("visual-reference-intent", intent_value)
        intent = LocalImageVisualReferenceIntent.model_validate(intent_value)
    except Exception as exc:
        raise VisualReferenceAcquisitionError("VISUAL_REFERENCE_INPUT_INVALID") from exc
    return command, intent


def load_discovery_command(
    *,
    command_path: Path,
    workspace: Path,
) -> LocalImageVisualReferenceDiscoveryCommand:
    """Load one canonical discovery command without following mutable links."""

    _require_workspace(workspace)
    command_value, _ = _load_canonical_json(command_path, maximum_bytes=256 * 1024)
    try:
        validate_contract("visual-reference-discovery-command", command_value)
        return LocalImageVisualReferenceDiscoveryCommand.model_validate(command_value)
    except Exception as exc:
        raise VisualReferenceAcquisitionError("VISUAL_REFERENCE_INPUT_INVALID") from exc


def _verified_page(
    candidate: object,
    page: dict[str, object],
) -> dict[str, object]:
    from eom_image_contracts import VisualReferenceIntentCandidate

    if not isinstance(candidate, VisualReferenceIntentCandidate):
        raise VisualReferenceAcquisitionError("VISUAL_REFERENCE_SOURCE_REJECTED")
    title = page.get("title")
    canonical_url = page.get("canonicalurl")
    namespace = page.get("ns")
    revisions = page.get("revisions")
    image_info = page.get("imageinfo")
    if (
        namespace != 6
        or title != candidate.file_title
        or canonical_url != candidate.canonical_page_url
        or not isinstance(revisions, list)
        or len(revisions) != 1
        or not isinstance(revisions[0], dict)
        or not isinstance(revisions[0].get("revid"), int)
        or not isinstance(image_info, list)
        or len(image_info) != 1
        or not isinstance(image_info[0], dict)
    ):
        raise VisualReferenceAcquisitionError("VISUAL_REFERENCE_SOURCE_REJECTED")
    info = image_info[0]
    original_url = _canonical_original_file_url(info.get("url"))
    media_type = info.get("mime")
    size = info.get("size")
    width = info.get("width")
    height = info.get("height")
    metadata = info.get("extmetadata")
    if (
        original_url is None
        or media_type not in {"image/jpeg", "image/png", "image/webp"}
        or not isinstance(size, int)
        or not 1 <= size <= 16 * 1024 * 1024
        or not isinstance(width, int)
        or not isinstance(height, int)
        or not 64 <= width <= 12_000
        or not 64 <= height <= 12_000
        or width * height > MAX_IMAGE_PIXELS
        or not isinstance(metadata, dict)
    ):
        raise VisualReferenceAcquisitionError("VISUAL_REFERENCE_SOURCE_REJECTED")
    license_id, license_url, license_name = _license(metadata)
    return {
        "page_revision_id": revisions[0]["revid"],
        "original_file_url": original_url,
        "original_media_type": media_type,
        "original_size_bytes": size,
        "original_width_px": width,
        "original_height_px": height,
        "license_id": license_id,
        "license_url": license_url,
        "license_short_name": license_name,
    }


def _canonical_original_file_url(value: object) -> str | None:
    """Strip only Wikimedia's fixed imageinfo tracking tuple from an upload URL."""

    if not isinstance(value, str):
        return None
    try:
        parsed = urlsplit(value)
        _require_https_url(value, hosts=frozenset({UPLOAD_HOST}), allow_query=True)
    except VisualReferenceAcquisitionError:
        return None
    if parsed.query:
        pairs = parse_qsl(parsed.query, keep_blank_values=True, strict_parsing=True)
        if pairs != [
            ("utm_source", "commons.wikimedia.org"),
            ("utm_campaign", "imageinfo"),
            ("utm_content", "original"),
        ]:
            return None
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))


def _license(metadata: dict[str, object]) -> tuple[str, str, str]:
    raw_code = _metadata_text(metadata, "License").casefold()
    _metadata_text(metadata, "LicenseShortName")
    # Commons still emits legacy HTTP or localized deed URLs for some otherwise valid
    # public-domain records.  Treat that field as untrusted descriptive metadata and bind
    # accepted identifiers to our fixed canonical license URLs instead.
    _metadata_text(metadata, "LicenseUrl", required=False)
    if raw_code in {"cc-zero", "cc0", "cc0-1.0"}:
        license_id = "CC0-1.0"
        license_url = "https://creativecommons.org/publicdomain/zero/1.0/"
        license_name = "CC0 1.0"
    elif raw_code in {"pd", "public-domain", "public domain"} or raw_code.startswith("pd-"):
        license_id = "PUBLIC-DOMAIN"
        license_url = "https://commons.wikimedia.org/wiki/Commons:Public_domain"
        license_name = "Public domain"
    else:
        raise VisualReferenceAcquisitionError("VISUAL_REFERENCE_LICENSE_REJECTED")
    _require_https_url(
        license_url,
        hosts=frozenset(
            {"creativecommons.org", "www.creativecommons.org", "commons.wikimedia.org"}
        ),
    )
    return license_id, license_url, license_name


def _metadata_text(
    metadata: dict[str, object],
    key: str,
    *,
    required: bool = True,
) -> str:
    entry = metadata.get(key)
    if entry is None and not required:
        return ""
    if not isinstance(entry, dict) or not isinstance(entry.get("value"), str):
        raise VisualReferenceAcquisitionError("VISUAL_REFERENCE_LICENSE_REJECTED")
    value = html.unescape(_HTML_TAG.sub("", cast(str, entry["value"]))).strip()
    if (required and not value) or len(value) > 1000 or any(ord(char) < 32 for char in value):
        raise VisualReferenceAcquisitionError("VISUAL_REFERENCE_LICENSE_REJECTED")
    return value


def _build_result(
    *,
    command: LocalImageVisualReferenceAcquisitionCommand,
    status: str,
    bundle: LocalImageVisualReferenceBundle | None,
    output_files: tuple[VisualReferenceAcquisitionOutputFile, ...],
    error_code: str | None,
    started_at: datetime,
    completed_at: datetime,
    duration_ms: int,
) -> LocalImageVisualReferenceAcquisitionResult:
    body = {
        "schema_version": "local-image-visual-reference-acquisition-result/1.0",
        "command_id": command.command_id,
        "attempt_id": command.attempt_id,
        "command_sha256": command.command_sha256,
        "status": status,
        "bundle": None if bundle is None else bundle.model_dump(mode="json"),
        "output_files": [value.model_dump(mode="json") for value in output_files],
        "error_code": error_code,
        "started_at": started_at.isoformat().replace("+00:00", "Z"),
        "completed_at": completed_at.isoformat().replace("+00:00", "Z"),
        "duration_ms": duration_ms,
    }
    try:
        result = LocalImageVisualReferenceAcquisitionResult.model_validate(
            {**body, "result_sha256": content_sha256(body)}
        )
        validate_contract("visual-reference-acquisition-result", result.model_dump(mode="json"))
        return result
    except Exception as exc:
        raise VisualReferenceAcquisitionError("VISUAL_REFERENCE_OUTPUT_INVALID") from exc


def _publish_output(workspace: Path, members: dict[str, bytes]) -> None:
    staging = Path(tempfile.mkdtemp(prefix=".reference-output-", dir=workspace))
    staging.chmod(0o750)
    try:
        for name, payload in members.items():
            target = staging / name
            target.parent.mkdir(mode=0o750, parents=True, exist_ok=True)
            target.parent.chmod(0o750)
            _write_exclusive(target, payload)
        os.rename(staging, workspace / "output")
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise


def _write_exclusive(path: Path, payload: bytes) -> None:
    descriptor = os.open(
        path,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0),
        0o640,
    )
    try:
        view = memoryview(payload)
        while view:
            written = os.write(descriptor, view)
            if written <= 0:
                raise OSError("short visual-reference write")
            view = view[written:]
        os.fsync(descriptor)
        os.fchmod(descriptor, 0o640)
    finally:
        os.close(descriptor)


def _load_canonical_json(path: Path, *, maximum_bytes: int) -> tuple[dict[str, object], bytes]:
    descriptor = -1
    try:
        metadata = path.lstat()
        if (
            path.is_symlink()
            or not stat.S_ISREG(metadata.st_mode)
            or metadata.st_nlink != 1
            or not 1 <= metadata.st_size <= maximum_bytes
            or stat.S_IMODE(metadata.st_mode) != 0o440
            or metadata.st_gid != os.getegid()
        ):
            raise VisualReferenceAcquisitionError("VISUAL_REFERENCE_INPUT_INVALID")
        descriptor = os.open(
            path,
            os.O_RDONLY | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0),
        )
        opened = os.fstat(descriptor)
        if (
            not stat.S_ISREG(opened.st_mode)
            or opened.st_nlink != 1
            or (opened.st_dev, opened.st_ino) != (metadata.st_dev, metadata.st_ino)
            or opened.st_size != metadata.st_size
        ):
            raise VisualReferenceAcquisitionError("VISUAL_REFERENCE_INPUT_INVALID")
        raw = bytearray()
        while len(raw) <= maximum_bytes:
            chunk = os.read(descriptor, min(64 * 1024, maximum_bytes + 1 - len(raw)))
            if not chunk:
                break
            raw.extend(chunk)
        closed = os.fstat(descriptor)
        if len(raw) != opened.st_size or (closed.st_dev, closed.st_ino, closed.st_size) != (
            opened.st_dev,
            opened.st_ino,
            opened.st_size,
        ):
            raise VisualReferenceAcquisitionError("VISUAL_REFERENCE_INPUT_INVALID")
        raw_bytes = bytes(raw)
        value = json.loads(raw_bytes, object_pairs_hook=_unique_object)
    except VisualReferenceAcquisitionError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise VisualReferenceAcquisitionError("VISUAL_REFERENCE_INPUT_INVALID") from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    if not isinstance(value, dict) or content_json_bytes(value) != raw_bytes:
        raise VisualReferenceAcquisitionError("VISUAL_REFERENCE_INPUT_INVALID")
    return value, raw_bytes


def _require_workspace(path: Path) -> None:
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise VisualReferenceAcquisitionError("VISUAL_REFERENCE_INPUT_INVALID") from exc
    if (
        not path.is_absolute()
        or path.is_symlink()
        or not stat.S_ISDIR(metadata.st_mode)
        or stat.S_IMODE(metadata.st_mode) != 0o1730
        or metadata.st_gid != os.getegid()
        or metadata.st_gid not in os.getgroups()
    ):
        raise VisualReferenceAcquisitionError("VISUAL_REFERENCE_INPUT_INVALID")


def _require_https_url(
    value: str,
    *,
    hosts: frozenset[str],
    allow_query: bool = False,
) -> str:
    parsed = urlsplit(value)
    if (
        parsed.scheme != "https"
        or parsed.hostname not in hosts
        or parsed.username is not None
        or parsed.password is not None
        or parsed.port is not None
        or not parsed.path.startswith("/")
        or parsed.fragment
        or (parsed.query and not allow_query)
    ):
        raise VisualReferenceAcquisitionError("VISUAL_REFERENCE_SOURCE_REJECTED")
    return value


def _require_public_addresses(
    host: str,
    resolver: Callable[..., list[tuple[Any, ...]]],
) -> None:
    try:
        addresses = resolver(host, 443, type=socket.SOCK_STREAM)
    except OSError as exc:
        raise VisualReferenceAcquisitionError("VISUAL_REFERENCE_SOURCE_UNAVAILABLE") from exc
    if not addresses:
        raise VisualReferenceAcquisitionError("VISUAL_REFERENCE_SOURCE_UNAVAILABLE")
    for entry in addresses:
        address = ipaddress.ip_address(entry[4][0])
        if not address.is_global:
            raise VisualReferenceAcquisitionError("VISUAL_REFERENCE_SOURCE_REJECTED")


def _unique_object(pairs: Iterable[tuple[str, object]]) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, item in pairs:
        if key in value:
            raise VisualReferenceAcquisitionError("VISUAL_REFERENCE_SOURCE_REJECTED")
        value[key] = item
    return value


def _discovery_page_order(value: object) -> tuple[int, int]:
    if not isinstance(value, dict):
        raise VisualReferenceAcquisitionError("VISUAL_REFERENCE_SOURCE_REJECTED")
    index = value.get("index")
    page_id = value.get("pageid")
    if not isinstance(index, int) or not isinstance(page_id, int):
        raise VisualReferenceAcquisitionError("VISUAL_REFERENCE_SOURCE_REJECTED")
    return index, page_id


def _reference_candidate_order(
    candidate: VisualReferenceIntentCandidate,
    *,
    query: str,
    official_rank: int,
) -> tuple[int, int, int, int]:
    """Prefer one clean morphology subject while preserving stable official relevance order."""

    title = " " + re.sub(r"[^a-z0-9]+", " ", candidate.file_title.casefold()).strip() + " "
    montage_penalty = int(
        any(f" {marker.strip()} " in title for marker in _MULTI_SUBJECT_TITLE_MARKERS)
    )
    query_value = query.casefold()
    requested_viewpoints = {marker for marker in _VIEWPOINT_TITLE_MARKERS if marker in query_value}
    viewpoint_matches = sum(marker in title for marker in requested_viewpoints)
    return montage_penalty, -viewpoint_matches, official_rank, candidate.page_id


def _subject_requests_one(subject: str) -> bool:
    normalized = " ".join(subject.casefold().split())
    return normalized.startswith(("one ", "a ", "an ", "1 "))


def _title_has_marker(title: str, markers: tuple[str, ...]) -> bool:
    normalized = " " + re.sub(r"[^a-z0-9]+", " ", title.casefold()).strip() + " "
    return any(f" {marker.strip()} " in normalized for marker in markers)


def _reference_discovery_queries(query: str) -> tuple[str, ...]:
    """Use one exact query and at most one deterministic subject-only fallback."""

    simplified = " ".join(_REFERENCE_QUERY_MODIFIERS.sub(" ", query).split())
    if simplified == query or len(simplified) < 3:
        return (query,)
    return query, simplified


def _mapping(value: object, key: str) -> dict[str, object]:
    if not isinstance(value, dict) or not isinstance(value.get(key), dict):
        raise VisualReferenceAcquisitionError("VISUAL_REFERENCE_SOURCE_REJECTED")
    return cast(dict[str, object], value[key])
