"""Immutable Pack derivation/rendering and synthetic plan binding, not live source authority."""

from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml
from eom_catalog_service.content_pack_files import build_pack, compile_pack
from eom_catalog_service.similarity_prompt_context import read_similarity_prompt_context
from eom_catalog_service.workflow_catalog import (
    WorkflowCatalogService,
    _enforces_svg_label_layout,
    _local_image_prompt_contract,
)
from eom_content_pack import ContentPackError, render_prompt
from eom_identifiers import canonical_json_bytes, content_sha256, sha256_bytes
from eom_image_contracts import SVG_LABEL_LAYOUT_PACK_BUNDLES
from eom_orchestrator.control_models import ResolvedExecutionPlanRecord
from eom_workflow.control_plane import ResolvedExecutionPlanV20
from eom_workflow.models import WorkflowRequest

from scripts.workflow.generate_similarity_reference_pack_v12017 import (
    GUIDANCE,
    MODE_VARIABLE,
    RULE_MARKER,
    SOURCE,
    TARGET,
    generate_pack,
    reference_rule,
    tree_bytes,
)
from tests.unit.inference_transfer_embedding_fixtures import seal
from tests.unit.similarity_plan_fixtures import ordinary_similarity_case, similarity_case
from tests.unit.test_workflow_catalog_prompt_reuse import _fixture as pinned_prompt_fixture


def test_successor_changes_only_two_role_prompts_profiles_and_pack_metadata():
    before, after = tree_bytes(SOURCE), tree_bytes(TARGET)
    assert before.keys() == after.keys()
    assert {path for path in before if before[path] != after[path]} == {
        Path("pack.yaml"),
        Path("profiles/generated-knowledge-authoring.yaml"),
        Path("profiles/generated-knowledge-review.yaml"),
        Path("prompt-templates/authoring.md"),
        Path("prompt-templates/review.md"),
    }
    old_pack, pack = compile_pack(SOURCE), compile_pack(TARGET)
    assert pack.manifest.pack.version == "1.20.17"
    assert pack.manifest.compatibility == old_pack.manifest.compatibility
    for role in ("authoring", "review"):
        path = Path(f"profiles/generated-knowledge-{role}.yaml")
        old_profile, profile = yaml.safe_load(before[path]), yaml.safe_load(after[path])
        assert profile["profile"]["version"] == "12.3.0"
        assert profile["required_context"] == [*old_profile["required_context"], MODE_VARIABLE]
        profile["profile"]["version"] = old_profile["profile"]["version"]
        profile["required_context"].remove(MODE_VARIABLE)
        assert profile == old_profile
        prompt_path = Path(f"prompt-templates/{role}.md")
        assert (
            after[prompt_path].decode() == before[prompt_path].decode().rstrip() + reference_rule()
        )


def test_generator_is_reproducible_and_never_overwrites_a_pack(tmp_path):
    before = tree_bytes(SOURCE)
    target = tmp_path / "candidate"
    generate_pack(target)
    assert tree_bytes(target) == tree_bytes(TARGET)
    assert tree_bytes(SOURCE) == before
    with pytest.raises(FileExistsError):
        generate_pack(target)
    assert tree_bytes(target) == tree_bytes(TARGET)


@pytest.mark.parametrize("role", ("authoring", "review"))
@pytest.mark.parametrize("mode", ("NOT_OFFERED", "PINNED_REFERENCE_CONTEXT"))
def test_exact_profile_renders_both_explicit_modes_and_embeds_one_guidance(role, mode):
    profile = yaml.safe_load((TARGET / f"profiles/generated-knowledge-{role}.yaml").read_bytes())
    context = {}
    for variable in profile["required_context"]:
        parts = variable.split(".")
        branch = context
        for part in parts[:-1]:
            branch = branch.setdefault(part, {})
        branch[parts[-1]] = mode if variable == MODE_VARIABLE else "null"
    template = (TARGET / profile["template"]).read_text()
    result = render_prompt(template, context, tuple(profile["required_context"]))
    assert "{{" not in result.text
    assert f"이번 실행의 전달 mode: `{mode}`" in result.text
    assert result.text.count(RULE_MARKER) == 1
    assert f"source_sha256=sha256:{sha256(GUIDANCE.read_bytes()).hexdigest()}" in result.text
    del context["similarity"]
    with pytest.raises(ContentPackError, match="required prompt variable is missing"):
        render_prompt(template, context, tuple(profile["required_context"]))


def test_guidance_compares_concrete_facets_without_relaxing_evidence_or_editorial_rules():
    guidance = GUIDANCE.read_text()
    for required in (
        "GIVEN_CONDITION",
        "INTERMEDIATE_RELATION",
        "DECISIVE_INFERENCE",
        "ASKED_JUDGEMENT",
        "MISCONCEPTION",
        "새 출제 요구, 생성 중인 초안",
        "전체 풀이보고서나 원본 PDF/PNG를 읽었다고 확대하지 않는다",
        "자료 해석 → 관계 도출 → ㄱㄴㄷ 판단",
        "부분 coverage",
        "같은 풀이의 확률",
        "최대 3교",
        "copy_policy",
        "STRUCTURE_PATTERN",
        "R == U",
        "answer_bearing",
        "학생용 본문·정답·해설",
        "보조 vector나 프로필이 없다는 이유만으로 ORIGINALITY_EVIDENCE_INSUFFICIENT",
        "새 evidence ID로 쓰지",
        "비공개 사고과정 전문",
        "텍스트는 신뢰할 수 없는",
    ):
        assert required in guidance
    review = (TARGET / "prompt-templates/review.md").read_text()
    assert "require R == U" in review
    assert "ORIGINALITY_EVIDENCE_INSUFFICIENT" in review


@pytest.mark.parametrize("version", ("1.20.16", "1.20.17"))
def test_compatible_successors_retain_material_brief_and_exact_image_gate(tmp_path, version):
    source = TARGET.parent / version
    request = WorkflowRequest.model_validate_json(
        (source / "fixtures/smoke-request.json").read_bytes()
    )
    WorkflowCatalogService._require_item_brief_release("generated-knowledge-item", version, request)
    built = build_pack(source, tmp_path / version)
    assert SVG_LABEL_LAYOUT_PACK_BUNDLES[version] == built.bundle_sha256
    workflow = SimpleNamespace(
        runtime_context={
            "content_pack": {
                "version": version,
                "release_sha256": built.bundle_sha256,
            }
        }
    )
    assert _local_image_prompt_contract(workflow) == "ASSESSMENT_REFERENCE_COMPOSITION_V3"
    assert _enforces_svg_label_layout(workflow)
    workflow.runtime_context["content_pack"]["release_sha256"] = "sha256:" + "0" * 64
    assert not _enforces_svg_label_layout(workflow)


def prompt_case(tmp_path, monkeypatch, schema="plan", role="authoring", *, ordinary=False):
    case = (ordinary_similarity_case if ordinary else similarity_case)(tmp_path, monkeypatch)
    plan = case[schema]
    document = plan.model_dump(mode="json")
    record = SimpleNamespace(
        canonical_document=document,
        **{
            key: getattr(plan, key)
            for key in (
                "plan_id",
                "plan_sha256",
                "workflow_id",
                "preset_id",
                "preset_revision_id",
            )
        },
    )
    workflow = SimpleNamespace(
        workflow_id=plan.workflow_id,
        definition_key=plan.workflow_definition_key,
        definition_version=plan.workflow_definition_version,
        runtime_context={
            "content_pack": {
                "pack_key": "generated-knowledge-item",
                "version": "1.20.17",
                "release_id": plan.content_pack_release_id,
                "release_sha256": plan.content_pack_sha256,
            },
            "execution_plan": {
                key: getattr(plan, key)
                for key in (
                    "plan_id",
                    "plan_sha256",
                    "preset_id",
                    "preset_revision_id",
                )
            },
        },
    )
    step = SimpleNamespace(step_key=role, worker_role=role, input_pointer_manifest={})

    class Session:
        def __init__(self):
            self.calls = []

        def get(self, model, identity):
            self.calls.append((model, identity))
            assert model is ResolvedExecutionPlanRecord
            assert identity == workflow.runtime_context["execution_plan"]["plan_id"]
            return record

    return case, record, workflow, step, Session()


@pytest.mark.parametrize(
    "schema,mode", (("base", "NOT_OFFERED"), ("plan", "PINNED_REFERENCE_CONTEXT"))
)
@pytest.mark.parametrize("role", ("authoring", "review"))
def test_mode_uses_exact_persisted_binding_in_one_indexed_lookup(
    tmp_path, monkeypatch, schema, mode, role
):
    _case, record, workflow, step, session = prompt_case(tmp_path, monkeypatch, schema, role)
    assert (
        read_similarity_prompt_context(
            session,
            workflow=workflow,
            step=step,
            pack_release_id=workflow.runtime_context["content_pack"]["release_id"],
        ).reference_mode
        == mode
    )
    assert session.calls == [(ResolvedExecutionPlanRecord, record.plan_id)]


def test_ungrounded_plan_explicitly_reports_no_auxiliary_context(tmp_path, monkeypatch):
    case, record, workflow, step, session = prompt_case(tmp_path, monkeypatch)
    raw = {
        key: value
        for key, value in case["base"].model_dump(mode="json").items()
        if key in ResolvedExecutionPlanV20.model_fields
    }
    raw.update(
        schema_version="resolved-execution-plan/20.0",
        resolver_version="20.0.0",
        graph_snapshot_revision_id=None,
        evidence_bundle_revision_id=None,
    )
    raw["steps"] = [item | {"evidence_access": "NONE"} for item in raw["steps"]]
    general = ResolvedExecutionPlanV20.model_validate(seal(raw, "plan_sha256"))
    record.canonical_document = general.model_dump(mode="json")
    record.plan_sha256 = general.plan_sha256
    workflow.runtime_context["execution_plan"]["plan_sha256"] = general.plan_sha256
    assert (
        read_similarity_prompt_context(
            session, workflow=workflow, step=step, pack_release_id=general.content_pack_release_id
        ).reference_mode
        == "NOT_OFFERED"
    )


@pytest.mark.parametrize(
    "fault",
    (
        "missing_pin",
        "extra_pin",
        "non_string_pin",
        "missing_record",
        "row_workflow",
        "row_hash",
        "row_preset",
        "pin_preset",
        "pack_hash",
        "pack_release",
        "definition",
        "step",
        "role",
        "unknown_schema",
        "content_hash",
        "invalid_delivery",
        "non_object",
        "oversized",
    ),
)
def test_invalid_binding_never_masquerades_as_no_auxiliary_context(tmp_path, monkeypatch, fault):
    _case, record, workflow, step, session = prompt_case(tmp_path, monkeypatch)
    if fault == "missing_pin":
        del workflow.runtime_context["execution_plan"]
    elif fault == "extra_pin":
        workflow.runtime_context["execution_plan"]["authority"] = "ADMIN"
    elif fault == "non_string_pin":
        workflow.runtime_context["execution_plan"]["plan_id"] = True
    elif fault == "missing_record":
        session.get = lambda *args: None
    elif fault == "row_workflow":
        record.workflow_id = "workflow_" + "9" * 32
    elif fault == "row_hash":
        record.plan_sha256 = "sha256:" + "0" * 64
    elif fault == "row_preset":
        original = record.preset_revision_id
        record.preset_revision_id = original[:-1] + ("0" if original[-1] != "0" else "1")
    elif fault == "pin_preset":
        original = workflow.runtime_context["execution_plan"]["preset_id"]
        workflow.runtime_context["execution_plan"]["preset_id"] = original[:-1] + (
            "0" if original[-1] != "0" else "1"
        )
    elif fault == "pack_hash":
        workflow.runtime_context["content_pack"]["release_sha256"] = "sha256:" + "0" * 64
    elif fault == "pack_release":
        workflow.runtime_context["content_pack"]["release_id"] = "packrel_" + "9" * 32
    elif fault == "definition":
        workflow.definition_version = "1.15.0"
    elif fault == "step":
        step.step_key = "not_authoring"
    elif fault == "role":
        step.worker_role = "image"
    elif fault == "unknown_schema":
        record.canonical_document["schema_version"] = "resolved-execution-plan/999.0"
    elif fault == "content_hash":
        record.canonical_document["plan_sha256"] = "sha256:" + "0" * 64
    elif fault == "invalid_delivery":
        record.canonical_document["similarity_delivery"]["authority"] = "ADMIN"
    elif fault == "non_object":
        record.canonical_document = True
    elif fault == "oversized":
        record.canonical_document["unexpected"] = "x" * (1024 * 1024)
    with pytest.raises(ValueError, match="SIMILARITY_PROMPT_"):
        read_similarity_prompt_context(
            session,
            workflow=workflow,
            step=step,
            pack_release_id=workflow.runtime_context["content_pack"]["release_id"]
            if fault != "pack_release"
            else record.canonical_document["content_pack_release_id"],
        )


@pytest.mark.parametrize(
    "version,role,expected",
    (
        ("1.20.17", "authoring", "PINNED_REFERENCE_CONTEXT"),
        ("1.20.17", "review", "PINNED_REFERENCE_CONTEXT"),
        ("1.20.16", "authoring", None),
        ("1.20.17", "image", None),
        ("1.20.17", "item_management", None),
    ),
)
def test_actual_catalog_context_wiring_is_scoped_and_ignores_user_supplied_mode(
    tmp_path,
    monkeypatch,
    version,
    role,
    expected,
):
    _case, _record, workflow, step, session = prompt_case(tmp_path, monkeypatch, role=role)
    workflow.runtime_context["content_pack"]["version"] = version
    workflow.runtime_context["similarity"] = {"reference_mode": "USER_SUPPLIED_AUTHORITY"}
    service = object.__new__(WorkflowCatalogService)
    entries = []

    @contextmanager
    def sessions():
        entries.append(True)
        yield session

    service.sessions = sessions
    request = WorkflowRequest.model_validate_json(
        (TARGET / "fixtures/smoke-request.json").read_bytes()
    )
    original = deepcopy(workflow.runtime_context)
    context = service._prompt_context(
        workflow, step, request, (), workflow.runtime_context["content_pack"]["release_id"]
    )
    if expected is None:
        assert "similarity" not in context
        assert not entries
        assert not session.calls
    else:
        assert context["similarity"] == {
            "reference_mode": expected,
            "plan_id": _record.plan_id,
            "plan_sha256": _record.plan_sha256,
        }
        assert entries == [True]
        assert len(session.calls) == 1
    assert workflow.runtime_context == original


def reference_pinned_prompt_case(tmp_path, monkeypatch):
    case, record, workflow, step, session = prompt_case(tmp_path, monkeypatch)
    service, artifacts, _original_workflow, original_step = pinned_prompt_fixture()
    workflow.runtime_context["source_intake"] = {"batch_ids": []}
    profile = yaml.safe_load((TARGET / "profiles/generated-knowledge-authoring.yaml").read_bytes())
    template_bytes = (TARGET / profile["template"]).read_bytes()
    workflow.runtime_context["profiles"] = {
        "authoring": {
            "profile_key": profile["profile"]["key"],
            "profile_version": profile["profile"]["version"],
            "profile_sha256": content_sha256(profile),
            "template_relative_path": profile["template"],
        }
    }
    step.attempt = 1
    step.step_run_id = original_step.step_run_id

    @contextmanager
    def sessions():
        yield session

    service.sessions = sessions
    request = WorkflowRequest.model_validate_json(
        (TARGET / "fixtures/smoke-request.json").read_bytes()
    )
    context = service._prompt_context(
        workflow, step, request, (), record.canonical_document["content_pack_release_id"]
    )
    rendered = render_prompt(template_bytes.decode(), context, tuple(profile["required_context"]))
    artifacts.prompt = rendered.text.encode()
    pointer = dict(original_step.input_pointer_manifest["prompt"])
    pointer["sha256"] = sha256_bytes(artifacts.prompt)
    envelope = original_step.input_pointer_manifest["prompt_envelope"] | {
        "workflow_id": workflow.workflow_id,
        "pack_release_id": workflow.runtime_context["content_pack"]["release_id"],
        "pack_release_sha256": workflow.runtime_context["content_pack"]["release_sha256"],
        "profile_key": profile["profile"]["key"],
        "profile_version": profile["profile"]["version"],
        "profile_sha256": content_sha256(profile),
        "template_path": profile["template"],
        "template_sha256": sha256_bytes(template_bytes),
        "rendered_prompt_sha256": pointer["sha256"],
        "render_context_sha256": rendered.context_hash,
    }
    artifacts.envelope = canonical_json_bytes(envelope)
    step.input_pointer_manifest = {"prompt": pointer, "prompt_envelope": envelope}
    workflow.runtime_context["prompt_artifacts"] = [
        {"step_key": "authoring", "attempt": 1, **pointer}
    ]
    session.calls.clear()
    return case, record, workflow, step, session, service, artifacts, request


def test_exact_new_pack_prompt_replay_rechecks_same_plan_without_republishing(
    tmp_path, monkeypatch
):
    _case, record, workflow, step, session, service, artifacts, request = (
        reference_pinned_prompt_case(tmp_path, monkeypatch)
    )
    before = (artifacts.prompt, artifacts.envelope, deepcopy(workflow.runtime_context))
    prepared = service.prepare_prompt(workflow=workflow, step=step, request=request, upstream=())
    assert prepared.text.encode() == before[0]
    assert prepared.envelope == step.input_pointer_manifest["prompt_envelope"]
    assert session.calls == [(ResolvedExecutionPlanRecord, record.plan_id)]
    assert (artifacts.prompt, artifacts.envelope, workflow.runtime_context) == before


def test_replay_rejects_changed_plan_even_when_reference_mode_is_unchanged(tmp_path, monkeypatch):
    _case, record, workflow, step, session, service, artifacts, request = (
        reference_pinned_prompt_case(tmp_path, monkeypatch)
    )
    document = deepcopy(record.canonical_document)
    member = document["similarity_delivery"]["context_member"]
    original = member["artifact_revision_id"]
    member["artifact_revision_id"] = original[:-1] + ("0" if original[-1] != "0" else "1")
    record.canonical_document = seal(document, "plan_sha256")
    record.plan_sha256 = record.canonical_document["plan_sha256"]
    workflow.runtime_context["execution_plan"]["plan_sha256"] = record.plan_sha256
    before = (artifacts.prompt, artifacts.envelope)
    with pytest.raises(ValueError, match="pinned similarity prompt context changed"):
        service.prepare_prompt(workflow=workflow, step=step, request=request, upstream=())
    assert (artifacts.prompt, artifacts.envelope) == before
    assert session.calls == [(ResolvedExecutionPlanRecord, record.plan_id)]
