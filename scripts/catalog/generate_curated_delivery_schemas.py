"""Generate only new delivery contracts; never reinterpret predecessor schemas."""

import argparse
import hashlib
import json
from pathlib import Path

from eom_catalog_contracts.curated_document_delivery_application import (
    CuratedDocumentDeliveryQueryV1,
    CuratedDocumentDeliveryResponseV1,
)

ROOT = Path(__file__).resolve().parents[2]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    for branch, model in (
        ("request", CuratedDocumentDeliveryQueryV1),
        ("response", CuratedDocumentDeliveryResponseV1),
    ):
        value = model.model_json_schema()
        value.update(
            {
                "$schema": "https://json-schema.org/draft/2020-12/schema",
                "$id": f"eom://schemas/catalog-application/curated-document-delivery-{branch}/1.0",
            }
        )
        raw = (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode()
        filename = f"catalog-curated-document-delivery-{branch}-v1.schema.json"
        for directory in (
            ROOT / "schemas/catalog-application",
            ROOT / "packages/catalog_contracts/eom_catalog_contracts/resources/catalog-application",
        ):
            path = directory / filename
            if args.check:
                if path.read_bytes() != raw:
                    raise SystemExit("curated delivery schema differs: " + str(path))
            else:
                path.write_bytes(raw)
        print(filename + " sha256:" + hashlib.sha256(raw).hexdigest())


if __name__ == "__main__":
    main()
