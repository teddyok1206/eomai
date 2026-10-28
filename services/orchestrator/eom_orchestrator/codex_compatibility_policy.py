"""Admission of committed live compatibility evidence into the reviewed allowlist."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from eom_identifiers import content_sha256, sha256_bytes
from eom_protocol.artifact_members import ArtifactMemberPointer
from eom_workflow.codex_compatibility import (
    CodexCompatibilityInvocation,
    CodexCompatibilityReport,
    CodexCompatibilityRuntime,
    load_compatibility_report,
    load_compatibility_request,
)
from eom_workflow.control_schemas import validate_control_contract
from jsonschema.exceptions import ValidationError as JsonSchemaValidationError
from sqlalchemy import Engine, select

from eom_orchestrator.codex_compatibility_probe import synthetic_probe_png, validate_probe_result
from eom_orchestrator.control_artifact_resolution import (
    BoundedControlArtifactRead,
    resolve_control_artifact_member,
    resolve_control_artifact_members,
)
from eom_orchestrator.control_models import CodexAuthBindingRecord
from eom_orchestrator.control_service import ControlPlaneError
from eom_orchestrator.database import build_session_factory
from eom_orchestrator.file_set_control_artifacts import (
    CONTROL_FILE_SET_PROTOCOL,
    CONTROL_FILE_SET_SCHEMA_HASH,
)
from eom_orchestrator.models import (
    ArtifactRecord,
    ArtifactRevisionRecord,
    JobRecord,
    ProtocolVersionRecord,
    WorkerSlotRecord,
)
from eom_orchestrator.reviewed_capability_policy import (
    COMPATIBILITY_SLOT_ROLES,
    ReviewedCapabilityBindingV3,
    ReviewedCapabilityPolicy,
    ReviewedModelCapability,
)

COMPATIBILITY_ARTIFACT_TYPE = "control_codex_runtime_compatibility"
COMPATIBILITY_REPORT_SCHEMA = "eom://schemas/workflow/codex-compatibility-report/1.0"
COMPATIBILITY_REQUEST_SCHEMA = "eom://schemas/workflow/codex-compatibility-request/1.0"
COMPATIBILITY_RESULT_SCHEMA = "eom://schemas/workflow/codex-compatibility-probe-result/1.0"
COMPATIBILITY_MANIFEST_VERSION = "codex-compatibility-file-set/1.0"
MAX_REPORT_BYTES = 128 * 1024
MAX_REPORT_AGE = timedelta(hours=24)


@dataclass(frozen=True, slots=True)
class CompatibilityAdmissionBinding:
    slot_id: str
    binding_id: str
    assignment_revision_id: str | None
    resource_version: int


def _invalid(message: str) -> ControlPlaneError:
    return ControlPlaneError("CONTROL_COMPATIBILITY_POLICY_INVALID", message)


def _unique_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def parse_compatibility_report(payload: bytes) -> CodexCompatibilityReport:
    if not 0 < len(payload) <= MAX_REPORT_BYTES:
        raise _invalid("compatibility report exceeds the bounded materialization")
    try:
        document = json.loads(payload.decode("utf-8"), object_pairs_hook=_unique_json_object)
        return load_compatibility_report(document)
    except (ValueError, UnicodeError, JsonSchemaValidationError) as exc:
        raise _invalid("compatibility report is malformed") from exc


def load_committed_compatibility_report(
    engine: Engine, pointer: ArtifactMemberPointer
) -> CodexCompatibilityReport:
    """Read an exact approved member, never accept a local JSON admission receipt."""

    if (
        pointer.schema_ref != COMPATIBILITY_REPORT_SCHEMA
        or pointer.media_type != "application/json"
    ):
        raise _invalid("compatibility Artifact schema or media type differs")
    with build_session_factory(engine)() as session:
        row = session.execute(
            select(ArtifactRevisionRecord, ArtifactRecord, JobRecord, ProtocolVersionRecord)
            .join(
                ArtifactRecord,
                ArtifactRecord.logical_artifact_id == ArtifactRevisionRecord.logical_artifact_id,
            )
            .join(JobRecord, JobRecord.job_id == ArtifactRevisionRecord.job_id)
            .join(
                ProtocolVersionRecord, ProtocolVersionRecord.version == JobRecord.protocol_version
            )
            .where(
                ArtifactRevisionRecord.revision_id == pointer.artifact_revision_id,
                ArtifactRevisionRecord.logical_artifact_id == pointer.artifact_id,
            )
        ).one_or_none()
        if row is None:
            raise _invalid("compatibility publication is missing")
        revision, artifact, job, protocol = row
        manifest = revision.manifest
        if (
            not artifact.approved
            or not revision.approved
            or job.status != "SUCCEEDED"
            or job.protocol_version != CONTROL_FILE_SET_PROTOCOL
            or protocol.schema_sha256 != CONTROL_FILE_SET_SCHEMA_HASH
            or job.task_type != COMPATIBILITY_ARTIFACT_TYPE
            or artifact.artifact_type != COMPATIBILITY_ARTIFACT_TYPE
            or artifact.job_id != job.job_id
            or job.logical_artifact_id != pointer.artifact_id
            or job.revision_id != pointer.artifact_revision_id
            or revision.content_hash != pointer.sha256
            or not isinstance(manifest, dict)
            or manifest.get("manifest_version") != COMPATIBILITY_MANIFEST_VERSION
            or manifest.get("artifact_type") != COMPATIBILITY_ARTIFACT_TYPE
            or manifest.get("primary_file") != pointer.member_path
            or manifest.get("job_id") != job.job_id
            or manifest.get("logical_artifact_id") != pointer.artifact_id
            or manifest.get("revision_id") != pointer.artifact_revision_id
            or content_sha256(manifest) != revision.manifest_hash
            or job.request_hash
            != content_sha256(
                {
                    "protocol_version": job.protocol_version,
                    "task_type": job.task_type,
                    "request": job.request,
                }
            )
        ):
            raise _invalid("compatibility publication is not canonical and committed")
        publication_request = dict(job.request)
        if (
            publication_request.get("artifact_type") != COMPATIBILITY_ARTIFACT_TYPE
            or publication_request.get("manifest_version") != COMPATIBILITY_MANIFEST_VERSION
            or publication_request.get("primary_file") != "report.json"
            or pointer.member_path != "report.json"
            or publication_request.get("members") != manifest.get("files")
            or revision.result != {"schema_version": "control-file-set-result/1.0", **job.request}
        ):
            raise _invalid("compatibility publication members differ from its request")
        raw_members = publication_request.get("members")
        if not isinstance(raw_members, list) or any(
            not isinstance(item, dict) for item in raw_members
        ):
            raise _invalid("compatibility publication members are malformed")
        members = {item.get("file_name"): item for item in raw_members}
        if (
            len(members) != len(raw_members)
            or not {"request.json", "report.json"} <= members.keys()
        ):
            raise _invalid("compatibility publication members are missing or duplicated")
        request_member = members["request.json"]
        report_member = members["report.json"]
    payload = resolve_control_artifact_member(engine, pointer, maximum_bytes=MAX_REPORT_BYTES)
    report = parse_compatibility_report(payload)
    if (
        sha256_bytes(payload) != pointer.sha256
        or publication_request.get("source_commit") != report.request.source_commit
        or report_member.get("sha256") != pointer.sha256
        or report_member.get("bytes") != len(payload)
        or report_member.get("schema_ref") != pointer.schema_ref
        or report_member.get("media_type") != pointer.media_type
        or request_member.get("schema_ref") != COMPATIBILITY_REQUEST_SCHEMA
        or request_member.get("media_type") != "application/json"
    ):
        raise _invalid("compatibility publication request differs from its report")
    try:
        request_pointer = ArtifactMemberPointer.model_validate(
            {
                **pointer.model_dump(mode="json"),
                "member_path": "request.json",
                "schema_ref": COMPATIBILITY_REQUEST_SCHEMA,
                "sha256": request_member.get("sha256"),
            }
        )
        request_bytes = resolve_control_artifact_member(
            engine, request_pointer, maximum_bytes=MAX_REPORT_BYTES
        )
        request = load_compatibility_request(
            json.loads(request_bytes.decode("utf-8"), object_pairs_hook=_unique_json_object)
        )
    except (ValueError, UnicodeError, JsonSchemaValidationError) as exc:
        raise _invalid("compatibility request member is malformed") from exc
    if (
        len(request_bytes) != request_member.get("bytes")
        or request != report.request
        or content_sha256(request.model_dump(mode="json")) != report.request_sha256
    ):
        raise _invalid("compatibility request member differs from its report")
    passed = tuple(case for case in report.cases if case.status == "PASS")
    reads = []
    invocations = []
    image_hash = sha256_bytes(synthetic_probe_png())
    for case in passed:
        member_path = f"{case.case_id}.output.json"
        member = members.get(member_path)
        if (
            member is None
            or member.get("sha256") != case.result_sha256
            or member.get("schema_ref") != COMPATIBILITY_RESULT_SCHEMA
            or member.get("media_type") != "application/json"
        ):
            raise _invalid("passing compatibility result member is missing or differs")
        invocation_document = {
            "schema_version": "codex-compatibility-invocation/1.0",
            "run_id": request.run_id,
            "case_id": case.case_id,
            "request_sha256": report.request_sha256,
            "job_id": case.job_id,
            "model": case.model,
            "reasoning_effort": case.reasoning_effort,
            "image_sha256": image_hash,
        }
        invocation = CodexCompatibilityInvocation.model_validate(
            {**invocation_document, "invocation_sha256": content_sha256(invocation_document)}
        )
        if invocation.invocation_sha256 != case.invocation_sha256:
            raise _invalid("passing compatibility invocation pin differs")
        invocations.append(invocation)
        reads.append(
            BoundedControlArtifactRead(
                pointer.model_copy(
                    update={
                        "member_path": member_path,
                        "schema_ref": COMPATIBILITY_RESULT_SCHEMA,
                        "sha256": case.result_sha256,
                    }
                ),
                maximum_bytes=16384,
            )
        )
    if reads:
        payloads = resolve_control_artifact_members(engine, tuple(reads))
        try:
            for payload, invocation in zip(payloads, invocations, strict=True):
                validate_probe_result(
                    json.loads(payload.decode("utf-8"), object_pairs_hook=_unique_json_object),
                    invocation,
                )
        except (ValueError, UnicodeError, JsonSchemaValidationError) as exc:
            raise _invalid("passing compatibility result proof is invalid") from exc
    return report


def current_admission_bindings(
    engine: Engine, *, runtime: CodexCompatibilityRuntime, now: datetime
) -> tuple[CompatibilityAdmissionBinding, ...]:
    """Six indexed slot/binding lookups in one query; no authentication impersonation."""

    with build_session_factory(engine)() as session:
        rows = session.execute(
            select(CodexAuthBindingRecord, WorkerSlotRecord)
            .join(
                WorkerSlotRecord, WorkerSlotRecord.slot_id == CodexAuthBindingRecord.worker_slot_id
            )
            .where(WorkerSlotRecord.slot_id.in_(tuple(COMPATIBILITY_SLOT_ROLES)))
        ).all()
        values = []
        for binding, slot in rows:
            if (
                not slot.enabled
                or slot.role != COMPATIBILITY_SLOT_ROLES[slot.slot_id]
                or binding.state in {"DISABLED", "DRAINING"}
            ):
                raise _invalid("required compatibility binding is disabled or has the wrong role")
            values.append(
                CompatibilityAdmissionBinding(
                    slot.slot_id,
                    binding.binding_id,
                    binding.current_assignment_revision_id,
                    binding.resource_version,
                )
            )
    if len(values) != 6 or {value.slot_id for value in values} != set(COMPATIBILITY_SLOT_ROLES):
        raise _invalid("all six current compatibility bindings must exist")
    return tuple(sorted(values, key=lambda value: value.slot_id))


def render_compatibility_policy(
    report: CodexCompatibilityReport,
    *,
    baseline_policy: ReviewedCapabilityPolicy,
    current_runtime: CodexCompatibilityRuntime,
    bindings: tuple[CompatibilityAdmissionBinding, ...],
    now: datetime,
) -> ReviewedCapabilityPolicy:
    """Keep compatible globals and admit exact passing pairs by current role binding.

    Keyed sets keep aggregation/storage O(cases + entries); canonical sorting is
    O(entries log entries), with at most 64 cases/32 emitted entries.
    Previous scoped claims are not a fresh report and are never silently carried forward.
    """

    if now.tzinfo is None or now.utcoffset() != timedelta(0):
        raise _invalid("policy check time must use UTC")
    if (
        report.runtime != current_runtime
        or not timedelta(0) <= now - report.completed_at <= MAX_REPORT_AGE
        or report.started_at > now
    ):
        raise _invalid("compatibility report is stale or its runtime differs")
    by_slot = {binding.slot_id: binding for binding in bindings}
    if len(bindings) != 6 or set(by_slot) != set(COMPATIBILITY_SLOT_ROLES):
        raise _invalid("compatibility admission requires exactly slots 01 through 06")
    if len({binding.binding_id for binding in bindings}) != 6:
        raise _invalid("compatibility admission requires distinct bindings")
    passed: dict[str, set[tuple[str, str]]] = {slot: set() for slot in COMPATIBILITY_SLOT_ROLES}
    for case in report.cases:
        binding = by_slot[case.slot_id]
        if (
            case.binding_id != binding.binding_id
            or case.assignment_revision_id != binding.assignment_revision_id
            or case.expected_resource_version > binding.resource_version
        ):
            raise _invalid("compatibility report binding pins are no longer current")
        if case.status == "PASS":
            passed[case.slot_id].add((case.model, str(case.reasoning_effort)))
    intersection = passed["01"] & passed["02"]
    # Authoring and review are admitted only as a tested pair. An exhausted
    # authoring account must not withhold independent image/support roles.
    if not intersection and not any(passed[slot] for slot in ("03", "04", "05", "06")):
        raise _invalid("no exact model/effort pair passed both required bindings")
    passed["01"] = intersection
    passed["02"] = intersection
    retain_baseline = (
        baseline_policy.expected_codex_cli_version == current_runtime.cli_version
        and (
            baseline_policy.version == 1 or baseline_policy.compatibility_runtime == current_runtime
        )
    )
    baseline = (
        tuple(item for item in baseline_policy.models if item.bindings is None)
        if retain_baseline
        else ()
    )
    global_pairs = {
        (item.model, str(effort)) for item in baseline for effort in item.reasoning_efforts
    }
    # Group only observed pair/slot memberships. Grouping just by model would
    # accidentally authorize another slot's untested reasoning effort.
    pair_slots: dict[tuple[str, str], set[str]] = {}
    for slot_id, pairs in passed.items():
        for pair in pairs - global_pairs:
            pair_slots.setdefault(pair, set()).add(slot_id)
    scoped: dict[tuple[str, tuple[str, ...]], set[str]] = {}
    for (model, effort), slots in pair_slots.items():
        scope_slots = tuple(sorted(slots, key=lambda slot: by_slot[slot].binding_id))
        scoped.setdefault((model, scope_slots), set()).add(effort)
    additions = tuple(
        ReviewedModelCapability.model_validate(
            {
                "model": model,
                "reasoning_efforts": sorted(efforts),
                "bindings": [
                    ReviewedCapabilityBindingV3.model_validate(
                        {
                            "binding_id": by_slot[slot_id].binding_id,
                            "assignment_revision_id": by_slot[slot_id].assignment_revision_id,
                            "slot_id": slot_id,
                            "role": COMPATIBILITY_SLOT_ROLES[slot_id],
                        }
                    )
                    for slot_id in scope_slots
                ],
            }
        )
        for (model, scope_slots), efforts in sorted(scoped.items())
    )
    if len(baseline) + len(additions) > 32:
        raise _invalid("passing compatibility scopes exceed the bounded policy entries")
    policy = ReviewedCapabilityPolicy(
        version=3,
        expected_codex_cli_version=current_runtime.cli_version,
        compatibility_runtime=current_runtime,
        models=(*baseline, *additions),
    )
    validate_control_contract("codex-reviewed-capability-policy-v3", policy.model_dump(mode="json"))
    return policy
