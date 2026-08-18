from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

pytestmark = [pytest.mark.privileged, pytest.mark.workflow_privileged]


@pytest.mark.skipif(
    os.environ.get("EOM_RUN_WORKFLOW_PRIVILEGED") != "1" or os.geteuid() != 0,
    reason="requires explicit root-only private-group filesystem integration",
)
def test_real_private_group_worker_handoff() -> None:
    worker = "eom-cdx-01"
    unrelated = "eom-cdx-02"
    root = Path("/srv/eom/workspaces") / worker
    job = root / f"privileged-test-{os.getpid()}"
    private_gid = root.stat().st_gid
    prepare_code = (
        f"import os,pathlib; p=pathlib.Path({str(job)!r}); p.mkdir(mode=0o2770); "
        f"os.chown(p,-1,{private_gid}); p.chmod(0o2770); "
        f"f=p/'input.json'; f.write_text('{{}}'); os.chown(f,-1,{private_gid}); "
        "f.chmod(0o640)"
    )
    result_code = (
        f"import pathlib; p=pathlib.Path({str(job / 'result.json')!r}); "
        "p.write_text('{}'); p.chmod(0o640)"
    )
    try:
        subprocess.run(
            [
                "runuser",
                "-u",
                "eom",
                "--",
                "/usr/bin/python3",
                "-c",
                prepare_code,
            ],
            check=True,
        )
        subprocess.run(
            ["runuser", "-u", worker, "--", "test", "-r", str(job / "input.json")], check=True
        )
        subprocess.run(
            [
                "runuser",
                "-u",
                worker,
                "--",
                "/usr/bin/python3",
                "-c",
                result_code,
            ],
            check=True,
        )
        subprocess.run(
            ["runuser", "-u", "eom", "--", "test", "-r", str(job / "result.json")], check=True
        )
        denied = subprocess.run(
            ["runuser", "-u", unrelated, "--", "test", "-r", str(job / "result.json")], check=False
        )
        assert denied.returncode != 0
    finally:
        if job.is_dir() and job.parent == root:
            for name in ("input.json", "result.json"):
                candidate = job / name
                if candidate.exists() and not candidate.is_symlink():
                    candidate.unlink()
            job.rmdir()
