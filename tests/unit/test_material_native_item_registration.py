"""Native Registry additions preserve source identity and validate exact replay components."""

from copy import deepcopy
from types import SimpleNamespace

import pytest
from eom_catalog_contracts.material_learning import MaterialArtifactMember, MaterialExtractionWork
from eom_catalog_contracts.material_learning_intake import MaterialLearningIntakeManifest
from eom_catalog_contracts.material_native_files import MaterialNativeItemBinding
from eom_catalog_contracts.material_native_intake import (
    MaterialNativeExamBundle,
    MaterialNativeLearningIntakeManifest,
)
from eom_catalog_service import material_native_item_registration as native
from eom_catalog_service.material_learning_models import LearningMaterialRevisionRecord
from eom_identifiers import canonical_json_bytes, content_sha256, sha256_bytes

from tests.unit.test_material_learning_intake import ACTOR
from tests.unit.test_material_native_files import binding_data, metadata_data, native_work
from tests.unit.test_material_native_intake import native_exam_bundle, native_intake
from tests.unit.test_material_native_resolution import case


def test_native_components_are_only_existing_primary_pointers_and_keep_original_role_order():
    binding = MaterialNativeItemBinding.model_validate(binding_data())
    pointer = MaterialArtifactMember.model_validate(metadata_data()["native_binding"])
    components = native.native_material_components(binding, pointer)
    assert [(value.component_type, value.ordinal) for value in components] == [
        ("METADATA", 0),
        ("OTHER", 0),
        ("OTHER", 1),
    ]
    assert components[1].artifact_id == binding.question.document.artifact_id
    assert components[2].sha256 == binding.solution.document.sha256
    assert components[1].metadata == {"document_role": "MAIN"}
    assert components[2].metadata == {"document_role": "SOLUTIONS"}


def resolution_case(monkeypatch, *, legacy=False):
    work = MaterialExtractionWork.model_validate(native_work())
    resolved = SimpleNamespace(work=work, operator_id=ACTOR)
    row = SimpleNamespace(
        material_id=work.material_id,
        created_by=ACTOR,
        manifest_artifact_id="artifact_" + "1" * 32,
        manifest_artifact_revision_id="rev_" + "2" * 32,
        manifest_sha256="sha256:" + "a" * 64,
    )

    class Session:
        def get(self, model, key):
            assert model is LearningMaterialRevisionRecord
            return row if key == work.material_revision_id else None

    intake = native_intake()
    if legacy:
        intake.pop("native_bundle")
        intake["schema_version"] = "material-learning-intake/1.0"
        parsed = MaterialLearningIntakeManifest.model_validate(intake)
    else:
        parsed = MaterialNativeLearningIntakeManifest.model_validate(intake)
    monkeypatch.setattr(native, "material_intake_pointer", lambda *args, **kwargs: None)
    monkeypatch.setattr(native, "read_material_intake", lambda *args, **kwargs: parsed)
    monkeypatch.setattr(
        native,
        "read_material_native_bundle",
        lambda *args, **kwargs: MaterialNativeExamBundle.model_validate(native_exam_bundle()),
    )
    return Session(), row, resolved


def test_actual_revision_intake_selects_native_binding_without_caller_metadata(monkeypatch):
    session, _, resolved = resolution_case(monkeypatch)
    checks = []
    binding = native.resolve_native_material_registration_binding(
        session, None, resolved, authorize=lambda: checks.append(True)
    )
    assert binding.item_number == 1 and binding.source_metadata.external_number is None
    assert binding.material_revision_id == resolved.work.material_revision_id
    assert len(checks) == 2


def test_missing_revision_is_never_silently_treated_as_legacy(monkeypatch):
    session, row, resolved = resolution_case(monkeypatch)
    row.created_by = "operator_" + "e" * 32
    with pytest.raises(ValueError, match="REGISTRATION_SOURCE_MISSING"):
        native.resolve_native_material_registration_binding(
            session, None, resolved, authorize=lambda: None
        )


def test_valid_committed_v1_intake_keeps_exact_original_registration_path(monkeypatch):
    session, _, resolved = resolution_case(monkeypatch, legacy=True)
    assert (
        native.resolve_native_material_registration_binding(
            session, None, resolved, authorize=lambda: None
        )
        is None
    )


def test_selected_item_verification_does_not_decode_workbook_or_scan_other_exam_items():
    from eom_catalog_service.material_native_resolution import verify_material_native_item_files

    bundle, _, reader, _ = case()
    verify_material_native_item_files(reader, bundle.items[0], authorize=lambda: None)
    assert len(reader.opened) == 2 and all(value.closed for value in reader.opened)
    assert {value["member_path"] for value in reader.calls} == {
        bundle.items[0].question.split_evidence.member_path,
        bundle.items[0].solution.split_evidence.member_path,
    }


def replay_case():
    binding = MaterialNativeItemBinding.model_validate(binding_data())
    body = canonical_json_bytes(binding.model_dump(mode="json"))
    pointer = MaterialArtifactMember.model_validate(
        {**metadata_data()["native_binding"], "sha256": sha256_bytes(body), "bytes": len(body)}
    )
    metadata = native.native_material_metadata(metadata_data(), binding, pointer)
    revision = SimpleNamespace(
        item_revision_id="itemrev_" + "3" * 32,
        metadata_json=metadata.model_dump(mode="json"),
        metadata_sha256=content_sha256(metadata.model_dump(mode="json")),
    )
    snapshot = SimpleNamespace(
        schema_ref=native.NATIVE_ITEM_PACK_METADATA_REF,
        metadata_json=deepcopy(revision.metadata_json),
        metadata_sha256=revision.metadata_sha256,
    )
    components = {}
    for component in native.native_material_components(binding, pointer):
        data = component.model_dump()
        data["metadata_json"] = data.pop("metadata")
        components[(component.component_type, component.ordinal)] = SimpleNamespace(**data)

    class Reader:
        def read_member(self, **kwargs):
            assert kwargs["sha256"] == sha256_bytes(body)
            return body

    return SimpleNamespace(scalar=lambda query: snapshot), Reader(), revision, components, binding


def test_replay_keeps_the_same_native_files_and_original_metadata():
    session, reader, revision, components, binding = replay_case()
    native.verify_registered_native_material(session, reader, revision, components, binding)
    components[("OTHER", 1)].sha256 = "sha256:" + "0" * 64
    with pytest.raises(ValueError, match="REGISTRATION_REPLAY_CONFLICT"):
        native.verify_registered_native_material(session, reader, revision, components, binding)


def test_replay_cannot_replace_an_original_unit_or_invent_an_external_number():
    session, reader, revision, components, binding = replay_case()
    revision.metadata_json["external_number"] = "12345"
    with pytest.raises(ValueError, match="METADATA_BINDING_MISMATCH"):
        native.verify_registered_native_material(session, reader, revision, components, binding)
