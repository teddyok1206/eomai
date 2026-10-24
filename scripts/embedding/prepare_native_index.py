"""Protected owner-release bootstrap for fixed INDEX and explicit QUERY root prepare."""

from __future__ import annotations

import os
import stat
import sys
from pathlib import Path


def main() -> int:
    try:
        release = Path(__file__).parent
        if (
            os.geteuid() != 0
            or sys.flags.isolated != 1
            or not sys.dont_write_bytecode
            or release.parent != Path("/opt/eom/embedding-owner-releases")
        ):
            return 1
        for node in (release, *release.parents):
            value = node.lstat()
            if not stat.S_ISDIR(value.st_mode) or value.st_uid != 0 or value.st_mode & 0o022:
                return 1
        overlay = release / "site-packages"
        value = overlay.lstat()
        if not stat.S_ISDIR(value.st_mode) or value.st_uid != 0 or value.st_mode & 0o022:
            return 1
        sys.path.insert(0, str(overlay))
        if len(sys.argv) == 2:
            from eom_orchestrator.native_embedding_index_handoff import main as prepare
        elif len(sys.argv) == 3 and sys.argv[1] == "QUERY":
            sys.argv.pop(1)
            from eom_orchestrator.native_embedding_query_handoff import main as prepare
        elif len(sys.argv) == 3 and sys.argv[1] == "PRIVATE_CHAT_QUERY":
            sys.argv.pop(1)
            from eom_orchestrator.native_private_chat_query_handoff import main as prepare
        elif len(sys.argv) == 3 and sys.argv[1] == "CUDA_INDEX":
            sys.argv.pop(1)
            from eom_catalog_service.embedding_native_cuda_index_controller import main as prepare
        elif len(sys.argv) == 3 and sys.argv[1] == "GPU_BATCH":
            sys.argv.pop(1)
            from eom_catalog_service.embedding_gpu_batch_owner_entry import main as prepare
        else:
            return 1

        return prepare()
    except Exception:
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
