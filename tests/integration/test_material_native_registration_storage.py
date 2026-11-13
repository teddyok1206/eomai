"""Native six-component Registry transactions on disposable PostgreSQL.

The completed worker/source admission port is explicit and synthetic, as in the
V1 Registry fixture. Native source parsing/authorization is tested by its owners;
these tests exercise real Artifact commit, pack validation, replay and concurrency.
"""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime
from threading import Barrier
from uuid import uuid4
from zipfile import ZipFile

import pytest
from eom_catalog_contracts.material_learning import MaterialExtractionWork, MaterialLearningRights
from eom_catalog_contracts.material_learning_intake import MaterialSourceUploadCommand
from eom_catalog_contracts.material_native_files import (
    NATIVE_ITEM_DOCUMENT_REF,
    MaterialNativeItemBinding,
    material_native_registration_key,
)
from eom_catalog_contracts.material_native_intake import (
    CreateNativeMaterialLearningCommand,
    MaterialNativeExamBundle,
    MaterialNativeLearningIntakeManifest,
)
from eom_catalog_service import material_item_registration as owner
from eom_catalog_service.content_pack_service import ContentPackService
from eom_catalog_service.material_learning_artifacts import publish_material_metadata
from eom_catalog_service.material_learning_models import (
    LearningMaterialRecord,
    LearningMaterialRevisionRecord,
)
from eom_catalog_service.material_learning_source import MaterialLearningSourceService
from eom_catalog_service.models import ItemComponentRecord, ItemRevisionRecord
from eom_hwpx_contracts.native_item_split import NativeItemSplitResult
from eom_identifiers import content_sha256, sha256_bytes
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from tests.integration.test_material_item_registration_storage import (
    ROOT,
)
from tests.integration.test_material_item_registration_storage import (
    controls as controls,
)
from tests.integration.test_material_item_registration_storage import (
    guarded_engine as guarded_engine,
)
from tests.integration.test_material_item_registration_storage import (
    material_intake as material_intake,
)
from tests.integration.test_material_item_registration_storage import (
    registration_case as registration_case,
)
from tests.unit.test_material_learning_contracts import rehash
from tests.unit.test_material_native_files import binding_data
from tests.unit.test_material_native_resolution import case as workbook_case
from tests.unit.test_office_document_converter import _write_minimal_hwpx

pytestmark = [pytest.mark.integration, pytest.mark.api_integration]


@pytest.fixture
def native_registration_case(creative_engine, registration_case, tmp_path, monkeypatch):
    create, resolved = registration_case
    service = create()
    packs = ContentPackService(creative_engine, service.settings)
    pack = packs.import_source(ROOT / "content/packs/uploaded-material-item/1.1.0")
    pack = packs.release(pack.content_pack_release_id, actor_id=resolved.operator_id)
    data = binding_data()
    data.update(
        material_id=resolved.work.material_id,
        material_revision_id=resolved.work.material_revision_id,
        unit_key=resolved.unit_key,
    )
    for role in ("question", "solution"):
        raw = b"PK\x03\x04synthetic-native-registry-document-" + role.encode()
        path = tmp_path / (role + ".hwpx")
        path.write_bytes(raw)
        member = role + ".hwpx"
        committed = service.artifacts.commit_file_set(
            files={member: path},
            primary_file=member,
            artifact_type="material-native-item-document",
            idempotency_key="native-registry-test:" + resolved.task_id + ":" + role,
            request={"fixture": True},
            result={"fixture": True},
            file_metadata={
                member: {
                    "schema_ref": NATIVE_ITEM_DOCUMENT_REF,
                    "media_type": "application/vnd.hancom.hwpx",
                }
            },
            expected_file_sha256={member: sha256_bytes(raw)},
        )
        document = data[role]["document"]
        document.update(
            artifact_id=committed.artifact_id,
            artifact_revision_id=committed.revision_id,
            member_path=member,
            sha256=sha256_bytes(raw),
            bytes=len(raw),
        )
        result = NativeItemSplitResult(
            source_sha256=data[role]["native_source_sha256"],
            plan_sha256=data[role]["split_plan_sha256"],
            source_role=data[role]["source_role"],
            item_number=1,
            ranges=data[role]["ranges"],
            paragraph_sha256=("sha256:" + "1" * 64,),
            context_sha256=(),
            binary_sha256=(),
            counts=dict(paragraphs=1, tables=0, equations=0, pictures=0),
            output_sha256=document["sha256"],
            output_size_bytes=document["bytes"],
        )
        receipt = publish_material_metadata(
            service.artifacts,
            service.settings,
            result,
            member_path="split-receipt.json",
            schema_ref=data[role]["split_evidence"]["schema_ref"],
            idempotency_key="native-registry-receipt-test:" + resolved.task_id + ":" + role,
            artifact_type="material-native-split-receipt",
        )
        data[role]["split_evidence"] = receipt.model_dump(mode="json")
    binding = MaterialNativeItemBinding.model_validate(rehash(data, "binding_sha256"))
    monkeypatch.setattr(
        owner, "resolve_native_material_registration_binding", lambda *args, **kwargs: binding
    )

    def factory():
        selected = create()
        selected.native_pack_release_id = pack.content_pack_release_id
        return selected

    return factory, resolved, binding


@pytest.fixture
def native_read_case(creative_engine, native_registration_case, tmp_path, monkeypatch):
    """Real source/rights/intake/Artifact rows around the declared synthetic result port.

    Only completed AI work is substituted by the existing Registry fixture. Native
    read permissions, six components, committed bytes and source lifecycle are real.
    Logical material rows are test preconditions, never a production import bypass.
    """
    create, resolved, original_binding = native_registration_case
    service = create()
    sources = MaterialLearningSourceService(creative_engine, service.settings)
    receipts = []
    for role in ("MAIN", "SOLUTIONS"):
        path = tmp_path / ("source-" + role + ".hwpx")
        _write_minimal_hwpx(path)
        with ZipFile(path, "a") as archive:
            archive.writestr("Test/role.txt", role.encode())
        raw = path.read_bytes()
        receipts.append(
            sources.ingest(
                path,
                MaterialSourceUploadCommand(
                    actor_id=resolved.operator_id,
                    original_filename=path.name,
                    source_format="HWPX",
                    media_type="application/vnd.hancom.hwpx",
                    content_length=len(raw),
                    sha256=sha256_bytes(raw),
                    rights_confirmed=True,
                    idempotency_key="native-read-source:" + uuid4().hex,
                ),
            )
        )
    workbook, _, _, payloads = workbook_case()
    workbook_files, workbook_metadata, workbook_hashes = {}, {}, {}
    for pointer in (workbook.workbook.workbook, workbook.workbook.parsed_workbook):
        path = tmp_path / ("native-read-" + pointer.member_path.rsplit("/", 1)[-1])
        path.write_bytes(payloads[pointer.member_path])
        workbook_files[pointer.member_path] = path
        workbook_metadata[pointer.member_path] = dict(
            schema_ref=pointer.schema_ref, media_type=pointer.media_type
        )
        workbook_hashes[pointer.member_path] = pointer.sha256
    published = service.artifacts.commit_file_set(
        files=workbook_files,
        primary_file=workbook.workbook.workbook.member_path,
        artifact_type="material-native-workbook",
        idempotency_key="native-read-workbook:" + uuid4().hex,
        request={"fixture": True},
        result={"fixture": True},
        file_metadata=workbook_metadata,
        expected_file_sha256=workbook_hashes,
    )
    data = original_binding.model_dump(mode="json")
    data["printed_label"] = resolved.work.question.printed_label
    selected = workbook.items[0]
    data["source_metadata"] = selected.source_metadata.model_dump(mode="json")
    data["workbook"] = {
        **workbook.workbook.model_dump(mode="json"),
        "row_number": selected.row_number,
        "row_sha256": selected.row_sha256,
    }
    for field in ("workbook", "parsed_workbook"):
        data["workbook"][field].update(
            artifact_id=published.artifact_id, artifact_revision_id=published.revision_id
        )
    for role, receipt in zip(("question", "solution"), receipts, strict=True):
        data[role]["original_source_sha256"] = receipt.original.sha256
        data[role]["native_source_sha256"] = receipt.original.sha256
        file = data[role]
        result = NativeItemSplitResult(
            source_sha256=file["native_source_sha256"],
            plan_sha256=file["split_plan_sha256"],
            source_role=file["source_role"],
            item_number=1,
            ranges=file["ranges"],
            paragraph_sha256=("sha256:" + "1" * 64,),
            context_sha256=(),
            binary_sha256=(),
            counts=dict(paragraphs=1, tables=0, equations=0, pictures=0),
            output_sha256=file["document"]["sha256"],
            output_size_bytes=file["document"]["bytes"],
        )
        pointer = publish_material_metadata(
            service.artifacts,
            service.settings,
            result,
            member_path="split-receipt.json",
            schema_ref=file["split_evidence"]["schema_ref"],
            idempotency_key="native-read-split:" + uuid4().hex,
            artifact_type="material-native-split-receipt",
        )
        file["split_evidence"] = pointer.model_dump(mode="json")
    binding = MaterialNativeItemBinding.model_validate(rehash(data, "binding_sha256"))
    bundle = MaterialNativeExamBundle.model_validate(
        rehash(
            dict(
                schema_version="material-native-exam-bundle/1.0",
                uploaded_by=resolved.operator_id,
                source_namespace=binding.source_namespace,
                exam_key=binding.exam_key,
                main_original=receipts[0].original.model_dump(mode="json"),
                solutions_original=receipts[1].original.model_dump(mode="json"),
                workbook={
                    key: value
                    for key, value in data["workbook"].items()
                    if key not in {"row_number", "row_sha256"}
                },
                items=[
                    dict(
                        item_number=1,
                        printed_label=binding.printed_label,
                        question=data["question"],
                        solution=data["solution"],
                        row_number=selected.row_number,
                        row_sha256=selected.row_sha256,
                        source_metadata=data["source_metadata"],
                    )
                ],
            ),
            "bundle_sha256",
        )
    )
    bundle_pointer = publish_material_metadata(
        service.artifacts,
        service.settings,
        bundle,
        member_path="native/exam-bundle.json",
        schema_ref="eom://schemas/material-learning/native-exam-bundle/1.0",
        idempotency_key="native-read-bundle:" + uuid4().hex,
        artifact_type="material-native-bundle",
    )
    command = CreateNativeMaterialLearningCommand.model_validate(
        dict(
            schema_version="material-learning-create/2.0",
            actor_id=resolved.operator_id,
            idempotency_key="native-read-intake:" + uuid4().hex,
            upload=dict(
                title="Native read fixture",
                material_kind="MOCK_EXAM",
                source_description="Synthetic reader test",
                additional_instructions="",
                curriculum_unit_hints=[],
                rights_confirmed=True,
            ),
            sources=[
                dict(source_role=role, source_upload=receipt.model_dump(mode="json"))
                for role, receipt in zip(("MAIN", "SOLUTIONS"), receipts, strict=True)
            ],
            native_bundle=bundle_pointer.model_dump(mode="json"),
        )
    )
    rights = MaterialLearningRights.model_validate(
        rehash(
            dict(
                schema_version="material-learning-rights/1.0",
                material_id=binding.material_id,
                material_revision_id=binding.material_revision_id,
                attested_by=resolved.operator_id,
                attested_at=datetime.now(UTC).isoformat().replace("+00:00", "Z"),
                basis="UPLOADER_ATTESTED_INTERNAL_PROCESSING",
                source_hashes=[receipt.original.sha256 for receipt in receipts],
                permitted_uses=[
                    "INTERNAL_ANALYSIS",
                    "ITEM_REGISTRATION",
                    "GRAPH_RETRIEVAL",
                    "LOCAL_EMBEDDING",
                ],
                public_redistribution_permitted=False,
                withdrawal_policy="DENY_NEW_RESOLUTION_PRESERVE_PINNED_AUDIT",
            ),
            "attestation_sha256",
        )
    )
    rights_pointer = publish_material_metadata(
        service.artifacts,
        service.settings,
        rights,
        member_path="rights/attestation.json",
        schema_ref="eom://schemas/material-learning/rights/1.0",
        idempotency_key="native-read-rights:" + uuid4().hex,
        artifact_type="material-native-rights",
    )
    intake = MaterialNativeLearningIntakeManifest(
        material_id=binding.material_id,
        material_revision_id=binding.material_revision_id,
        requested_by=resolved.operator_id,
        request_sha256=content_sha256(command.model_dump(mode="json")),
        upload=command.upload,
        sources=command.sources,
        rights_attestation=rights_pointer,
        native_bundle=bundle_pointer,
    )
    intake_pointer = publish_material_metadata(
        service.artifacts,
        service.settings,
        intake,
        member_path="material/intake.json",
        schema_ref="eom://schemas/material-learning/intake/2.0",
        idempotency_key="native-read-intake-record:" + uuid4().hex,
        artifact_type="material-native-intake",
    )
    with Session(creative_engine) as session, session.begin():
        material = LearningMaterialRecord(
            material_id=binding.material_id,
            lifecycle_state="ACTIVE",
            created_by=resolved.operator_id,
        )
        session.add(material)
        session.flush()
        session.add(
            LearningMaterialRevisionRecord(
                material_revision_id=binding.material_revision_id,
                material_id=binding.material_id,
                revision_number=1,
                title=command.upload.title,
                material_kind=command.upload.material_kind,
                request_sha256=intake.request_sha256,
                manifest_artifact_id=intake_pointer.artifact_id,
                manifest_artifact_revision_id=intake_pointer.artifact_revision_id,
                manifest_member_path=intake_pointer.member_path,
                manifest_sha256=intake_pointer.sha256,
                idempotency_key=command.idempotency_key,
                created_by=resolved.operator_id,
            )
        )
        session.flush()
        material.current_revision_id = binding.material_revision_id
    monkeypatch.setattr(
        owner, "resolve_native_material_registration_binding", lambda *a, **k: binding
    )
    return create, resolved, binding


def test_native_concurrent_registration_keeps_one_revision_and_six_exact_components(
    creative_engine, native_registration_case
):
    create, resolved, binding = native_registration_case
    barrier = Barrier(2)

    def submit(_):
        service = create()
        barrier.wait(timeout=10)
        return service.register_completed(
            task_id=resolved.task_id, operator_id=resolved.operator_id
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        first, second = pool.map(submit, range(2))
    assert first.item_revision_id == second.item_revision_id
    assert sum((first.created, second.created)) == 1
    with Session(creative_engine) as session:
        revision = session.get(ItemRevisionRecord, first.item_revision_id)
        assert revision.metadata_json["external_number"] is None
        assert revision.metadata_json["original_unit"] == " 단원 원문 "
        assert revision.metadata_json["source_kind"] == "EXTERNAL"
        rows = tuple(
            session.scalars(
                select(ItemComponentRecord).where(
                    ItemComponentRecord.item_revision_id == first.item_revision_id
                )
            )
        )
        components = {(row.component_type, row.ordinal): row for row in rows}
        assert len(rows) == 6
        assert (
            components[("OTHER", 0)].artifact_revision_id
            == binding.question.document.artifact_revision_id
        )
        assert components[("OTHER", 1)].sha256 == binding.solution.document.sha256
        assert (
            session.scalar(
                select(func.count())
                .select_from(ItemRevisionRecord)
                .where(ItemRevisionRecord.registration_key == revision.registration_key)
            )
            == 1
        )


def test_native_registry_commit_interruption_recovers_the_same_original_files(
    native_registration_case,
):
    create, resolved, _ = native_registration_case
    first = create()
    register = first.registry.register

    def interrupted(command):
        register(command)
        raise RuntimeError("synthetic native interruption after Registry commit")

    first.registry.register = interrupted
    with pytest.raises(RuntimeError, match="after Registry commit"):
        first.register_completed(task_id=resolved.task_id, operator_id=resolved.operator_id)
    replay = create().register_completed(task_id=resolved.task_id, operator_id=resolved.operator_id)
    assert not replay.created


def test_native_cannot_register_with_the_legacy_pack_or_missing_native_configuration(
    creative_engine,
    native_registration_case,
):
    create, resolved, _ = native_registration_case
    service = create()
    service.native_pack_release_id = service.pack_release_id
    with pytest.raises(ValueError, match="REGISTRATION_NOT_AUTHORIZED"):
        service.register_completed(task_id=resolved.task_id, operator_id=resolved.operator_id)
    service.native_pack_release_id = None
    with pytest.raises(ValueError, match="REGISTRATION_NOT_AUTHORIZED"):
        service.register_completed(task_id=resolved.task_id, operator_id=resolved.operator_id)
    with Session(creative_engine) as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(ItemRevisionRecord)
                .where(
                    ItemRevisionRecord.source_workflow_step_run_id == resolved.selection.step_run_id
                )
            )
            == 0
        )


def test_registered_native_source_metadata_uses_existing_material_rows_not_legacy_notion(
    creative_engine, native_read_case
):
    from eom_catalog_service.material_native_item_read import read_native_material_original_metadata

    create, resolved, binding = native_read_case
    registered = create().register_completed(
        task_id=resolved.task_id, operator_id=resolved.operator_id
    )
    with Session(creative_engine) as session:
        revision = session.get(ItemRevisionRecord, registered.item_revision_id)
        sources = read_native_material_original_metadata(
            session,
            item_manifests={revision.item_revision_id: revision.manifest_sha256},
        )
        source = sources[revision.item_revision_id]
        assert source.metadata.source_kind == "EXTERNAL"
        assert source.metadata.external_number == binding.source_metadata.external_number
        assert source.metadata.original_unit == binding.source_metadata.original_unit
        assert source.metadata.material_id == resolved.work.material_id
        assert source.material_title
        assert "source_id" not in source.metadata.model_dump()


def test_native_source_read_and_original_pair_download_use_real_permissions_artifacts_and_hashes(
    creative_engine, native_read_case
):
    from eom_catalog_contracts.material_native_item_read import MaterialNativeItemReadRequest
    from eom_catalog_service.material_native_item_read import (
        MaterialNativeItemReadError,
        MaterialNativeItemReadService,
    )
    from eom_orchestrator.models import ArtifactRevisionRecord

    create, resolved, binding = native_read_case
    registration = create()
    registered = registration.register_completed(
        task_id=resolved.task_id, operator_id=resolved.operator_id
    )
    with Session(creative_engine) as session:
        revision = session.get(ItemRevisionRecord, registered.item_revision_id)
        manifest = revision.manifest_sha256
    reads = MaterialNativeItemReadService(creative_engine, registration.settings)
    query = MaterialNativeItemReadRequest(
        operation="GET_NATIVE_MATERIAL_ITEM_SOURCE",
        actor_id=resolved.operator_id,
        item_revision_id=registered.item_revision_id,
        item_manifest_sha256=manifest,
    )
    source = reads.read_source(query)
    assert source.metadata.original_unit == binding.source_metadata.original_unit
    assert (
        source.question == binding.question.document
        and source.solution == binding.solution.document
    )
    for role, file in (("MAIN", binding.question), ("SOLUTIONS", binding.solution)):
        command = MaterialNativeItemReadRequest(
            **{
                **query.model_dump(),
                "operation": "GET_NATIVE_MATERIAL_ITEM_DOCUMENT",
                "source_role": role,
            }
        )
        result = reads.open_document(command)
        raw = b"".join(result.member.iter_chunks())
        assert sha256_bytes(raw) == result.header.sha256 == file.document.sha256
        assert len(raw) == result.header.content_length == file.document.bytes
        assert result.member.stream.closed
        assert result.header.filename.endswith(f"-{role.lower()}.hwpx")
        again = reads.open_document(command)
        assert again.header == result.header
        again.member.stream.close()
    # The canonical approved revision cannot be rewritten even by the test owner.
    # Assert that boundary rather than disabling the trigger to invent a revocation.
    from sqlalchemy.exc import ProgrammingError

    with (
        pytest.raises(ProgrammingError, match="approved EOM artifacts and revisions are immutable"),
        Session(creative_engine) as session,
        session.begin(),
    ):
        original = session.get(
            ArtifactRevisionRecord, source.workbook.workbook.artifact_revision_id
        )
        assert original is not None
        original.approved = False
    assert reads.read_source(query) == source
    from eom_identity_service.models import OperatorRecord

    with Session(creative_engine) as session, session.begin():
        session.get(OperatorRecord, resolved.operator_id).status = "DISABLED"
    with pytest.raises(MaterialNativeItemReadError, match="PERMISSION_DENIED"):
        reads.read_source(query)


def test_metadata_only_new_material_revision_does_not_duplicate_the_same_native_item(
    creative_engine, native_registration_case, monkeypatch
):
    """The synthetic completed-source port reaches the real UNIQUE/advisory guard.

    A metadata successor feature is not implemented by quietly returning the old
    lineage or by pretending a new material revision is a different source item.
    """
    create, resolved, binding = native_registration_case
    first = create().register_completed(task_id=resolved.task_id, operator_id=resolved.operator_id)
    replay = create().register_completed(task_id=resolved.task_id, operator_id=resolved.operator_id)
    assert first.item_revision_id == replay.item_revision_id and not replay.created
    new_revision = "materialrev_" + uuid4().hex
    work_data = resolved.work.model_dump(mode="json")
    work_data["material_revision_id"] = new_revision
    work = MaterialExtractionWork.model_validate(rehash(work_data))
    changed_binding = binding.model_dump(mode="json")
    changed_binding["material_revision_id"] = new_revision
    changed_binding["source_metadata"]["external_number"] = "54321"
    updated = MaterialNativeItemBinding.model_validate(rehash(changed_binding, "binding_sha256"))
    successor = replace(resolved, work=work)
    monkeypatch.setattr(owner, "resolve_completed_material_task", lambda *a, **k: successor)
    monkeypatch.setattr(
        owner, "resolve_native_material_registration_binding", lambda *a, **k: updated
    )
    stable_key = material_native_registration_key(resolved.operator_id, binding)
    assert stable_key == material_native_registration_key(resolved.operator_id, updated)
    with pytest.raises(ValueError, match="MATERIAL_NATIVE_METADATA_UPDATE_REQUIRED"):
        create().register_completed(task_id=resolved.task_id, operator_id=resolved.operator_id)
    with Session(creative_engine) as session:
        rows = tuple(
            session.scalars(
                select(ItemRevisionRecord).where(ItemRevisionRecord.registration_key == stable_key)
            )
        )
        assert len(rows) == 1 and rows[0].item_revision_id == first.item_revision_id
        assert rows[0].metadata_json["material_revision_id"] == binding.material_revision_id
        assert rows[0].metadata_json["external_number"] is None


def test_native_intake2_prepares_and_replays_in_the_real_educational_document_owner(
    creative_engine, native_read_case, tmp_path
):
    """Only Office/PDF pixel projection and extraction are synthetic adapters here."""
    from contextlib import contextmanager

    from eom_catalog_contracts.document_review import OfficeDocumentReviewConversionIdentity
    from eom_catalog_contracts.material_learning import MaterialArtifactMember
    from eom_catalog_contracts.material_native_intake import MaterialNativePreparationInput
    from eom_catalog_service.educational_document_service import EducationalDocumentService
    from eom_catalog_service.material_intake_read import (
        material_intake_pointer,
        read_material_intake,
    )
    from eom_catalog_service.material_learning_pages import MaterialPagePreparationService
    from eom_catalog_service.material_learning_source import authorize_material_learning
    from eom_catalog_service.material_learning_source_projection import LocalMaterialSource
    from eom_identifiers import canonical_json_bytes
    from eom_image_contracts.office_embedded_images import OfficeEmbeddedImageSet
    from eom_image_contracts.office_picture_uses import OfficePictureUseCatalog
    from eom_orchestrator.file_set_control_artifacts import ControlFileSetPublisher
    from eom_orchestrator.models import ArtifactRevisionRecord
    from eom_orchestrator.settings import Settings

    from tests.integration.test_material_learning_page_preparation import InterruptibleExtractor
    from tests.unit.test_material_learning_preparation import profile

    create, resolved, binding = native_read_case
    registration = create()
    artifacts, settings = registration.artifacts, registration.settings

    def authorize():
        with Session(creative_engine) as session:
            authorize_material_learning(session, resolved.operator_id)

    with Session(creative_engine) as session:
        material = session.get(LearningMaterialRevisionRecord, binding.material_revision_id)
        pointer = material_intake_pointer(
            session,
            artifact_id=material.manifest_artifact_id,
            revision_id=material.manifest_artifact_revision_id,
            sha256=material.manifest_sha256,
        )
    intake = read_material_intake(artifacts, pointer, authorize=authorize)
    assert isinstance(intake, MaterialNativeLearningIntakeManifest)
    assert pointer.schema_ref == "eom://schemas/material-learning/intake/2.0"
    pdf_path = tmp_path / "synthetic-native-review.pdf"
    pdf = b"%PDF-1.7\nexplicit synthetic Office projection adapter\n"
    pdf_path.write_bytes(pdf)
    raw_profile = profile()
    raw_profile.update(
        office_tool_source_commit="a" * 40,
        libreoffice_sha256="sha256:" + "b" * 64,
        h2orestart_sha256="sha256:" + "c" * 64,
        chunk_page_limit=1,
    )
    raw_profile = rehash(raw_profile, "profile_sha256")
    conversion = OfficeDocumentReviewConversionIdentity(
        conversion_kind="LIBREOFFICE_H2ORESTART_PDF",
        review_pdf_sha256=sha256_bytes(pdf),
        libreoffice_version="synthetic-adapter-not-executed",
        libreoffice_sha256=raw_profile["libreoffice_sha256"],
        h2orestart_sha256=raw_profile["h2orestart_sha256"],
    )
    local = {}
    for selected in intake.sources:
        embedded = OfficeEmbeddedImageSet.model_validate(
            rehash(
                dict(
                    schema_version="office-embedded-image-set/1.0",
                    source_sha256=selected.source_upload.original.sha256,
                    source_format="HWPX",
                    extractor_profile="WHOLE_EMBEDDED_RASTER_V1",
                    images=[],
                    unsupported_members=[],
                ),
                "manifest_sha256",
            )
        )
        catalog = OfficePictureUseCatalog.model_validate(
            rehash(
                dict(
                    schema_version="office-picture-use-catalog/1.0",
                    extractor_profile="HANCOM_NATIVE_PICTURE_USES_V1",
                    embedded_images=embedded.model_dump(mode="json"),
                    picture_uses=[],
                    rendered_uses=[],
                    native_objects=[],
                ),
                "manifest_sha256",
            )
        )
        raw_catalog = canonical_json_bytes(catalog.model_dump(mode="json"))
        catalog_path = tmp_path / (selected.source_role + "-catalog.json")
        catalog_path.write_bytes(raw_catalog)
        pdf_member, catalog_member = "source/review.pdf", "picture-use-catalog.json"
        metadata = {
            pdf_member: dict(
                schema_ref="eom://schemas/educational-document/pdf-source/1.0",
                media_type="application/pdf",
            ),
            catalog_member: dict(
                schema_ref="eom://schemas/image-provider/office-picture-use-catalog/1.0",
                media_type="application/json",
            ),
        }
        committed = artifacts.commit_file_set(
            files={pdf_member: pdf_path, catalog_member: catalog_path},
            primary_file=pdf_member,
            artifact_type="synthetic-native-office-projection",
            idempotency_key="native-document-projection:" + uuid4().hex,
            request={"synthetic_projection_adapter": True},
            result={"fixture": True},
            file_metadata=metadata,
            expected_file_sha256={
                pdf_member: sha256_bytes(pdf),
                catalog_member: sha256_bytes(raw_catalog),
            },
        )

        def member(name, raw, *, committed=committed, metadata=metadata):
            return MaterialArtifactMember(
                artifact_id=committed.artifact_id,
                artifact_revision_id=committed.revision_id,
                member_path=name,
                sha256=sha256_bytes(raw),
                bytes=len(raw),
                **metadata[name],
            )

        local[selected.source_role] = LocalMaterialSource(
            pdf_path, member(pdf_member, pdf), conversion, member(catalog_member, raw_catalog)
        )

    class Projection:
        def authorize_source(self, selected, *, operator_id):
            MaterialLearningSourceService(creative_engine, settings).resolve(
                selected.source_upload, operator_id=operator_id
            )

        @contextmanager
        def stage(self, work, selected, *, operator_id, authorize):
            authorize()
            self.authorize_source(selected, operator_id=operator_id)
            yield local[selected.source_role]
            authorize()

    work = MaterialNativePreparationInput.model_validate(
        rehash(
            dict(
                schema_version="material-learning-preparation-input/2.0",
                task_id="materialtask_" + uuid4().hex,
                material_id=binding.material_id,
                material_revision_id=binding.material_revision_id,
                intake_manifest=pointer.model_dump(mode="json"),
                profile=raw_profile,
                native_bundle=intake.native_bundle.model_dump(mode="json"),
            )
        )
    )
    extractor = InterruptibleExtractor()
    extractor.interrupt = False
    service = MaterialPagePreparationService(
        creative_engine,
        settings=settings,
        publisher=ControlFileSetPublisher(
            creative_engine,
            Settings(
                staging_root=settings.staging_root, nas_artifact_root=settings.nas_artifact_root
            ),
        ),
        source_commit="1" * 40,
        extractor=extractor,
        projections=Projection(),
    )
    first = service.prepare(work, operator_id=resolved.operator_id, authorize=authorize)
    assert first.prepared.schema_version == "material-learning-prepared/2.0"
    assert first.prepared.native_bundle == intake.native_bundle
    replay = service.prepare(work, operator_id=resolved.operator_id, authorize=authorize)
    assert replay == first and extractor.calls == [1, 2, 3, 1, 2, 3]
    documents = EducationalDocumentService(creative_engine, settings)
    for selected, prepared in zip(intake.sources, first.prepared.sources, strict=True):
        actual = documents.inspect_material_revision(prepared.document_revision_id)
        assert actual.original == selected.source_upload.original
        assert actual.source == local[selected.source_role].pdf
        with Session(creative_engine) as session:
            assert session.get(
                ArtifactRevisionRecord, actual.revision_manifest.artifact_revision_id
            ).approved


def test_native_registered_item_reuses_the_real_solution_and_common_embedding_projection(
    creative_engine, native_registration_case, tmp_path, controls
):
    from tests.integration.test_material_item_registration_storage import (
        test_uploaded_item_uses_real_registered_solution_and_common_embedding_projection as verify,
    )

    create, resolved, _ = native_registration_case
    verify(creative_engine, (create, resolved), tmp_path, controls, material_purpose=True)
