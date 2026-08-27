from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def _source(relative: str) -> str:
    return (REPOSITORY_ROOT / relative).read_text(encoding="utf-8")


def _shell_commands(source: str) -> tuple[str, ...]:
    commands: list[str] = []
    continued = ""
    for raw_line in source.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        continued += (" " if continued else "") + line.removesuffix("\\").rstrip()
        if line.endswith("\\"):
            continue
        commands.append(continued)
        continued = ""
    return tuple(commands)


def test_service_user_bootstrap_preserves_secret_directory_boundary() -> None:
    source = _source("scripts/api/bootstrap_service_user.sh")

    assert "chmod o+x" not in source
    assert "chmod 0751" not in source
    assert "chmod 0711" not in source
    assert "root:eom:750" in source
    assert "usermod" not in source


def test_runtime_doctor_does_not_access_secret_path() -> None:
    source = _source("apps/application_api/eom_api/cli.py")

    assert "/etc/eom/secrets" not in source
    assert "secret_file_permission" not in source
    assert '"secret_environment"' in source


def test_systemd_manager_reads_secret_and_runtime_reads_service_config() -> None:
    source = _source("infra/systemd/eom-api.service")
    metadata = _source("scripts/api/verify_deployment_metadata.sh")
    verifier = _source("apps/application_api/eom_api/runtime_isolation_verifier.py")

    assert "EnvironmentFile=/etc/eom/secrets/api.env" in source
    assert "Environment=EOM_API_CONFIG=/etc/eom-api/api.yaml" in source
    assert "ReadOnlyPaths=/etc/eom-api/api.yaml" in source
    assert "ReadOnlyPaths=/etc/eom/api.yaml" not in source
    assert 'check_metadata "${SECRET_DIRECTORY}" "root:eom:750"' in metadata
    assert "eom-api must not belong to the eom group" in metadata
    start = verifier.index('"api_environment_read",')
    end = verifier.index("    ProbeSpec(", start)
    inventory = verifier[start:end]
    assert "AccessExpectation.DENIED" in inventory
    assert "systemd manager supplies the environment" in inventory


def test_deploy_release_uses_only_noninteractive_sudo() -> None:
    source = _source("scripts/api/deploy_release.sh")
    commands = _shell_commands(source)
    sudo_commands = [command for command in commands if re.search(r"(^|[;&|]\s*)sudo\s", command)]

    assert sudo_commands
    assert all(re.search(r"(^|[;&|]\s*)sudo\s+-n(?:\s|$)", command) for command in sudo_commands)
    assert not any("sudo -v" in command for command in commands)
    assert 'EXPECTED_BRANCHES=("main"' in source


def test_all_release_builders_accept_reviewed_main_commits() -> None:
    for relative in (
        "scripts/api/deploy_release.sh",
        "scripts/web_gui/build_release.sh",
        "scripts/observe/deploy_release.sh",
    ):
        source = _source(relative)
        assert 'EXPECTED_BRANCHES=("main"' in source
        assert "status --porcelain" in source
        assert "rev-parse HEAD" in source


def test_openapi_export_uses_repository_source_not_installed_runtime() -> None:
    source = _source("scripts/api/export_openapi.sh")

    assert "apps/application_api" in source
    assert 'export PYTHONPATH="${python_path}"' in source
    assert source.index('export PYTHONPATH="${python_path}"') < source.index(
        '"${PYTHON}" -m eom_api openapi export'
    )


def test_api_release_verifies_knowledge_contract_resources() -> None:
    source = _source("scripts/api/deploy_release.sh")

    for required in (
        "eom_catalog_contracts/knowledge.py",
        "eom_catalog_contracts/legacy_knowledge.py",
        "knowledge/knowledge-types-v1.schema.json",
        "knowledge/knowledge-analysis-request-v1.schema.json",
        "knowledge/knowledge-analysis-result-v1.schema.json",
        "knowledge/knowledge-analysis-types-v2.schema.json",
        "knowledge/knowledge-analysis-request-v2.schema.json",
        "knowledge/knowledge-analysis-worker-proposal-v1.schema.json",
        "knowledge/knowledge-analysis-proposal-receipt-v1.schema.json",
        "knowledge/knowledge-analysis-risk-policy-v1.schema.json",
        "knowledge/knowledge-analysis-review-decision-v1.schema.json",
        "knowledge/knowledge-analysis-result-v2.schema.json",
        "knowledge/knowledge-analysis-types-v3.schema.json",
        "knowledge/knowledge-analysis-types-v4.schema.json",
        "knowledge/knowledge-analysis-request-v3.schema.json",
        "knowledge/knowledge-analysis-request-v4.schema.json",
        "knowledge/knowledge-analysis-request-v5.schema.json",
        "knowledge/knowledge-analysis-request-v6.schema.json",
        "knowledge/knowledge-analysis-worker-proposal-v2.schema.json",
        "knowledge/knowledge-analysis-worker-proposal-v3.schema.json",
        "knowledge/knowledge-analysis-worker-proposal-v4.schema.json",
        "knowledge/knowledge-analysis-proposal-receipt-v2.schema.json",
        "knowledge/knowledge-analysis-proposal-receipt-v3.schema.json",
        "knowledge/knowledge-analysis-proposal-receipt-v4.schema.json",
        "knowledge/knowledge-analysis-proposal-receipt-v5.schema.json",
        "knowledge/knowledge-analysis-result-v3.schema.json",
        "knowledge/knowledge-analysis-result-v4.schema.json",
        "knowledge/knowledge-analysis-result-v5.schema.json",
        "knowledge/knowledge-analysis-result-v6.schema.json",
        "knowledge/knowledge-graph-projection-v1.schema.json",
        "knowledge/knowledge-graph-projection-v2.schema.json",
        "knowledge/knowledge-graph-publication-result-v1.schema.json",
        "knowledge/knowledge-graph-publication-v1.schema.json",
        "knowledge/knowledge-graph-snapshot-manifest-v1.schema.json",
        "knowledge/knowledge-graph-snapshot-manifest-v2.schema.json",
        "knowledge/knowledge-graph-snapshot-manifest-v3.schema.json",
        "knowledge/knowledge-graph-snapshot-manifest-v4.schema.json",
        "knowledge/knowledge-graph-structure-manifest-v1.schema.json",
        "knowledge/education-retrieval-access-policy-v1.schema.json",
        "knowledge/education-retrieval-request-v1.schema.json",
        "knowledge/education-retrieval-request-v2.schema.json",
        "knowledge/evidence-bundle-manifest-v1.schema.json",
        "knowledge/evidence-bundle-manifest-v2.schema.json",
        "knowledge/evidence-bundle-manifest-v3.schema.json",
        "knowledge/evidence-bundle-manifest-v4.schema.json",
        "knowledge/evidence-bundle-publication-result-v1.schema.json",
        "knowledge/educational-retrieval-requirement-v1.schema.json",
        "knowledge/evidence-bundle-publication-result-v2.schema.json",
        "knowledge/evidence-bundle-publication-result-v3.schema.json",
        "knowledge/evidence-bundle-publication-result-v4.schema.json",
        "legacy-knowledge/legacy-source-inventory-v1.schema.json",
        "legacy-knowledge/legacy-source-inventory-policy-v1.schema.json",
        "legacy-knowledge/legacy-source-inventory-v2.schema.json",
        "legacy-knowledge/legacy-source-relation-manifest-v1.schema.json",
        "legacy-knowledge/legacy-source-rights-review-v1.schema.json",
        "legacy-knowledge/legacy-source-rights-review-v2.schema.json",
        "legacy-knowledge/legacy-source-selection-v1.schema.json",
        "legacy-knowledge/legacy-source-selection-v2.schema.json",
        "legacy-knowledge/pdf-page-range-materialization-manifest-v1.schema.json",
        "legacy-knowledge/textbook-analysis-bundle-manifest-v1.schema.json",
        "legacy-knowledge/textbook-analysis-bundle-manifest-v2.schema.json",
        "educational-document/educational-document-registration-request-v2.schema.json",
        "educational-document/educational-document-revision-manifest-v2.schema.json",
        "educational-document/educational-document-registration-receipt-v2.schema.json",
        "catalog-application/catalog-application-request-v2.schema.json",
        "catalog-application/catalog-application-response-v2.schema.json",
        "catalog-application/catalog-application-request-v3.schema.json",
        "catalog-application/catalog-application-response-v3.schema.json",
        "catalog-application/catalog-application-request-v4.schema.json",
        "catalog-application/catalog-application-response-v4.schema.json",
        "catalog-application/catalog-application-request-v5.schema.json",
        "catalog-application/catalog-application-response-v5.schema.json",
        "catalog-application/catalog-application-response-v6.schema.json",
        "catalog-application/catalog-application-request-v6.schema.json",
        "catalog-application/catalog-application-request-v7.schema.json",
        "catalog-application/catalog-application-response-v7.schema.json",
        "catalog-application/catalog-application-response-v8.schema.json",
        "catalog-application/catalog-application-response-v9.schema.json",
        "knowledge/knowledge-analysis-batch-request-v1.schema.json",
        "knowledge/knowledge-analysis-batch-request-v2.schema.json",
        "legacy-usage/assessment-assembly-manifest-v1.schema.json",
        "legacy-usage/legacy-usage-import-manifest-v1.schema.json",
        "legacy-usage/legacy-usage-mapping-contract-v1.schema.json",
        "legacy-usage/legacy-usage-row-proposal-v1.schema.json",
        "legacy-usage/product-usage-graph-projection-v1.schema.json",
    ):
        assert required in source
    for required in (
        "eom_api/routers/knowledge_analysis.py",
        "eom_api/services/catalog_application_client.py",
        "eom_catalog_service/knowledge_analysis_risk.py",
        "eom_catalog_service/knowledge_analysis_service.py",
        "eom_catalog_service/knowledge_analysis_sources.py",
        "eom_catalog_service/legacy_usage_models.py",
        "eom_catalog_service/legacy_usage_service.py",
        "eom_catalog_service/legacy_knowledge_intake_service.py",
        "eom_catalog_service/legacy_source_inventory.py",
        "eomctl/knowledge.py",
        "eom_catalog_service/legacy_xlsx.py",
        "eom_catalog_service/runtime_privileges.py",
    ):
        assert required in source


def test_release_migration_wrapper_pins_source_and_database_owner() -> None:
    source = _source("scripts/api/migrate_release.sh")

    assert "env -u EOM_DATABASE_URL" in source
    assert 'EOM_POSTGRES_ENV="${POSTGRES_ENV}"' in source
    assert "PYTHONDONTWRITEBYTECODE=1" in source
    assert "PYTHONSAFEPATH=1" in source
    assert "working tree must be clean" in source
    assert "source commit mismatch" in source
    assert "database_user != schema_owner" in source
    assert '"app" not in search_path' in source
    assert "run_reviewed_python -m alembic upgrade head" in source
    assert "CURRENT_MIGRATION_REVISION" in source


def test_privileged_metadata_verifier_is_root_only_and_secret_safe() -> None:
    source = _source("scripts/api/verify_deployment_metadata.sh")

    assert '"$(id -u)" -ne 0' in source
    assert "EOM_API_DATABASE_URL" in source
    assert "EOM_API_TOKEN_HASH_KEY" in source
    assert "EOM_API_FINGERPRINT_KEY" in source
    assert "root:eom:750" in source
    assert "cat " not in source
    assert not re.search(
        r"printf[^\n]*EOM_API_(?:DATABASE_URL|TOKEN_HASH_KEY|FINGERPRINT_KEY)", source
    )


def test_privileged_metadata_verifier_rejects_secret_directory_mode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_id = tmp_path / "id"
    fake_id.write_text("#!/bin/sh\nprintf '0\\n'\n", encoding="ascii")
    fake_id.chmod(0o700)
    fake_stat = tmp_path / "stat"
    fake_stat.write_text("#!/bin/sh\nprintf 'root:eom:751\\n'\n", encoding="ascii")
    fake_stat.chmod(0o700)
    monkeypatch.setenv("PATH", f"{tmp_path}:{os.environ['PATH']}")

    completed = subprocess.run(
        ("bash", str(REPOSITORY_ROOT / "scripts/api/verify_deployment_metadata.sh")),
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 1
    assert "metadata mismatch" in completed.stderr
    assert "EOM_API_" not in completed.stdout + completed.stderr


def test_runtime_verifier_separates_host_metadata_from_service_access() -> None:
    source = _source("scripts/api/verify_runtime_isolation.sh")

    assert '"$(id -u)" -ne 0' in source
    assert 'SERVICE_CONTEXT_VERIFIER="/srv/eom/conda/envs/eom-api/bin/' in source
    assert '"${SERVICE_CONTEXT_VERIFIER}"' in source
    assert "nsenter --target" not in source
    assert "test ! -r" not in source
    assert "runuser -u eom-api" not in source
    assert 'systemctl show --property=InaccessiblePaths --value "${SERVICE}"' in source
    assert 'systemctl show --property=CapabilityBoundingSet --value "${SERVICE}"' in source


def test_service_context_helper_has_fixed_command_and_probe_inventory() -> None:
    source = _source("apps/application_api/eom_api/runtime_isolation_verifier.py")
    pidfd_source = _source("apps/application_api/eom_api/runtime_isolation_pidfd.py")

    assert '"/usr/bin/nsenter"' in source
    assert '"/usr/bin/setpriv"' in source
    assert '"--bounding-set=-all"' in source
    assert '"--reset-env"' in source
    assert 'FIXED_CHILD_ARGUMENT: Final = "--fixed-service-probe"' in source
    assert "shell=True" not in source
    assert "eval(" not in source
    assert "os.system" not in source
    assert "caller_path" not in source
    assert "print(message" not in source
    assert "os.pidfd_open(" not in source
    assert '_LIBC_PIDFD_SYMBOL: Final = "pidfd_open"' in pidfd_source
    assert "syscall(" not in pidfd_source
    assert "shell=True" not in pidfd_source
    assert "PidfdBackend.NONE" in pidfd_source
    assert "use_main_pid" not in pidfd_source


def test_release_installs_runtime_verifier_and_packages_fixed_helper() -> None:
    deployment = _source("scripts/api/deploy_release.sh")
    package = _source("apps/application_api/pyproject.toml")

    assert (
        'RUNTIME_VERIFIER_TARGET="/usr/local/libexec/eom-api/verify-runtime-isolation"'
        in deployment
    )
    assert '"${RUNTIME_VERIFIER_SOURCE}" "${RUNTIME_VERIFIER_TARGET}"' in deployment
    assert 'sudo -n "${RUNTIME_VERIFIER_TARGET}"' in deployment
    invocation_marker = "runtime_isolation_verifier_invocation=START"
    assert invocation_marker in deployment
    assert deployment.index(invocation_marker) < deployment.index(
        'sudo -n "${RUNTIME_VERIFIER_TARGET}"'
    )
    assert '"eom_api/runtime_isolation_verifier.py"' in deployment
    assert '"eom_api/runtime_isolation_pidfd.py"' in deployment
    assert "runtime isolation console entry point missing" in deployment
    assert "runtime_isolation_verifier_capability=READY" in deployment
    assert "eom_api.runtime_isolation_verifier --capabilities" in deployment
    assert 'eom-api-runtime-isolation = "eom_api.runtime_isolation_verifier:main"' in package


def test_release_verifies_educational_document_schema_resources() -> None:
    deployment = _source("scripts/api/deploy_release.sh")

    for resource in (
        "educational-document-registration-receipt-v1.schema.json",
        "educational-document-registration-request-v1.schema.json",
        "educational-document-revision-manifest-v1.schema.json",
        "educational-document-rights-attestation-v1.schema.json",
        "educational-document-types-v1.schema.json",
    ):
        assert f'"educational-document/{resource}": ' in deployment
        assert f'"schemas/educational-document/{resource}"' in deployment


def test_release_verifies_curriculum_schema_resources() -> None:
    deployment = _source("scripts/api/deploy_release.sh")
    resource = "integrated-science-editorial-outline-v1.schema.json"

    assert f'"curriculum/{resource}": ' in deployment
    assert f'"schemas/curriculum/{resource}"' in deployment


def test_release_isolated_verifier_compiles_all_knowledge_analysis_definitions() -> None:
    deployment = _source("scripts/api/deploy_release.sh")

    assert (
        "analysis_v1, analysis_v2, analysis_v3, analysis_v4, analysis_v5, analysis_v6" in deployment
    )
    assert (
        "for path in (analysis_v1, analysis_v2, analysis_v3, analysis_v4, analysis_v5, analysis_v6)"
        in deployment
    )
    assert (
        'analysis_versions != {"1.0.0", "2.0.0", "3.0.0", "4.0.0", "5.0.0", "6.0.0"}' in deployment
    )


def test_release_install_normalizes_restrictive_operator_umask() -> None:
    deployment = _source("scripts/api/deploy_release.sh")
    install_body = deployment.partition("install_wheels() {")[2].partition("\n}")[0]

    assert "umask 022" in install_body
    install_command = "${API_PIP} install --no-deps --force-reinstall"
    assert install_command in install_body
    assert install_body.index("umask 022") < install_body.index(install_command)
    assert "runtime package ownership mismatch" in deployment
    assert "runtime package mode mismatch" in deployment
    assert "runtime entry point mode mismatch" in deployment
    assert "installed simulation mode mismatch" in deployment
    assert 'path.parent == installed_root / "bin"' in deployment


def test_shared_platform_release_restarts_every_long_lived_consumer() -> None:
    deployment = _source("scripts/api/deploy_release.sh")
    consumers = (
        "eom-catalog-application-runner.service",
        "eom-workflow-runner.service",
        "eom-hwpx-application-runner.service",
        "eom-api.service",
    )

    for consumer in consumers:
        assert f'"{consumer}"' in deployment
    assert 'for consumer in "${PLATFORM_CONSUMER_SERVICES[@]}"' in deployment
    assert 'sudo -n systemctl restart "${consumer}"' in deployment
    assert 'systemctl is-active --quiet "${consumer}"' in deployment
    assert 'systemctl is-enabled --quiet "${consumer}"' in deployment
    assert 'systemctl show --property=MainPID --value "${consumer}"' in deployment
    assert '"eom-workflow-runner",' in deployment


@pytest.mark.parametrize(
    "relative",
    [
        "scripts/api/bootstrap_service_user.sh",
        "scripts/api/deploy_release.sh",
        "scripts/api/migrate_release.sh",
        "scripts/api/verify_deployment_metadata.sh",
        "scripts/api/verify_runtime_isolation.sh",
    ],
)
def test_deployment_shell_has_valid_syntax(relative: str) -> None:
    completed = subprocess.run(
        ("bash", "-n", str(REPOSITORY_ROOT / relative)),
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr
