# INDEX GPU 배치·벡터 저장 실제 검증

상태: 운영 호환 전환 및 실제 CUDA 배치·저장 검증 PASS. 시각은 UTC.
사용자가 2026-11-13 “마무리해줘”로 INDEX 전용 호환 전환과 실제 검증을 승인했다.

## 확인된 실패

- 이전 재개 owner invocation `397f12fbff6f4cf19a5cf46770f68879`는
  CPU workflow `workflow_b958f12d681443b49fa518b34404ba2e`를 완료했다.
- 새 encoding 4개·binding 4개, 1,024차원 CPU shard와 index revision
  `embeddingindexrev_dbd7a7577d45414e402d6d07e09ddbc6`의 실제 NAS bytes를 읽어
  hash·shape·finite/L2·row pointer·index 포함을 확인했다. 이는 GPU 성공 증거가 아니다.
- GPU controller attempt `31db644b9a094b439f326a4ff6b753f4`는 11월 12일
  17:43:29~17:43:51에 `embedding_gpu_batch_unit_descriptor:75`의
  `daemon-reload` 10초 timeout으로 실패했다. CUDA 수치 실행 전이다.
- owner는 기존 CPU call을 drain한 뒤 18:01:38에 연결 실패를 기록하고 종료했다.
  이 늦은 종료 시각을 GPU 계산 시간으로 해석하지 않는다.
- 소스 `bc2e5ce0`의 30초 수정은 QUERY 쪽에는 반영됐으나 INDEX purpose delegation은
  기존 `df57dac24f31ad8448c518b7804e8d3ad8284c20`으로 고정돼 있었다.

## 좁은 운영 변경

1. 책임은 기존 INDEX controller 선택과 기존 descriptor adapter에 있다. 새 queue/worker/
   registry/API/schema/DB migration을 만들지 않는다.
2. 정본은 이미 설치된 불변 wheel, 기존 source request/Graph/policy, 성공 receipt다.
3. 선택은 INDEX controller `df57dac2` → `a7fc195d607bdca917cce0d48a4897b1db313c9b`다.
   실제 GPU 제어 관련 10개 모듈의 Git diff는 descriptor 대기 10초→30초 한 곳뿐이다.
4. `/etc/eom/local-indexing-owner.json`의 `controller_release`와
   `/etc/eom/embedding-gpu-batch-owner.env`의 INDEX 전용 delegation release/bootstrap SHA만
   함께 바꾼다. QUERY의 공용 bootstrap 선택과 나머지 env 값은 그대로다.
5. 접근은 두 고정 key lookup, 작은 config 직렬화·hash, 정확한 revision 참조로 O(1)이다.
6. 기존 typed parser와 canonical serializer를 사용하고, 실제 root interpreter import로
   선택한 설치본의 30초 제한을 확인했다. 기존 INDEX 본체는 `47fc5366`을 유지한다.
7. 실행 중 native GPU 작업이 없고 INDEX가 정지된 시점에 선택했다. 파일별 교체는
   원자적이지만 두 파일을 분산 transaction이라고 부르지 않는다.
8. 실행 계획·모델·precision/space/recipe·numerical runtime·source grant는 바꾸지 않는다.
   API/Web/QUERY/Catalog/creative/material의 PID·invocation과 관련 config hash를 보존한다.
9. 기존 encoding의 cutoff와 ordered SHA-256 fingerprint를 저장해 검증 후 비교한다.
   새 정상 encoding은 허용하고 기존 encoding의 변경·누락은 거부한다.
10. 기존 실패 allocation은 재실행·연장·성공 재해석하지 않는다. 새 호환 controller를
    사용하는 후속 정상 admission은 기존 owner와 멱등 parent store가 처리한다.
11. 기존 파일을 덮어쓰거나 timeout 검사를 제거하는 대안은 immutable release와 종료
    판정을 깨므로 사용하지 않는다. rollback은 정지 상태에서 보관된 두 before 파일을
    정확히 복구하는 작업이며, 완료 벡터·역사적 실행을 되돌리지 않는다.

전환 기록: `/var/lib/eom-index-controller-reload-20261113/`의 `plan.json`,
`root_env.before/after`, `owner.before/after`, `selected.json`, `start-requested.json`.
선택 때 daemon reload는 하지 않았다. 실제 신규 GPU descriptor의 reload 한 번만 기존
수치 allocation deadline 안에서 최대 30초 기다린다. timeout 후 자동 재전송은 없다.

## 검증과 종료 기준

- source focused 115 PASS, 관련 runtime mypy 2개 PASS, 설치 root import PASS.
- 03:10:57 INDEX 시작, 03:11:19 실제 runtime capture 후 reconciliation 진입.
- PASS로 닫으려면 실제 CUDA 수치 완료, canonical shard/vector hash·shape·finite/L2,
  encoding/binding/index 저장, 해당 Workflow 완료와 같은 결과의 무계산 재조회를 확인한다.
- 기존 데이터 불변성 및 다른 service/config 보존을 다시 확인한다.
- parent planning 성공·서비스 active·파일 존재·CPU 성공을 GPU 저장 성공으로 대체하지 않는다.

## 실제 CUDA 실행

- 신규 attempt: `2921b3ba4def4c5a96d71b20960555c5`.
- root controller는 03:14:20 시작, 03:20:53 정상 종료(exit 0)했다. 이 시간에는
  준비·검증·모델 실행이 포함되며 순수 GPU 연산 benchmark로 쓰지 않는다.
- 신규 Workflow: `workflow_2c2b8e4a50c94ae0840652dd1503e1de`.
  command: `wfcmd_be69c775a2644428b332dd01dadfeb9f`(attempt 1).
- CUDA encoding Job 4개가 성공했고 기존 coordinator의 `INDEX_PREPARED` → `REGISTERED`
  기록이 보존됐다. 등록 checkpoint 시각과 transaction이 외부 조회에 보인 시각은 다르다.
- GPU index revision `embeddingindexrev_aeb3d8e5470ac839d6aea394811e6762`와 별도로,
  동시 CPU standby의 index revision `embeddingindexrev_3bcc2722e57a4d2ba9d0f1bcbacd3267`도
  등록됐다. CPU 4개 추가를 CUDA 4개 추가 증거로 혼동하지 않는다.
- 03:26 보존 검사에서 기존 encoding 5,498개 fingerprint와 peer/config 보존 PASS.
  API `/api/v1/health/ready` READY, 실제 HTTPS redirect 후 화면 HTTP 200.
- read-only 진단의 첫 SQL에 없는 `workflow_commands.updated_at`을 지정한 오류가 있었다.
  조회문만 수정했으며 최초 오류 로그도 감사 파일로 보존한다. runtime 오류나 재실행이 아니다.

## 최종 결과

- 해당 CUDA Workflow는 **03:45:34 COMPLETED**, 원 command는 **SUCCEEDED / attempt 1**이다.
  기존 공식 `validate_completed_native_workflow`로 terminal step과 최종 pointer도 검증했다.
- 03:45:56 readback: CUDA 신규 encoding **4개**, source binding **4개**, shard **1개**,
  dimension **1,024**. 실제 Catalog Artifact owner로 `shard.json`과 `vectors.f32`를 읽어
  SHA-256·binary shape·finite·L2 norm·row index를 확인했다.
- encoding row → shard member → index binding, request/Graph/space → source plan →
  registration receipt → 해당 index revision이 일치한다. CPU space의 추가분은 제외했다.
- 같은 고정 Artifact member를 다시 읽어 동일 bytes를 확인했다. command attempt와 해당
  encoding rows는 그대로다. 검증 자체의 모델 실행·운영 DB 변경은 모두 0회다.
- 수치 완료만이 아니라 실제 등록 및 Workflow 종료까지 PASS다. 전체 corpus 임베딩이
  완료됐다는 뜻은 아니며, 기존 INDEX owner는 동일 invocation에서 배경 처리를 계속한다.
- 이 실행에서는 CUDA controller 종료 후에도 source/receipt 재검증과 최종 반영에 시간이
  소요됐다. 준비·후처리를 순수 GPU 연산 시간이나 벡터 유사도 계산 시간으로 해석하지
  않는다. 이번 범위에서 입력·검증·모델·batch size를 바꿔 속도를 과장하지 않았다.

최종 증거는 `cuda-storage-readback-12-20261113.json`,
`index-controller-reload-final-preservation-20261113.json`,
`index-gpu-numeric-terminal-20261113.json`과 기존 Catalog file-set 감사 Artifact에 보존한다.
감사 Artifact는 아래에 별도 인계 포인터로 기록한다.

## 감사 보관과 최종 운영 상태

- 감사 file set: `artifact_8506b33296d34fd4a3f8629e5ab739ad` /
  `rev_86bc70a439274f2099b5517e06e6fa44`, 12 members, 전체 hash-pinned 재조회 PASS.
  본 인계 포인터를 덧붙이기 전 문서와 실제 검증 결과·operator·오류 로그·전환 기록을
  기존 Catalog/Orchestrator 경계로 보관했다. env 원문·인증 자료는 포함하지 않았다.
- 03:47:10 최종 검사: 기존 encoding **5,498개 전부 불변**, peer services와 수치 pin 보존.
  INDEX PID `203375`, invocation `ae8aa922531144088813d2b712d8ed1f` 유지.
- 03:45:53 owner 자체가 원 CUDA command의 `BATCH_COMPLETED`를 관측했다.
  해당 고정 Graph 관측에서 eligible sources 1,556 / missing bindings 340이었다.
  이는 관측한 scope의 남은 연결 수이며 전체 DB의 미임베딩 문항 수로 바꾸어 부르지 않는다.
- 03:46:53 다음 `LOCAL_INDEXING_RECONCILIATION_STARTED`까지 확인했다. 실제 배경 처리는
  계속되며 이번 검증 종료를 이유로 중단하지 않는다.
- 일상적인 임베딩 Slack timer는 다시 켜지 않는다. 완료 milestone만 기존 개발 reporter로
  인계하며, 본 작업의 Git 변경은 운영/개발 문서뿐이다.
