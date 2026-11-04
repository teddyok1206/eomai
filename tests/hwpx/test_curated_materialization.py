"""Pinned real Item bytes -> shared workspace -> real mixed Builder."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from eom_catalog_contracts.creative_visual_derivation import derive_creative_visual_content
from eom_hwpx_builder.curated_renderer import render_curated_workspace
from eom_hwpx_builder.util import canonical_json_bytes, sha256_bytes, sha256_file
from eom_hwpx_contracts.curated_build import (
    CuratedArtifactMember,
    CuratedHwpxBuildInput,
    CuratedNativeDocumentInput,
    CuratedRegisteredItemInput,
)
from eom_hwpx_contracts.curated_mixed import CuratedEditorialSegment
from eom_hwpx_contracts.native_item_semantics import expected_native_item_events
from eom_hwpx_manager.adapter import copy_stable_regular_file
from eom_hwpx_manager.curated_materialization import CuratedInputMaterializer
from eom_hwpx_manager.errors import HwpxManagerError
from eom_identifiers import content_sha256

from tests.hwpx.test_curated_mixed_renderer import (
    BUILD_ID,
    save,
    stage_mixed,
)
from tests.hwpx.test_curated_mixed_renderer import (
    handoff_bytes as handoff_bytes,
)
from tests.hwpx.test_native_item import content_and_projection, image_bytes
from tests.unit.test_creative_visual_presentation import presentation


class Members:
    def __init__(self):
        self.files = {}
        self.calls = []

    def add(self, path, position, member, schema, media):
        pointer = CuratedArtifactMember(
            artifact_id=f"artifact_{position:032x}",
            artifact_revision_id=f"rev_{position:032x}",
            member_path=member,
            schema_ref=schema,
            media_type=media,
            sha256=sha256_file(path),
        )
        self.files[(pointer.artifact_id, pointer.artifact_revision_id, pointer.member_path)] = (
            pointer,
            path,
        )
        return pointer

    def resolve_members(self, pointers):
        self.calls.append(pointers)
        paths = []
        for value in pointers:
            pointer, path = self.files[(value.artifact_id, value.revision_id, value.member_name)]
            assert pointer.sha256 == value.expected_sha256 == sha256_file(path)
            assert pointer.media_type == value.media_type
            assert value.schema_ref is None or value.schema_ref == pointer.schema_ref
            assert path.stat().st_size <= value.max_bytes
            paths.append(path)
        return tuple(paths)


class Stager:
    def __init__(self):
        self.staged = []

    def stage_file(self, workspace, name, source, *, expected_sha256):
        target = workspace / name
        target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        copy_stable_regular_file(source, target, expected_sha256=expected_sha256)
        target.chmod(0o440)
        self.staged.append(name)
        return target

    def write_json(self, workspace, name, value):
        return save(workspace, name, canonical_json_bytes(value) + b"\n")


def component(pointer, *, kind="ITEM_CONTENT", ordinal=0, metadata=None):
    return dict(
        component_type=kind,
        ordinal=ordinal,
        artifact_id=pointer.artifact_id,
        artifact_revision_id=pointer.artifact_revision_id,
        logical_name=pointer.member_path,
        schema_ref=pointer.schema_ref,
        media_type=pointer.media_type,
        sha256=pointer.sha256,
        metadata=metadata or {},
    )


def cohort(tmp_path, handoff):
    source_root = tmp_path / "source"
    mixed, _plans = stage_mixed(source_root, handoff)
    members = Members()
    revisions = []
    document = members.add(
        source_root / "inputs/001.hwpx",
        1,
        "source/original.hwpx",
        "eom://schemas/content-intake/source-file/1.0",
        "application/vnd.hancom.hwpx",
    )
    placements = [
        CuratedNativeDocumentInput(
            position=1,
            source_format="HWPX",
            document=document,
            size_bytes=(source_root / "inputs/001.hwpx").stat().st_size,
        )
    ]
    canonical = {}
    for position in (2, 3, 4, 5):
        markdown_pointer = None
        images = []
        if position in (2, 3):
            content, projection, data = content_and_projection(
                repeated_image=position == 2, body=(0, 1, 4) if position == 3 else None
            )
            canonical[position] = content
            raw = canonical_json_bytes(content.model_dump(mode="json"))
            path = save(source_root, f"registered/{position:03d}.json", raw)
            schema = "eom.assessment.item-content/1.0"
            for binding in projection.images:
                image = save(source_root, binding.image.local_file, data)
                pointer = members.add(
                    image,
                    60,
                    binding.source.artifact_member,
                    "existing-canonical-image/1.0",
                    binding.source.media_type,
                )
                # The canonical source body, not this fixture's sequence, owns the
                # exact image identity. No image schema is invented in its body.
                members.files[
                    (
                        binding.source.artifact_id,
                        binding.source.artifact_revision_id,
                        binding.source.artifact_member,
                    )
                ] = (
                    pointer.model_copy(
                        update={
                            "artifact_id": binding.source.artifact_id,
                            "artifact_revision_id": binding.source.artifact_revision_id,
                        }
                    ),
                    image,
                )
        else:
            segment = mixed.segments[position - 1]
            assert isinstance(segment, CuratedEditorialSegment)
            path = source_root / segment.json_file
            schema = segment.source_schema_ref
            markdown_pointer = members.add(
                source_root / segment.markdown_file,
                position,
                "content-team-item.md",
                "eom://schemas/hwpx/content-team-editorial-markdown/2.0"
                if position == 5
                else "eom://schemas/hwpx/content-team-editorial-markdown/1.0",
                "text/markdown",
            )
            for image in segment.images:
                pointer = members.add(
                    source_root / image.local_file,
                    70 + image.binding.visual_ordinal,
                    image.binding.artifact_member,
                    image.binding.schema_ref,
                    image.binding.media_type,
                )
                members.files[
                    (
                        image.binding.artifact_id,
                        image.binding.artifact_revision_id,
                        image.binding.artifact_member,
                    )
                ] = (pointer, source_root / image.local_file)
                images.append(
                    component(
                        pointer.model_copy(
                            update={
                                "artifact_id": image.binding.artifact_id,
                                "artifact_revision_id": image.binding.artifact_revision_id,
                            }
                        ),
                        kind="IMAGE",
                        ordinal=image.binding.visual_ordinal,
                        metadata=image.binding.model_dump(),
                    )
                )
        source = members.add(
            path, position, "assessment-item-content.json", schema, "application/json"
        )
        placement = CuratedRegisteredItemInput(
            position=position,
            item_id=f"item_{position:032x}",
            item_revision_id=f"itemrev_{position:032x}",
            item_manifest_sha256="sha256:" + f"{position:064x}",
            source_content=source,
            display_content=source,
            recovery_manifest=None,
            editorial_markdown=markdown_pointer,
        )
        placements.append(placement)
        revisions.append(
            dict(
                item_id=placement.item_id,
                item_revision_id=placement.item_revision_id,
                manifest_sha256=placement.item_manifest_sha256,
                revision_state="APPROVED",
                components=[component(source), *images],
            )
        )
    assert mixed.handoff is not None
    members.files[
        (mixed.handoff.artifact_id, mixed.handoff.artifact_revision_id, "handoff-source.zip")
    ] = (
        CuratedArtifactMember(
            artifact_id=mixed.handoff.artifact_id,
            artifact_revision_id=mixed.handoff.artifact_revision_id,
            member_path="handoff-source.zip",
            schema_ref="eom://schemas/hwpx/content-team-handoff-archive/1.0",
            media_type="application/zip",
            sha256=mixed.handoff.archive_sha256,
        ),
        source_root / "input/handoff.zip",
    )
    plan = CuratedHwpxBuildInput(
        assembly_id="assembly_" + "1" * 32,
        assembly_revision_id=mixed.assembly_revision_id,
        assembly_manifest_sha256=mixed.assembly_manifest_sha256,
        handoff=mixed.handoff,
        converter=None,
        placements=tuple(placements),
    )
    registry = SimpleNamespace(inspect_revisions=Mock(return_value=tuple(revisions)))
    stager = Stager()
    service = CuratedInputMaterializer(members=members, registry=registry, adapter=stager)
    workspace = tmp_path / "workspace"
    workspace.mkdir(mode=0o700)
    return service, plan, workspace, canonical


def test_materialization_runs_real_mixed_builder_with_exact_inputs_and_shared_pngs(
    tmp_path, handoff_bytes
):
    service, plan, workspace, canonical = cohort(tmp_path, handoff_bytes)
    result = service.stage(workspace, build_id=BUILD_ID, inputs=plan)
    assert len(service.members.calls) == 2
    service.registry.inspect_revisions.assert_called_once()
    assert [row.position for row in result.request.segments] == [1, 2, 3, 4, 5]
    assert [row.position for row in result.editorial_items] == [4, 5]
    for native in result.canonical_items:
        original = canonical[native.item_number]
        assert [block.block_id for block in native.body] == [
            block.block_id for block in original.body
        ]
        assert native.source_sha256 == plan.placements[native.item_number - 1].source_content.sha256
        assert expected_native_item_events(native)
    staged_images = [name for name in service.adapter.staged if name.startswith("images/")]
    assert len(staged_images) == len(set(staged_images)) == 3
    assert (
        result.request.segments[3].images[0].local_file
        == result.request.segments[4].images[0].local_file
    )
    service.adapter.write_json(workspace, "request.json", result.request.model_dump(mode="json"))

    built = render_curated_workspace(workspace / "request.json", workspace / "result.json")

    assert built.status == "SUCCEEDED"
    assert built.section_source_positions == (1, 2, 3, 4, 5)
    assert built.input_plan_sha256 == result.request.input_plan_sha256
    assert built.output_sha256 == sha256_file(workspace / "output/assembled.hwpx")


@pytest.mark.parametrize(
    "damage",
    ["item_hash", "item_state", "content_pointer", "ambiguous_content", "missing_revision"],
)
def test_stale_item_inputs_fail_before_staging_or_resolving_source_bytes(
    tmp_path, handoff_bytes, damage
):
    service, plan, workspace, _canonical = cohort(tmp_path, handoff_bytes)
    rows = service.registry.inspect_revisions.return_value
    if damage == "item_hash":
        rows[0]["manifest_sha256"] = "sha256:" + "0" * 64
    elif damage == "item_state":
        rows[0]["revision_state"] = "REJECTED"
    elif damage == "content_pointer":
        rows[0]["components"][0]["sha256"] = "sha256:" + "0" * 64
    elif damage == "ambiguous_content":
        rows[0]["components"].append(rows[0]["components"][0])
    else:
        service.registry.inspect_revisions.return_value = rows[1:]
    with pytest.raises(HwpxManagerError):
        service.stage(workspace, build_id=BUILD_ID, inputs=plan)
    assert not service.adapter.staged and not service.members.calls


def test_superseded_exact_revision_is_supported_without_resolving_a_latest_item(
    tmp_path, handoff_bytes
):
    service, plan, workspace, _canonical = cohort(tmp_path, handoff_bytes)
    service.registry.inspect_revisions.return_value[0]["revision_state"] = "SUPERSEDED"
    staged = service.stage(workspace, build_id=BUILD_ID, inputs=plan)
    assert staged.request.segments[1].item_revision_id == plan.placements[1].item_revision_id


def test_changed_json_after_metadata_resolution_is_rejected(tmp_path, handoff_bytes):
    service, plan, workspace, _canonical = cohort(tmp_path, handoff_bytes)
    resolve = service.members.resolve_members

    def mutate(pointers):
        paths = resolve(pointers)
        for pointer, path in zip(pointers, paths, strict=True):
            if pointer.expected_sha256 == plan.placements[1].source_content.sha256:
                path.write_bytes(b'{"changed":true}')
        return paths

    service.members.resolve_members = mutate
    with pytest.raises(HwpxManagerError, match="changed between"):
        service.stage(workspace, build_id=BUILD_ID, inputs=plan)
    assert not (workspace / "request.json").exists()


@pytest.mark.parametrize("wrong_report", [False, True])
def test_restored_source_picture_uses_exact_derivation_and_solution_report(
    tmp_path, handoff_bytes, wrong_report
):
    service, plan, workspace, _canonical = cohort(tmp_path, handoff_bytes)
    original, manifest, view = presentation()
    data = image_bytes(size=(2000, 1000))
    # Image bytes have their own hash, distinct from the canonical JSON hashes.
    digest = sha256_bytes(data)
    visual = manifest.visuals[0].model_copy(
        update={
            "sha256": digest,
            "member_path": f"images/{digest[7:]}.png",
            "content_length": len(data),
        }
    )
    candidate = manifest.model_copy(update={"visuals": (visual,)})
    displayed = derive_creative_visual_content(
        original,
        candidate,
        artifact_id=view.display_content.artifact_id,
        artifact_revision_id=view.display_content.artifact_revision_id,
    )
    payload = candidate.model_dump(mode="json")
    payload["content_sha256"] = content_sha256(displayed.model_dump(mode="json"))
    payload.pop("manifest_sha256")
    checked = type(manifest).model_validate({**payload, "manifest_sha256": content_sha256(payload)})
    source = CuratedArtifactMember.model_validate(view.source_content.model_dump())
    display = CuratedArtifactMember.model_validate(view.display_content.model_dump()).model_copy(
        update={"sha256": content_sha256(displayed.model_dump(mode="json"))}
    )
    raw_manifest = canonical_json_bytes(checked.model_dump(mode="json"))
    recovery = CuratedArtifactMember.model_validate(view.recovery_manifest.model_dump()).model_copy(
        update={"sha256": sha256_bytes(raw_manifest)}
    )
    image_pointer = CuratedArtifactMember(
        artifact_id=display.artifact_id,
        artifact_revision_id=display.artifact_revision_id,
        member_path=visual.member_path,
        schema_ref="existing-source-image/1.0",
        media_type="image/png",
        sha256=digest,
    )
    for pointer, raw in (
        (source, canonical_json_bytes(original.model_dump(mode="json"))),
        (display, canonical_json_bytes(displayed.model_dump(mode="json"))),
        (recovery, raw_manifest),
        (image_pointer, data),
    ):
        path = save(tmp_path / "restored", pointer.artifact_id + "/" + pointer.member_path, raw)
        service.members.files[
            (pointer.artifact_id, pointer.artifact_revision_id, pointer.member_path)
        ] = (pointer, path)
    report = CuratedArtifactMember.model_validate(checked.role_result.model_dump())
    replacement = plan.placements[1].model_copy(
        update={
            "item_id": checked.item_id,
            "item_revision_id": checked.item_revision_id,
            "source_content": source,
            "display_content": display,
            "recovery_manifest": recovery,
        }
    )
    plan = plan.model_copy(
        update={"placements": (plan.placements[0], replacement, *plan.placements[2:])}
    )
    row = service.registry.inspect_revisions.return_value[0]
    row.update(
        item_id=checked.item_id,
        item_revision_id=checked.item_revision_id,
        components=[component(source), component(report, kind="REVIEW_REPORT")],
    )
    if wrong_report:
        row["components"][1]["sha256"] = "sha256:" + "0" * 64
        with pytest.raises(HwpxManagerError, match="solution report"):
            service.stage(workspace, build_id=BUILD_ID, inputs=plan)
    else:
        materialized = service.stage(workspace, build_id=BUILD_ID, inputs=plan)
        restored = materialized.canonical_items[0]
        assert restored.source_sha256 == source.sha256
        assert restored.effective_content_sha256 == display.sha256 != source.sha256
        picture = next(block for block in restored.body if block.type == "image")
        assert (picture.sha256, picture.width_px, picture.height_px) == (digest, 2000, 1000)
        assert (workspace / picture.local_file).read_bytes() == data
