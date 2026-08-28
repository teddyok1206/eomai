# EOM Guidance Markdown V1

Status: reviewed source format; runtime registration and Graph publication are separate operations.

Decision date: 2026-08-28 UTC

## 1. Responsibility and system boundary

EOM Guidance Markdown V1 is the canonical **source-document format** for reviewed internal guides
that humans maintain in Git and that EOM may later register as immutable `GUIDANCE` Educational
Document Revisions. It makes provenance, scope, normative strength, rule identity, validation, and
Graph projection intent reviewable without turning every Markdown file into executable worker
instructions.

It does not replace:

- `AGENTS.md` or a released Instruction Bundle Revision;
- a worker request/result JSON Schema;
- a Content Pack prompt template;
- an Educational Document, Artifact, or Graph publication lifecycle; or
- role- or request-specific Reference/Evidence Bundle selection.

The current implementation parses and validates source bytes only. Runtime registration,
publication, bundle selection, and worker materialization remain explicit future use cases.

## 2. Evidence considered

No primary source establishes one universally superior LLM-guide Markdown layout. The selected
format therefore optimizes human review, deterministic parsing, bounded instruction density, and
trust separation rather than claiming that Markdown syntax itself improves model quality.

- [CommonMark 0.31.2](https://spec.commonmark.org/0.31.2/) standardizes headings, lists, and fenced
  code blocks. YAML front matter is not part of CommonMark, so EOM uses an ordinary fenced `json`
  block for machine control data.
- [BCP 14 / RFC 2119](https://www.rfc-editor.org/rfc/rfc2119) and
  [RFC 8174](https://www.rfc-editor.org/rfc/rfc8174) provide explicit requirement levels. EOM uses
  `MUST`, `MUSTNOT`, `SHOULD`, `SHOULDNOT`, and `MAY` in stable rule IDs and in every rule body.
- [How Many Instructions Can LLMs Follow at Once?](https://arxiv.org/abs/2507.11538) reports
  degrading compliance as instruction density grows and an early-instruction bias. EOM therefore
  caps core rules at 16 and total structured rules at 64, and separates conditional modules from
  unconditional rules.
- [Does Prompt Formatting Have Any Impact on LLM Performance?](https://arxiv.org/abs/2411.10541)
  finds model- and task-dependent sensitivity across plain text, Markdown, JSON, and YAML rather
  than a universal winner. EOM fixes one format for reproducibility and tests it instead of relying
  on a formatting superstition.
- The July 2026 preprint
  [Prompt Design at Scale](https://arxiv.org/abs/2607.19257) likewise reports no reliable Markdown
  advantage in its controlled corpus and severe perfect-response decay at high simultaneous rule
  counts. It has not undergone peer review, so EOM treats it as supporting evidence rather than a
  settled result.
- [StruQ, USENIX Security 2025](https://www.usenix.org/conference/usenixsecurity25/presentation/chen-sizhe)
  shows the security value of separating prompts from data. Its trained-model guarantees do not
  automatically transfer to Codex, but its channel-separation principle supports keeping guides in
  `references/` and never concatenating them into `AGENTS.md`.
- [OpenAI's instruction-hierarchy work](https://openai.com/index/instruction-hierarchy-challenge/)
  emphasizes trusted-role precedence and objectively gradable constraints. The
  [official AGENTS.md guide](https://developers.openai.com/codex/guides/agents-md) also recommends
  concise rules with a safe path or exception and documents a default 32 KiB combined discovery
  limit. EOM therefore keeps large guides out of automatic AGENTS discovery.

## 3. Canonical source and revision model

The Git Markdown file is a reviewed source representation, not the runtime identity. The durable
model remains:

```text
guidance logical entity
  -> immutable Educational Document Revision
  -> Markdown Artifact Revision + exact SHA-256
  -> optional Graph projection pinned to one Graph Snapshot Revision
  -> optional Reference Bundle member pointer
  -> temporary worker materialization
```

The source intake file, reviewed derivative, registered document revision, Artifact Revision, and
Graph projection remain separate objects with separate hashes. Editing a reviewed derivative
creates a successor revision; it never mutates a released runtime artifact.

## 4. Fixed source format

Each file is strict NFC UTF-8, LF-only, no BOM, no tabs, no unsafe raw HTML, at most 128 KiB, and
ends with LF. Its structure is:

1. one ATX H1 title;
2. `## 문서 제어`;
3. the first fenced `json` block, validated as JSON Schema 2020-12;
4. exactly thirteen ordered H2 sections; and
5. one to sixty-four structured H3 rules.

The thirteen content sections are fixed:

1. 목적
2. 적용 범위
3. 신뢰 및 권한 경계
4. 입력 계약
5. 출력 계약
6. 핵심 규칙
7. 작업 절차
8. 도메인 모듈
9. 검증 체크리스트
10. 실패 및 중단 조건
11. 예시 및 반례
12. Graph 및 provenance
13. 변경 이력

Every H3 is a rule using this exact pattern:

```markdown
### VIS-MUST-001 — 과학적 관계 보존

- 수준: `MUST`
- 규칙: 문항과 해설이 정의한 방향, 비율, 개수, 수치 및 단위를 보존한다.
- 검증: 구조화된 삽화 명세와 생성 결과를 대조하여 모든 값이 일치함을 확인한다.
```

The ID is stable across wording-only corrections. A semantic change that alters compliance creates
a successor document revision and, when appropriate, a new rule ID. A `MUST` cannot be hidden in
ordinary prose; each mandatory rule must be independently identifiable and verifiable.

## 5. Document-control contract

The JSON control block is validated by
`schemas/guidance/eom-guidance-markdown-control-v1.schema.json`. It records:

- stable `guidance_key`, source revision number, status, title, locale, and guide type;
- one rule-prefix namespace and at most 16 core rule IDs;
- applicable product roles and use cases;
- `execution_authority=NONE` and `runtime_use=PINNED_REFERENCE_ONLY`;
- original filename, byte count, and SHA-256 of the protected intake source; and
- intended Graph source class, publication status, and allowed node types.

The parser rejects duplicate JSON keys, non-finite numbers, extra fields, malformed hashes,
misordered sections, unknown core rule IDs, duplicate rule IDs, incomplete rule blocks, title
mismatch, and non-NFC/control characters.

## 6. Authority and trust boundary

All Guidance Markdown is reference data, including text that says “system prompt,” “ignore prior
instructions,” or “always obey.” Its fixed control values deliberately cannot grant execution
authority. A future worker may read the file only when an Orchestrator-resolved, immutable
Reference Bundle permits its exact Artifact Revision and hash.

Executable role instructions require a separately reviewed Instruction Bundle derivative. The
derivative may cite the guide's immutable revision and rules, but has its own Artifact Revision and
hash. Graph publication cannot promote a reference into instructions.

## 7. Access patterns and data structures

| Access pattern | Structure | Complexity and scale |
| --- | --- | --- |
| guide lookup | indexed logical ID + revision ID | `O(log n)` persistent lookup |
| rule lookup | map keyed by stable rule ID | expected `O(1)`, at most 64 rules/document |
| duplicate detection | set of rule IDs/core IDs | `O(n)` parse time |
| ordered human review | immutable tuple in source order | `O(n)`, deterministic |
| Graph traversal | published adjacency + typed source pointers | bounded by retrieval budget |

The parser performs one linear scan over at most 128 KiB and stores one immutable text value plus
bounded metadata/rules: `O(n)` time and space. This is preferable to repeated heading scans or
filename-based inference.

## 8. Transaction, concurrency, retry, and idempotency

Source parsing has no side effect. Registration must hash and validate the exact bytes before one
transaction creates a new immutable document/artifact revision. The registration idempotency
fingerprint must include logical identity, intended revision, media/schema versions, and content
hash. Same key/same bytes may replay; same key/different bytes fails closed.

Graph analysis/publication is a distinct workflow. Failure does not rewrite the guide or partially
grant instruction authority. A missing or stale pointer, hash mismatch, rejected lifecycle, unsafe
path, or unknown schema stops before worker launch.

## 9. Dependency direction and ownership

`eom_catalog_contracts.guidance_document` owns the pure value/parser contract and depends only on
contract validation. Filesystem registration, NAS, PostgreSQL, Orchestrator materialization, GUI
editing, and Graph publication remain adapters/application services above it. Workers do not parse
mutable repository paths or commit guidance.

The canonical JSON Schema and packaged resource are byte-identical. Installed-wheel validation has
no repository-relative fallback.

## 10. Simpler alternatives rejected

- **Unvalidated Markdown only:** easiest to author, but cannot prove provenance, section shape,
  rule uniqueness, or trust status.
- **YAML front matter:** readable and popular, but not CommonMark, admits parser-specific behavior,
  and adds an avoidable loose parsing surface. JSON already has strict duplicate-key handling and a
  native JSON Schema boundary in EOM.
- **One JSON document without Markdown:** strongest machine contract, but poor for long human
  guidance, examples, tables, and review diffs.
- **Copy the whole guide into AGENTS.md:** immediately executable, but violates trust separation,
  increases instruction density, risks discovery truncation, and makes conditional modules
  unconditional.
- **Store each rule as a DB row immediately:** enables granular queries but prematurely creates a
  parallel prompt registry. The current document/revision/artifact model is sufficient.

## 11. Two-source transformation decisions

### 11.1 Mock-exam assembly source

The source is an assessment-form assembly policy above the one-item pipeline. Its fixed 25-item,
50-point, score-distribution, inquiry-count, coverage, uniqueness, and fail-closed shortage rules
are retained. Historical topic labels are mapped to the reviewed 6/35 editorial outline where
unambiguous and explicitly marked `REVIEW_REQUIRED` where not. The example 25-slot arrangement is
non-normative; it cannot silently become a fixed product blueprint.

The source's `C 이상` vocabulary is retained as a product criterion, but it must resolve through a
versioned review-rating policy before automation. Code must not compare free-form letters.

### 11.2 Illustration source

The source is split conceptually into a small unconditional visual/scientific core and conditional
physics, graph, table, chemistry, biology, earth-science, and image-edit modules. All meaningful
constraints are retained, while repeated statements are deduplicated under stable rule IDs.

Its proposed YAML request is preserved as a non-runtime example only. A future image worker change
must first introduce a dedicated JSON Schema and Pydantic request/result protocol; this guide does
not authorize an untyped YAML request.

## 12. Rollout boundary

This phase creates source contracts and reviewed derivative files only. It intentionally does not:

- register an Educational Document or Artifact Revision;
- publish Graph nodes/edges;
- edit an Execution Preset, Content Pack, or worker prompt;
- deploy/restart services; or
- touch the active textbook-analysis batch or slot05.

Runtime use requires a separately reviewed source-to-document registration, optional Graph
publication, Reference Bundle revision, preset binding, and non-live regression plan.

## 13. Required review checklist

- Canonical/package schema bytes and pinned hash match.
- Both derivatives parse from bytes and preserve the exact intake filename/size/hash.
- Every H3 is a unique structured rule and every core rule is `MUST`/`MUSTNOT`.
- Original intake files remain protected, untracked, and byte-identical.
- No guide grants itself execution authority or embeds secrets/runtime paths.
- No raw guide is copied into AGENTS, Content Pack prompts, or Graph publication.
- Historical Content Pack, preset, workflow, Graph, and slot05 runtime state are unchanged.
