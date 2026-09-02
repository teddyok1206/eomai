from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from eom_catalog_contracts import AssessmentPageImageInput, LegacyItemExtractionRequest
from eom_identifiers import content_sha256
from eom_workflow.compiler import compile_definition
from eom_workflow.models import (
    ArtifactPointer,
    ArtifactSpec,
    KnowledgeAnalysisWorkerRequest,
    LegacyItemExtractionWorkerRequest,
    RoleWorkerInput,
    WorkflowRequest,
)
from eom_workflow.schemas import (
    RESULT_SCHEMA_FILES,
    WorkflowSchemaError,
    constrained_result_schema,
    load_codex_result_schema,
    load_definition_schema,
    load_role_input_schema,
    load_role_result_schema,
    role_schema_bundle_hash,
    validate_codex_structured_output_schema,
    validate_role_input,
    validate_role_result,
    validate_schema_message,
)
from jsonschema import Draft202012Validator

JOB_ID = "job_0123456789abcdef0123456789abcdef"
WORKFLOW_ID = "workflow_0123456789abcdef0123456789abcdef"
STEP_RUN_ID = "steprun_0123456789abcdef0123456789abcdef"
ARTIFACT_ID = "artifact_0123456789abcdef0123456789abcdef"
REVISION_ID = "rev_0123456789abcdef0123456789abcdef"
ROOT = Path(__file__).resolve().parents[2]


def _input(role: str) -> RoleWorkerInput:
    upstream: tuple[ArtifactPointer, ...] = ()
    if role != "authoring":
        upstream = (
            ArtifactPointer(
                step_key="authoring",
                attempt=1,
                job_id=JOB_ID,
                logical_artifact_id=ARTIFACT_ID,
                revision_id=REVISION_ID,
                content_hash="sha256:" + "a" * 64,
                result_schema="authoring-result@1.0",
            ),
        )
    return RoleWorkerInput(
        job_id=JOB_ID,
        workflow_id=WORKFLOW_ID,
        step_run_id=STEP_RUN_ID,
        attempt=1,
        role=role,  # type: ignore[arg-type]
        request=WorkflowRequest(request_name="PLACEHOLDER_REQUEST", image_mode="required"),
        upstream_artifacts=upstream,
        artifact=ArtifactSpec(
            logical_artifact_id=ARTIFACT_ID,
            revision_id=REVISION_ID,
        ),
    )


def _result(role: str) -> dict[str, object]:
    outputs: dict[str, object] = {
        "authoring": {
            "draft": {"title": "PLACEHOLDER_CONTENT", "body": "PLACEHOLDER_CONTENT"},
            "metadata": {"domain": "placeholder"},
        },
        "image": {"image_spec": {"kind": "placeholder", "description": "PLACEHOLDER_IMAGE_SPEC"}},
        "review": {
            "review": {
                "decision": "ready_for_human",
                "findings": [],
                "summary": "PLACEHOLDER_REVIEW",
            }
        },
        "item_management": {
            "registration": {
                "result": "registered_placeholder",
                "summary": "PLACEHOLDER_REGISTRATION",
            }
        },
    }
    return {
        "schema_version": "1.0",
        "protocol_version": "workflow-role/1.0.1",
        "job_id": JOB_ID,
        "workflow_id": WORKFLOW_ID,
        "step_run_id": STEP_RUN_ID,
        "role": role,
        "status": "ok",
        "artifact": {
            "logical_artifact_id": ARTIFACT_ID,
            "revision_id": REVISION_ID,
            "file_name": "result.json",
            "media_type": "application/json",
        },
        "output": outputs[role],
        "completed_at": datetime(2026, 8, 15, tzinfo=UTC).isoformat().replace("+00:00", "Z"),
    }


def test_all_workflow_schemas_are_valid_draft_2020_12() -> None:
    Draft202012Validator.check_schema(load_definition_schema())
    for role in ("authoring", "image", "review", "item_management"):
        Draft202012Validator.check_schema(load_role_input_schema(role))
    Draft202012Validator.check_schema(load_role_input_schema("support", "workflow-role/1.4.0"))
    Draft202012Validator.check_schema(load_role_input_schema("support", "workflow-role/1.7.0"))
    Draft202012Validator.check_schema(load_role_input_schema("support", "workflow-role/1.8.0"))
    Draft202012Validator.check_schema(load_role_input_schema("support", "workflow-role/1.9.0"))
    Draft202012Validator.check_schema(load_role_input_schema("support", "workflow-role/1.10.0"))
    for schema_id in RESULT_SCHEMA_FILES:
        Draft202012Validator.check_schema(load_role_result_schema(schema_id))


def test_all_codex_result_projections_use_the_supported_strict_subset() -> None:
    for schema_id in RESULT_SCHEMA_FILES:
        projected = load_codex_result_schema(schema_id)
        Draft202012Validator.check_schema(projected)
        validate_codex_structured_output_schema(projected)
        assert "$schema" not in projected
        assert "$id" not in projected


@pytest.mark.parametrize("lookaround", ["(?=x)", "(?!x)", "(?<=x)", "(?<!x)"])
def test_codex_result_projection_rejects_regex_lookaround(lookaround: str) -> None:
    projected = load_codex_result_schema("legacy-item-extraction-result@1.0")
    artifact_pointer = projected["$defs"]["AssessmentItemContent_artifactPointer"]
    artifact_pointer["properties"]["artifact_member"]["pattern"] = f"^{lookaround}x$"

    with pytest.raises(WorkflowSchemaError, match="unsupported regex lookaround"):
        validate_codex_structured_output_schema(projected)


def test_legacy_extraction_codex_projection_rejects_empty_item_title() -> None:
    projected = load_codex_result_schema("legacy-item-extraction-result@1.0")
    item_content = projected["$defs"]["AssessmentItemContent"]
    title_reference = item_content["properties"]["title"]["$ref"]
    title_schema = projected["$defs"][title_reference.removeprefix("#/$defs/")]

    validator = Draft202012Validator(title_schema)
    assert not validator.is_valid("")
    assert validator.is_valid("원소 A")


def test_legacy_extraction_codex_projection_preserves_reachable_nonempty_strings() -> None:
    canonical = load_role_result_schema("legacy-item-extraction-result@1.0")
    projected = load_codex_result_schema("legacy-item-extraction-result@1.0")
    checked_paths: list[tuple[str | int, ...]] = []

    def visit(value: object, path: tuple[str | int, ...] = ()) -> None:
        if isinstance(value, dict):
            canonical_value: object = canonical
            for part in path:
                if isinstance(part, str):
                    if not isinstance(canonical_value, dict):
                        raise AssertionError(f"canonical schema path is not a mapping: {path}")
                    canonical_key = (
                        "oneOf" if part == "anyOf" and part not in canonical_value else part
                    )
                    canonical_value = canonical_value[canonical_key]
                else:
                    if not isinstance(canonical_value, list):
                        raise AssertionError(f"canonical schema path is not a sequence: {path}")
                    canonical_value = canonical_value[part]
            if (
                isinstance(canonical_value, dict)
                and canonical_value.get("type") == "string"
                and isinstance(canonical_value.get("minLength"), int)
                and canonical_value["minLength"] >= 1
            ):
                checked_paths.append(path)
                assert not Draft202012Validator(value).is_valid(""), path
            for key, child in value.items():
                visit(child, (*path, key))
        elif isinstance(value, list):
            for index, child in enumerate(value):
                visit(child, (*path, index))

    visit(projected)

    assert ("$defs", "AssessmentItemContent_text") in checked_paths
    assert len(checked_paths) == 16


@pytest.mark.parametrize(
    "member",
    ["/diagram.png", ".", "source/./diagram.png", "../diagram.png", "a//b", "a\\b"],
)
def test_codex_result_projection_rejects_unsafe_artifact_member(member: str) -> None:
    projected = load_codex_result_schema("legacy-item-extraction-result@1.0")
    artifact_pointer = projected["$defs"]["AssessmentItemContent_artifactPointer"]
    value = {
        "artifact_id": ARTIFACT_ID,
        "artifact_revision_id": REVISION_ID,
        "artifact_member": member,
        "sha256": "sha256:" + "a" * 64,
        "media_type": "image/png",
    }

    assert not Draft202012Validator(artifact_pointer).is_valid(value)


def test_codex_result_projection_rejects_a_property_without_an_explicit_type() -> None:
    projected = load_codex_result_schema("authoring-result@1.0")
    artifact = projected["$defs"]["artifact"]
    artifact["properties"]["file_name"] = {"const": "result.json"}

    with pytest.raises(
        WorkflowSchemaError,
        match=r"Codex result property has no explicit type at .*file_name",
    ):
        validate_codex_structured_output_schema(projected)


def test_codex_result_projection_rejects_reference_sibling_keywords() -> None:
    projected = load_codex_result_schema("knowledge-analysis-proposal-result@2.0")
    proposal = projected["$defs"]["KnowledgeAnalysisWorkerProposal"]
    anchor_ref = proposal["properties"]["anchors"]["items"]["$ref"]
    anchor = projected["$defs"][anchor_ref.removeprefix("#/$defs/")]
    anchor["properties"]["member_path"]["const"] = "source/original.pdf"

    with pytest.raises(
        WorkflowSchemaError,
        match=r"Codex result reference has sibling keywords at .*member_path",
    ):
        validate_codex_structured_output_schema(projected)


@pytest.mark.parametrize(
    ("role", "schema_id"),
    [
        ("authoring", "authoring-result@1.0"),
        ("image", "image-result@1.0"),
        ("review", "review-result@1.0"),
        ("item_management", "registration-result@1.0"),
    ],
)
def test_role_input_and_result_pass_schema_and_typed_validation(role: str, schema_id: str) -> None:
    worker_input = _input(role)
    assert validate_role_input(worker_input.model_dump(mode="json"), role) == worker_input
    parsed = validate_role_result(_result(role), role, schema_id)
    assert parsed.role == role


def test_constrained_result_schema_fixes_all_execution_identifiers() -> None:
    worker_input = _input("authoring")
    schema = constrained_result_schema("authoring-result@1.0", worker_input)
    validate_schema_message(schema, _result("authoring"), "constrained-result")
    properties = schema["properties"]
    assert properties["job_id"]["const"] == JOB_ID
    assert properties["workflow_id"]["const"] == WORKFLOW_ID
    assert properties["step_run_id"]["const"] == STEP_RUN_ID


def test_constrained_legacy_extraction_schema_resolves_nested_string_references() -> None:
    page = AssessmentPageImageInput.model_construct(
        page_input_id="assessmentpage_" + "1" * 32,
    )
    extraction_request = LegacyItemExtractionRequest.model_construct(
        extraction_request_id="itemextractreq_" + "2" * 32,
        request_sha256="sha256:" + "3" * 64,
        page_inputs=(page,),
        expected_item_numbers=(7,),
    )
    worker_input = RoleWorkerInput.model_construct(
        job_id=JOB_ID,
        workflow_id=WORKFLOW_ID,
        step_run_id=STEP_RUN_ID,
        attempt=1,
        role="support",
        request=LegacyItemExtractionWorkerRequest.model_construct(
            extraction_request=extraction_request,
        ),
        upstream_artifacts=(),
        artifact=ArtifactSpec(logical_artifact_id=ARTIFACT_ID, revision_id=REVISION_ID),
    )

    schema = constrained_result_schema("legacy-item-extraction-result@1.0", worker_input)
    properties = schema["$defs"]["LegacyItemExtractionResult"]["properties"]

    assert properties["extraction_request_id"]["const"] == extraction_request.extraction_request_id
    assert properties["request_sha256"] == {
        "type": "string",
        "pattern": "^sha256:[0-9a-f]{64}$",
        "const": extraction_request.request_sha256,
    }
    proposal = properties["items"]["items"]
    content_anchor_map = proposal["properties"]["content_anchor_map"]
    assert content_anchor_map["minItems"] == 2
    assert (
        'first mapping MUST use content_path exactly "title"' in content_anchor_map["description"]
    )
    assert (
        'later mapping MUST use a content_path beginning with "body["'
        in content_anchor_map["description"]
    )
    artifact_member_pattern = schema["$defs"]["AssessmentItemContent_artifactPointer"][
        "properties"
    ]["artifact_member"]["pattern"]
    assert not any(token in artifact_member_pattern for token in ("(?=", "(?!", "(?<=", "(?<!"))
    validate_codex_structured_output_schema(schema)


def test_constrained_knowledge_analysis_schema_fixes_request_identity() -> None:
    request = KnowledgeAnalysisWorkerRequest.model_validate(
        {"analysis_request": _knowledge_analysis_request()}
    )
    worker_input = RoleWorkerInput(
        job_id=JOB_ID,
        workflow_id=WORKFLOW_ID,
        step_run_id=STEP_RUN_ID,
        attempt=1,
        role="support",
        request=request,
        upstream_artifacts=(),
        artifact=ArtifactSpec(logical_artifact_id=ARTIFACT_ID, revision_id=REVISION_ID),
    )
    schema = constrained_result_schema("knowledge-analysis-proposal-result@1.0", worker_input)
    proposal = schema["$defs"]["KnowledgeAnalysisWorkerProposal"]
    assert proposal["properties"]["analysis_request_id"]["const"] == (
        "knowledgeanalysis_" + "1" * 32
    )
    anchor_ref = proposal["properties"]["anchors"]["items"]["$ref"]
    anchor = schema["$defs"][anchor_ref.removeprefix("#/$defs/")]
    assert anchor["properties"]["artifact_revision_id"]["const"] == "rev_" + "5" * 32
    assert anchor["properties"]["member_path"]["const"] == "source.pdf"
    assert anchor["properties"]["member_path"]["type"] == "string"
    assert "$ref" not in anchor["properties"]["member_path"]
    result = _knowledge_analysis_result()
    result["output"]["proposal"]["analysis_request_id"] = "knowledgeanalysis_" + "2" * 32  # type: ignore[index]
    errors = list(Draft202012Validator(schema).iter_errors(result))
    assert any(
        list(error.absolute_path) == ["output", "proposal", "analysis_request_id"]
        for error in errors
    )


@pytest.mark.parametrize(
    ("field", "invalid_value"),
    [
        ("artifact_revision_id", "rev_" + "0" * 32),
        ("member_path", "source/staged-index.md"),
    ],
)
def test_constrained_knowledge_analysis_schema_rejects_unpinned_anchor_source(
    field: str, invalid_value: str
) -> None:
    request = KnowledgeAnalysisWorkerRequest.model_validate(
        {"analysis_request": _knowledge_analysis_request()}
    )
    worker_input = RoleWorkerInput(
        job_id=JOB_ID,
        workflow_id=WORKFLOW_ID,
        step_run_id=STEP_RUN_ID,
        attempt=1,
        role="support",
        request=request,
        upstream_artifacts=(),
        artifact=ArtifactSpec(logical_artifact_id=ARTIFACT_ID, revision_id=REVISION_ID),
    )
    schema = constrained_result_schema("knowledge-analysis-proposal-result@1.0", worker_input)
    result = _knowledge_analysis_result()
    result["output"]["proposal"]["anchors"][0][field] = invalid_value  # type: ignore[index]

    errors = list(Draft202012Validator(schema).iter_errors(result))

    assert any(
        list(error.absolute_path) == ["output", "proposal", "anchors", 0, field]
        and error.validator == "const"
        for error in errors
    )


def test_role_schema_bundle_hash_is_canonical() -> None:
    first = role_schema_bundle_hash()
    assert first == role_schema_bundle_hash()
    assert first.startswith("sha256:")
    assert role_schema_bundle_hash("workflow-role/1.2.0") == (
        "sha256:09c325824484d1bbcb46e14fa3007aa2b51f9750235a1969dee67b2b795d60f4"
    )
    assert role_schema_bundle_hash("workflow-role/1.3.0") == (
        "sha256:dce3e0921cf2d0d236f813101406286cb86cabaef07c95030f05028fad664ab8"
    )
    assert role_schema_bundle_hash("workflow-role/1.4.0") == (
        "sha256:c385885dc445cee96ae8f0c2a122678c3db68f9b10d8162c7695108fbcc47b4b"
    )
    assert role_schema_bundle_hash("workflow-role/1.5.0") == (
        "sha256:92bfb56d96282e622a008ce4216d7dc03badea391e33dd3fd9a89c1f6d3255c9"
    )
    assert role_schema_bundle_hash("workflow-role/1.6.0") == (
        "sha256:089f00931b2e32a39d472f9481bd50d1d641255c0bce9e9dd1c74a5c13df9878"
    )
    assert role_schema_bundle_hash("workflow-role/1.7.0") == (
        "sha256:c3c13aef2f797fe255d7ca141ad374069b0e2c000314292ba68b99479f525058"
    )
    assert role_schema_bundle_hash("workflow-role/1.8.0") == (
        "sha256:1b99d22abf59081d8843934571d33346d0d0083fcfb9a000c5683577dc8827cc"
    )
    assert role_schema_bundle_hash("workflow-role/1.9.0") == (
        "sha256:e70c0dbd4856aeabbbedac97552933d5edbd44221f0cb5e7f8763d315d14e207"
    )
    assert role_schema_bundle_hash("workflow-role/1.10.0") == (
        "sha256:3a224f960ae01574e25b44bd9a187ba60a98f0638ecb8c30d11de4fe8111ab43"
    )
    assert role_schema_bundle_hash("workflow-role/1.11.0") == (
        "sha256:db929999c19a251e80ae5df7e63f499b1180ed316ed853ab8f36a476b6b06c9f"
    )
    assert role_schema_bundle_hash("workflow-role/1.14.0") == (
        "sha256:204a5070a9c465dde25677688980463c1df8feba64673001e2477a11d9f69e54"
    )


def _unresolved_schema_references(schema: dict[str, object]) -> set[str]:
    unresolved: set[str] = set()

    def resolve(reference: str) -> None:
        if not reference.startswith("#/"):
            unresolved.add(reference)
            return
        current: object = schema
        for raw_token in reference[2:].split("/"):
            token = raw_token.replace("~1", "/").replace("~0", "~")
            if isinstance(current, dict) and token in current:
                current = current[token]
            elif isinstance(current, list) and token.isdigit() and int(token) < len(current):
                current = current[int(token)]
            else:
                unresolved.add(reference)
                return

    def visit(value: object) -> None:
        if isinstance(value, dict):
            reference = value.get("$ref")
            if isinstance(reference, str):
                resolve(reference)
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    visit(schema)
    return unresolved


def test_multimodal_protocol_v1_9_closes_historical_transitive_references() -> None:
    historical_input = load_role_input_schema("support", "workflow-role/1.8.0")
    historical_result = load_role_result_schema("knowledge-analysis-proposal-result@5.0")
    expected_historical_gap = {
        "#/$defs/AnalysisV3_documentDependencyPointer",
        "#/$defs/AnalysisV3_originalSourceMember",
    }
    assert _unresolved_schema_references(historical_input) == expected_historical_gap
    assert _unresolved_schema_references(historical_result) == expected_historical_gap

    corrected_input = load_role_input_schema("support", "workflow-role/1.9.0")
    corrected_result = load_role_result_schema("knowledge-analysis-proposal-result@6.0")
    assert _unresolved_schema_references(corrected_input) == set()
    assert _unresolved_schema_references(corrected_result) == set()

    typed_input = load_role_input_schema("support", "workflow-role/1.10.0")
    typed_result = load_role_result_schema("knowledge-analysis-proposal-result@7.0")
    assert _unresolved_schema_references(typed_input) == set()
    assert _unresolved_schema_references(typed_result) == set()

    stable_input = load_role_input_schema("support", "workflow-role/1.11.0")
    stable_result = load_role_result_schema("knowledge-analysis-proposal-result@8.0")
    assert _unresolved_schema_references(stable_input) == set()
    assert _unresolved_schema_references(stable_result) == set()


def _knowledge_analysis_request() -> dict[str, object]:
    value: dict[str, object] = {
        "schema_version": "knowledge-analysis-request/2.0",
        "predecessor_analysis_run_id": None,
        "analysis_request_id": "knowledgeanalysis_" + "1" * 32,
        "source": {
            "source_kind": "CONTENT_INTAKE_FILE",
            "source_class": "TEXTBOOK",
            "intake_batch_id": "intake_" + "2" * 32,
            "source_file_id": "sourcefile_" + "3" * 32,
            "lifecycle_state": "ELIGIBLE",
            "artifact_member": {
                "artifact_id": "artifact_" + "4" * 32,
                "artifact_revision_id": "rev_" + "5" * 32,
                "member_path": "source.pdf",
                "materialized_path": "source/source.pdf",
                "sha256": "sha256:" + "6" * 64,
                "bytes": 123,
                "schema_ref": None,
                "media_type": "application/pdf",
                "logical_name": "source.pdf",
            },
        },
        "execution_preset_id": "execpreset_" + "7" * 32,
        "execution_preset_revision_id": "execpresetrev_" + "8" * 32,
        "execution_preset_sha256": "sha256:" + "9" * 64,
        "worker_proposal_schema_ref": (
            "eom://schemas/knowledge/knowledge-analysis-worker-proposal/1.0"
        ),
        "accepted_result_schema_ref": "eom://schemas/knowledge/knowledge-analysis-result/2.0",
        "prior_graph_snapshot": None,
        "requested_outputs": [
            "NORMALIZED_MARKDOWN",
            "SOURCE_ANCHORS",
            "NODES",
            "EDGES",
            "CLAIMS",
            "COMPONENT_OBSERVATIONS",
            "UNRESOLVED_AMBIGUITIES",
        ],
        "general_knowledge_mode": "AUXILIARY_UNATTRIBUTED",
        "risk_policy_revision_id": "analysisriskrev_" + "a" * 32,
        "created_at": "2026-08-23T00:00:00Z",
    }
    value["request_sha256"] = content_sha256(value)
    return value


def _knowledge_analysis_result() -> dict[str, object]:
    return {
        "schema_version": "1.0",
        "protocol_version": "workflow-role/1.4.0",
        "job_id": JOB_ID,
        "workflow_id": WORKFLOW_ID,
        "step_run_id": STEP_RUN_ID,
        "status": "ok",
        "artifact": {
            "logical_artifact_id": ARTIFACT_ID,
            "revision_id": REVISION_ID,
            "file_name": "result.json",
            "media_type": "application/json",
        },
        "completed_at": "2026-08-23T00:00:00Z",
        "role": "support",
        "output": {
            "proposal": {
                "schema_version": "knowledge-analysis-worker-proposal/1.0",
                "analysis_request_id": "knowledgeanalysis_" + "1" * 32,
                "normalized_markdown": "# source\n",
                "anchors": [
                    {
                        "anchor_id": "anchor_source",
                        "artifact_revision_id": "rev_" + "5" * 32,
                        "member_path": "source.pdf",
                        "anchor_kind": "PAGE",
                        "locator": "page=1",
                        "excerpt_sha256": "sha256:" + "b" * 64,
                    }
                ],
                "nodes": [
                    {
                        "node_id": "knode_concept",
                        "node_type": "CONCEPT",
                        "stable_key": "concept.source",
                        "label": "source concept",
                        "anchor_ids": ["anchor_source"],
                    }
                ],
                "edges": [],
                "claims": [],
                "component_observations": [],
                "unresolved_ambiguities": [],
                "general_knowledge_used": False,
                "completed_at": "2026-08-23T00:00:00Z",
            }
        },
    }


def test_knowledge_analysis_support_protocol_is_schema_first_and_typed() -> None:
    worker_input = {
        "schema_version": "1.0",
        "protocol_version": "workflow-role/1.4.0",
        "job_id": JOB_ID,
        "workflow_id": WORKFLOW_ID,
        "step_run_id": STEP_RUN_ID,
        "attempt": 1,
        "role": "support",
        "request": {
            "request_name": "KNOWLEDGE_ANALYSIS_REQUEST",
            "analysis_request": _knowledge_analysis_request(),
        },
        "upstream_artifacts": [],
        "artifact": {
            "logical_artifact_id": ARTIFACT_ID,
            "revision_id": REVISION_ID,
            "file_name": "result.json",
            "media_type": "application/json",
        },
    }
    parsed_input = validate_role_input(worker_input, "support", "workflow-role/1.4.0")
    assert parsed_input.request.request_name == "KNOWLEDGE_ANALYSIS_REQUEST"
    parsed_result = validate_role_result(
        _knowledge_analysis_result(), "support", "knowledge-analysis-proposal-result@1.0"
    )
    assert parsed_result.role == "support"


def test_knowledge_analysis_codex_projection_rejects_empty_normalized_markdown() -> None:
    projected = load_codex_result_schema("knowledge-analysis-proposal-result@1.0")
    result = _knowledge_analysis_result()
    result["output"]["proposal"]["normalized_markdown"] = ""  # type: ignore[index]

    errors = sorted(
        Draft202012Validator(projected).iter_errors(result),
        key=lambda error: list(error.absolute_path),
    )

    assert len(errors) == 1
    assert list(errors[0].absolute_path) == ["output", "proposal", "normalized_markdown"]
    assert errors[0].validator == "pattern"


def test_knowledge_analysis_codex_projection_preserves_multiline_markdown() -> None:
    projected = load_codex_result_schema("knowledge-analysis-proposal-result@1.0")
    result = _knowledge_analysis_result()
    result["output"]["proposal"]["normalized_markdown"] = "# Source\n\nEvidence.\n"  # type: ignore[index]

    assert list(Draft202012Validator(projected).iter_errors(result)) == []


def test_knowledge_analysis_support_protocol_fails_closed_on_dangling_anchor() -> None:
    result = _knowledge_analysis_result()
    result["output"]["proposal"]["nodes"][0]["anchor_ids"] = ["anchor_missing"]  # type: ignore[index]
    with pytest.raises(WorkflowSchemaError, match="failed typed validation"):
        validate_role_result(result, "support", "knowledge-analysis-proposal-result@1.0")


def test_knowledge_analysis_workflow_is_single_support_step_and_immutable() -> None:
    compiled = compile_definition(ROOT / "config/workflows/knowledge-analysis.v1.yaml", {"support"})
    assert compiled.sha256 == (
        "sha256:786c7e7d2a65fc5dd30b47faff87c363646c2c1d9a44956e66deb46564accedf"
    )
    assert [step.key for step in compiled.definition.steps] == ["analyze", "complete"]
    assert compiled.definition.limits.max_rework_cycles == 0
    assert compiled.definition.limits.max_step_attempts == 1


def test_integrity_knowledge_analysis_workflow_is_additive_and_immutable() -> None:
    compiled = compile_definition(ROOT / "config/workflows/knowledge-analysis.v4.yaml", {"support"})
    assert compiled.sha256 == (
        "sha256:448a0ea91c17a074e3ee03af79534a1d94865a04d88c2da2da3d1ce0e2e90fba"
    )
    assert compiled.definition.definition_version == "4.0.0"
    analyze = compiled.definition.steps[0]
    assert analyze.type == "agent"
    assert analyze.result_schema == "knowledge-analysis-proposal-result@4.0"
    assert compiled.definition.limits.max_rework_cycles == 0
    assert compiled.definition.limits.max_step_attempts == 1


def test_multimodal_knowledge_analysis_workflow_is_additive_and_immutable() -> None:
    compiled = compile_definition(ROOT / "config/workflows/knowledge-analysis.v5.yaml", {"support"})
    assert compiled.sha256 == (
        "sha256:eeeae223ae7496f5a8d1489bab7c18737bf4c428ae7edbd5fafc4a9f9c8aa489"
    )
    assert compiled.definition.definition_version == "5.0.0"
    analyze = compiled.definition.steps[0]
    assert analyze.type == "agent"
    assert analyze.result_schema == "knowledge-analysis-proposal-result@5.0"
    assert compiled.definition.limits.max_rework_cycles == 0
    assert compiled.definition.limits.max_step_attempts == 1


def test_schema_closed_multimodal_workflow_is_additive_and_immutable() -> None:
    compiled = compile_definition(ROOT / "config/workflows/knowledge-analysis.v6.yaml", {"support"})
    assert compiled.sha256 == (
        "sha256:406c6014df943ccf9de723bdcf0816864b5575011a3e1dc4ece70fc61cfe0b70"
    )
    assert compiled.definition.definition_version == "6.0.0"
    analyze = compiled.definition.steps[0]
    assert analyze.type == "agent"
    assert analyze.result_schema == "knowledge-analysis-proposal-result@6.0"
    assert compiled.definition.limits.max_rework_cycles == 0
    assert compiled.definition.limits.max_step_attempts == 1


def test_typed_identity_multimodal_workflow_is_additive_and_immutable() -> None:
    compiled = compile_definition(ROOT / "config/workflows/knowledge-analysis.v7.yaml", {"support"})
    assert compiled.sha256 == (
        "sha256:8d02cea6befe17d8d93e89429f536545ffb4a483990f828132c6a82231531618"
    )
    assert compiled.definition.definition_version == "7.0.0"
    analyze = compiled.definition.steps[0]
    assert analyze.type == "agent"
    assert analyze.result_schema == "knowledge-analysis-proposal-result@7.0"
    assert compiled.definition.limits.max_rework_cycles == 0
    assert compiled.definition.limits.max_step_attempts == 1


def test_stable_identity_multimodal_workflow_is_additive_and_immutable() -> None:
    compiled = compile_definition(ROOT / "config/workflows/knowledge-analysis.v8.yaml", {"support"})
    assert compiled.sha256 == (
        "sha256:6a47199314fd59932efd416e016adbde7f1319edbc04591ab1bdc4f3a6bdf06b"
    )
    assert compiled.definition.definition_version == "8.0.0"
    analyze = compiled.definition.steps[0]
    assert analyze.type == "agent"
    assert analyze.result_schema == "knowledge-analysis-proposal-result@8.0"
    assert compiled.definition.limits.max_rework_cycles == 0
    assert compiled.definition.limits.max_step_attempts == 1


def test_completed_worker_error_result_preserves_invalid_result_semantics() -> None:
    result = _result("authoring")
    result["status"] = "error"

    with pytest.raises(WorkflowSchemaError, match=r"authoring-result@1\.0 at status"):
        validate_role_result(result, "authoring", "authoring-result@1.0")


def test_catalog_request_is_projected_to_the_worker_contract() -> None:
    request = WorkflowRequest.model_validate(
        {
            "request_name": "PLACEHOLDER_REQUEST",
            "image_mode": "skip",
            "content_pack": {
                "pack_key": "generic-placeholder",
                "environment": "development",
            },
            "profiles": {
                "authoring": "authoring-default",
                "review": "review-default",
                "image": "image-placeholder",
                "registration": "registration-default",
            },
            "source_intake": {"batch_ids": ["intake_" + "a" * 32]},
            "registry_intent": {"mode": "CREATE_ITEM"},
        }
    )
    assert request.worker_request().model_dump(mode="json") == {
        "request_name": "PLACEHOLDER_REQUEST",
        "image_mode": "skip",
    }
    worker_input = _input("authoring").model_dump(mode="json")
    worker_input["request"] = request.model_dump(mode="json")
    parsed = RoleWorkerInput.model_validate(worker_input)
    assert parsed.request.model_dump(mode="json") == {
        "request_name": "PLACEHOLDER_REQUEST",
        "image_mode": "skip",
    }
