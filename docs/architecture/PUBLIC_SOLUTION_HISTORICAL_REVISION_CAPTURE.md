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

기존 INDEX metadata SDK·Identity/grant successor 절차로 이 소비자만 반영한다. 물리 GPU
controller, CPU/CUDA 환경·model/recipe/space와 QUERY는 변경하지 않는다. 진행 중 작업·lease의
안전한 종료를 확인하고 완료된 encoding/저장 head와 실패 이력을 보존한 뒤 공식 service를
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
