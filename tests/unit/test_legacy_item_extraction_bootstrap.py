from __future__ import annotations

import hashlib
import shutil
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import eom_orchestrator.legacy_item_extraction_bootstrap as legacy_bootstrap
import pytest
from eom_orchestrator.control_models import (
    ExecutionPresetRecord,
    ExecutionPresetRevisionRecord,
)
from eom_orchestrator.control_service import ControlPlaneError, compute_control_document_hash
from eom_orchestrator.legacy_item_extraction_bootstrap import (
    LegacyItemExtractionBootstrapManifest,
    _build_non_live_evaluation_report,
    _find_or_create_draft,
    _require_exact_six_slot_registry,
    load_legacy_item_extraction_bootstrap_manifest,
)
from eom_orchestrator.worker_registry import WorkerSlot
from eom_workflow import ExecutionPresetEvaluationReport
from eom_workflow.control_schemas import validate_control_contract
from jsonschema import ValidationError as JsonSchemaValidationError
from pydantic import ValidationError
from sqlalchemy.orm import Session, sessionmaker

ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / "config/control-plane/legacy-item-extraction-v1"


def _instruction_bundle() -> dict[str, object]:
    return {
        "bundle_id": "instrbundle_" + "1" * 32,
        "bundle_revision_id": "instrrev_" + "2" * 32,
        "manifest_artifact": {
            "artifact_id": "artifact_" + "3" * 32,
            "artifact_revision_id": "rev_" + "4" * 32,
            "sha256": "sha256:" + "5" * 64,
            "schema_ref": "eom://schemas/workflow/bundle-manifest/1.0",
            "media_type": "application/json",
            "logical_name": "manifest.json",
        },
        "manifest_sha256": "sha256:" + "6" * 64,
    }


def _role_policies(*, timeout_seconds: int = 7200) -> list[dict[str, object]]:
    return [
        {
            "role": "support",
            "model_candidates": [{"model": "gpt-5.6-terra", "reasoning_effort": "xhigh"}],
            "instruction_bundle": _instruction_bundle(),
            "reference_bundle": None,
            "worker_pool_key": "legacy-extraction",
            "timeout_seconds": timeout_seconds,
            "sandbox": "read-only",
            "network": "disabled",
        }
    ]


def _preset_revision(
    *,
    seed: str,
    state: str,
    revision_number: int,
    timeout_seconds: int = 7200,
) -> ExecutionPresetRevisionRecord:
    manifest = load_legacy_item_extraction_bootstrap_manifest(CONFIG)
    document: dict[str, Any] = {
        "schema_version": "execution-preset-revision/1.0",
        "preset_id": "execpreset_" + "7" * 32,
        "preset_revision_id": "execpresetrev_" + seed * 32,
        "revision_number": revision_number,
        "state": state,
        "display_name": manifest.display_name,
        "description": manifest.description,
        "role_policies": _role_policies(timeout_seconds=timeout_seconds),
        "capacity_policy_revision_id": "capacityrev_" + "8" * 32,
        "general_knowledge_policy": manifest.general_knowledge_policy,
        "compatible_workflow_protocols": list(manifest.compatible_workflow_protocols),
        "content_sha256": "sha256:" + "0" * 64,
        "created_at": manifest.created_at,
    }
    return cast(
        ExecutionPresetRevisionRecord,
        SimpleNamespace(
            preset_id=document["preset_id"],
            preset_revision_id=document["preset_revision_id"],
            revision_number=revision_number,
            state=state,
            canonical_document=document,
        ),
    )


class _PresetHistorySession:
    def __init__(
        self,
        *,
        logical: ExecutionPresetRecord,
        revisions: tuple[ExecutionPresetRevisionRecord, ...],
        current: ExecutionPresetRevisionRecord | None,
    ) -> None:
        self.logical = logical
        self.revisions = revisions
        self.current = current

    def scalar(self, _statement: object) -> ExecutionPresetRecord:
        return self.logical

    def scalars(self, _statement: object) -> tuple[ExecutionPresetRevisionRecord, ...]:
        return self.revisions

    def get(
        self, model: type[ExecutionPresetRevisionRecord], identity: str
    ) -> ExecutionPresetRevisionRecord | None:
        assert model is ExecutionPresetRevisionRecord
        if self.current is not None and self.current.preset_revision_id == identity:
            return self.current
        return None


def _select_existing_revision(
    monkeypatch: pytest.MonkeyPatch,
    *,
    logical_state: str = "ACTIVE",
    current_revision_id: str | None,
    revisions: tuple[ExecutionPresetRevisionRecord, ...],
    current: ExecutionPresetRevisionRecord | None,
) -> ExecutionPresetRevisionRecord:
    logical = cast(
        ExecutionPresetRecord,
        SimpleNamespace(
            preset_id="execpreset_" + "7" * 32,
            preset_key="legacy-item-extraction",
            current_revision_id=current_revision_id,
            state=logical_state,
        ),
    )
    fake_session = _PresetHistorySession(
        logical=logical,
        revisions=revisions,
        current=current,
    )

    @contextmanager
    def fake_transaction(_sessions: object) -> Iterator[Session]:
        yield cast(Session, fake_session)

    def reject_create(*_args: object, **_kwargs: object) -> ExecutionPresetRevisionRecord:
        raise AssertionError("existing history must never create another preset revision")

    monkeypatch.setattr(legacy_bootstrap, "transaction", fake_transaction)
    monkeypatch.setattr(legacy_bootstrap, "create_execution_preset_draft", reject_create)
    manifest = load_legacy_item_extraction_bootstrap_manifest(CONFIG)
    return _find_or_create_draft(
        cast(sessionmaker[Session], object()),
        manifest=manifest,
        role_policies=_role_policies(),
        capacity_policy_revision_id="capacityrev_" + "8" * 32,
        actor_id="legacy-bootstrap-test",
    )


def test_legacy_item_extraction_bootstrap_is_schema_first_and_exact() -> None:
    manifest = load_legacy_item_extraction_bootstrap_manifest(CONFIG)
    document = manifest.model_dump(mode="json")

    validate_control_contract("legacy-item-extraction-control-bootstrap", document)
    assert manifest.preset_key == "legacy-item-extraction"
    assert manifest.model == "gpt-5.6-terra"
    assert manifest.reasoning_effort == "xhigh"
    assert manifest.general_knowledge_policy == "DENY"
    assert manifest.compatible_workflow_protocols == ("workflow-role/1.14.0",)
    assert manifest.slot_key == "slot06"
    assert manifest.worker_pool_key == "legacy-extraction"
    assert manifest.timeout_seconds == 7200
    assert hashlib.sha256((CONFIG / "bootstrap.yaml").read_bytes()).hexdigest() == (
        "4d63661cc051c3eec1a8f56a7deaefa8350d993922e571f38db37d090826d4b6"
    )


def test_legacy_item_extraction_evaluation_uses_existing_v1_contract_code() -> None:
    document = _build_non_live_evaluation_report(
        preset_revision_id="execpresetrev_" + "a" * 32,
        policy_sha256="sha256:" + "b" * 64,
        evaluation_cases_total=49,
        completed_at=datetime(2026, 9, 1, 0, 1, tzinfo=UTC),
    )

    validate_control_contract("execution-preset-evaluation-report", document)
    report = ExecutionPresetEvaluationReport.model_validate(document)

    assert report.scope == "NON_LIVE"
    assert report.summary_code == "CONTRACT_VALIDATION"
    assert report.cases_total == report.cases_passed == 49
    assert report.report_sha256 == compute_control_document_hash(document, "report_sha256")


def test_legacy_item_extraction_bootstrap_reuses_matching_partial_draft(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    draft = _preset_revision(seed="a", state="DRAFT", revision_number=1)

    selected = _select_existing_revision(
        monkeypatch,
        current_revision_id=None,
        revisions=(draft,),
        current=None,
    )

    assert selected is draft


def test_legacy_item_extraction_bootstrap_replays_current_released_revision(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    draft = _preset_revision(seed="a", state="DRAFT", revision_number=1)
    released = _preset_revision(seed="b", state="RELEASED", revision_number=2)

    selected = _select_existing_revision(
        monkeypatch,
        current_revision_id=released.preset_revision_id,
        revisions=(draft, released),
        current=released,
    )

    assert selected is released


def test_legacy_item_extraction_bootstrap_rejects_current_policy_mismatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    matching_draft = _preset_revision(seed="a", state="DRAFT", revision_number=1)
    different_current = _preset_revision(
        seed="b", state="RELEASED", revision_number=2, timeout_seconds=7199
    )

    with pytest.raises(ControlPlaneError) as captured:
        _select_existing_revision(
            monkeypatch,
            current_revision_id=different_current.preset_revision_id,
            revisions=(matching_draft, different_current),
            current=different_current,
        )

    assert captured.value.code == "CONTROL_BOOTSTRAP_CONFLICT"


def test_legacy_item_extraction_bootstrap_rejects_dangling_current_pointer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    matching_draft = _preset_revision(seed="a", state="DRAFT", revision_number=1)

    with pytest.raises(ControlPlaneError) as captured:
        _select_existing_revision(
            monkeypatch,
            current_revision_id="execpresetrev_" + "b" * 32,
            revisions=(matching_draft,),
            current=None,
        )

    assert captured.value.code == "CONTROL_BOOTSTRAP_CONFLICT"


def test_legacy_item_extraction_bootstrap_rejects_foreign_current_revision(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    matching_draft = _preset_revision(seed="a", state="DRAFT", revision_number=1)
    foreign_current = _preset_revision(seed="b", state="RELEASED", revision_number=2)
    foreign_current.preset_id = "execpreset_" + "9" * 32

    with pytest.raises(ControlPlaneError) as captured:
        _select_existing_revision(
            monkeypatch,
            current_revision_id=foreign_current.preset_revision_id,
            revisions=(matching_draft, foreign_current),
            current=foreign_current,
        )

    assert captured.value.code == "CONTROL_BOOTSTRAP_CONFLICT"


def test_legacy_item_extraction_bootstrap_rejects_nonreleased_current_revision(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    draft = _preset_revision(seed="a", state="DRAFT", revision_number=1)

    with pytest.raises(ControlPlaneError) as captured:
        _select_existing_revision(
            monkeypatch,
            current_revision_id=draft.preset_revision_id,
            revisions=(draft,),
            current=draft,
        )

    assert captured.value.code == "CONTROL_BOOTSTRAP_CONFLICT"


def test_legacy_item_extraction_bootstrap_rejects_released_revision_without_current_pointer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    released = _preset_revision(seed="b", state="RELEASED", revision_number=2)

    with pytest.raises(ControlPlaneError) as captured:
        _select_existing_revision(
            monkeypatch,
            current_revision_id=None,
            revisions=(released,),
            current=None,
        )

    assert captured.value.code == "CONTROL_BOOTSTRAP_CONFLICT"


def test_legacy_item_extraction_bootstrap_rejects_retired_logical_preset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    matching_draft = _preset_revision(seed="a", state="DRAFT", revision_number=1)

    with pytest.raises(ControlPlaneError) as captured:
        _select_existing_revision(
            monkeypatch,
            logical_state="RETIRED",
            current_revision_id=None,
            revisions=(matching_draft,),
            current=None,
        )

    assert captured.value.code == "CONTROL_PRESET_RETIRED"


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("model", "gpt-5.6-sol"),
        ("reasoning_effort", "high"),
        ("general_knowledge_policy", "ALLOW_WITH_PROVENANCE"),
        ("compatible_workflow_protocols", ["workflow-role/1.11.0"]),
        ("slot_key", "slot05"),
        ("worker_pool_key", "support"),
        ("timeout_seconds", 3600),
    ),
)
def test_legacy_item_extraction_bootstrap_rejects_execution_drift(
    field: str, value: object
) -> None:
    document = load_legacy_item_extraction_bootstrap_manifest(CONFIG).model_dump(mode="json")
    document[field] = value

    with pytest.raises((JsonSchemaValidationError, ValidationError)):
        validate_control_contract("legacy-item-extraction-control-bootstrap", document)
        LegacyItemExtractionBootstrapManifest.model_validate(document)


def test_legacy_item_extraction_bootstrap_rejects_symlinked_root(tmp_path: Path) -> None:
    copied = tmp_path / "copied"
    shutil.copytree(CONFIG, copied)
    linked = tmp_path / "linked"
    linked.symlink_to(copied, target_is_directory=True)

    with pytest.raises(ControlPlaneError) as captured:
        load_legacy_item_extraction_bootstrap_manifest(linked)
    assert captured.value.code == "CONTROL_BOOTSTRAP_INVALID"


def test_legacy_item_extraction_requires_slot06_without_broadening_slot05() -> None:
    slots = tuple(
        WorkerSlot(
            slot_id=f"{ordinal:02d}",
            linux_user=f"eom-cdx-{ordinal:02d}",
            role=role,
            enabled=True,
            gpu=role == "image",
        )
        for ordinal, role in (
            (1, "authoring"),
            (2, "review"),
            (3, "image"),
            (4, "item_management"),
            (5, "support"),
            (6, "support"),
        )
    )
    _require_exact_six_slot_registry(slots)

    drifted = (*slots[:5], slots[5].model_copy(update={"enabled": False}))
    with pytest.raises(ControlPlaneError) as captured:
        _require_exact_six_slot_registry(drifted)
    assert captured.value.code == "CONTROL_BOOTSTRAP_SLOT_MISMATCH"


def test_legacy_item_extraction_bootstrap_cli_is_explicit_and_secret_free() -> None:
    source = (ROOT / "apps/eomctl/eomctl/control_plane.py").read_text(encoding="utf-8")
    config_text = "\n".join(
        path.read_text(encoding="utf-8") for path in sorted(CONFIG.rglob("*")) if path.is_file()
    ).casefold()

    assert '@control_plane_app.command("bootstrap-legacy-item-extraction")' in source
    assert all(
        forbidden not in config_text
        for forbidden in ("auth.json", "bearer ", "password=", "token=", "api_key")
    )
