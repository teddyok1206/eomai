# EOM module boundaries

이 문서는 EOM의 모듈화를 파일 개수나 줄 수가 아니라 책임, 의존 방향, transaction ownership과
hot-path 비용으로 판단하는 기준이다. 2026-10-01 UTC의 저장소 전체 Python import graph를 AST로
감사한 결과를 반영한다.

## 의존 방향

```text
interfaces / CLI / Application API / Scientific Studio
    -> application services / use cases
    -> domain models and state machines
    -> contracts / identifiers / immutable value objects

infrastructure adapters
    -> application/domain이 소유한 interface를 구현
```

`packages/*`는 contract와 domain value를 소유한다. 이 층은 `apps/*`, `services/*`, SQLAlchemy,
HTTP client, subprocess 또는 PostgreSQL driver를 import하지 않는다. `services/*`는 application
entrypoint를 import하지 않는다. 이 규칙은 `tests/unit/test_dependency_boundaries.py`가 새 package를
포함해 자동 검사한다.

Worker는 orchestration, DB 또는 NAS commit을 소유하지 않는다. CLI와 HTTP route는 presentation
입력을 typed command/query로 바꾸고 use case를 호출하며, business invariant를 별도로 복제하지
않는다. 큰 binary와 complete Item은 pointer/manifest 해석 경계에서만 materialize한다.

## 현재 감사 결과

| 경계 | 판정 | 설명 |
| --- | --- | --- |
| Contract/domain packages | PASS | runtime service/app 및 infrastructure import 0 |
| Service -> app 역방향 | PASS | service가 Application API/Web/CLI entrypoint를 import하지 않음 |
| Package/app cycle | PASS | lower layer나 entrypoint가 포함된 first-party cycle 없음 |
| Pagination responsibility | IMPROVED | HMAC cursor와 page value를 `services/pagination.py`로 분리 |
| Workflow schema hot path | IMPROVED | exact `(role, protocol)`/`schema_id`로 validated schema를 cache하고 caller에는 독립 copy 제공 |
| Runtime composition services | KNOWN DEBT | 아래 네 package가 공유 ORM/transaction composition으로 하나의 SCC를 이룸 |

현재 순환 composition cluster는 다음으로 제한된다.

```text
eom_catalog_service
eom_identity_service
eom_orchestrator
eom_workflow_runner
```

이는 네 개의 독립 microservice가 HTTP로 서로 호출하는 구조가 아니라, 하나의 PostgreSQL
transaction과 ORM metadata를 공유하는 modular monolith의 runtime composition 영역이다. 새 기능이
이 cycle에 들어오는 것은 허용하지 않는다. 기존 cluster를 한 번에 분리하면 Artifact commit,
Workflow claim, operator authorization의 atomicity를 깨거나 추가 network round trip을 만들 위험이
있으므로 이번 감사에서는 이동하지 않았다. 향후 분리는 먼저 shared persistence composition root와
application port를 명시하고, transaction/recovery benchmark가 기존과 같거나 나음을 증명한 작은
successor change로 수행한다.

## 큰 모듈을 판단하는 방법

줄 수만으로 module을 분리하지 않는다. 예를 들어 Catalog/Workflow contract의 큰 파일은 released
version family와 schema identity를 한곳에서 대조하는 역할도 한다. 반면 변경 이유가 다른 코드는
크기가 작아도 분리한다. 이번에 pagination codec을 Query projection에서 분리한 이유는 cursor
authentication과 SQL projection이 서로 다른 변경 이유를 가지며, codec에는 DB dependency가 전혀
필요하지 않기 때문이다.

다음 모듈은 후속 변경 시 우선적으로 seam을 확인한다.

- `eom_api.services.query_adapter`: assessment learning, document review, Item Registry projection을
  한 class가 제공한다. 새 query family를 추가할 때 독립 read service로 분리하되 기존 indexed query를
  중복 실행하지 않는다.
- `eom_catalog_service.workflow_catalog`: worker prompt staging, image handoff, registration adapter가
  모여 있다. 새 역할을 추가할 때 role별 port를 만들 수 있는지 먼저 확인한다.
- `eom_workflow.schemas`: schema inventory, canonical validation, Codex projection이 공존한다. released
  mapping의 정본은 유지하되 새 projection family는 별도 책임 module을 우선한다.

## 성능 기준

모듈화가 request hot path에 network hop, repeated parse/hash 또는 N+1 query를 추가해서는 안 된다.
이번 변경 전후 동일 source/environment에서 role schema materialization을 20회 측정했다.

| schema | 변경 전 1회 | 변경 후 1회 |
| --- | ---: | ---: |
| authoring input 1.24 | 7.629 ms | 0.051 ms |
| authoring result 12 | 35.642 ms | 0.284 ms |
| knowledge proposal result 10 | 63.863 ms | 0.837 ms |

cache key 공간은 checked-in finite protocol/result identity 집합으로 제한된다. 첫 materialization은
wheel resource hash/schema/reference 검증을 그대로 수행한다. cached canonical dict는 private이며
validation에서 read-only로만 사용한다. public loader는 deep copy를 반환하므로 caller mutation이
다음 validation을 오염시키지 않는다. DB schema, wire schema, Artifact identity와 runtime output은
바뀌지 않는다.

## 변경 전 체크리스트

1. 이 코드는 어느 layer가 소유하며 변경 이유가 하나인가?
2. cross-component 값은 기존 typed contract/pointer로 충분한가?
3. 새 import가 lower layer에서 app/service로 향하거나 reviewed runtime cluster를 넓히는가?
4. key lookup, membership, graph traversal, queue 또는 revision access에 맞는 자료구조인가?
5. 기존 indexed query, parse, hash 또는 materialization을 중복하는가?
6. transaction, idempotency, retry와 immutable history owner가 하나로 명확한가?
7. 분리로 추가되는 adapter가 실제 두 use case 또는 교체 가능한 boundary를 갖는가?
8. source test뿐 아니라 import boundary와 영향받는 runtime benchmark가 통과했는가?

큰 분리는 별도 ADR에서 canonical source, pointer, access pattern, index, complexity, transaction과
rollback을 먼저 정의한다. 단순히 파일을 작게 만들기 위한 wrapper/mixin/새 framework는 만들지
않는다.
