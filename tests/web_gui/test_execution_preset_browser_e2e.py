"""Opt-in actual browser test of the admin model editor; service boundary is synthetic."""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
from pathlib import Path

import httpx
import pytest
from eom_web_gui.gateways import HttpApplicationGateway

from tests.web_gui.test_execution_preset_admin import _wire_preset
from tests.web_gui.test_gateway import _list, _session

ROOT = Path(__file__).resolve().parents[2]


def test_model_editor_real_browser_lifecycle_replays_stale_responses_and_mobile(
    tmp_path: Path,
) -> None:
    if not os.environ.get("EOM_WEB_PLAYWRIGHT_MODULE"):
        pytest.skip("Opt-in check requires an existing Playwright environment")
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node is required for the actual model editor browser check")

    async def project_api_wire_data() -> list[dict[str, object]]:
        gateway = HttpApplicationGateway(
            application_api_url="http://127.0.0.1:8765",
            observability_url="http://127.0.0.1:8780",
            observability_access_token=None,
            timeout=1,
            transport=httpx.MockTransport(
                lambda _: httpx.Response(200, json=_list([_wire_preset()]))
            ),
        )
        try:
            return list(await gateway.execution_presets(_session()))
        finally:
            await gateway.close()

    # Exercise the real BFF adapter before the real browser consumes its response.  A direct
    # controller fixture alone cannot catch the scalar redactor dropping the revisions array.
    fixture = tmp_path / "preset-wire-projection.json"
    fixture.write_text(json.dumps(asyncio.run(project_api_wire_data())), encoding="utf-8")
    result = subprocess.run(
        [node, str(ROOT / "tests/web_gui/execution_preset_browser_checks.mjs")],
        env={**os.environ, "EOM_WEB_PRESET_FIXTURE_PATH": str(fixture)},
        text=True,
        capture_output=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "execution_preset_browser=PASS live_writes=0 model_calls=0" in result.stdout
