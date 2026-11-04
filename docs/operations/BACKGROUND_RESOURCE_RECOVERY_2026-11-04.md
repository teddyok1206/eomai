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

## 운영 배포 체크포인트

2026-11-04 08:58:32 UTC에 아래 호환 조합으로 배포·재개했다. 같은 Git commit으로
전체 서비스를 재설치하거나 진행 중인 네 worker를 초기화하지 않았다.

| 담당 | 실제 설치 source | 이번 변경 |
| --- | --- | --- |
| 창작 순차 등록 owner | `60e4435d80fd3b20f877f110db56efb931fb096f` | 자원 대기·같은 accepted source 재개 |
| INDEX metadata owner | `60e4435d80fd3b20f877f110db56efb931fb096f` | 자원/OS 유지보수 대기 |
| 공용 API/Catalog/runner/QUERY | `31073cb46be631066117d698d8eb9836eefe624d` | 변경·재시작 없음 |
| Web | `e22ca6e0af37d383daab24d24b3f3b796ebaedd3` | 변경·재시작 없음 |
| 격리 수치 CUDA controller | `a70cd43415598db500763ccf329cd762177cbe3c` | 모델·환경 bytes·space/profile 그대로 |

- 새 wheel의 non-editable import/RECORD/OpenAPI 검사와 설치 identity 검사를 통과했다.
  DB migration은 `20261103_0071` 그대로이며 새 migration은 없다.
- 09:04 UTC 네 슬롯(03–06)의 실제 RUNNING Job·만료 전 lease·정확한 worker unit의
  nonzero PID를 함께 확인했다. GUI의 네 슬롯과 후속 Graph/INDEX owner는 서로 다른 상태다.
- 09:02 UTC 생성된 새 CUDA encoding Job 네 건은 09:06:09 UTC 모두 SUCCEEDED가 됐다.
  09:08:49 UTC 새 CUDA 인덱스가 commit됐고, 원래 Workflow는 09:23:21 UTC COMPLETED가
  됐다. 계산 성공·인덱스 저장·Workflow 완료는 서로 다른 시점으로 확인했다.
- 11828·11829는 배포 이전 06:50/06:51 시작한 Job의 lease가 08:50/08:51 만료됐고,
  기존 Workflow가 09:02에 실패로 정리됐다. 최근 status의 source 예외는 기존 16건에
  이 두 건을 더한 18건이다. 이 사실을 새 코드의 전면 성공으로 숨기지 않으며, Job의
  잔여 RUNNING 표기와 실제 현재 유효 lease를 구분한다. 개별 원본의 재처리는 별도
  공식 복구 판정 없이 새 identity로 우회하지 않는다.

## 결정적 코드와 AI 결과 예외의 구분

정상적인 accepted report를 받은 뒤의 저장·Graph 등록·멱등 재조회·임베딩 연결 실패는
AI가 원인이라는 이유로 넘기지 않는다. 같은 입력·중단·동시 요청을 기존 담당 경계에서
재현하고 해당 책임 모듈을 수정한다. 이번 회귀는 AI 추론 없이 이 경계를 검증한다.

DB/디스크/OS 유지보수 같은 외부 자원 장애와 코드 결함도 구분한다. 자원 회복 뒤 같은
정본·accepted report로 재개하는 것은 허용하지만, 오류를 숨기거나 실패를 성공으로
바꾸는 것은 복구가 아니다. AI 결과의 부정확성/형식 문제는 기존 결과 검증의 별도 예외다.
전체 미래 오류 0을 수학적으로 보장했다고 표시하지 않는다.

## 실제 복구 검증 결과

- 새 owner에서 11826·11827·11831·11833의 Graph 등록·실제 operator 권한의 공식 풀이
  조회가 성공했다. 09:21:38 UTC VERIFIED 4건과
  `graphrev_ff62c5d5f108149afcb962b705b7a44e`를 확인했다. 11830·11832·11834·11835는
  다음 publication으로, 11836–11839는 다음 풀이 처리로 이어졌다. 번호는 비동기 완료
  순서이므로 11826–11829가 모두 성공한 것으로 해석하지 않는다.
- 실제 새 CUDA Job 4건은 모두 SUCCEEDED, 원래
  `workflow_875ccd6399f14a39aadff5e260a19a74`는 COMPLETED다. 새 인덱스는
  `embeddingindexrev_b323ab85ee45edbfc9d5f8014547f568`이며 manifest SHA는
  `sha256:34b89bb9c5fe55b4e3f1f555b01865eef3630c41e23237ca96f69b4978f02376`이다.
- Catalog의 실제 member 조회로 새 CUDA index5와 native role3/profile3 provenance,
  encoding ledger의 input hash·space·row를 대조했다. 같은 완료 Workflow/수치 Job과
  immutable manifest를 두 번 읽어 결과가 유지됨을 확인했다. 검증 자체의 모델 계산은 0회다.
  560개 binding/34개 native binding은 해당 인덱스의 분모이지 전체 1,053개 완료 수가 아니다.
- AI를 호출하지 않는 별도 경계 검증 112 PASS: Job/Workflow 전이, 임시 Artifact 저장
  전후 중단과 같은 요청 재전송, encoding 복구 identity, source 권한/실패 이력 보존,
  accepted 분석의 Graph 재사용을 확인했다. 집중 회귀 161 PASS와 합산해 고유 테스트
  총수라고 주장하지 않는다. 정상 source-count/state를 가진 typed fixture로 자원 회복
  lifecycle 37개를 다시 실행해 모두 통과했다.
- 원래 30분 creative/embedding 관측 timer와 API READY·실제 HTTPS 200은 유지된다.
  전체 1,053개 완료는 백그라운드이며, 18개 source 예외·실패 이력·구형 벡터는 보존했다.

## 감사 증거

기존 Orchestrator `ControlFileSetPublisher`로 검증 기록을 NAS에 등록하고 Catalog로
committed member를 재조회해 동일 bytes/hash를 확인했다. 새 worker schema는 만들지
않고 기존 private operations acceptance schema를 재사용했다.

- Artifact: `artifact_40fd022f0d4940a39d8e19b9cc38a0fe`
- Revision: `rev_6878de0b7a8f4bc292db2cca34eb7f15`
- Member: `report.json`
- SHA-256: `sha256:2842aef70eef5dacdb84aba200c5dee37b5a27fb5cd80e2755dab0c8687c7f48`
- 검증 항목 13개, 실제 실행·회귀·임시 DB cleanup·배포·삭제 범위 증거 파일 17개.
  보호된 env/auth 파일·사용자 비밀번호·문항 본문·worker 결과 원문은 포함하지 않았다.
