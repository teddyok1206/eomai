"""Install only the admitted creative owner's fixed systemd/config files.

Does not install wheels, start model work, alter existing services, or migrate DBs.
The runtime revalidates the exact admitted Artifact and its original operator.
"""

import argparse
import os
import re
import stat
import subprocess
import tempfile
from pathlib import Path

PYTHON = "/srv/eom/conda/envs/eom-api/bin/python"
UNIT_NAMES = (
    "eom-creative-learning.service",
    "eom-creative-learning-observe.service",
    "eom-creative-learning-observe.timer",
)


def render_configuration(prefix: Path, cohort_id: str, revision_id: str, limit: int) -> str:
    if (
        not re.fullmatch(r"/opt/eom/maintenance-releases/[0-9a-f]{40}", str(prefix))
        or not re.fullmatch(r"creativecohort_[0-9a-f]{32}", cohort_id)
        or not re.fullmatch(r"rev_[0-9a-f]{32}", revision_id)
        or not 1 <= limit <= 20000
    ):
        raise ValueError("CREATIVE_OWNER_INSTALL_INPUT_INVALID")
    return (
        f"EOM_CREATIVE_COHORT_ID={cohort_id}\n"
        f"EOM_CREATIVE_COHORT_REVISION_ID={revision_id}\n"
        f"EOM_CREATIVE_VERIFIED_LIMIT={limit}\n"
    )


def _root_file(path: Path) -> str:
    metadata = path.lstat()
    if (
        not stat.S_ISREG(metadata.st_mode)
        or metadata.st_uid != 0
        or metadata.st_gid != 0
        or metadata.st_nlink != 1
        or metadata.st_mode & 0o022
        or not 1 <= metadata.st_size <= 32768
    ):
        raise ValueError("CREATIVE_OWNER_INSTALL_TEMPLATE_INVALID")
    return path.read_text()


def _replace(path: Path, payload: str, mode: int) -> None:
    if path.exists() or path.is_symlink():
        _root_file(path)
    descriptor, raw = tempfile.mkstemp(prefix=".creative-owner-", dir=path.parent)
    temporary = Path(raw)
    try:
        with os.fdopen(descriptor, "w") as stream:
            os.fchmod(stream.fileno(), mode)
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prefix", type=Path, required=True)
    parser.add_argument("--cohort-id", required=True)
    parser.add_argument("--cohort-revision-id", required=True)
    parser.add_argument("--verified-limit", type=int, default=3)
    arguments = parser.parse_args()
    if os.geteuid() != 0:
        parser.error("root-owned local release installation is required")
    prefix = arguments.prefix
    config = render_configuration(
        prefix, arguments.cohort_id, arguments.cohort_revision_id, arguments.verified_limit
    )
    for path in (prefix, prefix / "site-packages", prefix / "inputs"):
        metadata = path.lstat()
        if (
            not stat.S_ISDIR(metadata.st_mode)
            or metadata.st_uid != 0
            or metadata.st_gid != 0
            or stat.S_IMODE(metadata.st_mode) != 0o555
        ):
            raise ValueError("CREATIVE_OWNER_INSTALL_PREFIX_INVALID")
    units = {}
    for name in UNIT_NAMES:
        template = name + (".in" if name.endswith(".service") else "")
        units[name] = (
            _root_file(prefix / "inputs" / template)
            .replace("@PREFIX@", str(prefix))
            .replace("@PYTHON@", PYTHON)
        )
        if "@PREFIX@" in units[name] or "@PYTHON@" in units[name]:
            raise ValueError("CREATIVE_OWNER_INSTALL_TEMPLATE_INVALID")
    state = Path("/var/lib/eom/creative-learning")
    state.mkdir(mode=0o750, exist_ok=True)
    metadata = state.lstat()
    if (
        not stat.S_ISDIR(metadata.st_mode)
        or metadata.st_uid != 0
        or metadata.st_gid != 0
        or stat.S_IMODE(metadata.st_mode) != 0o750
    ):
        raise ValueError("CREATIVE_OWNER_INSTALL_STATE_INVALID")
    _replace(Path("/etc/eom/creative-learning.env"), config, 0o600)
    for name, payload in units.items():
        _replace(Path("/etc/systemd/system") / name, payload, 0o644)
    subprocess.run(["/usr/bin/systemctl", "daemon-reload"], check=True, timeout=30)
    print("creative_owner_configuration=INSTALLED_NOT_STARTED")


if __name__ == "__main__":
    main()
