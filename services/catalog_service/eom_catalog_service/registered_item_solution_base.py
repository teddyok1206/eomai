"""Resolve an accepted registered-Item base for one additive public solution.

The existing Catalog reader owns byte/lifecycle validation. This adapter checks
the pinned base chain and derives role-aware anchors from canonical Item JSON,
not from model-written anchor names or a past-exam occurrence that does not exist.
"""

from __future__ import annotations

import json
import logging
import re
from collections import Counter
from functools import lru_cache
from types import MappingProxyType
from typing import Any

from eom_catalog_contracts import (
    SOLUTION_REFERENCE_NODE_TYPES,
    KnowledgeAnalysisBaseReferenceIndex,
    KnowledgeAnalysisBaseReferenceNode,
    KnowledgeAnalysisProposalReceipt,
    KnowledgeAnalysisRequestV2,
    KnowledgeAnalysisResultV2,
    KnowledgeAnalysisSourceArtifactMemberV2,
    KnowledgeAnalysisWorkerProposal,
    KnowledgeProposalArtifactMember,
    RegisteredItemAcceptedResultArtifactMember,
    RegisteredItemSolutionBasePointer,
    validate_contract,
)
from eom_catalog_contracts.validation import load_schema
from eom_identifiers import content_sha256
from eom_orchestrator.knowledge_analysis_models import KnowledgeAnalysisRunRecord
from eom_orchestrator.models import ArtifactRecord, ArtifactRevisionRecord
from jsonschema import Draft202012Validator
from pydantic import ValidationError
from sqlalchemy.orm import Session

from eom_catalog_service.artifacts import CatalogArtifactReader, CatalogArtifactService
from eom_catalog_service.item_content_contract import read_item_content
from eom_catalog_service.knowledge_proposal_resolution import (
    KnowledgeProposalResolutionError,
    resolve_knowledge_analysis_proposal,
)

_EDITORIAL_PROBLEM_FIELDS = frozenset(
    {"stem", "bottom_stem", "inquiry", "labeled_blocks", "visuals", "statements", "choices"}
)
_BLOCK_SOURCE_FIELDS = (frozenset({"body", "interaction"}), frozenset({"solution"}))
_SOURCE_FIELDS = MappingProxyType(
    {
        "1.0": _BLOCK_SOURCE_FIELDS,
        "1.1": _BLOCK_SOURCE_FIELDS,
        "2.0": (_EDITORIAL_PROBLEM_FIELDS, frozenset({"answer", "explanations"})),
        "3.0": (_EDITORIAL_PROBLEM_FIELDS, frozenset({"answer", "explanations"})),
    }
)
_LOGGER = logging.getLogger(__name__)
_CONCEPTUAL_REFERENCE_TYPES = frozenset({"CONCEPT", "PROCESS", "OBSERVABLE_PROPERTY", "FORMULA"})


class RegisteredItemSolutionReferenceError(ValueError):
    """A valid accepted base cannot express the roles required by a new full report."""

    code = "REGISTERED_ITEM_SOLUTION_REFERENCE_ROLES_UNAVAILABLE"

    def __init__(self) -> None:
        super().__init__(self.code)


class RegisteredItemSolutionAnchorError(RegisteredItemSolutionReferenceError):
    """Model-written locator/excerpt data is unusable, not corrupt Artifact bytes."""

    code = "REGISTERED_ITEM_SOLUTION_ANCHOR_INVALID"

    def __init__(self, message: str) -> None:
        ValueError.__init__(self, message)


@lru_cache(maxsize=1)
def _reference_node_validator() -> Draft202012Validator:
    # Cache only the existing hash-pinned schema, not a validation result or authority.
    return Draft202012Validator(
        load_schema("knowledge-analysis-solution-types-v1")["$defs"]["typedReferenceNode"]
    )


def _compatible_reference_nodes(
    proposal: KnowledgeAnalysisWorkerProposal,
) -> tuple[KnowledgeAnalysisBaseReferenceNode, ...]:
    nodes: list[KnowledgeAnalysisBaseReferenceNode] = []
    excluded: Counter[str] = Counter()
    validator = _reference_node_validator()
    for node in proposal.nodes:
        if node.node_type not in SOLUTION_REFERENCE_NODE_TYPES:
            continue
        value = {"node_id": node.node_id, "node_type": node.node_type}
        if not validator.is_valid(value):
            excluded[node.node_type] += 1
            continue
        try:
            reference = KnowledgeAnalysisBaseReferenceNode.model_validate(value)
        except ValidationError:
            excluded[node.node_type] += 1
            continue
        nodes.append(reference)
    if excluded:
        _LOGGER.warning(
            "REGISTERED_ITEM_SOLUTION_REFERENCE_SUBSET excluded_count=%d excluded_types=%s",
            sum(excluded.values()),
            ",".join(f"{kind}:{count}" for kind, count in sorted(excluded.items())),
        )
    kinds = {node.node_type for node in nodes}
    if "ITEM_ELEMENT" not in kinds or not kinds & _CONCEPTUAL_REFERENCE_TYPES:
        raise RegisteredItemSolutionReferenceError()
    return tuple(sorted(nodes, key=lambda node: node.node_id))


def _json_pointer(value: dict[str, Any], locator: str) -> tuple[str, object]:
    """Strict RFC6901 object/array lookup; no paths, negative indexes or guesses."""

    if not locator.startswith("/"):
        raise ValueError("registered solution anchors require source JSON pointers")
    encoded = locator[1:].split("/")
    if any(re.search(r"~(?![01])", token) for token in encoded):
        raise ValueError("registered solution anchor escape differs")
    tokens = tuple(token.replace("~1", "/").replace("~0", "~") for token in encoded)
    current: object = value
    for token in tokens:
        if isinstance(current, dict) and token in current:
            current = current[token]
        elif isinstance(current, list) and re.fullmatch(r"0|[1-9][0-9]*", token):
            position = int(token)
            if position >= len(current):
                raise ValueError("registered solution anchor array position is absent")
            current = current[position]
        else:
            raise ValueError("registered solution anchor target is absent")
    return tokens[0], current


def registered_item_solution_reference_index(
    request: KnowledgeAnalysisRequestV2,
    proposal: KnowledgeAnalysisWorkerProposal,
    source_value: dict[str, Any],
) -> KnowledgeAnalysisBaseReferenceIndex:
    """O(anchors * bounded pointer depth + nodes log nodes); no copied source body.

    New registered-Item base instructions pin each excerpt to the SHA of the
    canonical JSON value at its locator. Existing accepted bases with other
    locator conventions are explicit incompatible inputs, never rewritten.
    """

    source = request.source
    if source.source_kind != "APPROVED_ITEM_REVISION" or source.source_class != "APPROVED_ITEM":
        raise ValueError("registered solution base source is not a registered Item")
    version = source_value.get("schema_version")
    fields = _SOURCE_FIELDS.get(version) if isinstance(version, str) else None
    if fields is None:
        raise ValueError("registered solution source content version is unsupported")
    problem: set[str] = set()
    answer: set[str] = set()
    for anchor in proposal.anchors:
        if (
            anchor.artifact_revision_id != source.artifact_member.artifact_revision_id
            or anchor.member_path != source.artifact_member.member_path
        ):
            raise ValueError("registered solution anchor does not pin the source member")
        try:
            field, excerpt = _json_pointer(source_value, anchor.locator)
        except ValueError as error:
            raise RegisteredItemSolutionAnchorError(
                "registered solution anchor locator is invalid"
            ) from error
        if excerpt is None or (isinstance(excerpt, str | list | dict) and not excerpt):
            raise RegisteredItemSolutionAnchorError(
                "registered solution anchor has no source content"
            )
        if content_sha256(excerpt) != anchor.excerpt_sha256:
            raise RegisteredItemSolutionAnchorError(
                "registered solution anchor excerpt hash differs"
            )
        if field in fields[0]:
            problem.add(anchor.anchor_id)
        elif field in fields[1]:
            answer.add(anchor.anchor_id)
        else:
            raise RegisteredItemSolutionAnchorError(
                "registered solution anchor has no source-defined content role"
            )
    nodes = _compatible_reference_nodes(proposal)
    value = dict(
        anchor_ids=tuple(sorted(anchor.anchor_id for anchor in proposal.anchors)),
        problem_anchor_ids=tuple(sorted(problem)),
        answer_explanation_anchor_ids=tuple(sorted(answer)),
        nodes=[node.model_dump(mode="json") for node in nodes],
    )
    return KnowledgeAnalysisBaseReferenceIndex.model_validate(
        value | {"index_sha256": content_sha256(value)}
    )


def _read_json(
    artifacts: CatalogArtifactReader,
    pointer: KnowledgeProposalArtifactMember | KnowledgeAnalysisSourceArtifactMemberV2,
) -> dict[str, Any]:
    if pointer.schema_ref is None or pointer.media_type != "application/json":
        raise ValueError("registered solution JSON pointer schema/media is absent")
    raw = artifacts.read_member(
        artifact_id=pointer.artifact_id,
        revision_id=pointer.artifact_revision_id,
        member_path=pointer.member_path,
        sha256=pointer.sha256,
        media_type=pointer.media_type,
        schema_ref=pointer.schema_ref,
        max_bytes=max(1, pointer.bytes),
    )
    if len(raw) != pointer.bytes:
        raise ValueError("registered solution member byte count differs")
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError("registered solution member is not an object")
    return value


def validate_registered_item_solution_proposal(
    artifacts: CatalogArtifactReader,
    *,
    request: KnowledgeAnalysisRequestV2,
    proposal: KnowledgeAnalysisWorkerProposal,
) -> KnowledgeAnalysisBaseReferenceIndex:
    """Check canonical Item bytes before acceptance using the same report-base rule.

    Reader, schema and source-member errors deliberately remain distinct from
    model-written locator/excerpt failures; callers must not suppress authority
    or Artifact integrity failures as a correctable model result.
    """

    source = request.source.artifact_member
    if source.schema_ref is None:
        raise ValueError("registered solution canonical Item schema is absent")
    source_value = _read_json(artifacts, source)
    read_item_content(source.schema_ref, source_value)
    return registered_item_solution_reference_index(request, proposal, source_value)


def resolve_registered_item_solution_base(
    session: Session,
    artifacts: CatalogArtifactService,
    *,
    run: KnowledgeAnalysisRunRecord,
    request: KnowledgeAnalysisRequestV2,
    receipt: KnowledgeAnalysisProposalReceipt,
    receipt_pointer: KnowledgeProposalArtifactMember,
) -> RegisteredItemSolutionBasePointer:
    """Resolve immutable accepted-result -> original receipt -> original members."""

    if (
        run.state != "ACCEPTED"
        or request.source.source_kind != "APPROVED_ITEM_REVISION"
        or run.accepted_result_artifact_id is None
        or run.accepted_result_artifact_revision_id is None
        or run.accepted_result_sha256 is None
    ):
        raise ValueError("registered solution base is not an accepted Item analysis")
    revision = session.get(ArtifactRevisionRecord, run.accepted_result_artifact_revision_id)
    logical = session.get(ArtifactRecord, run.accepted_result_artifact_id)
    if (
        revision is None
        or logical is None
        or not revision.approved
        or not logical.approved
        or revision.logical_artifact_id != run.accepted_result_artifact_id
        or revision.content_hash != run.accepted_result_sha256
        or revision.manifest.get("artifact_type") != "knowledge-analysis-accepted-result"
        or revision.manifest.get("primary_file") != "evidence/accepted-result.json"
    ):
        raise ValueError("registered solution accepted base pointer is stale")
    pointer = RegisteredItemAcceptedResultArtifactMember(
        artifact_id=run.accepted_result_artifact_id,
        artifact_revision_id=run.accepted_result_artifact_revision_id,
        member_path="evidence/accepted-result.json",
        sha256=revision.content_hash,
        bytes=revision.content_bytes,
        logical_name="accepted-result.json",
    )
    value = _read_json(artifacts, pointer)
    validate_contract("knowledge-analysis-result-v2", value)
    accepted = KnowledgeAnalysisResultV2.model_validate(value)
    if (
        value != revision.result
        or accepted.analysis_request_id != request.analysis_request_id
        or accepted.analysis_request_id != run.analysis_request_id
        or accepted.analysis_request_sha256 != run.request_sha256
        or accepted.source != request.source
        or accepted.proposal_receipt != receipt_pointer
        or accepted.proposal_content_set_sha256 != receipt.content_set_sha256
        or accepted.counts != receipt.counts
        or receipt.analysis_request_id != request.analysis_request_id
        or receipt.source != request.source
        # The canonical writer retains six UTC fractional digits; Pydantic's
        # JSON display omits zero microseconds. Compare validated values after
        # the Artifact reader has checked the exact stored bytes and hash.
        or KnowledgeAnalysisProposalReceipt.model_validate(_read_json(artifacts, receipt_pointer))
        != receipt
    ):
        raise ValueError("registered solution accepted base content differs")
    proposal = resolve_knowledge_analysis_proposal(artifacts, receipt)
    if not isinstance(proposal, KnowledgeAnalysisWorkerProposal):
        raise KnowledgeProposalResolutionError("CONTENT_INVALID", "registered base family differs")
    reference_index = validate_registered_item_solution_proposal(
        artifacts, request=request, proposal=proposal
    )
    return RegisteredItemSolutionBasePointer(
        analysis_run_id=run.analysis_run_id,
        analysis_result_id=accepted.analysis_result_id,
        analysis_request_id=accepted.analysis_request_id,
        accepted_result_sha256=accepted.result_sha256,
        accepted_result_artifact=pointer,
        proposal_receipt=receipt_pointer,
        proposal_content_set_sha256=receipt.content_set_sha256,
        base_members=receipt.members,
        base_counts=receipt.counts,
        reference_index=reference_index,
    )
