"""Create the deterministic HWPX POC reference-template kit."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path

from PIL import Image, ImageDraw

KIT_ROOT = Path("/mnt/nas/eom/hwpx/poc-v0/reference-kit/v1")
REFERENCE_INBOX = Path("/mnt/nas/eom/hwpx/poc-v0/reference/inbox")
MANUAL_INBOX = Path("/mnt/nas/eom/hwpx/poc-v0/manual-validation/inbox")
MARKERS = (
    "{{EOM_DOCUMENT_TITLE}}",
    "{{EOM_ITEM_NUMBER}}",
    "{{EOM_UPPER_STEM}}",
    "{{EOM_LOWER_STEM}}",
    "{{EOM_POINTS}}",
    "{{EOM_TABLE_R1C1}}",
    "{{EOM_TABLE_R1C2}}",
    "{{EOM_TABLE_R1C3}}",
    "{{EOM_TABLE_R2C1}}",
    "{{EOM_TABLE_R2C2}}",
    "{{EOM_TABLE_R2C3}}",
    "{{EOM_STATEMENT_GIYEOK}}",
    "{{EOM_STATEMENT_NIEUN}}",
    "{{EOM_STATEMENT_DIGEUT}}",
    "{{EOM_CHOICE_1}}",
    "{{EOM_CHOICE_2}}",
    "{{EOM_CHOICE_3}}",
    "{{EOM_CHOICE_4}}",
    "{{EOM_CHOICE_5}}",
    "{{EOM_ANSWER}}",
    "{{EOM_AUTHORING_INTENT}}",
    "{{EOM_SOLUTION_OVERVIEW}}",
    "{{EOM_EXPLANATION_GIYEOK}}",
    "{{EOM_EXPLANATION_NIEUN}}",
    "{{EOM_EXPLANATION_DIGEUT}}",
    "{{EOM_EQUATION_ANCHOR}}",
    "EOM_EQ_PLACEHOLDER",
)


def sha256(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _image(path: Path, *, output: bool) -> None:
    image = Image.new("RGB", (800, 500), (245, 247, 250))
    draw = ImageDraw.Draw(image)
    if output:
        draw.rectangle((80, 70, 720, 430), fill=(28, 96, 140), outline=(15, 23, 42), width=8)
        draw.line((100, 400, 700, 100), fill=(240, 196, 25), width=20)
    else:
        draw.rectangle((80, 70, 720, 430), fill=(190, 204, 216), outline=(15, 23, 42), width=8)
        draw.ellipse((300, 150, 500, 350), fill=(214, 61, 57), outline=(15, 23, 42), width=8)
    image.save(path, format="PNG", optimize=False, compress_level=9)


def _example(output_hash: str) -> dict[str, object]:
    return {
        "schema_version": "1.0",
        "document_id": "placeholder-document-v1",
        "document_title": "PLACEHOLDER DOCUMENT",
        "item": {
            "item_number": "1",
            "upper_stem": "PLACEHOLDER UPPER STEM",
            "lower_stem": "PLACEHOLDER LOWER STEM",
            "table": {
                "rows": [
                    ["PLACEHOLDER R1C1", "PLACEHOLDER R1C2", "PLACEHOLDER R1C3"],
                    ["PLACEHOLDER R2C1", "PLACEHOLDER R2C2", "PLACEHOLDER R2C3"],
                ]
            },
            "image": {
                "source_path": "eom-placeholder-image-output.png",
                "media_type": "image/png",
                "sha256": output_hash,
                "expected_width_px": 800,
                "expected_height_px": 500,
            },
            "equation": {
                "source_format": "hancom-equation-script",
                "source": "x+y=z",
            },
            "statements": {
                "giyeok": "PLACEHOLDER STATEMENT GIYEOK",
                "nieun": "PLACEHOLDER STATEMENT NIEUN",
                "digeut": "PLACEHOLDER STATEMENT DIGEUT",
            },
            "choices": [f"PLACEHOLDER CHOICE {number}" for number in range(1, 6)],
            "points": "2",
        },
        "solution": {
            "answer": "1",
            "authoring_intent": "PLACEHOLDER AUTHORING INTENT",
            "overview": "PLACEHOLDER SOLUTION OVERVIEW",
            "statement_explanations": {
                "giyeok": "PLACEHOLDER EXPLANATION GIYEOK",
                "nieun": "PLACEHOLDER EXPLANATION NIEUN",
                "digeut": "PLACEHOLDER EXPLANATION DIGEUT",
            },
        },
    }


def create_kit(root: Path = KIT_ROOT) -> dict[str, str]:
    root.mkdir(mode=0o755, parents=True, exist_ok=True)
    REFERENCE_INBOX.mkdir(mode=0o755, parents=True, exist_ok=True)
    MANUAL_INBOX.mkdir(mode=0o755, parents=True, exist_ok=True)
    reference = root / "eom-placeholder-image-reference.png"
    output = root / "eom-placeholder-image-output.png"
    _image(reference, output=False)
    _image(output, output=True)
    (root / "reference-markers.txt").write_text("\n".join(MARKERS) + "\n", encoding="utf-8")
    (root / "reference-input.example.json").write_text(
        json.dumps(_example(sha256(output)), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    source = (
        Path(__file__).resolve().parents[2] / "docs/operations/HWPX_REFERENCE_TEMPLATE_CREATION.md"
    )
    (root / "REFERENCE_TEMPLATE_CREATION.md").write_text(
        source.read_text(encoding="utf-8"), encoding="utf-8"
    )
    for path in root.iterdir():
        if path.is_file():
            os.chmod(path, 0o644)
    return {"reference_sha256": sha256(reference), "output_sha256": sha256(output)}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=KIT_ROOT)
    args = parser.parse_args()
    result = create_kit(args.root)
    print(json.dumps({"created": True, "hashes_differ": len(set(result.values())) == 2}))


if __name__ == "__main__":
    main()
