"""Catalog's score adapter uses only the exact question descriptor and bounded XML."""

from decimal import Decimal
from io import BytesIO
from types import SimpleNamespace
from zipfile import ZIP_DEFLATED, ZipFile

import pytest
from eom_catalog_contracts.material_native_files import MaterialNativeFileBinding
from eom_catalog_contracts.source_score import parse_source_score_v2
from eom_catalog_service.material_native_score import (
    expected_native_source_score,
    read_native_question_score,
    require_native_source_score,
)
from eom_hwpx_contracts.native_item_score import observe_native_printed_score
from eom_identifiers import sha256_bytes

from tests.unit.test_material_native_intake import native_exam_bundle


def section(text):
    return (
        '<hs:sec xmlns:hs="http://www.hancom.co.kr/hwpml/2011/section" xmlns:hp="http://www.hancom.co.kr/hwpml/2011/paragraph"><hp:p><hp:run><hp:t>'
        + text
        + "</hp:t></hp:run></hp:p></hs:sec>"
    ).encode()


def package(*sections):
    stream = BytesIO()
    with ZipFile(stream, "w", compression=ZIP_DEFLATED) as archive:
        for index, raw in enumerate(sections):
            archive.writestr(f"Contents/section{index}.xml", raw)
        archive.writestr("BinData/not-a-score.png", b"[99.5pts]")
    return stream.getvalue()


def bound_question(payload):
    value = native_exam_bundle()["items"][0]["question"]
    value["document"].update(bytes=len(payload), sha256=sha256_bytes(payload))
    return MaterialNativeFileBinding.model_validate(value)


class Reader:
    def __init__(self, payload, question):
        self.payload, self.question = payload, question
        self.calls = []
        self.streams = []

    def open_verified_member(self, **kwargs):
        pointer = self.question.document
        assert kwargs == dict(
            artifact_id=pointer.artifact_id,
            revision_id=pointer.artifact_revision_id,
            member_path=pointer.member_path,
            schema_ref=pointer.schema_ref,
            media_type=pointer.media_type,
            sha256=pointer.sha256,
            max_bytes=pointer.bytes,
        )
        if sha256_bytes(self.payload) != pointer.sha256:
            raise ValueError("TEST_ARTIFACT_HASH_MISMATCH")
        self.calls.append(kwargs)
        stream = BytesIO(self.payload)
        self.streams.append(stream)
        return SimpleNamespace(stream=stream, content_length=len(self.payload))


@pytest.mark.parametrize("literal,expected", [("1.5", "1.5"), ("2.50", "2.5"), ("2", 2), ("0", 0)])
def test_exact_native_score_uses_original_question_and_reauthorizes(literal, expected):
    payload = package(section(f"[{literal}점]"))
    question = bound_question(payload)
    reader = Reader(payload, question)
    checks = []
    observation = read_native_question_score(
        reader, question, authorize=lambda: checks.append(True)
    )
    assert len(checks) == 2 and len(reader.calls) == 1
    assert reader.streams[0].closed
    assert observation.candidates[0].points == Decimal(literal)
    assert observation.candidates[0].printed_literal == literal
    assert expected_native_source_score(observation).points == expected
    require_native_source_score(
        observation, parse_source_score_v2(dict(state="PRINTED", points=expected))
    )


@pytest.mark.parametrize(
    "proposed",
    [
        {"state": "PRINTED", "points": 15},
        {"state": "PRINTED", "points": 0},
        {"state": "PRINTED", "points": 2},
        {"state": "UNPRINTED", "points": None},
    ],
)
def test_original_half_point_cannot_be_zero_scaled_rounded_or_called_unprinted(proposed):
    observation = observe_native_printed_score(section("[1.5점]"))
    with pytest.raises(ValueError, match="MATERIAL_NATIVE_SCORE_MISMATCH"):
        require_native_source_score(observation, parse_source_score_v2(proposed))


@pytest.mark.parametrize(
    "text,code", [("본문", "ABSENT"), ("[1.5점] [1.5점]", "AMBIGUOUS"), ("[0.25점]", "UNSUPPORTED")]
)
def test_unobservable_ambiguous_or_unsupported_points_are_not_invented(text, code):
    with pytest.raises(ValueError, match="MATERIAL_NATIVE_SCORE_" + code):
        expected_native_source_score(observe_native_printed_score(section(text)))


def test_hash_or_permission_failure_never_yields_an_expected_score():
    payload = package(section("[1.5점]"))
    question = bound_question(payload)
    reader = Reader(payload + b"changed", question)
    with pytest.raises(ValueError, match="HASH_MISMATCH"):
        read_native_question_score(reader, question, authorize=lambda: None)
    assert reader.streams == []

    def deny():
        raise PermissionError("TEST_SOURCE_FORBIDDEN")

    with pytest.raises(PermissionError):
        read_native_question_score(reader, question, authorize=deny)
    assert reader.calls == []


@pytest.mark.parametrize("sections", [(b"<!DOCTYPE bad><bad/>",), (b"<bad/>",), ()])
def test_invalid_packages_close_descriptors(sections):
    payload = package(*sections)
    question = bound_question(payload)
    reader = Reader(payload, question)
    with pytest.raises(ValueError):
        read_native_question_score(reader, question, authorize=lambda: None)
    assert reader.streams[0].closed


def test_separate_section_markers_remain_ambiguous():
    payload = package(section("[1.5점]"), section("[2.5점]"))
    question = bound_question(payload)
    result = read_native_question_score(Reader(payload, question), question, authorize=lambda: None)
    assert result.state == "AMBIGUOUS"
    assert len(result.candidates) == 2
