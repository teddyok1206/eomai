"""JSON Schema 2020-12 validation backed by wheel-owned resources."""

from __future__ import annotations

import hashlib
import json
from functools import lru_cache
from importlib.resources import files
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource

SCHEMA_FILES = {
    "composite-receipt": "local-image-composite-receipt-v1.schema.json",
    "composite-request": "local-image-composite-request-v1.schema.json",
    "model-manifest": "local-image-model-manifest-v1.schema.json",
    "provider-binding": "local-image-provider-binding-v1.schema.json",
    "generation-request": "local-image-generation-request-v1.schema.json",
    "generation-receipt": "local-image-generation-receipt-v1.schema.json",
    "quality-evaluation-plan": "local-image-quality-evaluation-plan-v1.schema.json",
    "quality-evaluation-result": "local-image-quality-evaluation-result-v1.schema.json",
    "training-authorization": "local-image-training-authorization-v1.schema.json",
    "training-candidate-inventory": ("local-image-training-candidate-inventory-v1.schema.json"),
    "training-dataset-manifest": "local-image-training-dataset-manifest-v1.schema.json",
    "training-eligibility-review": ("local-image-training-eligibility-review-v1.schema.json"),
    "lora-training-plan": "local-image-lora-training-plan-v1.schema.json",
    "lora-adapter-manifest": "local-image-lora-adapter-manifest-v1.schema.json",
    "lora-checkpoint-manifest": "local-image-lora-checkpoint-manifest-v1.schema.json",
    "lora-training-receipt": "local-image-lora-training-receipt-v1.schema.json",
    "lora-training-command": "local-image-lora-training-command-v1.schema.json",
    "lora-training-worker-result": ("local-image-lora-training-worker-result-v1.schema.json"),
}
SCHEMA_SHA256 = {
    "composite-receipt": "sha256:5a2c87fac79464d4e0fcc8a0ed2bf5a2b1be309c5da867eaeb757e2c23784256",
    "composite-request": "sha256:a238142416462d0dd597d06973ebc180e57c57acf61dc089c79209f6f1a8f4d9",
    "model-manifest": "sha256:f3c0d55b27e16785c14f04a52be0c84cfc23cb7fe10f9e40654891f907804fd3",
    "provider-binding": "sha256:5669a9e9d47b0e681b165dd7a8d71500d7f0552c968759273d4107eb488f00be",
    "generation-request": "sha256:8107b01c9f088bbf0b9d3c63e58c29252a5125acf5f5fb157be74f02cdb3839e",
    "generation-receipt": "sha256:eccd1c2b335ee6709c3962e3649784f16db120cc68eed7faf2e491db6efc3982",
    "quality-evaluation-plan": (
        "sha256:d0968b5e3237cef4edd5581f8e72e768c0e9c4c64efd4008d1bdeaed2c1497ca"
    ),
    "quality-evaluation-result": (
        "sha256:58ec74c1d1485fdaa5847bdfa8adb8603743d68db7f6c612ac36cf2f524a3335"
    ),
    "training-authorization": (
        "sha256:766c4f1facc36e59b0a12a3d1403bc98b6c00cf8a0206e894c5f42877c361c88"
    ),
    "training-dataset-manifest": (
        "sha256:ecb43e5ed58af59b40056a2afa0f541b12caffb71dee733aaa2681aef694c81c"
    ),
    "training-eligibility-review": (
        "sha256:28568f2e83c23e9d4d94cb8c9e967a193082dbbc35c332148b1e9ccf3bcbd4b9"
    ),
    "training-candidate-inventory": (
        "sha256:c9908e54437663d1044822c61ff1c7ada6e1de09be8f08b72d2932b1849a9ee2"
    ),
    "lora-training-plan": (
        "sha256:f55bb6a9f5560764aa21174a91d5f187d430aed20a8c0cbcbfe24e430f49fdf5"
    ),
    "lora-adapter-manifest": (
        "sha256:6ff652980b8b3599d0843395820d0e468270cfd17e9ab733a6b7ee28d6acb546"
    ),
    "lora-checkpoint-manifest": (
        "sha256:ceaafc8068624e4ff460b852b636ce8d468c203480c9ed94d0d1337620e62f6b"
    ),
    "lora-training-receipt": (
        "sha256:4fa7cb556139374b6964baa8aa028350843d2f7d85ff680a66f673e24f127089"
    ),
    "lora-training-command": (
        "sha256:6b7c6eb7acf0253b37cd627309bc8c1633f71da8becae2b760ba19cdb3ab4aa4"
    ),
    "lora-training-worker-result": (
        "sha256:310500458a4496105816c55b207bd39daa842dcfd3fa02a820f462484441f6d7"
    ),
}


@lru_cache(maxsize=len(SCHEMA_FILES))
def load_schema(name: str) -> dict[str, Any]:
    try:
        filename = SCHEMA_FILES[name]
    except KeyError as exc:
        raise ValueError(f"unknown local image contract: {name}") from exc
    resource = files("eom_image_contracts").joinpath("schemas", filename)
    raw = resource.read_bytes()
    if "sha256:" + hashlib.sha256(raw).hexdigest() != SCHEMA_SHA256[name]:
        raise ValueError(f"local image contract hash mismatch: {name}")
    value: dict[str, Any] = json.loads(raw.decode("utf-8"))
    Draft202012Validator.check_schema(value)
    return value


def validate_contract(name: str, value: dict[str, Any]) -> None:
    Draft202012Validator(
        load_schema(name),
        registry=_schema_registry(),
        format_checker=FormatChecker(),
    ).validate(value)


@lru_cache(maxsize=1)
def _schema_registry() -> Registry[Any]:
    resources = []
    for name in sorted(SCHEMA_FILES):
        schema = load_schema(name)
        identifier = schema.get("$id")
        if not isinstance(identifier, str):
            raise ValueError(f"local image contract lacks an identifier: {name}")
        resources.append((identifier, Resource.from_contents(schema)))
    return Registry().with_resources(resources)
