# 공개 풀이의 고정된 과거 문항 버전 capture

2026-11-15 UTC. 실제 INDEX 실패 `EMBEDDING_REGISTRY_POINTER_INVALID`의 원인은
수치 계산이 아니라 공개 Graph 후보와 capture의 lifecycle 조건 불일치였다.

## 경계와 정본

기존 Catalog source resolver가 승인 이력의 유일한 소유자다. Graph와 accepted 분석이
고정한 Item Revision·Artifact·hash가 정본이며, mutable current revision으로 교체하지
않는다. 새 분석은 계속 APPROVED만 받는다. 이미 공개된 source는 기존 규칙대로 APPROVED,
또는 승인/교체 이력이 완전한 SUPERSEDED, 승인 이력이 있는 RETIRED를 해석한다.

`require_historically_approved_item_revision`은 기존 resolver의 이력 조건만 추출한다.
`public_solution_source_capture`는 이미 일괄 조회하고 잠근 정확한 revision에 같은 조건을
적용한다. source 관계·권한·Graph/policy·보고서·Artifact provenance와 hash 검사는 그대로다.
누락되거나 불완전한 이력은 기존 안정된 오류로 거부한다. 최신 버전으로 대체하지 않는다.

## 자료구조와 동시성

지배적 연산은 pinned revision ID의 indexed bulk lookup과 key 집합 대조다. 기존 dict와
한 번의 `FOR SHARE` 조회를 유지하며 추가 순회는 O(n), 추가 공간은 O(1)이다. 문항별
resolver 호출/N+1, 별도 cache·queue·DB schema/index·migration은 필요 없다. 같은 transaction의
잠근 row와 최종 권한/provenance fence를 사용하며 capture는 읽기 전용이다. 실패 시 새
identity나 source를 만들지 않고 기존 orchestration의 재시도/정산 경계를 사용한다.

## 대안과 운영 전환

구버전을 SQL에서 제외하면 유효한 고정 Graph와 재현 가능한 과거 검색을 깨뜨린다.
current로 대체하면 revision/hash/report identity가 달라진다. 전체 source resolver를 다시
호출하면 이미 검증한 파일·관계를 중복 조회한다. 공통 이력 조건의 재사용이 더 작고 정확하다.

첫 전환은 기존 INDEX metadata SDK·Identity/grant successor 절차로 이 소비자만 반영한다.
물리 GPU controller, CPU/CUDA 환경·model/recipe/space와 QUERY는 이 단계에서 변경하지 않는다.
진행 중 작업·lease의 안전한 종료를 확인하고 완료된 encoding/저장 head와 실패 이력을 보존한 뒤 공식 service를
재개한다. 성공한 수치 계산을 실패로 바꾸거나 기존 벡터를 재생성하지 않는다.

## 검증

source 회귀와 guarded disposable PostgreSQL에서 exact old revision·공개 보고서·pointer
보존, 불완전한 이력·hash·최종 권한 거부 및 locked bulk read를 검증한다. DB fixture의 source
admission/report IO는 명시적 synthetic port여서 실제 NAS/운영 수치 완료 증거가 아니다.
실제 재개와 새 index 저장은 운영 기록에서 별도 판정한다.

## 이미 등록한 요청 한 건의 완료 인계

실제 추가 관측에서 중단된 CUDA 요청 한 건은 encoding4개가 SUCCEEDED이고 coordinator가
ALLOCATION → INDEX_PREPARED → REGISTERED까지 진행했다. 원래 command의 lease는 만료됐고
INDEX PID는0이다. 이미 등록된 index를 다시 계산하거나 이 요청을 실패로 바꿀 필요가 없다.

전환은 기존 Identity/grant successor와
`recover_prepared_index_publication`의 root/schema-owner 유지보수를 조합한다. 종전 운영
template의 unfinished0 조건은 **정확히 고정한 이 한 건만** 제외하도록 좁혀 사용한다.
인계 직전 exact service/request/intent/registration/checkpoint·성공한4개 receipt와 잠금 만료,
물리 자식 drain을 다시 검사하며 나머지 unfinished/held command는0이어야 한다. 새 service
head는 기존 CAS로 갱신하고 current source grants는 이전 범위·모델·recipe와 동등해야 한다.
완료 vector metadata의 고정 cutoff fingerprint와 다른 서비스/config의 불변도 대조한다.

후속 복구는 기존 request·producer·Artifact·index ID와 저장된 encoding을 그대로 사용한다.
publication-only executor는 source discovery·submit·allocation·수치 실행을 제공하지 않는다.
원래 command 재claim 및 완료 영수증 저장은 기존 Runner/Orchestrator가 담당한다. 같은
recovery command의 재실행은 같은 결과를 확인하며 실패·다른 head·미완료 encoding·유효한
claim은 거부한다. 복구가 끝나기 전 새 INDEX discovery를 시작하지 않는다. 새 DB/queue/
schema나 일반 runtime 권한은 추가하지 않는다. 기존 설계·동시성/중단/재전송 검증 경계는
`../operations/RETIRED_INDEX_PUBLICATION_RECOVERY.md`를 따른다.

## 같은 capture를 쓰는 QUERY와 private Catalog 소비자

설치본 대조에서 INDEX 이외의 두 소비자도 확인했다. QUERY의 고정 SDK는 공개 기준 문항
준비와 최종 전체 population 검증을 자체 Catalog adapter에서 수행한다. private Catalog는
완료 ranking의 strict 조회에서 같은 capture를 호출한다. 이 두 설치본에 이전 APPROVED-only
조건을 남기면 fresh 조회에서 같은 historical source를 거부할 수 있다. 정상 cache hit가
일부 full capture를 생략할 수 있으므로 모든 기존 조회가 실패한다고 일반화하지 않는다.

수정 책임은 동일한 Catalog 이력 조건이며 QUERY/결과 조회에 다른 허용 규칙을 만들지 않는다.
검증한 같은 immutable SDK를 두 소비자에 반영한다. 정본 Graph/policy/문항/보고서·model/
recipe/space와 실제 사용자 권한은 그대로다. 접근은 기존 config/pointer의 exact lookup과
bounded in-flight/lease 관측이며 새 cache/DB/queue/index/메시지 계약은 필요 없다.

기존 QUERY-only release의 primary/mixed/public metadata owner source, private configuration의
참조 hash, unit의 config hash/SDK entrypoint와 Catalog의 public-config hash를 같은 명시적
file-set CAS로 전환한다. Catalog SDK source도 같은 계획에서 고정한다. source/config hash는
각각 보존하며 numerical controller와 CPU/CUDA/shared numerical env는 바꾸지 않는다.
실제 in-flight QUERY를 자연 drain하고 진행 중인 INDEX·Material·ROLE·API/Web는 유지한다.
current operator/policy의 재인가를 생략하거나 과거 FAILED 검색을 자동 재실행하지 않는다.

단순 INDEX-only 배포는 다른 활성 소비자를 남겨 불충분하다. 반대로 전체 플랫폼·수치
runtime 재설치는 이 metadata leaf 수정에 불필요하다. 부분 전환·CAS 불일치·미종료 claim이면
새 동작을 멈추고 실제 파일/서비스 상태를 확인한다. rollback은 보관한 호환 metadata
설정·SDK 선택만 복구하며 기존 요청·성공/실패 이력·벡터를 손대지 않는다.

### 과거의 quiescent QUERY와 현재 in-flight를 구분

설치 시점의 nonterminal 행 개수만0으로 요구하면 수일 전 lease가 만료되고 현재 서비스가
실행하지 않는 과거 요청도 배포를 막는다. 반대로 과거 행을 일괄 취소하거나 성공 처리해서
gate를 통과시키지 않는다. 이번 인계는 읽기 전용으로 고정한 정확한 과거 Workflow/command
집합·상태·갱신 시각·lease metadata의 fingerprint만 예외로 보존한다. 새 in-flight/유효 claim,
기록 변경, 현재 native 자식이 있으면 그대로 전환을 거부한다.

QUERY는 socket 요청을 받은 exact Workflow만 실행하며 기동 시 모든 과거 요청을 재claim하지
않음을 설치한 진입점/서버에서 확인한다. main-only SIGINT 후 실제 자식 pool drain과 정상
종료를 확인한 뒤 기존 file-set CAS로 바꾼다. 과거 예외는 runtime의 일반 retry 정책이나
영구 허용 규칙이 아니다. INDEX가 독립적으로 OS 관측 오류로 이미 종료됐다면 그 실제
baseline을 기록하며, 배포가 INDEX를 유지·중단시켰다고 바꾸어 보고하지 않는다.

후속 OS 상태 조회 timeout은 별개의 운영 실패다. 이미 저장한 encoding/index와 실제
unfinished/claim을 확인한 후 동일 source·Identity·수치 pin의 공식 INDEX service를 재개해
fresh capture한다. persistent 관측 실패를 포괄 retry하거나 timeout·권한 검증을 완화하지 않는다.
이번 실제 전환과 저장 진행은 자료 학습 운영 checkpoint의2026-11-15 기록을 따른다.
