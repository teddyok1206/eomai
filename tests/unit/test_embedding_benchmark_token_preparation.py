from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from eom_catalog_service import embedding_benchmark_token_preparation as module
from eom_identifiers import content_sha256

from tests.unit.embedding_native_backend_fixtures import (
    configured_bundle,
    stage_protected_numeric_origins,
)


class Tokenizer:
    is_fast = True
    padding_side = "right"
    pad_token_id = 1

    def __init__(self, *, token_types: bool = True) -> None:
        self.token_types = token_types
        self.calls: list[tuple[tuple[str, ...], dict[str, Any]]] = []
        self.lengths: dict[str, int] = {}
        self.fault: str | None = None
        self.after_tokenize: Any = None

    def ids(self, text: str) -> list[int]:
        return [0, *[ord(value) for value in text], 2]

    def __call__(self, texts: tuple[str, ...], **kwargs: Any) -> Any:
        self.calls.append((texts, kwargs))
        ids = [
            list(range(self.lengths[text])) if text in self.lengths else self.ids(text)
            for text in texts
        ]
        result: dict[str, Any] = {
            "input_ids": ids,
            "attention_mask": [[1] * len(row) for row in ids],
        }
        if self.token_types:
            result["token_type_ids"] = [[0] * len(row) for row in ids]
        if self.fault == "not_mapping":
            return []
        if self.fault == "extra_key":
            result["offset_mapping"] = []
        elif self.fault == "missing_ids":
            del result["input_ids"]
        elif self.fault == "row_count":
            result["input_ids"] = []
        elif self.fault == "empty_ids":
            result["input_ids"][0] = []
        elif self.fault == "wrong_mask_length":
            result["attention_mask"][0].append(1)
        elif self.fault == "wrong_type_length":
            result["token_type_ids"][0].append(0)
        elif self.fault in {"bool_id", "negative_id", "float_id"}:
            result["input_ids"][0][0] = {
                "bool_id": True,
                "negative_id": -1,
                "float_id": 1.5,
            }[self.fault]
        elif self.fault == "masked":
            result["attention_mask"][0][0] = 0
        elif self.fault == "type_bool":
            result["token_type_ids"][0][0] = True
        elif self.fault == "raises":
            raise RuntimeError("private synthetic input must not be included in the error")
        if self.after_tokenize is not None:
            self.after_tokenize()
        return result


@pytest.fixture
def prepared_runtime(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, request):
    stage_protected_numeric_origins(tmp_path, monkeypatch)
    configured, bundle, root, manifest = configured_bundle(
        tmp_path, **getattr(request, "param", {})
    )
    tokenizer = Tokenizer()
    loads = []
    imports = []

    def load(path, **kwargs):
        loads.append((path, kwargs))
        return tokenizer

    class ForbiddenModel:
        def __getattr__(self, _name):
            pytest.fail("token preparation must never use AutoModel")

    transformers = SimpleNamespace(
        AutoTokenizer=SimpleNamespace(from_pretrained=load), AutoModel=ForbiddenModel()
    )
    original_import = module.importlib.import_module

    def import_module(name, *args, **kwargs):
        if name == "transformers":
            imports.append(name)
            return transformers
        assert name not in {"torch", "tokenizers", "numpy", "safetensors"}
        return original_import(name, *args, **kwargs)

    versions = {pin.name: pin.version for pin in bundle.execution_model_spec.runtime_versions}
    monkeypatch.setattr(module.importlib, "import_module", import_module)
    monkeypatch.setattr(module.importlib.metadata, "version", lambda name: versions[name])
    return SimpleNamespace(
        configured=configured,
        bundle=bundle,
        root=root,
        manifest=manifest,
        tokenizer=tokenizer,
        loads=loads,
        imports=imports,
        versions=versions,
    )


@pytest.mark.parametrize("token_types", (True, False))
def test_prepares_actual_ids_hash_with_exact_prefix_purpose_and_original_order(
    prepared_runtime, token_types
):
    runtime = prepared_runtime
    runtime.tokenizer.token_types = token_types
    texts = (
        module.BenchmarkTokenText("QUERY", "질문 수식 F=ma"),
        module.BenchmarkTokenText("DOCUMENT", "단위 36 km/h"),
        module.BenchmarkTokenText("DOCUMENT", ""),
        module.BenchmarkTokenText("QUERY", "질문 수식 F=ma"),
    )
    before = {path: path.read_bytes() for path in runtime.root.iterdir() if path.is_file()}
    result = module.prepare_benchmark_token_inputs(runtime.configured, texts)
    assert result.bundle == runtime.configured.pointer
    assert runtime.loads == [
        (
            str(runtime.root),
            {"local_files_only": True, "trust_remote_code": False, "use_fast": True},
        )
    ]
    assert runtime.imports == ["transformers"]
    assert runtime.tokenizer.calls == [
        (("query: 단위 36 km/h",), {"truncation": False, "padding": False}),
        (
            ("query: 질문 수식 F=ma", "query: 질문 수식 F=ma"),
            {"truncation": False, "padding": False},
        ),
    ]
    for text, row in zip(texts, result.rows, strict=True):
        assert row.purpose == text.purpose
        assert row.input_text_sha256 == content_sha256(text.text)
        if not text.text:
            assert row.token_count == 0 and row.token_ids_sha256 is None
        else:
            ids = runtime.tokenizer.ids("query: " + text.text)
            assert row.token_count == len(ids)
            assert row.token_ids_sha256 == content_sha256(
                {"input_ids": ids, "token_type_ids": [0] * len(ids) if token_types else None}
            )
    assert result.rows[0] == result.rows[3]
    assert before == {path: path.read_bytes() for path in runtime.root.iterdir() if path.is_file()}
    assert module.prepare_benchmark_token_inputs(runtime.configured, texts) == result
    with pytest.raises(FrozenInstanceError):
        result.rows = ()
    with pytest.raises(FrozenInstanceError):
        result.rows[0].token_count = 0


def test_exact_capacity_and_overflow_are_measured_without_truncation(prepared_runtime):
    runtime = prepared_runtime
    runtime.tokenizer.lengths = {
        "query: capacity": 2048,
        "query: overflow": 2049,
        "query: bounded overflow": 4096,
    }
    result = module.prepare_benchmark_token_inputs(
        runtime.configured,
        tuple(
            module.BenchmarkTokenText("DOCUMENT", text)
            for text in ("capacity", "overflow", "bounded overflow")
        ),
    )
    assert tuple(row.token_count for row in result.rows) == (2048, 2049, 4096)
    assert all(row.token_ids_sha256 is not None for row in result.rows)


def test_empty_negative_never_enters_tokenizer(prepared_runtime):
    runtime = prepared_runtime
    result = module.prepare_benchmark_token_inputs(
        runtime.configured, (module.BenchmarkTokenText("DOCUMENT", ""),)
    )
    assert runtime.tokenizer.calls == []
    assert result.rows == (
        module.BenchmarkPreparedTokenRow("DOCUMENT", content_sha256(""), 0, None),
    )


@pytest.mark.parametrize("prepared_runtime", ({"pooling": "CLS"},), indirect=True)
def test_bge_preparation_uses_its_actual_empty_prefix(prepared_runtime):
    runtime = prepared_runtime
    result = module.prepare_benchmark_token_inputs(
        runtime.configured,
        (module.BenchmarkTokenText("DOCUMENT", "문서"), module.BenchmarkTokenText("QUERY", "질문")),
    )
    assert runtime.bundle.execution_model_spec.upstream_repo == "BAAI/bge-m3"
    assert tuple(call[0] for call in runtime.tokenizer.calls) == (("문서",), ("질문",))
    assert tuple(row.token_count for row in result.rows) == (4, 4)


@pytest.mark.parametrize("prepared_runtime", ({"device": "CUDA"},), indirect=True)
def test_preparation_cannot_import_a_selected_cuda_bundle(prepared_runtime):
    runtime = prepared_runtime
    with pytest.raises(module.BenchmarkTokenPreparationError, match="RUNTIME_MISMATCH"):
        module.prepare_benchmark_token_inputs(
            runtime.configured, (module.BenchmarkTokenText("DOCUMENT", "x"),)
        )
    assert runtime.imports == []


@pytest.mark.parametrize("text", (" ", "\n", "x" * 262145, "가" * 87382, "\ud800"))
def test_invalid_text_is_rejected_before_preparation(text):
    with pytest.raises(module.BenchmarkTokenPreparationError, match="INPUT_INVALID"):
        module.BenchmarkTokenText("DOCUMENT", text)


@pytest.mark.parametrize("rows", ((), [module.BenchmarkTokenText("DOCUMENT", "x")], (object(),)))
def test_invalid_input_collection_fails_before_bundle_or_import(prepared_runtime, rows):
    runtime = prepared_runtime
    with pytest.raises(module.BenchmarkTokenPreparationError, match="INPUT_INVALID"):
        module.prepare_benchmark_token_inputs(runtime.configured, rows)
    assert runtime.imports == [] and runtime.loads == []


def test_maximum_row_count_and_its_overflow_are_bounded(prepared_runtime):
    runtime = prepared_runtime
    rows = (module.BenchmarkTokenText("DOCUMENT", "x"),) * 29
    assert len(module.prepare_benchmark_token_inputs(runtime.configured, rows).rows) == 29
    with pytest.raises(module.BenchmarkTokenPreparationError, match="INPUT_INVALID"):
        module.prepare_benchmark_token_inputs(runtime.configured, rows + rows[:1])
    assert len(runtime.loads) == 1


@pytest.mark.parametrize(
    "fault",
    (
        "not_mapping",
        "extra_key",
        "missing_ids",
        "row_count",
        "empty_ids",
        "wrong_mask_length",
        "wrong_type_length",
        "bool_id",
        "negative_id",
        "float_id",
        "masked",
        "type_bool",
        "raises",
    ),
)
def test_malformed_tokenizer_output_never_returns_partial_result_or_private_errors(
    prepared_runtime, fault
):
    runtime = prepared_runtime
    runtime.tokenizer.fault = fault
    with pytest.raises(module.BenchmarkTokenPreparationError) as error:
        module.prepare_benchmark_token_inputs(
            runtime.configured, (module.BenchmarkTokenText("DOCUMENT", "private synthetic input"),)
        )
    assert str(error.value) == "BENCHMARK_TOKEN_PREPARATION_TOKENIZER_INVALID"
    assert error.value.__suppress_context__ or fault != "raises"


def test_more_than_4096_actual_tokens_fail_closed(prepared_runtime):
    runtime = prepared_runtime
    runtime.tokenizer.lengths["query: too many"] = 4097
    with pytest.raises(module.BenchmarkTokenPreparationError, match="TOKENIZER_INVALID"):
        module.prepare_benchmark_token_inputs(
            runtime.configured, (module.BenchmarkTokenText("DOCUMENT", "too many"),)
        )


@pytest.mark.parametrize(
    "attribute,value",
    (("is_fast", False), ("padding_side", "left"), ("pad_token_id", True), ("pad_token_id", -1)),
)
def test_fixed_tokenizer_behavior_cannot_be_changed(prepared_runtime, attribute, value):
    runtime = prepared_runtime
    setattr(runtime.tokenizer, attribute, value)
    with pytest.raises(module.BenchmarkTokenPreparationError, match="TOKENIZER_INVALID"):
        module.prepare_benchmark_token_inputs(
            runtime.configured, (module.BenchmarkTokenText("DOCUMENT", "x"),)
        )
    assert runtime.tokenizer.calls == []


@pytest.mark.parametrize("name", ("transformers", "tokenizers"))
def test_installed_tokenizer_library_versions_are_pinned(prepared_runtime, name):
    runtime = prepared_runtime
    runtime.versions[name] = "999.0.0"
    with pytest.raises(module.BenchmarkTokenPreparationError, match="RUNTIME_MISMATCH"):
        module.prepare_benchmark_token_inputs(
            runtime.configured, (module.BenchmarkTokenText("DOCUMENT", "x"),)
        )
    assert runtime.imports == []


def test_wrong_bundle_pointer_fails_before_optional_import(prepared_runtime):
    runtime = prepared_runtime
    configured = replace(
        runtime.configured,
        pointer=runtime.configured.pointer.model_copy(
            update={"bundle_raw_sha256": "sha256:" + "0" * 64}
        ),
    )
    with pytest.raises(module.BenchmarkTokenPreparationError, match="BUNDLE_INVALID"):
        module.prepare_benchmark_token_inputs(
            configured, (module.BenchmarkTokenText("DOCUMENT", "x"),)
        )
    assert runtime.imports == []


@pytest.mark.parametrize("target", ("tokenizer", "bundle"))
def test_replaced_payload_or_bundle_after_tokenization_fails_before_return(
    prepared_runtime, target
):
    runtime = prepared_runtime
    path = runtime.root / "tokenizer.json" if target == "tokenizer" else runtime.manifest

    def replace_file():
        candidate = path.with_name("replacement")
        candidate.write_bytes(path.read_bytes())
        candidate.chmod(0o600)
        candidate.replace(path)

    runtime.tokenizer.after_tokenize = replace_file
    with pytest.raises(module.BenchmarkTokenPreparationError, match="BUNDLE_INVALID"):
        module.prepare_benchmark_token_inputs(
            runtime.configured, (module.BenchmarkTokenText("DOCUMENT", "x"),)
        )
