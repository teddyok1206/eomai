# 기존 기능 안정화·단순화 작업

기준: `13f95be8`, 2026-11-12 UTC. 신규 제품 기능·프레임워크·모델 실행은 범위 밖이다.
현재 구현과 실패 증거를 대조하며, 11월 8일 R01–R05 등 이미 완료한 정비는 반복하지 않는다.

## 순서와 완료 기준

| 단계 | 작업 | 완료 증거 |
| --- | --- | --- |
| S1 | 출제/유사도 Pack 호환 규칙의 중복 제거 | 기존 허용/거부 집합 동일, 실제 Pack→Catalog binding→Runner 검사 회귀 |
| S2 | 프리셋 퇴역과 기존 cohort 재시작 경계 | 실제 pin 오류 원인 분류, 역사 조회/재개와 신규 admission 구분, 중단·동시성·replay 검사 |
| S3 | 실제 연결·설치 검사 보강 | business guard를 mock하지 않는 경계 검사, fresh-process 초기화, 늦은 startup 실패 검출 |
| S4 | 확인된 요청 타입 오류와 책임 정리 | 두 Catalog reader의 요청 종류 검증, 잘못된 종류에 안정된 오류, 관련 mypy 통과 |
| S5 | 기존 배포·복구 절차의 반복 정리 | 기존 owner 안에서 작은 공통 절차 재사용, 실패/timeout/복구 순서 검사, 운영 적용 여부 별도 기록 |

전부 통과한 테스트 수가 아니라 같은 입력의 결과·순서·권한·핀·멱등성이 유지되는지를 본다.
새 증거가 없으면 가설적인 구조 개편은 하지 않는다. 운영 파일·정본·실패 이력은 직접 보정하지
않으며, 실제 배포/활성화·모델 실행 여부를 소스 검증과 구분한다.

## 작은 설계 노트

1. **소유 경계:** Pack family는 기존 `eom_workflow` 계약 계층, binding은 Catalog,
   실행 준비는 Runner가 소유한다. cohort restart는 Catalog와 기존 Orchestrator preset owner,
   배포는 기존 scripts/release owner에 둔다.
2. **정본:** released Pack/definition/control bytes 및 DB의 고정 revision. 중복 Python 상수를
   정리하는 것으로 released bytes나 활성 상태를 바꾸지 않는다.
3. **identity:** logical preset·released revision·cohort/plan·Artifact revision·hash를 분리한다.
   퇴역된 logical preset에 연결된 과거 revision을 최신 설정으로 치환하지 않는다.
4. **검증:** 기존 schema/media/hash/lifecycle/permission 검사를 유지한다. history 읽기가
   허용된다는 이유만으로 퇴역 설정에 신규 실행 authority를 주지 않는다.
5. **접근 패턴:** 유한 버전 집합 membership, exact revision PK 조회, cohort의 작은 pin 집합
   순회, append-only 실행/event 조회. 새 검색·queue·cache가 필요 없다.
6. **자료구조:** immutable frozenset과 기존 PK/FK·unique/lease 사용. 새 DB/index 없음.
7. **복잡도:** family membership 평균 O(1), pin 검사 O(H), H는 고정 history scope 수.
   전체 실행/Artifact를 스캔하거나 반복 파싱하지 않는다.
8. **트랜잭션:** 기존 admission/claim/등록 트랜잭션 및 lock 순서 유지. DB mutation 검증은
   guarded disposable PostgreSQL에서만 한다.
9. **의존 방향:** Catalog와 Runner가 하위 workflow 규칙을 가져온다. 서로의 private 상수를
   import하거나 domain에서 SQL/systemd를 호출하지 않는다.
10. **실패/재개:** stale/hash/권한 거부는 유지하며 기존 작업 identity로 replay한다.
    완료 기록의 재조회는 새 모델 실행을 유발하지 않는다. startup active와 readiness를 구분한다.
11. **단순한 대안:** 빠진 버전을 각 파일에 추가하면 동일 누락이 반복된다. 기존 하위 모듈의
    작은 집합을 재사용하는 것으로 충분하며 범용 호환성 registry는 만들지 않는다.

## 확인된 출발점

- Pack 1.20.19가 Catalog 복제 목록에서 빠진 오류는 `05ddda5b`에서 수정됐다. 이번에는
  Runner에 남은 같은 family 구성과 검사 범위를 정리한다. 이미 수정한 오류를 재발로 보고하지 않는다.
- 최근 creative 재시작의 `CREATIVE_COHORT_PRESET_PIN_MISMATCH`는 실제 실패 기록이다.
  preset lifecycle/capacity/hash 중 무엇인지 먼저 분류한다. ACTIVE 검사 삭제로 우회하지 않는다.
- 이전 mypy traversal에서 `creative_learning_proposal` 및 `registered_review_embedding_capture`
  2개 파일의 요청 union 처리 오류 5개가 기록됐다. 실제 source에서 재현 후 보완한다.
- 배포 wrapper의 날짜별 source 문자열 치환과 즉시 active 검사에는 유지보수 위험이 있다.
  현재 공식 절차·호출자를 확인한 뒤 실제 재사용 가능한 최소 부분만 정리한다.

## 보존 사항

팀장 프롬프트, released schema/Pack, 기존 문항·Graph·풀이보고서·임베딩,
진행 중 작업과 설치 pin, historical FAILED, 사용자 모델 선택을 보존한다.
검증 때문에 새 출제·GPU 계산이나 자동 재시도를 실행하지 않는다.

## 구현 중 확인과 좁힌 범위

- S2 운영 read-only 대조: 현재 office-four의 두 preset은 ACTIVE이며 이전 세 scope의
  preset 여섯 참조만 RETIRED였다. 전부 RELEASED revision·identity/hash/capacity/key는
  맞았다. 이 lifecycle 조건의 차이만 source에 수정했다. 역사적 scope 읽기를 허용해도
  새 analysis/extraction 제출은 기존 application admission을 거친다.
- S3 startup은 systemd의 기존 notify 프로토콜을 사용한다. 별도 polling framework 없이
  현재 fence와 scope 초기화가 끝난 뒤 `READY=1`만 보낸다. 고정 메시지에는 문항·권한·
  prompt가 없다. 직접 CLI 실행은 socket 없이 가능하다. 300초 startup budget은 유한
  대기 상한이며 사업 기능 전체의 완료/준비 보장이 아니다. unit과 compatible wheel은 한 묶음이다.
- S4 기존 두 Catalog 파일의 오류 5개와 이번 변경 대상 Runner의 같은 union 처리 오류
  4개를 발견했다. 실제 request 종류를 확인해 기존 안정된 오류로 거부하며 type-ignore나
  강제 cast로 감추지 않는다.
- S5 범위는 기존 release operator의 네 중복 판정 목록(context schema 선택·context 허용·
  migration 대응·receipt 생성)을 한 immutable 표로 정리하는 것이다. 과거 날짜별 배포
  스크립트를 이번 작업에서 재실행하거나 일괄 삭제하지 않는다. 재사용 가능한 현재 owner만
  개선하며 새 배포 framework는 만들지 않는다. 기존 25개 schema와 모든 잘못된 head 조합을 검증한다.

## 완료 범위

S1–S5 소스 구현과 연결·disposable DB·설치 검증을 완료했다. 운영 서비스는 변경하지 않았다.
실행 시간, 검증 결과, 실패 후 재검증 및 후속 배포 경계는
[검증 기록](../operations/MAINTENANCE_CONSOLIDATION_VERIFICATION_2026-11-12.md)에 정리했다.
