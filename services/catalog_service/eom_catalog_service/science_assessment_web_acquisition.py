"""Bounded acquisition of public science-assessment problem PDFs."""

from __future__ import annotations

import hashlib
import os
import re
import stat
import subprocess
import tempfile
import time
import unicodedata
from collections.abc import Callable, Iterable
from contextlib import suppress
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import cast
from urllib.parse import unquote, urlencode, urljoin, urlsplit, urlunsplit
from urllib.request import HTTPRedirectHandler, OpenerDirector, Request, build_opener
from urllib.robotparser import RobotFileParser

from eom_catalog_contracts import ScienceAssessmentWebCorpusPlan
from eom_identifiers import sha256_file

USER_AGENT = "EOMResearchDatasetBot/1.0 (+internal-assessment-research; rate-limited)"
MAX_HTML_BYTES = 8 * 1024 * 1024
MAX_PAGE_COUNT = 512
READ_CHUNK_BYTES = 1024 * 1024
_PDF_SIGNATURE = re.compile(rb"^%PDF-[12]\.[0-9]")
_POST_PATH = re.compile(r"^/[0-9]+$")
_EXCLUDED_LINK_TEXT = re.compile(r"(?:정답|해설|답지|등급컷|채점|듣기|보충|분석|변형)")
_PROBLEM_LINK_TEXT = re.compile(r"(?:문제|문제지)")
_ACTIVE_PDF_MARKERS = (
    b"/JavaScript",
    b"/JS",
    b"/Launch",
    b"/EmbeddedFile",
    b"/RichMedia",
)
_SUBJECT_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("INTEGRATED_SCIENCE", re.compile(r"통합\s*과학")),
    ("EARTH_SCIENCE", re.compile(r"지구\s*과학\s*[12\u2160\u2161]?")),
    ("LIFE_SCIENCE", re.compile(r"(?:생명\s*과학|생물)\s*[12\u2160\u2161]?")),
    ("CHEMISTRY", re.compile(r"화학\s*[12\u2160\u2161]?")),
    ("PHYSICS", re.compile(r"물리(?:학)?\s*[12\u2160\u2161]?")),
    (
        "GENERAL_SCIENCE",
        re.compile(r"(?:과학\s*탐구|과학\s*문제|생활과\s*과학|과학탐구실험)"),
    ),
)


class ScienceAssessmentAcquisitionError(RuntimeError):
    """Stable, content-free acquisition error."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class ScienceAssessmentPdfCandidate:
    post_url: str
    download_url: str
    link_text: str
    original_filename: str
    subject_family: str
    subject_label: str
    issuer_type: str
    administration_year: int
    grade: int
    session_label: str


@dataclass(frozen=True, slots=True)
class AcquiredScienceAssessmentPdf:
    candidate: ScienceAssessmentPdfCandidate
    resolved_url: str
    source: Path
    sha256: str
    bytes: int
    page_count: int


@dataclass(frozen=True, slots=True)
class ScienceAssessmentAcquisitionFailure:
    candidate: ScienceAssessmentPdfCandidate
    error_code: str


@dataclass(frozen=True, slots=True)
class ScienceAssessmentDiscovery:
    post_count: int
    candidates: tuple[ScienceAssessmentPdfCandidate, ...]
    rejected_link_count: int


class _PageParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: list[tuple[str, str]] = []
        self.title = ""
        self._href: str | None = None
        self._anchor_text: list[str] = []
        self._in_title = False
        self._title_text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "a":
            self._href = dict(attrs).get("href")
            self._anchor_text = []
        elif tag == "title":
            self._in_title = True
            self._title_text = []

    def handle_data(self, data: str) -> None:
        if self._href is not None:
            self._anchor_text.append(data)
        if self._in_title:
            self._title_text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._href is not None:
            text = " ".join("".join(self._anchor_text).split())
            self.links.append((self._href, unicodedata.normalize("NFC", text)))
            self._href = None
            self._anchor_text = []
        elif tag == "title" and self._in_title:
            self.title = unicodedata.normalize("NFC", " ".join("".join(self._title_text).split()))
            self._in_title = False
            self._title_text = []


class _AllowlistRedirectHandler(HTTPRedirectHandler):
    def __init__(self, allowed_hosts: frozenset[str]) -> None:
        self.allowed_hosts = allowed_hosts

    def redirect_request(
        self,
        req: Request,
        fp: object,
        code: int,
        msg: str,
        headers: object,
        newurl: str,
    ) -> Request | None:
        normalized = _https_url(urljoin(req.full_url, newurl))
        if urlsplit(normalized).hostname not in self.allowed_hosts:
            raise ScienceAssessmentAcquisitionError("SCIENCE_CORPUS_REDIRECT_HOST_REJECTED")
        return super().redirect_request(req, fp, code, msg, headers, normalized)  # type: ignore[arg-type]


class ScienceAssessmentHttpClient:
    """HTTPS-only, rate-limited HTTP adapter with redirect host validation."""

    def __init__(
        self,
        *,
        allowed_hosts: Iterable[str],
        delay_ms: int,
        opener: OpenerDirector | None = None,
        monotonic: Callable[[], float] = time.monotonic,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        self.allowed_hosts = frozenset(allowed_hosts)
        self.delay_seconds = delay_ms / 1000
        self.opener = opener or build_opener(_AllowlistRedirectHandler(self.allowed_hosts))
        self.monotonic = monotonic
        self.sleeper = sleeper
        self._next_request_at: dict[str, float] = {}

    def read_html(self, url: str) -> str:
        normalized = self._require_url(url)
        response = self._open(normalized)
        try:
            media_type = response.headers.get_content_type()
            payload = cast(bytes, response.read(MAX_HTML_BYTES + 1))
            if media_type not in {"text/html", "application/xhtml+xml", "text/plain"}:
                raise ScienceAssessmentAcquisitionError("SCIENCE_CORPUS_HTML_MEDIA_INVALID")
            if len(payload) > MAX_HTML_BYTES:
                raise ScienceAssessmentAcquisitionError("SCIENCE_CORPUS_HTML_TOO_LARGE")
            charset = cast(str | None, response.headers.get_content_charset()) or "utf-8"
            return payload.decode(charset, "replace")
        finally:
            response.close()

    def download_pdf(self, url: str, target_directory: Path, max_bytes: int) -> tuple[Path, str]:
        normalized = self._require_url(url)
        response = self._open(normalized)
        temporary_path: Path | None = None
        try:
            resolved = self._require_url(response.geturl())
            declared = response.headers.get("Content-Length")
            if declared is not None and (not declared.isdigit() or int(declared) > max_bytes):
                raise ScienceAssessmentAcquisitionError("SCIENCE_CORPUS_PDF_TOO_LARGE")
            target_directory.mkdir(mode=0o700, parents=True, exist_ok=True)
            descriptor, raw_path = tempfile.mkstemp(
                prefix=".science-pdf-", suffix=".partial", dir=target_directory
            )
            temporary_path = Path(raw_path)
            os.fchmod(descriptor, 0o600)
            digest = hashlib.sha256()
            total = 0
            prefix = b""
            try:
                while True:
                    chunk = response.read(READ_CHUNK_BYTES)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > max_bytes:
                        raise ScienceAssessmentAcquisitionError("SCIENCE_CORPUS_PDF_TOO_LARGE")
                    if len(prefix) < 8:
                        prefix += chunk[: 8 - len(prefix)]
                    digest.update(chunk)
                    view = memoryview(chunk)
                    while view:
                        written = os.write(descriptor, view)
                        if written <= 0:
                            raise OSError("short PDF write")
                        view = view[written:]
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
            if total < 1024 or _PDF_SIGNATURE.fullmatch(prefix[:8]) is None:
                raise ScienceAssessmentAcquisitionError("SCIENCE_CORPUS_PDF_SIGNATURE_INVALID")
            content_sha256 = "sha256:" + digest.hexdigest()
            final = target_directory / f"{digest.hexdigest()}.pdf"
            if final.exists():
                _require_regular_single_link(final)
                if sha256_file(final) != content_sha256:
                    raise ScienceAssessmentAcquisitionError("SCIENCE_CORPUS_LOCAL_HASH_CONFLICT")
                temporary_path.unlink()
            else:
                temporary_path.replace(final)
                final.chmod(0o600)
            temporary_path = None
            return final, resolved
        finally:
            response.close()
            if temporary_path is not None:
                with suppress(FileNotFoundError):
                    temporary_path.unlink()

    def _require_url(self, url: str) -> str:
        normalized = _https_url(url)
        if urlsplit(normalized).hostname not in self.allowed_hosts:
            raise ScienceAssessmentAcquisitionError("SCIENCE_CORPUS_URL_HOST_REJECTED")
        return normalized

    def _open(self, url: str):  # type: ignore[no-untyped-def]
        host = urlsplit(url).hostname
        assert host is not None
        now = self.monotonic()
        wait = self._next_request_at.get(host, now) - now
        if wait > 0:
            self.sleeper(wait)
        self._next_request_at[host] = self.monotonic() + self.delay_seconds
        request = Request(
            url,
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "application/pdf,text/html;q=0.9,*/*;q=0.1",
            },
        )
        return self.opener.open(request, timeout=45)


class ScienceAssessmentWebAcquirer:
    def __init__(
        self,
        plan: ScienceAssessmentWebCorpusPlan,
        *,
        http: ScienceAssessmentHttpClient | None = None,
        qpdf: Path = Path("/usr/bin/qpdf"),
        pdfinfo: Path = Path("/usr/bin/pdfinfo"),
    ) -> None:
        self.plan = plan
        self.http = http or ScienceAssessmentHttpClient(
            allowed_hosts=("legendstudy.com", *plan.allowed_download_hosts),
            delay_ms=plan.crawl_delay_ms,
        )
        self.qpdf = _require_executable(qpdf)
        self.pdfinfo = _require_executable(pdfinfo)

    def discover(self) -> ScienceAssessmentDiscovery:
        self._require_robots_permission()
        post_categories: dict[str, set[str]] = {}
        for category in self.plan.category_urls:
            category_posts: set[str] = set()
            for page in range(1, self.plan.max_post_pages + 1):
                html = self.http.read_html(_category_page_url(category, page))
                parser = _parse_page(html)
                observed = {
                    urljoin(self.plan.source_site, href)
                    for href, _text in parser.links
                    if _POST_PATH.fullmatch(urlsplit(urljoin(self.plan.source_site, href)).path)
                }
                new = observed - category_posts
                if not new:
                    break
                category_posts.update(new)
                for post in new:
                    post_categories.setdefault(post, set()).add(category)
            else:
                raise ScienceAssessmentAcquisitionError("SCIENCE_CORPUS_POST_LIMIT_REACHED")
        if len(post_categories) > self.plan.max_post_pages:
            raise ScienceAssessmentAcquisitionError("SCIENCE_CORPUS_POST_LIMIT_REACHED")

        candidates: dict[tuple[str, str], ScienceAssessmentPdfCandidate] = {}
        rejected = 0
        for post_url, categories in sorted(post_categories.items()):
            parser = _parse_page(self.http.read_html(post_url))
            for href, link_text in parser.links:
                candidate = _candidate_from_link(
                    post_url=post_url,
                    post_title=parser.title,
                    category_urls=tuple(sorted(categories)),
                    href=href,
                    link_text=link_text,
                    allowed_hosts=set(self.plan.allowed_download_hosts),
                )
                if candidate is None:
                    if ".pdf" in (href + link_text).casefold():
                        rejected += 1
                    continue
                candidates[(candidate.post_url, candidate.download_url)] = candidate
        return ScienceAssessmentDiscovery(
            post_count=len(post_categories),
            candidates=tuple(
                sorted(
                    candidates.values(),
                    key=lambda value: (value.download_url, value.post_url, value.link_text),
                )
            ),
            rejected_link_count=rejected,
        )

    def acquire(
        self,
        discovery: ScienceAssessmentDiscovery,
        workspace: Path,
    ) -> tuple[
        tuple[AcquiredScienceAssessmentPdf, ...],
        tuple[ScienceAssessmentAcquisitionFailure, ...],
    ]:
        _require_empty_private_directory(workspace)
        documents = workspace / "documents"
        documents.mkdir(mode=0o700)
        acquired: list[AcquiredScienceAssessmentPdf] = []
        failures: list[ScienceAssessmentAcquisitionFailure] = []
        by_url: dict[str, tuple[Path, str, int]] = {}
        failures_by_url: dict[str, str] = {}
        for candidate in discovery.candidates:
            try:
                prior_failure = failures_by_url.get(candidate.download_url)
                if prior_failure is not None:
                    failures.append(
                        ScienceAssessmentAcquisitionFailure(
                            candidate=candidate,
                            error_code=prior_failure,
                        )
                    )
                    continue
                cached = by_url.get(candidate.download_url)
                if cached is None:
                    source, resolved = self.http.download_pdf(
                        candidate.download_url,
                        documents,
                        self.plan.max_pdf_bytes,
                    )
                    page_count = _validate_pdf(source, qpdf=self.qpdf, pdfinfo=self.pdfinfo)
                    cached = (source, resolved, page_count)
                    by_url[candidate.download_url] = cached
                source, resolved, page_count = cached
                metadata = _require_regular_single_link(source)
                acquired.append(
                    AcquiredScienceAssessmentPdf(
                        candidate=candidate,
                        resolved_url=resolved,
                        source=source,
                        sha256=sha256_file(source),
                        bytes=metadata.st_size,
                        page_count=page_count,
                    )
                )
            except (OSError, ScienceAssessmentAcquisitionError, subprocess.SubprocessError) as exc:
                code = getattr(exc, "code", "SCIENCE_CORPUS_PDF_ACQUISITION_FAILED")
                error_code = str(code)
                failures_by_url[candidate.download_url] = error_code
                failures.append(
                    ScienceAssessmentAcquisitionFailure(
                        candidate=candidate,
                        error_code=error_code,
                    )
                )
        return tuple(acquired), tuple(failures)

    def _require_robots_permission(self) -> None:
        robots_url = self.plan.source_site + "/robots.txt"
        parser = RobotFileParser()
        parser.set_url(robots_url)
        parser.parse(self.http.read_html(robots_url).splitlines())
        if any(not parser.can_fetch(USER_AGENT, value) for value in self.plan.category_urls):
            raise ScienceAssessmentAcquisitionError("SCIENCE_CORPUS_ROBOTS_REJECTED")


def _candidate_from_link(
    *,
    post_url: str,
    post_title: str,
    category_urls: tuple[str, ...],
    href: str,
    link_text: str,
    allowed_hosts: set[str],
) -> ScienceAssessmentPdfCandidate | None:
    combined = unicodedata.normalize("NFC", f"{link_text} {href}")
    if ".pdf" not in combined.casefold():
        return None
    if _EXCLUDED_LINK_TEXT.search(combined) or not _PROBLEM_LINK_TEXT.search(combined):
        return None
    subject = _subject(combined)
    if subject is None:
        return None
    absolute = _https_url(urljoin(post_url, href))
    if urlsplit(absolute).hostname not in allowed_hosts:
        return None
    context = unicodedata.normalize(
        "NFC", unquote(" ".join((post_title, *category_urls, link_text)))
    )
    issuer = "KICE" if re.search(r"(?:평가원|모의평가|수능)", context) else "EDUCATION_AUTHORITY"
    grade = 3 if issuer == "KICE" else _grade(context)
    year = _administration_year(context, issuer)
    session = _session_label(context, issuer)
    if grade is None or year is None or session is None:
        return None
    filename = _original_filename(link_text, absolute)
    canonical_link_text = link_text.strip() or filename
    return ScienceAssessmentPdfCandidate(
        post_url=_https_url(post_url),
        download_url=absolute,
        link_text=canonical_link_text[:512],
        original_filename=filename,
        subject_family=subject[0],
        subject_label=subject[1],
        issuer_type=issuer,
        administration_year=year,
        grade=grade,
        session_label=session,
    )


def _subject(value: str) -> tuple[str, str] | None:
    for family, pattern in _SUBJECT_PATTERNS:
        match = pattern.search(value)
        if match is not None:
            return family, " ".join(match.group(0).split())[:128]
    return None


def _grade(value: str) -> int | None:
    match = re.search(r"(?:고등학교\s*|고\s*)([123])(?:\s*학년)?", value)
    return int(match.group(1)) if match is not None else None


def _administration_year(value: str, issuer: str) -> int | None:
    시행 = re.search(r"((?:19|20)\d{2})\s*년[^\n]{0,40}?시행", value)
    if 시행 is not None:
        return int(시행.group(1))
    calendar = re.search(r"((?:19|20)\d{2})\s*년\s*(?:[0-9]{1,2}\s*월|수능)", value)
    if calendar is not None:
        return int(calendar.group(1))
    academic = re.search(r"((?:19|20)\d{2})\s*학년도", value)
    if academic is not None:
        year = int(academic.group(1))
        return year - 1 if issuer == "KICE" else year
    return None


def _session_label(value: str, issuer: str) -> str | None:
    month = re.search(r"(?<!\d)(1[0-2]|[1-9])\s*월", value)
    if month is not None:
        kind = "모의평가" if issuer == "KICE" else "학력평가"
        return f"{int(month.group(1))}월 {kind}"
    if issuer == "KICE" and "수능" in value:
        return "대학수학능력시험"
    return None


def _original_filename(link_text: str, url: str) -> str:
    text_match = re.search(r"([^/\\]{1,255}?\.pdf)", link_text, flags=re.IGNORECASE)
    value = text_match.group(1) if text_match is not None else Path(urlsplit(url).path).name
    value = unicodedata.normalize("NFC", unquote(value)).strip()
    value = "".join(
        "_" if character in "/\\" or ord(character) < 32 or ord(character) == 127 else character
        for character in value
    )
    if not value.casefold().endswith(".pdf"):
        value = "science-assessment.pdf"
    if len(value) > 255:
        value = value[:251] + ".pdf"
    return value


def _category_page_url(category: str, page: int) -> str:
    separator = "&" if "?" in category else "?"
    return category + separator + urlencode({"page": page})


def _parse_page(value: str) -> _PageParser:
    parser = _PageParser()
    parser.feed(value)
    parser.close()
    return parser


def _https_url(value: str) -> str:
    parts = urlsplit(value)
    if parts.scheme not in {"http", "https"} or not parts.hostname:
        raise ScienceAssessmentAcquisitionError("SCIENCE_CORPUS_URL_INVALID")
    if parts.username is not None or parts.password is not None or parts.fragment:
        raise ScienceAssessmentAcquisitionError("SCIENCE_CORPUS_URL_INVALID")
    port = f":{parts.port}" if parts.port is not None else ""
    return urlunsplit(("https", parts.hostname.casefold() + port, parts.path, parts.query, ""))


def _require_executable(path: Path) -> Path:
    metadata = path.stat()
    if path.is_symlink() or not stat.S_ISREG(metadata.st_mode) or not os.access(path, os.X_OK):
        raise ScienceAssessmentAcquisitionError("SCIENCE_CORPUS_VALIDATOR_INVALID")
    return path


def _require_empty_private_directory(path: Path) -> None:
    metadata = path.stat()
    if (
        path.is_symlink()
        or not stat.S_ISDIR(metadata.st_mode)
        or stat.S_IMODE(metadata.st_mode) != 0o700
        or any(path.iterdir())
    ):
        raise ScienceAssessmentAcquisitionError("SCIENCE_CORPUS_WORKSPACE_INVALID")


def _require_regular_single_link(path: Path) -> os.stat_result:
    metadata = path.lstat()
    if path.is_symlink() or not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
        raise ScienceAssessmentAcquisitionError("SCIENCE_CORPUS_LOCAL_FILE_INVALID")
    return metadata


def _validate_pdf(path: Path, *, qpdf: Path, pdfinfo: Path) -> int:
    _require_regular_single_link(path)
    checked = subprocess.run(
        (str(qpdf), "--warning-exit-0", "--check", str(path)),
        stdin=subprocess.DEVNULL,
        capture_output=True,
        timeout=60,
        check=False,
        env={"LANG": "C.UTF-8", "PATH": "/usr/bin:/bin"},
    )
    if checked.returncode != 0:
        raise ScienceAssessmentAcquisitionError("SCIENCE_CORPUS_PDF_STRUCTURE_INVALID")
    inspected = subprocess.run(
        (str(pdfinfo), str(path)),
        stdin=subprocess.DEVNULL,
        capture_output=True,
        timeout=30,
        check=False,
        env={"LANG": "C.UTF-8", "PATH": "/usr/bin:/bin"},
    )
    if inspected.returncode != 0:
        raise ScienceAssessmentAcquisitionError("SCIENCE_CORPUS_PDF_INFO_INVALID")
    details = inspected.stdout.decode("utf-8", "replace")
    pages = re.search(r"^Pages:\s+([0-9]+)\s*$", details, flags=re.MULTILINE)
    encrypted = re.search(r"^Encrypted:\s+(\S+)", details, flags=re.MULTILINE)
    if pages is None or encrypted is None or encrypted.group(1).casefold() != "no":
        raise ScienceAssessmentAcquisitionError("SCIENCE_CORPUS_PDF_INFO_INVALID")
    page_count = int(pages.group(1))
    if not 1 <= page_count <= MAX_PAGE_COUNT:
        raise ScienceAssessmentAcquisitionError("SCIENCE_CORPUS_PDF_PAGE_COUNT_INVALID")
    overlap = b""
    longest_marker = max(map(len, _ACTIVE_PDF_MARKERS))
    with path.open("rb") as stream:
        while chunk := stream.read(READ_CHUNK_BYTES):
            sample = overlap + chunk
            if any(marker in sample for marker in _ACTIVE_PDF_MARKERS):
                raise ScienceAssessmentAcquisitionError("SCIENCE_CORPUS_PDF_ACTIVE_CONTENT")
            overlap = sample[-(longest_marker - 1) :]
    return page_count
