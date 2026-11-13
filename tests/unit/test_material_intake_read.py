"""Committed schema chooses a material parser; unknown or corrupt versions never fall back."""

from copy import deepcopy
from types import SimpleNamespace

import pytest
from eom_catalog_contracts.material_learning import MaterialArtifactMember
from eom_catalog_service.material_intake_read import (
    material_intake_pointer,
    material_preparation_pointer,
    material_prepared_pointer,
    read_material_intake,
    read_material_preparation,
    read_material_prepared,
)
from eom_identifiers import canonical_json_bytes, content_sha256, sha256_bytes
from eom_orchestrator.models import ArtifactRecord, ArtifactRevisionRecord

from tests.unit.test_material_learning_contracts import member, rehash
from tests.unit.test_material_native_intake import (
    native_intake,
    native_preparation,
    native_prepared,
)


def record_case(data, schema, member_path):
    encoded = canonical_json_bytes(data)
    pointer = MaterialArtifactMember.model_validate(
        {
            **member(member_path, "application/json"),
            "schema_ref": schema,
            "sha256": sha256_bytes(encoded),
            "bytes": len(encoded),
        }
    )
    manifest = dict(
        manifest_version="catalog-file-set/1.0",
        primary_file=member_path,
        files=[
            dict(
                file_name=member_path,
                schema_ref=schema,
                media_type="application/json",
                sha256=pointer.sha256,
                bytes=pointer.bytes,
            )
        ],
    )
    revision = SimpleNamespace(
        approved=True,
        logical_artifact_id=pointer.artifact_id,
        content_hash=pointer.sha256,
        content_bytes=len(encoded),
        manifest=manifest,
        manifest_hash=content_sha256(manifest),
    )
    artifact = SimpleNamespace(approved=True)
    calls = []

    class Session:
        def get(self, model, identifier):
            if model is ArtifactRevisionRecord and identifier == pointer.artifact_revision_id:
                return revision
            if model is ArtifactRecord and identifier == pointer.artifact_id:
                return artifact
            return None

    class Reader:
        def read_member(self, **kwargs):
            calls.append(kwargs)
            assert kwargs == dict(
                artifact_id=pointer.artifact_id,
                revision_id=pointer.artifact_revision_id,
                member_path=pointer.member_path,
                sha256=pointer.sha256,
                media_type=pointer.media_type,
                schema_ref=pointer.schema_ref,
                max_bytes=pointer.bytes,
            )
            return encoded

    return pointer, revision, artifact, Session(), Reader(), calls


@pytest.mark.parametrize(
    "data,schema,path,pin,read",
    [
        (native_intake, "intake", "intake", material_intake_pointer, read_material_intake),
        (
            native_preparation,
            "preparation-input",
            "preparation-input",
            material_preparation_pointer,
            read_material_preparation,
        ),
        (
            native_prepared,
            "prepared",
            "prepared",
            material_prepared_pointer,
            read_material_prepared,
        ),
    ],
)
def test_exact_committed_v2_schema_dispatch_and_reauthorization(data, schema, path, pin, read):
    pointer, _, _, session, reader, calls = record_case(
        data(), f"eom://schemas/material-learning/{schema}/2.0", f"material/{path}.json"
    )
    actual = pin(
        session,
        artifact_id=pointer.artifact_id,
        revision_id=pointer.artifact_revision_id,
        sha256=pointer.sha256,
    )
    assert actual == pointer
    auth = []
    value = read(reader, actual, authorize=lambda: auth.append(True))
    assert value.schema_version.endswith("/2.0")
    assert len(calls) == 1 and len(auth) == 2


@pytest.mark.parametrize(
    "mismatch",
    [
        "missing",
        "unapproved",
        "wrong_artifact",
        "hash",
        "schema",
        "duplicate",
        "size",
        "primary",
        "manifest_hash",
    ],
)
def test_metadata_pointer_rejects_stale_missing_or_unexpected_committed_members(mismatch):
    pointer, revision, artifact, session, _, _ = record_case(
        native_intake(), "eom://schemas/material-learning/intake/2.0", "material/intake.json"
    )
    requested_revision = pointer.artifact_revision_id
    if mismatch == "missing":
        requested_revision = "rev_" + "0" * 32
    elif mismatch == "unapproved":
        artifact.approved = False
    elif mismatch == "wrong_artifact":
        revision.logical_artifact_id = "artifact_" + "0" * 32
    elif mismatch == "hash":
        revision.content_hash = "sha256:" + "0" * 64
    elif mismatch == "schema":
        revision.manifest["files"][0]["schema_ref"] = "eom://schemas/material-learning/intake/999.0"
    elif mismatch == "duplicate":
        revision.manifest["files"].append(deepcopy(revision.manifest["files"][0]))
    elif mismatch == "size":
        revision.manifest["files"][0]["bytes"] += 1
    elif mismatch == "manifest_hash":
        revision.manifest_hash = "sha256:" + "0" * 64
    else:
        revision.manifest["primary_file"] = "other.json"
    if mismatch != "manifest_hash":
        revision.manifest_hash = content_sha256(revision.manifest)
    with pytest.raises(ValueError, match="CHECKPOINT"):
        material_intake_pointer(
            session,
            artifact_id=pointer.artifact_id,
            revision_id=requested_revision,
            sha256=pointer.sha256,
        )


def test_parse_failure_never_retries_with_another_schema_and_denied_actor_reads_nothing():
    pointer, _, _, _, reader, calls = record_case(
        native_intake(), "eom://schemas/material-learning/intake/1.0", "material/intake.json"
    )
    with pytest.raises(ValueError):
        read_material_intake(reader, pointer, authorize=lambda: None)
    assert len(calls) == 1
    calls.clear()

    def denied():
        raise ValueError("ACTUAL_OPERATOR_PERMISSION_DENIED")

    with pytest.raises(ValueError, match="PERMISSION_DENIED"):
        read_material_intake(reader, pointer, authorize=denied)
    assert calls == []


def test_revoked_authority_after_read_does_not_return_the_manifest():
    pointer, _, _, _, reader, calls = record_case(
        native_intake(), "eom://schemas/material-learning/intake/2.0", "material/intake.json"
    )
    checked = 0

    def authorize():
        nonlocal checked
        checked += 1
        if checked > 1:
            raise ValueError("ACTUAL_OPERATOR_PERMISSION_REVOKED")

    with pytest.raises(ValueError, match="PERMISSION_REVOKED"):
        read_material_intake(reader, pointer, authorize=authorize)
    assert len(calls) == 1 and checked == 2


@pytest.mark.parametrize("kind", ["intake", "preparation-input", "prepared"])
def test_existing_v1_committed_records_still_use_their_exact_original_parser(kind):
    factory, pin, read = {
        "intake": (native_intake, material_intake_pointer, read_material_intake),
        "preparation-input": (
            native_preparation,
            material_preparation_pointer,
            read_material_preparation,
        ),
        "prepared": (native_prepared, material_prepared_pointer, read_material_prepared),
    }[kind]
    data = factory()
    data.pop("native_bundle")
    data["schema_version"] = data["schema_version"].replace("/2.0", "/1.0")
    if kind != "intake":
        data["intake_manifest"]["schema_ref"] = "eom://schemas/material-learning/intake/1.0"
        rehash(data, "input_sha256" if kind == "preparation-input" else "prepared_sha256")
    pointer, _, _, session, reader, calls = record_case(
        data, f"eom://schemas/material-learning/{kind}/1.0", f"material/{kind}.json"
    )
    actual = pin(
        session,
        artifact_id=pointer.artifact_id,
        revision_id=pointer.artifact_revision_id,
        sha256=pointer.sha256,
    )
    assert read(reader, actual, authorize=lambda: None).schema_version.endswith("/1.0")
    assert len(calls) == 1
