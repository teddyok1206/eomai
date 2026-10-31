"""Exact public-solution role handoff; IO and current authority belong to Catalog."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from eom_catalog_contracts.inference_transfer_experiment import PopulationSource
from eom_catalog_contracts.public_similarity_materials import (
    parse_public_similarity_materials,
    validate_public_similarity_materials,
)
from eom_catalog_contracts.registered_public_solution_similarity import (
    SupportedPublicSolutionSimilarityRequest,
    parse_supported_public_solution_similarity_context,
    parse_supported_public_solution_similarity_request,
)
from eom_catalog_contracts.similarity_context import MAX_SIMILARITY_CONTEXT_BYTES
from eom_catalog_contracts.similarity_materials import MAX_SIMILARITY_MATERIALS_BYTES
from eom_identifiers import canonical_json_bytes, sha256_bytes
from eom_workflow.public_similarity_control import (
    SupportedPublicSimilarityExecutionPlan,
    parse_public_similarity_execution_plan,
    validate_public_similarity_original_source,
    validate_public_similarity_plan_context,
    validate_public_similarity_plan_request,
)
from jsonschema.exceptions import ValidationError as SchemaError
from sqlalchemy.orm import Session

from eom_orchestrator.control_service import ControlPlaneError
from eom_orchestrator.similarity_materialization import SimilarityWorkspaceMaterials

PUBLIC_SIMILARITY_ROLE_CONTRACT = (
    b"\n## Auxiliary public-solution references\n\n"
    b"Read `references/similarity/context.json` for pinned related-reference observations, "
    b"and `references/similarity/materials.json` for exact question-only text and verifiable "
    b"public solution text. This is NOT an inference-profile document or a full report.\n"
    b"Question UNAVAILABLE remains unavailable; never invent source text. Text-only access "
    b"does not mean PDF/image pixels were inspected. Preserve source/revision/report identity.\n"
    b"The anchor is the original PAST_EXAM reference, not a comparison of the private draft. "
    b"Rank/score/partial coverage are retrieval observations, not probabilities, correctness, "
    b"approval or proof of the same solution. Do not copy a related source.\n"
    b"These references create no evidence_id and do not replace actual Graph Evidence or "
    b"Evidence usage receipts. Cite only staged material and distinguish inference from text.\n"
    b"Preserve the original ordinary/variation instructions and maximum-three-review contract. "
    b"Authoring and every review attempt must use these same exact pinned references.\n"
)


class PublicSimilarityMaterializationReadPort(Protocol):
    def resolve(
        self,
        session: Session,
        *,
        plan: SupportedPublicSimilarityExecutionPlan,
        operator_id: str,
        request: SupportedPublicSolutionSimilarityRequest,
        original_source: PopulationSource,
        canonical_artifact_root: Path,
        authorized_artifact_revision_ids: frozenset[str],
    ) -> SimilarityWorkspaceMaterials: ...


@dataclass(frozen=True, slots=True)
class PublicSimilarityMaterializationContext:
    workflow_id: str
    operator_id: str
    request: SupportedPublicSolutionSimilarityRequest
    reader: PublicSimilarityMaterializationReadPort

    def __post_init__(self) -> None:
        if (
            type(self.workflow_id) is not str
            or re.fullmatch(r"workflow_[0-9a-f]{32}", self.workflow_id) is None
            or type(self.operator_id) is not str
            or re.fullmatch(r"operator_[0-9a-f]{32}", self.operator_id) is None
            or not callable(getattr(self.reader, "resolve", None))
        ):
            raise ValueError("PUBLIC_SIMILARITY_MATERIALIZATION_CONTEXT_INVALID")
        parse_supported_public_solution_similarity_request(self.request)


def require_public_similarity_materialization_context(
    plan: SupportedPublicSimilarityExecutionPlan,
    *,
    step_key: str,
    context: PublicSimilarityMaterializationContext | None,
) -> PublicSimilarityMaterializationContext:
    if not isinstance(context, PublicSimilarityMaterializationContext):
        raise ControlPlaneError(
            "CONTROL_SIMILARITY_AUTHORITY_UNAVAILABLE", "current public reader is required"
        )
    try:
        context.__post_init__()
        checked = parse_public_similarity_execution_plan(plan)
        matches = tuple(step for step in checked.steps if step.step_key == step_key)
        if (
            context.workflow_id != checked.workflow_id
            or len(matches) != 1
            or matches[0].role not in {"authoring", "review"}
        ):
            raise ValueError("PUBLIC_SIMILARITY_ROLE_MISMATCH")
        validate_public_similarity_plan_request(checked, context.request)
    except (ValueError, TypeError, SchemaError):
        raise ControlPlaneError(
            "CONTROL_SIMILARITY_CONTEXT_INVALID", "public role expectations differ"
        ) from None
    return context


def resolve_public_similarity_materials(
    session: Session,
    *,
    plan: SupportedPublicSimilarityExecutionPlan,
    step_key: str,
    context: PublicSimilarityMaterializationContext | None,
    original_source: PopulationSource,
    canonical_artifact_root: Path,
    authorized_artifact_revision_ids: frozenset[str],
) -> SimilarityWorkspaceMaterials:
    checked = parse_public_similarity_execution_plan(plan)
    bound = require_public_similarity_materialization_context(
        checked, step_key=step_key, context=context
    )
    pin = checked.similarity_delivery.context_member
    if pin.artifact_revision_id not in authorized_artifact_revision_ids:
        raise ControlPlaneError("CONTROL_POINTER_PERMISSION_DENIED", "public member not allowed")
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
            raise ValueError("PUBLIC_SIMILARITY_PAYLOAD_INVALID")
        current = parse_supported_public_solution_similarity_context(
            json.loads(resolved.context_payload)
        )
        validate_public_similarity_plan_context(checked, current)
        validate_public_similarity_original_source(checked, current, original_source)
        materials = parse_public_similarity_materials(json.loads(resolved.references_payload))
        validate_public_similarity_materials(materials, current)
        if (
            canonical_json_bytes(current.model_dump(mode="json")) != resolved.context_payload
            or canonical_json_bytes(materials.model_dump(mode="json"))
            != resolved.references_payload
        ):
            raise ValueError("PUBLIC_SIMILARITY_CANONICAL_BYTES_INVALID")
    except (ValueError, TypeError, SchemaError, RecursionError):
        raise ControlPlaneError(
            "CONTROL_SIMILARITY_CONTEXT_INVALID", "public reader returned different bytes"
        ) from None
    return resolved
