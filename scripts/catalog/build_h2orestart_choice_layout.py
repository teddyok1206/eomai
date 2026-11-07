"""Build the bounded choice-cell fix on top of the exact equation-compatible OXT."""

from __future__ import annotations

import argparse
import io
import json
import subprocess
import tempfile
import zipfile
from pathlib import Path

from scripts.catalog.build_h2orestart_equations import repack, sha

BASE_SHA256 = "50d8cf433f12270b5ee44fa974993bc36b5804ef550f0ce09b39266305b1b2cb"
SOURCE_SHA256 = "f02c6603f1b4e551e77601f2eb842546077cd156e1a26cbaa8d25d373478756d"
PROVENANCE = Path(__file__).resolve().parents[2] / "third_party/h2orestart/0.7.14-eom.3"


def build(base: Path, upstream: Path, output: Path) -> Path:
    base_bytes, source_bytes = base.read_bytes(), upstream.read_bytes()
    if sha(base_bytes) != BASE_SHA256 or sha(source_bytes) != SOURCE_SHA256:
        raise ValueError("H2ORESTART_BUILD_INPUT_HASH_MISMATCH")
    output.mkdir(mode=0o700, exist_ok=False)
    with zipfile.ZipFile(io.BytesIO(base_bytes)) as bundle:
        outer = [(i.filename, bundle.read(i.filename), i.compress_type) for i in bundle.infolist()]
        jar_bytes = bundle.read("H2Orestart.jar")
    with tempfile.TemporaryDirectory(prefix="choice-cell-", dir=output) as temporary:
        workspace = Path(temporary)
        source = workspace / "source/soffice/ConvTable.java"
        source.parent.mkdir(parents=True)
        source.write_bytes(source_bytes)
        jar = workspace / "base.jar"
        jar.write_bytes(jar_bytes)
        subprocess.run(
            [
                "git",
                "apply",
                "--unidiff-zero",
                "--ignore-space-change",
                "--ignore-whitespace",
                str(PROVENANCE / "ConvTable-choice-cell-compatibility.patch"),
            ],
            cwd=workspace,
            check=True,
            capture_output=True,
            timeout=30,
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
                str(PROVENANCE / "HancomChoiceCellLayout.java"),
            ],
            check=True,
            capture_output=True,
            timeout=60,
        )
        replacements = {
            p.relative_to(classes).as_posix(): p.read_bytes()
            for p in sorted(classes.rglob("*.class"))
        }
        assert {
            "soffice/ConvTable.class",
            "soffice/HancomChoiceCellLayout.class",
        } <= replacements.keys()
        assert len(replacements) <= 8 and all(
            p.startswith(("soffice/ConvTable", "soffice/HancomChoiceCellLayout"))
            and b[:8] == b"\xca\xfe\xba\xbe\0\0\x004"
            for p, b in replacements.items()
        )
        with zipfile.ZipFile(io.BytesIO(jar_bytes)) as original:
            inner = [
                (
                    i.filename,
                    replacements.pop(i.filename, original.read(i.filename)),
                    i.compress_type,
                )
                for i in original.infolist()
            ]
            inner.extend((n, p, zipfile.ZIP_DEFLATED) for n, p in sorted(replacements.items()))
        patched_jar = repack(inner)
    updated = []
    for name, payload, compression in outer:
        if name == "H2Orestart.jar":
            payload = patched_jar
        elif name == "description.xml":
            marker = b'<version value="0.7.14.2"/>'
            if payload.count(marker) != 1:
                raise ValueError("H2ORESTART_BUILD_VERSION_MISMATCH")
            payload = payload.replace(marker, b'<version value="0.7.14.3"/>')
        updated.append((name, payload, compression))
    result = repack(updated)
    target = output / "H2Orestart-0.7.14-eom.3.oxt"
    with target.open("xb") as stream:
        stream.write(result)
    report = {
        "base_sha256": BASE_SHA256,
        "upstream_table_sha256": SOURCE_SHA256,
        "bundle_sha256": sha(result),
        "bundle_bytes": len(result),
        "jar_sha256": sha(patched_jar),
        "output": str(target),
    }
    (output / "build-manifest.json").write_text(json.dumps(report, sort_keys=True) + "\n")
    print(json.dumps(report, sort_keys=True))
    return target


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-bundle", type=Path, required=True)
    parser.add_argument("--upstream-table-source", type=Path, required=True)
    parser.add_argument("--output-directory", type=Path, required=True)
    args = parser.parse_args()
    build(args.base_bundle, args.upstream_table_source, args.output_directory)
