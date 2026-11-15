"""Nonlive owner composition: fake canonical ports, real contracts, no DB/NAS/parser/model.

These tests prove correction validation/delegation, not PostgreSQL concurrency or
actual corpus pixels. The existing reviewed-import/Registry owner retains CAS.
"""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest
from eom_catalog_contracts.assessment_item import AssessmentItemContent, ImageBlock
from eom_catalog_contracts.creative_source_visuals import CREATIVE_SOURCE_VISUAL_IMAGE_REF
from eom_catalog_contracts.material_item_lineage import (
    MATERIAL_ITEM_LINEAGE_REF,
    MaterialItemLineage,
)
from eom_catalog_contracts.material_learning import MaterialArtifactMember, MaterialExtractionWork
from eom_catalog_contracts.material_native_files import (
    MaterialImportedNativeItemMetadata,
    MaterialNativeItemBinding,
)
from eom_catalog_contracts.material_native_item_read import MaterialNativeItemSource
from eom_catalog_contracts.material_native_visual_correction import (
    MaterialNativeVisualCorrectionCommand,
    MaterialNativeVisualCorrectionPrepared,
    MaterialNativeVisualCorrectionResult,
)
from eom_catalog_contracts.material_native_visual_selection import (
    build_material_native_question_visual_scope,
)
from eom_catalog_contracts.validation import load_schema, validate_contract
from eom_catalog_service import material_native_visual_correction as owner
from eom_catalog_service.models import ItemRecord, ItemRevisionRecord
from eom_identifiers import canonical_json_bytes, content_sha256, sha256_bytes
from eom_operator_identity import PermissionKey
from eom_protocol.artifact_members import ArtifactMemberPointer
from pydantic import ValidationError

from tests.unit.test_assessment_item_content import item_content
from tests.unit.test_material_learning_contracts import rehash
from tests.unit.test_material_learning_intake import ACTOR
from tests.unit.test_material_native_files import binding_data, metadata_data, native_work
from tests.unit.test_material_native_visual_preparation_service import Artifacts, _real_catalog

BASE = "itemrev_" + "1" * 32
NEXT = "itemrev_" + "2" * 32
ITEM = "item_" + "3" * 32
MANIFEST = "sha256:" + "4" * 64


def _pointer(pointer):
    return ArtifactMemberPointer.model_validate(pointer.model_dump(exclude={"bytes"}))


@pytest.fixture
def correction(monkeypatch):
    events = []
    artifacts = Artifacts(events)
    state = SimpleNamespace(
        permission=True, active=None, imports=0, import_failure=None, counter=10
    )

    def put(value, member, schema):
        state.counter += 1
        pointer_type = (
            ArtifactMemberPointer if schema.startswith("eom.") else MaterialArtifactMember
        )
        pointer = pointer_type(
            artifact_id=f"artifact_{state.counter:032x}",
            artifact_revision_id=f"rev_{state.counter + 100:032x}",
            member_path=member,
            schema_ref=schema,
            media_type="application/json",
            sha256="sha256:" + "0" * 64,
            **({} if schema.startswith("eom.") else {"bytes": 1}),
        )
        return artifacts.put(pointer, canonical_json_bytes(value.model_dump(mode="json")))

    value = item_content()
    value["body"] = [block for block in value["body"] if block["type"] != "image"]
    content = AssessmentItemContent.model_validate(value)
    content_pointer = put(
        content, "assessment-item-content.json", "eom.assessment.item-content/1.0"
    )
    binding = MaterialNativeItemBinding.model_validate(binding_data())
    binding_pointer = put(
        binding, "native/binding.json", "eom://schemas/material-learning/native-item-binding/1.0"
    )
    catalog, payloads = _real_catalog(binding.question.original_source_sha256)
    catalog_pointer = put(
        catalog,
        "picture-use-catalog.json",
        "eom://schemas/image-provider/office-picture-use-catalog/1.0",
    )
    for view in catalog.rendered_uses:
        artifacts.put(
            MaterialArtifactMember(
                artifact_id=catalog_pointer.artifact_id,
                artifact_revision_id=catalog_pointer.artifact_revision_id,
                member_path=view.member_path,
                schema_ref=CREATIVE_SOURCE_VISUAL_IMAGE_REF,
                media_type="image/png",
                sha256=view.sha256,
                bytes=view.content_length,
            ),
            payloads[view.member_path],
        )
    work_data = native_work()
    work_data["sources"][0]["office_catalog"] = catalog_pointer.model_dump(mode="json")
    work = MaterialExtractionWork.model_validate(rehash(work_data))
    work_pointer = put(
        work, "material/work.json", "eom://schemas/material-learning/extraction-work/1.0"
    )
    report = ArtifactMemberPointer(
        artifact_id="artifact_" + "8" * 32,
        artifact_revision_id="rev_" + "9" * 32,
        member_path="result.json",
        schema_ref="material-learning-result@1.0",
        media_type="application/json",
        sha256="sha256:" + "a" * 64,
    )
    lineage_data = dict(
        schema_version="material-learning-item-lineage/1.0",
        material_id=work.material_id,
        material_revision_id=work.material_revision_id,
        task_id=work.task_id,
        unit_key=work.unit_key,
        selection=dict(
            schema_version="material-learning-authorization-request/1.0",
            operation="AUTHORIZE_MATERIAL_LEARNING_INPUT",
            workflow_id="workflow_" + "1" * 32,
            step_run_id="steprun_" + "2" * 32,
            plan_id="execplan_" + "3" * 32,
            plan_sha256="sha256:" + "4" * 64,
            input_sha256=work.input_sha256,
        ),
        work_input=work_pointer.model_dump(mode="json"),
        role_result=report.model_dump(mode="json"),
        input_sha256=work.input_sha256,
        result_sha256="sha256:" + "b" * 64,
        proposed_content_sha256=content_pointer.sha256,
        registered_content_sha256=content_pointer.sha256,
        source_answer_mode="EDITORIAL_SOURCE",
        warning_codes=[],
        registration_policy="PRESERVE_SOURCE_WITH_REVIEW_WARNINGS_V1",
        requested_by=ACTOR,
        created_at="2026-11-15T00:00:00Z",
    )
    lineage = MaterialItemLineage.model_validate(rehash(lineage_data, "lineage_sha256"))
    lineage_pointer = put(lineage, "lineage.json", MATERIAL_ITEM_LINEAGE_REF)
    metadata = MaterialImportedNativeItemMetadata.model_validate(
        metadata_data()
        | {
            "native_binding": binding_pointer.model_dump(mode="json"),
            "lineage_sha256": lineage.lineage_sha256,
        }
    )

    def component(kind, ordinal, pointer):
        return SimpleNamespace(
            component_type=kind,
            ordinal=ordinal,
            schema_ref=pointer.schema_ref,
            media_type=pointer.media_type,
            artifact_id=pointer.artifact_id,
            artifact_revision_id=pointer.artifact_revision_id,
            sha256=pointer.sha256,
            logical_name=pointer.member_path,
            required=True,
            metadata_json={"TEST_ONLY": kind},
        )

    components = tuple(
        sorted(
            (
                component("ITEM_CONTENT", 0, content_pointer),
                component("SOURCE_REFERENCE", 0, lineage_pointer),
                component("REVIEW_REPORT", 0, report),
                component("METADATA", 0, binding_pointer),
                component("OTHER", 0, binding.question.document),
                component("OTHER", 1, binding.solution.document),
            ),
            key=lambda row: (row.component_type, row.ordinal),
        )
    )
    state.item = SimpleNamespace(item_id=ITEM, lifecycle_state="ACTIVE", current_revision_id=BASE)
    state.rows = {
        BASE: SimpleNamespace(
            item_revision_id=BASE,
            item_id=ITEM,
            revision_state="APPROVED",
            manifest_sha256=MANIFEST,
            lock_version=1,
            metadata_json=metadata.model_dump(mode="json"),
        )
    }
    state.components, state.contents = {BASE: components}, {BASE: content}
    state.metadata, state.work, state.binding = metadata, work, binding
    state.catalog, state.catalog_pointer = catalog, catalog_pointer
    state.question_catalog, _ = _real_catalog(binding.question.document.sha256, native=True)
    state.artifacts, state.events, state.saved = artifacts, events, {}
    state.source_checks = []

    class Session:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def get(self, model, key, **_kwargs):
            if model is ItemRecord:
                return state.item if key == ITEM else None
            assert model is ItemRevisionRecord
            return state.rows.get(key)

        def scalar(self, _statement):
            return state.active

        def scalars(self, statement):
            revision_id = next(iter(statement.compile().params.values()))
            return state.components[revision_id]

    def authorize(_session, actor_id):
        state.events.append(("authorize", actor_id))
        if not state.permission:
            raise ValueError("TEST_READ_PERMISSION_REVOKED")

    monkeypatch.setattr(owner, "authorize_native_material_read", authorize)
    monkeypatch.setattr(
        owner,
        "effective_permissions",
        lambda *_args: {PermissionKey.ITEM_STRUCTURED_CONTENT_IMPORT},
    )
    monkeypatch.setattr(
        owner,
        "pin_material_primary",
        lambda _session, pointer: SimpleNamespace(
            pointer=artifacts.values[
                pointer.artifact_id, pointer.artifact_revision_id, pointer.member_path
            ][0]
        ),
    )

    def reauthorize(_session, *, operator_id, work):
        assert operator_id == ACTOR and work == state.work
        state.events.append(("source-authorize", work.task_id))

    def read_source(request):
        state.source_checks.append(request)
        assert request.actor_id == ACTOR
        if request.item_manifest_sha256 != state.rows[request.item_revision_id].manifest_sha256:
            raise ValueError("TEST_NATIVE_MANIFEST_MISMATCH")
        return MaterialNativeItemSource(
            material_title="TEST_ONLY",
            metadata=state.metadata,
            question=binding.question.document,
            solution=binding.solution.document,
            workbook=binding.workbook,
        )

    def question_scope(file, *, item_number, catalog, catalog_pointer, authorize):
        authorize()
        actual = build_material_native_question_visual_scope(
            file,
            item_number=item_number,
            source_catalog=catalog,
            source_catalog_sha256=catalog_pointer.sha256,
            question_catalog=state.question_catalog,
        )
        authorize()
        return actual

    def import_reviewed(base_id, corrected, *, reviewed_by, review_reason, expected_version):
        key = (
            base_id,
            content_sha256(corrected.model_dump(mode="json")),
            reviewed_by,
            review_reason,
        )
        if key in state.saved:
            return state.saved[key]
        if state.import_failure:
            raise RuntimeError(state.import_failure)
        if (
            state.item.current_revision_id != base_id
            or state.rows[base_id].lock_version != expected_version
        ):
            raise ValueError("TEST_EXISTING_OWNER_CAS_STALE")
        assert reviewed_by == ACTOR and review_reason.startswith(
            "Reviewed Native image-only insertion: sha256:"
        )
        pointer = put(corrected, "assessment-item-content.json", "eom.assessment.item-content/1.0")
        state.imports += 1
        state.contents[NEXT] = corrected
        state.components[NEXT] = tuple(
            component("ITEM_CONTENT", 0, pointer)
            if row.component_type == "ITEM_CONTENT"
            else deepcopy(row)
            for row in state.components[BASE]
        )
        state.rows[NEXT] = SimpleNamespace(
            item_revision_id=NEXT,
            item_id=ITEM,
            revision_state="APPROVED",
            lock_version=1,
            manifest_sha256="sha256:" + "c" * 64,
            metadata_json=deepcopy(state.rows[BASE].metadata_json),
        )
        state.rows[BASE].revision_state = "SUPERSEDED"
        state.rows[BASE].lock_version += 1
        state.item.current_revision_id = NEXT
        result = SimpleNamespace(
            item_id=ITEM,
            item_revision_id=NEXT,
            resource_version=1,
            content_artifact_id=pointer.artifact_id,
            content_artifact_revision_id=pointer.artifact_revision_id,
            content_sha256=pointer.sha256,
        )
        state.saved[key] = result
        return result

    service = object.__new__(owner.MaterialNativeVisualCorrectionService)
    service.sessions, service.artifacts = Session, artifacts
    service.sources = SimpleNamespace(reauthorize=reauthorize)
    service.native_sources = SimpleNamespace(read_source=read_source)
    service.native_visuals = SimpleNamespace(question_scope=question_scope)
    service.registry = SimpleNamespace(
        load_item_content=lambda revision_id: state.contents[revision_id]
    )
    service.imports = SimpleNamespace(import_reviewed=import_reviewed)
    command = MaterialNativeVisualCorrectionCommand(
        actor_id=ACTOR,
        base_item_revision_id=BASE,
        base_item_manifest_sha256=MANIFEST,
        expected_version=1,
        picture_use_id=catalog.picture_uses[0].use_id,
        insert_after_block_id="block_stem",
    )
    return service, command, state


def test_prepare_is_read_only_and_inserts_one_exact_existing_png_pointer(correction):
    service, command, state = correction
    before = deepcopy(state.contents[BASE].model_dump(mode="json"))
    prepared = service.prepare(command)
    assert prepared == service.prepare(command)
    assert state.imports == 0 and state.item.current_revision_id == BASE
    assert state.contents[BASE].model_dump(mode="json") == before
    assert prepared.image.artifact.artifact_id == state.catalog_pointer.artifact_id
    assert prepared.image.artifact.sha256 == state.catalog.rendered_uses[0].sha256
    assert prepared.image.width_px == state.catalog.rendered_uses[0].width_px
    assert prepared.source_task_id == state.work.task_id
    assert len(state.source_checks) == 2


def test_reviewed_import_preserves_all_other_values_components_and_old_history(correction):
    service, command, state = correction
    prepared = service.prepare(command)
    before = deepcopy(state.contents[BASE].model_dump(mode="json"))
    old_components = deepcopy(state.components[BASE])
    receipt = service.import_reviewed(command, prepared=prepared)
    actual = state.contents[NEXT].model_dump(mode="json")
    image = actual["body"].pop(1)
    assert actual == before and image == prepared.image.model_dump(mode="json")
    assert state.contents[BASE].model_dump(mode="json") == before
    assert state.components[BASE] == old_components
    assert [row for row in state.components[NEXT] if row.component_type != "ITEM_CONTENT"] == [
        row for row in old_components if row.component_type != "ITEM_CONTENT"
    ]
    assert state.rows[NEXT].metadata_json == state.rows[BASE].metadata_json
    assert (
        receipt.item_revision_id == NEXT and receipt.prepared.command.base_item_revision_id == BASE
    )
    assert state.source_checks[-1].item_revision_id == NEXT


def test_exact_replay_delegates_to_existing_owner_without_second_revision(correction):
    service, command, state = correction
    prepared = service.prepare(command)
    first = service.import_reviewed(command, prepared=prepared)
    assert service.import_reviewed(command, prepared=prepared) == first
    assert state.imports == 1
    with pytest.raises(ValueError, match="BASE_STALE"):
        service.prepare(command)


def applied_correction(correction):
    """Supplement the synthetic Registry port with its real stored import provenance."""
    service, command, state = correction
    prepared = service.prepare(command)
    receipt = service.import_reviewed(command, prepared=prepared)
    state.rows[BASE].superseded_by_revision_id = NEXT
    state.rows[BASE].content_pack_release_id = "packrelease_native"
    state.rows[NEXT].content_pack_release_id = "packrelease_native"
    state.rows[NEXT].created_by = command.actor_id
    state.rows[NEXT].approved_by = command.actor_id
    content = next(
        value for value in state.components[NEXT] if value.component_type == "ITEM_CONTENT"
    )
    content.metadata_json = dict(
        import_protocol="reviewed-structured-item-content/1.0",
        reviewed_by=command.actor_id,
        review_reason="Reviewed Native image-only insertion: " + prepared.prepared_sha256,
        base_revision_id=BASE,
    )
    return service, receipt, state


def test_applied_receipt_revalidates_source_current_native_and_image_only_content(correction):
    service, receipt, state = applied_correction(correction)
    snapshot = deepcopy(state.contents[BASE].model_dump(mode="json"))
    assert (
        service.validate_applied(receipt, actor_id=receipt.prepared.command.actor_id)
        == receipt.prepared
    )
    assert (
        service.validate_applied(receipt, actor_id=receipt.prepared.command.actor_id)
        == receipt.prepared
    )
    assert state.imports == 1
    assert state.contents[BASE].model_dump(mode="json") == snapshot
    assert state.source_checks[-1].item_revision_id == NEXT


@pytest.mark.parametrize(
    "changed",
    [
        "actor",
        "current",
        "state",
        "version",
        "manifest",
        "pack",
        "parent",
        "metadata",
        "component",
        "provenance",
        "content",
        "permission",
    ],
)
def test_applied_receipt_is_not_authority_for_a_stale_or_unreviewed_successor(correction, changed):
    service, receipt, state = applied_correction(correction)
    actor = receipt.prepared.command.actor_id
    if changed == "actor":
        actor = "operator_" + "f" * 32
    elif changed == "current":
        state.item.current_revision_id = BASE
    elif changed == "state":
        state.rows[NEXT].revision_state = "SUPERSEDED"
    elif changed == "version":
        state.rows[NEXT].lock_version += 1
    elif changed == "manifest":
        state.rows[NEXT].manifest_sha256 = "sha256:" + "f" * 64
    elif changed == "pack":
        state.rows[NEXT].content_pack_release_id = "unrelated_release"
    elif changed == "parent":
        state.rows[BASE].superseded_by_revision_id = "itemrev_" + "f" * 32
    elif changed == "metadata":
        state.rows[NEXT].metadata_json["title"] = "changed"
    elif changed == "component":
        next(
            value for value in state.components[NEXT] if value.component_type == "REVIEW_REPORT"
        ).sha256 = "sha256:" + "f" * 64
    elif changed == "provenance":
        next(
            value for value in state.components[NEXT] if value.component_type == "ITEM_CONTENT"
        ).metadata_json["review_reason"] = "not reviewed"
    elif changed == "content":
        state.contents[NEXT] = state.contents[BASE]
    else:
        state.permission = False
    with pytest.raises(ValueError):
        service.validate_applied(receipt, actor_id=actor)
    assert state.imports == 1


def test_permission_revocation_during_applied_content_read_is_rechecked(correction):
    service, receipt, state = applied_correction(correction)
    original = service.registry.load_item_content

    def read(revision):
        value = original(revision)
        if revision == NEXT:
            state.permission = False
        return value

    service.registry.load_item_content = read
    with pytest.raises(ValueError, match="PERMISSION_REVOKED"):
        service.validate_applied(receipt, actor_id=receipt.prepared.command.actor_id)
    assert state.imports == 1


@pytest.mark.parametrize(
    "changed",
    ["manifest", "version", "current", "state", "active", "actor", "permission", "lineage"],
)
def test_wrong_or_active_source_rejected_before_import(correction, changed):
    service, command, state = correction
    if changed == "manifest":
        command = command.model_copy(update={"base_item_manifest_sha256": "sha256:" + "f" * 64})
    elif changed == "version":
        command = command.model_copy(update={"expected_version": 2})
    elif changed == "current":
        state.item.current_revision_id = NEXT
    elif changed == "state":
        state.rows[BASE].revision_state = "RETIRED"
    elif changed == "active":
        state.active = "materialrun_" + "f" * 32
    elif changed == "actor":
        command = command.model_copy(update={"actor_id": "operator_" + "e" * 32})
    elif changed == "permission":
        state.permission = False
    else:
        state.rows[BASE].metadata_json["lineage_sha256"] = "sha256:" + "f" * 64
    with pytest.raises(ValueError):
        service.prepare(command)
    assert state.imports == 0


def test_other_question_or_reference_use_is_not_admitted_from_global_catalog(correction):
    service, command, state = correction
    command = command.model_copy(update={"picture_use_id": state.catalog.picture_uses[1].use_id})
    with pytest.raises(ValueError, match="USE_OUT_OF_SCOPE"):
        service.prepare(command)


@pytest.mark.parametrize("changed", ["bytes", "dimensions", "hash"])
def test_exact_png_member_is_revalidated(correction, changed):
    service, command, state = correction
    view = state.catalog.rendered_uses[0]
    key = (
        state.catalog_pointer.artifact_id,
        state.catalog_pointer.artifact_revision_id,
        view.member_path,
    )
    pointer, raw = state.artifacts.values[key]
    if changed == "bytes":
        raw = raw[:-1]
    elif changed == "dimensions":
        raw = raw[:16] + b"\0\0\0\1" + raw[20:]
        pointer = pointer.model_copy(update={"sha256": sha256_bytes(raw)})
    else:
        pointer = pointer.model_copy(update={"sha256": "sha256:" + "f" * 64})
    state.artifacts.values[key] = pointer, raw
    with pytest.raises(ValueError):
        service.prepare(command)
    assert state.imports == 0


def test_operator_permission_revocation_after_prepare_blocks_import(correction):
    service, command, state = correction
    prepared = service.prepare(command)
    state.permission = False
    with pytest.raises(ValueError, match="PERMISSION_REVOKED"):
        service.import_reviewed(command, prepared=prepared)
    assert state.imports == 0


def test_changed_review_input_and_import_failure_do_not_change_original(correction):
    service, command, state = correction
    prepared = service.prepare(command)
    changed = command.model_copy(update={"insert_after_block_id": "block_prompt"})
    with pytest.raises(ValueError, match="PREPARATION_CHANGED"):
        service.import_reviewed(changed, prepared=prepared)
    state.import_failure = "TEST_EXISTING_IMPORT_FAILED"
    with pytest.raises(RuntimeError, match="TEST_EXISTING_IMPORT_FAILED"):
        service.import_reviewed(command, prepared=prepared)
    assert state.imports == 0 and state.item.current_revision_id == BASE


def test_existing_import_owner_still_handles_final_cas(correction):
    service, command, state = correction
    prepared = service.prepare(command)
    state.item.current_revision_id = NEXT
    with pytest.raises(ValueError, match="EXISTING_OWNER_CAS_STALE"):
        service.import_reviewed(command, prepared=prepared)
    assert state.imports == 0


def test_missing_insertion_block_and_duplicate_image_rejected(correction):
    service, command, state = correction
    with pytest.raises(ValueError, match="INSERTION_INVALID"):
        service.prepare(command.model_copy(update={"insert_after_block_id": "block_unknown"}))
    prepared = service.prepare(command)
    canonical = state.contents[BASE]
    corrected = owner.insert_native_visual_image(
        canonical, image=prepared.image, insert_after_block_id="block_stem"
    )
    with pytest.raises(ValueError, match="ALREADY_REPRESENTED"):
        owner.insert_native_visual_image(
            corrected, image=prepared.image, insert_after_block_id="block_stem"
        )


def test_native_equation_and_every_other_unselected_value_stays_unchanged(correction):
    service, command, state = correction
    before = state.contents[BASE]
    prepared = service.prepare(command)
    corrected = owner.insert_native_visual_image(
        before, image=prepared.image, insert_after_block_id="block_stem"
    )
    assert (
        tuple(block for block in corrected.body if not isinstance(block, ImageBlock)) == before.body
    )
    assert corrected.solution == before.solution and corrected.interaction == before.interaction


def test_contracts_are_closed_canonical_hash_bound_and_mirrored(correction):
    service, command, _state = correction
    prepared = service.prepare(command)
    result = service.import_reviewed(command, prepared=prepared)
    for key, model in (
        ("command", command),
        ("prepared", prepared),
        ("result", result),
    ):
        schema_key = f"material-native-visual-correction-{key}-v1"
        validate_contract(schema_key, model.model_dump(mode="json"))
        root = Path(__file__).resolve().parents[2]
        path = f"material-learning/{schema_key}.schema.json"
        assert (root / "schemas" / path).read_bytes() == (
            root / "packages/catalog_contracts/eom_catalog_contracts/resources" / path
        ).read_bytes()
        assert load_schema(schema_key)["additionalProperties"] is False
    with pytest.raises(ValidationError):
        MaterialNativeVisualCorrectionCommand.model_validate(
            command.model_dump() | {"image_path": "/TEST_ONLY"}
        )
    with pytest.raises(ValidationError, match="PREPARATION_INVALID"):
        MaterialNativeVisualCorrectionPrepared.model_validate(
            prepared.model_dump() | {"prepared_sha256": "sha256:" + "f" * 64}
        )
    with pytest.raises(ValidationError, match="RESULT_INVALID"):
        MaterialNativeVisualCorrectionResult.model_validate(
            result.model_dump() | {"item_revision_id": BASE}
        )
