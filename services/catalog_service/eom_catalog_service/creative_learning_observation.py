"""Read-only operational heartbeat; never completion authority or a retry loop."""

import json
import os
import re
import stat
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path

from eom_catalog_service.creative_learning_runner import STATE_ROOT, validate_state_root


def read_observation(root: Path, cohort_id: str) -> dict[str, object]:
    validate_state_root(root)
    if re.fullmatch(r"creativecohort_[0-9a-f]{32}", cohort_id) is None:
        raise ValueError("CREATIVE_OBSERVATION_ID_INVALID")
    descriptor = os.open(root / (cohort_id + ".json"), os.O_RDONLY | os.O_NOFOLLOW)
    try:
        metadata = os.fstat(descriptor)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_uid != os.geteuid()
            or metadata.st_nlink != 1
            or stat.S_IMODE(metadata.st_mode) != 0o640
            or not 0 < metadata.st_size <= 16384
        ):
            raise ValueError("CREATIVE_OBSERVATION_FILE_INVALID")
        payload = os.read(descriptor, 16385)
        if len(payload) != metadata.st_size:
            raise ValueError("CREATIVE_OBSERVATION_FILE_INVALID")
    finally:
        os.close(descriptor)
    document = json.loads(payload)
    state, completed, total, observed_at = (
        document.get(key) for key in ("state", "verified_count", "target_count", "observed_at")
    )
    if (
        state
        not in {
            "STARTING",
            "EXTRACTING",
            "ANALYZING",
            "VERIFIED",
            "CANARY_VERIFIED",
            "COMPLETED",
            "STOPPED",
            "STOPPED_TECHNICAL_FAILURE",
        }
        or type(completed) is not int
        or type(total) is not int
        or not 0 <= completed <= total <= 20000
        or not isinstance(observed_at, str)
    ):
        raise ValueError("CREATIVE_OBSERVATION_STATUS_INVALID")
    timestamp = datetime.fromisoformat(observed_at)
    if timestamp.utcoffset() != timedelta(0):
        raise ValueError("CREATIVE_OBSERVATION_STATUS_INVALID")
    return {
        "cohort_id": cohort_id,
        "state": state,
        "verified_count": completed,
        "target_count": total,
        "observed_at": observed_at,
        "status_stale": datetime.now(UTC) - timestamp > timedelta(minutes=30),
        "authority": "DERIVED_OPERATIONAL_STATUS_NOT_ACCEPTANCE_RECEIPT",
    }


def main() -> None:
    result = read_observation(STATE_ROOT, os.environ.get("EOM_CREATIVE_COHORT_ID", ""))
    process = subprocess.run(
        [
            "/usr/bin/systemctl",
            "show",
            "eom-creative-learning.service",
            "--property=ActiveState",
            "--property=SubState",
            "--property=Result",
        ],
        capture_output=True,
        check=False,
        timeout=10,
        env={"PATH": "/usr/bin:/bin", "LANG": "C", "LC_ALL": "C"},
    )
    if process.returncode or len(process.stdout) > 4096:
        raise ValueError("CREATIVE_OBSERVATION_UNIT_UNAVAILABLE")
    properties = dict(line.split("=", 1) for line in process.stdout.decode().splitlines())
    active = properties.get("ActiveState")
    healthy = (result["state"] == "COMPLETED" and properties.get("Result") == "success") or (
        active == "active"
        and not result["status_stale"]
        and result["state"] in {"STARTING", "EXTRACTING", "ANALYZING", "VERIFIED"}
    )
    result.update(service_active=active, check="OK" if healthy else "ATTENTION_REQUIRED")
    print(json.dumps(result, sort_keys=True), flush=True)
    if not healthy:
        raise SystemExit(1)
