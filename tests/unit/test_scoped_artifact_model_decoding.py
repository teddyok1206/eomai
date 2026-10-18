"""Real temporary members and synthetic metadata; no live DB/NAS/latency claim."""

from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path
from typing import cast
from unittest.mock import Mock

import pytest
from eom_catalog_service import pinned_artifact_resolution as module
from eom_catalog_service.artifacts import CatalogModelArtifactReader
from eom_catalog_service.pinned_artifact_resolution import (
    PinnedArtifactReadContext,
    PinnedArtifactResolutionError,
)
from eom_identifiers import content_sha256, sha256_bytes
from eom_orchestrator.models import ArtifactRecord, ArtifactRevisionRecord, JobRecord
from eom_protocol.artifact_members import ArtifactMemberPointer
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from tests.unit.test_pinned_artifact_read_context import MetadataSession
from tests.unit.test_pinned_artifact_resolution import _fixture


class FrozenValue(BaseModel):
    model_config = ConfigDict(frozen=True)
    value: int


def decode(_schema: str, raw: bytes) -> FrozenValue:
    return FrozenValue.model_validate_json(raw)


def context_case(tmp_path):
    original, settings, arguments = _fixture(tmp_path)
    session = MetadataSession(*original.records.values())
    reader = PinnedArtifactReadContext(cast(Session, session), settings)
    reader.prefetch(((arguments["artifact_id"], arguments["artifact_revision_id"]),))
    pointer = ArtifactMemberPointer.model_validate(
        {
            key: value
            for key, value in arguments.items()
            if key in ArtifactMemberPointer.model_fields
        }
    )
    return reader, pointer, session


def test_same_decoder_reused_but_every_read_revalidates_member(tmp_path, monkeypatch):
    reader, pointer, _session = context_case(tmp_path)
    decoder = Mock(side_effect=decode)
    resolve = Mock(wraps=module._resolve_pinned_artifact_member)
    monkeypatch.setattr(module, "_resolve_pinned_artifact_member", resolve)
    assert isinstance(reader, CatalogModelArtifactReader)
    first = reader.read_model_member(pointer, expected_bytes=11, decoder=decoder)
    assert reader.read_model_member(pointer, expected_bytes=11, decoder=decoder) is first
    assert decoder.call_count == 1 and resolve.call_count == 2
    assert reader._decoded_bytes == 11 and len(reader._decoded) == 1


@pytest.mark.parametrize("fault", ["approval", "producer", "revision", "root", "thread"])
def test_decoded_hit_never_bypasses_mutable_provenance_checks(tmp_path, monkeypatch, fault):
    reader, pointer, session = context_case(tmp_path)
    reader.read_model_member(pointer, expected_bytes=11, decoder=decode)
    revision = session.get(ArtifactRevisionRecord, pointer.artifact_revision_id)
    if fault == "approval":
        session.get(ArtifactRecord, pointer.artifact_id).approved = False
    elif fault == "producer":
        session.get(JobRecord, revision.job_id).status = "RUNNING"
    elif fault == "revision":
        revision.content_hash = "sha256:" + "f" * 64
    elif fault == "root":
        session.root.is_active = False
    else:
        monkeypatch.setattr(module, "get_ident", lambda: -1)
    with pytest.raises((OSError, PinnedArtifactResolutionError)):
        reader.read_model_member(pointer, expected_bytes=11, decoder=decode)


@pytest.mark.parametrize("missing", [False, True])
def test_existing_root_snapshot_reuse_does_not_survive_a_new_materialization(tmp_path, missing):
    reader, pointer, session = context_case(tmp_path)
    first = reader.read_model_member(pointer, expected_bytes=11, decoder=decode)
    revision = session.get(ArtifactRevisionRecord, pointer.artifact_revision_id)
    path = Path(revision.nas_path) / pointer.member_path
    if missing:
        path.unlink()
    else:
        path.write_bytes(b'{"value":2}')
    # Existing raw-member semantics deliberately retain validated immutable bytes
    # within one root. A new root must resolve and hash physical bytes afresh.
    assert reader.read_model_member(pointer, expected_bytes=11, decoder=decode) is first
    fresh = PinnedArtifactReadContext(
        cast(Session, MetadataSession(*session.records.values())), reader.settings
    )
    fresh.prefetch(((pointer.artifact_id, pointer.artifact_revision_id),))
    with pytest.raises(PinnedArtifactResolutionError):
        fresh.read_model_member(pointer, expected_bytes=11, decoder=decode)


@pytest.mark.parametrize("field", ["sha256", "schema_ref", "media_type", "member_path"])
def test_exact_pointer_fields_cannot_reuse_other_decoded_meaning(tmp_path, field):
    reader, pointer, _session = context_case(tmp_path)
    reader.read_model_member(pointer, expected_bytes=11, decoder=decode)
    changed = "sha256:" + "f" * 64 if field == "sha256" else "foreign"
    wrong = pointer.model_copy(update={field: changed})
    with pytest.raises(PinnedArtifactResolutionError):
        reader.read_model_member(wrong, expected_bytes=11, decoder=decode)


@pytest.mark.parametrize("size", [0, -1, True, 10, 12])
def test_current_bound_and_exact_size_are_checked_even_after_hit(tmp_path, size):
    reader, pointer, _session = context_case(tmp_path)
    reader.read_model_member(pointer, expected_bytes=11, decoder=decode)
    with pytest.raises(PinnedArtifactResolutionError):
        reader.read_model_member(pointer, expected_bytes=size, decoder=decode)


def test_decoder_switch_and_failed_decode_do_not_poison_or_reuse_other_model(tmp_path):
    reader, pointer, _session = context_case(tmp_path)
    first = reader.read_model_member(pointer, expected_bytes=11, decoder=decode)
    other = Mock(side_effect=decode)
    second = reader.read_model_member(pointer, expected_bytes=11, decoder=other)
    assert first == second and first is not second
    failed = Mock(side_effect=ValueError("synthetic invalid schema"))
    for _ in range(2):
        with pytest.raises(ValueError, match="synthetic"):
            reader.read_model_member(pointer, expected_bytes=11, decoder=failed)
    assert failed.call_count == 2 and not reader._decoded
    assert reader._decoded_bytes == 0
    assert reader.read_model_member(pointer, expected_bytes=11, decoder=decode) == first


@pytest.mark.parametrize("nested", [False, True])
def test_mutable_models_or_frozen_roots_with_mutable_children_are_not_retained(tmp_path, nested):
    class Mutable(BaseModel):
        value: int

    class FrozenRoot(BaseModel):
        model_config = ConfigDict(frozen=True)
        children: tuple[Mutable, ...]

    reader, pointer, _session = context_case(tmp_path)
    model = Mutable(value=1)
    decoder = Mock(return_value=FrozenRoot(children=(model,)) if nested else model)
    reader.read_model_member(pointer, expected_bytes=11, decoder=decoder)
    reader.read_model_member(pointer, expected_bytes=11, decoder=decoder)
    assert decoder.call_count == 2 and not reader._decoded and reader._decoded_bytes == 0


@pytest.mark.parametrize("field", ["list", "mapping", "extra"])
def test_frozen_root_mutable_containers_and_extras_are_not_retained(tmp_path, field):
    class Container(BaseModel):
        model_config = ConfigDict(frozen=True)
        entries: object

    class Extra(BaseModel):
        model_config = ConfigDict(frozen=True, extra="allow")
        value: int

    model = (
        Extra(value=1, extra_field=2)
        if field == "extra"
        else Container(entries=[1] if field == "list" else {"value": 1})
    )
    reader, pointer, _session = context_case(tmp_path)
    decoder = Mock(return_value=model)
    for _ in range(2):
        reader.read_model_member(pointer, expected_bytes=11, decoder=decoder)
    assert decoder.call_count == 2 and not reader._decoded


@pytest.mark.parametrize("limit", ["bytes", "members"])
def test_oversized_or_disabled_decoded_retention_does_not_change_valid_reads(tmp_path, limit):
    reader, pointer, _session = context_case(tmp_path)
    if limit == "bytes":
        reader.MAX_DECODED_BYTES = 10
    else:
        reader.MAX_DECODED_MEMBERS = 0
    decoder = Mock(side_effect=decode)
    for _ in range(2):
        assert reader.read_model_member(pointer, expected_bytes=11, decoder=decoder).value == 1
    assert decoder.call_count == 2 and not reader._decoded and reader._decoded_bytes == 0


@pytest.mark.parametrize("bound", ["raw", "decoded_bytes", "decoded_members"])
def test_each_existing_lru_enforces_its_own_retention_bound(tmp_path, bound):
    original, settings, arguments = _fixture(tmp_path)
    revision = original.get(ArtifactRevisionRecord, arguments["artifact_revision_id"])
    descriptors = [revision.manifest["files"][0]]
    for value in (2, 3):
        payload = json.dumps({"value": value}, separators=(",", ":")).encode()
        name = f"evidence/{value}.json"
        (Path(revision.nas_path) / name).write_bytes(payload)
        descriptors.append(descriptors[0] | {"file_name": name, "sha256": sha256_bytes(payload)})
    revision.manifest["files"] = descriptors
    revision.manifest_hash = content_sha256(revision.manifest)
    session = MetadataSession(*original.records.values())
    reader = PinnedArtifactReadContext(cast(Session, session), settings)
    reader.prefetch(((arguments["artifact_id"], arguments["artifact_revision_id"]),))
    if bound == "raw":
        reader.MAX_RETAINED_BYTES = 22
    elif bound == "decoded_bytes":
        reader.MAX_DECODED_BYTES = 22
    else:
        reader.MAX_DECODED_MEMBERS = 2
    pointers = tuple(
        reader.member_pointer(
            arguments["artifact_id"],
            arguments["artifact_revision_id"],
            row["file_name"],
            schema_ref=row["schema_ref"],
            media_type=row["media_type"],
        )
        for row in descriptors
    )
    decoder = Mock(side_effect=decode)
    for pointer in pointers:
        reader.read_model_member(pointer, expected_bytes=11, decoder=decoder)
    retained_models = 3 if bound == "raw" else 2
    assert len(reader._decoded) == retained_models and reader._decoded_bytes == 11 * retained_models
    assert reader.read_model_member(pointers[1], expected_bytes=11, decoder=decoder).value == 2
    assert decoder.call_count == 3
    reader.read_model_member(pointers[0], expected_bytes=11, decoder=decoder)
    assert decoder.call_count == (3 if bound == "raw" else 4)
    assert reader._decoded_bytes <= reader.MAX_DECODED_BYTES


@pytest.mark.parametrize(
    "fault", ["missing", "bytes", "approval", "producer", "revision", "root", "thread"]
)
def test_model_retained_after_raw_eviction_still_requires_actual_member_resolution(
    tmp_path, monkeypatch, fault
):
    original, settings, arguments = _fixture(tmp_path)
    revision = original.get(ArtifactRevisionRecord, arguments["artifact_revision_id"])
    binary = b"unparsedPNG"
    binary_name = "evidence/other.png"
    (Path(revision.nas_path) / binary_name).write_bytes(binary)
    revision.manifest["files"].append(
        {
            "file_name": binary_name,
            "sha256": sha256_bytes(binary),
            "bytes": len(binary),
            "schema_ref": "synthetic-image/1",
            "media_type": "image/png",
        }
    )
    revision.manifest_hash = content_sha256(revision.manifest)
    session = MetadataSession(*original.records.values())
    reader = PinnedArtifactReadContext(cast(Session, session), settings)
    reader.prefetch(((arguments["artifact_id"], arguments["artifact_revision_id"]),))
    pointer = reader.member_pointer(
        arguments["artifact_id"],
        arguments["artifact_revision_id"],
        arguments["member_path"],
        schema_ref=arguments["schema_ref"],
        media_type=arguments["media_type"],
    )
    reader.MAX_RETAINED_BYTES = 11
    decoder = Mock(side_effect=decode)
    reader.read_model_member(pointer, expected_bytes=11, decoder=decoder)
    reader.verify_member(
        artifact_id=pointer.artifact_id,
        revision_id=pointer.artifact_revision_id,
        member_path=binary_name,
        sha256=sha256_bytes(binary),
        schema_ref="synthetic-image/1",
        media_type="image/png",
        max_bytes=len(binary),
    )
    assert len(reader._members) == len(reader._decoded) == 1
    assert next(iter(reader._members))[2] == binary_name
    assert next(iter(reader._decoded))[2] == pointer.member_path
    path = Path(revision.nas_path) / pointer.member_path
    if fault == "missing":
        path.unlink()
    elif fault == "bytes":
        path.write_bytes(b'{"value":2}')
    elif fault == "approval":
        session.get(ArtifactRecord, pointer.artifact_id).approved = False
    elif fault == "producer":
        session.get(JobRecord, revision.job_id).status = "RUNNING"
    elif fault == "revision":
        revision.content_hash = "sha256:" + "f" * 64
    elif fault == "root":
        session.root.is_active = False
    else:
        monkeypatch.setattr(module, "get_ident", lambda: -1)
    with pytest.raises((OSError, PinnedArtifactResolutionError)):
        reader.read_model_member(pointer, expected_bytes=11, decoder=decoder)
    assert decoder.call_count == 1


def test_decoded_values_do_not_cross_root_request_lifetimes(tmp_path):
    first, pointer, session = context_case(tmp_path)
    second = PinnedArtifactReadContext(
        cast(Session, MetadataSession(*session.records.values())), first.settings
    )
    second.prefetch(((pointer.artifact_id, pointer.artifact_revision_id),))
    decoder = Mock(side_effect=decode)
    one = first.read_model_member(pointer, expected_bytes=11, decoder=decoder)
    two = second.read_model_member(pointer, expected_bytes=11, decoder=decoder)
    assert one == two and one is not two and decoder.call_count == 2


def payload_context(tmp_path, pointer, payload):
    original, settings, _arguments = _fixture(
        tmp_path, payload=payload, member_path=pointer.member_path, schema_ref=pointer.schema_ref
    )
    # Logical identity is independent of the temporary storage location.
    for row in original.records.values():
        row.logical_artifact_id = pointer.artifact_id
        if isinstance(row, (ArtifactRevisionRecord, JobRecord)):
            row.revision_id = pointer.artifact_revision_id
        if isinstance(row, ArtifactRevisionRecord):
            row.manifest.update(
                logical_artifact_id=pointer.artifact_id,
                revision_id=pointer.artifact_revision_id,
            )
            row.manifest_hash = content_sha256(row.manifest)
    session = MetadataSession(*original.records.values())
    reader = PinnedArtifactReadContext(cast(Session, session), settings)
    reader.prefetch(((pointer.artifact_id, pointer.artifact_revision_id),))
    return reader, session


def test_actual_item_consumer_reuses_schema_decoding_but_projects_each_current_profile(
    tmp_path, monkeypatch
):
    from eom_catalog_service import inference_transfer_snapshot_catalog_adapter as snapshot

    from tests.unit.inference_transfer_snapshot_fixtures import snapshot_prepare
    from tests.unit.test_inference_transfer_snapshot_catalog_adapter import owner_input

    value, _candidate, payload = owner_input("a")
    pointer = value.profile.source_basis.source.artifact_member
    reader, session = payload_context(tmp_path, pointer, payload)
    adapter = object.__new__(snapshot.CatalogInferenceTransferSnapshotSourceAdapter)
    parse = Mock(wraps=snapshot.read_item_content)
    project = Mock(wraps=snapshot.project_staged_item_entry)
    monkeypatch.setattr(snapshot, "read_item_content", parse)
    monkeypatch.setattr(snapshot, "project_staged_item_entry", project)
    results = tuple(
        adapter._materialize_entries(snapshot_prepare(), (value,), artifact_reader=reader)
        for _ in range(4)
    )
    assert all(result == results[0] for result in results)
    assert parse.call_count == 1 and project.call_count == 4
    session.get(ArtifactRecord, pointer.artifact_id).approved = False
    with pytest.raises(snapshot.InferenceTransferServiceError, match="SOURCE_PIN_MISMATCH"):
        adapter._materialize_entries(snapshot_prepare(), (value,), artifact_reader=reader)


def test_actual_report_consumer_reuses_report_but_rebuilds_current_receipt_aggregate(
    tmp_path, monkeypatch
):
    from eom_catalog_contracts import KnowledgeAnalysisProposalReceiptV9
    from eom_catalog_service import knowledge_proposal_resolution as proposal

    from tests.unit.test_past_exam_solution_analysis_contracts import _solution_resolution_records

    _run, _accepted, _logical, proposal_revision, _proposal, payload = (
        _solution_resolution_records()
    )
    receipt = KnowledgeAnalysisProposalReceiptV9.model_validate(proposal_revision.result)
    reader, session = payload_context(tmp_path, receipt.solution_report, payload)
    validate = Mock(wraps=proposal.validate_contract)
    monkeypatch.setattr(proposal, "validate_contract", validate)
    first = proposal.resolve_knowledge_solution_proposal(reader, receipt)
    changed = receipt.model_copy(
        update={"completed_at": receipt.completed_at + timedelta(seconds=1)}
    )
    second = proposal.resolve_knowledge_solution_proposal(reader, changed)
    assert first.solution_report is second.solution_report
    assert first.completed_at != second.completed_at and validate.call_count == 1
    session.get(ArtifactRecord, receipt.solution_report.artifact_id).approved = False
    with pytest.raises(proposal.KnowledgeProposalResolutionError):
        proposal.resolve_knowledge_solution_proposal(reader, receipt)


def test_four_phase_synthetic_operation_count_reduces_decoding_not_resolution(
    tmp_path, monkeypatch
):
    original, settings, arguments = _fixture(tmp_path)
    revision = original.get(ArtifactRevisionRecord, arguments["artifact_revision_id"])
    descriptors = revision.manifest["files"]
    for value in range(128):
        payload = json.dumps({"value": value}, separators=(",", ":")).encode()
        name = f"evidence/synthetic-{value}.json"
        (Path(revision.nas_path) / name).write_bytes(payload)
        descriptors.append(
            {
                "file_name": name,
                "sha256": sha256_bytes(payload),
                "bytes": len(payload),
                "schema_ref": arguments["schema_ref"],
                "media_type": "application/json",
            }
        )
    revision.manifest_hash = content_sha256(revision.manifest)
    resolve = Mock(wraps=module._resolve_pinned_artifact_member)
    monkeypatch.setattr(module, "_resolve_pinned_artifact_member", resolve)
    totals, counts = [], []
    for retain in (False, True):
        session = MetadataSession(*original.records.values())
        reader = PinnedArtifactReadContext(cast(Session, session), settings)
        if not retain:
            reader.MAX_DECODED_MEMBERS = 0
        reader.prefetch(((arguments["artifact_id"], arguments["artifact_revision_id"]),))
        decoder = Mock(side_effect=decode)
        phase_totals = []
        for _phase in range(4):
            total = 0
            for row in descriptors[1:]:
                pointer = reader.member_pointer(
                    arguments["artifact_id"],
                    arguments["artifact_revision_id"],
                    row["file_name"],
                    schema_ref=row["schema_ref"],
                    media_type=row["media_type"],
                )
                total += reader.read_model_member(
                    pointer, expected_bytes=row["bytes"], decoder=decoder
                ).value
            phase_totals.append(total)
        assert len(session.statements) == 3
        totals.append(tuple(phase_totals))
        counts.append(decoder.call_count)
    assert counts == [512, 128] and totals[0] == totals[1] == (8128,) * 4
    assert resolve.call_count == 1024  # Every member in every phase, both configurations.
