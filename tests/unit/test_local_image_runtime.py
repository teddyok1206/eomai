from __future__ import annotations

import os
import pwd
import re
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

from scripts.image_trainer.stage_crop_locator import _make_trainer_readonly_directory

ROOT = Path(__file__).resolve().parents[2]


def test_training_staging_directory_mode_is_not_filtered_by_operator_umask(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(os, "chown", lambda *_args: None)
    target = tmp_path / "inputs"
    previous = os.umask(0o077)
    try:
        _make_trainer_readonly_directory(target, trainer_gid=980)
    finally:
        os.umask(previous)

    assert stat.S_IMODE(target.stat().st_mode) == 0o550


def test_training_stagers_use_the_exact_shared_directory_boundary() -> None:
    for relative in (
        "scripts/image_trainer/stage_micro_probe.py",
        "scripts/image_trainer/stage_science_micro_probe.py",
        "scripts/image_trainer/stage_science_campaign_micro_probe.py",
        "scripts/image_trainer/stage_micro_evaluation.py",
        "scripts/image_trainer/stage_science_micro_evaluation.py",
        "scripts/image_trainer/stage_science_campaign_micro_evaluation.py",
        "scripts/image_trainer/stage_science_subject_benchmark.py",
        "scripts/image_trainer/stage_science_subject_multiseed.py",
    ):
        source = (ROOT / relative).read_text(encoding="utf-8")
        assert "_make_trainer_readonly_directory(" in source
        assert ".mkdir(mode=0o550)" not in source


def test_local_image_unit_is_fixed_hardened_and_nas_inaccessible() -> None:
    source = (ROOT / "infra/systemd/eom-image-provider@.service").read_text(encoding="utf-8")

    assert "User=eom-image" in source
    assert "Group=eom-image" in source
    assert "eom-local-image generate-composite" in source
    assert "/srv/eom/image-workspaces/%i/request.json" in source
    assert "--gpu-lock /var/lib/eom-image/gpu0.lock" in source
    assert "PrivateNetwork=true" in source
    assert "NoNewPrivileges=true" in source
    assert "RestrictSUIDSGID=true" in source
    assert "DevicePolicy=closed" in source
    assert "ReadOnlyPaths=/srv/eom/models/image" in source
    assert "ReadWritePaths=/srv/eom/image-workspaces/%i" in source
    assert "InaccessiblePaths=/mnt/nas" in source
    assert "InaccessiblePaths=/home/eom/EOM" in source
    assert "Restart=no" in source


def test_visual_reference_acquirer_has_network_but_no_gpu_model_nas_or_repo_access() -> None:
    source = (ROOT / "infra/systemd/eom-image-reference-acquirer@.service").read_text(
        encoding="utf-8"
    )

    assert "User=eom-image-reference" in source
    assert "Group=eom-image-reference" in source
    assert "eom-local-image acquire-reference" in source
    assert "/srv/eom/image-reference-workspaces/%i/command.json" in source
    assert "PrivateNetwork=false" in source
    assert "PrivateDevices=true" in source
    assert "RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6" in source
    assert "--gpu-lock" not in source
    assert "ReadWritePaths=/srv/eom/image-reference-workspaces/%i" in source
    assert "InaccessiblePaths=/mnt/nas" in source
    assert "InaccessiblePaths=/srv/eom/models" in source
    assert "InaccessiblePaths=/home/eom/EOM" in source
    assert "Restart=no" in source


def test_visual_reference_discoverer_has_the_same_bounded_network_boundary() -> None:
    source = (ROOT / "infra/systemd/eom-image-reference-discoverer@.service").read_text(
        encoding="utf-8"
    )

    assert "User=eom-image-reference" in source
    assert "eom-local-image discover-reference" in source
    assert "PrivateNetwork=false" in source
    assert "PrivateDevices=true" in source
    assert "RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6" in source
    assert "--gpu-lock" not in source
    assert "ReadWritePaths=/srv/eom/image-reference-workspaces/%i" in source
    assert "InaccessiblePaths=/mnt/nas" in source
    assert "InaccessiblePaths=/srv/eom/models" in source
    assert "InaccessiblePaths=/home/eom/EOM" in source


def test_reference_conditioned_provider_has_gpu_but_no_network_nas_or_acquirer_access() -> None:
    source = (ROOT / "infra/systemd/eom-image-reference-provider@.service").read_text(
        encoding="utf-8"
    )

    assert "User=eom-image" in source
    assert "eom-local-image generate-reference-composite" in source
    assert "--gpu-lock /var/lib/eom-image/gpu0.lock" in source
    assert "PrivateNetwork=true" in source
    assert "DevicePolicy=closed" in source
    assert "ReadOnlyPaths=/srv/eom/models/image" in source
    assert "ReadWritePaths=/srv/eom/image-workspaces/%i" in source
    assert "InaccessiblePaths=/srv/eom/image-reference-workspaces" in source
    assert "InaccessiblePaths=/mnt/nas" in source
    assert "InaccessiblePaths=/home/eom/EOM" in source
    assert "Restart=no" in source


def test_style_reference_provider_reads_only_exact_model_and_adapter_stores() -> None:
    source = (ROOT / "infra/systemd/eom-image-reference-style-provider@.service").read_text(
        encoding="utf-8"
    )

    assert "User=eom-image" in source
    assert "eom-local-image generate-reference-style-composite" in source
    assert "--style-adapter-store-root /srv/eom/models/image-style" in source
    assert "--gpu-lock /var/lib/eom-image/gpu0.lock" in source
    assert "PrivateNetwork=true" in source
    assert "ReadOnlyPaths=/srv/eom/models/image" in source
    assert "ReadOnlyPaths=/srv/eom/models/image-style" in source
    assert "ReadWritePaths=/srv/eom/image-workspaces/%i" in source
    assert "InaccessiblePaths=/mnt/nas" in source
    assert "InaccessiblePaths=/home/eom/EOM" in source
    assert "Restart=no" in source


def test_local_image_trainer_unit_is_isolated_and_shares_only_gpu_capacity_lock() -> None:
    source = (ROOT / "infra/systemd/eom-image-trainer@.service").read_text(encoding="utf-8")

    assert "User=eom-image" in source
    assert "Group=eom-image" in source
    assert "eom-local-image-trainer train" in source
    assert "/srv/eom/image-training-workspaces/%i/command.json" in source
    assert "--gpu-lock /var/lib/eom-image/gpu0.lock" in source
    assert "Environment=CUBLAS_WORKSPACE_CONFIG=:4096:8" in source
    assert "PrivateNetwork=true" in source
    assert "NoNewPrivileges=true" in source
    assert "DevicePolicy=closed" in source
    assert "ReadOnlyPaths=/srv/eom/models/image" in source
    assert "ReadWritePaths=/srv/eom/image-training-workspaces/%i" in source
    assert "InaccessiblePaths=/mnt/nas" in source
    assert "InaccessiblePaths=/srv/eom/image-workspaces" in source
    assert "Restart=no" in source


def test_local_image_crop_locator_unit_is_isolated_without_gpu_or_nas_access() -> None:
    source = (ROOT / "infra/systemd/eom-image-crop-locator@.service").read_text(encoding="utf-8")

    assert "User=eom-image" in source
    assert "Group=eom-image" in source
    assert "eom-local-image-trainer locate-crops" in source
    assert "/srv/eom/image-training-workspaces/%i/command.json" in source
    assert "--gpu-lock" not in source
    assert "PrivateNetwork=true" in source
    assert "PrivateDevices=true" in source
    assert "NoNewPrivileges=true" in source
    assert "ReadWritePaths=/srv/eom/image-training-workspaces/%i" in source
    assert "InaccessiblePaths=/mnt/nas" in source
    assert "InaccessiblePaths=/home/eom/EOM" in source
    assert "Restart=no" in source


def test_science_visual_pilot_unit_is_isolated_without_gpu_or_nas_access() -> None:
    source = (ROOT / "infra/systemd/eom-image-science-visual-pilot@.service").read_text(
        encoding="utf-8"
    )

    assert "User=eom-image" in source
    assert "Group=eom-image" in source
    assert "eom-local-image-trainer science-corpus-visual-pilot" in source
    assert "/srv/eom/image-training-workspaces/%i/command.json" in source
    assert "--gpu-lock" not in source
    assert "PrivateNetwork=true" in source
    assert "PrivateDevices=true" in source
    assert "NoNewPrivileges=true" in source
    assert "ReadWritePaths=/srv/eom/image-training-workspaces/%i" in source
    assert "InaccessiblePaths=/mnt/nas" in source
    assert "InaccessiblePaths=/home/eom/EOM" in source
    assert "Restart=no" in source


def test_local_image_micro_probe_unit_is_evaluation_only_and_nas_inaccessible() -> None:
    source = (ROOT / "infra/systemd/eom-image-lora-micro-probe@.service").read_text(
        encoding="utf-8"
    )

    assert "User=eom-image" in source
    assert "Group=eom-image" in source
    assert "eom-local-image-trainer micro-probe" in source
    assert "/srv/eom/image-training-workspaces/%i/command.json" in source
    assert "--gpu-lock /var/lib/eom-image/gpu0.lock" in source
    assert "Environment=CUBLAS_WORKSPACE_CONFIG=:4096:8" in source
    assert "PrivateNetwork=true" in source
    assert "NoNewPrivileges=true" in source
    assert "ReadOnlyPaths=/srv/eom/models/image" in source
    assert "ReadWritePaths=/srv/eom/image-training-workspaces/%i" in source
    assert "InaccessiblePaths=/mnt/nas" in source
    assert "InaccessiblePaths=/home/eom/EOM" in source
    assert "Restart=no" in source


def test_science_micro_probe_unit_is_evaluation_only_and_nas_inaccessible() -> None:
    source = (ROOT / "infra/systemd/eom-image-science-lora-micro-probe@.service").read_text(
        encoding="utf-8"
    )

    assert "User=eom-image" in source
    assert "Group=eom-image" in source
    assert "eom-local-image-trainer science-micro-probe" in source
    assert "/srv/eom/image-training-workspaces/%i/command.json" in source
    assert "--gpu-lock /var/lib/eom-image/gpu0.lock" in source
    assert "Environment=CUBLAS_WORKSPACE_CONFIG=:4096:8" in source
    assert "PrivateNetwork=true" in source
    assert "NoNewPrivileges=true" in source
    assert "ReadOnlyPaths=/srv/eom/models/image" in source
    assert "ReadWritePaths=/srv/eom/image-training-workspaces/%i" in source
    assert "InaccessiblePaths=/mnt/nas" in source
    assert "InaccessiblePaths=/home/eom/EOM" in source
    assert "Restart=no" in source


def test_science_campaign_micro_probe_unit_is_evaluation_only_and_nas_inaccessible() -> None:
    source = (
        ROOT / "infra/systemd/eom-image-science-campaign-lora-micro-probe@.service"
    ).read_text(encoding="utf-8")

    assert "User=eom-image" in source
    assert "Group=eom-image" in source
    assert "eom-local-image-trainer science-campaign-micro-probe" in source
    assert "/srv/eom/image-training-workspaces/%i/command.json" in source
    assert "--gpu-lock /var/lib/eom-image/gpu0.lock" in source
    assert "Environment=CUBLAS_WORKSPACE_CONFIG=:4096:8" in source
    assert "PrivateNetwork=true" in source
    assert "NoNewPrivileges=true" in source
    assert "ReadOnlyPaths=/srv/eom/models/image" in source
    assert "ReadWritePaths=/srv/eom/image-training-workspaces/%i" in source
    assert "InaccessiblePaths=/mnt/nas" in source
    assert "InaccessiblePaths=/home/eom/EOM" in source
    assert "Restart=no" in source


def test_local_image_micro_evaluation_unit_is_isolated_and_nas_inaccessible() -> None:
    source = (ROOT / "infra/systemd/eom-image-lora-micro-evaluation@.service").read_text(
        encoding="utf-8"
    )

    assert "User=eom-image" in source
    assert "Group=eom-image" in source
    assert "eom-local-image-trainer evaluate-micro-probe" in source
    assert "/srv/eom/image-training-workspaces/%i/command.json" in source
    assert "--gpu-lock /var/lib/eom-image/gpu0.lock" in source
    assert "Environment=CUBLAS_WORKSPACE_CONFIG=:4096:8" in source
    assert "PrivateNetwork=true" in source
    assert "NoNewPrivileges=true" in source
    assert "ReadOnlyPaths=/srv/eom/models/image" in source
    assert "ReadWritePaths=/srv/eom/image-training-workspaces/%i" in source
    assert "InaccessiblePaths=/mnt/nas" in source
    assert "InaccessiblePaths=/home/eom/EOM" in source
    assert "Restart=no" in source


def test_science_micro_evaluation_unit_is_isolated_and_nas_inaccessible() -> None:
    source = (ROOT / "infra/systemd/eom-image-science-lora-micro-evaluation@.service").read_text(
        encoding="utf-8"
    )

    assert "User=eom-image" in source
    assert "Group=eom-image" in source
    assert "eom-local-image-trainer evaluate-science-micro-probe" in source
    assert "/srv/eom/image-training-workspaces/%i/command.json" in source
    assert "--gpu-lock /var/lib/eom-image/gpu0.lock" in source
    assert "Environment=CUBLAS_WORKSPACE_CONFIG=:4096:8" in source
    assert "PrivateNetwork=true" in source
    assert "NoNewPrivileges=true" in source
    assert "ReadOnlyPaths=/srv/eom/models/image" in source
    assert "ReadWritePaths=/srv/eom/image-training-workspaces/%i" in source
    assert "InaccessiblePaths=/mnt/nas" in source
    assert "InaccessiblePaths=/home/eom/EOM" in source
    assert "Restart=no" in source


def test_science_campaign_micro_evaluation_unit_is_isolated_and_nas_inaccessible() -> None:
    source = (
        ROOT / "infra/systemd/eom-image-science-campaign-lora-micro-evaluation@.service"
    ).read_text(encoding="utf-8")

    assert "User=eom-image" in source
    assert "Group=eom-image" in source
    assert "eom-local-image-trainer evaluate-science-campaign-micro-probe" in source
    assert "/srv/eom/image-training-workspaces/%i/command.json" in source
    assert "--gpu-lock /var/lib/eom-image/gpu0.lock" in source
    assert "Environment=CUBLAS_WORKSPACE_CONFIG=:4096:8" in source
    assert "PrivateNetwork=true" in source
    assert "NoNewPrivileges=true" in source
    assert "ReadOnlyPaths=/srv/eom/models/image" in source
    assert "ReadWritePaths=/srv/eom/image-training-workspaces/%i" in source
    assert "InaccessiblePaths=/mnt/nas" in source
    assert "InaccessiblePaths=/home/eom/EOM" in source
    assert "Restart=no" in source


def test_science_subject_multiseed_unit_is_isolated_and_nas_inaccessible() -> None:
    source = (ROOT / "infra/systemd/eom-image-science-subject-multiseed@.service").read_text(
        encoding="utf-8"
    )

    assert "User=eom-image" in source
    assert "Group=eom-image" in source
    assert "eom-local-image-trainer science-subject-multiseed" in source
    assert "/srv/eom/image-training-workspaces/%i/command.json" in source
    assert "--gpu-lock /var/lib/eom-image/gpu0.lock" in source
    assert "Environment=CUBLAS_WORKSPACE_CONFIG=:4096:8" in source
    assert "PrivateNetwork=true" in source
    assert "NoNewPrivileges=true" in source
    assert "ReadOnlyPaths=/srv/eom/models/image" in source
    assert "ReadWritePaths=/srv/eom/image-training-workspaces/%i" in source
    assert "InaccessiblePaths=/mnt/nas" in source
    assert "InaccessiblePaths=/home/eom/EOM" in source
    assert "Restart=no" in source


def test_polkit_grants_only_exact_local_image_instances_to_runner() -> None:
    source = (ROOT / "infra/polkit/50-eom-worker-units.rules").read_text(encoding="utf-8")

    assert "eom-image-provider@imgreq_" in source
    assert "eom-image-reference-acquirer@imgrefcmd_" in source
    assert "eom-image-reference-discoverer@imgrefdiscover_" in source
    assert "eom-image-reference-provider@imgreq_" in source
    assert "eom-image-trainer@imgtrainrun_" in source
    assert "eom-image-lora-micro-probe@imgmicrotrainrun_" in source
    assert "eom-image-science-lora-micro-probe@imgscimicrotrainrun_" in source
    assert "eom-image-lora-micro-evaluation@imgmicroevalrun_" in source
    assert "eom-image-science-lora-micro-evaluation@imgscimicroevalrun_" in source
    assert "eom-image-science-campaign-lora-micro-evaluation@imgscicampaignmicroevalrun_" in source
    assert "eom-image-science-subject-benchmark@imgscisubjectbenchmarkrun_" in source
    assert "eom-image-science-subject-multiseed@imgscisubjectmultiseedrun_" in source
    assert "eom-image-crop-locator@imgcroplocator_" in source
    assert "eom-image-science-visual-pilot@imgscivisattempt_" in source
    assert "localImageUnit.test(unit)" in source
    assert "localImageScienceMicroProbeUnit.test(unit)" in source
    assert re.search(
        r"subject\.user === \"eom-workflow-runner\"[\s\S]+localImageUnit\.test\(unit\)",
        source,
    )
    assert 'subject.user === "eom-image"' not in source


def test_runner_can_stage_handoff_but_cannot_read_model_bytes() -> None:
    source = (ROOT / "infra/systemd/eom-workflow-runner.service").read_text(encoding="utf-8")

    assert "SupplementaryGroups=" in source and "eom-image" in source
    assert "eom-image-reference" in source
    assert "ReadOnlyPaths=/etc/eom/local-image-provider.json" in source
    assert "ReadWritePaths=/srv/eom/image-workspaces" in source
    assert "ReadWritePaths=/srv/eom/image-reference-workspaces" in source
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
    assert "peft-0.17.1-*.whl" in deploy
    assert 'metadata.version("peft") == "0.17.1"' in deploy
    assert "eom-image-reference-acquirer@.service" in deploy
    assert "eom-image-reference-discoverer@.service" in deploy
    assert "eom-image-reference" in deploy
    assert "RUNNER_RESTART_REQUIRED=YES" in deploy
    assert "systemctl restart" not in deploy
    assert "chmod -R" not in deploy and "chown -R" not in deploy
    assert "stat -c '%U:%G:%a' /etc/eom" in deploy
    assert '"root:root:755"' in deploy
    assert "LOCAL_IMAGE_SHARED_CONFIG_ROOT_DRIFT" in deploy
    assert "install -d -o root -g eom -m 0750 /etc/eom" not in deploy
    assert 'install -o root -g root -m 0644 "${BINDING_SOURCE}"' in deploy
    assert "os.walk(files_root, followlinks=False)" in normalize
    assert "manifest.files" in normalize

    trainer_build = (ROOT / "scripts/image_trainer/build_release.sh").read_text(encoding="utf-8")
    trainer_deploy = (ROOT / "scripts/image_trainer/deploy_runtime.sh").read_text(encoding="utf-8")
    science_evaluation_stage = (
        ROOT / "scripts/image_trainer/stage_science_micro_evaluation.py"
    ).read_text(encoding="utf-8")
    assert "eom_image_trainer/science_micro_probe_runner.py" in trainer_build
    assert "eom_image_trainer/science_micro_evaluation_runner.py" in trainer_build
    assert "eom_image_trainer/science_subject_benchmark_runner.py" in trainer_build
    assert "eom_image_trainer/science_subject_multiseed_runner.py" in trainer_build
    assert "eom-image-science-lora-micro-probe@.service" in trainer_deploy
    assert "eom-image-science-lora-micro-evaluation@.service" in trainer_deploy
    assert "eom-image-science-campaign-lora-micro-evaluation@.service" in trainer_deploy
    assert "eom-image-science-subject-benchmark@.service" in trainer_deploy
    assert "eom-image-science-subject-multiseed@.service" in trainer_deploy
    assert '"${SCIENCE_MICRO_PROBE_UNIT_TARGET}"' in trainer_deploy
    assert "content_json_bytes(command.model_dump" in science_evaluation_stage
    assert "from eom_identifiers import canonical_json_bytes" not in science_evaluation_stage


def test_local_image_release_scripts_have_valid_syntax() -> None:
    for relative in (
        "scripts/image_provider/build_release.sh",
        "scripts/image_provider/deploy_runtime.sh",
        "scripts/image_trainer/build_release.sh",
        "scripts/image_trainer/deploy_runtime.sh",
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
    for relative in (
        "scripts/image_trainer/stage_crop_locator.py",
        "scripts/image_trainer/publish_crop_locator_result.py",
        "scripts/image_trainer/stage_micro_probe.py",
        "scripts/image_trainer/stage_science_micro_probe.py",
        "scripts/image_trainer/stage_micro_evaluation.py",
        "scripts/image_trainer/stage_science_micro_evaluation.py",
        "scripts/image_trainer/publish_science_micro_evaluation.py",
        "scripts/image_trainer/stage_science_subject_benchmark.py",
        "scripts/image_trainer/stage_science_subject_multiseed.py",
        "scripts/image_trainer/publish_science_subject_multiseed_plan.py",
        "scripts/image_trainer/publish_science_subject_multiseed_result.py",
        "scripts/image_trainer/publish_science_subject_multiseed_review.py",
    ):
        compile(
            (ROOT / relative).read_text(encoding="utf-8"),
            Path(relative).name,
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
    assert "subtle sparse flat-gray scientific background shapes" in source
    assert "pale blue" not in source
    assert 'grp.getgrnam("eom-image")' in source
    assert "provider_group.gr_gid not in os.getgroups()" in source
    assert "shutil.rmtree(workspace)" in source
    assert "WorkflowCatalogService" not in source
    assert "session" not in source.lower()


def test_local_image_unit_has_valid_systemd_syntax_when_analyzer_is_available(
    tmp_path: Path,
) -> None:
    if shutil.which("systemd-analyze") is None:
        return
    try:
        pwd.getpwnam("eom-image")
    except KeyError:
        return
    for unit in (
        ROOT / "infra/systemd/eom-image-provider@.service",
        ROOT / "infra/systemd/eom-image-reference-acquirer@.service",
        ROOT / "infra/systemd/eom-image-reference-discoverer@.service",
        ROOT / "infra/systemd/eom-image-reference-provider@.service",
        ROOT / "infra/systemd/eom-image-reference-style-provider@.service",
        ROOT / "infra/systemd/eom-image-trainer@.service",
        ROOT / "infra/systemd/eom-image-lora-micro-probe@.service",
        ROOT / "infra/systemd/eom-image-science-lora-micro-probe@.service",
        ROOT / "infra/systemd/eom-image-lora-micro-evaluation@.service",
        ROOT / "infra/systemd/eom-image-science-lora-micro-evaluation@.service",
        ROOT / "infra/systemd/eom-image-science-campaign-lora-micro-evaluation@.service",
        ROOT / "infra/systemd/eom-image-science-subject-benchmark@.service",
        ROOT / "infra/systemd/eom-image-science-subject-multiseed@.service",
        ROOT / "infra/systemd/eom-image-crop-locator@.service",
        ROOT / "infra/systemd/eom-image-science-visual-pilot@.service",
    ):
        verified_unit = unit
        if (
            unit.name
            in {
                "eom-image-trainer@.service",
                "eom-image-lora-micro-probe@.service",
                "eom-image-science-lora-micro-probe@.service",
                "eom-image-lora-micro-evaluation@.service",
                "eom-image-science-lora-micro-evaluation@.service",
                "eom-image-science-campaign-lora-micro-evaluation@.service",
                "eom-image-crop-locator@.service",
                "eom-image-science-visual-pilot@.service",
            }
            and not Path(
                "/srv/eom/conda/envs/eom-image-trainer/bin/eom-local-image-trainer"
            ).is_file()
        ):
            verified_unit = tmp_path / unit.name
            verified_unit.write_text(
                "\n".join(
                    "ExecStart=/usr/bin/true" if line.startswith("ExecStart=") else line
                    for line in unit.read_text(encoding="utf-8").splitlines()
                )
                + "\n",
                encoding="utf-8",
            )
        completed = subprocess.run(
            ["systemd-analyze", "verify", str(verified_unit)],
            capture_output=True,
            check=False,
            text=True,
        )
        assert completed.returncode == 0, completed.stderr
