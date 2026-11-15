"""The existing source owner authorizes exact native visual work and unchanged base pages."""

from types import SimpleNamespace

import pytest
from eom_catalog_contracts.material_learning import MaterialExtractionWork, MaterialLearningRights
from eom_catalog_contracts.material_native_intake import MaterialNativeExamBundle
from eom_catalog_contracts.material_native_visual_work import (
    material_native_question_visual_scope,
    material_visual_work_sources,
)
from eom_catalog_service import material_learning_authorization as owner
from eom_catalog_service import material_native_visual_context as context_owner
from eom_catalog_service.material_learning_models import (
    LearningMaterialRecord,
    LearningMaterialRevisionRecord,
    MaterialLearningRunRecord,
    MaterialLearningTaskRecord,
)
from eom_identifiers import canonical_json_bytes, content_sha256
from eom_orchestrator.models import ArtifactRevisionRecord

from tests.unit.test_material_learning_contracts import rehash
from tests.unit.test_material_native_intake import native_exam_bundle
from tests.unit.test_material_native_visual_preparation import base_prepared
from tests.unit.test_material_native_visual_prepared_read import read_case
from tests.unit.test_material_native_visual_work import extracted_work


def authorization_case(monkeypatch, version=3):
    _, prepared, intake, work, _ = extracted_work(monkeypatch, version)
    # Historical fixture factories intentionally use independent upload examples;
    # this owner test binds the actual source receipt, rather than bypassing that check.
    sources = tuple(
        source.model_copy(
            update={
                "original": selection.source_upload.original,
                "original_filename": selection.source_upload.original_filename,
            }
        )
        for source, selection in zip(prepared.sources, intake.sources, strict=True)
    )
    prepared_body = prepared.model_dump(mode="json")
    prepared_body["sources"] = [source.model_dump(mode="json") for source in sources]
    if version == 3:
        base_body = base_prepared().model_dump(mode="json")
        base_body["sources"] = prepared_body["sources"]
        base_body = rehash(base_body, "prepared_sha256")
        prepared_body["base_prepared"].update(
            sha256=content_sha256(base_body), bytes=len(canonical_json_bytes(base_body))
        )
    prepared = type(prepared).model_validate(rehash(prepared_body, "prepared_sha256"))
    work_body = work.model_dump(mode="json")
    work_body["sources"] = [
        source.model_dump(mode="json") for source in material_visual_work_sources(prepared)
    ]
    work = MaterialExtractionWork.model_validate(rehash(work_body))
    actor = intake.requested_by
    authorizer = object.__new__(owner.CatalogMaterialLearningSourceAuthorizer)
    authorizer.artifacts = object()
    page_reads, source_reads, permission_checks = [], [], []
    original_work = work
    input_revision_id = "rev_" + "8" * 32
    run_id = "materialrun_" + "8" * 32
    state = dict(prepared=prepared if version == 3 else None, work=original_work, revoked_at=None)
    records = {
        (MaterialLearningTaskRecord, work.task_id): SimpleNamespace(
            run_id=run_id,
            state="READY",
            task_kind="QUESTION",
            input_artifact_id="artifact_" + "8" * 32,
            input_artifact_revision_id=input_revision_id,
            input_sha256=content_sha256(work.model_dump(mode="json")),
        ),
        (MaterialLearningRunRecord, run_id): SimpleNamespace(
            material_revision_id=work.material_revision_id, created_by=actor, state="PROCESSING"
        ),
        (LearningMaterialRevisionRecord, work.material_revision_id): SimpleNamespace(
            material_id=work.material_id,
            material_revision_id=work.material_revision_id,
            created_by=actor,
            manifest_artifact_id=prepared.intake_manifest.artifact_id,
            manifest_artifact_revision_id=prepared.intake_manifest.artifact_revision_id,
            manifest_sha256=prepared.intake_manifest.sha256,
        ),
        (LearningMaterialRecord, work.material_id): SimpleNamespace(
            lifecycle_state="ACTIVE", material_id=work.material_id, created_by=actor
        ),
        (ArtifactRevisionRecord, input_revision_id): SimpleNamespace(
            content_bytes=len(canonical_json_bytes(work.model_dump(mode="json")))
        ),
    }

    class Session:
        def get(self, model, identifier, **_kwargs):
            return records.get((model, identifier))

    def authorize(_session, operator_id):
        permission_checks.append(operator_id)
        if operator_id != actor or state["revoked_at"] == len(permission_checks):
            raise ValueError("ACTUAL_OPERATOR_PERMISSION_REVOKED")

    def read_intake(_artifacts, pointer, *, authorize):
        authorize()
        assert pointer == prepared.intake_manifest
        authorize()
        return intake

    def read_visual(_session, _artifacts, _run, *, authorize):
        authorize()
        authorize()
        return state["prepared"]

    bundle = MaterialNativeExamBundle.model_validate(native_exam_bundle())

    def read_bundle(_artifacts, pointer, *, sources, operator_id, authorize):
        authorize()
        assert (
            pointer == intake.native_bundle and sources == intake.sources and operator_id == actor
        )
        authorize()
        return bundle

    def source_resolve(receipt, *, operator_id):
        assert operator_id == actor
        source_reads.append(receipt)

    authorizer.sources = SimpleNamespace(resolve=source_resolve)
    documents = {}
    registrations = {}
    for source in prepared.sources:
        registrations[source.document_revision_id] = SimpleNamespace(
            revision_manifest=SimpleNamespace(
                sha256=source.document_manifest_sha256,
                schema_ref="eom://schemas/material-learning/document-revision/1.0",
                member_path="document/document-revision.json",
            )
        )
        documents[source.document_revision_id] = SimpleNamespace(
            material_id=work.material_id,
            material_revision_id=work.material_revision_id,
            source_role=source.source_role,
            document_id=source.document_id,
            original=source.original,
            source=source.pdf,
            analysis_bundle_manifest=source.page_bundle,
            rights_attestation=work.rights_attestation,
            source_page_count=source.page_count,
        )
    document_calls = []

    def inspect_document(revision_id):
        document_calls.append(revision_id)
        return registrations[revision_id]

    authorizer.documents = SimpleNamespace(inspect_material_revision=inspect_document)

    def read_metadata(_artifacts, pointer, model, **_kwargs):
        if model is MaterialLearningRights:
            return SimpleNamespace(
                material_id=work.material_id,
                material_revision_id=work.material_revision_id,
                attested_by=actor,
                source_hashes=tuple(
                    entry.source_upload.original.sha256 for entry in intake.sources
                ),
            )
        if model is MaterialExtractionWork:
            assert pointer.sha256 == content_sha256(original_work.model_dump(mode="json"))
            assert pointer.bytes == len(canonical_json_bytes(original_work.model_dump(mode="json")))
            if content_sha256(state["work"].model_dump(mode="json")) != pointer.sha256:
                raise ValueError("TEST_CANONICAL_WORK_HASH_MISMATCH")
            return state["work"]
        return documents[document_calls[-1]]

    def read_pages(_artifacts, source, physical_pages):
        base = next(value for value in prepared.sources if value.source_role == source.source_role)
        assert source == base
        page_reads.append((source, physical_pages))
        pages = []
        for page in original_work.pages:
            if page.source_role != source.source_role or page.physical_page not in physical_pages:
                continue

            def input_page(*, input_index, source_role, actual=page):
                return actual.model_copy(
                    update={"input_index": input_index, "source_role": source_role}
                )

            pages.append(SimpleNamespace(page=page, input_page=input_page))
        return SimpleNamespace(pages=tuple(pages))

    monkeypatch.setattr(owner, "authorize_material_learning", authorize)
    monkeypatch.setattr(
        owner, "material_intake_pointer", lambda *args, **kwargs: prepared.intake_manifest
    )
    monkeypatch.setattr(owner, "read_material_intake", read_intake)
    monkeypatch.setattr(owner, "read_native_visual_prepared_for_run", read_visual)
    monkeypatch.setattr(owner, "read_material_native_bundle", read_bundle)
    monkeypatch.setattr(owner, "read_material_metadata", read_metadata)
    monkeypatch.setattr(owner, "read_material_source_pages", read_pages)
    return authorizer, Session(), actor, work, state, page_reads, source_reads, permission_checks


@pytest.mark.parametrize("version", [1, 2, 3])
def test_actual_source_owner_accepts_exact_instructions_and_reads_only_base_pages(
    monkeypatch, version
):
    authorizer, session, actor, work, _, pages, sources, permissions = authorization_case(
        monkeypatch, version
    )
    assert authorizer.reauthorize(session, operator_id=actor, work=work) == work
    assert len(pages) == 2 and len(sources) == 2
    assert all(operator == actor for operator in permissions)


def test_future_input_derives_exact_scope_from_authorized_prepared_source(monkeypatch):
    authorizer, session, actor, work, state, pages, sources, permissions = authorization_case(
        monkeypatch, 3
    )
    actual = authorizer.authorize_future_input(session, operator_id=actor, work=work)
    assert actual.work_input == work
    assert actual.native_visual_scope == material_native_question_visual_scope(
        state["prepared"], printed_label=work.question.printed_label
    )
    assert actual.native_visual_scope is not None
    assert len(pages) == len(sources) == 2
    assert all(operator == actor for operator in permissions)


def test_future_native_input_requires_prepared_scope_without_reinterpreting_legacy(
    monkeypatch,
):
    authorizer, session, actor, work, _, _, _, _ = authorization_case(monkeypatch, 2)
    assert authorizer.reauthorize(session, operator_id=actor, work=work) == work
    with pytest.raises(ValueError, match="MATERIAL_NATIVE_VISUAL_PREPARATION_REQUIRED"):
        authorizer.authorize_future_input(session, operator_id=actor, work=work)


def test_future_generic_input_keeps_explicit_null_native_scope(monkeypatch):
    authorizer, session, actor, work, _, _, _, _ = authorization_case(monkeypatch, 1)
    actual = authorizer.authorize_future_input(session, operator_id=actor, work=work)
    assert actual.work_input == work and actual.native_visual_scope is None


@pytest.mark.parametrize(
    "case",
    [
        "suffix_missing",
        "suffix_changed",
        "old_catalog",
        "wrong_new_catalog",
        "page_changed",
        "stored_input_changed",
    ],
)
def test_source_owner_rejects_unpinned_hint_catalog_or_work_bytes(monkeypatch, case):
    authorizer, session, actor, work, state, _, _, _ = authorization_case(monkeypatch)
    body = work.model_dump(mode="json")
    if case == "suffix_missing":
        body["additional_instructions"] = body["additional_instructions"].split("\n\n", 1)[0]
    elif case == "suffix_changed":
        body["additional_instructions"] += "different scope"
    elif case == "old_catalog":
        body["sources"][0]["office_catalog"] = (
            state["prepared"].sources[0].office_catalog.model_dump(mode="json")
        )
    elif case == "wrong_new_catalog":
        body["sources"][0]["office_catalog"]["sha256"] = "sha256:" + "0" * 64
    elif case == "page_changed":
        body["pages"][0]["image"]["sha256"] = "sha256:" + "0" * 64
    else:
        stored = work.model_dump(mode="json")
        stored["pages"][0]["image"]["sha256"] = "sha256:" + "0" * 64
        state["work"] = MaterialExtractionWork.model_validate(rehash(stored))
    changed = MaterialExtractionWork.model_validate(rehash(body))
    with pytest.raises(
        ValueError,
        match=r"SOURCE_INPUT_MISMATCH|WORK_SOURCE_MISMATCH|INPUT_CHANGED|WORK_HASH_MISMATCH",
    ):
        authorizer.reauthorize(session, operator_id=actor, work=changed)


@pytest.mark.parametrize(
    "case", ["native_bundle", "intake_pointer", "native_question", "native_split"]
)
def test_actual_source_owner_rechecks_checkpoint_and_native_file_membership(monkeypatch, case):
    authorizer, session, actor, work, state, pages, _, _ = authorization_case(monkeypatch)
    body = state["prepared"].model_dump(mode="json")
    if case == "native_bundle":
        body["native_bundle"]["artifact_revision_id"] = "rev_" + "0" * 32
    elif case == "intake_pointer":
        body["intake_manifest"]["artifact_revision_id"] = "rev_" + "0" * 32
    else:
        field = "question_document" if case == "native_question" else "split_evidence"
        body["question_visual_scopes"][0][field]["sha256"] = "sha256:" + "0" * 64
    state["prepared"] = type(state["prepared"]).model_validate(rehash(body, "prepared_sha256"))
    with pytest.raises(
        ValueError,
        match=r"CHECKPOINT_BUNDLE_MISMATCH|CHECKPOINT_CHAIN_MISMATCH|BUNDLE_SCOPE_MISMATCH",
    ):
        authorizer.reauthorize(session, operator_id=actor, work=work)
    assert pages == []


def test_actual_operator_and_late_revocation_are_not_replaced_by_prepared_authority(monkeypatch):
    authorizer, session, actor, work, state, pages, _, permissions = authorization_case(monkeypatch)
    with pytest.raises(ValueError, match="PERMISSION_REVOKED"):
        authorizer.reauthorize(session, operator_id="operator_" + "0" * 32, work=work)
    assert not pages
    permissions.clear()
    state["revoked_at"] = 8
    with pytest.raises(ValueError, match="PERMISSION_REVOKED"):
        authorizer.reauthorize(session, operator_id=actor, work=work)
    assert len(pages) == 2 and len(permissions) == 8


def test_context_uses_only_the_run_exact_pointer_and_real_prepared_base_reader(monkeypatch):
    pointer, session, reader, events, _, _ = read_case()
    run = SimpleNamespace(
        prepared_artifact_id=pointer.artifact_id,
        prepared_artifact_revision_id=pointer.artifact_revision_id,
        prepared_sha256=pointer.sha256,
        material_revision_id=base_prepared().material_revision_id,
    )
    result = context_owner.read_native_visual_prepared_for_run(
        session, reader, run, authorize=lambda: events.append("auth")
    )
    assert result.base_prepared.schema_ref.endswith("prepared/2.0")
    assert [event for event in events if isinstance(event, tuple)] == [
        ("read", pointer.artifact_revision_id),
        ("read", result.base_prepared.artifact_revision_id),
    ]
    assert events.count("auth") == 6


@pytest.mark.parametrize("case", ["partial_pin", "foreign_revision", "missing_revision"])
def test_context_does_not_infer_latest_or_accept_a_foreign_material_revision(monkeypatch, case):
    pointer, session, reader, events, _, _ = read_case()
    run = SimpleNamespace(
        prepared_artifact_id=pointer.artifact_id,
        prepared_artifact_revision_id=pointer.artifact_revision_id,
        prepared_sha256=pointer.sha256,
        material_revision_id=base_prepared().material_revision_id,
    )
    if case == "partial_pin":
        run.prepared_sha256 = None
    elif case == "foreign_revision":
        run.material_revision_id = "materialrev_" + "0" * 32
    else:
        run.prepared_artifact_revision_id = "rev_" + "0" * 32
    with pytest.raises(
        ValueError, match=r"CHECKPOINT_MISSING|CHECKPOINT_POINTER_INVALID|SOURCE_MISMATCH"
    ):
        context_owner.read_native_visual_prepared_for_run(
            session, reader, run, authorize=lambda: None
        )
    assert len(events) == (2 if case == "foreign_revision" else 0)
