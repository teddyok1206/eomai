"""Uncached originals stay in the supported Catalog/converter boundary."""

from contextlib import nullcontext
from types import SimpleNamespace as NS
from unittest.mock import Mock

import pytest
from eom_catalog_contracts.creative_learning_cohort import CreativeLearningCohort
from eom_catalog_contracts.creative_preview_preparation import CreativePreviewPreparationResult
from eom_catalog_contracts.external_item_media import ExternalItemDocumentMediaQuery
from eom_catalog_service import creative_preview_preparation as adapter
from eom_catalog_service.creative_cohort_preparation import CreativeCohortPreparationService
from eom_catalog_service.external_item_preview_projection import ExternalItemPreviewUnavailable

from tests.unit.test_creative_learning_cohort import cohort_value


def query():
    return ExternalItemDocumentMediaQuery(
        source_id="extitem_" + "1" * 32,
        source_revision_id="extitemrev_" + "2" * 32,
        edition=3,
    )


def test_untrusted_process_cannot_launch_catalog_preparation(monkeypatch):
    monkeypatch.setattr(adapter.os, "geteuid", lambda: 123)
    run = Mock()
    monkeypatch.setattr(adapter.subprocess, "run", run)
    with pytest.raises(ValueError, match="COORDINATOR_INVALID"):
        adapter.prepare_creative_preview(query())
    run.assert_not_called()


@pytest.mark.parametrize("returncode,valid", [(1, False), (0, False), (0, True)])
def test_preparation_uses_fixed_owner_installed_code_and_typed_source(
    monkeypatch, returncode, valid
):
    stdout = (
        CreativePreviewPreparationResult(
            source_id=query().source_id,
            source_revision_id=query().source_revision_id,
            edition=3,
            status="READY",
        )
        .model_dump_json()
        .encode()
        if valid
        else b"private output"
    )
    monkeypatch.setattr(adapter.os, "geteuid", lambda: 0)
    # resolve() still uses the real path; only the installed ownership gate is
    # substituted so this unit test never needs root or an actual converter.
    with monkeypatch.context() as patch:
        patch.setattr(
            adapter.Path, "stat", lambda *_args, **_kwargs: NS(st_uid=0, st_gid=0, st_mode=0o555)
        )
        run = Mock(return_value=NS(returncode=returncode, stdout=stdout, stderr=b""))
        patch.setattr(adapter.subprocess, "run", run)
        if returncode or not valid:
            with pytest.raises(ValueError, match="PREPARATION_FAILED"):
                adapter.prepare_creative_preview(query())
        else:
            adapter.prepare_creative_preview(query())
        args = run.call_args.args[0]
    assert "--uid=eom-catalog-manager" in args and "--uid=root" not in args
    assert "NoNewPrivileges=true" in args and "ProtectHome=true" in args
    assert "--" in args and "-I" in args and "-B" in args
    assert '"source_revision_id":"' + query().source_revision_id + '"' in args[-1]
    assert run.call_args.kwargs["timeout"] == 345


@pytest.mark.parametrize("foreign", [False, True])
def test_only_same_source_typed_converter_failure_is_returned_as_deferred(monkeypatch, foreign):
    monkeypatch.setattr(adapter.os, "geteuid", lambda: 0)
    prepared = CreativePreviewPreparationResult(
        source_id=query().source_id,
        source_revision_id="extitemrev_" + "f" * 32 if foreign else query().source_revision_id,
        edition=3,
        status="DEFERRED",
        error_code="OFFICE_DOCUMENT_CONVERSION_OUTPUT_MISSING",
    )
    with monkeypatch.context() as patch:
        patch.setattr(
            adapter.Path, "stat", lambda *_args, **_kwargs: NS(st_uid=0, st_gid=0, st_mode=0o555)
        )
        patch.setattr(
            adapter.subprocess,
            "run",
            Mock(
                return_value=NS(
                    returncode=0,
                    stdout=prepared.model_dump_json().encode(),
                    stderr=b"",
                )
            ),
        )
        if foreign:
            with pytest.raises(ValueError, match="IDENTITY_MISMATCH"):
                adapter.prepare_creative_preview(query())
        else:
            with pytest.raises(adapter.CreativeSourcePreviewDeferred) as error:
                adapter.prepare_creative_preview(query())
            assert error.value.result == prepared


@pytest.mark.parametrize("cached", [False, True])
def test_preview_is_prepared_only_after_owner_and_exact_source_check(monkeypatch, cached):
    cohort = CreativeLearningCohort.model_validate(cohort_value())
    target = cohort.targets[0]
    service = object.__new__(CreativeCohortPreparationService)
    service.cohort = cohort
    service.sessions = lambda: nullcontext(object())
    member = NS(stream=Mock())
    service.preview = NS(open=Mock(return_value=NS(member=member)))
    if not cached:
        service.preview.open.side_effect = ExternalItemPreviewUnavailable(
            "EXTERNAL_ITEM_PREVIEW_NOT_READY"
        )
    authorize, prepare = Mock(), Mock()
    monkeypatch.setattr(
        "eom_catalog_service.external_creative_learning_source.authorize_external_creative_learning_claim",
        authorize,
    )
    monkeypatch.setattr(
        "eom_catalog_service.external_creative_learning_targets.get_external_creative_learning_target",
        lambda *_args, **_kwargs: target,
    )
    monkeypatch.setattr(
        "eom_catalog_service.creative_cohort_preparation.prepare_creative_preview", prepare
    )
    service._ensure_preview(target)
    authorize.assert_called_once()
    assert prepare.call_count == (0 if cached else 1)
    if cached:
        member.stream.close.assert_called_once()
    authorize.side_effect = ValueError("SOURCE_PERMISSION_DENIED")
    prepare.reset_mock()
    with pytest.raises(ValueError, match="SOURCE_PERMISSION_DENIED"):
        service._ensure_preview(target)
    prepare.assert_not_called()
