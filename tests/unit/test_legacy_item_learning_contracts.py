from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest
from eom_catalog_contracts import (
    LegacyItemEditorialCompatibilityPolicy,
    LegacyItemEditorialCompatibilityProposal,
    LegacyItemEditorialCompatibilityRequest,
    LegacyItemEditorialCompatibilityResult,
    LegacyItemPromotionRequest,
    validate_contract,
)
from eom_catalog_service.legacy_item_editorial_validation import (
    LegacyItemEditorialDeterministicEvaluator,
)
from eom_identifiers import (
    canonical_json_bytes,
    content_sha256,
    item_origin_profile_id_for_revision,
    sha256_bytes,
)
from eom_orchestrator.legacy_item_editorial_compatibility_artifact import (
    stage_legacy_item_editorial_compatibility_proposal,
)
from eom_workflow.control_schemas import _control_schema_registry
from eom_workflow.models import (
    ArtifactSpec,
    LegacyItemEditorialCompatibilityRoleResult,
    LegacyItemEditorialCompatibilityWorkerRequest,
    RoleWorkerInput,
)
from eom_workflow.schemas import (
    constrained_result_schema,
    validate_role_input,
    validate_role_result,
)
from jsonschema import Draft202012Validator
from jsonschema import ValidationError as JsonSchemaValidationError
from pydantic import ValidationError
from sqlalchemy import create_engine


def _artifact(
    seed: str,
    member_path: str,
    schema_ref: str,
    media_type: str,
) -> dict[str, str]:
    return {
        "artifact_id": "artifact_" + seed * 32,
        "artifact_revision_id": "rev_" + seed * 32,
        "member_path": member_path,
        "schema_ref": schema_ref,
        "media_type": media_type,
        "sha256": "sha256:" + seed * 64,
    }


def _source() -> dict[str, object]:
    return {
        "item_id": "item_" + "1" * 32,
        "item_revision_id": "itemrev_" + "2" * 32,
        "item_manifest_sha256": "sha256:" + "3" * 64,
        "item_content": _artifact(
            "4",
            "item/item-content.json",
            "eom://schemas/item-registry/assessment-item-content-v2",
            "application/json",
        ),
        "extraction_acceptance_id": "itemacceptance_" + "5" * 32,
        "extraction_acceptance_sha256": "sha256:" + "6" * 64,
        "item_origin_profile_id": "originprofile_" + "7" * 32,
        "item_origin_profile_sha256": "sha256:" + "8" * 64,
        "lifecycle_state": "APPROVED",
    }


def _authorities() -> list[dict[str, object]]:
    return [
        {
            "authority_kind": "CONTENT_TEAM_PROMPT",
            "reference_key": "content-team-integrated-science-authoring-v05",
            "reference_revision": "5.0",
            "artifact_member": _artifact(
                "9",
                "references/guidance/content-team-authoring.md",
                "eom://schemas/guidance/eom-guidance-markdown-control/1.0",
                "text/markdown",
            ),
        },
        {
            "authority_kind": "HWP_QUESTION_EDITOR_PROFILE",
            "reference_key": "content-team-hwp-question-editor-handoff-v1",
            "reference_revision": "1.0",
            "artifact_member": _artifact(
                "a",
                "references/guidance/hwp-question-editor-handoff.md",
                "eom://schemas/guidance/eom-guidance-markdown-control/1.0",
                "text/markdown",
            ),
        },
    ]


def _renderer_profile() -> dict[str, object]:
    return {
        "renderer_profile": "content-team-hwp-question-editor-v1",
        "artifact_id": "artifact_" + "d" * 32,
        "artifact_revision_id": "rev_" + "e" * 32,
        "archive_member_path": "handoff-source.zip",
        "archive_schema_ref": "eom://schemas/hwpx/content-team-handoff-archive/1.0",
        "archive_media_type": "application/zip",
        "archive_sha256": "sha256:" + "1" * 64,
        "profile_sha256": "sha256:" + "2" * 64,
    }


def _request() -> dict[str, object]:
    value: dict[str, object] = {
        "schema_version": "legacy-item-editorial-compatibility-request/1.0",
        "compatibility_request_id": "editorialcompatreq_" + "b" * 32,
        "predecessor_compatibility_run_id": None,
        "source": _source(),
        "authorities": _authorities(),
        "renderer_profile": _renderer_profile(),
        "compatibility_policy_revision_id": "editorialcompatpolicyrev_" + "c" * 32,
        "compatibility_policy_sha256": "sha256:" + "d" * 64,
        "requested_checks": [
            "CONTENT_CONTRACT",
            "MARKDOWN_PROJECTION",
            "HWPX_RENDERABILITY",
            "LOSSLESSNESS",
        ],
        "created_at": "2026-09-03T00:00:00Z",
    }
    value["request_sha256"] = content_sha256(value)
    return value


def _policy() -> dict[str, object]:
    value: dict[str, object] = {
        "schema_version": "legacy-item-editorial-compatibility-policy/1.0",
        "compatibility_policy_revision_id": "editorialcompatpolicyrev_" + "c" * 32,
        "state": "RELEASED",
        "required_authorities": [
            "CONTENT_TEAM_PROMPT",
            "HWP_QUESTION_EDITOR_PROFILE",
        ],
        "required_checks": [
            "CONTENT_CONTRACT",
            "MARKDOWN_PROJECTION",
            "HWPX_RENDERABILITY",
            "LOSSLESSNESS",
        ],
        "maximum_issue_count": 128,
        "maximum_result_bytes": 262144,
        "automatic_retry": False,
        "close_compatible_tuple": True,
        "released_at": "2026-09-03T00:00:00Z",
        "released_by": "operator_contract_reviewer",
    }
    value["content_sha256"] = content_sha256(value)
    return value


def _checks(outcome: str = "PASS") -> list[dict[str, object]]:
    return [
        {
            "check_kind": kind,
            "outcome": outcome,
            "validator_key": f"content-team.{kind.lower().replace('_', '-')}",
            "validator_revision": "1.0",
            "evidence_sha256": "sha256:" + character * 64,
        }
        for kind, character in zip(
            (
                "CONTENT_CONTRACT",
                "MARKDOWN_PROJECTION",
                "HWPX_RENDERABILITY",
                "LOSSLESSNESS",
            ),
            "ef01",
            strict=True,
        )
    ]


def _result(*, compatible: bool = True) -> dict[str, object]:
    request = _request()
    authorities = deepcopy(request["authorities"])
    assert isinstance(authorities, list)
    issues: list[dict[str, object]] = []
    if not compatible:
        prompt = authorities[0]
        assert isinstance(prompt, dict)
        member = prompt["artifact_member"]
        assert isinstance(member, dict)
        issues.append(
            {
                "issue_id": "editorialissue_" + "2" * 32,
                "authority_kind": "CONTENT_TEAM_PROMPT",
                "authority_artifact_revision_id": member["artifact_revision_id"],
                "authority_sha256": member["sha256"],
                "rule_locator": "section:reviewed-rule",
                "category": "CONTENT_CONTRACT",
                "severity": "ADAPTATION_REQUIRED",
                "item_content_paths": ["body.0"],
                "observation": "검토 대상 표현이 권위 문서의 규칙과 다르다.",
                "required_adaptation": "권위 문서가 지정한 표현으로 검토한다.",
            }
        )
    value: dict[str, object] = {
        "schema_version": "legacy-item-editorial-compatibility-result/1.0",
        "compatibility_result_id": "editorialcompatresult_" + "3" * 32,
        "compatibility_request_id": request["compatibility_request_id"],
        "request_sha256": request["request_sha256"],
        "source": deepcopy(request["source"]),
        "authorities": authorities,
        "renderer_profile": deepcopy(request["renderer_profile"]),
        "proposal_artifact": _artifact(
            "f",
            "editorial/proposal.json",
            ("eom://schemas/legacy-assessment/legacy-item-editorial-compatibility-proposal/1.0"),
            "application/json",
        ),
        "proposal_sha256": "sha256:" + "f" * 64,
        "status": "COMPATIBLE" if compatible else "NEEDS_ADAPTATION",
        "issues": issues,
        "deterministic_checks": _checks(),
        "lossless_projection": compatible,
        "convergence_state": "CLOSED" if compatible else "OPEN",
        "completed_at": "2026-09-03T00:05:00Z",
    }
    value["result_sha256"] = content_sha256(value)
    return value


def _proposal(*, compatible: bool = True) -> dict[str, object]:
    result = _result(compatible=compatible)
    value: dict[str, object] = {
        "schema_version": "legacy-item-editorial-compatibility-proposal/1.0",
        "compatibility_request_id": result["compatibility_request_id"],
        "request_sha256": result["request_sha256"],
        "source": deepcopy(result["source"]),
        "authorities": deepcopy(result["authorities"]),
        "renderer_profile": deepcopy(result["renderer_profile"]),
        "status": result["status"],
        "issues": deepcopy(result["issues"]),
        "completed_at": result["completed_at"],
    }
    value["proposal_sha256"] = content_sha256(value)
    return value


def test_editorial_compatibility_request_validates_in_both_contract_layers() -> None:
    value = _request()

    validate_contract("legacy-item-editorial-compatibility-request", value)
    parsed = LegacyItemEditorialCompatibilityRequest.model_validate(value)

    assert parsed.source.lifecycle_state == "APPROVED"
    assert tuple(item.authority_kind for item in parsed.authorities) == (
        "CONTENT_TEAM_PROMPT",
        "HWP_QUESTION_EDITOR_PROFILE",
    )


def test_execution_plan_registry_resolves_editorial_compatibility_request() -> None:
    resource = _control_schema_registry().get(
        "eom://schemas/legacy-assessment/legacy-item-editorial-compatibility-request/1.0"
    )

    assert resource is not None
    Draft202012Validator(resource.contents).validate(_request())


def test_compatibility_policy_contains_only_lifecycle_bounds_and_team_authorities() -> None:
    value = _policy()

    validate_contract("legacy-item-editorial-compatibility-policy", value)
    parsed = LegacyItemEditorialCompatibilityPolicy.model_validate(value)

    assert parsed.automatic_retry is False
    assert parsed.close_compatible_tuple is True
    assert parsed.required_authorities == (
        "CONTENT_TEAM_PROMPT",
        "HWP_QUESTION_EDITOR_PROFILE",
    )


def test_compatible_exact_tuple_closes_without_editorial_issues() -> None:
    value = _result()

    validate_contract("legacy-item-editorial-compatibility-result", value)
    parsed = LegacyItemEditorialCompatibilityResult.model_validate(value)

    assert parsed.status == "COMPATIBLE"
    assert parsed.convergence_state == "CLOSED"
    assert parsed.issues == ()


def test_noncompatible_tuple_stays_open_with_exact_authority_pointer() -> None:
    value = _result(compatible=False)

    validate_contract("legacy-item-editorial-compatibility-result", value)
    parsed = LegacyItemEditorialCompatibilityResult.model_validate(value)

    assert parsed.status == "NEEDS_ADAPTATION"
    assert parsed.convergence_state == "OPEN"
    assert parsed.issues[0].authority_kind == "CONTENT_TEAM_PROMPT"


def test_worker_proposal_cannot_claim_server_owned_deterministic_checks() -> None:
    value = _proposal()

    validate_contract("legacy-item-editorial-compatibility-proposal", value)
    parsed = LegacyItemEditorialCompatibilityProposal.model_validate(value)

    assert parsed.status == "COMPATIBLE"
    assert "deterministic_checks" not in type(parsed).model_fields


def test_request_rejects_authority_order_or_stale_self_hash() -> None:
    value = _request()
    authorities = value["authorities"]
    assert isinstance(authorities, list)
    authorities.reverse()

    with pytest.raises(ValidationError, match="ordered content-team authorities"):
        LegacyItemEditorialCompatibilityRequest.model_validate(value)


def test_result_rejects_issue_that_is_not_bound_to_its_authority_revision() -> None:
    value = _result(compatible=False)
    issues = value["issues"]
    assert isinstance(issues, list)
    issue = issues[0]
    assert isinstance(issue, dict)
    issue["authority_sha256"] = "sha256:" + "f" * 64
    value["result_sha256"] = content_sha256(
        {key: item for key, item in value.items() if key != "result_sha256"}
    )

    with pytest.raises(ValidationError, match="exact authority revision"):
        LegacyItemEditorialCompatibilityResult.model_validate(value)


def test_compatible_result_rejects_a_failed_deterministic_check() -> None:
    value = _result()
    checks = value["deterministic_checks"]
    assert isinstance(checks, list)
    check = checks[-1]
    assert isinstance(check, dict)
    check["outcome"] = "FAIL"
    value["result_sha256"] = content_sha256(
        {key: item for key, item in value.items() if key != "result_sha256"}
    )

    with pytest.raises(JsonSchemaValidationError):
        validate_contract("legacy-item-editorial-compatibility-result", value)
    with pytest.raises(ValidationError, match="issue-free, lossless, and pass checks"):
        LegacyItemEditorialCompatibilityResult.model_validate(value)


def test_compatible_result_requires_every_deterministic_check_to_pass() -> None:
    value = _result()
    checks = value["deterministic_checks"]
    assert isinstance(checks, list) and isinstance(checks[2], dict)
    checks[2]["outcome"] = "NOT_APPLICABLE"
    value["result_sha256"] = content_sha256(
        {key: item for key, item in value.items() if key != "result_sha256"}
    )

    with pytest.raises(JsonSchemaValidationError):
        validate_contract("legacy-item-editorial-compatibility-result", value)
    with pytest.raises(ValidationError, match="issue-free, lossless, and pass checks"):
        LegacyItemEditorialCompatibilityResult.model_validate(value)


def test_v1_legacy_item_never_closes_without_lossless_content_team_projection() -> None:
    item = {
        "schema_version": "1.0",
        "locale": "ko-KR",
        "title": "검토할 문항",
        "body": [
            {
                "block_id": "block_stem",
                "type": "paragraph",
                "purpose": "stem",
                "text": "자료를 보고 옳은 답을 고르시오.",
            }
        ],
        "interaction": {
            "type": "single_choice",
            "choices": [
                {"choice_id": f"choice_{index}", "label": str(index), "text": f"선지 {index}"}
                for index in range(1, 6)
            ],
        },
        "solution": {
            "correct_choice_ids": ["choice_1"],
            "accepted_answers": [],
            "explanation": "검토된 해설",
            "authoring_intent": "자료 해석을 확인한다.",
            "statement_explanations": [],
        },
        "score": {"points": 2},
    }
    item_bytes = canonical_json_bytes(item)
    request_value = _request()
    source = request_value["source"]
    assert isinstance(source, dict)
    pointer = source["item_content"]
    assert isinstance(pointer, dict)
    pointer["schema_ref"] = "eom://schemas/item-registry/assessment-item-content-v1"
    pointer["sha256"] = sha256_bytes(item_bytes)
    request_value["request_sha256"] = content_sha256(
        {key: value for key, value in request_value.items() if key != "request_sha256"}
    )
    request = LegacyItemEditorialCompatibilityRequest.model_validate(request_value)

    class FakeArtifacts:
        def read_member(self, **_: object) -> bytes:
            return item_bytes

    evaluator = LegacyItemEditorialDeterministicEvaluator(
        create_engine("sqlite+pysqlite:///:memory:"),
        artifacts=FakeArtifacts(),  # type: ignore[arg-type]
    )
    assessment = evaluator.evaluate(request)

    assert tuple(check.outcome for check in assessment.checks) == (
        "PASS",
        "FAIL",
        "NOT_APPLICABLE",
        "FAIL",
    )
    assert assessment.lossless_projection is False


def test_exact_request_replay_is_stable_and_changed_authority_is_a_new_key() -> None:
    original = LegacyItemEditorialCompatibilityRequest.model_validate(_request())
    replay = LegacyItemEditorialCompatibilityRequest.model_validate(_request())
    changed_value = _request()
    authorities = changed_value["authorities"]
    assert isinstance(authorities, list)
    profile = authorities[1]
    assert isinstance(profile, dict)
    profile["reference_revision"] = "1.1"
    member = profile["artifact_member"]
    assert isinstance(member, dict)
    member["artifact_revision_id"] = "rev_" + "f" * 32
    member["sha256"] = "sha256:" + "f" * 64
    changed_value["request_sha256"] = content_sha256(
        {key: item for key, item in changed_value.items() if key != "request_sha256"}
    )
    changed = LegacyItemEditorialCompatibilityRequest.model_validate(changed_value)

    assert original.request_sha256 == replay.request_sha256
    assert changed.request_sha256 != original.request_sha256


def test_legacy_item_promotion_request_is_schema_valid_and_replay_stable() -> None:
    value: dict[str, object] = {
        "schema_version": "legacy-item-promotion-request/1.0",
        "acceptance_id": "itemacceptance_" + "1" * 32,
        "acceptance_sha256": "sha256:" + "2" * 64,
        "item_proposal_id": "itemproposal_" + "3" * 32,
        "item_number": 7,
        "content_pack_release_id": "packrel_" + "4" * 32,
        "primary_taxonomy_ref": None,
        "difficulty_band": None,
        "requested_by": "operator_legacy_promotion",
        "idempotency_key": "legacy-promotion-test-0001",
    }
    value["request_sha256"] = content_sha256(value)

    validate_contract("legacy-item-promotion-request", value)
    request = LegacyItemPromotionRequest.model_validate(value)

    assert request.request_sha256 == content_sha256(
        request.model_dump(mode="json", exclude={"request_sha256"})
    )
    assert item_origin_profile_id_for_revision("itemrev_" + "5" * 32) == (
        item_origin_profile_id_for_revision("itemrev_" + "5" * 32)
    )


def _compatibility_worker_input() -> RoleWorkerInput:
    request = LegacyItemEditorialCompatibilityRequest.model_validate(_request())
    return RoleWorkerInput(
        protocol_version="workflow-role/1.16.0",
        job_id="job_" + "1" * 32,
        workflow_id="workflow_" + "2" * 32,
        step_run_id="steprun_" + "3" * 32,
        attempt=1,
        role="support",
        request=LegacyItemEditorialCompatibilityWorkerRequest(compatibility_request=request),
        upstream_artifacts=(),
        artifact=ArtifactSpec(
            logical_artifact_id="artifact_" + "4" * 32,
            revision_id="rev_" + "5" * 32,
        ),
    )


def _compatibility_role_result() -> dict[str, object]:
    worker_input = _compatibility_worker_input()
    return {
        "schema_version": "1.0",
        "protocol_version": "workflow-role/1.16.0",
        "job_id": worker_input.job_id,
        "workflow_id": worker_input.workflow_id,
        "step_run_id": worker_input.step_run_id,
        "status": "ok",
        "artifact": worker_input.artifact.model_dump(mode="json"),
        "completed_at": "2026-09-03T00:05:00Z",
        "role": "support",
        "output": {"proposal": _proposal()},
    }


def test_editorial_compatibility_role_protocol_is_closed_and_request_bound() -> None:
    worker_input = _compatibility_worker_input()
    document = worker_input.model_dump(mode="json")

    assert validate_role_input(document, "support", "workflow-role/1.16.0") == worker_input
    schema = constrained_result_schema(
        "legacy-item-editorial-compatibility-result@1.0", worker_input
    )
    result = _compatibility_role_result()
    errors = tuple(Draft202012Validator(schema).iter_errors(result))
    assert errors == ()
    parsed = validate_role_result(
        result,
        "support",
        "legacy-item-editorial-compatibility-result@1.0",
    )
    assert isinstance(parsed, LegacyItemEditorialCompatibilityRoleResult)
    assert isinstance(
        worker_input.request,
        LegacyItemEditorialCompatibilityWorkerRequest,
    )
    assert parsed.output.proposal.request_sha256 == (
        worker_input.request.compatibility_request.request_sha256
    )

    proposal = result["output"]
    assert isinstance(proposal, dict)
    proposal_value = proposal["proposal"]
    assert isinstance(proposal_value, dict)
    source = proposal_value["source"]
    assert isinstance(source, dict)
    source["item_id"] = "item_" + "f" * 32
    assert tuple(Draft202012Validator(schema).iter_errors(result))


def test_editorial_proposal_staging_keeps_self_hash_separate_from_artifact_hash(
    tmp_path: Path,
) -> None:
    request = LegacyItemEditorialCompatibilityRequest.model_validate(_request())
    proposal = LegacyItemEditorialCompatibilityProposal.model_validate(_proposal())

    staged = stage_legacy_item_editorial_compatibility_proposal(
        proposal=proposal,
        request=request,
        job_id="job_" + "1" * 32,
        logical_artifact_id="artifact_" + "2" * 32,
        revision_id="rev_" + "3" * 32,
        staging=tmp_path,
    )

    artifact_hash = sha256_bytes(canonical_json_bytes(proposal.model_dump(mode="json")))
    assert staged.primary_hash == artifact_hash
    assert staged.primary_hash != proposal.proposal_sha256
    assert staged.manifest["primary_file"] == "result.json"
    assert staged.manifest["artifact_type"] == ("legacy-item-editorial-compatibility-proposal")


def test_editorial_proposal_staging_rejects_renderer_profile_drift(tmp_path: Path) -> None:
    request = LegacyItemEditorialCompatibilityRequest.model_validate(_request())
    value = _proposal()
    renderer = value["renderer_profile"]
    assert isinstance(renderer, dict)
    renderer["profile_sha256"] = "sha256:" + "3" * 64
    value["proposal_sha256"] = content_sha256(
        {key: item for key, item in value.items() if key != "proposal_sha256"}
    )
    proposal = LegacyItemEditorialCompatibilityProposal.model_validate(value)

    with pytest.raises(RuntimeError, match="pinned request"):
        stage_legacy_item_editorial_compatibility_proposal(
            proposal=proposal,
            request=request,
            job_id="job_" + "1" * 32,
            logical_artifact_id="artifact_" + "2" * 32,
            revision_id="rev_" + "3" * 32,
            staging=tmp_path,
        )
