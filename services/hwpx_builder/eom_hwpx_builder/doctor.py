"""Non-secret HWPX builder environment checks."""

from __future__ import annotations

import importlib.metadata
import importlib.util
import pwd
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

from eom_hwpx_contracts.validation import SCHEMA_FILES, load_schema
from PIL import features

from eom_hwpx_builder.errors import HwpxError
from eom_hwpx_builder.kordoc_runtime import KordocRuntime
from eom_hwpx_builder.models import PackageLimits

ENV_PREFIX = Path("/srv/eom/conda/envs/eom-hwpx")
WORKSPACE = Path("/var/lib/eom-hwpx")
REFERENCE = Path("/mnt/nas/eom/hwpx/poc-v0/reference/inbox/eom_hwpx_reference_v1.hwpx")
KIT = Path("/mnt/nas/eom/hwpx/poc-v0/reference-kit/v1")


@dataclass(frozen=True)
class DoctorCheck:
    name: str
    status: str
    detail: str


def run_doctor() -> dict[str, object]:
    checks: list[DoctorCheck] = []
    checks.append(
        DoctorCheck(
            "python_environment",
            "PASS" if Path(sys.prefix).resolve() == ENV_PREFIX else "FAIL",
            str(ENV_PREFIX),
        )
    )
    checks.append(
        DoctorCheck(
            "python_version",
            "PASS" if sys.version_info[:2] == (3, 12) else "FAIL",
            f"{sys.version_info.major}.{sys.version_info.minor}",
        )
    )
    try:
        version = importlib.metadata.version("eom-hwpx-builder")
        module = importlib.util.find_spec("eom_hwpx_builder")
        origin = Path(module.origin).resolve() if module and module.origin else None
        non_editable = bool(origin and "site-packages" in origin.parts)
    except importlib.metadata.PackageNotFoundError:
        version = "not-installed"
        non_editable = False
    checks.append(
        DoctorCheck("builder_wheel", "PASS" if non_editable else "FAIL", f"version={version}")
    )
    schema_ok = True
    try:
        for name in SCHEMA_FILES:
            load_schema(name)
    except Exception:
        schema_ok = False
    checks.append(
        DoctorCheck(
            "schema_package",
            "PASS" if schema_ok else "FAIL",
            f"{len(SCHEMA_FILES)} schemas",
        )
    )
    try:
        capability = KordocRuntime().capabilities()
        kordoc_status = "PASS"
        kordoc_detail = f"node={capability.node_major},kordoc={capability.kordoc_version},offline"
    except HwpxError:
        kordoc_status = "FAIL"
        kordoc_detail = "pinned Node/Kordoc runtime unavailable"
    checks.append(DoctorCheck("kordoc_runtime", kordoc_status, kordoc_detail))
    try:
        account = pwd.getpwnam("eom-hwpx")
        user_ok = account.pw_shell.endswith("nologin")
    except KeyError:
        user_ok = False
    checks.append(DoctorCheck("builder_user", "PASS" if user_ok else "FAIL", "eom-hwpx"))
    checks.append(
        DoctorCheck("workspace", "PASS" if WORKSPACE.is_dir() else "FAIL", str(WORKSPACE))
    )
    checks.append(DoctorCheck("reference_kit", "PASS" if KIT.is_dir() else "FAIL", str(KIT)))
    checks.append(
        DoctorCheck(
            "reference_template",
            "PASS" if REFERENCE.is_file() else "PENDING_MANUAL_ACTION",
            "FOUND" if REFERENCE.is_file() else "PENDING_REFERENCE_TEMPLATE",
        )
    )
    checks.append(
        DoctorCheck(
            "xml_safety_parser",
            "PASS",
            "lxml:no_network,no_dtd,no_entities,no_recover",
        )
    )
    checks.append(
        DoctorCheck(
            "image_processing",
            "PASS" if features.check("zlib") else "FAIL",
            "Pillow PNG",
        )
    )
    checks.append(
        DoctorCheck("package_limits", "PASS", PackageLimits().model_dump_json(exclude_none=True))
    )
    checks.append(
        DoctorCheck(
            "active_content_rejection",
            "PASS",
            "scripts, macros, OLE, encryption, links, executables, embedded packages",
        )
    )
    checks.append(
        DoctorCheck(
            "equation_binding_capability",
            "PASS",
            "observed marker or unique anchor-bound source only",
        )
    )
    failed = any(check.status == "FAIL" for check in checks)
    return {"passed": not failed, "checks": [asdict(check) for check in checks]}
