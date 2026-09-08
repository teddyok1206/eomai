#!/srv/eom/conda/envs/eom-api/bin/python
"""Verify exact retirement evidence before releasing the Workflow-runner hold."""

from __future__ import annotations

import argparse
import fcntl
import grp
import importlib.resources
import importlib.util
import json
import os
import pwd
import re
import site
import stat
import sys
from collections import Counter
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Never

from jsonschema import Draft202012Validator, FormatChecker
from pydantic import ValidationError

if TYPE_CHECKING:
    from eom_api_contracts.mock_exam_execution import MockExamProductionExecution
    from eom_api_contracts.mock_exam_retirement import MockExamProductionRetirementReceiptV1

_CHECKPOINT_ROOT = Path("/var/lib/eom-api/mock-exam-production")
_RECEIPT_ROOT = Path("/var/lib/eom-api/mock-exam-retirement-receipts")
_MAX_RECEIPT_BYTES = 1024 * 1024
_MAX_CHECKPOINT_BYTES = 2 * 1024 * 1024
_EXECUTION_ID = re.compile(r"^productionexec_[0-9a-f]{32}$")
_EXECUTION_REVISION_ID = re.compile(r"^productionexecrev_[0-9a-f]{32}$")
_PRODUCTION_REQUEST_ID = re.compile(r"^productionreq_[0-9a-f]{32}$")
_PRODUCTION_PLAN_ID = re.compile(r"^productionplan_[0-9a-f]{32}$")
_OPERATOR_ID = re.compile(r"^operator_[0-9a-f]{32}$")
_SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")
_CANCELLABLE_WORKFLOW_STATES = frozenset(
    {
        "REQUESTED",
        "RUNNING",
        "AWAITING_HUMAN_APPROVAL",
        "REWORK_REQUESTED",
        "APPROVED",
        "REGISTERING",
    }
)


class HoldReleaseReceiptError(RuntimeError):
    """Stable failure before any deployment-hold mutation."""


@dataclass(frozen=True)
class ExpectedRetirementPins:
    execution_id: str
    execution_revision_id: str
    checkpoint_sha256: str
    production_request_id: str
    production_plan_id: str
    production_plan_sha256: str
    operator_id: str
    receipt_sha256: str

    def validate(self) -> None:
        patterns = (
            (_EXECUTION_ID, self.execution_id),
            (_EXECUTION_REVISION_ID, self.execution_revision_id),
            (_SHA256, self.checkpoint_sha256),
            (_PRODUCTION_REQUEST_ID, self.production_request_id),
            (_PRODUCTION_PLAN_ID, self.production_plan_id),
            (_SHA256, self.production_plan_sha256),
            (_OPERATOR_ID, self.operator_id),
            (_SHA256, self.receipt_sha256),
        )
        if any(pattern.fullmatch(value) is None for pattern, value in patterns):
            _fail("expected retirement pointer is malformed")


@dataclass(frozen=True)
class FileOwner:
    uid: int
    gid: int


@dataclass
class _CheckpointReadLease:
    current: bytes
    immutable: bytes
    lock_descriptor: int

    def close(self) -> None:
        os.close(self.lock_descriptor)


@contextmanager
def _validated_release_receipt_lock(
    *,
    receipt_path: Path,
    expected: ExpectedRetirementPins,
    checkpoint_root: Path = _CHECKPOINT_ROOT,
    receipt_root: Path = _RECEIPT_ROOT,
    receipt_owner: FileOwner | None = None,
    checkpoint_owner: FileOwner | None = None,
) -> Iterator[MockExamProductionRetirementReceiptV1]:
    """Validate exact evidence while exclusively fencing every checkpoint writer."""

    expected.validate()
    _require_installed_contract_packages()
    from eom_api_contracts.mock_exam_execution import MockExamProductionExecution
    from eom_api_contracts.mock_exam_retirement import MockExamProductionRetirementReceiptV1
    from pydantic import TypeAdapter

    if (
        not receipt_path.is_absolute()
        or not receipt_root.is_absolute()
        or not checkpoint_root.is_absolute()
    ):
        _fail("retirement evidence paths must be absolute")
    expected_receipt_path = receipt_root / (f"{expected.execution_id}.retirement-receipt.json")
    if receipt_path != expected_receipt_path:
        _fail("retirement receipt path does not match the expected execution")
    receipt_owner = receipt_owner or _account_owner("eom-api")
    checkpoint_owner = checkpoint_owner or _account_owner("eom-api")
    receipt_root_descriptor = _open_directory(
        receipt_root,
        owner=receipt_owner,
        allowed_modes=frozenset({0o700}),
    )
    try:
        receipt_payload = _read_directory_file(
            receipt_root_descriptor,
            receipt_path.name,
            owner=receipt_owner,
            allowed_modes=frozenset({0o600}),
            maximum_bytes=_MAX_RECEIPT_BYTES,
        )
    finally:
        os.close(receipt_root_descriptor)
    envelope = _load_json_object(receipt_payload)
    if set(envelope) != {"status", "data"} or envelope["status"] != "SUCCEEDED":
        _fail("retirement receipt envelope is invalid")
    data = envelope["data"]
    if not isinstance(data, dict):
        _fail("retirement receipt payload is invalid")
    _validate_json_schema(data, "mock-exam-production-retirement-v1.schema.json")
    try:
        receipt = MockExamProductionRetirementReceiptV1.model_validate(data)
    except ValidationError as exc:
        raise HoldReleaseReceiptError("retirement receipt contract is invalid") from exc

    checkpoint_lease = _read_checkpoint_pair(
        checkpoint_root,
        expected.execution_id,
        owner=checkpoint_owner,
    )
    try:
        if checkpoint_lease.current != checkpoint_lease.immutable:
            _fail("current checkpoint differs from its immutable revision")
        checkpoint_data = _load_json_object(checkpoint_lease.current)
        schema_version = checkpoint_data.get("schema_version")
        schema_by_version = {
            "mock-exam-production-execution/1.0": ("mock-exam-production-execution-v1.schema.json"),
            "mock-exam-production-execution/2.0": ("mock-exam-production-execution-v2.schema.json"),
        }
        if not isinstance(schema_version, str) or schema_version not in schema_by_version:
            _fail("production checkpoint schema version is invalid")
        _validate_json_schema(checkpoint_data, schema_by_version[schema_version])
        try:
            checkpoint: MockExamProductionExecution = TypeAdapter(
                MockExamProductionExecution
            ).validate_python(checkpoint_data)
        except ValidationError as exc:
            raise HoldReleaseReceiptError("production checkpoint contract is invalid") from exc

        _require_exact_pins(receipt, checkpoint, expected)
        _require_exact_outcomes(receipt, checkpoint)
        _require_exact_command_hash(receipt, checkpoint)
        yield receipt
    finally:
        checkpoint_lease.close()


def validate_release_receipt(
    *,
    receipt_path: Path,
    expected: ExpectedRetirementPins,
    checkpoint_root: Path = _CHECKPOINT_ROOT,
    receipt_root: Path = _RECEIPT_ROOT,
    receipt_owner: FileOwner | None = None,
    checkpoint_owner: FileOwner | None = None,
) -> MockExamProductionRetirementReceiptV1:
    """Validate the explicit receipt and its canonical checkpoint without mutation."""

    with _validated_release_receipt_lock(
        receipt_path=receipt_path,
        expected=expected,
        checkpoint_root=checkpoint_root,
        receipt_root=receipt_root,
        receipt_owner=receipt_owner,
        checkpoint_owner=checkpoint_owner,
    ) as receipt:
        return receipt


def _read_checkpoint_pair(
    checkpoint_root: Path,
    execution_id: str,
    *,
    owner: FileOwner,
) -> _CheckpointReadLease:
    root_descriptor = _open_directory(
        checkpoint_root,
        owner=owner,
        allowed_modes=frozenset({0o700, 0o750}),
    )
    lock_descriptor: int | None = None
    execution_descriptor: int | None = None
    try:
        lock_descriptor = _open_checkpoint_lock(
            root_descriptor,
            f".{execution_id}.lock",
            owner=owner,
        )
        execution_descriptor = _open_directory_entry(
            root_descriptor,
            execution_id,
            owner=owner,
            allowed_modes=frozenset({0o700, 0o750}),
        )
        current = _read_directory_file(
            execution_descriptor,
            "current.json",
            owner=owner,
            allowed_modes=frozenset({0o600, 0o640}),
            maximum_bytes=_MAX_CHECKPOINT_BYTES,
        )
        current_data = _load_json_object(current)
        revision_id = current_data.get("execution_revision_id")
        if (
            not isinstance(revision_id, str)
            or _EXECUTION_REVISION_ID.fullmatch(revision_id) is None
        ):
            _fail("production checkpoint revision pointer is invalid")
        immutable = _read_directory_file(
            execution_descriptor,
            f"{revision_id}.json",
            owner=owner,
            allowed_modes=frozenset({0o600, 0o640}),
            maximum_bytes=_MAX_CHECKPOINT_BYTES,
        )
        if (
            _read_directory_file(
                execution_descriptor,
                "current.json",
                owner=owner,
                allowed_modes=frozenset({0o600, 0o640}),
                maximum_bytes=_MAX_CHECKPOINT_BYTES,
            )
            != current
        ):
            _fail("current checkpoint changed during release validation")
        lease = _CheckpointReadLease(
            current=current,
            immutable=immutable,
            lock_descriptor=lock_descriptor,
        )
        lock_descriptor = None
        return lease
    finally:
        if execution_descriptor is not None:
            os.close(execution_descriptor)
        if lock_descriptor is not None:
            os.close(lock_descriptor)
        os.close(root_descriptor)


def _open_checkpoint_lock(
    root_descriptor: int,
    name: str,
    *,
    owner: FileOwner,
) -> int:
    if Path(name).name != name:
        _fail("checkpoint lock identity is invalid")
    flags = os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW | os.O_NONBLOCK
    try:
        descriptor = os.open(name, flags, dir_fd=root_descriptor)
    except OSError as exc:
        raise HoldReleaseReceiptError("checkpoint lock is unavailable") from exc
    try:
        metadata = os.fstat(descriptor)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_uid != owner.uid
            or metadata.st_gid != owner.gid
            or metadata.st_nlink != 1
            or stat.S_IMODE(metadata.st_mode) not in {0o600, 0o640}
            or metadata.st_size != 0
        ):
            _fail("checkpoint lock identity is invalid")
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except (OSError, HoldReleaseReceiptError) as exc:
        os.close(descriptor)
        if isinstance(exc, HoldReleaseReceiptError):
            raise
        raise HoldReleaseReceiptError("checkpoint lock is unavailable") from exc
    return descriptor


def _require_exact_pins(
    receipt: MockExamProductionRetirementReceiptV1,
    checkpoint: Any,
    expected: ExpectedRetirementPins,
) -> None:
    from eom_identifiers import content_sha256

    receipt_pins = (
        receipt.execution_id,
        receipt.execution_revision_id,
        receipt.checkpoint_sha256,
        receipt.production_request_id,
        receipt.production_plan_id,
        receipt.production_plan_sha256,
        receipt.operator_id,
        receipt.receipt_sha256,
    )
    expected_pins = (
        expected.execution_id,
        expected.execution_revision_id,
        expected.checkpoint_sha256,
        expected.production_request_id,
        expected.production_plan_id,
        expected.production_plan_sha256,
        expected.operator_id,
        expected.receipt_sha256,
    )
    checkpoint_pins = (
        checkpoint.execution_id,
        checkpoint.execution_revision_id,
        checkpoint.checkpoint_sha256,
        checkpoint.production_request_id,
        checkpoint.production_plan_id,
        checkpoint.production_plan_sha256,
        checkpoint.operator_id,
    )
    if receipt_pins != expected_pins or checkpoint_pins != expected_pins[:-1]:
        _fail("retirement receipt does not match the expected production checkpoint")
    retirement_digest = content_sha256(
        {
            "schema_version": "mock-exam-production-retirement-identity/1.0",
            "execution_id": checkpoint.execution_id,
            "execution_revision_id": checkpoint.execution_revision_id,
            "checkpoint_sha256": checkpoint.checkpoint_sha256,
            "reason_code": "SUPERSEDED_BY_CORRECTED_PROTOCOL",
        }
    )
    if receipt.retirement_id != (
        "productionretire_" + retirement_digest.removeprefix("sha256:")[:32]
    ):
        _fail("retirement identity does not match the pinned checkpoint")


def _require_exact_outcomes(
    receipt: MockExamProductionRetirementReceiptV1,
    checkpoint: Any,
) -> None:
    dispositions = Counter(outcome.disposition for outcome in receipt.outcomes)
    if dispositions != Counter({"CANCEL_QUEUED": 24, "UNSUCCESSFUL_TERMINAL_PRESERVED": 1}):
        _fail("retirement receipt disposition aggregate is invalid")
    preserved = tuple(
        outcome
        for outcome in receipt.outcomes
        if outcome.disposition == "UNSUCCESSFUL_TERMINAL_PRESERVED"
    )
    if len(preserved) != 1 or preserved[0].prior_workflow_state != "FAILED":
        _fail("retirement receipt must preserve exactly one failed Workflow")
    if any(
        outcome.prior_workflow_state not in _CANCELLABLE_WORKFLOW_STATES
        for outcome in receipt.outcomes
        if outcome.disposition == "CANCEL_QUEUED"
    ):
        _fail("only active Workflow states may have queued retirement cancellation")
    cancel_ids = tuple(
        outcome.cancel_command_id
        for outcome in receipt.outcomes
        if outcome.disposition == "CANCEL_QUEUED"
    )
    if None in cancel_ids or len(set(cancel_ids)) != 24:
        _fail("retirement cancellation command pointers must be unique")
    expected_cohort = tuple(
        (row.position, row.workflow_call_id, row.workflow_id) for row in checkpoint.item_runs
    )
    observed_cohort = tuple(
        (outcome.position, outcome.workflow_call_id, outcome.workflow_id)
        for outcome in receipt.outcomes
    )
    if any(row[2] is None for row in expected_cohort) or observed_cohort != expected_cohort:
        _fail("retirement receipt does not cover the pinned Workflow cohort")


def _require_exact_command_hash(
    receipt: MockExamProductionRetirementReceiptV1,
    checkpoint: Any,
) -> None:
    from eom_api_contracts.mock_exam_retirement import MockExamProductionRetirementCommandV1
    from eom_identifiers import content_sha256

    rows_by_position = {row.position: row for row in checkpoint.item_runs}
    bindings: list[dict[str, Any]] = []
    for outcome in receipt.outcomes:
        row = rows_by_position[outcome.position]
        if row.start_command_id is None:
            _fail("pinned production checkpoint has no start-command identity")
        bindings.append(
            {
                "position": outcome.position,
                "workflow_call_id": outcome.workflow_call_id,
                "workflow_id": outcome.workflow_id,
                "start_command_id": row.start_command_id,
                "expected_workflow_resource_version": (outcome.expected_workflow_resource_version),
                "observed_workflow_state": outcome.prior_workflow_state,
            }
        )
    command_body = {
        "schema_version": "mock-exam-production-retirement-command/1.0",
        "retirement_id": receipt.retirement_id,
        "execution_id": receipt.execution_id,
        "execution_revision_id": receipt.execution_revision_id,
        "checkpoint_sha256": receipt.checkpoint_sha256,
        "production_request_id": receipt.production_request_id,
        "production_plan_id": receipt.production_plan_id,
        "production_plan_sha256": receipt.production_plan_sha256,
        "operator_id": receipt.operator_id,
        "reason_code": receipt.reason_code,
        "authorized_at": receipt.retired_at.isoformat().replace("+00:00", "Z"),
        "bindings": bindings,
    }
    if content_sha256(command_body) != receipt.command_sha256:
        _fail("retirement receipt command hash does not match the pinned cohort")
    try:
        MockExamProductionRetirementCommandV1.model_validate(
            {**command_body, "command_sha256": receipt.command_sha256}
        )
    except ValidationError as exc:
        raise HoldReleaseReceiptError("retirement command contract is invalid") from exc


def _validate_json_schema(document: dict[str, Any], schema_name: str) -> None:
    try:
        schema_resource = importlib.resources.files("eom_api_contracts") / "schemas" / schema_name
        schema = json.loads(schema_resource.read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)
        Draft202012Validator(schema, format_checker=FormatChecker()).validate(document)
    except Exception as exc:
        raise HoldReleaseReceiptError("installed JSON Schema validation failed") from exc


def _require_installed_contract_packages() -> None:
    site_roots = tuple(Path(value).resolve() for value in site.getsitepackages())
    for package in ("eom_api_contracts", "eom_identifiers"):
        specification = importlib.util.find_spec(package)
        if specification is None or specification.origin is None:
            _fail("installed release contract package is unavailable")
        origin = Path(specification.origin).resolve()
        if not any(origin.is_relative_to(root) for root in site_roots):
            _fail("release contracts were not loaded from the installed environment")


def _load_json_object(payload: bytes) -> dict[str, Any]:
    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                _fail("JSON document contains a duplicate key")
            result[key] = value
        return result

    try:
        document = json.loads(
            payload.decode("utf-8", errors="strict"),
            object_pairs_hook=reject_duplicates,
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HoldReleaseReceiptError("retirement evidence JSON is invalid") from exc
    if not isinstance(document, dict):
        _fail("retirement evidence must be a JSON object")
    return document


def _open_directory(
    path: Path,
    *,
    owner: FileOwner,
    allowed_modes: frozenset[int],
) -> int:
    flags = os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW | os.O_DIRECTORY
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise HoldReleaseReceiptError("checkpoint directory is unavailable") from exc
    try:
        _require_directory(os.fstat(descriptor), owner, allowed_modes)
    except Exception:
        os.close(descriptor)
        raise
    return descriptor


def _open_directory_entry(
    parent_descriptor: int,
    name: str,
    *,
    owner: FileOwner,
    allowed_modes: frozenset[int],
) -> int:
    if Path(name).name != name:
        _fail("checkpoint directory identity is invalid")
    flags = os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW | os.O_DIRECTORY
    try:
        descriptor = os.open(name, flags, dir_fd=parent_descriptor)
    except OSError as exc:
        raise HoldReleaseReceiptError("checkpoint execution directory is unavailable") from exc
    try:
        _require_directory(os.fstat(descriptor), owner, allowed_modes)
    except Exception:
        os.close(descriptor)
        raise
    return descriptor


def _read_directory_file(
    directory_descriptor: int,
    name: str,
    *,
    owner: FileOwner,
    allowed_modes: frozenset[int],
    maximum_bytes: int,
) -> bytes:
    if Path(name).name != name:
        _fail("checkpoint file identity is invalid")
    flags = os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW | os.O_NONBLOCK
    try:
        descriptor = os.open(name, flags, dir_fd=directory_descriptor)
    except OSError as exc:
        raise HoldReleaseReceiptError("checkpoint file is unavailable") from exc
    try:
        return _read_open_file(
            descriptor,
            owner=owner,
            allowed_modes=allowed_modes,
            maximum_bytes=maximum_bytes,
        )
    finally:
        os.close(descriptor)


def _read_open_file(
    descriptor: int,
    *,
    owner: FileOwner,
    allowed_modes: frozenset[int],
    maximum_bytes: int,
) -> bytes:
    before = os.fstat(descriptor)
    _require_file(before, owner, allowed_modes, maximum_bytes)
    chunks = bytearray()
    saw_eof = False
    while len(chunks) <= maximum_bytes:
        chunk = os.read(descriptor, min(64 * 1024, maximum_bytes + 1 - len(chunks)))
        if not chunk:
            saw_eof = True
            break
        chunks.extend(chunk)
    after = os.fstat(descriptor)
    if (
        not saw_eof
        or len(chunks) != before.st_size
        or _file_identity(before) != _file_identity(after)
    ):
        _fail("retirement evidence file changed while it was read")
    return bytes(chunks)


def _require_directory(
    metadata: os.stat_result,
    owner: FileOwner,
    allowed_modes: frozenset[int],
) -> None:
    if (
        not stat.S_ISDIR(metadata.st_mode)
        or metadata.st_uid != owner.uid
        or metadata.st_gid != owner.gid
        or stat.S_IMODE(metadata.st_mode) not in allowed_modes
    ):
        _fail("checkpoint directory identity is invalid")


def _require_file(
    metadata: os.stat_result,
    owner: FileOwner,
    allowed_modes: frozenset[int],
    maximum_bytes: int,
) -> None:
    if (
        not stat.S_ISREG(metadata.st_mode)
        or metadata.st_uid != owner.uid
        or metadata.st_gid != owner.gid
        or metadata.st_nlink != 1
        or stat.S_IMODE(metadata.st_mode) not in allowed_modes
        or not 0 < metadata.st_size <= maximum_bytes
    ):
        _fail("retirement evidence file identity is invalid")


def _file_identity(metadata: os.stat_result) -> tuple[int, ...]:
    return (
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_mode,
        metadata.st_uid,
        metadata.st_gid,
        metadata.st_nlink,
        metadata.st_size,
        metadata.st_mtime_ns,
        metadata.st_ctime_ns,
    )


def _account_owner(name: str) -> FileOwner:
    try:
        account = pwd.getpwnam(name)
        group = grp.getgrgid(account.pw_gid)
    except KeyError as exc:
        raise HoldReleaseReceiptError("required local account is unavailable") from exc
    if group.gr_gid != account.pw_gid or group.gr_name != name:
        _fail("required local account group is invalid")
    return FileOwner(uid=account.pw_uid, gid=account.pw_gid)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--receipt-file", required=True, type=Path)
    parser.add_argument("--execution-id", required=True)
    parser.add_argument("--execution-revision-id", required=True)
    parser.add_argument("--checkpoint-sha256", required=True)
    parser.add_argument("--production-request-id", required=True)
    parser.add_argument("--production-plan-id", required=True)
    parser.add_argument("--production-plan-sha256", required=True)
    parser.add_argument("--operator-id", required=True)
    parser.add_argument("--receipt-sha256", required=True)
    parser.add_argument("--hold-lock-until-release-signal", action="store_true")
    return parser


def main() -> int:
    arguments = _parser().parse_args()
    expected = ExpectedRetirementPins(
        execution_id=arguments.execution_id,
        execution_revision_id=arguments.execution_revision_id,
        checkpoint_sha256=arguments.checkpoint_sha256,
        production_request_id=arguments.production_request_id,
        production_plan_id=arguments.production_plan_id,
        production_plan_sha256=arguments.production_plan_sha256,
        operator_id=arguments.operator_id,
        receipt_sha256=arguments.receipt_sha256,
    )
    try:
        if arguments.hold_lock_until_release_signal:
            with _validated_release_receipt_lock(
                receipt_path=arguments.receipt_file,
                expected=expected,
            ):
                print("workflow_runner_hold_release_receipt=VERIFIED_LOCKED", flush=True)
                signal = sys.stdin.buffer.readline(64)
                if signal != b"RELEASE_COMPLETE\n":
                    _fail("hold release completion signal is invalid")
            print("workflow_runner_hold_release_receipt=RELEASE_CONFIRMED", flush=True)
        else:
            validate_release_receipt(
                receipt_path=arguments.receipt_file,
                expected=expected,
            )
            print("workflow_runner_hold_release_receipt=VERIFIED")
    except (HoldReleaseReceiptError, OSError, ValueError):
        raise SystemExit("workflow runner hold release receipt validation failed") from None
    return 0


def _fail(message: str) -> Never:
    raise HoldReleaseReceiptError(message)


if __name__ == "__main__":
    raise SystemExit(main())
