"""Build the pinned equation-compatible OXT without installing or downloading anything."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import subprocess
import tempfile
import zipfile
from pathlib import Path

BASE_SHA256 = "2b3ead8f1c782ba47cdc800262e99196850b525347843f0bd9b76e8431a7de96"
SOURCE_SHA256 = "0235fe114fc98f05a4ea1c2d5196364c517f7ec0574e4fafaa203775454d06de"
REPOSITORY = Path(__file__).resolve().parents[2]
PROVENANCE = REPOSITORY / "third_party/h2orestart/0.7.14-eom.2"
ZIP_TIME = (2026, 11, 6, 0, 0, 0)


def sha(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def repack(members: list[tuple[str, bytes, int]]) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name, payload, compression in members:
            info = zipfile.ZipInfo(name, ZIP_TIME)
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            info.compress_type = compression
            archive.writestr(info, payload, compresslevel=9)
    return output.getvalue()


def build(base: Path, upstream: Path, output: Path) -> Path:
    base_bytes = base.read_bytes()
    source_bytes = upstream.read_bytes()
    if sha(base_bytes) != BASE_SHA256 or sha(source_bytes) != SOURCE_SHA256:
        raise ValueError("H2ORESTART_BUILD_INPUT_HASH_MISMATCH")
    output.mkdir(mode=0o700, exist_ok=True)
    with zipfile.ZipFile(io.BytesIO(base_bytes)) as bundle:
        jar_bytes = bundle.read("H2Orestart.jar")
        outer = [
            (entry.filename, bundle.read(entry.filename), entry.compress_type)
            for entry in bundle.infolist()
        ]
    with tempfile.TemporaryDirectory(prefix="h2o-equation-build.", dir=output) as temporary:
        workspace = Path(temporary)
        source = workspace / "source/soffice/ConvEquation.java"
        source.parent.mkdir(parents=True)
        source.write_bytes(source_bytes)
        jar = workspace / "base.jar"
        jar.write_bytes(jar_bytes)
        subprocess.run(
            [
                "/usr/bin/git",
                "apply",
                "--unidiff-zero",
                "--ignore-space-change",
                "--ignore-whitespace",
                str(PROVENANCE / "ConvEquation-style-compatibility.patch"),
            ],
            cwd=workspace,
            check=True,
            capture_output=True,
        )
        classes = workspace / "classes"
        classes.mkdir()
        subprocess.run(
            [
                "/usr/bin/java",
                "-m",
                "jdk.compiler/com.sun.tools.javac.Main",
                "-source",
                "8",
                "-target",
                "8",
                "-encoding",
                "UTF-8",
                "-cp",
                str(jar) + ":/usr/share/java/libreoffice-24.2.7.jar",
                "-d",
                str(classes),
                str(source),
                str(PROVENANCE / "HancomEquationStyle.java"),
            ],
            check=True,
            capture_output=True,
        )
        with zipfile.ZipFile(io.BytesIO(jar_bytes)) as original:
            replacements = {
                "soffice/ConvEquation.class": (classes / "soffice/ConvEquation.class").read_bytes(),
                "soffice/HancomEquationStyle.class": (
                    classes / "soffice/HancomEquationStyle.class"
                ).read_bytes(),
            }
            inner = [
                (
                    entry.filename,
                    replacements.pop(entry.filename, original.read(entry.filename)),
                    entry.compress_type,
                )
                for entry in original.infolist()
            ]
            inner.extend(
                (name, payload, zipfile.ZIP_DEFLATED)
                for name, payload in sorted(replacements.items())
            )
        patched_jar = repack(inner)
    updated = []
    for name, payload, compression in outer:
        if name == "H2Orestart.jar":
            payload = patched_jar
        elif name == "description.xml":
            marker = b'<version value="0.7.14.1"/>'
            if payload.count(marker) != 1:
                raise ValueError("H2ORESTART_BUILD_VERSION_MISMATCH")
            payload = payload.replace(marker, b'<version value="0.7.14.2"/>')
        updated.append((name, payload, compression))
    result = repack(updated)
    target = output / "H2Orestart-0.7.14-eom.2.oxt"
    with target.open("xb") as stream:
        stream.write(result)
    report = {
        "base_sha256": BASE_SHA256,
        "upstream_equation_sha256": SOURCE_SHA256,
        "equation_patch_sha256": sha(
            (PROVENANCE / "ConvEquation-style-compatibility.patch").read_bytes()
        ),
        "equation_style_sha256": sha((PROVENANCE / "HancomEquationStyle.java").read_bytes()),
        "jar_sha256": sha(patched_jar),
        "bundle_sha256": sha(result),
        "bundle_bytes": len(result),
        "output": str(target),
    }
    (output / "build-manifest.json").write_text(json.dumps(report, sort_keys=True) + "\n")
    print(json.dumps(report, sort_keys=True))
    return target


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-bundle", type=Path, required=True)
    parser.add_argument("--upstream-equation-source", type=Path, required=True)
    parser.add_argument("--output-directory", type=Path, required=True)
    arguments = parser.parse_args()
    build(arguments.base_bundle, arguments.upstream_equation_source, arguments.output_directory)
