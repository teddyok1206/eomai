import subprocess
from pathlib import Path

from eom_catalog_service.settings import CATALOG_FIXED_STAGING_ROOTS

ROOT = Path(__file__).resolve().parents[2]


def test_runtime_bootstrap_is_exact_and_non_recursive() -> None:
    source = (ROOT / "scripts/workflow/bootstrap_runtime_paths.sh").read_text(encoding="utf-8")
    assert '[[ "${EUID}" -eq 0 ]]' in source
    assert "/srv/eom/staging/catalog" in source
    assert "/srv/eom/staging/catalog/content-packs" in source
    assert "/srv/eom/staging/catalog/registry" in source
    assert "/srv/eom/staging/catalog/workflow-prompts" in source
    assert "/srv/eom/workspaces" in source
    assert "chmod -R" not in source
    assert "chown -R" not in source
    assert "\nsudo " not in source
    assert "2770" in source and "0750" in source
    assert "find " not in source


def test_runtime_verifier_includes_all_fixed_catalog_staging_boundaries() -> None:
    source = (ROOT / "scripts/workflow/verify_runtime_paths.sh").read_text(encoding="utf-8")
    assert "/srv/eom/staging/catalog/content-packs" in source
    assert "/srv/eom/staging/catalog/registry" in source
    assert "/srv/eom/staging/catalog/workflow-prompts" in source
    assert "eom:eom:750" in source
    assert "mktemp -d" in source
    assert ".eom-runtime-probe." in source


def test_runtime_scripts_match_typed_fixed_catalog_inventory() -> None:
    expected = {
        str(definition.path_beneath(Path("/srv/eom/staging/catalog")))
        for definition in CATALOG_FIXED_STAGING_ROOTS
    }
    assert expected == {
        "/srv/eom/staging/catalog/content-packs",
        "/srv/eom/staging/catalog/registry",
        "/srv/eom/staging/catalog/workflow-prompts",
    }
    for relative in (
        "scripts/workflow/bootstrap_runtime_paths.sh",
        "scripts/workflow/verify_runtime_paths.sh",
    ):
        source = (ROOT / relative).read_text(encoding="utf-8")
        assert all(path in source for path in expected)
        assert "chmod -R" not in source
        assert "chown -R" not in source


def test_systemd_authorization_verifier_is_nonprivileged_and_negative_by_default() -> None:
    source = (ROOT / "scripts/workflow/verify_systemd_worker_authorization.sh").read_text(
        encoding="utf-8"
    )
    assert "sudo" not in source
    assert "codex" not in source.lower()
    assert "--uid=root --gid=root /usr/bin/true" in source
    assert "restart" in source
    assert "malformed.service" in source
    assert "eom-worker-auth-status" in source
    assert "eom-worker-auth-${slot}.service" in source


def test_runtime_scripts_have_valid_shell_syntax() -> None:
    for relative in (
        "scripts/workflow/bootstrap_runtime_paths.sh",
        "scripts/workflow/check_no_active_worker_leases.py",
        "scripts/workflow/deploy_runner_service.sh",
        "scripts/workflow/deploy_worker_runtime.sh",
        "scripts/workflow/install_runner_configuration.sh",
        "scripts/workflow/provision_worker_slot06.sh",
        "scripts/workflow/verify_runtime_paths.sh",
        "scripts/workflow/verify_systemd_worker_authorization.sh",
    ):
        if relative.endswith(".py"):
            compile((ROOT / relative).read_text(encoding="utf-8"), relative, "exec")
            continue
        result = subprocess.run(
            ["bash", "-n", str(ROOT / relative)],
            capture_output=True,
            check=False,
            text=True,
        )
        assert result.returncode == 0, result.stderr


def test_worker_runtime_doctor_receives_each_slot_group_explicitly() -> None:
    source = (ROOT / "scripts/workflow/deploy_worker_runtime.sh").read_text(encoding="utf-8")

    for slot in range(1, 7):
        assert f"-G eom-cdx-{slot:02d}" in source
    assert "eom-cdx-01,eom-cdx-02" not in source
    assert "EOM_STAGING_ROOT=/var/lib/eom-workflow-runner/orchestrator-staging" in source
    assert "eom-workflow-runner:eom:700" in source


def test_worker_runtime_deployment_fails_closed_on_durable_lease() -> None:
    deployer = (ROOT / "scripts/workflow/deploy_worker_runtime.sh").read_text(encoding="utf-8")
    guard = (ROOT / "scripts/workflow/check_no_active_worker_leases.py").read_text(encoding="utf-8")

    assert "check_no_active_worker_leases.py" in deployer
    assert "runuser -u eom-workflow-runner -g eom --" in deployer
    assert "an active or reconciling worker lease blocks runtime deployment" in deployer
    assert 'WorkerLeaseRecord.state.in_(("ACTIVE", "RECONCILING"))' in guard
    assert "DELETE" not in guard
    assert "UPDATE" not in guard


def test_worker_runtime_reloads_auth_broker_under_the_reviewed_slot06_groups() -> None:
    deployer = (ROOT / "scripts/workflow/deploy_worker_runtime.sh").read_text(encoding="utf-8")
    broker = (ROOT / "infra/systemd/eom-codex-auth-broker.service").read_text(encoding="utf-8")

    assert 'systemctl stop "${BROKER_SERVICE}"' in deployer
    assert 'systemctl start "${BROKER_SERVICE}"' in deployer
    assert 'systemctl enable "${BROKER_SERVICE}"' in deployer
    assert "BROKER_STOPPED" in deployer
    assert "eom-cdx-06" in broker
    assert "ReadOnlyPaths=-/run/eom-codex-login-06" in broker


def test_worker_runtime_atomically_installs_reviewed_six_slot_inventory() -> None:
    deployer = (ROOT / "scripts/workflow/deploy_worker_runtime.sh").read_text(encoding="utf-8")

    assert "WORKER_CONFIG_SOURCE=${REPOSITORY}/config/worker-slots.example.yaml" in deployer
    assert "WORKER_CONFIG_TARGET=/etc/eom/worker-slots.yaml" in deployer
    assert 'require_regular "${WORKER_CONFIG_TARGET}" root:eom:640' in deployer
    assert "mktemp /etc/eom/.worker-slots.XXXXXX" in deployer
    assert 'install -o root -g eom -m 0640 "${WORKER_CONFIG_SOURCE}"' in deployer
    assert 'mv -f "${WORKER_CONFIG_TEMPORARY}" "${WORKER_CONFIG_TARGET}"' in deployer
    assert 'cmp -s "${WORKER_CONFIG_SOURCE}" "${WORKER_CONFIG_TARGET}"' in deployer
    assert "worker_inventory_sha256=" in deployer
    assert "WorkerRegistry.load(Path(sys.argv[1]))" in deployer


def test_slot06_identity_provisioning_is_scoped_and_non_disruptive() -> None:
    source = (ROOT / "scripts/workflow/provision_worker_slot06.sh").read_text(encoding="utf-8")

    assert "eom-cdx-06" in source
    assert "--no-create-home" in source
    assert "--shell /usr/sbin/nologin" in source
    assert 'usermod --append --groups "${WORKER}" "${RUNNER}"' in source
    assert "for forbidden in eom sudo docker lxd adm" in source
    assert "systemctl" not in source
    assert "\nsudo " not in source
    assert "service_restart=NONE" in source


def test_worker_runtime_deployer_installs_and_smokes_bubblewrap_profile() -> None:
    deployer = (ROOT / "scripts/workflow/deploy_worker_runtime.sh").read_text(encoding="utf-8")
    profile = (ROOT / "infra/apparmor/eom-codex-bwrap").read_text(encoding="utf-8")

    assert "profile eom-codex-bwrap " in profile
    assert "codex-resources/bwrap flags=(unconfined)" in profile
    assert "userns," in profile
    assert "capability" not in profile
    assert "network," not in profile
    assert "apparmor_restrict_unprivileged_userns=0" not in deployer
    assert '"${APPARMOR_PARSER}" -Q -K "${APPARMOR_SOURCE}"' in deployer
    assert '"${APPARMOR_PARSER}" -r -K "${APPARMOR_TARGET}"' in deployer
    assert "systemd-run --quiet --wait --collect --service-type=oneshot" in deployer
    assert 'run_fixed_worker_sandbox_smoke "${CAPABILITY_SMOKE_UNIT}"' in deployer
    assert 'run_fixed_worker_sandbox_smoke "${BWRAP_SMOKE_UNIT}"' in deployer
    assert "--unshare-all --die-with-parent --new-session" in deployer
    assert "--property=ProtectKernelTunables=no" in deployer
    assert "--property=CapabilityBoundingSet=" in deployer
    assert "--property=AmbientCapabilities=" in deployer
    assert "^CapPrm:[[:space:]]+" in deployer
    assert "^CapEff:[[:space:]]+" in deployer
    assert "^CapAmb:[[:space:]]+" in deployer
    assert "0000000000000000" in deployer
    assert "CAP_CHOWN" not in deployer
    assert "CAP_SYS_ADMIN" not in deployer
    assert "CAP_NET_ADMIN" not in deployer
    assert "Codex Bubblewrap must not have file capabilities" in deployer
    assert "RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6 AF_NETLINK" in deployer
    assert "AF_PACKET" not in deployer


def test_runner_configuration_installs_root_owned_capability_policy() -> None:
    source = (ROOT / "scripts/workflow/install_runner_configuration.sh").read_text(encoding="utf-8")

    assert "config/workflows/knowledge-analysis.v8.yaml" in source
    assert "config/workflows/knowledge-analysis.v6.yaml" not in source
    assert (ROOT / "config/workflows/knowledge-analysis.v2.yaml").is_file()
    assert (ROOT / "config/workflows/knowledge-analysis.v1.yaml").is_file()
    assert "/knowledge-analysis.yaml" in source
    assert "config/workflows/legacy-item-extraction.v1.yaml" in source
    assert "/legacy-item-extraction.yaml" in source
    assert "config/workflows/legacy-item-editorial-compatibility.v1.yaml" in source
    assert "/legacy-item-editorial-compatibility.yaml" in source
    assert "content/prompt-templates/placeholders/support.txt" in source
    assert "/support.txt" in source
    assert "content/prompt-templates/placeholders/legacy-item-extraction.txt" in source
    assert "/legacy-item-extraction.txt" in source
    assert "content/prompt-templates/placeholders/legacy-item-editorial-compatibility.txt" in source
    assert "/legacy-item-editorial-compatibility.txt" in source
    assert "config/codex-capabilities.example.yaml" in source
    assert "/codex-capabilities.yaml" in source
    assert "install -o root -g root -m 0644" in source
    assert "root:root:644" in source
    assert "sudo" not in source
