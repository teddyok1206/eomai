"""Nonlive fake lifecycle ports; no DB, Artifact filesystem, auth or inference.

These tests verify upgrade policy/CAS composition, not PostgreSQL locking. The
guarded storage suite must additionally exercise genuine concurrent release.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime, timedelta
from threading import RLock
from types import SimpleNamespace

import pytest
from eom_identifiers import content_sha256, sha256_bytes
from eom_orchestrator import material_learning_coverage_controls as owner
from eom_orchestrator.control_models import ExecutionPresetRecord, ExecutionPresetRevisionRecord
from eom_orchestrator.control_service import ControlPlaneError
from eom_orchestrator.preset_model_selection import (
    current_model_preset,
    require_model_only_successor,
)
from eom_workflow.control_plane import (
    ControlArtifactPointer,
    ExecutionPresetEvaluationReport,
    ExecutionPresetRevision,
)

from tests.unit.test_execution_control_contracts import _preset

NOW = datetime(2026, 11, 15, tzinfo=UTC)
ACTOR = "operator_" + "7" * 32


def _hashed(value):
    body = deepcopy(value)
    body["content_sha256"] = content_sha256(
        {key: item for key, item in body.items() if key != "content_sha256"}
    )
    return body


def _base():
    value = _preset()
    value.update(
        display_name="관리자가 고른 자료 학습",
        description="현재 관리자 설정 그대로",
        general_knowledge_policy="DENY",
        compatible_workflow_protocols=["workflow-role/1.37.0"],
        created_at=NOW.isoformat().replace("+00:00", "Z"),
    )
    value["role_policies"][0].update(
        role="support",
        worker_pool_key="support",
        reference_bundle=None,
        timeout_seconds=7200,
        model_candidates=[
            {"model": "gpt-6-sol", "reasoning_effort": "medium"},
            {"model": "gpt-5.6-terra", "reasoning_effort": "xhigh"},
        ],
    )
    return ExecutionPresetRevision.model_validate(_hashed(value))


def _revision(base, *, number=2, state="DRAFT", protocol="workflow-role/1.39.0", edit=None):
    body = base.model_dump(mode="json")
    body.update(
        preset_revision_id=f"execpresetrev_{number:032x}",
        revision_number=number,
        state=state,
        compatible_workflow_protocols=[protocol],
        created_at=NOW.isoformat().replace("+00:00", "Z"),
    )
    if edit:
        edit(body)
    return ExecutionPresetRevision.model_validate(_hashed(body))


def _row(value):
    return ExecutionPresetRevisionRecord(
        preset_id=value.preset_id,
        preset_revision_id=value.preset_revision_id,
        state=value.state,
        revision_number=value.revision_number,
        content_sha256=value.content_sha256,
        canonical_document=value.model_dump(mode="json"),
    )


@pytest.fixture
def upgrade(monkeypatch, request):
    base = _base()
    exact_score = getattr(request, "param", None) == "exact-score"
    target = "workflow-role/1.40.0" if exact_score else "workflow-role/1.39.0"
    if exact_score:
        value = base.model_dump(mode="json")
        value["compatible_workflow_protocols"] = ["workflow-role/1.39.0"]
        base = ExecutionPresetRevision.model_validate(_hashed(value))
    state = SimpleNamespace(
        base=base,
        rows={base.preset_revision_id: _row(base)},
        drafts=0,
        releases=0,
        evaluations=[],
        authorization=[],
        denied_at=None,
        protocol=[],
        lock=RLock(),
        other_presets={
            key: "UNCHANGED"
            for key in (
                "material-item-analysis",
                "material-item-solution",
                "material-knowledge-analysis",
            )
        },
    )
    state.logical = ExecutionPresetRecord(
        preset_id=base.preset_id,
        preset_key="material-learning",
        state="ACTIVE",
        current_revision_id=base.preset_revision_id,
    )

    class Session:
        def __enter__(self):
            state.lock.acquire()
            return self

        def __exit__(self, *_args):
            state.lock.release()

        def execute(self, _statement):
            return None  # Existing advisory lock port; never raw SQL mutation.

        def scalar(self, _statement):
            return state.logical if state.logical.preset_key == "material-learning" else None

        def scalars(self, _statement):
            return tuple(
                row
                for row in state.rows.values()
                if row.state == "DRAFT"
                and row.canonical_document["compatible_workflow_protocols"] == [target]
            )

        def get(self, kind, key, **_kwargs):
            if kind is ExecutionPresetRecord:
                return state.logical if key == state.logical.preset_id else None
            assert kind is ExecutionPresetRevisionRecord
            return state.rows.get(key)

    sessions = SimpleNamespace(begin=Session)

    def create(_session, **request):
        assert request["preset_key"] == "material-learning"
        state.drafts += 1
        value = _revision(base, number=max(row.revision_number for row in state.rows.values()) + 1)
        body = value.model_dump(mode="json")
        for field in (
            "display_name",
            "description",
            "role_policies",
            "capacity_policy_revision_id",
            "general_knowledge_policy",
            "compatible_workflow_protocols",
        ):
            body[field] = request[field]
        body["created_at"] = request["created_at"].isoformat().replace("+00:00", "Z")
        value = ExecutionPresetRevision.model_validate(_hashed(body))
        row = _row(value)
        state.rows[row.preset_revision_id] = row
        return row

    def record(_session, *, document, report_artifact, created_by):
        report = ExecutionPresetEvaluationReport.model_validate(document)
        assert created_by == ACTOR and report.scope == "NON_LIVE" and report.outcome == "PASS"
        assert report_artifact.sha256 == sha256_bytes(canonical_payload(document))
        state.evaluations.append(report)

    def release(_session, *, draft_revision_id, released_by, released_at):
        assert released_by == ACTOR
        assert any(
            report.evaluated_preset_revision_id == draft_revision_id for report in state.evaluations
        )
        state.releases += 1
        draft = owner.validated_preset(state.rows[draft_revision_id])
        value = _revision(
            draft,
            number=max(row.revision_number for row in state.rows.values()) + 1,
            state="RELEASED",
            protocol=target,
        )
        row = _row(value)
        state.rows[value.preset_revision_id] = row
        state.logical.current_revision_id = value.preset_revision_id
        assert released_at == draft.created_at
        return row

    monkeypatch.setattr(owner, "create_execution_preset_draft", create)
    monkeypatch.setattr(owner, "record_execution_preset_evaluation", record)
    monkeypatch.setattr(owner, "release_execution_preset", release)
    monkeypatch.setattr(
        owner,
        "ensure_protocol_version",
        lambda _session, version, digest: state.protocol.append((version, digest)),
    )

    def authorize(actor):
        assert actor == ACTOR
        state.authorization.append(actor)
        if state.denied_at == len(state.authorization):
            raise PermissionError("TEST_CURRENT_OPERATOR_REVOKED")

    class Publisher:
        def __init__(self):
            self.calls, self.saved, self.hook = [], {}, None
            self.unknown_once = False

        def publish_bytes(self, **request):
            self.calls.append(request)
            key = request["idempotency_key"]
            if key in self.saved:
                raw, value = self.saved[key]
                assert raw == request["payload"]
            else:
                value = SimpleNamespace(
                    pointer=ControlArtifactPointer(
                        artifact_id="artifact_" + "8" * 32,
                        artifact_revision_id="rev_" + "9" * 32,
                        sha256=sha256_bytes(request["payload"]),
                        schema_ref=request["schema_ref"],
                        media_type="application/json",
                        logical_name=request["logical_name"],
                    )
                )
                self.saved[key] = request["payload"], value
            if self.hook:
                self.hook()
            if self.unknown_once:
                self.unknown_once = False
                raise ControlPlaneError(
                    "TEST_UNKNOWN_PUBLICATION", "lost response, immutable key retained"
                )
            return value

    publisher = Publisher()
    arguments = dict(
        expected_current_revision_id=base.preset_revision_id,
        expected_current_sha256=base.content_sha256,
        operator_id=ACTOR,
        source_commit="a" * 40,
        authorize=authorize,
        reviewed_at=NOW,
    )
    return sessions, publisher, arguments, state


def canonical_payload(document):
    return owner.canonical_json_bytes(document) + b"\n"


def test_upgrade_clones_current_admin_policy_only_protocol_changes(upgrade):
    sessions, publisher, arguments, state = upgrade
    before = deepcopy(state.rows[state.base.preset_revision_id].canonical_document)
    others = deepcopy(state.other_presets)
    released = owner.upgrade_material_learning_coverage_preset(sessions, publisher, **arguments)
    owner.require_material_learning_coverage_successor(state.base, released)
    assert released.preset_id == state.base.preset_id and released.state == "RELEASED"
    assert released.role_policies == state.base.role_policies
    assert (
        released.display_name == state.base.display_name
        and released.description == state.base.description
    )
    assert state.rows[state.base.preset_revision_id].canonical_document == before
    assert state.other_presets == others
    assert state.drafts == state.releases == len(state.evaluations) == 1
    assert len(state.authorization) == 3 and len(publisher.calls) == 1
    assert state.protocol[0][0] == "workflow-role/1.39.0"


def test_exact_replay_adds_no_draft_evaluation_artifact_or_revision(upgrade):
    sessions, publisher, arguments, state = upgrade
    first = owner.upgrade_material_learning_coverage_preset(sessions, publisher, **arguments)
    assert (
        owner.upgrade_material_learning_coverage_preset(sessions, publisher, **arguments) == first
    )
    assert state.drafts == state.releases == len(state.evaluations) == len(publisher.calls) == 1


@pytest.mark.parametrize("upgrade", ["exact-score"], indirect=True)
def test_exact_score_successor_preserves_models_authority_and_replays_without_work(upgrade):
    sessions, publisher, arguments, state = upgrade
    prior = deepcopy(state.rows[state.base.preset_revision_id].canonical_document)
    value = owner.upgrade_material_learning_exact_score_preset(sessions, publisher, **arguments)
    owner.require_material_learning_exact_score_successor(state.base, value)
    assert value.preset_id == state.base.preset_id
    assert value.compatible_workflow_protocols == ("workflow-role/1.40.0",)
    assert value.role_policies == state.base.role_policies
    assert value.capacity_policy_revision_id == state.base.capacity_policy_revision_id
    assert state.rows[state.base.preset_revision_id].canonical_document == prior
    assert (
        owner.upgrade_material_learning_exact_score_preset(sessions, publisher, **arguments)
        == value
    )
    assert state.drafts == state.releases == len(publisher.calls) == 1
    assert state.protocol[0][0] == "workflow-role/1.40.0"


@pytest.mark.parametrize("upgrade", ["exact-score"], indirect=True)
def test_exact_score_unknown_publication_reuses_same_report_key_on_explicit_resume(upgrade):
    sessions, publisher, arguments, state = upgrade
    publisher.unknown_once = True
    with pytest.raises(ControlPlaneError, match="lost response"):
        owner.upgrade_material_learning_exact_score_preset(sessions, publisher, **arguments)
    owner.upgrade_material_learning_exact_score_preset(
        sessions, publisher, **(arguments | {"reviewed_at": NOW + timedelta(days=1)})
    )
    assert state.drafts == state.releases == 1
    assert len(publisher.calls) == 2 and len(publisher.saved) == 1
    assert publisher.calls[0]["payload"] == publisher.calls[1]["payload"]


@pytest.mark.parametrize("field", ["model", "depth", "timeout", "capacity", "instruction"])
def test_exact_score_upgrade_cannot_change_any_non_protocol_policy(field):
    original = _base().model_dump(mode="json")
    original["compatible_workflow_protocols"] = ["workflow-role/1.39.0"]
    base = ExecutionPresetRevision.model_validate(_hashed(original))

    def edit(body):
        role = body["role_policies"][0]
        if field == "model":
            role["model_candidates"][0]["model"] = "gpt-6-astra"
        elif field == "depth":
            role["model_candidates"][0]["reasoning_effort"] = "high"
        elif field == "timeout":
            role["timeout_seconds"] -= 1
        elif field == "capacity":
            body["capacity_policy_revision_id"] = "capacityrev_" + "f" * 32
        else:
            role["instruction_bundle"]["manifest_sha256"] = "sha256:" + "f" * 64

    successor = _revision(base, protocol="workflow-role/1.40.0", edit=edit)
    with pytest.raises(ControlPlaneError) as error:
        owner.require_material_learning_exact_score_successor(base, successor)
    assert error.value.code == "CONTROL_MATERIAL_EXACT_SCORE_POLICY_CHANGED"


def test_unknown_publication_is_not_automatically_resubmitted_and_explicit_resume_reuses_key(
    upgrade,
):
    sessions, publisher, arguments, state = upgrade
    publisher.unknown_once = True
    with pytest.raises(ControlPlaneError, match="lost response"):
        owner.upgrade_material_learning_coverage_preset(sessions, publisher, **arguments)
    assert len(publisher.calls) == 1 and state.releases == 0
    resumed = arguments | {"reviewed_at": NOW + timedelta(days=1)}
    owner.upgrade_material_learning_coverage_preset(sessions, publisher, **resumed)
    assert len(publisher.calls) == 2 and len(publisher.saved) == 1
    assert publisher.calls[0]["idempotency_key"] == publisher.calls[1]["idempotency_key"]
    assert publisher.calls[0]["payload"] == publisher.calls[1]["payload"]
    assert state.drafts == state.releases == 1


def test_administrator_change_during_artifact_publication_is_cas_rejected(upgrade):
    sessions, publisher, arguments, state = upgrade

    def changed():
        value = _revision(
            state.base,
            number=50,
            state="RELEASED",
            protocol="workflow-role/1.37.0",
            edit=lambda body: body["role_policies"][0]["model_candidates"][0].update(
                reasoning_effort="high"
            ),
        )
        state.rows[value.preset_revision_id] = _row(value)
        state.logical.current_revision_id = value.preset_revision_id

    publisher.hook = changed
    with pytest.raises(ControlPlaneError) as raised:
        owner.upgrade_material_learning_coverage_preset(sessions, publisher, **arguments)
    assert raised.value.code == "CONTROL_PRESET_BASE_STALE"
    assert state.releases == 0 and not state.evaluations
    assert state.logical.current_revision_id.endswith(f"{50:032x}")


@pytest.mark.parametrize("phase", [1, 2, 3])
def test_actual_authorization_is_required_at_each_side_effect_boundary(upgrade, phase):
    sessions, publisher, arguments, state = upgrade
    state.denied_at = phase
    with pytest.raises(PermissionError, match="REVOKED"):
        owner.upgrade_material_learning_coverage_preset(sessions, publisher, **arguments)
    assert state.releases == 0
    assert len(publisher.calls) == (1 if phase == 3 else 0)


@pytest.mark.parametrize(
    "changed", ["hash", "retired", "logical", "wrong-current", "protocol", "general"]
)
def test_wrong_current_hash_logical_or_family_cannot_start_upgrade(upgrade, changed):
    sessions, publisher, arguments, state = upgrade
    if changed == "hash":
        arguments["expected_current_sha256"] = "sha256:" + "f" * 64
    elif changed == "retired":
        state.logical.state = "RETIRED"
    elif changed == "logical":
        state.logical.preset_key = "material-item-analysis"
    elif changed == "wrong-current":
        value = _revision(state.base, number=20, state="RELEASED", protocol="workflow-role/1.37.0")
        state.rows[value.preset_revision_id] = _row(value)
        state.logical.current_revision_id = value.preset_revision_id
    else:
        body = state.base.model_dump(mode="json")
        body[
            "compatible_workflow_protocols" if changed == "protocol" else "general_knowledge_policy"
        ] = ["workflow-role/1.4.0"] if changed == "protocol" else "ALLOW_WITH_PROVENANCE"
        value = ExecutionPresetRevision.model_validate(_hashed(body))
        state.rows[value.preset_revision_id] = _row(value)
        arguments["expected_current_sha256"] = value.content_sha256
    with pytest.raises(ControlPlaneError):
        owner.upgrade_material_learning_coverage_preset(sessions, publisher, **arguments)
    assert not publisher.calls and state.drafts == state.releases == 0


@pytest.mark.parametrize(
    "field", ["models", "instruction", "reference", "capacity", "timeout", "name", "general"]
)
def test_pure_successor_rule_rejects_every_nonprotocol_change(field):
    base = _base()

    def change(body):
        role = body["role_policies"][0]
        if field == "models":
            role["model_candidates"][0]["reasoning_effort"] = "high"
        elif field == "instruction":
            role["instruction_bundle"]["manifest_sha256"] = "sha256:" + "f" * 64
        elif field == "reference":
            role["reference_bundle"] = _preset()["role_policies"][0]["reference_bundle"]
        elif field == "capacity":
            body["capacity_policy_revision_id"] = "capacityrev_" + "f" * 32
        elif field == "timeout":
            role["timeout_seconds"] = 60
        elif field == "name":
            body["display_name"] = "changed"
        else:
            body["general_knowledge_policy"] = "ALLOW_WITH_PROVENANCE"

    with pytest.raises(ControlPlaneError) as raised:
        owner.require_material_learning_coverage_successor(base, _revision(base, edit=change))
    assert raised.value.code == "CONTROL_MATERIAL_COVERAGE_POLICY_CHANGED"


def test_only_exact_target_draft_is_resumed_without_rewriting_other_drafts(upgrade):
    sessions, publisher, arguments, state = upgrade
    unrelated = _revision(
        state.base,
        number=10,
        edit=lambda body: body["role_policies"][0]["model_candidates"][0].update(
            reasoning_effort="high"
        ),
    )
    state.rows[unrelated.preset_revision_id] = _row(unrelated)
    before = deepcopy(state.rows[unrelated.preset_revision_id].canonical_document)
    owner.upgrade_material_learning_coverage_preset(sessions, publisher, **arguments)
    assert state.rows[unrelated.preset_revision_id].canonical_document == before
    assert state.drafts == state.releases == 1


def test_matching_duplicate_drafts_are_explicitly_ambiguous(upgrade):
    sessions, publisher, arguments, state = upgrade
    for number in (10, 11):
        value = _revision(state.base, number=number)
        state.rows[value.preset_revision_id] = _row(value)
    with pytest.raises(ControlPlaneError) as raised:
        owner.upgrade_material_learning_coverage_preset(sessions, publisher, **arguments)
    assert raised.value.code == "CONTROL_MATERIAL_COVERAGE_DRAFT_AMBIGUOUS"
    assert not publisher.calls and state.drafts == state.releases == 0


def test_after_upgrade_normal_existing_admin_model_only_path_still_works(upgrade):
    sessions, publisher, arguments, state = upgrade
    released = owner.upgrade_material_learning_coverage_preset(sessions, publisher, **arguments)

    def edit(body):
        body["role_policies"][0]["model_candidates"][0].update(reasoning_effort="high")

    draft = _revision(released, number=60, edit=edit)
    require_model_only_successor(released, draft)
    current = _revision(draft, number=61, state="RELEASED")
    state.rows[current.preset_revision_id] = _row(current)
    state.logical.current_revision_id = current.preset_revision_id
    with sessions.begin() as session:
        assert current_model_preset(session, released) == current
    with pytest.raises(ControlPlaneError) as raised:
        owner.upgrade_material_learning_coverage_preset(sessions, publisher, **arguments)
    assert raised.value.code == "CONTROL_PRESET_BASE_STALE"
