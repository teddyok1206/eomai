"""HWPX integration health checks without exposing secrets."""

from __future__ import annotations

import json
import pwd
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path

from eom_orchestrator.migration import CURRENT_MIGRATION_REVISION
from sqlalchemy import Engine, text

from eom_hwpx_manager.settings import HwpxSettings


@dataclass(frozen=True)
class HwpxDoctorCheck:
    name: str
    status: str
    detail: str


def run_hwpx_doctor(engine: Engine, settings: HwpxSettings) -> list[HwpxDoctorCheck]:
    checks: list[HwpxDoctorCheck] = []
    checks.append(
        HwpxDoctorCheck(
            "environment",
            "PASS" if settings.builder_python.is_file() else "FAIL",
            str(settings.builder_python.parent.parent),
        )
    )
    active_templates = 0
    try:
        metadata_run = subprocess.run(
            [
                str(settings.builder_python),
                "-c",
                (
                    "import importlib.metadata as m,json,pathlib,eom_hwpx_builder; "
                    "d=m.distribution('eom-hwpx-builder'); "
                    "u=d.read_text('direct_url.json') or ''; "
                    "p=str(pathlib.Path(eom_hwpx_builder.__file__).resolve()); "
                    "print(json.dumps({'version':d.version,'path':p,'editable':"
                    "'\\\"editable\\\": true' in u}))"
                ),
            ],
            capture_output=True,
            check=False,
            timeout=10,
            env={"PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"},
            text=True,
        )
        metadata = json.loads(metadata_run.stdout)
        version = str(metadata.get("version", "unavailable"))
        import_path = str(metadata.get("path", "unavailable"))
        non_editable = (
            metadata_run.returncode == 0
            and not metadata.get("editable", True)
            and "site-packages" in import_path
            and not import_path.startswith("/home/eom/EOM/")
        )
        builder_status = "PASS" if non_editable else "FAIL"
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError, TypeError):
        version = "unavailable"
        builder_status = "FAIL"
    checks.append(HwpxDoctorCheck("installed_builder_wheel", builder_status, version))
    checks.append(
        HwpxDoctorCheck(
            "non_editable_import",
            "PASS" if builder_status == "PASS" else "FAIL",
            "site-packages" if builder_status == "PASS" else "invalid import location",
        )
    )
    checks.append(
        HwpxDoctorCheck(
            "builder_binary",
            "PASS" if settings.builder_binary.is_file() else "FAIL",
            str(settings.builder_binary),
        )
    )
    try:
        account = pwd.getpwnam(settings.builder_user)
        user_ok = account.pw_shell.endswith("nologin")
    except KeyError:
        user_ok = False
    checks.append(
        HwpxDoctorCheck("builder_user", "PASS" if user_ok else "FAIL", settings.builder_user)
    )
    checks.append(
        HwpxDoctorCheck(
            "workspace_root",
            "PASS" if settings.workspace_root.is_dir() else "FAIL",
            str(settings.workspace_root),
        )
    )
    checks.append(
        HwpxDoctorCheck(
            "reference_kit",
            "PASS" if settings.reference_kit.is_dir() else "FAIL",
            str(settings.reference_kit),
        )
    )
    checks.append(
        HwpxDoctorCheck(
            "reference_inbox",
            "PASS" if settings.reference_inbox.is_dir() else "FAIL",
            str(settings.reference_inbox),
        )
    )
    reference = settings.reference_inbox / "eom_hwpx_reference_v1.hwpx"
    checks.append(
        HwpxDoctorCheck(
            "reference_template",
            "PASS" if reference.is_file() else "PENDING_MANUAL_ACTION",
            "FOUND" if reference.is_file() else "PENDING_REFERENCE_TEMPLATE",
        )
    )
    try:
        with engine.connect() as connection:
            revision = connection.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalar_one()
            active_templates = connection.execute(
                text(
                    "SELECT count(*) FROM hwpx_template_revisions "
                    "WHERE approved_at IS NOT NULL AND immutable"
                )
            ).scalar_one()
        migration_ok = revision == CURRENT_MIGRATION_REVISION
    except Exception:
        revision = "unavailable"
        migration_ok = False
    checks.append(HwpxDoctorCheck("migration", "PASS" if migration_ok else "FAIL", str(revision)))
    checks.append(
        HwpxDoctorCheck(
            "active_template_revision",
            "PASS" if active_templates else "PENDING_MANUAL_ACTION",
            str(active_templates),
        )
    )
    checks.append(
        HwpxDoctorCheck(
            "artifact_service",
            "PASS" if settings.nas_artifact_root.is_dir() else "FAIL",
            "nas://artifacts",
        )
    )
    checks.append(
        HwpxDoctorCheck(
            "nas_hwpx_root",
            "PASS" if settings.hwpx_root.is_dir() else "FAIL",
            "nas://hwpx/poc-v0",
        )
    )
    checks.append(
        HwpxDoctorCheck(
            "transient_sandbox",
            "PASS" if Path("/usr/bin/systemd-run").is_file() else "FAIL",
            "PrivateNetwork and inaccessible runtime boundaries",
        )
    )
    try:
        completed = subprocess.run(
            [str(settings.builder_binary), "doctor"],
            capture_output=True,
            check=False,
            timeout=20,
            env={"PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"},
        )
        result = json.loads(completed.stdout)
        required = {
            "schema_package",
            "xml_safety_parser",
            "image_processing",
            "package_limits",
            "active_content_rejection",
            "equation_binding_capability",
            "kordoc_runtime",
        }
        passed_names = {
            str(item.get("name"))
            for item in result.get("checks", [])
            if item.get("status") == "PASS"
        }
        parser_ok = required.issubset(passed_names)
    except Exception:
        parser_ok = False
    checks.append(
        HwpxDoctorCheck(
            "builder_security_capabilities", "PASS" if parser_ok else "FAIL", "bounded ZIP/XML"
        )
    )
    return checks


def doctor_payload(checks: list[HwpxDoctorCheck]) -> dict[str, object]:
    fatal = [check for check in checks if check.status == "FAIL"]
    return {"passed": not fatal, "checks": [asdict(check) for check in checks]}
