# EOM Integrated Science Editorial Outline V1

Status: user-confirmed editorial hierarchy; source-controlled design authority, not yet a published
Curriculum Framework Revision or Knowledge Graph Snapshot.

Confirmed: 2026-08-24 UTC

Related documents:

- [EOMIS Legacy Curriculum Semantic Pilot Review](EOMIS_LEGACY_CURRICULUM_SEMANTIC_PILOT.md)
- [EOMIS Legacy Knowledge Integration Plan](EOMIS_LEGACY_KNOWLEDGE_INTEGRATION_PLAN.md)

## 1. Boundary and authority

This document fixes the EOM company editorial outline used to organize Integrated Science content.
It is a controlled company classification, distinct from the official curriculum source document.
It does not itself grant source rights, replace achievement-standard text, or publish graph data.

The fixed hierarchy is:

```text
VOLUME       I권 or II권
  MAJOR      대단원 1 through 6
    MIDDLE   reviewed code such as 1-(1), with its exact label
```

When projected through the current four-level curriculum graph contract, use:

```text
MAJOR                  EOM volume (I권, II권)
  MIDDLE               EOM large unit (대단원)
    MINOR              EOM middle unit (중단원)
      ACHIEVEMENT_STANDARD
```

The graph level names are implementation terms; the Korean editorial terms above are the product
semantics. `I권` aligns with the source course `통합과학1`, and `II권` aligns with `통합과학2`, but
that alignment must be stored as a reviewed mapping between two identities rather than treated as
identity-by-label.

## 2. Fixed ordered outline

Sibling order and codes are part of the reviewed outline. Labels may be corrected only by creating
a successor revision; they must not be normalized silently.

| 권 | 대단원 코드 | 대단원 | 중단원 코드 | 중단원 |
| --- | ---: | --- | --- | --- |
| I권 | 1 | 과학의 기초 | 1-(1) | 시간과 공간 |
| I권 | 1 | 과학의 기초 | 1-(2) | 기본량과 단위 |
| I권 | 1 | 과학의 기초 | 1-(3) | 측정과 어림 |
| I권 | 1 | 과학의 기초 | 1-(4) | 정보와 신호 |
| I권 | 2 | 물질과 규칙성 | 2-(1) | 원소 형성 |
| I권 | 2 | 물질과 규칙성 | 2-(2) | 별의 진화 |
| I권 | 2 | 물질과 규칙성 | 2-(3) | 원소의 주기성 |
| I권 | 2 | 물질과 규칙성 | 2-(4) | 이온 결합과 공유 결합 |
| I권 | 2 | 물질과 규칙성 | 2-(5) | 지각과 생명체 구성 물질의 규칙성 |
| I권 | 2 | 물질과 규칙성 | 2-(6) | 물질의 전기적 성질 |
| I권 | 3 | 시스템과 상호작용 | 3-(1) | 지구시스템의 구성과 상호작용 |
| I권 | 3 | 시스템과 상호작용 | 3-(2) | 판구조론과 지각 변동 |
| I권 | 3 | 시스템과 상호작용 | 3-(3) | 중력장 내의 운동 |
| I권 | 3 | 시스템과 상호작용 | 3-(4) | 충격량과 운동량 |
| I권 | 3 | 시스템과 상호작용 | 3-(5) | 생명 시스템의 기본 단위 |
| I권 | 3 | 시스템과 상호작용 | 3-(6) | 물질대사 |
| I권 | 3 | 시스템과 상호작용 | 3-(7) | 유전자와 단백질 |
| II권 | 4 | 변화와 다양성 | 4-(1) | 지질 시대의 환경과 생물 |
| II권 | 4 | 변화와 다양성 | 4-(2) | 자연선택 |
| II권 | 4 | 변화와 다양성 | 4-(3) | 생물다양성 |
| II권 | 4 | 변화와 다양성 | 4-(4) | 산화와 환원 |
| II권 | 4 | 변화와 다양성 | 4-(5) | 산성과 염기성 |
| II권 | 4 | 변화와 다양성 | 4-(6) | 중화 반응 |
| II권 | 4 | 변화와 다양성 | 4-(7) | 물질 변화에서의 에너지 출입 |
| II권 | 5 | 환경과 에너지 | 5-(1) | 생태계 구성 요소 |
| II권 | 5 | 환경과 에너지 | 5-(2) | 생태계 평형 |
| II권 | 5 | 환경과 에너지 | 5-(3) | 대기와 해양의 상호작용 |
| II권 | 5 | 환경과 에너지 | 5-(4) | 온실 기체와 지구 온난화 |
| II권 | 5 | 환경과 에너지 | 5-(5) | 핵융합 |
| II권 | 5 | 환경과 에너지 | 5-(6) | 발전 |
| II권 | 5 | 환경과 에너지 | 5-(7) | 에너지 전환과 효율 |
| II권 | 6 | 과학과 미래 사회 | 6-(1) | 감염병과 병원체 |
| II권 | 6 | 과학과 미래 사회 | 6-(2) | 인공지능과 과학 탐구 |
| II권 | 6 | 과학과 미래 사회 | 6-(3) | 로봇 |
| II권 | 6 | 과학과 미래 사회 | 6-(4) | 과학기술과 윤리 |

Cardinality invariants:

- two volumes;
- six large units;
- 35 middle units;
- I권 contains large units 1–3 and 17 middle units;
- II권 contains large units 4–6 and 18 middle units;
- every middle-unit code is unique and its numeric prefix equals its parent large-unit code.

## 3. Identity and mapping rules

Labels and codes are values, not database identities. The eventual published graph must allocate
stable logical unit IDs under one immutable Framework Revision and retain the fixed code as a
reviewed alias. It must not derive an ID by hashing only the Korean label.

The authoritative relationships are sparse adjacency edges and an immutable sibling ordinal. The
published closure projection is derived and rebuildable. Expected access patterns are:

- exact code lookup through `(framework_revision_id, unit_code)` with a unique B-tree index;
- volume or large-unit subtree traversal through adjacency and materialized closure;
- item/source lookup through graph edges to pinned Item Revision or Artifact Revision pointers;
- deterministic display through parent plus immutable ordinal;
- alias lookup through a normalized alias index without merging distinct units automatically.

At the current scale, all operations are small, but lookup must remain indexed rather than scanning
all 35 units for each item or source relationship.

## 4. Official-source linkage

The original 32-page curriculum PDF remains one canonical source Artifact. Integrated Science page
scope is an analysis locator, not a replacement PDF identity. The future mapping review must connect
each EOM middle unit to one or more official curriculum domains/achievement standards using:

- pinned source Artifact and Artifact Revision;
- physical page or closed page range;
- excerpt hash and extraction implementation/options hash;
- official standard code and definition/reference role;
- reviewed mapping state, reviewer, UTC time, and immutable revision.

Science Inquiry Experiment is outside this outline and outside the current pilot analysis scope.

## 5. Change and publication policy

This Markdown record is the reviewed human input for the next protocol artifact; it is not itself a
runtime seed. Before graph publication, encode the hierarchy in the existing versioned Knowledge
Graph structure contract or an additive reviewed framework contract, validate all cardinalities and
source mappings, and commit it as an immutable Artifact Revision. No production DB/NAS data is
created from this document without the remaining rights and Framework authority gates.
