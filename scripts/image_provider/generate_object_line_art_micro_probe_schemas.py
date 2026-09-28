#!/usr/bin/env python3
"""Generate the additive object-line-art 16/4/4 probe schemas."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[2]
CANONICAL = ROOT / "schemas/image-provider"
PACKAGED = ROOT / "packages/image_contracts/eom_image_contracts/schemas"
FAMILIES = (
    "adapter-manifest",
    "evaluation-command",
    "evaluation-result",
    "probe-command",
    "probe-plan",
    "probe-worker-result",
)

REPLACEMENTS = (
    (
        "EVALUATION_ONLY_SCIENCE_CAMPAIGN_EXPANDED_PROBE",
        "EVALUATION_ONLY_SCIENCE_OBJECT_LINE_ART_PROBE",
    ),
    (
        "eom-local-image-science-campaign-lora-micro-trainer/1.1",
        "eom-local-image-science-campaign-lora-micro-trainer/1.2",
    ),
    (
        "local-image-science-campaign-lora-micro-adapter-manifest/1.1",
        "local-image-science-campaign-lora-micro-adapter-manifest/1.2",
    ),
    (
        "local-image-science-campaign-lora-micro-evaluation-command/1.1",
        "local-image-science-campaign-lora-micro-evaluation-command/1.2",
    ),
    (
        "local-image-science-campaign-lora-micro-evaluation-result/1.1",
        "local-image-science-campaign-lora-micro-evaluation-result/1.2",
    ),
    (
        "local-image-science-campaign-lora-micro-probe-command/1.1",
        "local-image-science-campaign-lora-micro-probe-command/1.2",
    ),
    (
        "local-image-science-campaign-lora-micro-probe-plan/1.1",
        "local-image-science-campaign-lora-micro-probe-plan/1.2",
    ),
    (
        "local-image-science-campaign-lora-micro-probe-worker-result/1.1",
        "local-image-science-campaign-lora-micro-probe-worker-result/1.2",
    ),
    (
        "inputs/science-visual-campaign-crop-set.json",
        "inputs/science-object-line-art-crop-set.json",
    ),
    ("imgsciviscampaigncrop_", "imgscivislineartcrop_"),
)


def _replace(value: Any) -> Any:
    if isinstance(value, str):
        for source, target in REPLACEMENTS:
            value = value.replace(source, target)
        return value
    if isinstance(value, list):
        return [_replace(item) for item in value]
    if isinstance(value, dict):
        return {key: _replace(item) for key, item in value.items()}
    return value


def main() -> int:
    for family in FAMILIES:
        source = CANONICAL / f"local-image-science-campaign-lora-micro-{family}-v2.schema.json"
        schema = _replace(json.loads(source.read_text(encoding="utf-8")))
        Draft202012Validator.check_schema(schema)
        payload = json.dumps(schema, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
        filename = f"local-image-science-campaign-lora-micro-{family}-v3.schema.json"
        for directory in (CANONICAL, PACKAGED):
            (directory / filename).write_text(payload, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
