"""Prepare bounded benchmark token expectations; never load a model or grant authority."""

from __future__ import annotations

import importlib
import importlib.metadata
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

from eom_catalog_contracts.embedding_runtime_bundle import EmbeddingRuntimeBundlePointer
from eom_identifiers import content_sha256

from eom_catalog_service.embedding_bundle_resolver import (
    ConfiguredEmbeddingBundle,
    EmbeddingBundleResolutionError,
    resolve_configured_embedding_bundle,
)

_MAX_ROWS = 29
_MAX_TEXT_BYTES = 262144
_MAX_TOKENS = 4096
_PURPOSES: tuple[Literal["DOCUMENT", "QUERY"], ...] = ("DOCUMENT", "QUERY")
_SHA256 = re.compile(r"sha256:[0-9a-f]{64}\Z")


class BenchmarkTokenPreparationError(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class BenchmarkTokenText:
    """Already authorized exact view/public fixture; this value grants no source rights."""

    purpose: Literal["DOCUMENT", "QUERY"]
    text: str

    def __post_init__(self) -> None:
        if (
            self.purpose not in _PURPOSES
            or type(self.text) is not str
            or (self.text != "" and not self.text.strip())
        ):
            raise BenchmarkTokenPreparationError("BENCHMARK_TOKEN_PREPARATION_INPUT_INVALID")
        try:
            size = len(self.text.encode("utf-8"))
        except UnicodeError:
            raise BenchmarkTokenPreparationError(
                "BENCHMARK_TOKEN_PREPARATION_INPUT_INVALID"
            ) from None
        if size > _MAX_TEXT_BYTES:
            raise BenchmarkTokenPreparationError("BENCHMARK_TOKEN_PREPARATION_INPUT_INVALID")


@dataclass(frozen=True, slots=True)
class BenchmarkPreparedTokenRow:
    """Small expected hashes, not a native execution/token witness or an access grant."""

    purpose: Literal["DOCUMENT", "QUERY"]
    input_text_sha256: str
    token_count: int
    token_ids_sha256: str | None

    def __post_init__(self) -> None:
        if (
            self.purpose not in _PURPOSES
            or type(self.input_text_sha256) is not str
            or _SHA256.fullmatch(self.input_text_sha256) is None
            or type(self.token_count) is not int
            or not 0 <= self.token_count <= _MAX_TOKENS
            or (
                self.token_ids_sha256 is None
                if self.token_count
                else self.token_ids_sha256 is not None
            )
            or (
                self.token_ids_sha256 is not None
                and (
                    type(self.token_ids_sha256) is not str
                    or _SHA256.fullmatch(self.token_ids_sha256) is None
                )
            )
            or (self.token_count == 0 and self.input_text_sha256 != content_sha256(""))
        ):
            raise BenchmarkTokenPreparationError("BENCHMARK_TOKEN_PREPARATION_TOKENIZER_INVALID")


@dataclass(frozen=True, slots=True)
class BenchmarkPreparedTokens:
    bundle: EmbeddingRuntimeBundlePointer
    rows: tuple[BenchmarkPreparedTokenRow, ...]


def _matrix(value: object, expected_rows: int) -> tuple[tuple[int, ...], ...]:
    if not isinstance(value, (tuple, list)) or len(value) != expected_rows:
        raise BenchmarkTokenPreparationError("BENCHMARK_TOKEN_PREPARATION_TOKENIZER_INVALID")
    rows = []
    for row in value:
        if (
            type(row) not in (tuple, list)
            or not 1 <= len(row) <= _MAX_TOKENS
            or any(type(token) is not int or token < 0 for token in row)
        ):
            raise BenchmarkTokenPreparationError("BENCHMARK_TOKEN_PREPARATION_TOKENIZER_INVALID")
        rows.append(tuple(row))
    return tuple(rows)


def _prepared_batch(
    texts: tuple[BenchmarkTokenText, ...], value: object
) -> tuple[BenchmarkPreparedTokenRow, ...]:
    if not isinstance(value, Mapping) or (
        set(value) - {"input_ids", "attention_mask", "token_type_ids"}
        or not {"input_ids", "attention_mask"}.issubset(value)
    ):
        raise BenchmarkTokenPreparationError("BENCHMARK_TOKEN_PREPARATION_TOKENIZER_INVALID")
    ids = _matrix(value["input_ids"], len(texts))
    masks = _matrix(value["attention_mask"], len(texts))
    raw_types = value.get("token_type_ids")
    types = None if raw_types is None else _matrix(raw_types, len(texts))
    rows = []
    for index, text in enumerate(texts):
        token_types = None if types is None else types[index]
        if masks[index] != (1,) * len(ids[index]) or (
            token_types is not None and len(token_types) != len(ids[index])
        ):
            raise BenchmarkTokenPreparationError("BENCHMARK_TOKEN_PREPARATION_TOKENIZER_INVALID")
        rows.append(
            BenchmarkPreparedTokenRow(
                text.purpose,
                content_sha256(text.text),
                len(ids[index]),
                content_sha256({"input_ids": ids[index], "token_type_ids": token_types}),
            )
        )
    return tuple(rows)


def prepare_benchmark_token_inputs(
    configured: ConfiguredEmbeddingBundle,
    texts: tuple[BenchmarkTokenText, ...],
) -> BenchmarkPreparedTokens:
    """Read one verified local tokenizer and prepare expected hashes in input order.

    Call only after the owning application authorizes/materializes the exact selected
    source views. This leaf writes nothing and does not authorize publication, issue
    native evidence, instantiate AutoModel or run a numerical forward.
    """
    try:
        if (
            type(configured) is not ConfiguredEmbeddingBundle
            or type(texts) is not tuple
            or not 1 <= len(texts) <= _MAX_ROWS
            or any(type(text) is not BenchmarkTokenText for text in texts)
        ):
            raise BenchmarkTokenPreparationError("BENCHMARK_TOKEN_PREPARATION_INPUT_INVALID")
        for text in texts:
            text.__post_init__()
        resolved = resolve_configured_embedding_bundle(configured)
        if resolved.bundle.numerical_runtime.device.kind != "CPU":
            raise BenchmarkTokenPreparationError("BENCHMARK_TOKEN_PREPARATION_RUNTIME_MISMATCH")
        spec = resolved.bundle.execution_model_spec
        versions: dict[str, str] = {pin.name: pin.version for pin in spec.runtime_versions}
        if any(
            importlib.metadata.version(name) != versions[name]
            for name in ("transformers", "tokenizers")
        ):
            raise BenchmarkTokenPreparationError("BENCHMARK_TOKEN_PREPARATION_RUNTIME_MISMATCH")
        transformers = importlib.import_module("transformers")
        tokenizer = transformers.AutoTokenizer.from_pretrained(
            str(resolved.payload.root),
            local_files_only=True,
            trust_remote_code=False,
            use_fast=True,
        )
        if (
            tokenizer.is_fast is not True
            or tokenizer.padding_side != "right"
            or type(tokenizer.pad_token_id) is not int
            or tokenizer.pad_token_id < 0
        ):
            raise BenchmarkTokenPreparationError("BENCHMARK_TOKEN_PREPARATION_TOKENIZER_INVALID")
        resolved.assert_unchanged()
        rows: list[BenchmarkPreparedTokenRow | None] = [
            BenchmarkPreparedTokenRow(text.purpose, content_sha256(""), 0, None)
            if text.text == ""
            else None
            for text in texts
        ]
        for purpose in _PURPOSES:
            positions = tuple(
                index for index, text in enumerate(texts) if text.purpose == purpose and text.text
            )
            if not positions:
                continue
            selected = tuple(texts[index] for index in positions)
            prefix = spec.query_prefix if purpose == "QUERY" else spec.document_prefix
            batch = tokenizer(
                tuple(prefix + text.text for text in selected), truncation=False, padding=False
            )
            resolved.assert_unchanged()
            for index, row in zip(positions, _prepared_batch(selected, batch), strict=True):
                rows[index] = row
        prepared = tuple(row for row in rows if row is not None)
        if len(prepared) != len(texts):
            raise BenchmarkTokenPreparationError("BENCHMARK_TOKEN_PREPARATION_TOKENIZER_INVALID")
        resolved.assert_unchanged()
        return BenchmarkPreparedTokens(configured.pointer, prepared)
    except BenchmarkTokenPreparationError:
        raise
    except EmbeddingBundleResolutionError:
        raise BenchmarkTokenPreparationError("BENCHMARK_TOKEN_PREPARATION_BUNDLE_INVALID") from None
    except importlib.metadata.PackageNotFoundError:
        raise BenchmarkTokenPreparationError(
            "BENCHMARK_TOKEN_PREPARATION_RUNTIME_MISMATCH"
        ) from None
    except Exception:
        # Tokenizer/import exceptions may quote private selected text or local paths.
        raise BenchmarkTokenPreparationError(
            "BENCHMARK_TOKEN_PREPARATION_TOKENIZER_INVALID"
        ) from None
