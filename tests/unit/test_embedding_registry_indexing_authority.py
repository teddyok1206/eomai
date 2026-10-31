"""Real shared Artifact/Registry logic with explicit synthetic IAM/population seams.

These cases do not authenticate an installed service, perform DB writes or run a
model. Identity/policy tests own those separate boundaries; no test seam is wired
into production composition.
"""

from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from eom_catalog_service.embedding_registry_application import (
    read_pinned_embedding_index,
    register_embedding_index,
    validate_resolved_embedding_registration,
)
from eom_catalog_service.embedding_registry_catalog_adapter import CatalogEmbeddingRegistryVerifier
from eom_catalog_service.embedding_registry_indexing_authority import (
    CatalogIndexingRegistrySourceAuthority,
)
from eom_catalog_service.embedding_registry_ports import (
    EmbeddingRegistryCaller,
    EmbeddingRegistryError,
    EmbeddingRegistryLookup,
    EmbeddingRegistryServiceCaller,
    SelectedEmbeddingSources,
    validate_embedding_registry_actor,
)
from eom_catalog_service.inference_transfer_service import (
    AdmittedInferenceTransferCorpus,
    AdmittedInferenceTransferSource,
)
from eom_catalog_service.local_indexing_source_authority import CatalogLocalIndexingSourceAuthority
from eom_catalog_service.local_indexing_source_ports import LocalIndexingSourceError
from eom_catalog_service.similarity_context_ports import SimilarityContextReadError
from eom_identity_service import LocalIndexingFenceError

from tests.unit import test_embedding_registry_catalog_adapter as registry_fixtures
from tests.unit import test_local_indexing_source_authority as source_fixtures
from tests.unit.embedding_registry_application_fixtures import capture_pair
from tests.unit.inference_transfer_fixtures import NOW
from tests.unit.test_embedding_registry_application import memory as memory
from tests.unit.test_local_indexing_runtime_admission import installed as installed
from tests.unit.test_postgres_local_indexing_fence import case as case

registry_owner = registry_fixtures.owner
source_owner = source_fixtures.owner


@pytest.fixture
def service_case(registry_owner, source_owner, monkeypatch: pytest.MonkeyPatch):
    base, session, command, index, binding, _scope, root = registry_owner
    policy = source_owner.policy
    gate = CatalogIndexingRegistrySourceAuthority(
        source_owner.authority,
        policy.access_policy_revision_id,
        policy.content_sha256,
        policy.native_execution_policy_sha256,
        policy.resource_profile_sha256,
    )
    verifier = CatalogEmbeddingRegistryVerifier.for_indexing_service(
        base.engine, base.configuration, source_authority=gate, settings=base.settings
    )
    # Reuse the exact local immutable numerical/index members. Population/IAM is
    # explicitly synthetic, while the new public service front door stays real.
    verifier.sources = base.sources
    _, resolved = capture_pair()
    corpus = AdmittedInferenceTransferCorpus(
        (resolved.entries[0].profile,),
        (),
        False,
        0,
        (
            AdmittedInferenceTransferSource(
                binding.solution_evidence.base_analysis_run_id, binding.source
            ),
        ),
    )
    population = Mock(return_value=(corpus, resolved.entries))
    monkeypatch.setattr(verifier.sources, "_capture_population", population)
    original_execute = session.execute

    def execute(statement):
        # The real owner now enumerates source/analysis pairs in bounded SQL
        # pages before materializing each page. IAM and paging logic stay real;
        # this test's SQL seam returns its one synthetic approved association.
        names = tuple(column["name"] for column in statement.column_descriptions)
        if names == ("source_revision_id", "analysis_run_id"):
            return [
                (binding.source.item_revision_id, binding.solution_evidence.base_analysis_run_id)
            ]
        return original_execute(statement)

    monkeypatch.setattr(session, "execute", execute)
    return SimpleNamespace(
        verifier=verifier,
        base=base,
        session=session,
        command=command,
        index=index,
        binding=binding,
        root=root,
        gate=gate,
        policy=policy,
        source=source_owner,
        population=population,
        caller=EmbeddingRegistryServiceCaller(policy.service),
        query=EmbeddingRegistryLookup(
            command.corpus_id,
            command.namespace,
            command.graph_snapshot,
            command.policy_revision_id,
            command.policy_sha256,
        ),
    )


def test_service_selected_source_read_retains_actual_authority_and_exact_pins(service_case):
    c = service_case
    selection = SelectedEmbeddingSources(c.query, (c.binding.source.item_revision_id,))
    resolved = c.verifier.resolve_selected_sources(c.session, c.caller, selection)
    assert resolved.sources == (c.binding.source,)
    intent = c.population.call_args.args[1]
    assert intent.source_revision_ids == selection.source_revision_ids
    assert intent.graph_snapshot == c.query.graph_snapshot
    assert intent.access_policy_revision_id == c.query.policy_revision_id
    assert intent.service_policy_revision_id == c.policy.access_policy_revision_id
    assert c.source.iam.called
    c.verifier.resolve_lookup(c.session, c.caller, c.query)
    assert c.population.call_args.args[1].source_revision_ids == selection.source_revision_ids
    assert c.gate.source_intent(c.caller, c.query, c.base.configuration).source_revision_ids == ()


def test_service_selected_read_does_not_waive_current_denial(service_case):
    c = service_case
    c.source.iam.side_effect = LocalIndexingFenceError("LOCAL_INDEXING_FENCE_FORBIDDEN")
    with pytest.raises(EmbeddingRegistryError):
        c.verifier.resolve_selected_sources(
            c.session,
            c.caller,
            SelectedEmbeddingSources(c.query, (c.binding.source.item_revision_id,)),
        )
    c.population.assert_not_called()


def test_service_cannot_supply_subset_as_registration_population(service_case):
    c = service_case
    with pytest.raises(EmbeddingRegistryError, match="SOURCE_PIN_MISMATCH"):
        c.gate.source_intent(
            c.caller,
            c.command,
            c.base.configuration,
            source_revision_ids=(c.binding.source.item_revision_id,),
        )
    c.population.assert_not_called()


def test_service_reuses_canonical_registration_and_separate_source_policy(service_case) -> None:
    c = service_case
    resolved = c.verifier.resolve_registration(c.session, c.caller, c.command)
    assert validate_resolved_embedding_registration(c.command, resolved) == resolved
    assert resolved.index == c.index and resolved.sources == (c.binding.source,)
    assert c.binding.policy_revision_id == c.policy.source_access_policy_revision_id
    assert c.binding.policy_revision_id != c.policy.access_policy_revision_id
    c.population.assert_called_once()
    intent = c.population.call_args.args[1]
    assert intent.service_policy_revision_id == c.policy.access_policy_revision_id
    assert not hasattr(intent, "requester_role") and not hasattr(
        intent, "requester_permission_keys"
    )
    assert c.source.iam.call_count == 6
    assert all(call.args == (c.session,) for call in c.source.iam.call_args_list)
    assert not c.base.sources.capture_in_session.called
    assert c.verifier.identity_fence is None


def test_service_scope_only_admission_has_no_population_or_files(service_case) -> None:
    c = service_case
    c.verifier.require_index_publication_scope(c.session, c.caller, c.query)
    assert c.source.iam.call_count == 1
    c.population.assert_not_called()
    assert not c.session.statements and not c.base.sources.capture_in_session.called


def test_new_reconciliation_selects_and_authorizes_exact_current_graph(service_case):
    c = service_case
    c.source.session.corpus.current_graph_snapshot_revision_id = (
        c.query.graph_snapshot.graph_snapshot_revision_id
    )
    query = c.gate.current_lookup(c.source.session, c.base.configuration)
    assert query == c.query
    assert query.policy_revision_id == c.policy.source_access_policy_revision_id
    assert query.policy_revision_id != c.policy.access_policy_revision_id
    c.population.assert_not_called()


def test_no_published_graph_is_not_a_fabricated_empty_snapshot(service_case):
    c = service_case
    c.source.session.corpus.current_graph_snapshot_revision_id = None
    assert c.gate.current_lookup(c.source.session, c.base.configuration) is None
    c.source.retrieval.resolve_snapshot_pointer.assert_not_called()
    c.population.assert_not_called()


@pytest.mark.parametrize("field", ["corpus", "native_policy", "resource", "namespace"])
def test_current_head_does_not_broaden_installed_service_selection(service_case, field):
    c = service_case
    c.source.session.corpus.current_graph_snapshot_revision_id = (
        c.query.graph_snapshot.graph_snapshot_revision_id
    )
    gate, configuration = c.gate, c.base.configuration
    if field == "corpus":
        configuration = replace(configuration, corpus_id="corpus_" + "f" * 32)
    elif field == "namespace":
        configuration = replace(
            configuration,
            namespace=configuration.namespace.model_copy(
                update={
                    "view": "CONTENT_ONLY"
                    if configuration.namespace.view != "CONTENT_ONLY"
                    else "METADATA_ONLY"
                }
            ),
        )
    else:
        gate = replace(
            gate,
            **{
                "native_execution_policy_sha256"
                if field == "native_policy"
                else "resource_profile_sha256": "sha256:" + "f" * 64
            },
        )
    with pytest.raises(LocalIndexingSourceError, match="FORBIDDEN"):
        gate.current_lookup(c.source.session, configuration)
    c.population.assert_not_called()


def test_prepared_index_and_lookup_use_same_service_front_door(service_case) -> None:
    c = service_case
    prepared = c.verifier.resolve_prepared_index(c.session, c.caller, c.command, c.index)
    assert prepared.index == c.index
    lookup = c.verifier.resolve_lookup(c.session, c.caller, c.query)
    assert lookup.sources == (c.binding.source,) and len(lookup.entries) == 1
    assert c.population.call_count == 2 and not c.base.sources.capture_in_session.called


@pytest.mark.parametrize("mode", ["human-in-service", "service-in-human"])
def test_no_implicit_caller_mode_switch_or_operator_fallback(service_case, mode) -> None:
    c = service_case
    owner, caller = (
        (c.verifier, EmbeddingRegistryCaller("operator_" + "1" * 32))
        if mode == "human-in-service"
        else (c.base, c.caller)
    )
    with pytest.raises(EmbeddingRegistryError, match="AUTHORITY_UNAVAILABLE"):
        owner.resolve_registration(c.session, caller, c.command)
    c.source.iam.assert_not_called()
    c.population.assert_not_called()
    assert not c.base.sources.capture_in_session.called and not c.session.statements


@pytest.mark.parametrize(
    "field,value",
    [
        ("service_id", "localindexservice_" + "f" * 32),
        ("service_revision_id", "localindexservicerev_" + "f" * 32),
        ("service_identity_sha256", "sha256:" + "f" * 64),
    ],
)
def test_exact_service_reference_is_selection_not_possession_authority(service_case, field, value):
    c = service_case
    caller = EmbeddingRegistryServiceCaller(c.caller.service.model_copy(update={field: value}))
    with pytest.raises(EmbeddingRegistryError, match="FORBIDDEN"):
        c.verifier.resolve_registration(c.session, caller, c.command)
    c.source.iam.assert_not_called()
    c.population.assert_not_called()
    assert not c.session.statements


@pytest.mark.parametrize("stage", ["initial", "late"])
def test_revocation_before_capture_or_after_file_read_blocks_result(service_case, stage):
    c = service_case
    checked = c.source.iam.return_value
    denied = LocalIndexingFenceError("LOCAL_INDEXING_FENCE_FORBIDDEN")
    c.source.iam.side_effect = [denied] if stage == "initial" else [checked] * 5 + [denied]
    with pytest.raises(EmbeddingRegistryError, match="FORBIDDEN"):
        c.verifier.resolve_registration(c.session, c.caller, c.command)
    assert not c.base.sources.capture_in_session.called
    assert c.population.call_count == (0 if stage == "initial" else 1)


@pytest.mark.parametrize(
    "code,expected",
    [
        ("LOCAL_INDEXING_SOURCE_FORBIDDEN", "FORBIDDEN"),
        ("LOCAL_INDEXING_SOURCE_UNAVAILABLE", "AUTHORITY_UNAVAILABLE"),
        ("LOCAL_INDEXING_SOURCE_SCOPE_INVALID", "AUTHORITY_UNAVAILABLE"),
    ],
)
def test_service_errors_remain_stable_and_do_not_fallback(
    service_case, monkeypatch, code, expected
):
    c = service_case
    monkeypatch.setattr(
        CatalogLocalIndexingSourceAuthority,
        "authorize_scope",
        Mock(side_effect=LocalIndexingSourceError(code)),
    )
    with pytest.raises(EmbeddingRegistryError, match=expected):
        c.verifier.resolve_registration(c.session, c.caller, c.command)
    c.population.assert_not_called()
    assert not c.base.sources.capture_in_session.called


@pytest.mark.parametrize("change", ["source-policy", "capacity", "namespace"])
def test_service_grant_bounds_precede_population_and_file_reads(service_case, change):
    c = service_case
    query = c.query
    if change == "source-policy":
        query = replace(query, policy_sha256="sha256:" + "f" * 64)
    elif change == "capacity":
        c.verifier._indexing_source_authority = replace(c.gate, maximum_sources=1)
        query = replace(query, maximum_sources=2)
    else:
        other_view = "CONTENT_ONLY" if query.namespace.view == "METADATA_ONLY" else "METADATA_ONLY"
        query = replace(query, namespace=query.namespace.model_copy(update={"view": other_view}))
    with pytest.raises(EmbeddingRegistryError, match=r"FORBIDDEN|SOURCE_PIN_MISMATCH"):
        c.verifier.resolve_lookup(c.session, c.caller, query)
    c.population.assert_not_called()
    assert not c.base.sources.capture_in_session.called and not c.session.statements


@pytest.mark.parametrize("fault", ["binary", "producer"])
def test_service_cannot_bypass_existing_numerical_or_artifact_checks(service_case, fault):
    c = service_case
    if fault == "binary":
        p = c.binding.row_ref.shard_manifest
        (c.root / p.artifact_id / p.artifact_revision_id / "vectors.f32").write_bytes(b"corrupt")
    else:
        from eom_orchestrator.models import JobRecord

        c.session.get(JobRecord, "job_" + "c" * 32).status = "RUNNING"
    with pytest.raises(EmbeddingRegistryError, match="POINTER_INVALID"):
        c.verifier.resolve_registration(c.session, c.caller, c.command)
    c.population.assert_not_called()


def test_service_cannot_be_used_as_human_similarity_or_pinned_query(service_case) -> None:
    c = service_case
    with pytest.raises(EmbeddingRegistryError, match="FORBIDDEN"):
        read_pinned_embedding_index(c.session, c.caller, object(), c.verifier)
    with pytest.raises(EmbeddingRegistryError, match="FORBIDDEN"):
        c.verifier.resolve_pinned_read(c.session, c.caller, object(), object())
    with pytest.raises(SimilarityContextReadError, match="AUTHORITY_UNAVAILABLE"):
        c.verifier._similarity_capture(c.session, c.caller, object())
    c.source.iam.assert_not_called()
    c.population.assert_not_called()


def test_closed_service_caller_rejects_hidden_or_fake_authority(service_case) -> None:
    c = service_case
    for fake in (
        SimpleNamespace(service=c.caller.service),
        EmbeddingRegistryCaller("localindexservice_" + "1" * 32),
        EmbeddingRegistryServiceCaller(c.caller.service.model_copy(update={"roles": ["ADMIN"]})),
    ):
        with pytest.raises(EmbeddingRegistryError, match="CALLER_INVALID"):
            validate_embedding_registry_actor(fake)
    with pytest.raises(EmbeddingRegistryError, match="CONFIGURATION_INVALID"):
        replace(c.gate, authority=Mock(spec=CatalogLocalIndexingSourceAuthority))
    with pytest.raises(EmbeddingRegistryError, match="AUTHORITY_UNAVAILABLE"):
        CatalogEmbeddingRegistryVerifier.for_indexing_service(
            c.base.engine, c.base.configuration, source_authority=object()
        )


def test_common_registration_replay_still_reauthorizes_service(memory, service_case) -> None:
    # Memory persistence + synthetic trusted verifier proves common application
    # semantics only, not actual service authentication or DB concurrency.
    session, verifier = memory
    caller = service_case.caller
    command, _ = capture_pair()
    verifier.authorize_scope = Mock()
    first = register_embedding_index(session, caller, command, verifier, now=NOW)
    replay = register_embedding_index(session, caller, command, verifier, now=NOW)
    assert not first.replayed and replay.replayed
    assert first.index_revision_id == replay.index_revision_id
    assert all(call.args[1] == caller for call in verifier.authorize_scope.call_args_list)
    before = {name: dict(rows) for name, rows in session.state.items()}
    verifier.authorize_scope = Mock(
        side_effect=EmbeddingRegistryError("EMBEDDING_REGISTRY_FORBIDDEN")
    )
    with pytest.raises(EmbeddingRegistryError, match="FORBIDDEN"):
        register_embedding_index(session, caller, command, verifier, now=NOW)
    assert session.state == before
