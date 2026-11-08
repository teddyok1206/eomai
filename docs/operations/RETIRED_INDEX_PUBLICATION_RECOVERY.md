# 계산 완료 후 릴리스가 교체된 INDEX 저장 복구

## 범위와 설계

2026-11-08 확인: 과거 CPU workflow 한 건은 4개 encoding의 검증·Artifact commit까지
성공했으나 INDEX_PREPARED 이후 중단됐다. 이전 서비스 revision에 고정된 요청이므로
새 INDEX 서비스에 그대로 claim시키거나 성공 상태만 기록해서는 안 된다.

복구는 **root + 실제 PostgreSQL schema owner의 명시적 유지보수 작업**이다. 일반
service IAM이나 사용자 권한을 넓히지 않는다. 현행 서비스와 현재 RELEASED CPU
source policy가 이전 요청과 같은 자료 범위·모델·recipe·resource를 여전히 허용하는지
확인하고, 정확히 지정된 과거 요청의 이미 준비된 publication만 이어간다.
이 유지보수 권한을 새 source discovery, submit, allocation, model execution에 쓸 수
없어야 한다. 기존 source/registry 검증 및 Orchestrator Artifact publisher를 재사용한다.

- 정본: 기존 Workflow request/Graph/plan/policy, 성공한 encoding receipts와 Artifact.
- identity: 기존 Workflow/step/native launch/index producer/receipt producer는 유지한다.
  실행한 유지보수 코드와 현재 허용한 서비스 revision은 별도 audit로 남긴다.
- pointers: 원래 request hash, native intent hash, INDEX_PREPARED registration command,
  current service reference와 current CPU policy hash를 고정한다. latest 치환은 없다.
- 접근: 정확한 ID 조회와 최대 4개 encoding membership; 기존 PK/index와 작은 tuple/set.
  전체 자료 검증은 기존 Catalog resolver 책임이며 새 scan/index/cache를 만들지 않는다.
- 동시성: 원래 Workflow/command lease 및 shared service-head lock을 유지한다.
  동일 요청 replay는 기존 prepared/registered/completed checkpoint를 이어간다.
  GPU namespace·현재 GPU 요청·QUERY·service PID는 변경하지 않는다.
- 실패: 다른 source/identity, 미완료 encoding, failed history, stale registration head,
  hash 오류, 유효한 다른 command claim이면 명시적으로 중단한다. 계산 재실행은 없다.
- 단순 대안: 구 서비스를 재활성화하면 현 GPU를 방해하고 알려진 timeout을 다시
  실행한다. DB 상태만 바꾸면 실제 index/receipt가 없으므로 채택하지 않는다.

## 검증과 운영 판정

구현은 기존 source gate의 명시적 유지보수 분기와 publication-only executor다.
일반 INDEX/QUERY API에는 이 권한을 노출하지 않는다. 151개 focused unit 및 실제
disposable PostgreSQL의 중단 후 publication·원래 command 재claim·terminal replay·
동시 접근 거부·실패 이력 거부 검사 4개가 통과했다. Ruff/mypy도 통과했다.
검사 중 fixture의 terminal replay 호출과 late command fence를 보정했으며, 이때의
실패는 운영 실행이 아니다. 운영 DB에서 pytest를 실행하지 않았다.

별도 immutable installed wheel에서 실행한다. 운영 성공은 실제 원래 index 등록,
Workflow COMPLETED, 같은 요청 replay, 숫자 worker 시작 횟수 증가 0 및 GPU 계속
진행을 확인한 뒤에만 기록한다.

운영 첫 publication 시도에서 기존 fixed-owner workspace가 root 유지보수를 거부했다.
수치 실행이나 index 등록 전에 중단됐으며 원래 command의 lease 만료 뒤 같은 요청만
이어간다. 일반 owner UID 검사를 완화하지 않는다. 별도 root-only materialization이
원래 owner의 staged index.json을 retained FD·소유자·mode·고정 hash로 검증하고,
publication 동안만 root 소유 임시 workspace에 전달한다. 원래 폴더의 소유자나 파일은
바꾸지 않고 vector bytes도 복사하지 않는다. 임시 DB 검사는 이 실제 경계도 통과한다.

### 이미 다른 INDEX가 앞서 등록된 경우

운영 재조회에서 CPU head가 159→183으로 전진했고, 남은 4개 encoding은 현재 832개
binding에 포함되지 않았음이 확인됐다. 원래 prepared revision을 head로 덮어쓰거나
동일 revision의 bytes를 바꾸지 않는다. 명시적으로 고정한 현재 index revision/hash와
원래 복구 command를 입력으로 기존 Catalog assembler/registry를 통해 successor를 만든다.
현재 reusable rows와 원래 SUCCEEDED receipts의 rows만 합치며 새로운 수치 실행은 없다.
원래 Graph·namespace·source grant를 유지하고 현행 전체 source 검증과 head CAS를 적용한다.
successor index/Artifact/producer identity는 새로 생성하고 원래 prepared checkpoint는 남긴다.
동일 계획의 identity/time은 고정한다. 등록과 원래 실행 종료는 한 SQL transaction이며,
Artifact commit 후 SQL 실패 시 같은 계획으로 replay한다. 다른 head면 자동 latest 재시도하지 않는다.
성공 후 원래 실행은 `EMBEDDING_INDEX_PUBLICATION_REPLACED`로 FAILED 종료한다. 이는
수치 계산 실패가 아니라 원래 index publication이 대체됐다는 이력이다. SUCCEEDED encoding
4개는 변경하지 않으며 새 registry receipt와 대체 사유를 함께 기록한다. 기존 성공/실패 이력과
동시 GPU/QUERY 실행은 보존한다. 새 queue/DB/migration/API는 없다.

### Registry 저장점과 유지보수 권한

첫 successor 시도는 Artifact commit 뒤 Registry의 중복 방지 savepoint에서 유지보수
fence가 재호출되어 거부됐다. DB 등록/종료는 함께 rollback됐고 Artifact는 동일 계획의
재사용 대상으로 남았다. 임시 PostgreSQL에서 같은 오류를 재현했다. 최초 권한 확인과
잠금은 반드시 outer transaction에서 하며, 동일 root/session/thread로 이미 확인된 경우에만
savepoint 안의 재검사를 허용한다. 최초 savepoint admission, 다른 root/session/thread는
허용하지 않는다. 운영 서비스 권한·검증 조건을 완화하지 않는다.

추가 검증: focused unit와 disposable PostgreSQL 188 PASS, Ruff format/check 및
focused mypy PASS. 실제 Registry savepoint에서 권한을 다시 확인하도록 fixture를 보강했고,
savepoint rollback/새 root 거부와 Artifact commit 뒤 SQL rollback 후 같은 계획 재실행을 확인했다.

운영 재시도 중 별도 INDEX owner가 2026-11-08 15:46:49 UTC에 자체 종료한 사실을 확인했다.
직전 CUDA Workflow는 COMPLETED였으며, 다음 CPU command readiness의
`WorkflowRuntimeNotReady`가 원인으로 기록됐다. 복구 helper가 서비스 상태 차이를 탐지해
자동 진행을 거부했다. 기존 baseline을 덮지 않고, 같은 invocation의 failed/PID 0과
QUERY·원래 CPU unit 불변을 확인한 별도 `successor-runtime-before.json`을 기록했다.
publication 복구는 이 중단된 상태를 그대로 보존한다. 서비스 재개는 별도 사전 점검 후 수행한다.

## 실제 publication 복구 완료

2026-11-08 16:05:41 UTC, installed recovery source
`538678a18a6e530173add50f93005a308ddebfc0`에서 등록과 원래 실행 종료가 함께 commit됐다.
원래 publication plan의 source `933c2bca89793836f5c11ecad48dd225443cac56`, 시각,
Artifact identity는 첫 시도 그대로 재사용했다. 새 수치 실행은 0회다.

- CPU index binding: 832 → 836, 기존 832개 보존 + 누락 encoding 4개 반영.
- 새 index revision: `embeddingindexrev_7a5fa5757f5cd0b02be742fe0a43e129`, lock 184.
- index hash: `sha256:973dae169a4fa5d8152b2f4a26aef714ffdbd97e1959e57dce67ce84d57a279b`.
- Artifact: `artifact_7a5fa5757f5cd0b02be742fe0a43e129`,
  revision `rev_7a5fa5757f5cd0b02be742fe0a43e129`, member `index.json`.
- 원래 Workflow/command/step/native coordinator는 publication 대체 사유로 종료했다.
  원래 encoding 4개는 SUCCEEDED 상태를 보존한다.
- 16:06:32 UTC 동일 계획 replay는 같은 registration을 반환했다. 재계산·새 등록 없이
  기존 종료/encoding 상태를 확인했다. QUERY PID/invocation은 변하지 않았다.

이 836개는 CPU namespace의 전체 binding 수이며 기출 GPU 395/520과 다른 분모다.
GPU 관리 서비스 재개/다음 묶음 성공은 이 publication 완료와 구분한다.

## 백그라운드 INDEX 재개

현재 설치본의 CPU verifier를 같은 서비스 사용자와 read-only loader-cache bind 안에서
실행해 PASS를 확인했다(모델 forward 없음). 일반 shell의 mount 없는 실행은 의도대로
`HOST_CONFIGURATION_MOUNT_INVALID`로 거부되므로 운영 실패 재현으로 해석하지 않는다.
이후 현행 service revision에 속한 대기 요청 1건의 space/runtime/resource/native policy가
실제 설정과 일치함을 확인했다. 예전 service revision의 대기 기록은 대상에서 제외해 보존했다.

16:08:35 UTC 원래 installed source `1083b89f`의 INDEX owner를 재개했다.
PID `774682`, invocation `bae83e900f544d4e99976b8a54f7cc41`.
동시 실행 중인 native unit이 없음을 확인했고, API/Web/QUERY/creative/material 서비스와
설정·수치 runtime hash는 그대로다. DB/Artifact/실패 기록을 고치거나 새 요청으로 우회하지 않았다.

15:46의 readiness 실패는 새 설치환경 검사에서 재현되지 않았다. 정확한 하위 사유는
당시 로그에 보존되지 않아 확정하지 않는다. 이번 publication 복구의 savepoint 결함 수정과
구분하며, 재개 직후 READY만으로 새 GPU 묶음 완료를 주장하지 않는다.

복구 command/plan, 완료·replay, 사전 검사와 서비스 재개, 테스트·실패·빌드 로그 등
30개 파일을 기존 Catalog→Orchestrator Artifact 경계로 보관하고 전체 readback/hash를 확인했다.
감사 Artifact `artifact_d9a1aaa742004d83a5a8f638dd4e9beb`,
revision `rev_61278f01c08546319e241dadc35beb79`.
