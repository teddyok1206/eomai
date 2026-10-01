from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from eom_api.services.item_approval_service import ItemApprovalApplicationService
from eom_api.services.query_adapter import QueryAdapter
from eom_catalog_contracts import (
    ApproveItemRevisionCommandV1,
    ItemRevisionApprovalReceiptV1,
    ItemRevisionManifestV2,
    validate_contract,
)
from eom_catalog_service.content_pack_files import compile_pack
from eom_catalog_service.models import ContentPackReleaseRecord
from eom_catalog_service.registry_service import RegistryService
from eom_hwpx_manager.application_service import HwpxApplicationService
from eom_hwpx_manager.errors import HwpxManagerError
from eom_identifiers import content_sha256
from eom_item_registry import (
    ComponentPointer,
    ItemRevisionApprovalMode,
    RegistrationRequest,
    RegistryError,
    RegistryErrorCode,
)
from eom_operator_identity import ActorContext, ActorSource, ActorType, PermissionKey
from eom_workflow import WORKFLOW_ADMISSION_BY_IDENTITY, compile_definition
from pydantic import ValidationError

ROOT = Path(__file__).resolve().parents[2]
PACK_PREDECESSOR = ROOT / "content/packs/generated-knowledge-item/1.20.12"
PACK_SUCCESSOR = ROOT / "content/packs/generated-knowledge-item/1.20.13"


def _registration_request() -> RegistrationRequest:
    return RegistrationRequest(
        mode="CREATE_ITEM",
        registration_key="post-registration-review-test",
        content_pack_release_id="packrel_" + "1" * 32,
        workflow_id="workflow_" + "2" * 32,
        workflow_definition_key="generic-item-development",
        workflow_definition_version="1.16.0",
        source_workflow_step_run_id="steprun_" + "3" * 32,
        source_intake_batch_ids=(),
        item_type_key="eom-template-multiple-choice",
        primary_taxonomy_ref="GENERAL_SCIENCE",
        difficulty_band="보통",
        tag_keys=("EOM_QUESTION_TEMPLATE",),
        metadata_schema_ref="eom://metadata/content-team-item@1.0",
        metadata={"subject": "통합과학"},
        components=(
            ComponentPointer(
                component_type="ITEM_CONTENT",
                ordinal=0,
                schema_ref="eom.assessment.item-content/3.0",
                media_type="application/json",
                artifact_id="artifact_" + "4" * 32,
                artifact_revision_id="rev_" + "5" * 32,
                sha256="sha256:" + "6" * 64,
                logical_name="item-content.json",
            ),
        ),
        approval_mode=ItemRevisionApprovalMode.POST_REGISTRATION_HUMAN_REVIEW,
        created_by="operator_review",
    )


def test_successor_workflow_registers_before_external_human_approval() -> None:
    compiled = compile_definition(
        ROOT / "config/workflows/generic-item-development.v1.16.yaml",
        {"authoring", "image", "review", "item_management"},
    )
    definition = compiled.definition
    assert definition.definition_version == "1.16.0"
    assert compiled.sha256 == (
        "sha256:0bc5ad197679302f21035b551ea2ce93a357a46f43dd3b0815cc64a94fcb20ed"
    )
    assert "human_approval" not in {step.key for step in definition.steps}
    review = next(step for step in definition.steps if step.key == "review")
    registration = next(step for step in definition.steps if step.key == "registration")
    assert review.on_success == "registration"
    assert registration.on_success == "complete"
    assert (
        WORKFLOW_ADMISSION_BY_IDENTITY[("generic-item-development", "1.16.0")].role_protocol_version
        == "workflow-role/1.24.0"
    )


def test_successor_pack_changes_only_immutable_identity_and_compatibility() -> None:
    predecessor = {
        path.relative_to(PACK_PREDECESSOR): path.read_bytes()
        for path in PACK_PREDECESSOR.rglob("*")
        if path.is_file()
    }
    successor = {
        path.relative_to(PACK_SUCCESSOR): path.read_bytes()
        for path in PACK_SUCCESSOR.rglob("*")
        if path.is_file()
    }
    assert predecessor.keys() == successor.keys()
    assert {path for path in predecessor if predecessor[path] != successor[path]} == {
        Path("pack.yaml")
    }
    compiled = compile_pack(PACK_SUCCESSOR)
    assert compiled.manifest.pack.version == "1.20.13"
    assert compiled.source_tree_sha256 == (
        "sha256:fe65db8148e61cb9b93948f990bd3791d58ff84304fb7044e5dfae4e76765448"
    )
    assert compiled.manifest.compatibility.workflow_definitions[0].versions == ("1.16.0",)


def test_post_registration_manifest_is_typed_and_schema_valid() -> None:
    request = _registration_request()
    release = ContentPackReleaseRecord(
        content_pack_release_id=request.content_pack_release_id,
        content_pack_id="contentpack_" + "7" * 32,
        version="1.20.13",
        schema_version="1.1",
        state="RELEASED",
        source_tree_sha256="sha256:" + "8" * 64,
        bundle_sha256="sha256:" + "9" * 64,
        manifest_sha256="sha256:" + "a" * 64,
        bundle_artifact_id="artifact_" + "b" * 32,
        bundle_artifact_revision_id="rev_" + "c" * 32,
        canonical_manifest_json={},
        compatibility_json={},
        lock_version=1,
    )
    manifest = RegistryService._manifest(
        request,
        item_id="item_" + "d" * 32,
        revision_id="itemrev_" + "e" * 32,
        revision_number=1,
        pack=release,
        pack_key="generated-knowledge-item",
        metadata_hash=content_sha256(request.metadata),
        created_at=datetime(2026, 10, 1, tzinfo=UTC),
    )
    validate_contract("item-revision-manifest-v2", manifest)
    parsed = ItemRevisionManifestV2.model_validate(manifest)
    assert parsed.revision_state == "IN_REVIEW"
    assert parsed.approval_policy.required_review_artifact == "VALIDATED_HWPX"


def test_post_registration_mode_is_closed_to_successor_create_item() -> None:
    request = _registration_request()
    with pytest.raises(ValidationError, match="new Item"):
        RegistrationRequest.model_validate(
            request.model_dump(mode="json") | {"mode": "REVISE_ITEM", "item_id": "item_" + "f" * 32}
        )


def test_approval_command_and_receipt_reject_hash_repair() -> None:
    command_body = {
        "operation": "APPROVE_ITEM_REVISION",
        "item_revision_id": "itemrev_" + "1" * 32,
        "expected_revision_version": 1,
        "hwpx_build_id": "hwpxbuild_" + "2" * 32,
        "hwpx_output_artifact_id": "artifact_" + "3" * 32,
        "hwpx_output_artifact_revision_id": "rev_" + "4" * 32,
        "hwpx_output_sha256": "sha256:" + "5" * 64,
        "reason": "검증된 HWPX를 확인했습니다.",
        "approved_by": "operator_review",
        "idempotency_key": "post-registration-approval-key",
    }
    command = ApproveItemRevisionCommandV1.model_validate(
        command_body | {"submission_sha256": content_sha256(command_body)}
    )
    validate_contract("catalog-application-request-v18", command.model_dump(mode="json"))
    with pytest.raises(ValidationError, match="submission hash differs"):
        ApproveItemRevisionCommandV1.model_validate(
            command.model_dump(mode="json") | {"reason": "변조"}
        )

    receipt_body = {
        "schema_version": "item-revision-approval-receipt/1.0",
        "item_id": "item_" + "6" * 32,
        "item_revision_id": command.item_revision_id,
        "item_revision_number": 1,
        "prior_revision_state": "IN_REVIEW",
        "approved_revision_state": "APPROVED",
        "manifest_artifact_id": "artifact_" + "7" * 32,
        "manifest_artifact_revision_id": "rev_" + "8" * 32,
        "manifest_sha256": "sha256:" + "9" * 64,
        "workflow_id": "workflow_" + "a" * 32,
        "registration_step_run_id": "steprun_" + "b" * 32,
        "hwpx_build_id": command.hwpx_build_id,
        "hwpx_output_artifact_id": command.hwpx_output_artifact_id,
        "hwpx_output_artifact_revision_id": command.hwpx_output_artifact_revision_id,
        "hwpx_output_sha256": command.hwpx_output_sha256,
        "approved_by": command.approved_by,
        "approved_at": datetime(2026, 10, 1, tzinfo=UTC).isoformat().replace("+00:00", "Z"),
        "reason_sha256": content_sha256(command.reason),
        "idempotency_key": command.idempotency_key,
        "approval_submission_sha256": command.submission_sha256,
    }
    receipt = ItemRevisionApprovalReceiptV1.model_validate(
        receipt_body | {"receipt_sha256": content_sha256(receipt_body)}
    )
    validate_contract("item-revision-approval-receipt", receipt.model_dump(mode="json"))


def test_hwpx_eligibility_allows_only_current_successor_review_revision() -> None:
    class Registry:
        def inspect_revision(self, _revision_id: str) -> dict[str, Any]:
            return {
                "item_id": "item_" + "1" * 32,
                "revision_state": "IN_REVIEW",
                "workflow_definition_version": "1.16.0",
            }

        def inspect_item(self, _item_id: str) -> dict[str, Any]:
            return {"current_revision_id": "itemrev_" + "2" * 32}

    service = object.__new__(HwpxApplicationService)
    service.registry = Registry()  # type: ignore[assignment]
    revision_id = "itemrev_" + "2" * 32
    assert service._eligible_revision(revision_id)["revision_state"] == "IN_REVIEW"

    class LegacyRegistry(Registry):
        def inspect_revision(self, _revision_id: str) -> dict[str, Any]:
            return {
                "item_id": "item_" + "1" * 32,
                "revision_state": "IN_REVIEW",
                "workflow_definition_version": "1.15.0",
            }

    service.registry = LegacyRegistry()  # type: ignore[assignment]
    with pytest.raises(HwpxManagerError, match="not current and eligible"):
        service._eligible_revision(revision_id)


def test_item_projection_exposes_pending_and_exact_approval_receipt() -> None:
    pending_revision = SimpleNamespace(
        revision_state="IN_REVIEW",
        workflow_definition_version="1.16.0",
        approved_at=None,
        approved_by=None,
    )
    pending = QueryAdapter._approval(pending_revision, None)  # type: ignore[arg-type]
    assert pending.status == "PENDING"
    assert pending.human_review_required is True
    assert pending.approval_receipt_sha256 is None
    assert pending.hwpx_build_id is None

    approved_revision = SimpleNamespace(
        revision_state="APPROVED",
        workflow_definition_version="1.16.0",
        approved_at=datetime(2026, 10, 1, tzinfo=UTC),
        approved_by="operator_review",
    )
    approval_event = SimpleNamespace(
        payload={
            "approval_receipt": {
                "receipt_sha256": "sha256:" + "d" * 64,
                "hwpx_build_id": "hwpxbuild_" + "e" * 32,
            }
        }
    )
    approved = QueryAdapter._approval(  # type: ignore[arg-type]
        approved_revision,
        approval_event,
    )
    assert approved.status == "APPROVED"
    assert approved.approval_receipt_sha256 == "sha256:" + "d" * 64
    assert approved.hwpx_build_id == "hwpxbuild_" + "e" * 32


def test_catalog_approval_rejects_output_from_another_hwpx_build() -> None:
    body = {
        "operation": "APPROVE_ITEM_REVISION",
        "item_revision_id": "itemrev_" + "1" * 32,
        "expected_revision_version": 1,
        "hwpx_build_id": "hwpxbuild_" + "2" * 32,
        "hwpx_output_artifact_id": "artifact_" + "3" * 32,
        "hwpx_output_artifact_revision_id": "rev_" + "4" * 32,
        "hwpx_output_sha256": "sha256:" + "5" * 64,
        "reason": "검증된 HWPX를 확인했습니다.",
        "approved_by": "operator_review",
        "idempotency_key": "post-registration-output-key",
    }
    command = ApproveItemRevisionCommandV1.model_validate(
        body | {"submission_sha256": content_sha256(body)}
    )
    revision = SimpleNamespace(item_revision_id=command.item_revision_id)
    artifact = SimpleNamespace(approved=True, artifact_type="hwpx-content-team-build")
    output = SimpleNamespace(
        approved=True,
        logical_artifact_id=command.hwpx_output_artifact_id,
        content_hash=command.hwpx_output_sha256,
        manifest={
            "manifest_version": "content-team-hwpx-artifact/1.0",
            "artifact_type": "hwpx-content-team-build",
            "primary_file": "content-team-item.hwpx",
            "content_hash": command.hwpx_output_sha256,
        },
        result={
            "builder_result": {
                "status": "SUCCEEDED",
                "build_id": command.hwpx_build_id,
                "item_revision_id": command.item_revision_id,
                "output_sha256": command.hwpx_output_sha256,
            }
        },
    )
    RegistryService._require_hwpx_approval_output(  # type: ignore[arg-type]
        revision=revision,
        artifact=artifact,
        output=output,
        command=command,
    )
    output.result["builder_result"]["build_id"] = "hwpxbuild_" + "f" * 32
    with pytest.raises(RegistryError) as captured:
        RegistryService._require_hwpx_approval_output(  # type: ignore[arg-type]
            revision=revision,
            artifact=artifact,
            output=output,
            command=command,
        )
    assert captured.value.code == RegistryErrorCode.ITEM_APPROVAL_HWPX_INVALID


def test_api_approval_service_binds_exact_successful_hwpx_build() -> None:
    class Hwpx:
        @staticmethod
        def get_build(_build_id: str) -> SimpleNamespace:
            return SimpleNamespace(
                item_revision_id="itemrev_" + "1" * 32,
                state="SUCCEEDED",
                validation_state="PASS",
                output_artifact_id="artifact_" + "2" * 32,
                output_artifact_revision_id="rev_" + "3" * 32,
                output_sha256="sha256:" + "4" * 64,
            )

    class Catalog:
        command: ApproveItemRevisionCommandV1 | None = None

        def approve_item_revision(
            self, command: ApproveItemRevisionCommandV1
        ) -> ItemRevisionApprovalReceiptV1:
            self.command = command
            return SimpleNamespace(item_revision_id=command.item_revision_id)  # type: ignore[return-value]

    catalog = Catalog()
    service = ItemApprovalApplicationService(hwpx=Hwpx(), catalog=catalog)  # type: ignore[arg-type]
    service.approve(
        "itemrev_" + "1" * 32,
        hwpx_build_id="hwpxbuild_" + "5" * 32,
        reason="HWPX 검토 완료",
        expected_revision_version=1,
        actor=ActorContext(
            actor_type=ActorType.OPERATOR,
            operator_id="operator_" + "6" * 32,
            session_id="apisession_" + "7" * 32,
            request_id="post-registration-approval-test",
            authentication_time=datetime(2026, 10, 1, tzinfo=UTC),
            permissions=frozenset({PermissionKey.WORKFLOW_APPROVE}),
            source=ActorSource.APPLICATION_API,
        ),
        idempotency_key="post-registration-approval-key",
    )
    assert catalog.command is not None
    assert catalog.command.hwpx_output_artifact_revision_id == "rev_" + "3" * 32
