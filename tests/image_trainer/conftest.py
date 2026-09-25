from __future__ import annotations

import os

import pytest


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    if os.environ.get("EOM_RUN_IMAGE_TRAINER_RUNTIME") == "1":
        return
    marker = pytest.mark.skip(
        reason="set EOM_RUN_IMAGE_TRAINER_RUNTIME=1 in the isolated CUDA trainer environment"
    )
    for item in items:
        item.add_marker(marker)
