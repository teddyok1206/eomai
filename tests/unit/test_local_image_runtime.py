from __future__ import annotations

import pwd
import re
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_local_image_unit_is_fixed_hardened_and_nas_inaccessible() -> None:
    source = (ROOT / "infra/systemd/eom-image-provider@.service").read_text(encoding="utf-8")

    assert "User=eom-image" in source
    assert "Group=eom-image" in source
    assert "eom-local-image generate-composite" in source
    assert "/srv/eom/image-workspaces/%i/request.json" in source
    assert "--gpu-lock /run/eom-image-provider/gpu0.lock" in source
    assert "PrivateNetwork=true" in source
    assert "NoNewPrivileges=true" in source
    assert "RestrictSUIDSGID=true" in source
    assert "DevicePolicy=closed" in source
    assert "ReadOnlyPaths=/srv/eom/models/image" in source
    assert "ReadWritePaths=/srv/eom/image-workspaces/%i" in source
    assert "InaccessiblePaths=/mnt/nas" in source
    assert "InaccessiblePaths=/home/eom/EOM" in source
    assert "Restart=no" in source


def test_polkit_grants_only_exact_local_image_instances_to_runner() -> None:
    source = (ROOT / "infra/polkit/50-eom-worker-units.rules").read_text(encoding="utf-8")

    assert "eom-image-provider@imgreq_" in source
    assert "localImageUnit.test(unit)" in source
    assert re.search(
        r"subject\.user === \"eom-workflow-runner\"[\s\S]+localImageUnit\.test\(unit\)",
        source,
    )
    assert 'subject.user === "eom-image"' not in source


def test_runner_can_stage_handoff_but_cannot_read_model_bytes() -> None:
    source = (ROOT / "infra/systemd/eom-workflow-runner.service").read_text(encoding="utf-8")

    assert "SupplementaryGroups=" in source and "eom-image" in source
    assert "ReadOnlyPaths=/etc/eom/local-image-provider.json" in source
    assert "ReadWritePaths=/srv/eom/image-workspaces" in source
    assert "InaccessiblePaths=/srv/eom/models/image" in source
    assert "PrivateDevices=true" in source


def test_local_image_release_scripts_are_offline_scoped_and_non_recursive() -> None:
    build = (ROOT / "scripts/image_provider/build_release.sh").read_text(encoding="utf-8")
    deploy = (ROOT / "scripts/image_provider/deploy_runtime.sh").read_text(encoding="utf-8")
    normalize = (ROOT / "scripts/image_provider/normalize_runtime_permissions.py").read_text(
        encoding="utf-8"
    )

    assert "--no-deps --no-build-isolation" in build
    assert 'git -C "${REPOSITORY}" archive' in build
    assert "curl" not in build and "wget" not in build
    assert "--no-deps --force-reinstall" in deploy
    assert "RUNNER_RESTART_REQUIRED=YES" in deploy
    assert "systemctl restart" not in deploy
    assert "chmod -R" not in deploy and "chown -R" not in deploy
    assert "os.walk(files_root, followlinks=False)" in normalize
    assert "manifest.files" in normalize


def test_local_image_release_scripts_have_valid_syntax() -> None:
    for relative in (
        "scripts/image_provider/build_release.sh",
        "scripts/image_provider/deploy_runtime.sh",
    ):
        completed = subprocess.run(
            ["bash", "-n", str(ROOT / relative)],
            capture_output=True,
            check=False,
            text=True,
        )
        assert completed.returncode == 0, completed.stderr
    compile(
        (ROOT / "scripts/image_provider/normalize_runtime_permissions.py").read_text(
            encoding="utf-8"
        ),
        "normalize_runtime_permissions.py",
        "exec",
    )
    compile(
        (ROOT / "scripts/image_provider/run_fixed_composite_smoke.py").read_text(encoding="utf-8"),
        "run_fixed_composite_smoke.py",
        "exec",
    )


def test_fixed_composite_smoke_uses_production_adapter_and_is_not_an_item_workflow() -> None:
    source = (ROOT / "scripts/image_provider/run_fixed_composite_smoke.py").read_text(
        encoding="utf-8"
    )

    assert "FixedLocalImageProviderAdapter(settings).generate" in source
    assert "LOCAL_GENERATIVE_BACKGROUND" in source
    assert "compose_vector_overlay_svg" in source
    assert "LOCAL_IMAGE_FIXED_UNIT_SMOKE_PASS" in source
    assert 'grp.getgrnam("eom-image")' in source
    assert "provider_group.gr_gid not in os.getgroups()" in source
    assert "shutil.rmtree(workspace)" in source
    assert "WorkflowCatalogService" not in source
    assert "session" not in source.lower()


def test_local_image_unit_has_valid_systemd_syntax_when_analyzer_is_available() -> None:
    if shutil.which("systemd-analyze") is None:
        return
    try:
        pwd.getpwnam("eom-image")
    except KeyError:
        return
    unit = ROOT / "infra/systemd/eom-image-provider@.service"
    completed = subprocess.run(
        ["systemd-analyze", "verify", str(unit)],
        capture_output=True,
        check=False,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr
