from __future__ import annotations

import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TRAINER_PYTHON = Path("/srv/eom/conda/envs/eom-image-trainer/bin/python")


def test_quality_metrics_use_non_overflowing_rgb_luminance(tmp_path: Path) -> None:
    if not TRAINER_PYTHON.is_file():
        return
    script = """
from pathlib import Path
from PIL import Image, ImageDraw
from scripts.image_provider.run_quality_evaluation import _metrics

target = Path(__import__('sys').argv[1])
image = Image.new('RGB', (800, 500), 'white')
ImageDraw.Draw(image).rectangle((0, 0, 99, 99), fill='black')
image.save(target, format='PNG', optimize=False, compress_level=9)
metrics = _metrics(target)
assert metrics.dark_ink_fraction_milli == 25, metrics
assert metrics.white_background_fraction_milli == 975, metrics
"""
    completed = subprocess.run(
        [str(TRAINER_PYTHON), "-c", script, str(tmp_path / "bounded.png")],
        cwd=ROOT,
        env={
            **os.environ,
            "PYTHONPATH": f"{ROOT}:{ROOT / 'packages/image_contracts'}",
        },
        capture_output=True,
        check=False,
        text=True,
        timeout=30,
    )
    assert completed.returncode == 0, completed.stderr
