"""Fixed stdlib-first image/trainer composition; not a general module launcher.

Install as a root-owned immutable unit input only with the reviewed GPU lifetime
owner and all affected templates. Importing this module has no signal side effects.
"""

from __future__ import annotations

import argparse
import grp
import os
import pwd
import runpy
import signal
import sys
from pathlib import Path
from types import MappingProxyType

_ROLES = MappingProxyType(
    {
        "PROVIDER": (Path("/srv/eom/conda/envs/eom-image"), "eom_image_provider.cli"),
        "TRAINER": (Path("/srv/eom/conda/envs/eom-image-trainer"), "eom_image_trainer.cli"),
    }
)


def main() -> None:
    if len(sys.argv) < 3 or sys.argv[1] not in _ROLES:
        raise SystemExit("IMAGE_GPU_UNIT_BOOTSTRAP_INVALID")
    parser = argparse.ArgumentParser(add_help=False, allow_abbrev=False, exit_on_error=False)
    parser.add_argument("--gpu-lock", action="append")
    try:
        selection, _ = parser.parse_known_args(sys.argv[2:])
    except argparse.ArgumentError as error:
        raise SystemExit("IMAGE_GPU_UNIT_BOOTSTRAP_INVALID") from error
    if selection.gpu_lock != ["/run/eom-gpu-lease/gpu0.lock"]:
        # The migrated unit must not select the retained legacy/rollback branch.
        raise SystemExit("IMAGE_GPU_UNIT_BOOTSTRAP_INVALID")
    prefix, module = _ROLES[sys.argv[1]]
    try:
        user = pwd.getpwnam("eom-image")
        lease_gid = grp.getgrnam("eom-gpu-lease").gr_gid
        groups = set(os.getgroups())
    except (KeyError, OSError) as error:
        raise SystemExit("IMAGE_GPU_UNIT_BOOTSTRAP_INVALID") from error
    if (
        user.pw_uid <= 0
        or user.pw_gid <= 0
        or lease_gid <= 0
        or lease_gid == user.pw_gid
        or os.getresuid() != (user.pw_uid,) * 3
        or os.getresgid() != (user.pw_gid,) * 3
        or lease_gid not in groups
        or not groups <= {user.pw_gid, lease_gid}
        or Path(sys.prefix) != prefix
        or Path(sys.executable).parent != prefix / "bin"
        or sys.flags.isolated != 1
        or not sys.dont_write_bytecode
        or sys.platform != "linux"
        or any(
            name == library or name.startswith(library + ".")
            for name in sys.modules
            for library in ("torch", "transformers", "tokenizers", "numpy", "diffusers")
        )
    ):
        raise SystemExit("IMAGE_GPU_UNIT_BOOTSTRAP_INVALID")
    # Do this before either CLI's imports can create native library threads.
    # The fixed root observer owns ACK and retirement; no signal means no model.
    signal.pthread_sigmask(signal.SIG_BLOCK, {signal.SIGUSR1})
    sys.argv = [
        str(
            prefix
            / "bin"
            / ("eom-local-image" if sys.argv[1] == "PROVIDER" else "eom-local-image-trainer")
        ),
        *sys.argv[2:],
    ]
    runpy.run_module(module, run_name="__main__", alter_sys=True)


if __name__ == "__main__":
    main()
