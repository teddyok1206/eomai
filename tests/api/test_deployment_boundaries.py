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
    assert "ReadOnlyPaths=/etc/eom/local-image-provider.json" in source
    assert "InaccessiblePaths=/srv/eom/models/image" in source
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
    assert "prepare_runtime_dependencies\n    build_release" in source
    assert "eom-codex-auth identity must be deployed before the API unit" in source
    assert 'scripts/api/migrate_release.sh"' in source
    assert '--verify "${COMMIT}"' in source
    assert (
        '"legacy-assessment/legacy-item-extraction-batch-v2.schema.json": '
        '"schemas/legacy-assessment/legacy-item-extraction-batch-v2.schema.json"'
    ) in source
    assert 'scripts/api/bootstrap_runtime_role.sh"' in source
    assert 'scripts/catalog/bootstrap_runtime_role.py"' in source
    assert 'scripts/hwpx/bootstrap_manager_runtime_role.py"' in source
    assert (
        'MOCK_EXAM_DEPLOYMENT_ADMISSION_TARGET="/usr/local/libexec/eom-api/'
        'verify-mock-exam-deployment-admission"'
    ) in source
    assert "sudo -n -u eom-api /usr/bin/env -i" in source
    assert '"${API_PYTHON}" -I "${MOCK_EXAM_DEPLOYMENT_ADMISSION_TARGET}"' in source
    assert source.index("verify_mock_exam_deployment_admission\n") < source.index(
        "prepare_runtime_dependencies\n"
    )
    assert source.count("    verify_mock_exam_deployment_admission\n") == 2
    assert source.rindex("    verify_mock_exam_deployment_admission\n") < source.index(
        "    install_wheels\n"
    )
    assert source.index("require_clean_tree\n") < source.index(
        "verify_mock_exam_deployment_admission\n"
    )
    assert (
        source.index("install_wheels\n")
        < source.index("reconcile_installed_catalog_runtime_privileges\n")
        < source.index("reconcile_installed_hwpx_manager_runtime_privileges\n")
        < source.index("install_service\n")
    )


def test_mock_exam_deployment_admission_uses_installed_unprivileged_contract_boundary() -> None:
    deployment = _source("scripts/api/deploy_release.sh")
    guard = _source("scripts/api/verify_mock_exam_deployment_admission.py")

    install = "sudo -n install -o root -g root -m 0755 \\\n"
    execute = "sudo -n -u eom-api /usr/bin/env -i"
    assert deployment.index(install) < deployment.index(execute)
    assert '"${API_PYTHON}" -I "${MOCK_EXAM_DEPLOYMENT_ADMISSION_TARGET}"' in deployment
    assert "from eom_api_contracts.mock_exam_execution import (" in guard
    assert "MockExamProductionExecutionV1," in guard
    assert "mock_exam_production_is_terminal," in guard
    assert 'CHECKPOINT_ROOT = Path("/var/lib/eom-api/mock-exam-production")' in guard
    assert "sys.path" not in guard
    assert "/home/eom/EOM" not in guard


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
        "knowledge/knowledge-analysis-types-v5.schema.json",
        "knowledge/knowledge-assessment-page-image-observation-v2.schema.json",
        "knowledge/knowledge-analysis-request-v3.schema.json",
        "knowledge/knowledge-analysis-request-v4.schema.json",
        "knowledge/knowledge-analysis-request-v5.schema.json",
        "knowledge/knowledge-analysis-request-v6.schema.json",
        "knowledge/knowledge-analysis-request-v9.schema.json",
        "knowledge/knowledge-analysis-worker-proposal-v2.schema.json",
        "knowledge/knowledge-analysis-worker-proposal-v3.schema.json",
        "knowledge/knowledge-analysis-worker-proposal-v4.schema.json",
        "knowledge/knowledge-analysis-proposal-receipt-v2.schema.json",
        "knowledge/knowledge-analysis-proposal-receipt-v3.schema.json",
        "knowledge/knowledge-analysis-proposal-receipt-v4.schema.json",
        "knowledge/knowledge-analysis-proposal-receipt-v5.schema.json",
        "knowledge/knowledge-analysis-proposal-receipt-v8.schema.json",
        "knowledge/knowledge-analysis-result-v3.schema.json",
        "knowledge/knowledge-analysis-result-v4.schema.json",
        "knowledge/knowledge-analysis-result-v5.schema.json",
        "knowledge/knowledge-analysis-result-v6.schema.json",
        "knowledge/knowledge-analysis-result-v9.schema.json",
        "knowledge/knowledge-analysis-worker-proposal-v7.schema.json",
        "knowledge/knowledge-graph-projection-v1.schema.json",
        "knowledge/knowledge-graph-projection-v2.schema.json",
        "knowledge/knowledge-graph-projection-v3.schema.json",
        "knowledge/knowledge-graph-publication-result-v1.schema.json",
        "knowledge/knowledge-graph-publication-v1.schema.json",
        "knowledge/knowledge-graph-publication-v2.schema.json",
        "knowledge/knowledge-graph-publication-v3.schema.json",
        "knowledge/knowledge-graph-publication-v4.schema.json",
        "knowledge/knowledge-graph-snapshot-manifest-v1.schema.json",
        "knowledge/knowledge-graph-snapshot-manifest-v2.schema.json",
        "knowledge/knowledge-graph-snapshot-manifest-v3.schema.json",
        "knowledge/knowledge-graph-snapshot-manifest-v4.schema.json",
        "knowledge/knowledge-graph-snapshot-manifest-v5.schema.json",
        "knowledge/knowledge-graph-snapshot-manifest-v6.schema.json",
        "knowledge/knowledge-graph-snapshot-manifest-v7.schema.json",
        "knowledge/knowledge-graph-structure-manifest-v1.schema.json",
        "knowledge/knowledge-graph-structure-manifest-v2.schema.json",
        "knowledge/knowledge-graph-structure-manifest-v3.schema.json",
        "knowledge/knowledge-graph-structure-manifest-v4.schema.json",
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
        "catalog-application/catalog-application-request-v8.schema.json",
        "catalog-application/catalog-application-response-v7.schema.json",
        "catalog-application/catalog-application-response-v8.schema.json",
        "catalog-application/catalog-application-response-v9.schema.json",
        "catalog-application/catalog-application-request-v10.schema.json",
        "catalog-application/catalog-application-response-v10.schema.json",
        "item-registry/assessment-item-content-v2.schema.json",
        "item-registry/assessment-item-content-v3.schema.json",
        "catalog-application/catalog-item-media-request-v1.schema.json",
        "catalog-application/catalog-item-media-response-v1.schema.json",
        "catalog-application/catalog-assessment-page-list-request-v1.schema.json",
        "catalog-application/catalog-assessment-page-list-response-v1.schema.json",
        "catalog-application/catalog-assessment-page-media-request-v1.schema.json",
        "catalog-application/catalog-assessment-page-media-response-v1.schema.json",
        "knowledge/knowledge-analysis-batch-request-v1.schema.json",
        "knowledge/knowledge-analysis-batch-request-v2.schema.json",
        "knowledge/knowledge-analysis-batch-request-v3.schema.json",
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


def test_api_release_verifies_local_image_runtime_and_contract_resources() -> None:
    source = _source("scripts/api/deploy_release.sh")

    for required in (
        "eom_image_contracts/models.py",
        "eom_image_contracts/validation.py",
        "eom_catalog_service/generated_stimulus.py",
        "eom_catalog_service/local_image_adapter.py",
        "eom_catalog_service/vector_stimulus.py",
        "eom_catalog_service/workflow_catalog.py",
        "local-image-model-manifest-v1.schema.json",
        "local-image-generation-request-v1.schema.json",
        "local-image-generation-receipt-v1.schema.json",
        "local-image-provider-binding-v1.schema.json",
        "local-image-composite-request-v1.schema.json",
        "local-image-composite-receipt-v1.schema.json",
        "Image Contract schema wheel resources mismatch",
        "Image Contract schema resource drift",
    ):
        assert required in source


def test_api_release_verifies_content_team_contract_runtime() -> None:
    source = _source("scripts/api/deploy_release.sh")

    for required in (
        "eom_hwpx_contracts/content_team_equations.py",
        "eom_hwpx_contracts/content_team_markdown.py",
        "eom_hwpx_contracts/models.py",
        "eom_hwpx_contracts/validation.py",
        "eom_hwpx_contracts/schemas/hwpx-content-team-exam-render-request-v2.schema.json",
        "eom_hwpx_contracts/schemas/hwpx-content-team-exam-build-result-v2.schema.json",
        "eom_hwpx_manager/content_team_exam_service.py",
        "eom_hwpx_manager/assembly_render_projection.py",
    ):
        assert required in source
    assert "eom_hwpx_builder/content_team_handoff.py" not in source
    assert "eom_hwpx_manager/content_team_markdown.py" not in source
    assert "eom_hwpx_manager/content_team_equations.py" not in source


def test_hwpx_release_verifies_content_team_handoff_runtime() -> None:
    source = _source("scripts/hwpx/deploy_builder.sh")

    assert "eom_hwpx_builder/content_team_handoff.py" in source
    assert "hwpx-content-team-exam-render-request-v2.schema.json" in source
    assert "hwpx-content-team-exam-build-result-v2.schema.json" in source


def test_content_team_font_installer_pins_exact_files_and_never_depends_on_eomis() -> None:
    source = _source("scripts/catalog/install_content_team_svg_fonts.sh")

    for required in (
        "/usr/local/share/fonts/eom",
        "SMJGothicStd-Regular.otf",
        "NotoSansCJKkr-Regular.otf",
        "CenturyOldStyle-Regular.otf",
        "CenturyOldStyle-Italic.otf",
        "9200e1e46cca77f0ff9481c5345c3333caf22d50487418df74f830e4221adea1",
        "6bcb2a0703aa137e874fc2dffa85f6c21ba9a67fa329e81b8c801663af7e992a",
        "7f9420403e10e7e74f002fbb48e8034d48f64cbdbef556d4f964b266043de338",
        "44b00cbdab9fdb7b4307db79784c5b90cbc52c5ffb0add32ac8239d73e567809",
        "--source-dir",
        "--korean-fallback-source",
        "--verify-only",
        "fc-cache",
        "fontconfig resolved an unexpected font",
    ):
        assert required in source
    assert "/home/eom/EOMIS" not in source
    assert "curl" not in source
    assert "wget" not in source
    assert "pip install" not in source


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
    assert 'EXPECTED_SUPPLEMENTARY_GROUPS="eom-codex-auth"' in source
    assert "service supplementary groups mismatch" in source


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


def test_release_verifies_mock_exam_assembly_protocol_and_policy_resources() -> None:
    deployment = _source("scripts/api/deploy_release.sh")

    for resource in (
        "mock-exam-assembly-cohort-v1.schema.json",
        "mock-exam-assembly-manifest-v1.schema.json",
        "mock-exam-assembly-manifest-v2.schema.json",
        "mock-exam-assembly-manifest-v3.schema.json",
        "mock-exam-assembly-plan-v1.schema.json",
        "mock-exam-assembly-plan-v2.schema.json",
        "mock-exam-production-plan-v2.schema.json",
        "mock-exam-assembly-policy-v1.schema.json",
        "mock-exam-layout-policy-v1.schema.json",
        "mock-exam-rating-policy-v1.schema.json",
    ):
        assert f'"assessment-assembly/{resource}": ' in deployment
        assert f'"schemas/assessment-assembly/{resource}"' in deployment
    assert "integrated-science-mock-exam-assembly-v1.json" in deployment
    assert "integrated-science-mock-exam-layout-v1.json" in deployment
    assert "integrated-science-item-rating-v1.json" in deployment
    assert '"content/assembly-policies" / policy_name' in deployment
    for runtime in (
        "eom_catalog_contracts/approved_item_graph_publication.py",
        "eom_catalog_contracts/item_review.py",
        "eom_catalog_contracts/mock_exam_planner.py",
        "eom_catalog_contracts/mock_exam_production_plan.py",
        "eom_catalog_service/approved_item_graph_publication_service.py",
        "eom_catalog_service/automatic_item_graph_publication_service.py",
        "eom_catalog_service/mock_exam_candidate_repository.py",
        "eom_catalog_service/mock_exam_item_review_publication_service.py",
        "eom_catalog_service/mock_exam_assembly_service.py",
        "eom_api/routers/assessment_assemblies.py",
        "eom_api/mock_exam_production_cli.py",
        "eom_api/services/mock_exam_generation_block_resolver.py",
        "eom_api/services/mock_exam_production_application.py",
        "eom_api/services/mock_exam_production_checkpoint_store.py",
        "eom_api/services/mock_exam_production_composition.py",
        "eom_api/services/mock_exam_production_coordinator.py",
        "eom_api/services/mock_exam_production_release_resolver.py",
        "eom_api/services/mock_exam_production_runner.py",
    ):
        assert f'"{runtime}"' in deployment


def test_release_verifies_mock_exam_production_protocol_resources() -> None:
    deployment = _source("scripts/api/deploy_release.sh")

    for resource in (
        "mock-exam-item-review-decision-v1.schema.json",
        "mock-exam-item-review-decision-v2.schema.json",
        "mock-exam-item-review-publication-command-v1.schema.json",
        "mock-exam-item-review-publication-result-v1.schema.json",
        "mock-exam-item-review-publication-result-v2.schema.json",
        "mock-exam-production-plan-v1.schema.json",
        "mock-exam-review-eligibility-query-v1.schema.json",
        "mock-exam-review-eligibility-result-v1.schema.json",
        "mock-exam-review-eligibility-result-v2.schema.json",
    ):
        assert f'"assessment-assembly/{resource}": ' in deployment
        assert f'"schemas/assessment-assembly/{resource}"' in deployment
    for resource in (
        "approved-item-graph-publication-command-v1.schema.json",
        "approved-item-graph-publication-result-v1.schema.json",
    ):
        assert f'"knowledge/{resource}": ' in deployment
        assert f'"schemas/knowledge/{resource}"' in deployment
    for resource in (
        "catalog-application-request-v11.schema.json",
        "catalog-application-response-v11.schema.json",
        "catalog-application-request-v12.schema.json",
        "catalog-application-response-v12.schema.json",
    ):
        assert f'"catalog-application/{resource}": ' in deployment
        assert f'"schemas/catalog-application/{resource}"' in deployment


def test_release_packages_curriculum_graph_capability_api_schema() -> None:
    deployment = _source("scripts/api/deploy_release.sh")

    assert "schemas != expected_api_schemas" in deployment
    assert "expected exactly 26 packaged API schemas" in deployment
    assert '"eom_api_contracts/schemas/item-bank-entry-v1.schema.json"' in deployment
    assert '"eom_api_contracts/schemas/production-item-candidate-v1.schema.json"' in deployment
    assert '"eom_api_contracts/schemas/production-item-candidate-v2.schema.json"' in deployment
    assert '"eom_api_contracts/schemas/mock-exam-assembly-plan-v1.schema.json"' in deployment
    assert '"eom_api_contracts/schemas/mock-exam-assembly-plan-v2.schema.json"' in deployment
    assert '"eom_api_contracts/schemas/curriculum-graph-capability-v1.schema.json"' in deployment
    assert '"eom_api_contracts/schemas/assessment-item-occurrence-v1.schema.json"' in deployment
    assert '"eom_api_contracts/schemas/assessment-item-occurrence-v2.schema.json"' in deployment
    assert '"eom_api_contracts/schemas/assessment-learning-batch-v1.schema.json"' in deployment
    assert '"eom_api_contracts/schemas/assessment-learning-exam-v1.schema.json"' in deployment
    assert '"eom_api_contracts/schemas/assessment-learning-page-v1.schema.json"' in deployment
    assert '"eom_api_contracts/schemas/mock-exam-production-execution-v1.schema.json"' in deployment
    assert '"eom_api_contracts/schemas/mock-exam-production-execution-v2.schema.json"' in deployment
    assert (
        '"eom_api_contracts/schemas/mock-exam-production-retirement-v1.schema.json"' in deployment
    )
    assert '"eom_api_contracts/schemas/mock-exam-review-eligibility-v1.schema.json"' in deployment
    assert '"eom_api_contracts/schemas/mock-exam-review-eligibility-v2.schema.json"' in deployment
    assert '"eom_api_contracts/schemas/hwpx-v2.schema.json"' in deployment
    assert '"eom_api_contracts/schemas/workflow-start-v1.schema.json"' in deployment
    assert '"eom_api_contracts/mock_exam_execution.py"' in deployment
    assert '"eom_api_contracts/item_bank.py"' in deployment
    assert '"eom_api_contracts/mock_exam_retirement.py"' in deployment
    assert '"eom_api_contracts/workflows.py"' in deployment
    assert '"eom_api/routers/item_bank.py"' in deployment
    assert "API schema resource drift" in deployment
    assert "API schema resource missing from RECORD" in deployment
    assert "packaged OpenAPI differs from canonical release artifacts" in deployment
    assert "packaged OpenAPI checksum mismatch" in deployment
    assert "mock-exam contract package exports are incomplete" in deployment
    assert "mock-exam terminal-state contract export is incomplete" in deployment
    assert "mock-exam retirement contract package exports are incomplete" in deployment
    assert "legacy Graph automation must preserve its local 1..16 batch contract" in deployment
    assert 'CURRENT_MIGRATION_REVISION != "20260908_0032"' in deployment


def test_release_verifies_assessment_occurrence_graph_schema_resources() -> None:
    deployment = _source("scripts/api/deploy_release.sh")

    for resource in (
        "item-origin/assessment-occurrence-revision-v2.schema.json",
        "knowledge/knowledge-types-v2.schema.json",
        "knowledge/knowledge-graph-projection-v4.schema.json",
        "knowledge/knowledge-graph-publication-v5.schema.json",
        "knowledge/knowledge-graph-snapshot-manifest-v8.schema.json",
        "knowledge/knowledge-graph-structure-manifest-v5.schema.json",
    ):
        assert f'"{resource}": ' in deployment
        assert f'"schemas/{resource}"' in deployment


def test_release_verifies_guidance_schema_resources() -> None:
    deployment = _source("scripts/api/deploy_release.sh")
    resource = "eom-guidance-markdown-control-v1.schema.json"

    assert f'"guidance/{resource}": ' in deployment
    assert f'"schemas/guidance/{resource}"' in deployment


def test_release_isolated_verifier_compiles_all_knowledge_analysis_definitions() -> None:
    deployment = _source("scripts/api/deploy_release.sh")

    assert (
        "analysis_v1, analysis_v2, analysis_v3, analysis_v4, analysis_v5, analysis_v6" in deployment
    )
    assert (
        "for path in (analysis_v1, analysis_v2, analysis_v3, analysis_v4, "
        "analysis_v5, analysis_v6, analysis_v7, analysis_v8, analysis_v9)" in deployment
    )
    assert (
        'analysis_versions != {"1.0.0", "2.0.0", "3.0.0", "4.0.0", '
        '"5.0.0", "6.0.0", "7.0.0", "8.0.0", "9.0.0"}' in deployment
    )
    assert 'load_role_input_schema("support", "workflow-role/1.18.0")' in deployment


def test_release_verifies_content_team_v3_installed_wheel_boundary() -> None:
    deployment = _source("scripts/api/deploy_release.sh")
    hwpx_deployment = _source("scripts/hwpx/deploy_builder.sh")
    runbook = _source("docs/architecture/CONTENT_TEAM_MOCK_EXAM_ITEM_PROTOCOL_V3.md")

    assert '"1.8", "1.9")' in deployment
    assert "definition_v1_8, definition_v1_9" in deployment
    assert '"1.7.0", "1.8.0", "1.9.0"}' in deployment
    for role in ("authoring", "image", "review", "item_management"):
        assert f'load_role_input_schema("{role}", "workflow-role/1.19.0")' in deployment
    for runtime in (
        "eom_image_contracts/safe_svg.py",
        "hwpx-content-team-editorial-question-v2.schema.json",
        "hwpx-content-team-render-request-v3.schema.json",
        "hwpx-content-team-build-result-v3.schema.json",
        "hwpx-content-team-exam-render-request-v3.schema.json",
        "hwpx-content-team-exam-build-result-v3.schema.json",
    ):
        assert runtime in deployment
    assert '"eom_hwpx_builder/cli.py"' in hwpx_deployment
    assert "CONTENT_TEAM_EXAM_V3_RUNTIME=READY" in hwpx_deployment
    assert "installed HWPX V3 source drift" in hwpx_deployment
    assert "sha256:43b7659bb96845f97fc2c29f5b26eaf561b4ba36ed0a1ee811088aa7cd9675a8" in (
        hwpx_deployment
    )
    assert "content-team-exam-render-request/3.0" in hwpx_deployment
    api_deploy = "scripts/api/deploy_release.sh --install-preserve-workflow-runner-inactive"
    builder_install = "scripts/hwpx/deploy_builder.sh --install"
    builder_verify = "scripts/hwpx/deploy_builder.sh --verify"
    assert (
        runbook.index(api_deploy) < runbook.index(builder_install) < runbook.index(builder_verify)
    )
    knowledge_bootstrap = runbook.partition('"${EOMCTL}" control-plane bootstrap-knowledge-item')[
        2
    ].partition("\n\n")[0]
    assert "--evaluation-cases-total 4" in knowledge_bootstrap


def test_release_verifies_legacy_item_extraction_runtime_and_contracts() -> None:
    deployment = _source("scripts/api/deploy_release.sh")

    for runtime_member in (
        "eom_orchestrator/legacy_item_extraction_artifact.py",
        "eom_orchestrator/legacy_item_extraction_bootstrap.py",
        "eom_orchestrator/legacy_item_editorial_compatibility_artifact.py",
        "eom_orchestrator/legacy_item_editorial_compatibility_bootstrap.py",
        "eom_catalog_contracts/item_origin.py",
        "eom_catalog_contracts/legacy_assessment.py",
        "eom_catalog_service/item_origin_models.py",
        "eom_catalog_service/item_origin_service.py",
        "eom_catalog_service/legacy_assessment_bundle_discovery.py",
        "eom_catalog_service/legacy_assessment_models.py",
        "eom_catalog_service/legacy_assessment_packages.py",
        "eom_catalog_service/legacy_assessment_registry.py",
        "eom_catalog_service/legacy_assessment_rights.py",
        "eom_catalog_service/legacy_item_acceptance_service.py",
        "eom_catalog_service/legacy_item_extraction_service.py",
        "eom_catalog_service/legacy_item_editorial_compatibility_service.py",
        "eom_catalog_service/legacy_item_editorial_validation.py",
        "eom_catalog_service/legacy_item_learning_models.py",
        "eom_catalog_service/legacy_item_learning_service.py",
        "eom_catalog_service/legacy_item_promotion_service.py",
        "eom_hwpx_manager/content_team_compatibility_evidence.py",
        "eomctl/legacy_assessment.py",
    ):
        assert f'"{runtime_member}"' in deployment
    for resource in (
        "item-origin/item-origin-types-v1.schema.json",
        "item-origin/organization-revision-v1.schema.json",
        "item-origin/assessment-occurrence-revision-v1.schema.json",
        "item-origin/item-origin-profile-v1.schema.json",
        "legacy-assessment/legacy-assessment-types-v1.schema.json",
        "legacy-assessment/assessment-source-bundle-proposal-v1.schema.json",
        "legacy-assessment/assessment-source-bundle-v1.schema.json",
        "legacy-assessment/assessment-layout-observation-v1.schema.json",
        "legacy-assessment/legacy-item-extraction-request-v1.schema.json",
        "legacy-assessment/legacy-item-extraction-receipt-v1.schema.json",
        "legacy-assessment/legacy-item-extraction-result-v1.schema.json",
        "legacy-assessment/legacy-item-extraction-acceptance-v1.schema.json",
        "legacy-assessment/legacy-item-corpus-coverage-v1.schema.json",
        "legacy-assessment/legacy-item-promotion-request-v1.schema.json",
        "legacy-assessment/legacy-item-editorial-compatibility-policy-v1.schema.json",
        "legacy-assessment/legacy-item-editorial-compatibility-request-v1.schema.json",
        "legacy-assessment/legacy-item-editorial-compatibility-proposal-v1.schema.json",
        "legacy-assessment/legacy-item-editorial-compatibility-result-v1.schema.json",
    ):
        assert f'"{resource}"' in deployment
        assert f'"schemas/{resource}"' in deployment
    assert '"config/workflows/legacy-item-extraction.v1.yaml"' in deployment
    assert '"config/workflows/legacy-item-editorial-compatibility.v1.yaml"' in deployment
    assert 'load_role_input_schema("support", "workflow-role/1.14.0")' in deployment
    assert 'load_role_input_schema("support", "workflow-role/1.16.0")' in deployment
    assert 'legacy.definition_key != "legacy-item-extraction"' in deployment
    assert 'legacy.definition_version != "1.0.0"' in deployment
    assert 'editorial.definition_key != "legacy-item-editorial-compatibility"' in deployment
    assert 'editorial.definition_version != "1.0.0"' in deployment


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
        "scripts/api/workflow_runner_deployment_hold.sh",
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


def test_integration_fixture_requires_explicit_database_url_without_secret_fallback() -> None:
    source = _source("tests/integration/conftest.py")

    assert 'explicit_url = os.environ.get("EOM_DATABASE_URL")' in source
    assert "if not explicit_url:" in source
    assert "build_engine(explicit_url)" in source
    assert "engine = build_engine()" not in source
    assert "runtime secret-file fallback is forbidden" in source
