"""Visual restoration never changes canonical Item, Graph or accepted solution identities."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from eom_catalog_contracts import AssessmentItemContent
from eom_catalog_contracts.creative_visual_derivation import (
    derive_creative_visual_content,
    nonvisual_item_content_sha256,
)
from eom_catalog_contracts.creative_visual_presentation import (
    VISUAL_PRESENTATION_ARTIFACT_TYPE,
    VISUAL_PRESENTATION_CONTENT_SCHEMA_REF,
    VISUAL_PRESENTATION_MEMBER,
    VISUAL_PRESENTATION_SCHEMA_REF,
    CreativeVisualPresentationManifest,
    ItemVisualPresentation,
    ItemVisualPresentationResponse,
    RecoveredSourceVisual,
    visual_presentation_key,
)
from eom_catalog_contracts.item_visual_render_revision import item_visual_render_revision
from eom_catalog_contracts.validation import validate_contract
from eom_catalog_service.creative_visual_presentation_service import (
    CreativeVisualPresentationError,
    CreativeVisualPresentationService,
)
from eom_catalog_service.item_visual_presentation_dispatch import dispatch_item_visual_presentation
from eom_catalog_service.models import ItemRecord, ItemRevisionRecord
from eom_identifiers import canonical_json_bytes, content_sha256
from eom_orchestrator.models import ArtifactRecord, ArtifactRevisionRecord
from eom_protocol.artifact_members import ArtifactMemberPointer
from sqlalchemy import create_engine

from tests.unit.test_assessment_item_content import item_content
from tests.unit.test_catalog_staging import _settings


def pointer(member: str, schema: str, media: str = "application/json", seed: str = "1"):
    return ArtifactMemberPointer(
        artifact_id="artifact_" + seed * 32,
        artifact_revision_id="rev_" + seed * 32,
        member_path=member,
        schema_ref=schema,
        media_type=media,
        sha256="sha256:" + seed * 64,
    )


def fixture():
    canonical = AssessmentItemContent.model_validate(item_content())
    source = pointer("assessment-item-content.json", "eom.assessment.item-content/1.0")
    source = source.model_copy(update={"sha256": content_sha256(canonical.model_dump(mode="json"))})
    value = dict(
        item_id="item_" + "4" * 32,
        item_revision_id="itemrev_" + "5" * 32,
        source_id="extitem_" + "6" * 32,
        source_revision_id="extitemrev_" + "7" * 32,
        canonical_content=source,
        source_document=pointer(
            "source/original.hwp", "intake-source-file/1.0", "application/vnd.hancom.hwp"
        ),
        source_pdf=pointer(
            "preview/original.pdf", "external-item-preview-pdf/1.0", "application/pdf"
        ),
        role_result=pointer("result.json", "external-item-learning-result@2.0"),
        role_work_sha256="sha256:" + "8" * 64,
        content_sha256="sha256:" + "0" * 64,
        nonvisual_content_sha256=nonvisual_item_content_sha256(canonical),
        visuals=[
            dict(
                canonical_block_id="block_image",
                display_block_id="block_restored_" + "a" * 24,
                source_region_id="extregion_" + "b" * 32,
                target_region_id="extregion_" + "c" * 32,
                physical_page=1,
                target_box=dict(left=0, top=0, right=4200, bottom=9000),
                source_images=[
                    dict(
                        source_member="BinData/BIN0001.png",
                        source_member_sha256="sha256:" + "d" * 64,
                        pixel_sha256="sha256:" + "e" * 64,
                        width_px=2000,
                        height_px=1000,
                        source_object_number=17,
                    )
                ],
                member_path="images/" + "f" * 64 + ".png",
                sha256="sha256:" + "f" * 64,
                width_px=2000,
                height_px=1000,
                content_length=2048,
            )
        ],
        authorized_by_operator_id="operator_" + "9" * 32,
        created_at=datetime(2026, 11, 2, tzinfo=UTC),
    )
    # Defaults participate in the canonical manifest hash.
    value["visuals"] = tuple(RecoveredSourceVisual.model_validate(v) for v in value["visuals"])
    shell = CreativeVisualPresentationManifest.model_construct(**value)
    value = shell.model_dump(mode="json")
    value.pop("manifest_sha256", None)
    manifest = CreativeVisualPresentationManifest.model_validate(
        {**value, "manifest_sha256": content_sha256(value)}
    )
    displayed = derive_creative_visual_content(
        canonical,
        manifest,
        artifact_id="artifact_" + "a" * 32,
        artifact_revision_id="rev_" + "b" * 32,
    )
    value["content_sha256"] = content_sha256(displayed.model_dump(mode="json"))
    manifest = CreativeVisualPresentationManifest.model_validate(
        {**value, "manifest_sha256": content_sha256(value)}
    )
    return canonical, manifest, displayed


def presentation():
    canonical, manifest, displayed = fixture()
    display = ArtifactMemberPointer(
        artifact_id="artifact_" + "a" * 32,
        artifact_revision_id="rev_" + "b" * 32,
        member_path="assessment-item-content.json",
        schema_ref=VISUAL_PRESENTATION_CONTENT_SCHEMA_REF,
        media_type="application/json",
        sha256=manifest.content_sha256,
    )
    recovery = ArtifactMemberPointer(
        artifact_id=display.artifact_id,
        artifact_revision_id=display.artifact_revision_id,
        member_path=VISUAL_PRESENTATION_MEMBER,
        schema_ref=VISUAL_PRESENTATION_SCHEMA_REF,
        media_type="application/json",
        sha256=content_sha256(manifest.model_dump(mode="json")),
    )
    return (
        canonical,
        manifest,
        ItemVisualPresentation(
            item_id=manifest.item_id,
            item_revision_id=manifest.item_revision_id,
            source_content=manifest.canonical_content,
            display_content=display,
            recovery_manifest=recovery,
            content=displayed,
        ),
    )


def test_derivation_changes_only_declared_image_identity_and_size():
    canonical, manifest, displayed = fixture()
    before = canonical.model_dump(mode="json")
    actual = displayed.model_dump(mode="json")
    expected = json.loads(json.dumps(before))
    expected["body"][2].update(
        block_id=manifest.visuals[0].display_block_id,
        artifact=actual["body"][2]["artifact"],
        width_px=2000,
        height_px=1000,
    )
    assert actual == expected
    assert canonical.model_dump(mode="json") == before
    assert actual["solution"] == before["solution"]
    assert actual["interaction"] == before["interaction"]
    validate_contract("creative-visual-presentation-v1", manifest.model_dump(mode="json"))


@pytest.mark.parametrize("field", ["title", "solution", "interaction", "alt_text"])
def test_a_changed_scientific_or_descriptive_field_is_not_a_visual_restoration(field):
    canonical, manifest, _ = fixture()
    value = canonical.model_dump(mode="json")
    if field == "title":
        value["title"] += " changed"
    elif field == "solution":
        value["solution"]["explanation"] += " changed"
    elif field == "interaction":
        value["interaction"]["choices"][0]["text"] += " changed"
    else:
        value["body"][2]["alt_text"] += " changed"
    with pytest.raises(ValueError, match="NONVISUAL_MISMATCH"):
        derive_creative_visual_content(
            AssessmentItemContent.model_validate(value),
            manifest,
            artifact_id="artifact_" + "a" * 32,
            artifact_revision_id="rev_" + "b" * 32,
        )


@pytest.mark.parametrize(
    "field,value",
    [("page_captures", 1), ("source_image_crops", 1), ("reference_original_used", True)],
)
def test_captures_crops_and_reference_originals_are_not_admitted(field, value):
    _, manifest, _ = fixture()
    document = manifest.model_dump(mode="json")
    document["visuals"][0][field] = value
    with pytest.raises(ValueError):
        CreativeVisualPresentationManifest.model_validate(document)


def test_render_revision_preserves_original_approval_and_does_not_mutate_source():
    _, _, view = presentation()
    component = dict(
        component_type="ITEM_CONTENT",
        ordinal=0,
        **{
            "artifact_id": view.source_content.artifact_id,
            "artifact_revision_id": view.source_content.artifact_revision_id,
            "logical_name": view.source_content.member_path,
            "schema_ref": view.source_content.schema_ref,
            "media_type": view.source_content.media_type,
            "sha256": view.source_content.sha256,
            "metadata": {},
        },
    )
    revision = dict(
        item_id=view.item_id,
        item_revision_id=view.item_revision_id,
        revision_state="APPROVED",
        manifest_sha256="sha256:" + "8" * 64,
        components=[component],
    )
    before = json.loads(json.dumps(revision))
    rendered = item_visual_render_revision(revision, view)
    assert revision == before
    assert rendered["item_revision_id"] == revision["item_revision_id"]
    assert rendered["manifest_sha256"] == revision["manifest_sha256"]
    assert rendered["components"][0]["sha256"] == view.display_content.sha256
    assert (
        rendered["components"][0]["metadata"]["canonical_content"]["sha256"]
        == view.source_content.sha256
    )
    revision["components"][0]["sha256"] = "sha256:" + "0" * 64
    with pytest.raises(ValueError, match="SOURCE_MISMATCH"):
        item_visual_render_revision(revision, view)


def test_canonical_passthrough_and_response_schema():
    canonical, manifest, view = presentation()
    original = ItemVisualPresentation(
        item_id=view.item_id,
        item_revision_id=view.item_revision_id,
        source_content=view.source_content,
        display_content=view.source_content,
        content=canonical,
    )
    for selected in (view, original):
        response = ItemVisualPresentationResponse(status="OK", presentation=selected)
        validate_contract(
            "catalog-item-visual-presentation-response-v1", response.model_dump(mode="json")
        )
    assert manifest.canonical_content == view.source_content
    assert visual_presentation_key(view.item_revision_id) == visual_presentation_key(
        view.item_revision_id
    )
    assert visual_presentation_key("itemrev_" + "2" * 32) != visual_presentation_key(
        view.item_revision_id
    )


def test_socket_read_is_bounded_typed_and_does_not_accept_model_authority():
    _, _, view = presentation()
    reader = SimpleNamespace(load_item_visual_presentation=Mock(return_value=view))
    request = dict(operation="GET_ITEM_VISUAL_PRESENTATION", item_revision_id=view.item_revision_id)
    result = ItemVisualPresentationResponse.model_validate_json(
        dispatch_item_visual_presentation(reader, canonical_json_bytes(request) + b"\n")
    )
    assert result.presentation == view
    for invalid in ({**request, "role": "ADMIN"}, {**request, "artifact_path": "/etc/passwd"}, {}):
        result = ItemVisualPresentationResponse.model_validate_json(
            dispatch_item_visual_presentation(reader, canonical_json_bytes(invalid) + b"\n")
        )
        assert (
            result.status == "ERROR" and result.error_code == "CATALOG_APPLICATION_REQUEST_INVALID"
        )
    assert reader.load_item_visual_presentation.call_count == 1


def test_socket_failure_does_not_disclose_paths_or_claim_canonical_success():
    reader = SimpleNamespace(
        load_item_visual_presentation=Mock(side_effect=RuntimeError("private path"))
    )
    raw = (
        canonical_json_bytes(
            dict(operation="GET_ITEM_VISUAL_PRESENTATION", item_revision_id="itemrev_" + "1" * 32)
        )
        + b"\n"
    )
    result = dispatch_item_visual_presentation(reader, raw)
    assert b"private path" not in result
    assert ItemVisualPresentationResponse.model_validate_json(result).status == "ERROR"


class FakeReadSession:
    def __init__(
        self, revision, item, component, job=None, artifact=None, published=None, report=None
    ):
        self.records = {
            ItemRevisionRecord: revision,
            ItemRecord: item,
            ArtifactRecord: artifact,
            ArtifactRevisionRecord: published,
        }
        self.scalar_results = [component, job, report]

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def get(self, model, identity):
        return self.records.get(model)

    def scalar(self, statement):
        return self.scalar_results.pop(0)


def read_fixture(monkeypatch, tmp_path):
    canonical, manifest, view = presentation()
    revision = SimpleNamespace(
        item_id=view.item_id,
        revision_state="APPROVED",
        workflow_definition_version="1.0",
        metadata_json=dict(
            source_kind="CREATIVE",
            source_id=manifest.source_id,
            source_revision_id=manifest.source_revision_id,
        ),
    )
    component = SimpleNamespace(
        artifact_id=view.source_content.artifact_id,
        artifact_revision_id=view.source_content.artifact_revision_id,
        logical_name=view.source_content.member_path,
        schema_ref=view.source_content.schema_ref,
        media_type="application/json",
        sha256=view.source_content.sha256,
    )
    report = SimpleNamespace(
        artifact_id=manifest.role_result.artifact_id,
        artifact_revision_id=manifest.role_result.artifact_revision_id,
        logical_name=manifest.role_result.member_path,
        schema_ref=manifest.role_result.schema_ref,
        media_type="application/json",
        sha256=manifest.role_result.sha256,
    )
    job = SimpleNamespace(
        status="SUCCEEDED",
        protocol_version="control-file-set/1.0",
        task_type=VISUAL_PRESENTATION_ARTIFACT_TYPE,
        worker_slot_id=None,
        logical_artifact_id=view.display_content.artifact_id,
        revision_id=view.display_content.artifact_revision_id,
        job_id="job_" + "a" * 32,
    )
    artifact = SimpleNamespace(approved=True, artifact_type=VISUAL_PRESENTATION_ARTIFACT_TYPE)
    published = SimpleNamespace(
        approved=True,
        logical_artifact_id=job.logical_artifact_id,
        job_id=job.job_id,
        manifest=dict(
            primary_file="assessment-item-content.json",
            files=[
                dict(
                    file_name=VISUAL_PRESENTATION_MEMBER,
                    sha256=view.recovery_manifest.sha256,
                    schema_ref=VISUAL_PRESENTATION_SCHEMA_REF,
                )
            ],
        ),
    )
    session = FakeReadSession(
        revision,
        SimpleNamespace(lifecycle_state="ACTIVE"),
        component,
        job,
        artifact,
        published,
        report,
    )
    service = CreativeVisualPresentationService(
        create_engine("sqlite://"),
        source=SimpleNamespace(load_item_content=Mock(return_value=canonical)),
        settings=_settings(tmp_path),
    )
    service.sessions = lambda: session
    bodies = {
        VISUAL_PRESENTATION_MEMBER: canonical_json_bytes(manifest.model_dump(mode="json")),
        "assessment-item-content.json": canonical_json_bytes(view.content.model_dump(mode="json")),
    }

    def resolve(session, settings, **request):
        assert request["expected_artifact_types"] == {VISUAL_PRESENTATION_ARTIFACT_TYPE}
        assert request["expected_primary_file"] == "assessment-item-content.json"
        payload = bodies[request["member_path"]]
        assert content_sha256(json.loads(payload)) == request["sha256"]
        return SimpleNamespace(payload=payload)

    monkeypatch.setattr(
        "eom_catalog_service.creative_visual_presentation_service.resolve_pinned_artifact_member",
        resolve,
    )
    return service, session, view, bodies


def test_read_keeps_all_canonical_sources_and_selects_the_exact_rendering(monkeypatch, tmp_path):
    service, _, view, _ = read_fixture(monkeypatch, tmp_path)
    assert service.read(view.item_revision_id) == view


@pytest.mark.parametrize(
    "condition", ["failed", "worker", "unapproved", "missing_manifest", "retired"]
)
def test_invalid_registered_restoration_never_silently_falls_back(monkeypatch, tmp_path, condition):
    service, session, view, _ = read_fixture(monkeypatch, tmp_path)
    if condition == "failed":
        session.scalar_results[1].status = "FAILED"
    elif condition == "worker":
        session.scalar_results[1].worker_slot_id = "support-05"
    elif condition == "unapproved":
        session.records[ArtifactRecord].approved = False
    elif condition == "missing_manifest":
        session.records[ArtifactRevisionRecord].manifest["files"] = []
    else:
        session.records[ItemRecord].lifecycle_state = "RETIRED"
    with pytest.raises(CreativeVisualPresentationError):
        service.read(view.item_revision_id)


def test_missing_recovery_is_an_explicit_canonical_projection(monkeypatch, tmp_path):
    service, session, view, _ = read_fixture(monkeypatch, tmp_path)
    session.scalar_results[1] = None
    result = service.read(view.item_revision_id)
    assert result.recovery_manifest is None
    assert result.source_content == result.display_content == view.source_content
