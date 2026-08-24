from __future__ import annotations

import os
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest
from eom_api.services.catalog_application_client import (
    CatalogApplicationClient,
    CatalogApplicationClientError,
)
from eom_catalog_contracts import (
    AssessmentItemContent,
    CatalogApplicationErrorCode,
    CatalogApplicationRequest,
    CatalogApplicationResponse,
    CreateEvidenceBundleCommand,
    CreateItemProductionEvidenceCommand,
    CreateKnowledgeAnalysisCommand,
    EvidenceBundlePublicationResult,
    EvidenceBundlePublicationResultV2,
    KnowledgeAnalysisApplicationResult,
    ReviewedItemContentImportCommand,
    validate_contract,
)
from eom_catalog_service.application_server import CatalogApplicationServer
from eom_identifiers import content_sha256

from tests.unit.test_assessment_item_content import item_content


class FakeImports:
    def import_reviewed(self, *_args: object, **_kwargs: object) -> SimpleNamespace:
        return SimpleNamespace(
            item_id="item_" + "1" * 32,
            item_revision_id="itemrev_" + "2" * 32,
            resource_version=1,
            content_artifact_id="artifact_" + "3" * 32,
            content_artifact_revision_id="rev_" + "4" * 32,
            content_sha256="sha256:" + "5" * 64,
        )


class FakeRegistry:
    def load_item_content(self, _revision_id: str) -> AssessmentItemContent:
        return AssessmentItemContent.model_validate(item_content())


class FakeKnowledgeAnalysis:
    def create(self, _command: object) -> KnowledgeAnalysisApplicationResult:
        return KnowledgeAnalysisApplicationResult(
            analysis_run_id="analysisrun_" + "7" * 32,
            workflow_id="workflow_" + "8" * 32,
            state="QUEUED",
            resource_version=3,
        )

    reconcile = create
    review = create


class FakeKnowledgeRetrieval:
    def create(self, command: object) -> EvidenceBundlePublicationResult:
        assert isinstance(command, CreateEvidenceBundleCommand)
        value = {
            "schema_version": "evidence-bundle-publication-result/1.0",
            "evidence_bundle_id": "evidence_" + "1" * 32,
            "evidence_bundle_revision_id": "evidencerev_" + "2" * 32,
            "revision_number": 1,
            "state": "PUBLISHED",
            "retrieval_request_id": "retrieval_" + "3" * 32,
            "retrieval_request_sha256": "sha256:" + "4" * 64,
            "graph_snapshot": {
                "graph_id": "graph_" + "5" * 32,
                "graph_snapshot_revision_id": command.graph_snapshot_revision_id,
                "manifest_artifact": {
                    "artifact_id": "artifact_" + "6" * 32,
                    "artifact_revision_id": "rev_" + "7" * 32,
                    "sha256": "sha256:" + "8" * 64,
                    "schema_ref": ("eom://schemas/knowledge/knowledge-graph-snapshot-manifest/2.0"),
                    "media_type": "application/json",
                    "logical_name": "manifest.json",
                    "member_path": "projections/manifest.json",
                },
                "manifest_sha256": "sha256:" + "8" * 64,
            },
            "access_policy_revision_id": command.access_policy_revision_id,
            "access_policy_sha256": "sha256:" + "9" * 64,
            "manifest_artifact": {
                "artifact_id": "artifact_" + "a" * 32,
                "artifact_revision_id": "rev_" + "b" * 32,
                "sha256": "sha256:" + "c" * 64,
                "schema_ref": "eom://schemas/knowledge/evidence-bundle-manifest/2.0",
                "media_type": "application/json",
                "logical_name": "manifest.json",
                "member_path": "evidence/manifest.json",
            },
            "manifest_sha256": "sha256:" + "d" * 64,
            "budget": {
                "document_count": 1,
                "item_revision_count": 0,
                "graph_node_count": 1,
                "claim_count": 0,
                "estimated_context_tokens": 128,
            },
            "published_at": "2026-08-24T00:00:00Z",
            "result_sha256": "sha256:" + "0" * 64,
        }
        value["result_sha256"] = content_sha256(
            {key: item for key, item in value.items() if key != "result_sha256"}
        )
        return EvidenceBundlePublicationResult.model_validate(value)

    def create_item_production(
        self, command: CreateItemProductionEvidenceCommand
    ) -> EvidenceBundlePublicationResultV2:
        legacy_command = _retrieval_command()
        base = self.create(legacy_command)
        value = {
            **base.model_dump(mode="json", exclude={"schema_version", "result_sha256"}),
            "schema_version": "evidence-bundle-publication-result/2.0",
            "access_policy_revision_id": command.access_policy_revision_id,
            "access_policy_sha256": command.access_policy_sha256,
            "requester_permissions_sha256": content_sha256(
                {"permission_keys": list(command.requester_permission_keys)}
            ),
            "context_artifact": {
                "artifact_id": "artifact_" + "e" * 32,
                "artifact_revision_id": "rev_" + "e" * 32,
                "sha256": "sha256:" + "e" * 64,
                "schema_ref": "eom://schemas/knowledge/evidence-bundle-context/1.0",
                "media_type": "text/markdown",
                "logical_name": "context.md",
                "member_path": "evidence/context.md",
            },
            "result_sha256": "sha256:" + "0" * 64,
        }
        value["result_sha256"] = content_sha256(
            {key: item for key, item in value.items() if key != "result_sha256"}
        )
        return EvidenceBundlePublicationResultV2.model_validate(value)


def _retrieval_command() -> CreateEvidenceBundleCommand:
    value = {
        "operation": "CREATE_EVIDENCE_BUNDLE",
        "graph_snapshot_revision_id": "graphrev_" + "e" * 32,
        "query_kind": "ITEM_PREPARATION",
        "curriculum_scope": None,
        "topic_keys": ["earth.plate-boundary"],
        "target_item_revision_id": None,
        "required_item_elements": [],
        "source_classes": ["TEXTBOOK"],
        "evidence_budget": {
            "max_documents": 2,
            "max_item_revisions": 0,
            "max_graph_nodes": 8,
            "max_claims": 2,
            "max_context_tokens": 2000,
        },
        "access_policy_revision_id": "accessrev_" + "f" * 32,
        "requester_role": "ADMIN",
        "requester_permission_keys": ["knowledge_graph:read", "knowledge_graph:retrieve"],
        "requested_by": "operator_" + "1" * 32,
        "idempotency_key": "knowledge-retrieval-round-trip",
        "submission_sha256": "sha256:" + "0" * 64,
    }
    value["submission_sha256"] = content_sha256(
        {
            key: item
            for key, item in value.items()
            if key not in {"idempotency_key", "submission_sha256"}
        }
    )
    return CreateEvidenceBundleCommand.model_validate(value)


def _item_evidence_command() -> CreateItemProductionEvidenceCommand:
    value = {
        "operation": "CREATE_ITEM_PRODUCTION_EVIDENCE",
        "requirement": {
            "schema_version": "educational-retrieval-requirement/1.0",
            "corpus_key": "science-core",
            "query_kind": "ITEM_PREPARATION",
            "curriculum_root_key": "earth.plate-boundary",
            "topic_keys": ["earth.plate-boundary"],
            "required_item_elements": ["statement_set", "table"],
            "source_classes": ["APPROVED_ITEM", "TEXTBOOK"],
        },
        "evidence_budget": {
            "max_documents": 2,
            "max_item_revisions": 2,
            "max_graph_nodes": 8,
            "max_claims": 2,
            "max_context_tokens": 2000,
        },
        "access_policy_revision_id": "accessrev_" + "f" * 32,
        "access_policy_sha256": "sha256:" + "f" * 64,
        "requester_role": "ADMIN",
        "requester_permission_keys": ["knowledge_graph:read", "knowledge_graph:retrieve"],
        "requested_by": "operator_" + "1" * 32,
        "idempotency_key": "item-production-evidence-round-trip",
        "submission_sha256": "sha256:" + "0" * 64,
    }
    value["submission_sha256"] = content_sha256(
        {
            key: item
            for key, item in value.items()
            if key not in {"idempotency_key", "submission_sha256"}
        }
    )
    return CreateItemProductionEvidenceCommand.model_validate(value)


def _server(tmp_path: Path, *, allowed_uid: int | None = None) -> CatalogApplicationServer:
    runtime = tmp_path / "runtime"
    runtime.mkdir(mode=0o750)
    runtime.chmod(0o750)
    return CatalogApplicationServer(  # type: ignore[arg-type]
        FakeImports(),
        FakeRegistry(),
        FakeKnowledgeAnalysis(),
        FakeKnowledgeRetrieval(),
        socket_path=runtime / "manager.sock",
        allowed_uid=os.getuid() if allowed_uid is None else allowed_uid,
        expected_uid=os.getuid(),
        expected_gid=os.getgid(),
    )


def _client(server: CatalogApplicationServer) -> CatalogApplicationClient:
    return CatalogApplicationClient(
        server.socket_path,
        expected_uid=os.getuid(),
        expected_gid=os.getgid(),
    )


def test_catalog_application_contract_validates_schema_and_typed_models() -> None:
    command = ReviewedItemContentImportCommand(
        base_revision_id="itemrev_" + "6" * 32,
        expected_version=1,
        reviewed_by="operator_test_admin",
        review_reason="검토된 구조화 문항과 모든 포인터를 승인합니다.",
        content=AssessmentItemContent.model_validate(item_content()),
    )
    request = CatalogApplicationRequest(root=command).model_dump(mode="json")
    validate_contract("catalog-application-request", request)
    response = CatalogApplicationResponse(
        status="OK",
        operation="GET_ITEM_CONTENT",
        content=AssessmentItemContent.model_validate(item_content()),
    ).model_dump(mode="json", exclude_none=True)
    validate_contract("catalog-application-response", response)

    analysis_command = CreateKnowledgeAnalysisCommand(
        source={
            "source_kind": "CONTENT_INTAKE_FILE",
            "source_class": "TEXTBOOK",
            "intake_batch_id": "intake_" + "1" * 32,
            "source_file_id": "sourcefile_" + "2" * 32,
        },
        preset_key="knowledge-analysis",
        general_knowledge_mode="DISABLED",
        risk_policy_revision_id="analysisriskrev_" + "3" * 32,
        requested_by="operator_test_admin",
        idempotency_key="knowledge-analysis-contract-key",
    )
    analysis_request = CatalogApplicationRequest(root=analysis_command).model_dump(mode="json")
    validate_contract("catalog-application-request-v2", analysis_request)
    analysis_response = CatalogApplicationResponse(
        status="OK",
        operation="CREATE_KNOWLEDGE_ANALYSIS",
        analysis=FakeKnowledgeAnalysis().create(analysis_command),
    ).model_dump(mode="json", exclude_none=True)
    validate_contract("catalog-application-response-v2", analysis_response)

    retrieval_command = _retrieval_command()
    retrieval_request = CatalogApplicationRequest(root=retrieval_command).model_dump(mode="json")
    validate_contract("catalog-application-request-v3", retrieval_request)
    retrieval_response = CatalogApplicationResponse(
        status="OK",
        operation="CREATE_EVIDENCE_BUNDLE",
        evidence=FakeKnowledgeRetrieval().create(retrieval_command),
    ).model_dump(mode="json", exclude_none=True)
    validate_contract("catalog-application-response-v3", retrieval_response)
    item_command = _item_evidence_command()
    item_request = CatalogApplicationRequest(root=item_command).model_dump(mode="json")
    validate_contract("catalog-application-request-v4", item_request)
    item_response = CatalogApplicationResponse(
        status="OK",
        operation="CREATE_ITEM_PRODUCTION_EVIDENCE",
        item_production_evidence=FakeKnowledgeRetrieval().create_item_production(item_command),
    ).model_dump(mode="json", exclude_none=True)
    validate_contract("catalog-application-response-v4", item_response)


def test_catalog_socket_round_trip_preserves_typed_content_and_import_result(
    tmp_path: Path,
) -> None:
    server = _server(tmp_path)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        client = _client(server)
        imported = client.import_reviewed(
            ReviewedItemContentImportCommand(
                base_revision_id="itemrev_" + "6" * 32,
                expected_version=1,
                reviewed_by="operator_test_admin",
                review_reason="검토된 구조화 문항과 모든 포인터를 승인합니다.",
                content=AssessmentItemContent.model_validate(item_content()),
            )
        )
        assert imported.item_revision_id == "itemrev_" + "2" * 32
        loaded = client.load_item_content("itemrev_" + "2" * 32)
        assert loaded == AssessmentItemContent.model_validate(item_content())
        analysis = client.create_knowledge_analysis(
            CreateKnowledgeAnalysisCommand(
                source={
                    "source_kind": "CONTENT_INTAKE_FILE",
                    "source_class": "TEXTBOOK",
                    "intake_batch_id": "intake_" + "1" * 32,
                    "source_file_id": "sourcefile_" + "2" * 32,
                },
                preset_key="knowledge-analysis",
                general_knowledge_mode="DISABLED",
                risk_policy_revision_id="analysisriskrev_" + "3" * 32,
                requested_by="operator_test_admin",
                idempotency_key="knowledge-analysis-round-trip",
            )
        )
        assert analysis.analysis_run_id == "analysisrun_" + "7" * 32
        evidence = client.create_evidence_bundle(_retrieval_command())
        assert evidence.evidence_bundle_revision_id == "evidencerev_" + "2" * 32
        assert evidence.graph_snapshot.graph_snapshot_revision_id == "graphrev_" + "e" * 32
        item_evidence = client.create_item_production_evidence(_item_evidence_command())
        assert item_evidence.context_artifact.member_path == "evidence/context.md"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_catalog_socket_rejects_wrong_peer_and_unsafe_socket_metadata(tmp_path: Path) -> None:
    server = _server(tmp_path, allowed_uid=os.getuid() + 1)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with pytest.raises(CatalogApplicationClientError) as raised:
            _client(server).load_item_content("itemrev_" + "2" * 32)
        assert (
            raised.value.code == CatalogApplicationErrorCode.CATALOG_APPLICATION_UNAVAILABLE.value
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    regular = tmp_path / "not-a-socket"
    regular.write_bytes(b"")
    client = CatalogApplicationClient(
        regular,
        expected_uid=os.getuid(),
        expected_gid=os.getgid(),
    )
    with pytest.raises(CatalogApplicationClientError) as raised:
        client.load_item_content("itemrev_" + "2" * 32)
    assert raised.value.code == CatalogApplicationErrorCode.CATALOG_APPLICATION_UNAVAILABLE.value


def test_catalog_application_systemd_boundary_keeps_api_away_from_nas() -> None:
    unit = Path("infra/systemd/eom-catalog-application-runner.service").read_text(encoding="utf-8")
    assert "User=eom-catalog-manager" in unit
    assert "Group=eom-api" in unit
    assert "SupplementaryGroups=eom" in unit
    assert "Environment=EOM_CATALOG_STAGING_ROOT=/var/lib/eom-catalog-api/staging" in unit
    assert "ExecStartPre=/usr/bin/install -d -m 0750 " in unit
    assert "/var/lib/eom-catalog-api/staging/registry" in unit
    assert "ReadWritePaths=/srv/eom/staging/catalog" not in unit
    assert "InaccessiblePaths=/srv/eom/staging/catalog" in unit
    assert "ReadWritePaths=/mnt/nas/eom/artifacts" in unit
    assert "InaccessiblePaths=/etc/eom/secrets/api.env" in unit
    assert "NoNewPrivileges=true" in unit
    assert "CapabilityBoundingSet=\n" in unit
    api_unit = Path("infra/systemd/eom-api.service").read_text(encoding="utf-8")
    assert (
        "After=network-online.target docker.service eom-catalog-application-runner.service"
        in api_unit
    )
    assert "Wants=network-online.target eom-catalog-application-runner.service" in api_unit
    assert "ReadWritePaths=/mnt/nas" not in api_unit
    assert "ReadWritePaths=/srv/eom/staging/catalog" not in api_unit
    assert "InaccessiblePaths=/etc/eom/secrets/catalog-manager.env" in api_unit


def test_workflow_runner_uses_its_own_catalog_staging_identity() -> None:
    unit = Path("infra/systemd/eom-workflow-runner.service").read_text(encoding="utf-8")
    composition = Path("services/workflow_runner/eom_workflow_runner/composition.py").read_text(
        encoding="utf-8"
    )

    private_root = "/var/lib/eom-workflow-runner/catalog-staging"
    assert f"Environment=EOM_CATALOG_STAGING_ROOT={private_root}" in unit
    assert f"ExecStartPre=/usr/bin/install -d -m 0750 {private_root}" in unit
    assert f"{private_root}/content-packs" in unit
    assert f"{private_root}/registry" in unit
    assert f"{private_root}/workflow-prompts" in unit
    assert "InaccessiblePaths=/srv/eom/staging" in unit
    assert 'runner_user="eom-workflow-runner"' in composition


def test_application_api_catalog_client_depends_on_protocol_not_server_implementation() -> None:
    client_source = Path(
        "apps/application_api/eom_api/services/catalog_application_client.py"
    ).read_text(encoding="utf-8")
    problem_source = Path("apps/application_api/eom_api/problem_details.py").read_text(
        encoding="utf-8"
    )

    assert "eom_catalog_contracts" in client_source
    assert "eom_catalog_service" not in client_source
    assert "eom_catalog_service" not in problem_source
