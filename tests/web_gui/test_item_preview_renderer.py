from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def test_item_preview_renderer_preserves_order_and_formats_equations(tmp_path: Path) -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node is not available for the browser helper regression")
    module = tmp_path / "item-preview.mjs"
    module.write_bytes((ROOT / "apps/web_gui/eom_web_gui/static/item-preview.js").read_bytes())
    script = f"""
import {{formatEquationSource, orderedItemPreviewBlocks}} from {json.dumps(module.as_uri())};
const preview = {{schema_version: "2.0", blocks: [
  {{block_id: "block_stem", type: "paragraph"}},
  {{block_id: "block_data", type: "table"}},
  {{block_id: "block_image", type: "image"}},
  {{block_id: "block_equation", type: "equation"}},
  {{block_id: "block_prompt", type: "paragraph"}},
  {{block_id: "block_claims", type: "statement_set"}},
]}};
const kinds = orderedItemPreviewBlocks(preview).map((block) => block.type).join(",");
if (kinds !== "paragraph,table,image,equation,paragraph,statement_set") {{
  throw new Error("ITEM_PREVIEW_ORDER_CHANGED");
}}
if (formatEquationSource("a^2+b_1=\\\\sqrt{{c}}") !== "a²+b₁=√(c)") {{
  throw new Error("ITEM_PREVIEW_EQUATION_FORMAT_INVALID");
}}
let duplicateFailed = false;
try {{ orderedItemPreviewBlocks({{...preview, blocks: [preview.blocks[0], preview.blocks[0]]}}); }}
catch (error) {{ duplicateFailed = error.message === "ITEM_PREVIEW_BLOCK_DUPLICATE"; }}
if (!duplicateFailed) throw new Error("ITEM_PREVIEW_DUPLICATE_NOT_REJECTED");
"""
    completed = subprocess.run(
        [node, "--input-type=module", "--eval", script],
        check=False,
        text=True,
        capture_output=True,
    )
    assert completed.returncode == 0, completed.stderr


def test_item_preview_dom_uses_safe_text_and_same_origin_media() -> None:
    source = (ROOT / "apps/web_gui/eom_web_gui/static/app.js").read_text(encoding="utf-8")
    assert "orderedItemPreviewBlocks(preview)" in source
    assert "image.src = block.media_url" in source
    assert "textContent = block.text" in source
    assert ".innerHTML" not in source
