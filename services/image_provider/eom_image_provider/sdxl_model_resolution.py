"""Resolve a pinned root-owned SDXL stack without reading weights into Python memory."""

from __future__ import annotations

import json
import os
import stat
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType

from eom_image_contracts import (
    LocalImageSdxlLineartStack,
    SdxlLineartComponentRole,
    SdxlLineartStackPointer,
    content_json_bytes,
    validate_contract,
)

from eom_image_provider.provider import ProviderError
from eom_image_provider.staged_file_io import (
    read_staged_member,
    verified_directory,
    verify_staged_member,
)


@dataclass(frozen=True)
class ResolvedSdxlStack:
    manifest: LocalImageSdxlLineartStack
    component_roots: Mapping[SdxlLineartComponentRole, Path]


def resolve_sdxl_stack(
    model_store_root: Path,
    pointer: SdxlLineartStackPointer,
    *,
    expected_owner_uid: int = 0,
) -> ResolvedSdxlStack:
    revision = model_store_root / pointer.model_id / pointer.model_revision_id
    with (
        verified_directory(model_store_root, expected_owner_uid=expected_owner_uid),
        verified_directory(revision, expected_owner_uid=expected_owner_uid) as descriptor,
    ):
        raw = read_staged_member(
            descriptor,
            "manifest.json",
            maximum_bytes=256 * 1024,
            expected_owner_uid=expected_owner_uid,
        )
        try:
            value = json.loads(raw)
            validate_contract("sdxl-lineart-stack", value)
            manifest = LocalImageSdxlLineartStack.model_validate(value)
            if raw not in (content_json_bytes(value), content_json_bytes(value) + b"\n"):
                raise ValueError("noncanonical model manifest")
        except (ValueError, TypeError) as exc:
            raise ProviderError("SDXL_PROBE_MODEL_INVALID") from exc
        if (
            manifest.model_id != pointer.model_id
            or manifest.model_revision_id != pointer.model_revision_id
            or manifest.manifest_sha256 != pointer.manifest_sha256
            or manifest.provider_family != pointer.provider_family
            or manifest.runtime_contract_version != pointer.runtime_contract_version
        ):
            raise ProviderError("SDXL_PROBE_HASH_MISMATCH")
        roots = {}
        for component in manifest.components:
            folder = component.role.lower()
            directory = revision / "components" / folder
            with verified_directory(directory, expected_owner_uid=expected_owner_uid) as root:
                expected = {file.relative_path for file in component.files}
                observed: set[str] = set()
                for parent, directories, files in os.walk(directory, followlinks=False):
                    for name in directories:
                        path = Path(parent) / name
                        metadata = path.lstat()
                        if (
                            not stat.S_ISDIR(metadata.st_mode)
                            or metadata.st_uid != expected_owner_uid
                            or stat.S_IMODE(metadata.st_mode) & 0o022
                        ):
                            raise ProviderError("SDXL_PROBE_MODEL_INVALID")
                    observed.update(
                        (Path(parent) / name).relative_to(directory).as_posix() for name in files
                    )
                if observed != expected:
                    raise ProviderError("SDXL_PROBE_MODEL_INVALID")
                for file in component.files:
                    verify_staged_member(
                        root,
                        file.relative_path,
                        size_bytes=file.size_bytes,
                        sha256=file.sha256,
                        expected_owner_uid=expected_owner_uid,
                    )
            roots[component.role] = directory
        return ResolvedSdxlStack(manifest=manifest, component_roots=MappingProxyType(roots))
