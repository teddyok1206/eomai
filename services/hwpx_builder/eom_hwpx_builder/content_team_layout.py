"""Project reviewed template-only furniture from canonical editorial semantics.

Single-item, exam and curated output share this boundary. The frozen handoff
keeps a literal question number and a statement box even when its marker values
are empty; neither is authored content. Only those exact native structures may
be removed. No source Item, equation, image or table content is rewritten.
"""

from __future__ import annotations

from lxml import etree  # type: ignore[import-untyped]

from eom_hwpx_builder.errors import HwpxError, HwpxErrorCode

HP = "{http://www.hancom.co.kr/hwpml/2011/paragraph}"
QUESTION_TABLE_ID = "1153727214"
STATEMENT_TABLE_ID = "1153727226"


def _fail(message: str) -> None:
    raise HwpxError(HwpxErrorCode.HWPX_STRUCTURAL_VALIDATION_FAILED, message)


def _stem_paragraph(root: etree._Element) -> etree._Element:
    tables = [table for table in root.iter(HP + "tbl") if table.get("id") == QUESTION_TABLE_ID]
    if len(tables) != 1:
        _fail("content-team question layout table is ambiguous")
    bodies = [
        body
        for row in tables[0].findall(HP + "tr")
        for cell in row.findall(HP + "tc")
        for body in cell.findall(HP + "subList")
    ]
    if len(bodies) != 1:
        _fail("content-team question layout body is ambiguous")
    paragraphs = bodies[0].findall(HP + "p")
    # Table-only layouts clone the stem's style for a later native table host.
    # The reviewed outer body owns one first paragraph; style alone is not identity.
    if (
        not paragraphs
        or paragraphs[0].get("paraPrIDRef") != "47"
        or paragraphs[0].get("styleIDRef") != "25"
    ):
        _fail("content-team question stem paragraph is ambiguous")
    return paragraphs[0]


def assert_content_team_numbering(root: etree._Element, *, item_number: int) -> None:
    """The shared renderer, not a downstream assembly, owns question numbering."""

    paragraph = _stem_paragraph(root)
    runs = paragraph.findall(HP + "run")
    first_text = None if not runs else runs[0].find(HP + "t")
    if (
        first_text is None
        or not (first_text.text or "").startswith(f"{item_number}. ")
        or runs[0].get("charPrIDRef") == "30"
    ):
        _fail("content-team question number differs from its exact placement")


def _empty_statement_host(root: etree._Element) -> etree._Element:
    tables = [table for table in root.iter(HP + "tbl") if table.get("id") == STATEMENT_TABLE_ID]
    if len(tables) != 1:
        _fail("content-team empty statement template is ambiguous")
    table = tables[0]
    text = "".join("".join(node.itertext()) for node in table.iter(HP + "t"))
    if (
        table.get("rowCnt") != "3"
        or table.get("colCnt") != "3"
        or "".join(text.split()) != "<보기>ㄱ.ㄴ.ㄷ."
        or any(
            node.tag in {HP + "pic", HP + "equation", HP + "ole", HP + "container"}
            or (node is not table and node.tag == HP + "tbl")
            for node in table.iter()
        )
    ):
        _fail("content-team empty statement template contains unexpected content")
    run = table.getparent()
    paragraph = None if run is None else run.getparent()
    if (
        run is None
        or paragraph is None
        or run.tag != HP + "run"
        or paragraph.tag != HP + "p"
        or paragraph.getparent() is None
        or paragraph.getparent().tag != HP + "subList"
        or tuple(node.tag for node in paragraph)
        not in (
            (HP + "run",),
            (HP + "run", HP + "linesegarray"),
        )
        or tuple(node.tag for node in run) != (HP + "tbl", HP + "t")
        or "".join(run[1].itertext()).strip()
    ):
        _fail("content-team empty statement host contains unexpected content")
    return paragraph


def project_content_team_template_layout(
    root: etree._Element, *, item_number: int, has_statements: bool
) -> None:
    """Remove exact template remnants after handoff validation, before publication."""

    paragraph = _stem_paragraph(root)
    runs = paragraph.findall(HP + "run")
    if (
        len(runs) < 2
        or runs[0].get("charPrIDRef") != "30"
        or tuple(node.tag for node in runs[0]) != (HP + "t",)
        or runs[0][0].text != "1. "
        or len(runs[0][0])
        or runs[1].find(HP + "t") is None
        or not (runs[1].find(HP + "t").text or "").startswith(f"{item_number}. ")
    ):
        _fail("content-team template number prefix differs from the reviewed layout")
    # Validate both changes before touching XML, so an unsafe statement box leaves
    # the caller's in-memory document unchanged as well as its canonical input.
    statement_host = None if has_statements else _empty_statement_host(root)
    paragraph.remove(runs[0])
    for cache in tuple(paragraph.findall(HP + "linesegarray")):
        paragraph.remove(cache)
    if statement_host is not None:
        statement_host.getparent().remove(statement_host)
    assert_content_team_numbering(root, item_number=item_number)
