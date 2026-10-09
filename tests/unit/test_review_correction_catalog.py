from __future__ import annotations

import json
from contextlib import nullcontext
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from eom_catalog_service.workflow_catalog import (
    REVIEW_CORRECTION_PROMPT_MARKER,
    WorkflowCatalogService,
)
from eom_identifiers import canonical_json_bytes, content_sha256, sha256_bytes
from eom_workflow import (
    ArtifactPointer,
    ReviewPolicyCorrectionRequired,
    WorkflowRequest,
    WorkflowReviewCorrectionDirective,
    build_review_correction_directive,
    build_review_escalation_directive,
    build_review_rework_directive,
    structural_review_complexity,
    validate_primary_review_escalation_policy,
)
from eom_workflow.models import (
    ContentTeamAuthoringRoleResultV12,
    ContentTeamReviewRoleResultV12,
)
from eom_workflow_runner.models import WorkflowInstanceRecord, WorkflowStepRunRecord

from tests.unit.test_execution_materializer import _knowledge_fixture
from tests.unit.test_graph_review_v11_protocol import (
    _authoring_result,
    _v12_plan_review_step,
    _v12_review_document,
)

ROOT = Path(__file__).resolve().parents[2]
TEMPLATE = "Review {{upstream.authoring.result_json}}."


def _pointer(result: dict[str, Any], *, attempt: int = 1) -> ArtifactPointer:
    return ArtifactPointer(
        step_key=str(result["role"]),
        attempt=attempt,
        job_id=result["job_id"],
        logical_artifact_id=result["artifact"]["logical_artifact_id"],
        revision_id=result["artifact"]["revision_id"],
        content_hash=content_sha256(result),
        result_schema=f"{result['role']}-result@12.0",
    )


class _Artifacts:
    def __init__(self, results: tuple[dict[str, Any], ...]) -> None:
        self.results = {
            (result["artifact"]["logical_artifact_id"], result["artifact"]["revision_id"]): result
            for result in results
        }
        self.loads: list[tuple[str, str]] = []
        self.commits: list[dict[str, Any]] = []
        self.prompt: bytes | None = None
        self.envelope: bytes | None = None

    def load_json_revision(
        self, *, artifact_id: str, revision_id: str, content_hash: str
    ) -> dict[str, Any]:
        self.loads.append((artifact_id, revision_id))
        result = self.results[(artifact_id, revision_id)]
        if content_sha256(result) != content_hash:
            raise ValueError("immutable result hash differs")
        return deepcopy(result)

    def commit_file_set(self, **values: Any) -> SimpleNamespace:
        self.commits.append(values)
        self.prompt = values["files"]["prompt.txt"].read_bytes()
        self.envelope = values["files"]["prompt-envelope.json"].read_bytes()
        return SimpleNamespace(
            artifact_id="artifact_" + "a" * 32,
            revision_id="rev_" + "a" * 32,
            content_hash=sha256_bytes(self.prompt),
            manifest_hash="sha256:" + "a" * 64,
        )

    def load_rendered_prompt(self, **values: str) -> tuple[bytes, bytes]:
        assert self.prompt is not None and self.envelope is not None
        assert values["prompt_sha256"] == sha256_bytes(self.prompt)
        assert values["envelope_sha256"] == sha256_bytes(self.envelope)
        return self.prompt, self.envelope


def _fixture(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[
    WorkflowCatalogService,
    _Artifacts,
    WorkflowInstanceRecord,
    WorkflowStepRunRecord,
    WorkflowRequest,
    ArtifactPointer,
    dict[str, Any],
]:
    graph = _knowledge_fixture(
        tmp_path, monkeypatch, manifest_schema_version="5.0", workflow_definition_version="1.13.0"
    )
    authoring_data = _authoring_result(graph).model_dump(mode="json")
    authoring_data["protocol_version"] = "workflow-role/1.24.0"
    authoring = ContentTeamAuthoringRoleResultV12.model_validate(authoring_data)
    score = structural_review_complexity(authoring)
    review_data = _v12_review_document(graph, score=score + 1)
    review = ContentTeamReviewRoleResultV12.model_validate(review_data)
    with pytest.raises(ReviewPolicyCorrectionRequired) as captured:
        validate_primary_review_escalation_policy(authoring=authoring, review=review)
    authoring_pointer = _pointer(authoring_data)
    directive = build_review_correction_directive(
        workflow_id=authoring.workflow_id,
        reviewed_authoring=authoring_pointer,
        source_review=_pointer(review_data),
        review_pass="PRIMARY",
        pass_number=2,
        issue=captured.value.issue,
    )
    pack = {
        "release_id": "packrel_" + "1" * 32,
        "release_sha256": "sha256:" + "1" * 64,
    }
    profile = {
        "profile_key": "generated-knowledge-review",
        "profile_version": "12.2.1",
        "profile_sha256": "sha256:" + "2" * 64,
        "template_relative_path": "prompt-templates/review.md",
        "required_context": ["upstream.authoring.result_json"],
    }
    workflow = cast(
        WorkflowInstanceRecord,
        SimpleNamespace(
            workflow_id=authoring.workflow_id,
            runtime_context={
                "content_pack": pack,
                "profiles": {"review": profile},
                "source_intake": {"batch_ids": []},
            },
        ),
    )
    step = cast(
        WorkflowStepRunRecord,
        SimpleNamespace(
            step_key="review",
            worker_role="review",
            attempt=2,
            step_run_id="steprun_" + "9" * 32,
            result_schema="review-result@12.0",
            input_pointer_manifest={
                "upstream_artifacts": [authoring_pointer.model_dump(mode="json")],
                "review_correction_directive": directive.model_dump(mode="json"),
            },
        ),
    )
    artifacts = _Artifacts((authoring_data, review_data))
    service = object.__new__(WorkflowCatalogService)
    service.artifacts = cast(Any, artifacts)
    (tmp_path / "prompts").mkdir(mode=0o750)
    service.settings = cast(Any, SimpleNamespace(prompt_staging_root=tmp_path / "prompts"))
    stored_profile = SimpleNamespace(
        **{key: value for key, value in profile.items() if key != "template_relative_path"},
        template_relative_path=profile["template_relative_path"],
        output_schema_ref=step.result_schema,
    )
    service.sessions = cast(
        Any, lambda: nullcontext(SimpleNamespace(scalar=lambda _: stored_profile))
    )
    service.resources = cast(Any, SimpleNamespace(read=lambda *_: TEMPLATE.encode("utf-8")))
    monkeypatch.setattr(
        service,
        "_pinned_release",
        lambda *_: SimpleNamespace(content_pack_release_id=pack["release_id"]),
    )

    def binding(
        _session: Any, *, step: WorkflowStepRunRecord, directive: WorkflowReviewCorrectionDirective
    ) -> None:
        if step.attempt != directive.next_attempt:
            raise ValueError("review correction directive differs from its exact step inputs")

    # DB-backed retry-chain proof is exercised by the runner integration suite. These tests
    # isolate Catalog's strict result resolution, feedback materialization, and prompt replay.
    monkeypatch.setattr(
        "eom_catalog_service.workflow_catalog.validate_review_correction_step_binding", binding
    )
    request = WorkflowRequest.model_validate(
        json.loads(
            (
                ROOT / "content/packs/generated-knowledge-item/1.20.15/fixtures/smoke-request.json"
            ).read_text(encoding="utf-8")
        )
    )
    return service, artifacts, workflow, step, request, authoring_pointer, review_data


def _pin_prompt(
    service: WorkflowCatalogService,
    workflow: WorkflowInstanceRecord,
    step: WorkflowStepRunRecord,
    request: WorkflowRequest,
    authoring: ArtifactPointer,
) -> str:
    prepared = service.prepare_prompt(
        workflow=workflow, step=step, request=request, upstream=(authoring,)
    )
    step.input_pointer_manifest = {
        **step.input_pointer_manifest,
        "prompt": prepared.pointer,
        "prompt_envelope": prepared.envelope,
    }
    workflow.runtime_context["prompt_artifacts"] = [
        {"step_key": step.step_key, "attempt": step.attempt, **prepared.pointer}
    ]
    return prepared.text


def test_correction_context_has_exact_prior_result_without_ordinary_upstream_duplicate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service, artifacts, workflow, step, request, authoring, review = _fixture(tmp_path, monkeypatch)
    context = service._prompt_context(workflow, step, request, (authoring,), "packrel_" + "1" * 32)

    assert set(context["upstream"]) == {"authoring"}
    correction = context["review_correction"]
    assert json.loads(correction["source_review_result_json"]) == review
    assert (
        json.loads(correction["directive_json"])
        == step.input_pointer_manifest["review_correction_directive"]
    )
    assert "2교" in correction["instruction_text"]
    assert len(artifacts.loads) == len(set(artifacts.loads)) == 2
    assert context["rework"]["feedback_json"] == "null"
    assert context["escalation"]["directive_json"] == "null"


def test_correction_retains_rework_and_generated_image_context_without_duplicate_loads(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service, artifacts, workflow, step, request, authoring, review = _fixture(tmp_path, monkeypatch)
    rework = build_review_rework_directive(
        prior_authoring=authoring,
        source_review=_pointer(review),
        blocking_finding_codes=("DIFFICULTY_MISMATCH",),
        disregarded_finding_codes=(),
        observed_rework_cycle_count=0,
        max_rework_cycles=3,
    )
    generated_stimulus = {"artifact_revision_id": "rev_" + "e" * 32}
    workflow.runtime_context.update(
        {
            "review_rework_history": [rework.model_dump(mode="json")],
            "review_rework_status": rework.outcome,
            "generated_stimulus": generated_stimulus,
        }
    )
    context = service._prompt_context(workflow, step, request, (authoring,), "packrel_" + "1" * 32)

    assert json.loads(context["rework"]["feedback_json"]) == rework.model_dump(mode="json")
    assert json.loads(context["rework"]["source_review_result_json"]) == review
    assert context["generated_stimulus"] == generated_stimulus
    assert len(artifacts.loads) == len(set(artifacts.loads)) == 2


def test_prompt_hashes_cover_supplement_and_source_without_changing_pack_template(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service, artifacts, workflow, step, request, authoring, review = _fixture(tmp_path, monkeypatch)
    prepared = service.prepare_prompt(
        workflow=workflow, step=step, request=request, upstream=(authoring,)
    )

    assert REVIEW_CORRECTION_PROMPT_MARKER in prepared.text
    assert canonical_json_bytes(review).decode("utf-8") in prepared.text
    assert prepared.envelope["template_sha256"] == sha256_bytes(TEMPLATE.encode("utf-8"))
    assert prepared.envelope["rendered_prompt_sha256"] == sha256_bytes(
        prepared.text.encode("utf-8")
    )
    context = service._prompt_context(workflow, step, request, (authoring,), "packrel_" + "1" * 32)
    assert prepared.envelope["render_context_sha256"] == content_sha256(context)
    assert len(artifacts.commits) == 1


def test_correction_prompt_replay_uses_exact_artifact_without_recommit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service, artifacts, workflow, step, request, authoring, _ = _fixture(tmp_path, monkeypatch)
    text = _pin_prompt(service, workflow, step, request, authoring)
    replay = service.prepare_prompt(
        workflow=workflow, step=step, request=request, upstream=(authoring,)
    )

    assert replay.text == text
    assert len(artifacts.commits) == 1


@pytest.mark.parametrize("change", ("removed", "rehash", "bad_hash"))
def test_pinned_correction_prompt_rejects_changed_or_removed_directive(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, change: str
) -> None:
    service, _, workflow, step, request, authoring, _ = _fixture(tmp_path, monkeypatch)
    _pin_prompt(service, workflow, step, request, authoring)
    if change == "removed":
        del step.input_pointer_manifest["review_correction_directive"]
    else:
        directive = deepcopy(step.input_pointer_manifest["review_correction_directive"])
        directive["pass_number"] = 3
        directive["decision_sha256"] = (
            content_sha256(
                {key: value for key, value in directive.items() if key != "decision_sha256"}
            )
            if change == "rehash"
            else "sha256:" + "f" * 64
        )
        step.input_pointer_manifest["review_correction_directive"] = directive

    with pytest.raises(ValueError):
        service.prepare_prompt(workflow=workflow, step=step, request=request, upstream=(authoring,))


@pytest.mark.parametrize("change", ("foreign_workflow", "attempt", "authoring_pin", "upstream"))
def test_correction_rejects_wrong_workflow_attempt_and_authored_input(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, change: str
) -> None:
    service, _, workflow, step, request, authoring, _ = _fixture(tmp_path, monkeypatch)
    if change == "foreign_workflow":
        workflow.workflow_id = "workflow_" + "f" * 32
    elif change == "attempt":
        step.attempt = 3
    elif change == "upstream":
        step.input_pointer_manifest["upstream_artifacts"] = []
    else:
        authoring = authoring.model_copy(update={"revision_id": "rev_" + "f" * 32})

    with pytest.raises(ValueError, match="exact step inputs"):
        service._prompt_context(workflow, step, request, (authoring,), "packrel_" + "1" * 32)


def test_correction_rejects_result_hash_mismatch_without_looser_result_loading(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service, artifacts, workflow, step, request, authoring, _ = _fixture(tmp_path, monkeypatch)
    source = WorkflowReviewCorrectionDirective.model_validate(
        step.input_pointer_manifest["review_correction_directive"]
    ).source_review
    artifacts.results[(source.logical_artifact_id, source.revision_id)]["workflow_id"] = (
        "workflow_" + "f" * 32
    )

    with pytest.raises(ValueError, match="result hash differs"):
        service._prompt_context(workflow, step, request, (authoring,), "packrel_" + "1" * 32)


def test_correction_rejects_even_hash_valid_review_from_another_workflow(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service, artifacts, workflow, step, request, authoring, review = _fixture(tmp_path, monkeypatch)
    foreign = deepcopy(review)
    foreign["workflow_id"] = "workflow_" + "f" * 32
    pointer = _pointer(foreign)
    directive = deepcopy(step.input_pointer_manifest["review_correction_directive"])
    directive["source_review"] = pointer.model_dump(mode="json")
    directive["decision_sha256"] = content_sha256(
        {key: value for key, value in directive.items() if key != "decision_sha256"}
    )
    artifacts.results[(pointer.logical_artifact_id, pointer.revision_id)] = foreign
    step.input_pointer_manifest["review_correction_directive"] = directive

    with pytest.raises(ValueError, match="immutable pointer"):
        service._prompt_context(workflow, step, request, (authoring,), "packrel_" + "1" * 32)


@pytest.mark.parametrize("value", ("expected", "observed"))
def test_correction_recomputes_values_instead_of_trusting_even_self_hashed_directive(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    service, _, workflow, step, request, authoring, _ = _fixture(tmp_path, monkeypatch)
    directive = deepcopy(step.input_pointer_manifest["review_correction_directive"])
    directive["issue"][value]["structural_complexity_score"] = 8
    directive["decision_sha256"] = content_sha256(
        {key: data for key, data in directive.items() if key != "decision_sha256"}
    )
    step.input_pointer_manifest["review_correction_directive"] = directive

    with pytest.raises(ValueError, match="independently computed policy"):
        service._prompt_context(workflow, step, request, (authoring,), "packrel_" + "1" * 32)


@pytest.mark.parametrize("tampered_target", (False, True))
def test_escalated_correction_preserves_original_context_and_rejects_changed_target_pins(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, tampered_target: bool
) -> None:
    service, artifacts, workflow, step, request, authoring_pointer, _ = _fixture(
        tmp_path, monkeypatch
    )
    (tmp_path / "escalation").mkdir()
    graph = _knowledge_fixture(
        tmp_path / "escalation",
        monkeypatch,
        manifest_schema_version="5.0",
        workflow_definition_version="1.13.0",
    )
    authoring = ContentTeamAuthoringRoleResultV12.model_validate(
        artifacts.results[(authoring_pointer.logical_artifact_id, authoring_pointer.revision_id)]
    )
    score = structural_review_complexity(authoring)
    primary_data = _v12_review_document(
        graph,
        score=score,
        candidate_disposition="UNCERTAIN",
        reasons=("CANDIDATE_FINDING_PRESENT", "EVIDENCE_UNCERTAINTY"),
    )
    primary = ContentTeamReviewRoleResultV12.model_validate(primary_data)
    primary_pointer = _pointer(primary_data)
    escalation = build_review_escalation_directive(
        workflow_id=workflow.workflow_id,
        reviewed_authoring=authoring_pointer,
        source_review=primary_pointer,
        authoring_result=authoring,
        review_result=primary,
        plan_step=_v12_plan_review_step(),
    )
    assert escalation is not None
    invalid_data = _v12_review_document(
        graph,
        score=score + 1,
        candidate_disposition="DEMOTED",
        review_pass="ESCALATED",
        reasons=escalation.reason_codes,
        source_review=primary_pointer,
    )
    invalid_data["job_id"] = "job_" + "9" * 32
    invalid_data["artifact"]["logical_artifact_id"] = "artifact_" + "9" * 32
    invalid_data["artifact"]["revision_id"] = "rev_" + "9" * 32
    if tampered_target:
        invalid_data["output"]["independent_review_report"]["verification_targets"][0][
            "verification_terms"
        ] = ["changed_target"]
    source_pointer = _pointer(invalid_data, attempt=2)
    original_directive = WorkflowReviewCorrectionDirective.model_validate(
        step.input_pointer_manifest["review_correction_directive"]
    )
    expected = original_directive.issue.expected.model_copy(
        update={"decision": "COMPLETED", "reason_codes": escalation.reason_codes}
    )
    observed = original_directive.issue.observed.model_copy(
        update={"decision": "COMPLETED", "reason_codes": escalation.reason_codes}
    )
    correction = build_review_correction_directive(
        workflow_id=workflow.workflow_id,
        reviewed_authoring=authoring_pointer,
        source_review=source_pointer,
        review_pass="ESCALATED",
        pass_number=2,
        issue=original_directive.issue.model_copy(
            update={"expected": expected, "observed": observed}
        ),
    )
    step.attempt = 3
    step.input_pointer_manifest["review_escalation_directive"] = escalation.model_dump(mode="json")
    step.input_pointer_manifest["review_correction_directive"] = correction.model_dump(mode="json")
    step.input_pointer_manifest["upstream_artifacts"] = [
        authoring_pointer.model_dump(mode="json"),
        primary_pointer.model_dump(mode="json"),
    ]
    artifacts.results[(primary_pointer.logical_artifact_id, primary_pointer.revision_id)] = (
        primary_data
    )
    artifacts.results[(source_pointer.logical_artifact_id, source_pointer.revision_id)] = (
        invalid_data
    )

    if tampered_target:
        with pytest.raises(ValueError, match="verification target pins differ"):
            service._prompt_context(
                workflow, step, request, (authoring_pointer, primary_pointer), "packrel_" + "1" * 32
            )
        return
    context = service._prompt_context(
        workflow, step, request, (authoring_pointer, primary_pointer), "packrel_" + "1" * 32
    )

    assert json.loads(context["escalation"]["directive_json"]) == escalation.model_dump(mode="json")
    assert json.loads(context["escalation"]["source_review_result_json"]) == primary_data
    assert json.loads(context["review_correction"]["source_review_result_json"]) == invalid_data
    assert len(artifacts.loads) == len(set(artifacts.loads)) == 3
