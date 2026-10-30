"""Existing full native QUERY executor with QUERY2; IAM/unit/model seams are synthetic.

The original Job/event journal, protected local staging, Artifact and receipt IO
are real. This is not installed/GPU/live source acceptance.
"""

from dataclasses import replace

import pytest
from eom_catalog_contracts.public_solution_embedding_index import PublicSolutionIndexNamespace
from eom_catalog_service.embedding_encoder_adapter import encode_public_solution_query
from eom_catalog_service.embedding_registry_catalog_adapter import (
    EmbeddingRegistryOwnerConfiguration,
)
from eom_identifiers import canonical_json_bytes, sha256_bytes
from eom_orchestrator.embedding_artifact_store import EmbeddingArtifactStore
from eom_orchestrator.local_embedding_completion_artifacts import NativeEmbeddingCompletionPublisher
from eom_orchestrator.models import ArtifactRevisionRecord, JobRecord
from eom_orchestrator.native_embedding_query_systemd import NativeQueryLaunchError
from eom_workflow.native_reference_query_coordinator import NativeQueryCompletedV2
from eom_workflow.reference_query_execution import (
    ReferenceQueryStepOutputV2,
    parse_reference_query_execution_policy,
    parse_reference_query_workflow_request_v3,
)
from sqlalchemy import func, select

from tests.unit.inference_transfer_embedding_fixtures import seal
from tests.unit.test_embedding_incremental_encoding import SyntheticNativeBackend
from tests.unit.test_public_solution_query_source import public_query_sources
from tests.unit.test_public_solution_reference_query_execution import public_workflow_case
from tests.unit.test_reference_query_native_executor import make_executor_case


def make_public_executor_case(tmp_path, monkeypatch, *, publisher=None, identity=None):
    value = make_executor_case(tmp_path, monkeypatch, publisher=publisher)
    case = public_workflow_case(identity=identity)
    resources = value.sources.policy.resource_profile
    case.policy = parse_reference_query_execution_policy(
        seal(
            case.policy.model_dump(mode="json")
            | {"resource_profile": resources.model_dump(mode="json")},
            "policy_sha256",
        )
    )
    case.request = parse_reference_query_workflow_request_v3(
        seal(
            case.request.model_dump(mode="json")
            | {
                "resource_profile": resources.model_dump(mode="json"),
                "native_execution_policy_sha256": case.policy.policy_sha256,
                "native_execution_policy": case.request.native_execution_policy.model_dump(
                    mode="json"
                )
                | {
                    "sha256": sha256_bytes(
                        canonical_json_bytes(case.policy.model_dump(mode="json"))
                    ),
                },
            },
            "request_sha256",
        )
    )
    value.request = case.request
    value.sources = public_query_sources(case)
    value.workflow.workflow_id = case.launch.workflow_id
    value.step.step_run_id = case.launch.step_run_id
    context = case.request.context_request
    selected = context.views[0]
    value.owner.configuration = replace(
        value.owner.configuration,
        registry=EmbeddingRegistryOwnerConfiguration(
            value.owner.configuration.registry.corpus_id,
            PublicSolutionIndexNamespace(
                storage_partition=selected.index.storage_partition,
                space_sha256=case.policy.spaces.document.space_sha256,
                view=selected.view,
                recipe_sha256=selected.recipe.recipe_sha256,
                population_scope="ALL_ADMITTED_GRAPH_ITEMS",
            ),
            case.policy.spaces.document,
            selected.recipe,
            context.source_classes,
        ),
        native_execution_policy=case.request.native_execution_policy,
        native_execution_policy_sha256=case.request.native_execution_policy_sha256,
        runtime_bundle=case.request.runtime_bundle,
    )
    value.launcher.checkpoint_schema_version = "native-reference-query-coordinator/1.1"

    def run(prepared):
        assert value.root_depth == 0, "SQL/source locks survived numerical execution"
        value.runs.append(prepared)
        if value.failure:
            raise NativeQueryLaunchError(value.failure)
        backend = SyntheticNativeBackend(prepared.request.spaces.query)
        backend.batch_size, backend.threads = prepared.request.batch_size, prepared.request.threads
        encoded = encode_public_solution_query(prepared.request, backend)
        for name, raw in (
            ("result.json", canonical_json_bytes(encoded.result.model_dump(mode="json"))),
            ("vectors.f32", encoded.vectors),
        ):
            target = prepared.workspace / name
            target.write_bytes(raw)
            target.chmod(0o600)
        if value.after_run:
            value.after_run(prepared)
        return encoded.result

    value.launcher.run.side_effect = run
    return value


@pytest.fixture
def query(tmp_path, monkeypatch):
    return make_public_executor_case(tmp_path, monkeypatch)


def test_existing_executor_query2_staging_four_checkpoints_canonical_result_and_exact_replay(query):
    output = query.execute()
    assert isinstance(output, ReferenceQueryStepOutputV2)
    original = query.history()
    assert original.state == "SUCCEEDED" and len(original.records) == 4
    assert all(
        row.schema_version == "native-reference-query-coordinator/2.0" for row in original.records
    )
    assert isinstance(original.records[3].payload, NativeQueryCompletedV2)
    assert query.execute(generation=2) == output and query.history() == original
    assert len(query.runs) == 1
    with query.publisher.sessions.begin() as session:
        assert session.scalar(select(func.count()).select_from(JobRecord)) == 3
        assert session.scalar(select(func.count()).select_from(ArtifactRevisionRecord)) == 2


@pytest.mark.parametrize(
    "boundary", ["query_before", "query_after", "receipt_before", "receipt_after"]
)
def test_query2_actual_executor_resumes_each_publication_boundary_without_another_encode(
    query, monkeypatch, boundary
):
    owner = (
        EmbeddingArtifactStore
        if boundary.startswith("query")
        else NativeEmbeddingCompletionPublisher
    )
    original = owner.publish_supported_reference_query

    def crash(self, *args, **kwargs):
        if boundary.endswith("after"):
            original(self, *args, **kwargs)
        raise KeyboardInterrupt("synthetic original owner termination")

    with monkeypatch.context() as patch:
        patch.setattr(owner, "publish_supported_reference_query", crash)
        with pytest.raises(KeyboardInterrupt):
            query.execute()
    before = query.history()
    assert len(before.records) == (2 if boundary.startswith("query") else 3)
    assert isinstance(query.execute(generation=2), ReferenceQueryStepOutputV2)
    assert query.history().launch == before.launch
    assert query.history().records[: len(before.records)] == before.records
    assert len(query.runs) == 1


def test_query2_failed_original_never_becomes_success_and_does_not_allocate_replacement(query):
    query.failure = "NATIVE_QUERY_KNOWN_FAILED"
    with pytest.raises(NativeQueryLaunchError):
        query.execute()
    before = query.history()
    assert before.state == "FAILED" and len(before.records) == 1
    query.failure = None
    with pytest.raises(ValueError, match="TERMINAL_HISTORY"):
        query.execute(generation=2)
    assert query.history() == before and len(query.runs) == 1
