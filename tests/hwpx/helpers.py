from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path
from typing import Any

from eom_hwpx_builder.bindings import TEXT_MARKERS
from eom_hwpx_builder.util import sha256_bytes
from PIL import Image, ImageDraw

HP = "http://www.hancom.co.kr/hwpml/2011/paragraph"
OPF = "http://www.idpf.org/2007/opf"
CONTAINER = "urn:oasis:names:tc:opendocument:xmlns:container"


def png_bytes(*, output: bool = False, dimensions: tuple[int, int] = (800, 500)) -> bytes:
    image = Image.new("RGB", dimensions, (240, 244, 248))
    draw = ImageDraw.Draw(image)
    if output:
        draw.rectangle((40, 40, dimensions[0] - 40, dimensions[1] - 40), fill=(20, 100, 150))
        draw.line((80, dimensions[1] - 80, dimensions[0] - 80, 80), fill=(240, 190, 20), width=16)
    else:
        draw.rectangle((40, 40, dimensions[0] - 40, dimensions[1] - 40), fill=(190, 205, 215))
        draw.ellipse((300, 150, 500, 350), fill=(210, 60, 55))
    output_stream = io.BytesIO()
    image.save(output_stream, format="PNG", optimize=False, compress_level=9)
    return output_stream.getvalue()


def document(image: bytes | None = None) -> dict[str, Any]:
    output = image or png_bytes(output=True)
    return {
        "schema_version": "1.0",
        "document_id": "placeholder-document-v1",
        "document_title": "PLACEHOLDER DOCUMENT",
        "item": {
            "item_number": "1",
            "upper_stem": "PLACEHOLDER UPPER STEM 한글 & <XML>",
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
                "sha256": sha256_bytes(output),
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


def _paragraph(marker: str, identifier: int, *, split: bool = False) -> str:
    if split:
        midpoint = len(marker) // 2
        runs = (
            f'<hp:run charPrIDRef="0"><hp:t>{marker[:midpoint]}</hp:t></hp:run>'
            f'<hp:run charPrIDRef="1"><hp:t>{marker[midpoint:]}</hp:t></hp:run>'
        )
    else:
        runs = f'<hp:run charPrIDRef="0"><hp:t>{marker}</hp:t></hp:run>'
    return f'<hp:p id="p{identifier}">{runs}</hp:p>'


def synthetic_parts(
    *,
    split_marker: bool = True,
    equation_anchor: bool = False,
    reference_image: bytes | None = None,
) -> list[tuple[str, bytes, int]]:
    image = reference_image or png_bytes()
    paragraphs = []
    non_table_markers = {
        field: marker
        for field, marker in TEXT_MARKERS.items()
        if not field.startswith("item.table.")
    }
    for index, marker in enumerate(non_table_markers.values()):
        paragraphs.append(
            _paragraph(marker, index, split=split_marker and marker == "{{EOM_UPPER_STEM}}")
        )
    if equation_anchor:
        paragraphs.append(_paragraph("{{EOM_EQUATION_ANCHOR}}", 100))
        equation = '<hp:equation id="eq1" script="x+y=z"/>'
    else:
        equation = '<hp:equation id="eq1" script="EOM_EQ_PLACEHOLDER"/>'
    positions = ((0, 0), (0, 1), (0, 2), (1, 0), (1, 1), (1, 2))
    table_cells = "".join(
        (
            f'<hp:tc id="cell{index}">'
            f"{_paragraph(TEXT_MARKERS[f'item.table.rows.{row}.{column}'], 200 + index)}"
            "</hp:tc>"
        )
        for index, (row, column) in enumerate(positions)
    )
    section = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<hp:section xmlns:hp="{HP}">'
        + "".join(paragraphs)
        + f'<hp:tbl id="table1" rows="2" cols="3">{table_cells}</hp:tbl>'
        + '<hp:pic id="pic1" binaryItemIDRef="image1"/>'
        + equation
        + "</hp:section>"
    ).encode()
    content = f'''<?xml version="1.0" encoding="UTF-8"?>
<opf:package xmlns:opf="{OPF}">
  <opf:metadata>
    <opf:title>SYNTHETIC PLACEHOLDER TEMPLATE</opf:title>
    <opf:meta name="eom-build-id" content="template"/>
  </opf:metadata>
  <opf:manifest>
    <opf:item id="header" href="header.xml" media-type="application/xml"/>
    <opf:item id="section0" href="section0.xml" media-type="application/xml"/>
    <opf:item id="image1" href="../BinData/image1.png" media-type="image/png"/>
  </opf:manifest>
  <opf:spine><opf:itemref idref="section0"/></opf:spine>
</opf:package>'''.encode()
    return [
        ("mimetype", b"application/hwp+zip", zipfile.ZIP_STORED),
        (
            "version.xml",
            (
                b'<?xml version="1.0" encoding="UTF-8"?>'
                b'<version xmlns="urn:synthetic:version" owpml="synthetic-poc"/>'
            ),
            zipfile.ZIP_DEFLATED,
        ),
        (
            "settings.xml",
            b'<?xml version="1.0" encoding="UTF-8"?><settings xmlns="urn:synthetic:settings"/>',
            zipfile.ZIP_DEFLATED,
        ),
        (
            "META-INF/container.xml",
            (
                '<?xml version="1.0" encoding="UTF-8"?>'
                f'<container xmlns="{CONTAINER}"><rootfiles>'
                '<rootfile full-path="Contents/content.hpf"/>'
                "</rootfiles></container>"
            ).encode(),
            zipfile.ZIP_DEFLATED,
        ),
        ("Contents/content.hpf", content, zipfile.ZIP_DEFLATED),
        (
            "Contents/header.xml",
            (
                b'<?xml version="1.0" encoding="UTF-8"?>'
                b'<header xmlns="urn:synthetic:header"><styles/></header>'
            ),
            zipfile.ZIP_DEFLATED,
        ),
        ("Contents/section0.xml", section, zipfile.ZIP_DEFLATED),
        ("BinData/image1.png", image, zipfile.ZIP_DEFLATED),
        ("Preview/PrvText.txt", b"SYNTHETIC PREVIEW", zipfile.ZIP_DEFLATED),
        ("Extra/unknown.dat", b"SYNTHETIC UNKNOWN PART", zipfile.ZIP_STORED),
    ]


def write_hwpx(path: Path, parts: list[tuple[str, bytes, int]] | None = None) -> Path:
    with zipfile.ZipFile(path, "w") as archive:
        for name, data, compression in parts or synthetic_parts():
            info = zipfile.ZipInfo(name, (1980, 1, 1, 0, 0, 0))
            info.compress_type = compression
            archive.writestr(info, data)
    return path


def prepare_workspace(root: Path, *, equation_anchor: bool = False) -> tuple[Path, bytes]:
    root.mkdir()
    (root / "input").mkdir()
    output_image = png_bytes(output=True)
    reference_image = png_bytes(output=False)
    template = write_hwpx(
        root / "template.hwpx",
        synthetic_parts(equation_anchor=equation_anchor, reference_image=reference_image),
    )
    from eom_hwpx_builder.bindings import compile_bindings
    from eom_hwpx_builder.util import sha256_file

    bindings = compile_bindings(
        template,
        template_id="hwpxtpl_" + "a" * 32,
        template_revision_id="hwpxrev_" + "b" * 32,
        reference_image_sha256=sha256_bytes(reference_image),
    )
    (root / "template-bindings.json").write_text(bindings.model_dump_json(indent=2))
    (root / "input/document.json").write_text(
        json.dumps(document(output_image), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (root / "input/eom-placeholder-image-output.png").write_bytes(output_image)
    request = {
        "request_version": "1.0",
        "build_id": "hwpxbuild_" + "c" * 32,
        "template_id": bindings.template_id,
        "template_revision_id": bindings.template_revision_id,
        "template_sha256": sha256_file(template),
        "template_file": "template.hwpx",
        "bindings_file": "template-bindings.json",
        "document_file": "input/document.json",
        "image_file": "input/eom-placeholder-image-output.png",
        "output_directory": "output",
    }
    request_path = root / "request.json"
    request_path.write_text(json.dumps(request), encoding="utf-8")
    return request_path, output_image
