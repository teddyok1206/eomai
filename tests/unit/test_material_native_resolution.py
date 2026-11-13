"""Native receipt admission rechecks committed bytes and the actual XLSX observations."""

from io import BytesIO
from types import SimpleNamespace

import pytest
from eom_catalog_contracts.material_learning import MaterialArtifactMember
from eom_catalog_contracts.material_native_intake import (
    MATERIAL_NATIVE_BUNDLE_REF,
    CreateNativeMaterialLearningCommand,
    MaterialNativeExamBundle,
)
from eom_catalog_service.material_native_resolution import (
    read_material_native_bundle,
    verify_material_native_bundle_files,
)
from eom_catalog_service.native_exam_workbook import read_native_exam_workbook
from eom_identifiers import canonical_json_bytes, content_sha256, sha256_bytes

from tests.unit.test_material_learning_contracts import rehash
from tests.unit.test_material_native_files import split_result
from tests.unit.test_material_native_intake import native_create, native_exam_bundle
from tests.unit.test_native_exam_intake import _parts, _zip


def case():
    value = native_exam_bundle()
    payloads = {}

    def pin(pointer, payload):
        result = {**pointer, "sha256": sha256_bytes(payload), "bytes": len(payload)}
        payloads[result["member_path"]] = payload
        return result

    raw = _zip(_parts())
    parsed = read_native_exam_workbook(raw)
    sheet = parsed.worksheets[0]
    row = sheet.rows[0]
    value["workbook"].update(
        workbook=pin(value["workbook"]["workbook"], raw),
        parsed_workbook=pin(
            value["workbook"]["parsed_workbook"],
            canonical_json_bytes(parsed.model_dump(mode="json")),
        ),
        worksheet_name=sheet.name,
    )
    item = value["items"][0]
    item.update(
        row_number=row.row_number,
        row_sha256=content_sha256(row.model_dump(mode="json")),
        source_metadata=dict(
            external_number=row.external_number,
            original_unit=row.unit_raw,
            original_classification="통합과학 - 창작",
            source_name=row.source_label,
        ),
    )
    for role in ("question", "solution"):
        file = item[role]
        file["document"] = pin(file["document"], b"PK\x03\x04synthetic-native-" + role.encode())
    temporary = MaterialNativeExamBundle.model_validate(rehash(value, "bundle_sha256"))
    for role in ("question", "solution"):
        file = getattr(temporary.items[0], role)
        # The producer/preservation verifier has separate native-package tests. Here
        # each synthetic receipt deliberately tests only the Artifact binding owner.
        record = split_result(SimpleNamespace(question=file)).model_dump(mode="json")
        record["source_role"] = file.source_role
        item[role]["split_evidence"] = pin(
            file.split_evidence.model_dump(mode="json"), canonical_json_bytes(record)
        )
    bundle = MaterialNativeExamBundle.model_validate(rehash(value, "bundle_sha256"))
    body = canonical_json_bytes(bundle.model_dump(mode="json"))
    pointer = MaterialArtifactMember.model_validate(pin(native_create()["native_bundle"], body))

    class Reader:
        def __init__(self):
            self.opened = []
            self.calls = []

        def read_member(self, **kwargs):
            self.calls.append(kwargs)
            return payloads[kwargs["member_path"]]

        def open_verified_member(self, **kwargs):
            stream = BytesIO(payloads[kwargs["member_path"]])
            self.opened.append(stream)
            return SimpleNamespace(stream=stream, content_length=len(stream.getbuffer()))

    return bundle, pointer, Reader(), payloads


def test_native_bundle_source_owner_and_all_files_are_verified_without_returning_documents():
    bundle, pointer, reader, _ = case()
    command = CreateNativeMaterialLearningCommand.model_validate(native_create())
    checks = []
    assert (
        read_material_native_bundle(
            reader,
            pointer,
            sources=command.sources,
            operator_id=command.actor_id,
            authorize=lambda: checks.append(True),
        )
        == bundle
    )
    assert len(checks) == 2
    assert pointer.schema_ref == MATERIAL_NATIVE_BUNDLE_REF
    assert (
        verify_material_native_bundle_files(reader, bundle, authorize=lambda: checks.append(True))
        is None
    )
    assert len(reader.opened) == 2 and all(stream.closed for stream in reader.opened)


@pytest.mark.parametrize("part", ["bundle", "parsed_workbook", "workbook", "receipt"])
def test_native_bundle_rejects_changed_committed_bytes(part):
    bundle, pointer, reader, payloads = case()
    selected = {
        "bundle": pointer,
        "parsed_workbook": bundle.workbook.parsed_workbook,
        "workbook": bundle.workbook.workbook,
        "receipt": bundle.items[0].question.split_evidence,
    }[part]
    payloads[selected.member_path] += b"changed"
    with pytest.raises(ValueError, match="IDENTITY_MISMATCH"):
        if part == "bundle":
            command = CreateNativeMaterialLearningCommand.model_validate(native_create())
            read_material_native_bundle(
                reader,
                pointer,
                sources=command.sources,
                operator_id=command.actor_id,
                authorize=lambda: None,
            )
        else:
            verify_material_native_bundle_files(reader, bundle, authorize=lambda: None)


def test_native_bundle_rejects_another_operator_before_file_validation():
    _, pointer, reader, _ = case()
    command = CreateNativeMaterialLearningCommand.model_validate(native_create())
    with pytest.raises(ValueError, match=r"OWNER_OR_SOURCE_MISMATCH|OWNER_MISMATCH"):
        read_material_native_bundle(
            reader,
            pointer,
            sources=command.sources,
            operator_id="operator_" + "0" * 32,
            authorize=lambda: None,
        )
    assert not reader.opened


def test_native_bundle_closes_descriptor_if_the_native_file_size_or_signature_is_wrong():
    bundle, _, reader, payloads = case()
    selected = bundle.items[0].question.document
    payloads[selected.member_path] = b"not a native document"
    with pytest.raises(ValueError, match="DOCUMENT_IDENTITY_MISMATCH"):
        verify_material_native_bundle_files(reader, bundle, authorize=lambda: None)
    assert len(reader.opened) == 1 and reader.opened[0].closed


def test_native_bundle_denies_revoked_permission_without_reading_any_artifact():
    bundle, _, reader, _ = case()

    def revoked():
        raise ValueError("REVOKED")

    with pytest.raises(ValueError, match="REVOKED"):
        verify_material_native_bundle_files(reader, bundle, authorize=revoked)
    assert not reader.calls and not reader.opened
