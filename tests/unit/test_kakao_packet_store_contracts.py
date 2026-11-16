"""Exact packet request/projection schemas; no renderer, model, network or runtime writes."""

from datetime import UTC, date, datetime
from pathlib import Path

import pytest
from eom_catalog_contracts.kakao_packet_store import (
    PACKET_REF,
    KakaoPacketCreate,
    KakaoPacketMutation,
    KakaoPacketPage,
    KakaoPacketRevise,
    KakaoStoredPacket,
)
from eom_catalog_contracts.kakao_question import KakaoQuestionProvenance
from eom_catalog_contracts.validation import CATALOG_SCHEMA_RESOURCES, validate_contract
from eom_catalog_service.kakao_packet_models import (
    KakaoPacketCommandRecord,
    KakaoPacketRecord,
    KakaoPacketRevisionRecord,
)
from eom_catalog_service.kakao_packet_service import KakaoPacketService  # noqa: F401
from sqlalchemy import Boolean, Date, DateTime, Integer, String
from sqlalchemy.dialects.postgresql import dialect
from sqlalchemy.schema import CreateTable

from tests.unit.test_kakao_question_editing import identity, pointer


def create_packet():
    return KakaoPacketCreate(
        source_binding_id=identity("kakaobinding", 1),
        title="질문 자료",
        questions=(
            KakaoQuestionProvenance(
                question_id=identity("kakaoquestion", 1),
                question_revision_id=identity("kakaoquestionrev", 1),
            ),
        ),
        display_start_date=date(2026, 10, 1),
        display_end_date_inclusive=date(2026, 10, 31),
        mode="DRAFT",
        include_replies=False,
    )


def stored_packet():
    command = create_packet()
    return KakaoStoredPacket(
        source_binding_id=command.source_binding_id,
        title=command.title,
        packet_id=identity("kakaopacket", 1),
        packet_revision_id=identity("kakaopacketrev", 1),
        previous_revision_id=None,
        resource_version=1,
        manifest=pointer(PACKET_REF, b"packet"),
        display_start_date=command.display_start_date,
        display_end_date_inclusive=command.display_end_date_inclusive,
        mode=command.mode,
        include_replies=command.include_replies,
        question_count=1,
        student_count=1,
        created_at=datetime(2026, 11, 16, tzinfo=UTC),
    )


def test_packet_schema_is_mirrored_and_validates_all_message_types():
    root = Path(__file__).resolve().parents[2]
    resource = CATALOG_SCHEMA_RESOURCES["kakao-packet-store-v1"]
    assert (root / resource.canonical_path).read_bytes() == (
        root / "packages/catalog_contracts/eom_catalog_contracts" / resource.resource_path
    ).read_bytes()
    create, stored = create_packet(), stored_packet()
    revise = KakaoPacketRevise.model_validate(
        create.model_dump(mode="json")
        | dict(
            schema_version="kakao-packet-revise/1.0",
            packet_id=stored.packet_id,
            parent_revision_id=stored.packet_revision_id,
            expected_resource_version=1,
        )
    )
    for value in (
        create,
        revise,
        stored,
        KakaoPacketMutation(packet=stored, replayed=False),
        KakaoPacketPage(items=(stored,), next_cursor=None),
    ):
        validate_contract("kakao-packet-store-v1", value.model_dump(mode="json"))


@pytest.mark.parametrize(
    "field,value",
    [
        ("include_replies", 1),
        ("mode", "latest"),
        ("questions", ()),
        ("title", "\nprivate"),
        ("title", "   "),
        ("display_end_date_inclusive", "2026-09-30"),
        ("actor_id", identity("operator", 1)),
        ("collection_coverage", "COMPLETE"),
        ("source_path", "/private/messages.json"),
        ("approved", True),
    ],
)
def test_packet_commands_reject_forged_authority_invalid_period_or_empty_selection(field, value):
    with pytest.raises(ValueError):
        KakaoPacketCreate.model_validate(create_packet().model_dump(mode="json") | {field: value})


def test_packet_cannot_select_two_versions_of_one_logical_question():
    one = create_packet()
    with pytest.raises(ValueError, match="QUESTION_DUPLICATED"):
        KakaoPacketCreate.model_validate(
            one.model_dump(mode="json")
            | dict(
                questions=(
                    one.questions[0],
                    one.questions[0].model_copy(
                        update={"question_revision_id": identity("kakaoquestionrev", 2)}
                    ),
                )
            )
        )


@pytest.mark.parametrize(
    "changes",
    [
        {"resource_version": True},
        {"resource_version": 2},
        {"previous_revision_id": identity("kakaopacketrev", 1)},
        {"student_count": 2},
        {"manifest": pointer("wrong-schema", b"packet")},
    ],
)
def test_stored_packet_requires_exact_revision_pointer_and_bounded_counts(changes):
    with pytest.raises(ValueError):
        KakaoStoredPacket.model_validate(stored_packet().model_dump(mode="json") | changes)


def test_packet_records_contain_only_small_metadata_and_indexed_page_lookup():
    for model in (KakaoPacketRecord, KakaoPacketCommandRecord, KakaoPacketRevisionRecord):
        assert all(
            isinstance(column.type, (String, Integer, Date, DateTime, Boolean))
            for column in model.__table__.columns
        )
        ddl = str(CreateTable(model.__table__).compile(dialect=dialect()))
        assert "JSON" not in ddl and "BYTEA" not in ddl
    assert {index.name for index in KakaoPacketRecord.__table__.indexes} == {"ix_kakao_packet_page"}
