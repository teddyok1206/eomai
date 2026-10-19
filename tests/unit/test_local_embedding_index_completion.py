"""Real pure assembly/contracts with synthetic owner ports; no DB/model/NAS calls."""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import Mock

import pytest
from eom_catalog_contracts.embedding_registry import EmbeddingIndexRegistrationResult
from eom_catalog_contracts.inference_transfer_embedding import (
    IncrementalEmbeddingInput,
    embedding_input_set_sha256,
)
from eom_catalog_contracts.mixed_embedding_registry import EmbeddingIndexRegistrationResultV2
from eom_catalog_service.embedding_index_assembly import PreparedEmbeddingIndexBasis
from eom_catalog_service.embedding_index_assembly_v2 import PreparedMixedEmbeddingIndexBasis
from eom_catalog_service.embedding_registry_ports import ResolvedEmbeddingRegistration
from eom_identifiers import canonical_json_bytes, sha256_bytes
from eom_orchestrator.native_embedding_coordinator import (
    NativeEmbeddingCoordinator,
    NativeEmbeddingCoordinatorHistory,
)
from eom_protocol.artifact_members import ArtifactMemberPointer
from eom_workflow.local_embedding_encoding_job import EmbeddingEncodingReadResult
from eom_workflow.local_embedding_encoding_ownership_v2 import (
    EmbeddingEncodingCompletedEventV2,
    EmbeddingEncodingReadResultV2,
    LocalEmbeddingLaunchAssociationV2,
    LocalEmbeddingLaunchIntentV2,
    validate_embedding_encoding_completions_v2,
)
from eom_workflow.local_embedding_workflow_receipt_v2 import (
    parse_supported_local_embedding_step_output,
)
from eom_workflow.native_embedding_coordinator import (
    NativeArtifactProducerIdentity,
    NativeCoordinatorAllocation,
)
from eom_workflow_runner import local_embedding_index_completion as module

from tests.unit.inference_transfer_embedding_fixtures import embedding_result, seal
from tests.unit.inference_transfer_fixtures import NOW
from tests.unit.local_embedding_admission_fixtures import member
from tests.unit.local_embedding_workflow_receipt_fixtures import receipt_fixture
from tests.unit.test_embedding_index_assembly import rows_for as legacy_rows_for
from tests.unit.test_embedding_index_assembly_v2 import rows_for
from tests.unit.test_local_embedding_source_plan_v2 import inputs
from tests.unit.test_mixed_native_workflow_carriers import carrier_fixture


def _read(event: Any, mixed: bool) -> Any:
    model = EmbeddingEncodingReadResultV2 if mixed else EmbeddingEncodingReadResult
    return model.model_validate(
        seal(
            dict(
                schema_version=(
                    "embedding-encoding-ownership/2.0" if mixed else "embedding-encoding-job/1.0"
                ),
                record_type="READ_RESULT",
                owned_job=event.owned_job.model_dump(mode="json"),
                owner_intent=event.intent.model_dump(mode="json"),
                status="COMPLETED",
                completion=event.model_dump(mode="json"),
            ),
            "read_sha256",
        )
    )


def _review_only_completion(f: Any, event: Any) -> tuple[Any, Any]:
    """Actual owned subset excludes the already-completed borrowed legacy encoding."""
    encoding = event.owned_job.request.encoding
    document = f["input"].model_dump(mode="json")
    document["job_id"] = "job_" + "7" * 32
    document["rows"] = [
        row.model_dump(mode="json") for row in f["input"].rows if row.encoding == encoding
    ]
    document["input_set_sha256"] = embedding_input_set_sha256((encoding,))
    request = IncrementalEmbeddingInput.model_validate(seal(document, "request_sha256"))
    association_body = f["association"].model_dump(mode="json")
    intent = LocalEmbeddingLaunchIntentV2.model_validate(
        seal(
            f["association"].intent.model_dump(mode="json")
            | {
                "workflow_id": "workflow_" + "4" * 32,
                "step_run_id": "steprun_" + "4" * 32,
                "native_launch_job_id": request.job_id,
            },
            "intent_sha256",
        )
    )
    association_body["intent"] = intent.model_dump(mode="json")
    association_body.update(
        owned_jobs=[event.owned_job.model_dump(mode="json")],
        owned_input=member(
            "input.json",
            "eom://schemas/knowledge/incremental-embedding-input/1.0",
            request.model_dump(mode="json"),
            "7",
        ).model_dump(mode="json"),
        owned_input_request_sha256=request.request_sha256,
        owned_input_set_sha256=request.input_set_sha256,
    )
    association = LocalEmbeddingLaunchAssociationV2.model_validate(
        seal(association_body, "association_sha256")
    )
    result = embedding_result(request)
    shard = member(
        "shard.json",
        "eom://schemas/knowledge/embedding-vector-shard/1.0",
        result.shard.model_dump(mode="json"),
        "a",
    )
    receipt = event.receipt.model_dump(mode="json")
    receipt["native_launch_job_id"] = request.job_id
    receipt.update(
        result_manifest=member(
            "result.json",
            "eom://schemas/knowledge/incremental-embedding-result/1.0",
            result.model_dump(mode="json"),
            "a",
        ).model_dump(mode="json"),
        result_sha256=result.result_sha256,
        shard_manifest=shard.model_dump(mode="json"),
        shard_sha256=result.shard.shard_sha256,
        row_ref=dict(
            shard_manifest=shard.model_dump(mode="json"),
            row_index=0,
            encoding_sha256=encoding.encoding_sha256,
        ),
    )
    receipt["binary_member"].update(
        artifact_id=shard.artifact_id,
        artifact_revision_id=shard.artifact_revision_id,
        sha256=result.shard.binary.sha256,
    )
    completed = EmbeddingEncodingCompletedEventV2.model_validate(
        seal(
            event.model_dump(mode="json")
            | {
                "intent": intent.model_dump(mode="json"),
                "launch_association_sha256": association.association_sha256,
                "receipt": seal(receipt, "receipt_sha256"),
            },
            "event_sha256",
        )
    )
    validate_embedding_encoding_completions_v2((completed,), association, request, result)
    return completed, result.shard


def _harness(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, mixed: bool, borrowed: bool = False
) -> Any:
    old = receipt_fixture()
    if mixed:
        f = carrier_fixture()
        request, plan, policy = f["request"], f["plan"], f["policy"]
        entries = inputs("CONTENT_ONLY")[1].entries
        bases = tuple(
            (d.source_revision_id, d.base_analysis_run_id)
            for d in plan.demands
            if hasattr(d, "base_analysis_run_id")
        )
        reusable, shard = rows_for(plan)
        basis_type = PreparedMixedEmbeddingIndexBasis
        intent = f["association"].intent
        template = f["receipt"].registration_result
    else:
        request, plan, policy = old.native.request, old.native.plan, old.native.policy
        entries, bases = old.native.entries, ()
        reusable, shard = legacy_rows_for(old.native)
        basis_type = PreparedEmbeddingIndexBasis
        intent = old.native.association.intent
        template = old.receipt.registration_result
    readings = ()
    new_shards = ()
    if borrowed:
        assert mixed
        legacy_event = old.native.completions[0]
        known = {d.encoding.encoding_sha256 for d in plan.demands}
        assert legacy_event.owned_job.request.encoding.encoding_sha256 in known
        newer = next(
            e
            for e in f["events"]
            if e.owned_job.request.encoding.encoding_sha256
            != legacy_event.owned_job.request.encoding.encoding_sha256
        )
        newer, new_shard = _review_only_completion(f, newer)
        readings = (_read(legacy_event, False), _read(newer, True))
        # Both completed rows belong to original other owners. This coordinator
        # publishes their associations without claiming another native launch.
        intent = type(intent).model_validate(
            seal(
                intent.model_dump(mode="json")
                | {
                    "workflow_id": "workflow_" + "9" * 32,
                    "step_run_id": "steprun_" + "9" * 32,
                    "native_launch_job_id": "job_" + "9" * 32,
                },
                "intent_sha256",
            )
        )
        new_shards = (
            (legacy_event.receipt.shard_manifest, old.native.result.shard),
            (newer.receipt.shard_manifest, new_shard),
        )
        reusable, shards = (), ()
    else:
        shards = (shard,)
    basis = basis_type(plan, reusable, shards, None, 1)
    state = SimpleNamespace(records=[], index=None, resolved=None, receipt=None, output=None)
    coordinator = NativeEmbeddingCoordinator(intent, request)
    allocation = NativeCoordinatorAllocation(
        index_producer=NativeArtifactProducerIdentity(
            job_id="job_" + "c" * 32,
            artifact_id="artifact_" + "b" * 32,
            artifact_revision_id="rev_" + "b" * 32,
        ),
        receipt_producer=NativeArtifactProducerIdentity(
            job_id="job_" + "e" * 32,
            artifact_id="artifact_" + "d" * 32,
            artifact_revision_id="rev_" + "d" * 32,
        ),
        created_at=NOW,
        source_commit="a" * 40,
    )
    state.records.append(coordinator.checkpoint("ALLOCATION", allocation))

    def history(_session: Any) -> Any:
        coordinator._validate_history(tuple(state.records))
        return NativeEmbeddingCoordinatorHistory(
            ("RUNNING", "VALIDATING_RESULT", "COMMITTING", "SUCCEEDED")[len(state.records) - 1],
            tuple(state.records),
        )

    def append(session: Any, record: Any) -> Any:
        coordinator._validate_history((*state.records, record))
        state.records.append(record)
        return history(session)

    coordinator.read, coordinator.append = Mock(side_effect=history), Mock(side_effect=append)
    owner = SimpleNamespace(
        catalog=Mock(),
        settings=object(),
        registry_caller=Mock(return_value=object()),
        fence_mutation=Mock(),
    )
    owner.catalog.prepare_index_basis.return_value = basis
    owner.catalog.prepare_mixed_index_basis.return_value = basis
    owner.catalog.resolve_optional_index_publication.return_value = None
    artifacts, completions = Mock(), Mock()

    def stage(*, index: Any, workspace: Path) -> None:
        state.index = index

    def read_staged(**kwargs: Any) -> Any:
        assert kwargs["expected_sha256"] == sha256_bytes(
            canonical_json_bytes(state.index.model_dump(mode="json"))
        )
        return state.index

    artifacts.stage_index_manifest.side_effect = stage
    artifacts.read_staged_index.side_effect = read_staged
    artifacts.read_staged_mixed_index.side_effect = read_staged

    def resolve(_session: Any, _caller: Any, _command: Any, index: Any) -> Any:
        state.resolved = ResolvedEmbeddingRegistration(
            plan.corpus_id,
            index,
            tuple(
                sorted(
                    (*shards, *new_shards),
                    key=lambda pair: (
                        pair[0].artifact_id,
                        pair[0].artifact_revision_id,
                        pair[0].member_path,
                        pair[0].sha256,
                    ),
                )
            ),
            None,
            plan.sources,
            entries,
            base_analysis_run_ids=bases,
        )
        return state.resolved

    owner.catalog.resolve_prepared_index.side_effect = resolve

    def publish_index(**kwargs: Any) -> Any:
        assert kwargs["index"] == state.index
        return SimpleNamespace(
            index_manifest=state.records[1].payload.registration_command.index_manifest
        )

    artifacts.publish_index.side_effect = publish_index

    def register(_session: Any, _caller: Any, command: Any, _catalog: Any) -> Any:
        body = template.model_dump(mode="json")
        body.update(
            **{
                field: getattr(command, field)
                for field in (
                    "operation_key",
                    "request_sha256",
                    "index_id",
                    "index_revision_id",
                    "index_manifest",
                    "index_sha256",
                )
            },
            current_index_revision_id=command.index_revision_id,
        )
        return (
            EmbeddingIndexRegistrationResultV2 if mixed else EmbeddingIndexRegistrationResult
        ).model_validate(seal(body, "result_sha256"))

    def publish_receipt(receipt: Any, *, identity: Any) -> Any:
        state.receipt = receipt
        schema = "eom://schemas/workflow/local-embedding-workflow-receipt/" + (
            "2.0" if mixed else "1.0"
        )
        body = dict(
            schema_version="local-embedding-step-output/" + ("2.0" if mixed else "1.0"),
            purpose="LOCAL_EMBEDDING",
            workflow_id=receipt.workflow_id,
            step_run_id=receipt.step_run_id,
            step_key="encode_batch",
            attempt=1,
            receipt_owner_job_id=identity.job_id,
            execution_result_schema="incremental-embedding-result@1.0",
            receipt_schema=schema,
            receipt=ArtifactMemberPointer(
                artifact_id=identity.artifact_id,
                artifact_revision_id=identity.artifact_revision_id,
                member_path="receipt.json",
                schema_ref=schema,
                media_type="application/json",
                sha256=sha256_bytes(canonical_json_bytes(receipt.model_dump(mode="json"))),
            ).model_dump(mode="json"),
            receipt_sha256=receipt.receipt_sha256,
        )
        state.output = parse_supported_local_embedding_step_output(seal(body, "output_sha256"))
        return state.output

    completions.publish.side_effect = publish_receipt
    monkeypatch.setattr(module, "ensure_native_index_owner_workspace", lambda _: tmp_path)
    monkeypatch.setattr(module, "NativeEmbeddingCoordinator", Mock(return_value=coordinator))
    monkeypatch.setattr(module, "register_embedding_index", Mock(side_effect=register))
    monkeypatch.setattr(
        module,
        "verify_embedding_index_registration_observation",
        Mock(side_effect=lambda *_: state.resolved),
    )
    monkeypatch.setattr(module, "read_native_embedding_launch_association", Mock(return_value=None))
    monkeypatch.setattr(
        module, "read_native_embedding_launch", Mock(return_value=SimpleNamespace(intent=intent))
    )
    monkeypatch.setattr(
        module, "resolve_native_embedding_completion", Mock(side_effect=lambda *_: state.receipt)
    )
    encoding_artifacts = Mock()
    encoding_artifacts.resolve_shared_row_shards.return_value = new_shards
    monkeypatch.setattr(
        module, "CatalogLocalEmbeddingEncodingArtifacts", Mock(return_value=encoding_artifacts)
    )
    service = module.NativeEmbeddingIndexCompletion(owner, object(), object())
    service._current = Mock(
        return_value=SimpleNamespace(admission=SimpleNamespace(plan=plan, policy=policy))
    )

    @contextmanager
    def fenced() -> Any:
        yield object()

    args = dict(
        workflow=SimpleNamespace(workflow_id=intent.workflow_id),
        step=SimpleNamespace(step_run_id=intent.step_run_id, platform_job_id=None),
        request=request,
        lease=object(),
        caller=object(),
        coordinator=coordinator,
        allocation=allocation,
        readings=readings,
        fenced_transaction=fenced,
        publications=SimpleNamespace(artifacts=artifacts, completions=completions),
    )
    return SimpleNamespace(
        service=service,
        args=args,
        state=state,
        owner=owner,
        artifacts=artifacts,
        completions=completions,
        readings=readings,
        basis=basis,
    )


@pytest.mark.parametrize("mixed", [False, True])
def test_same_publish_flow_uses_exact_contract_family_without_numerical_execution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mixed: bool
) -> None:
    h = _harness(tmp_path, monkeypatch, mixed=mixed)
    output = h.service.publish(**h.args)
    suffix = "2.0" if mixed else "1.0"
    assert output.schema_version == "local-embedding-step-output/" + suffix
    assert h.state.index.schema_version == "embedding-index-manifest/" + suffix
    assert h.state.receipt.schema_version == "local-embedding-workflow-receipt/" + suffix
    assert len(h.state.records) == 4 and h.owner.fence_mutation.call_count == 1
    assert h.service._current.call_count == 4
    assert h.state.records[1].payload.registration_command.index_manifest.schema_ref.endswith(
        "/" + suffix
    )
    assert all(
        record.schema_version == "native-embedding-coordinator/" + suffix
        for record in h.state.records
    )
    assert h.artifacts.read_staged_mixed_index.call_count == int(mixed)
    assert h.artifacts.read_staged_index.call_count == int(not mixed)
    assert h.owner.catalog.prepare_mixed_index_basis.call_count == int(mixed)
    assert h.owner.catalog.prepare_index_basis.call_count == int(not mixed)
    assert tuple(binding.row_ref for binding in h.state.index.bindings) == tuple(
        row.row_ref for row in h.basis.reusable_rows
    )
    assert (
        h.service.validate_completion(
            session=object(),
            workflow=h.args["workflow"],
            step=h.args["step"],
            request=h.args["request"],
            command_lease=h.args["lease"],
            output=output,
        )
        == output
    )


def test_completed_original_owner1_and_owner2_rows_are_consumed_without_retagging(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    h = _harness(tmp_path, monkeypatch, mixed=True, borrowed=True)
    before = tuple(row.model_dump(mode="json") for row in h.readings)
    h.service.publish(**h.args)
    assert tuple(row.model_dump(mode="json") for row in h.readings) == before
    assert h.readings[0].schema_version == "embedding-encoding-job/1.0"
    assert h.readings[1].schema_version == "embedding-encoding-ownership/2.0"
    assert all(
        row.owned_job.request.schema_version == "embedding-encoding-job/1.0" for row in h.readings
    )
    assert {binding.encoding for binding in h.state.index.bindings} == {
        row.owned_job.request.encoding for row in h.readings
    }


def test_prepared_recovery_reads_original_index2_without_new_basis_or_reassembly(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    h = _harness(tmp_path, monkeypatch, mixed=True)
    actual_current = h.service._current.return_value
    h.service._current.side_effect = [actual_current, PermissionError("CURRENT_SOURCE_WITHDRAWN")]
    with pytest.raises(PermissionError, match="CURRENT_SOURCE_WITHDRAWN"):
        h.service.publish(**h.args)
    original = h.state.records[1]
    h.artifacts.publish_index.assert_not_called()
    h.completions.publish.assert_not_called()
    h.service._current.side_effect = None
    h.service.publish(**h.args)
    assert h.state.records[1] == original
    h.owner.catalog.prepare_mixed_index_basis.assert_called_once()
    h.artifacts.stage_index_manifest.assert_called_once()
    h.artifacts.read_staged_mixed_index.assert_called_once()


def test_wrong_basis_family_fails_before_any_artifact_stage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    h = _harness(tmp_path, monkeypatch, mixed=True)
    legacy = receipt_fixture().native
    rows, shard = legacy_rows_for(legacy)
    h.owner.catalog.prepare_mixed_index_basis.return_value = PreparedEmbeddingIndexBasis(
        legacy.plan, rows, (shard,), None, 1
    )
    with pytest.raises(ValueError, match="FAMILY_MISMATCH"):
        h.service.publish(**h.args)
    h.artifacts.stage_index_manifest.assert_not_called()
    h.completions.publish.assert_not_called()
