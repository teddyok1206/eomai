"""Pinned mixed delivery metadata, ordered receipts and storage constraints."""

import importlib.util
import json
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import Mock

import pytest
from eom_catalog_contracts import (
    CuratedDocumentAssemblyManifestV1,
    CuratedExternalDocumentPlacement,
)
from eom_catalog_service.curated_document_assembly_models import (
    CuratedDocumentAssemblyRevisionRecord,
)
from eom_hwpx_contracts import (
    CONTENT_TEAM_HANDOFF_MEMBERS,
    ContentTeamHandoffSnapshot,
    validate_contract,
)
from eom_hwpx_contracts.curated_build import (
    CuratedArtifactMember,
    CuratedHwpxBuildInput,
    CuratedNativeDocumentInput,
    CuratedRegisteredItemInput,
)
from eom_hwpx_contracts.curated_document import CuratedHwpConverterSnapshot
from eom_hwpx_contracts.validation import load_schema
from eom_hwpx_manager.curated_application_service import (
    CuratedBuildReceipt,
    CuratedHwpxApplicationService,
)
from eom_hwpx_manager.curated_build_models import HwpxCuratedBuildRecord
from eom_hwpx_manager.errors import HwpxManagerError
from eom_identifiers import content_sha256
from jsonschema import ValidationError as SchemaValidationError
from pydantic import ValidationError
from sqlalchemy import CheckConstraint, ForeignKeyConstraint, UniqueConstraint
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateIndex, CreateTable

from tests.unit.test_curated_document_assembly_manifest import _manifest

ROOT = Path(__file__).resolve().parents[2]


def build_manifest() -> CuratedDocumentAssemblyManifestV1:
    return CuratedDocumentAssemblyManifestV1.model_validate(_manifest())


def test_input_metadata_budget_rejects_before_queue_write(monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import MagicMock

    from eom_hwpx_manager import curated_application_service as application

    from tests.unit.test_curated_document_assembly_resolution import _actor

    manifest = build_manifest()
    assemblies = Mock()
    assemblies.authorize_delivery_build.return_value = manifest
    pins = Mock()
    pins.pin_inputs.return_value = build_inputs(manifest)
    service = CuratedHwpxApplicationService(Mock(), assemblies=assemblies, input_pins=pins)
    session = MagicMock()
    session.__enter__.return_value.scalar.return_value = None
    service.sessions = Mock(return_value=session)
    # Byte budget, not character count: represent a large valid metadata input
    # without building hundreds of expensive artifact fixtures in this unit test.
    monkeypatch.setattr(application, "json", SimpleNamespace(dumps=lambda *a, **k: "가" * 174763))
    with pytest.raises(HwpxManagerError, match="metadata budget"):
        service.request_build(
            manifest.assembly_id,
            assembly_revision_id=manifest.assembly_revision_id,
            manifest_sha256=manifest.manifest_sha256,
            actor=_actor(),
            idempotency_key="metadata-budget-test-001",
        )
    assert service.sessions.call_count == 1
    session.__enter__.return_value.add.assert_not_called()


def build_inputs(manifest: CuratedDocumentAssemblyManifestV1) -> CuratedHwpxBuildInput:
    placements = []
    for row in manifest.placements:
        if isinstance(row, CuratedExternalDocumentPlacement):
            placements.append(
                CuratedNativeDocumentInput(
                    position=row.position,
                    source_format=row.source_format,
                    document=CuratedArtifactMember.model_validate(
                        row.document_artifact.model_dump()
                    ),
                    size_bytes=row.document_size_bytes,
                )
            )
        else:
            pointer = CuratedArtifactMember(
                artifact_id="artifact_" + "a" * 32,
                artifact_revision_id="rev_" + "b" * 32,
                member_path="assessment-item-content.json",
                media_type="application/json",
                schema_ref="eom.assessment.item-content/1.0",
                sha256="sha256:" + "c" * 64,
            )
            placements.append(
                CuratedRegisteredItemInput(
                    position=row.position,
                    item_id=row.item_id,
                    item_revision_id=row.item_revision_id,
                    item_manifest_sha256=row.item_manifest_sha256,
                    source_content=pointer,
                    display_content=pointer,
                    recovery_manifest=None,
                    editorial_markdown=None,
                )
            )
    return CuratedHwpxBuildInput(
        assembly_id=manifest.assembly_id,
        assembly_revision_id=manifest.assembly_revision_id,
        assembly_manifest_sha256=manifest.manifest_sha256,
        handoff=ContentTeamHandoffSnapshot(
            artifact_id="artifact_" + "d" * 32,
            artifact_revision_id="rev_" + "e" * 32,
            members=tuple(
                {"purpose": p, "sha256": h, "size": n} for p, h, n in CONTENT_TEAM_HANDOFF_MEMBERS
            ),
        ),
        converter=(
            CuratedHwpConverterSnapshot(
                profile="HWP2HWPX_NATIVE_V1",
                source_commit="62d95b980a4e3a6766877dd3fb6f7f45f4afcf3d",
                bundle_sha256="sha256:" + "f" * 64,
            )
            if any(
                isinstance(row, CuratedNativeDocumentInput) and row.source_format == "HWP"
                for row in placements
            )
            else None
        ),
        placements=tuple(placements),
    )


def build_record() -> HwpxCuratedBuildRecord:
    manifest = build_manifest()
    inputs = build_inputs(manifest)
    return HwpxCuratedBuildRecord(
        build_id="hwpxbuild_" + "1" * 32,
        assembly_id=manifest.assembly_id,
        assembly_revision_id=manifest.assembly_revision_id,
        assembly_manifest_sha256=manifest.manifest_sha256,
        input_plan=inputs.model_dump(mode="json"),
        input_plan_sha256=content_sha256(inputs.model_dump(mode="json")),
        planned_job_id="job_" + "2" * 32,
        platform_job_id="job_" + "2" * 32,
        planned_artifact_id="artifact_" + "3" * 32,
        planned_artifact_revision_id="rev_" + "4" * 32,
        state="VALIDATING",
        validation_state="PENDING",
        placement_count=3,
        resource_version=3,
        started_at=datetime.now(UTC),
    )


def build_receipt(record: HwpxCuratedBuildRecord) -> CuratedBuildReceipt:
    return CuratedBuildReceipt(
        build_id=record.build_id,
        input_plan_sha256=record.input_plan_sha256,
        job_id=record.planned_job_id,
        artifact_id=record.planned_artifact_id,
        artifact_revision_id=record.planned_artifact_revision_id,
        output_sha256="sha256:" + "5" * 64,
        output_size_bytes=1000,
        section_count=4,
        binary_count=0,
        native_table_count=0,
        native_equation_count=0,
    )


def test_build_input_schema_is_mirrored_and_contains_only_typed_pointers() -> None:
    manifest = build_manifest()
    inputs = build_inputs(manifest)
    value = inputs.model_dump(mode="json")
    validate_contract("curated-build-input", value)
    CuratedHwpxApplicationService._require_inputs(inputs, manifest)
    path = ROOT / "schemas/hwpx/hwpx-curated-build-input-v1.schema.json"
    assert json.loads(path.read_bytes()) == load_schema("curated-build-input")
    assert (
        path.read_bytes()
        == (ROOT / "packages/hwpx_contracts/eom_hwpx_contracts/schemas" / path.name).read_bytes()
    )
    assert len(json.dumps(value)) < 16000
    for forbidden in ("body", "payload", "permissions", "password", "nas_path"):
        value[forbidden] = "not an input field"
        with pytest.raises(ValidationError):
            CuratedHwpxBuildInput.model_validate(value)
        with pytest.raises(SchemaValidationError):
            validate_contract("curated-build-input", value)
        del value[forbidden]


@pytest.mark.parametrize(
    "member", ["../secret", "/tmp/a", "a//b", "a/./b", "a/../b", "a\\b", "a\x00b"]
)
def test_snapshot_cannot_embed_arbitrary_filesystem_paths(member: str) -> None:
    value = build_inputs(build_manifest()).placements[0].document.model_dump()
    value["member_path"] = member
    with pytest.raises(ValidationError):
        CuratedArtifactMember.model_validate(value)


@pytest.mark.parametrize("mutation", ["order", "size", "source", "revision", "manifest"])
def test_build_input_must_match_saved_order_and_exact_pointers(mutation: str) -> None:
    manifest = build_manifest()
    value = build_inputs(manifest).model_dump(mode="json")
    if mutation == "order":
        value["placements"][1], value["placements"][2] = (
            value["placements"][2],
            value["placements"][1],
        )
        for pos, row in enumerate(value["placements"], 1):
            row["position"] = pos
    elif mutation == "size":
        value["placements"][0]["size_bytes"] += 1
    elif mutation == "source":
        value["placements"][0]["document"]["sha256"] = "sha256:" + "f" * 64
    elif mutation == "revision":
        value["placements"][1]["item_revision_id"] = "itemrev_" + "f" * 32
    else:
        value["assembly_manifest_sha256"] = "sha256:" + "f" * 64
    inputs = CuratedHwpxBuildInput.model_validate(value)
    with pytest.raises(HwpxManagerError):
        CuratedHwpxApplicationService._require_inputs(inputs, manifest)


def test_native_only_build_needs_no_content_team_payload_or_fake_item() -> None:
    value = build_inputs(build_manifest()).model_dump(mode="json")
    value["placements"] = value["placements"][:1]
    value["handoff"] = None
    value["converter"] = None
    value["placements"][0]["source_format"] = "HWPX"
    value["placements"][0]["document"]["media_type"] = "application/vnd.hancom.hwpx"
    inputs = CuratedHwpxBuildInput.model_validate(value)
    validate_contract("curated-build-input", inputs.model_dump(mode="json"))
    assert inputs.handoff is None and inputs.converter is None
    value["placements"][0]["source_format"] = "HWP"
    value["placements"][0]["document"]["media_type"] = "application/vnd.hancom.hwp"
    with pytest.raises(ValidationError, match="tools"):
        CuratedHwpxBuildInput.model_validate(value)


def test_receipt_accepts_native_documents_with_multiple_sections_and_no_images() -> None:
    record = build_record()
    CuratedHwpxApplicationService._complete(record, build_receipt(record))
    assert record.state == "SUCCEEDED" and record.validation_state == "PASS"
    assert record.section_count == 4 and record.placement_count == 3
    assert record.binary_count == record.native_table_count == record.native_equation_count == 0
    assert record.output_artifact_revision_id == record.planned_artifact_revision_id


@pytest.mark.parametrize(
    "field,value",
    [
        ("build_id", "hwpxbuild_" + "f" * 32),
        ("input_plan_sha256", "sha256:" + "f" * 64),
        ("artifact_id", "artifact_" + "f" * 32),
        ("artifact_revision_id", "rev_" + "f" * 32),
        ("job_id", "job_" + "f" * 32),
        ("section_count", 2),
        ("binary_count", -1),
        ("output_size_bytes", 0),
    ],
)
def test_receipt_rejects_a_different_execution_or_incomplete_output(
    field: str, value: object
) -> None:
    record = build_record()
    receipt = replace(build_receipt(record), **{field: value})
    with pytest.raises(HwpxManagerError):
        CuratedHwpxApplicationService._complete(record, receipt)
    assert record.state == "VALIDATING" and record.output_artifact_id is None


def test_curated_storage_has_real_assembly_fk_unique_keys_and_partial_indexes() -> None:
    table = HwpxCuratedBuildRecord.__table__
    assert (
        table.metadata.tables["curated_document_assembly_revisions"]
        is CuratedDocumentAssemblyRevisionRecord.__table__
    )
    ddl = str(CreateTable(table).compile(dialect=postgresql.dialect()))
    assert "BYTEA" not in ddl and "item_revisions" not in ddl
    assert any(
        isinstance(c, ForeignKeyConstraint) and len(c.elements) == 2 for c in table.constraints
    )
    assert any(
        isinstance(c, UniqueConstraint)
        and tuple(c.columns.keys()) == ("created_by_operator_id", "idempotency_key")
        for c in table.constraints
    )
    indexes = {
        i.name: str(CreateIndex(i).compile(dialect=postgresql.dialect())) for i in table.indexes
    }
    assert "WHERE state = 'REQUESTED'" in indexes["ix_hwpx_curated_requested_fifo"]
    assert "WHERE state IN ('RUNNING','VALIDATING')" in indexes["ix_hwpx_curated_recovery"]
    checks = {c.name: str(c.sqltext) for c in table.constraints if isinstance(c, CheckConstraint)}
    assert checks["ck_hwpx_curated_terminal_evidence"].endswith("IS TRUE")


def test_frozen_migration_matches_orm_and_refuses_to_delete_build_history(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = ROOT / "migrations/versions/20261104_0072_hwpx_curated_builds.py"
    spec = importlib.util.spec_from_file_location("curated_delivery_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.revision == "20261104_0072" and module.down_revision == "20261103_0071"
    table = HwpxCuratedBuildRecord.__table__
    # Migration 0076 changes exactly these two bounds for the occurrence successor.
    # All other released table columns/constraints remain byte-equivalent after whitespace.
    checks = {c.name: str(c.sqltext) for c in table.constraints if isinstance(c, CheckConstraint)}
    historical = " ".join(module._DDL[0].split())
    for name, old in {
        "ck_hwpx_curated_count": "placement_count BETWEEN 1 AND 200 AND resource_version > 0",
        "ck_hwpx_curated_metadata_budget": (
            "jsonb_typeof(input_plan) = 'object' AND octet_length(input_plan::text) <= 524288 AND "
            "jsonb_typeof(initiator_context) = 'object' "
            "AND octet_length(initiator_context::text) <= 4096"
        ),
    }.items():
        assert old in historical
        historical = historical.replace(old, checks[name])
    assert historical == " ".join(
        str(CreateTable(table).compile(dialect=postgresql.dialect())).split()
    )
    assert "HWPX_CURATED_BUILD_TERMINAL_IMMUTABLE" in module._DDL[-2]
    ops = Mock()
    monkeypatch.setattr(module, "op", ops)
    ops.get_bind.return_value.scalar.return_value = True
    with pytest.raises(RuntimeError, match="HISTORY_EXISTS"):
        module.downgrade()
    ops.drop_table.assert_not_called()
