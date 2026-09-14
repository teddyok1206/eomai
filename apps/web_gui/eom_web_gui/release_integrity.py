"""Installed Web GUI distribution integrity verification without source-tree access."""

from __future__ import annotations

import base64
import csv
import hashlib
import importlib.metadata
import json
import stat
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path

REQUIRED_RUNTIME_FILES = frozenset(
    {
        "__init__.py",
        "__main__.py",
        "app.py",
        "build-info.json",
        "cli.py",
        "contracts.py",
        "draft_integrity.py",
        "gateways.py",
        "item_preview_projection.py",
        "knowledge_quality.py",
        "redaction.py",
        "release_integrity.py",
        "request_drafts.py",
        "resources.py",
        "services.py",
        "sessions.py",
        "settings.py",
        "static/app.js",
        "static/curriculum-selector.js",
        "static/eom-mark.svg",
        "static/execution-preset-editor.js",
        "static/index.html",
        "static/item-preview.js",
        "static/login.html",
        "static/login.js",
        "static/presentation-vocabulary.ko-KR.json",
        "static/styles.css",
        "timeline.py",
    }
)


class ReleaseIntegrityError(RuntimeError):
    pass


@dataclass(frozen=True)
class VerifiedWebRelease:
    source_commit: str
    package_version: str
    verified_file_count: int


def _record_entries(record_text: str) -> dict[str, tuple[str, int]]:
    entries: dict[str, tuple[str, int]] = {}
    seen: set[str] = set()
    for path, encoded_hash, encoded_size in csv.reader(record_text.splitlines()):
        if path in seen:
            raise ReleaseIntegrityError("Web GUI RECORD contains a duplicate path")
        seen.add(path)
        if not encoded_hash or not encoded_size:
            continue
        if (
            not encoded_hash.startswith("sha256=")
            or not encoded_size.isascii()
            or not encoded_size.isdigit()
        ):
            raise ReleaseIntegrityError("Web GUI RECORD entry is not a bounded SHA-256 descriptor")
        entries[path] = (encoded_hash.removeprefix("sha256="), int(encoded_size))
    return entries


def verify_recorded_package_files(
    *,
    distribution_root: Path,
    package_root: Path,
    record_text: str,
) -> int:
    """Verify every installed source/static file and reject unrecorded stale files."""

    distribution_root = distribution_root.resolve(strict=True)
    package_root = package_root.resolve(strict=True)
    try:
        package_relative = package_root.relative_to(distribution_root).as_posix()
    except ValueError as exc:
        raise ReleaseIntegrityError("Web GUI package is outside its distribution root") from exc
    entries = _record_entries(record_text)
    observed: set[str] = set()
    for path in package_root.rglob("*"):
        relative = path.relative_to(package_root)
        if "__pycache__" in relative.parts or path.suffix == ".pyc":
            continue
        metadata = path.lstat()
        if stat.S_ISLNK(metadata.st_mode):
            raise ReleaseIntegrityError("Web GUI package contains a symlink")
        if not stat.S_ISREG(metadata.st_mode):
            continue
        relative_name = relative.as_posix()
        recorded_name = f"{package_relative}/{relative_name}"
        descriptor = entries.get(recorded_name)
        if descriptor is None:
            raise ReleaseIntegrityError("Web GUI package contains an unrecorded file")
        expected_hash, expected_size = descriptor
        if metadata.st_size != expected_size:
            raise ReleaseIntegrityError("Web GUI installed file size differs from RECORD")
        encoded_hash = (
            base64.urlsafe_b64encode(hashlib.sha256(path.read_bytes()).digest())
            .decode()
            .rstrip("=")
        )
        if encoded_hash != expected_hash:
            raise ReleaseIntegrityError("Web GUI installed file hash differs from RECORD")
        observed.add(relative_name)
    if missing := REQUIRED_RUNTIME_FILES - observed:
        raise ReleaseIntegrityError(f"Web GUI runtime files are missing: {sorted(missing)}")
    if unexpected := observed - REQUIRED_RUNTIME_FILES:
        raise ReleaseIntegrityError(
            f"Web GUI runtime files contain unknown entries: {sorted(unexpected)}"
        )
    recorded_package_files = {
        name.removeprefix(f"{package_relative}/")
        for name in entries
        if name.startswith(f"{package_relative}/")
    }
    if observed != recorded_package_files:
        raise ReleaseIntegrityError("Web GUI installed package differs from its RECORD inventory")
    return len(observed)


def verify_installed_web_gui(
    *, expected_commit: str, expected_version: str = "0.1.0"
) -> VerifiedWebRelease:
    if len(expected_commit) != 40 or any(
        value not in "0123456789abcdef" for value in expected_commit
    ):
        raise ReleaseIntegrityError("expected Web GUI commit is invalid")
    distribution = importlib.metadata.distribution("eom-web-gui")
    if distribution.metadata["Name"] != "eom-web-gui" or distribution.version != expected_version:
        raise ReleaseIntegrityError("installed Web GUI distribution metadata differs")
    direct_url = distribution.read_text("direct_url.json")
    if direct_url and json.loads(direct_url).get("dir_info", {}).get("editable") is True:
        raise ReleaseIntegrityError("installed Web GUI distribution is editable")
    record_text = distribution.read_text("RECORD")
    if record_text is None:
        raise ReleaseIntegrityError("installed Web GUI RECORD is missing")
    package_root = Path(str(files("eom_web_gui"))).resolve(strict=True)
    distribution_root = Path(str(distribution.locate_file("."))).resolve(strict=True)
    build = json.loads((package_root / "build-info.json").read_text(encoding="ascii"))
    if set(build) != {"build_timestamp_utc", "package_version", "source_commit"}:
        raise ReleaseIntegrityError("installed Web GUI build metadata has unknown fields")
    if build["source_commit"] != expected_commit or build["package_version"] != expected_version:
        raise ReleaseIntegrityError("installed Web GUI build identity differs")
    verified = verify_recorded_package_files(
        distribution_root=distribution_root,
        package_root=package_root,
        record_text=record_text,
    )
    return VerifiedWebRelease(
        source_commit=expected_commit,
        package_version=expected_version,
        verified_file_count=verified,
    )
