"""Real Catalog dispatch/temporary Artifact IO; source/IAM/QUERY evidence is synthetic."""

from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from eom_catalog_contracts.public_similarity_materials import validate_public_similarity_materials
from eom_catalog_contracts.registered_public_solution_embedding import (
    parse_public_solution_encoding_entry,
)
from eom_catalog_contracts.registered_public_solution_similarity import (
    parse_supported_public_solution_similarity_context,
    public_solution_reference_for_entry,
)
from eom_catalog_service.embedding_registry_catalog_adapter import CatalogEmbeddingRegistryVerifier
from eom_catalog_service.embedding_registry_ports import EmbeddingRegistryCaller
from eom_catalog_service.inference_transfer_service import (
    AdmittedInferenceTransferCorpus,
    AdmittedInferenceTransferSource,
)
from eom_catalog_service.public_similarity_materials_read import CatalogPublicSolutionMaterialsRead
from eom_catalog_service.public_solution_capture_ports import CapturedPublicSolutionSources
from eom_catalog_service.public_solution_source_capture import CatalogPublicSolutionSourceCapture
from eom_catalog_service.similarity_context_ports import SimilarityContextReadError
from eom_identifiers import canonical_json_bytes, sha256_bytes
from eom_identity_service import OperatorAuthorizationFenceError
from eom_orchestrator.models import ArtifactRecord, ArtifactRevisionRecord, JobRecord

from tests.unit.inference_transfer_embedding_fixtures import seal
from tests.unit.test_embedding_registry_catalog_adapter import _file_set
from tests.unit.test_embedding_registry_catalog_adapter import owner as owner
from tests.unit.test_inference_transfer_item_projection import _item_v1
from tests.unit.test_pinned_artifact_read_context import MetadataSession, member_stream_counts
from tests.unit.test_public_similarity_materials_contracts import material_case
from tests.unit.test_public_solution_index_assembly import setup


def catalog_case(owner, monkeypatch, *, registered=False, capture_fault=None, source_fault=None):
    old, session, _, _, _, scope, root = owner
    context, materials = material_case(registered)
    entries, records, paths = {}, [], []
    for number, material in enumerate((materials.anchor, *materials.entries), 1):
        body = material.entry.model_dump(mode="json")
        artifact_id, revision_id = (
            "artifact_" + f"{number + 256:032x}",
            "rev_" + f"{number + 512:032x}",
        )
        item = _item_v1().model_dump(mode="json")
        if source_fault == "question_limit":
            item["body"] = [
                {
                    "block_id": f"block_large_{index}",
                    "type": "paragraph",
                    "purpose": "context",
                    "text": "가" * 19000 + "끝에서도 보존되지 않는다.",
                }
                for index in range(5)
            ]
            item["solution"]["statement_explanations"] = []
        payload = canonical_json_bytes(item)
        if source_fault == "json":
            payload = b'{"not_valid_item":true}'
        source = body["source"]["artifact_member"]
        source.update(
            artifact_id=artifact_id,
            artifact_revision_id=revision_id,
            member_path="item.json",
            schema_ref="eom.assessment.item-content/1.0",
            media_type="application/json",
            bytes=len(payload),
            sha256=sha256_bytes(payload),
        )
        if source_fault == "schema":
            source["schema_ref"] = "eom://schemas/item-registry/unknown-question-v1"
        elif source_fault == "media":
            source["media_type"] = "application/octet-stream"
        elif source_fault == "limit":
            source["bytes"] = 16 * 1024 * 1024 + 1
        entry = parse_public_solution_encoding_entry(seal(body, "entry_sha256"))
        entries[entry.source.item_revision_id] = entry
        file_records = _file_set(
            root,
            artifact_id,
            revision_id,
            "control_test_question",
            "item.json",
            {"item.json": (payload, source["schema_ref"], source["media_type"])},
            f"{number + 8:x}",
        )
        records.extend(file_records)
        paths.append(root / artifact_id / revision_id / "item.json")
    session.records.update(MetadataSession(*records).records)
    body = context.model_dump(mode="json")
    body["request"]["anchor"] = public_solution_reference_for_entry(
        entries[context.request.anchor.source.item_revision_id]
    ).model_dump(mode="json")
    body["request"] = seal(body["request"], "request_sha256")
    for candidate in body["candidates"]:
        reference = public_solution_reference_for_entry(
            entries[candidate["source"]["item_revision_id"]]
        )
        candidate.update(reference.model_dump(mode="json"))
    context = parse_supported_public_solution_similarity_context(seal(body, "context_sha256"))
    namespace = setup()[3]
    verifier = CatalogEmbeddingRegistryVerifier(
        old.engine,
        replace(
            old.configuration,
            namespace=namespace,
            space=context.request.views[0].index.spaces.document,
            recipe=context.request.views[0].recipe,
            source_classes=context.request.source_classes,
        ),
        identity_fence=old.identity_fence,
        settings=old.settings,
    )
    session.get_bind = lambda: verifier.engine
    calls = []

    def authorize(session, command, **options):
        options["artifact_reader"].require_session(session)
        options["identity_fence"].fence_current_operator(session, command.actor_id)
        return scope

    def capture(_self, session, command, recipe, **options):
        authorize(session, command, **options)
        calls.append((command, options["artifact_reader"]))
        values = tuple(reversed(tuple(entries.values())))
        if capture_fault == "missing":
            values = values[:-1]
        elif capture_fault == "duplicate":
            values = (*values, values[-1])
        elif capture_fault == "entry_hash":
            values = (
                *values[:-1],
                values[-1].model_copy(update={"entry_sha256": "sha256:" + "0" * 64}),
            )
        corpus = AdmittedInferenceTransferCorpus(
            (),
            (),
            capture_fault == "truncated",
            0,
            tuple(
                AdmittedInferenceTransferSource(entry.base_analysis_run_id, entry.source)
                for entry in values
            ),
        )
        return CapturedPublicSolutionSources(
            values, (), tuple(entry.source.item_revision_id for entry in values), scope, corpus
        )

    verifier.sources.authorize_scope_in_session = Mock(side_effect=authorize)
    monkeypatch.setattr(CatalogPublicSolutionSourceCapture, "capture_in_session", capture)
    return SimpleNamespace(
        owner=verifier,
        session=session,
        context=context,
        entries=entries,
        calls=calls,
        paths=paths,
        records=records,
    )


def invoke(case, caller=None):
    return CatalogPublicSolutionMaterialsRead(case.owner).read_in_session(
        case.session, caller or EmbeddingRegistryCaller("operator_" + "1" * 32), case.context
    )


@pytest.mark.parametrize("registered", (False, True))
def test_one_exact_selected_batch_and_bounded_shared_reader_in_context_order(
    owner, monkeypatch, registered
):
    case = catalog_case(owner, monkeypatch, registered=registered)
    streams = member_stream_counts(monkeypatch, set(case.paths))
    result = invoke(case)
    assert validate_public_similarity_materials(result, case.context) == result
    assert tuple(value.entry.source for value in result.entries) == tuple(
        value.source for value in case.context.candidates
    )
    assert all(value.question.status == "AVAILABLE" for value in (result.anchor, *result.entries))
    assert all(
        "SOLUTION_ONLY" not in value.question.content.text
        for value in (result.anchor, *result.entries)
    )
    assert len(case.calls) == 1
    command, reader = case.calls[0]
    assert command.source_revision_ids == tuple(sorted(case.entries))
    assert command.actor_id == "operator_" + "1" * 32
    assert command.graph_snapshot == case.context.request.graph_snapshot
    assert command.access_policy_sha256 == case.context.request.policy_sha256
    assert command.source_classes == case.context.request.source_classes
    assert reader is case.session.info[type(reader)]
    assert streams.opened == streams.closed == {path: 1 for path in case.paths}
    # Prefetch and final provenance each use three set-based metadata reads,
    # independent of the number of selected questions. No per-question SQL.
    assert len(case.session.statements) == 6
    assert invoke(case) == result
    assert len(case.calls) == 2
    assert streams.opened == {path: 1 for path in case.paths}
    assert not case.session.new and not case.session.dirty and not case.session.deleted


@pytest.mark.parametrize("fault", ("missing", "duplicate", "truncated", "entry_hash"))
def test_selected_source_projection_drift_is_not_partial_success(owner, monkeypatch, fault):
    case = catalog_case(owner, monkeypatch, capture_fault=fault)
    with pytest.raises(SimilarityContextReadError) as error:
        invoke(case)
    assert error.value.code == "SOURCE_POINTER_INVALID"


@pytest.mark.parametrize(
    "fault",
    (
        "tamper",
        "missing_file",
        "missing_revision",
        "foreign_revision",
        "approval",
        "producer",
        "byte_count",
        "json",
        "schema_pin",
    ),
)
def test_actual_question_member_corruption_and_lifecycle_fail_closed(owner, monkeypatch, fault):
    case = catalog_case(owner, monkeypatch, source_fault="json" if fault == "json" else None)
    if fault == "tamper":
        case.paths[0].write_bytes(b"not the source")
    elif fault == "missing_file":
        case.paths[0].unlink()
    elif fault == "missing_revision":
        record = next(value for value in case.records if isinstance(value, ArtifactRevisionRecord))
        case.session.records.pop((ArtifactRevisionRecord, record.revision_id))
    elif fault == "foreign_revision":
        record = next(value for value in case.records if isinstance(value, ArtifactRevisionRecord))
        record.logical_artifact_id = "artifact_" + "0" * 32
    elif fault == "approval":
        next(
            value for value in case.records if isinstance(value, ArtifactRevisionRecord)
        ).approved = False
    elif fault == "producer":
        next(value for value in case.records if isinstance(value, JobRecord)).status = "FAILED"
    elif fault in {"byte_count", "schema_pin"}:
        revision = next(
            value for value in case.records if isinstance(value, ArtifactRevisionRecord)
        )
        revision.manifest["files"][0]["bytes" if fault == "byte_count" else "schema_ref"] = (
            999 if fault == "byte_count" else "foreign/1.0"
        )
    with pytest.raises(SimilarityContextReadError) as error:
        invoke(case)
    assert error.value.code == "SOURCE_POINTER_INVALID"


@pytest.mark.parametrize(
    "fault,reason",
    (
        ("schema", "SCHEMA_UNSUPPORTED"),
        ("media", "MEDIA_TYPE_UNSUPPORTED"),
        ("limit", "SOURCE_BYTE_LIMIT_EXCEEDED"),
    ),
)
def test_declared_unsupported_question_is_explicit_without_fabricated_text(
    owner, monkeypatch, fault, reason
):
    case = catalog_case(owner, monkeypatch, source_fault=fault)
    streams = member_stream_counts(monkeypatch, set(case.paths))
    result = invoke(case)
    assert all(
        value.question.status == "UNAVAILABLE" and value.question.reason == reason
        for value in (result.anchor, *result.entries)
    )
    assert all(
        value.entry.public_solution.status == "AVAILABLE"
        for value in (result.anchor, *result.entries)
    )
    assert not streams.opened


def test_complete_large_question_is_unavailable_not_a_clipped_partial_text(owner, monkeypatch):
    case = catalog_case(owner, monkeypatch, source_fault="question_limit")
    result = invoke(case)
    for material in (result.anchor, *result.entries):
        assert material.question.status == "UNAVAILABLE"
        assert material.question.reason == "QUESTION_TEXT_LIMIT_EXCEEDED"
        assert material.entry.public_solution.status == "AVAILABLE"


@pytest.mark.parametrize("late", (False, True))
def test_actual_operator_denial_keeps_access_error_before_or_after_materialization(
    owner, monkeypatch, late
):
    case = catalog_case(owner, monkeypatch)

    def denied(*args, **kwargs):
        raise OperatorAuthorizationFenceError("OPERATOR_AUTHORIZATION_FENCE_FORBIDDEN")

    if late:
        case.owner.sources.authorize_scope_in_session.side_effect = denied
    else:
        case.owner.identity_fence.fence_current_operator.side_effect = denied
    with pytest.raises(SimilarityContextReadError) as error:
        invoke(case)
    assert error.value.code == "SOURCE_ACCESS_DENIED"
    assert len(case.calls) == (1 if late else 0)


def test_late_artifact_approval_revocation_is_not_hidden_by_warm_reader(owner, monkeypatch):
    case = catalog_case(owner, monkeypatch)

    def revoke(*args, **kwargs):
        next(value for value in case.records if isinstance(value, ArtifactRecord)).approved = False

    case.owner.sources.authorize_scope_in_session.side_effect = revoke
    with pytest.raises(SimilarityContextReadError) as error:
        invoke(case)
    assert error.value.code == "SOURCE_POINTER_INVALID"


@pytest.mark.parametrize(
    "fault", ("root", "nested", "engine", "fence", "caller", "recipe", "classes")
)
def test_no_service_identity_or_cross_root_namespace_authority_borrowing(owner, monkeypatch, fault):
    case = catalog_case(owner, monkeypatch)
    caller = None
    if fault == "root":
        case.session.root.is_active = False
    elif fault == "nested":
        case.session.in_nested_transaction = lambda: True
    elif fault == "engine":
        case.session.get_bind = lambda: object()
    elif fault == "fence":
        case.owner.identity_fence = None
    elif fault == "caller":
        caller = SimpleNamespace(operator_id="operator_" + "1" * 32)
    elif fault == "recipe":
        case.owner.configuration = replace(
            case.owner.configuration,
            recipe=case.owner.configuration.recipe.model_copy(
                update={"recipe_sha256": "sha256:" + "0" * 64}
            ),
        )
    else:
        case.owner.configuration = replace(case.owner.configuration, source_classes=("PAST_EXAM",))
    with pytest.raises(SimilarityContextReadError):
        invoke(case, caller)
    assert not case.calls
