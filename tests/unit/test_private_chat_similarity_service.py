"""Synthetic owned-question composition; no live identity, DB, ML or native admission."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest
from eom_catalog_contracts import (
    PrivateChatSimilarityContext,
    PrivateChatSimilarityRequest,
    validate_private_chat_query_execution,
)
from eom_catalog_contracts.embedding_reference_query import raw_similarity_contract_value
from eom_catalog_contracts.inference_transfer_embedding import parse_embedding_binding
from eom_catalog_contracts.private_chat_similarity import (
    PRIVATE_CHAT_LIMITATION_ORDER,
    PrivateChatViewCoverage,
)
from eom_catalog_contracts.similarity_context import (
    SimilarityViewCoverage,
    parse_similarity_context,
)
from eom_catalog_contracts.validation import CATALOG_SCHEMA_RESOURCES, load_schema
from eom_catalog_service.embedding_encoder_adapter import encode_private_chat_query
from eom_catalog_service.embedding_registry_ports import (
    AuthorizedEmbeddingReadProfile,
    EmbeddingRegistryCaller,
)
from eom_catalog_service.private_chat_similarity_ports import (
    PreparedPrivateChatSimilarity,
    PrivateChatQueryUnavailable,
    VerifiedPrivateChatQueryRead,
)
from eom_catalog_service.private_chat_similarity_service import (
    PrivateChatSimilarityApplicationService,
)
from eom_catalog_service.similarity_context_ports import (
    PreparedSimilaritySource,
    SimilarityContextReadError,
)
from eom_identifiers import canonical_json_bytes, content_sha256, sha256_bytes
from eom_orchestrator.general_chat_similarity_basis import (
    PreparedPrivateChatQuery,
    build_private_chat_query_encoding_input,
)
from eom_protocol.artifact_members import ArtifactMemberPointer
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError as SchemaError

from tests.unit.inference_transfer_embedding_fixtures import seal, shard_pointer
from tests.unit.inference_transfer_fixtures import sha
from tests.unit.test_embedding_private_chat_query import backend, private_context_request
from tests.unit.test_private_chat_query_basis import TEXT, basis
from tests.unit.test_similarity_context_service import CALLER
from tests.unit.test_similarity_context_service import case as reference_case


class Owner:
    def __init__(self, prepared, query, reads):
        self.prepared, self.query, self.reads = prepared, query, reads
        self.calls = []
        self.denial = None

    def prepare_private_chat_similarity(self, caller, request):
        assert caller == CALLER
        self.calls.append("prepare")
        return self.prepared

    def resolve_private_chat_query(self, caller, request, prepared):
        self.calls.append("query")
        return self.query

    def read_private_chat_similarity_index(self, caller, request, prepared):
        self.calls.append("index")
        return self.reads

    def reauthorize_private_chat_similarity(self, caller, request, prepared):
        self.calls.append("reauthorize")
        if self.denial:
            raise SimilarityContextReadError(self.denial)


def case():
    old, sources, _ = reference_case()
    request = PrivateChatSimilarityRequest.model_validate(
        seal(
            private_context_request(old.views[0]).model_dump(mode="json")
            | {
                "graph_snapshot": old.graph_snapshot.model_dump(mode="json"),
                "policy_revision_id": old.policy_revision_id,
                "policy_sha256": old.policy_sha256,
                "source_classes": old.source_classes,
            },
            "request_sha256",
        )
    )
    native = build_private_chat_query_encoding_input(
        PreparedPrivateChatQuery(basis(), TEXT),
        request,
        job_id="job_" + "7" * 32,
        query_request_id="embeddingquery_" + "8" * 32,
        batch_size=4,
        threads=1,
    )
    encoded = encode_private_chat_query(native, backend(native))
    result = encoded.result
    member = ArtifactMemberPointer(
        artifact_id="artifact_" + "e" * 32,
        artifact_revision_id="rev_" + "e" * 32,
        member_path="result.json",
        media_type="application/json",
        schema_ref="eom://schemas/knowledge/embedding-private-chat-query-result/1.0",
        sha256=content_sha256(result),
    )
    query = VerifiedPrivateChatQueryRead(
        native,
        result,
        member,
        shard_pointer(result.shard, "e"),
        encoded.vectors,
    )
    prepared = PreparedPrivateChatSimilarity(
        request.request_sha256, basis(), TEXT, sources.prepared.sources
    )
    return request, Owner(prepared, query, (sources.reads[0],))


def compose(request, owner):
    return PrivateChatSimilarityApplicationService(owner).compose(CALLER, request)


def test_schema_mirror_and_old_result_rejection():
    resource = CATALOG_SCHEMA_RESOURCES["system-rag-private-chat-similarity"]
    root = Path(__file__).resolve().parents[2]
    raw = (root / resource.canonical_path).read_bytes()
    assert (
        raw
        == (
            root / "packages/catalog_contracts/eom_catalog_contracts" / resource.resource_path
        ).read_bytes()
    )
    assert (
        sha256_bytes(raw)
        == resource.sha256
        == "sha256:884bc8b9d873746ffea5cfb5042859a61eaa5942a8f488f4fc3d2d76db14d586"
    )
    Draft202012Validator.check_schema(load_schema("system-rag-private-chat-similarity"))
    request, owner = case()
    context = compose(request, owner)
    with pytest.raises((ValueError, SchemaError)):
        parse_similarity_context(context)


def test_private_query_scores_all_sources_without_false_self_exclusion_or_graph_evidence():
    request, owner = case()
    result = compose(request, owner)
    assert result.status == "READY", result
    assert (
        result.population.authorized_source_count == result.population.accepted_profile_count == 3
    )
    assert result.population.views[0].scored_count == 3
    assert len(result.candidates) == 3  # Approved-reference mode would exclude source a.
    assert result.candidates[0].source.item_revision_id.endswith("a" * 32)
    assert [v.source.item_revision_id[-1] for v in result.candidates] == ["a", "c", "b"]
    assert result.limitations == PRIVATE_CHAT_LIMITATION_ORDER[:3]
    assert all(v.explanation is None and len(v.observations) == 1 for v in result.candidates)
    assert "graph_evidence" not in result.model_dump()
    assert TEXT not in canonical_json_bytes(result).decode()
    assert owner.calls == ["prepare", "query", "index", "reauthorize"]
    validate_private_chat_query_execution(
        result,
        owner.query.request,
        owner.query.result,
        owner.query.result_member,
        owner.query.shard_member,
    )
    assert canonical_json_bytes(result) == canonical_json_bytes(compose(request, owner))


def test_private_parent_is_derived_not_an_opaque_hash_or_a_relabelled_approved_anchor():
    request, owner = case()
    assert owner.query.request.context_request_sha256 == request.request_sha256
    assert owner.query.request.basis == request.query_basis
    other = PrivateChatSimilarityRequest.model_validate(
        seal(
            request.model_dump(mode="json")
            | {
                "query_basis": seal(
                    request.query_basis.model_dump(mode="json")
                    | {
                        "turn_id": "chatturn_" + "f" * 32,
                    },
                    "basis_sha256",
                ),
            },
            "request_sha256",
        )
    )
    with pytest.raises(ValueError, match="BASIS_MISMATCH"):
        build_private_chat_query_encoding_input(
            PreparedPrivateChatQuery(basis(), TEXT),
            other,
            job_id=owner.query.request.job_id,
            query_request_id=owner.query.request.query_request_id,
            batch_size=4,
            threads=1,
        )


@pytest.mark.parametrize("fault", ["index_absent", "query_absent", "overflow"])
def test_unavailability_does_not_become_graph_evidence_or_silently_run_an_encoder(fault):
    request, owner = case()
    if fault == "index_absent":
        request = PrivateChatSimilarityRequest.model_validate(
            seal(
                request.model_dump(mode="json")
                | {
                    "views": [request.views[0].model_dump(mode="json") | {"index": None}],
                },
                "request_sha256",
            )
        )
        owner.prepared = replace(owner.prepared, request_sha256=request.request_sha256)
    else:
        owner.query = PrivateChatQueryUnavailable(
            "INPUT_OVERFLOW" if fault == "overflow" else "QUERY_NOT_OFFERED"
        )
    result = compose(request, owner)
    assert result.status == "UNAVAILABLE", result
    assert result.query_execution is None and result.candidates == ()
    assert result.population.views[0].available_binding_count is None
    assert result.population.views[0].scored_count == 0
    assert owner.calls == (
        ["prepare", "reauthorize"]
        if fault == "index_absent"
        else ["prepare", "query", "reauthorize"]
    )


@pytest.mark.parametrize("fault", ["missing_report", "missing_binding", "empty", "truncated"])
def test_partial_coverage_has_separate_denominators_and_no_invented_vectors(fault):
    request, owner = case()
    read = owner.reads[0]
    if fault == "missing_report":
        owner.prepared = replace(
            owner.prepared,
            sources=(
                replace(owner.prepared.sources[0], profile=None, solution_evidence=None),
                *owner.prepared.sources[1:],
            ),
        )
        read = replace(read, profiles=read.profiles[1:], bindings=read.bindings[1:])
    elif fault == "missing_binding":
        read = replace(read, bindings=read.bindings[1:])
    elif fault == "empty":
        read = replace(read, bindings=(), numerical_rows=())
    else:
        owner.prepared = replace(owner.prepared, truncated=True)
    owner.reads = (read,)
    result = compose(request, owner)
    assert result.status == ("EMPTY" if fault == "empty" else "PARTIAL"), result
    assert result.population.authorized_source_count == 3
    assert result.population.accepted_profile_count == (2 if fault == "missing_report" else 3)
    assert result.population.missing_report_count == (1 if fault == "missing_report" else 0)
    assert (
        result.population.views[0].missing_view_count
        == {"missing_report": 0, "missing_binding": 1, "empty": 3, "truncated": 0}[fault]
    )


@pytest.mark.parametrize(
    "fault", ["text", "basis", "request", "source_duplicate", "profile_duplicate"]
)
def test_stale_or_duplicate_preparation_fails_before_query_or_index(fault):
    request, owner = case()
    if fault == "text":
        owner.prepared = replace(owner.prepared, query_text=TEXT + " changed")
    elif fault == "basis":
        owner.prepared = replace(
            owner.prepared,
            query_basis=basis().model_copy(update={"turn_id": "chatturn_" + "f" * 32}),
        )
    elif fault == "request":
        owner.prepared = replace(owner.prepared, request_sha256=sha("f"))
    elif fault == "source_duplicate":
        owner.prepared = replace(owner.prepared, sources=owner.prepared.sources * 2)
    else:
        source = replace(owner.prepared.sources[1], profile=owner.prepared.sources[0].profile)
        owner.prepared = replace(owner.prepared, sources=(owner.prepared.sources[0], source))
    result = compose(request, owner)
    assert result.status == "FAILED" and result.error_code == "SOURCE_POINTER_INVALID"
    assert result.population is None and result.candidates == () and result.query_execution is None
    assert owner.calls == ["prepare"]


@pytest.mark.parametrize(
    "fault",
    ["native_parent", "binary", "result_member", "shard_member", "old_schema", "bogus_outcome"],
)
def test_query_closure_and_protocol_confusion_fail_without_candidate_disclosure(fault):
    request, owner = case()
    query = owner.query
    if fault == "native_parent":
        query = replace(
            query, request=query.request.model_copy(update={"context_request_sha256": sha("f")})
        )
    elif fault == "binary":
        query = replace(query, binary=query.binary[:-1])
    elif fault == "result_member":
        query = replace(
            query, result_member=query.result_member.model_copy(update={"sha256": sha("f")})
        )
    elif fault == "shard_member":
        query = replace(
            query,
            shard_member=query.shard_member.model_copy(
                update={"artifact_revision_id": "rev_" + "f" * 32}
            ),
        )
    elif fault == "old_schema":
        query = replace(
            query,
            result=query.result.model_copy(
                update={"schema_version": "embedding-reference-query-result/1.0"}
            ),
        )
    else:
        query = object()
    owner.query = query
    result = compose(request, owner)
    assert result.status == "FAILED" and result.error_code == "QUERY_RESULT_INVALID", result
    assert result.population is None and result.query_execution is None and result.candidates == ()
    assert "reauthorize" not in owner.calls


@pytest.mark.parametrize(
    "fault", ["scope", "selection", "binding_duplicate", "row_duplicate", "missing_read"]
)
def test_common_document_validator_rejects_foreign_or_duplicated_reads(fault):
    request, owner = case()
    read = owner.reads[0]
    if fault == "scope":
        read = replace(
            read,
            intent=replace(read.intent, scope=replace(read.intent.scope, policy_sha256=sha("f"))),
        )
    elif fault == "selection":
        read = replace(
            read,
            intent=replace(
                read.intent, selection=request.views[0].model_copy(update={"index": None})
            ),
        )
    elif fault == "binding_duplicate":
        read = replace(read, bindings=read.bindings * 2)
    elif fault == "row_duplicate":
        read = replace(read, numerical_rows=read.numerical_rows * 2)
    owner.reads = () if fault == "missing_read" else (read,)
    result = compose(request, owner)
    assert result.status == "FAILED" and result.error_code == "INDEX_POINTER_INVALID", result
    assert result.population is None and result.query_execution is None and result.candidates == ()


@pytest.mark.parametrize(
    "code", ["SOURCE_ACCESS_DENIED", "SOURCE_REVOKED", "AUTHORITY_UNAVAILABLE"]
)
def test_last_moment_owner_or_public_source_revocation_discards_all_observations(code):
    request, owner = case()
    owner.denial = code
    result = compose(request, owner)
    assert result.status == "FAILED" and result.error_code == code
    assert result.population is None and result.query_execution is None and result.candidates == ()
    assert result.limitations == PRIVATE_CHAT_LIMITATION_ORDER[:3]
    assert owner.calls[-1] == "reauthorize"


@pytest.mark.parametrize(
    "caller", [None, object(), EmbeddingRegistryCaller("ADMIN"), EmbeddingRegistryCaller(None)]
)
def test_missing_or_model_supplied_authority_is_not_a_grant(caller):
    request, owner = case()
    result = PrivateChatSimilarityApplicationService(owner).compose(caller, request)
    assert result.status == "FAILED" and result.error_code == "AUTHORITY_UNAVAILABLE"
    assert owner.calls == []


def test_missing_owner_and_unexpected_owner_failure_are_safe_not_implicit_defaults(monkeypatch):
    request, owner = case()
    assert (
        PrivateChatSimilarityApplicationService(None).compose(CALLER, request).error_code
        == "AUTHORITY_UNAVAILABLE"
    )

    def failed(*args):
        raise RuntimeError(TEXT)

    monkeypatch.setattr(owner, "prepare_private_chat_similarity", failed)
    result = compose(request, owner)
    assert result.status == "FAILED" and TEXT not in canonical_json_bytes(result).decode()


@pytest.mark.parametrize(
    "field", ["actor_id", "anchor", "topics", "unit_ids", "query_text", "graph_evidence"]
)
def test_wire_request_has_no_authority_fake_anchor_private_text_or_unimplemented_filters(field):
    request = private_context_request()
    with pytest.raises((ValueError, SchemaError)):
        PrivateChatSimilarityRequest.model_validate(
            seal(request.model_dump(mode="json") | {field: "not allowed"}, "request_sha256")
        )


def test_private_coverage_allows_1024_without_widening_approved_reference_limit():
    body = dict(
        view="CONTENT_ONLY",
        status="READY",
        available_binding_count=1024,
        binding_set_sha256=sha("a"),
        scored_count=1024,
        missing_view_count=0,
        reason=None,
    )
    assert PrivateChatViewCoverage.model_validate(body).scored_count == 1024
    with pytest.raises(ValueError):
        SimilarityViewCoverage.model_validate(body)


def test_all_1024_synthetic_bindings_are_scored_with_stable_ties_and_deduplicated_rows():
    # These fabricated owner-local values test bounded composition, NOT source admission.
    request, owner = case()
    original = owner.reads[0]
    template = original.bindings[0]
    sources, profiles, bindings = [], [], []
    for ordinal in range(1024):
        seed = f"{ordinal:032x}"
        source = template.source.model_copy(
            update={
                "item_id": "item_" + seed,
                "item_revision_id": "itemrev_" + seed,
            }
        )
        profile = template.profile.model_copy(
            update={
                "profile_id": "inferenceprofile_" + seed,
                "profile_revision_id": "inferenceprofilerev_" + seed,
                "profile_sha256": content_sha256({"synthetic": ordinal}),
            }
        )
        sources.append(PreparedSimilaritySource(source, profile, template.solution_evidence))
        profiles.append(AuthorizedEmbeddingReadProfile(source.item_revision_id, profile))
        bindings.append(
            parse_embedding_binding(
                seal(
                    template.model_dump(mode="json")
                    | {
                        "source": source.model_dump(mode="json"),
                        "profile": profile.model_dump(mode="json"),
                    },
                    "binding_sha256",
                )
            )
        )
    owner.prepared = replace(owner.prepared, sources=tuple(sources))
    rows = tuple(v for v in original.numerical_rows if v.row.encoding == template.encoding)
    assert len(rows) == 1  # Same immutable text encoding can support distinct bindings.
    owner.reads = (
        replace(
            original,
            sources=tuple(v.source for v in sources),
            profiles=tuple(profiles),
            bindings=tuple(bindings),
            numerical_rows=rows,
        ),
    )
    result = compose(request, owner)
    assert result.status == "READY", result
    assert (
        result.population.authorized_source_count
        == result.population.accepted_profile_count
        == 1024
    )
    assert result.population.views[0].scored_count == 1024
    assert len(result.candidates) == request.top_k
    assert [v.profile for v in result.candidates] == [v.profile for v in sources[: request.top_k]]


@pytest.mark.parametrize(
    "fault", ["status", "candidate_count", "fake_graph", "copied_extra", "limitations", "hash"]
)
def test_context_model_rejects_fabricated_or_incomplete_observations(fault):
    request, owner = case()
    result = compose(request, owner)
    body = raw_similarity_contract_value(result)
    if fault == "status":
        body["status"] = "PARTIAL"
    elif fault == "candidate_count":
        body["candidates"].pop()
    elif fault == "fake_graph":
        body["graph_evidence"] = owner.query.result_member.model_dump(mode="json")
    elif fault == "copied_extra":
        body = result.model_copy(update={"authority": "ADMIN"})
    elif fault == "limitations":
        body["limitations"] = []
    else:
        body["context_sha256"] = sha("f")
    if fault not in {"hash", "copied_extra"}:
        body = seal(body, "context_sha256")
    with pytest.raises((ValueError, SchemaError)):
        PrivateChatSimilarityContext.model_validate(body)
