from __future__ import annotations

from types import SimpleNamespace
from typing import cast

import pytest
from eom_catalog_service.artifacts import CatalogArtifactService
from eom_catalog_service.workflow_catalog import WorkflowCatalogService
from eom_identifiers import canonical_json_bytes, content_sha256, sha256_bytes
from eom_workflow import WorkflowRequest
from eom_workflow_runner.models import WorkflowInstanceRecord, WorkflowStepRunRecord


class _Artifacts:
    def __init__(self, prompt: bytes, envelope: bytes) -> None:
        self.prompt = prompt
        self.envelope = envelope
        self.calls: list[dict[str, object]] = []

    def load_rendered_prompt(self, **values: object) -> tuple[bytes, bytes]:
        self.calls.append(values)
        return self.prompt, self.envelope


def _fixture() -> tuple[
    WorkflowCatalogService,
    _Artifacts,
    WorkflowInstanceRecord,
    WorkflowStepRunRecord,
]:
    prompt = b"Review the immutable authoring result."
    pointer = {
        "artifact_id": "artifact_" + "1" * 32,
        "artifact_revision_id": "rev_" + "2" * 32,
        "sha256": sha256_bytes(prompt),
        "manifest_sha256": "sha256:" + "3" * 64,
        "schema_ref": "eom://schemas/content-pack/prompt-envelope-v1",
    }
    envelope: dict[str, object] = {
        "schema_version": "1.0",
        "pack_release_id": "packrel_" + "4" * 32,
        "pack_release_sha256": "sha256:" + "5" * 64,
        "profile_key": "generated-knowledge-review",
        "profile_version": "7.0.0",
        "profile_sha256": "sha256:" + "6" * 64,
        "template_path": "prompt-templates/review.md",
        "template_sha256": "sha256:" + "7" * 64,
        "render_context_sha256": "sha256:" + "8" * 64,
        "rendered_prompt_sha256": pointer["sha256"],
        "workflow_id": "workflow_" + "9" * 32,
        "step_run_id": "steprun_" + "a" * 32,
        "source_intake_batch_ids": [],
    }
    runtime_context = {
        "content_pack": {
            "release_id": envelope["pack_release_id"],
            "release_sha256": envelope["pack_release_sha256"],
        },
        "profiles": {
            "review": {
                "profile_key": envelope["profile_key"],
                "profile_version": envelope["profile_version"],
                "profile_sha256": envelope["profile_sha256"],
                "template_relative_path": envelope["template_path"],
            }
        },
        "source_intake": {"batch_ids": []},
        "prompt_artifacts": [{"step_key": "review", "attempt": 1, **pointer}],
    }
    workflow = cast(
        WorkflowInstanceRecord,
        SimpleNamespace(workflow_id=envelope["workflow_id"], runtime_context=runtime_context),
    )
    step = cast(
        WorkflowStepRunRecord,
        SimpleNamespace(
            step_run_id=envelope["step_run_id"],
            step_key="review",
            attempt=1,
            worker_role="review",
            input_pointer_manifest={"prompt": pointer, "prompt_envelope": envelope},
        ),
    )
    artifacts = _Artifacts(prompt, canonical_json_bytes(envelope))
    service = object.__new__(WorkflowCatalogService)
    service.artifacts = cast(CatalogArtifactService, artifacts)
    return service, artifacts, workflow, step


def test_prepare_prompt_reuses_the_exact_pinned_step_artifact() -> None:
    service, artifacts, workflow, step = _fixture()

    prepared = service.prepare_prompt(
        workflow=workflow,
        step=step,
        request=cast(WorkflowRequest, object()),
        upstream=(),
    )

    assert prepared.text == "Review the immutable authoring result."
    assert prepared.pointer == step.input_pointer_manifest["prompt"]
    assert prepared.envelope == step.input_pointer_manifest["prompt_envelope"]
    assert artifacts.calls == [
        {
            "artifact_id": "artifact_" + "1" * 32,
            "revision_id": "rev_" + "2" * 32,
            "prompt_sha256": sha256_bytes(artifacts.prompt),
            "manifest_sha256": "sha256:" + "3" * 64,
            "envelope_sha256": sha256_bytes(artifacts.envelope),
        }
    ]


def test_prepare_prompt_rejects_runtime_pointer_drift() -> None:
    service, artifacts, workflow, step = _fixture()
    workflow.runtime_context["prompt_artifacts"][0]["sha256"] = content_sha256(
        {"drift": True}
    )

    with pytest.raises(ValueError, match="not bound"):
        service.prepare_prompt(
            workflow=workflow,
            step=step,
            request=cast(WorkflowRequest, object()),
            upstream=(),
        )

    assert artifacts.calls == []
