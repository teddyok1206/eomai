"""Real temporary immutable bytes, synthetic source/IAM; never a live latency claim."""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import replace
from pathlib import Path
from time import perf_counter

import pytest
from eom_catalog_service import pinned_artifact_resolution as pinned
from eom_catalog_service.embedding_registry_ports import ResolvedPinnedEmbeddingIndex
from eom_catalog_service.pinned_artifact_resolution import PinnedArtifactReadContext
from eom_catalog_service.similarity_context_ports import SimilarityContextReadError
from eom_identifiers import content_sha256, sha256_bytes
from eom_orchestrator.models import ArtifactRecord, ArtifactRevisionRecord

from tests.unit.test_embedding_registry_catalog_adapter import owner as owner
from tests.unit.test_pinned_artifact_read_context import MetadataSession
from tests.unit.test_pinned_artifact_resolution import _fixture
from tests.unit.test_similarity_context_service import CALLER, case


@pytest.mark.parametrize("fault", ("root", "settings", "thread", "registration"))
def test_borrowed_reader_is_not_an_authority_or_cross_root_handle(owner, monkeypatch, fault):
    from eom_catalog_service import embedding_registry_catalog_adapter as module

    verifier, session, command, *_ = owner
    request, _sources, _query = case()
    settings = verifier.settings
    if fault == "settings":
        settings = replace(settings, nas_artifact_root=settings.nas_artifact_root / "wrong")
    reader = PinnedArtifactReadContext(session, settings)
    if fault == "root":
        reader = PinnedArtifactReadContext(MetadataSession(), settings)
    elif fault == "thread":
        monkeypatch.setattr(pinned, "get_ident", lambda: -1)
    if fault == "registration":
        with pytest.raises(module.EmbeddingRegistryError):
            verifier._capture(
                session,
                CALLER,
                command,
                module.InferenceTransferSessionCapturePhase.CAPTURE_POPULATION,
                artifact_reader=reader,
            )
    else:
        with pytest.raises(SimilarityContextReadError):
            verifier.prepare_similarity_context_in_session(
                session, CALLER, request, artifact_reader=reader
            )
    verifier.sources.capture_in_session.assert_not_called()


@pytest.mark.parametrize("withdrawn", (False, True))
def test_real_catalog_reuses_one_reader_but_retains_four_fresh_population_captures(
    owner, monkeypatch, withdrawn
):
    from eom_catalog_service import embedding_registry_catalog_adapter as module

    verifier, session, command, _index, _binding, _scope, _root = owner
    request, _sources, _query = case()
    reader = PinnedArtifactReadContext(session, verifier.settings)
    original = verifier.sources.capture_in_session.side_effect
    phase_count = Counter()
    readers, hashes = [], []
    original_hash = pinned.sha256_file
    pointer = command.index_manifest

    def count_hash(path):
        hashes.append(path)
        return original_hash(path)

    def capture(actual_session, actual_command, recipe, **options):
        # Actual authority is intentionally synthetic here, but is called each time.
        current = original(actual_session, actual_command, recipe, **options)
        phase = options["phase"].value
        phase_count[phase] += 1
        context = options["artifact_reader"]
        readers.append(context)
        if phase == "CAPTURE_POPULATION":
            if withdrawn and phase_count[phase] == 4:
                old = session.records[(ArtifactRecord, pointer.artifact_id)]
                session.records[(ArtifactRecord, pointer.artifact_id)] = ArtifactRecord(
                    logical_artifact_id=old.logical_artifact_id,
                    job_id=old.job_id,
                    artifact_type=old.artifact_type,
                    approved=False,
                )
            context.prefetch(((pointer.artifact_id, pointer.artifact_revision_id),))
            context.read_member(
                artifact_id=pointer.artifact_id,
                revision_id=pointer.artifact_revision_id,
                member_path=pointer.member_path,
                sha256=pointer.sha256,
                media_type=pointer.media_type,
                schema_ref=pointer.schema_ref,
                max_bytes=1024 * 1024,
            )
        return current

    def index_read(actual_session, caller, intent, owner):
        owner.authorize_scope(actual_session, caller, intent.scope)
        owner._capture(
            actual_session,
            caller,
            intent.scope,
            module.InferenceTransferSessionCapturePhase.CAPTURE_POPULATION,
        )
        owner.authorize_scope(actual_session, caller, intent.scope)
        return ResolvedPinnedEmbeddingIndex(intent, (), (), (), ())

    monkeypatch.setattr(pinned, "sha256_file", count_hash)
    monkeypatch.setattr(verifier.sources, "capture_in_session", capture)
    monkeypatch.setattr(module, "read_pinned_embedding_index", index_read)
    prepared = verifier.prepare_similarity_context_in_session(
        session, CALLER, request, artifact_reader=reader
    )
    verifier.read_similarity_views_in_session(
        session, CALLER, request, prepared, artifact_reader=reader
    )
    if withdrawn:
        with pytest.raises(SimilarityContextReadError):
            verifier.prepare_similarity_context_in_session(
                session, CALLER, request, artifact_reader=reader
            )
    else:
        assert (
            verifier.prepare_similarity_context_in_session(
                session, CALLER, request, artifact_reader=reader
            )
            == prepared
        )
    assert phase_count == {"CAPTURE_POPULATION": 4, "AUTHORIZE_SCOPE": 9}
    assert all(value is reader for value in readers)
    assert hashes == [
        Path(session.records[(ArtifactRevisionRecord, pointer.artifact_revision_id)].nas_path)
        / pointer.member_path
    ]


def test_520_member_four_phase_benchmark_reuses_bytes_not_current_authority(tmp_path, monkeypatch):
    original, settings, arguments = _fixture(tmp_path)
    revision = original.get(ArtifactRevisionRecord, arguments["artifact_revision_id"])
    root = Path(revision.nas_path)
    revision.manifest["files"] = []
    descriptors = []
    for number in range(520):
        name = f"evidence/synthetic-{number}.json"
        payload = json.dumps({"value": number, "synthetic_padding": "x" * 4096}).encode()
        (root / name).write_bytes(payload)
        descriptor = {
            "file_name": name,
            "sha256": sha256_bytes(payload),
            "bytes": len(payload),
            "schema_ref": arguments["schema_ref"],
            "media_type": "application/json",
        }
        revision.manifest["files"].append(descriptor)
        descriptors.append(descriptor)
    # Preserve a valid canonical primary descriptor and bytes in addition to the520 rows.
    revision.manifest["files"].append(
        {
            "file_name": arguments["member_path"],
            "sha256": arguments["sha256"],
            "bytes": revision.content_bytes,
            "schema_ref": arguments["schema_ref"],
            "media_type": arguments["media_type"],
        }
    )
    revision.manifest_hash = content_sha256(revision.manifest)
    hash_calls = []
    actual_hash = pinned.sha256_file
    monkeypatch.setattr(
        pinned, "sha256_file", lambda path: (hash_calls.append(path), actual_hash(path))[1]
    )
    results = {}
    for reuse in (False, True):
        session = MetadataSession(*original.records.values())
        shared = PinnedArtifactReadContext(session, settings) if reuse else None
        start, before = perf_counter(), len(hash_calls)
        totals = []
        for _phase in range(4):
            context = shared or PinnedArtifactReadContext(session, settings)
            context.prefetch(((arguments["artifact_id"], arguments["artifact_revision_id"]),))
            total = 0
            for descriptor in descriptors:
                total += len(
                    context.read_member(
                        artifact_id=arguments["artifact_id"],
                        revision_id=arguments["artifact_revision_id"],
                        member_path=descriptor["file_name"],
                        sha256=descriptor["sha256"],
                        schema_ref=descriptor["schema_ref"],
                        media_type="application/json",
                        max_bytes=8192,
                    )
                )
            totals.append(total)
        results["shared" if reuse else "independent"] = {
            "physical_reads": len(hash_calls) - before,
            "metadata_queries": len(session.statements),
            "elapsed_ms": round((perf_counter() - start) * 1000),
        }
        assert len(set(totals)) == 1 and totals[0] > 2 * 1024 * 1024
    assert results["independent"]["physical_reads"] == 2080
    assert results["shared"]["physical_reads"] == 520
    assert results["independent"]["metadata_queries"] == 12
    assert results["shared"]["metadata_queries"] == 3
    # No wall-time assertion: filesystem warmth/scheduling must not make correctness flaky.
    print(json.dumps({"synthetic_read_reuse_only_not_live_latency": results}, sort_keys=True))
