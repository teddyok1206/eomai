# Bounded benchmark token preparation

2026-10-18 UTC. Design before behavior; existing benchmark1.0 input and token
witness schemas remain unchanged. No operating corpus, tokenizer or model was run.

1. Responsibility: prepare the expected count/token-ID hashes needed by the
   existing benchmark inputs, without loading a numerical model. This Catalog
   infrastructure leaf neither selects sources nor authorizes or starts a Job.
2. Canonical source: the caller's already authorized exact rendered text and the
   existing `ConfiguredEmbeddingBundle` resolved by the official bundle/payload
   resolver. Historical BGE coverage may select strata, not supply missing IDs.
3. Preserve bundle/model/Artifact/revision and content-hash identities. The frozen
   returned value pins the exact runtime-bundle pointer and small per-row hashes;
   it creates no logical entity, revision, Artifact, registry or wire message.
4. Resolve and revalidate the protected local bundle/payload before and after
   tokenization. Check the exact installed transformers/tokenizers versions.
   Load `AutoTokenizer` from that resolved local directory with local-only,
   remote-code-disabled, fast-tokenizer arguments. Never load `AutoModel`.
5. Access is stable ordered iteration over at most29 inputs:18 DOCUMENT rows,
   2 QUERY rows,8 public protocol cases and1 capacity text. The caller supplies
   only the selected authorized rows, not a second full corpus snapshot.
6. Use frozen tuples/value objects and a two-purpose positional batch mapping.
   Keep no mutable/global cache and no new index or dependency. Empty negative
   input is recorded before tokenization; whitespace-only input is invalid.
7. Work is O(selected UTF-8/token bytes), bounded by29 texts of262144 UTF-8 bytes
   and4096 unpadded tokens each. The fixed payload audit is reused from the
   existing resolver. No vectors, tensors, forwards, padding or truncation occur.
8. The owner must authorize sources before this explicit local materialization
   boundary and reauthorize canonical publication later. No DB transaction,
   credential, lease or authority object is accepted or fabricated by this leaf.
9. Catalog infrastructure depends on the existing contracts/bundle resolver;
   domain/contract packages do not import tokenizers. Optional ML imports remain
   lazy, inside the explicitly selected isolated runtime. No CLI or service added.
10. Validate actual IDs, all-one unpadded masks and optional token types; hash
    exactly the released `{input_ids, token_type_ids}` value used by
    `encode_observed`, not a new attention-mask witness. Failure returns a stable
    content-free error and no partial result. The operation writes nothing, so
    repeating it produces the same values without a Job/model retry.
11. Reusing normal INDEX/QUERY results would be simpler but those contracts do
    not retain token-ID hashes. Constructing the existing numerical backend would
    unnecessarily load the model. This bounded preparation closes that gap without
    another framework, protocol, backend hierarchy or arbitrary tokenizer port.

Source tests use only synthetic local payloads and fake tokenizer imports; they
must prove exact prefixes/order/hashes, overflow/empty behavior, immutable return
values, bundle/runtime failure and post-load mutation rejection. They are not
actual token preparation, source authorization or six-launch acceptance.

The actual six launches, all nine owner gates and original-Job finalization remain
separate. The existing numerical/timing readers and launch receipts do not provide
an actual SANDBOX or IMAGE_TRAINER_REGRESSION proof reader; caller PASS values must
not replace those missing concrete evidence checks.

## Source verification

Three focused suites:126 PASS/3.89s, including synthetic tokenizer preparation,
exact bundle resolution and runtime-bundle contracts. Strict mypy1, Ruff/check,
format2 and diff checks PASS. JUnit:
`/tmp/eom-benchmark-preparation.AFzIkR8y-token-preparation-final.xml`.
The first invocation used installed rather than detached-worktree imports and
collected no new tests; the corrected invocation initially exposed a mock that
also denied legitimate schema-resource imports. The fake now intercepts only the
optional tokenizer import and rejects numerical-library imports. No production
schema or resolver rule was weakened. Actual corpus/tokenizer/model/DB/runtime
operations remain0; the actual selected source preparation and finalization are
still operating work, not implied by these source tests.

Root repeated the same three suites after transfer to the main workspace:
126 PASS/3.95s, strict mypy1 and Ruff/format2 PASS. Evidence:
`/tmp/eom-index-ledger-db.Cbcjez2P/token-preparation-root.xml`, raw
`f7b4b34d6c2dd181470356d5b6e7d53e43783f40375a594423cbb8d95cd481fb`.
This remains tokenizer-preparation source verification, not actual tokenization.
