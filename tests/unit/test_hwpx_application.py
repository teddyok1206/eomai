from __future__ import annotations

import os
import re
import stat
import subprocess
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from eom_hwpx_manager import capability as capability_module
from eom_hwpx_manager import runner
from eom_hwpx_manager.application_adapter import (
    WORKSPACE_DIRECTORY_MODE,
    WORKSPACE_FILE_MODE,
    WORKSPACE_ROOT_MODE,
    FixedContentTeamBuilderAdapter,
    FixedKordocBuilderAdapter,
    FixedQuestionTemplateBuilderAdapter,
)
from eom_hwpx_manager.application_service import HwpxApplicationService
from eom_hwpx_manager.application_state import (
    ApplicationBuildState,
    require_application_transition,
)
from eom_hwpx_manager.capability import HwpxCapabilityService
from eom_hwpx_manager.errors import HwpxManagerError, HwpxManagerErrorCode
from eom_hwpx_manager.markdown_structure import inspect_markdown_structure
from eom_hwpx_manager.settings import HwpxSettings
from eom_identifiers import sha256_file


def test_capability_is_prepared_when_runtime_is_absent(tmp_path: Path) -> None:
    service = HwpxCapabilityService(HwpxSettings(builder_binary=tmp_path / "missing"))
    value = service.inspect()
    assert value.state == "PREPARED_NOT_DEPLOYED"
    assert value.detail_code == "HWPX_BUILDER_NOT_DEPLOYED"


def test_capability_ready_requires_fixed_version_offline_and_manager(tmp_path: Path) -> None:
    binary = tmp_path / "eom-hwpx"
    binary.write_text(
        "#!/bin/sh\nprintf '%s\\n' "
        '\'{"status":"READY","node_major":22,"kordoc_version":"4.9.0",'
        '"offline_required":true}\'\n',
        encoding="utf-8",
    )
    binary.chmod(0o755)
    ready = HwpxCapabilityService(
        HwpxSettings(builder_binary=binary),
        isolation_preflight=lambda: (True, "HWPX_ISOLATED_BUILDER_READY"),
    ).inspect()
    assert ready.state == "READY"
    assert ready.native_equations and ready.native_tables
    unregistered = HwpxCapabilityService(
        HwpxSettings(builder_binary=binary),
        manager_registered=False,
        isolation_preflight=lambda: (True, "HWPX_ISOLATED_BUILDER_READY"),
    ).inspect()
    assert unregistered.state == "DEGRADED"
    assert unregistered.detail_code == "HWPX_MANAGER_NOT_REGISTERED"

    not_deployed = HwpxCapabilityService(
        HwpxSettings(builder_binary=binary),
        isolation_preflight=lambda: (False, "HWPX_ISOLATED_BUILDER_NOT_DEPLOYED"),
    ).inspect()
    assert not_deployed.state == "PREPARED_NOT_DEPLOYED"
    assert not_deployed.detail_code == "HWPX_ISOLATED_BUILDER_NOT_DEPLOYED"


def test_capability_mismatch_is_degraded_and_sanitized(tmp_path: Path) -> None:
    binary = tmp_path / "eom-hwpx"
    binary.write_text("#!/bin/sh\nprintf 'not-json SECRET_VALUE\\n'\n", encoding="utf-8")
    binary.chmod(0o755)
    value = HwpxCapabilityService(HwpxSettings(builder_binary=binary)).inspect()
    assert value.state == "DEGRADED"
    assert "SECRET" not in value.detail_code


def test_capability_rejects_end_of_life_node_20(tmp_path: Path) -> None:
    binary = tmp_path / "eom-hwpx"
    binary.write_text(
        "#!/bin/sh\nprintf '%s\\n' "
        '\'{"status":"READY","node_major":20,"kordoc_version":"4.9.0",'
        '"offline_required":true}\'\n',
        encoding="utf-8",
    )
    binary.chmod(0o755)

    value = HwpxCapabilityService(HwpxSettings(builder_binary=binary)).inspect()

    assert value.state == "DEGRADED"
    assert value.detail_code == "HWPX_CAPABILITY_INTEGRITY_MISMATCH"


def test_capability_rejects_symlink_and_oversized_response(tmp_path: Path) -> None:
    target = tmp_path / "builder-target"
    target.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    target.chmod(0o755)
    link = tmp_path / "eom-hwpx"
    link.symlink_to(target)
    assert HwpxCapabilityService(HwpxSettings(builder_binary=link)).inspect().state == "DEGRADED"
    target.write_text(
        "#!/bin/sh\nprintf '%020000d' 0\n",
        encoding="utf-8",
    )
    value = HwpxCapabilityService(HwpxSettings(builder_binary=target)).inspect()
    assert value.state == "DEGRADED"
    assert value.detail_code == "HWPX_CAPABILITY_RESPONSE_INVALID"


def test_isolation_preflight_rejects_non_root_or_wrong_mode_units(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    builder = tmp_path / "eom-hwpx-kordoc@.service"
    question_builder = tmp_path / "eom-hwpx-builder@.service"
    content_team_builder = tmp_path / "eom-hwpx-content-team@.service"
    runner_unit = tmp_path / "eom-hwpx-application-runner.service"
    builder.write_text(
        "\n".join(sorted(capability_module.REQUIRED_BUILDER_DIRECTIVES)) + "\n",
        encoding="utf-8",
    )
    runner_unit.write_text(
        "\n".join(sorted(capability_module.REQUIRED_RUNNER_DIRECTIVES)) + "\n",
        encoding="utf-8",
    )
    builder.chmod(0o644)
    question_builder.write_text(
        "\n".join(sorted(capability_module.REQUIRED_QUESTION_TEMPLATE_BUILDER_DIRECTIVES)) + "\n",
        encoding="utf-8",
    )
    question_builder.chmod(0o644)
    content_team_builder.write_text(
        "\n".join(sorted(capability_module.REQUIRED_CONTENT_TEAM_BUILDER_DIRECTIVES)) + "\n",
        encoding="utf-8",
    )
    content_team_builder.chmod(0o644)
    runner_unit.chmod(0o644)
    monkeypatch.setattr(capability_module, "BUILDER_UNIT_PATH", builder)
    monkeypatch.setattr(
        capability_module,
        "QUESTION_TEMPLATE_BUILDER_UNIT_PATH",
        question_builder,
    )
    monkeypatch.setattr(
        capability_module,
        "CONTENT_TEAM_BUILDER_UNIT_PATH",
        content_team_builder,
    )
    monkeypatch.setattr(capability_module, "RUNNER_UNIT_PATH", runner_unit)
    monkeypatch.setattr(capability_module, "SYSTEMCTL", Path("/usr/bin/true"))

    assert capability_module.fixed_builder_isolation_preflight() == (
        False,
        "HWPX_ISOLATED_BUILDER_LAYOUT_INVALID",
    )

    runner_unit.chmod(0o600)
    assert capability_module.fixed_builder_isolation_preflight() == (
        False,
        "HWPX_ISOLATED_BUILDER_LAYOUT_INVALID",
    )


def test_markdown_native_structure_inventory_and_required_bounds() -> None:
    value = inspect_markdown_structure(
        b"# Item\n\n$$x = v_0 t$$\n\n| A | B |\n| --- | --- |\n| 1 | 2 |\n"
    )
    assert value.native_equation_count == 1
    assert value.native_table_count == 1
    with pytest.raises(HwpxManagerError):
        inspect_markdown_structure(b"")


def test_application_build_transition_table_fails_closed() -> None:
    require_application_transition(ApplicationBuildState.REQUESTED, ApplicationBuildState.RUNNING)
    require_application_transition(ApplicationBuildState.RUNNING, ApplicationBuildState.VALIDATING)
    require_application_transition(
        ApplicationBuildState.VALIDATING, ApplicationBuildState.SUCCEEDED
    )
    with pytest.raises(RuntimeError):
        require_application_transition(
            ApplicationBuildState.REQUESTED, ApplicationBuildState.SUCCEEDED
        )


def test_secure_download_fd_rejects_hash_mismatch_and_directory(tmp_path: Path) -> None:
    output = tmp_path / "output.hwpx"
    output.write_bytes(b"HWPX_TEST_BYTES")
    expected = sha256_file(output)
    fd = HwpxApplicationService._verified_fd(output, expected)
    try:
        assert os.read(fd, 4) == b"HWPX"
    finally:
        os.close(fd)
    with pytest.raises(HwpxManagerError):
        HwpxApplicationService._verified_fd(output, "sha256:" + "0" * 64)
    with pytest.raises(HwpxManagerError):
        HwpxApplicationService._verified_fd(tmp_path, expected)


def test_artifact_primary_file_rejects_traversal_and_symlink(tmp_path: Path) -> None:
    root = tmp_path / "artifact"
    root.mkdir()
    output = root / "document.hwpx"
    output.write_bytes(b"HWPX")
    revision = SimpleNamespace(nas_path=str(root), manifest={"primary_file": "document.hwpx"})
    assert HwpxApplicationService._primary_file(revision) == output  # type: ignore[arg-type]
    escaped = SimpleNamespace(nas_path=str(root), manifest={"primary_file": "../escape.hwpx"})
    with pytest.raises(HwpxManagerError):
        HwpxApplicationService._primary_file(escaped)  # type: ignore[arg-type]
    output.unlink()
    output.symlink_to(tmp_path / "elsewhere.hwpx")
    with pytest.raises(HwpxManagerError):
        HwpxApplicationService._primary_file(revision)  # type: ignore[arg-type]


def test_download_filename_is_ascii_and_fixed_extension() -> None:
    value = HwpxApplicationService._safe_filename("문항 item_01.hwpx")
    assert value.endswith(".hwpx")
    assert value.isascii()
    assert "/" not in value and "\\" not in value and ".." not in value


def test_markdown_component_requires_one_typed_pinned_pointer() -> None:
    component: dict[str, Any] = {
        "schema_ref": "eom.hwpx.markdown-document",
        "media_type": "text/markdown; charset=utf-8",
        "artifact_id": "artifact_" + "a" * 32,
        "artifact_revision_id": "rev_" + "b" * 32,
        "sha256": "sha256:" + "c" * 64,
    }
    assert HwpxApplicationService._markdown_component({"components": [component]}) == component
    with pytest.raises(HwpxManagerError):
        HwpxApplicationService._markdown_component({"components": []})
    with pytest.raises(HwpxManagerError):
        HwpxApplicationService._markdown_component({"components": [component, component]})


@pytest.mark.parametrize(
    ("schema_ref", "expected_renderer"),
    [
        ("eom.assessment.item-content/1.0", "eom-template"),
        ("eom.assessment.item-content/2.0", "content-team"),
    ],
)
def test_automatic_renderer_resolves_from_one_canonical_item_component(
    schema_ref: str, expected_renderer: str
) -> None:
    component: dict[str, Any] = {
        "component_type": "ITEM_CONTENT",
        "ordinal": 0,
        "schema_ref": schema_ref,
        "media_type": "application/json",
        "artifact_id": "artifact_" + "a" * 32,
        "artifact_revision_id": "rev_" + "b" * 32,
        "sha256": "sha256:" + "c" * 64,
    }

    renderer, resolved = HwpxApplicationService._resolve_build_source(
        {"components": [component]}, "auto"
    )

    assert renderer == expected_renderer
    assert resolved is component


def test_automatic_renderer_rejects_missing_or_mixed_canonical_sources() -> None:
    first = {
        "component_type": "ITEM_CONTENT",
        "ordinal": 0,
        "schema_ref": "eom.assessment.item-content/1.0",
        "media_type": "application/json",
    }
    second = first | {"schema_ref": "eom.assessment.item-content/2.0"}

    with pytest.raises(HwpxManagerError, match="exactly one automatic"):
        HwpxApplicationService._resolve_build_source({"components": []}, "auto")
    with pytest.raises(HwpxManagerError, match="exactly one automatic"):
        HwpxApplicationService._resolve_build_source({"components": [first, second]}, "auto")


def test_runner_returns_sanitized_failure_without_traceback(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    class FakeEngine:
        def dispose(self) -> None:
            pass

    class FailingService:
        def __init__(self, _engine: object, **_kwargs: object) -> None:
            pass

        def process_next(self) -> None:
            raise HwpxManagerError(
                HwpxManagerErrorCode.HWPX_KORDOC_SOURCE_INVALID,
                "SECRET_SOURCE_PATH",
            )

    monkeypatch.setattr(runner, "build_engine", FakeEngine)
    monkeypatch.setattr(runner, "_runtime_privileges_ready", lambda _engine: True)
    monkeypatch.setattr(runner, "_runtime_staging_ready", lambda _path: True)
    monkeypatch.setattr(runner, "RegistryService", lambda _engine: object())
    monkeypatch.setattr(runner, "HwpxApplicationService", FailingService)

    assert runner.run_once() == 1
    captured = capsys.readouterr()
    assert "HWPX_KORDOC_SOURCE_INVALID" in captured.err
    assert "SECRET_SOURCE_PATH" not in captured.err
    assert "Traceback" not in captured.err


def test_runner_fails_closed_before_queue_access_when_manager_privileges_are_missing(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    class FakeEngine:
        def dispose(self) -> None:
            pass

    called = False

    class UnexpectedService:
        def __init__(self, _engine: object, **_kwargs: object) -> None:
            nonlocal called
            called = True

    monkeypatch.setattr(runner, "build_engine", FakeEngine)
    monkeypatch.setattr(runner, "_runtime_privileges_ready", lambda _engine: False)
    monkeypatch.setattr(runner, "HwpxApplicationService", UnexpectedService)

    assert runner.run_once() == 1
    captured = capsys.readouterr()
    assert "HWPX_MANAGER_DATABASE_PRIVILEGES_UNAVAILABLE" in captured.err
    assert "Traceback" not in captured.err
    assert not called


def test_runner_fails_closed_before_queue_access_when_private_staging_is_unavailable(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    class FakeEngine:
        def dispose(self) -> None:
            pass

    called = False

    class UnexpectedService:
        def __init__(self, _engine: object, **_kwargs: object) -> None:
            nonlocal called
            called = True

    monkeypatch.setattr(runner, "build_engine", FakeEngine)
    monkeypatch.setattr(runner, "_runtime_privileges_ready", lambda _engine: True)
    monkeypatch.setattr(runner, "_runtime_staging_ready", lambda _path: False)
    monkeypatch.setattr(runner, "HwpxApplicationService", UnexpectedService)

    assert runner.run_once() == 1
    captured = capsys.readouterr()
    assert "HWPX_MANAGER_STAGING_UNAVAILABLE" in captured.err
    assert "Traceback" not in captured.err
    assert not called


def test_application_adapter_root_contract_is_private_group_only() -> None:
    metadata = os.stat_result((stat.S_IFDIR | 0o2770, 1, 1, 1, 0, 986, 0, 0, 0, 0))
    assert FixedKordocBuilderAdapter._root_contract_ready(metadata, 986, [986])
    assert not FixedKordocBuilderAdapter._root_contract_ready(metadata, 986, [])
    wrong_mode = os.stat_result((stat.S_IFDIR | 0o2777, 1, 1, 1, 0, 986, 0, 0, 0, 0))
    assert not FixedKordocBuilderAdapter._root_contract_ready(wrong_mode, 986, [986])


def test_application_adapter_finalizes_private_group_paths_without_setgid(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir(mode=0o700)
    target = workspace / "request.json"
    target.write_text("{}", encoding="ascii")

    FixedQuestionTemplateBuilderAdapter._finalize_directory(workspace, os.getgid())
    FixedQuestionTemplateBuilderAdapter._finalize_file(target, os.getgid())

    workspace_metadata = workspace.stat()
    target_metadata = target.stat()
    assert stat.S_IMODE(workspace_metadata.st_mode) == WORKSPACE_DIRECTORY_MODE
    assert workspace_metadata.st_mode & stat.S_ISGID == 0
    assert workspace_metadata.st_gid == os.getgid()
    assert stat.S_IMODE(target_metadata.st_mode) == WORKSPACE_FILE_MODE
    assert target_metadata.st_gid == os.getgid()
    assert target_metadata.st_mode & 0o007 == 0


def test_application_adapter_uses_only_fixed_unit_and_arguments(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace_root = tmp_path / "workspaces"
    workspace_root.mkdir()
    build_id = "hwpxbuild_" + "a" * 32
    workspace = workspace_root / build_id
    workspace.mkdir()
    workspace.chmod(WORKSPACE_DIRECTORY_MODE)
    log_root = tmp_path / "logs"
    calls: list[list[str]] = []

    def run_fixed(argv: list[str], **_kwargs: object) -> subprocess.CompletedProcess[bytes]:
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 0, b"", b"")

    monkeypatch.setattr("eom_hwpx_manager.application_adapter.subprocess.run", run_fixed)
    adapter = FixedKordocBuilderAdapter(
        HwpxSettings(workspace_root=workspace_root, timeout_seconds=180)
    )
    result = adapter.run(
        workspace,
        "render-kordoc",
        ["--request", "request.json", "--result", "result.json"],
        log_root,
    )
    assert result.exit_code == 0
    assert calls == [
        [
            "/usr/bin/systemctl",
            "--no-ask-password",
            "--wait",
            "start",
            f"eom-hwpx-kordoc@{build_id}.service",
        ]
    ]
    with pytest.raises(HwpxManagerError):
        adapter.run(workspace, "render-kordoc", ["--request", "../../secret"], log_root)
    assert len(calls) == 1


def test_content_team_adapter_uses_only_its_fixed_unit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace_root = tmp_path / "workspaces"
    workspace_root.mkdir()
    build_id = "hwpxbuild_" + "b" * 32
    workspace = workspace_root / build_id
    workspace.mkdir()
    workspace.chmod(WORKSPACE_DIRECTORY_MODE)
    calls: list[list[str]] = []

    def run_fixed(argv: list[str], **_kwargs: object) -> subprocess.CompletedProcess[bytes]:
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 0, b"", b"")

    monkeypatch.setattr("eom_hwpx_manager.application_adapter.subprocess.run", run_fixed)
    adapter = FixedContentTeamBuilderAdapter(
        HwpxSettings(workspace_root=workspace_root, timeout_seconds=300)
    )

    result = adapter.run(
        workspace,
        "render-content-team",
        ["--request", "request.json", "--result", "result.json"],
        tmp_path / "logs",
    )

    assert result.exit_code == 0
    assert calls == [
        [
            "/usr/bin/systemctl",
            "--no-ask-password",
            "--wait",
            "start",
            f"eom-hwpx-content-team@{build_id}.service",
        ]
    ]


def test_application_adapter_has_no_transient_or_chown_fallback() -> None:
    source = Path("services/hwpx_manager/eom_hwpx_manager/application_adapter.py").read_text(
        encoding="utf-8"
    )
    unit = Path("infra/systemd/eom-hwpx-kordoc@.service").read_text(encoding="utf-8")
    bootstrap = Path("scripts/hwpx/bootstrap_builder_user.sh").read_text(encoding="utf-8")
    assert "systemd-run" not in source
    assert "os.chown" not in source
    assert "shell=True" not in source
    assert "ExecStart=/srv/eom/conda/envs/eom-hwpx/bin/eom-hwpx render-kordoc" in unit
    assert "CapabilityBoundingSet=" in unit
    assert "UMask=0007" in unit
    assert "UMask=0077" not in unit
    assert "RestrictSUIDSGID=true" in unit
    handoff = Path("services/hwpx_builder/eom_hwpx_builder/handoff.py").read_text(encoding="utf-8")
    assert "HANDOFF_DIRECTORY_MODE = 0o750" in handoff
    assert "HANDOFF_DIRECTORY_MODE = 0o2750" not in handoff
    assert f"-m {WORKSPACE_ROOT_MODE:o} /srv/eom/hwpx-workspaces" in bootstrap


def test_question_template_adapter_uses_only_its_fixed_unit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace_root = tmp_path / "workspaces"
    workspace_root.mkdir()
    build_id = "hwpxbuild_" + "b" * 32
    workspace = workspace_root / build_id
    workspace.mkdir()
    workspace.chmod(WORKSPACE_DIRECTORY_MODE)
    calls: list[list[str]] = []

    def run_fixed(argv: list[str], **_kwargs: object) -> subprocess.CompletedProcess[bytes]:
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 0, b"", b"")

    monkeypatch.setattr("eom_hwpx_manager.application_adapter.subprocess.run", run_fixed)
    adapter = FixedQuestionTemplateBuilderAdapter(
        HwpxSettings(workspace_root=workspace_root, timeout_seconds=180)
    )
    result = adapter.run(
        workspace,
        "render",
        ["--request", "request.json", "--result", "result.json"],
        tmp_path / "logs",
    )
    assert result.unit_name == f"eom-hwpx-builder@{build_id}.service"
    assert calls == [
        [
            "/usr/bin/systemctl",
            "--no-ask-password",
            "--wait",
            "start",
            f"eom-hwpx-builder@{build_id}.service",
        ]
    ]
    with pytest.raises(HwpxManagerError):
        adapter.run(workspace, "render-kordoc", ["--request", "request.json"], tmp_path / "logs")
    assert len(calls) == 1


def test_application_runner_separates_manager_state_from_builder_home() -> None:
    unit = Path("infra/systemd/eom-hwpx-application-runner.service").read_text(encoding="utf-8")
    assert "User=eom-hwpx-manager" in unit
    assert "SupplementaryGroups=eom eom-hwpx" in unit
    assert "StateDirectory=eom-hwpx-api" in unit
    assert "StateDirectoryMode=0700" in unit
    assert "WorkingDirectory=/var/lib/eom-hwpx-api" in unit
    assert "Environment=HOME=/var/lib/eom-hwpx-api" in unit
    assert "Environment=EOM_STAGING_ROOT=/var/lib/eom-hwpx-api/staging" in unit
    assert "ReadWritePaths=/var/lib/eom-hwpx-api" in unit
    assert "ReadWritePaths=/srv/eom/staging" not in unit
    assert "InaccessiblePaths=/var/lib/eom-hwpx" in unit
    assert "WorkingDirectory=/var/lib/eom-hwpx\n" not in unit


def test_runner_private_staging_preflight_fails_closed(tmp_path: Path) -> None:
    staging = tmp_path / "staging"

    assert runner._runtime_staging_ready(staging)
    assert stat.S_IMODE(staging.stat().st_mode) == 0o700

    staging.chmod(0o750)
    assert not runner._runtime_staging_ready(staging)

    staging.chmod(0o700)
    staging.rmdir()
    staging.symlink_to(tmp_path)
    assert not runner._runtime_staging_ready(staging)


def test_builder_bootstrap_group_matcher_uses_closed_exact_names() -> None:
    bootstrap = Path("scripts/hwpx/bootstrap_builder_user.sh").read_text(encoding="utf-8")
    match = re.search(r"^FORBIDDEN_GROUP_PATTERN='([^']+)'$", bootstrap, re.MULTILINE)
    assert match is not None
    pattern = re.compile(match.group(1))

    for allowed in ("eom-hwpx", "eom-api", "eom-cdx", "eom-cdx-admin"):
        assert pattern.fullmatch(allowed) is None
    for forbidden in ("sudo", "docker", "eom", "eom-cdx-01", "eom-cdx-999"):
        assert pattern.fullmatch(forbidden) is not None
