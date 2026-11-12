"""Generate the additive standard workbook contracts before parser implementation."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from eom_catalog_contracts.content_workbook_import import (
    ContentWorkbookDocument,
    ContentWorkbookError,
    ContentWorkbookImportResult,
    ContentWorkbookPreview,
    ContentWorkbookProposal,
    ContentWorkbookReply,
    ContentWorkbookRequest,
)
from pydantic import TypeAdapter


def main() -> None:
    root = Path(__file__).resolve().parents[2]
    for name, uri, model in (
        ("document", "workbook-document", ContentWorkbookDocument),
        ("proposal", "workbook-proposal", ContentWorkbookProposal),
        ("preview", "workbook-preview", ContentWorkbookPreview),
        ("import-result", "workbook-import-result", ContentWorkbookImportResult),
        ("error", "workbook-error", ContentWorkbookError),
        ("request", "workbook-request", ContentWorkbookRequest),
        ("reply", "workbook-reply", ContentWorkbookReply),
    ):
        schema = TypeAdapter(model).json_schema()
        schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
        schema["$id"] = f"eom://schemas/content-planning/{uri}/1.0"
        encoded = (json.dumps(schema, indent=2, ensure_ascii=False) + "\n").encode()
        filename = f"content-workbook-{name}-v1.schema.json"
        for directory in (
            root / "schemas/content-planning",
            root / "packages/catalog_contracts/eom_catalog_contracts/resources/content-planning",
        ):
            (directory / filename).write_bytes(encoded)
        print(filename, "sha256:" + hashlib.sha256(encoded).hexdigest())


if __name__ == "__main__":
    main()
