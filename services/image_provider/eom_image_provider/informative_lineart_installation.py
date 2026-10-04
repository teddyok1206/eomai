"""Operator-only materialization of one pinned extractor revision into the protected store."""

from __future__ import annotations

import json
import os
import stat
import tempfile
from pathlib import Path

from eom_image_contracts import (
    InformativeLineartPointer,
    LocalImageInformativeLineartManifest,
    content_json_bytes,
    validate_contract,
)
from jsonschema import ValidationError as JsonSchemaValidationError

from eom_image_provider.informative_lineart_model import (
    informative_lineart_config_bytes,
    informative_lineart_license_bytes,
)
from eom_image_provider.informative_lineart_resolution import resolve_informative_lineart_material
from eom_image_provider.provider import ProviderError
from eom_image_provider.staged_file_io import (
    copy_verified_member,
    read_staged_member,
    verified_directory,
    write_staged_member,
)


def _directory(path: Path, *, group_gid: int) -> None:
    try:
        path.mkdir(mode=0o750)
    except FileExistsError:
        metadata = path.lstat()
        if (
            not stat.S_ISDIR(metadata.st_mode)
            or metadata.st_uid != 0
            or metadata.st_gid != group_gid
            or stat.S_IMODE(metadata.st_mode) != 0o750
        ):
            raise ProviderError("LINEART_EXTRACTOR_INSTALL_INVALID") from None
        return
    os.chown(path, 0, group_gid)
    path.chmod(0o750)


def install_informative_lineart_revision(
    *,
    source: Path,
    model_store_root: Path,
    pointer: InformativeLineartPointer,
    source_owner_uid: int,
    worker_group_gid: int,
) -> LocalImageInformativeLineartManifest:
    """Exclusive staging, FD/hash-checked copy, final receipt before atomic revision publication.

    A failed temporary install remains for diagnosis. Existing immutable revisions are checked,
    never overwritten. This operator boundary has no Torch, network, activation or NAS writes.
    """
    if os.geteuid() != 0 or source_owner_uid <= 0 or worker_group_gid <= 0:
        raise ProviderError("LINEART_EXTRACTOR_INSTALL_REQUIRES_OPERATOR")
    try:
        pointer = InformativeLineartPointer.model_validate_json(pointer.model_dump_json())
        with verified_directory(source, expected_owner_uid=source_owner_uid) as origin:
            raw = read_staged_member(
                origin,
                "manifest.json",
                maximum_bytes=64 * 1024,
                expected_owner_uid=source_owner_uid,
            )
            value = json.loads(raw)
            validate_contract("informative-lineart-manifest", value)
            manifest = LocalImageInformativeLineartManifest.model_validate(value)
            if raw != content_json_bytes(value):
                raise ValueError("noncanonical install manifest")
            actual = InformativeLineartPointer(
                **manifest.model_dump(include=set(InformativeLineartPointer.model_fields))
            )
            if actual != pointer or set(os.listdir(origin)) != {
                "manifest.json",
                *(file.relative_path for file in manifest.files),
            }:
                raise ProviderError("LINEART_EXTRACTOR_INSTALL_INVALID")
            for name, expected in (
                ("config.json", informative_lineart_config_bytes()),
                ("LICENSE", informative_lineart_license_bytes()),
                ("upstream.json", content_json_bytes(manifest.upstream.model_dump(mode="json"))),
            ):
                if (
                    read_staged_member(
                        origin, name, maximum_bytes=64 * 1024, expected_owner_uid=source_owner_uid
                    )
                    != expected
                ):
                    raise ProviderError("LINEART_EXTRACTOR_INSTALL_INVALID")
            with verified_directory(model_store_root, expected_owner_uid=0):
                logical = model_store_root / pointer.extractor_id
                _directory(logical, group_gid=worker_group_gid)
                final = logical / pointer.extractor_revision_id
                if os.path.lexists(final):
                    return resolve_informative_lineart_material(model_store_root, pointer).manifest
                staging = Path(tempfile.mkdtemp(prefix=".installing-lineart-", dir=logical))
                os.chown(staging, 0, worker_group_gid)
                staging.chmod(0o750)
                with verified_directory(staging, expected_owner_uid=0) as destination:
                    for file in manifest.files:
                        copy_verified_member(
                            origin,
                            destination,
                            file.relative_path,
                            size_bytes=file.size_bytes,
                            sha256=file.sha256,
                            source_owner_uid=source_owner_uid,
                            destination_group_gid=worker_group_gid,
                        )
                    write_staged_member(destination, "manifest.json", raw)
                    os.chown(staging / "manifest.json", 0, worker_group_gid)
                    (staging / "manifest.json").chmod(0o640)
                    os.fsync(destination)
                # Validate all pinned metadata and files before the revision becomes visible.
                with verified_directory(staging, expected_owner_uid=0) as staged:
                    for file in manifest.files:
                        payload = read_staged_member(
                            staged,
                            file.relative_path,
                            maximum_bytes=file.size_bytes,
                            expected_sha256=file.sha256,
                            expected_owner_uid=0,
                        )
                        if len(payload) != file.size_bytes:
                            raise ProviderError("LINEART_EXTRACTOR_HASH_MISMATCH")
                # An operator installs with all extractor work quiescent; never replace an existing
                # nonempty directory. rename is publication, not a mutable-current pointer update.
                os.rename(staging, final)
                with verified_directory(logical, expected_owner_uid=0) as descriptor:
                    os.fsync(descriptor)
            return resolve_informative_lineart_material(model_store_root, pointer).manifest
    except ProviderError:
        raise
    except (ValueError, TypeError, OSError, JsonSchemaValidationError) as exc:
        raise ProviderError("LINEART_EXTRACTOR_INSTALL_INVALID") from exc
