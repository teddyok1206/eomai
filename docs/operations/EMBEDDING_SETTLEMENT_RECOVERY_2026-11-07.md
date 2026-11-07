# GPU 결과 확인 시간 만료 수정

설계: [완료 확인 시간 분리](../architecture/EMBEDDING_ALLOCATION_SETTLEMENT_BUDGET.md).
시각은 UTC이며 아래 source 검증을 운영 완료로 해석하지 않는다.

## 원래 실패 정리

`workflow_bfb8b5f72e4544b8b9f644f3407bab4a`의 수치 unit은 FAILED로 종료됐고,
원 invocation `f07e2f164d9f47c586468fd4cf1cbd0d`의 retirement/FDSTORE=0이 이미 존재했다.
이 증거를 설치된 `recover_retired_indexing_workflow`에 전달해 원 Workflow/command와
4개 encoding 예약을 FAILED로 공식 정리했다. 모델 실행 0, runtime pin 변경 0이다.
계획 Job의 SUCCEEDED는 계획 완료일 뿐이므로 수치 성공으로 바꾸지 않았다.
원 결과 파일·339/520 저장 결과·실패 이력은 보존했다.

## 소스 검증

- 처음 focused 92 PASS. 추가 물리경계 suite는 163 PASS + 옛 421초 fixture 1 FAIL이었다.
  새 한도 780초의 초과값 781초로 fixture를 수정했고 최종 관련 56 PASS 및 22 PASS 재확인.
  서로 중복된 집합이며 합산하지 않는다.
- compute timer가 backend에서 작동하고 최종 ACK 대기에는 해제되는지, ACK 유실 시
  결과 파일을 남겨도 성공하지 않으며 lease를 닫는지를 실제 Unix socket fixture로 검사했다.
  별도 자식 프로세스의 kernel SIGALRM 종료 검증도 유지했다.
- Ruff format/check, production 4개 mypy, systemd unit 정적 검사, diff check PASS.
- disposable PostgreSQL `/tmp/eom-api-testdb-20261107141752_cb226959`의 0074 migration
  왕복 PASS. planning/recovery suite는 95 PASS + 제한계정 미준비 3 FAIL이었다.
  공식 runtime-role reconcile 뒤 recovery 39개 전체 PASS. 원 59개 planning 검사와 함께
  동시 생성·원 deadline replay·실패 history·권한 거부·복구의 rollback을 확인했다.
  운영 DB에서 pytest를 실행하지 않았다.
- 잘못된 unit test 파일명으로 수집 전 거부된 1회 호출은 검사 결과로 세지 않는다.

## 운영 반영

- 수정 source `c915281ea3acda63ea066ba9de397f7bbc335295`를 커밋·push하고 wheel/RECORD를 검증했다.
- 새 CUDA private package를 설치한 뒤 실제 prefix byte audit와 no-forward GPU probe,
  두 ACK, same-live receipt 2.1 seal/readback, PID1 FDSTORE retirement를 통과했다.
  모델·토크나이저 추론은 이 qualification에서 실행하지 않았다.
- 새 receipt raw SHA는
  `sha256:62c13d1e700c429d096e251a56ea164e31c88afc5c403fde37e55ca093e3caea`다.
  기존 numerical implementation/model/dtype/vector space는 유지했다.
- INDEX/controller/QUERY와 CUDA 설정을 호환 전환했다. INDEX identity는 기존 공식
  register/activate 경계에서 successor를 만들었고, CPU/CUDA grant의 source scope는 유지했다.
  QUERY provider가 사용하는 API wheel/code pins는 그대로다. Catalog는 public read 설정 hash만
  갱신했다. API/Web PID·invocation과 창작/자료 학습 서비스는 유지했다.
- 14:44:33 UTC에 INDEX/QUERY가 active인 것을 확인했다. 이는 actual index commit 증거가 아니다.
  재개 후 실제 작업의 저장 완료와 다음 묶음 진행은 별도로 확인한다.
- QUERY 구성·시작 경계 관련 source 검사 101 PASS. disposable DB는 공식 cleanup으로 제거했다.

## 실제 실행 검증

- 재개한 CUDA Workflow는 `workflow_5de3b915ec5d4b3ba186d60c6738778b`, allocation은
  `embeddingallocation_18df11050aa341f684697d55d89aebf8`다. 입력은 14:50:13,
  결과 JSON/벡터는 14:52:06 UTC에 생성됐다. numerical worker와 root controller는
  모두 exit 0이며 controller 완료 시각은 14:52:43 UTC다.
- 15:03:41 UTC read-only snapshot에서 public-solution CUDA encoding 저장 행이
  764 → 768로 증가했다. CPU 736과 기존 corpus partition의 각 1,563행은 그대로다.
  이는 vector record 수이며 문항 수가 아니다. GPU 계산과 encoding 저장은 실제 통과했다.
- 이 snapshot에서 Workflow는 아직 RUNNING이다. index publication 및 Workflow 완료,
  다음 묶음 시작을 encoding 저장 성공과 구분해 추가 확인한다.
- 15:07:52 UTC snapshot에서는 새 current CUDA index
  `embeddingindexrev_2db97a40093f7fc0404de938b638bd67`의 binding 768개와 eligible source
  1,556개를 확인했다. index publication도 실제 저장됐으며, Workflow terminal settlement는
  아직 별도 진행 중이다. eligible source 모집단과 기출 520개 분모는 서로 다르다.
- 새 allocation 만료 전에 numerical lifetime이 정상 종료됐으며, 이후 별도 source 검증과
  index publication은 기존 Workflow/command 경계에서 진행한다. allocation 연장·재계산은 없다.
- 운영 조회는 REPEATABLE READ / READ ONLY로 상태와 append-only history를 같은 snapshot에서
  읽었다. 최초 READ COMMITTED 조회에서 발생한 history 경합은 관측 도구 문제였으며,
  runtime 실패나 DB 수정으로 처리하지 않았다.
- 15:18:20 UTC owner가 `BATCH_COMPLETED`를 기록했고, 15:18:47 UTC snapshot에서
  위 Workflow의 COMPLETED, encode_batch/complete의 SUCCEEDED, receipt Job
  `job_7629bfe63f57464eb73f1f2a3aaa4a5e`의 SUCCEEDED를 확인했다.
  실제 계산·encoding 저장·index commit·Workflow 종료 모두 통과했다.
- 같은 실행이 후속 CPU standby Workflow `workflow_2cf4270baadc4e30b1714b71d8b5ada2`를
  공식 제출했다. 기존 관측기의 15:10 보고는 기출 CUDA 341/520으로, 이전 339/520보다
  2개 증가했다. 새 vector 4개를 기출 4개로 잘못 세지 않는다.
- 이번 reconciliation 전체는 2,011,076 ms였다. 수치 계산 뒤 여러 단계의 정본 재검증이
  오래 걸렸으며, timeout 수정의 성공을 처리량 개선으로 주장하지 않는다. 현재 실행을
  보존하고 이 성능 경계는 별도 후속 후보로 기록한다.
- 15:19:20 UTC 같은 INDEX PID에서 다음 GPU reconciliation이 자동 시작됐다.
  15:20:23 UTC에는 CPU standby의 native handoff 준비 unit도 실행 중이다. CPU 대기가
  다음 GPU discovery를 가로막지 않는 경로를 확인했다. 다음 묶음의 수치 계산 완료를
  주장하는 증거는 아니며, background producer와 기존 10분 관측/Slack timer는 유지한다.

## 설치 중 실패와 복구 구분

초기 설치 준비에서 전체 저장소 archive가 64 MiB 한도를 넘었다. 실제 package/source closure로
범위를 좁혔으나 첫 byte audit에서 의존성 lockfile이 archive에 빠진 것이 확인됐다.
그때 prefix 교체는 이미 끝났으므로 재설치하지 않았다. 같은 commit의 lockfile까지 포함한
archive를 보존하고 기존 `admit_index_runtime.py prefix-bytes`로 읽기 전용 재감사했다.
원 실패 audit와 prefix backup은 보존했다.

설치/qualification 호출에서 stopped FAILED 상태, GPU 장치가 가려진 namespace, helper 최초
읽기의 atime, CUDA 전용 working directory를 바로잡았다. 해당 실패는 실제 모델 실행 전이며,
권한/hash/격리 검사를 제거하지 않았다. 성공한 probe output에 재사용 template의
`cpu_owners=CONTINUED_UNCHANGED`가 있으나 **CPU prefix 불변만 의미하며 서비스 연속 실행
증거로 사용하지 않는다**. 배포 중 INDEX/QUERY를 멈췄고 이후 호환 묶음으로 재기동했다.

정확한 before/after, source/wheel/input pins, 실패 및 성공 기록:
`/var/lib/eom-allocation-settlement-20261107`,
`/var/lib/eom-allocation-settlement-index-20261107`.

## 슬롯 풀이 후속 상태

14:46:03 UTC에 이전에 공식 재개한 11828 successor의 extract/complete 모두 SUCCEEDED와
Workflow COMPLETED를 확인했다. 창작 producer projection은 1,053개 중 1,035개 등록 검증 완료,
원본 읽기/변환 보류 18개다. 이 시점 active slot lease가 없는 것은 처리 가능한 잔여 문항이
끝난 상태와 구분해 해석한다. 기존 실패를 성공으로 바꾸지 않았다.
