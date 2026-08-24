"""Typed contracts for source-grounded analysis, graph snapshots, and Evidence Bundles."""

from __future__ import annotations

from datetime import datetime, timedelta
from enum import StrEnum
from pathlib import PurePosixPath
from typing import Annotated, Literal

from eom_identifiers import content_sha256
from pydantic import AfterValidator, BaseModel, ConfigDict, Field, field_validator, model_validator


def _require_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError("timestamp must use UTC")
    return value


def _safe_member_path(value: str) -> str:
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or "." in path.parts:
        raise ValueError("artifact member path must be normalized and relative")
    if not path.parts or path.parts[0] not in {"source", "normalized", "projections", "evidence"}:
        raise ValueError("artifact member path is outside the knowledge contract roots")
    return value


def _safe_text(value: str) -> str:
    if any(ord(character) < 32 and character not in "\t\n\r" for character in value):
        raise ValueError("text contains a control character")
    return value


UtcDatetime = Annotated[datetime, AfterValidator(_require_utc)]
Sha256 = Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]
SafeMemberPath = Annotated[
    str,
    Field(
        pattern=r"^(source|normalized|projections|evidence)/[A-Za-z0-9._()가-힣/-]+$",
        max_length=512,
    ),
    AfterValidator(_safe_member_path),
]
AnchorId = Annotated[str, Field(pattern=r"^anchor_[a-z0-9][a-z0-9_-]{0,63}$")]
NodeId = Annotated[str, Field(pattern=r"^knode_[a-z0-9][a-z0-9_-]{0,63}$")]


def _safe_canonical_member_path(value: str) -> str:
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or "." in path.parts or not path.parts:
        raise ValueError("canonical artifact member path must be normalized and relative")
    return value


def _safe_source_path(value: str) -> str:
    _safe_canonical_member_path(value)
    if PurePosixPath(value).parts[0] != "source":
        raise ValueError("analysis source must materialize under source/")
    return value


def _safe_normalized_path(value: str) -> str:
    _safe_canonical_member_path(value)
    if PurePosixPath(value).parts[0] != "normalized":
        raise ValueError("analysis proposal members must materialize under normalized/")
    return value


CanonicalMemberPath = Annotated[
    str,
    Field(pattern=r"^[A-Za-z0-9._()가-힣/-]+$", min_length=1, max_length=512),
    AfterValidator(_safe_canonical_member_path),
]
AnalysisSourcePath = Annotated[
    str,
    Field(pattern=r"^source/[A-Za-z0-9._()가-힣/-]+$", min_length=8, max_length=512),
    AfterValidator(_safe_source_path),
]
AnalysisNormalizedPath = Annotated[
    str,
    Field(pattern=r"^normalized/[A-Za-z0-9._()가-힣/-]+$", min_length=12, max_length=512),
    AfterValidator(_safe_normalized_path),
]


class FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, use_enum_values=True)


class KnowledgeSourceClass(StrEnum):
    CURRICULUM = "CURRICULUM"
    TEXTBOOK = "TEXTBOOK"
    APPROVED_ITEM = "APPROVED_ITEM"
    PAST_EXAM = "PAST_EXAM"
    INTERNAL_GUIDE = "INTERNAL_GUIDE"


class KnowledgeNodeType(StrEnum):
    CURRICULUM_FRAMEWORK_REVISION = "CURRICULUM_FRAMEWORK_REVISION"
    CURRICULUM_UNIT = "CURRICULUM_UNIT"
    ACHIEVEMENT_STANDARD = "ACHIEVEMENT_STANDARD"
    CONCEPT = "CONCEPT"
    CLAIM = "CLAIM"
    PROCESS = "PROCESS"
    OBSERVABLE_PROPERTY = "OBSERVABLE_PROPERTY"
    FORMULA = "FORMULA"
    DATA_REPRESENTATION = "DATA_REPRESENTATION"
    DOCUMENT_REVISION = "DOCUMENT_REVISION"
    DOCUMENT_SECTION = "DOCUMENT_SECTION"
    FIGURE = "FIGURE"
    TABLE = "TABLE"
    EQUATION = "EQUATION"
    ITEM_REVISION = "ITEM_REVISION"
    ITEM_ELEMENT = "ITEM_ELEMENT"
    ASSESSMENT_PATTERN = "ASSESSMENT_PATTERN"


class KnowledgeEdgeType(StrEnum):
    CONTAINS_CURRICULUM_UNIT = "CONTAINS_CURRICULUM_UNIT"
    PRECEDES_CURRICULUM_UNIT = "PRECEDES_CURRICULUM_UNIT"
    DEFINES_ACHIEVEMENT_STANDARD = "DEFINES_ACHIEVEMENT_STANDARD"
    DEFINES = "DEFINES"
    EXPLAINS = "EXPLAINS"
    IS_A = "IS_A"
    PART_OF = "PART_OF"
    CAUSES = "CAUSES"
    AFFECTS = "AFFECTS"
    DEPENDS_ON = "DEPENDS_ON"
    CONTRASTS_WITH = "CONTRASTS_WITH"
    REQUIRES_PREREQUISITE = "REQUIRES_PREREQUISITE"
    SUPPORTS_CLAIM = "SUPPORTS_CLAIM"
    CONTRADICTS_CLAIM = "CONTRADICTS_CLAIM"
    ILLUSTRATES = "ILLUSTRATES"
    TABULATES = "TABULATES"
    EXPRESSES_AS_EQUATION = "EXPRESSES_AS_EQUATION"
    DERIVED_FROM = "DERIVED_FROM"
    CITES_SOURCE = "CITES_SOURCE"
    ALIGNS_WITH_CURRICULUM = "ALIGNS_WITH_CURRICULUM"
    HAS_ITEM_ELEMENT = "HAS_ITEM_ELEMENT"
    ASSESSES_CONCEPT = "ASSESSES_CONCEPT"
    REQUIRES_CONCEPT = "REQUIRES_CONCEPT"
    USES_SOURCE_EVIDENCE = "USES_SOURCE_EVIDENCE"
    REPRESENTS_CONCEPT = "REPRESENTS_CONCEPT"
    SUPPORTS_STATEMENT = "SUPPORTS_STATEMENT"
    CONTRADICTS_STATEMENT = "CONTRADICTS_STATEMENT"
    PART_OF_INTERACTION = "PART_OF_INTERACTION"
    USES_ASSESSMENT_PATTERN = "USES_ASSESSMENT_PATTERN"
    SIMILAR_TO_ITEM = "SIMILAR_TO_ITEM"


class KnowledgeArtifactMemberPointer(FrozenModel):
    artifact_id: str = Field(pattern=r"^artifact_[0-9a-f]{32}$")
    artifact_revision_id: str = Field(pattern=r"^rev_[0-9a-f]{32}$")
    sha256: Sha256
    schema_ref: str = Field(
        pattern=r"^eom(?:\.assess(?:ment)?|://schemas/)[A-Za-z0-9._/@:-]{1,191}$",
        max_length=256,
    )
    media_type: str = Field(pattern=r"^[a-z0-9.+-]+/[A-Za-z0-9.+-]+$", max_length=128)
    logical_name: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,255}$")
    member_path: SafeMemberPath


class KnowledgeSourceRevisionPointer(FrozenModel):
    source_class: KnowledgeSourceClass
    logical_id: str = Field(pattern=r"^[a-z][a-z0-9]*_[0-9a-f]{32}$")
    revision_id: str = Field(pattern=r"^[a-z][a-z0-9]*rev_[0-9a-f]{32}$")
    lifecycle_state: Literal["APPROVED"] = "APPROVED"
    artifact_member: KnowledgeArtifactMemberPointer


class KnowledgeGraphSnapshotPointer(FrozenModel):
    graph_id: str = Field(pattern=r"^graph_[0-9a-f]{32}$")
    graph_snapshot_revision_id: str = Field(pattern=r"^graphrev_[0-9a-f]{32}$")
    manifest_artifact: KnowledgeArtifactMemberPointer
    manifest_sha256: Sha256


class KnowledgeSourceAnchor(FrozenModel):
    anchor_id: AnchorId
    source_revision_id: str = Field(pattern=r"^[a-z][a-z0-9]*rev_[0-9a-f]{32}$")
    artifact_revision_id: str = Field(pattern=r"^rev_[0-9a-f]{32}$")
    member_path: SafeMemberPath
    anchor_kind: Literal[
        "PAGE", "SECTION", "PARAGRAPH", "TABLE", "FIGURE", "EQUATION", "ITEM_ELEMENT"
    ]
    locator: str = Field(min_length=1, max_length=256)
    excerpt_sha256: Sha256

    _text = field_validator("locator")(_safe_text)


class KnowledgeAnalysisRequest(FrozenModel):
    schema_version: Literal["knowledge-analysis-request/1.0"] = "knowledge-analysis-request/1.0"
    analysis_request_id: str = Field(pattern=r"^knowledgeanalysis_[0-9a-f]{32}$")
    source: KnowledgeSourceRevisionPointer
    execution_preset_id: str = Field(pattern=r"^execpreset_[0-9a-f]{32}$")
    execution_preset_revision_id: str = Field(pattern=r"^execpresetrev_[0-9a-f]{32}$")
    execution_preset_sha256: Sha256
    result_schema_ref: Literal["eom://schemas/knowledge/knowledge-analysis-result/1.0"] = (
        "eom://schemas/knowledge/knowledge-analysis-result/1.0"
    )
    prior_graph_snapshot: KnowledgeGraphSnapshotPointer | None
    requested_outputs: tuple[
        Literal[
            "NORMALIZED_MARKDOWN",
            "SOURCE_ANCHORS",
            "NODES",
            "EDGES",
            "COMPONENT_OBSERVATIONS",
        ],
        ...,
    ] = Field(min_length=1, max_length=5)
    general_knowledge_mode: Literal["DISABLED", "AUXILIARY_UNATTRIBUTED"]
    created_at: UtcDatetime

    @model_validator(mode="after")
    def unique_requested_outputs(self) -> KnowledgeAnalysisRequest:
        if len(self.requested_outputs) != len(set(self.requested_outputs)):
            raise ValueError("requested analysis outputs must be unique")
        return self


class ProposedKnowledgeNode(FrozenModel):
    node_id: NodeId
    node_type: KnowledgeNodeType
    stable_key: str = Field(pattern=r"^[a-z0-9][a-z0-9._:-]{0,191}$")
    label: str = Field(min_length=1, max_length=500)
    anchor_ids: tuple[AnchorId, ...] = Field(min_length=1, max_length=32)

    _text = field_validator("label")(_safe_text)


class ProposedKnowledgeEdge(FrozenModel):
    edge_id: str = Field(pattern=r"^kedge_[a-z0-9][a-z0-9_-]{0,63}$")
    edge_type: KnowledgeEdgeType
    from_node_id: NodeId
    to_node_id: NodeId
    confidence_milli: int = Field(ge=0, le=1000)
    anchor_ids: tuple[AnchorId, ...] = Field(min_length=1, max_length=32)


class ProposedKnowledgeClaim(FrozenModel):
    claim_id: str = Field(pattern=r"^claim_[a-z0-9][a-z0-9_-]{0,63}$")
    text: str = Field(min_length=1, max_length=4000)
    anchor_ids: tuple[AnchorId, ...] = Field(min_length=1, max_length=32)

    _text = field_validator("text")(_safe_text)


class KnowledgeComponentObservation(FrozenModel):
    component_id: str = Field(pattern=r"^component_[a-z0-9][a-z0-9_-]{0,63}$")
    kind: Literal["PARAGRAPH", "TABLE", "FIGURE", "EQUATION"]
    anchor_id: AnchorId
    artifact_member: KnowledgeArtifactMemberPointer | None


class KnowledgeAmbiguity(FrozenModel):
    code: str = Field(pattern=r"^[A-Z][A-Z0-9_]{2,63}$")
    description: str = Field(min_length=1, max_length=2000)
    anchor_ids: tuple[AnchorId, ...] = Field(max_length=32)

    _text = field_validator("description")(_safe_text)


class KnowledgeAnalysisResult(FrozenModel):
    schema_version: Literal["knowledge-analysis-result/1.0"] = "knowledge-analysis-result/1.0"
    analysis_request_id: str = Field(pattern=r"^knowledgeanalysis_[0-9a-f]{32}$")
    source_revision_id: str = Field(pattern=r"^[a-z][a-z0-9]*rev_[0-9a-f]{32}$")
    status: Literal["PROPOSED"] = "PROPOSED"
    normalized_markdown: KnowledgeArtifactMemberPointer
    anchors: tuple[KnowledgeSourceAnchor, ...] = Field(min_length=1, max_length=2000)
    nodes: tuple[ProposedKnowledgeNode, ...] = Field(min_length=1, max_length=2000)
    edges: tuple[ProposedKnowledgeEdge, ...] = Field(max_length=5000)
    claims: tuple[ProposedKnowledgeClaim, ...] = Field(max_length=2000)
    component_observations: tuple[KnowledgeComponentObservation, ...] = Field(max_length=2000)
    unresolved_ambiguities: tuple[KnowledgeAmbiguity, ...] = Field(max_length=200)
    completed_at: UtcDatetime
    result_sha256: Sha256

    @model_validator(mode="after")
    def all_proposal_references_resolve(self) -> KnowledgeAnalysisResult:
        if self.normalized_markdown.media_type != "text/markdown" or not (
            self.normalized_markdown.member_path.startswith("normalized/")
        ):
            raise ValueError("normalized Markdown pointer has the wrong media type or member path")
        anchors = {anchor.anchor_id for anchor in self.anchors}
        if len(anchors) != len(self.anchors):
            raise ValueError("source anchor IDs must be unique")
        if any(anchor.source_revision_id != self.source_revision_id for anchor in self.anchors):
            raise ValueError("source anchor revision does not match analyzed source")
        nodes = {node.node_id for node in self.nodes}
        if len(nodes) != len(self.nodes):
            raise ValueError("proposed node IDs must be unique")
        edge_ids = {edge.edge_id for edge in self.edges}
        claim_ids = {claim.claim_id for claim in self.claims}
        component_ids = {item.component_id for item in self.component_observations}
        if len(edge_ids) != len(self.edges) or len(claim_ids) != len(self.claims):
            raise ValueError("proposed edge and claim IDs must be unique")
        if len(component_ids) != len(self.component_observations):
            raise ValueError("component observation IDs must be unique")
        for edge in self.edges:
            if edge.from_node_id not in nodes or edge.to_node_id not in nodes:
                raise ValueError("proposed edge endpoint does not resolve")
            if edge.from_node_id == edge.to_node_id:
                raise ValueError("proposed graph self-edges are not allowed")
        referenced_anchor_sets = [
            *(node.anchor_ids for node in self.nodes),
            *(edge.anchor_ids for edge in self.edges),
            *(claim.anchor_ids for claim in self.claims),
            *((item.anchor_id,) for item in self.component_observations),
            *(item.anchor_ids for item in self.unresolved_ambiguities),
        ]
        if any(not set(references).issubset(anchors) for references in referenced_anchor_sets):
            raise ValueError("proposal source anchor pointer does not resolve")
        return self


class KnowledgeAnalysisSourceArtifactMemberV2(FrozenModel):
    artifact_id: str = Field(pattern=r"^artifact_[0-9a-f]{32}$")
    artifact_revision_id: str = Field(pattern=r"^rev_[0-9a-f]{32}$")
    member_path: CanonicalMemberPath
    materialized_path: AnalysisSourcePath
    sha256: Sha256
    bytes: int = Field(ge=1, le=100 * 1024 * 1024)
    schema_ref: str | None = Field(
        default=None,
        pattern=r"^eom(?:\.assess(?:ment)?|://schemas/)[A-Za-z0-9._/@:-]{1,191}$",
        max_length=256,
    )
    media_type: str = Field(pattern=r"^[a-z0-9.+-]+/[A-Za-z0-9.+-]+$", max_length=128)
    logical_name: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,255}$")


class ContentIntakeKnowledgeSourceV2(FrozenModel):
    source_kind: Literal["CONTENT_INTAKE_FILE"] = "CONTENT_INTAKE_FILE"
    source_class: Literal["CURRICULUM", "TEXTBOOK", "PAST_EXAM", "INTERNAL_GUIDE"]
    intake_batch_id: str = Field(pattern=r"^intake_[0-9a-f]{32}$")
    source_file_id: str = Field(pattern=r"^sourcefile_[0-9a-f]{32}$")
    lifecycle_state: Literal["ELIGIBLE"] = "ELIGIBLE"
    artifact_member: KnowledgeAnalysisSourceArtifactMemberV2


class ApprovedItemKnowledgeSourceV2(FrozenModel):
    source_kind: Literal["APPROVED_ITEM_REVISION"] = "APPROVED_ITEM_REVISION"
    source_class: Literal["APPROVED_ITEM", "PAST_EXAM"]
    item_id: str = Field(pattern=r"^item_[0-9a-f]{32}$")
    item_revision_id: str = Field(pattern=r"^itemrev_[0-9a-f]{32}$")
    lifecycle_state: Literal["APPROVED"] = "APPROVED"
    artifact_member: KnowledgeAnalysisSourceArtifactMemberV2


KnowledgeAnalysisSourceV2 = Annotated[
    ContentIntakeKnowledgeSourceV2 | ApprovedItemKnowledgeSourceV2,
    Field(discriminator="source_kind"),
]


KNOWLEDGE_ANALYSIS_OUTPUTS_V2 = frozenset(
    {
        "NORMALIZED_MARKDOWN",
        "SOURCE_ANCHORS",
        "NODES",
        "EDGES",
        "CLAIMS",
        "COMPONENT_OBSERVATIONS",
        "UNRESOLVED_AMBIGUITIES",
    }
)


class KnowledgeAnalysisRequestV2(FrozenModel):
    schema_version: Literal["knowledge-analysis-request/2.0"] = "knowledge-analysis-request/2.0"
    analysis_request_id: str = Field(pattern=r"^knowledgeanalysis_[0-9a-f]{32}$")
    source: KnowledgeAnalysisSourceV2
    execution_preset_id: str = Field(pattern=r"^execpreset_[0-9a-f]{32}$")
    execution_preset_revision_id: str = Field(pattern=r"^execpresetrev_[0-9a-f]{32}$")
    execution_preset_sha256: Sha256
    worker_proposal_schema_ref: Literal[
        "eom://schemas/knowledge/knowledge-analysis-worker-proposal/1.0"
    ] = "eom://schemas/knowledge/knowledge-analysis-worker-proposal/1.0"
    accepted_result_schema_ref: Literal["eom://schemas/knowledge/knowledge-analysis-result/2.0"] = (
        "eom://schemas/knowledge/knowledge-analysis-result/2.0"
    )
    predecessor_analysis_run_id: str | None = Field(
        default=None, pattern=r"^analysisrun_[0-9a-f]{32}$"
    )
    prior_graph_snapshot: KnowledgeGraphSnapshotPointer | None
    requested_outputs: tuple[
        Literal[
            "NORMALIZED_MARKDOWN",
            "SOURCE_ANCHORS",
            "NODES",
            "EDGES",
            "CLAIMS",
            "COMPONENT_OBSERVATIONS",
            "UNRESOLVED_AMBIGUITIES",
        ],
        ...,
    ] = Field(min_length=7, max_length=7)
    general_knowledge_mode: Literal["DISABLED", "AUXILIARY_UNATTRIBUTED"]
    risk_policy_revision_id: str = Field(pattern=r"^analysisriskrev_[0-9a-f]{32}$")
    created_at: UtcDatetime
    request_sha256: Sha256

    @model_validator(mode="after")
    def exact_outputs_and_hash(self) -> KnowledgeAnalysisRequestV2:
        if set(self.requested_outputs) != KNOWLEDGE_ANALYSIS_OUTPUTS_V2:
            raise ValueError("knowledge analysis V2 requires the complete bounded output set")
        body = self.model_dump(mode="json", exclude={"request_sha256"})
        if content_sha256(body) != self.request_sha256:
            raise ValueError("knowledge analysis request hash does not match canonical content")
        return self


class KnowledgeSourceAnchorV2(FrozenModel):
    anchor_id: AnchorId
    artifact_revision_id: str = Field(pattern=r"^rev_[0-9a-f]{32}$")
    member_path: CanonicalMemberPath
    anchor_kind: Literal[
        "PAGE", "SECTION", "PARAGRAPH", "TABLE", "FIGURE", "EQUATION", "ITEM_ELEMENT"
    ]
    locator: str = Field(min_length=1, max_length=256)
    excerpt_sha256: Sha256

    _text = field_validator("locator")(_safe_text)


class ProposedKnowledgeClaimV2(FrozenModel):
    claim_id: str = Field(pattern=r"^claim_[a-z0-9][a-z0-9_-]{0,63}$")
    text: str = Field(min_length=1, max_length=4000)
    confidence_milli: int = Field(ge=0, le=1000)
    anchor_ids: tuple[AnchorId, ...] = Field(min_length=1, max_length=32)
    general_knowledge_influenced: bool

    _text = field_validator("text")(_safe_text)


class KnowledgeComponentObservationV2(FrozenModel):
    component_id: str = Field(pattern=r"^component_[a-z0-9][a-z0-9_-]{0,63}$")
    kind: Literal["PARAGRAPH", "TABLE", "FIGURE", "EQUATION"]
    anchor_id: AnchorId
    confidence_milli: int = Field(ge=0, le=1000)


class KnowledgeAmbiguityV2(FrozenModel):
    code: str = Field(pattern=r"^[A-Z][A-Z0-9_]{2,63}$")
    description: str = Field(min_length=1, max_length=2000)
    blocking: bool
    anchor_ids: tuple[AnchorId, ...] = Field(max_length=32)

    _text = field_validator("description")(_safe_text)


class KnowledgeAnalysisWorkerProposal(FrozenModel):
    schema_version: Literal["knowledge-analysis-worker-proposal/1.0"] = (
        "knowledge-analysis-worker-proposal/1.0"
    )
    analysis_request_id: str = Field(pattern=r"^knowledgeanalysis_[0-9a-f]{32}$")
    normalized_markdown: str = Field(min_length=1, max_length=262144)
    anchors: tuple[KnowledgeSourceAnchorV2, ...] = Field(min_length=1, max_length=1024)
    nodes: tuple[ProposedKnowledgeNode, ...] = Field(min_length=1, max_length=512)
    edges: tuple[ProposedKnowledgeEdge, ...] = Field(max_length=1024)
    claims: tuple[ProposedKnowledgeClaimV2, ...] = Field(max_length=512)
    component_observations: tuple[KnowledgeComponentObservationV2, ...] = Field(max_length=512)
    unresolved_ambiguities: tuple[KnowledgeAmbiguityV2, ...] = Field(max_length=128)
    general_knowledge_used: bool
    completed_at: UtcDatetime

    _markdown = field_validator("normalized_markdown")(_safe_text)

    @model_validator(mode="after")
    def proposal_references_are_closed(self) -> KnowledgeAnalysisWorkerProposal:
        anchor_ids = [anchor.anchor_id for anchor in self.anchors]
        node_ids = [node.node_id for node in self.nodes]
        edge_ids = [edge.edge_id for edge in self.edges]
        claim_ids = [claim.claim_id for claim in self.claims]
        component_ids = [item.component_id for item in self.component_observations]
        ambiguity_codes = [item.code for item in self.unresolved_ambiguities]
        stable_keys = [node.stable_key for node in self.nodes]
        for values, label in (
            (anchor_ids, "anchor"),
            (node_ids, "node"),
            (stable_keys, "node stable key"),
            (edge_ids, "edge"),
            (claim_ids, "claim"),
            (component_ids, "component"),
            (ambiguity_codes, "ambiguity code"),
        ):
            if len(values) != len(set(values)):
                raise ValueError(f"knowledge proposal {label} identities must be unique")
        anchors = set(anchor_ids)
        nodes = set(node_ids)
        referenced_anchors = [
            *(node.anchor_ids for node in self.nodes),
            *(edge.anchor_ids for edge in self.edges),
            *(claim.anchor_ids for claim in self.claims),
            *((item.anchor_id,) for item in self.component_observations),
            *(item.anchor_ids for item in self.unresolved_ambiguities),
        ]
        if any(not set(values).issubset(anchors) for values in referenced_anchors):
            raise ValueError("knowledge proposal anchor pointer does not resolve")
        for edge in self.edges:
            if edge.from_node_id not in nodes or edge.to_node_id not in nodes:
                raise ValueError("knowledge proposal edge endpoint does not resolve")
            if edge.from_node_id == edge.to_node_id:
                raise ValueError("knowledge proposal self-edges are not allowed")
        influenced = any(claim.general_knowledge_influenced for claim in self.claims)
        if influenced and not self.general_knowledge_used:
            raise ValueError("claim provenance requires general_knowledge_used")
        return self


class KnowledgeProposalCounts(FrozenModel):
    anchors: int = Field(ge=1, le=1024)
    nodes: int = Field(ge=1, le=512)
    edges: int = Field(ge=0, le=1024)
    claims: int = Field(ge=0, le=512)
    component_observations: int = Field(ge=0, le=512)
    ambiguities: int = Field(ge=0, le=128)


class KnowledgeAnalysisRiskPolicy(FrozenModel):
    """Immutable deterministic review policy applied after proposal validation."""

    schema_version: Literal["knowledge-analysis-risk-policy/1.0"] = (
        "knowledge-analysis-risk-policy/1.0"
    )
    risk_policy_revision_id: str = Field(pattern=r"^analysisriskrev_[0-9a-f]{32}$")
    state: Literal["RELEASED"] = "RELEASED"
    minimum_confidence_milli: int = Field(ge=0, le=1000)
    review_source_classes: tuple[
        Literal["CURRICULUM", "TEXTBOOK", "APPROVED_ITEM", "PAST_EXAM", "INTERNAL_GUIDE"],
        ...,
    ] = Field(max_length=5)
    review_when_general_knowledge_used: bool
    review_when_blocking_ambiguity_present: bool
    maximum_auto_accept_counts: KnowledgeProposalCounts
    created_at: UtcDatetime
    content_sha256: Sha256

    @model_validator(mode="after")
    def immutable_policy_is_canonical(self) -> KnowledgeAnalysisRiskPolicy:
        if len(self.review_source_classes) != len(set(self.review_source_classes)):
            raise ValueError("knowledge analysis review source classes must be unique")
        body = self.model_dump(mode="json", exclude={"content_sha256"})
        if content_sha256(body) != self.content_sha256:
            raise ValueError("knowledge analysis risk policy hash does not match canonical content")
        return self


class KnowledgeProposalArtifactMember(FrozenModel):
    artifact_id: str = Field(pattern=r"^artifact_[0-9a-f]{32}$")
    artifact_revision_id: str = Field(pattern=r"^rev_[0-9a-f]{32}$")
    member_path: AnalysisNormalizedPath
    sha256: Sha256
    bytes: int = Field(ge=0, le=2 * 1024 * 1024)
    schema_ref: str = Field(
        pattern=r"^eom://schemas/knowledge/[A-Za-z0-9._/@:-]{1,191}$", max_length=256
    )
    media_type: Literal["text/markdown", "application/x-ndjson", "application/json"]
    logical_name: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,255}$")


class KnowledgeProposalMembers(FrozenModel):
    normalized_markdown: KnowledgeProposalArtifactMember
    anchors: KnowledgeProposalArtifactMember
    nodes: KnowledgeProposalArtifactMember
    edges: KnowledgeProposalArtifactMember
    claims: KnowledgeProposalArtifactMember
    component_observations: KnowledgeProposalArtifactMember
    unresolved_ambiguities: KnowledgeProposalArtifactMember


class KnowledgeAnalysisProposalReceipt(FrozenModel):
    schema_version: Literal["knowledge-analysis-proposal-receipt/1.0"] = (
        "knowledge-analysis-proposal-receipt/1.0"
    )
    analysis_request_id: str = Field(pattern=r"^knowledgeanalysis_[0-9a-f]{32}$")
    source: KnowledgeAnalysisSourceV2
    status: Literal["PROPOSED_VALIDATED"] = "PROPOSED_VALIDATED"
    members: KnowledgeProposalMembers
    counts: KnowledgeProposalCounts
    general_knowledge_used: bool
    minimum_confidence_milli: int | None = Field(default=None, ge=0, le=1000)
    blocking_ambiguity_count: int = Field(ge=0, le=128)
    content_set_sha256: Sha256
    completed_at: UtcDatetime

    @model_validator(mode="after")
    def member_set_is_one_immutable_artifact(self) -> KnowledgeAnalysisProposalReceipt:
        members = list(self.members.__class__.model_fields)
        values = [getattr(self.members, name) for name in members]
        identities = {(value.artifact_id, value.artifact_revision_id) for value in values}
        if len(identities) != 1:
            raise ValueError("proposal members must share one Artifact Revision")
        expected = {
            "normalized_markdown": ("normalized/document.md", "text/markdown"),
            "anchors": ("normalized/anchors.jsonl", "application/x-ndjson"),
            "nodes": ("normalized/nodes.jsonl", "application/x-ndjson"),
            "edges": ("normalized/edges.jsonl", "application/x-ndjson"),
            "claims": ("normalized/claims.jsonl", "application/x-ndjson"),
            "component_observations": (
                "normalized/components.jsonl",
                "application/x-ndjson",
            ),
            "unresolved_ambiguities": (
                "normalized/ambiguities.jsonl",
                "application/x-ndjson",
            ),
        }
        if any(
            (getattr(self.members, name).member_path, getattr(self.members, name).media_type)
            != expected[name]
            for name in members
        ):
            raise ValueError("proposal member path or media type is inconsistent")
        descriptors = [
            {
                "member_path": value.member_path,
                "sha256": value.sha256,
                "bytes": value.bytes,
                "schema_ref": value.schema_ref,
                "media_type": value.media_type,
            }
            for value in sorted(values, key=lambda item: item.member_path)
        ]
        if content_sha256(descriptors) != self.content_set_sha256:
            raise ValueError("proposal content-set hash does not match member descriptors")
        return self


class KnowledgeAnalysisReviewDecision(FrozenModel):
    schema_version: Literal["knowledge-analysis-review-decision/1.0"] = (
        "knowledge-analysis-review-decision/1.0"
    )
    decision_id: str = Field(pattern=r"^analysisdecision_[0-9a-f]{32}$")
    analysis_request_id: str = Field(pattern=r"^knowledgeanalysis_[0-9a-f]{32}$")
    proposal_artifact_id: str = Field(pattern=r"^artifact_[0-9a-f]{32}$")
    proposal_artifact_revision_id: str = Field(pattern=r"^rev_[0-9a-f]{32}$")
    proposal_content_set_sha256: Sha256
    risk_policy_revision_id: str = Field(pattern=r"^analysisriskrev_[0-9a-f]{32}$")
    decision: Literal["APPROVE", "REJECT"]
    decided_by_operator_id: str = Field(pattern=r"^operator_[0-9a-f]{32}$")
    notes: str = Field(min_length=1, max_length=2000)
    decided_at: UtcDatetime
    decision_sha256: Sha256

    _text = field_validator("notes")(_safe_text)

    @model_validator(mode="after")
    def exact_decision_hash(self) -> KnowledgeAnalysisReviewDecision:
        body = self.model_dump(mode="json", exclude={"decision_sha256"})
        if content_sha256(body) != self.decision_sha256:
            raise ValueError("knowledge analysis decision hash does not match canonical content")
        return self


class KnowledgeAnalysisResultV2(FrozenModel):
    schema_version: Literal["knowledge-analysis-result/2.0"] = "knowledge-analysis-result/2.0"
    analysis_result_id: str = Field(pattern=r"^knowledgeanalysisresult_[0-9a-f]{32}$")
    analysis_request_id: str = Field(pattern=r"^knowledgeanalysis_[0-9a-f]{32}$")
    analysis_request_sha256: Sha256
    source: KnowledgeAnalysisSourceV2
    status: Literal["ACCEPTED"] = "ACCEPTED"
    proposal_receipt: KnowledgeProposalArtifactMember
    proposal_content_set_sha256: Sha256
    risk_policy_revision_id: str = Field(pattern=r"^analysisriskrev_[0-9a-f]{32}$")
    acceptance_mode: Literal["AUTO_POLICY", "HUMAN_APPROVED"]
    review_decision: KnowledgeArtifactMemberPointer | None
    counts: KnowledgeProposalCounts
    general_knowledge_used: bool
    minimum_confidence_milli: int | None = Field(default=None, ge=0, le=1000)
    blocking_ambiguity_count: int = Field(ge=0, le=128)
    accepted_at: UtcDatetime
    result_sha256: Sha256

    @model_validator(mode="after")
    def acceptance_is_pointer_only_and_hashed(self) -> KnowledgeAnalysisResultV2:
        if (
            self.proposal_receipt.member_path != "normalized/proposal-receipt.json"
            or self.proposal_receipt.media_type != "application/json"
        ):
            raise ValueError("accepted result requires the exact proposal receipt member")
        human = self.acceptance_mode == "HUMAN_APPROVED"
        if human != (self.review_decision is not None):
            raise ValueError("human acceptance requires one review decision pointer")
        if self.review_decision is not None and (
            self.review_decision.media_type != "application/json"
            or not self.review_decision.member_path.startswith("evidence/")
        ):
            raise ValueError("review decision pointer has the wrong media type or member path")
        body = self.model_dump(mode="json", exclude={"result_sha256"})
        if content_sha256(body) != self.result_sha256:
            raise ValueError("knowledge analysis result hash does not match canonical content")
        return self


class KnowledgeGraphProjections(FrozenModel):
    nodes: KnowledgeArtifactMemberPointer
    edges: KnowledgeArtifactMemberPointer
    curriculum_closure: KnowledgeArtifactMemberPointer | None
    markdown: KnowledgeArtifactMemberPointer
    lexical_index: KnowledgeArtifactMemberPointer

    @model_validator(mode="after")
    def projection_paths_are_isolated(self) -> KnowledgeGraphProjections:
        values = (
            self.nodes,
            self.edges,
            self.curriculum_closure,
            self.markdown,
            self.lexical_index,
        )
        if any(
            value is not None and not value.member_path.startswith("projections/")
            for value in values
        ):
            raise ValueError("graph projections must materialize under projections/")
        return self


class KnowledgeGraphCounts(FrozenModel):
    source_revisions: int = Field(ge=1, le=10000)
    nodes: int = Field(ge=1, le=10_000_000)
    edges: int = Field(ge=0, le=50_000_000)
    anchors: int = Field(ge=1, le=20_000_000)


class KnowledgeGraphSnapshotManifest(FrozenModel):
    schema_version: Literal["knowledge-graph-snapshot-manifest/1.0"] = (
        "knowledge-graph-snapshot-manifest/1.0"
    )
    graph_id: str = Field(pattern=r"^graph_[0-9a-f]{32}$")
    graph_snapshot_revision_id: str = Field(pattern=r"^graphrev_[0-9a-f]{32}$")
    revision_number: int = Field(ge=1)
    previous_graph_snapshot_revision_id: str | None = Field(
        default=None, pattern=r"^graphrev_[0-9a-f]{32}$"
    )
    state: Literal["PUBLISHED"] = "PUBLISHED"
    ontology_version: Literal["education-knowledge-graph/1.0"] = "education-knowledge-graph/1.0"
    publisher_version: str = Field(pattern=r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")
    source_revisions: tuple[KnowledgeSourceRevisionPointer, ...] = Field(
        min_length=1, max_length=10000
    )
    analysis_results: tuple[KnowledgeArtifactMemberPointer, ...] = Field(
        min_length=1, max_length=10000
    )
    projections: KnowledgeGraphProjections
    counts: KnowledgeGraphCounts
    snapshot_sha256: Sha256
    created_at: UtcDatetime

    @model_validator(mode="after")
    def immutable_snapshot_is_coherent(self) -> KnowledgeGraphSnapshotManifest:
        if self.previous_graph_snapshot_revision_id == self.graph_snapshot_revision_id:
            raise ValueError("graph snapshot cannot point to itself as its predecessor")
        source_revisions = [source.revision_id for source in self.source_revisions]
        result_revisions = [result.artifact_revision_id for result in self.analysis_results]
        if len(source_revisions) != len(set(source_revisions)):
            raise ValueError("graph snapshot source revisions must be unique")
        if len(result_revisions) != len(set(result_revisions)):
            raise ValueError("graph snapshot analysis artifacts must be unique")
        if self.counts.source_revisions != len(self.source_revisions):
            raise ValueError("graph source count does not match pinned source revisions")
        return self


class CurriculumRetrievalScope(FrozenModel):
    framework_revision_id: str = Field(pattern=r"^curriculumrev_[0-9a-f]{32}$")
    root_unit_id: str = Field(pattern=r"^currunit_[0-9a-f]{32}$")
    include_descendants: bool


class EvidenceBudget(FrozenModel):
    max_documents: int = Field(ge=1, le=32)
    max_item_revisions: int = Field(ge=0, le=64)
    max_graph_nodes: int = Field(ge=1, le=256)
    max_claims: int = Field(ge=1, le=128)
    max_context_tokens: int = Field(ge=1000, le=32000)


class EducationRetrievalRequest(FrozenModel):
    schema_version: Literal["education-retrieval-request/1.0"] = "education-retrieval-request/1.0"
    retrieval_request_id: str = Field(pattern=r"^retrieval_[0-9a-f]{32}$")
    graph_snapshot: KnowledgeGraphSnapshotPointer
    query_kind: Literal["CURRICULUM_COMPONENTS", "APPROVED_ITEM_STRUCTURE", "ITEM_PREPARATION"]
    curriculum_scope: CurriculumRetrievalScope | None
    topic_keys: tuple[Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9._:-]{0,127}$")], ...] = Field(
        max_length=20
    )
    target_item_revision_id: str | None = Field(default=None, pattern=r"^itemrev_[0-9a-f]{32}$")
    required_item_elements: tuple[
        Literal["paragraph", "table", "image", "equation", "statement_set", "choice"], ...
    ] = Field(max_length=8)
    source_classes: tuple[KnowledgeSourceClass, ...] = Field(min_length=1, max_length=5)
    retrieval_mode: Literal["HYBRID_LOCAL_MULTIHOP"] = "HYBRID_LOCAL_MULTIHOP"
    evidence_budget: EvidenceBudget
    access_policy_revision_id: str = Field(pattern=r"^accessrev_[0-9a-f]{32}$")
    requester_role: Literal["ADMIN", "EDITOR", "REVIEWER", "WORKER"]
    requested_at: UtcDatetime
    request_sha256: Sha256

    @model_validator(mode="after")
    def retrieval_scope_is_explicit(self) -> EducationRetrievalRequest:
        for values, label in (
            (self.topic_keys, "topic keys"),
            (self.required_item_elements, "required item elements"),
            (self.source_classes, "source classes"),
        ):
            if len(values) != len(set(values)):
                raise ValueError(f"retrieval {label} must be unique")
        if self.query_kind in {"CURRICULUM_COMPONENTS", "APPROVED_ITEM_STRUCTURE"} and (
            self.curriculum_scope is None
        ):
            raise ValueError("curriculum retrieval requires a pinned curriculum scope")
        if self.curriculum_scope is None and not self.topic_keys:
            raise ValueError("retrieval requires a curriculum scope or controlled topic keys")
        if self.query_kind == "APPROVED_ITEM_STRUCTURE" and not self.required_item_elements:
            raise ValueError("item structure retrieval requires item element filters")
        return self


class EvidenceEntry(FrozenModel):
    evidence_id: str = Field(pattern=r"^evidenceitem_[0-9a-f]{32}$")
    evidence_kind: Literal["DOCUMENT", "ITEM_REVISION", "CLAIM", "TABLE", "FIGURE", "EQUATION"]
    use: Literal["GROUNDING", "REFERENCE_PATTERN", "AVOID_COPY"]
    source: KnowledgeSourceRevisionPointer
    anchor_ids: tuple[AnchorId, ...] = Field(min_length=1, max_length=32)
    relevance_milli: int = Field(ge=0, le=1000)
    answer_bearing: bool


class EvidenceBundleBudget(FrozenModel):
    document_count: int = Field(ge=0, le=32)
    item_revision_count: int = Field(ge=0, le=64)
    graph_node_count: int = Field(ge=0, le=256)
    claim_count: int = Field(ge=0, le=128)
    estimated_context_tokens: int = Field(ge=0, le=32000)


class EvidenceBundleManifest(FrozenModel):
    schema_version: Literal["evidence-bundle-manifest/1.0"] = "evidence-bundle-manifest/1.0"
    evidence_bundle_id: str = Field(pattern=r"^evidence_[0-9a-f]{32}$")
    evidence_bundle_revision_id: str = Field(pattern=r"^evidencerev_[0-9a-f]{32}$")
    revision_number: int = Field(ge=1)
    retrieval_request_id: str = Field(pattern=r"^retrieval_[0-9a-f]{32}$")
    retrieval_request_sha256: Sha256
    graph_snapshot: KnowledgeGraphSnapshotPointer
    access_policy_revision_id: str = Field(pattern=r"^accessrev_[0-9a-f]{32}$")
    entries: tuple[EvidenceEntry, ...] = Field(min_length=1, max_length=128)
    budget: EvidenceBundleBudget
    manifest_sha256: Sha256
    created_at: UtcDatetime

    @model_validator(mode="after")
    def entries_are_unique_and_counted(self) -> EvidenceBundleManifest:
        identifiers = [entry.evidence_id for entry in self.entries]
        immutable_sources = [
            (
                entry.source.revision_id,
                entry.source.artifact_member.artifact_revision_id,
                entry.source.artifact_member.member_path,
                entry.use,
            )
            for entry in self.entries
        ]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("Evidence Bundle entry IDs must be unique")
        if len(immutable_sources) != len(set(immutable_sources)):
            raise ValueError("Evidence Bundle cannot duplicate an immutable source for one use")
        document_count = sum(entry.evidence_kind == "DOCUMENT" for entry in self.entries)
        item_count = sum(entry.evidence_kind == "ITEM_REVISION" for entry in self.entries)
        claim_count = sum(entry.evidence_kind == "CLAIM" for entry in self.entries)
        if (document_count, item_count, claim_count) != (
            self.budget.document_count,
            self.budget.item_revision_count,
            self.budget.claim_count,
        ):
            raise ValueError("Evidence Bundle counts do not match selected entries")
        return self
