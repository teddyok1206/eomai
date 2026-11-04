# 창작 등록·임베딩 자원 장애 복구

2026-11-04 UTC. 기존 복구 이후 새로 발생한 장애만 다룬다. 기존 네 슬롯은 유효한
RUNNING 작업을 유지하므로 중단하지 않는다. Graph·Item·풀이·벡터·실패 이력은 보존한다.

## 확인된 원인

- 06:59 창작 publication의 `OperationalError`: PostgreSQL 로그의
  `could not write/extend ... No space left on device`. 로컬 root 파일시스템은
  914GB 중 약 875GB 사용, 일반 사용자 여유 약 196MB였다. inode 고갈은 아니다.
  일시 DB 연결 장애로 추정하거나 무조건 재시작해서 해결할 문제가 아니다.
- 06:53 INDEX: 물리 GPU 계산 전 host cache mount identity 검사에서 실패했다.
  같은 시각 unattended system update가 실행됐고 host `/etc/ld.so.cache`가 교체됐다.
  보호된 CUDA snapshot의 파일 identity는 그대로다. 직접 확인된 실패는 mounted cache와
  그 snapshot의 identity 불일치다. host update의 파일 교체와 연결된 것으로 판단하며,
  실제 mount/hash 검사는 끄지 않고 새 capture를 업데이트와 겹치지 않도록 보류한다.
- 현재 GUI 4슬롯의 RUNNING과 위 두 후속 담당의 중단은 서로 다른 상태다.

## 최소 변경 설계

1. **경계:** 기존 creative application/driver와 INDEX owner·설치 환경 capture 경계만
   보강한다. 새 worker protocol·queue·RAG engine은 만들지 않는다.
2. **정본:** 기존 accepted report·Item·Graph·committed vector/index와 실패 기록이다.
   진행 cache나 systemd ACTIVE는 완료 증거가 아니다.
3. **식별/포인터:** 원래 cohort/source/revision/hash와 멱등 요청을 유지한다. 실패한
   allocation은 기존 공식 미실행 실패 증거·maintenance 경계로 종료하며 성공으로 바꾸지 않는다.
4. **해결 검사:** source/권한/hash/실제 수치 실행 여부를 원래 담당이 다시 확인한다.
   모르는 상태에서 새 identity로 중복 계산하거나 파일 검사를 끄지 않는다.
5. **접근 패턴:** 기존 원본 순회·고유 claim·Graph CAS·append-only 이력과 자원 상태 조회다.
6. **구조:** 기존 map/set/unique key/lease/index를 유지한다. 디스크 상태는 파생 관측이며
   DB에 새 queue/완료 카운터를 추가하지 않는다.
7. **규모/복잡도:** 자원 관측은 고정 경로 statfs O(1), backoff는 기존 작업 identity를
   재사용한다. 빌드 정리는 명시적으로 확인한 오래된 재생성 source 복사본에 한정한다.
8. **동시성:** 실행 중 슬롯·수치 작업은 취소하지 않는다. DB 공간 부족 시 새 write-heavy
   처리는 대기하며, 회복 후 같은 source/publication을 원래 application에서 이어간다.
9. **의존:** adapters는 공간·설치 상태를 관측하고 application이 retry/defer를 결정한다.
   CLI/systemd가 임의 DB row 수정이나 모델 재생성 규칙을 구현하지 않는다.
10. **실패/복구:** 안전한 transient/resource 오류와 계약·권한·hash 오류를 구분한다.
    전자는 제한 backoff/자원 회복 후 재개, 후자는 명시 중단한다. 모든 예외 삼키기나
    무조건 자동 재시작은 하지 않는다.
11. **단순 대안:** 재시작만 하거나 용량을 소량만 비우면 재발한다. 충분한 여유 확보,
    실제 원인 수정과 자원 대기·멱등 재개를 기존 두 경계에 결합한다.

## 공간 확보 범위

우선 `/home/eom/.cache/pip`의 재설치 가능한 다운로드 캐시 5,037.5MB를 공식 pip cache
purge로 정리했다. 설치된 패키지·모델·정본·NAS에는 영향 없다. 이 캐시는 다시 다운로드해
생성할 수 있으며 별도 복구 백업은 만들지 않았다.

추가 정리는 `/tmp/eom-api-build/<commit>.<suffix>/source` 중 오래되고 완료된 빌드의
재생성 가능한 Git source 복사본만 대상으로 계획 목록을 먼저 고정한다. 배포 wheel의
source commit과 디렉터리 이름을 대조한다. `dist` wheel·`source.tar`·배포/rollback 기록·
환경 파일·현재/최근 실행 환경은 그대로 둔다. 삭제한 source 복사본은 남겨둔 같은
source.tar에서 복원할 수 있다. 모델/문항/DB/실패 증거를 공간 확보 대상으로 삼지 않는다.

## 검증과 종료

디스크 부족·회복, DB rollback/불확실 commit 후 동일 요청 replay, 안전하지 않은 오류
거부, 실제 격리 환경의 mount/설치 검사, 원래 대상의 Graph 등록·공식 읽기와 실제 CUDA
저장 및 이후 다음 작업까지 확인한다. mutating DB 검사는 disposable DB에서 수행한다.
서비스 재시작이나 첫 한 건 성공만으로 장기 무오류를 주장하지 않는다.

## 구현·검증 체크포인트

- 로컬 쓰기 여유 10GiB를 확보하지 못하면 기존 creative/INDEX 담당은 새 처리를 대기한다.
  디스크 경로 자체가 없거나 읽을 수 없는 설정 오류는 여유 공간 정상으로 위장하지 않는다.
- SQLSTATE 53100과 명시적인 연결·deadlock·serialization·자원 오류만 60초 간격으로
  재개한다. 권한·인증·무결성·schema 오류와 이유 불명인 SQL 취소는 재시도하지 않는다.
  재개 시 기존 service/runtime, accepted tuple, 멱등 요청을 그대로 사용한다.
- background Graph future의 복구 가능 DB 실패는 같은 accepted source들을 다시
  READY_TO_PUBLISH로 유지한다. commit 후 연결이 끊겼어도 다음 membership/권한/포인터
  검사에서 이미 반영된 분석을 재사용한다. 부분 결과를 전체 VERIFIED로 세지 않는다.
- resource wait는 `WAITING_FOR_RESOURCES`/`RESOURCE_WAIT`로 표시한다. 죽은 owner를
  정상으로 표시하거나 모델 작업을 다시 시작하지 않는다.
- INDEX는 OS apt 유지보수 상태를 loop 시작과 시간이 오래 걸린 source preparation 뒤,
  실제 allocation claim/physical IPC 전 두 번 확인한다. active/activating/알 수 없는
  상태면 보류한다. 시스템 업데이트를 끄거나 기존 kernel mount/hash 검사를 완화하지 않는다.
- 기존 실패 GPU parent `job_09a8c9dc18c24d4990f8e5f1c6816119`는 실제 root 종료·빈 input·
  grant 없음·수치 실행 없음 증거를 기존 unbound-failure application으로 등록했다.
  같은 기록 재전송 결과도 일치했다. 실패를 성공으로 바꾸거나 임의 SQL로 row를 고치지 않았다.
  증거는 `artifact_4c278fb2c95b4ec58a4703e8945fa3aa` /
  `rev_4be31458dbe24c998b1d00e0b87a7c23` / `controller-failure.json`이다.
- 747개의 오래된 빌드 source 복사본 약 48.4GiB와 pip cache 약 4.7GiB를 정리해
  로컬 여유가 약 53GiB로 늘었다. source.tar·wheel·환경 파일·현재 runtime은 보존했다.
- 공간 회복 후 같은 cohort를 08:29 UTC 재개해 11822–11825의 Graph 등록·공식 풀이
  조회를 확인했다. Graph는 `graphrev_a7acdf14a53a800ed72c7f4e471ffbd9`다.
- 집중 회귀 161 PASS, 변경 production 8개 파일 mypy PASS, ruff/format PASS.
  disposable PostgreSQL의 기존 Graph CAS/재전송과 실제 SQLSTATE 53100/40P01/42501
  rollback·동일 key 재사용 검증을 합쳐 9 PASS. 해당 DB는 공식 cleanup으로 제거했다.
  앞선 테스트 invocation의 marker env 누락과 임시 table fixture 충돌은 보존하고 수정했다.
  운영 DB에서 pytest나 디스크 채우기 fault injection을 실행하지 않았다.

모든 미래 오류가 사라진다는 보장이 아니다. 알려진 자원 장애에 작업 전체가 바로 종료되지
않고, 안전성이 확인되지 않는 오류는 계속 정직하게 중단·보고하는 방향이다. 새 protocol,
DB migration, queue, 모델·수치 계약 변경 없이 기존 두 owner에 반영한다.
