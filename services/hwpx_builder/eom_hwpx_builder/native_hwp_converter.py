"""Fixed, hash-pinned optional Java adapter inside the existing Builder sandbox."""

from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path

from eom_hwpx_contracts.curated_document import CuratedHwpConverterSnapshot
from eom_hwpx_contracts.native_conversion import NativeHwpConverterBundle
from eom_hwpx_contracts.validation import parse_json_object, validate_contract

from eom_hwpx_builder.curated_resources import fail
from eom_hwpx_builder.hwp_conversion_package import (
    HwpConversionPackageReceipt,
    normalize_hwp_conversion_package,
)
from eom_hwpx_builder.native_hwp_preservation import verify_native_hwp_candidate
from eom_hwpx_builder.util import sha256_bytes, sha256_file

_TOOL_ROOT = Path("/srv/eom/vendor/hwp2hwpx")
_JAVA = Path("/usr/lib/jvm/java-21-openjdk-amd64/bin/java")
_INSTALL_OWNER_UID = 0


def _protected_path(path: Path, *, directory: bool = False) -> None:
    metadata = path.lstat()
    expected = stat.S_ISDIR if directory else stat.S_ISREG
    if (
        not expected(metadata.st_mode)
        or metadata.st_uid != _INSTALL_OWNER_UID
        or metadata.st_mode & 0o022
    ):
        fail("native converter installation is not protected")


def read_native_conversion_file(path: Path, limit: int) -> bytes:
    descriptor = os.open(path, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW)
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or not 1 <= before.st_size <= limit:
            fail("native conversion file boundary is invalid")
        with os.fdopen(os.dup(descriptor), "rb") as stream:
            payload = stream.read(limit + 1)
        after = os.fstat(descriptor)
        if (
            before.st_dev,
            before.st_ino,
            before.st_size,
            before.st_mtime_ns,
            before.st_ctime_ns,
        ) != (
            after.st_dev,
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
            after.st_ctime_ns,
        ) or len(payload) != before.st_size:
            fail("native conversion file changed during read")
        return payload
    finally:
        os.close(descriptor)


class NativeHwpConverter:
    """Verify one installed bundle per build; never accept executable paths from input."""

    def __init__(self, snapshot: CuratedHwpConverterSnapshot) -> None:
        root = _TOOL_ROOT / snapshot.bundle_sha256.removeprefix("sha256:")
        for parent in (*reversed(_TOOL_ROOT.parents[:-1]), _TOOL_ROOT, root):
            _protected_path(parent, directory=True)
        manifest = root / "manifest.json"
        _protected_path(manifest)
        value = parse_json_object(read_native_conversion_file(manifest, 16 * 1024))
        validate_contract("native-hwp-bundle", value)
        bundle = NativeHwpConverterBundle.model_validate(value)
        if (
            bundle.bundle_sha256 != snapshot.bundle_sha256
            or bundle.source_commit != snapshot.source_commit
        ):
            fail("native converter differs from the pinned bundle")
        _protected_path(_JAVA)
        if sha256_file(_JAVA) != bundle.java_sha256:
            fail("native converter Java binary differs")
        files = []
        for file in bundle.files:
            path = root / file.filename
            _protected_path(path)
            if (
                path.stat().st_size != file.size_bytes
                or sha256_bytes(read_native_conversion_file(path, 16 * 1024 * 1024)) != file.sha256
            ):
                fail("native converter installed file differs")
            files.append(str(path))
        self._classpath = os.pathsep.join(files)

    def convert(
        self, source: Path, output: Path, *, source_sha256: str
    ) -> HwpConversionPackageReceipt:
        """Read immutable staged HWP, compare source evidence, produce a fresh native HWPX."""
        candidate = output.with_suffix(".candidate.hwpx")
        evidence = output.with_suffix(".evidence.json")
        if (
            source.is_symlink()
            or not source.is_file()
            or any(path.exists() or path.is_symlink() for path in (output, candidate, evidence))
            or sha256_file(source) != source_sha256
        ):
            fail("native HWP input/output identity differs")
        result = subprocess.run(
            [
                str(_JAVA),
                "-Xmx384m",
                "-XX:ActiveProcessorCount=2",
                "-cp",
                self._classpath,
                "eom.hwpx.NativeHwpConverter",
                str(source),
                str(candidate),
                str(evidence),
            ],
            cwd=output.parent,
            env={"LANG": "C.UTF-8", "LC_ALL": "C.UTF-8", "PATH": "/usr/bin:/bin", "TZ": "UTC"},
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=90,
            check=False,
        )
        if result.returncode != 0 or sha256_file(source) != source_sha256:
            fail("native HWP converter failed or its source changed")
        verify_native_hwp_candidate(
            candidate,
            read_native_conversion_file(evidence, 16 * 1024 * 1024),
            source_sha256=source_sha256,
        )
        return normalize_hwp_conversion_package(candidate, output)
