from __future__ import annotations

from pathlib import Path

import pytest
from eom_catalog_service.pdf_learning_completion_runtime import (
    PdfLearningRuntimeError,
    SystemdPdfLearningRuntimeObserver,
)


def _properties(automation: Path, extra: Path | None = None) -> dict[str, tuple[str, ...]]:
    rendered = f"{automation} (ignore_errors=no)"
    if extra is not None:
        rendered += f" {extra} (ignore_errors=no)"
    return {
        "ActiveState": ("active",),
        "MainPID": ("123",),
        "ExecMainStartTimestamp": ("Fri 2099-01-02 03:04:05 UTC",),
        "EnvironmentFiles": (rendered,),
        "Environment": ("",),
    }


def _observer(tmp_path: Path) -> tuple[SystemdPdfLearningRuntimeObserver, Path, Path]:
    automation = tmp_path / "legacy-item-automation.env"
    extra = tmp_path / "catalog.env"
    automation.write_text("EOM_LEGACY_ITEM_AUTOMATION_MODE=DISABLED\n", encoding="utf-8")
    extra.write_text("OTHER_SETTING=value\n", encoding="utf-8")
    observer = SystemdPdfLearningRuntimeObserver(
        automation_env_path=automation,
        runtime_dropin_root=tmp_path / "runtime-dropins",
        workflow_hold_root=tmp_path / "workflow-hold",
    )
    return observer, automation, extra


def _permit_test_configuration_reads(
    observer: SystemdPdfLearningRuntimeObserver,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        observer,
        "_read_configuration",
        lambda path: (path.read_bytes(), path.stat()),
    )


def test_runtime_observer_accepts_empty_direct_environment_and_safe_extra_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    observer, automation, extra = _observer(tmp_path)
    _permit_test_configuration_reads(observer, monkeypatch)
    monkeypatch.setattr(observer, "_unit_properties", lambda: _properties(automation, extra))
    monkeypatch.setattr(observer, "_directory_entries", lambda _path: ())

    observed = observer.observe()

    assert observed.automation_mode == "DISABLED"


def test_runtime_observer_rejects_later_environment_file_automation_override(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    observer, automation, extra = _observer(tmp_path)
    _permit_test_configuration_reads(observer, monkeypatch)
    extra.write_text("EOM_LEGACY_ITEM_AUTOMATION_MODE=AUTO\n", encoding="utf-8")
    monkeypatch.setattr(observer, "_unit_properties", lambda: _properties(automation, extra))
    monkeypatch.setattr(observer, "_directory_entries", lambda _path: ())

    with pytest.raises(PdfLearningRuntimeError, match="overrides automation mode"):
        observer.observe()


def test_runtime_observer_rejects_whitespace_prefixed_environment_override(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    observer, automation, extra = _observer(tmp_path)
    _permit_test_configuration_reads(observer, monkeypatch)
    extra.write_text("  EOM_LEGACY_ITEM_AUTOMATION_MODE=AUTO  \n", encoding="utf-8")
    monkeypatch.setattr(observer, "_unit_properties", lambda: _properties(automation, extra))
    monkeypatch.setattr(observer, "_directory_entries", lambda _path: ())

    with pytest.raises(PdfLearningRuntimeError, match="overrides automation mode"):
        observer.observe()


def test_unit_property_parser_allows_empty_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _Completed:
        stdout = (
            "ActiveState=active\n"
            "MainPID=123\n"
            "ExecMainStartTimestamp=Fri 2099-01-02 03:04:05 UTC\n"
            "EnvironmentFiles=/etc/eom/legacy-item-automation.env (ignore_errors=no)\n"
            "Environment=\n"
        )

    monkeypatch.setattr(
        "eom_catalog_service.pdf_learning_completion_runtime.subprocess.run",
        lambda *_args, **_kwargs: _Completed(),
    )

    properties = SystemdPdfLearningRuntimeObserver()._unit_properties()

    assert properties["Environment"] == ("",)
