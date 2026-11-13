"""Native DB reads preserve metadata and files without impersonating a legacy source."""

from contextlib import nullcontext
from copy import deepcopy
from io import BytesIO
from types import SimpleNamespace

import pytest
from eom_api_contracts.item_db_registration import MaterialNativeItemDbEntryView
from eom_catalog_contracts.material_learning import MaterialArtifactMember
from eom_catalog_contracts.material_native_intake import (
    MaterialNativeLearningIntakeManifest,
    bind_native_exam_items,
)
from eom_catalog_contracts.material_native_item_read import (
    MaterialNativeItemReadRequest,
    MaterialNativeItemReadResponse,
)
from eom_catalog_service import material_native_item_read as owner
from eom_catalog_service.artifacts import VerifiedArtifactMemberStream
from eom_catalog_service.material_learning_models import LearningMaterialRevisionRecord
from eom_catalog_service.material_native_item_read_dispatch import (
    dispatch_native_material_item_read,
)
from eom_catalog_service.material_native_item_registration import (
    NATIVE_ITEM_PACK_METADATA_REF,
    native_material_components,
    native_material_metadata,
)
from eom_catalog_service.models import ItemRevisionRecord
from eom_identifiers import canonical_json_bytes, content_sha256, sha256_bytes
from eom_operator_identity import PermissionKey
from pydantic import ValidationError
from sqlalchemy.dialects import postgresql

from tests.unit.test_material_item_db_contracts import entry
from tests.unit.test_material_learning_intake import ACTOR
from tests.unit.test_material_native_files import metadata_data
from tests.unit.test_material_native_intake import native_intake
from tests.unit.test_material_native_resolution import case

REVISION = "itemrev_" + "3" * 32
MANIFEST = "sha256:" + "4" * 64
READER = "operator_" + "e" * 32


def request(role=None):
    return MaterialNativeItemReadRequest(
        operation="GET_NATIVE_MATERIAL_ITEM_SOURCE"
        if role is None
        else "GET_NATIVE_MATERIAL_ITEM_DOCUMENT",
        actor_id=READER,
        item_revision_id=REVISION,
        item_manifest_sha256=MANIFEST,
        source_role=role,
    )


def native_case(monkeypatch):
    bundle, bundle_pointer, _, payloads = case()
    (binding,) = bind_native_exam_items(
        bundle,
        material_id=metadata_data()["material_id"],
        material_revision_id=metadata_data()["material_revision_id"],
        units={1: (metadata_data()["unit_key"], "1")},
    )
    body = canonical_json_bytes(binding.model_dump(mode="json"))
    pointer = MaterialArtifactMember.model_validate(
        {
            **metadata_data()["native_binding"],
            "sha256": sha256_bytes(body),
            "bytes": len(body),
        }
    )
    payloads[pointer.member_path] = body
    metadata = native_material_metadata(metadata_data(), binding, pointer)
    revision = SimpleNamespace(
        item_revision_id=REVISION,
        manifest_sha256=MANIFEST,
        revision_state="APPROVED",
        metadata_json=metadata.model_dump(mode="json"),
        metadata_sha256=content_sha256(metadata.model_dump(mode="json")),
    )
    material_revision = SimpleNamespace(
        material_revision_id=metadata.material_revision_id,
        material_id=metadata.material_id,
        created_by=ACTOR,
        title="원본 모의고사",
        manifest_artifact_id="artifact_" + "a" * 32,
        manifest_artifact_revision_id="rev_" + "b" * 32,
        manifest_sha256="sha256:" + "a" * 64,
    )
    snapshot = SimpleNamespace(
        schema_ref=NATIVE_ITEM_PACK_METADATA_REF,
        metadata_json=deepcopy(revision.metadata_json),
        metadata_sha256=revision.metadata_sha256,
    )
    components = {}
    for component in native_material_components(binding, pointer):
        value = component.model_dump()
        value["metadata_json"] = value.pop("metadata")
        components[(component.component_type, component.ordinal)] = SimpleNamespace(**value)
    for kind in ("ITEM_CONTENT", "SOURCE_REFERENCE", "REVIEW_REPORT"):
        components[(kind, 0)] = SimpleNamespace(component_type=kind, ordinal=0)
    item = SimpleNamespace(lifecycle_state="ACTIVE")
    material = SimpleNamespace(
        material_id=metadata.material_id,
        lifecycle_state="ACTIVE",
        created_by=ACTOR,
    )

    class Session:
        def __init__(self):
            self.queries = []

        def execute(self, statement):
            self.queries.append(statement)
            return SimpleNamespace(
                all=lambda: [
                    (
                        revision,
                        item,
                        material_revision,
                        material,
                        snapshot,
                        components[("METADATA", 0)],
                    )
                ]
            )

        def get(self, model, key, **kwargs):
            return {
                ItemRevisionRecord: revision,
                LearningMaterialRevisionRecord: material_revision,
            }[model]

        def scalar(self, statement):
            return snapshot

        def scalars(self, statement):
            return components.values()

    session = Session()
    permissions = []

    def authorize(_session, actor):
        assert actor == READER and actor != ACTOR
        permissions.append(actor)

    monkeypatch.setattr(owner, "authorize_native_material_read", authorize)
    monkeypatch.setattr(owner, "material_intake_pointer", lambda *args, **kwargs: pointer)
    intake_data = native_intake()
    intake_data["native_bundle"] = bundle_pointer.model_dump(mode="json")
    rights = {
        "schema_version": "material-learning-rights/1.0",
        "material_id": metadata.material_id,
        "material_revision_id": metadata.material_revision_id,
        "attested_by": ACTOR,
        "attested_at": "2026-11-05T00:00:00Z",
        "basis": "UPLOADER_ATTESTED_INTERNAL_PROCESSING",
        "source_hashes": [
            selected["source_upload"]["original"]["sha256"] for selected in intake_data["sources"]
        ],
        "permitted_uses": [
            "INTERNAL_ANALYSIS",
            "ITEM_REGISTRATION",
            "GRAPH_RETRIEVAL",
            "LOCAL_EMBEDDING",
        ],
        "public_redistribution_permitted": False,
        "withdrawal_policy": "DENY_NEW_RESOLUTION_PRESERVE_PINNED_AUDIT",
    }
    rights["attestation_sha256"] = content_sha256(rights)
    raw_rights = canonical_json_bytes(rights)
    payloads["rights/attestation.json"] = raw_rights
    intake_data["rights_attestation"].update(sha256=sha256_bytes(raw_rights), bytes=len(raw_rights))
    intake = MaterialNativeLearningIntakeManifest.model_validate(intake_data)
    monkeypatch.setattr(owner, "read_material_intake", lambda *args, **kwargs: intake)
    # This unit fixture models rows; real Artifact lifecycle is exercised separately
    # by the disposable PostgreSQL read/stream test, not fabricated here.
    monkeypatch.setattr(owner, "require_native_material_source_members", lambda *args: None)

    class Artifacts:
        def __init__(self):
            self.opened = []
            self.reads = []

        def read_member(self, **kwargs):
            self.reads.append(kwargs)
            raw = payloads[kwargs["member_path"]]
            assert kwargs["sha256"] == sha256_bytes(raw)
            return raw

        def open_verified_member(self, **kwargs):
            raw = payloads[kwargs["member_path"]]
            assert kwargs["sha256"] == sha256_bytes(raw)
            stream = VerifiedArtifactMemberStream(BytesIO(raw), len(raw), sha256_bytes(raw))
            self.opened.append(stream)
            return stream

    service = owner.MaterialNativeItemReadService.__new__(owner.MaterialNativeItemReadService)
    service.sessions = lambda: nullcontext(session)
    service.artifacts = Artifacts()
    return SimpleNamespace(**locals())


def test_native_db_view_preserves_null_number_raw_original_unit_and_external_provenance():
    value = entry()
    value.update(schema_version="material-item-db-entry/2.0", metadata=metadata_data())
    view = MaterialNativeItemDbEntryView.model_validate(value)
    assert view.metadata.source_kind == "EXTERNAL"
    assert view.metadata.external_number is None
    assert view.metadata.original_unit == " 단원 원문 "
    assert "source_id" not in view.model_dump() and "cells" not in view.model_dump()


@pytest.mark.parametrize(
    "change",
    [
        {"source_role": "MAIN"},
        {"artifact_id": "artifact_" + "f" * 32},
        {"item_revision_id": "latest"},
        {"actor_id": "ADMIN"},
    ],
)
def test_native_read_never_accepts_paths_hash_only_or_model_supplied_role(change):
    value = {**request().model_dump(mode="json"), **change}
    with pytest.raises(ValidationError):
        MaterialNativeItemReadRequest.model_validate(value)


def test_metadata_read_is_one_indexed_query_and_preserves_original_not_graph_unit(monkeypatch):
    state = native_case(monkeypatch)
    values = owner.read_native_material_original_metadata(
        state.session, item_manifests={REVISION: MANIFEST}
    )
    assert values[REVISION].metadata.original_unit == state.binding.source_metadata.original_unit
    assert len(state.session.queries) == 1
    sql = str(state.session.queries[0].compile(dialect=postgresql.dialect()))
    assert "item_revisions.item_revision_id IN" in sql and "item_metadata_snapshots" in sql
    assert not state.service.artifacts.reads and not state.service.artifacts.opened


@pytest.mark.parametrize("part", ["manifest", "snapshot", "material", "component", "hash"])
def test_original_metadata_requires_exact_registered_snapshot_and_source(monkeypatch, part):
    state = native_case(monkeypatch)
    if part == "manifest":
        state.revision.manifest_sha256 = "sha256:" + "f" * 64
    elif part == "snapshot":
        state.snapshot.metadata_sha256 = "sha256:" + "f" * 64
    elif part == "material":
        state.material.lifecycle_state = "RETIRED"
    elif part == "component":
        state.components[("METADATA", 0)].sha256 = "sha256:" + "f" * 64
    else:
        state.revision.metadata_json["original_unit"] = "forged"
    with pytest.raises(owner.MaterialNativeItemReadError):
        owner.read_native_material_original_metadata(
            state.session, item_manifests={REVISION: MANIFEST}
        )


def test_source_read_validates_native_pair_and_workbook_but_does_not_open_large_files(monkeypatch):
    state = native_case(monkeypatch)
    source = state.service.read_source(request())
    assert source.metadata.external_number == state.binding.source_metadata.external_number
    assert source.question == state.binding.question.document
    assert source.solution == state.binding.solution.document
    assert source.workbook == state.binding.workbook
    assert not state.service.artifacts.opened
    assert len(state.permissions) >= 3


@pytest.mark.parametrize("role", ["MAIN", "SOLUTIONS"])
def test_direct_download_resolves_only_selected_editable_file_and_stable_filename(
    monkeypatch, role
):
    state = native_case(monkeypatch)
    result = state.service.open_document(request(role))
    expected = state.binding.question if role == "MAIN" else state.binding.solution
    assert result.header.sha256 == expected.document.sha256
    assert result.header.filename.endswith(f"-{role.lower()}.hwpx")
    assert result.member.stream.read(4) == b"PK\x03\x04"
    result.member.stream.close()
    assert len(state.service.artifacts.opened) == 1


def test_changed_native_component_never_reaches_file_bytes(monkeypatch):
    state = native_case(monkeypatch)
    state.components[("OTHER", 1)].sha256 = "sha256:" + "f" * 64
    with pytest.raises(ValueError, match="REGISTRATION_REPLAY_CONFLICT"):
        state.service.open_document(request("SOLUTIONS"))
    assert not state.service.artifacts.opened


def test_permission_revocation_fails_before_any_native_artifact_read(monkeypatch):
    state = native_case(monkeypatch)

    def deny(*args):
        raise owner.MaterialNativeItemReadError("MATERIAL_NATIVE_READ_PERMISSION_DENIED")

    monkeypatch.setattr(owner, "authorize_native_material_read", deny)
    output = BytesIO()
    dispatch_native_material_item_read(
        request("MAIN").model_dump(mode="json"), output, service=state.service
    )
    reply = MaterialNativeItemReadResponse.model_validate_json(output.getvalue())
    assert reply.status == "ERROR" and reply.error_code == "MATERIAL_NATIVE_READ_PERMISSION_DENIED"
    assert not state.service.artifacts.reads and not state.service.artifacts.opened


def test_private_dispatch_streams_exact_bytes_after_validated_header_and_closes_fd(monkeypatch):
    state = native_case(monkeypatch)
    output = BytesIO()
    dispatch_native_material_item_read(
        request("SOLUTIONS").model_dump(mode="json"), output, service=state.service
    )
    header, raw = output.getvalue().split(b"\n", 1)
    reply = MaterialNativeItemReadResponse.model_validate_json(header)
    assert reply.sha256 == sha256_bytes(raw) == state.binding.solution.document.sha256
    assert state.service.artifacts.opened[0].stream.closed


def test_actual_reader_needs_both_permissions_not_source_creator_identity(monkeypatch):
    current = SimpleNamespace(status="ACTIVE", deleted_at=None, must_change_password=False)
    session = SimpleNamespace(get=lambda *args, **kwargs: current)
    authorize = owner.authorize_native_material_read
    monkeypatch.setattr(owner, "effective_permissions", lambda *args: {PermissionKey.ITEM_READ})
    with pytest.raises(owner.MaterialNativeItemReadError, match="PERMISSION_DENIED"):
        authorize(session, READER)
    monkeypatch.setattr(
        owner,
        "effective_permissions",
        lambda *args: {
            PermissionKey.ITEM_READ,
            PermissionKey.CONTENT_INTAKE_READ,
        },
    )
    authorize(session, READER)
    current.status = "DISABLED"
    with pytest.raises(owner.MaterialNativeItemReadError, match="PERMISSION_DENIED"):
        authorize(session, READER)
