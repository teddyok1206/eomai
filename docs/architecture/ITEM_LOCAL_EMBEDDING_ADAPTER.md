# Optional offline Item embeddings

Status: implementation candidate, 2026-10-10 UTC. No model is installed or activated by this
document, and fake-backend tests do not establish educational quality or runtime performance.

## Boundary and model choice

The existing Catalog authorizes exact Item, Graph, policy and solution-report revisions before
passing comparison profiles to the optional ranker. The ranker reads no database, NAS, actor role
or global corpus. It returns only exact eligible profile pointers and cosine scores. Similarity
does not establish scientific correctness, plagiarism or transferable reasoning. Existing lexical
and Graph retrieval and evidence receipts remain authoritative.

The application-owned `inference_transfer_ports.py` interface has one optional infrastructure
implementation in `local_embedding_adapter.py`. Numerical dependencies are imported only when an
explicitly constructed offline backend is admitted; importing Catalog does not import torch or
Transformers. Core dependency files are unchanged. An isolated Orchestrator-managed process should
receive staged, validated profiles and a protected model pointer, return local results, and let
the Orchestrator perform validation and canonical Artifact publication. No parallel search engine,
model download at inference time, direct worker NAS write or vector database is introduced.

## Reviewed model candidates

Primary upstream metadata was inspected on 2026-10-10 UTC. These revisions are experiment
candidates, not a permanent model decision or a quality guarantee.

| Model | Exact upstream revision | Dense recipe | Safe weights |
|---|---|---|---|
| BAAI/bge-m3 | `5617a9f61b028005a4858fdac845db406aefb181` | CLS, L2, 1024 dimensions, up to 8192 tokens, no prefix | Main has only pickle weights; not admitted |
| intfloat/multilingual-e5-small | `614241f622f53c4eeff9890bdc4f31cfecc418b3` | masked mean, L2, 384 dimensions, at most 512 tokens | Native safetensors available |
| intfloat/multilingual-e5-base | `d128750597153bb5987e10b1c3493a34e5a4502a` | masked mean, L2, 768 dimensions, at most 512 tokens | Native safetensors available |

All three cards identify MIT licensing. For symmetric Item-profile similarity, E5 requires
`query: ` on both sides; its asymmetric retrieval example uses `query: ` and `passage: ` instead.
These are different recipes and must not be silently interchanged. The current symmetric contract
pins both prefixes. Absolute E5 cosine values are not calibrated judgement thresholds.

BGE-M3's upstream `pytorch_model.bin` is 2,271,145,830 bytes, SHA-256
`b5e0ce3470abf5ef3831aa1bd5553b486803e83251590ab7ff35a117cf6aad38`.
The inspected official refs expose no converted safetensors revision. Runtime must not pickle-load
it or imply a locally converted weight belongs byte-for-byte to that upstream commit. A future
conversion needs separately reviewed acquisition/provenance; initial E5 evaluation avoids that
extra mechanism.

Primary references:

- [BGE-M3 model card](https://huggingface.co/BAAI/bge-m3)
- [BGE-M3 official dense implementation](https://github.com/FlagOpen/FlagEmbedding/blob/master/FlagEmbedding/finetune/embedder/encoder_only/m3/modeling.py)
- [E5-small pinned model card](https://huggingface.co/intfloat/multilingual-e5-small/blob/614241f622f53c4eeff9890bdc4f31cfecc418b3/README.md)
- [E5-small pinned files](https://huggingface.co/intfloat/multilingual-e5-small/tree/614241f622f53c4eeff9890bdc4f31cfecc418b3)
- [E5-base pinned files](https://huggingface.co/intfloat/multilingual-e5-base/tree/d128750597153bb5987e10b1c3493a34e5a4502a)

## Small-model acquisition inventory

The five required inference files total 487,725,595 bytes. Adding the reviewed SentencePiece and
pooling configuration gives 492,794,846 bytes (about 470 MiB). Weight/tokenizer large-file hashes
come from upstream LFS metadata; small JSON files were read and hashed. This is a candidate file
inventory, not proof that local files were installed. Acquisition must verify every byte again.

| Member | Bytes | SHA-256 |
|---|---:|---|
| `config.json` | 655 | `69137736cab8b8903a07fe8afaafdda25aac55415a12a55d1bffa9f581abf959` |
| `model.safetensors` | 470641600 | `1a55775f53449dac10a2bcbc312469fac40b96d53198c407081a831f81c98477` |
| `special_tokens_map.json` | 167 | `d05497f1da52c5e09554c0cd874037a083e1dc1b9cfd48034d1c717f1afc07a7` |
| `tokenizer.json` | 17082730 | `0b44a9d7b51c3c62626640cda0e2c2f70fdacdc25bbbd68038369d14ebdf4c39` |
| `tokenizer_config.json` | 443 | `a1d6bc8734a6f635dc158508bef000f8e2e5a759c7d92f984b2c86e5ff53425b` |
| `sentencepiece.bpe.model` | 5069051 | `cfc8146abe2a0488e9e2a0c56de7952f7c11ab059eca145a0a727afce0db2865` |
| `1_Pooling/config.json` | 200 | `987f7a67a38fa564c849bb5d277c52ab9088a84368fc0be31a354125aebb12a0` |

E5-base's safetensors weight is 1,112,201,288 bytes, SHA-256
`a18a44fad1d0b46ded15928144138cff1135d5cc8233bdd90be5f18822de09a7`.
Its analogous seven-file snapshot is 1,134,354,591 bytes. Small is a more economical CPU baseline,
not a claim of superior science-question quality.

## Pointer resolution and loading

Model logical ID, immutable revision ID and canonical manifest hash remain distinct. A model path
is derived from trusted model-store configuration and those typed IDs, never model-supplied input.
The manifest binds upstream, file identities/hashes, exact runtime versions, pooling, prefixes,
normalization, dimension, dtype and overflow policy. Protected directories must not be writable by
untrusted principals. File validation rejects links, extra/unlisted files, unsafe paths, nonregular
files, changed file identity, mismatched sizes/hashes and remote-code configuration.

Loading uses CPU float32, eager attention, eval and inference mode, `local_files_only=True`,
`trust_remote_code=False`, and `use_safetensors=True`. AutoModel/Tokenizer are installed library
implementations, not Python code from the model directory. File identities are rechecked around
loading and each inference command; weights are streamed and hashed once at command admission,
not repeatedly per Item. Missing model/runtime is an explicit unavailable error, not a fallback
embedding, cloud call or changed model selection.

Concrete claim text is preserved, including numbers, units and negation. Tokenizer overflow is
rejected rather than truncating away a decisive tail condition. A shorter comparison profile must
be a deliberate exact successor; it must not silently discard facts under an old hash. E5's
512-token bound therefore needs measurement against real profiles before corpus-wide processing.

## Access patterns, complexity and runtime isolation

Only application-admitted profiles are encoded. Query and candidates are bounded separately;
candidate output references retain exact revisions and hashes. Normalized vectors must have finite
values, expected dimension and nonzero finite norm; input order and stable identity tie-breaking
are deterministic. Exact cosine comparisons cost O(Nd); selecting stable top-K adds bounded
ordering cost. Temporary vectors cost O(Nd), with N at most 1024 and d at most 4096. No mutable
global cache, persistence schema or ANN index is needed for initial experiments around 520 Items.

The public ranker provenance includes the complete immutable model recipe, manifest hash and
weight/runtime pins. The application binds it to the sorted eligible exact profile-pointer set
hash, and rechecks the same provenance around ranking. Native provenance also rechecks protected
file identities; a changed model/dimension is an error. Fake numerical backends carry explicit
`TEST_ONLY` provenance with no real model spec, never a fabricated production model identity.
Provenance construction revalidates canonical recipe hashes rather than trusting a frozen object
whose fields were bypassed with `model_copy`. Neural inference itself has model/token-dependent
cost; O(Nd) here describes exact vector comparison, not a neural runtime performance claim.

The installed image/trainer environments contain torch 2.7.1+cu128, Transformers 4.56.2,
safetensors 0.6.2 and tokenizers 0.22.2, but their interpreter is Python 3.11.15. EOM contracts use
Python 3.12 syntax, so these environments cannot import the new Catalog adapter and are not reused
or upgraded in place. API/core contain none of the neural dependencies. The optional
`infra/conda/eom-embedding-experiment.environment.yml` selects Python 3.12.13, and its adjacent
requirements lock pins CPU torch 2.7.1+cpu, Transformers 4.56.2, safe tensors/tokenizer libraries
and the existing protocol validation dependencies. The official PyTorch CPU wheel URL and SHA
avoid adding a competing global package index. Torch provides model execution; Transformers
provides installed architecture/tokenizer implementations; safetensors avoids pickle; NumPy is a
model-library requirement; the remaining entries pin their transitive dependencies. No dependency
is added to core, and no CUDA/vision/trainer/SentenceTransformers extras are installed. Runtime
and model pins must name the actual `2.7.1+cpu` distribution, not the existing CUDA variant.
An isolated process must have no
network or NAS access, bounded CPU/memory/time, read-only model/environment mounts and one staged
workspace. CPU-first experiments do not compete for the image GPU lease. Any later GPU adapter
must explicitly participate in the existing physical-GPU capacity boundary.

## Validation and evidence boundary

Fake backends test permission-prefiltered candidates, result count, invalid vectors, zero norm,
nonfinite values, mismatched dimensions, duplicates, stable ties and concrete-text preservation.
Filesystem fixtures test pinned manifests and negative resolution cases without real weights.
Lazy-import tests ensure optional dependencies are absent from core imports.

A bounded CPU toy experiment has now executed in a temporary explicit Python 3.12 Conda
environment, using seven official E5-small files whose sizes and hashes were verified again.
There were two attempts: the first completed inference but failed canonical output serialization
because it contained floats; the second passed after recording scaled integer measurements. The
failed attempt remains a failure, not a successful acceptance receipt. Exact runtime/model pins,
execution counts, measurements, temporary evidence locations and the observed ranking limitation
are recorded in the [first implementation checkpoint](ITEM_INFERENCE_TRANSFER_FIRST_CHECKPOINT.md).

This developer-process experiment is not actual corpus admission, a protected production install,
OS-level runtime-isolation acceptance or human-labelled transfer evaluation; those gates remain
pending. Record exact projection/input-set pins and authorized real-corpus outcomes when they are
executed. Neither unit tests nor the toy probe establish educational-quality PASS. Existing
lexical/Graph results remain the comparison baseline and are not replaced or relabelled by cosine
scores.
