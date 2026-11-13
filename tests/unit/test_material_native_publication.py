"""Synthetic Artifact/source ports test publication identity, not native producer correctness."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from eom_catalog_contracts.material_learning_intake import (
    MaterialLearningSourceSelection,
    MaterialSourceUploadManifest,
)
from eom_catalog_service import material_native_publication as owner
from eom_catalog_service.artifacts import CatalogArtifact
from eom_catalog_service.material_native_publication import MaterialNativeArtifactPublicationService
from eom_catalog_service.material_native_resolution import (
    read_material_native_bundle,
    verify_material_native_bundle_files,
)
from eom_catalog_service.native_exam_workbook import read_native_exam_workbook
from eom_catalog_service.settings import CatalogSettings
from eom_hwpx_contracts.native_conversion_v2 import NativeHwpQualifiedConversionReceiptV2
from eom_hwpx_contracts.native_item_split import NativeItemSplitResult
from eom_identifiers import sha256_bytes
from sqlalchemy import create_engine

from tests.unit.test_material_learning_intake import ACTOR, source_receipt
from tests.unit.test_native_exam_intake import _parts, _zip


class MemoryArtifacts:
    """Synthetic owner with exact replay, primary identity and member metadata."""

    def __init__(self) -> None:
        self.records: dict[str, tuple[dict[str, Any], CatalogArtifact]] = {}
        self.calls: list[dict[str, Any]] = []
        self.payloads: dict[tuple[str, str, str], bytes] = {}

    def commit_file_set(self, **kwargs: Any) -> CatalogArtifact:
        self.calls.append(kwargs)
        key, request = kwargs["idempotency_key"], kwargs["request"]
        if key in self.records:
            old_request, artifact = self.records[key]
            if old_request != request:
                raise ValueError("SYNTHETIC_IDEMPOTENCY_CONFLICT")
            return artifact
        entries = []
        for name, path in sorted(kwargs["files"].items()):
            payload = path.read_bytes()
            assert sha256_bytes(payload) == kwargs["expected_file_sha256"][name]
            entries.append(
                {
                    "file_name": name,
                    "sha256": sha256_bytes(payload),
                    "bytes": len(payload),
                    **kwargs["file_metadata"][name],
                }
            )
        primary = next(entry for entry in entries if entry["file_name"] == kwargs["primary_file"])
        number = len(self.records) + 1
        artifact = CatalogArtifact(
            job_id=f"job_{number:032x}",
            artifact_id=f"artifact_{number:032x}",
            revision_id=f"rev_{number:032x}",
            content_hash=primary["sha256"],
            manifest_hash="sha256:" + "0" * 64,
            content_bytes=primary["bytes"],
            nas_path="memory-only-test",
            manifest={"primary_file": kwargs["primary_file"], "files": entries},
        )
        self.records[key] = (request, artifact)
        for name, path in kwargs["files"].items():
            self.payloads[artifact.artifact_id, artifact.revision_id, name] = path.read_bytes()
        return artifact

    def read_member(self, **kwargs: Any) -> bytes:
        payload = self.payloads[kwargs["artifact_id"], kwargs["revision_id"], kwargs["member_path"]]
        assert sha256_bytes(payload) == kwargs["sha256"]
        assert len(payload) <= kwargs["max_bytes"]
        return payload

    def open_verified_member(self, **kwargs: Any) -> Any:
        payload = self.read_member(**kwargs)
        return SimpleNamespace(stream=BytesIO(payload), content_length=len(payload))


class MemorySources:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def resolve(self, receipt: Any, *, operator_id: str) -> MaterialSourceUploadManifest:
        assert receipt.uploaded_by == operator_id
        self.calls.append(operator_id)
        return MaterialSourceUploadManifest(
            uploaded_by=operator_id,
            original_filename=receipt.original_filename,
            source_format=receipt.source_format,
            rights_confirmed=True,
            original=receipt.original.model_dump(exclude={"artifact_id", "artifact_revision_id"}),
        )


def _qualified(original: str, native: str) -> NativeHwpQualifiedConversionReceiptV2:
    return NativeHwpQualifiedConversionReceiptV2.model_validate(
        dict(
            snapshot=dict(
                source_commit="62d95b980a4e3a6766877dd3fb6f7f45f4afcf3d",
                bundle_sha256="sha256:" + "f" * 64,
            ),
            evidence=dict(
                schema_version="native-hwp-conversion-evidence/2.0",
                source_sha256=original,
                candidate_sha256="sha256:" + "c" * 64,
                section_count=1,
                masterpage_count=0,
                memo_count=0,
                paragraph_sha256=["sha256:" + "1" * 64],
                table_sha256=[],
                equation_sha256=[],
                binary_sha256=[],
                shape_counts={
                    key: 0
                    for key in (
                        "pic",
                        "container",
                        "rect",
                        "ellipse",
                        "arc",
                        "polygon",
                        "curve",
                        "line",
                        "connectLine",
                    )
                },
                auxiliary_master_pages=[],
                auxiliary_exceptions=[],
                whole_paper_layout="NOT_VERIFIED",
                warnings=[],
            ),
            normalization=dict(
                candidate_sha256="sha256:" + "c" * 64,
                output_sha256=native,
                empty_style_attribute_count=0,
                expanded_size_attribute_count=0,
                rebuilt_intent_box_count=0,
            ),
        )
    )


def _case(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, hwp: bool = False
) -> tuple[
    MaterialNativeArtifactPublicationService,
    MemoryArtifacts,
    MemorySources,
    list[str],
    dict[str, Any],
]:
    artifacts, sources = MemoryArtifacts(), MemorySources()
    settings = CatalogSettings(staging_root=tmp_path)
    service = MaterialNativeArtifactPublicationService(
        create_engine("sqlite://"), settings, artifacts=artifacts, sources=sources
    )
    auth: list[str] = []
    monkeypatch.setattr(
        owner, "authorize_material_learning", lambda session, actor: auth.append(actor)
    )
    selections = []
    results: dict[str, tuple[NativeItemSplitResult, ...]] = {}
    dirs = {}
    proofs = {}
    build_receipt: Callable[[str], dict[str, Any]] = source_receipt
    for role, letter in (("MAIN", "a"), ("SOLUTIONS", "e")):
        receipt = build_receipt("HWP" if hwp else "HWPX")
        receipt["original"]["sha256"] = "sha256:" + letter * 64
        receipt["original"]["artifact_id"] = "artifact_" + letter * 32
        receipt["original"]["artifact_revision_id"] = "rev_" + letter * 32
        receipt["manifest"]["artifact_id"] = "artifact_" + letter * 32
        receipt["manifest"]["artifact_revision_id"] = "rev_" + letter * 32
        selections.append(
            MaterialLearningSourceSelection.model_validate(
                dict(source_role=role, source_upload=receipt)
            )
        )
        native_hash = (
            "sha256:" + ("b" if role == "MAIN" else "d") * 64
            if hwp
            else receipt["original"]["sha256"]
        )
        directory = tmp_path / role
        directory.mkdir()
        dirs[role] = directory
        items = []
        for number in (1, 2):
            payload = _zip(
                {
                    "mimetype": b"application/hwp+zip",
                    "Contents/section0.xml": f"<native>{role}:{number}</native>".encode(),
                }
            )
            path = directory / f"{number:03d}.hwpx"
            path.write_bytes(payload)
            items.append(
                NativeItemSplitResult.model_validate(
                    dict(
                        source_sha256=native_hash,
                        plan_sha256="sha256:" + letter * 64,
                        source_role=role,
                        item_number=number,
                        ranges=[
                            dict(
                                section_member="Contents/section0.xml",
                                start_paragraph=number - 1,
                                end_paragraph=number,
                                subtree_sha256="sha256:" + "2" * 64,
                            )
                        ],
                        paragraph_sha256=["sha256:" + "3" * 64],
                        context_sha256=[],
                        binary_sha256=[],
                        counts=dict(paragraphs=1, tables=0, equations=0, pictures=0),
                        output_sha256=sha256_bytes(payload),
                        output_size_bytes=len(payload),
                    )
                )
            )
        results[role] = tuple(items)
        if hwp:
            proofs[role] = _qualified(receipt["original"]["sha256"], native_hash)
    workbook_path = tmp_path / "source.xlsx"
    raw = _zip(_parts(ids=False))
    workbook_path.write_bytes(raw)
    args = dict(
        operator_id=ACTOR,
        source_namespace="synthetic-native",
        exam_key="exam-01",
        sources=tuple(selections),
        question_directory=dirs["MAIN"],
        question_results=results["MAIN"],
        solution_directory=dirs["SOLUTIONS"],
        solution_results=results["SOLUTIONS"],
        workbook_path=workbook_path,
        parsed_workbook=read_native_exam_workbook(raw),
        conversion_receipts=proofs,
    )
    return service, artifacts, sources, auth, args


@pytest.mark.parametrize("hwp", [False, True])
def test_native_documents_are_primary_and_qualified_proof_is_shared_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, hwp: bool
) -> None:
    service, artifacts, sources, auth, args = _case(tmp_path, monkeypatch, hwp=hwp)
    result = service.publish_exam(**args)
    assert len(result.bundle.items) == 2
    assert [item.source_metadata.external_number for item in result.bundle.items] == [None, None]
    assert result.bundle.items[0].source_metadata.original_unit == " 3.시스템과 상호작용"
    assert result.bundle.items[0].source_metadata.original_classification == "통합과학 - 창작"
    assert len(sources.calls) == 4
    assert auth and set(auth) == {ACTOR}
    documents = [
        call for call in artifacts.calls if call["artifact_type"] == "material-native-item-document"
    ]
    assert len(documents) == 4
    for call in documents:
        assert call["primary_file"].endswith(".hwpx")
        request, metadata = call["request"], call["file_metadata"]
        assert request["producer_profile"] == "DIRECT_NATIVE_PARAGRAPHS_V1"
        assert request["native_source_sha256"] and request["split_plan_sha256"]
        assert metadata["native/split-result.json"]["media_type"] == "application/json"
        assert (
            request["conversion_proof"] is not None if hwp else request["conversion_proof"] is None
        )
        assert call["result"]["source_role"] == request["source_role"]
    proofs = [
        call
        for call in artifacts.calls
        if call["artifact_type"] == "material-native-qualified-conversion"
    ]
    assert len(proofs) == (2 if hwp else 0)
    reader: Any = (
        artifacts  # Existing resolver's concrete annotation; immutable transport is synthetic.
    )
    assert (
        read_material_native_bundle(
            reader,
            result.pointer,
            sources=args["sources"],
            operator_id=ACTOR,
            authorize=lambda: None,
        )
        == result.bundle
    )
    verify_material_native_bundle_files(reader, result.bundle, authorize=lambda: None)
    count = len(artifacts.records)
    replay = service.publish_exam(**args)
    assert replay == result and len(artifacts.records) == count


def test_later_excel_ids_change_metadata_only_not_native_artifacts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service, artifacts, _, _, args = _case(tmp_path, monkeypatch, hwp=True)
    before = service.publish_exam(**args)
    count = len(artifacts.records)
    raw = _zip(_parts(ids=True))
    args["workbook_path"].write_bytes(raw)
    args["parsed_workbook"] = read_native_exam_workbook(raw)
    after = service.publish_exam(**args)
    assert before.pointer != after.pointer
    assert [item.source_metadata.external_number for item in after.bundle.items] == [
        "12341",
        "12342",
    ]
    assert [item.question for item in before.bundle.items] == [
        item.question for item in after.bundle.items
    ]
    assert [item.solution for item in before.bundle.items] == [
        item.solution for item in after.bundle.items
    ]
    assert len(artifacts.records) == count + 2  # shared workbook and bundle only


@pytest.mark.parametrize(
    "error", ["coverage", "role", "file_hash", "workbook_hash", "missing_proof", "wrong_proof"]
)
def test_preflight_rejects_conflicts_before_any_artifact_commit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, error: str
) -> None:
    service, artifacts, _, _, args = _case(tmp_path, monkeypatch, hwp=True)
    if error == "coverage":
        args["question_results"] = args["question_results"][:1]
    elif error == "role":
        args["question_results"] = tuple(
            r.model_copy(update={"source_role": "SOLUTIONS"}) for r in args["question_results"]
        )
    elif error == "file_hash":
        (args["question_directory"] / "002.hwpx").write_bytes(b"changed file")
    elif error == "workbook_hash":
        args["workbook_path"].write_bytes(_zip(_parts(ids=True)))
    elif error == "missing_proof":
        args["conversion_receipts"] = {}
    else:
        args["conversion_receipts"]["MAIN"] = _qualified("sha256:" + "a" * 64, "sha256:" + "9" * 64)
    with pytest.raises(ValueError):
        service.publish_exam(**args)
    assert not artifacts.calls


def test_permission_denial_never_substitutes_another_actor_or_publishes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service, artifacts, sources, _, args = _case(tmp_path, monkeypatch)

    def deny(session: Any, actor: str) -> None:
        raise ValueError("REVOKED_ACTUAL_OPERATOR")

    monkeypatch.setattr(owner, "authorize_material_learning", deny)
    with pytest.raises(ValueError, match="REVOKED_ACTUAL_OPERATOR"):
        service.publish_exam(**args)
    assert not artifacts.calls and not sources.calls


@pytest.mark.parametrize("kind", ["file", "directory", "hardlink"])
def test_local_input_links_are_never_dereferenced_for_publication(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, kind: str
) -> None:
    import os

    service, artifacts, _, _, args = _case(tmp_path, monkeypatch)
    if kind == "directory":
        linked = tmp_path / "linked"
        linked.symlink_to(args["question_directory"], target_is_directory=True)
        args["question_directory"] = linked
    elif kind == "file":
        link = tmp_path / "linked.xlsx"
        link.symlink_to(args["workbook_path"])
        args["workbook_path"] = link
    else:
        os.link(args["workbook_path"], tmp_path / "hardlinked.xlsx")
    with pytest.raises((ValueError, OSError)):
        service.publish_exam(**args)
    assert not artifacts.calls


def test_artifact_owner_primary_identity_is_independently_checked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service, artifacts, _, _, args = _case(tmp_path, monkeypatch)
    real = artifacts.commit_file_set
    monkeypatch.setattr(
        artifacts,
        "commit_file_set",
        lambda **kw: replace(real(**kw), content_hash="sha256:" + "0" * 64),
    )
    with pytest.raises(ValueError, match="COMMITTED_PRIMARY_MISMATCH"):
        service.publish_exam(**args)
    assert len(artifacts.calls) == 1


def test_interrupted_publication_reuses_original_keys_without_hiding_owner_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service, artifacts, _, _, args = _case(tmp_path, monkeypatch)
    real = artifacts.commit_file_set
    failed: list[str] = []
    fail_once = True

    def interrupt(**kwargs: Any) -> CatalogArtifact:
        nonlocal fail_once
        if len(artifacts.records) == 1 and fail_once:
            fail_once = False
            failed.append(kwargs["idempotency_key"])
            raise ValueError("SYNTHETIC_EXISTING_ARTIFACT_OWNER_INTERRUPTED")
        return real(**kwargs)

    monkeypatch.setattr(artifacts, "commit_file_set", interrupt)
    with pytest.raises(ValueError, match="OWNER_INTERRUPTED"):
        service.publish_exam(**args)
    assert len(artifacts.records) == 1
    first_key, first_artifact = next(iter(artifacts.records.items()))
    outcome = service.publish_exam(**args)
    assert first_key in artifacts.records and artifacts.records[first_key] == first_artifact
    assert failed[0] in artifacts.records
    assert len(outcome.bundle.items) == 2 and len(artifacts.records) == 6
