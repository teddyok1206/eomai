"""Build the blank, offline content-placement workbook; no database or service writes.

One file describes one content edition. Input values remain empty, including all
placement numbers. This is a reviewable template, not an activated import API.
Only Python's standard library is needed; XLSX bytes are generated outside Git.
"""

from __future__ import annotations

from io import BytesIO
from pathlib import Path
from xml.etree import ElementTree as ET
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PKG = "http://schemas.openxmlformats.org/package/2006/relationships"
ET.register_namespace("", NS)
ET.register_namespace("r", REL)
HEADERS = ("묶음", "회차·단원", "문항 번호", "고유번호 *", "배점", "메모")
INFO = (
    ("교재명 *", "시스템에서 사용할 교재·시험지 이름입니다."),
    ("종류 *", "목록에서 교재 / 모의고사 / 주간지 / 기타 중 선택합니다."),
    ("판 이름 *", "같은 교재의 판을 구분할 이름입니다. 연도는 아래에 따로 적습니다."),
    ("연도", "사용 학년도를 네 자리 숫자로 적습니다. 모르면 비워 둡니다."),
    ("인쇄 여부 *", "인쇄 완료 / 인쇄 전 / 확인 필요 중 선택합니다."),
    ("인쇄일", "인쇄 완료인 경우 아는 날짜만 YYYY-MM-DD 형식으로 적습니다."),
)
GUIDE = (
    (
        "작성 순서",
        "교재 정보를 한 번 적고, 문항 배치에 한 줄당 한 문항씩 입력하세요. *는 필수입니다.",
    ),
    (
        "한 파일의 범위",
        "교재 한 권의 한 판을 담습니다. 여러 회차·단원은 문항 배치 시트에서 나눕니다.",
    ),
    (
        "고유번호",
        "DB 문항의 숫자 다섯 자리입니다. 앞자리 0을 포함해 그대로 입력하세요. "
        "교재의 문제 번호와 다릅니다.",
    ),
    ("묶음", "회차·단원을 더 크게 묶을 때만 적습니다. 필요 없으면 비워 두세요."),
    (
        "회차·단원",
        "교재 안의 배치 구분 이름입니다. DB 문항의 소속 단원을 변경하지 않습니다. "
        "비우면 본문 구간입니다.",
    ),
    (
        "행 순서",
        "위에서 아래로 배치됩니다. 같은 묶음·회차의 행은 연속해서 작성하세요. "
        "묶음·회차는 각 행에 반복해서 적습니다.",
    ),
    (
        "빈칸의 의미",
        "빈 묶음은 묶음 없음, 빈 회차·단원은 본문입니다. 위 행의 값을 자동으로 물려받지 않습니다.",
    ),
    (
        "문항 번호",
        "교재에 인쇄된 문제 번호입니다. 비우면 구간마다 1부터 순서대로 붙입니다. "
        "전체 연속 번호가 필요하면 직접 적으세요.",
    ),
    ("중복 문항", "같은 고유번호를 여러 곳에 써도 됩니다. 각각의 사용 위치를 보존합니다."),
    (
        "배점·메모",
        "선택 항목입니다. 배점은 0~1,000점, 소수 셋째 자리까지입니다. "
        "페이지 등 참고사항은 메모에 적으세요.",
    ),
    (
        "인쇄 정보",
        "업로드 날짜를 인쇄일로 대신하지 않습니다. 인쇄 여부는 파일 전체 기준입니다. "
        "상태가 섞였다면 확인 필요를 선택하세요.",
    ),
    (
        "번호 연결 확인",
        "찾지 못한 번호나 연결 후보가 여러 개인 번호는 가져오기에서 확인해야 합니다. "
        "현재 DB 파일이 실제 과거 인쇄본과 같다는 뜻은 아닙니다.",
    ),
    (
        "입력 방법",
        "서식은 유지하고 값만 붙여넣어 주세요. 시트명·열 제목은 바꾸지 말고, "
        "병합셀·셀 수식·매크로·외부 연결은 넣지 마세요.",
    ),
    (
        "행 추가",
        "준비된 빈 행 아래에도 같은 형식으로 이어서 적을 수 있습니다. "
        "아무 내용 없는 행은 문항으로 세지 않습니다.",
    ),
    (
        "현재 범위",
        "이 파일은 입력 양식입니다. 업로드·DB 연결 기능은 별도 구현 단계이며, "
        "파일 작성만으로 등록되지는 않습니다.",
    ),
    ("양식 버전", "EOM 콘텐츠 배치 입력 양식 1.0"),
)


def node(parent: ET.Element, tag: str, **attributes: str) -> ET.Element:
    return ET.SubElement(parent, f"{{{NS}}}{tag}", attributes)


def cell(row: ET.Element, reference: str, text: str | None, style: int = 0) -> None:
    element = node(row, "c", r=reference, s=str(style))
    if text is not None:
        element.set("t", "inlineStr")
        node(node(element, "is"), "t").text = text


def sheet(widths: tuple[int, ...], *, freeze: bool = False) -> tuple[ET.Element, ET.Element]:
    root = ET.Element(f"{{{NS}}}worksheet")
    node(node(root, "sheetPr"), "pageSetUpPr", fitToPage="1")
    view = node(node(root, "sheetViews"), "sheetView", workbookViewId="0", showGridLines="0")
    if freeze:
        node(view, "pane", ySplit="1", topLeftCell="A2", activePane="bottomLeft", state="frozen")
    node(root, "sheetFormatPr", defaultRowHeight="27")
    columns = node(root, "cols")
    for number, width in enumerate(widths, 1):
        node(
            columns,
            "col",
            min=str(number),
            max=str(number),
            width=str(width),
            customWidth="1",
            style="2",
        )
    return root, node(root, "sheetData")


def validation(
    root: ET.Element,
    area: str,
    kind: str,
    formula: str,
    message: str,
    second: str | None = None,
    operator: str | None = None,
) -> None:
    validations = root.find(f"{{{NS}}}dataValidations")
    if validations is None:
        validations = node(root, "dataValidations", count="0")
    attributes = dict(
        type=kind,
        sqref=area,
        allowBlank="1",
        showInputMessage="1",
        showErrorMessage="1",
        errorStyle="stop",
        promptTitle="작성 안내",
        prompt=message,
        errorTitle="입력 내용을 확인해 주세요",
        error=message,
    )
    if operator:
        attributes["operator"] = operator
    if kind == "list":
        attributes["showDropDown"] = "0"
    entry = node(validations, "dataValidation", **attributes)
    node(entry, "formula1").text = formula
    if second is not None:
        node(entry, "formula2").text = second
    validations.set("count", str(len(validations)))


def finish(root: ET.Element, *, landscape: bool = False) -> None:
    node(
        root,
        "pageMargins",
        left="0.3",
        right="0.3",
        top="0.4",
        bottom="0.4",
        header="0.2",
        footer="0.2",
    )
    node(
        root,
        "pageSetup",
        paperSize="9",
        orientation="landscape" if landscape else "portrait",
        fitToWidth="1",
        fitToHeight="0",
    )


def info_sheet() -> ET.Element:
    root, data = sheet((23, 37, 73))
    header = node(data, "row", r="1", ht="32", customHeight="1")
    for column, value in zip("ABC", ("교재 정보", "입력란", "작성 방법"), strict=True):
        cell(header, f"{column}1", value, 1)
    for index, (label, hint) in enumerate(INFO, 2):
        row = node(data, "row", r=str(index), ht="46", customHeight="1")
        cell(row, f"A{index}", label, 3)
        cell(row, f"B{index}", None, 4 if index == 5 else 2)
        cell(row, f"C{index}", hint, 0)
    validation(root, "B3", "list", '"교재,모의고사,주간지,기타"', "목록에서 종류를 선택하세요.")
    validation(
        root,
        "B5",
        "whole",
        "1900",
        "연도는 1900~3000 사이의 네 자리 정수입니다.",
        "3000",
        "between",
    )
    validation(
        root, "B6", "list", '"인쇄 완료,인쇄 전,확인 필요"', "파일 전체의 인쇄 상태를 선택하세요."
    )
    # The input date keeps text format: no Excel date-system inference at import.
    finish(root, landscape=True)
    return root


def placement_sheet() -> ET.Element:
    root, data = sheet((24, 29, 16, 18, 13, 50), freeze=True)
    points_column = root.find(f"{{{NS}}}cols/{{{NS}}}col[@min='5']")
    assert points_column is not None
    points_column.set("style", "4")
    header = node(data, "row", r="1", ht="32", customHeight="1")
    for column, value in zip("ABCDEF", HEADERS, strict=True):
        cell(header, f"{column}1", value, 1)
    for index in range(2, 202):
        row = node(data, "row", r=str(index))
        for column in "ABCDEF":
            cell(row, f"{column}{index}", None, 4 if column == "E" else 2)
    node(root, "autoFilter", ref="A1:F201")
    validation(
        root,
        "D2:D1048576",
        "custom",
        'AND(ISTEXT(D2),LEN(D2)=5,IFERROR(AND(VALUE(D2)>=0,VALUE(D2)<=99999,TEXT(VALUE(D2),"00000")=D2),FALSE))',
        "DB 고유번호를 숫자 다섯 자리로 적으세요. 앞자리 0도 그대로 입력합니다.",
    )
    validation(
        root,
        "E2:E1048576",
        "custom",
        "AND(ISNUMBER(E2),E2>=0,E2<=1000,ROUND(E2,3)=E2)",
        "배점은 0~1000점, 소수 셋째 자리까지 입력하세요. 모르면 비워 두세요.",
    )
    finish(root, landscape=True)
    return root


def guide_sheet() -> ET.Element:
    root, data = sheet((22, 105))
    header = node(data, "row", r="1", ht="32", customHeight="1")
    cell(header, "A1", "작성 안내", 1)
    cell(header, "B1", "입력 칸은 교재 정보와 문항 배치 시트에 있습니다.", 1)
    for index, (label, text) in enumerate(GUIDE, 2):
        row = node(data, "row", r=str(index), ht="45", customHeight="1")
        cell(row, f"A{index}", label, 3)
        cell(row, f"B{index}", text, 0)
    finish(root, landscape=True)
    return root


def styles() -> str:
    return f'''<styleSheet xmlns="{NS}">
<fonts count="3"><font><sz val="11"/><name val="Noto Sans CJK KR"/><color rgb="FF1D1D1F"/></font>
<font><b/><sz val="12"/><name val="Noto Sans CJK KR"/><color rgb="FFFFFFFF"/></font>
<font><b/><sz val="11"/><name val="Noto Sans CJK KR"/><color rgb="FF3730A3"/></font></fonts>
<fills count="4"><fill><patternFill patternType="none"/></fill>
<fill><patternFill patternType="gray125"/></fill>
<fill><patternFill patternType="solid"><fgColor rgb="FF4F46E5"/>
<bgColor indexed="64"/></patternFill></fill>
<fill><patternFill patternType="solid"><fgColor rgb="FFEEF2FF"/>
<bgColor indexed="64"/></patternFill></fill></fills>
<borders count="2"><border><left/><right/><top/><bottom/><diagonal/></border>
<border><left/><right/><top/><bottom style="hair"><color rgb="FFD2D2D7"/></bottom>
<diagonal/></border></borders>
<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>
<cellXfs count="5">
<xf numFmtId="0" fontId="0" fillId="0" borderId="1" xfId="0" applyAlignment="1">
<alignment vertical="center" wrapText="1"/></xf>
<xf numFmtId="0" fontId="1" fillId="2" borderId="0" xfId="0" applyAlignment="1">
<alignment vertical="center" wrapText="1"/></xf>
<xf numFmtId="49" fontId="0" fillId="0" borderId="1" xfId="0"
 applyNumberFormat="1" applyAlignment="1"><alignment vertical="center" wrapText="1"/></xf>
<xf numFmtId="0" fontId="2" fillId="3" borderId="1" xfId="0" applyAlignment="1">
<alignment vertical="center" wrapText="1"/></xf>
<xf numFmtId="0" fontId="0" fillId="0" borderId="1" xfId="0" applyAlignment="1">
<alignment vertical="center" wrapText="1"/></xf>
</cellXfs><cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/>
</cellStyles></styleSheet>'''


def render_template() -> bytes:
    """Return the small static template, independent of repository or runtime state."""
    workbook = ET.Element(f"{{{NS}}}workbook")
    sheets = node(workbook, "sheets")
    names = ("교재 정보", "문항 배치", "작성 안내")
    for index, name in enumerate(names, 1):
        entry = node(sheets, "sheet", name=name, sheetId=str(index))
        entry.set(f"{{{REL}}}id", f"rId{index}")
    parts: dict[str, str | ET.Element] = {
        "xl/workbook.xml": workbook,
        "xl/styles.xml": styles(),
        "xl/worksheets/sheet1.xml": info_sheet(),
        "xl/worksheets/sheet2.xml": placement_sheet(),
        "xl/worksheets/sheet3.xml": guide_sheet(),
        "_rels/.rels": (
            f'<Relationships xmlns="{PKG}"><Relationship Id="rId1" '
            f'Type="{REL}/officeDocument" Target="xl/workbook.xml"/></Relationships>'
        ),
        "xl/_rels/workbook.xml.rels": f'<Relationships xmlns="{PKG}">'
        + "".join(
            f'<Relationship Id="rId{i}" Type="{REL}/worksheet" Target="worksheets/sheet{i}.xml"/>'
            for i in range(1, 4)
        )
        + f'<Relationship Id="rId4" Type="{REL}/styles" Target="styles.xml"/></Relationships>',
        "[Content_Types].xml": '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" '
        'ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/xl/workbook.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
        '<Override PartName="/xl/styles.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
        + "".join(
            f'<Override PartName="/xl/worksheets/sheet{i}.xml" '
            'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
            for i in range(1, 4)
        )
        + "</Types>",
    }
    output = BytesIO()
    with ZipFile(output, "w", compression=ZIP_DEFLATED) as archive:
        for name, part in parts.items():
            data = (
                part.encode("utf-8")
                if isinstance(part, str)
                else ET.tostring(part, encoding="utf-8")
            )
            ET.fromstring(data)
            member = ZipInfo(name, date_time=(2026, 11, 12, 0, 0, 0))
            member.compress_type = ZIP_DEFLATED
            archive.writestr(member, data)
    return output.getvalue()


def build_template(output: Path) -> None:
    """Create an exclusive template file; never overwrite a user's completed workbook."""
    with output.open("xb") as stream:
        stream.write(render_template())
