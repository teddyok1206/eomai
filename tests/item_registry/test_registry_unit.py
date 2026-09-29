from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from eom_catalog_contracts import validate_contract
from eom_catalog_service.models import (
    ContentPackReleaseRecord,
    ItemProvenanceRecord,
    ItemRecord,
    ItemRelationshipRecord,
    ItemRevisionRecord,
)
from eom_catalog_service.registry_service import RegistryService
from eom_identifiers import canonical_json_bytes, content_sha256
from eom_item_registry import (
    ComponentPointer,
    ItemRevisionState,
    PastExamVariationSourcePointer,
    RegistrationRequest,
    RegistryError,
    UsagePlanState,
    new_item_id,
    new_item_revision_id,
    require_revision_transition,
    require_usage_plan_transition,
)
from eom_orchestrator.models import Base
from sqlalchemy import LargeBinary


def _request() -> RegistrationRequest:
    return RegistrationRequest(
        mode="CREATE_ITEM",
        registration_key="workflow:test:registration:1",
        content_pack_release_id="packrel_" + "1" * 32,
        workflow_id="workflow_" + "2" * 32,
        workflow_definition_key="generic-item-development",
        workflow_definition_version="1.1.0",
        source_workflow_step_run_id="steprun_" + "3" * 32,
        source_intake_batch_ids=("intake_" + "4" * 32,),
        item_type_key="generic-multiple-choice",
        primary_taxonomy_ref="PLACEHOLDER_TAXONOMY",
        difficulty_band="PLACEHOLDER_DIFFICULTY",
        tag_keys=("PLACEHOLDER_TAG",),
        metadata_schema_ref="eom://metadata/generic-placeholder@1.0",
        metadata={
            "domain": "PLACEHOLDER_DOMAIN",
            "item_type": "PLACEHOLDER_ITEM_TYPE",
            "difficulty": "PLACEHOLDER_DIFFICULTY",
            "tags": ["PLACEHOLDER_TAG"],
        },
        components=(
            ComponentPointer(
                component_type="UPPER_STEM",
                ordinal=0,
                schema_ref="eom://component/placeholder@1.0",
                media_type="application/json",
                artifact_id="artifact_" + "5" * 32,
                artifact_revision_id="rev_" + "6" * 32,
                sha256="sha256:" + "7" * 64,
                logical_name="PLACEHOLDER_CONTENT",
            ),
        ),
        created_by="operator_01",
    )


def test_identifiers_and_explicit_state_tables() -> None:
    assert new_item_id().startswith("item_")
    assert new_item_revision_id().startswith("itemrev_")
    require_revision_transition(ItemRevisionState.APPROVED, ItemRevisionState.SUPERSEDED)
    require_usage_plan_transition(UsagePlanState.RESERVED, UsagePlanState.FULFILLED)
    with pytest.raises(RegistryError):
        require_revision_transition(ItemRevisionState.APPROVED, ItemRevisionState.DRAFT)
    with pytest.raises(RegistryError):
        require_usage_plan_transition(UsagePlanState.FULFILLED, UsagePlanState.RESERVED)


def test_item_manifest_is_canonical_and_schema_valid() -> None:
    request = _request()
    release = ContentPackReleaseRecord(
        content_pack_release_id=request.content_pack_release_id,
        content_pack_id="contentpack_" + "8" * 32,
        version="0.1.0",
        schema_version="1.0",
        state="RELEASED",
        source_tree_sha256="sha256:" + "9" * 64,
        bundle_sha256="sha256:" + "a" * 64,
        manifest_sha256="sha256:" + "b" * 64,
        bundle_artifact_id="artifact_" + "c" * 32,
        bundle_artifact_revision_id="rev_" + "d" * 32,
        canonical_manifest_json={},
        compatibility_json={},
        lock_version=1,
    )
    created_at = datetime(2026, 8, 17, tzinfo=UTC)
    first = RegistryService._manifest(
        request,
        item_id="item_" + "e" * 32,
        revision_id="itemrev_" + "f" * 32,
        revision_number=1,
        pack=release,
        pack_key="generic-placeholder",
        metadata_hash=content_sha256(request.metadata),
        created_at=created_at,
    )
    second = RegistryService._manifest(
        request,
        item_id="item_" + "e" * 32,
        revision_id="itemrev_" + "f" * 32,
        revision_number=1,
        pack=release,
        pack_key="generic-placeholder",
        metadata_hash=content_sha256(request.metadata),
        created_at=created_at,
    )
    validate_contract("item-revision-manifest", first)
    assert canonical_json_bytes(first) == canonical_json_bytes(second)


def _variation_source() -> PastExamVariationSourcePointer:
    return PastExamVariationSourcePointer(
        item_id="item_" + "a" * 32,
        item_revision_id="itemrev_" + "b" * 32,
        content_artifact_id="artifact_" + "c" * 32,
        content_artifact_revision_id="rev_" + "d" * 32,
        content_schema_ref="eom://schemas/item-registry/assessment-item-content-v3",
        content_sha256="sha256:" + "e" * 64,
        plan_id="execplan_" + "f" * 32,
        plan_sha256="sha256:" + "1" * 64,
        evidence_bundle_revision_id="evidencerev_" + "2" * 32,
        evidence_manifest_sha256="sha256:" + "3" * 64,
    )


def test_variation_manifest_and_lineage_pin_source_revision_without_revising_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = _variation_source()
    request = _request().model_copy(
        update={"past_exam_variation_source": source, "source_intake_batch_ids": ()}
    )
    release = ContentPackReleaseRecord(
        content_pack_release_id=request.content_pack_release_id,
        content_pack_id="contentpack_" + "8" * 32,
        version="1.20.8",
        schema_version="1.1",
        state="RELEASED",
        source_tree_sha256="sha256:" + "9" * 64,
        bundle_sha256="sha256:" + "a" * 64,
        manifest_sha256="sha256:" + "b" * 64,
        bundle_artifact_id="artifact_" + "8" * 32,
        bundle_artifact_revision_id="rev_" + "8" * 32,
        canonical_manifest_json={},
        compatibility_json={},
        lock_version=1,
    )
    new_item_id = "item_" + "4" * 32
    new_revision_id = "itemrev_" + "5" * 32
    manifest = RegistryService._manifest(
        request,
        item_id=new_item_id,
        revision_id=new_revision_id,
        revision_number=1,
        pack=release,
        pack_key="generated-knowledge-item",
        metadata_hash=content_sha256(request.metadata),
        created_at=datetime(2026, 9, 29, tzinfo=UTC),
    )
    validate_contract("item-revision-manifest", manifest)
    assert manifest["provenance"] == [
        {
            "type": "PAST_EXAM_VARIATION",
            "source_item_id": source.item_id,
            "source_item_revision_id": source.item_revision_id,
            "source_artifact_id": source.content_artifact_id,
            "source_artifact_revision_id": source.content_artifact_revision_id,
            "source_sha256": source.content_sha256,
            "plan_id": source.plan_id,
            "plan_sha256": source.plan_sha256,
            "evidence_bundle_revision_id": source.evidence_bundle_revision_id,
            "evidence_manifest_sha256": source.evidence_manifest_sha256,
        }
    ]

    class Session:
        def __init__(self) -> None:
            self.added: list[object] = []

        def add(self, value: object) -> None:
            self.added.append(value)

    monkeypatch.setattr(
        RegistryService,
        "_validate_variation_source",
        classmethod(lambda cls, session, pointer: None),
    )
    session = Session()
    revision = ItemRevisionRecord(item_revision_id=new_revision_id, item_id=new_item_id)
    RegistryService._add_variation_lineage(session, revision, request)  # type: ignore[arg-type]

    relationship = next(
        value for value in session.added if isinstance(value, ItemRelationshipRecord)
    )
    provenance = next(value for value in session.added if isinstance(value, ItemProvenanceRecord))
    assert (
        relationship.source_item_id,
        relationship.target_item_id,
        relationship.relationship_type,
    ) == (new_item_id, source.item_id, "PAST_EXAM_VARIANT_OF")
    assert provenance.item_revision_id == new_revision_id
    assert provenance.source_key == source.item_revision_id
    assert provenance.source_artifact_revision_id == source.content_artifact_revision_id
    assert provenance.source_sha256 == source.content_sha256


def test_keyset_cursor_round_trip_and_invalid_cursor() -> None:
    item = ItemRecord(
        item_id="item_" + "1" * 32,
        lifecycle_state="ACTIVE",
        created_by="operator_01",
        lock_version=1,
    )
    item.created_at = datetime(2026, 8, 17, 12, tzinfo=UTC)
    cursor = RegistryService._encode_cursor(item)
    assert RegistryService._decode_cursor(cursor) == (item.created_at, item.item_id)
    with pytest.raises(RegistryError):
        RegistryService._decode_cursor("invalid")


def test_domain_package_has_no_infrastructure_dependency() -> None:
    root = Path("packages/item_registry/eom_item_registry")
    source = "\n".join(path.read_text(encoding="utf-8") for path in root.glob("*.py"))
    assert "eom_catalog_service" not in source
    assert "sqlalchemy" not in source
    assert "subprocess" not in source


def test_registry_tables_do_not_store_large_binary() -> None:
    registry_tables = {
        name for name in Base.metadata.tables if name.startswith(("item", "deliverable", "usage"))
    }
    assert registry_tables
    assert all(
        not isinstance(column.type, LargeBinary)
        for name in registry_tables
        for column in Base.metadata.tables[name].columns
    )
