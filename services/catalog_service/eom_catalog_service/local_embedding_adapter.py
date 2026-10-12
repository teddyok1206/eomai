"""Optional offline dense embeddings; no model dependency is imported in Catalog core."""

from __future__ import annotations

import hashlib
import importlib
import importlib.metadata
import json
import os
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from eom_catalog_contracts.inference_transfer_text import concrete_profile_text
from eom_catalog_contracts.item_inference_transfer import (
    InferenceTransferProfile,
    InferenceTransferProfilePointer,
    LocalEmbeddingModelSpec,
)
from eom_identifiers import canonical_json_bytes

from eom_catalog_service.inference_transfer_ports import (
    EmbeddingRankerProvenance,
    LocalTextEmbeddingBackend,
    ScoredInferenceTransferProfile,
)
from eom_catalog_service.inference_transfer_vectors import (
    normalized_vector,
    rank_normalized_vectors,
)

_MAX_PROFILE_BYTES = 256 * 1024
_MAX_CANDIDATES = 1024
_MAX_MANIFEST_BYTES = 128 * 1024
_SAFE_FILES = frozenset(
    {
        "config.json",
        "model.safetensors",
        "tokenizer.json",
        "tokenizer_config.json",
        "special_tokens_map.json",
        "sentencepiece.bpe.model",
        "1_Pooling/config.json",
        "README.md",
        "LICENSE",
    }
)


class LocalEmbeddingError(ValueError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def profile_embedding_text(profile: InferenceTransferProfile) -> str:
    """Preserve concrete statements, including negation/units, without embedding internal IDs."""

    text = concrete_profile_text(profile)
    if not text.strip() or len(text.encode("utf-8")) > _MAX_PROFILE_BYTES:
        raise LocalEmbeddingError("LOCAL_EMBEDDING_INPUT_INVALID")
    return text


def _normalized(vector: tuple[float, ...], dimension: int) -> tuple[float, ...]:
    try:
        return normalized_vector(vector, dimension)
    except ValueError as exc:
        raise LocalEmbeddingError("LOCAL_EMBEDDING_VECTOR_INVALID") from exc


class ExactLocalEmbeddingRanker:
    """One bounded exact O(Nd) comparison, using no global index, cache, or authority."""

    def __init__(self, backend: LocalTextEmbeddingBackend) -> None:
        if type(backend.dimension) is not int or not 1 <= backend.dimension <= 4096:
            raise LocalEmbeddingError("LOCAL_EMBEDDING_VECTOR_INVALID")
        self._backend = backend
        self._dimension = backend.dimension
        self._initial_provenance = backend.provenance
        spec = self._initial_provenance.model_spec
        if spec is not None and spec.dimension != self._dimension:
            raise LocalEmbeddingError("LOCAL_EMBEDDING_VECTOR_INVALID")

    @property
    def provenance(self) -> EmbeddingRankerProvenance:
        current = self._backend.provenance
        if current != self._initial_provenance or self._backend.dimension != self._dimension:
            raise LocalEmbeddingError("LOCAL_EMBEDDING_MODEL_CHANGED")
        return current

    @property
    def model_spec(self) -> LocalEmbeddingModelSpec | None:
        return self.provenance.model_spec

    def rank(
        self,
        query_profile: InferenceTransferProfile,
        eligible_profiles: tuple[InferenceTransferProfile, ...],
        *,
        top_k: int,
    ) -> tuple[ScoredInferenceTransferProfile, ...]:
        if type(top_k) is not int or not 1 <= top_k <= 100:
            raise LocalEmbeddingError("LOCAL_EMBEDDING_INPUT_INVALID")
        if len(eligible_profiles) > _MAX_CANDIDATES:
            raise LocalEmbeddingError("LOCAL_EMBEDDING_INPUT_INVALID")
        if not eligible_profiles:
            return ()
        before = self.provenance
        references = tuple(
            InferenceTransferProfilePointer(
                profile_id=profile.profile_id,
                profile_revision_id=profile.profile_revision_id,
                profile_sha256=profile.profile_sha256,
            )
            for profile in eligible_profiles
        )
        keys = tuple(
            (ref.profile_id, ref.profile_revision_id, ref.profile_sha256) for ref in references
        )
        if len(set(keys)) != len(keys):
            raise LocalEmbeddingError("LOCAL_EMBEDDING_DUPLICATE_PROFILE")
        query_vectors = self._backend.encode(
            (profile_embedding_text(query_profile),), purpose="QUERY"
        )
        vectors = self._backend.encode(
            tuple(profile_embedding_text(profile) for profile in eligible_profiles),
            purpose="DOCUMENT",
        )
        if len(query_vectors) != 1 or len(vectors) != len(references):
            raise LocalEmbeddingError("LOCAL_EMBEDDING_VECTOR_INVALID")
        query = _normalized(query_vectors[0], self._dimension)
        candidates = tuple(
            (reference, _normalized(vector, self._dimension))
            for reference, vector in zip(references, vectors, strict=True)
        )
        if self.provenance != before:
            raise LocalEmbeddingError("LOCAL_EMBEDDING_MODEL_CHANGED")
        return rank_normalized_vectors(query, candidates, top_k=top_k)


@dataclass(frozen=True)
class _FileEpoch:
    path: Path
    identity: tuple[int, int, int, int, int]


@dataclass(frozen=True)
class ProtectedEmbeddingManifest:
    """Small verified metadata bytes; no weights or permission grant are materialized."""

    path: Path
    raw: bytes
    sha256: str
    _owner_uid: int
    _epochs: tuple[_FileEpoch, ...]

    def assert_unchanged(self) -> None:
        _assert_snapshot_unchanged(self.path.parent, self._owner_uid, self._epochs)


@dataclass(frozen=True)
class ResolvedLocalEmbeddingPayload:
    """Supported immutable payload seam shared by legacy verification and successors."""

    root: Path
    model_spec: LocalEmbeddingModelSpec
    manifest: ProtectedEmbeddingManifest
    _owner_uid: int
    _epochs: tuple[_FileEpoch, ...]

    def assert_unchanged(self) -> None:
        _assert_snapshot_unchanged(self.root, self._owner_uid, self._epochs)
        self.manifest.assert_unchanged()


def _assert_snapshot_unchanged(root: Path, owner_uid: int, epochs: tuple[_FileEpoch, ...]) -> None:
    try:
        _require_safe_path(root, expected_owner_uid=owner_uid)
        for epoch in epochs:
            if _file_identity(epoch.path.lstat()) != epoch.identity:
                raise LocalEmbeddingError("LOCAL_EMBEDDING_MODEL_CHANGED")
    except OSError as exc:
        raise LocalEmbeddingError("LOCAL_EMBEDDING_MODEL_CHANGED") from exc


def _file_identity(value: os.stat_result) -> tuple[int, int, int, int, int]:
    return value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns, value.st_ctime_ns


def _require_safe_path(path: Path, *, expected_owner_uid: int) -> None:
    if not path.is_absolute() or ".." in path.parts:
        raise LocalEmbeddingError("LOCAL_EMBEDDING_MODEL_INVALID")
    for component in (path, *path.parents):
        value = component.lstat()
        if stat.S_ISLNK(value.st_mode):
            raise LocalEmbeddingError("LOCAL_EMBEDDING_MODEL_INVALID")
    value = path.lstat()
    if (
        not stat.S_ISDIR(value.st_mode)
        or value.st_uid != expected_owner_uid
        or stat.S_IMODE(value.st_mode) & 0o022
    ):
        raise LocalEmbeddingError("LOCAL_EMBEDDING_MODEL_INVALID")


def _read_verified_file(
    path: Path, *, owner_uid: int, maximum_bytes: int, retain_bytes: bool
) -> tuple[bytes, str, _FileEpoch]:
    descriptor = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        value = os.fstat(descriptor)
        if (
            not stat.S_ISREG(value.st_mode)
            or value.st_uid != owner_uid
            or value.st_nlink != 1
            or stat.S_IMODE(value.st_mode) & 0o022
            or not 0 < value.st_size <= maximum_bytes
        ):
            raise LocalEmbeddingError("LOCAL_EMBEDDING_MODEL_INVALID")
        digest = hashlib.sha256()
        chunks = []
        observed = 0
        while chunk := os.read(descriptor, 1024 * 1024):
            observed += len(chunk)
            if observed > maximum_bytes:
                raise LocalEmbeddingError("LOCAL_EMBEDDING_MODEL_INVALID")
            digest.update(chunk)
            if retain_bytes:
                chunks.append(chunk)
        if observed != value.st_size or _file_identity(value) != _file_identity(
            os.fstat(descriptor)
        ):
            raise LocalEmbeddingError("LOCAL_EMBEDDING_MODEL_CHANGED")
        return (
            b"".join(chunks),
            "sha256:" + digest.hexdigest(),
            _FileEpoch(path, _file_identity(value)),
        )
    finally:
        os.close(descriptor)


def _reject_remote_configuration(value: Any) -> None:
    if isinstance(value, dict):
        if "auto_map" in value or "trust_remote_code" in value:
            raise LocalEmbeddingError("LOCAL_EMBEDDING_MODEL_INVALID")
        for member in value.values():
            _reject_remote_configuration(member)
    elif isinstance(value, list):
        for member in value:
            _reject_remote_configuration(member)


class OfflineTransformersEmbeddingBackend:
    """Explicit isolated CPU backend; construction never downloads or imports remote code."""

    def __init__(
        self,
        model_store_root: Path,
        spec: LocalEmbeddingModelSpec,
        *,
        expected_owner_uid: int = 0,
        batch_size: int = 4,
        threads: int = 4,
    ) -> None:
        if (
            type(batch_size) is not int
            or not 1 <= batch_size <= 16
            or type(threads) is not int
            or not 1 <= threads <= 16
        ):
            raise LocalEmbeddingError("LOCAL_EMBEDDING_INPUT_INVALID")
        spec = LocalEmbeddingModelSpec.model_validate(spec.model_dump(mode="json"))
        self._spec = spec
        self._owner_uid = expected_owner_uid
        self._batch_size = batch_size
        self._epochs: tuple[_FileEpoch, ...] = ()
        self._model: Any = None
        self._tokenizer: Any = None
        self._torch: Any = None
        self._root = model_store_root / spec.model_id / spec.model_revision_id
        try:
            self._resolve(model_store_root, expected_owner_uid)
            for requirement in spec.runtime_versions:
                if importlib.metadata.version(requirement.name) != requirement.version:
                    raise LocalEmbeddingError("LOCAL_EMBEDDING_RUNTIME_UNSUPPORTED")
            self._torch = importlib.import_module("torch")
            self._torch.set_num_threads(threads)
            transformers = importlib.import_module("transformers")
            self._tokenizer = transformers.AutoTokenizer.from_pretrained(
                str(self._root), local_files_only=True, trust_remote_code=False, use_fast=True
            )
            self._model = (
                transformers.AutoModel.from_pretrained(
                    str(self._root),
                    local_files_only=True,
                    trust_remote_code=False,
                    use_safetensors=True,
                    dtype=self._torch.float32,
                    attn_implementation="eager",
                )
                .to("cpu")
                .eval()
            )
            if self._model.config.hidden_size != spec.dimension:
                raise LocalEmbeddingError("LOCAL_EMBEDDING_MODEL_INVALID")
            self._assert_unchanged()
        except LocalEmbeddingError:
            raise
        except (ImportError, importlib.metadata.PackageNotFoundError) as exc:
            raise LocalEmbeddingError("LOCAL_EMBEDDING_RUNTIME_UNSUPPORTED") from exc
        except (OSError, ValueError, TypeError, KeyError) as exc:
            raise LocalEmbeddingError("LOCAL_EMBEDDING_MODEL_INVALID") from exc

    @property
    def dimension(self) -> int:
        return self._spec.dimension

    @property
    def provenance(self) -> EmbeddingRankerProvenance:
        self._assert_unchanged()
        spec = LocalEmbeddingModelSpec.model_validate(self._spec.model_dump(mode="json"))
        return EmbeddingRankerProvenance("PINNED_MODEL", spec)

    @property
    def model_spec(self) -> LocalEmbeddingModelSpec:
        spec = self.provenance.model_spec
        if spec is None:
            raise LocalEmbeddingError("LOCAL_EMBEDDING_MODEL_INVALID")
        return spec

    def _resolve(self, model_store_root: Path, owner_uid: int) -> None:
        self._epochs = _resolve_embedding_snapshot(model_store_root, self._spec, owner_uid)

    def _assert_unchanged(self) -> None:
        try:
            _require_safe_path(self._root, expected_owner_uid=self._owner_uid)
            for epoch in self._epochs:
                if _file_identity(epoch.path.lstat()) != epoch.identity:
                    raise LocalEmbeddingError("LOCAL_EMBEDDING_MODEL_CHANGED")
        except OSError as exc:
            raise LocalEmbeddingError("LOCAL_EMBEDDING_MODEL_CHANGED") from exc

    def _validate_texts(
        self, texts: tuple[str, ...], purpose: Literal["QUERY", "DOCUMENT"]
    ) -> None:
        if (
            not isinstance(texts, tuple)
            or purpose not in {"QUERY", "DOCUMENT"}
            or len(texts) > _MAX_CANDIDATES
            or any(
                not isinstance(text, str)
                or not text.strip()
                or len(text.encode("utf-8")) > _MAX_PROFILE_BYTES
                for text in texts
            )
        ):
            raise LocalEmbeddingError("LOCAL_EMBEDDING_INPUT_INVALID")
        self._assert_unchanged()

    def _tokenize(self, texts: tuple[str, ...], purpose: Literal["QUERY", "DOCUMENT"]) -> Any:
        prefix = self._spec.query_prefix if purpose == "QUERY" else self._spec.document_prefix
        return self._tokenizer(
            tuple(prefix + text for text in texts), truncation=False, padding=False
        )

    def token_lengths(
        self, texts: tuple[str, ...], *, purpose: Literal["QUERY", "DOCUMENT"]
    ) -> tuple[int, ...]:
        self._validate_texts(texts, purpose)
        lengths: list[int] = []
        try:
            for index in range(0, len(texts), self._batch_size):
                tokens = self._tokenize(texts[index : index + self._batch_size], purpose)
                lengths.extend(len(ids) for ids in tokens["input_ids"])
            if len(lengths) != len(texts):
                raise LocalEmbeddingError("LOCAL_EMBEDDING_INFERENCE_FAILED")
            self._assert_unchanged()
        except LocalEmbeddingError:
            raise
        except (OSError, ValueError, TypeError, KeyError, RuntimeError) as exc:
            raise LocalEmbeddingError("LOCAL_EMBEDDING_INFERENCE_FAILED") from exc
        return tuple(lengths)

    def encode(
        self, texts: tuple[str, ...], *, purpose: Literal["QUERY", "DOCUMENT"]
    ) -> tuple[tuple[float, ...], ...]:
        self._validate_texts(texts, purpose)
        output: list[tuple[float, ...]] = []
        try:
            for index in range(0, len(texts), self._batch_size):
                tokens = self._tokenize(texts[index : index + self._batch_size], purpose)
                if any(len(ids) > self._spec.maximum_tokens for ids in tokens["input_ids"]):
                    raise LocalEmbeddingError("LOCAL_EMBEDDING_INPUT_TOO_LONG")
                padded = self._tokenizer.pad(tokens, padding=True, return_tensors="pt")
                with self._torch.inference_mode():
                    hidden = self._model(**padded).last_hidden_state
                    if self._spec.pooling == "CLS":
                        pooled = hidden[:, 0]
                    else:
                        mask = padded["attention_mask"].unsqueeze(-1).bool()
                        pooled = hidden.masked_fill(~mask, 0.0).sum(dim=1)
                        pooled = pooled / padded["attention_mask"].sum(dim=1).unsqueeze(-1)
                    output.extend(
                        _normalized(tuple(row), self.dimension) for row in pooled.tolist()
                    )
            self._assert_unchanged()
        except LocalEmbeddingError:
            raise
        except (OSError, ValueError, TypeError, KeyError, RuntimeError) as exc:
            raise LocalEmbeddingError("LOCAL_EMBEDDING_INFERENCE_FAILED") from exc
        return tuple(output)


def _resolve_embedding_snapshot(
    model_store_root: Path, spec: LocalEmbeddingModelSpec, owner_uid: int
) -> tuple[_FileEpoch, ...]:
    root = model_store_root / spec.model_id / spec.model_revision_id
    _require_safe_path(model_store_root, expected_owner_uid=owner_uid)
    _require_safe_path(root.parent, expected_owner_uid=owner_uid)
    _require_safe_path(root, expected_owner_uid=owner_uid)
    raw, _sha, manifest_epoch = _read_verified_file(
        root / "manifest.json",
        owner_uid=owner_uid,
        maximum_bytes=_MAX_MANIFEST_BYTES,
        retain_bytes=True,
    )
    manifest = LocalEmbeddingModelSpec.model_validate_json(raw)
    if manifest != spec or raw not in (
        canonical_json_bytes(manifest.model_dump(mode="json")),
        canonical_json_bytes(manifest.model_dump(mode="json")) + b"\n",
    ):
        raise LocalEmbeddingError("LOCAL_EMBEDDING_MODEL_INVALID")
    expected = {file.member_path for file in manifest.files}
    observed: set[str] = set()
    directories = [model_store_root, root.parent, root]
    for parent, names, files in os.walk(root, followlinks=False):
        for name in names:
            directory = Path(parent) / name
            _require_safe_path(directory, expected_owner_uid=owner_uid)
            directories.append(directory)
        observed.update((Path(parent) / name).relative_to(root).as_posix() for name in files)
    if not expected <= _SAFE_FILES or observed != expected | {"manifest.json"}:
        raise LocalEmbeddingError("LOCAL_EMBEDDING_MODEL_INVALID")
    epochs = [*(_FileEpoch(path, _file_identity(path.lstat())) for path in directories)]
    epochs.append(manifest_epoch)
    for member in manifest.files:
        retain = member.member_path in {"config.json", "tokenizer_config.json"}
        maximum = min(member.size_bytes, 128 * 1024) if retain else member.size_bytes
        payload, sha, epoch = _read_verified_file(
            root / member.member_path,
            owner_uid=owner_uid,
            maximum_bytes=maximum,
            retain_bytes=retain,
        )
        if epoch.identity[2] != member.size_bytes or sha != member.sha256:
            raise LocalEmbeddingError("LOCAL_EMBEDDING_HASH_MISMATCH")
        if retain:
            _reject_remote_configuration(json.loads(payload))
        epochs.append(epoch)
    for epoch in epochs:
        if _file_identity(epoch.path.lstat()) != epoch.identity:
            raise LocalEmbeddingError("LOCAL_EMBEDDING_MODEL_CHANGED")
    return tuple(epochs)


def verify_local_embedding_model_snapshot(
    model_store_root: Path,
    spec: LocalEmbeddingModelSpec,
    *,
    expected_owner_uid: int = 0,
) -> LocalEmbeddingModelSpec:
    """Validate the exact offline snapshot without importing libraries or loading a model.

    This is filesystem/hash verification, not an authorization or inference-quality proof.
    The numerical adapter and installed negative probe share this authoritative resolver.
    """
    try:
        validated = LocalEmbeddingModelSpec.model_validate(spec.model_dump(mode="json"))
        _resolve_embedding_snapshot(model_store_root, validated, expected_owner_uid)
        return validated
    except LocalEmbeddingError:
        raise
    except (OSError, ValueError, TypeError, KeyError) as exc:
        raise LocalEmbeddingError("LOCAL_EMBEDDING_MODEL_INVALID") from exc


def read_protected_embedding_manifest(
    path: Path,
    *,
    expected_owner_uid: int = 0,
    maximum_bytes: int = _MAX_MANIFEST_BYTES,
) -> ProtectedEmbeddingManifest:
    """Read bounded owner-configured metadata using the authoritative protected-file checks.

    Locations come from trusted adapter configuration, never a worker-supplied path.
    Exact schema/hash/lifecycle/authority closure belongs to its resolver/owner.
    """
    try:
        if type(maximum_bytes) is not int or not 1 <= maximum_bytes <= _MAX_MANIFEST_BYTES:
            raise LocalEmbeddingError("LOCAL_EMBEDDING_MODEL_INVALID")
        _require_safe_path(path.parent, expected_owner_uid=expected_owner_uid)
        directory_epochs = (_FileEpoch(path.parent, _file_identity(path.parent.lstat())),)
        raw, sha, epoch = _read_verified_file(
            path,
            owner_uid=expected_owner_uid,
            maximum_bytes=maximum_bytes,
            retain_bytes=True,
        )
        result = ProtectedEmbeddingManifest(
            path, raw, sha, expected_owner_uid, (*directory_epochs, epoch)
        )
        result.assert_unchanged()
        return result
    except LocalEmbeddingError:
        raise
    except (OSError, ValueError, TypeError, KeyError) as exc:
        raise LocalEmbeddingError("LOCAL_EMBEDDING_MODEL_INVALID") from exc


def resolve_local_embedding_payload(
    model_store_root: Path,
    spec: LocalEmbeddingModelSpec,
    *,
    expected_owner_uid: int = 0,
) -> ResolvedLocalEmbeddingPayload:
    """Resolve the exact legacy payload once, retaining only small metadata and stat epochs.

    Successors do not reinterpret the legacy runtime pins or pass their flat spec into
    the legacy manifest check. Member hashes are streamed by the unchanged resolver.
    """
    try:
        checked = LocalEmbeddingModelSpec.model_validate(spec.model_dump(mode="json"))
        epochs = _resolve_embedding_snapshot(model_store_root, checked, expected_owner_uid)
        root = model_store_root / checked.model_id / checked.model_revision_id
        manifest = read_protected_embedding_manifest(
            root / "manifest.json", expected_owner_uid=expected_owner_uid
        )
        result = ResolvedLocalEmbeddingPayload(root, checked, manifest, expected_owner_uid, epochs)
        result.assert_unchanged()
        return result
    except LocalEmbeddingError:
        raise
    except (OSError, ValueError, TypeError, KeyError) as exc:
        raise LocalEmbeddingError("LOCAL_EMBEDDING_MODEL_INVALID") from exc
