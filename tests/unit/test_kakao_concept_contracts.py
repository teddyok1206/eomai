"""Bounded local proposals, not Graph retrieval, worker execution or source authority."""

import copy
from pathlib import Path

import pytest
from eom_kakao_archive_contracts import canonical_bytes, sha256
from eom_kakao_archive_contracts.concept_validation import (
    CONCEPT_SCHEMA_SHA256,
    load_concept_schema,
)
from eom_kakao_archive_contracts.concepts import (
    ConceptEvidenceContext,
    concept_input_members,
    concept_result_schema,
    parse_concept_request,
    validate_concept_result,
)
from eom_kakao_archive_contracts.study_validation import STUDY_SCHEMA_SHA256
from eom_kakao_archive_contracts.validation import SCHEMA_SHA256
from jsonschema import Draft202012Validator, ValidationError

ROOT = Path(__file__).resolve().parents[2]


def question():
    # A pure local proposal fixture must not import the PDF worker or source owner.
    original = dict(
        question_revision_id="kakaoquestionrev_" + "1" * 32,
        student=dict(
            text_blocks=[
                dict(
                    source_occurrence_id="kakaomessage_" + "1" * 32,
                    value=dict(
                        span_id="student-question", text="별의 질량과 광도는 어떤 관계인가요?"
                    ),
                )
            ],
            images=[
                dict(
                    source_occurrence_id="kakaomessage_" + "2" * 32,
                    value=dict(
                        attachment_occurrence_id="kakaoattachment_" + "1" * 32,
                        attachment_revision_id="kakaoattachmentrev_" + "1" * 32,
                        member=dict(
                            relative_path="images/question.png",
                            sha256=sha256(b"photo"),
                            size_bytes=5,
                            media_type="image/png",
                        ),
                        availability="AVAILABLE",
                        quality_accepted=True,
                        transform=None,
                    ),
                )
            ],
            ordered_blocks=[
                dict(kind="TEXT", span_id="student-question"),
                dict(kind="IMAGE", attachment_occurrence_id="kakaoattachment_" + "1" * 32),
            ],
        ),
        staff=dict(
            text_blocks=[
                dict(
                    source_occurrence_id="kakaomessage_" + "3" * 32,
                    value=dict(span_id="staff-reply", text="주계열성의 관계를 함께 확인해 보세요."),
                )
            ],
            images=[],
            ordered_blocks=[dict(kind="TEXT", span_id="staff-reply")],
        ),
    )
    return {
        "question_revision_id": original["question_revision_id"],
        "question_manifest_sha256": sha256(canonical_bytes(original)),
        "student": original["student"],
        "staff": original["staff"],
    }


def plan_request():
    return parse_concept_request(
        dict(
            schema_version="kakao-concept-assistance-request/1.0",
            phase="PLAN",
            task_id="kakaoconcepttask_" + "1" * 32,
            question=question(),
            base_study_revision_id=None,
            additional_instructions="기초 개념을 먼저 찾아 주세요.",
        )
    )


def plan():
    return dict(
        phase="PLAN",
        status="PLANNED",
        focus_summary="질량과 광도의 관계",
        queries=[dict(concept="질량과 광도", query="별의 질량 광도 관계", reason="질문과의 연결")],
        limitations=[],
    )


def context(*, page=True, change=None):
    value = dict(
        schema_version="kakao-concept-evidence-context/1.0",
        evidence=[
            dict(
                evidence_key="E1",
                source_class="TEXTBOOK",
                display_title="검증용 교재",
                location="물리 페이지 3",
                text_kind="APPROVED_ANALYSIS_NOT_VERBATIM_SOURCE",
                analysis_text="분석 요약은 원문 인용이 아니다.",
                original_passages=[
                    dict(passage_key="Q1", text="질량이 큰 주계열성은 광도가 크다.")
                ],
            )
        ],
        pages=[
            dict(
                page_key="E1P3",
                evidence_key="E1",
                physical_page=3,
                width_pixels=800,
                height_pixels=1000,
                member=dict(
                    relative_path="pages/E1P3.png",
                    sha256=sha256(b"page"),
                    size_bytes=4,
                    media_type="image/png",
                ),
            )
        ]
        if page
        else [],
        limitations=[],
    )
    if change:
        change(value)
    return ConceptEvidenceContext.model_validate(
        value | dict(context_sha256=sha256(canonical_bytes(value)))
    )


def compose_request(*, page=True):
    return parse_concept_request(
        plan_request().model_dump(mode="json")
        | dict(
            phase="COMPOSE",
            plan=plan(),
            context=context(page=page).model_dump(mode="json"),
        )
    )


def composed(*, capture=True):
    return dict(
        phase="COMPOSE",
        status="DRAFT_READY",
        focus_summary="관련 개념 설명 초안",
        blocks=[
            dict(
                title="주계열성",
                relevance="질량과 광도 관계를 확인한다.",
                explanation="학생용 모델 설명 초안",
                citations=[dict(evidence_key="E1", passage_key="Q1", quote="광도가 크다")],
                captures=[
                    dict(
                        page_key="E1P3",
                        rectangle=dict(x=0.1, y=0.2, width=0.6, height=0.4),
                        reason="실제 제공 페이지의 개념 부분",
                    )
                ]
                if capture
                else [],
            )
        ],
        staff_checks=[],
        limitations=[],
    )


def result(request, payload):
    return dict(
        schema_version="kakao-concept-assistance-result/1.0",
        task_id=request.task_id,
        request_sha256=sha256(canonical_bytes(request.model_dump(mode="json"))),
        output=payload,
    )


def test_closed_schema_mirror_and_predecessor_bytes_are_unchanged():
    canonical = ROOT / "schemas/kakao-archive/concept-assistance-v1.schema.json"
    mirror = (
        ROOT
        / "packages/kakao_archive_contracts/eom_kakao_archive_contracts/schemas"
        / canonical.name
    )
    assert canonical.read_bytes() == mirror.read_bytes()
    assert sha256(canonical.read_bytes()) == CONCEPT_SCHEMA_SHA256
    assert load_concept_schema()["$schema"].endswith("draft/2020-12/schema")
    for filename, pin in (
        ("worker-question-render-v1.schema.json", SCHEMA_SHA256),
        ("worker-study-render-v1.schema.json", STUDY_SCHEMA_SHA256),
    ):
        assert sha256((canonical.parent / filename).read_bytes()) == pin


def test_plan_and_compose_parse_and_constrained_json_outputs_are_self_contained():
    for request, payload in ((plan_request(), plan()), (compose_request(), composed())):
        raw = result(request, payload)
        schema = concept_result_schema(request)
        Draft202012Validator.check_schema(schema)
        # No external resolver, source checkout or network is necessary for model output.
        Draft202012Validator(schema).validate(raw)
        assert validate_concept_result(request, raw).task_id == request.task_id
        assert parse_concept_request(request.model_dump(mode="json")) == request


@pytest.mark.parametrize(
    "field",
    [
        "student_display_name",
        "student_id",
        "actor_id",
        "session_token",
        "slot_id",
        "source_path",
        "source_url",
        "role",
    ],
)
def test_model_request_cannot_claim_student_list_auth_slot_or_external_files(field):
    value = plan_request().model_dump(mode="json")
    value[field] = "untrusted"
    with pytest.raises(ValueError, match="SCHEMA_INVALID"):
        parse_concept_request(value)


@pytest.mark.parametrize("case", ["task", "hash", "phase", "new-edit"])
def test_old_or_foreign_result_is_not_adopted(case):
    request = plan_request()
    value = result(request, plan())
    if case == "task":
        value["task_id"] = "kakaoconcepttask_" + "2" * 32
    elif case == "hash":
        value["request_sha256"] = sha256(b"other")
    elif case == "phase":
        value["output"] = composed(capture=False)
    else:
        request = parse_concept_request(
            request.model_dump(mode="json")
            | dict(base_study_revision_id="kakaostudyrev_" + "9".zfill(32))
        )
    with pytest.raises(ValueError, match="INPUT_MISMATCH"):
        validate_concept_result(request, value)


@pytest.mark.parametrize(
    "case",
    [
        "source",
        "fabricated-quote",
        "analysis-as-quote",
        "missing-page",
        "foreign-page",
        "outside-page",
        "duplicate-citation",
    ],
)
def test_unmaterialized_or_mismatched_evidence_and_capture_are_rejected(case):
    request = compose_request()
    value = result(request, composed())
    block = value["output"]["blocks"][0]
    if case == "source":
        block["citations"][0]["evidence_key"] = "E2"
    elif case == "fabricated-quote":
        block["citations"][0]["quote"] = "원문에 없는 문장"
    elif case == "analysis-as-quote":
        block["citations"][0]["quote"] = request.context.evidence[0].analysis_text
    elif case == "missing-page":
        request = compose_request(page=False)
        value["request_sha256"] = sha256(canonical_bytes(request.model_dump(mode="json")))
    elif case == "foreign-page":
        block["captures"][0]["page_key"] = "E2P3"
    elif case == "outside-page":
        block["captures"][0]["rectangle"]["width"] = 1
    else:
        block["citations"].append(copy.deepcopy(block["citations"][0]))
    with pytest.raises(ValueError):
        validate_concept_result(request, value)


def test_analysis_only_context_does_not_require_a_fake_quote_or_crop():
    request = compose_request(page=False)
    payload = composed(capture=False)
    payload["blocks"][0]["citations"][0].update(passage_key=None, quote=None)
    accepted = validate_concept_result(request, result(request, payload))
    assert not accepted.output.blocks[0].captures
    assert accepted.output.blocks[0].citations[0].quote is None
    with pytest.raises(ValidationError):
        Draft202012Validator(concept_result_schema(request)).validate(result(request, composed()))


def test_empty_retrieval_is_no_match_not_grounded_success():
    request = compose_request(page=False)
    empty = context(page=False, change=lambda v: v.update(evidence=[]))
    request = parse_concept_request(
        request.model_dump(mode="json") | dict(context=empty.model_dump(mode="json"))
    )
    payload = composed(capture=False)
    with pytest.raises(ValueError, match="CITATION_INVALID"):
        validate_concept_result(request, result(request, payload))
    payload.update(status="NO_MATCH", blocks=[], limitations=["허용 교재에 관련 근거가 없습니다."])
    accepted = validate_concept_result(request, result(request, payload))
    assert accepted.output.status == "NO_MATCH"
    Draft202012Validator(concept_result_schema(request)).validate(result(request, payload))


def test_modified_context_and_duplicate_members_are_not_silently_accepted():
    value = context().model_dump(mode="json")
    value["evidence"][0]["analysis_text"] = "바뀐 내용"
    with pytest.raises(ValueError, match="HASH_MISMATCH"):
        ConceptEvidenceContext.model_validate(value)
    request = compose_request()
    raw = request.model_dump(mode="json")
    student = raw["question"]["student"]["images"][0]["value"]["member"]
    raw["context"]["pages"][0]["member"].update(relative_path=student["relative_path"])
    new_context = raw["context"]
    new_context["context_sha256"] = sha256(
        canonical_bytes({k: v for k, v in new_context.items() if k != "context_sha256"})
    )
    with pytest.raises(ValueError, match="MEMBER_COLLISION"):
        parse_concept_request(raw)
    assert len({m.relative_path for m in concept_input_members(request)}) == len(
        concept_input_members(request)
    )


def test_prompt_is_dedicated_two_phase_data_only_and_no_chat_or_fake_search_authority():
    text = (
        ROOT / "config/control-plane/kakao-concepts-v1/instructions/kakao-concepts.md"
    ).read_text()
    for rule in (
        "PLAN",
        "COMPOSE",
        "worker에 검색 도구가 있다고 가정하지",
        "원문 인용문이 아니다",
        "남긴다",
        "메시지·답장을 절대로 보내지",
        "original_passages",
        "page key",
    ):
        assert rule in text
    assert "retrieve_eom_knowledge" not in text
