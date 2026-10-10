# 문항 핵심 착상 전이: 실제 운영 검증 기록

상태 시각: 2026-10-10 UTC. 이 문서는 실제 설치·실행 증거와 남은 gate를
구분한다. 소스 테스트 통과를 운영 활성화나 사람의 전이 품질 승인으로 확대하지 않는다.

## 보존하는 설계와 범위

- [승인된 설계 원문](ITEM_INFERENCE_TRANSFER_DESIGN_ORIGINAL.md)의 SHA-256:
  `f4adc8c7cf8197f3d310f8bb3463b79b54229dae6e2257b0b1c39005c7632e4a`.
- 정본은 기존 승인 문항·기출 분석·풀이보고서 및 pin된 Graph/policy다. 새 비교 표현,
  벡터와 쌍 비교는 보조 파생물이다. 기존 검색·출제·검토·승인 의미를 대체하지 않는다.
- 실제 `guiadmin` 사용 승인을 받았다. 승인은 인증 토큰이나 자격 증명 그 자체가 아니다.
  실제 session과 현재 권한을 검증하기 전에는 corpus를 읽거나 worker를 제출하지 않는다.
- 원래 occurrence-backed 기출 목표 520개를 사용한다. 별도 trusted-RAG canary는 의도적으로
  제외한다. 기존 풀이보고서 520개를 다시 생성하지 않는다.

## Component 상태

| Component | 실제 상태 | 한계 |
|---|---|---|
| 기존 공유 API/platform | 설치 source `83884224651d8b9516a7a54370077757138c518c` | 새 비교 owner API는 아직 이 설치에 활성화하지 않음 |
| 운영 PostgreSQL | 마지막 read-only head `20261009_0050` | source의 `20261010_0051` 적용 전 |
| 별도 CPU Conda | `/opt/eom/conda/envs/eom-embedding-experiment` 보호 snapshot 발행 완료 | 격리 probe와 실제 corpus 실험은 별도 gate |
| CPU platform | `06134fcd91413a957ac3133db062dbcdd525ee15` wheel에서 비편집 설치 | d291 candidate와 1,361개 payload member가 일치함; source 표기는 원래 설치값 유지 |
| 현재 API build-only 후보 | `d2917ba448f21b86e7731d8477e802c658c2e106` | 후속 source 수정 중; 아직 공유 운영 설치하지 않음 |

Component들이 같은 commit이어야 한다고 가정하지 않는다. 실제 파일·wheel·contract
호환성과 설치 provenance를 따로 기록한다. build-only 결과를 live release로 부르지 않는다.

## 보호 CPU 설치의 실제 증거

2026-10-10 15:08 UTC경 보호 snapshot·model·고정 unit·polkit 설치가 완료됐다.

- 고정 runtime의 독립 byte-tree SHA-256:
  `d0dcd26e841ef583ead382b19269f559a3263a35ce809d34c6308bfe0399ed73`.
- 전용 CPU identity: UID 979 / GID 976, private group만 사용, nologin.
- 모델: `intfloat/multilingual-e5-small`, upstream commit
  `614241f622f53c4eeff9890bdc4f31cfecc418b3`.
- local model/revision:
  `embeddingmodel_f30c692a99476867e96f3567ae266036` /
  `embeddingmodelrev_82eace0bd4ceeacb31ced2e8e40bc293`.
- semantic manifest SHA-256:
  `f106f8df1ca01062a3900fa65f4c235d278294c34a113efe1cc1934432d0d9eb`.
- root-private phase receipt:
  `/opt/eom/.embedding-install-n6SfouPM/phase-receipt`.
- 원래 developer tree는
  `/opt/eom/conda/envs/.embedding-prepublication-.embedding-install-n6SfouPM`에 보존했다.
  이 원래 tree는 보호 실행 환경이 아니며 root로 실행하지 않는다.

새 inode에 복사한 뒤 hash/type/mode/link와 wheel payload를 검증하고 고정 prefix로
발행했다. mutable interpreter·pip를 root로 실행하는 방식이나 광범위한 기존 runtime
소유권 변경은 사용하지 않았다. 설치 자체는 모델 load/forward를 실행하지 않는다.

## No-forward preflight에서 발견한 실제 차이

1. 처음의 unprivileged `pkcheck --detail` 호출은 trusted caller 조건 때문에 거절됐다.
   정책을 확대하지 않고 root caller가 실제 별도 kernel-validated subject의
   `PID,starttime,UID`를 확인하는 adapter로 수정했다. 실제 여섯 allow/deny case는 PASS다.
2. installed unit/polkit bytes와 runtime 경로 검증은 PASS다. 그러나 `systemctl show`가
   빈 structured `ExecStartPre`/`ExecStartPost`를 출력하지 않는 실제 serialization 차이로
   strict parser가 실행 전에 거절했다. `--all`도 이 host에서는 빈 배열을 출력하지 않았다.
   나머지 필수 property·exact FragmentPath·drop-in·reload 검증은 유지하면서 이 차이를
   재현 테스트로 보완했다. unit·권한·sandbox 정책을 바꾸는 해결이 아니다.
   수정 driver SHA-256은
   `6333f2aa7b3456c4d5433ca91afa83688018257f8a44f1de4e8fb90a378be477`이며
   root-private `/var/lib/eom-embedding-verifier.XeVJgr8B/verify.py`에서 실행했다.

위 두 preflight 거절 시점의 probe는 `MainPID=0`, `InvocationID` 없음,
inactive/dead였고 실행하지 않았다.

### 최초 실제 no-forward probe와 권한 수정

수정 preflight 뒤 최초 실제 probe가 15:20:29–15:20:31 UTC에 실행됐지만 exit 1로
종료했다. InvocationID는 `5c4878814d5f42a3b28fc91049a7fe36`이다. 모델 load/forward를
호출하지 않는 고정 검증 프로그램이므로 이것을 임베딩 실험이나 worker 비교로 세지 않는다.

root와 실제 전용 CPU UID로 지원된 runtime/model 검증을 따로 조회해 원인을 분류했다.
runtime/RECORD는 양쪽 PASS였지만 model snapshot은 root PASS / CPU `PermissionError`였다.
metadata에서 고정 모델 논리 ID 부모만 root:976:0700임을 확인했다. installer의
`mkdir(mode=0750)`에 umask 077이 적용되고 explicit chmod가 없어 private group traversal이
누락된 것이다. revision은 0750, manifest는 0440으로 의도한 값이었다.

독립 model manifest/member hash 검증 뒤 해당 부모의 retained FD와 정확 UID/GID/inode를
검사하고 **그 부모만 0700 → 0750**으로 복원했다. 소유자·group·모델 bytes·기존 runtime·다른
서비스 권한은 바꾸지 않았다. source installer에 실제 umask 회귀 테스트를 보강했다.
수정 뒤 실제 CPU UID로 동일 model snapshot/hash read를 다시 확인해 PASS였다.
이는 outside-sandbox read 검증이며 전체 격리 probe PASS의 대체 증거는 아니다.

사용자가 기록 보존 후 no-forward 검증 **1회** 재실행을 명시적으로 승인했다. 원래 실패
observation·확인된 원인·수정·승인 한도를 root-owned 0400 receipt로 먼저 보존했다.

- receipt: `/var/lib/eom-embedding-probe-recovery.vNOQNB0B/first-failed-observation.json`.
- receipt SHA-256: `2397e9df2e0bb279bc7a249313e4621b806ac02ef141447dc3becfdcb469c5ab`.

정확한 기존 failed InvocationID·terminal 상태·PID 0·고정 unit/polkit/runtime/model pins와
실제 권한 범위를 재확인한 뒤, 승인된 fixed no-forward probe만 reset-failed했다. 정상
garbage collection 뒤 fresh 상태를 확인하고 동일 reviewed driver의 기존 첫 실행 guard를
그대로 사용해 **한 번** 실행했다. generic retry, 새 identity, main experiment 재실행이나
과거 실패의 성공 재해석은 사용하지 않았다.

실제 재검증은 **PASS**다. 새 InvocationID는 `1f3c503f4ed2400b9b62fa58a422259e`,
상태는 active/exited, MainPID 0, Result success, ExecMainStatus 0다. 동일 policy의 전후
일치와 설치/RECORD/model hash, 실제 identity/network/file/socket negative 검증이 통과했다.
model load/forward 0이다. 첫 실패 journal과 위 receipt를 보존하며 자동 재실행은 없다.

## 현재 source 회귀 검증

최종 동결 source에 대해 94개 test 파일 **2,582 PASS / 89.50초**, Ruff check/format
46개 파일 PASS, strict mypy production 25개 파일 PASS, Bash syntax/diff 검사 PASS다.
최초 통합 실행은 동시 source/test guard 정렬 중 이전 assertions 두 개가 실패했다
(2,578 PASS / 2 FAIL). 전체 동결 뒤 다시 실행한 결과를 위 최종 gate로 기록한다.
앞선 overlapping focused suite 수를 합산해 고유 테스트 수로 과장하지 않는다.

## 운영 변경 경계

공유 API 설치 전에는 지원된 owner projection으로 실제 command/job/lease/GPU claim의
quiescence를 다시 확인한다. historical failed/terminal row와 실제 실행 가능한 일을
구별하며, DB row 직접 수정이나 과거 성공 재해석을 하지 않는다.

기존 migration wrapper가 mutable API interpreter와 checkout을 root로 실행하는 경계를
발견해 [고정 release-operator adapter](../operations/RELEASE_OPERATOR_RUNTIME.md)로 좁혔다.
이 adapter는 기존 Alembic/role bootstrap을 재사용한다. 새 service/queue/worker protocol은
만들지 않는다. root-private reviewed source/wheels/context와 보호 interpreter를 먼저 입장시키고,
exact `20261010_0051` 및 기존 role reconciliation만 허용한다. 아직 실제 DB migration이나
공유 service 중지·교체를 수행하지 않았다.

## 남은 실제 실험과 사람 검토

- 격리 no-forward probe PASS: **PASS_AFTER_ONE_APPROVED_RETRY / FIRST_FAILURE_PRESERVED**.
- compatible shared release / 실제 `guiadmin` 인증·metadata·corpus read: **PENDING**.
- 고정 4-query, top-k 8, batch 4, threads 4 CPU 실험: **NOT_RUN**.
- 최대 2개 selected pair의 지원된 Orchestrator/Codex 비교: **NOT_RUN**.
- 사람의 풀이 전이 품질: **NOT_EVALUATED**.

E5의 512-token 범위를 넘는 자료를 자르거나 성공한 subset을 전체 520개처럼 보고하지
않는다. common encodable pool과 고정 query 조건을 만족하지 못하면
`INSUFFICIENT_ENCODING_COVERAGE`라는 측정 결과를 보존한다. Artifact commit 완료와
유효 benchmark 완료, 사람 평가 완료는 다른 상태다.

사람에게 최종적으로 모아줄 검토는 exact pair·자료 pins·후보 근거·대응하는 조건과
착상·대응하지 않는 부분·새 추론·rubric이다. model 출력으로 사람 평가나 교육 품질 PASS를
만들지 않는다. 사용자의 추가 선택이 필요한 successor 정책은 별도 gate로 남긴다.
