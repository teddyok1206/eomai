"""Synthetic owner ports exercise explicit role/Pack/lineage versions, not live authority."""

from contextlib import nullcontext
from types import SimpleNamespace

import pytest
from eom_catalog_contracts.creative_source_draft import SourceImageBlock
from eom_catalog_contracts.material_item_lineage import (
    MATERIAL_ITEM_LINEAGE_REF,
    MATERIAL_ITEM_LINEAGE_V2_REF,
    MATERIAL_ITEM_LINEAGE_V3_REF,
    MaterialItemLineage,
    MaterialItemLineageV2,
    MaterialItemLineageV3,
)
from eom_catalog_contracts.material_native_files import MaterialNativeItemBinding
from eom_catalog_service import material_item_registration as owner
from eom_catalog_service.creative_source_content import materialize_source_observation_content
from eom_identifiers import canonical_json_bytes, content_sha256
from eom_operator_identity import PermissionKey

from tests.unit.test_creative_source_draft import resolved_image
from tests.unit.test_material_native_files import binding_data
from tests.unit.test_material_task_results import case


def resolved_case(monkeypatch, *, successor=False, exact_score=False):
    fixture = case(monkeypatch, successor=successor, native=True, exact_score=exact_score)
    resolved = owner.resolve_completed_material_task(
        fixture.session,
        fixture.artifacts,
        task_id=fixture.task.task_id,
        operator_id=fixture.actor,
    )
    result = resolved.role.output.learning_result
    images = {
        block.block_id: resolved_image().model_copy(
            update={
                "block_id": block.block_id,
                "purpose": block.purpose,
                "alt_text": block.alt_text,
            }
        )
        for block in result.proposal.content.body
        if isinstance(block, SourceImageBlock)
    }
    content = materialize_source_observation_content(result, resolved_images=images)
    return resolved, content


@pytest.mark.parametrize("family", [1, 2, 3])
def test_lineage_construction_selects_only_the_exact_actual_result_family(monkeypatch, family):
    resolved, content = resolved_case(monkeypatch, successor=family == 2, exact_score=family == 3)
    lineage = owner.material_item_lineage(resolved, content)
    assert (
        type(lineage)
        is {1: MaterialItemLineage, 2: MaterialItemLineageV2, 3: MaterialItemLineageV3}[family]
    )
    assert lineage.role_result == resolved.result_pointer
    assert lineage.result_sha256 == content_sha256(
        resolved.role.output.learning_result.model_dump(mode="json")
    )
    assert lineage.result_sha256 != lineage.role_result.sha256
    assert lineage.lineage_sha256 == content_sha256(
        lineage.model_dump(mode="json", exclude={"lineage_sha256"})
    )


@pytest.mark.parametrize(
    "family,native,version",
    [
        (1, False, "1.0.0"),
        (1, True, "1.1.0"),
        (2, False, "1.2.0"),
        (2, True, "1.3.0"),
        (3, False, "1.4.0"),
        (3, True, "1.5.0"),
    ],
)
def test_authorization_selects_four_exact_released_pack_profiles_not_latest(
    monkeypatch, family, native, version
):
    resolved, _ = resolved_case(monkeypatch, successor=family == 2, exact_score=family == 3)
    service = object.__new__(owner.MaterialItemRegistrationService)
    service.pack_release_id, service.native_pack_release_id = "generic", "native"
    service.coverage_pack_release_id = "coverage"
    service.native_coverage_pack_release_id = "native-coverage"
    service.exact_score_pack_release_id = "score"
    service.native_exact_score_pack_release_id = "native-score"
    service.sources = SimpleNamespace(reauthorize=lambda *args, **kwargs: None)
    release = SimpleNamespace(content_pack_id="pack", state="RELEASED", version=version)
    logical = SimpleNamespace(pack_key="uploaded-material-item")
    expected_id = (
        ("native-score" if native else "score")
        if family == 3
        else ("native-coverage" if native else "coverage")
        if family == 2
        else ("native" if native else "generic")
    )

    def get(model, key, **_kwargs):
        if model is owner.ContentPackReleaseRecord:
            assert key == expected_id
            return release
        return logical

    session = SimpleNamespace(get=get)
    service.pack_resources = SimpleNamespace(
        read=lambda _session, _release, member: (
            '{"$id":"' + owner.NATIVE_ITEM_PACK_METADATA_REF + '"}'
            if member.endswith(".json")
            else "item_type:\n  key: uploaded-material-item\n  required_components: "
            "[ITEM_CONTENT, SOURCE_REFERENCE, REVIEW_REPORT, METADATA, OTHER]"
        ).encode()
    )
    monkeypatch.setattr(
        owner,
        "effective_permissions",
        lambda *_args: {PermissionKey.ITEM_STRUCTURED_CONTENT_IMPORT},
    )
    binding = MaterialNativeItemBinding.model_validate(binding_data()) if native else None
    service._authorize(session, resolved, binding)
    for wrong in {"1.0.0", "1.1.0", "1.2.0", "1.3.0", "1.4.0", "1.5.0", "1.99.0"} - {version}:
        release.version = wrong
        with pytest.raises(ValueError, match="NOT_AUTHORIZED"):
            service._authorize(session, resolved, binding)


def replay_case(monkeypatch, *, successor=False, exact_score=False):
    resolved, content = resolved_case(monkeypatch, successor=successor, exact_score=exact_score)
    lineage = owner.material_item_lineage(resolved, content)
    service = object.__new__(owner.MaterialItemRegistrationService)
    service.pack_release_id = "pack"
    service.coverage_pack_release_id = "pack"
    service.exact_score_pack_release_id = "pack"
    item = SimpleNamespace(lifecycle_state="ACTIVE", current_revision_id="itemrev_" + "a" * 32)
    revision = SimpleNamespace(
        item_id="item_" + "a" * 32,
        item_revision_id=item.current_revision_id,
        revision_state="APPROVED",
        workflow_id=resolved.selection.workflow_id,
        source_workflow_step_run_id=resolved.selection.step_run_id,
        content_pack_release_id="pack",
        metadata_json={"lineage_sha256": lineage.lineage_sha256, "source_kind": "EXTERNAL"},
    )
    source = SimpleNamespace(
        component_type="SOURCE_REFERENCE",
        ordinal=0,
        artifact_id="artifact_" + "f" * 32,
        artifact_revision_id="rev_" + "e" * 32,
        schema_ref=(
            MATERIAL_ITEM_LINEAGE_V3_REF
            if exact_score
            else MATERIAL_ITEM_LINEAGE_V2_REF
            if successor
            else MATERIAL_ITEM_LINEAGE_REF
        ),
        logical_name="lineage.json",
        sha256=content_sha256(lineage.model_dump(mode="json")),
    )
    content_component = SimpleNamespace(
        component_type="ITEM_CONTENT",
        ordinal=0,
        artifact_id="artifact_" + "d" * 32,
        artifact_revision_id="rev_" + "c" * 32,
        logical_name="item-content.json",
        schema_ref=(
            owner.ASSESSMENT_ITEM_CONTENT_V1_1_SCHEMA_REF
            if exact_score
            else owner.ASSESSMENT_ITEM_CONTENT_SCHEMA_REF
        ),
        sha256=lineage.registered_content_sha256,
    )
    report = SimpleNamespace(
        component_type="REVIEW_REPORT",
        ordinal=0,
        artifact_id=resolved.result_pointer.artifact_id,
        artifact_revision_id=resolved.result_pointer.artifact_revision_id,
        sha256=resolved.result_pointer.sha256,
    )
    session = SimpleNamespace(
        scalars=lambda _query: (source, content_component, report),
        get=lambda *_args, **_kwargs: item,
    )
    payload = lineage.model_dump(mode="json")
    reads = []

    def read_member(**pointer):
        assert pointer["schema_ref"] == source.schema_ref
        reads.append(pointer)
        return canonical_json_bytes(payload)

    service.artifacts = SimpleNamespace(
        read_member=read_member, verify_member=lambda **_kwargs: True
    )
    return service, session, revision, resolved, lineage, source, payload, reads


@pytest.mark.parametrize("family", [1, 2, 3])
def test_registration_replay_parses_exact_lineage_version_and_keeps_all_pins(monkeypatch, family):
    service, session, revision, resolved, expected, _, _, reads = replay_case(
        monkeypatch, successor=family == 2, exact_score=family == 3
    )
    assert service._verify_registered(session, revision, resolved) == expected
    assert len(reads) == 1 and reads[0]["max_bytes"] == 64 * 1024


@pytest.mark.parametrize("change", ["schema", "hash", "role_revision", "inner_result"])
def test_registration2_replay_rejects_version_or_lineage_hash_or_source_changes(
    monkeypatch, change
):
    service, session, revision, resolved, _, source, payload, _ = replay_case(
        monkeypatch, successor=True
    )
    if change == "schema":
        source.schema_ref = MATERIAL_ITEM_LINEAGE_REF
    elif change == "hash":
        payload["lineage_sha256"] = "sha256:" + "0" * 64
    else:
        if change == "role_revision":
            payload["role_result"]["artifact_revision_id"] = "rev_" + "f" * 32
        else:
            payload["result_sha256"] = "sha256:" + "f" * 64
        payload["lineage_sha256"] = content_sha256(
            {key: value for key, value in payload.items() if key != "lineage_sha256"}
        )
    with pytest.raises(ValueError):
        service._verify_registered(session, revision, resolved)


@pytest.mark.parametrize("native", [False, True])
def test_missing_new_pack_never_reuses_legacy_and_fails_before_artifact_writes(monkeypatch, native):
    resolved, _ = resolved_case(monkeypatch, successor=True)
    service = object.__new__(owner.MaterialItemRegistrationService)
    service.pack_release_id, service.native_pack_release_id = "legacy-generic", "legacy-native"
    service.coverage_pack_release_id = service.native_coverage_pack_release_id = None
    service.sources = SimpleNamespace(reauthorize=lambda *args, **kwargs: None)
    reads = []
    session = SimpleNamespace(get=lambda *args, **kwargs: reads.append(args))
    service.sessions = lambda: nullcontext(session)
    binding = MaterialNativeItemBinding.model_validate(binding_data()) if native else None
    service._native_binding = lambda *args: binding
    monkeypatch.setattr(owner, "resolve_completed_material_task", lambda *args, **kwargs: resolved)
    monkeypatch.setattr(
        owner,
        "effective_permissions",
        lambda *_args: {PermissionKey.ITEM_STRUCTURED_CONTENT_IMPORT},
    )
    service.artifacts = SimpleNamespace(
        commit_file_set=lambda **kwargs: pytest.fail("unexpected Artifact write")
    )
    with pytest.raises(ValueError, match="NOT_AUTHORIZED"):
        service.register_completed(task_id=resolved.task_id, operator_id=resolved.operator_id)
    assert not reads  # No legacy Pack was dereferenced as an implicit substitute.
