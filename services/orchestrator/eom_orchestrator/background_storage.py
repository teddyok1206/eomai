"""Local scratch headroom for existing long-running metadata owners, not an authority."""

import shutil
from pathlib import Path

MIN_BACKGROUND_FREE_BYTES = 10 * 1024**3


class BackgroundStoragePressure(RuntimeError):
    code = "BACKGROUND_LOCAL_STORAGE_LOW"


def require_background_write_capacity(path: Path) -> None:
    """Keep reserve for DB/Artifact commit and already-dispatched worker completions.

    Observe the owner's fixed local state filesystem. Do not turn a missing or
    inaccessible configured path into an invented capacity observation.
    """
    if shutil.disk_usage(path).free < MIN_BACKGROUND_FREE_BYTES:
        raise BackgroundStoragePressure(BackgroundStoragePressure.code)
