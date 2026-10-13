"""Offline use-case tests: no database, native model, runtime activation or NAS."""

from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import MagicMock, Mock

import eom_catalog_service.inference_transfer_catalog_adapter as adapter_module
import pytest
from eom_catalog_contracts import ApprovedPastExamItemKnowledgeSourceV3, EvidenceBudget
from eom_catalog_contracts.item_inference_transfer import (
    InferenceTransferProfile,
    InferenceTransferProfilePointer,
)
from eom_catalog_service.inference_transfer_catalog_adapter import (
    CatalogInferenceTransferSourceAdapter,
)
from eom_catalog_service.inference_transfer_ports import (
    EmbeddingRankerProvenance,
    ScoredInferenceTransferProfile,
)
from eom_catalog_service.inference_transfer_scope import InferenceTransferPopulationScope
from eom_catalog_service.inference_transfer_service import (
    AdmittedInferenceTransferCorpus,
    AdmittedInferenceTransferSource,
    InferenceTransferApplicationService,
    InferenceTransferSearchCommand,
    InferenceTransferServiceError,
)
from eom_catalog_service.knowledge_retrieval_service import ReadOnlyKnowledgeCandidatePool
from eom_identifiers import content_sha256
from eom_operator_identity import PermissionKey
from sqlalchemy.orm import Session

from tests.unit.inference_transfer_fixtures import profile, sha


def exact_profile(seed: str) -> InferenceTransferProfile:
    value = profile(seed).model_dump(mode="json", exclude={"profile_sha256"})
    value["source_basis"]["source"]["item_id"] = "item_" + seed * 32
    value["source_basis"]["source"]["item_revision_id"] = "itemrev_" + seed * 32
    value["source_basis"]["solution_evidence"]["base_analysis_run_id"] = "analysisrun_" + seed * 32
    pointer = value["source_basis"]["solution_evidence"]
    pointer["pointer_sha256"] = content_sha256(
        {key: child for key, child in pointer.items() if key != "pointer_sha256"}
    )
    value["profile_sha256"] = content_sha256(value)
    return InferenceTransferProfile.model_validate(value)


def command(**changes: Any) -> InferenceTransferSearchCommand:
    return replace(
        InferenceTransferSearchCommand(
            actor_id="operator_" + "f" * 32,
            graph_snapshot=profile().source_basis.graph_snapshot,
            access_policy_revision_id="accessrev_" + "f" * 32,
            access_policy_sha256=sha("f"),
            query_item_revision_id="itemrev_" + "a" * 32,
            top_k=2,
        ),
        **changes,
    )


class Sources:
    def __init__(self, corpus: AdmittedInferenceTransferCorpus) -> None:
        self.corpus = corpus
        self.authorizations: list[AdmittedInferenceTransferCorpus] = []
        self.revoked = False
        self.revoked_run_ids: set[str] = set()

    def load(self, _command: InferenceTransferSearchCommand) -> AdmittedInferenceTransferCorpus:
        return self.corpus

    def reauthorize(
        self,
        _command: InferenceTransferSearchCommand,
        value: AdmittedInferenceTransferCorpus,
    ) -> None:
        self.authorizations.append(value)
        if self.revoked or any(
            row.analysis_run_id in self.revoked_run_ids for row in value.sources
        ):
            raise InferenceTransferServiceError("INFERENCE_TRANSFER_FORBIDDEN")


def corpus(
    *profiles: InferenceTransferProfile, graph_scores: tuple[tuple[str, int], ...] = ()
) -> AdmittedInferenceTransferCorpus:
    return AdmittedInferenceTransferCorpus(
        tuple(profiles),
        graph_scores,
        False,
        0,
        tuple(
            AdmittedInferenceTransferSource(
                value.source_basis.solution_evidence.base_analysis_run_id,
                value.source_basis.source,
            )
            for value in profiles
        ),
    )


def test_embedding_finds_nonlexical_candidate_and_union_keeps_graph_provenance() -> None:
    a, b, c = (exact_profile(seed) for seed in "abc")
    sources = Sources(
        corpus(a, b, c, graph_scores=((c.source_basis.source.item_revision_id, 975),))
    )
    ranker = Mock(provenance=EmbeddingRankerProvenance(kind="TEST_ONLY", model_spec=None))
    ranker.rank.return_value = (
        ScoredInferenceTransferProfile(InferenceTransferProfilePointer.from_profile(b), 0.91),
    )
    result = InferenceTransferApplicationService(sources, ranker).search(command())
    assert result.status == "CANDIDATES"
    assert [candidate.provenance for candidate in result.candidates] == [
        ("EMBEDDING_POOL",),
        ("GRAPH_LEXICAL",),
    ]
    assert result.candidates[0].graph_relevance_milli is None
    assert result.candidates[1].cosine_similarity is None
    assert result.candidates[1].graph_relevance_milli == 975
    assert ranker.rank.call_args.args == (a, (b, c))
    assert sources.authorizations == [sources.corpus]
    assert result.embedding_provenance is not None
    assert result.embedding_provenance.kind == "TEST_ONLY"
    assert any("TEST_ONLY" in text for text in result.limitations)
    assert result.eligible_profile_set_sha256.startswith("sha256:")


def test_duplicate_channel_candidate_keeps_both_scores_without_duplication() -> None:
    a, b = exact_profile("a"), exact_profile("b")
    sources = Sources(corpus(a, b, graph_scores=((b.source_basis.source.item_revision_id, 850),)))
    ranker = Mock(provenance=EmbeddingRankerProvenance(kind="TEST_ONLY", model_spec=None))
    ranker.rank.return_value = (
        ScoredInferenceTransferProfile(InferenceTransferProfilePointer.from_profile(b), -0.25),
    )
    result = InferenceTransferApplicationService(sources, ranker).search(command())
    assert len(result.candidates) == 1
    assert result.candidates[0].provenance == ("EMBEDDING_POOL", "GRAPH_LEXICAL")
    assert result.candidates[0].cosine_similarity == -0.25
    assert result.candidates[0].graph_relevance_milli == 850


def test_exact_profile_population_hash_is_order_independent_and_changes_with_revision() -> None:
    a, b = exact_profile("a"), exact_profile("b")
    result = InferenceTransferApplicationService(Sources(corpus(a, b))).search(command())
    reordered = InferenceTransferApplicationService(Sources(corpus(b, a))).search(command())
    assert result.eligible_profile_set_sha256 == reordered.eligible_profile_set_sha256
    changed = InferenceTransferApplicationService(Sources(corpus(a, exact_profile("c")))).search(
        command()
    )
    assert changed.eligible_profile_set_sha256 != result.eligible_profile_set_sha256
    assert result.embedding_provenance is None


def test_ranker_identity_cannot_change_between_read_and_scores() -> None:
    a, b = exact_profile("a"), exact_profile("b")
    sources = Sources(corpus(a, b))
    ranker = Mock(provenance=EmbeddingRankerProvenance(kind="TEST_ONLY", model_spec=None))

    def swap(*_args: Any, **_kwargs: Any) -> tuple[ScoredInferenceTransferProfile, ...]:
        ranker.provenance = object()
        return (
            ScoredInferenceTransferProfile(InferenceTransferProfilePointer.from_profile(b), 0.9),
        )

    ranker.rank.side_effect = swap
    with pytest.raises(InferenceTransferServiceError, match="MODEL_PIN_MISMATCH"):
        InferenceTransferApplicationService(sources, ranker).search(command())
    assert not sources.authorizations


def test_missing_model_and_missing_accepted_report_are_honest_without_fake_vectors() -> None:
    a = exact_profile("a")
    missing = exact_profile("b")
    sources = Sources(
        replace(
            corpus(a),
            missing_solution_reports=1,
            truncated=True,
            sources=(
                *corpus(a).sources,
                AdmittedInferenceTransferSource(
                    missing.source_basis.solution_evidence.base_analysis_run_id,
                    missing.source_basis.source,
                ),
            ),
        )
    )
    result = InferenceTransferApplicationService(sources).search(command())
    assert result.status == "UNAVAILABLE" and not result.candidates
    assert any("UNAVAILABLE" in text for text in result.limitations)
    assert any("풀이보고서가 없는" in text for text in result.limitations)
    assert result.truncated and result.missing_solution_report_count == 1


def test_unindexed_query_does_not_invent_profile_or_call_model() -> None:
    sources = Sources(corpus(exact_profile("b")))
    ranker = Mock(provenance=EmbeddingRankerProvenance(kind="TEST_ONLY", model_spec=None))
    result = InferenceTransferApplicationService(sources, ranker).search(command())
    assert result.status == "NOT_INDEXED" and result.query_profile is None
    assert result.candidates == ()
    ranker.rank.assert_not_called()
    assert sources.authorizations


@pytest.mark.parametrize("forgery", ("unknown", "wrong_hash", "query", "duplicate"))
def test_ranker_cannot_materialize_unadmitted_references(forgery: str) -> None:
    a, b, c = (exact_profile(seed) for seed in "abc")
    sources = Sources(corpus(a, b))
    pointer = InferenceTransferProfilePointer.from_profile(b)
    if forgery == "unknown":
        pointer = InferenceTransferProfilePointer.from_profile(c)
    elif forgery == "wrong_hash":
        pointer = pointer.model_copy(update={"profile_sha256": sha("0")})
    elif forgery == "query":
        pointer = InferenceTransferProfilePointer.from_profile(a)
    value = ScoredInferenceTransferProfile(pointer, 0.8)
    ranker = Mock(provenance=EmbeddingRankerProvenance(kind="TEST_ONLY", model_spec=None))
    ranker.rank.return_value = (value, value) if forgery == "duplicate" else (value,)
    with pytest.raises(InferenceTransferServiceError):
        InferenceTransferApplicationService(sources, ranker).search(command())
    assert not sources.authorizations


def test_revoked_permission_between_ranking_and_result_blocks_everything() -> None:
    a, b = exact_profile("a"), exact_profile("b")
    sources = Sources(corpus(a, b))
    ranker = Mock(provenance=EmbeddingRankerProvenance(kind="TEST_ONLY", model_spec=None))

    def revoke(*_args: Any, **_kwargs: Any) -> tuple[ScoredInferenceTransferProfile, ...]:
        sources.revoked = True
        return (
            ScoredInferenceTransferProfile(InferenceTransferProfilePointer.from_profile(b), 0.9),
        )

    ranker.rank.side_effect = revoke
    with pytest.raises(InferenceTransferServiceError, match="FORBIDDEN"):
        InferenceTransferApplicationService(sources, ranker).search(command())


def test_duplicate_corpus_revision_and_graph_scores_fail_instead_of_latest_substitution() -> None:
    a, b = exact_profile("a"), exact_profile("b")
    with pytest.raises(InferenceTransferServiceError, match=r"DUPLICATE_(PROFILE|SOURCE)"):
        InferenceTransferApplicationService(Sources(corpus(a, a))).search(command())
    with pytest.raises(InferenceTransferServiceError, match="DUPLICATE_GRAPH_SCORE"):
        InferenceTransferApplicationService(
            Sources(
                corpus(
                    a,
                    b,
                    graph_scores=(
                        (b.source_basis.source.item_revision_id, 1),
                        (b.source_basis.source.item_revision_id, 2),
                    ),
                )
            )
        ).search(command())


def test_output_union_is_bounded_and_does_not_evict_graph_channel_with_cosine_scale() -> None:
    a, b, c, d = (exact_profile(seed) for seed in "abcd")
    sources = Sources(
        corpus(a, b, c, d, graph_scores=((d.source_basis.source.item_revision_id, 999),))
    )
    ranker = Mock(provenance=EmbeddingRankerProvenance(kind="TEST_ONLY", model_spec=None))
    ranker.rank.return_value = tuple(
        ScoredInferenceTransferProfile(InferenceTransferProfilePointer.from_profile(p), score)
        for p, score in ((b, 0.99), (c, 0.98))
    )
    result = InferenceTransferApplicationService(sources, ranker).search(command())
    assert len(result.candidates) == 2
    assert result.candidates[1].profile == InferenceTransferProfilePointer.from_profile(d)


def test_out_of_scope_graph_score_cannot_consume_admitted_channel_budget() -> None:
    a, b, canary = (exact_profile(seed) for seed in "abc")
    sources = Sources(
        corpus(
            a,
            b,
            graph_scores=(
                (canary.source_basis.source.item_revision_id, 999),
                (b.source_basis.source.item_revision_id, 800),
            ),
        )
    )
    result = InferenceTransferApplicationService(sources).search(
        command(
            top_k=1, population_scope=InferenceTransferPopulationScope.OCCURRENCE_BACKED_PAST_EXAM
        )
    )
    assert len(result.candidates) == 1
    assert result.candidates[0].profile == InferenceTransferProfilePointer.from_profile(b)
    assert result.candidates[0].provenance == ("GRAPH_LEXICAL",)
    assert sources.authorizations == [sources.corpus]


@pytest.mark.parametrize("missing_report", (False, True))
def test_unranked_or_unreported_source_revocation_blocks_population_counts(
    missing_report: bool,
) -> None:
    a, b, c = (exact_profile(seed) for seed in "abc")
    value = corpus(a, b, c)
    if missing_report:
        value = replace(value, profiles=(a, b), missing_solution_reports=1)
    sources = Sources(value)
    ranker = Mock(provenance=EmbeddingRankerProvenance(kind="TEST_ONLY", model_spec=None))

    def revoke(*_args: Any, **_kwargs: Any) -> tuple[ScoredInferenceTransferProfile, ...]:
        sources.revoked_run_ids.add(c.source_basis.solution_evidence.base_analysis_run_id)
        return (
            ScoredInferenceTransferProfile(InferenceTransferProfilePointer.from_profile(b), 0.9),
        )

    ranker.rank.side_effect = revoke
    with pytest.raises(InferenceTransferServiceError, match="FORBIDDEN"):
        InferenceTransferApplicationService(sources, ranker).search(command(top_k=1))
    assert sources.authorizations == [value]


def test_catalog_reauthorization_rejects_revoked_unreported_source_before_counts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    missing = exact_profile("b")
    value = AdmittedInferenceTransferCorpus((), (), False, 1, corpus(missing).sources)
    adapter = object.__new__(CatalogInferenceTransferSourceAdapter)
    session = MagicMock()
    session_context = MagicMock()
    session_context.__enter__.return_value = session
    adapter.sessions = Mock(return_value=session_context)
    adapter.retrieval = Mock()
    adapter.retrieval.admit_read_only_candidate_pool.return_value = ReadOnlyKnowledgeCandidatePool(
        command().graph_snapshot, (), False
    )
    monkeypatch.setattr(adapter, "_scope", Mock())
    resolution = Mock()
    monkeypatch.setattr(adapter_module, "resolve_solution_evidence_by_base_run", resolution)
    with pytest.raises(InferenceTransferServiceError, match="SOURCE_PIN_MISMATCH"):
        scoped_command = command(
            population_scope=InferenceTransferPopulationScope.OCCURRENCE_BACKED_PAST_EXAM
        )
        adapter.reauthorize(scoped_command, value)
    resolution.assert_not_called()
    scope_mock = cast(Mock, adapter._scope)
    assert scope_mock.call_args.kwargs == {}
    assert scope_mock.call_args.args[1] is scoped_command
    assert (
        scope_mock.call_args.args[1].population_scope
        == InferenceTransferPopulationScope.OCCURRENCE_BACKED_PAST_EXAM
    )


def test_default_population_is_unchanged_and_scope_rejects_untyped_values() -> None:
    assert command().population_scope == InferenceTransferPopulationScope.ALL_ADMITTED_GRAPH_ITEMS
    with pytest.raises(ValueError, match="population scope"):
        command(population_scope="OCCURRENCE_BACKED_PAST_EXAM")


def test_population_cannot_include_unadmitted_sources_without_reports() -> None:
    value = replace(corpus(exact_profile("a")), profiles=(), missing_solution_reports=1)
    with pytest.raises(InferenceTransferServiceError, match="UNADMITTED_SOURCE"):
        InferenceTransferApplicationService(Sources(value)).search(
            command(source_classes=("APPROVED_ITEM",))
        )


def test_admitted_visual_source_subtype_matches_exact_core_solution_source() -> None:
    a, b = exact_profile("a"), exact_profile("b")
    body = b.model_dump(mode="json", exclude={"profile_sha256"})
    body["source_basis"]["source"]["artifact_member"].update(
        materialized_path="source/item-content.json", logical_name="item-content.json"
    )
    b = InferenceTransferProfile.model_validate(body | {"profile_sha256": content_sha256(body)})
    value = corpus(a, b)

    def pointer(member: str, schema: str, media: str = "application/json") -> dict[str, str]:
        return {
            "artifact_id": "artifact_" + "f" * 32,
            "artifact_revision_id": "rev_" + "f" * 32,
            "member_path": member,
            "sha256": sha("f"),
            "schema_ref": "eom://schemas/legacy-assessment/" + schema + "/1.0",
            "media_type": media,
        }

    visual_source = ApprovedPastExamItemKnowledgeSourceV3.model_validate(
        b.source_basis.source.model_dump(mode="json")
        | {
            "extraction_acceptance_id": "itemacceptance_" + "f" * 32,
            "extraction_acceptance_sha256": sha("f"),
            "extraction_acceptance_artifact": pointer(
                "acceptance.json", "legacy-item-extraction-acceptance"
            ),
            "extraction_result_id": "itemextractresult_" + "f" * 32,
            "extraction_result_sha256": sha("f"),
            "extraction_result_artifact": pointer("result.json", "legacy-item-extraction-result"),
            "item_proposal_id": "itemproposal_" + "f" * 32,
            "item_number": 1,
            "bundle": {
                "assessment_source_bundle_id": "assessbundle_" + "f" * 32,
                "assessment_source_bundle_revision_id": "assessbundlerev_" + "f" * 32,
                "bundle_manifest_sha256": sha("f"),
            },
            "layout_observation": {
                "assessment_layout_observation_id": "assessmentlayout_" + "f" * 32,
                "artifact": pointer("layout.json", "assessment-layout-observation"),
                "workspace_relative_path": "source/layout-observation.json",
                "observation_sha256": sha("f"),
            },
            "page_inputs": [
                {
                    "page_input_id": "assessmentpage_" + "f" * 32,
                    "source_role": "PROBLEM_DOCUMENT",
                    "physical_page": 1,
                    "source": pointer("sources/problem.pdf", "pdf-source", "application/pdf"),
                    "image": pointer("pages/problem-000001.png", "page-image", "image/png"),
                    "workspace_relative_path": "source/pages/assessmentpage_" + "f" * 32 + ".png",
                    "width_px": 1200,
                    "height_px": 1800,
                }
            ],
            "page_image_count": 1,
        }
    )
    value = replace(
        value,
        sources=(
            value.sources[0],
            replace(value.sources[1], source=visual_source),
        ),
    )
    sources = Sources(value)
    ranker = Mock(provenance=EmbeddingRankerProvenance(kind="TEST_ONLY", model_spec=None))
    ranker.rank.return_value = (
        ScoredInferenceTransferProfile(InferenceTransferProfilePointer.from_profile(b), 0.9),
    )
    result = InferenceTransferApplicationService(sources, ranker).search(command())
    assert len(result.candidates) == 1
    assert sources.authorizations[0].sources[1].source is visual_source


def test_authority_uses_actual_actor_permissions_and_roles_not_injected_claims(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = object.__new__(CatalogInferenceTransferSourceAdapter)
    actor = SimpleNamespace(status="ACTIVE", deleted_at=None, must_change_password=False)
    session = Mock()
    session.get.return_value = actor
    permissions = frozenset(
        {
            PermissionKey.ITEM_READ,
            PermissionKey.KNOWLEDGE_GRAPH_RETRIEVE,
            PermissionKey.KNOWLEDGE_ANALYSIS_READ,
            PermissionKey.CONTENT_INTAKE_READ,
        }
    )
    monkeypatch.setattr(adapter_module, "effective_permissions", Mock(return_value=permissions))
    monkeypatch.setattr(
        adapter_module,
        "active_role_assignments",
        Mock(return_value=((None, SimpleNamespace(role_key="REVIEWER")),)),
    )
    adapter.retrieval = Mock()
    adapter.retrieval.resolve_access_policy.return_value = SimpleNamespace(
        allowed_requester_roles=("ADMIN", "REVIEWER"),
        answer_bearing_roles=("REVIEWER",),
        maximum_budget=EvidenceBudget(
            max_documents=8,
            max_item_revisions=8,
            max_graph_nodes=256,
            max_claims=32,
            max_context_tokens=8000,
        ),
    )
    scoped_command = command(
        population_scope=InferenceTransferPopulationScope.OCCURRENCE_BACKED_PAST_EXAM
    )
    scope = adapter._scope(cast(Session, session), scoped_command)
    assert scope.requester_role == "REVIEWER" and scope.requested_by == command().actor_id
    assert scope.requester_permission_keys == tuple(
        sorted(permission.value for permission in permissions)
    )
    assert "WORKER" not in scope.requester_permission_keys
    assert scope.population_scope == scoped_command.population_scope
    monkeypatch.setattr(adapter_module, "effective_permissions", Mock(return_value=frozenset()))
    with pytest.raises(InferenceTransferServiceError, match="FORBIDDEN"):
        adapter._scope(cast(Session, session), scoped_command)


@pytest.mark.parametrize(
    "actor_change",
    ({"status": "DISABLED"}, {"deleted_at": "2026-01-01"}, {"must_change_password": True}),
)
def test_inactive_deleted_and_password_change_actors_are_denied_before_retrieval(
    actor_change: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    adapter = object.__new__(CatalogInferenceTransferSourceAdapter)
    actor = {"status": "ACTIVE", "deleted_at": None, "must_change_password": False} | actor_change
    session = Mock()
    session.get.return_value = SimpleNamespace(**actor)
    monkeypatch.setattr(
        adapter_module, "effective_permissions", Mock(return_value=frozenset(PermissionKey))
    )
    adapter.retrieval = Mock()
    with pytest.raises(InferenceTransferServiceError, match="FORBIDDEN"):
        adapter._scope(cast(Session, session), command())
    adapter.retrieval.resolve_access_policy.assert_not_called()


def test_public_bounded_channel_union_preserves_legacy_order_and_deduplicates_views() -> None:
    from eom_catalog_service.inference_transfer_service import bounded_profile_channel_union

    values = tuple(
        InferenceTransferProfilePointer.from_profile(exact_profile(seed)) for seed in "abcd"
    )
    assert (
        bounded_profile_channel_union((values[:2], (values[1], values[2])), top_k=3) == values[:3]
    )
    assert bounded_profile_channel_union(
        (values[:2], values[2:], (values[0],), (values[3],)), top_k=4
    ) == (values[0], values[2], values[3], values[1])
    assert bounded_profile_channel_union((), top_k=1) == ()
    with pytest.raises(ValueError):
        bounded_profile_channel_union(((),) * 5, top_k=1)
