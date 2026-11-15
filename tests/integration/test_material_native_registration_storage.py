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

from tests.integration.test_material_coverage_registration_storage import build_family_registration
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
def native_registration_case(creative_engine, registration_case, tmp_path, monkeypatch, request):
    options = getattr(request, "param", {})
    exact = options.get("family") == 3
    create, resolved = registration_case
    if exact:
        create, resolved = build_family_registration(
            creative_engine, registration_case, tmp_path, monkeypatch, **options
        )
    service = create()
    packs = ContentPackService(creative_engine, service.settings)
    pack = packs.import_source(
        ROOT / "content/packs/uploaded-material-item" / ("1.5.0" if exact else "1.1.0")
    )
    pack = packs.release(pack.content_pack_release_id, actor_id=resolved.operator_id)
    data = binding_data()
    data.update(
        material_id=resolved.work.material_id,
        material_revision_id=resolved.work.material_revision_id,
        unit_key=resolved.unit_key,
    )
    for role in ("question", "solution"):
        raw = b"PK\x03\x04synthetic-native-registry-document-" + role.encode()
        if exact:
            from tests.unit.test_material_native_score import package, section

            raw = package(section(f"[{options['points']}점]" if role == "question" else "해설"))
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
        if exact:
            selected.native_exact_score_pack_release_id = pack.content_pack_release_id
        else:
            selected.native_pack_release_id = pack.content_pack_release_id
        # The parent fixture substitutes completed AI/source admission and has no
        # Material run/task rows. This port is synthetic here too: these cases
        # test Registry commit/replay/metadata, not native visual qualification.
        monkeypatch.setattr(selected, "_verify_native_visual_scope", lambda *_a, **_k: None)
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


def test_native_preparation_recovery_preserves_original_pair_workbook_and_bundle(
    creative_engine, native_read_case
):
    from types import SimpleNamespace

    from eom_catalog_contracts.material_learning_preparation import MaterialPreparationProfile
    from eom_catalog_contracts.material_preparation_recovery import (
        RecoverMaterialPreparationCommand,
    )
    from eom_catalog_service.material_intake_read import (
        material_intake_pointer,
        read_material_intake,
        read_material_preparation,
    )
    from eom_catalog_service.material_learning_coordinator import build_material_preparation_input
    from eom_catalog_service.material_learning_models import (
        MaterialLearningRunRecord,
        MaterialLearningTaskRecord,
    )
    from eom_catalog_service.material_preparation_recovery import MaterialPreparationRecoveryService

    from tests.unit.test_material_learning_preparation import profile

    create, resolved, binding = native_read_case
    artifacts = create().artifacts
    settings = create().settings
    with Session(creative_engine) as session:
        revision = session.get(LearningMaterialRevisionRecord, binding.material_revision_id)
        intake_pointer = material_intake_pointer(
            session,
            artifact_id=revision.manifest_artifact_id,
            revision_id=revision.manifest_artifact_revision_id,
            sha256=revision.manifest_sha256,
        )
    intake = read_material_intake(artifacts, intake_pointer, authorize=lambda: None)
    run_id, task_id = "materialrun_" + uuid4().hex, "materialtask_" + uuid4().hex
    old_profile = MaterialPreparationProfile.model_validate(profile())
    old_work = build_material_preparation_input(
        intake, intake_pointer=intake_pointer, task_id=task_id, profile=old_profile
    )
    pointer = publish_material_metadata(
        artifacts,
        settings,
        old_work,
        member_path="material/preparation-input.json",
        schema_ref="eom://schemas/material-learning/preparation-input/2.0",
        idempotency_key="material-prepare-input:" + task_id,
        artifact_type="material-learning-preparation-input",
    )
    now = datetime.now(UTC)
    with Session(creative_engine) as session, session.begin():
        session.add(
            MaterialLearningRunRecord(
                run_id=run_id,
                material_revision_id=binding.material_revision_id,
                attempt=1,
                state="PREPARING",
                next_event_sequence=1,
                created_by=resolved.operator_id,
                created_at=now,
                updated_at=now,
            )
        )
        session.flush()
        session.add(
            MaterialLearningTaskRecord(
                task_id=task_id,
                run_id=run_id,
                task_kind="PREPARE",
                unit_key="source-preparation",
                ordinal=1,
                attempt=1,
                state="PREPARING",
                execution_lane="MATERIAL_LEARNING",
                input_artifact_id=pointer.artifact_id,
                input_artifact_revision_id=pointer.artifact_revision_id,
                input_sha256=pointer.sha256,
                created_at=now,
                updated_at=now,
            )
        )
    raw = old_profile.model_dump(mode="json")
    raw["source_commit"] = "2" * 40
    raw["profile_sha256"] = content_sha256({k: v for k, v in raw.items() if k != "profile_sha256"})
    target = MaterialPreparationProfile.model_validate(raw)
    service = MaterialPreparationRecoveryService(
        creative_engine,
        settings=settings,
        target_profile=target,
        drain=SimpleNamespace(require_quiescent=lambda: None),
    )
    command = RecoverMaterialPreparationCommand(
        actor_id=resolved.operator_id,
        run_id=run_id,
        expected_updated_at=now,
        expected_input_sha256=pointer.sha256,
        target_profile_sha256=target.profile_sha256,
        error_code="MATERIAL_LEARNING_SOURCE_FILE_INVALID",
    )
    result = service.recover(command)
    new_work = read_material_preparation(artifacts, result.new_input, authorize=lambda: None)
    assert new_work.schema_version == "material-learning-preparation-input/2.0"
    assert new_work.intake_manifest == old_work.intake_manifest == intake_pointer
    assert new_work.native_bundle == old_work.native_bundle == intake.native_bundle
    assert new_work.material_revision_id == old_work.material_revision_id
    assert new_work.profile.profile_sha256 == target.profile_sha256
    assert service.recover(command).replayed


@pytest.fixture
def native_finalization_case(creative_engine, native_read_case, monkeypatch, request):
    """Real source/Artifact/history; only already-completed model admission is synthetic."""
    from types import SimpleNamespace

    from eom_catalog_contracts.material_discovery_finalization_recovery import (
        RecoverNativeMaterialDiscoveryFinalizationCommand,
    )
    from eom_catalog_contracts.material_learning_preparation import MaterialPreparationProfile
    from eom_catalog_contracts.material_native_intake import MaterialNativePreparedArtifact
    from eom_catalog_service import material_discovery_finalization_recovery as recovery_owner
    from eom_catalog_service.material_discovery_finalization_recovery import (
        NativeMaterialDiscoveryFinalizationRecoveryService,
    )
    from eom_catalog_service.material_intake_read import (
        material_intake_pointer,
        read_material_intake,
    )
    from eom_catalog_service.material_learning_coordinator import build_material_preparation_input
    from eom_catalog_service.material_learning_models import (
        MaterialLearningRunRecord,
        MaterialLearningTaskRecord,
    )
    from eom_catalog_service.material_native_resolution import read_material_native_bundle

    from tests.unit.test_material_learning_preparation import profile
    from tests.unit.test_material_native_discovery_coverage import plan
    from tests.unit.test_material_native_intake import native_prepared

    create, resolved, binding = native_read_case
    settings, artifacts = create().settings, create().artifacts
    with Session(creative_engine) as session:
        revision = session.get(LearningMaterialRevisionRecord, binding.material_revision_id)
        intake_pointer = material_intake_pointer(
            session,
            artifact_id=revision.manifest_artifact_id,
            revision_id=revision.manifest_artifact_revision_id,
            sha256=revision.manifest_sha256,
        )
    intake = read_material_intake(artifacts, intake_pointer, authorize=lambda: None)
    native = read_material_native_bundle(
        artifacts,
        intake.native_bundle,
        sources=intake.sources,
        operator_id=resolved.operator_id,
        authorize=lambda: None,
    )
    selected_case = getattr(request, "param", "MATERIAL_NATIVE_DISCOVERY_NUMBER_INVALID")
    failure_code = selected_case[0] if isinstance(selected_case, tuple) else selected_case
    data = native_prepared()
    data.update(
        material_id=binding.material_id,
        material_revision_id=binding.material_revision_id,
        intake_manifest=intake_pointer.model_dump(mode="json"),
        native_bundle=intake.native_bundle.model_dump(mode="json"),
    )
    for source, selection in zip(data["sources"], intake.sources, strict=True):
        source["original"] = selection.source_upload.original.model_dump(mode="json")
        source["actual_format"] = "HWPX"
        if isinstance(selected_case, tuple) and selected_case[1] == "VISUAL":
            source["office_catalog"].update(
                member_path="picture-use-catalog.json",
                schema_ref="eom://schemas/image-provider/office-picture-use-catalog/1.0",
            )
    prepared = MaterialNativePreparedArtifact.model_validate(rehash(data, "prepared_sha256"))
    pointer = publish_material_metadata(
        artifacts,
        settings,
        prepared,
        member_path="material/prepared.json",
        schema_ref="eom://schemas/material-learning/prepared/2.0",
        idempotency_key="native-finalization-prepared:" + uuid4().hex,
        artifact_type="material-learning-prepared",
    )
    if isinstance(selected_case, tuple) and selected_case[1] == "VISUAL":
        from eom_catalog_contracts.material_native_visual_preparation import (
            MaterialNativeVisualPreparedArtifact,
        )

        from tests.unit.test_material_native_visual_preparation import visual_profile

        catalog = prepared.sources[0].office_catalog
        assert catalog is not None
        visual = prepared.model_dump(mode="json")
        visual.update(
            schema_version="material-learning-prepared/3.0",
            base_prepared=pointer.model_dump(mode="json"),
            visual_profile=visual_profile(),
            catalog_supplements=[
                dict(
                    source_role="MAIN",
                    base_catalog=catalog.model_dump(mode="json"),
                    catalog=catalog.model_dump(mode="json"),
                )
            ],
            question_visual_scopes=[
                dict(
                    item_number=1,
                    question_document=binding.question.document.model_dump(mode="json"),
                    split_evidence=binding.question.split_evidence.model_dump(mode="json"),
                    source_catalog_sha256=catalog.sha256,
                    allowed_picture_use_ids=[],
                )
            ],
        )
        qualified = MaterialNativeVisualPreparedArtifact.model_validate(
            rehash(visual, "prepared_sha256")
        )
        pointer = publish_material_metadata(
            artifacts,
            settings,
            qualified,
            member_path="material/prepared.json",
            schema_ref="eom://schemas/material-learning/prepared/3.0",
            idempotency_key="native-reanalysis-visual-prepared:" + uuid4().hex,
            artifact_type="material-learning-prepared",
        )
    runs = tuple("materialrun_" + uuid4().hex for _ in range(3))
    prepares = tuple("materialtask_" + uuid4().hex for _ in range(3))
    discovers = tuple("materialtask_" + uuid4().hex for _ in range(2))
    work = build_material_preparation_input(
        intake,
        intake_pointer=intake_pointer,
        task_id=prepares[1],
        profile=MaterialPreparationProfile.model_validate(profile()),
    )
    preparation_pointer = publish_material_metadata(
        artifacts,
        settings,
        work,
        member_path="material/preparation-input.json",
        schema_ref="eom://schemas/material-learning/preparation-input/2.0",
        idempotency_key="native-finalization-input:" + uuid4().hex,
        artifact_type="material-learning-preparation-input",
    )
    now = datetime.now(UTC)
    with Session(creative_engine) as session, session.begin():
        for index, run_id in enumerate(runs):
            session.add(
                MaterialLearningRunRecord(
                    run_id=run_id,
                    material_revision_id=binding.material_revision_id,
                    attempt=index + 1,
                    predecessor_run_id=runs[index - 1] if index else None,
                    state="FAILED",
                    next_event_sequence=1,
                    created_by=resolved.operator_id,
                    prepared_artifact_id=pointer.artifact_id if index else None,
                    prepared_artifact_revision_id=pointer.artifact_revision_id if index else None,
                    prepared_sha256=pointer.sha256 if index else None,
                    error_code=failure_code if index == 2 else None,
                    created_at=now,
                    updated_at=now,
                )
            )
        session.flush()
        for index, task_id in enumerate(prepares):
            session.add(
                MaterialLearningTaskRecord(
                    task_id=task_id,
                    run_id=runs[index],
                    task_kind="PREPARE",
                    unit_key="source-preparation",
                    ordinal=1,
                    attempt=index + 1,
                    predecessor_task_id=prepares[index - 1] if index else None,
                    state="COMPLETED" if index else "FAILED",
                    execution_lane="MATERIAL_LEARNING",
                    input_artifact_id=preparation_pointer.artifact_id,
                    input_artifact_revision_id=preparation_pointer.artifact_revision_id,
                    input_sha256=preparation_pointer.sha256,
                    output_artifact_id=pointer.artifact_id if index else None,
                    output_artifact_revision_id=pointer.artifact_revision_id if index else None,
                    output_sha256=pointer.sha256 if index else None,
                    created_at=now,
                    updated_at=now,
                )
            )
        for index, task_id in enumerate(discovers):
            session.add(
                MaterialLearningTaskRecord(
                    task_id=task_id,
                    run_id=runs[index + 1],
                    task_kind="DISCOVER",
                    unit_key="native-discovery-main",
                    ordinal=2,
                    attempt=index + 1,
                    predecessor_task_id=discovers[0] if index else None,
                    state="COMPLETED",
                    execution_lane="MATERIAL_LEARNING",
                    workflow_id=resolved.selection.workflow_id if index == 0 else None,
                    input_artifact_id=resolved.work_pointer.artifact_id,
                    input_artifact_revision_id=resolved.work_pointer.artifact_revision_id,
                    input_sha256=resolved.work_pointer.sha256,
                    output_artifact_id=resolved.result_pointer.artifact_id,
                    output_artifact_revision_id=resolved.result_pointer.artifact_revision_id,
                    output_sha256=resolved.result_pointer.sha256,
                    created_at=now,
                    updated_at=now,
                )
            )
    value = plan()
    values = dict(value.by_unit)
    for key, original in values.items():
        role = "MAIN" if original.unit.kind == "QUESTION" else "SOLUTIONS"
        source = next(source for source in prepared.sources if source.source_role == role)
        values[key] = replace(original, source=source)
    admitted = replace(value, run_id=runs[2], by_unit=values)
    # The model owner has separate complete-result/rights tests. This explicit
    # admission port avoids Codex, reconstructed worker prose or fake Job state.
    monkeypatch.setattr(recovery_owner, "read_material_discovery_plan", lambda *a, **k: admitted)
    service = NativeMaterialDiscoveryFinalizationRecoveryService(
        creative_engine, settings=settings, source_commit="f" * 40
    )
    command = RecoverNativeMaterialDiscoveryFinalizationCommand(
        actor_id=resolved.operator_id,
        run_id=runs[2],
        expected_updated_at=now,
        expected_prepared_sha256=pointer.sha256,
        target_source_commit="f" * 40,
    )
    return SimpleNamespace(
        service=service,
        command=command,
        runs=runs,
        prepares=prepares,
        discovers=discovers,
        pointer=pointer,
        native=native,
        admitted=admitted,
        owner=recovery_owner,
        settings=settings,
    )


@pytest.mark.parametrize(
    "native_finalization_case",
    [
        "MATERIAL_NATIVE_DISCOVERY_REGION_INCOMPLETE",
        ("MATERIAL_NATIVE_DISCOVERY_REGION_INCOMPLETE", "VISUAL"),
    ],
    indirect=True,
)
def test_native_incomplete_reanalysis_validates_real_source_and_inherited_producer(
    creative_engine, native_finalization_case, monkeypatch
):
    """Real source, rights, checkpoint/history and Artifact IO; AI admission only is synthetic."""
    from eom_catalog_contracts.material_learning_intake import RetryMaterialLearningRunCommand
    from eom_catalog_service import material_discovery_reanalysis as reanalysis
    from eom_catalog_service.material_learning_models import (
        MaterialLearningRunRecord,
        MaterialLearningTaskRecord,
    )

    case = native_finalization_case
    values = {
        key: replace(
            planned,
            discovery_task_id=case.discovers[0],
            unit=planned.unit.model_copy(update={"continuation": "TO_NEXT"})
            if planned.unit.kind == "QUESTION"
            else planned.unit,
        )
        for key, planned in case.admitted.by_unit.items()
    }
    admitted = replace(case.admitted, by_unit=values)
    monkeypatch.setattr(reanalysis, "read_material_discovery_plan", lambda *a, **k: admitted)
    command = RetryMaterialLearningRunCommand(
        actor_id=case.command.actor_id,
        run_id=case.command.run_id,
        expected_updated_at=case.command.expected_updated_at,
    )
    service = reanalysis.NativeMaterialDiscoveryReanalysisService(creative_engine, case.settings)
    result = service.try_retry(command)
    assert (result.reused_tasks, result.retried_tasks, result.state) == (1, 1, "DISCOVERING")
    assert service.try_retry(command).replayed
    with Session(creative_engine) as session:
        rows = tuple(
            session.scalars(
                select(MaterialLearningTaskRecord)
                .where(MaterialLearningTaskRecord.run_id == result.run_id)
                .order_by(MaterialLearningTaskRecord.ordinal)
            )
        )
        assert rows[0].state == "COMPLETED" and rows[0].predecessor_task_id == case.prepares[2]
        assert rows[1].state == "PENDING" and rows[1].predecessor_task_id == case.discovers[1]
        assert rows[1].input_artifact_revision_id is rows[1].output_artifact_revision_id is None
        assert session.get(MaterialLearningRunRecord, command.run_id).state == "FAILED"


def test_native_finalization_concurrent_attempt_four_reuses_all_results_without_model(
    creative_engine, native_finalization_case
):
    from eom_catalog_service.material_discovery_finalization_recovery import (
        NativeMaterialDiscoveryFinalizationRecoveryService,
    )
    from eom_catalog_service.material_learning_models import (
        MaterialLearningRunRecord,
        MaterialLearningTaskRecord,
    )
    from eom_catalog_service.material_task_history import read_material_task_histories
    from eom_workflow_runner.models import WorkflowCommandRecord, WorkflowInstanceRecord

    case = native_finalization_case
    with Session(creative_engine) as session:
        before = tuple(
            session.scalar(select(func.count()).select_from(model))
            for model in (
                WorkflowInstanceRecord,
                WorkflowCommandRecord,
                ItemRevisionRecord,
            )
        )
    barrier = Barrier(2)

    def submit(_):
        service = NativeMaterialDiscoveryFinalizationRecoveryService(
            creative_engine, settings=case.settings, source_commit="f" * 40
        )
        barrier.wait(timeout=10)
        return service.recover(case.command)

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = tuple(executor.map(submit, range(2)))
    assert len({result.run_id for result in results}) == 1
    assert sum(not result.replayed for result in results) == 1
    result = results[0]
    assert result.prepared == case.pointer and result.reused_tasks == 2
    with Session(creative_engine) as session:
        original = session.get(MaterialLearningRunRecord, case.command.run_id)
        successor = session.get(MaterialLearningRunRecord, result.run_id)
        assert (
            original.state == "FAILED" and original.updated_at == case.command.expected_updated_at
        )
        assert original.error_code == "MATERIAL_NATIVE_DISCOVERY_NUMBER_INVALID"
        assert successor.predecessor_run_id == original.run_id and successor.attempt == 4
        tasks = tuple(
            session.scalars(
                select(MaterialLearningTaskRecord)
                .where(MaterialLearningTaskRecord.run_id == result.run_id)
                .order_by(MaterialLearningTaskRecord.ordinal)
            )
        )
        assert [(task.task_kind, task.state, task.attempt) for task in tasks] == [
            ("PREPARE", "COMPLETED", 4),
            ("DISCOVER", "COMPLETED", 3),
        ]
        assert all(task.workflow_id is None and task.item_revision_id is None for task in tasks)
        history = read_material_task_histories(session, tasks)
        assert len(history[tasks[0].task_id].tasks) == 4
        assert len(history[tasks[1].task_id].tasks) == 3
        assert history[tasks[1].task_id].result_task().workflow_id is not None
        assert before == tuple(
            session.scalar(select(func.count()).select_from(model))
            for model in (
                WorkflowInstanceRecord,
                WorkflowCommandRecord,
                ItemRevisionRecord,
            )
        )
    assert case.service.recover(case.command).replayed


@pytest.mark.parametrize("fault", ["stale", "source", "prepared", "actor", "pair"])
def test_native_finalization_invalid_commands_or_pair_never_create_a_run(
    creative_engine, native_finalization_case, monkeypatch, fault
):
    from datetime import timedelta

    from eom_catalog_service.material_learning_models import MaterialLearningRunRecord

    case, command = native_finalization_case, native_finalization_case.command
    changes = {
        "stale": dict(expected_updated_at=command.expected_updated_at - timedelta(seconds=1)),
        "source": dict(target_source_commit="e" * 40),
        "prepared": dict(expected_prepared_sha256="sha256:" + "0" * 64),
        "actor": dict(actor_id="operator_" + "0" * 32),
    }
    if fault == "pair":
        broken = replace(
            case.admitted,
            by_unit={
                key: value
                for key, value in case.admitted.by_unit.items()
                if value.unit.kind == "QUESTION"
            },
        )
        monkeypatch.setattr(case.owner, "read_material_discovery_plan", lambda *a, **k: broken)
    else:
        command = command.model_copy(update=changes[fault])
    with pytest.raises(ValueError):
        case.service.recover(command)
    with Session(creative_engine) as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(MaterialLearningRunRecord)
                .where(MaterialLearningRunRecord.predecessor_run_id == case.command.run_id)
            )
            == 0
        )


def test_native_finalization_transaction_interruption_has_no_partial_successor(
    creative_engine, native_finalization_case, monkeypatch
):
    from eom_catalog_service.material_learning_models import MaterialLearningRunRecord

    case = native_finalization_case

    def interrupt(*args, **kwargs):
        raise RuntimeError("synthetic finalization transaction interruption")

    with monkeypatch.context() as scoped:
        scoped.setattr(case.owner, "append_material_event", interrupt)
        with pytest.raises(RuntimeError, match="transaction interruption"):
            case.service.recover(case.command)
    with Session(creative_engine) as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(MaterialLearningRunRecord)
                .where(MaterialLearningRunRecord.predecessor_run_id == case.command.run_id)
            )
            == 0
        )
    result = case.service.recover(case.command)
    assert not result.replayed and case.service.recover(case.command).replayed


@pytest.fixture
def native_visual_correction_case(creative_engine, native_read_case, tmp_path, monkeypatch):
    """Real six-component Item/Artifact/rights/read/import; source-pixel qualification is a port.

    Like this module's original registration fixture, completed AI/source preparation
    is synthetic. No model or real Hancom parser runs. The reviewed-import owner,
    Registry CAS/unique keys, stored components, canonical bytes and Native read are real.
    """
    from types import SimpleNamespace
    from unittest.mock import Mock

    from eom_catalog_contracts import ImageBlock
    from eom_catalog_contracts.creative_source_visuals import CREATIVE_SOURCE_VISUAL_IMAGE_REF
    from eom_catalog_contracts.material_native_files import MaterialImportedNativeItemMetadata
    from eom_catalog_contracts.material_native_visual_correction import (
        MaterialNativeVisualCorrectionCommand,
        MaterialNativeVisualCorrectionPrepared,
        native_visual_correction_block_id,
    )
    from eom_catalog_contracts.material_native_visual_preparation import (
        MaterialNativeQuestionVisualScope,
    )
    from eom_catalog_service.material_learning_artifacts import pin_material_primary
    from eom_catalog_service.material_native_visual_correction import (
        MaterialNativeVisualCorrectionService,
        insert_native_visual_image,
    )
    from eom_identifiers import canonical_json_bytes
    from eom_protocol.artifact_members import ArtifactMemberPointer

    from tests.unit.test_material_native_visual_preparation_service import _real_catalog

    create, resolved, binding = native_read_case
    registration = create()
    original = registration.register_completed(
        task_id=resolved.task_id, operator_id=resolved.operator_id
    )
    catalog, payloads = _real_catalog(binding.question.original_source_sha256)
    files, metadata, hashes = {}, {}, {}
    for member, payload in payloads.items():
        path = tmp_path / ("correction-" + member.replace("/", "-"))
        path.write_bytes(payload)
        files[member] = path
        is_catalog = member == "picture-use-catalog.json"
        metadata[member] = dict(
            schema_ref="eom://schemas/image-provider/office-picture-use-catalog/1.0"
            if is_catalog
            else CREATIVE_SOURCE_VISUAL_IMAGE_REF,
            media_type="application/json" if is_catalog else "image/png",
        )
        hashes[member] = sha256_bytes(payload)
    published = registration.artifacts.commit_file_set(
        files=files,
        primary_file="picture-use-catalog.json",
        artifact_type="office-picture-use-catalog",
        idempotency_key="native-correction-pixels:" + uuid4().hex,
        request={"synthetic_source_qualification": True},
        result={"synthetic_source_qualification": True},
        file_metadata=metadata,
        expected_file_sha256=hashes,
    )

    def pointer(member):
        from eom_catalog_contracts.material_learning import MaterialArtifactMember

        return MaterialArtifactMember(
            artifact_id=published.artifact_id,
            artifact_revision_id=published.revision_id,
            member_path=member,
            **metadata[member],
            sha256=hashes[member],
            bytes=len(payloads[member]),
        )

    canonical = registration.registry.load_item_content(original.item_revision_id)
    with Session(creative_engine) as session:
        original_row = session.get(ItemRevisionRecord, original.item_revision_id)
        original_manifest_sha256 = original_row.manifest_sha256
        original_version = original_row.lock_version
    view = catalog.rendered_uses[0]
    catalog_pointer = pointer("picture-use-catalog.json")
    command = MaterialNativeVisualCorrectionCommand(
        actor_id=resolved.operator_id,
        base_item_revision_id=original.item_revision_id,
        base_item_manifest_sha256=original_manifest_sha256,
        expected_version=original_version,
        picture_use_id=catalog.picture_uses[0].use_id,
        insert_after_block_id=canonical.body[0].block_id,
    )
    image = ImageBlock(
        block_id=native_visual_correction_block_id(command.picture_use_id),
        purpose="stimulus",
        artifact=dict(
            artifact_id=published.artifact_id,
            artifact_revision_id=published.revision_id,
            artifact_member=view.member_path,
            sha256=view.sha256,
            media_type="image/png",
        ),
        alt_text="Synthetic source-only test picture",
        width_px=view.width_px,
        height_px=view.height_px,
    )
    corrected = insert_native_visual_image(
        canonical, image=image, insert_after_block_id=command.insert_after_block_id
    )
    service = MaterialNativeVisualCorrectionService(
        creative_engine,
        native_visuals=Mock(),
        settings=registration.settings,
    )
    with Session(creative_engine) as session:
        row = session.get(ItemRevisionRecord, original.item_revision_id)
        components = service._components(session, original.item_revision_id)
        indexed = {(c.component_type, c.ordinal): c for c in components}
        lineage = pin_material_primary(
            session,
            ArtifactMemberPointer(
                **{
                    key: getattr(indexed["SOURCE_REFERENCE", 0], key)
                    for key in (
                        "artifact_id",
                        "artifact_revision_id",
                        "schema_ref",
                        "media_type",
                        "sha256",
                    )
                },
                member_path=indexed["SOURCE_REFERENCE", 0].logical_name,
            ),
        ).pointer
        source_metadata = MaterialImportedNativeItemMetadata.model_validate(row.metadata_json)
    body = dict(
        schema_version="material-native-visual-correction-prepared/1.0",
        command=command.model_dump(mode="json"),
        item_id=original.item_id,
        material_id=source_metadata.material_id,
        material_revision_id=source_metadata.material_revision_id,
        source_task_id=resolved.task_id,
        source_lineage=lineage.model_dump(mode="json"),
        native_binding=source_metadata.native_binding.model_dump(mode="json"),
        catalog=catalog_pointer.model_dump(mode="json"),
        scope=MaterialNativeQuestionVisualScope(
            item_number=1,
            question_document=binding.question.document,
            split_evidence=binding.question.split_evidence,
            source_catalog_sha256=catalog_pointer.sha256,
            allowed_picture_use_ids=(command.picture_use_id,),
        ).model_dump(mode="json"),
        base_content=ArtifactMemberPointer(
            artifact_id=indexed["ITEM_CONTENT", 0].artifact_id,
            artifact_revision_id=indexed["ITEM_CONTENT", 0].artifact_revision_id,
            member_path=indexed["ITEM_CONTENT", 0].logical_name,
            schema_ref=indexed["ITEM_CONTENT", 0].schema_ref,
            media_type=indexed["ITEM_CONTENT", 0].media_type,
            sha256=indexed["ITEM_CONTENT", 0].sha256,
        ).model_dump(mode="json"),
        image=image.model_dump(mode="json"),
        corrected_content_sha256=content_sha256(corrected.model_dump(mode="json")),
        corrected_content_bytes=len(canonical_json_bytes(corrected.model_dump(mode="json"))),
        preserved_components_sha256=content_sha256(
            [c.model_dump(mode="json") for c in components if c.component_type != "ITEM_CONTENT"]
        ),
    )
    prepared = MaterialNativeVisualCorrectionPrepared.model_validate(
        {**body, "prepared_sha256": content_sha256(body)}
    )

    def factory():
        target = MaterialNativeVisualCorrectionService(
            creative_engine, native_visuals=Mock(), settings=registration.settings
        )

        def qualified(actual, *, require_current):
            assert actual == command
            return SimpleNamespace(prepared=prepared, content=corrected, metadata=source_metadata)

        monkeypatch.setattr(target, "_resolve", qualified)
        return target

    return SimpleNamespace(**locals())


def test_native_correction_concurrent_import_replay_preserves_five_components_and_history(
    creative_engine,
    native_visual_correction_case,
):
    from eom_catalog_service.models import ItemRecord

    value = native_visual_correction_case
    barrier = Barrier(2)

    def submit(_):
        service = value.factory()
        barrier.wait(timeout=10)
        return service.import_reviewed(value.command, prepared=value.prepared)

    with ThreadPoolExecutor(max_workers=2) as pool:
        first, second = pool.map(submit, range(2))
    assert first == second
    assert value.factory().import_reviewed(value.command, prepared=value.prepared) == first
    assert (
        value.factory().validate_applied(first, actor_id=value.resolved.operator_id)
        == value.prepared
    )
    with Session(creative_engine) as session:
        original = session.get(ItemRevisionRecord, value.original.item_revision_id)
        successor = session.get(ItemRevisionRecord, first.item_revision_id)
        assert original.revision_state == "SUPERSEDED" and successor.revision_state == "APPROVED"
        assert original.superseded_by_revision_id == first.item_revision_id
        assert original.metadata_json == successor.metadata_json
        assert original.content_pack_release_id == successor.content_pack_release_id
        assert (
            session.get(ItemRecord, successor.item_id).current_revision_id == first.item_revision_id
        )
        assert (
            session.scalar(
                select(func.count())
                .select_from(ItemRevisionRecord)
                .where(ItemRevisionRecord.item_id == successor.item_id)
            )
            == 2
        )
        after = value.service._components(session, first.item_revision_id)
        assert tuple(c for c in after if c.component_type != "ITEM_CONTENT") == tuple(
            c for c in value.components if c.component_type != "ITEM_CONTENT"
        )
    assert (
        value.registration.registry.load_item_content(value.original.item_revision_id)
        == value.canonical
    )
    actual = value.registration.registry.load_item_content(first.item_revision_id).model_dump(
        mode="json"
    )
    actual["body"].pop(1)
    assert actual == value.canonical.model_dump(mode="json")


def test_native_correction_real_fresh_base_uses_new_content_despite_preserved_original_lineage(
    creative_engine,
    native_visual_correction_case,
    controls,
):
    from eom_catalog_contracts import CreateKnowledgeAnalysisCommand, KnowledgeAnalysisRequestV2
    from eom_catalog_service.knowledge_analysis_service import KnowledgeAnalysisApplicationService
    from eom_orchestrator.knowledge_analysis_models import KnowledgeAnalysisRunRecord

    from tests.integration.test_knowledge_analysis_service import POLICY_ID

    value = native_visual_correction_case
    service = value.factory()
    receipt = service.import_reviewed(value.command, prepared=value.prepared)
    service.validate_applied(receipt, actor_id=value.resolved.operator_id)
    application = KnowledgeAnalysisApplicationService(creative_engine, service.settings)
    command = CreateKnowledgeAnalysisCommand(
        source=dict(
            source_kind="APPROVED_ITEM_REVISION",
            source_class="APPROVED_ITEM",
            item_revision_id=receipt.item_revision_id,
        ),
        # The existing released baseline exercises the identical approved-Item
        # source resolver without re-releasing the separate Material controls.
        preset_key="knowledge-analysis",
        general_knowledge_mode="DISABLED",
        risk_policy_revision_id=POLICY_ID,
        requested_by=value.resolved.operator_id,
        idempotency_key="native-correction-real-base:" + uuid4().hex,
    )
    first = application.create_with_pinned_preset(
        command,
        preset_id=controls[2].preset_id,
        preset_revision_id=controls[2].preset_revision_id,
    )
    assert (
        application.create_with_pinned_preset(
            command,
            preset_id=controls[2].preset_id,
            preset_revision_id=controls[2].preset_revision_id,
        )
        == first
    )
    with Session(creative_engine) as session:
        row = session.get(KnowledgeAnalysisRunRecord, first.analysis_run_id)
        request = KnowledgeAnalysisRequestV2.model_validate(row.canonical_request)
        assert (
            request.source.item_revision_id
            == receipt.item_revision_id
            != value.original.item_revision_id
        )
        assert (
            request.source.artifact_member.sha256
            == receipt.content.sha256
            != value.prepared.base_content.sha256
        )
        assert row.predecessor_analysis_run_id is None
        assert (
            session.scalar(
                select(func.count())
                .select_from(KnowledgeAnalysisRunRecord)
                .where(KnowledgeAnalysisRunRecord.idempotency_key == command.idempotency_key)
            )
            == 1
        )
