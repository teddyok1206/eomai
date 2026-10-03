"""Acquisition-owner use case: public pinned inputs to one safe, local model revision."""

from __future__ import annotations

import hashlib
import os
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from eom_image_contracts import (
    InformativeLineartUpstream,
    LocalImageInformativeLineartManifest,
    ModelFile,
    content_json_bytes,
    validate_contract,
)

from eom_image_provider.informative_lineart_model import (
    InformativeLineartConversion,
    convert_informative_lineart_weights,
    informative_lineart_config_bytes,
    informative_lineart_license_bytes,
)
from eom_image_provider.provider import ProviderError
from eom_image_provider.staged_file_io import (
    create_staged_directory,
    verified_directory,
    write_staged_member,
)


@dataclass(frozen=True)
class AcquiredInformativeLineartModel:
    manifest: LocalImageInformativeLineartManifest
    tensor_count: int
    parameter_count: int


def acquire_informative_lineart_model(
    staging_root: Path,
    *,
    created_by: str,
    fetch: Callable[[str, int], bytes],
    convert: Callable[[bytes, InformativeLineartUpstream], InformativeLineartConversion] = (
        convert_informative_lineart_weights
    ),
    created_at: datetime | None = None,
) -> AcquiredInformativeLineartModel:
    """Write only a fresh local ``model`` child, never install, activate or commit to NAS.

    The acquisition owner supplies an exclusive, owner-only staging root. A failed attempt
    retains partial staging; the final manifest is written last. Replays cannot overwrite it.
    """
    upstream = InformativeLineartUpstream.pinned()
    try:
        with verified_directory(staging_root, expected_owner_uid=os.geteuid()) as root:
            if os.listdir(root):
                raise ProviderError("LINEART_EXTRACTOR_STAGING_INVALID")
            evidence = (
                ("README.md", 64 * 1024, upstream.license_record_sha256),
                ("app.py", 64 * 1024, upstream.architecture_source_sha256),
                (upstream.weight_filename, upstream.weight_bytes, upstream.weight_sha256),
            )
            # Check pinned provenance before any Torch import, conversion or filesystem write.
            source_weights = b""
            for name, ceiling, expected in evidence:
                payload = fetch(name, ceiling)
                if not 0 < len(payload) <= ceiling:
                    raise ProviderError("LINEART_EXTRACTOR_DOWNLOAD_INVALID")
                if "sha256:" + hashlib.sha256(payload).hexdigest() != expected:
                    raise ProviderError("LINEART_EXTRACTOR_HASH_MISMATCH")
                if name == upstream.weight_filename:
                    if len(payload) != upstream.weight_bytes:
                        raise ProviderError("LINEART_EXTRACTOR_MODEL_INVALID")
                    source_weights = payload
            conversion = convert(source_weights, upstream)
            members = {
                "LICENSE": informative_lineart_license_bytes(),
                "config.json": informative_lineart_config_bytes(),
                "model.safetensors": conversion.safetensors_bytes,
                "upstream.json": content_json_bytes(upstream.model_dump(mode="json")),
            }
            manifest = LocalImageInformativeLineartManifest.create(
                files=tuple(
                    ModelFile(
                        relative_path=name,
                        size_bytes=len(payload),
                        sha256="sha256:" + hashlib.sha256(payload).hexdigest(),
                    )
                    for name, payload in sorted(members.items())
                ),
                created_at=created_at if created_at is not None else datetime.now(UTC),
                created_by=created_by,
            )
            value = manifest.model_dump(mode="json")
            validate_contract("informative-lineart-manifest", value)
            create_staged_directory(root, "model")
            with verified_directory(
                staging_root / "model", expected_owner_uid=os.geteuid()
            ) as target:
                for name, payload in sorted(members.items()):
                    write_staged_member(target, name, payload)
                write_staged_member(target, "manifest.json", content_json_bytes(value))
            return AcquiredInformativeLineartModel(
                manifest=manifest,
                tensor_count=conversion.tensor_count,
                parameter_count=conversion.parameter_count,
            )
    except ProviderError as exc:
        if exc.code.startswith("LINEART_EXTRACTOR_"):
            raise
        raise ProviderError("LINEART_EXTRACTOR_STAGING_INVALID") from exc
    except (ValueError, TypeError, OSError) as exc:
        raise ProviderError("LINEART_EXTRACTOR_MODEL_INVALID") from exc
