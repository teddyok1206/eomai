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

## 2026-11-05 배치 확장 전 경계 검토

다음은 저장소 수정·격리 검증 결과이며 운영 활성화 선언이 아니다. 새 dependency, DB migration,
queue/framework, worker 권한 또는 released schema/definition bytes 변경은 없다.

| 확인된 문제 | 책임 경계와 조치 |
| --- | --- |
| 단일 문항 HWPX의 중단 후 RUNNING 잔류 | Manager startup + renderer port에서 원래 Job/source/output을 확인하고 기존 receipt 연결 또는 중단 기록; 새 render 금지 |
| refresh와 자격 변경의 잠금 역전, lock 대기 중 access 철회 | Identity에서 session → token 순서를 통일하고 대기 후 token을 다시 확인 |
| 관리자 ETag의 transaction 밖 선검사 | Identity가 target row lock 안에서 CAS; API는 412로 표현만 변환 |
| 계정 변경 후 응답 저장 사이 crash window | local Operator command와 bounded idempotency receipt를 동일 transaction으로 commit |
| Web 자동 refresh와 자격 변경의 token 교체 race | 동일 session lock으로 교체까지 직렬화; 일반 조회는 병렬 유지 |
| Web readiness·실제 body 크기·무제한 replay cache | mandatory API ready/503, 실제 ASGI byte 제한, bounded LRU; optional observe와 upload 전용 한도 보존 |
| API의 실제 body 초과가 JSON 오류로 바뀜 | ASGI byte 제한의 HTTP 413과 기존 `API_BODY_TOO_LARGE` 의미를 FastAPI 예외 경계까지 유지 |
| 200개 선조회 뒤 관리자 필터 적용 | Identity SQL에서 status/active role/literal prefix를 먼저 적용한 뒤 limit |
| 문서 processing lease와 Catalog 대기창 불일치 | composition에서 connect/upload/response/continuation 예산 이상의 effective lease 사용 |
| migration과 ORM의 물리 선언 차이 | 기존 열 길이·FK RESTRICT·index 이름/식을 맞춤; DB DDL 변경 없이 compare_metadata 차이 0 |
| schema 내부 `$id` 오검출·resource mirror 검사 누락 | audit에서 독립 schema resource scope와 package resource identity를 함께 검증 |

자료 검토 이미지의 늦은 load 응답 guard는 기존 코드에 있어 재수정하지 않았다. transport의
`FAILED_FINAL`/retention은 [idempotency 문서](API_IDEMPOTENCY.md)에 현재 의미를 명시했다.
historical Workflow/Job 실패나 원본·Graph·벡터·HWPX 결과는 이 작업에서 수정하지 않는다.

검증은 source API, Web/contract/dependency, HWPX output suite와 guarded PostgreSQL의
중단·동시 claim·같은 요청 replay·stale ETag·refresh/rotation 경합·receipt 직전 fault를 포함한다.
historical admission fixture는 격리 DB에 한정되며 현재 운영 admission을 넓히지 않는다.
서로 다른 frozen standard preset을 요구하는 V1/V2 bootstrap은 별도 새 DB에서 단독 PASS했다.

대규모 Catalog intake의 backpressure, 전체 textbook 목록의 query 수와 공통 DB deadline은
이 검토에서 현재 운영 결함/부하 한계를 재현한 항목이 아니다. 다음 대형 배치의 실제 access
pattern·query plan·처리량을 확인한 뒤 다룬다. 근거 없이 새 queue, 광범위 cache 또는 전체
statement/worker timeout 변경을 추가하지 않는다. 실제 browser/Hancom/권한 실험의 opt-in
skip과 기존 기술 acceptance를 새 source의 운영 PASS로 바꿔 보고하지 않는다.

### 운영 반영 체크포인트

사용자 승인 후 `4013f66b37fd7667bab6b61e0de0a1d9f6cb8cb2`를 main에 push하고
API·Web·shared platform/runner·HWPX Manager·Catalog 설치본에 반영했다. 설치 wheel의
실제 파일을 대조했으며 새 dependency 설치나 DB migration은 하지 않았다(`20261104_0072`).
QUERY owner 코드는 `93705191`을 유지하고 typed configuration의 API provider source/wheel/
code-member hash만 새 API에 맞췄다. GPU INDEX와 수치 runtime/config는 그대로이며
동일 INDEX PID/InvocationID를 배포 전후 대조했다. 기존 Builder의 확정 출제의도 수정도 보존했다.

실제 설치 API provider의 process/config/code fence, API service mount namespace/권한
격리, HTTPS 로그인 화면·Web live/ready·미인증 session 조회의 401, dependency check와
배포 metadata 검사를 통과했다. 실제 사용자 비밀번호를 받아 새 로그인·refresh를 수행한
인증 smoke나 새 HWPX/검색 계산 acceptance로 확대 해석하지 않는다.
이후 사용자가 실제 Studio 로그인/기존 화면의 정상 동작과 합본 HWPX의 출제의도 표시를
확인했다. 이는 해당 사용자 경로의 수동 확인이며 자동 API login/refresh 검사와는 구분한다.

창작 투입기를 멈추는 단계에서 기존 publication 종료 대기가 systemd의 3분 한도를 넘어
timeout 종료한 이력은 보존했다. 운영 API 교체 전 유효 worker lease·비 INDEX command·
실행 가능한 대기 command·HWPX·채팅·query/builder unit이 모두 0임을 별도로 확인했다.
DB 상태를 보정하지 않고 같은 창작 scope/pin의 공식 service start로 원래 작업을 재개했다.
투입기의 `close()`가 publication을 기다리는 시간과 운영 stop 한도 정렬은 후속 운영 점검
항목이다. 무조건 graceful stop에 성공했다거나 모든 미래 중단이 해결됐다고 주장하지 않는다.

정확한 설치·검증·이전 wheel/config pointer와 timeout 기록은
`/var/lib/eom-system-review-release-20261105/`에 있고, API 배포 정본 기록은
`/var/lib/eom-api/deployments/4013f66b37fd7667bab6b61e0de0a1d9f6cb8cb2.json`이다.
기존 read-only observer의 배포 후 조회에서 창작 Graph 누적 806건을 확인했으며, 실행별
`verified_count` 초기화와 정본 누적 등록 수를 혼동하지 않는다. 이 수는 그 시각의 관측이다.
