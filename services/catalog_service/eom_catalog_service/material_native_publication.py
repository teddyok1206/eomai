"""Publish qualified local native exam outputs through the existing Artifact owner.

This application adapter does not convert, split, infer, register or execute models.
The protected native producer separately proves raw-HWP preservation. Publication
binds its typed receipt to actual local bytes, the original uploader and exact XLSX.
"""

from __future__ import annotations

import hashlib
import os
import re
import stat
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from eom_catalog_contracts.material_learning import MaterialArtifactMember
from eom_catalog_contracts.material_learning_intake import (
    MaterialLearningSourceSelection,
    MaterialSourceUploadManifest,
    MaterialSourceUploadReceipt,
)
from eom_catalog_contracts.material_native_files import (
    NATIVE_ITEM_DOCUMENT_REF,
    NATIVE_ITEM_SPLIT_EVIDENCE_REF,
    NATIVE_WORKBOOK_MANIFEST_REF,
    MaterialNativeFileBinding,
    MaterialNativeSourceMetadata,
)
from eom_catalog_contracts.material_native_intake import (
    MATERIAL_NATIVE_BUNDLE_REF,
    MaterialNativeExamBundle,
    MaterialNativeExamItem,
    MaterialNativeWorkbookSource,
    require_native_exam_bundle_sources,
    require_native_exam_bundle_workbook,
)
from eom_catalog_contracts.native_exam_intake import NativeExamWorkbookDocument
from eom_hwpx_contracts.native_conversion_v2 import (
    NATIVE_HWP_QUALIFIED_CONVERSION_REF,
    NativeHwpQualifiedConversionReceiptV2,
)
from eom_hwpx_contracts.native_item_split import NativeItemSplitResult, SourceRole
from eom_identifiers import canonical_json_bytes, content_sha256, sha256_bytes
from eom_orchestrator.database import build_session_factory
from sqlalchemy import Engine

from eom_catalog_service.artifacts import CatalogArtifact, CatalogArtifactService
from eom_catalog_service.material_learning_source import (
    MaterialLearningSourceService,
    authorize_material_learning,
)
from eom_catalog_service.native_exam_workbook import read_native_exam_workbook
from eom_catalog_service.settings import CatalogSettings

_JSON_MAX = 4 * 1024 * 1024
_WORKBOOK_MAX = 8 * 1024 * 1024
_DOCUMENT_MAX = 256 * 1024 * 1024
_EXAM_MAX = 512 * 1024 * 1024
_WORKBOOK_MEDIA = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


class NativePublicationArtifactPort(Protocol):
    """Existing owner interface; tests substitute transport, not preservation authority."""

    def commit_file_set(
        self,
        *,
        files: dict[str, Path],
        primary_file: str,
        artifact_type: str,
        idempotency_key: str,
        request: dict[str, Any],
        result: dict[str, Any],
        file_metadata: dict[str, dict[str, str]],
        expected_file_sha256: dict[str, str],
    ) -> CatalogArtifact: ...


class NativePublicationSourcePort(Protocol):
    def resolve(
        self, receipt: MaterialSourceUploadReceipt, *, operator_id: str
    ) -> MaterialSourceUploadManifest: ...


@dataclass(frozen=True, slots=True)
class MaterialNativePublication:
    bundle: MaterialNativeExamBundle
    pointer: MaterialArtifactMember


def _epoch(value: os.stat_result) -> tuple[int, ...]:
    return (
        value.st_dev,
        value.st_ino,
        value.st_mode,
        value.st_nlink,
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
    )


def _regular_file(
    path: Path,
    *,
    maximum: int,
    expected_sha256: str | None = None,
    expected_bytes: int | None = None,
    materialize: bool = False,
) -> tuple[str, int, bytes]:
    """Descriptor identity checks plus Artifact owner's expected-hash check at commit."""
    absolute = path.absolute()
    for parent in reversed(absolute.parents):
        if not stat.S_ISDIR(parent.lstat().st_mode):
            raise ValueError("MATERIAL_NATIVE_LOCAL_PATH_INVALID")
    fd = os.open(absolute, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
    with os.fdopen(fd, "rb") as stream:
        before = os.fstat(stream.fileno())
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_nlink != 1
            or not 1 <= before.st_size <= maximum
            or (expected_bytes is not None and before.st_size != expected_bytes)
        ):
            raise ValueError("MATERIAL_NATIVE_LOCAL_FILE_INVALID")
        digest = hashlib.sha256()
        chunks: list[bytes] = []
        size = 0
        prefix = b""
        while chunk := stream.read(1024 * 1024):
            size += len(chunk)
            if size > before.st_size:
                raise ValueError("MATERIAL_NATIVE_LOCAL_FILE_CHANGED")
            digest.update(chunk)
            if not prefix:
                prefix = chunk[:4]
            if materialize:
                chunks.append(chunk)
        sha = "sha256:" + digest.hexdigest()
        if (
            _epoch(before) != _epoch(os.fstat(stream.fileno()))
            or _epoch(before) != _epoch(absolute.lstat())
            or size != before.st_size
            or (expected_sha256 is not None and sha != expected_sha256)
        ):
            raise ValueError("MATERIAL_NATIVE_LOCAL_FILE_CHANGED")
    return sha, size, b"".join(chunks) if materialize else prefix


def _json(path: Path, value: object) -> tuple[str, int]:
    payload = canonical_json_bytes(value)
    if not 1 <= len(payload) <= _JSON_MAX:
        raise ValueError("MATERIAL_NATIVE_METADATA_SIZE_INVALID")
    with path.open("xb") as stream:
        stream.write(payload)
    return sha256_bytes(payload), len(payload)


class MaterialNativeArtifactPublicationService:
    def __init__(
        self,
        engine: Engine,
        settings: CatalogSettings,
        *,
        artifacts: NativePublicationArtifactPort | None = None,
        sources: NativePublicationSourcePort | None = None,
    ) -> None:
        self.sessions = build_session_factory(engine)
        self.settings = settings
        self.artifacts: NativePublicationArtifactPort = (
            artifacts if artifacts is not None else CatalogArtifactService(engine, settings)
        )
        self.sources: NativePublicationSourcePort = (
            sources if sources is not None else MaterialLearningSourceService(engine, settings)
        )

    def _authorize(self, operator_id: str) -> None:
        with self.sessions() as session:
            authorize_material_learning(session, operator_id)

    def _reauthorize_sources(
        self, operator_id: str, sources: tuple[MaterialLearningSourceSelection, ...]
    ) -> None:
        self._authorize(operator_id)
        for selection in sources:
            self.sources.resolve(selection.source_upload, operator_id=operator_id)
        self._authorize(operator_id)

    def _commit(
        self,
        *,
        operator_id: str,
        files: dict[str, Path],
        primary: str,
        metadata: dict[str, dict[str, str]],
        hashes: dict[str, str],
        sizes: dict[str, int],
        kind: str,
        key: str,
        request: dict[str, Any],
    ) -> dict[str, MaterialArtifactMember]:
        self._authorize(operator_id)
        artifact = self.artifacts.commit_file_set(
            files=files,
            primary_file=primary,
            artifact_type=kind,
            idempotency_key=key,
            request=request,
            result={
                "sha256": hashes[primary],
                **{
                    key: request[key]
                    for key in (
                        "original_source_sha256",
                        "native_source_sha256",
                        "split_plan_sha256",
                        "source_role",
                        "item_number",
                        "producer_profile",
                        "conversion_proof",
                    )
                    if key in request
                },
            },
            file_metadata=metadata,
            expected_file_sha256=hashes,
        )
        if (
            artifact.content_hash != hashes[primary]
            or artifact.content_bytes != sizes[primary]
            or artifact.manifest.get("primary_file") != primary
        ):
            raise ValueError("MATERIAL_NATIVE_COMMITTED_PRIMARY_MISMATCH")
        entries = artifact.manifest.get("files")
        if not isinstance(entries, list) or any(
            not isinstance(v, dict) or not isinstance(v.get("file_name"), str) for v in entries
        ):
            raise ValueError("MATERIAL_NATIVE_COMMITTED_MANIFEST_INVALID")
        by_name = {v.get("file_name"): v for v in entries}
        if len(by_name) != len(entries) or set(by_name) != set(files):
            raise ValueError("MATERIAL_NATIVE_COMMITTED_MANIFEST_INVALID")
        pointers = {}
        for name in files:
            actual = by_name[name]
            if any(
                actual.get(k) != v
                for k, v in {**metadata[name], "sha256": hashes[name], "bytes": sizes[name]}.items()
            ):
                raise ValueError("MATERIAL_NATIVE_COMMITTED_MEMBER_MISMATCH")
            pointers[name] = MaterialArtifactMember(
                artifact_id=artifact.artifact_id,
                artifact_revision_id=artifact.revision_id,
                member_path=name,
                schema_ref=metadata[name]["schema_ref"],
                media_type=metadata[name]["media_type"],
                sha256=hashes[name],
                bytes=sizes[name],
            )
        self._authorize(operator_id)
        return pointers

    def publish_exam(
        self,
        *,
        operator_id: str,
        source_namespace: str,
        exam_key: str,
        sources: tuple[MaterialLearningSourceSelection, ...],
        question_directory: Path,
        question_results: tuple[NativeItemSplitResult, ...],
        solution_directory: Path,
        solution_results: tuple[NativeItemSplitResult, ...],
        workbook_path: Path,
        parsed_workbook: NativeExamWorkbookDocument,
        conversion_receipts: Mapping[SourceRole, NativeHwpQualifiedConversionReceiptV2]
        | None = None,
    ) -> MaterialNativePublication:
        """Trusted local-preparation entry point, never a public arbitrary-path API."""
        if (
            re.fullmatch(r"operator_[0-9a-f]{32}", operator_id) is None
            or re.fullmatch(r"[a-z0-9][a-z0-9._:-]{0,127}", source_namespace) is None
            or not 1 <= len(exam_key) <= 256
            or any(ord(c) < 32 or ord(c) == 127 for c in exam_key)
        ):
            raise ValueError("MATERIAL_NATIVE_PUBLICATION_INPUT_INVALID")
        sources = tuple(
            MaterialLearningSourceSelection.model_validate(s.model_dump(mode="json"))
            for s in sources
        )
        if (
            tuple(s.source_role for s in sources) != ("MAIN", "SOLUTIONS")
            or any(
                s.source_upload.uploaded_by != operator_id
                or s.source_upload.source_format not in {"HWP", "HWPX"}
                for s in sources
            )
            or sources[0].source_upload.original.sha256 == sources[1].source_upload.original.sha256
        ):
            raise ValueError("MATERIAL_NATIVE_PUBLICATION_SOURCE_PAIR_INVALID")
        self._reauthorize_sources(operator_id, sources)
        workbook = NativeExamWorkbookDocument.model_validate(
            parsed_workbook.model_dump(mode="json")
        )
        _, _, raw = _regular_file(
            workbook_path,
            maximum=_WORKBOOK_MAX,
            expected_sha256=workbook.sha256,
            expected_bytes=workbook.bytes,
            materialize=True,
        )
        if read_native_exam_workbook(raw) != workbook:
            raise ValueError("MATERIAL_NATIVE_WORKBOOK_OBSERVATION_MISMATCH")
        if len(canonical_json_bytes(workbook.model_dump(mode="json"))) > _JSON_MAX:
            raise ValueError("MATERIAL_NATIVE_METADATA_SIZE_INVALID")
        sheet = next(sheet for sheet in workbook.worksheets if sheet.rows)
        numbers = tuple(row.question_number for row in sheet.rows)
        result_sets: dict[SourceRole, tuple[NativeItemSplitResult, ...]] = {
            "MAIN": tuple(
                NativeItemSplitResult.model_validate(r.model_dump(mode="json"))
                for r in question_results
            ),
            "SOLUTIONS": tuple(
                NativeItemSplitResult.model_validate(r.model_dump(mode="json"))
                for r in solution_results
            ),
        }
        directories = {"MAIN": question_directory, "SOLUTIONS": solution_directory}
        proofs = dict(conversion_receipts or {})
        if set(proofs) - {"MAIN", "SOLUTIONS"}:
            raise ValueError("MATERIAL_NATIVE_CONVERSION_ROLE_INVALID")
        total = 0
        for selection in sources:
            role = selection.source_role
            results = result_sets[role]
            if (
                tuple(r.item_number for r in results) != numbers
                or any(r.source_role != role for r in results)
                or len({(r.source_sha256, r.plan_sha256, r.profile) for r in results}) != 1
            ):
                raise ValueError("MATERIAL_NATIVE_RESULT_COVERAGE_MISMATCH")
            original = selection.source_upload.original
            if selection.source_upload.source_format == "HWPX":
                if results[0].source_sha256 != original.sha256 or role in proofs:
                    raise ValueError("MATERIAL_NATIVE_IDENTITY_SOURCE_MISMATCH")
            else:
                if role not in proofs:
                    raise ValueError("MATERIAL_NATIVE_QUALIFIED_CONVERSION_REQUIRED")
                proof = NativeHwpQualifiedConversionReceiptV2.model_validate(
                    proofs[role].model_dump(mode="json")
                )
                if (
                    proof.evidence.source_sha256 != original.sha256
                    or proof.normalization.output_sha256 != results[0].source_sha256
                ):
                    raise ValueError("MATERIAL_NATIVE_CONVERSION_SOURCE_MISMATCH")
                if len(canonical_json_bytes(proof.model_dump(mode="json"))) > _JSON_MAX:
                    raise ValueError("MATERIAL_NATIVE_METADATA_SIZE_INVALID")
                proofs[role] = proof
            for result in results:
                if len(canonical_json_bytes(result.model_dump(mode="json"))) > _JSON_MAX:
                    raise ValueError("MATERIAL_NATIVE_METADATA_SIZE_INVALID")
                _, size, prefix = _regular_file(
                    directories[role] / f"{result.item_number:03d}.hwpx",
                    maximum=_DOCUMENT_MAX,
                    expected_sha256=result.output_sha256,
                    expected_bytes=result.output_size_bytes,
                )
                if prefix != b"PK\x03\x04":
                    raise ValueError("MATERIAL_NATIVE_DOCUMENT_FORMAT_INVALID")
                total += size
                if total > _EXAM_MAX:
                    raise ValueError("MATERIAL_NATIVE_EXAM_SIZE_INVALID")
        with tempfile.TemporaryDirectory(
            prefix="material-native-publication.", dir=self.settings.staging_root
        ) as temporary:
            workspace = Path(temporary)
            proof_pointers = {}
            for role, proof in sorted(proofs.items()):
                local = workspace / f"conversion-{role}.json"
                sha, size = _json(local, proof.model_dump(mode="json"))
                member = f"native/conversion-{role.lower()}.json"
                proof_pointers[role] = self._commit(
                    operator_id=operator_id,
                    files={member: local},
                    primary=member,
                    metadata={
                        member: {
                            "schema_ref": NATIVE_HWP_QUALIFIED_CONVERSION_REF,
                            "media_type": "application/json",
                        }
                    },
                    hashes={member: sha},
                    sizes={member: size},
                    kind="material-native-qualified-conversion",
                    key="native-conversion:"
                    + content_sha256([operator_id, role, proof.model_dump(mode="json")])[7:],
                    request={"operator_id": operator_id, "source_role": role, "sha256": sha},
                )[member]
            native_files: dict[tuple[str, int], MaterialNativeFileBinding] = {}
            for selection in sources:
                role = selection.source_role
                for result in result_sets[role]:
                    native_files[role, result.item_number] = self._publish_document(
                        workspace,
                        operator_id=operator_id,
                        source_namespace=source_namespace,
                        exam_key=exam_key,
                        selection=selection,
                        source_path=directories[role] / f"{result.item_number:03d}.hwpx",
                        result=result,
                        conversion_proof=proof_pointers.get(role),
                    )
            workbook_source = self._publish_workbook(
                workspace,
                operator_id=operator_id,
                source_namespace=source_namespace,
                exam_key=exam_key,
                path=workbook_path,
                workbook=workbook,
                sheet_name=sheet.name,
            )
            cells = {c.reference: c.value for c in sheet.cells}
            class_columns = tuple(c.column for c in sheet.columns if c.semantic == "CLASSIFICATION")
            items = tuple(
                MaterialNativeExamItem(
                    item_number=row.question_number,
                    printed_label=str(row.question_number),
                    question=native_files["MAIN", row.question_number],
                    solution=native_files["SOLUTIONS", row.question_number],
                    row_number=row.row_number,
                    row_sha256=content_sha256(row.model_dump(mode="json")),
                    source_metadata=MaterialNativeSourceMetadata(
                        external_number=row.external_number,
                        original_unit=row.unit_raw,
                        original_classification=(
                            cells.get(class_columns[0] + str(row.row_number))
                            if class_columns
                            else None
                        ),
                        source_name=row.source_label,
                    ),
                )
                for row in sheet.rows
            )
            body = dict(
                schema_version="material-native-exam-bundle/1.0",
                uploaded_by=operator_id,
                source_namespace=source_namespace,
                exam_key=exam_key,
                main_original=sources[0].source_upload.original.model_dump(mode="json"),
                solutions_original=sources[1].source_upload.original.model_dump(mode="json"),
                workbook=workbook_source.model_dump(mode="json"),
                items=[item.model_dump(mode="json") for item in items],
            )
            bundle = MaterialNativeExamBundle.model_validate(
                {**body, "bundle_sha256": content_sha256(body)}
            )
            require_native_exam_bundle_sources(bundle, sources, operator_id=operator_id)
            require_native_exam_bundle_workbook(bundle, workbook)
            self._authorize(operator_id)
            member = "native/exam-bundle.json"
            local = workspace / "exam-bundle.json"
            sha, size = _json(local, bundle.model_dump(mode="json"))
            pointer = self._commit(
                operator_id=operator_id,
                files={member: local},
                primary=member,
                metadata={
                    member: {
                        "schema_ref": MATERIAL_NATIVE_BUNDLE_REF,
                        "media_type": "application/json",
                    }
                },
                hashes={member: sha},
                sizes={member: size},
                kind="material-native-exam-bundle",
                key="native-exam-bundle:" + content_sha256([operator_id, bundle.bundle_sha256])[7:],
                request={
                    "operator_id": operator_id,
                    "bundle_sha256": bundle.bundle_sha256,
                    "conversion_proofs": {
                        role: p.model_dump(mode="json") for role, p in proof_pointers.items()
                    },
                },
            )[member]
        self._reauthorize_sources(operator_id, sources)
        return MaterialNativePublication(bundle, pointer)

    def _publish_document(
        self,
        workspace: Path,
        *,
        operator_id: str,
        source_namespace: str,
        exam_key: str,
        selection: MaterialLearningSourceSelection,
        source_path: Path,
        result: NativeItemSplitResult,
        conversion_proof: MaterialArtifactMember | None,
    ) -> MaterialNativeFileBinding:
        role = result.source_role
        document_name = "native/question.hwpx" if role == "MAIN" else "native/solution.hwpx"
        receipt_name = "native/split-result.json"
        local = workspace / f"split-{role}-{result.item_number:05d}.json"
        sha, size = _json(local, result.model_dump(mode="json"))
        identity = {
            "operator_id": operator_id,
            "source_namespace": source_namespace,
            "exam_key": exam_key,
            "original_source": selection.source_upload.original.model_dump(mode="json"),
            "native_source_sha256": result.source_sha256,
            "split_plan_sha256": result.plan_sha256,
            "source_role": role,
            "item_number": result.item_number,
            "producer_profile": result.profile,
            "conversion_proof_sha256": conversion_proof.sha256 if conversion_proof else None,
        }
        pointers = self._commit(
            operator_id=operator_id,
            files={document_name: source_path, receipt_name: local},
            primary=document_name,
            metadata={
                document_name: {
                    "schema_ref": NATIVE_ITEM_DOCUMENT_REF,
                    "media_type": "application/vnd.hancom.hwpx",
                },
                receipt_name: {
                    "schema_ref": NATIVE_ITEM_SPLIT_EVIDENCE_REF,
                    "media_type": "application/json",
                },
            },
            hashes={document_name: result.output_sha256, receipt_name: sha},
            sizes={document_name: result.output_size_bytes, receipt_name: size},
            kind="material-native-item-document",
            key="native-item-document:" + content_sha256(identity)[7:],
            request={
                **identity,
                "original_source_sha256": selection.source_upload.original.sha256,
                "output_sha256": result.output_sha256,
                "split_result_sha256": sha,
                "conversion_proof": conversion_proof.model_dump(mode="json")
                if conversion_proof
                else None,
            },
        )
        return MaterialNativeFileBinding(
            source_role=role,
            original_source_sha256=selection.source_upload.original.sha256,
            native_source_sha256=result.source_sha256,
            document=pointers[document_name],
            split_evidence=pointers[receipt_name],
            split_plan_sha256=result.plan_sha256,
            ranges=result.ranges,
        )

    def _publish_workbook(
        self,
        workspace: Path,
        *,
        operator_id: str,
        source_namespace: str,
        exam_key: str,
        path: Path,
        workbook: NativeExamWorkbookDocument,
        sheet_name: str,
    ) -> MaterialNativeWorkbookSource:
        member, parsed_member = "native/original.xlsx", "native/workbook.json"
        local = workspace / "parsed-workbook.json"
        sha, size = _json(local, workbook.model_dump(mode="json"))
        pointers = self._commit(
            operator_id=operator_id,
            files={member: path, parsed_member: local},
            primary=parsed_member,
            metadata={
                member: {
                    "schema_ref": "eom://schemas/material-learning/native-exam-workbook-source/1.0",
                    "media_type": _WORKBOOK_MEDIA,
                },
                parsed_member: {
                    "schema_ref": NATIVE_WORKBOOK_MANIFEST_REF,
                    "media_type": "application/json",
                },
            },
            hashes={member: workbook.sha256, parsed_member: sha},
            sizes={member: workbook.bytes, parsed_member: size},
            kind="material-native-workbook",
            key="native-exam-workbook:"
            + content_sha256([operator_id, source_namespace, exam_key, workbook.sha256, sha])[7:],
            request={
                "operator_id": operator_id,
                "workbook_sha256": workbook.sha256,
                "parsed_sha256": sha,
            },
        )
        return MaterialNativeWorkbookSource(
            workbook=pointers[member],
            parsed_workbook=pointers[parsed_member],
            worksheet_name=sheet_name,
        )
