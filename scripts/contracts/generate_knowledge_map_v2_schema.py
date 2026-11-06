"""Add external provenance without changing released Map V1 bytes."""

import hashlib
import json
from pathlib import Path


def main():
    root = Path(__file__).resolve().parents[2]
    value = json.loads((root / "schemas/knowledge/knowledge-map-view-v1.schema.json").read_text())
    value["$id"] = "eom://schemas/knowledge/knowledge-map-view/2.0"
    value["properties"]["schema_version"]["const"] = "knowledge-map-view/2.0"
    value["$defs"]["layer"]["enum"].append("EXTERNAL")
    value["$defs"]["node"]["properties"]["layers"]["maxItems"] = 8
    payload = (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode()
    for directory in (
        root / "schemas/knowledge",
        root / "packages/catalog_contracts/eom_catalog_contracts/resources/knowledge",
    ):
        (directory / "knowledge-map-view-v2.schema.json").write_bytes(payload)
    print("knowledge-map-view-v2 sha256:" + hashlib.sha256(payload).hexdigest())


if __name__ == "__main__":
    main()
