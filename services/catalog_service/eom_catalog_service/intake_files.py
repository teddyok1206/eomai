"""Bounded filesystem adapter for untrusted intake inputs."""

from __future__ import annotations

import json
import mimetypes
import re
import stat
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

import yaml
from eom_content_intake import IntakeError, IntakeErrorCode
from eom_identifiers import content_sha256, sha256_file

MAX_FILES = 500
MAX_FILE_BYTES = 100 * 1024 * 1024
MAX_BATCH_BYTES = 2 * 1024 * 1024 * 1024
MAX_SCAN_BYTES = 2 * 1024 * 1024

SECRET_PATTERNS = (
    re.compile(rb"-----BEGIN (?:OPENSSH|RSA|EC|DSA) PRIVATE KEY-----"),
    re.compile(rb"hooks\.slack\.com/services/[A-Za-z0-9/]+"),
    re.compile(rb"\bxox[bap]-[A-Za-z0-9-]{10,}"),
    re.compile(rb"\b(?:OPENAI_API_KEY|AWS_SECRET_ACCESS_KEY|DATABASE_URL)\s*="),
    re.compile(rb"postgres(?:ql)?(?:\+\w+)?://[^\s]+:[^\s]+@"),
    re.compile(rb"\bpassword\s*[:=]\s*[^\s]{8,}", re.IGNORECASE),
    re.compile(rb'"(?:access_token|refresh_token|private_key)"\s*:'),
)

REQUIRED_ANALYSIS_HEADINGS = (
    "# 분석 개요",
    "# 원본 파일 목록",
    "# 추출한 규칙 후보",
    "# 용어 및 개념 후보",
    "# Content Pack 반영 제안",
    "# 중복 및 충돌",
    "# 불명확한 항목",
    "# 반영하지 않을 항목",
    "# 사용자 결정 필요 사항",
    "# 신뢰도 및 한계",
)


@dataclass(frozen=True)
class DiscoveredSource:
    source: Path
    normalized_relative_path: str
    original_filename: str
    normalized_filename: str
    media_type: str
    size_bytes: int
    sha256: str


class UniqueKeyLoader(yaml.SafeLoader):
    pass


def _unique_mapping(
    loader: UniqueKeyLoader, node: yaml.nodes.MappingNode, deep: bool = False
) -> dict[Any, Any]:
    result: dict[Any, Any] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in result:
            raise IntakeError(
                IntakeErrorCode.CONTENT_INTAKE_ANALYSIS_INVALID,
                "YAML contains a duplicate key",
            )
        result[key] = loader.construct_object(value_node, deep=deep)
    return result


UniqueKeyLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _unique_mapping)


def safe_relative_path(value: str) -> str:
    if "\x00" in value or "\\" in value:
        raise IntakeError(IntakeErrorCode.CONTENT_INTAKE_UNSAFE_PATH, "unsafe intake path")
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or not path.parts:
        raise IntakeError(IntakeErrorCode.CONTENT_INTAKE_UNSAFE_PATH, "unsafe intake path")
    if any(any(ord(character) < 32 for character in part) for part in path.parts):
        raise IntakeError(IntakeErrorCode.CONTENT_INTAKE_UNSAFE_PATH, "unsafe intake filename")
    return path.as_posix()


def discover_source_files(source_directory: Path) -> tuple[DiscoveredSource, ...]:
    try:
        root_stat = source_directory.lstat()
        root = source_directory.resolve(strict=True)
    except OSError as exc:
        raise IntakeError(
            IntakeErrorCode.CONTENT_INTAKE_FILE_MISSING, "source directory is unavailable"
        ) from exc
    if source_directory.is_symlink() or not stat.S_ISDIR(root_stat.st_mode):
        raise IntakeError(IntakeErrorCode.CONTENT_INTAKE_UNSAFE_PATH, "source must be a directory")

    discovered: list[DiscoveredSource] = []
    normalized_seen: set[str] = set()
    casefold_seen: set[str] = set()
    total_bytes = 0
    for candidate in sorted(root.rglob("*"), key=lambda path: path.as_posix()):
        relative = candidate.relative_to(root).as_posix()
        normalized = unicodedata.normalize("NFC", safe_relative_path(relative))
        casefold_key = normalized.casefold()
        if normalized in normalized_seen or casefold_key in casefold_seen:
            raise IntakeError(
                IntakeErrorCode.CONTENT_INTAKE_UNSAFE_PATH,
                "intake paths collide after normalization",
            )
        normalized_seen.add(normalized)
        casefold_seen.add(casefold_key)

        item_stat = candidate.lstat()
        if stat.S_ISDIR(item_stat.st_mode):
            if candidate.is_symlink():
                raise IntakeError(
                    IntakeErrorCode.CONTENT_INTAKE_UNSAFE_PATH,
                    "intake directory contains a symlink",
                )
            continue
        if candidate.is_symlink() or not stat.S_ISREG(item_stat.st_mode) or item_stat.st_nlink != 1:
            raise IntakeError(
                IntakeErrorCode.CONTENT_INTAKE_UNSAFE_PATH,
                "intake source must contain only regular non-linked files",
            )
        if item_stat.st_size > MAX_FILE_BYTES:
            raise IntakeError(IntakeErrorCode.CONTENT_INTAKE_INVALID, "intake file is too large")
        total_bytes += item_stat.st_size
        if total_bytes > MAX_BATCH_BYTES:
            raise IntakeError(IntakeErrorCode.CONTENT_INTAKE_INVALID, "intake batch is too large")
        if len(discovered) >= MAX_FILES:
            raise IntakeError(IntakeErrorCode.CONTENT_INTAKE_INVALID, "intake has too many files")
        if _contains_secret(candidate):
            raise IntakeError(
                IntakeErrorCode.CONTENT_INTAKE_SECRET_DETECTED,
                "source contains a suspected secret and cannot be accepted",
            )
        media_type = mimetypes.guess_type(normalized)[0] or "application/octet-stream"
        discovered.append(
            DiscoveredSource(
                source=candidate,
                normalized_relative_path=normalized,
                original_filename=candidate.name,
                normalized_filename=unicodedata.normalize("NFC", candidate.name),
                media_type=media_type,
                size_bytes=item_stat.st_size,
                sha256=sha256_file(candidate),
            )
        )
    if not discovered:
        raise IntakeError(IntakeErrorCode.CONTENT_INTAKE_INVALID, "intake batch is empty")
    return tuple(discovered)


def source_fingerprint(files: Iterable[DiscoveredSource]) -> str:
    return content_sha256(
        [
            {
                "relative_path": file.normalized_relative_path,
                "size_bytes": file.size_bytes,
                "sha256": file.sha256,
            }
            for file in files
        ]
    )


def validate_analysis_markdown(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    if len(text.encode("utf-8")) > 1024 * 1024:
        raise IntakeError(
            IntakeErrorCode.CONTENT_INTAKE_ANALYSIS_INVALID, "analysis report is too large"
        )
    lowered = text.casefold()
    if "<script" in lowered or "<iframe" in lowered:
        raise IntakeError(
            IntakeErrorCode.CONTENT_INTAKE_ANALYSIS_INVALID,
            "analysis report contains forbidden active HTML",
        )
    positions = [text.find(heading) for heading in REQUIRED_ANALYSIS_HEADINGS]
    if any(position < 0 for position in positions) or positions != sorted(positions):
        raise IntakeError(
            IntakeErrorCode.CONTENT_INTAKE_ANALYSIS_INVALID,
            "analysis report is missing required ordered sections",
        )
    return text


def load_strict_yaml(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    if len(text.encode("utf-8")) > 2 * 1024 * 1024:
        raise IntakeError(
            IntakeErrorCode.CONTENT_INTAKE_ANALYSIS_INVALID, "mapping proposal is too large"
        )
    value = yaml.load(text, Loader=UniqueKeyLoader)
    if not isinstance(value, dict):
        raise IntakeError(
            IntakeErrorCode.CONTENT_INTAKE_ANALYSIS_INVALID,
            "mapping proposal must be an object",
        )
    _reject_unsafe_values(value)
    return value


def load_strict_json(path: Path) -> dict[str, Any]:
    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in items:
            if key in result:
                raise IntakeError(
                    IntakeErrorCode.CONTENT_INTAKE_ANALYSIS_INVALID,
                    "JSON contains a duplicate key",
                )
            result[key] = value
        return result

    value = json.loads(
        path.read_text(encoding="utf-8"),
        object_pairs_hook=pairs,
        parse_constant=lambda _value: (_ for _ in ()).throw(
            IntakeError(
                IntakeErrorCode.CONTENT_INTAKE_ANALYSIS_INVALID,
                "JSON contains a non-finite number",
            )
        ),
    )
    if not isinstance(value, dict):
        raise IntakeError(IntakeErrorCode.CONTENT_INTAKE_ANALYSIS_INVALID, "JSON must be an object")
    return value


def _contains_secret(path: Path) -> bool:
    with path.open("rb") as stream:
        sample = stream.read(MAX_SCAN_BYTES)
    return any(pattern.search(sample) for pattern in SECRET_PATTERNS)


def _reject_unsafe_values(value: Any) -> None:
    if isinstance(value, dict):
        forbidden = {"command", "shell", "sql", "python", "eval", "exec", "import"}
        for key, item in value.items():
            if str(key).casefold() in forbidden:
                raise IntakeError(
                    IntakeErrorCode.CONTENT_INTAKE_ANALYSIS_INVALID,
                    "mapping proposal contains an executable field",
                )
            _reject_unsafe_values(item)
    elif isinstance(value, list):
        for item in value:
            _reject_unsafe_values(item)
    elif isinstance(value, str):
        if value.startswith(("/", "file://", "http://", "https://")) or "../" in value:
            raise IntakeError(
                IntakeErrorCode.CONTENT_INTAKE_ANALYSIS_INVALID,
                "mapping proposal contains an unsafe external reference",
            )
