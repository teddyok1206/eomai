from __future__ import annotations

import json
from contextlib import nullcontext
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from eom_api.services.control_plane_adapter import ControlPlaneAdapter
from eom_api_contracts.control_plane import CodexAccountView
from eom_orchestrator.control_models import CodexAuthBindingRecord
from eom_orchestrator.general_chat_models import GeneralChatCapacityRecord
from eom_web_gui.contracts import CodexAccountStatusView
from jsonschema import Draft202012Validator
from pydantic import ValidationError

ROOT = Path(__file__).resolve().parents[2]
NOW = datetime(2026, 11, 10, 12, tzinfo=UTC)
FIELDS = {"assignment_purpose", "active_chat_count", "chat_runtime_state"}


def binding(slot_id: str = "06") -> CodexAuthBindingRecord:
    return CodexAuthBindingRecord(
        binding_id="authbinding_" + slot_id[1] * 32,
        worker_slot_id=slot_id,
        account_label="test-slot",
        state="READY",
        reason_code=None,
        codex_cli_version="0.162.1",
        observed_at=NOW,
        valid_until=NOW + timedelta(minutes=15),
        resource_version=1,
    )


def capacity(*, active: bool = False) -> GeneralChatCapacityRecord:
    return GeneralChatCapacityRecord(
        slot_key="chat",
        worker_slot_id="06",
        runtime_id="runtime-test",
        heartbeat_at=NOW,
        active_turn_id="chatturn_" + "1" * 32 if active else None,
        expires_at=NOW + timedelta(minutes=5) if active else None,
    )


def project(
    row: CodexAuthBindingRecord, chat: GeneralChatCapacityRecord | None
) -> CodexAccountView:
    return ControlPlaneAdapter._account(
        row,
        capabilities=(),
        active_lease_count=0,
        last_successful_job_id=None,
        active_auth_enrollment=None,
        usage_observation=None,
        chat_capacity=chat,
        projected_at=NOW,
    )


@pytest.mark.parametrize(
    ("case", "expected_state", "expected_count"),
    [
        ("idle", "READY", 0),
        ("active", "BUSY", 1),
        ("expired_heartbeat", "UNAVAILABLE", 1),
        ("future_heartbeat", "UNAVAILABLE", 1),
        ("expired_claim", "UNAVAILABLE", 1),
        ("missing_runtime", "UNAVAILABLE", 0),
        ("disabled", "UNAVAILABLE", 1),
        ("expired_binding", "UNAVAILABLE", 1),
    ],
)
def test_chat_occupation_is_not_a_fake_lease_or_stale_answer(
    case: str, expected_state: str, expected_count: int
) -> None:
    row = binding()
    chat = capacity(active=case not in {"idle", "missing_runtime"})
    if case == "expired_heartbeat":
        chat.heartbeat_at = NOW - timedelta(seconds=31)
    elif case == "future_heartbeat":
        chat.heartbeat_at = NOW + timedelta(seconds=1)
    elif case == "expired_claim":
        chat.expires_at = NOW - timedelta(seconds=1)
    elif case == "missing_runtime":
        chat.runtime_id = chat.heartbeat_at = None
    elif case == "disabled":
        row.state = "DISABLED"
    elif case == "expired_binding":
        row.valid_until = NOW
    result = project(row, chat)
    assert result.assignment_purpose == "GENERAL_CHAT"
    assert result.active_chat_count == expected_count
    assert result.chat_runtime_state == expected_state
    assert result.active_lease_count == 0
    assert result.state == row.state
    assert CodexAccountStatusView.model_validate(result.model_dump(mode="json")).model_dump(
        mode="json"
    ) == result.model_dump(mode="json")


@pytest.mark.parametrize("reserved", [False, True])
def test_other_slots_and_legacy_dedicated_chat_do_not_gain_an_assignment(reserved: bool) -> None:
    chat = capacity(active=True)
    if not reserved:
        chat.worker_slot_id = None
    result = project(binding("05" if reserved else "06"), chat)
    assert result.assignment_purpose == "GENERAL_WORK"
    assert result.active_chat_count == 0
    assert result.chat_runtime_state is None


def test_old_account_response_remains_readable_and_assignment_schema_matches() -> None:
    original = project(binding(), None).model_dump(mode="json")
    old = {key: value for key, value in original.items() if key not in FIELDS}
    assert CodexAccountView.model_validate(old).model_dump(mode="json") == original
    assert CodexAccountStatusView.model_validate(old).model_dump(mode="json") == original
    path = "schemas/api/v1/codex-slot-assignment-v1.schema.json"
    schema = json.loads((ROOT / path).read_text())
    packaged = ROOT / "packages/api_contracts/eom_api_contracts/schemas" / Path(path).name
    assert json.loads(packaged.read_text()) == schema
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema)
    for purpose in ("GENERAL_WORK", "GENERAL_CHAT"):
        for count in (0, 1, 2):
            for state in (None, "READY", "BUSY", "UNAVAILABLE"):
                assignment = dict(
                    assignment_purpose=purpose, active_chat_count=count, chat_runtime_state=state
                )
                schema_valid = validator.is_valid(assignment)
                for model in (CodexAccountView, CodexAccountStatusView):
                    if schema_valid:
                        model.model_validate(old | assignment)
                    else:
                        with pytest.raises(ValidationError):
                            model.model_validate(old | assignment)


def test_account_list_reads_chat_singleton_once_for_all_six_slots() -> None:
    rows = tuple(binding(f"0{number}") for number in range(1, 7))
    chat = capacity(active=True)
    chat.heartbeat_at = datetime.now(UTC)
    chat.expires_at = chat.heartbeat_at + timedelta(minutes=5)
    for row in rows:
        row.valid_until = chat.expires_at

    class Session:
        reads = 0

        def get(self, model: type, identifier: str) -> GeneralChatCapacityRecord:
            assert model is GeneralChatCapacityRecord and identifier == "chat"
            self.reads += 1
            return chat

        def scalars(self, statement: Any) -> tuple:
            if statement.column_descriptions[0]["entity"] is CodexAuthBindingRecord:
                return rows
            return ()

        def execute(self, statement: Any) -> SimpleNamespace:
            return SimpleNamespace(all=lambda: [])

    session = Session()
    adapter = object.__new__(ControlPlaneAdapter)
    adapter.sessions = cast(Any, lambda: nullcontext(session))
    result = adapter.list_accounts()
    assert session.reads == 1
    assert len(result) == 6
    assert [value.slot_key for value in result if value.assignment_purpose == "GENERAL_CHAT"] == [
        "slot06"
    ]
    assert [value.active_chat_count for value in result] == [0, 0, 0, 0, 0, 1]
    assert sum(value.active_lease_count for value in result) == 0
