"""Schema-first candidate only; current 1.1/1.2 policy dispatch stays closed."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import cast
from unittest.mock import Mock

import pytest
from eom_catalog_contracts import load_schema, validate_contract
from eom_catalog_contracts.local_indexing_mixed_policy import (
    LocalIndexingMixedAccessPolicy,
    parse_supported_local_indexing_access_policy,
)
from eom_catalog_contracts.segmented_local_indexing_policy import (
    SEGMENTED_LOCAL_INDEXING_POLICY_SCHEMA,
    SegmentedLocalIndexingAccessPolicy,
    local_indexing_publication_policy_bytes,
    parse_local_indexing_publication_policy,
    parse_segmented_local_indexing_access_policy,
    segmented_local_indexing_policy_bytes,
)
from eom_catalog_contracts.validation import CATALOG_SCHEMA_RESOURCES
from eom_catalog_service import inference_transfer_snapshot_catalog_adapter as capture_module
from eom_catalog_service.inference_transfer_service import AdmittedInferenceTransferCorpus
from eom_catalog_service.inference_transfer_snapshot_catalog_adapter import (
    CatalogInferenceTransferSnapshotSourceAdapter,
    LocalIndexingSessionCapture,
)
from eom_catalog_service.knowledge_retrieval_service import (
    KnowledgeRetrievalApplicationService,
    KnowledgeRetrievalServiceError,
    ReadOnlyKnowledgeCandidatePool,
)
from eom_catalog_service.local_indexing_policy_publication import (
    LocalIndexingPolicyPublicationError,
    publish_local_indexing_access_policy,
)
from eom_catalog_service.local_indexing_source_paging import CandidateSourcePage
from eom_catalog_service.local_indexing_source_ports import LocalIndexingSourceError
from eom_catalog_service.segmented_local_indexing_population_read import (
    SegmentedPopulationReadError,
    read_segmented_candidate_source_page,
    scan_segmented_candidate_sources,
)
from eom_identifiers import canonical_json_bytes, content_sha256, sha256_bytes
from jsonschema import Draft202012Validator
from sqlalchemy.orm import Session

from tests.unit.test_local_indexing_mixed_policy import mixed_policy_document
from tests.unit.test_local_indexing_runtime_admission import installed as installed
from tests.unit.test_local_indexing_source_authority import MetadataSession
from tests.unit.test_local_indexing_source_authority import owner as owner
from tests.unit.test_postgres_local_indexing_fence import case as case


def candidate_document(**changes: object) -> dict[str, object]:
    body: dict[str, object] = deepcopy(mixed_policy_document())
    body["schema_version"] = "education-retrieval-access-policy/1.3"
    body.pop("maximum_sources")
    body["maximum_page_sources"] = 1024
    body["maximum_population_sources"] = 10000
    body.update(changes)
    body["content_sha256"] = content_sha256(
        {key: value for key, value in body.items() if key != "content_sha256"}
    )
    return body


def test_mirrored_schema_and_frozen_value_do_not_activate_old_dispatch() -> None:
    root = Path(__file__).resolve().parents[2]
    entry = CATALOG_SCHEMA_RESOURCES[SEGMENTED_LOCAL_INDEXING_POLICY_SCHEMA]
    raw = (root / entry.canonical_path).read_bytes()
    assert sha256_bytes(raw) == entry.sha256
    assert (
        raw
        == (
            root / "packages/catalog_contracts/eom_catalog_contracts" / entry.resource_path
        ).read_bytes()
    )
    Draft202012Validator.check_schema(load_schema(SEGMENTED_LOCAL_INDEXING_POLICY_SCHEMA))
    body = candidate_document()
    validate_contract(SEGMENTED_LOCAL_INDEXING_POLICY_SCHEMA, body)
    policy = SegmentedLocalIndexingAccessPolicy.model_validate(body)
    assert policy.maximum_page_sources == 1024
    assert policy.maximum_population_sources == 10000
    assert segmented_local_indexing_policy_bytes(policy) == canonical_json_bytes(body)
    assert parse_segmented_local_indexing_access_policy(canonical_json_bytes(body)) == policy
    assert parse_local_indexing_publication_policy(policy) == policy
    assert local_indexing_publication_policy_bytes(policy) == canonical_json_bytes(body)
    old = LocalIndexingMixedAccessPolicy.model_validate(mixed_policy_document())
    assert parse_local_indexing_publication_policy(old) == old
    assert local_indexing_publication_policy_bytes(old) == canonical_json_bytes(
        old.model_dump(mode="json")
    )
    with pytest.raises(ValueError):
        parse_supported_local_indexing_access_policy(body)
    with pytest.raises(ValueError):
        LocalIndexingMixedAccessPolicy.model_validate(body)


@pytest.mark.parametrize(
    "change",
    (
        {"maximum_page_sources": 1025},
        {"maximum_page_sources": 0},
        {"maximum_population_sources": 1024},
        {"maximum_population_sources": 1048577},
        {"maximum_page_sources": 8, "maximum_population_sources": 10000},
        {"maximum_page_sources": True},
        {"maximum_population_sources": True},
        {"maximum_sources": 1024},
    ),
)
def test_limits_and_predecessor_field_are_not_interchangeable(
    change: dict[str, object],
) -> None:
    with pytest.raises(ValueError):
        SegmentedLocalIndexingAccessPolicy.model_validate(candidate_document(**change))


def test_canonical_bytes_and_member_scope_are_closed() -> None:
    raw = canonical_json_bytes(candidate_document())
    with pytest.raises(ValueError):
        parse_segmented_local_indexing_access_policy(b" " + raw)
    with pytest.raises(ValueError):
        SegmentedLocalIndexingAccessPolicy.model_validate(
            candidate_document(source_classes=["PAST_EXAM", "APPROVED_ITEM"])
        )
    with pytest.raises(ValueError):
        SegmentedLocalIndexingAccessPolicy.model_validate(
            candidate_document(source_access_policy_revision_id="accessrev_" + "e" * 32)
        )


def test_owner_publication_still_requires_real_postgres_root() -> None:
    policy = SegmentedLocalIndexingAccessPolicy.model_validate(candidate_document())
    with Session() as session, pytest.raises(LocalIndexingPolicyPublicationError) as caught:
        publish_local_indexing_access_policy(session, policy)
    assert caught.value.code == "LOCAL_INDEXING_POLICY_CONTEXT_INVALID"
    forged = policy.model_copy(update={"injected_authority": "ADMIN"})
    with Session() as session, pytest.raises(ValueError):
        publish_local_indexing_access_policy(session, forged)
    assert session.get_transaction() is None


def test_pinned_segmented_read_is_distinct_from_existing_runtime_reader() -> None:
    policy = SegmentedLocalIndexingAccessPolicy.model_validate(candidate_document())
    session = MetadataSession(policy)  # type: ignore[arg-type]
    actual = KnowledgeRetrievalApplicationService.resolve_segmented_local_indexing_access_policy(
        cast(Session, session), policy.access_policy_revision_id, sha256=policy.content_sha256
    )
    assert actual == policy
    assert session.calls[0]._for_update_arg is None
    with pytest.raises(KnowledgeRetrievalServiceError) as caught:
        KnowledgeRetrievalApplicationService.resolve_local_indexing_access_policy(
            cast(Session, session), policy.access_policy_revision_id, sha256=policy.content_sha256
        )
    assert caught.value.code == "KNOWLEDGE_RETRIEVAL_POLICY_INVALID"


@pytest.mark.parametrize("fault", ("schema", "state", "hash", "document"))
def test_segmented_reader_rejects_stale_or_forged_metadata(fault: str) -> None:
    policy = SegmentedLocalIndexingAccessPolicy.model_validate(candidate_document())
    session = MetadataSession(policy)  # type: ignore[arg-type]
    if fault == "schema":
        session.policy.schema_version = "education-retrieval-access-policy/1.2"
    elif fault == "state":
        session.policy.state = "RETIRED"
    elif fault == "hash":
        session.policy.content_sha256 = "sha256:" + "f" * 64
    else:
        session.policy.canonical_document["maximum_page_sources"] = 8
    with pytest.raises(KnowledgeRetrievalServiceError):
        KnowledgeRetrievalApplicationService.resolve_segmented_local_indexing_access_policy(
            cast(Session, session), policy.access_policy_revision_id, sha256=policy.content_sha256
        )


def _segmented_owner(owner, *, page: int = 1024, population: int = 10000):
    policy = SegmentedLocalIndexingAccessPolicy.model_validate(
        candidate_document(
            service=owner.policy.service.model_dump(mode="json"),
            runtime_configuration_sha256=owner.policy.runtime_configuration_sha256,
            corpus_id=owner.policy.corpus_id,
            graph_id=owner.policy.graph_id,
            source_access_policy_revision_id=owner.policy.source_access_policy_revision_id,
            source_access_policy_sha256=owner.policy.source_access_policy_sha256,
            maximum_page_sources=page,
            maximum_population_sources=min(population, page * 1024),
        )
    )
    owner.intent = replace(
        owner.intent,
        namespace=policy.namespaces[0],
        source_classes=policy.source_classes,
        service_policy_revision_id=policy.access_policy_revision_id,
        service_policy_sha256=policy.content_sha256,
    )
    owner.retrieval.resolve_access_policy.return_value.allowed_source_classes = (
        policy.source_classes
    )
    owner.retrieval.resolve_segmented_local_indexing_access_policy.return_value = policy
    return policy


def test_segmented_page_authority_uses_actual_service_and_pinned_graph(owner) -> None:
    policy = _segmented_owner(owner)
    assert owner.authority.authorize_segmented_scope(owner.session, owner.intent) == policy
    owner.iam.assert_called_once_with(owner.session)
    owner.retrieval.resolve_segmented_local_indexing_access_policy.assert_called_once_with(
        owner.session, policy.access_policy_revision_id, sha256=policy.content_sha256
    )
    owner.retrieval.resolve_local_indexing_access_policy.assert_not_called()
    owner.retrieval.resolve_snapshot_pointer.assert_called_once_with(
        owner.session, owner.intent.graph_snapshot.graph_snapshot_revision_id
    )


def test_segmented_candidate_admission_reuses_canonical_source_reader(owner) -> None:
    _segmented_owner(owner)
    retrieval = object.__new__(KnowledgeRetrievalApplicationService)
    retrieval.resolve_snapshot_pointer = Mock(return_value=owner.intent.graph_snapshot)
    expected = ReadOnlyKnowledgeCandidatePool(owner.intent.graph_snapshot, (), False)
    retrieval._read_candidate_pool = Mock(return_value=expected)
    actual = retrieval.admit_segmented_local_indexing_candidate_pool(
        owner.session, owner.intent, authority=owner.authority
    )
    assert actual == expected
    assert owner.iam.call_count == 2
    retrieval._read_candidate_pool.assert_called_once()
    assert retrieval._read_candidate_pool.call_args.kwargs["allow_answer_bearing"] is True
    assert owner.retrieval.resolve_segmented_local_indexing_access_policy.call_count == 2
    assert owner.retrieval.resolve_local_indexing_access_policy.call_count == 0


def test_segmented_page_capture_reuses_profile_artifact_owner_and_checks_exact_pair(
    owner, monkeypatch: pytest.MonkeyPatch
) -> None:
    policy = _segmented_owner(owner)
    source, run = "itemrev_" + "1" * 32, "analysisrun_" + "1" * 32
    page = CandidateSourcePage(((source, run),), None, True)
    read_page = Mock(return_value=(policy, page))
    monkeypatch.setattr(capture_module, "read_segmented_candidate_source_page", read_page)
    adapter = object.__new__(CatalogInferenceTransferSnapshotSourceAdapter)
    adapter.sources = Mock()
    pool = ReadOnlyKnowledgeCandidatePool(owner.intent.graph_snapshot, (), False)
    adapter.sources.retrieval.admit_segmented_local_indexing_candidate_pool.return_value = pool
    corpus = AdmittedInferenceTransferCorpus(
        (),
        (),
        False,
        0,
        (SimpleNamespace(analysis_run_id=run, source=SimpleNamespace(item_revision_id=source)),),
    )

    def capture(session, scope, recipe, *, artifact_reader, read_pool):
        assert (session, recipe, artifact_reader) == (owner.session, owner.intent.recipe, reader)
        assert scope.source_revision_ids == (source,)
        assert scope.analysis_run_ids == (run,)
        assert read_pool() is pool
        return corpus, ()

    adapter._capture_population = Mock(side_effect=capture)
    reader = Mock()
    actual_page, result = adapter.capture_segmented_indexing_page_in_session(
        owner.session, owner.intent, authority=owner.authority, artifact_reader=reader
    )
    assert actual_page == page
    assert result == LocalIndexingSessionCapture(result.scope, corpus, ())
    assert read_page.call_count == 2
    reader.require_session.assert_called_once_with(owner.session)
    adapter.sources.retrieval.admit_local_indexing_candidate_pool.assert_not_called()

    adapter._capture_population = Mock(
        return_value=(AdmittedInferenceTransferCorpus((), (), False, 0, ()), ())
    )
    with pytest.raises(ValueError, match="SOURCE_PIN_MISMATCH"):
        adapter.capture_segmented_indexing_page_in_session(
            owner.session, owner.intent, authority=owner.authority, artifact_reader=reader
        )

    adapter._capture_population = Mock(return_value=(corpus, ()))
    changed = CandidateSourcePage((("itemrev_" + "2" * 32, "analysisrun_" + "2" * 32),), None, True)
    read_page.side_effect = [(policy, page), (policy, changed)]
    with pytest.raises(SegmentedPopulationReadError, match="UNAVAILABLE"):
        adapter.capture_segmented_indexing_page_in_session(
            owner.session, owner.intent, authority=owner.authority, artifact_reader=reader
        )


def test_segmented_page_cap_and_old_runtime_reader_fail_closed(owner) -> None:
    policy = _segmented_owner(owner, page=8)
    with pytest.raises(LocalIndexingSourceError, match="FORBIDDEN"):
        owner.authority.authorize_segmented_scope(
            owner.session, replace(owner.intent, maximum_candidates=9)
        )
    owner.retrieval.resolve_local_indexing_access_policy.return_value = policy
    with pytest.raises(LocalIndexingSourceError, match="UNAVAILABLE"):
        owner.authority.authorize_scope(owner.session, owner.intent)


def test_segmented_graph_and_source_policy_denials_do_not_grant_page(owner) -> None:
    _segmented_owner(owner)
    owner.session.publication = None
    with pytest.raises(LocalIndexingSourceError, match="FORBIDDEN"):
        owner.authority.authorize_segmented_scope(owner.session, owner.intent)
    owner.session.publication = object()
    owner.retrieval.resolve_access_policy.return_value.allowed_source_classes = ("PAST_EXAM",)
    with pytest.raises(LocalIndexingSourceError, match="FORBIDDEN"):
        owner.authority.authorize_segmented_scope(owner.session, owner.intent)


def _page_session(owner, rows: tuple[tuple[str, str], ...]):
    root = SimpleNamespace(is_active=True)
    owner.session.get_transaction = lambda: root
    owner.session.get_nested_transaction = lambda: None
    owner.session.connection = lambda: SimpleNamespace(
        get_isolation_level=lambda: "REPEATABLE READ"
    )
    owner.session.new = set()
    owner.session.dirty = set()
    owner.session.deleted = set()
    owner.session.execute = Mock(return_value=SimpleNamespace(all=lambda: rows))
    return root


def test_catalog_page_reauthorizes_same_pin_after_bounded_source_read(owner) -> None:
    policy = _segmented_owner(owner)
    rows = (("itemrev_" + "1" * 32, "analysisrun_" + "1" * 32),)
    _page_session(owner, rows)
    actual, page = read_segmented_candidate_source_page(
        cast(Session, owner.session), owner.intent, authority=owner.authority
    )
    assert actual == policy and page.members == rows and page.complete
    assert owner.iam.call_count == 2
    assert owner.session.execute.call_count == 1


def test_catalog_page_rejects_duplicate_and_changed_authority(owner) -> None:
    policy = _segmented_owner(owner)
    source = "itemrev_" + "1" * 32
    rows = ((source, "analysisrun_" + "1" * 32), (source, "analysisrun_" + "2" * 32))
    _page_session(owner, rows)
    with pytest.raises(SegmentedPopulationReadError, match="PAGE_INVALID"):
        read_segmented_candidate_source_page(
            cast(Session, owner.session), owner.intent, authority=owner.authority
        )
    owner.session.execute.return_value = SimpleNamespace(all=lambda: rows[:1])
    owner.authority.authorize_segmented_scope = Mock(
        side_effect=[policy, policy.model_copy(update={"maximum_population_sources": 9999})]
    )
    with pytest.raises(SegmentedPopulationReadError, match="UNAVAILABLE"):
        read_segmented_candidate_source_page(
            cast(Session, owner.session), owner.intent, authority=owner.authority
        )


def test_catalog_page_requires_clean_active_root_before_authority(owner) -> None:
    _segmented_owner(owner)
    _page_session(owner, ())
    owner.session.dirty = {object()}
    with pytest.raises(SegmentedPopulationReadError, match="CONTEXT_INVALID"):
        read_segmented_candidate_source_page(
            cast(Session, owner.session), owner.intent, authority=owner.authority
        )
    owner.iam.assert_not_called()


def test_complete_1025_source_scan_retains_only_page_descriptors(owner) -> None:
    _segmented_owner(owner)
    rows = tuple(
        (f"itemrev_{number:032x}", f"analysisrun_{number:032x}") for number in range(1, 1026)
    )
    _page_session(owner, ())
    owner.session.execute.side_effect = (
        SimpleNamespace(all=lambda: rows[:1025]),
        SimpleNamespace(all=lambda: rows[1024:]),
    )
    summary = scan_segmented_candidate_sources(
        cast(Session, owner.session), owner.intent, authority=owner.authority
    )
    assert summary.source_count == 1025
    assert tuple(segment.source_count for segment in summary.segments) == (1024, 1)
    assert summary.segments[0].last_source_revision_id == rows[1023][0]
    assert summary.segments[1].first_source_revision_id == rows[1024][0]
    expected_graph = owner.intent.graph_snapshot.graph_snapshot_revision_id
    assert summary.graph_snapshot_revision_id == expected_graph
    assert summary.selection_sha256.startswith("sha256:")
    assert owner.session.execute.call_count == 2
    assert owner.iam.call_count == 4
    assert not hasattr(summary, "members")


def test_scan_rejects_incomplete_or_over_policy_population(owner) -> None:
    _segmented_owner(owner, population=1025)
    _page_session(owner, ())
    with pytest.raises(SegmentedPopulationReadError, match="INCOMPLETE"):
        scan_segmented_candidate_sources(
            cast(Session, owner.session), owner.intent, authority=owner.authority
        )
    rows = tuple(
        (f"itemrev_{number:032x}", f"analysisrun_{number:032x}") for number in range(1, 1027)
    )
    owner.session.execute.side_effect = (
        SimpleNamespace(all=lambda: rows[:1025]),
        SimpleNamespace(all=lambda: rows[1024:]),
    )
    with pytest.raises(SegmentedPopulationReadError, match="INCOMPLETE"):
        scan_segmented_candidate_sources(
            cast(Session, owner.session), owner.intent, authority=owner.authority
        )


def test_full_scan_cannot_relabel_exact_subset_as_entire_population(owner) -> None:
    _segmented_owner(owner)
    _page_session(owner, ())
    selected = replace(owner.intent, source_revision_ids=("itemrev_" + "1" * 32,))
    with pytest.raises(SegmentedPopulationReadError, match="CONTEXT_INVALID"):
        scan_segmented_candidate_sources(
            cast(Session, owner.session), selected, authority=owner.authority
        )
    owner.iam.assert_not_called()


def test_full_scan_rejects_read_committed_before_any_page(owner) -> None:
    _segmented_owner(owner)
    _page_session(owner, ())
    owner.session.connection = lambda: SimpleNamespace(get_isolation_level=lambda: "READ COMMITTED")
    with pytest.raises(SegmentedPopulationReadError, match="CONTEXT_INVALID"):
        scan_segmented_candidate_sources(
            cast(Session, owner.session), owner.intent, authority=owner.authority
        )
    owner.iam.assert_not_called()
    owner.session.execute.assert_not_called()
