"""Build the reviewed optional converter from checksum-pinned primary sources.

No production install, DB, credentials, native document parsing or worker launch.
Compilation disables annotation processing and executes no external build hooks.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import tarfile
import urllib.request
import zipfile
from pathlib import Path, PurePosixPath

from eom_hwpx_contracts.native_conversion import NativeHwpConverterBundle
from eom_hwpx_contracts.native_conversion_v2 import NativeHwpConverterBundleV2
from eom_hwpx_contracts.validation import validate_contract

COMMIT = "62d95b980a4e3a6766877dd3fb6f7f45f4afcf3d"
JAVA = Path("/usr/lib/jvm/java-21-openjdk-amd64/bin/java")
ARCHIVE = (
    f"https://codeload.github.com/neolord0/hwp2hwpx/tar.gz/{COMMIT}",
    "25c3314fb7e41e2a6b060bfccfbf6068babb66ab75ffc4f7559b4e52286cb18c",
)
DEPENDENCIES = {
    "hwplib-1.1.10.jar": (
        "https://repo.maven.apache.org/maven2/kr/dogfoot/hwplib/1.1.10/hwplib-1.1.10.jar",
        "fce557a7b4aff0c626c544558e0939459601a008d9378457b6183f7f3ae9d1b9",
    ),
    "hwpxlib-1.0.9.jar": (
        "https://repo.maven.apache.org/maven2/kr/dogfoot/hwpxlib/1.0.9/hwpxlib-1.0.9.jar",
        "c2461bde566d200770100b8572ae5e944e9d63bb92642d2840affb7cd88b8566",
    ),
}


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return "sha256:" + hashlib.file_digest(stream, "sha256").hexdigest()


def download(target: Path, url: str, expected: str, *, max_bytes: int = 16 * 1024 * 1024) -> None:
    with urllib.request.urlopen(url, timeout=40) as incoming, target.open("xb") as output:
        remaining = max_bytes
        while chunk := incoming.read(min(remaining + 1, 1024 * 1024)):
            remaining -= len(chunk)
            if remaining < 0:
                raise ValueError("converter dependency download exceeded bound")
            output.write(chunk)
    if digest(target) != "sha256:" + expected:
        raise ValueError("converter dependency checksum differs")


def build(
    output: Path, repository: Path, *, profile: str = "V1"
) -> NativeHwpConverterBundle | NativeHwpConverterBundleV2:
    if profile not in {"V1", "V2"}:
        raise ValueError("unsupported native converter build profile")
    if not output.is_absolute() or output.exists() or output.is_symlink():
        raise ValueError("converter build needs a fresh absolute output directory")
    output.mkdir(mode=0o700)
    workspace = output / "build"
    workspace.mkdir(mode=0o700)
    archive = workspace / "source.tar.gz"
    download(archive, *ARCHIVE, max_bytes=64 * 1024 * 1024)
    for name, (url, sha) in DEPENDENCIES.items():
        download(output / name, url, sha)
    prefix = f"hwp2hwpx-{COMMIT}"
    with tarfile.open(archive) as source:
        members = source.getmembers()
        if len(members) > 5000 or sum(member.size for member in members) > 50 * 1024 * 1024:
            raise ValueError("converter source archive exceeds bounds")
        if any(
            not (member.isfile() or member.isdir())
            or not PurePosixPath(member.name).parts
            or PurePosixPath(member.name).parts[0] != prefix
            or ".." in PurePosixPath(member.name).parts
            for member in members
        ):
            raise ValueError("converter source archive contains an unsafe member")
        source.extractall(workspace, filter="data")
    source_root = workspace / prefix
    sources = sorted((source_root / "src/main/java").rglob("*.java"))
    if not 1 <= len(sources) <= 1000 or any(path.is_symlink() for path in sources):
        raise ValueError("converter Java source set is invalid")
    classes = workspace / "classes"
    classes.mkdir(mode=0o700)
    adapter_root = repository / "services/hwpx_builder/native_hwp"
    adapters = tuple(
        adapter_root / name
        for name in (
            "NativeHwpConverter.java",
            "NativeHwpReaderV2.java",
            "NativeHwpConverterV2.java",
            "NativeHwpWriterV2.java",
        )
    )
    if any(not path.is_file() or path.is_symlink() for path in adapters):
        raise ValueError("native converter adapter source differs")
    classpath = ":".join(str(output / name) for name in DEPENDENCIES)
    completed = subprocess.run(
        [
            str(JAVA),
            "--add-modules",
            "jdk.compiler",
            "-cp",
            classpath,
            "com.sun.tools.javac.Main",
            "-proc:none",
            "-encoding",
            "UTF-8",
            "-d",
            str(classes),
            *(str(path) for path in adapters),
            *(str(path) for path in sources),
        ],
        capture_output=True,
        timeout=120,
        check=False,
        env={"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "TZ": "UTC"},
    )
    if completed.returncode:
        raise ValueError("converter compilation failed; no installed runtime changed")
    with zipfile.ZipFile(output / "converter.jar", "x") as jar:
        payloads = {
            path.relative_to(classes).as_posix(): path.read_bytes()
            for path in sorted(classes.rglob("*.class"))
        }
        payloads["META-INF/NOTICE.md"] = (
            repository / "services/hwpx_builder/native_hwp/NOTICE.md"
        ).read_bytes()
        payloads["META-INF/LICENSE-upstream.txt"] = (source_root / "license.txt").read_bytes()
        for name, data in sorted(payloads.items()):
            info = zipfile.ZipInfo(name, (1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            jar.writestr(info, data)
    value = {
        "schema_version": "native-hwp-converter-bundle/2.0"
        if profile == "V2"
        else "native-hwp-converter-bundle/1.0",
        "source_commit": COMMIT,
        "java_sha256": digest(JAVA),
        "files": [
            {
                "filename": name,
                "sha256": digest(output / name),
                "size_bytes": (output / name).stat().st_size,
            }
            for name in ("converter.jar", *DEPENDENCIES)
        ],
    }
    if profile == "V2":
        value.update(
            {
                "profile": "HWP2HWPX_NATIVE_V2",
                "entrypoint": "eom.hwpx.NativeHwpConverterV2",
                "adapter_source_sha256": "sha256:"
                + hashlib.sha256(
                    json.dumps(
                        [(path.name, digest(path)) for path in adapters],
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    ).encode()
                ).hexdigest(),
            }
        )
    value["bundle_sha256"] = (
        "sha256:"
        + hashlib.sha256(
            json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
    )
    validate_contract("native-hwp-bundle-v2" if profile == "V2" else "native-hwp-bundle", value)
    bundle = (
        NativeHwpConverterBundleV2.model_validate(value)
        if profile == "V2"
        else NativeHwpConverterBundle.model_validate(value)
    )
    with (output / "manifest.json").open("x", encoding="utf-8") as stream:
        stream.write(
            json.dumps(bundle.model_dump(mode="json"), ensure_ascii=False, sort_keys=True) + "\n"
        )
    # Keep source and compiler workspace as explicit build evidence, not runtime payload.
    return bundle


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--profile", choices=("V1", "V2"), default="V1")
    args = parser.parse_args()
    repository = Path(__file__).resolve().parents[2]
    bundle = build(args.output, repository, profile=args.profile)
    print(json.dumps({"status": "BUILT_NOT_INSTALLED", "bundle_sha256": bundle.bundle_sha256}))


if __name__ == "__main__":
    main()
