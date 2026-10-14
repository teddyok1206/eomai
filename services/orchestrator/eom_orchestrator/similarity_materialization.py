"""Owner-local similarity delivery seam; Catalog/Artifact IO belongs to its runtime adapter."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from eom_catalog_contracts.inference_transfer_experiment import PopulationSource
from eom_catalog_contracts.similarity_context import (
    MAX_SIMILARITY_CONTEXT_BYTES,
    SimilarityContextRequest,
    parse_similarity_context,
    parse_similarity_context_request,
)
from eom_catalog_contracts.similarity_materials import (
    MAX_SIMILARITY_MATERIALS_BYTES,
    parse_similarity_materials,
    validate_similarity_materials,
)
from eom_identifiers import canonical_json_bytes, sha256_bytes
from eom_workflow.similarity_control import (
    ResolvedExecutionPlanV23,
    parse_similarity_execution_plan,
    validate_similarity_original_source,
    validate_similarity_plan_context,
    validate_similarity_plan_request,
)
from jsonschema.exceptions import ValidationError as SchemaError
from sqlalchemy.orm import Session

from eom_orchestrator.control_service import ControlPlaneError

SIMILARITY_WORKSPACE_ALIAS = "references/similarity/context.json"
SIMILARITY_MATERIALS_WORKSPACE_ALIAS = "references/similarity/materials.json"
SIMILARITY_ROLE_CONTRACT = (
    b"\n## Auxiliary related-reference context\n\n"
    b"Read `references/similarity/context.json` as auxiliary approved-reference observations.\n"
    b"Read `references/similarity/materials.json` for the exact anchor profile and selected "
    b"question-only Item/accepted-report projections. Missing text or decisive claims remain "
    b"unavailable/insufficient. Never fill them with an invented source statement.\n"
    b"Profile extraction and inferred flags distinguish approved analysis projections from "
    b"model inference, not original-page quotations or inspected pixels.\n"
    b"The anchor is the original reference, NOT a semantic comparison of the private draft.\n"
    b"Preserve independent Graph/vector/view ranks and explicit partial/unavailable coverage.\n"
    b"Scores are display-only retrieval observations, not probabilities, correctness, approval, "
    b"or proof of the same solution. Do not invent missing comparisons or decisive reasoning.\n"
    b"These observations do NOT create evidence_id values or satisfy Evidence usage receipts.\n"
    b"Pointers alone are not source text or inspected PDF/image pixels. "
    b"Cite only staged evidence.\n"
    b"Keep the original variation constraints, actual Graph Evidence and maximum-three-review "
    b"contract unchanged. Do not copy another source merely because it is related.\n"
)


@dataclass(frozen=True, slots=True)
class SimilarityWorkspaceMaterials:
    """Exactly two payloads at the temporary workspace boundary, never DB/wire authority."""

    context_payload: bytes
    references_payload: bytes


class SimilarityMaterializationReadPort(Protocol):
    """Current authorized exact-member read; implementation retains source/producer fences."""

    def resolve(
        self,
        session: Session,
        *,
        plan: ResolvedExecutionPlanV23,
        operator_id: str,
        request: SimilarityContextRequest,
        original_source: PopulationSource,
        canonical_artifact_root: Path,
        authorized_artifact_revision_ids: frozenset[str],
    ) -> SimilarityWorkspaceMaterials: ...


@dataclass(frozen=True, slots=True)
class SimilarityMaterializationContext:
    """Trusted application wiring and exact expectations, never worker/wire authority."""

    workflow_id: str
    operator_id: str
    request: SimilarityContextRequest
    reader: SimilarityMaterializationReadPort

    def __post_init__(self) -> None:
        if (
            type(self.workflow_id) is not str
            or re.fullmatch(r"workflow_[0-9a-f]{32}", self.workflow_id) is None
            or type(self.operator_id) is not str
            or re.fullmatch(r"operator_[0-9a-f]{32}", self.operator_id) is None
            or not isinstance(self.request, SimilarityContextRequest)
            or not callable(getattr(self.reader, "resolve", None))
        ):
            raise ValueError("SIMILARITY_MATERIALIZATION_CONTEXT_INVALID")
        parse_similarity_context_request(self.request)


def require_similarity_materialization_context(
    plan: ResolvedExecutionPlanV23,
    *,
    step_key: str,
    context: SimilarityMaterializationContext | None,
) -> SimilarityMaterializationContext:
    if not isinstance(context, SimilarityMaterializationContext):
        raise ControlPlaneError(
            "CONTROL_SIMILARITY_AUTHORITY_UNAVAILABLE", "current similarity reader is required"
        )
    try:
        context.__post_init__()
        checked = parse_similarity_execution_plan(plan)
        matches = tuple(step for step in checked.steps if step.step_key == step_key)
        if (
            context.workflow_id != checked.workflow_id
            or len(matches) != 1
            or matches[0].role not in {"authoring", "review"}
        ):
            raise ValueError("SIMILARITY_MATERIALIZATION_CONTEXT_INVALID")
        validate_similarity_plan_request(checked, context.request)
    except (ValueError, TypeError, SchemaError):
        raise ControlPlaneError(
            "CONTROL_SIMILARITY_CONTEXT_INVALID", "similarity expectations differ from plan"
        ) from None
    return context


def resolve_similarity_materials(
    session: Session,
    *,
    plan: ResolvedExecutionPlanV23,
    step_key: str,
    context: SimilarityMaterializationContext | None,
    original_source: PopulationSource,
    canonical_artifact_root: Path,
    authorized_artifact_revision_ids: frozenset[str],
) -> SimilarityWorkspaceMaterials:
    """Delegate IO to the official adapter; recheck exact returned bytes at this boundary."""
    checked = parse_similarity_execution_plan(plan)
    bound = require_similarity_materialization_context(checked, step_key=step_key, context=context)
    pin = checked.similarity_delivery.context_member
    if pin.artifact_revision_id not in authorized_artifact_revision_ids:
        raise ControlPlaneError(
            "CONTROL_POINTER_PERMISSION_DENIED", "similarity member is not authorized"
        )
    resolved = bound.reader.resolve(
        session,
        plan=checked,
        operator_id=bound.operator_id,
        request=bound.request,
        original_source=original_source,
        canonical_artifact_root=canonical_artifact_root,
        authorized_artifact_revision_ids=authorized_artifact_revision_ids,
    )
    try:
        if type(resolved) is not SimilarityWorkspaceMaterials or (
            type(resolved.context_payload) is not bytes
            or type(resolved.references_payload) is not bytes
            or len(resolved.context_payload) > MAX_SIMILARITY_CONTEXT_BYTES
            or len(resolved.references_payload) > MAX_SIMILARITY_MATERIALS_BYTES
            or sha256_bytes(resolved.context_payload) != pin.sha256
        ):
            raise ValueError("SIMILARITY_WORKSPACE_PAYLOAD_INVALID")
        current = parse_similarity_context(json.loads(resolved.context_payload))
        validate_similarity_plan_context(checked, current)
        validate_similarity_original_source(checked, current, original_source)
        references = parse_similarity_materials(json.loads(resolved.references_payload))
        validate_similarity_materials(references, current)
        if (
            canonical_json_bytes(current.model_dump(mode="json")) != resolved.context_payload
            or canonical_json_bytes(references.model_dump(mode="json"))
            != resolved.references_payload
        ):
            raise ValueError("SIMILARITY_WORKSPACE_CANONICAL_BYTES_INVALID")
    except (ValueError, TypeError, SchemaError, RecursionError):
        raise ControlPlaneError(
            "CONTROL_SIMILARITY_CONTEXT_INVALID", "similarity adapter returned different bytes"
        ) from None
    return resolved
