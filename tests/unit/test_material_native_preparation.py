"""Actual minimal XLSX, synthetic protected tool and declared canonical owner ports."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest
from eom_catalog_contracts.material_learning_intake import (
    MaterialLearningAcceptance,
    MaterialLearningSourceSelection,
)
from eom_catalog_contracts.material_native_intake import CreateNativeMaterialLearningCommand
from eom_catalog_contracts.material_native_prepare import PrepareNativeMaterialExamCommand
from eom_catalog_service import material_native_preparation as owner
from eom_catalog_service.material_learning_store import material_submission_identity
from eom_catalog_service.material_native_preparation import MaterialNativePreparationService
from eom_catalog_service.material_native_publication import (
    MaterialNativeArtifactPublicationService,
    MaterialNativePublication,
)
from eom_catalog_service.settings import CatalogSettings
from eom_hwpx_contracts.native_conversion_v2 import NativeHwpConverterSnapshotV2
from eom_hwpx_contracts.native_exam_preparation import (
    NativeExamFilePreparationRequest,
    NativeExamFilePreparationResult,
    native_exam_preparation_sha256,
)
from eom_hwpx_contracts.native_item_split import NativeItemSplitResult, native_split_contract_sha256
from eom_identifiers import canonical_json_bytes, content_sha256, sha256_bytes
from eom_orchestrator.native_exam_preparation import PreparedNativeExamFiles
from pydantic import ValidationError
from sqlalchemy import create_engine

from tests.unit.test_material_learning_intake import ACTOR, create_command, source_receipt
from tests.unit.test_material_native_publication import MemoryArtifacts, MemorySources, _qualified
from tests.unit.test_native_exam_intake import _parts, _zip


class SyntheticNativeTool:
    """Does not claim native preservation; tests the application/transport ownership boundary."""

    def __init__(self) -> None:
        self.calls: list[NativeExamFilePreparationRequest] = []
        self.configured_python: list[Path] = []

    def __call__(
        self,
        source_bytes: bytes,
        *,
        request: NativeExamFilePreparationRequest,
        workspace: Path,
        python: Path,
    ) -> PreparedNativeExamFiles:
        self.calls.append(request)
        self.configured_python.append(python)
        assert sha256_bytes(source_bytes) == request.expected_source_sha256
        native = (
            request.expected_source_sha256
            if request.source_format == "HWPX"
            else (sha256_bytes(b"synthetic-converted:" + source_bytes))
        )
        ranges = [
            {
                "section_member": "Contents/section0.xml",
                "start_paragraph": number - 1,
                "end_paragraph": number,
                "subtree_sha256": "sha256:" + "2" * 64,
            }
            for number in request.expected_numbers
        ]
        plan = dict(
            schema_version="native-item-split-plan/1.0",
            profile="DIRECT_NATIVE_PARAGRAPHS_V1",
            source_sha256=native,
            source_role=request.source_role,
            items=[
                {"item_number": n, "ranges": [r]}
                for n, r in zip(request.expected_numbers, ranges, strict=True)
            ],
        )
        plan_sha = native_split_contract_sha256(plan)
        workspace.mkdir(mode=0o700)
        payloads: dict[str, bytes] = {}
        splits = []
        items = []
        for number, selected in zip(request.expected_numbers, ranges, strict=True):
            name = f"items/{number:03d}.hwpx"
            payload = _zip(
                {
                    "mimetype": b"application/hwp+zip",
                    "Contents/section0.xml": (
                        f"<native>{request.source_role}:{number}</native>".encode()
                    ),
                }
            )
            payloads[name] = payload
            split = NativeItemSplitResult.model_validate(
                dict(
                    source_sha256=native,
                    plan_sha256=plan_sha,
                    source_role=request.source_role,
                    item_number=number,
                    ranges=[selected],
                    paragraph_sha256=["sha256:" + "3" * 64],
                    context_sha256=[],
                    binary_sha256=[],
                    counts=dict(paragraphs=1, tables=0, equations=0, pictures=0),
                    output_sha256=sha256_bytes(payload),
                    output_size_bytes=len(payload),
                )
            )
            split_name = f"splits/{number:03d}.json"
            split_bytes = canonical_json_bytes(split.model_dump(mode="json"))
            payloads[split_name] = split_bytes
            splits.append(split)
            items.append(
                dict(
                    item_number=number,
                    document=dict(
                        member_path=name,
                        sha256=sha256_bytes(payload),
                        bytes=len(payload),
                        media_type="application/vnd.hancom.hwpx",
                    ),
                    split_evidence=dict(
                        member_path=split_name,
                        sha256=sha256_bytes(split_bytes),
                        bytes=len(split_bytes),
                        media_type="application/json",
                    ),
                )
            )
        proof = None
        conversion = None
        if request.source_format == "HWP":
            proof = _qualified(request.expected_source_sha256, native)
            assert proof.snapshot == request.converter
            raw = canonical_json_bytes(proof.model_dump(mode="json"))
            payloads["conversion.json"] = raw
            conversion = dict(
                member_path="conversion.json",
                sha256=sha256_bytes(raw),
                bytes=len(raw),
                media_type="application/json",
            )
        result = NativeExamFilePreparationResult.model_validate(
            dict(
                request_sha256=native_exam_preparation_sha256(request.model_dump(mode="json")),
                original_source_sha256=request.expected_source_sha256,
                native_source_sha256=native,
                source_format=request.source_format,
                source_role=request.source_role,
                expected_numbers=request.expected_numbers,
                plan_sha256=plan_sha,
                items=items,
                conversion=conversion,
                materialized_bytes=sum(len(raw) for raw in payloads.values()),
            )
        )
        payloads["result.json"] = canonical_json_bytes(result.model_dump(mode="json"))
        for name, raw in payloads.items():
            path = workspace / name
            path.parent.mkdir(mode=0o700, exist_ok=True)
            path.write_bytes(raw)
            path.chmod(0o600)
        return PreparedNativeExamFiles(
            result, workspace, tuple(sorted(payloads)), tuple(splits), proof
        )


class RecordingPublication:
    def __init__(self, delegate: MaterialNativeArtifactPublicationService) -> None:
        self.delegate = delegate
        self.calls: list[dict[str, Any]] = []
        self.fail_before_publication = False

    def publish_exam(self, **kwargs: Any) -> MaterialNativePublication:
        self.calls.append(kwargs)
        if self.fail_before_publication:
            raise ValueError("SYNTHETIC_PUBLICATION_INTERRUPTED")
        return self.delegate.publish_exam(**kwargs)


class RecordingIntake:
    def __init__(self) -> None:
        self.calls: list[CreateNativeMaterialLearningCommand] = []
        self.accepted: dict[tuple[str, str], MaterialLearningAcceptance] = {}
        self.fail_once = False

    def create(self, command: CreateNativeMaterialLearningCommand) -> MaterialLearningAcceptance:
        self.calls.append(command)
        if self.fail_once:
            self.fail_once = False
            raise ValueError("SYNTHETIC_INTAKE_INTERRUPTED_AFTER_PUBLICATION")
        key = (command.actor_id, command.idempotency_key)
        request_sha = content_sha256(command.model_dump(mode="json"))
        if key in self.accepted:
            original = self.accepted[key]
            if original.request_sha256 != request_sha:
                raise ValueError("SYNTHETIC_INTAKE_IDEMPOTENCY_CONFLICT")
            return original.model_copy(update={"replayed": True})
        identity = material_submission_identity(*key)
        value = MaterialLearningAcceptance(
            material_id=identity.material_id,
            material_revision_id=identity.material_revision_id,
            run_id=identity.first_run_id,
            request_sha256=request_sha,
            replayed=False,
        )
        self.accepted[key] = value
        return value


def _case(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, hwp: bool = False) -> tuple[Any, ...]:
    settings = CatalogSettings(staging_root=tmp_path)
    engine = create_engine("sqlite://")
    artifacts, sources = MemoryArtifacts(), MemorySources()
    publisher = MaterialNativeArtifactPublicationService(
        engine, settings, artifacts=artifacts, sources=sources
    )
    publication = RecordingPublication(publisher)
    tool, intake = SyntheticNativeTool(), RecordingIntake()
    authorization: list[str] = []
    monkeypatch.setattr(
        owner, "authorize_material_learning", lambda s, actor: authorization.append(actor)
    )
    monkeypatch.setattr(
        "eom_catalog_service.material_native_publication.authorize_material_learning",
        lambda s, actor: authorization.append(actor),
    )
    snapshot = NativeHwpConverterSnapshotV2(
        source_commit="62d95b980a4e3a6766877dd3fb6f7f45f4afcf3d", bundle_sha256="sha256:" + "f" * 64
    )
    service = MaterialNativePreparationService(
        engine,
        settings,
        python=Path("/opt/eom/test-protected-native/runtime/bin/python"),
        converter=snapshot,
        artifacts=artifacts,
        sources=sources,
        publication=publication,
        intake=intake,
        tool=tool,
    )
    selections = []
    for role, letter in (("MAIN", "a"), ("SOLUTIONS", "e")):
        raw = (
            (bytes.fromhex("d0cf11e0a1b11ae1") + role.encode())
            if hwp
            else _zip({"mimetype": b"application/hwp+zip", "Contents/section0.xml": role.encode()})
        )
        receipt = source_receipt("HWP" if hwp else "HWPX")
        for key in ("original", "manifest"):
            receipt[key]["artifact_id"] = "artifact_" + letter * 32
            receipt[key]["artifact_revision_id"] = "rev_" + letter * 32
        receipt["original"].update(sha256=sha256_bytes(raw), bytes=len(raw))
        selection = MaterialLearningSourceSelection.model_validate(
            dict(source_role=role, source_upload=receipt)
        )
        selections.append(selection)
        pointer = selection.source_upload.original
        artifacts.payloads[
            pointer.artifact_id, pointer.artifact_revision_id, pointer.member_path
        ] = raw
    raw_book = _zip(_parts(ids=False))
    path = tmp_path / "private-upload.bin"
    path.write_bytes(raw_book)
    path.chmod(0o600)
    command = PrepareNativeMaterialExamCommand.model_validate(
        dict(
            actor_id=ACTOR,
            idempotency_key="native-exam-prepare-synthetic-request",
            upload=create_command()["upload"],
            sources=[s.model_dump(mode="json") for s in selections],
            source_namespace="synthetic-preparation",
            exam_key="exam-01",
            workbook_filename="../../not-a-path.xlsx",
            workbook_sha256=sha256_bytes(raw_book),
            workbook_bytes=len(raw_book),
        )
    )
    return service, path, command, artifacts, sources, publication, intake, tool, authorization


@pytest.mark.parametrize("hwp", [False, True])
def test_prepare_calls_two_fixed_tools_then_existing_publication_and_async_intake(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, hwp: bool
) -> None:
    service, path, command, artifacts, sources, publication, intake, tool, auth = _case(
        tmp_path, monkeypatch, hwp=hwp
    )
    accepted = service.prepare_and_create(path, command)
    assert not accepted.replayed
    assert [r.source_role for r in tool.calls] == ["MAIN", "SOLUTIONS"]
    assert all(r.expected_numbers == (1, 2) for r in tool.calls)
    assert all((r.converter is not None) == hwp for r in tool.calls)
    assert set(tool.configured_python) == {service.python}
    assert len(publication.calls) == len(intake.calls) == 1
    assert publication.calls[0]["workbook_path"].name == "metadata.xlsx"
    assert not publication.calls[0]["workbook_path"].exists()
    assert not list(tmp_path.glob("material-native-prepare.*"))
    assert intake.calls[0].idempotency_key == command.idempotency_key
    assert intake.calls[0].actor_id == command.actor_id
    assert auth and set(auth) == {ACTOR}
    assert sources.calls and artifacts.records
    count = len(artifacts.records)
    replay = service.prepare_and_create(path, command)
    assert replay.replayed and replay.run_id == accepted.run_id
    assert len(artifacts.records) == count and len(intake.accepted) == 1


def test_same_command_after_publication_interruption_reuses_canonical_artifacts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service, path, command, artifacts, _, publication, intake, tool, _ = _case(
        tmp_path, monkeypatch
    )
    intake.fail_once = True
    with pytest.raises(ValueError, match="INTAKE_INTERRUPTED"):
        service.prepare_and_create(path, command)
    count = len(artifacts.records)
    original_pointer = intake.calls[0].native_bundle
    result = service.prepare_and_create(path, command)
    assert not result.replayed and len(intake.accepted) == 1
    assert len(artifacts.records) == count
    assert intake.calls[1].native_bundle == original_pointer
    assert len(publication.calls) == 2 and len(tool.calls) == 4


@pytest.mark.parametrize(
    "case", ["mode", "symlink", "hardlink", "hash", "size", "owner", "not_xlsx"]
)
def test_bad_workbook_handoff_never_reaches_tool_or_publication(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, case: str
) -> None:
    service, path, command, artifacts, _, publication, intake, tool, _ = _case(
        tmp_path, monkeypatch
    )
    if case == "mode":
        path.chmod(0o644)
    elif case == "symlink":
        link = tmp_path / "linked.xlsx"
        link.symlink_to(path)
        path = link
    elif case == "hardlink":
        os.link(path, tmp_path / "other.xlsx")
    elif case == "hash":
        command = command.model_copy(update={"workbook_sha256": "sha256:" + "0" * 64})
    elif case == "size":
        command = command.model_copy(update={"workbook_bytes": command.workbook_bytes + 1})
    elif case == "owner":
        monkeypatch.setattr(owner.os, "geteuid", lambda: path.stat().st_uid + 1)
    else:
        raw = b"not-a-workbook"
        path.write_bytes(raw)
        command = command.model_copy(
            update={"workbook_sha256": sha256_bytes(raw), "workbook_bytes": len(raw)}
        )
    with pytest.raises(ValueError):
        service.prepare_and_create(path, command)
    assert not tool.calls and not publication.calls and not intake.calls and not artifacts.records


def test_wrong_actor_and_revoked_source_never_trigger_native_tools(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service, path, command, _, sources, publication, _, tool, _ = _case(tmp_path, monkeypatch)
    wrong = command.model_copy(update={"actor_id": "operator_" + "f" * 32})
    with pytest.raises(ValidationError):
        service.prepare_and_create(path, wrong)

    def denied(*args: Any, **kwargs: Any) -> Any:
        raise ValueError("SOURCE_OWNER_REVOKED")

    def must_not_parse(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("metadata decoded before source authorization")

    monkeypatch.setattr(sources, "resolve", denied)
    monkeypatch.setattr(owner, "read_native_exam_workbook", must_not_parse)
    with pytest.raises(ValueError, match="SOURCE_OWNER_REVOKED"):
        service.prepare_and_create(path, command)
    assert not tool.calls and not publication.calls


def test_native_source_bytes_are_checked_before_tool_submission(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service, path, command, artifacts, _, publication, _, tool, _ = _case(tmp_path, monkeypatch)
    member = command.sources[0].source_upload.original
    artifacts.payloads[member.artifact_id, member.artifact_revision_id, member.member_path] += (
        b"changed"
    )
    with pytest.raises((ValueError, AssertionError)):
        service.prepare_and_create(path, command)
    assert not tool.calls and not publication.calls


def test_tool_cannot_switch_declared_source_role_before_publication(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from dataclasses import replace

    service, path, command, _, _, publication, _, tool, _ = _case(tmp_path, monkeypatch)

    def switched(*args: Any, **kwargs: Any) -> PreparedNativeExamFiles:
        prepared = tool(*args, **kwargs)
        return replace(
            prepared, result=prepared.result.model_copy(update={"source_role": "SOLUTIONS"})
        )

    service.tool = switched
    with pytest.raises(ValueError, match="TOOL_RESULT_MISMATCH"):
        service.prepare_and_create(path, command)
    assert not publication.calls


def test_upload_authorization_is_public_and_does_not_open_workbook_or_call_tools(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service, path, command, _, sources, publication, intake, tool, _ = _case(tmp_path, monkeypatch)
    path.unlink()
    service.authorize_upload(command)
    assert sources.calls == [ACTOR, ACTOR]
    assert not publication.calls and not intake.calls and not tool.calls


def test_upload_authorization_rejects_revoked_actual_operator_before_source_resolution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service, _, command, _, sources, publication, _, tool, _ = _case(tmp_path, monkeypatch)

    def deny(*args: Any, **kwargs: Any) -> None:
        raise ValueError("ACTUAL_OPERATOR_REVOKED")

    monkeypatch.setattr(owner, "authorize_material_learning", deny)
    with pytest.raises(ValueError, match="ACTUAL_OPERATOR_REVOKED"):
        service.authorize_upload(command)
    assert not sources.calls and not publication.calls and not tool.calls
