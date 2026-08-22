"""Secure Content Pack source loader and deterministic bundle adapter."""

from __future__ import annotations

import json
import shutil
import stat
import unicodedata
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, cast

from eom_catalog_contracts import ContentPackManifest, ContentPackProfile, validate_contract
from eom_content_pack import (
    ContentPackError,
    ContentPackErrorCode,
    validate_prompt_template,
)
from eom_identifiers import canonical_json_bytes, content_sha256, sha256_bytes, sha256_file

from eom_catalog_service.intake_files import (
    SECRET_PATTERNS,
    load_strict_json,
    load_strict_yaml,
)

ALLOWED_EXTENSIONS = frozenset({".yaml", ".yml", ".json", ".md", ".txt"})
MAX_PACK_FILES = 500
MAX_PACK_FILE_BYTES = 2 * 1024 * 1024
FIXED_ZIP_TIME = (1980, 1, 1, 0, 0, 0)


@dataclass(frozen=True)
class PackSourceFile:
    relative_path: str
    path: Path
    media_type: str
    size_bytes: int
    sha256: str
    logical_role: str


@dataclass(frozen=True)
class CompiledPack:
    source_root: Path
    manifest: ContentPackManifest
    files: tuple[PackSourceFile, ...]
    profiles: tuple[ContentPackProfile, ...]
    canonical_manifest: dict[str, Any]
    source_tree_sha256: str


@dataclass(frozen=True)
class BuiltPack:
    compiled: CompiledPack
    bundle_path: Path
    manifest_path: Path
    bundle_sha256: str
    manifest_sha256: str


def compile_pack(source_root: Path) -> CompiledPack:
    files = _discover_files(source_root)
    by_path = {item.relative_path: item for item in files}
    pack_file = by_path.get("pack.yaml")
    if pack_file is None:
        raise ContentPackError(
            ContentPackErrorCode.CONTENT_PACK_REFERENCE_MISSING, "pack.yaml is missing"
        )
    raw = load_strict_yaml(pack_file.path)
    contract_name = "content-pack-v2" if raw.get("schema_version") == "1.1" else "content-pack"
    validate_contract(contract_name, raw)
    manifest = ContentPackManifest.model_validate(raw)
    referenced = _referenced_paths(manifest)
    missing = sorted(referenced - by_path.keys())
    if missing:
        raise ContentPackError(
            ContentPackErrorCode.CONTENT_PACK_REFERENCE_MISSING,
            f"content pack references a missing file: {missing[0]}",
        )
    profiles: list[ContentPackProfile] = []
    for profile_type, entries in sorted(manifest.profiles.items()):
        for profile_key, relative_path in sorted(entries.items()):
            profile_raw = load_strict_yaml(by_path[relative_path].path)
            validate_contract("content-pack-profile", profile_raw)
            profile = ContentPackProfile.model_validate(profile_raw)
            if profile.profile.type != profile_type or profile.profile.key != profile_key:
                raise ContentPackError(
                    ContentPackErrorCode.CONTENT_PACK_PROFILE_INVALID,
                    "profile identity does not match pack.yaml",
                )
            template_file = by_path.get(profile.template)
            if template_file is None:
                raise ContentPackError(
                    ContentPackErrorCode.CONTENT_PACK_REFERENCE_MISSING,
                    "profile prompt template is missing",
                )
            template = template_file.path.read_text(encoding="utf-8")
            validate_prompt_template(template, profile.required_context)
            profiles.append(profile)
    _validate_structured_files(files)
    source_tree_sha256 = content_sha256(
        [{"path": item.relative_path, "sha256": item.sha256} for item in files]
    )
    canonical_manifest: dict[str, Any] = {
        "schema_version": "1.0",
        "pack_key": manifest.pack.key,
        "pack_version": manifest.pack.version,
        "source_tree_sha256": source_tree_sha256,
        "files": [
            {
                "relative_path": item.relative_path,
                "media_type": item.media_type,
                "size_bytes": item.size_bytes,
                "sha256": item.sha256,
                "logical_role": item.logical_role,
            }
            for item in files
        ],
    }
    return CompiledPack(
        source_root=source_root,
        manifest=manifest,
        files=files,
        profiles=tuple(profiles),
        canonical_manifest=canonical_manifest,
        source_tree_sha256=source_tree_sha256,
    )


def build_pack(source_root: Path, output_directory: Path) -> BuiltPack:
    compiled = compile_pack(source_root)
    output_directory.mkdir(parents=True, exist_ok=True)
    file_name = f"{compiled.manifest.pack.key}-{compiled.manifest.pack.version}.eompack"
    bundle_path = output_directory / file_name
    manifest_path = output_directory / "content-pack-manifest.json"
    manifest_bytes = canonical_json_bytes(compiled.canonical_manifest)
    manifest_path.write_bytes(manifest_bytes)
    with zipfile.ZipFile(bundle_path, "w") as archive:
        for item in compiled.files:
            _write_zip_entry(archive, item.relative_path, item.path.read_bytes())
        _write_zip_entry(archive, "content-pack-manifest.json", manifest_bytes)
    built = BuiltPack(
        compiled=compiled,
        bundle_path=bundle_path,
        manifest_path=manifest_path,
        bundle_sha256=sha256_file(bundle_path),
        manifest_sha256=sha256_bytes(manifest_bytes),
    )
    inspect_bundle(bundle_path)
    return built


def materialize_pack_source(
    template_root: Path,
    output_root: Path,
    *,
    batch_id: str,
    proposal_key: str,
    pack_key: str,
    version: str,
) -> CompiledPack:
    compile_pack(template_root)
    if output_root.exists():
        raise ContentPackError(
            ContentPackErrorCode.CONTENT_PACK_BUILD_FAILED,
            "pack source output already exists",
        )
    shutil.copytree(template_root, output_root, copy_function=shutil.copyfile)
    pack_path = output_root / "pack.yaml"
    raw = load_strict_yaml(pack_path)
    raw["pack"]["key"] = pack_key
    raw["pack"]["version"] = version
    raw["provenance"]["intake_batch_ids"] = [batch_id]
    raw["provenance"]["mapping_proposal_ids"] = [proposal_key]
    import yaml

    pack_path.write_text(yaml.safe_dump(raw, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return compile_pack(output_root)


def inspect_bundle(bundle_path: Path) -> dict[str, Any]:
    with zipfile.ZipFile(bundle_path) as archive:
        seen: set[str] = set()
        folded: set[str] = set()
        entries: dict[str, bytes] = {}
        for info in archive.infolist():
            name = _safe_path(info.filename)
            if name in seen or name.casefold() in folded:
                raise ContentPackError(
                    ContentPackErrorCode.CONTENT_PACK_DUPLICATE_PATH,
                    "bundle contains a duplicate path",
                )
            if stat.S_ISLNK(info.external_attr >> 16):
                raise ContentPackError(
                    ContentPackErrorCode.CONTENT_PACK_UNSAFE_PATH,
                    "bundle contains a symbolic link",
                )
            seen.add(name)
            folded.add(name.casefold())
            entries[name] = archive.read(info)
    try:
        manifest = cast(dict[str, Any], json.loads(entries["content-pack-manifest.json"]))
    except (KeyError, json.JSONDecodeError) as exc:
        raise ContentPackError(
            ContentPackErrorCode.CONTENT_PACK_INVALID, "bundle manifest is invalid"
        ) from exc
    expected = {entry["relative_path"]: entry for entry in manifest.get("files", [])}
    if set(entries) != set(expected) | {"content-pack-manifest.json"}:
        raise ContentPackError(
            ContentPackErrorCode.CONTENT_PACK_INVALID, "bundle entries do not match manifest"
        )
    for name, metadata in expected.items():
        if sha256_bytes(entries[name]) != metadata["sha256"]:
            raise ContentPackError(
                ContentPackErrorCode.CONTENT_PACK_INVALID, "bundle file hash mismatch"
            )
    return manifest


def _discover_files(root: Path) -> tuple[PackSourceFile, ...]:
    if root.is_symlink() or not root.is_dir():
        raise ContentPackError(
            ContentPackErrorCode.CONTENT_PACK_UNSAFE_PATH,
            "content pack source must be a directory",
        )
    resolved = root.resolve(strict=True)
    discovered: list[PackSourceFile] = []
    normalized: set[str] = set()
    folded: set[str] = set()
    for candidate in sorted(resolved.rglob("*"), key=lambda path: path.as_posix()):
        info = candidate.lstat()
        if stat.S_ISDIR(info.st_mode):
            if candidate.is_symlink():
                raise ContentPackError(
                    ContentPackErrorCode.CONTENT_PACK_UNSAFE_PATH,
                    "content pack contains a symbolic link",
                )
            continue
        if candidate.is_symlink() or not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise ContentPackError(
                ContentPackErrorCode.CONTENT_PACK_UNSAFE_PATH,
                "content pack contains a linked or special file",
            )
        if info.st_mode & 0o111 or info.st_size > MAX_PACK_FILE_BYTES:
            raise ContentPackError(
                ContentPackErrorCode.CONTENT_PACK_UNSAFE_PATH,
                "content pack contains executable or oversized data",
            )
        relative = unicodedata.normalize(
            "NFC", _safe_path(candidate.relative_to(resolved).as_posix())
        )
        if relative in normalized or relative.casefold() in folded:
            raise ContentPackError(
                ContentPackErrorCode.CONTENT_PACK_DUPLICATE_PATH,
                "content pack paths collide after normalization",
            )
        if Path(relative).suffix.casefold() not in ALLOWED_EXTENSIONS:
            raise ContentPackError(
                ContentPackErrorCode.CONTENT_PACK_UNSAFE_PATH,
                "content pack contains an unsupported file type",
            )
        if len(discovered) >= MAX_PACK_FILES:
            raise ContentPackError(
                ContentPackErrorCode.CONTENT_PACK_INVALID, "content pack has too many files"
            )
        data = candidate.read_bytes()
        if any(pattern.search(data) for pattern in SECRET_PATTERNS):
            raise ContentPackError(
                ContentPackErrorCode.CONTENT_PACK_SECRET_DETECTED,
                "content pack contains a suspected secret",
            )
        normalized.add(relative)
        folded.add(relative.casefold())
        discovered.append(
            PackSourceFile(
                relative_path=relative,
                path=candidate,
                media_type=_media_type(relative),
                size_bytes=info.st_size,
                sha256=sha256_bytes(data),
                logical_role=_logical_role(relative),
            )
        )
    return tuple(discovered)


def _validate_structured_files(files: tuple[PackSourceFile, ...]) -> None:
    for item in files:
        suffix = Path(item.relative_path).suffix.casefold()
        if suffix in {".yaml", ".yml"}:
            load_strict_yaml(item.path)
        elif suffix == ".json":
            load_strict_json(item.path)
        elif suffix in {".md", ".txt"}:
            text = item.path.read_text(encoding="utf-8")
            if "<script" in text.casefold() or "<iframe" in text.casefold():
                raise ContentPackError(
                    ContentPackErrorCode.CONTENT_PACK_INVALID,
                    "content pack text contains active HTML",
                )


def _referenced_paths(manifest: ContentPackManifest) -> set[str]:
    result = set(manifest.taxonomies.values())
    result.update(item.source for item in manifest.item_types)
    for profiles in manifest.profiles.values():
        result.update(profiles.values())
    result.update(manifest.metadata_schemas.values())
    result.update(manifest.rubrics.values())
    return result


def _safe_path(value: str) -> str:
    if "\x00" in value or "\\" in value:
        raise ContentPackError(ContentPackErrorCode.CONTENT_PACK_UNSAFE_PATH, "unsafe pack path")
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or not path.parts:
        raise ContentPackError(ContentPackErrorCode.CONTENT_PACK_UNSAFE_PATH, "unsafe pack path")
    return path.as_posix()


def _write_zip_entry(archive: zipfile.ZipFile, name: str, data: bytes) -> None:
    info = zipfile.ZipInfo(name, FIXED_ZIP_TIME)
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = 0o100640 << 16
    archive.writestr(info, data)


def _media_type(path: str) -> str:
    return {
        ".yaml": "application/yaml",
        ".yml": "application/yaml",
        ".json": "application/json",
        ".md": "text/markdown",
        ".txt": "text/plain",
    }[Path(path).suffix.casefold()]


def _logical_role(path: str) -> str:
    if path == "pack.yaml":
        return "PACK_MANIFEST"
    return path.split("/", 1)[0].replace("-", "_").upper()
