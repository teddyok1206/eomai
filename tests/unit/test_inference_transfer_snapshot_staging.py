"""Fake supported-owner staging checks; never live authentication or model evidence."""

from __future__ import annotations

import ast
from dataclasses import replace
from typing import Any

import pytest
from eom_catalog_contracts.inference_transfer_experiment import (
    ExperimentBudget,
    SuppliedGraphBaseline,
    profile_set_sha256,
)
from eom_catalog_contracts.inference_transfer_snapshot import (
    InferenceTransferSnapshotAuthorizeResult,
    InferenceTransferSnapshotPrepareResult,
    InferenceTransferSnapshotReadRequest,
    InferenceTransferSnapshotReadResult,
    InferenceTransferSnapshotRecord,
    InferenceTransferSnapshotRequest,
    InferenceTransferSnapshotResult,
)
from eom_catalog_contracts.item_inference_transfer import InferenceTransferProfilePointer
from eom_identifiers import canonical_json_bytes, content_sha256
from eom_orchestrator import inference_transfer_snapshot_staging as staging
from eom_orchestrator.inference_transfer_snapshot_staging import (
    AuthenticatedSnapshotActor,
    SnapshotExperimentStageCommand,
    SnapshotReadFailure,
    SnapshotStagingError,
    reauthorize_staged_experiment,
    stage_snapshot_experiment,
)

from tests.unit.inference_transfer_experiment_fixtures import experiment_request
from tests.unit.inference_transfer_fixtures import profile
from tests.unit.inference_transfer_snapshot_fixtures import (
    hashed,
    snapshot_header,
    snapshot_prepare,
    snapshot_prepare_result,
    snapshot_records,
    snapshot_v3_record,
)

ACTOR = AuthenticatedSnapshotActor("synthetic-operator")


class Owner:
    def __init__(
        self,
        records: tuple[InferenceTransferSnapshotRecord, ...] | None = None,
        *,
        query_seeds: tuple[str, ...] = ("a",),
        width: int = 64,
    ) -> None:
        self.records = snapshot_records() if records is None else records
        self.prepare = snapshot_prepare(
            query_item_revision_ids=tuple("itemrev_" + seed * 32 for seed in query_seeds),
            chunk_budget={"max_entries": width, "max_encoded_bytes": 3 * 1024**2},
        )
        self.prepared = snapshot_prepare_result(
            self.records, header=snapshot_header(self.records, prepare=self.prepare)
        )
        self.calls: list[tuple[str, InferenceTransferSnapshotRequest]] = []
        self.failure: SnapshotReadFailure | RuntimeError | None = None
        self.failure_phase = "READ"
        self.maximum_records = 64
        self.transform: Any = None

    def execute(
        self, actor_id: str, request: InferenceTransferSnapshotRequest
    ) -> InferenceTransferSnapshotResult:
        self.calls.append((actor_id, request))
        if request.phase == self.failure_phase and self.failure is not None:
            raise self.failure
        if request.phase == "PREPARE":
            result = self.prepared
        elif isinstance(request, InferenceTransferSnapshotReadRequest):
            if len(request.selected_index_entries) > self.maximum_records:
                raise SnapshotReadFailure("INFERENCE_TRANSFER_SNAPSHOT_BUDGET_EXCEEDED")
            by_base = {row.index_entry.base_analysis_run_id: row for row in self.records}
            selected = tuple(
                by_base[row.base_analysis_run_id] for row in request.selected_index_entries
            )
            eligible = tuple(
                row.index_entry.profile
                for row in self.records
                if row.index_entry.profile is not None
            )
            baselines = tuple(
                hashed(
                    SuppliedGraphBaseline,
                    "result_sha256",
                    query=row.index_entry.profile,
                    command_sha256=content_sha256("synthetic owner command"),
                    ordered_candidates=tuple(p for p in eligible if p != row.index_entry.profile),
                )
                for row in selected
                if row.index_entry.profile is not None
                and row.source.item_revision_id in request.header.prepare.query_item_revision_ids
            )
            result = hashed(
                InferenceTransferSnapshotReadResult,
                "result_sha256",
                header_sha256=request.header.header_sha256,
                read_sha256=request.read_sha256,
                records=selected,
                baselines=baselines,
                limitations=("Synthetic owner: no real authorization evidence.",),
            )
        else:
            result = hashed(
                InferenceTransferSnapshotAuthorizeResult,
                "result_sha256",
                header_sha256=request.header.header_sha256,
                authorization_sha256=request.authorization_sha256,
                source_count=request.header.source_count,
                profile_count=request.header.profile_count,
                missing_report_count=request.header.missing_report_count,
                staged_entry_set_sha256=request.staged_entry_set_sha256,
                staged_baseline_set_sha256=request.staged_baseline_set_sha256,
            )
        return result if self.transform is None else self.transform(request, result)


def command(owner: Owner, **budget: Any) -> SnapshotExperimentStageCommand:
    example = experiment_request()
    return SnapshotExperimentStageCommand(
        prepare_request=owner.prepare,
        experiment_id=example.experiment_id,
        experiment_revision_id=example.experiment_revision_id,
        model_spec=example.model_spec,
        budget=ExperimentBudget(**({"minimum_common_candidates": 1} | budget)),
    )


def test_complete_exact_assembly_is_deterministic_and_no_initial_authorization_cached():
    owner = Owner(width=2)
    staged = stage_snapshot_experiment(ACTOR, command(owner), owner)
    replay = stage_snapshot_experiment(ACTOR, command(owner), owner)
    assert staged == replay
    assert staged.header == owner.prepared.header and staged.index == owner.prepared.index
    assert [req.phase for _, req in owner.calls] == ["PREPARE", "READ", "READ"] * 2
    assert all(actor_id == ACTOR.actor_id for actor_id, _ in owner.calls)
    request = staged.request
    assert request.scope.actor_id == ACTOR.actor_id
    assert request.scope.data_provenance == "AUTHORIZED_CORPUS_SNAPSHOT"
    assert request.scope.population_sha256 == staged.header.population_sha256
    assert request.scope.eligible_profile_set_sha256 == profile_set_sha256(
        request.queries
        + tuple(
            row.index_entry.profile
            for row in owner.records[1:]
            if row.index_entry.profile is not None
        )
    )
    assert len(request.entries) == 3 and len(request.scope.population_sources) == 3
    assert len(request.baselines) == 1
    assert staged.accumulated_received_bytes > len(
        canonical_json_bytes(owner.prepared.model_dump(mode="json"))
    )
    assert (
        len(canonical_json_bytes(request.model_dump(mode="json")))
        <= request.budget.maximum_input_bytes
    )


def test_missing_report_remains_in_denominator_not_as_encodable_entry():
    owner = Owner(snapshot_records(missing_seed="b"), width=1)
    staged = stage_snapshot_experiment(ACTOR, command(owner), owner)
    assert (
        staged.header.source_count,
        staged.header.profile_count,
        staged.header.missing_report_count,
    ) == (3, 2, 1)
    assert len(staged.request.scope.population_sources) == 3
    assert len(staged.request.entries) == 2
    authorized = reauthorize_staged_experiment(ACTOR, staged, owner)
    assert (authorized.source_count, authorized.profile_count, authorized.missing_report_count) == (
        3,
        2,
        1,
    )


@pytest.mark.parametrize("queries,missing", (((), None), (("b",), "b")))
def test_no_automatic_query_selection_or_missing_report_query(queries, missing):
    owner = Owner(snapshot_records(missing_seed=missing), query_seeds=queries)
    with pytest.raises(SnapshotStagingError, match="QUERY_UNAVAILABLE"):
        stage_snapshot_experiment(ACTOR, command(owner), owner)
    assert [request.phase for _, request in owner.calls] == ["PREPARE"]


def test_multiple_requested_queries_and_baselines_are_exact_across_chunks():
    owner = Owner(query_seeds=("a", "c"), width=1)
    staged = stage_snapshot_experiment(ACTOR, command(owner), owner)
    assert staged.request.queries == tuple(owner.records[n].index_entry.profile for n in (0, 2))
    assert tuple(row.query for row in staged.request.baselines) == staged.request.queries


def test_unmaterialized_baseline_is_explicit_not_a_fabricated_empty_result():
    owner = Owner()

    def unavailable(request, result):
        if request.phase != "READ":
            return result
        return hashed(
            InferenceTransferSnapshotReadResult,
            "result_sha256",
            **(
                result.model_dump(mode="json", exclude={"result_sha256"})
                | {"baselines": (), "limitations": ("Official baseline unavailable.",)}
            ),
        )

    owner.transform = unavailable
    staged = stage_snapshot_experiment(ACTOR, command(owner), owner)
    assert staged.request.baselines == ()
    assert staged.limitations == ("Official baseline unavailable.",)


def test_baseline_candidate_from_outside_complete_index_is_rejected():
    owner = Owner()
    foreign = InferenceTransferProfilePointer.from_profile(profile("d"))

    def inject_candidate(request, result):
        if request.phase != "READ":
            return result
        baseline = hashed(
            SuppliedGraphBaseline,
            "result_sha256",
            **(
                result.baselines[0].model_dump(mode="json", exclude={"result_sha256"})
                | {"ordered_candidates": (foreign,)}
            ),
        )
        return hashed(
            InferenceTransferSnapshotReadResult,
            "result_sha256",
            **(
                result.model_dump(mode="json", exclude={"result_sha256"})
                | {"baselines": (baseline,)}
            ),
        )

    owner.transform = inject_candidate
    with pytest.raises(SnapshotStagingError):
        stage_snapshot_experiment(ACTOR, command(owner), owner)
    assert len(owner.calls) == 2


def test_full_v3_source_not_replaced_by_profile_core_v2():
    owner = Owner((snapshot_v3_record(), *snapshot_records()[1:]))
    staged = stage_snapshot_experiment(ACTOR, command(owner), owner)
    assert staged.request.scope.population_sources[0] == owner.records[0].source
    assert staged.request.entries[0].profile.source_basis.source != owner.records[0].source
    assert reauthorize_staged_experiment(ACTOR, staged, owner).source_count == 3


def test_only_explicit_read_budget_error_splits_same_chunk_in_order():
    owner = Owner()
    owner.maximum_records = 1
    staged = stage_snapshot_experiment(ACTOR, command(owner), owner)
    reads = [req for _, req in owner.calls if isinstance(req, InferenceTransferSnapshotReadRequest)]
    assert [
        tuple(row.base_analysis_run_id[-1] for row in req.selected_index_entries) for req in reads
    ] == [("a", "b", "c"), ("a",), ("b", "c"), ("b",), ("c",)]
    assert len(staged.request.entries) == 3
    assert all(req.header == owner.prepared.header for req in reads)


def test_single_record_budget_error_fails_without_truncation_or_retry():
    owner = Owner(width=1)
    owner.maximum_records = 0
    with pytest.raises(SnapshotStagingError, match="BUDGET_EXCEEDED"):
        stage_snapshot_experiment(ACTOR, command(owner), owner)
    assert len(owner.calls) == 2


@pytest.mark.parametrize(
    "code",
    (
        "INFERENCE_TRANSFER_FORBIDDEN",
        "INFERENCE_TRANSFER_SNAPSHOT_CHANGED",
        "INFERENCE_TRANSFER_SNAPSHOT_UNAVAILABLE",
        "secret-untrusted-failure-details",
    ),
)
def test_permission_transport_revocation_unknown_failure_not_implicitly_retried(code):
    owner = Owner()
    owner.failure = SnapshotReadFailure(code)
    with pytest.raises(SnapshotReadFailure) as error:
        stage_snapshot_experiment(ACTOR, command(owner), owner)
    assert len(owner.calls) == 2
    assert "secret" not in str(error.value)


def test_unexpected_port_error_is_sanitized_and_not_retried():
    owner = Owner()
    owner.failure = RuntimeError("private source content must not escape")
    with pytest.raises(SnapshotStagingError, match="UNAVAILABLE") as error:
        stage_snapshot_experiment(ACTOR, command(owner), owner)
    assert len(owner.calls) == 2 and "private" not in str(error.value)


@pytest.mark.parametrize(
    "kind", ("foreign_actor", "foreign_prepare", "wrong_phase", "bad_hash", "untyped")
)
def test_prepare_reply_exact_context_and_schema_are_required(kind):
    owner = Owner()

    def transform(request, result):
        if kind == "foreign_actor":
            header = hashed(
                type(owner.prepared.header),
                "header_sha256",
                **(
                    owner.prepared.header.model_dump(mode="json", exclude={"header_sha256"})
                    | {"actor_id": "foreign-operator"}
                ),
            )
            return hashed(
                InferenceTransferSnapshotPrepareResult,
                "result_sha256",
                header=header,
                index=owner.prepared.index,
            )
        if kind == "foreign_prepare":
            header = snapshot_header(
                owner.records,
                prepare=snapshot_prepare(query_item_revision_ids=("itemrev_" + "b" * 32,)),
            )
            return snapshot_prepare_result(owner.records, header=header)
        if kind == "wrong_phase":
            return hashed(
                InferenceTransferSnapshotAuthorizeResult,
                "result_sha256",
                header_sha256=owner.prepared.header.header_sha256,
                authorization_sha256=content_sha256("unrelated"),
                source_count=0,
                profile_count=0,
                missing_report_count=0,
                staged_entry_set_sha256=content_sha256([]),
                staged_baseline_set_sha256=content_sha256([]),
            )
        if kind == "bad_hash":
            return result.model_copy(update={"result_sha256": content_sha256("forged")})
        return None

    owner.transform = transform
    with pytest.raises(SnapshotStagingError):
        stage_snapshot_experiment(ACTOR, command(owner), owner)
    assert len(owner.calls) == 1


@pytest.mark.parametrize(
    "kind", ("omit", "foreign_chunk", "read_hash", "body_hash", "wrong_phase", "duplicate")
)
def test_read_requires_complete_ordered_exact_chunk_and_hashes(kind):
    owner = Owner(width=2)

    def transform(request, result):
        if request.phase != "READ":
            return result
        assert isinstance(result, InferenceTransferSnapshotReadResult)
        body = result.model_dump(mode="json", exclude={"result_sha256"})
        if kind == "omit":
            body["records"] = (result.records[0],)
        elif kind == "foreign_chunk":
            body["records"] = (owner.records[2],)
            body["baselines"] = ()
        elif kind == "read_hash":
            body["read_sha256"] = content_sha256("foreign read")
        elif kind == "body_hash":
            return result.model_copy(update={"result_sha256": content_sha256("foreign bytes")})
        elif kind == "duplicate":
            return result.model_copy(update={"records": (result.records[0], result.records[0])})
        else:
            return owner.prepared
        return hashed(InferenceTransferSnapshotReadResult, "result_sha256", **body)

    owner.transform = transform
    with pytest.raises(SnapshotStagingError):
        stage_snapshot_experiment(ACTOR, command(owner), owner)
    assert len(owner.calls) == 2


def test_receive_budget_is_accumulated_not_reset_for_each_chunk():
    owner = Owner(width=1)
    initial = stage_snapshot_experiment(ACTOR, command(owner), owner)
    budget = initial.accumulated_received_bytes - 1
    owner.calls.clear()
    with pytest.raises(SnapshotStagingError, match="BUDGET_EXCEEDED"):
        stage_snapshot_experiment(ACTOR, command(owner, maximum_input_bytes=budget), owner)
    assert len(owner.calls) == 4


@pytest.mark.parametrize("budget", ({"maximum_profiles": 2}, {"maximum_queries": 1}))
def test_budget_population_query_ceiling_checked_before_materialized_reads(budget):
    owner = Owner(query_seeds=("a", "c"))
    with pytest.raises(SnapshotStagingError, match="BUDGET_EXCEEDED"):
        stage_snapshot_experiment(ACTOR, command(owner, **budget), owner)
    assert len(owner.calls) == 1


def test_final_canonical_experiment_limit_checked_independently(monkeypatch):
    owner = Owner()
    initial = stage_snapshot_experiment(ACTOR, command(owner), owner)
    oversized_budget = initial.request.budget.model_copy(update={"maximum_input_bytes": 1024})
    # Exercise the final canonical request boundary directly, not the receive budget.
    request = hashed(
        type(initial.request),
        "request_sha256",
        **(
            initial.request.model_dump(mode="json", exclude={"request_sha256"})
            | {"budget": oversized_budget}
        ),
    )
    with pytest.raises(SnapshotStagingError, match="BUDGET_EXCEEDED"):
        staging._validated_experiment(request)


def test_post_model_reauthorization_always_calls_current_owner_not_cached_reply():
    owner = Owner(width=1)
    staged = stage_snapshot_experiment(ACTOR, command(owner), owner)
    first = reauthorize_staged_experiment(ACTOR, staged, owner)
    second = reauthorize_staged_experiment(ACTOR, staged, owner)
    assert first == second
    assert [request.phase for _, request in owner.calls][-2:] == ["AUTHORIZE", "AUTHORIZE"]
    owner.failure_phase = "AUTHORIZE"
    owner.failure = SnapshotReadFailure("INFERENCE_TRANSFER_FORBIDDEN")
    with pytest.raises(SnapshotReadFailure, match="FORBIDDEN"):
        reauthorize_staged_experiment(ACTOR, staged, owner)
    assert [request.phase for _, request in owner.calls][-1:] == ["AUTHORIZE"]


@pytest.mark.parametrize("kind", ("actor", "query", "request_hash", "index", "baseline"))
def test_final_reauthorization_revalidates_staged_identity_before_owner_call(kind):
    owner = Owner()
    staged = stage_snapshot_experiment(ACTOR, command(owner), owner)
    owner.calls.clear()
    actor = ACTOR
    if kind == "actor":
        actor = AuthenticatedSnapshotActor("foreign-operator")
    elif kind == "request_hash":
        staged = replace(
            staged,
            request=staged.request.model_copy(update={"request_sha256": content_sha256("foreign")}),
        )
    elif kind == "index":
        staged = replace(staged, index=staged.index[:-1])
    else:
        body = staged.request.model_dump(mode="json", exclude={"request_sha256"})
        if kind == "query":
            body.update(queries=(staged.index[1].profile,), baselines=())
        else:
            baseline = hashed(
                SuppliedGraphBaseline,
                "result_sha256",
                **(
                    staged.request.baselines[0].model_dump(mode="json", exclude={"result_sha256"})
                    | {"ordered_candidates": ()}
                ),
            )
            body["baselines"] = (baseline,)
        staged = replace(staged, request=hashed(type(staged.request), "request_sha256", **body))
    if kind == "baseline":
        # Valid local hashes are not authority: the owner is still required and can refuse.
        owner.failure_phase = "AUTHORIZE"
        owner.failure = SnapshotReadFailure("INFERENCE_TRANSFER_SNAPSHOT_CHANGED")
        with pytest.raises(SnapshotReadFailure, match="CHANGED"):
            reauthorize_staged_experiment(actor, staged, owner)
        assert len(owner.calls) == 1
    else:
        with pytest.raises(SnapshotStagingError):
            reauthorize_staged_experiment(actor, staged, owner)
        assert owner.calls == []


def test_final_authorize_response_requires_current_exact_phase_and_hash():
    owner = Owner()
    staged = stage_snapshot_experiment(ACTOR, command(owner), owner)
    owner.calls.clear()
    owner.transform = lambda request, result: result.model_copy(
        update={
            "authorization_sha256": content_sha256("foreign"),
            "result_sha256": content_sha256("foreign"),
        }
    )
    with pytest.raises(SnapshotStagingError):
        reauthorize_staged_experiment(ACTOR, staged, owner)
    assert len(owner.calls) == 1


def test_optional_source_module_does_not_import_infrastructure():
    from inspect import getsource

    tree = ast.parse(getsource(staging))
    imports = [node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
    imports.extend(
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    )
    forbidden = (
        "eom_api",
        "eom_catalog_service",
        "sqlalchemy",
        "socket",
        "subprocess",
        "pathlib",
        "os",
    )
    assert not any(
        name == banned or name.startswith(banned + ".") for name in imports for banned in forbidden
    )
