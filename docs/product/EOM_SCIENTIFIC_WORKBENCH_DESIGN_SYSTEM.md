# EOM Scientific Workbench Design System

Status: adopted for the Scientific Studio presentation layer

Scope: `apps/web_gui` static presentation only

Locale baseline: `ko-KR`

## 1. Responsibility and boundary

Scientific Studio is an evidence-oriented production workbench for making, reviewing, registering,
and delivering science assessment items. Its visual system must let a user understand the work before
it exposes platform terminology.

This design system changes presentation, not product truth. Application API resources, workflow
states, error codes, identifiers, permissions, persistence, and service boundaries remain canonical.
The GUI may translate those values through the versioned presentation vocabulary, group them, and
progressively disclose them. It must never reinterpret, synthesize, or mutate them.

The dominant interaction patterns are:

- follow an ordered production process;
- inspect immutable evidence and revision provenance;
- make a bounded human decision;
- recover a known resource by exact ID;
- monitor concurrent work and diagnose a failure.

The existing DOM and typed API responses remain the canonical data sources. The design layer adds no
client-side data store, external font, analytics script, framework, or network dependency.

## 2. Design stance: Scientific Workbench

The product should feel like a calm scientific instrument and a well-edited research notebook. It is
neither a marketing dashboard nor a collection of decorative cards.

The visual hierarchy follows this order:

1. the user's goal and current decision;
2. the production path and current stage;
3. evidence, validation, and provenance;
4. exact identifiers and diagnostic detail.

Process is shown before outcome. Evidence is shown next to the work it supports. Empty states explain
the next useful action. Small radii, hairline borders, restrained shadows, and compact typography keep
dense work readable without making the interface feel like a generic administration console.

## 3. Automatic surface modes

Surface mode is derived from the current route. It is not a personal theme and is not stored as user
preference.

| Mode | Views | Purpose |
| --- | --- | --- |
| 사용자 작업면 (`human`) | 새 문항 요청, 완성 문항, 승인, HWPX, 대시보드 | Goals, content, decisions, and delivery use plain Korean and calm sans-serif hierarchy. |
| 운영·근거 화면 (`engine`) | 문항 제작 진행, Codex 실행 관리, 교육 지식 맵, DB Explorer | Provenance, execution state, timings, immutable IDs, and diagnostics may use compact mono accents. |

Both modes expose the same authorized capabilities. Mode changes density and emphasis only; it never
changes requests, permissions, fields, state transitions, or error handling. The current mode is
visible in both the sidebar and top bar so a user knows which reading frame applies.

## 4. Semantic color roles

Color names describe responsibility rather than a widget:

| Token | Role |
| --- | --- |
| Ink | primary text and the deepest neutral |
| Graphite | secondary structural text |
| Mist | workbench background and quiet grouped surfaces |
| Porcelain | navigation and document-adjacent surfaces |
| Line | boundaries and table rules |
| Oxidized Teal | user action and completed production work |
| Cobalt | active process, information, and technical focus |
| Amber | review or attention required |
| Vermilion | failure, destructive consequence, or blocked state |

Color is never the only state signal. Every state includes text and, where compact display helps, a
shape or icon. Primary buttons use action teal; cobalt is reserved for information and the active
execution step. World-facing product content remains on a warm document surface.

## 5. Structural components

### Production map

The map presents the stable user-level flow:

```text
requirements -> item composition -> quality review -> human approval -> pinned revision -> HWPX
```

It is a presentation of existing workflow state, not a second state machine. JavaScript derives
`complete` and `current` only from the same workflow and step values already used by the detailed
stage rail. Unknown states remain unknown and do not infer progress.

### Evidence strip

The evidence strip answers “what was this item grounded in?” without flooding the page with IDs.
Curriculum keys and source classes may be shown directly. Evidence Bundle and Graph Snapshot revision
IDs remain available as technical hover/detail metadata while the primary label says that the source
was pinned. When no managed evidence is attached, the strip explicitly says that the structured
request and worker's general science knowledge were used.

### Technical disclosure

Exact IDs, ETags, schema versions, hashes, and raw diagnostic codes remain available, but secondary
technical material is grouped under native `details` disclosure on user-facing surfaces. Recovery
controls that require an ID, such as opening a known HWPX build, remain directly visible.

### Document surface

The completed item preview remains typographically distinct from application chrome. It represents a
publication artifact and therefore retains its serif, page-like surface. Presentation metadata must
not be mistaken for rendered item content.

### Knowledge analysis quality surface

The education knowledge view observes existing batch and range projections. It may derive page
coverage, progress estimates, structural findings, and curriculum-key-to-document-revision
relationships, but it must not present these as a published Graph Snapshot. It has no accept, retry,
cancel, or publication action. Structural warnings are separate from scientific-content review, and
the derived report is never persisted as canonical evidence.

The one-item and HWPX views use the same three-part handoff language—fixed requirements, validated
production, secure delivery—without creating another state machine. Their visual steps are derived
from the existing Item Revision, HWPX build, validation, and download-availability values.

### Advanced execution policy

Execution Preset mutation is an infrequent administrator operation, not routine production work. It
remains collapsed under `고급 실행 정책` by default. The Studio does not accept an arbitrary preset
JSON document: an administrator selects an existing active immutable V1 revision, changes only the
guided model/effort/timeout and descriptive fields, and preserves its pinned capacity, instruction,
reference, sandbox, network, and protocol pointers.
Model/effort choices are drawn only from candidates already released for the same role in another
active editable preset; a merely observed account capability is not treated as publication approval.

Creating a DRAFT and releasing that DRAFT are separate review boundaries. Each renders a summary,
requires a fresh explicit confirmation, and becomes invalid when editable input changes. Knowledge
retrieval V2 presets are deliberately excluded from this bounded editor because changing their
access-policy and Evidence Bundle contract requires the reviewed platform rollout path.

## 6. Typography, density, and motion

- Human text uses the existing local/system Korean sans stack.
- IDs, hashes, timestamps, execution annotations, and engine-mode eyebrows use the existing mono
  stack.
- Application text follows one readable scale: 14 px body, 13 px labels and messages, and 12 px
  captions. Ordinary instructions, states, field labels, and table values must not be compressed
  below the caption size merely to fit more information on screen.
- The only text below 12 px is compact machine notation such as an ordinal, truncated immutable ID,
  graph key, or document-preview metadata. It must remain secondary, recoverable at normal size in a
  detail surface, and never carry the only explanation of an action or state.
- Human-mode panels use their Korean heading as the primary label and suppress repeated decorative
  uppercase eyebrow copy. Page-level context and engine-mode evidence labels remain visible.
- Card radius remains at or below 8 px; control radius remains at or below 6 px.
- Shadows establish document elevation or overlay ownership, not decoration.
- Animation is unnecessary for status truth. Any transition must be subtle and is effectively
  disabled by `prefers-reduced-motion: reduce`.
- Dense tables stay dense. User composition fields retain comfortable input height and line spacing.

## 7. Accessibility and trust

- Keyboard focus remains visible against every surface.
- Native controls and `details` are preferred over custom interaction widgets.
- Process position uses `aria-current="step"`.
- Status regions keep their existing live-region behavior.
- No untrusted API value is inserted through `innerHTML`; dynamic labels use `textContent` and created
  DOM nodes.
- Raw backend values remain available for diagnosis, while Korean presentation labels are explicitly
  mapped by the versioned vocabulary and fail closed to an unknown-state label.
- Responsive layouts preserve task order: goal, action, content, provenance.

## 8. Extension rules

New GUI work should extend these components instead of creating a parallel visual language.

1. Assign every new view to `human` or `engine` from its dominant access pattern.
2. Reuse a semantic token; do not introduce a component-named color.
3. Show the user goal before implementation nouns.
4. Put evidence beside the claim or artifact it supports.
5. Keep exact IDs recoverable, but disclose them progressively when they are not the task.
6. Preserve backend values and compare raw protocol values for behavior.
7. Add no client persistence unless a separate design establishes ownership and invalidation.
8. Test mode mapping, safe DOM rendering, reduced motion, responsive behavior, and presentation-only
   boundaries.

## 9. Deliberate non-goals

This design phase does not add or change an API, workflow, DB schema, model provider, worker prompt,
item contract, authorization rule, HWPX contract, storage path, or runtime service. It does not add
gamification, community features, arbitrary themes, or chain-of-thought exposure. Future item library,
quality-profile, and knowledge-graph editing features require their own protocol-first designs.
