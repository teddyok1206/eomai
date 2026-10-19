"""Existing state machine with synthetic mixed owner captures; never live authority."""

from __future__ import annotations

from dataclasses import replace
from typing import cast
from unittest.mock import Mock

import pytest
from eom_catalog_contracts.embedding_registry import EmbeddingIndexNamespace
from eom_catalog_contracts.inference_transfer_embedding import EmbeddingSourceBinding
from eom_catalog_contracts.inference_transfer_experiment import population_sha256
from eom_catalog_contracts.mixed_embedding_index import (
    MIXED_EMBEDDING_INDEX_SCHEMA_REF,
    MixedEmbeddingIndexManifest,
    RegisteredReviewEmbeddingSourceBinding,
)
from eom_catalog_contracts.mixed_embedding_registry import (
    EmbeddingIndexRegistrationResultV2,
    MixedEmbeddingIndexNamespace,
    RegisterEmbeddingIndexCommandV2,
)
from eom_catalog_contracts.registered_review_profile import (
    RegisteredReviewProfilePointer,
    RegisteredReviewSourceBasis,
    build_registered_review_profile,
)
from eom_catalog_service import embedding_registry_application as application
from eom_catalog_service.embedding_registry_ports import (
    EmbeddingBindingLookupKey,
    EmbeddingRegistryCaller,
    EmbeddingRegistryError,
    EmbeddingRegistryLookup,
    RegisteredEmbeddingIndexRead,
    RegisteredReviewEmbeddingBindingLookupKey,
    ResolvedEmbeddingRegistration,
)
from eom_catalog_service.embedding_registry_repository import (
    ASSOCIATION_COLUMNS,
    REGISTERED_REVIEW_ASSOCIATION_COLUMNS,
    artifact_member,
)
from eom_catalog_service.embedding_source_associations import embedding_binding_lookup_key
from eom_identifiers import content_sha256
from eom_protocol.artifact_members import ArtifactMemberPointer
from sqlalchemy.orm import Session

from tests.unit.embedding_registry_application_fixtures import (
    MemoryRepository,
    MemorySession,
    SyntheticVerifier,
    capture_pair,
)
from tests.unit.inference_transfer_embedding_fixtures import embedding_entry, seal
from tests.unit.inference_transfer_fixtures import NOW
from tests.unit.mixed_embedding_fixtures import mixed_embedding_case
from tests.unit.test_mixed_embedding_registry import mixed_registration_command

CALLER = EmbeddingRegistryCaller("operator_" + "1" * 32)


def mixed_capture(previous=None):
    new_entry, _binding, shard, shard_pointer, index = mixed_embedding_case()
    old = next(value for value in index.bindings if isinstance(value, EmbeddingSourceBinding))
    body = index.model_dump(mode="json")
    for value in body["bindings"]:
        value.update(policy_revision_id=old.policy_revision_id, policy_sha256=old.policy_sha256)
        value["binding_sha256"] = seal(value, "binding_sha256")["binding_sha256"]
    if previous is not None:
        prior_command, prior = previous
        body.update(
            index_revision_id="embeddingindexrev_" + "f" * 32,
            previous_manifest=prior_command.index_manifest.model_dump(mode="json"),
        )
    index = MixedEmbeddingIndexManifest.model_validate(seal(body, "index_sha256"))
    registered = next(
        value
        for value in index.bindings
        if isinstance(value, RegisteredReviewEmbeddingSourceBinding)
    )
    sources = tuple(binding.source for binding in index.bindings)
    base_ids = tuple(
        sorted(
            (
                (old.source.item_revision_id, old.solution_evidence.base_analysis_run_id),
                (registered.source.item_revision_id, registered.base_analysis_run_id),
            )
        )
    )
    pointer = ArtifactMemberPointer(
        artifact_id="artifact_" + ("b" if previous is None else "c") * 32,
        artifact_revision_id="rev_" + ("b" if previous is None else "c") * 32,
        member_path="index.json",
        schema_ref=MIXED_EMBEDDING_INDEX_SCHEMA_REF,
        media_type="application/json",
        sha256=content_sha256(index.model_dump(mode="json")),
    )
    command_body = mixed_registration_command().model_dump(mode="json")
    command_body.update(
        operation_key="synthetic-mixed:first" if previous is None else "synthetic-mixed:next",
        namespace={
            "storage_partition": index.storage_partition,
            "space_sha256": index.space.space_sha256,
            "view": index.view,
            "recipe_sha256": index.recipe.recipe_sha256,
            "projection_version": "mixed-solution-comparison/2.0",
            "population_scope": "ALL_ADMITTED_GRAPH_ITEMS",
        },
        index_id=index.index_id,
        index_revision_id=index.index_revision_id,
        index_manifest=pointer.model_dump(mode="json"),
        index_sha256=index.index_sha256,
        graph_snapshot=old.graph_snapshot.model_dump(mode="json"),
        policy_revision_id=old.policy_revision_id,
        policy_sha256=old.policy_sha256,
        expected_current_index_revision_id=None
        if previous is None
        else prior.index.index_revision_id,
        expected_lock_version=1 if previous is None else 2,
        source_set_sha256=population_sha256(sources),
        binding_set_sha256=content_sha256([binding.binding_sha256 for binding in index.bindings]),
        eligible_source_count=2,
        binding_count=2,
    )
    command = RegisterEmbeddingIndexCommandV2.model_validate(seal(command_body, "request_sha256"))
    capture = ResolvedEmbeddingRegistration(
        corpus_id=command.corpus_id,
        index=index,
        shards=((shard_pointer, shard),),
        previous=None if previous is None else (prior_command.index_manifest, prior.index),
        sources=sources,
        entries=(new_entry, embedding_entry()),
        base_analysis_run_ids=base_ids,
    )
    return command, capture


class MixedMemoryRepository(MemoryRepository):
    """Reuse the legacy memory transaction/CAS behavior, with both ledger key families."""

    def bindings(self, keys):
        expected = {(type(key), key.columns()) for key in keys}
        result = {}
        for digest, row in self.session.state["bindings"].items():
            registered = row.evidence_kind == "REGISTERED_ITEM_REVIEW_SOLUTION"
            columns = REGISTERED_REVIEW_ASSOCIATION_COLUMNS if registered else ASSOCIATION_COLUMNS
            key_type = (
                RegisteredReviewEmbeddingBindingLookupKey
                if registered
                else EmbeddingBindingLookupKey
            )
            if (key_type, tuple(getattr(row, name) for name in columns)) in expected:
                result[digest] = row
        return result

    def read_pinned_revision(self, index_id, revision_id):
        revision = self.revision(revision_id)
        head = self.session.state["heads"].get(index_id)
        if revision is None or head is None or revision.index_id != index_id:
            return None
        model = (
            MixedEmbeddingIndexNamespace
            if head.projection_version == "mixed-solution-comparison/2.0"
            else EmbeddingIndexNamespace
        )
        return RegisteredEmbeddingIndexRead(
            head.corpus_id,
            model.model_validate({name: getattr(head, name) for name in model.model_fields}),
            revision.index_id,
            revision.index_revision_id,
            artifact_member(revision, "manifest_"),
            revision.index_sha256,
            revision.graph_snapshot_revision_id,
            revision.policy_revision_id,
            revision.policy_sha256,
            revision.binding_count,
            revision.binding_set_sha256,
        )


class MixedSyntheticVerifier(SyntheticVerifier):
    def resolve_lookup(self, session, caller, query):
        result = super().resolve_lookup(session, caller, query)
        return replace(result, base_analysis_run_ids=self.capture.base_analysis_run_ids)


@pytest.fixture
def memory(monkeypatch):
    command, capture = mixed_capture()
    monkeypatch.setattr(application, "EmbeddingRegistryRepository", MixedMemoryRepository)
    return MemorySession(), MixedSyntheticVerifier(capture), command, capture


def _register(session, owner, command):
    return application.register_embedding_index(
        cast(Session, session), CALLER, command, owner, now=NOW
    )


def _query(command):
    return EmbeddingRegistryLookup(
        command.corpus_id,
        command.namespace,
        command.graph_snapshot,
        command.policy_revision_id,
        command.policy_sha256,
    )


def test_actual_common_closure_accepts_old_new_branches_and_both_individual_extractors(memory):
    _session, _owner, command, capture = memory
    assert application.validate_resolved_embedding_registration(command, capture) is capture
    assert all(
        command.namespace.accepts_projection(value.projection_version)
        for value in capture.index.bindings
    )


@pytest.mark.parametrize(
    "fault", ("missing", "wrong_registered", "wrong_legacy", "review_job", "duplicate", "foreign")
)
def test_real_base_association_map_is_required_and_not_inferred_from_review(memory, fault):
    _session, _owner, command, capture = memory
    registered = next(
        b for b in capture.index.bindings if isinstance(b, RegisteredReviewEmbeddingSourceBinding)
    )
    old = next(b for b in capture.index.bindings if isinstance(b, EmbeddingSourceBinding))
    bases = dict(capture.base_analysis_run_ids)
    if fault == "missing":
        del bases[registered.source.item_revision_id]
    elif fault == "wrong_registered":
        bases[registered.source.item_revision_id] = "analysisrun_" + "f" * 32
    elif fault == "wrong_legacy":
        bases[old.source.item_revision_id] = "analysisrun_" + "f" * 32
    elif fault == "review_job":
        bases[registered.source.item_revision_id] = registered.review_evidence.review.job_id
    elif fault == "foreign":
        bases["itemrev_" + "f" * 32] = "analysisrun_" + "f" * 32
    values = tuple(bases.items())
    if fault == "duplicate":
        values += values[:1]
    with pytest.raises(EmbeddingRegistryError):
        application.validate_resolved_embedding_registration(
            command, replace(capture, base_analysis_run_ids=values)
        )


def test_old_command_cannot_register_new_index_even_with_the_same_raw_corpus_claim(memory):
    _session, _owner, _command, capture = memory
    legacy, _ = capture_pair()
    with pytest.raises(EmbeddingRegistryError, match="SOURCE_PIN_MISMATCH"):
        application.validate_resolved_embedding_registration(legacy, capture)


def test_register_same_key_replay_retains_original_bindings_encodings_and_receipt(memory):
    session, owner, command, capture = memory
    first = _register(session, owner, command)
    replay = _register(session, owner, command)
    assert isinstance(first, EmbeddingIndexRegistrationResultV2)
    assert not first.replayed and replay.replayed and replay.is_current
    assert first.registered_at == replay.registered_at
    assert {name: len(values) for name, values in session.state.items()} == {
        "heads": 1,
        "revisions": 1,
        "encodings": 2,
        "bindings": 2,
    }
    for binding in capture.index.bindings:
        row = session.state["bindings"][binding.binding_sha256]
        if isinstance(binding, RegisteredReviewEmbeddingSourceBinding):
            assert row.solution_analysis_run_id is None
            assert row.review_job_id == binding.review_evidence.review.job_id


def test_missing_lookup_has_both_key_families_then_reuses_exact_rows_after_registration(memory):
    session, owner, command, capture = memory
    before = application.prepare_missing_embedding_bindings(
        cast(Session, session), CALLER, _query(command), owner
    )
    assert before.observation.available_view_count == len(before.observation.missing) == 2
    assert any(
        isinstance(key, RegisteredReviewEmbeddingBindingLookupKey)
        for key in before.observation.missing
    )
    _register(session, owner, command)
    after = application.prepare_missing_embedding_bindings(
        cast(Session, session), CALLER, _query(command), owner
    )
    assert after.observation.missing == ()
    assert len(after.observation.reusable_rows) == 2 and len(after.bindings) == 2
    assert {embedding_binding_lookup_key(value) for value in after.bindings} == {
        embedding_binding_lookup_key(value) for value in capture.index.bindings
    }


def test_new_revision_reuses_all_encodings_and_same_bindings_without_overwriting_first_origins(
    memory,
):
    session, owner, command, capture = memory
    first = _register(session, owner, command)
    successor, next_capture = mixed_capture((command, capture))
    owner.captures[successor.index_revision_id] = next_capture
    second = _register(session, owner, successor)
    historical = _register(session, owner, command)
    assert second.current_lock_version == historical.current_lock_version == 3
    assert historical.replayed and not historical.is_current
    assert len(session.state["encodings"]) == 2 and len(session.state["bindings"]) == 2
    assert len(session.state["revisions"]) == 2
    assert all(
        row.binding_manifest_sha256 == first.index_manifest.sha256
        for row in session.state["bindings"].values()
    )


def test_failed_cas_rolls_back_new_head_and_all_components(memory):
    session, owner, command, _capture = memory
    session.cas_succeeds = False
    with pytest.raises(EmbeddingRegistryError, match="STALE_CURRENT"):
        _register(session, owner, command)
    assert all(not values for values in session.state.values())


def test_new_provenance_binding_reuses_exact_numeric_encoding_and_preserves_old_binding(memory):
    session, owner, command, capture = memory
    first = _register(session, owner, command)
    successor, next_capture = mixed_capture((command, capture))
    entry = next(
        value for value in next_capture.entries if value.profile.schema_version.endswith("/2.0")
    )
    basis = entry.profile.source_basis.model_dump(mode="json")
    evidence = basis["review_evidence"]
    evidence["authoring_receipt_sha256"] = "sha256:" + "f" * 64
    basis["review_evidence"] = seal(evidence, "evidence_sha256")
    profile = build_registered_review_profile(
        source_basis=RegisteredReviewSourceBasis.model_validate(basis),
        claims=entry.profile.claims,
        created_at=entry.profile.created_at,
    )
    refreshed_entry = type(entry).model_validate(
        entry.model_dump(mode="json") | {"profile": profile.model_dump(mode="json")}
    )
    index_body = next_capture.index.model_dump(mode="json")
    for binding in index_body["bindings"]:
        if binding["schema_version"].endswith("/2.0"):
            binding.update(
                profile=RegisteredReviewProfilePointer.from_profile(profile).model_dump(
                    mode="json"
                ),
                review_evidence=basis["review_evidence"],
            )
            binding["binding_sha256"] = seal(binding, "binding_sha256")["binding_sha256"]
    index = MixedEmbeddingIndexManifest.model_validate(seal(index_body, "index_sha256"))
    request = successor.model_dump(mode="json")
    request["index_manifest"]["sha256"] = content_sha256(index.model_dump(mode="json"))
    request.update(
        index_sha256=index.index_sha256,
        binding_set_sha256=content_sha256([value.binding_sha256 for value in index.bindings]),
    )
    successor = RegisterEmbeddingIndexCommandV2.model_validate(seal(request, "request_sha256"))
    next_capture = replace(
        next_capture,
        index=index,
        entries=tuple(
            refreshed_entry if value is entry else value for value in next_capture.entries
        ),
    )
    owner.captures[successor.index_revision_id] = next_capture
    second = _register(session, owner, successor)
    assert second.current_lock_version == 3
    assert len(session.state["encodings"]) == 2
    assert len(session.state["bindings"]) == 3
    original_registered = next(
        value
        for value in capture.index.bindings
        if isinstance(value, RegisteredReviewEmbeddingSourceBinding)
    )
    fresh_registered = next(
        value
        for value in index.bindings
        if isinstance(value, RegisteredReviewEmbeddingSourceBinding)
    )
    assert original_registered.encoding == fresh_registered.encoding
    assert (
        session.state["bindings"][original_registered.binding_sha256].binding_manifest_sha256
        == first.index_manifest.sha256
    )
    assert (
        session.state["bindings"][fresh_registered.binding_sha256].binding_manifest_sha256
        == second.index_manifest.sha256
    )


def test_forged_command_extra_is_rejected_before_authority_or_state_writes(memory):
    session, owner, command, _capture = memory
    with pytest.raises(EmbeddingRegistryError, match="REQUEST_INVALID"):
        _register(session, owner, command.model_copy(update={"undeclared": "forbidden"}))
    assert owner.calls == []
    assert all(not values for values in session.state.values())


def test_post_registration_observation_is_read_only_and_keeps_exact_two_branch_components(
    memory, monkeypatch
):
    session, owner, command, capture = memory
    result = _register(session, owner, command)
    writes = Mock(side_effect=AssertionError("observation cannot mutate history"))
    for name in ("head", "create_head", "advance", "add_revision", "insert_components"):
        monkeypatch.setattr(MixedMemoryRepository, name, writes)
    assert (
        application.verify_embedding_index_registration_observation(
            cast(Session, session), CALLER, command, result, owner
        )
        is capture
    )
    writes.assert_not_called()
