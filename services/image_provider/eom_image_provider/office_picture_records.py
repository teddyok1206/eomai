"""Bounded, read-only HWP5 native record decoding (Hancom format tables 17/83/107).

No inference of a physical page, reference region, or member name from its use ID.
Unsupported grouped drawings remain explicit instead of silently dropping labels.
"""

from __future__ import annotations

import hashlib
import io
import math
import re
import struct
from collections.abc import Iterator, Mapping
from dataclasses import dataclass

from eom_image_contracts.office_picture_uses import (
    OfficeNativeObject,
    OfficeNativeObjectKind,
    OfficeObjectLocator,
    OfficePictureGeometry,
    OfficePicturePlacement,
    OfficePictureUse,
    UnresolvedPictureReason,
    office_object_id,
)

from eom_image_provider.office_embedded_images import OfficeEmbeddedImageError, _inflate

_MAX_STREAM = 64 * 1024 * 1024
_MAX_TOTAL = 128 * 1024 * 1024
_MAX_RECORDS = 100000
_DRAWING_TAGS = frozenset(range(78, 84))


def _sha(raw: bytes) -> str:
    return "sha256:" + hashlib.sha256(raw).hexdigest()


@dataclass(frozen=True, slots=True)
class HwpRecord:
    ordinal: int
    tag: int
    level: int
    body: bytes


def hwp_records(raw: bytes) -> Iterator[HwpRecord]:
    cursor = 0
    ordinal = 0
    while cursor < len(raw):
        if cursor + 4 > len(raw) or ordinal >= _MAX_RECORDS:
            raise OfficeEmbeddedImageError("OFFICE_PICTURE_RECORD_INVALID")
        header = struct.unpack_from("<I", raw, cursor)[0]
        cursor += 4
        size = header >> 20
        if size == 4095:
            if cursor + 4 > len(raw):
                raise OfficeEmbeddedImageError("OFFICE_PICTURE_RECORD_INVALID")
            size = struct.unpack_from("<I", raw, cursor)[0]
            cursor += 4
        if cursor + size > len(raw):
            raise OfficeEmbeddedImageError("OFFICE_PICTURE_RECORD_INVALID")
        yield HwpRecord(ordinal, header & 1023, (header >> 10) & 1023, raw[cursor : cursor + size])
        cursor += size
        ordinal += 1


def hwp_binary_bindings(raw: bytes, members: Mapping[str, str]) -> tuple[str | None, ...]:
    """Picture BinData index addresses DocInfo order, NOT BIN<index> storage."""
    bindings: list[str | None] = []
    for record in hwp_records(raw):
        if record.tag != 18:
            continue
        if len(record.body) < 2 or len(bindings) >= 2048:
            raise OfficeEmbeddedImageError("OFFICE_PICTURE_BINDING_INVALID")
        kind = struct.unpack_from("<H", record.body)[0] & 15
        if kind == 0:
            # A linked filename is never read, resolved or returned as a path.
            bindings.append(None)
            continue
        if kind not in {1, 2} or len(record.body) < 6:
            raise OfficeEmbeddedImageError("OFFICE_PICTURE_BINDING_INVALID")
        storage, length = struct.unpack_from("<HH", record.body, 2)
        if not 0 < length <= 12 or 6 + 2 * length > len(record.body):
            raise OfficeEmbeddedImageError("OFFICE_PICTURE_BINDING_INVALID")
        try:
            extension = record.body[6 : 6 + 2 * length].decode("utf-16-le").lower()
        except UnicodeError as exc:
            raise OfficeEmbeddedImageError("OFFICE_PICTURE_BINDING_INVALID") from exc
        if re.fullmatch(r"[a-z0-9]{1,12}", extension) is None:
            raise OfficeEmbeddedImageError("OFFICE_PICTURE_BINDING_INVALID")
        key = f"bindata/bin{storage:04x}.{extension}"
        # Missing embedded storage is not an external link. Retain its exact
        # expected member so the catalog reports MISSING_IMAGE, not EXTERNAL.
        bindings.append(members.get(key, f"BinData/BIN{storage:04X}.{extension}"))
    return tuple(bindings)


def _shape_geometry(shape: bytes, picture: bytes) -> OfficePictureGeometry | None:
    # General shapes repeat the control ID; child shapes contain it once.
    if len(shape) < 4 or shape[:4] != b"cip$":
        return None
    offset = 8 if shape[4:8] == b"cip$" else 4
    if len(shape) < offset + 92 or len(picture) < 73:
        return None
    initial_width, initial_height, current_width, current_height, flags = struct.unpack_from(
        "<5I", shape, offset + 12
    )
    # High editing/reserved bits are present in ordinary Hancom originals.
    # Only the specified flip bits affect this view; the actual linear
    # rendering matrices below independently reject unsupported transforms.
    angle = struct.unpack_from("<H", shape, offset + 32)[0]
    count = struct.unpack_from("<H", shape, offset + 42)[0]
    if (
        not 0 < initial_width <= 1_000_000_000
        or not 0 < initial_height <= 1_000_000_000
        or not 0 < current_width <= 1_000_000_000
        or not 0 < current_height <= 1_000_000_000
        or angle % 90
        or not 1 <= count <= 32
        or offset + 92 + count * 96 > len(shape)
    ):
        return None
    matrices = struct.unpack_from("<" + "d" * (6 + count * 12), shape, offset + 44)
    if not all(math.isfinite(value) and abs(value) <= 1_000_000_000 for value in matrices):
        return None
    if any(
        abs(matrices[index] - value) > 1e-7 for index, value in ((0, 1), (1, 0), (3, 0), (4, 1))
    ):
        return None
    # Off-diagonal scale/shear or arbitrary rotations cannot be replaced by a
    # guessed quarter turn. Admit only diagonal scaling and orthogonal rotation.
    if count != 1:
        return None
    for index in range(count):
        scale = matrices[6 + index * 12 : 12 + index * 12]
        rotate = matrices[12 + index * 12 : 18 + index * 12]
        if abs(scale[1]) > 1e-7 or abs(scale[3]) > 1e-7 or scale[0] <= 0 or scale[4] <= 0:
            return None
        if _rotation_quarter_turn(rotate) != (angle // 90) % 4:
            return None
    points = struct.unpack_from("<8i", picture, 12)
    rectangle_width, rectangle_height = points[2], points[5]
    if points != (0, 0, rectangle_width, 0, rectangle_width, rectangle_height, 0, rectangle_height):
        return None
    # Hancom revision 1.3 table 116: reference image dimensions follow the
    # effects record. They are NOT the edited picture rectangle (table 107).
    # With unknown effects/version tails, do not guess an original extent.
    if len(picture) == 91 and struct.unpack_from("<I", picture, 78)[0] == 0:
        width, height = struct.unpack_from("<2I", picture, 82)
    elif len(picture) == 78:
        width, height = rectangle_width, rectangle_height
    else:
        return None
    if width <= 0 or height <= 0:
        return None
    viewport = struct.unpack_from("<4i", picture, 44)
    if viewport == (0, 0, 0, 0):
        viewport = (0, 0, width, height)
    try:
        return OfficePictureGeometry(
            original_extent=(width, height),
            viewport=viewport,
            clockwise_quarter_turns=(angle // 90) % 4,
            flip_horizontal=bool(flags & 1),
            flip_vertical=bool(flags & 2),
        )
    except ValueError:
        return None


def _rotation_quarter_turn(matrix: tuple[float, ...]) -> int | None:
    a, b, _x, c, d, _y = matrix
    for turns, values in enumerate(((1, 0, 0, 1), (0, -1, 1, 0), (-1, 0, 0, -1), (0, 1, -1, 0))):
        if all(
            abs(observed - expected) < 1e-7
            for observed, expected in zip((a, b, c, d), values, strict=True)
        ):
            return turns
    return None


def _section_objects(
    raw: bytes, *, member: str, source_sha256: str, bindings: tuple[str | None, ...]
) -> tuple[list[OfficePictureUse], list[OfficeNativeObject]]:
    stack: list[HwpRecord] = []
    shapes: list[HwpRecord] = []
    groups: list[HwpRecord] = []
    controls: list[HwpRecord] = []
    paragraphs: list[HwpRecord] = []
    uses: list[OfficePictureUse] = []
    objects: list[OfficeNativeObject] = []
    for record in hwp_records(raw):
        while stack and stack[-1].level >= record.level:
            previous = stack.pop()
            if previous.tag == 71:
                controls.pop()
            elif previous.tag == 66:
                paragraphs.pop()
            if previous.tag == 76:
                shapes.pop()
                if b"noc$" in previous.body[:8]:
                    groups.pop()
        locator = OfficeObjectLocator(member_path=member, ordinal=record.ordinal)
        group = groups[-1] if groups else None
        group_id = (
            None
            if group is None
            else office_object_id(
                source_sha256, OfficeObjectLocator(member_path=member, ordinal=group.ordinal)
            )
        )
        if record.tag == 85:
            if len(record.body) < 73:
                raise OfficeEmbeddedImageError("OFFICE_PICTURE_RECORD_INVALID")
            binding = struct.unpack_from("<H", record.body, 71)[0]
            if not 1 <= binding <= len(bindings):
                raise OfficeEmbeddedImageError("OFFICE_PICTURE_BINDING_INVALID")
            source_member = bindings[binding - 1]
            shape = shapes[-1] if shapes else None
            geometry = None if shape is None else _shape_geometry(shape.body, record.body)
            reasons: list[UnresolvedPictureReason] = []
            if source_member is None:
                reasons.append("EXTERNAL_IMAGE")
            if geometry is None:
                reasons.append("GEOMETRY_UNRESOLVED")
            if group_id is not None:
                reasons.append("GROUP_COMPOSITION_REQUIRED")
            if (
                record.body[68:71] != b"\0\0\0"
                or (len(record.body) >= 82 and struct.unpack_from("<I", record.body, 78)[0] != 0)
                or (len(record.body) == 91 and record.body[90] != 0)
            ):
                reasons.append("IMAGE_EFFECT_UNSUPPORTED")
            proof = record.body + (b"" if shape is None else shape.body)
            uses.append(
                OfficePictureUse(
                    use_id=office_object_id(source_sha256, locator),
                    locator=locator,
                    source_member=source_member,
                    native_sha256=_sha(proof),
                    group_id=group_id,
                    geometry=geometry,
                    placement=_placement(
                        controls[-1] if controls else None,
                        paragraphs[-1].ordinal if paragraphs else None,
                    ),
                    unresolved_reasons=tuple(sorted(reasons)),
                )
            )
        kind: OfficeNativeObjectKind | None = None
        if record.tag in _DRAWING_TAGS:
            kind = "DRAWING"
        elif record.tag == 88:
            kind = "EQUATION"
        elif record.tag == 77:
            kind = "TABLE"
        elif record.tag == 76 and b"noc$" in record.body[:8]:
            kind = "GROUP"
        if kind is not None:
            objects.append(
                OfficeNativeObject(
                    object_id=office_object_id(source_sha256, locator),
                    locator=locator,
                    kind=kind,
                    group_id=group_id,
                    native_sha256=_sha(record.body),
                )
            )
        stack.append(record)
        if record.tag == 71:
            controls.append(record)
        elif record.tag == 66:
            paragraphs.append(record)
        if record.tag == 76:
            shapes.append(record)
            if kind == "GROUP":
                groups.append(record)
        if len(uses) > 2048 or len(objects) > 4096:
            raise OfficeEmbeddedImageError("OFFICE_PICTURE_OBJECT_LIMIT")
    return uses, objects


def _placement(control: HwpRecord | None, anchor: int | None) -> OfficePicturePlacement | None:
    if control is None or control.body[:4] != b" osg" or len(control.body) < 28:
        return None
    flags, vertical, horizontal, width, height, z_order = struct.unpack_from(
        "<IiiIIi", control.body, 4
    )
    vertical_relative = (flags >> 3) & 3
    if vertical_relative > 2:
        return None
    try:
        return OfficePicturePlacement.model_validate(
            {
                "horizontal_offset": horizontal,
                "vertical_offset": vertical,
                "horizontal_relative": ("PAPER", "PAGE", "COLUMN", "PARA")[(flags >> 8) & 3],
                "vertical_relative": ("PAPER", "PAGE", "PARA")[vertical_relative],
                "width": width,
                "height": height,
                "z_order": z_order,
                "anchor_ordinal": anchor,
            }
        )
    except ValueError:
        return None


def read_hwp_picture_uses(
    payload: bytes, *, source_sha256: str
) -> tuple[list[OfficePictureUse], list[OfficeNativeObject]]:
    try:
        import olefile  # type: ignore[import-untyped]
    except ImportError as exc:
        raise OfficeEmbeddedImageError("OFFICE_EMBEDDED_HWP_READER_UNAVAILABLE") from exc
    with olefile.OleFileIO(
        io.BytesIO(payload), write_mode=False, raise_defects=olefile.DEFECT_INCORRECT
    ) as document:
        header = document.openstream("FileHeader").read(4097)
        if not header.startswith(b"HWP Document File") or len(header) < 40 or len(header) > 4096:
            raise OfficeEmbeddedImageError("OFFICE_EMBEDDED_HWP_HEADER_INVALID")
        flags = struct.unpack_from("<I", header, 36)[0]
        if flags & 6:
            raise OfficeEmbeddedImageError("OFFICE_EMBEDDED_HWP_PROTECTED")
        entries = document.listdir()
        members: dict[str, str] = {}
        for parts in entries:
            if len(parts) == 2 and parts[0] == "BinData":
                name = "/".join(parts)
                if name.casefold() in members:
                    raise OfficeEmbeddedImageError("OFFICE_PICTURE_DUPLICATE_MEMBER")
                members[name.casefold()] = name
        total = 0

        def stream(name: str) -> bytes:
            nonlocal total
            size = document.get_size(name)
            if not 0 < size <= _MAX_STREAM:
                raise OfficeEmbeddedImageError("OFFICE_PICTURE_STREAM_LIMIT")
            raw = document.openstream(name).read(_MAX_STREAM + 1)
            if len(raw) != size:
                raise OfficeEmbeddedImageError("OFFICE_PICTURE_STREAM_INVALID")
            raw = _inflate(raw) if flags & 1 else raw
            total += len(raw)
            if total > _MAX_TOTAL:
                raise OfficeEmbeddedImageError("OFFICE_PICTURE_STREAM_LIMIT")
            return raw

        bindings = hwp_binary_bindings(stream("DocInfo"), members)
        sections = sorted(
            "/".join(parts)
            for parts in entries
            if len(parts) == 2 and re.fullmatch(r"BodyText/Section[0-9]+", "/".join(parts))
        )
        if not 1 <= len(sections) <= 64:
            raise OfficeEmbeddedImageError("OFFICE_PICTURE_SECTION_LIMIT")
        uses: list[OfficePictureUse] = []
        objects: list[OfficeNativeObject] = []
        for member in sections:
            found, native = _section_objects(
                stream(member), member=member, source_sha256=source_sha256, bindings=bindings
            )
            uses.extend(found)
            objects.extend(native)
        return uses, objects
