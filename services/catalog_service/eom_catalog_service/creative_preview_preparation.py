"""Local owner adapter to the existing Catalog preview/converter use case."""

import json
import os
import stat
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

from eom_catalog_contracts.external_item_media import (
    ExternalItemDocumentMediaQuery,
    ExternalItemPreviewPrepareCommand,
)

from eom_catalog_service.external_item_preview_projection import (
    ExternalItemPreviewProjectionService,
    ExternalItemPreviewUnavailable,
)


def prepare_in_catalog_owner() -> None:
    """Trusted Catalog composition; only the existing converter parses Office bytes."""
    import pwd

    from eom_orchestrator.database import build_engine

    if os.geteuid() != pwd.getpwnam("eom-catalog-manager").pw_uid:
        raise ValueError("CREATIVE_PREVIEW_OWNER_INVALID")
    command = ExternalItemPreviewPrepareCommand.model_validate_json(sys.argv[-1])
    query = ExternalItemDocumentMediaQuery(
        source_id=command.source_id,
        source_revision_id=command.source_revision_id,
        edition=command.edition,
    )
    engine = build_engine()
    try:
        service = ExternalItemPreviewProjectionService(engine)
        try:
            preview = service.open(query)
        except ExternalItemPreviewUnavailable as error:
            if error.code != "EXTERNAL_ITEM_PREVIEW_NOT_READY":
                raise
            service.build(query)
            preview = service.open(query)
        preview.member.stream.close()
        print("CREATIVE_PREVIEW_READY", flush=True)
    finally:
        engine.dispose()


def prepare_creative_preview(query: ExternalItemDocumentMediaQuery) -> None:
    """No API peer impersonation or worker privilege changes; run the actual owner."""
    if os.geteuid() != 0:
        raise ValueError("CREATIVE_PREVIEW_COORDINATOR_INVALID")
    package_root = Path(__file__).resolve().parents[1]
    for path in (package_root, Path(__file__).resolve()):
        metadata = path.stat()
        if metadata.st_uid != 0 or metadata.st_gid != 0 or stat.S_IMODE(metadata.st_mode) & 0o022:
            raise ValueError("CREATIVE_PREVIEW_INSTALLED_SOURCE_INVALID")
    command = ExternalItemPreviewPrepareCommand(
        source_id=query.source_id,
        source_revision_id=query.source_revision_id,
        edition=query.edition,
    )
    properties = (
        "EnvironmentFile=/etc/eom/secrets/catalog-manager.env",
        "Environment=EOM_CATALOG_STAGING_ROOT=/var/lib/eom-catalog-api/staging",
        "NoNewPrivileges=true",
        "PrivateTmp=true",
        "ProtectHome=true",
        "ProtectSystem=strict",
        "ReadWritePaths=/var/lib/eom-catalog-api/staging /mnt/nas/eom/artifacts",
        "InaccessiblePaths=/home/eom/EOM /home/eom/EOMIS "
        "/srv/eom/worker-homes /etc/eom/secrets/api.env",
        "RuntimeMaxSec=330",
    )
    arguments = [
        "/usr/bin/systemd-run",
        "--quiet",
        "--wait",
        "--pipe",
        "--collect",
        "--unit=eom-creative-preview-" + uuid4().hex[:20],
        "--uid=eom-catalog-manager",
        "--gid=eom-api",
        "--service-type=exec",
    ]
    arguments.extend(flag for value in properties for flag in ("--property", value))
    arguments.extend(
        (
            "--",
            sys.executable,
            "-I",
            "-B",
            "-c",
            "import sys; sys.path.insert(0, " + repr(str(package_root)) + "); "
            "from eom_catalog_service.creative_preview_preparation "
            "import prepare_in_catalog_owner; "
            "prepare_in_catalog_owner()",
            json.dumps(command.model_dump(mode="json"), sort_keys=True, separators=(",", ":")),
        )
    )
    try:
        result = subprocess.run(
            arguments,
            check=False,
            capture_output=True,
            timeout=345,
            env={"PATH": "/usr/bin:/bin", "LANG": "C", "LC_ALL": "C", "TZ": "UTC"},
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise ValueError("CREATIVE_PREVIEW_PREPARATION_FAILED") from error
    if (
        result.returncode != 0
        or result.stdout.strip() != b"CREATIVE_PREVIEW_READY"
        or len(result.stderr) > 65536
    ):
        raise ValueError("CREATIVE_PREVIEW_PREPARATION_FAILED")
