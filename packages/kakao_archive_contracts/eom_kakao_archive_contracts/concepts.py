"""Private local concept proposals; trusted owners retain source pins and publish nothing here."""

from typing import Annotated, Literal, Self

from pydantic import Field, TypeAdapter, model_validator

from .concept_validation import load_concept_schema, validate_concept_contract
from .render import FrozenModel, LocalMember, QuestionRevisionId, Sha256, canonical_bytes, sha256
from .study import StudyRevisionId, StudySourceContent

ConceptTaskId = Annotated[str, Field(pattern=r"^kakaoconcepttask_[0-9a-f]{32}$")]
EvidenceKey = Annotated[str, Field(pattern=r"^E[1-3]$")]
PageKey = Annotated[str, Field(pattern=r"^E[1-3]P[1-9][0-9]{0,4}$")]
PassageKey = Annotated[str, Field(pattern=r"^Q[1-9][0-9]?$")]
Limitation = Annotated[str, Field(min_length=1, max_length=256)]


class ConceptQuestion(FrozenModel):
    question_revision_id: QuestionRevisionId
    question_manifest_sha256: Sha256
    student: StudySourceContent
    staff: StudySourceContent | None

    @model_validator(mode="after")
    def bounded_content(self) -> Self:
        if (
            sum(len(t.value.text) for c in (self.student, self.staff) if c for t in c.text_blocks)
            > 60000
        ):
            raise ValueError("KAKAO_CONCEPT_QUESTION_TOO_LARGE")
        return self


class ConceptOriginalPassage(FrozenModel):
    passage_key: PassageKey
    text: str = Field(min_length=1, max_length=4000)


class ConceptEvidence(FrozenModel):
    evidence_key: EvidenceKey
    source_class: Literal["TEXTBOOK"] = "TEXTBOOK"
    display_title: str = Field(min_length=1, max_length=256)
    location: str = Field(min_length=1, max_length=256)
    text_kind: Literal["APPROVED_ANALYSIS_NOT_VERBATIM_SOURCE"] = (
        "APPROVED_ANALYSIS_NOT_VERBATIM_SOURCE"
    )
    analysis_text: str = Field(min_length=1, max_length=6000)
    original_passages: tuple[ConceptOriginalPassage, ...] = Field(max_length=8)

    @model_validator(mode="after")
    def unique_passages(self) -> Self:
        keys = [p.passage_key for p in self.original_passages]
        if len(set(keys)) != len(keys):
            raise ValueError("KAKAO_CONCEPT_PASSAGE_DUPLICATED")
        return self


class ConceptPage(FrozenModel):
    page_key: PageKey
    evidence_key: EvidenceKey
    physical_page: int = Field(ge=1, le=100000, strict=True)
    width_pixels: int = Field(ge=1, le=20000, strict=True)
    height_pixels: int = Field(ge=1, le=20000, strict=True)
    member: LocalMember

    @model_validator(mode="after")
    def actual_local_page(self) -> Self:
        if (
            self.page_key != f"{self.evidence_key}P{self.physical_page}"
            or self.member.media_type != "image/png"
            or self.width_pixels * self.height_pixels > 16000000
        ):
            raise ValueError("KAKAO_CONCEPT_PAGE_INVALID")
        return self


class ConceptEvidenceContext(FrozenModel):
    schema_version: Literal["kakao-concept-evidence-context/1.0"] = (
        "kakao-concept-evidence-context/1.0"
    )
    context_sha256: Sha256
    evidence: tuple[ConceptEvidence, ...] = Field(max_length=3)
    pages: tuple[ConceptPage, ...] = Field(max_length=12)
    limitations: tuple[Limitation, ...] = Field(max_length=12)

    @model_validator(mode="after")
    def closed_context(self) -> Self:
        keys = {e.evidence_key for e in self.evidence}
        if (
            len(keys) != len(self.evidence)
            or len({p.page_key for p in self.pages}) != len(self.pages)
            or any(p.evidence_key not in keys for p in self.pages)
            or len(set(self.limitations)) != len(self.limitations)
        ):
            raise ValueError("KAKAO_CONCEPT_CONTEXT_INVALID")
        raw = canonical_bytes(self.model_dump(mode="json", exclude={"context_sha256"}))
        if len(raw) > 60000 or sha256(raw) != self.context_sha256:
            raise ValueError("KAKAO_CONCEPT_CONTEXT_HASH_MISMATCH")
        validate_concept_contract("context", self.model_dump(mode="json"))
        return self


class ConceptQuery(FrozenModel):
    concept: str = Field(min_length=1, max_length=128)
    query: str = Field(min_length=1, max_length=256)
    reason: str = Field(min_length=1, max_length=500)


class ConceptPlan(FrozenModel):
    phase: Literal["PLAN"] = "PLAN"
    status: Literal["PLANNED", "NEEDS_INPUT"]
    focus_summary: str = Field(min_length=1, max_length=1000)
    queries: tuple[ConceptQuery, ...] = Field(max_length=4)
    limitations: tuple[Limitation, ...] = Field(max_length=12)

    @model_validator(mode="after")
    def planned_queries(self) -> Self:
        if (self.status == "PLANNED") != bool(self.queries) or len(
            {q.query.strip().casefold() for q in self.queries}
        ) != len(self.queries):
            raise ValueError("KAKAO_CONCEPT_PLAN_INVALID")
        return self


class ConceptCitation(FrozenModel):
    evidence_key: EvidenceKey
    passage_key: PassageKey | None
    quote: str | None = Field(min_length=1, max_length=1000)

    @model_validator(mode="after")
    def explicit_original_quote(self) -> Self:
        if (self.passage_key is None) != (self.quote is None):
            raise ValueError("KAKAO_CONCEPT_QUOTE_INVALID")
        return self


class ConceptRectangle(FrozenModel):
    x: float = Field(ge=0, le=1)
    y: float = Field(ge=0, le=1)
    width: float = Field(gt=0, le=1)
    height: float = Field(gt=0, le=1)

    @model_validator(mode="after")
    def inside_page(self) -> Self:
        if self.x + self.width > 1 or self.y + self.height > 1:
            raise ValueError("KAKAO_CONCEPT_CROP_OUTSIDE_PAGE")
        return self


class ConceptCapture(FrozenModel):
    page_key: PageKey
    rectangle: ConceptRectangle
    reason: str = Field(min_length=1, max_length=500)


class ConceptBlock(FrozenModel):
    title: str = Field(min_length=1, max_length=128)
    relevance: str = Field(min_length=1, max_length=1000)
    explanation: str = Field(min_length=1, max_length=8000)
    citations: tuple[ConceptCitation, ...] = Field(min_length=1, max_length=6)
    captures: tuple[ConceptCapture, ...] = Field(max_length=4)


class ConceptStaffCheck(FrozenModel):
    observation: str = Field(min_length=1, max_length=1000)
    reason: str = Field(min_length=1, max_length=1000)
    evidence_keys: tuple[EvidenceKey, ...] = Field(max_length=3)

    @model_validator(mode="after")
    def unique_keys(self) -> Self:
        if len(set(self.evidence_keys)) != len(self.evidence_keys):
            raise ValueError("KAKAO_CONCEPT_CITATION_DUPLICATED")
        return self


class ConceptComposition(FrozenModel):
    phase: Literal["COMPOSE"] = "COMPOSE"
    status: Literal["DRAFT_READY", "NO_MATCH", "NEEDS_INPUT"]
    focus_summary: str = Field(min_length=1, max_length=1000)
    blocks: tuple[ConceptBlock, ...] = Field(max_length=6)
    staff_checks: tuple[ConceptStaffCheck, ...] = Field(max_length=6)
    limitations: tuple[Limitation, ...] = Field(max_length=12)

    @model_validator(mode="after")
    def ready_has_blocks(self) -> Self:
        if (self.status == "DRAFT_READY") != bool(self.blocks):
            raise ValueError("KAKAO_CONCEPT_COMPOSITION_INVALID")
        return self


class _ConceptRequestBase(FrozenModel):
    schema_version: Literal["kakao-concept-assistance-request/1.0"] = (
        "kakao-concept-assistance-request/1.0"
    )
    task_id: ConceptTaskId
    question: ConceptQuestion
    base_study_revision_id: StudyRevisionId | None
    additional_instructions: str = Field(max_length=6000)


class ConceptPlanRequest(_ConceptRequestBase):
    phase: Literal["PLAN"] = "PLAN"


class ConceptComposeRequest(_ConceptRequestBase):
    phase: Literal["COMPOSE"] = "COMPOSE"
    plan: ConceptPlan
    context: ConceptEvidenceContext

    @model_validator(mode="after")
    def planned(self) -> Self:
        if self.plan.status != "PLANNED":
            raise ValueError("KAKAO_CONCEPT_PLAN_NOT_READY")
        return self


ConceptRequest = Annotated[ConceptPlanRequest | ConceptComposeRequest, Field(discriminator="phase")]


class ConceptResult(FrozenModel):
    schema_version: Literal["kakao-concept-assistance-result/1.0"] = (
        "kakao-concept-assistance-result/1.0"
    )
    task_id: ConceptTaskId
    request_sha256: Sha256
    output: Annotated[ConceptPlan | ConceptComposition, Field(discriminator="phase")]


def parse_concept_request(value: object) -> ConceptPlanRequest | ConceptComposeRequest:
    validate_concept_contract("request", value)
    adapter: TypeAdapter[ConceptPlanRequest | ConceptComposeRequest] = TypeAdapter(ConceptRequest)
    request = adapter.validate_python(value)
    if len(canonical_bytes(request.model_dump(mode="json"))) > 262144:
        raise ValueError("KAKAO_CONCEPT_REQUEST_TOO_LARGE")
    concept_input_members(request)
    return request


def concept_input_members(
    request: ConceptPlanRequest | ConceptComposeRequest,
) -> tuple[LocalMember, ...]:
    members: dict[str, LocalMember] = {}
    values = [
        image.value.member
        for content in (request.question.student, request.question.staff)
        if content
        for image in content.images
        if image.value.member is not None
    ]
    if isinstance(request, ConceptComposeRequest):
        values.extend(page.member for page in request.context.pages)
    for member in values:
        if member.relative_path in members and members[member.relative_path] != member:
            raise ValueError("KAKAO_CONCEPT_MEMBER_COLLISION")
        members[member.relative_path] = member
    if sum(m.size_bytes for m in members.values()) > 134217728:
        raise ValueError("KAKAO_CONCEPT_INPUT_TOO_LARGE")
    return tuple(members.values())


def validate_concept_result(
    request: ConceptPlanRequest | ConceptComposeRequest,
    value: object,
) -> ConceptResult:
    validate_concept_contract("result", value)
    result = ConceptResult.model_validate(value)
    if (result.task_id, result.request_sha256, result.output.phase) != (
        request.task_id,
        sha256(canonical_bytes(request.model_dump(mode="json"))),
        request.phase,
    ):
        raise ValueError("KAKAO_CONCEPT_RESULT_INPUT_MISMATCH")
    if isinstance(request, ConceptComposeRequest) and isinstance(result.output, ConceptComposition):
        evidence = {e.evidence_key: e for e in request.context.evidence}
        pages = {p.page_key: p for p in request.context.pages}
        passages = {
            (e.evidence_key, p.passage_key): p.text
            for e in evidence.values()
            for p in e.original_passages
        }
        for block in result.output.blocks:
            citations = {c.evidence_key for c in block.citations}
            if not citations <= evidence.keys() or len(set(block.citations)) != len(
                block.citations
            ):
                raise ValueError("KAKAO_CONCEPT_CITATION_INVALID")
            for citation in block.citations:
                if citation.quote is not None and (
                    citation.passage_key is None
                    or citation.quote
                    not in passages.get((citation.evidence_key, citation.passage_key), "")
                ):
                    raise ValueError("KAKAO_CONCEPT_QUOTE_NOT_MATERIALIZED")
            for capture in block.captures:
                page = pages.get(capture.page_key)
                if page is None or page.evidence_key not in citations:
                    raise ValueError("KAKAO_CONCEPT_PAGE_NOT_MATERIALIZED")
        if any(not set(c.evidence_keys) <= evidence.keys() for c in result.output.staff_checks):
            raise ValueError("KAKAO_CONCEPT_CITATION_INVALID")
    return result


def concept_result_schema(request: ConceptPlanRequest | ConceptComposeRequest) -> dict[str, object]:
    """Constrain the existing model JSON-output mechanism to this exact request."""
    schema = load_concept_schema()
    schema.pop("oneOf")
    name = "compose_result" if isinstance(request, ConceptComposeRequest) else "plan_result"
    schema["$ref"] = "#/$defs/" + name
    props = schema["$defs"][name]["properties"]
    props["task_id"] = {"const": request.task_id}
    props["request_sha256"] = {"const": sha256(canonical_bytes(request.model_dump(mode="json")))}
    if isinstance(request, ConceptComposeRequest):
        keys = [e.evidence_key for e in request.context.evidence]
        if keys:
            schema["$defs"]["citation"]["properties"]["evidence_key"] = {"enum": keys}
        else:
            schema["$defs"]["compose"]["properties"]["blocks"]["maxItems"] = 0
        page_keys = [p.page_key for p in request.context.pages]
        if page_keys:
            schema["$defs"]["capture"]["properties"]["page_key"] = {"enum": page_keys}
        else:
            schema["$defs"]["block"]["properties"]["captures"]["maxItems"] = 0
    # Model output has no need to resolve request-only external schema resources.
    keep = (
        {"compose_result", "compose", "block", "capture", "rectangle", "citation", "staff_check"}
        if isinstance(request, ConceptComposeRequest)
        else {"plan_result", "plan", "query"}
    )
    schema["$defs"] = {key: value for key, value in schema["$defs"].items() if key in keep}
    return schema
