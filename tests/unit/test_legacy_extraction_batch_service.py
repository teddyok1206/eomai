from __future__ import annotations

from contextlib import nullcontext
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from eom_catalog_contracts import LegacySourcePreliminaryClass
from eom_catalog_service import legacy_item_extraction_batch_models
from eom_catalog_service.legacy_item_extraction_batch_models import (
    LegacyItemExtractionBatchEventRecord,
    LegacyItemExtractionBatchRecord,
    LegacyItemExtractionBatchWorkUnitRecord,
)
from eom_catalog_service.legacy_item_extraction_batch_service import (
    IN_FLIGHT_WORK_UNIT_STATES,
    CreateLegacyItemExtractionBatchCommand,
    LegacyItemExtractionBatchService,
    LegacyItemExtractionBatchServiceError,
)
from eom_orchestrator.models import Base
from eomctl.cli import app
from sqlalchemy import LargeBinary
from test_legacy_extraction_batch_contracts import _manifest_v2
from typer.testing import CliRunner


class _MemberSession:
    def __init__(self, member: object) -> None:
        self.member = member

    def scalars(self, _statement: object) -> tuple[object, ...]:
        return (self.member,)


def _member_for_manifest() -> SimpleNamespace:
    binding = _manifest_v2().work_units[0].corpus_source_bindings[0]
    reviewed = binding.reviewed_inventory_source
    return SimpleNamespace(
        assessment_source_bundle_member_id=binding.bundle_member_id,
        ordinal=0,
        inventory_id=reviewed.inventory_id,
        inventory_sha256=reviewed.inventory_sha256,
        inventory_entry_key=reviewed.entry_key,
        inventory_content_sha256=reviewed.content_sha256,
        source_sha256=reviewed.content_sha256,
    )


def _service_without_init() -> LegacyItemExtractionBatchService:
    return object.__new__(LegacyItemExtractionBatchService)


def test_corpus_binding_requires_exact_reviewed_member_and_original_inventory_entry() -> None:
    manifest = _manifest_v2()
    unit = manifest.work_units[0]
    binding = unit.corpus_source_bindings[0]
    entry = SimpleNamespace(
        entry_key=binding.corpus_inventory_source.entry_key,
        content_sha256=binding.corpus_inventory_source.content_sha256,
        preliminary_class=LegacySourcePreliminaryClass.ORIGINAL_SOURCE_CANDIDATE,
    )
    inventory = SimpleNamespace(entries=(entry,))
    service = _service_without_init()
    session = _MemberSession(_member_for_manifest())

    service._validate_corpus_bindings(
        cast(Any, session),
        manifest,
        unit,
        cast(Any, inventory),
    )

    entry.preliminary_class = LegacySourcePreliminaryClass.EXCLUDED_RUNTIME_STATE
    with pytest.raises(LegacyItemExtractionBatchServiceError) as captured:
        service._validate_corpus_bindings(
            cast(Any, session),
            manifest,
            unit,
            cast(Any, inventory),
        )
    assert captured.value.code == "LEGACY_EXTRACTION_BATCH_CORPUS_BINDING_STALE"


def test_corpus_binding_rejects_missing_reviewed_member_coverage() -> None:
    manifest = _manifest_v2()
    unit = manifest.work_units[0]
    extra_member = _member_for_manifest()
    extra_member.assessment_source_bundle_member_id = "assessbundlemember_" + "f" * 32

    class TwoMemberSession:
        @staticmethod
        def scalars(_statement: object) -> tuple[object, ...]:
            return (_member_for_manifest(), extra_member)

    with pytest.raises(LegacyItemExtractionBatchServiceError) as captured:
        _service_without_init()._validate_corpus_bindings(
            cast(Any, TwoMemberSession()),
            manifest,
            unit,
            cast(Any, SimpleNamespace(entries=())),
        )
    assert captured.value.code == "LEGACY_EXTRACTION_BATCH_CORPUS_BINDING_INVALID"


def test_invalid_admission_never_crosses_manifest_artifact_commit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _service_without_init()
    manifest = _manifest_v2()
    command = CreateLegacyItemExtractionBatchCommand(manifest, "operator-test")
    service.sessions = cast(Any, lambda: nullcontext(SimpleNamespace()))
    monkeypatch.setattr(service, "_load_inventory", lambda _manifest: SimpleNamespace())
    monkeypatch.setattr(service, "_find_by_idempotency", lambda _key: None)

    def reject(*_args: object) -> None:
        raise LegacyItemExtractionBatchServiceError(
            "LEGACY_EXTRACTION_BATCH_OPERATOR_INVALID",
            "invalid actor",
        )

    monkeypatch.setattr(service, "_validate_admission", reject)
    monkeypatch.setattr(
        service,
        "_commit_manifest",
        lambda _manifest: pytest.fail("invalid admission must not commit an Artifact"),
    )

    with pytest.raises(LegacyItemExtractionBatchServiceError) as captured:
        service.create(command)
    assert captured.value.code == "LEGACY_EXTRACTION_BATCH_OPERATOR_INVALID"


def test_runner_claims_pending_work_before_due_review_reconciliation_when_idle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _service_without_init()
    calls: list[tuple[str, str]] = []
    monkeypatch.setattr(
        service,
        "claim",
        lambda **_values: SimpleNamespace(work_unit_id="legacyworkunit-new"),
    )
    monkeypatch.setattr(
        service,
        "submit_claimed",
        lambda work_unit_id, *, lease_owner, observed_at: calls.append((work_unit_id, lease_owner)),
    )
    monkeypatch.setattr(
        service,
        "_reserve_reconciliation",
        lambda _now: pytest.fail("an idle worker slot must receive pending work first"),
    )

    assert service.advance_once(runner_id="runner-a") is True
    assert calls == [("legacyworkunit-new", "runner-a")]


def test_automatic_acceptance_reconciles_due_result_before_claiming_more_work(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _service_without_init()
    service.automatic_acceptance = cast(Any, SimpleNamespace())
    calls: list[tuple[str, str]] = []
    monkeypatch.setattr(service, "_reserve_reconciliation", lambda _now: "legacyworkunit-ready")
    monkeypatch.setattr(
        service,
        "reconcile_work_unit",
        lambda work_unit_id, *, observed_at: calls.append(("reconcile", work_unit_id)),
    )
    monkeypatch.setattr(
        service,
        "claim",
        lambda **_values: pytest.fail("due automatic acceptance must be finalized first"),
    )

    assert service.advance_once(runner_id="runner-auto") is True
    assert calls == [("reconcile", "legacyworkunit-ready")]


def test_runner_reconciles_due_work_when_an_in_flight_handoff_blocks_claim(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _service_without_init()
    calls: list[tuple[str, str]] = []
    monkeypatch.setattr(service, "claim", lambda **_values: None)
    monkeypatch.setattr(service, "_reserve_reconciliation", lambda _now: "legacyworkunit-x")
    monkeypatch.setattr(
        service,
        "reconcile_work_unit",
        lambda work_unit_id, *, observed_at: calls.append(("reconcile", work_unit_id)),
    )

    assert service.advance_once(runner_id="runner-b") is True
    assert calls == [("reconcile", "legacyworkunit-x")]


def test_runner_is_idle_when_no_claim_or_reconciliation_is_available(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _service_without_init()
    monkeypatch.setattr(service, "claim", lambda **_values: None)
    monkeypatch.setattr(service, "_reserve_reconciliation", lambda _now: None)

    assert service.advance_once(runner_id="runner-idle") is False


def test_claim_does_not_consume_another_unit_while_one_handoff_is_in_flight(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _service_without_init()
    session = SimpleNamespace(execute=lambda _statement: None)

    class Sessions:
        @staticmethod
        def begin() -> object:
            return nullcontext(session)

    service.sessions = cast(Any, Sessions())
    monkeypatch.setattr(service, "_release_expired_claims", lambda _session, _now: None)
    monkeypatch.setattr(
        service,
        "_in_flight_work_unit_id",
        lambda _session: "legacyworkunit-in-flight",
    )

    claimed = service.claim(
        lease_owner="runner-c",
        observed_at=datetime.now(UTC),
    )

    assert claimed is None
    assert frozenset({"CLAIMED", "SUBMITTED"}) == IN_FLIGHT_WORK_UNIT_STATES


def test_explicit_state_table_rejects_skipping_review() -> None:
    record = SimpleNamespace(state="PENDING")
    with pytest.raises(LegacyItemExtractionBatchServiceError) as captured:
        LegacyItemExtractionBatchService._transition_work_unit(
            cast(Any, record),
            "ACCEPTED",
        )
    assert captured.value.code == "LEGACY_EXTRACTION_BATCH_TRANSITION_INVALID"
    assert record.state == "PENDING"


def test_batch_persistence_is_pointer_only_indexed_and_event_history_is_immutable() -> None:
    assert legacy_item_extraction_batch_models.__name__.endswith(
        "legacy_item_extraction_batch_models"
    )
    table_names = {
        LegacyItemExtractionBatchRecord.__tablename__,
        LegacyItemExtractionBatchWorkUnitRecord.__tablename__,
        LegacyItemExtractionBatchEventRecord.__tablename__,
    }
    assert set(Base.metadata.tables) >= table_names
    for table_name in table_names:
        table = Base.metadata.tables[table_name]
        assert all(not isinstance(column.type, LargeBinary) for column in table.columns)
    for table_name in table_names - {"legacy_item_extraction_batch_events"}:
        assert {"bytes", "content", "document", "nas_path", "payload"}.isdisjoint(
            Base.metadata.tables[table_name].columns.keys()
        )

    work_unit_indexes = {
        str(index.name)
        for index in Base.metadata.tables["legacy_item_extraction_batch_work_units"].indexes
    }
    assert work_unit_indexes >= {
        "ix_legacy_item_extraction_batch_work_unit_claim",
        "uq_legacy_item_extraction_batch_work_unit_workflow",
    }
    source = Path("migrations/versions/20260903_0027_legacy_item_extraction_batches.py").read_text(
        encoding="utf-8"
    )
    assert 'down_revision: str | None = "20260903_0026"' in source
    assert "FOR EACH ROW EXECUTE FUNCTION reject_legacy_assessment_immutable_mutation()" in source
    assert "DELETE FROM" not in source
    assert "LargeBinary" not in source


def test_catalog_runner_owns_automatic_batch_progression() -> None:
    source = Path("services/catalog_service/eom_catalog_service/application_runner.py").read_text(
        encoding="utf-8"
    )
    assert "legacy_extraction_batches.advance_once(runner_id=runner_id)" in source
    assert "LEGACY_ITEM_EXTRACTION_BATCH_RUNNER_ERROR" in source


def test_cli_exposes_pointer_only_batch_operations() -> None:
    result = CliRunner().invoke(app, ["legacy-assessment", "extraction-batch", "--help"])
    assert result.exit_code == 0
    for command in ("create", "inspect", "work-units", "claim", "submit", "reconcile"):
        assert command in result.stdout
