"""Existing preparation owner dispatches exact native successors without relaxing V1."""

from __future__ import annotations

from contextlib import nullcontext
from copy import deepcopy
from types import SimpleNamespace
from typing import Any

import pytest
from eom_catalog_contracts.material_learning import MaterialArtifactMember
from eom_catalog_contracts.material_learning_intake import MaterialLearningIntakeManifest
from eom_catalog_contracts.material_learning_preparation import (
    MaterialPreparationProfile,
    MaterialPreparedArtifact,
)
from eom_catalog_contracts.material_native_intake import (
    MATERIAL_NATIVE_INTAKE_REF,
    MATERIAL_NATIVE_PREPARED_REF,
    MaterialNativeExamBundle,
    MaterialNativeLearningIntakeManifest,
    MaterialNativePreparationInput,
    MaterialNativePreparedArtifact,
    MaterialPreparation,
    MaterialPrepared,
)
from eom_catalog_service import material_learning_coordinator as coordinator_owner
from eom_catalog_service import material_learning_pages as pages_owner
from eom_catalog_service.material_learning_coordinator import (
    MaterialLearningCoordinator,
    build_material_preparation_input,
)
from eom_catalog_service.material_learning_pages import MaterialPagePreparationService
from eom_identifiers import content_sha256

from tests.unit.test_material_learning_contracts import rehash
from tests.unit.test_material_learning_intake import ACTOR
from tests.unit.test_material_learning_preparation import profile
from tests.unit.test_material_native_intake import (
    native_exam_bundle,
    native_intake,
    native_prepared,
)


def _intake(native: bool) -> Any:
    value = native_intake()
    if native:
        return MaterialNativeLearningIntakeManifest.model_validate(value)
    value.pop("native_bundle")
    value["schema_version"] = "material-learning-intake/1.0"
    return MaterialLearningIntakeManifest.model_validate(value)


def _intake_pointer(native: bool) -> MaterialArtifactMember:
    value = native_prepared()["intake_manifest"]
    value["schema_ref"] = (
        MATERIAL_NATIVE_INTAKE_REF if native else "eom://schemas/material-learning/intake/1.0"
    )
    return MaterialArtifactMember.model_validate(value)


def _work(native: bool) -> MaterialPreparation:
    return build_material_preparation_input(
        _intake(native),
        intake_pointer=_intake_pointer(native),
        task_id="materialtask_" + "7" * 32,
        profile=MaterialPreparationProfile.model_validate(profile()),
    )


@pytest.mark.parametrize("native", [False, True])
def test_input_creation_pins_exact_committed_family_and_keeps_old_bytes(native: bool) -> None:
    work = _work(native)
    original = dict(
        schema_version="material-learning-preparation-input/1.0",
        task_id="materialtask_" + "7" * 32,
        material_id=_intake(native).material_id,
        material_revision_id=_intake(native).material_revision_id,
        intake_manifest=_intake_pointer(native).model_dump(mode="json"),
        profile=profile(),
    )
    if native:
        assert isinstance(work, MaterialNativePreparationInput)
        assert work.native_bundle == _intake(native).native_bundle
        original.update(
            schema_version="material-learning-preparation-input/2.0",
            native_bundle=work.native_bundle.model_dump(mode="json"),
        )
    else:
        assert "native_bundle" not in work.model_dump()
    assert work.model_dump(mode="json") == {**original, "input_sha256": content_sha256(original)}


def _page_service(
    monkeypatch: pytest.MonkeyPatch, native: bool
) -> tuple[Any, list[Any], list[Any]]:
    service = object.__new__(MaterialPagePreparationService)
    service.source_commit = profile()["source_commit"]
    service.extractor = SimpleNamespace(**profile()["extractor"])
    service.artifacts = object()
    service.publisher = object()
    intake = _intake(native)
    authorization: list[Any] = []
    published: list[Any] = []

    def read_intake(_artifacts: Any, pointer: Any, *, authorize: Any) -> Any:
        authorize()
        assert pointer == _intake_pointer(native)
        authorize()
        return intake

    monkeypatch.setattr(pages_owner, "read_material_intake", read_intake)
    monkeypatch.setattr(pages_owner, "find_material_publication", lambda *args, **kwargs: None)
    bundle = MaterialNativeExamBundle.model_validate(native_exam_bundle())
    monkeypatch.setattr(pages_owner, "read_material_metadata", lambda *args, **kwargs: bundle)
    sources = MaterialNativePreparedArtifact.model_validate(native_prepared()).sources
    service._prepare_source = lambda _work, _intake, selection, **kw: next(
        s for s in sources if s.source_role == selection.source_role
    )

    def publish(prepared: Any, **kwargs: Any) -> MaterialArtifactMember:
        published.append((prepared, kwargs))
        pointer = _intake_pointer(native).model_dump(mode="json")
        pointer.update(member_path="material/prepared.json", schema_ref=kwargs["schema_ref"])
        return MaterialArtifactMember.model_validate(pointer)

    service._publish_metadata = publish
    return service, authorization, published


@pytest.mark.parametrize("native", [False, True])
def test_existing_page_owner_publishes_exact_prepared_family(
    monkeypatch: pytest.MonkeyPatch, native: bool
) -> None:
    service, authorizations, published = _page_service(monkeypatch, native)
    outcome = service.prepare(
        _work(native), operator_id=ACTOR, authorize=lambda: authorizations.append(True)
    )
    assert len(published) == 1
    assert len(authorizations) >= 4
    assert outcome.prepared.material_id == _intake(native).material_id
    if native:
        assert isinstance(outcome.prepared, MaterialNativePreparedArtifact)
        assert outcome.prepared.native_bundle == _intake(native).native_bundle
        assert outcome.pointer.schema_ref == MATERIAL_NATIVE_PREPARED_REF
    else:
        assert isinstance(outcome.prepared, MaterialPreparedArtifact)
        assert outcome.pointer.schema_ref == "eom://schemas/material-learning/prepared/1.0"
        assert "native_bundle" not in outcome.prepared.model_dump()


def test_preparation_cannot_switch_native_bundle_even_with_valid_rehashed_work(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, _, published = _page_service(monkeypatch, True)
    data = _work(True).model_dump(mode="json")
    data["native_bundle"]["artifact_revision_id"] = "rev_" + "f" * 32
    work = MaterialNativePreparationInput.model_validate(rehash(data))
    with pytest.raises(ValueError, match="NATIVE_CHECKPOINT_BUNDLE_MISMATCH"):
        service.prepare(work, operator_id=ACTOR, authorize=lambda: None)
    assert not published


def test_v2_intake_is_never_reparsed_as_v1_on_checkpoint_conflict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, _, published = _page_service(monkeypatch, True)
    monkeypatch.setattr(pages_owner, "read_material_intake", lambda *a, **kw: _intake(True))
    with pytest.raises(ValueError, match="CHECKPOINT_CHAIN_MISMATCH"):
        service.prepare(_work(False), operator_id=ACTOR, authorize=lambda: None)
    assert not published


@pytest.mark.parametrize("mismatch", ["family", "bundle"])
def test_prepared_replay_requires_same_native_chain_before_source_staging(
    monkeypatch: pytest.MonkeyPatch, mismatch: str
) -> None:
    service, _, published = _page_service(monkeypatch, True)
    service.sessions = lambda: nullcontext(object())
    pointer = _intake_pointer(True)
    monkeypatch.setattr(pages_owner, "find_material_publication", lambda *args, **kwargs: pointer)
    monkeypatch.setattr(
        pages_owner,
        "pin_material_primary",
        lambda *args, **kwargs: SimpleNamespace(pointer=pointer),
    )
    data = deepcopy(native_prepared())
    replay: MaterialPrepared
    if mismatch == "family":
        data.pop("native_bundle")
        data["schema_version"] = "material-learning-prepared/1.0"
        data["intake_manifest"] = _intake_pointer(False).model_dump(mode="json")
        replay = MaterialPreparedArtifact.model_validate(rehash(data, "prepared_sha256"))
    else:
        data["native_bundle"]["artifact_revision_id"] = "rev_" + "f" * 32
        replay = MaterialNativePreparedArtifact.model_validate(rehash(data, "prepared_sha256"))
    monkeypatch.setattr(pages_owner, "read_material_prepared", lambda *args, **kwargs: replay)
    with pytest.raises(ValueError):
        service.prepare(_work(True), operator_id=ACTOR, authorize=lambda: None)
    assert not published


@pytest.mark.parametrize("native", [False, True])
def test_coordinator_context_reads_one_committed_small_prepared_manifest(
    monkeypatch: pytest.MonkeyPatch, native: bool
) -> None:
    intake = _intake(native)
    data = native_prepared()
    if not native:
        data.pop("native_bundle")
        data["schema_version"] = "material-learning-prepared/1.0"
        data["intake_manifest"] = _intake_pointer(False).model_dump(mode="json")
        prepared: MaterialPrepared = MaterialPreparedArtifact.model_validate(
            rehash(data, "prepared_sha256")
        )
    else:
        prepared = MaterialNativePreparedArtifact.model_validate(data)
    pointer_data = _intake_pointer(native).model_dump(mode="json")
    pointer_data.update(
        member_path="material/prepared.json",
        schema_ref=(
            MATERIAL_NATIVE_PREPARED_REF
            if native
            else "eom://schemas/material-learning/prepared/1.0"
        ),
    )
    pointer = MaterialArtifactMember.model_validate(pointer_data)
    run = SimpleNamespace(
        run_id="materialrun_" + "1" * 32,
        prepared_artifact_id=pointer.artifact_id,
        prepared_artifact_revision_id=pointer.artifact_revision_id,
        prepared_sha256=pointer.sha256,
    )
    service = object.__new__(MaterialLearningCoordinator)
    service.sessions = lambda: nullcontext(SimpleNamespace(get=lambda *args: run))
    service.artifacts = object()
    service.intake = lambda _claim: (intake, _intake_pointer(native))
    authorized: list[Any] = []
    service.authorize = lambda _claim: authorized.append(True)
    calls: list[Any] = []

    def read_prepared(_artifacts: Any, actual: Any, *, authorize: Any) -> MaterialPrepared:
        authorize()
        calls.append(actual)
        authorize()
        return prepared

    monkeypatch.setattr(coordinator_owner, "material_prepared_pointer", lambda *args, **kw: pointer)
    monkeypatch.setattr(coordinator_owner, "read_material_prepared", read_prepared)
    context = service.context(run)
    assert context.prepared == prepared and context.intake == intake
    assert calls == [pointer] and len(authorized) == 2
