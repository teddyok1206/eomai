"""Read-only, allowlist-first observation of untrusted legacy source trees."""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import unicodedata
from collections.abc import Iterable
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any, Literal, TypeVar

from eom_catalog_contracts import (
    LegacyExclusionReason,
    LegacyFileObservation,
    LegacyInventoryClassificationRule,
    LegacyKnowledgeContractErrorCode,
    LegacyRightsState,
    LegacyRootAlias,
    LegacySourceCanonicality,
    LegacySourceFamily,
    LegacySourceInventoryClassSummary,
    LegacySourceInventoryEntry,
    LegacySourceInventoryPolicy,
    LegacySourceInventorySummary,
    LegacySourceInventoryV2,
    LegacySourcePreliminaryClass,
    validate_contract,
)
from eom_identifiers import content_sha256
from pydantic import BaseModel, ConfigDict, Field, model_validator

SCANNER_VERSION = "1.0.0"
MAX_CONTROL_DOCUMENT_BYTES = 2 * 1024 * 1024
READ_CHUNK_BYTES = 1024 * 1024
_OPEN_READ = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
_OPEN_DIRECTORY = _OPEN_READ | getattr(os, "O_DIRECTORY", 0)

_SECRET_PREFIX_MARKERS = (
    b"-----BEGIN " + b"PRIVATE KEY-----",
    b"-----BEGIN " + b"RSA PRIVATE KEY-----",
    b"-----BEGIN " + b"OPENSSH PRIVATE KEY-----",
)
_SECRET_CONTENT_PATTERNS = (
    re.compile(
        rb"(?i)(?:api[_-]?key|apikey|client_secret|password|secret_key)"
        rb"[\"']?\s*[:=]\s*[\"']?[A-Za-z0-9_./+=:-]{16,}"
    ),
    re.compile(
        rb"(?i)authorization[\"']?\s*[:=]\s*[\"']?bearer\s+"
        rb"[A-Za-z0-9_.-]{20,}"
    ),
    re.compile(rb"(?i)(?:sk-|ghp_|xox[baprs]-|eom_(?:at|rt)_)[A-Za-z0-9_-]{20,}"),
)


class LegacySourceInventoryError(RuntimeError):
    """Stable, content-free failure raised by the inventory boundary."""

    def __init__(self, code: LegacyKnowledgeContractErrorCode) -> None:
        self.code = code
        super().__init__(code.value)


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, use_enum_values=True)


class LegacySourceRoot(_FrozenModel):
    root_alias: LegacyRootAlias
    configuration_identity: str = Field(pattern=r"^legacyroot_[0-9a-f]{32}$")
    absolute_path: str = Field(min_length=2, max_length=4096)

    @model_validator(mode="after")
    def safe_absolute_path(self) -> LegacySourceRoot:
        value = self.absolute_path
        path = Path(value)
        if (
            not path.is_absolute()
            or value != str(path)
            or value != unicodedata.normalize("NFC", value)
            or any(part in {"", ".", ".."} for part in path.parts[1:])
            or any(ord(character) < 32 or ord(character) == 127 for character in value)
        ):
            raise ValueError("legacy root path must be normalized and absolute")
        return self


class LegacySourceRootConfiguration(_FrozenModel):
    schema_version: Literal["legacy-source-root-configuration/1.0"]
    configuration_revision_id: str = Field(pattern=r"^legacyrootconfigrev_[0-9a-f]{32}$")
    roots: tuple[LegacySourceRoot, ...] = Field(min_length=1, max_length=2)

    @model_validator(mode="after")
    def unique_roots(self) -> LegacySourceRootConfiguration:
        aliases = tuple(root.root_alias for root in self.roots)
        if len(aliases) != len(set(aliases)) or aliases != tuple(sorted(aliases)):
            raise ValueError("legacy root aliases must be unique and sorted")
        return self

    def resolve(self, alias: LegacyRootAlias) -> LegacySourceRoot:
        matches = tuple(root for root in self.roots if root.root_alias == alias)
        if len(matches) != 1:
            raise LegacySourceInventoryError(
                LegacyKnowledgeContractErrorCode.LEGACY_KNOWLEDGE_CONFIGURATION_INVALID
            )
        return matches[0]

    def identity_sha256(self, alias: LegacyRootAlias) -> str:
        root = self.resolve(alias)
        return content_sha256(
            {
                "schema_version": "legacy-source-root-identity/1.0",
                "configuration_revision_id": self.configuration_revision_id,
                "root_alias": root.root_alias,
                "configuration_identity": root.configuration_identity,
            }
        )


ModelT = TypeVar("ModelT", bound=BaseModel)


def load_inventory_policy(path: Path) -> LegacySourceInventoryPolicy:
    value = _load_json_document(path, protected=False)
    try:
        validate_contract("legacy-source-inventory-policy", value)
        return LegacySourceInventoryPolicy.model_validate(value)
    except ValueError as exc:
        raise LegacySourceInventoryError(
            LegacyKnowledgeContractErrorCode.LEGACY_KNOWLEDGE_POLICY_INVALID
        ) from exc


def load_root_configuration(path: Path) -> LegacySourceRootConfiguration:
    value = _load_json_document(path, protected=True)
    try:
        return LegacySourceRootConfiguration.model_validate(value)
    except ValueError as exc:
        raise LegacySourceInventoryError(
            LegacyKnowledgeContractErrorCode.LEGACY_KNOWLEDGE_CONFIGURATION_INVALID
        ) from exc


def load_inventory_manifest(path: Path) -> LegacySourceInventoryV2:
    value = _load_json_document(path, protected=True)
    try:
        validate_contract("legacy-source-inventory-v2", value)
        return LegacySourceInventoryV2.model_validate(value)
    except ValueError as exc:
        raise LegacySourceInventoryError(
            LegacyKnowledgeContractErrorCode.LEGACY_KNOWLEDGE_CONTRACT_INVALID
        ) from exc


def write_inventory_manifest(path: Path, inventory: LegacySourceInventoryV2) -> None:
    """Atomically create one operator-protected dry-run manifest."""

    if (
        not path.is_absolute()
        or path.name in {"", ".", ".."}
        or any(part in {".", ".."} for part in path.parts)
        or str(path) != unicodedata.normalize("NFC", str(path))
        or any(ord(character) < 32 or ord(character) == 127 for character in str(path))
    ):
        raise LegacySourceInventoryError(
            LegacyKnowledgeContractErrorCode.LEGACY_KNOWLEDGE_OUTPUT_INVALID
        )
    payload = (
        json.dumps(
            inventory.model_dump(mode="json"),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        + b"\n"
    )
    parent_fd = -1
    output_fd = -1
    created = False
    try:
        parent_fd = _open_absolute_directory(path.parent)
        output_fd = os.open(
            path.name,
            os.O_WRONLY
            | os.O_CREAT
            | os.O_EXCL
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NOFOLLOW", 0),
            0o600,
            dir_fd=parent_fd,
        )
        created = True
        os.fchmod(output_fd, 0o600)
        view = memoryview(payload)
        while view:
            written = os.write(output_fd, view)
            if written <= 0:
                raise OSError("short inventory manifest write")
            view = view[written:]
        os.fsync(output_fd)
        metadata = os.fstat(output_fd)
        if not stat.S_ISREG(metadata.st_mode) or stat.S_IMODE(metadata.st_mode) != 0o600:
            raise OSError("inventory manifest final metadata mismatch")
    except (OSError, ValueError) as exc:
        if created and parent_fd >= 0:
            with suppress(OSError):
                os.unlink(path.name, dir_fd=parent_fd)
        raise LegacySourceInventoryError(
            LegacyKnowledgeContractErrorCode.LEGACY_KNOWLEDGE_OUTPUT_INVALID
        ) from exc
    finally:
        if output_fd >= 0:
            os.close(output_fd)
        if parent_fd >= 0:
            os.close(parent_fd)


class LegacySourceInventoryScanner:
    """One-pass fd-relative scanner; it never opens a legacy path for writing."""

    def scan(
        self,
        *,
        policy: LegacySourceInventoryPolicy,
        roots: LegacySourceRootConfiguration,
        root_alias: LegacyRootAlias,
        observed_at: datetime | None = None,
    ) -> LegacySourceInventoryV2:
        if policy.scanner_version != SCANNER_VERSION:
            raise LegacySourceInventoryError(
                LegacyKnowledgeContractErrorCode.LEGACY_KNOWLEDGE_POLICY_INVALID
            )
        root = roots.resolve(root_alias)
        rules = tuple(rule for rule in policy.classification_rules if rule.root_alias == root_alias)
        if not rules:
            raise LegacySourceInventoryError(
                LegacyKnowledgeContractErrorCode.LEGACY_KNOWLEDGE_POLICY_INVALID
            )
        scopes = _minimal_scan_scopes(rule.relative_prefix for rule in rules)
        state = _ScanState(policy=policy, root_alias=root_alias, rules=rules)
        root_fd = -1
        try:
            root_fd = _open_absolute_directory(Path(root.absolute_path))
            root_before = os.fstat(root_fd)
            for scope in scopes:
                scope_fd = _open_relative_directory(root_fd, PurePosixPath(scope).parts)
                try:
                    self._walk_directory(
                        directory_fd=scope_fd,
                        relative_parts=PurePosixPath(scope).parts,
                        state=state,
                    )
                finally:
                    os.close(scope_fd)
            root_after = os.fstat(root_fd)
            if _directory_identity(root_before) != _directory_identity(root_after):
                raise LegacySourceInventoryError(
                    LegacyKnowledgeContractErrorCode.LEGACY_KNOWLEDGE_ROOT_CHANGED
                )
        except LegacySourceInventoryError:
            raise
        except OSError as exc:
            raise LegacySourceInventoryError(
                LegacyKnowledgeContractErrorCode.LEGACY_KNOWLEDGE_ROOT_INVALID
            ) from exc
        finally:
            if root_fd >= 0:
                os.close(root_fd)

        entries = tuple(
            sorted(
                state.entries,
                key=lambda entry: (entry.relative_path.casefold(), entry.relative_path),
            )
        )
        summary = _inventory_summary(entries)
        source_set_payload = {
            "schema_version": "legacy-source-set/1.0",
            "scanner_version": SCANNER_VERSION,
            "scanner_policy_revision_id": policy.policy_revision_id,
            "scanner_policy_sha256": policy.policy_sha256,
            "root_alias": root_alias,
            "root_configuration_sha256": roots.identity_sha256(root_alias),
            "entries": [entry.model_dump(mode="json") for entry in entries],
            "summary": summary.model_dump(mode="json"),
        }
        source_set_sha256 = content_sha256(source_set_payload)
        inventory_id = "legacyinventory_" + source_set_sha256.removeprefix("sha256:")[:32]
        identity_payload = {
            "schema_version": "legacy-source-inventory/2.0",
            "inventory_id": inventory_id,
            "scanner_version": SCANNER_VERSION,
            "scanner_policy_revision_id": policy.policy_revision_id,
            "scanner_policy_sha256": policy.policy_sha256,
            "root_alias": root_alias,
            "root_configuration_sha256": roots.identity_sha256(root_alias),
            "entries": [entry.model_dump(mode="json") for entry in entries],
            "summary": summary.model_dump(mode="json"),
            "source_set_sha256": source_set_sha256,
        }
        inventory = LegacySourceInventoryV2(
            schema_version="legacy-source-inventory/2.0",
            inventory_id=inventory_id,
            observed_at=observed_at or datetime.now(UTC),
            scanner_version=SCANNER_VERSION,
            scanner_policy_revision_id=policy.policy_revision_id,
            scanner_policy_sha256=policy.policy_sha256,
            root_alias=root_alias,
            root_configuration_sha256=roots.identity_sha256(root_alias),
            entries=entries,
            summary=summary,
            source_set_sha256=source_set_sha256,
            inventory_sha256=content_sha256(identity_payload),
        )
        validate_contract("legacy-source-inventory-v2", inventory.model_dump(mode="json"))
        return inventory

    def _walk_directory(
        self,
        *,
        directory_fd: int,
        relative_parts: tuple[str, ...],
        state: _ScanState,
    ) -> None:
        if len(relative_parts) > state.policy.limits.max_depth:
            state.fail_capacity()
        before = os.fstat(directory_fd)
        try:
            with os.scandir(directory_fd) as iterator:
                names = sorted((entry.name for entry in iterator), key=str.casefold)
        except OSError as exc:
            raise LegacySourceInventoryError(
                LegacyKnowledgeContractErrorCode.LEGACY_KNOWLEDGE_ROOT_INVALID
            ) from exc
        for name in names:
            path_parts = (*relative_parts, name)
            relative_path = "/".join(path_parts)
            state.register_path(relative_path)
            try:
                metadata = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
            except OSError as exc:
                raise LegacySourceInventoryError(
                    LegacyKnowledgeContractErrorCode.LEGACY_KNOWLEDGE_FILE_CHANGED
                ) from exc
            if stat.S_ISDIR(metadata.st_mode):
                if state.exclusion_reasons(path_parts):
                    continue
                child_fd = -1
                try:
                    child_fd = os.open(name, _OPEN_DIRECTORY, dir_fd=directory_fd)
                    opened = os.fstat(child_fd)
                    if _file_identity(metadata) != _file_identity(opened):
                        raise LegacySourceInventoryError(
                            LegacyKnowledgeContractErrorCode.LEGACY_KNOWLEDGE_FILE_CHANGED
                        )
                    self._walk_directory(
                        directory_fd=child_fd,
                        relative_parts=path_parts,
                        state=state,
                    )
                finally:
                    if child_fd >= 0:
                        os.close(child_fd)
                continue
            state.add_entry(
                self._observe_entry(
                    parent_fd=directory_fd,
                    name=name,
                    relative_path=relative_path,
                    path_parts=path_parts,
                    metadata=metadata,
                    state=state,
                )
            )
        after = os.fstat(directory_fd)
        if _directory_identity(before) != _directory_identity(after):
            raise LegacySourceInventoryError(
                LegacyKnowledgeContractErrorCode.LEGACY_KNOWLEDGE_ROOT_CHANGED
            )

    def _observe_entry(
        self,
        *,
        parent_fd: int,
        name: str,
        relative_path: str,
        path_parts: tuple[str, ...],
        metadata: os.stat_result,
        state: _ScanState,
    ) -> LegacySourceInventoryEntry:
        entry_key = _entry_key(state.root_alias, relative_path)
        configured_reasons = state.exclusion_reasons(path_parts)
        if stat.S_ISLNK(metadata.st_mode):
            return _excluded_entry(
                entry_key,
                relative_path,
                LegacyFileObservation.SYMLINK,
                metadata.st_size,
                (*configured_reasons, LegacyExclusionReason.SYMLINK),
            )
        if not stat.S_ISREG(metadata.st_mode):
            return _excluded_entry(
                entry_key,
                relative_path,
                LegacyFileObservation.SPECIAL,
                metadata.st_size,
                (*configured_reasons, LegacyExclusionReason.SPECIAL_FILE),
            )
        if metadata.st_nlink != 1:
            return _excluded_entry(
                entry_key,
                relative_path,
                LegacyFileObservation.HARDLINK,
                metadata.st_size,
                (*configured_reasons, LegacyExclusionReason.HARDLINK),
            )
        if configured_reasons:
            return _excluded_entry(
                entry_key,
                relative_path,
                LegacyFileObservation.REGULAR,
                metadata.st_size,
                configured_reasons,
            )
        rule = state.classification_rule(path_parts)
        if rule is None:
            return _excluded_entry(
                entry_key,
                relative_path,
                LegacyFileObservation.REGULAR,
                metadata.st_size,
                (LegacyExclusionReason.OUTSIDE_ALLOWLIST,),
            )
        if metadata.st_size > state.policy.limits.max_file_bytes:
            return _excluded_entry(
                entry_key,
                relative_path,
                LegacyFileObservation.REGULAR,
                metadata.st_size,
                (LegacyExclusionReason.SIZE_LIMIT,),
            )
        state.reserve_candidate_bytes(metadata.st_size)
        try:
            descriptor = os.open(name, _OPEN_READ, dir_fd=parent_fd)
        except PermissionError:
            return _excluded_entry(
                entry_key,
                relative_path,
                LegacyFileObservation.UNREADABLE,
                metadata.st_size,
                (LegacyExclusionReason.UNREADABLE,),
            )
        except OSError as exc:
            raise LegacySourceInventoryError(
                LegacyKnowledgeContractErrorCode.LEGACY_KNOWLEDGE_FILE_CHANGED
            ) from exc
        try:
            opened = os.fstat(descriptor)
            if _file_identity(metadata) != _file_identity(opened) or not stat.S_ISREG(
                opened.st_mode
            ):
                raise LegacySourceInventoryError(
                    LegacyKnowledgeContractErrorCode.LEGACY_KNOWLEDGE_FILE_CHANGED
                )
            prefix = os.read(descriptor, state.policy.limits.signature_scan_bytes)
            if _contains_secret(prefix):
                _require_unchanged_file(opened, os.fstat(descriptor))
                return _excluded_entry(
                    entry_key,
                    relative_path,
                    LegacyFileObservation.REGULAR,
                    opened.st_size,
                    (LegacyExclusionReason.SECRET_OR_CREDENTIAL,),
                )
            media_type = _detect_media_type(PurePosixPath(relative_path).suffix.casefold(), prefix)
            if media_type is None:
                _require_unchanged_file(opened, os.fstat(descriptor))
                return _excluded_entry(
                    entry_key,
                    relative_path,
                    LegacyFileObservation.REGULAR,
                    opened.st_size,
                    (LegacyExclusionReason.UNSUPPORTED_MEDIA,),
                )
            digest = hashlib.sha256(prefix)
            while chunk := os.read(descriptor, READ_CHUNK_BYTES):
                digest.update(chunk)
            final = os.fstat(descriptor)
            _require_unchanged_file(opened, final)
        finally:
            os.close(descriptor)
        preliminary_class = LegacySourcePreliminaryClass(rule.preliminary_class)
        canonicality = (
            LegacySourceCanonicality.ORIGINAL
            if preliminary_class == LegacySourcePreliminaryClass.ORIGINAL_SOURCE_CANDIDATE
            else LegacySourceCanonicality.DERIVED
        )
        return LegacySourceInventoryEntry(
            entry_key=entry_key,
            relative_path=relative_path,
            file_observation=LegacyFileObservation.REGULAR,
            size_bytes=metadata.st_size,
            media_type=media_type,
            content_sha256="sha256:" + digest.hexdigest(),
            preliminary_class=preliminary_class,
            source_family=LegacySourceFamily(rule.source_family),
            canonicality=canonicality,
            rights_state=LegacyRightsState.UNREVIEWED,
            relation_group_key=None,
            exclusion_reasons=(),
        )


class _ScanState:
    def __init__(
        self,
        *,
        policy: LegacySourceInventoryPolicy,
        root_alias: LegacyRootAlias,
        rules: tuple[LegacyInventoryClassificationRule, ...],
    ) -> None:
        self.policy = policy
        self.root_alias = root_alias
        self.rules = rules
        self.entries: list[LegacySourceInventoryEntry] = []
        self._paths: set[str] = set()
        self._collision_keys: set[str] = set()
        self._candidate_bytes = 0

    def register_path(self, value: str) -> None:
        if (
            value != unicodedata.normalize("NFC", value)
            or len(value) > self.policy.limits.max_path_length
            or len(PurePosixPath(value).parts) > self.policy.limits.max_depth
            or any(ord(character) < 32 or ord(character) == 127 for character in value)
            or "\\" in value
        ):
            raise LegacySourceInventoryError(
                LegacyKnowledgeContractErrorCode.LEGACY_KNOWLEDGE_UNSAFE_PATH
            )
        collision_key = value.casefold()
        if value in self._paths or collision_key in self._collision_keys:
            raise LegacySourceInventoryError(
                LegacyKnowledgeContractErrorCode.LEGACY_KNOWLEDGE_DUPLICATE_ENTRY
            )
        self._paths.add(value)
        self._collision_keys.add(collision_key)

    def add_entry(self, entry: LegacySourceInventoryEntry) -> None:
        if len(self.entries) >= self.policy.limits.max_observations:
            self.fail_capacity()
        self.entries.append(entry)

    def reserve_candidate_bytes(self, size_bytes: int) -> None:
        self._candidate_bytes += size_bytes
        if self._candidate_bytes > self.policy.limits.max_candidate_bytes:
            self.fail_capacity()

    def fail_capacity(self) -> None:
        raise LegacySourceInventoryError(
            LegacyKnowledgeContractErrorCode.LEGACY_KNOWLEDGE_CAPACITY_EXCEEDED
        )

    def exclusion_reasons(self, path_parts: tuple[str, ...]) -> tuple[LegacyExclusionReason, ...]:
        folded_parts = tuple(part.casefold() for part in path_parts)
        basename = folded_parts[-1]
        suffix = PurePosixPath(basename).suffix.casefold()
        reasons: set[LegacyExclusionReason] = set()
        for rule in self.policy.exclusion_rules:
            matched = (
                (rule.match_kind == "PATH_SEGMENT" and rule.value in folded_parts)
                or (rule.match_kind == "BASENAME" and rule.value == basename)
                or (rule.match_kind == "SUFFIX" and rule.value == suffix)
            )
            if matched:
                reasons.add(LegacyExclusionReason(rule.reason))
        return tuple(sorted(reasons, key=str))

    def classification_rule(
        self, path_parts: tuple[str, ...]
    ) -> LegacyInventoryClassificationRule | None:
        suffix = PurePosixPath(path_parts[-1]).suffix.casefold()
        matches = []
        for rule in self.rules:
            prefix_parts = PurePosixPath(rule.relative_prefix).parts
            if path_parts[: len(prefix_parts)] == prefix_parts and suffix in rule.allowed_suffixes:
                matches.append(rule)
        if len(matches) > 1:
            raise LegacySourceInventoryError(
                LegacyKnowledgeContractErrorCode.LEGACY_KNOWLEDGE_POLICY_INVALID
            )
        return matches[0] if matches else None


def _load_json_document(path: Path, *, protected: bool) -> dict[str, Any]:
    descriptor = -1
    parent_fd = -1
    try:
        if (
            not path.is_absolute()
            or path.name in {"", ".", ".."}
            or any(part in {".", ".."} for part in path.parts)
        ):
            raise OSError("control document path is unsafe")
        parent_fd = _open_absolute_directory(path.parent)
        descriptor = os.open(path.name, _OPEN_READ, dir_fd=parent_fd)
        before = os.fstat(descriptor)
        mode = stat.S_IMODE(before.st_mode)
        allowed_owner = before.st_uid in {0, os.geteuid()}
        unsafe_mode = bool(mode & (0o077 if protected else 0o022))
        if not stat.S_ISREG(before.st_mode) or before.st_size > MAX_CONTROL_DOCUMENT_BYTES:
            raise OSError("invalid control document")
        if not allowed_owner or unsafe_mode:
            raise OSError("unsafe control document ownership or mode")
        chunks: list[bytes] = []
        remaining = MAX_CONTROL_DOCUMENT_BYTES + 1
        while remaining and (chunk := os.read(descriptor, min(remaining, READ_CHUNK_BYTES))):
            chunks.append(chunk)
            remaining -= len(chunk)
        if remaining == 0:
            raise OSError("control document exceeds limit")
        after = os.fstat(descriptor)
        if _file_identity(before) != _file_identity(after):
            raise OSError("control document changed")
        value = json.loads(
            b"".join(chunks).decode("utf-8"),
            object_pairs_hook=_unique_json_object,
            parse_constant=lambda _value: (_ for _ in ()).throw(ValueError("non-finite JSON")),
        )
        if not isinstance(value, dict):
            raise ValueError("control document must be an object")
        return value
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as exc:
        raise LegacySourceInventoryError(
            LegacyKnowledgeContractErrorCode.LEGACY_KNOWLEDGE_CONFIGURATION_INVALID
        ) from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if parent_fd >= 0:
            os.close(parent_fd)


def _unique_json_object(items: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in items:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _open_absolute_directory(path: Path) -> int:
    if not path.is_absolute():
        raise OSError("directory path is not absolute")
    descriptor = os.open("/", _OPEN_DIRECTORY)
    try:
        for part in path.parts[1:]:
            child = os.open(part, _OPEN_DIRECTORY, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        metadata = os.fstat(descriptor)
        if not stat.S_ISDIR(metadata.st_mode):
            raise OSError("directory target is not a directory")
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def _open_relative_directory(root_fd: int, parts: tuple[str, ...]) -> int:
    descriptor = os.dup(root_fd)
    try:
        for part in parts:
            child = os.open(part, _OPEN_DIRECTORY, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def _minimal_scan_scopes(prefixes: Iterable[str]) -> tuple[str, ...]:
    ordered = sorted(set(prefixes), key=lambda value: (len(PurePosixPath(value).parts), value))
    scopes: list[str] = []
    scope_parts: list[tuple[str, ...]] = []
    for value in ordered:
        parts = PurePosixPath(value).parts
        if any(parts[: len(existing)] == existing for existing in scope_parts):
            continue
        scopes.append(value)
        scope_parts.append(parts)
    return tuple(sorted(scopes, key=lambda value: (value.casefold(), value)))


def _entry_key(root_alias: LegacyRootAlias, relative_path: str) -> str:
    digest = content_sha256(
        {
            "schema_version": "legacy-source-entry-identity/1.0",
            "root_alias": root_alias,
            "relative_path": relative_path,
        }
    ).removeprefix("sha256:")
    return "legacyentry_" + digest[:32]


def _excluded_entry(
    entry_key: str,
    relative_path: str,
    observation: LegacyFileObservation,
    size_bytes: int,
    reasons: Iterable[LegacyExclusionReason],
) -> LegacySourceInventoryEntry:
    normalized_reasons = tuple(sorted(set(reasons), key=str))
    return LegacySourceInventoryEntry(
        entry_key=entry_key,
        relative_path=relative_path,
        file_observation=observation,
        size_bytes=size_bytes,
        media_type=None,
        content_sha256=None,
        preliminary_class=LegacySourcePreliminaryClass.EXCLUDED_RUNTIME_STATE,
        source_family=LegacySourceFamily.EXCLUDED,
        canonicality=LegacySourceCanonicality.UNKNOWN,
        rights_state=LegacyRightsState.UNREVIEWED,
        relation_group_key=None,
        exclusion_reasons=normalized_reasons,
    )


def _inventory_summary(
    entries: tuple[LegacySourceInventoryEntry, ...],
) -> LegacySourceInventorySummary:
    def class_summary(
        classification: LegacySourcePreliminaryClass,
    ) -> LegacySourceInventoryClassSummary:
        matching = tuple(entry for entry in entries if entry.preliminary_class == classification)
        return LegacySourceInventoryClassSummary(
            file_count=len(matching),
            byte_count=sum(entry.size_bytes for entry in matching),
        )

    return LegacySourceInventorySummary(
        original_source_candidates=class_summary(
            LegacySourcePreliminaryClass.ORIGINAL_SOURCE_CANDIDATE
        ),
        derived_migration_evidence=class_summary(
            LegacySourcePreliminaryClass.DERIVED_MIGRATION_EVIDENCE
        ),
        excluded_runtime_state=class_summary(LegacySourcePreliminaryClass.EXCLUDED_RUNTIME_STATE),
        total_file_count=len(entries),
        total_byte_count=sum(entry.size_bytes for entry in entries),
    )


def _contains_secret(prefix: bytes) -> bool:
    lowered = prefix.lower()
    if any(marker.lower() in lowered for marker in _SECRET_PREFIX_MARKERS):
        return True
    return any(pattern.search(prefix) is not None for pattern in _SECRET_CONTENT_PATTERNS)


def _detect_media_type(suffix: str, prefix: bytes) -> str | None:
    if suffix == ".pdf" and prefix.startswith(b"%PDF-"):
        return "application/pdf"
    if suffix == ".png" and prefix.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if suffix == ".hwp" and prefix.startswith(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"):
        return "application/vnd.hancom.hwp"
    if suffix == ".hwpx" and prefix.startswith(b"PK\x03\x04"):
        return "application/vnd.hancom.hwpx"
    if suffix == ".xlsx" and prefix.startswith(b"PK\x03\x04"):
        return "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    stripped = prefix.lstrip()
    if suffix == ".json" and stripped.startswith((b"{", b"[")):
        try:
            prefix.decode("utf-8")
        except UnicodeDecodeError:
            return None
        return "application/json"
    if suffix in {".md", ".txt", ".csv"}:
        try:
            prefix.decode("utf-8")
        except UnicodeDecodeError:
            return None
        return {".md": "text/markdown", ".txt": "text/plain", ".csv": "text/csv"}[suffix]
    return None


def _file_identity(value: os.stat_result) -> tuple[int, int, int, int, int, int]:
    return (
        value.st_dev,
        value.st_ino,
        stat.S_IFMT(value.st_mode),
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
    )


def _require_unchanged_file(before: os.stat_result, after: os.stat_result) -> None:
    if _file_identity(before) != _file_identity(after):
        raise LegacySourceInventoryError(
            LegacyKnowledgeContractErrorCode.LEGACY_KNOWLEDGE_FILE_CHANGED
        )


def _directory_identity(value: os.stat_result) -> tuple[int, int, int, int, int]:
    return (
        value.st_dev,
        value.st_ino,
        stat.S_IFMT(value.st_mode),
        value.st_mtime_ns,
        value.st_ctime_ns,
    )
