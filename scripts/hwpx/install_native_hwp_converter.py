"""Install only a verified optional native converter bundle; no runtime restart or DB write."""

from __future__ import annotations

import argparse
import os
import stat
from pathlib import Path

from eom_hwpx_builder.util import read_stable_local_file, sha256_bytes, sha256_file
from eom_hwpx_contracts.native_conversion import NativeHwpConverterBundle
from eom_hwpx_contracts.native_conversion_v2 import NativeHwpConverterBundleV2
from eom_hwpx_contracts.validation import parse_json_object, validate_contract

ROOT = Path("/srv/eom/vendor/hwp2hwpx")
JAVA = Path("/usr/lib/jvm/java-21-openjdk-amd64/bin/java")


def install(source: Path, expected_sha256: str) -> Path:
    if os.geteuid() != 0 or not source.is_absolute() or source.resolve(strict=True) != source:
        raise ValueError("installation requires root and an explicit regular source directory")
    payload = read_stable_local_file(source / "manifest.json", max_bytes=16 * 1024)
    value = parse_json_object(payload)
    bundle: NativeHwpConverterBundle | NativeHwpConverterBundleV2
    if value.get("schema_version") == "native-hwp-converter-bundle/2.0":
        validate_contract("native-hwp-bundle-v2", value)
        bundle = NativeHwpConverterBundleV2.model_validate(value)
    else:
        validate_contract("native-hwp-bundle", value)
        bundle = NativeHwpConverterBundle.model_validate(value)
    if bundle.bundle_sha256 != expected_sha256 or sha256_file(JAVA) != bundle.java_sha256:
        raise ValueError("installation bundle or Java identity differs")
    ROOT.mkdir(mode=0o755, exist_ok=True)
    for parent in (*reversed(ROOT.parents[:-1]), ROOT):
        metadata = parent.lstat()
        if not stat.S_ISDIR(metadata.st_mode) or metadata.st_uid != 0 or metadata.st_mode & 0o022:
            raise ValueError("installation parent is not protected")
    # The sudo shell intentionally uses umask 077. These public, reviewed JARs
    # must still be readable by the unprivileged Builder; they contain no secrets.
    ROOT.chmod(0o755)
    target = ROOT / expected_sha256.removeprefix("sha256:")
    payloads = {"manifest.json": payload}
    for file in bundle.files:
        data = read_stable_local_file(source / file.filename, max_bytes=16 * 1024 * 1024)
        if len(data) != file.size_bytes or sha256_bytes(data) != file.sha256:
            raise ValueError("installation source file differs")
        payloads[file.filename] = data
    if target.exists() or target.is_symlink():
        metadata = target.lstat()
        if not stat.S_ISDIR(metadata.st_mode) or metadata.st_uid != 0 or metadata.st_mode & 0o022:
            raise ValueError("installed destination is not protected")
        for name, data in payloads.items():
            path = target / name
            metadata = path.lstat()
            if (
                not stat.S_ISREG(metadata.st_mode)
                or metadata.st_uid != 0
                or metadata.st_mode & 0o022
                or read_stable_local_file(path, max_bytes=16 * 1024 * 1024) != data
            ):
                raise ValueError("existing installed bundle differs; never overwrite it")
            path.chmod(0o444)
        target.chmod(0o755)
        return target
    # An incomplete installation is never a published bundle identity. A fixed
    # private stage is retained on failure for diagnosis, rather than overwritten.
    stage = ROOT / (".install-" + expected_sha256.removeprefix("sha256:"))
    stage.mkdir(mode=0o700)
    for name, data in payloads.items():
        descriptor = os.open(
            stage / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o444
        )
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
            os.fchmod(stream.fileno(), 0o444)
    stage.chmod(0o755)
    stage.rename(target)
    return target


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--bundle-sha256", required=True)
    args = parser.parse_args()
    target = install(args.source, args.bundle_sha256)
    print(f"native_hwp_converter=INSTALLED bundle={target.name}")


if __name__ == "__main__":
    main()
