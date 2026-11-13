"""Fixed, hash-pinned optional Java adapter inside the existing Builder sandbox."""

from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path

from eom_hwpx_contracts.curated_document import CuratedHwpConverterSnapshot
from eom_hwpx_contracts.native_conversion import NativeHwpConverterBundle
from eom_hwpx_contracts.native_conversion_v2 import (
    NativeHwpConversionEvidenceV2,
    NativeHwpConverterBundleV2,
    NativeHwpConverterSnapshotV2,
    NativeHwpNormalizationReceiptV2,
    NativeHwpQualifiedConversionReceiptV2,
)
from eom_hwpx_contracts.validation import parse_json_object, validate_contract

from eom_hwpx_builder.curated_resources import fail
from eom_hwpx_builder.hwp_conversion_package import (
    HwpConversionPackageReceipt,
    normalize_hwp_conversion_package,
)
from eom_hwpx_builder.native_hwp_preservation import verify_native_hwp_candidate
from eom_hwpx_builder.native_hwp_preservation_v2 import verify_native_hwp_candidate_v2
from eom_hwpx_builder.util import read_stable_local_file, sha256_bytes, sha256_file

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


class NativeHwpConverter:
    """Verify one installed bundle per build; never accept executable paths from input."""

    _profile = "V1"

    def __init__(
        self, snapshot: CuratedHwpConverterSnapshot | NativeHwpConverterSnapshotV2
    ) -> None:
        self._snapshot = snapshot
        root = _TOOL_ROOT / snapshot.bundle_sha256.removeprefix("sha256:")
        for parent in (*reversed(_TOOL_ROOT.parents[:-1]), _TOOL_ROOT, root):
            _protected_path(parent, directory=True)
        manifest = root / "manifest.json"
        _protected_path(manifest)
        value = parse_json_object(read_stable_local_file(manifest, max_bytes=16 * 1024))
        bundle: NativeHwpConverterBundle | NativeHwpConverterBundleV2
        if isinstance(snapshot, NativeHwpConverterSnapshotV2):
            validate_contract("native-hwp-bundle-v2", value)
            bundle = NativeHwpConverterBundleV2.model_validate(value)
            self._profile = "V2"
        else:
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
                or sha256_bytes(read_stable_local_file(path, max_bytes=16 * 1024 * 1024))
                != file.sha256
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
                "eom.hwpx.NativeHwpConverterV2"
                if self._profile == "V2"
                else "eom.hwpx.NativeHwpConverter",
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
        payload = read_stable_local_file(evidence, max_bytes=16 * 1024 * 1024)
        if self._profile == "V2":
            verify_native_hwp_candidate_v2(candidate, payload, source_sha256=source_sha256)
        else:
            verify_native_hwp_candidate(candidate, payload, source_sha256=source_sha256)
        return normalize_hwp_conversion_package(candidate, output)

    def convert_qualified(
        self, source: Path, output: Path, *, source_sha256: str
    ) -> NativeHwpQualifiedConversionReceiptV2:
        """V2-only proof packaging; the native conversion runs exactly once."""
        if not isinstance(self._snapshot, NativeHwpConverterSnapshotV2):
            fail("qualified conversion requires the explicit V2 snapshot")
        normalization = self.convert(source, output, source_sha256=source_sha256)
        evidence = NativeHwpConversionEvidenceV2.model_validate_json(
            read_stable_local_file(output.with_suffix(".evidence.json"), max_bytes=16 * 1024 * 1024)
        )
        if (
            evidence.source_sha256 != source_sha256
            or sha256_file(output) != normalization.output_sha256
        ):
            fail("qualified native conversion source/output identity differs")
        return NativeHwpQualifiedConversionReceiptV2(
            snapshot=self._snapshot,
            evidence=evidence,
            normalization=NativeHwpNormalizationReceiptV2(
                candidate_sha256=normalization.candidate_sha256,
                output_sha256=normalization.output_sha256,
                empty_style_attribute_count=normalization.empty_style_attribute_count,
                expanded_size_attribute_count=normalization.expanded_size_attribute_count,
                rebuilt_intent_box_count=normalization.rebuilt_intent_box_count,
            ),
        )
