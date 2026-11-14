"""Prepared3 resolves one authorized exact V2 base, never latest or recursive checkpoints."""

from copy import deepcopy
from types import SimpleNamespace

import pytest
from eom_catalog_contracts.material_learning import MaterialArtifactMember
from eom_catalog_contracts.material_learning_intake import MaterialLearningIntakeManifest
from eom_catalog_contracts.material_native_intake import (
    MaterialNativeLearningIntakeManifest,
    MaterialNativePreparationInput,
    require_native_material_checkpoint_chain,
)
from eom_catalog_contracts.material_native_visual_preparation import (
    MATERIAL_NATIVE_VISUAL_PREPARED_REF,
    MaterialNativeVisualPreparedArtifact,
)
from eom_catalog_service.material_intake_read import (
    material_prepared_pointer,
    read_material_prepared,
    read_native_visual_prepared_base,
)
from eom_identifiers import canonical_json_bytes, content_sha256, sha256_bytes
from eom_orchestrator.models import ArtifactRecord, ArtifactRevisionRecord

from tests.unit.test_material_learning_contracts import member, rehash
from tests.unit.test_material_native_intake import native_intake, native_preparation
from tests.unit.test_material_native_visual_preparation import base_prepared, visual_prepared


def read_case(body=None):
    body = visual_prepared() if body is None else body
    base = base_prepared()
    base_pointer = MaterialArtifactMember.model_validate(body["base_prepared"])
    encoded = canonical_json_bytes(body)
    pointer = MaterialArtifactMember.model_validate(
        {
            **member("material/prepared.json", "application/json"),
            "artifact_id": "artifact_" + "9" * 32,
            "artifact_revision_id": "rev_" + "9" * 32,
            "schema_ref": MATERIAL_NATIVE_VISUAL_PREPARED_REF,
            "sha256": sha256_bytes(encoded),
            "bytes": len(encoded),
        }
    )
    payloads = {
        pointer.artifact_revision_id: encoded,
        base_pointer.artifact_revision_id: canonical_json_bytes(base.model_dump(mode="json")),
    }
    pointers = {value.artifact_revision_id: value for value in (pointer, base_pointer)}
    records = {}
    for current in pointers.values():
        manifest = dict(
            primary_file=current.member_path,
            files=[
                dict(
                    file_name=current.member_path,
                    schema_ref=current.schema_ref,
                    media_type=current.media_type,
                    sha256=current.sha256,
                    bytes=current.bytes,
                )
            ],
        )
        records[ArtifactRevisionRecord, current.artifact_revision_id] = SimpleNamespace(
            approved=True,
            logical_artifact_id=current.artifact_id,
            content_hash=current.sha256,
            content_bytes=current.bytes,
            manifest=manifest,
            manifest_hash=content_sha256(manifest),
        )
        records[ArtifactRecord, current.artifact_id] = SimpleNamespace(approved=True)
    events = []

    class Session:
        def get(self, model, identifier):
            return records.get((model, identifier))

    class Reader:
        def read_member(self, **kwargs):
            events.append(("read", kwargs["revision_id"]))
            actual = pointers.get(kwargs["revision_id"])
            payload = payloads.get(kwargs["revision_id"])
            if actual is None or payload is None:
                raise ValueError("TEST_CANONICAL_ARTIFACT_MISSING")
            if (
                kwargs
                != dict(
                    artifact_id=actual.artifact_id,
                    revision_id=actual.artifact_revision_id,
                    member_path=actual.member_path,
                    schema_ref=actual.schema_ref,
                    media_type=actual.media_type,
                    sha256=actual.sha256,
                    max_bytes=actual.bytes,
                )
                or sha256_bytes(payload) != actual.sha256
            ):
                raise ValueError("TEST_CANONICAL_ARTIFACT_HASH_MISMATCH")
            return payload

    return pointer, Session(), Reader(), events, payloads, pointers


def test_committed_prepared3_resolves_exact_base2_and_reauthorizes_both_read_boundaries():
    pointer, session, reader, events, _, _ = read_case()
    actual = material_prepared_pointer(
        session,
        artifact_id=pointer.artifact_id,
        revision_id=pointer.artifact_revision_id,
        sha256=pointer.sha256,
    )
    assert actual == pointer
    prepared = read_material_prepared(reader, actual, authorize=lambda: events.append("auth"))
    assert isinstance(prepared, MaterialNativeVisualPreparedArtifact)
    assert prepared.sources == base_prepared().sources
    assert events == [
        "auth",
        ("read", pointer.artifact_revision_id),
        "auth",
        ("read", prepared.base_prepared.artifact_revision_id),
        "auth",
        "auth",
    ]


def test_public_base_reader_is_one_direct_v2_read_with_permission_checks():
    _, _, reader, events, _, _ = read_case()
    prepared = MaterialNativeVisualPreparedArtifact.model_validate(visual_prepared())
    actual = read_native_visual_prepared_base(
        reader, prepared, authorize=lambda: events.append("auth")
    )
    assert actual == base_prepared()
    assert events == ["auth", ("read", prepared.base_prepared.artifact_revision_id), "auth"]


@pytest.mark.parametrize("revoked_at", [1, 2, 3, 4])
def test_current_permission_revocation_never_returns_a_visual_or_base_checkpoint(revoked_at):
    pointer, _, reader, events, _, _ = read_case()
    checks = 0

    def authorize():
        nonlocal checks
        checks += 1
        if checks == revoked_at:
            raise ValueError("ACTUAL_OPERATOR_PERMISSION_REVOKED")

    with pytest.raises(ValueError, match="PERMISSION_REVOKED"):
        read_material_prepared(reader, pointer, authorize=authorize)
    assert checks == revoked_at
    assert len(events) == (0 if revoked_at == 1 else 1 if revoked_at == 2 else 2)


@pytest.mark.parametrize(
    "case", ["missing", "bad_hash", "same_pointer_changed_bytes", "wrong_base_type"]
)
def test_base_corruption_is_explicit_and_never_retries_another_schema(case):
    body = visual_prepared()
    if case == "bad_hash":
        body["base_prepared"]["sha256"] = "sha256:" + "0" * 64
    elif case == "wrong_base_type":
        nested = canonical_json_bytes(body)
        body["base_prepared"].update(sha256=sha256_bytes(nested), bytes=len(nested))
    pointer, _, reader, events, payloads, pointers = read_case(rehash(body, "prepared_sha256"))
    base_id = body["base_prepared"]["artifact_revision_id"]
    if case == "missing":
        payloads.pop(base_id)
    elif case == "same_pointer_changed_bytes":
        changed = base_prepared().model_dump(mode="json")
        changed["profile_sha256"] = "sha256:" + "0" * 64
        payloads[base_id] = canonical_json_bytes(rehash(changed, "prepared_sha256"))
    elif case == "wrong_base_type":
        payloads[base_id] = nested
    with pytest.raises(ValueError):
        read_material_prepared(reader, pointer, authorize=lambda: None)
    assert events == [("read", pointer.artifact_revision_id), ("read", base_id)]
    assert set(pointers) == {pointer.artifact_revision_id, base_id}


@pytest.mark.parametrize(
    "field",
    [
        "material_id",
        "material_revision_id",
        "profile_sha256",
        "native_bundle",
        "intake_manifest",
        "sources",
    ],
)
def test_forged_base_source_profile_bundle_or_intake_is_not_accepted_after_read(field):
    body = visual_prepared()
    if field == "material_id":
        body[field] = "material_" + "0" * 32
    elif field == "material_revision_id":
        body[field] = "materialrev_" + "0" * 32
    elif field == "profile_sha256":
        body[field] = "sha256:" + "0" * 64
    elif field == "sources":
        body[field][0]["page_bundle"]["sha256"] = "sha256:" + "0" * 64
    else:
        body[field]["artifact_revision_id"] = "rev_" + "0" * 32
    pointer, _, reader, events, _, _ = read_case(rehash(body, "prepared_sha256"))
    with pytest.raises(ValueError, match="PREPARED_BASE_MISMATCH"):
        read_material_prepared(reader, pointer, authorize=lambda: None)
    assert len(events) == 2


def test_base_pointer_cannot_recursively_reference_another_prepared3_even_if_constructed():
    _, _, reader, events, _, _ = read_case()
    prepared = MaterialNativeVisualPreparedArtifact.model_validate(visual_prepared())
    broken = prepared.model_copy(
        update={
            "base_prepared": prepared.base_prepared.model_copy(
                update={"schema_ref": MATERIAL_NATIVE_VISUAL_PREPARED_REF}
            )
        }
    )
    with pytest.raises(ValueError, match="METADATA_POINTER_INVALID"):
        read_native_visual_prepared_base(reader, broken, authorize=lambda: None)
    assert events == []


def test_native_checkpoint_family_accepts_preparation2_prepared3_and_exact_intake_bundle():
    intake = MaterialNativeLearningIntakeManifest.model_validate(native_intake())
    preparation = MaterialNativePreparationInput.model_validate(native_preparation())
    prepared = MaterialNativeVisualPreparedArtifact.model_validate(visual_prepared())
    require_native_material_checkpoint_chain(intake, preparation=preparation, prepared=prepared)
    changed = prepared.model_dump(mode="json")
    changed["native_bundle"]["artifact_revision_id"] = "rev_" + "0" * 32
    forged = MaterialNativeVisualPreparedArtifact.model_validate(rehash(changed, "prepared_sha256"))
    with pytest.raises(ValueError, match="CHECKPOINT_BUNDLE_MISMATCH"):
        require_native_material_checkpoint_chain(intake, prepared=forged)


def test_non_native_intake_cannot_sneak_into_the_new_prepared_family():
    body = deepcopy(native_intake())
    body.pop("native_bundle")
    body["schema_version"] = "material-learning-intake/1.0"
    intake = MaterialLearningIntakeManifest.model_validate(body)
    prepared = MaterialNativeVisualPreparedArtifact.model_validate(visual_prepared())
    with pytest.raises(ValueError, match="CHECKPOINT_CHAIN_MISMATCH"):
        require_native_material_checkpoint_chain(intake, prepared=prepared)
