"""Catalog pinning uses bounded SELECTs, not full Item/PNG materialization."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from eom_catalog_contracts import CuratedDocumentAssemblyManifestV1
from eom_catalog_contracts.creative_visual_presentation import (
    VISUAL_PRESENTATION_ARTIFACT_TYPE,
    VISUAL_PRESENTATION_CONTENT_SCHEMA_REF,
    VISUAL_PRESENTATION_SCHEMA_REF,
    visual_presentation_key,
)
from eom_catalog_service.curated_delivery_inputs import (
    CuratedDeliveryInputError,
    CuratedDeliveryInputs,
)
from eom_hwpx_contracts.curated_build import CuratedArtifactMember
from eom_identifiers import content_sha256
from sqlalchemy import create_engine

from tests.unit.test_curated_document_assembly_manifest import _manifest, _rehash
from tests.unit.test_curated_document_assembly_resolution import _actor
from tests.unit.test_curated_hwpx_build import build_inputs


def fixture(*, visual=False, version="1.0", count=2, detected_hwpx=False):
    value = _manifest()
    base = value["placements"][1]
    value["placements"] = [
        value["placements"][0],
        *[
            {
                **base,
                "placement_kind": "REGISTERED_ITEM_REVISION",
                "position": index + 2,
                "item_id": f"item_{index + 1:032x}",
                "item_revision_id": f"itemrev_{index + 1:032x}",
                "item_manifest_sha256": "sha256:" + f"{index + 1:064x}",
            }
            for index in range(count)
        ],
    ]
    if detected_hwpx:
        value["placements"][0]["source_format"] = "HWPX"
        value["placements"][0]["document_artifact"]["media_type"] = "application/vnd.hancom.hwpx"
    manifest = CuratedDocumentAssemblyManifestV1.model_validate(_rehash(value))
    tools = build_inputs(manifest)
    artifacts, revisions, jobs, components, item_rows, publications = {}, {}, {}, [], [], []

    def add(pointer, size=256, *, artifact_type="item-content", key=None):
        identity = pointer.artifact_revision_id
        if identity not in revisions:
            job_id = f"job_{len(jobs) + 1:032x}"
            job = SimpleNamespace(
                job_id=job_id,
                status="SUCCEEDED",
                logical_artifact_id=pointer.artifact_id,
                revision_id=identity,
                protocol_version="control-file-set/1.0",
                task_type=artifact_type,
                worker_slot_id=None,
                idempotency_key=key,
            )
            jobs[job_id] = job
            artifacts[pointer.artifact_id] = SimpleNamespace(
                logical_artifact_id=pointer.artifact_id, approved=True, artifact_type=artifact_type
            )
            revision = SimpleNamespace(
                revision_id=identity,
                logical_artifact_id=pointer.artifact_id,
                job_id=job_id,
                approved=True,
                content_hash=pointer.sha256,
                content_bytes=size,
                manifest={
                    "logical_artifact_id": pointer.artifact_id,
                    "revision_id": identity,
                    "job_id": job_id,
                    "primary_file": pointer.member_path,
                    "files": [],
                },
            )
            revisions[identity] = revision
        revision = revisions[identity]
        revision.manifest["files"].append(
            dict(
                file_name=pointer.member_path,
                sha256=pointer.sha256,
                schema_ref=pointer.schema_ref,
                media_type=pointer.media_type,
                bytes=size,
            )
        )
        revision.manifest_hash = content_sha256(revision.manifest)
        return jobs[revision.job_id], revision

    for selected in manifest.placements:
        if selected.placement_kind == "EXTERNAL_SOURCE_DOCUMENT":
            add(
                CuratedArtifactMember.model_validate(selected.document_artifact.model_dump()),
                selected.document_size_bytes,
            )
            continue
        source = CuratedArtifactMember(
            artifact_id=f"artifact_{selected.position + 100:032x}",
            artifact_revision_id=f"rev_{selected.position + 100:032x}",
            member_path="assessment-item-content.json",
            schema_ref=f"eom.assessment.item-content/{version}",
            media_type="application/json",
            sha256="sha256:" + f"{selected.position + 100:064x}",
        )
        add(source)
        metadata = {}
        if version != "1.0":
            markdown = source.model_copy(
                update={
                    "member_path": "content-team-item.md",
                    "schema_ref": "eom://schemas/hwpx/content-team-editorial-markdown/2.0"
                    if version == "3.0"
                    else "eom://schemas/hwpx/content-team-editorial-markdown/1.0",
                    "media_type": "text/markdown",
                    "sha256": "sha256:" + "6" * 64,
                }
            )
            add(markdown)
            metadata = {
                "editorial_markdown_member": markdown.member_path,
                "editorial_markdown_sha256": markdown.sha256,
                "editorial_markdown_schema_ref": markdown.schema_ref,
            }
        components.append(
            SimpleNamespace(
                item_revision_id=selected.item_revision_id,
                artifact_id=source.artifact_id,
                artifact_revision_id=source.artifact_revision_id,
                logical_name=source.member_path,
                schema_ref=source.schema_ref,
                media_type=source.media_type,
                sha256=source.sha256,
                required=True,
                metadata_json=metadata,
            )
        )
        revision = SimpleNamespace(
            item_revision_id=selected.item_revision_id,
            item_id=selected.item_id,
            manifest_sha256=selected.item_manifest_sha256,
            revision_state="APPROVED",
            metadata_json={"source_kind": "CREATIVE" if visual else "AI"},
        )
        item_rows.append((revision, SimpleNamespace(lifecycle_state="ACTIVE")))
        if visual:
            display = source.model_copy(
                update={
                    "artifact_id": f"artifact_{selected.position + 200:032x}",
                    "artifact_revision_id": f"rev_{selected.position + 200:032x}",
                    "schema_ref": VISUAL_PRESENTATION_CONTENT_SCHEMA_REF,
                    "sha256": "sha256:" + f"{selected.position + 200:064x}",
                }
            )
            job, _published = add(
                display,
                artifact_type=VISUAL_PRESENTATION_ARTIFACT_TYPE,
                key=visual_presentation_key(selected.item_revision_id),
            )
            add(
                display.model_copy(
                    update={
                        "member_path": "visual-presentation.json",
                        "schema_ref": VISUAL_PRESENTATION_SCHEMA_REF,
                        "sha256": "sha256:" + "7" * 64,
                    }
                )
            )
            publications.append(job)
    assert tools.handoff is not None
    add(
        CuratedArtifactMember(
            artifact_id=tools.handoff.artifact_id,
            artifact_revision_id=tools.handoff.artifact_revision_id,
            member_path="handoff-source.zip",
            schema_ref="eom://schemas/hwpx/content-team-handoff-archive/1.0",
            media_type="application/zip",
            sha256=tools.handoff.archive_sha256,
        ),
        44_201_901,
    )

    class Session:
        calls = 0

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            pass

        def execute(self, query):
            assert query.is_select
            self.calls += 1
            return SimpleNamespace(all=lambda: item_rows)

        def scalars(self, query):
            assert query.is_select
            self.calls += 1
            entity = query.column_descriptions[0]["entity"].__name__
            if entity == "ItemComponentRecord":
                return tuple(components)
            if entity == "ArtifactRecord":
                return tuple(artifacts.values())
            if entity == "ArtifactRevisionRecord":
                return tuple(revisions.values())
            if "idempotency_key" in str(query.whereclause):
                return tuple(publications)
            return tuple(jobs.values())

    session = Session()
    assemblies = SimpleNamespace(authorize_delivery_build=Mock(return_value=manifest))
    service = CuratedDeliveryInputs(
        create_engine("sqlite://"),
        assemblies=assemblies,
        handoff=tools.handoff,
        converter=tools.converter,
    )
    service.sessions = lambda: session
    return (
        service,
        manifest,
        SimpleNamespace(
            session=session,
            components=components,
            revisions=revisions,
            artifacts=artifacts,
            jobs=jobs,
            publications=publications,
            item_rows=item_rows,
        ),
    )


@pytest.mark.parametrize("count", [1, 100])
def test_exact_metadata_pin_uses_constant_select_count_and_keeps_actor(count):
    service, manifest, data = fixture(count=count)
    actor = _actor()
    plan = service.pin_inputs(manifest, actor=actor)
    assert data.session.calls == 5
    assert [row.position for row in plan.placements] == list(range(1, count + 2))
    assert plan.assembly_revision_id == manifest.assembly_revision_id
    assert plan.converter == service.converter and plan.handoff == service.handoff
    service.assemblies.authorize_delivery_build.assert_called_once_with(
        manifest.assembly_id,
        assembly_revision_id=manifest.assembly_revision_id,
        manifest_sha256=manifest.manifest_sha256,
        actor=actor,
    )
    assert "nas_path" not in plan.model_dump_json()


def test_restored_publication_is_pinned_not_latest_preview_or_old_cropped_media():
    service, manifest, data = fixture(visual=True)
    data.item_rows[0][0].revision_state = "SUPERSEDED"
    plan = service.pin_inputs(manifest, actor=_actor())
    assert data.session.calls == 6
    for row in plan.placements[1:]:
        assert row.source_content != row.display_content
        assert row.recovery_manifest is not None
        assert (
            row.display_content.artifact_revision_id == row.recovery_manifest.artifact_revision_id
        )
    assert plan.placements[1].item_revision_id == manifest.placements[1].item_revision_id


@pytest.mark.parametrize("version", ["2.0", "3.0"])
def test_editorial_schema_and_markdown_are_pinned_without_recasting(version):
    service, manifest, _data = fixture(version=version)
    plan = service.pin_inputs(manifest, actor=_actor())
    row = plan.placements[1]
    assert row.source_content.schema_ref.endswith("/" + version)
    assert row.editorial_markdown is not None
    assert row.editorial_markdown.artifact_id == row.source_content.artifact_id


def test_detected_hwpx_does_not_use_its_misleading_hwp_filename_as_format():
    service, manifest, _data = fixture(detected_hwpx=True)
    plan = service.pin_inputs(manifest, actor=_actor())
    assert plan.placements[0].document.member_path.endswith(".hwp")
    assert plan.placements[0].source_format == "HWPX" and plan.converter is None


@pytest.mark.parametrize(
    "damage",
    [
        "rejected_item",
        "optional_content",
        "duplicate_component",
        "revoked_artifact",
        "failed_producer",
        "manifest_hash",
        "member_schema",
        "duplicate_member",
        "running_visual",
    ],
)
def test_incomplete_revoked_or_changed_pointers_are_explicit_errors(damage):
    service, manifest, data = fixture(visual=damage == "running_visual")
    if damage == "rejected_item":
        data.item_rows[0][0].revision_state = "REJECTED"
    elif damage == "optional_content":
        data.components[0].required = False
    elif damage == "duplicate_component":
        data.components.append(data.components[0])
    elif damage == "revoked_artifact":
        next(iter(data.artifacts.values())).approved = False
    elif damage == "failed_producer":
        next(iter(data.jobs.values())).status = "FAILED"
    elif damage == "running_visual":
        data.publications[0].status = "RUNNING"
    else:
        revision = next(iter(data.revisions.values()))
        if damage == "manifest_hash":
            revision.manifest_hash = "sha256:" + "0" * 64
        elif damage == "member_schema":
            revision.manifest["files"][0]["schema_ref"] = "wrong-schema/1.0"
            revision.manifest_hash = content_sha256(revision.manifest)
        else:
            revision.manifest["files"] *= 2
            revision.manifest_hash = content_sha256(revision.manifest)
    with pytest.raises(CuratedDeliveryInputError, match="POINTER_INVALID"):
        service.pin_inputs(manifest, actor=_actor())
