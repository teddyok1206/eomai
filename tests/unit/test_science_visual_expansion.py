from __future__ import annotations

import ast
import hashlib
import json
from collections import Counter
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest
from eom_catalog_contracts import ScienceAssessmentWebCorpusManifestV2
from eom_catalog_service.science_visual_expansion_planning import (
    build_science_visual_expansion_plan,
    select_science_visual_expansion_sources,
    validate_science_visual_expansion_predecessors,
)
from eom_catalog_service.science_visual_pilot import (
    ScienceVisualPilotPlanningError,
    build_science_visual_pilot_plan_v3,
)
from eom_image_contracts import (
    SCHEMA_SHA256,
    ImageEvaluationArtifactMember,
    LocalImageScienceCorpusTrainingAuthorization,
    LocalImageScienceCorpusVisualPilotCommandV4,
    LocalImageScienceCorpusVisualPilotPlanV3,
    LocalImageScienceCorpusVisualPilotPlanV4,
    content_json_bytes,
    content_sha256,
    load_schema,
    validate_contract,
)
from eom_image_contracts.science_visual_pilot_codec import (
    build_science_visual_pilot_command,
    parse_science_visual_pilot_command,
    parse_science_visual_pilot_plan,
)
from eom_image_trainer import science_corpus_visual_runner as worker
from eom_orchestrator.local_image_training_control_artifacts import (
    LocalImageTrainingControlArtifactPublisher,
)
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError as JsonSchemaValidationError

from scripts.image_trainer import publish_science_visual_pilot_result as publication
from scripts.image_trainer import stage_science_visual_expansion as staging
from tests.unit.test_publish_science_visual_pilot_result import _stage_complete_workspace
from tests.unit.test_science_corpus_visual_contracts import _authorization_value, _plan_v3_value
from tests.unit.test_science_visual_pilot_planning import _document


def _raw_sha(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def _pointer(plan, index=1):
    return ImageEvaluationArtifactMember(
        artifact_id="artifact_" + f"{index:032x}",
        artifact_revision_id="rev_" + f"{index:032x}",
        member_path="manifests/visual-pilot-plan.json",
        schema_ref="eom://schemas/image-provider/" + plan.schema_version,
        media_type="application/json",
        sha256=_raw_sha(content_json_bytes(plan.model_dump(mode="json"))),
    )


def _seal(value):
    body = {key: item for key, item in value.items() if key not in {"pilot_id", "plan_sha256"}}
    body["pilot_id"] = "imgscivispilot_" + content_sha256(body)[7:39]
    body["plan_sha256"] = content_sha256(body)
    return body


@dataclass(frozen=True)
class _Context:
    corpus: ScienceAssessmentWebCorpusManifestV2
    authorization: LocalImageScienceCorpusTrainingAuthorization
    plans: tuple[LocalImageScienceCorpusVisualPilotPlanV3, ...]
    pointers: tuple[ImageEvaluationArtifactMember, ...]


@pytest.fixture(scope="module")
def context():
    template = LocalImageScienceCorpusVisualPilotPlanV3.model_validate(_plan_v3_value())
    authorization = LocalImageScienceCorpusTrainingAuthorization.model_validate(
        _authorization_value()
    )
    # Synthetic planner fixture, not a claim of published/authorized live corpus bytes.
    corpus = cast(
        ScienceAssessmentWebCorpusManifestV2,
        SimpleNamespace(
            documents=tuple(_document(index) for index in range(600)),
            corpus_id=template.corpus_id,
            manifest_sha256=template.corpus_manifest_sha256,
            acquisition_sha256=template.acquisition_sha256,
            resolution_sha256=template.resolution_sha256,
            resolution_policy_id=template.resolution_policy_id,
            resolution_policy_sha256=template.resolution_policy_sha256,
        ),
    )
    plans = tuple(
        build_science_visual_pilot_plan_v3(
            corpus=corpus,
            corpus_manifest=template.corpus_manifest,
            authorization=authorization,
            authorization_pointer=template.training_authorization,
            selection_seed_sha256=template.selection_seed_sha256,
            campaign_shard_index=index,
            campaign_shard_count=3,
            guidance_authorities=template.guidance_authorities,
            tools=template.tools,
            source_commit="b" * 40,
            created_at=template.created_at,
            created_by="unit_test",
            locator_policy=template.locator_policy,
        )
        for index in range(3)
    )
    return _Context(
        corpus,
        authorization,
        plans,
        tuple(_pointer(plan, index + 1) for index, plan in enumerate(plans)),
    )


def _admit(context, **overrides):
    first = context.plans[0]
    values = {
        "corpus": context.corpus,
        "corpus_manifest": first.corpus_manifest,
        "authorization": context.authorization,
        "authorization_pointer": first.training_authorization,
        "plans": context.plans,
        "plan_pointers": context.pointers,
        "selection_seed_sha256": first.selection_seed_sha256,
        "created_at": datetime(2026, 10, 4, 6, 0, tzinfo=UTC),
    }
    return validate_science_visual_expansion_predecessors(**(values | overrides))


def _expansion(context, index=0):
    first = context.plans[0]
    return build_science_visual_expansion_plan(
        corpus=context.corpus,
        corpus_manifest=first.corpus_manifest,
        authorization=context.authorization,
        authorization_pointer=first.training_authorization,
        predecessor_plans=context.plans,
        predecessor_plan_pointers=context.pointers,
        selection_seed_sha256=first.selection_seed_sha256,
        campaign_shard_index=index,
        campaign_shard_count=3,
        guidance_authorities=first.guidance_authorities,
        tools=first.tools,
        source_commit="b" * 40,
        created_at=datetime(2026, 10, 4, 6, 0, tzinfo=UTC),
        created_by="unit_test",
        locator_policy=first.locator_policy,
        source_limit=18,
        page_limit=120,
    )


def test_new_sources_are_disjoint_deterministic_and_preserve_whole_corpus_groups(context):
    excluded = _admit(context)
    assert len(excluded) == 108
    expanded = tuple(_expansion(context, index) for index in range(3))
    assert _expansion(context) == expanded[0]
    selected = tuple(source for plan in expanded for source in plan.selected_sources)
    assert len(selected) == len({source.document_id for source in selected}) == 54
    assert not excluded.intersection(source.document_id for source in selected)
    assert Counter(source.partition for source in selected) == {
        "TRAIN": 36,
        "VALIDATION": 9,
        "HOLDOUT": 9,
    }
    assert len({plan.campaign_id for plan in expanded}) == 1
    assert expanded[0].campaign_id != context.plans[0].campaign_id
    historical_groups = {
        source.exam_group_sha256: source.partition
        for plan in context.plans
        for source in plan.selected_sources
    }
    for source in selected:
        if source.exam_group_sha256 in historical_groups:
            assert source.partition == historical_groups[source.exam_group_sha256]
    reversed_corpus = cast(
        ScienceAssessmentWebCorpusManifestV2,
        SimpleNamespace(documents=tuple(reversed(context.corpus.documents))),
    )
    assert (
        select_science_visual_expansion_sources(
            reversed_corpus,
            selection_seed_sha256=context.plans[0].selection_seed_sha256,
            excluded_document_ids=excluded,
            campaign_shard_index=0,
            campaign_shard_count=3,
            source_limit=18,
            page_limit=120,
        )
        == expanded[0].selected_sources
    )


@pytest.mark.parametrize("kind", ("plan", "command"))
def test_additive_schemas_are_202012_pinned_and_packaged(context, kind):
    plan = _expansion(context)
    command = build_science_visual_pilot_command(
        plan=plan,
        plan_pointer=_pointer(plan, 10),
        requested_at=plan.created_at,
        requested_by="unit_test",
    )
    model = plan if kind == "plan" else command
    name = "science-corpus-visual-pilot-" + kind + "-v4"
    validate_contract(name, model.model_dump(mode="json"))
    Draft202012Validator.check_schema(load_schema(name))
    filename = "local-image-science-corpus-visual-pilot-" + kind + "-v4.schema.json"
    root = Path(__file__).resolve().parents[2]
    raw = (root / "schemas/image-provider" / filename).read_bytes()
    assert SCHEMA_SHA256[name] == _raw_sha(raw)
    assert (
        raw
        == (root / "packages/image_contracts/eom_image_contracts/schemas" / filename).read_bytes()
    )
    assert filename in (root / "scripts/image_trainer/build_release.sh").read_text()


@pytest.mark.parametrize(
    "fault", ("missing", "duplicate", "hash", "schema", "seed", "time", "scope")
)
def test_predecessor_faults_fail_before_selection(context, fault):
    options = {}
    if fault == "missing":
        options = {"plans": context.plans[:-1], "plan_pointers": context.pointers[:-1]}
    elif fault == "duplicate":
        options = {"plan_pointers": (context.pointers[0],) * 3}
    elif fault in {"hash", "schema"}:
        pointer = context.pointers[0].model_copy(
            update={
                "sha256" if fault == "hash" else "schema_ref": "sha256:" + "f" * 64
                if fault == "hash"
                else "eom://schemas/unknown/1.0",
            }
        )
        options = {"plan_pointers": (pointer, *context.pointers[1:])}
    elif fault == "seed":
        options = {"selection_seed_sha256": "sha256:" + "d" * 64}
    elif fault == "time":
        options = {"created_at": datetime(2020, 1, 1, tzinfo=UTC)}
    else:
        options = {
            "corpus_manifest": context.plans[0].corpus_manifest.model_copy(
                update={"artifact_revision_id": "rev_" + "f" * 32}
            )
        }
    with pytest.raises(ScienceVisualPilotPlanningError, match="SCIENCE_VISUAL_EXPANSION_"):
        _admit(context, **options)


@pytest.mark.parametrize("field,value", (("bytes", 9000), ("partition", "VALIDATION")))
def test_frozen_source_metadata_is_not_reinterpreted_even_with_rehashed_plan(context, field, value):
    plan = context.plans[0]
    body = plan.model_dump(mode="json")
    source = next(source for source in body["selected_sources"] if source["partition"] == "TRAIN")
    source[field] = value
    changed = LocalImageScienceCorpusVisualPilotPlanV3.model_validate(_seal(body))
    altered = replace(
        context,
        plans=(changed, *context.plans[1:]),
        pointers=(_pointer(changed), *context.pointers[1:]),
    )
    with pytest.raises(
        ScienceVisualPilotPlanningError, match="SCIENCE_VISUAL_EXPANSION_FROZEN_SOURCE_MISMATCH"
    ):
        _admit(altered)


def test_complete_history_can_keep_its_published_terminal_newline(context):
    first = context.plans[0]
    pointer = context.pointers[0].model_copy(
        update={
            "sha256": _raw_sha(content_json_bytes(first.model_dump(mode="json")) + b"\n"),
        }
    )
    assert len(_admit(replace(context, pointers=(pointer, *context.pointers[1:])))) == 108


@pytest.mark.parametrize("excluded", (frozenset(), frozenset({"sciencedoc_" + "f" * 32})))
def test_exclusion_set_cannot_silently_invent_missing_sources(context, excluded):
    with pytest.raises(ScienceVisualPilotPlanningError, match="EXPANSION_EXCLUSIONS_INVALID"):
        select_science_visual_expansion_sources(
            context.corpus,
            selection_seed_sha256=context.plans[0].selection_seed_sha256,
            excluded_document_ids=excluded,
            campaign_shard_index=0,
            campaign_shard_count=3,
            source_limit=18,
            page_limit=120,
        )


def test_new_command_and_worker_resolve_exact_protocol_without_pdf_access(context, tmp_path):
    plan = _expansion(context)
    command = build_science_visual_pilot_command(
        plan=plan,
        plan_pointer=_pointer(plan, 10),
        requested_at=plan.created_at,
        requested_by="unit_test",
    )
    assert type(command) is LocalImageScienceCorpusVisualPilotCommandV4
    assert parse_science_visual_pilot_command(command.model_dump(mode="json")) == command
    assert parse_science_visual_pilot_plan(plan.model_dump(mode="json"), command) == plan
    command_path = tmp_path / "command.json"
    command_path.write_bytes(content_json_bytes(command.model_dump(mode="json")))
    command_path.chmod(0o600)
    source_path = tmp_path / command.staged_plan_member
    source_path.parent.mkdir(mode=0o700)
    source_path.write_bytes(content_json_bytes(plan.model_dump(mode="json")))
    source_path.chmod(0o600)
    assert worker.load_command(command_path) == command
    assert worker._load_plan(tmp_path, command) == plan
    assert not (tmp_path / "input/pdfs").exists()


def test_cross_version_plan_and_command_are_not_coerced(context):
    plan = _expansion(context)
    command = build_science_visual_pilot_command(
        plan=plan,
        plan_pointer=_pointer(plan, 10),
        requested_at=plan.created_at,
        requested_by="unit_test",
    )
    with pytest.raises(JsonSchemaValidationError):
        parse_science_visual_pilot_plan(context.plans[0].model_dump(mode="json"), command)
    malformed = command.model_dump(mode="json")
    malformed["schema_version"] = "local-image-science-corpus-visual-pilot-command/9.0"
    with pytest.raises(ValueError, match="unsupported"):
        parse_science_visual_pilot_command(malformed)


@pytest.mark.parametrize("fault", ("missing", "hash"))
def test_worker_rejects_missing_or_hash_drifted_plan_before_pdf(context, tmp_path, fault):
    plan = _expansion(context)
    command = build_science_visual_pilot_command(
        plan=plan,
        plan_pointer=_pointer(plan, 10),
        requested_at=plan.created_at,
        requested_by="unit_test",
    )
    if fault == "hash":
        path = tmp_path / command.staged_plan_member
        path.parent.mkdir(mode=0o700)
        path.write_bytes(content_json_bytes(context.plans[0].model_dump(mode="json")))
        path.chmod(0o600)
    with pytest.raises(worker.ScienceCorpusVisualRunnerError):
        worker._load_plan(tmp_path, command)
    assert not (tmp_path / "pages").exists()


def test_contract_modules_have_no_infrastructure_dependencies():
    root = Path(__file__).resolve().parents[2]
    for filename in ("science_visual_expansion.py", "science_visual_pilot_codec.py"):
        path = root / "packages/image_contracts/eom_image_contracts" / filename
        imports = {
            node.module.split(".")[0]
            for node in ast.walk(ast.parse(path.read_text()))
            if isinstance(node, ast.ImportFrom) and node.module
        }
        assert not imports.intersection(
            {
                "sqlalchemy",
                "subprocess",
                "PIL",
                "eom_catalog_service",
                "eom_orchestrator",
                "eom_image_trainer",
            }
        )


def test_naive_timestamp_is_rejected_before_history_comparison(context):
    with pytest.raises(ScienceVisualPilotPlanningError, match="TIMESTAMP_INVALID"):
        _admit(context, created_at=datetime(2026, 10, 4, 6, 0))


def test_replay_and_frozen_plan_do_not_change_identity(context):
    plan = _expansion(context)
    values = {
        "plan": plan,
        "plan_pointer": _pointer(plan, 10),
        "requested_at": plan.created_at,
        "requested_by": "unit_test",
    }
    first = build_science_visual_pilot_command(**values)
    second = build_science_visual_pilot_command(**values)
    assert first == second
    assert content_json_bytes(first.model_dump(mode="json")) == content_json_bytes(
        second.model_dump(mode="json")
    )
    with pytest.raises(ValueError):
        plan.campaign_id = context.plans[0].campaign_id


def test_rehashed_command_cannot_change_source_size(context):
    plan = _expansion(context)
    command = build_science_visual_pilot_command(
        plan=plan,
        plan_pointer=_pointer(plan, 10),
        requested_at=plan.created_at,
        requested_by="unit_test",
    )
    body = command.model_dump(mode="json", exclude={"attempt_id", "command_sha256"})
    body["staged_sources"][0]["bytes"] += 1
    body["attempt_id"] = "imgscivisattempt_" + content_sha256(body)[7:39]
    body["command_sha256"] = content_sha256(body)
    altered = parse_science_visual_pilot_command(body)
    with pytest.raises(ValueError, match="staged PDFs differ"):
        parse_science_visual_pilot_plan(plan.model_dump(mode="json"), altered)


def test_new_plan_publication_uses_existing_control_owner_and_exact_bytes(context):
    plan = _expansion(context)
    requests = []

    class FakePublisher:
        def publish_bytes(self, **request):
            requests.append(request)
            assert request["artifact_type"] == "control_local_image_science_visual_pilot_plan_v4"
            assert request["payload"] == content_json_bytes(plan.model_dump(mode="json"))
            return SimpleNamespace(
                pointer=SimpleNamespace(
                    artifact_id="artifact_" + "d" * 32,
                    artifact_revision_id="rev_" + "e" * 32,
                    logical_name=request["logical_name"],
                    schema_ref=request["schema_ref"],
                    media_type=request["media_type"],
                    sha256=_raw_sha(request["payload"]),
                )
            )

    publisher = LocalImageTrainingControlArtifactPublisher(FakePublisher(), source_commit="b" * 40)
    pointer = publisher.commit_science_visual_pilot_plan_v4(plan)
    assert pointer.sha256 == _raw_sha(content_json_bytes(plan.model_dump(mode="json")))
    assert (
        requests[0]["idempotency_key"]
        == "local-image-science-visual-expansion-plan:" + plan.plan_sha256[7:]
    )


def test_supported_staging_preflight_has_no_pdf_publication_or_dispatch(
    context, tmp_path, monkeypatch, capsys
):
    basis = context.plans[0].corpus_manifest
    authorization = context.plans[0].training_authorization
    for name, pointer in (("basis.json", basis), ("authorization.json", authorization)):
        path = tmp_path / name
        path.write_bytes(content_json_bytes(pointer.model_dump(mode="json")))
        path.chmod(0o600)
    args = SimpleNamespace(
        basis_crop_set_pointer=tmp_path / "basis.json",
        authorization_pointer=tmp_path / "authorization.json",
        created_at=datetime(2026, 10, 4, 6, 0, tzinfo=UTC),
        created_by="unit_test",
        source_commit="b" * 40,
        campaign_shard_index=0,
        campaign_shard_count=3,
        source_limit=18,
        page_limit=120,
        candidate_limit=512,
        preflight_only=True,
    )
    disposed = []
    monkeypatch.setattr(staging, "_parser", lambda: SimpleNamespace(parse_args=lambda: args))
    monkeypatch.setattr(
        staging, "build_engine", lambda: SimpleNamespace(dispose=lambda: disposed.append(True))
    )
    monkeypatch.setattr(staging.stage, "_require_release", lambda _commit: None)
    monkeypatch.setattr(staging.stage, "_load_corpus", lambda _engine, _pointer: context.corpus)
    monkeypatch.setattr(
        staging.stage, "_guidance", lambda _commit: context.plans[0].guidance_authorities
    )
    monkeypatch.setattr(
        staging.stage,
        "_tool",
        lambda name, *_args: (
            context.plans[0].tools.pdftoppm
            if name == "/usr/bin/pdftoppm"
            else context.plans[0].tools.tesseract
        ),
    )
    monkeypatch.setattr(
        staging,
        "resolve_sdxl_training_sources",
        lambda *_args, **_kwargs: SimpleNamespace(
            authorization=context.authorization,
            plans=context.plans,
            inventory=SimpleNamespace(
                pilot_results=tuple(
                    SimpleNamespace(pilot_plan=pointer) for pointer in context.pointers
                )
            ),
        ),
    )

    def forbidden(*_args, **_kwargs):
        raise AssertionError("read-only preflight crossed a PDF/write/dispatch boundary")

    monkeypatch.setattr(staging, "ControlArtifactPublisher", forbidden)
    monkeypatch.setattr(staging.stage, "_stage_workspace", forbidden)
    monkeypatch.setattr(staging.stage, "_write_receipt", forbidden)
    monkeypatch.setattr(staging.stage, "_load_artifact_member", forbidden)
    assert staging.main() == 0
    assert "PASS_METADATA_ONLY_NO_PDF_READ" in capsys.readouterr().out
    assert disposed == [True]


@pytest.mark.parametrize("version", ("1.0", "1.1", "1.2"))
def test_codec_preserves_released_command_bytes(tmp_path, version):
    workspace, _count = _stage_complete_workspace(
        tmp_path,
        use_v2=version == "1.1",
        use_v3=version == "1.2",
    )
    raw = (workspace / "command.json").read_bytes()
    prior = parse_science_visual_pilot_command(json.loads(raw))
    plan = parse_science_visual_pilot_plan(
        json.loads((workspace / "input/visual-pilot-plan.json").read_bytes()),
        prior,
    )
    reconstructed = build_science_visual_pilot_command(
        plan=plan,
        plan_pointer=prior.plan,
        requested_at=prior.requested_at,
        requested_by=prior.requested_by,
    )
    assert content_json_bytes(reconstructed.model_dump(mode="json")) == raw


def test_supplemental_result_reuses_exact_closed_page_crop_admission(context, tmp_path):
    plan = _expansion(context)
    workspace, count = _stage_complete_workspace(tmp_path, plan_value=plan.model_dump(mode="json"))
    command, resolved, result, _payload, output_bytes = publication._load_workspace(workspace)
    assert type(command) is LocalImageScienceCorpusVisualPilotCommandV4
    assert type(resolved) is LocalImageScienceCorpusVisualPilotPlanV4
    assert resolved == plan
    assert len(result.page_images) == plan.max_page_images
    assert len(result.visual_candidates) == len(plan.selected_sources)
    assert count == len(result.page_images) + len(result.visual_candidates) + 1
    assert output_bytes > 0
