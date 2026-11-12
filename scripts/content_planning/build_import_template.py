"""Export the package-owned blank workbook with an explicit EOM Python environment."""

from __future__ import annotations

import argparse
from pathlib import Path

from eom_catalog_contracts.content_workbook_template import build_template

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    arguments = parser.parse_args()
    build_template(arguments.output)
    print(arguments.output)
