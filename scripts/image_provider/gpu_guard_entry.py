"""Fixed root installation entry; copy as start_gpu_guard.py/watch_gpu_guard.py.

Configuration is a small root-owned installation value, never worker authority.
No repository, model input, credentials, NAS or latest-owner fallback is read.
"""

from __future__ import annotations

import json
import os
import re
import stat
import sys
from pathlib import Path

OWNER_RELEASE = "1031a2323d24cf2fcb968e1edd83a5e0cf5047a3"
ENTRY_ROOT = Path("/usr/local/libexec/eom-image-runtime")
OWNER_SITE = Path("/opt/eom/embedding-owner-releases") / OWNER_RELEASE / "site-packages"
CONFIG_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "additionalProperties": False,
    "required": [
        "schema_version",
        "owner_release_commit",
        "guardian_template_sha256",
        "installation",
    ],
    "properties": {
        "schema_version": {"const": "image-gpu-guardian-config/1.0"},
        "owner_release_commit": {"const": OWNER_RELEASE},
        "guardian_template_sha256": {"type": "string", "pattern": "^sha256:[0-9a-f]{64}$"},
        "installation": {"type": "object"},
    },
}


def _require(condition: bool) -> None:
    if not condition:
        raise ValueError("IMAGE_GPU_GUARD_ENTRY_INVALID")


def _epoch(value: os.stat_result) -> tuple[int, ...]:
    return (
        value.st_dev,
        value.st_ino,
        value.st_uid,
        value.st_gid,
        value.st_mode,
        value.st_nlink,
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
    )


def _directory(path: Path) -> None:
    for member in (path, *path.parents):
        value = member.lstat()
        _require(stat.S_ISDIR(value.st_mode) and value.st_uid == 0 and not value.st_mode & 0o022)


def _read(path: Path, maximum: int) -> tuple[bytes, tuple[int, ...]]:
    _directory(path.parent)
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK)
    try:
        initial = os.fstat(descriptor)
        _require(
            stat.S_ISREG(initial.st_mode)
            and initial.st_uid == 0
            and not initial.st_mode & 0o022
            and initial.st_nlink == 1
            and 0 < initial.st_size <= maximum
        )
        chunks, size = [], 0
        while chunk := os.read(descriptor, min(65536, maximum + 1 - size)):
            size += len(chunk)
            _require(size <= maximum)
            chunks.append(chunk)
        _require(
            size == initial.st_size
            and _epoch(initial) == _epoch(os.fstat(descriptor))
            and _epoch(initial) == _epoch(path.lstat())
        )
        return b"".join(chunks), _epoch(initial)
    finally:
        os.close(descriptor)


def _unique(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result = {}
    for key, value in pairs:
        _require(key not in result)
        result[key] = value
    return result


def diagnostic_code(error: Exception) -> str:
    """Preserve known stable codes, never serialize validation inputs or OS paths."""
    for candidate in (getattr(error, "code", None), str(error)):
        if (
            type(candidate) is str
            and re.fullmatch(
                r"(?:IMAGE_GPU_|INSTALLED_RUNTIME_|NATIVE_CUDA_PROBE_)[A-Z0-9_]{1,120}", candidate
            )
            is not None
        ):
            return candidate
    return "IMAGE_GPU_GUARD_ENTRY_FAILED_" + type(error).__name__.upper()


def main() -> None:
    entry = Path(__file__)
    _require(
        os.getresuid() == (0, 0, 0)
        and sys.flags.isolated == 1
        and bool(sys.dont_write_bytecode)
        and sys.platform == "linux"
        and len(sys.argv) == 2
        and entry.parent == ENTRY_ROOT
        and entry.name in {"start_gpu_guard.py", "watch_gpu_guard.py"}
    )
    _read(entry, 128 * 1024)
    path = ENTRY_ROOT / "installation.json"
    raw, epoch = _read(path, 64 * 1024)
    config = json.loads(raw, object_pairs_hook=_unique)
    _directory(OWNER_SITE)
    _read(OWNER_SITE / "eom_catalog_service/__init__.py", 64 * 1024)
    sys.path.insert(0, str(OWNER_SITE))

    from eom_catalog_service.image_gpu_unit_guardian import (
        ImageGpuInstallationPins,
        manage_image_gpu_unit_lifetime,
        start_image_gpu_unit_guardian,
    )
    from eom_catalog_service.image_gpu_unit_identity import image_gpu_unit_template
    from jsonschema import Draft202012Validator
    from pydantic import TypeAdapter

    Draft202012Validator(CONFIG_SCHEMA).validate(config)
    adapter = TypeAdapter(ImageGpuInstallationPins)
    # Existing frozen installation model owns the19-name/device/hash invariants;
    # validate its generated2020-12 schema separately so local $defs keep their scope.
    installation_schema = adapter.json_schema()
    installation_schema["additionalProperties"] = False
    Draft202012Validator(installation_schema).validate(config["installation"])
    installation = adapter.validate_python(config["installation"])
    image_gpu_unit_template(sys.argv[1])
    _require(_epoch(path.lstat()) == epoch)
    if entry.name == "start_gpu_guard.py":
        start_image_gpu_unit_guardian(
            sys.argv[1], guardian_template_sha256=config["guardian_template_sha256"]
        )
    else:
        manage_image_gpu_unit_lifetime(sys.argv[1], installation=installation)
    _require(_epoch(path.lstat()) == epoch)


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        # Stable bounded diagnostics; never dump config, prompts, paths or credentials.
        print(diagnostic_code(error), file=sys.stderr)
        raise SystemExit(1) from None
