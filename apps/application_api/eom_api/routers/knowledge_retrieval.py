"""Bounded ADMIN retrieval commands and pointer-only Evidence Bundle projection."""

from __future__ import annotations

from typing import Literal

from eom_api_contracts import (
    CommandResult,
    CreateEvidenceBundleRequest,
    EvidenceBundleView,
    SingleResponse,
)
from eom_catalog_contracts import (
    CreateEvidenceBundleCommand,
    CurriculumRetrievalScope,
    EvidenceBudget,
)
from eom_identifiers import content_sha256
from eom_operator_identity import PermissionKey, RoleKey
from fastapi import APIRouter, Depends, Request

from eom_api.dependencies import Auth, IdempotencyKey, require_permission
from eom_api.routers.common import one, run_command

router = APIRouter(tags=["knowledge-retrieval"])


@router.post(
    "/knowledge-retrievals",
    operation_id="knowledge_retrieval_create",
    status_code=201,
    response_model=SingleResponse[CommandResult],
    dependencies=[
        Depends(
            require_permission(PermissionKey.KNOWLEDGE_GRAPH_RETRIEVE, fresh=True, admin_only=True)
        )
    ],
)
def create_evidence_bundle(
    request: Request,
    body: CreateEvidenceBundleRequest,
    authentication: Auth,
    idempotency_key: IdempotencyKey,
) -> SingleResponse[CommandResult]:
    def execute() -> CommandResult:
        actor = request.state.request_context.actor()
        submission_key = request.app.state.services.idempotency.submission_key(
            operator_id=actor.actor_id,
            endpoint_key="knowledge_retrieval_create",
            raw_key=idempotency_key,
        )
        command_value = {
            "operation": "CREATE_EVIDENCE_BUNDLE",
            "graph_snapshot_revision_id": body.graph_snapshot_revision_id,
            "query_kind": body.query_kind,
            "curriculum_scope": (
                CurriculumRetrievalScope.model_validate(
                    body.curriculum_scope.model_dump(mode="json")
                ).model_dump(mode="json")
                if body.curriculum_scope is not None
                else None
            ),
            "topic_keys": list(body.topic_keys),
            "target_item_revision_id": body.target_item_revision_id,
            "required_item_elements": list(body.required_item_elements),
            "source_classes": list(body.source_classes),
            "evidence_budget": EvidenceBudget.model_validate(
                body.evidence_budget.model_dump(mode="json")
            ).model_dump(mode="json"),
            "access_policy_revision_id": body.access_policy_revision_id,
            "requester_role": _requester_role(authentication),
            "requester_permission_keys": sorted(
                permission.value for permission in authentication.permissions
            ),
            "requested_by": actor.actor_id,
        }
        command = CreateEvidenceBundleCommand(
            **command_value,
            idempotency_key=submission_key,
            submission_sha256=content_sha256(command_value),
        )
        result = request.app.state.services.catalog_application.create_evidence_bundle(command)
        return CommandResult(
            command_id=f"knowledge-retrieval-{result.retrieval_request_id}",
            resource_type="evidence_bundle",
            resource_id=result.evidence_bundle_id,
            status="COMPLETED",
            resource_version=1,
            status_url=f"/api/v1/evidence-bundles/{result.evidence_bundle_id}",
        )

    return one(
        request,
        run_command(
            request,
            raw_key=idempotency_key,
            body=body.model_dump(mode="json"),
            resource_type="evidence_bundle",
            callback=execute,
            response_status=201,
        ),
    )


@router.get(
    "/evidence-bundles/{evidence_bundle_id}",
    operation_id="evidence_bundle_get",
    response_model=SingleResponse[EvidenceBundleView],
    dependencies=[
        Depends(require_permission(PermissionKey.KNOWLEDGE_GRAPH_READ, fresh=True, admin_only=True))
    ],
)
def get_evidence_bundle(
    request: Request, evidence_bundle_id: str
) -> SingleResponse[EvidenceBundleView]:
    return one(request, request.app.state.services.queries.evidence_bundle(evidence_bundle_id))


def _requester_role(authentication: Auth) -> Literal["ADMIN", "EDITOR", "REVIEWER", "WORKER"]:
    roles = set(authentication.operator.roles)
    if RoleKey.ADMIN in roles:
        return "ADMIN"
    if RoleKey.EDITOR in roles:
        return "EDITOR"
    if RoleKey.REVIEWER in roles:
        return "REVIEWER"
    return "WORKER"
