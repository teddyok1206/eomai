"""Current operator and canonical six-source admission, never Job or model admission."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from eom_catalog_contracts.embedding_device_benchmark import (
    MAX_BENCHMARK_STAGED_BYTES,
    BenchmarkOwnerRequest,
    BenchmarkStagedInputs,
    embedding_device_benchmark_bytes,
    parse_embedding_device_benchmark_bytes,
    validate_benchmark_staged_inputs,
)
from eom_catalog_contracts.inference_transfer_experiment import (
    experiment_view_text,
    profile_key,
)
from eom_catalog_contracts.item_inference_transfer import InferenceTransferProfilePointer
from eom_catalog_contracts.knowledge import (
    ApprovedPastExamItemKnowledgeSourceV3,
    same_approved_item_source_identity,
)
from eom_identifiers import content_sha256
from eom_identity_service import (
    AuthenticatedOperatorSession,
    AuthenticatedSessionFence,
    CapturedOperatorAuthorizationFence,
)
from eom_operator_identity import PermissionKey
from jsonschema.exceptions import ValidationError as JsonSchemaError
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from eom_catalog_service.inference_transfer_catalog_adapter import (
    InferenceTransferCorpusReadCommand,
)
from eom_catalog_service.inference_transfer_scope import InferenceTransferPopulationScope
from eom_catalog_service.inference_transfer_snapshot_catalog_adapter import (
    CatalogInferenceTransferSnapshotSourceAdapter,
    InferenceTransferSessionCapturePhase,
)
from eom_catalog_service.pinned_artifact_resolution import PinnedArtifactReadContext
from eom_catalog_service.settings import CatalogSettings


class BenchmarkSourceAdmissionError(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _require(condition: bool) -> None:
    if not condition:
        raise BenchmarkSourceAdmissionError("BENCHMARK_SOURCE_PIN_MISMATCH")


def _read_command(request: BenchmarkOwnerRequest, actor: str) -> InferenceTransferCorpusReadCommand:
    revisions = tuple(sorted(source.source.item_revision_id for source in request.sources))
    _require(len(set(revisions)) == 6)
    return InferenceTransferCorpusReadCommand(
        actor_id=actor,
        graph_snapshot=request.graph_snapshot,
        access_policy_revision_id=request.policy_revision_id,
        access_policy_sha256=request.policy_sha256,
        source_classes=tuple(sorted({source.source.source_class for source in request.sources})),
        maximum_candidates=6,
        population_scope=InferenceTransferPopulationScope.ALL_ADMITTED_GRAPH_ITEMS,
        source_revision_ids=revisions,
    )


class CatalogBenchmarkSourceAdmission:
    """Reuse official GraphRAG resolution; caller owns the root and later launch admission."""

    def __init__(
        self,
        engine: Engine,
        *,
        capture: AuthenticatedOperatorSession,
        session_fence: AuthenticatedSessionFence,
        settings: CatalogSettings | None = None,
    ) -> None:
        self._identity = CapturedOperatorAuthorizationFence(
            capture, session_fence, PermissionKey.WORKFLOW_START
        )
        self._sources = CatalogInferenceTransferSnapshotSourceAdapter(engine, settings)
        self._settings = settings or CatalogSettings.from_environment()

    @contextmanager
    def admit_in_session(
        self, session: Session, request: BenchmarkOwnerRequest
    ) -> Iterator[BenchmarkStagedInputs]:
        """Retain root locks through a caller mutation and check scope/expiry late.

        Caller must promptly commit this root or roll it back on any exception.
        The exit fence checks scope without rereading/hashing immutable input text.
        """
        inputs = self.resolve_in_session(session, request)
        root = session.get_transaction()
        _require(root is not None and root.is_active)
        assert root is not None
        yield inputs
        _require(
            session.get_transaction() is root
            and root.is_active
            and not session.in_nested_transaction()
        )
        actor = self._identity.capture.operator_id
        self._sources.capture_in_session(
            session,
            _read_command(request, actor),
            request.view_recipe,
            identity_fence=self._identity,
            artifact_reader=PinnedArtifactReadContext(session, self._settings),
            phase=InferenceTransferSessionCapturePhase.AUTHORIZE_SCOPE,
        )
        self._identity.fence_current_operator(session, actor)

    def resolve_in_session(
        self, session: Session, request: BenchmarkOwnerRequest
    ) -> BenchmarkStagedInputs:
        """Reauthorize before IO; no persisted actor ID or parsed receipt is authority.

        Returned inputs are an explicit owner materialization, not a transferable grant.
        Token witness correctness and both installed backends remain separate requirements.
        """
        embedding_device_benchmark_bytes(request)
        if session.in_nested_transaction():
            raise BenchmarkSourceAdmissionError("BENCHMARK_SOURCE_ROOT_TRANSACTION_REQUIRED")
        actor = self._identity.capture.operator_id
        if request.operator_audit_id != actor:
            raise BenchmarkSourceAdmissionError("BENCHMARK_SOURCE_OPERATOR_MISMATCH")
        self._identity.fence_current_operator(session, actor)
        command = _read_command(request, actor)
        reader = PinnedArtifactReadContext(session, self._settings)
        captured = self._sources.capture_in_session(
            session,
            command,
            request.view_recipe,
            identity_fence=self._identity,
            artifact_reader=reader,
        )
        corpus = captured.corpus
        _require(corpus is not None)
        assert corpus is not None
        _require(
            not corpus.truncated
            and corpus.missing_solution_reports == 0
            and len(corpus.profiles) == len(corpus.sources) == len(captured.entries) == 6
        )
        entries = {
            profile_key(InferenceTransferProfilePointer.from_profile(entry.profile)): entry
            for entry in captured.entries
        }
        profiles = {
            profile_key(InferenceTransferProfilePointer.from_profile(profile)): profile
            for profile in corpus.profiles
        }
        sources = {source.source.item_revision_id: source for source in corpus.sources}
        _require(
            len(entries) == len(profiles) == len(sources) == 6
            and entries.keys()
            == profiles.keys()
            == {profile_key(s.profile) for s in request.sources}
        )
        for selection in request.sources:
            key = profile_key(selection.profile)
            entry, admitted = entries[key], sources.get(selection.source.item_revision_id)
            _require(admitted is not None)
            assert admitted is not None
            basis = entry.profile.source_basis
            _require(
                entry.profile == profiles[key]
                # Accepted report bases pin core Item/member identity; a reauthorized
                # Graph source can additionally carry the complete V3 visual lineage.
                and same_approved_item_source_identity(admitted.source, selection.source)
                and same_approved_item_source_identity(selection.source, basis.source)
                and (
                    not isinstance(selection.source, ApprovedPastExamItemKnowledgeSourceV3)
                    or admitted.source == selection.source
                )
                and admitted.analysis_run_id == selection.solution_evidence.base_analysis_run_id
                and basis.solution_evidence == selection.solution_evidence
                and basis.graph_snapshot == request.graph_snapshot
            )
        # No arbitrary worker path: resolve only the pinned, committed input member.
        pointer = request.input_manifest
        reader.prefetch(((pointer.artifact_id, pointer.artifact_revision_id),))
        raw = reader.read_member(
            artifact_id=pointer.artifact_id,
            revision_id=pointer.artifact_revision_id,
            member_path=pointer.member_path,
            sha256=pointer.sha256,
            media_type=pointer.media_type,
            schema_ref=pointer.schema_ref,
            max_bytes=MAX_BENCHMARK_STAGED_BYTES,
        )
        try:
            inputs = parse_embedding_device_benchmark_bytes(
                raw, maximum_bytes=MAX_BENCHMARK_STAGED_BYTES
            )
        except (ValueError, JsonSchemaError):
            raise BenchmarkSourceAdmissionError("BENCHMARK_INPUT_INVALID") from None
        _require(type(inputs) is BenchmarkStagedInputs)
        assert isinstance(inputs, BenchmarkStagedInputs)
        _require(embedding_device_benchmark_bytes(inputs) == raw)
        validate_benchmark_staged_inputs(request, inputs)
        for row in (*inputs.documents, *inputs.queries):
            entry = entries[profile_key(row.row.profile)]
            text = experiment_view_text(entry, row.row.view)
            _require(
                text is not None
                and bool(text.strip())
                and row.text == text
                and row.row.input_text_sha256 == content_sha256(text)
            )
        reader.require_session(session)
        self._identity.fence_current_operator(session, actor)
        return inputs
