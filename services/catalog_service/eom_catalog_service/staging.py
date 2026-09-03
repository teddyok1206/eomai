"""Managed Catalog staging roots and operation-local materialization."""

from __future__ import annotations

import os
import re
import stat
from contextlib import suppress
from pathlib import Path
from typing import Any

from eom_identifiers import canonical_json_bytes, sha256_bytes, sha256_file

from eom_catalog_service.errors import CatalogError, CatalogErrorCode
from eom_catalog_service.settings import CatalogSettings, CatalogStagingArea

_REGISTRATION_KEY = re.compile(r"[A-Za-z0-9][A-Za-z0-9:_-]{0,199}\Z")
_SHA256_HEX = re.compile(r"[0-9a-f]{64}\Z")


def require_catalog_runtime_directory(path: Path, message: str) -> Path:
    """Require an exact process-owned Catalog directory without normalizing it."""
    try:
        metadata = path.lstat()
        resolved = path.resolve(strict=True)
    except OSError as exc:
        raise OSError(message) from exc
    valid = (
        not path.is_symlink()
        and stat.S_ISDIR(metadata.st_mode)
        and resolved == path.absolute()
        and metadata.st_uid == os.geteuid()
        and metadata.st_gid == os.getegid()
        and stat.S_IMODE(metadata.st_mode) == 0o750
        and os.access(path, os.W_OK | os.X_OK)
    )
    if not valid:
        raise OSError(message)
    return resolved


def create_catalog_operation_directory(
    parent: Path,
    name: str,
    *,
    message: str,
    allow_existing: bool = True,
) -> Path:
    """Create one safe operation child beneath an already managed root."""
    if not name or Path(name).name != name or name in {".", ".."}:
        raise OSError(message)
    resolved_parent = require_catalog_runtime_directory(parent, message)
    path = parent / name
    if path.parent.resolve(strict=True) != resolved_parent:
        raise OSError(message)
    try:
        path.mkdir(mode=0o750, parents=False)
        path.chmod(0o750)
    except FileExistsError:
        if not allow_existing:
            raise OSError(message) from None
    return require_catalog_runtime_directory(path, message)


def require_fixed_catalog_staging_root(
    settings: CatalogSettings,
    area: CatalogStagingArea,
) -> Path:
    """Validate both the configured Catalog root and one declared fixed child."""
    try:
        staging_root = require_catalog_runtime_directory(
            settings.staging_root,
            "Catalog staging root is not prepared",
        )
        fixed_root = require_catalog_runtime_directory(
            settings.fixed_staging_root(area),
            f"Catalog {area.value} staging root is not prepared",
        )
        if fixed_root.parent != staging_root:
            raise OSError("Catalog fixed staging root escapes its configured parent")
        return fixed_root
    except OSError as exc:
        code = {
            CatalogStagingArea.CONTENT_PACKS: (
                CatalogErrorCode.CATALOG_CONTENT_PACK_STAGING_INVALID
            ),
            CatalogStagingArea.REGISTRY: CatalogErrorCode.CATALOG_REGISTRY_STAGING_INVALID,
            CatalogStagingArea.WORKFLOW_PROMPTS: "CATALOG_PROMPT_STAGING_INVALID",
        }[area]
        raise CatalogError(code, f"Catalog {area.value} staging is unavailable") from exc


def stage_registry_manifest(
    settings: CatalogSettings,
    registration_key: str,
    manifest: dict[str, Any],
) -> Path:
    """Exclusively materialize a registration manifest below the managed registry root."""
    if _REGISTRATION_KEY.fullmatch(registration_key) is None:
        raise CatalogError(
            CatalogErrorCode.CATALOG_REGISTRY_STAGING_INVALID,
            "registration staging identity is invalid",
        )
    try:
        manifest_bytes = canonical_json_bytes(manifest)
    except (TypeError, ValueError) as exc:
        raise CatalogError(
            CatalogErrorCode.CATALOG_REGISTRY_STAGING_INVALID,
            "registration manifest cannot be staged canonically",
        ) from exc
    root = require_fixed_catalog_staging_root(settings, CatalogStagingArea.REGISTRY)
    operation: Path | None = None
    manifest_path: Path | None = None
    try:
        operation = create_catalog_operation_directory(
            root,
            registration_key,
            message="registration staging directory is unsafe",
            allow_existing=False,
        )
        manifest_path = operation / "item-revision-manifest.json"
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(manifest_path, flags, 0o640)
        with os.fdopen(descriptor, "wb") as output:
            os.fchmod(output.fileno(), 0o640)
            output.write(manifest_bytes)
        metadata = manifest_path.lstat()
        if manifest_path.is_symlink() or not stat.S_ISREG(metadata.st_mode):
            raise OSError("registration manifest is not a regular file")
        return manifest_path
    except (CatalogError, OSError) as exc:
        if manifest_path is not None:
            with suppress(OSError):
                manifest_path.unlink()
        if operation is not None:
            with suppress(OSError):
                operation.rmdir()
        if isinstance(exc, CatalogError):
            raise
        raise CatalogError(
            CatalogErrorCode.CATALOG_REGISTRY_STAGING_INVALID,
            "registration manifest staging failed",
        ) from exc


def stage_registry_item_content(
    settings: CatalogSettings,
    content: dict[str, Any],
) -> tuple[Path, str]:
    """Idempotently materialize canonical item JSON in one hash-keyed registry operation."""

    try:
        content_bytes = canonical_json_bytes(content)
    except (TypeError, ValueError) as exc:
        raise CatalogError(
            CatalogErrorCode.CATALOG_REGISTRY_STAGING_INVALID,
            "item content cannot be staged canonically",
        ) from exc
    content_hash = sha256_bytes(content_bytes)
    digest = content_hash.removeprefix("sha256:")
    if _SHA256_HEX.fullmatch(digest) is None:
        raise CatalogError(
            CatalogErrorCode.CATALOG_REGISTRY_STAGING_INVALID,
            "item content staging identity is invalid",
        )
    root = require_fixed_catalog_staging_root(settings, CatalogStagingArea.REGISTRY)
    operation = create_catalog_operation_directory(
        root,
        f"item-content-{digest}",
        message="item content staging directory is unsafe",
        allow_existing=True,
    )
    content_path = operation / "assessment-item-content.json"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(content_path, flags, 0o640)
    except FileExistsError:
        descriptor = None
    except OSError as exc:
        raise CatalogError(
            CatalogErrorCode.CATALOG_REGISTRY_STAGING_INVALID,
            "item content staging failed",
        ) from exc
    if descriptor is not None:
        try:
            with os.fdopen(descriptor, "wb") as output:
                os.fchmod(output.fileno(), 0o640)
                output.write(content_bytes)
        except OSError as exc:
            with suppress(OSError):
                content_path.unlink()
            raise CatalogError(
                CatalogErrorCode.CATALOG_REGISTRY_STAGING_INVALID,
                "item content staging failed",
            ) from exc
    try:
        metadata = content_path.lstat()
        if (
            content_path.is_symlink()
            or not stat.S_ISREG(metadata.st_mode)
            or metadata.st_uid != os.geteuid()
            or metadata.st_gid != os.getegid()
            or stat.S_IMODE(metadata.st_mode) != 0o640
            or metadata.st_size != len(content_bytes)
            or sha256_file(content_path) != content_hash
            or content_path.read_bytes() != content_bytes
        ):
            raise OSError("staged item content is stale or unsafe")
    except OSError as exc:
        raise CatalogError(
            CatalogErrorCode.CATALOG_REGISTRY_STAGING_INVALID,
            "item content staging verification failed",
        ) from exc
    return content_path, content_hash


def stage_content_team_item_materialization(
    settings: CatalogSettings,
    content: dict[str, Any],
    markdown: bytes,
) -> tuple[Path, str, Path, str]:
    """Stage canonical V2 JSON and its deterministic editor Markdown side by side."""

    if not markdown or len(markdown) > 1024 * 1024:
        raise CatalogError(
            CatalogErrorCode.CATALOG_REGISTRY_STAGING_INVALID,
            "content-team Markdown size is outside the bounded profile",
        )
    content_path, content_hash = stage_registry_item_content(settings, content)
    markdown_hash = sha256_bytes(markdown)
    markdown_path = content_path.parent / "content-team-item.md"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(markdown_path, flags, 0o640)
    except FileExistsError:
        descriptor = None
    except OSError as exc:
        raise CatalogError(
            CatalogErrorCode.CATALOG_REGISTRY_STAGING_INVALID,
            "content-team Markdown staging failed",
        ) from exc
    if descriptor is not None:
        try:
            with os.fdopen(descriptor, "wb") as output:
                os.fchmod(output.fileno(), 0o640)
                output.write(markdown)
        except OSError as exc:
            with suppress(OSError):
                markdown_path.unlink()
            raise CatalogError(
                CatalogErrorCode.CATALOG_REGISTRY_STAGING_INVALID,
                "content-team Markdown staging failed",
            ) from exc
    try:
        metadata = markdown_path.lstat()
        if (
            markdown_path.is_symlink()
            or not stat.S_ISREG(metadata.st_mode)
            or metadata.st_uid != os.geteuid()
            or metadata.st_gid != os.getegid()
            or stat.S_IMODE(metadata.st_mode) != 0o640
            or metadata.st_size != len(markdown)
            or sha256_file(markdown_path) != markdown_hash
            or markdown_path.read_bytes() != markdown
        ):
            raise OSError("staged content-team Markdown is stale or unsafe")
    except OSError as exc:
        raise CatalogError(
            CatalogErrorCode.CATALOG_REGISTRY_STAGING_INVALID,
            "content-team Markdown staging verification failed",
        ) from exc
    return content_path, content_hash, markdown_path, markdown_hash
