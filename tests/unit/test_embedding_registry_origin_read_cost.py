"""Bounded first-origin read/DTO cost; source/IAM/SQL are synthetic, no model/DB.

The real registration application with its existing memory repository creates
cumulative four-binding revisions. The concrete Catalog reference verifier then
reads actual temporary Artifact files through PinnedArtifactReadContext. Timing
excludes fixture construction and is diagnostic, never a live-throughput claim.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from time import perf_counter_ns
from tracemalloc import get_traced_memory, start, stop
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import Mock

import pytest
from eom_catalog_contracts.embedding_registry import RegisterEmbeddingIndexCommand
from eom_catalog_contracts.inference_transfer_embedding import EmbeddingIndexManifest
from eom_catalog_contracts.inference_transfer_experiment import (
    StagedExperimentEntry,
    population_sha256,
)
from eom_catalog_service import embedding_registry_application as application
from eom_catalog_service import embedding_registry_catalog_adapter as catalog
from eom_catalog_service import pinned_artifact_resolution as artifact_reads
from eom_catalog_service.embedding_registry_ports import (
    EmbeddingRegistryCaller,
    EmbeddingRegistryLookup,
    EmbeddingRegistryVerificationPort,
    ResolvedEmbeddingRegistration,
)
from eom_catalog_service.embedding_registry_repository import binding_origin, registered_row
from eom_catalog_service.inference_transfer_service import (
    AdmittedInferenceTransferCorpus,
    AdmittedInferenceTransferSource,
)
from eom_catalog_service.pinned_artifact_resolution import PinnedArtifactReadContext
from eom_catalog_service.settings import CatalogSettings
from eom_identifiers import canonical_json_bytes, content_sha256
from eom_protocol.artifact_members import ArtifactMemberPointer
from sqlalchemy.orm import Session

from tests.unit.embedding_registry_application_fixtures import (
    MemoryRepository,
    MemorySession,
    SyntheticVerifier,
    capture_pair,
)
from tests.unit.inference_transfer_embedding_fixtures import (
    embedding_entry,
    index_manifest,
    index_pointer,
    seal,
    source_binding,
    vector_shard,
)
from tests.unit.inference_transfer_fixtures import NOW
from tests.unit.test_embedding_registry_catalog_adapter import OwnerSession, _file_set

CALLER = EmbeddingRegistryCaller("operator_" + "1" * 32)
BATCH_SIZE = 4


def _entry(number: int) -> StagedExperimentEntry:
    body = embedding_entry().model_dump(mode="json")
    identity = f"{number + 1024:032x}"
    body["profile"]["profile_id"] = "inferenceprofile_" + identity
    body["profile"]["profile_revision_id"] = "inferenceprofilerev_" + identity
    source = body["profile"]["source_basis"]["source"]
    source.update(item_id="item_" + identity, item_revision_id="itemrev_" + identity)
    body["profile"] = seal(body["profile"], "profile_sha256")
    # Shared immutable content/report and metadata intentionally deduplicate to one
    # encoding; this isolates historical index metadata from numerical/model work.
    return StagedExperimentEntry.model_validate(body)


def _history(count: int) -> tuple[tuple[Any, ...], ...]:
    template, initial = capture_pair()
    entries = tuple(_entry(number) for number in range(count))
    shard = vector_shard((source_binding(entries[0]).encoding,))
    bindings = tuple(source_binding(entry, shard=shard) for entry in entries)
    previous = None
    history = []
    for ordinal, size in enumerate(range(BATCH_SIZE, count + 1, BATCH_SIZE), start=1):
        index_body = index_manifest(
            *bindings[:size], previous_manifest=None if previous is None else previous[0]
        ).model_dump(mode="json")
        index_body["index_revision_id"] = "embeddingindexrev_" + f"{ordinal:032x}"
        index = EmbeddingIndexManifest.model_validate(seal(index_body, "index_sha256"))
        pointer_body = index_pointer(index).model_dump(mode="json")
        pointer_body.update(
            artifact_id="artifact_" + f"{ordinal:032x}",
            artifact_revision_id="rev_" + f"{ordinal:032x}",
        )
        pointer = ArtifactMemberPointer.model_validate(pointer_body)
        sources = tuple(entry.profile.source_basis.source for entry in entries[:size])
        command_body = template.model_dump(mode="json")
        command_body.update(
            index_revision_id=index.index_revision_id,
            index_manifest=pointer.model_dump(mode="json"),
            index_sha256=index.index_sha256,
            expected_current_index_revision_id=None
            if previous is None
            else previous[1].index_revision_id,
            expected_lock_version=ordinal,
            operation_key=f"synthetic-origin-cost:{ordinal}",
            source_set_sha256=population_sha256(sources),
            binding_set_sha256=content_sha256(
                [binding.binding_sha256 for binding in index.bindings]
            ),
            eligible_source_count=size,
            binding_count=size,
        )
        command = RegisterEmbeddingIndexCommand.model_validate(seal(command_body, "request_sha256"))
        resolved = ResolvedEmbeddingRegistration(
            initial.corpus_id,
            index,
            ((bindings[0].row_ref.shard_manifest, shard),),
            previous,
            sources,
            entries[:size],
        )
        history.append((command, resolved))
        previous = pointer, index
    return tuple(history)


def _records(
    root: Path, pointer: ArtifactMemberPointer, index: EmbeddingIndexManifest, number: int
):
    records = _file_set(
        root,
        pointer.artifact_id,
        pointer.artifact_revision_id,
        "control_embedding_index",
        "index.json",
        {
            "index.json": (
                canonical_json_bytes(index.model_dump(mode="json")),
                pointer.schema_ref,
                pointer.media_type,
            )
        },
        "0",
    )
    # Give each synthetic producer a valid unique identity before the first reader
    # captures immutable metadata; never mutate a previously captured Artifact.
    job, logical, revision = records
    job.job_id = logical.job_id = revision.job_id = "job_" + f"{number:032x}"
    revision.manifest = revision.manifest | {"job_id": job.job_id}
    revision.manifest_hash = content_sha256(revision.manifest)
    return records


@pytest.mark.parametrize("count", (16, 64, 256))
def test_cumulative_first_origin_manifest_read_and_decode_cost(
    count: int,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    history = _history(count)
    session = MemorySession()
    owner = SyntheticVerifier(*(resolved for _command, resolved in history))
    monkeypatch.setattr(application, "EmbeddingRegistryRepository", MemoryRepository)
    for command, _resolved in history:
        application.register_embedding_index(
            cast(Session, session),
            CALLER,
            command,
            cast(EmbeddingRegistryVerificationPort, owner),
            now=NOW,
        )
    first, last = history[0][0], history[-1][0]
    head = session.state["heads"][last.index_id]
    replay = application.register_embedding_index(
        cast(Session, session),
        CALLER,
        first,
        cast(EmbeddingRegistryVerificationPort, owner),
        now=NOW,
    )
    assert replay.replayed and not replay.is_current
    assert head.current_index_revision_id == last.index_revision_id
    expected_origins = {
        binding.binding_sha256: command.index_manifest
        for command, resolved in reversed(history)
        for binding in resolved.index.bindings
    }
    actual_origins = tuple(binding_origin(row) for row in session.state["bindings"].values())
    assert len(actual_origins) == count
    assert all(
        origin.manifest == expected_origins[origin.binding_sha256] for origin in actual_origins
    )
    assert len({origin.manifest for origin in actual_origins}) == count // BATCH_SIZE
    rows = tuple(registered_row(row) for row in session.state["encodings"].values())
    assert len(rows) == 1  # Intentional immutable encoding deduplication.

    records = tuple(
        record
        for ordinal, (command, resolved) in enumerate(history, start=1)
        for record in _records(tmp_path, command.index_manifest, resolved.index, ordinal)
    )
    concrete_session = OwnerSession(last, *records)
    concrete_session.binding_records = session.state["bindings"]
    resolved = history[-1][1]
    verifier = catalog.CatalogEmbeddingRegistryVerifier(
        cast(Any, object()),
        catalog.EmbeddingRegistryOwnerConfiguration(
            last.corpus_id,
            last.namespace,
            resolved.index.space,
            resolved.index.recipe,
            ("PAST_EXAM",),
        ),
        identity_fence=Mock(),
        settings=CatalogSettings(nas_artifact_root=tmp_path),
    )
    corpus = AdmittedInferenceTransferCorpus(
        tuple(entry.profile for entry in resolved.entries),
        (),
        False,
        0,
        tuple(
            AdmittedInferenceTransferSource(
                binding.solution_evidence.base_analysis_run_id, binding.source
            )
            for binding in resolved.index.bindings
        ),
    )
    calls: Counter[str] = Counter()
    timings: Counter[str] = Counter()
    parsed_bindings = []
    original_parse = catalog.parse_supported_embedding_index
    original_binding = catalog.assemble_embedding_source_binding
    # The current reader opens one guarded descriptor, reads bytes, then hashes
    # those exact bytes. Instrument that actual leaf, not its retired path API.
    original_hash = artifact_reads.sha256_bytes
    original_read = PinnedArtifactReadContext.read_pinned

    def capture(current, _caller, _intent, _phase):
        calls["capture"] += 1
        return PinnedArtifactReadContext(current, verifier.settings), SimpleNamespace(
            corpus=corpus,
            entries=resolved.entries,
        )

    def parse_index(document):
        calls["index_dto_decode"] += 1
        parsed_bindings.append(len(document["bindings"]))
        started = perf_counter_ns()
        try:
            return original_parse(document)
        finally:
            timings["index_dto_decode_ns"] += perf_counter_ns() - started

    def construct_binding(**options):
        calls["current_binding_construction"] += 1
        return original_binding(**options)

    def read_member(reader, **options):
        if options["member_path"] == "index.json":
            calls["index_member_read_boundary"] += 1
        return original_read(reader, **options)

    def physical_hash(payload):
        assert isinstance(payload, bytes)
        calls["physical_index_read_hash"] += 1
        started = perf_counter_ns()
        try:
            return original_hash(payload)
        finally:
            timings["physical_index_payload_hash_ns"] += perf_counter_ns() - started

    def shards(_reader, pointers):
        calls["shard_boundary"] += 1
        assert pointers == (resolved.shards[0][0],)
        # Numerical validation is an explicit synthetic seam: no vectors/model.
        return resolved.shards

    monkeypatch.setattr(verifier, "_capture", capture)
    monkeypatch.setattr(verifier, "_read_shards", shards)
    monkeypatch.setattr(catalog, "parse_supported_embedding_index", parse_index)
    monkeypatch.setattr(catalog, "assemble_embedding_source_binding", construct_binding)
    monkeypatch.setattr(PinnedArtifactReadContext, "read_pinned", read_member)
    monkeypatch.setattr(artifact_reads, "sha256_bytes", physical_hash)
    query = EmbeddingRegistryLookup(
        last.corpus_id,
        last.namespace,
        last.graph_snapshot,
        last.policy_revision_id,
        last.policy_sha256,
    )
    # Keep an executed control of the former cumulative-origin operation, not
    # merely a relaxed expected counter. It reuses the unchanged selected-index
    # reader and proves every first origin contains the exact expected binding.
    expected_bindings = {binding.binding_sha256: binding for binding in resolved.index.bindings}
    origin_pointers = tuple(dict.fromkeys(origin.manifest for origin in actual_origins))
    start()
    try:
        baseline_started = perf_counter_ns()
        for _ in range(2):
            reader = PinnedArtifactReadContext(cast(Session, concrete_session), verifier.settings)
            historical = {
                pointer: {
                    binding.binding_sha256: binding
                    for binding in verifier._read_index(reader, pointer).bindings
                }
                for pointer in origin_pointers
            }
            for origin in actual_origins:
                assert (
                    historical[origin.manifest][origin.binding_sha256]
                    == expected_bindings[origin.binding_sha256]
                )
            del historical
        baseline_elapsed_ns = perf_counter_ns() - baseline_started
        _baseline_retained_bytes, baseline_peak_bytes = get_traced_memory()
    finally:
        stop()
    revisions = count // BATCH_SIZE
    expected_visits = BATCH_SIZE * revisions * (revisions + 1) // 2
    assert sorted(parsed_bindings) == sorted(list(range(BATCH_SIZE, count + 1, BATCH_SIZE)) * 2)
    assert sum(parsed_bindings) == 2 * expected_visits
    assert calls == {
        "index_dto_decode": 2 * revisions,
        # _read_index verifies the member, then read_model_member revalidates
        # that same cached member. There is still only one physical read/hash.
        "index_member_read_boundary": 4 * revisions,
        "physical_index_read_hash": 2 * revisions,
    }
    baseline_calls, baseline_timings = dict(calls), dict(timings)
    calls.clear()
    timings.clear()
    parsed_bindings.clear()
    start()
    try:
        started = perf_counter_ns()
        for _ in range(2):
            actual = verifier.verify_registered_references(
                cast(Session, concrete_session),
                CALLER,
                query,
                rows,
                actual_origins,
            )
            assert len(actual.origins) == count
            for value in actual.origins:
                assert value.binding == expected_bindings[value.origin.binding_sha256]
                assert value.origin.manifest == expected_origins[value.origin.binding_sha256]
        elapsed_ns = perf_counter_ns() - started
        _retained_bytes, peak_bytes = get_traced_memory()
    finally:
        stop()
    assert parsed_bindings == []
    assert calls == {
        "capture": 2,
        "current_binding_construction": 2 * count,
        "index_member_read_boundary": 2 * revisions,
        "physical_index_read_hash": 2 * revisions,
        "shard_boundary": 2,
    }
    print(
        "embedding_origin_cost="
        + json.dumps(
            {
                "bindings": count,
                "batch_size": BATCH_SIZE,
                "first_origin_revisions": revisions,
                "prior_full_dto_binding_visits_per_capture": expected_visits,
                "historical_full_dto_binding_visits_per_capture": 0,
                "calls": dict(calls),
                "timings": dict(timings),
                "baseline_origin_only_calls": baseline_calls,
                "baseline_origin_only_timings": baseline_timings,
                "baseline_origin_only_elapsed_ns": baseline_elapsed_ns,
                "baseline_origin_only_traced_peak_bytes": baseline_peak_bytes,
                "two_capture_elapsed_ns": elapsed_ns,
                "two_capture_traced_peak_bytes": peak_bytes,
                "source_iam_sql": "SYNTHETIC",
                "numerical_validation": "SYNTHETIC_SEAM",
                "live_throughput": "NOT_MEASURED",
            },
            sort_keys=True,
        )
    )
