from __future__ import annotations

import importlib
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Literal

import pytest
from eom_catalog_contracts.item_inference_transfer import LocalEmbeddingModelSpec
from eom_catalog_service.inference_transfer_ports import (
    EmbeddingRankerProvenance,
    ScoredInferenceTransferProfile,
)
from eom_catalog_service.local_embedding_adapter import (
    ExactLocalEmbeddingRanker,
    LocalEmbeddingError,
    OfflineTransformersEmbeddingBackend,
    profile_embedding_text,
)
from eom_identifiers import canonical_json_bytes, content_sha256, sha256_bytes

from tests.unit.inference_transfer_fixtures import embedding_model, profile


class FakeBackend:
    dimension = 2
    provenance = EmbeddingRankerProvenance("TEST_ONLY", None)

    def __init__(self, vectors: tuple[tuple[float, ...], ...] = ((1.0, 0.0),)) -> None:
        self.vectors = vectors
        self.query: tuple[tuple[float, ...], ...] = ((1.0, 0.0),)
        self.calls: list[tuple[tuple[str, ...], str]] = []

    def encode(
        self, texts: tuple[str, ...], *, purpose: Literal["QUERY", "DOCUMENT"]
    ) -> tuple[tuple[float, ...], ...]:
        self.calls.append((texts, purpose))
        return self.query if purpose == "QUERY" else self.vectors


def test_validated_profile_text_preserves_negation_units_and_concrete_inference() -> None:
    parsed = profile(
        condition="마찰이 없고 속력은 36 km/h이다.", inference="전체 에너지가 보존된다."
    )
    text = profile_embedding_text(parsed)
    assert text == (
        "GIVEN_CONDITION: 마찰이 없고 속력은 36 km/h이다.\n"
        "DECISIVE_INFERENCE: 전체 에너지가 보존된다."
    )
    assert parsed.profile_id not in text
    assert parsed.profile_sha256 not in text
    assert "INTERPRET_GIVEN" not in text


def test_ranker_encodes_only_application_provided_eligible_exact_profiles() -> None:
    query = profile("a")
    allowed = profile("b", condition="승인된 비교 자료 10 m/s", inference="힘의 합을 구한다.")
    denied = profile("c", condition="비공개 자료", inference="접근할 수 없는 풀이")
    backend = FakeBackend()
    result = ExactLocalEmbeddingRanker(backend).rank(query, (allowed,), top_k=5)
    assert tuple(score.profile.profile_revision_id for score in result) == (
        allowed.profile_revision_id,
    )
    assert result[0].profile.profile_sha256 == allowed.profile_sha256
    assert backend.calls == [
        ((profile_embedding_text(query),), "QUERY"),
        ((profile_embedding_text(allowed),), "DOCUMENT"),
    ]
    assert all("비공개" not in text for texts, _purpose in backend.calls for text in texts)
    assert denied.profile_id not in repr(result)


def test_exact_cosine_normalizes_and_stable_ties_ignore_candidate_input_order() -> None:
    backend = FakeBackend(((3.0, 4.0), (6.0, 8.0)))
    ranker = ExactLocalEmbeddingRanker(backend)
    a, b = profile("b"), profile("c")
    forward = ranker.rank(profile("a"), (a, b), top_k=2)
    reverse = ranker.rank(profile("a"), (b, a), top_k=2)
    assert forward == reverse
    assert forward[0].profile.profile_id == a.profile_id
    assert forward[0].cosine_similarity == pytest.approx(0.6)


@pytest.mark.parametrize(
    "vector", [(0.0, 0.0), (float("nan"), 1.0), (float("inf"), 1.0), (1.0,), (True, 0.0)]
)
@pytest.mark.parametrize("purpose", ["QUERY", "DOCUMENT"])
def test_invalid_query_or_candidate_vector_fails_explicitly(
    vector: tuple[float, ...], purpose: str
) -> None:
    backend = FakeBackend((vector,))
    if purpose == "QUERY":
        backend.query = (vector,)
    with pytest.raises(LocalEmbeddingError, match="VECTOR_INVALID"):
        ExactLocalEmbeddingRanker(backend).rank(profile("a"), (profile("b"),), top_k=1)


@pytest.mark.parametrize("vectors", [(), ((1.0, 0.0), (0.0, 1.0))])
def test_backend_result_count_must_match_exact_input_count(
    vectors: tuple[tuple[float, ...], ...],
) -> None:
    with pytest.raises(LocalEmbeddingError, match="VECTOR_INVALID"):
        ExactLocalEmbeddingRanker(FakeBackend(vectors)).rank(profile("a"), (profile("b"),), top_k=1)


@pytest.mark.parametrize("top_k", [0, 101, True, 1.5, "1", None])
def test_invalid_budget_fails_before_any_embedding(top_k: Any) -> None:
    backend = FakeBackend()
    with pytest.raises(LocalEmbeddingError, match="INPUT_INVALID"):
        ExactLocalEmbeddingRanker(backend).rank(profile("a"), (profile("b"),), top_k=top_k)
    assert backend.calls == []


@pytest.mark.parametrize("dimension", [True, 1.5, "384", None, 0, 4097])
def test_invalid_backend_dimension_is_not_a_numeric_model_recipe(dimension: Any) -> None:
    backend = FakeBackend()
    backend.dimension = dimension
    with pytest.raises(LocalEmbeddingError, match="VECTOR_INVALID"):
        ExactLocalEmbeddingRanker(backend)
    assert backend.calls == []


@pytest.mark.parametrize("score", [True, float("nan"), float("inf"), 1.01, "0.5", None])
def test_public_cosine_score_is_a_finite_real_value_not_a_boolean(score: Any) -> None:
    from eom_catalog_contracts.item_inference_transfer import InferenceTransferProfilePointer

    with pytest.raises(ValueError, match="cosine similarity"):
        ScoredInferenceTransferProfile(
            InferenceTransferProfilePointer.from_profile(profile()), score
        )


def test_duplicate_exact_profile_fails_before_any_embedding() -> None:
    backend = FakeBackend()
    candidate = profile("b")
    with pytest.raises(LocalEmbeddingError, match="DUPLICATE_PROFILE"):
        ExactLocalEmbeddingRanker(backend).rank(profile("a"), (candidate, candidate), top_k=1)
    assert backend.calls == []


def test_empty_scope_has_no_model_call_or_global_corpus_fallback() -> None:
    backend = FakeBackend()
    assert ExactLocalEmbeddingRanker(backend).rank(profile("a"), (), top_k=1) == ()
    assert backend.calls == []


def test_fake_backend_explicitly_has_no_actual_model_or_recipe_claim() -> None:
    ranker = ExactLocalEmbeddingRanker(FakeBackend())
    assert ranker.provenance == EmbeddingRankerProvenance("TEST_ONLY", None)
    assert ranker.model_spec is None
    with pytest.raises(ValueError, match="provenance"):
        EmbeddingRankerProvenance("PINNED_MODEL", None)
    with pytest.raises(ValueError, match="provenance"):
        EmbeddingRankerProvenance("TEST_ONLY", embedding_model())
    forged = embedding_model().model_copy(update={"manifest_sha256": "sha256:" + "0" * 64})
    with pytest.raises(ValueError, match="canonical content"):
        EmbeddingRankerProvenance("PINNED_MODEL", forged)


def test_ranker_refuses_changed_dimension_or_model_selection() -> None:
    backend = FakeBackend()
    ranker = ExactLocalEmbeddingRanker(backend)
    backend.dimension = 3
    with pytest.raises(LocalEmbeddingError, match="MODEL_CHANGED"):
        ranker.rank(profile("a"), (profile("b"),), top_k=1)
    assert backend.calls == []


def _model_tree(tmp_path: Path) -> tuple[Path, LocalEmbeddingModelSpec]:
    spec = embedding_model("intfloat/multilingual-e5-small")
    value = spec.model_dump(mode="json", exclude={"manifest_sha256"})
    payloads = {
        "config.json": canonical_json_bytes({"hidden_size": 384, "model_type": "bert"}),
        "model.safetensors": b"synthetic bytes: fake loader only, never real weights",
        "tokenizer.json": b"{}",
        "tokenizer_config.json": b"{}",
        "special_tokens_map.json": b"{}",
    }
    value["files"] = [
        {"member_path": name, "size_bytes": len(payload), "sha256": sha256_bytes(payload)}
        for name, payload in sorted(payloads.items())
    ]
    value["manifest_sha256"] = content_sha256(value)
    spec = LocalEmbeddingModelSpec.model_validate(value)
    root = tmp_path / spec.model_id / spec.model_revision_id
    root.mkdir(parents=True, mode=0o700)
    root.parent.chmod(0o700)
    tmp_path.chmod(0o700)
    for name, payload in payloads.items():
        (root / name).write_bytes(payload)
        (root / name).chmod(0o600)
    (root / "manifest.json").write_bytes(canonical_json_bytes(spec.model_dump(mode="json")))
    (root / "manifest.json").chmod(0o600)
    return root, spec


class FakeMask:
    def unsqueeze(self, _dimension: int) -> FakeMask:
        return self

    def bool(self) -> FakeMask:
        return self

    def __invert__(self) -> FakeMask:
        return self

    def sum(self, *, dim: int) -> FakeMask:
        return self


class FakePooled:
    def __init__(self, count: int) -> None:
        self.count = count

    def __truediv__(self, _other: Any) -> FakePooled:
        return self

    def tolist(self) -> list[list[float]]:
        return [[2.0, 1.0] + [0.0] * 382 for _index in range(self.count)]


class FakeHidden:
    def __init__(self, count: int) -> None:
        self.count = count

    def masked_fill(self, _mask: Any, _value: float) -> FakeHidden:
        return self

    def sum(self, *, dim: int) -> FakePooled:
        return FakePooled(self.count)


def _fake_loader(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    from contextlib import nullcontext

    observed: dict[str, Any] = {"texts": [], "model_calls": 0, "imports": []}

    class Tokenizer:
        def __call__(self, texts: tuple[str, ...], **kwargs: Any) -> dict[str, Any]:
            observed["texts"].append((texts, kwargs))
            return {"input_ids": [list(range(len(text.split()) + 2)) for text in texts]}

        def pad(self, tokens: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
            return tokens | {"attention_mask": FakeMask()}

    class Model:
        config = SimpleNamespace(hidden_size=384)

        def to(self, device: str) -> Model:
            observed["device"] = device
            return self

        def eval(self) -> Model:
            observed["eval"] = True
            return self

        def __call__(self, **tokens: Any) -> Any:
            observed["model_calls"] += 1
            return SimpleNamespace(last_hidden_state=FakeHidden(len(tokens["input_ids"])))

    def tokenizer_load(path: str, **kwargs: Any) -> Tokenizer:
        observed["tokenizer_load"] = (path, kwargs)
        return Tokenizer()

    def model_load(path: str, **kwargs: Any) -> Model:
        observed["model_load"] = (path, kwargs)
        return Model()

    torch = SimpleNamespace(float32="float32", inference_mode=nullcontext)
    transformers = SimpleNamespace(
        AutoTokenizer=SimpleNamespace(from_pretrained=tokenizer_load),
        AutoModel=SimpleNamespace(from_pretrained=model_load),
    )
    original_import = importlib.import_module

    def load_module(name: str, package: str | None = None) -> Any:
        observed["imports"].append(name)
        if name == "torch":
            return torch
        if name == "transformers":
            return transformers
        return original_import(name, package)

    monkeypatch.setattr(importlib.metadata, "version", lambda _name: "1.0.0")
    monkeypatch.setattr(importlib, "import_module", load_module)
    return observed


def test_offline_loader_uses_pinned_safe_cpu_recipe_and_bounded_batching(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, spec = _model_tree(tmp_path)
    observed = _fake_loader(monkeypatch)
    backend = OfflineTransformersEmbeddingBackend(
        tmp_path, spec, expected_owner_uid=os.geteuid(), batch_size=2
    )
    assert backend.model_spec == spec
    assert backend.provenance == EmbeddingRankerProvenance("PINNED_MODEL", spec)
    vectors = backend.encode(("마찰이 없다 36 km/h", "전류는 2 A", "온도는 20 ℃"), purpose="QUERY")
    assert len(vectors) == 3
    assert all(len(vector) == 384 for vector in vectors)
    assert observed["device"] == "cpu" and observed["eval"]
    assert observed["model_load"][0] == str(root)
    assert observed["model_load"][1] == {
        "local_files_only": True,
        "trust_remote_code": False,
        "use_safetensors": True,
        "dtype": "float32",
        "attn_implementation": "eager",
    }
    assert observed["tokenizer_load"][1] == {
        "local_files_only": True,
        "trust_remote_code": False,
        "use_fast": True,
    }
    assert observed["model_calls"] == 2
    assert observed["texts"][0] == (
        ("query: 마찰이 없다 36 km/h", "query: 전류는 2 A"),
        {"truncation": False, "padding": False},
    )


@pytest.mark.parametrize("batch_size", [0, 17, True, 1.5, "4", None])
def test_invalid_batch_budget_fails_before_model_resolution_or_import(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, batch_size: Any
) -> None:
    observed = _fake_loader(monkeypatch)
    with pytest.raises(LocalEmbeddingError, match="INPUT_INVALID"):
        OfflineTransformersEmbeddingBackend(
            tmp_path, embedding_model(), expected_owner_uid=os.geteuid(), batch_size=batch_size
        )
    assert observed["imports"] == []


@pytest.mark.parametrize("purpose", ["QUERY", "DOCUMENT"])
def test_overflow_rejects_without_erasing_tail_negation_or_running_model(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, purpose: Literal["QUERY", "DOCUMENT"]
) -> None:
    _root, spec = _model_tree(tmp_path)
    observed = _fake_loader(monkeypatch)
    backend = OfflineTransformersEmbeddingBackend(tmp_path, spec, expected_owner_uid=os.geteuid())
    with pytest.raises(LocalEmbeddingError, match="INPUT_TOO_LONG"):
        backend.encode(("물체 " * 520 + "마찰이 없다 36 km/h",), purpose=purpose)
    assert observed["model_calls"] == 0
    assert observed["texts"][0][0][0].endswith("마찰이 없다 36 km/h")


@pytest.mark.parametrize(
    "fault", ["missing", "extra", "hash", "size", "symlink", "hardlink", "write_mode", "stale"]
)
def test_model_resolution_fails_before_numerical_import_for_untrusted_or_wrong_pointer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fault: str
) -> None:
    root, spec = _model_tree(tmp_path)
    observed = _fake_loader(monkeypatch)
    weight = root / "model.safetensors"
    if fault == "missing":
        weight.unlink()
    elif fault == "extra":
        (root / "pytorch_model.bin").write_bytes(b"must never load pickle")
    elif fault == "hash":
        weight.write_bytes(b"x" * weight.stat().st_size)
    elif fault == "size":
        weight.write_bytes(b"x")
    elif fault == "symlink":
        weight.unlink()
        weight.symlink_to(root / "tokenizer.json")
    elif fault == "hardlink":
        weight.unlink()
        os.link(root / "tokenizer.json", weight)
    elif fault == "write_mode":
        weight.chmod(0o660)
    else:
        value = spec.model_dump(mode="json", exclude={"manifest_sha256"})
        value["model_revision_id"] = "embeddingmodelrev_" + "c" * 32
        spec = LocalEmbeddingModelSpec.model_validate(
            value | {"manifest_sha256": content_sha256(value)}
        )
    with pytest.raises(LocalEmbeddingError, match=r"MODEL_INVALID|HASH_MISMATCH"):
        OfflineTransformersEmbeddingBackend(tmp_path, spec, expected_owner_uid=os.geteuid())
    assert observed["imports"] == []


def test_changed_runtime_or_loaded_model_never_silently_substitutes_latest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, spec = _model_tree(tmp_path)
    observed = _fake_loader(monkeypatch)
    monkeypatch.setattr(importlib.metadata, "version", lambda _name: "2.0.0")
    with pytest.raises(LocalEmbeddingError, match="RUNTIME_UNSUPPORTED"):
        OfflineTransformersEmbeddingBackend(tmp_path, spec, expected_owner_uid=os.geteuid())
    assert observed["imports"] == []
    monkeypatch.setattr(importlib.metadata, "version", lambda _name: "1.0.0")
    backend = OfflineTransformersEmbeddingBackend(tmp_path, spec, expected_owner_uid=os.geteuid())
    (root / "model.safetensors").write_bytes(b"changed after model load")
    with pytest.raises(LocalEmbeddingError, match="MODEL_CHANGED"):
        _ = backend.provenance
    with pytest.raises(LocalEmbeddingError, match="MODEL_CHANGED"):
        backend.encode(("마찰이 없다",), purpose="QUERY")
    assert observed["model_calls"] == 0


@pytest.mark.parametrize(
    "configuration", [{"auto_map": {"AutoModel": "external.Model"}}, {"trust_remote_code": False}]
)
def test_even_hash_pinned_remote_code_configuration_is_rejected_before_import(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, configuration: dict[str, Any]
) -> None:
    root, spec = _model_tree(tmp_path)
    observed = _fake_loader(monkeypatch)
    payload = canonical_json_bytes(configuration)
    (root / "config.json").write_bytes(payload)
    value = spec.model_dump(mode="json", exclude={"manifest_sha256"})
    for member in value["files"]:
        if member["member_path"] == "config.json":
            member["size_bytes"] = len(payload)
            member["sha256"] = sha256_bytes(payload)
    spec = LocalEmbeddingModelSpec.model_validate(
        value | {"manifest_sha256": content_sha256(value)}
    )
    (root / "manifest.json").write_bytes(canonical_json_bytes(spec.model_dump(mode="json")))
    with pytest.raises(LocalEmbeddingError, match="MODEL_INVALID"):
        OfflineTransformersEmbeddingBackend(tmp_path, spec, expected_owner_uid=os.geteuid())
    assert observed["imports"] == []


def test_unsafe_model_directory_is_rejected_without_version_or_import_lookup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, spec = _model_tree(tmp_path)
    observed = _fake_loader(monkeypatch)
    root.parent.chmod(0o770)
    with pytest.raises(LocalEmbeddingError, match="MODEL_INVALID"):
        OfflineTransformersEmbeddingBackend(tmp_path, spec, expected_owner_uid=os.geteuid())
    assert observed["imports"] == []


def test_directory_link_inside_trusted_store_is_not_an_immutable_model_revision(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, spec = _model_tree(tmp_path)
    observed = _fake_loader(monkeypatch)
    original = root.parent
    replacement = tmp_path / "alternate"
    original.rename(replacement)
    original.symlink_to(replacement, target_is_directory=True)
    with pytest.raises(LocalEmbeddingError, match="MODEL_INVALID"):
        OfflineTransformersEmbeddingBackend(tmp_path, spec, expected_owner_uid=os.geteuid())
    assert observed["imports"] == []


def test_manifest_hash_or_pointer_tampering_is_not_implicit_latest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, spec = _model_tree(tmp_path)
    observed = _fake_loader(monkeypatch)
    raw = (root / "manifest.json").read_bytes().replace(b'"dimension":384', b'"dimension":768')
    (root / "manifest.json").write_bytes(raw)
    with pytest.raises(LocalEmbeddingError, match="MODEL_INVALID"):
        OfflineTransformersEmbeddingBackend(tmp_path, spec, expected_owner_uid=os.geteuid())
    assert observed["imports"] == []


@pytest.mark.parametrize("invalid", ["", "  ", 5, None])
def test_non_text_or_blank_input_does_not_reach_tokenizer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, invalid: Any
) -> None:
    _root, spec = _model_tree(tmp_path)
    observed = _fake_loader(monkeypatch)
    backend = OfflineTransformersEmbeddingBackend(tmp_path, spec, expected_owner_uid=os.geteuid())
    with pytest.raises(LocalEmbeddingError, match="INPUT_INVALID"):
        backend.encode((invalid,), purpose="QUERY")
    assert observed["texts"] == []


@pytest.mark.parametrize("texts", ["마찰이 없다", ["마찰이 없다"], None])
def test_backend_requires_an_immutable_text_batch_not_character_iteration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, texts: Any
) -> None:
    _root, spec = _model_tree(tmp_path)
    observed = _fake_loader(monkeypatch)
    backend = OfflineTransformersEmbeddingBackend(tmp_path, spec, expected_owner_uid=os.geteuid())
    with pytest.raises(LocalEmbeddingError, match="INPUT_INVALID"):
        backend.encode(texts, purpose="QUERY")
    assert observed["texts"] == []


def test_core_import_never_imports_optional_numeric_dependencies() -> None:
    code = (
        "import sys; import eom_catalog_service.local_embedding_adapter; "
        "assert not any(name in sys.modules "
        "for name in ('torch','transformers','safetensors','numpy'))"
    )
    completed = subprocess.run(
        [sys.executable, "-c", code], check=False, capture_output=True, text=True
    )
    assert completed.returncode == 0, completed.stderr
