from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def test_middle_first_selection_fills_parent_and_fails_closed(tmp_path: Path) -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node is not available for the browser helper regression")
    module = tmp_path / "curriculum-selector.mjs"
    module.write_bytes(
        (ROOT / "apps/web_gui/eom_web_gui/static/curriculum-selector.js").read_bytes()
    )
    outline = json.loads(
        (ROOT / "content/curriculum/eom-integrated-science-editorial-outline-v1.json").read_text(
            encoding="utf-8"
        )
    )
    script = f"""
import {{
  curriculumAncestors,
  curriculumOptionsForSelection,
  reconcileCurriculumSelection,
}} from {json.dumps(module.as_uri())};
let input = "";
for await (const chunk of process.stdin) input += chunk;
const outline = JSON.parse(input);
const selected = reconcileCurriculumSelection(
  outline.units,
  {{large: "", middle: "eom.is.middle.3-2", small: ""}},
  "MIDDLE",
);
if (selected.large !== "eom.is.large.3") throw new Error("MIDDLE_PARENT_NOT_FILLED");
const selectedOptions = curriculumOptionsForSelection(outline.units, selected);
if (selectedOptions.middle.length !== 7) throw new Error("MIDDLE_OPTIONS_NOT_FILTERED");
if (selectedOptions.middle.some((unit) => unit.parent_key !== "eom.is.large.3")) {{
  throw new Error("MIDDLE_OPTIONS_ESCAPE_LARGE");
}}
const changed = reconcileCurriculumSelection(
  outline.units,
  {{...selected, large: "eom.is.large.4"}},
  "LARGE",
);
if (changed.middle !== "") throw new Error("INCOMPATIBLE_MIDDLE_NOT_CLEARED");
const futureUnits = [...outline.units, {{
  key: "eom.is.small.3-2-a",
  level: "SMALL",
  parent_key: "eom.is.middle.3-2",
  code: "3-(2)-가",
  label: "가",
}}, {{
  key: "eom.is.small.3-3-a",
  level: "SMALL",
  parent_key: "eom.is.middle.3-3",
  code: "3-(3)-가",
  label: "가",
}}, {{
  key: "eom.is.small.4-1-a",
  level: "SMALL",
  parent_key: "eom.is.middle.4-1",
  code: "4-(1)-가",
  label: "가",
}}];
const largeOnlyOptions = curriculumOptionsForSelection(futureUnits, {{
  large: "eom.is.large.3", middle: "", small: "",
}});
if (largeOnlyOptions.small.map((unit) => unit.key).join(",") !==
    "eom.is.small.3-2-a,eom.is.small.3-3-a") {{
  throw new Error("SMALL_OPTIONS_NOT_FILTERED_BY_LARGE");
}}
const middleOptions = curriculumOptionsForSelection(futureUnits, {{
  large: "eom.is.large.3", middle: "eom.is.middle.3-2", small: "",
}});
if (middleOptions.small.map((unit) => unit.key).join(",") !== "eom.is.small.3-2-a") {{
  throw new Error("SMALL_OPTIONS_NOT_FILTERED_BY_MIDDLE");
}}
const unscopedOptions = curriculumOptionsForSelection(futureUnits, {{
  large: "", middle: "", small: "",
}});
if (unscopedOptions.small.length !== 3) throw new Error("SMALL_FIRST_OPTIONS_MISSING");
const futureSmall = reconcileCurriculumSelection(
  futureUnits,
  {{large: "", middle: "", small: "eom.is.small.3-2-a"}},
  "SMALL",
);
if (futureSmall.middle !== "eom.is.middle.3-2" || futureSmall.large !== "eom.is.large.3") {{
  throw new Error("SMALL_ANCESTORS_NOT_FILLED");
}}
let missingFailed = false;
try {{ curriculumAncestors(outline.units, "eom.is.middle.9-9"); }}
catch (error) {{ missingFailed = error.message === "CURRICULUM_OUTLINE_UNIT_MISSING"; }}
if (!missingFailed) throw new Error("UNKNOWN_UNIT_DID_NOT_FAIL_CLOSED");
"""
    completed = subprocess.run(
        [node, "--input-type=module", "--eval", script],
        check=False,
        input=json.dumps(outline),
        text=True,
        capture_output=True,
    )
    assert completed.returncode == 0, completed.stderr
