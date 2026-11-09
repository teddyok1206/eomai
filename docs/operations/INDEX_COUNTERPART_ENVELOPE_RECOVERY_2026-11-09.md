# INDEX CPU counterpart 형식 유지와 중단 복구

## 범위와 확인된 원인

Excel 기능과 독립된 사용자 요청이다. INDEX만 수정하며 API/Web/QUERY/문항 등록,
수치 runtime·모델·완료 벡터/보고서는 변경하지 않는다.

2026-11-09 08:35:37 UTC INDEX가 CPU 완료 처리의 ValidationError로 종료했다.
원래 CUDA request는 5.0이지만 `prepare_matching`이 선택한 4개 source만 보고 CPU
request/plan을 4.0으로 낮췄다. 전체 인덱스에는 native-office source가 포함되어
5.0 index가 만들어졌고 4.0 registration command와 충돌했다. CPU 수치 결과는 이미
저장됐으며 실패 지점은 INDEX_PREPARED checkpoint 전이다. 마지막 GPU workflow는
COMPLETED, GPU current index binding은 952였다. READY를 성공 증거로 삼지 않는다.

## 최소 수정 설계

- 소유: Workflow Runner의 counterpart 준비가 원 요청의 public envelope를 보존한다.
  새 플래그/queue/CPU 비활성화는 도입하지 않는다. 최초 전체 discovery의 자동 판별과
  pinned source/Graph/policy/model/space 검사는 유지한다.
- 정본: 원 Workflow/ALLOCATION/성공한 encoding receipts 및 exact staged index metadata.
  기존 4.0 request나 index bytes를 5.0으로 덮어쓰지 않는다.
- 복구: 기존 `index_publication_successor`에 좁은 2.0 유지보수 입력을 추가한다.
  아직 registration command가 없으므로 allocation checkpoint SHA와 staged index member
  SHA를 pin한다. 정확한 request4/index5 충돌, 전 encoding SUCCEEDED, 만료 command,
  root/schema-owner와 현행 동등 grant를 확인한 경우에만 새 index를 게시한다.
  원래 coordinator/workflow는 publication 대체 사유로 FAILED 종료하고 성공 encoding은
  보존한다. 원래 FAILED 기록을 성공으로 바꾸거나 새 수치 실행을 하지 않는다.
- 동일 aggregate/정본 storage/Artifact publisher/Registry CAS/원래 transaction을 재사용한다.
  접근은 exact ID/PK, 최대 4개 encoding의 set membership, bounded index metadata 읽기다.
  새 DB/migration/cache/서비스는 없고 기존 successor의 멱등 plan/hash를 재사용한다.
- 단순 대안인 daemon restart만으로는 같은 4→5 mismatch가 반복된다. 구 request bytes
  변경이나 완료 상태 직접 UPDATE는 실제 publication/이력과 맞지 않으므로 하지 않는다.
- 원래 유효하지 않은 저장 명령을 통과시키도록 기존 released schema를 완화하지 않는다.

## 검증/운영 기록

기존 설치본에서 request5 → CPU request4로 낮아지는 regression을 재현했다.
수정 source의 관련 unit 87 PASS, disposable PostgreSQL recovery 11 PASS:
실제 request4/index5 mismatch, 완료 encoding 유지, 동시 잠금 거부, 잘못된 hash 거부,
FAILED 이력 거부, Artifact commit 후 SQL rollback, 같은 successor plan replay를 포함한다.
숫자 forward 수는 복구 전후 그대로다. Ruff/format과 변경 core 5개 파일 mypy PASS.
초기 DB 테스트의 환경 opt-in 누락 skip 및 fixture 오류 2회는 운영 변경이 아니다.

메인 Excel 작업이 dirty 상태이므로 그 변경을 포함하거나 stash하지 않는다. 본 수정의
좁은 commit을 Git archive로 분리해 INDEX owner wheel만 빌드하고, 기존 owner-pair RECORD
검증·immutable installer를 사용한다. API/Web 릴리스나 migration을 실행하지 않는다.
운영 INDEX 전환, 새 binding 및 처리 재개는 아래에 별도 기록한다.

## 설치와 복구 진행

- 변경 source: `2229937a37777eeb4b2905d5e38a98fd959ff4a8`.
- 추가 dependency/coordinator/cancellation unit 74 PASS, 개발 문맥 13 PASS.
- 기존 unstarted cancellation disposable DB 32 PASS(다른 제한 계정 설정을 필요로 하는
  nonowner 2건은 이번 수정 경계 밖이므로 제외). 복구 suite 11 PASS와 별도다.
- immutable 설치 wheel 직접 unit 28 PASS 및 실제 numerical-owner interpreter import PASS.
  최초 수동 import 검사는 존재하지 않는 `local_indexing_service_daemon` 이름을 사용해
  실패했고, 실제 `local_indexing_service_entry/runtime`로 검사하여 통과했다.
- platform wheel SHA-256 `32a604ec680306c40fd413dbd6adeb9cd47563cb68b949ec6bd9990afe0fe60b`.
- API contracts wheel SHA-256 `cb228997bb1e96abcb3fa653224d667fab641438a3220bce1d6266960ea9afb1`.
- 기존 설치본 대비 runtime Python 5개와 새 recovery schema1개만 다르다. 기존 JSON
  contract bytes는 전부 보존하고, API contracts의 모든 wheel member는 byte-identical이다.
- 수치 runtime source `c915281ea3acda63ea066ba9de397f7bbc335295`와 장치·모델·routing은 그대로다.
- release/rollback 증거: `/var/lib/eom-index-envelope-release-20261109`.
  완료 데이터 대조: `/var/lib/eom-index-envelope-audit-20261109`.
- 변경 전 보존 기준: encoding4,974, binding133,558, index revision582,
  accepted analysis2,883, registered report1,038. 이는 현재 문항 수가 아니라 과거 revision을
  포함한 각 정본 관계의 분모다.

원래 요청 `workflow_b6e9f8ff3a2845099009a1b2e7401204`의 수치 encoding4건은
SUCCEEDED다. 새 service activation 전에 별도의 미실행 standby
`workflow_2df06cb6dc6c46f9bf636f29db93135b`만 공식 cancellation/replay로 종료했다.
CPU head896과 staging900의 차이4건을 고정한 successor publication을 실행 중이다.
이 시점에는 INDEX daemon을 아직 시작하지 않았으며 API/Web/QUERY/creative invocation은
유지했다. 성공 여부와 새 일반 batch 진행은 이후 증거로 구분한다.

### 복구 검증 보정

첫 publication-only 시도에서 같은 root transaction의 source/Registry fence마다
900-binding staged manifest를 반복 검증하는 비용을 확인했다. Registry의 binding 검증
중에 이 operator 실행만 SIGINT로 중단했고, SQL rollback 후 CPU head896/원 Workflow
RUNNING/encoding4건 SUCCEEDED가 그대로임을 읽기 전용으로 확인했다. 이미 게시된
candidate Artifact는 같은 고정 plan의 재사용 대상이며 삭제하지 않는다.

staged metadata는 원 충돌의 입력 증거이며 새로 게시하는 bytes는 canonical receipts로
조립한다. 최초 outer-root admission에서만 staging hash·schema·allocation 일치를 확인하고,
동일 root/session/thread에 보유한 잠금 하에서는 기존 SQL identity/encoding 검증을 계속한다.
다른 transaction은 반드시 다시 읽는다. 새 cache/전역 상태/지속성은 만들지 않았다.
합성 반복 fence25회에서 staged parse1회, 다음 root에서 추가1회와 잘못된 hash 거부를
disposable PostgreSQL 검사로 확인한다. 기존 released schema와 수치 실행은 그대로다.

메인 Excel 개발이 shared source의 migration head를 0075로 바꾸는 도중 임시 DB 검사가
0074 불일치로 시작을 거부했다. 운영 DB를 변경하지 않았고, pinned2229937a source archive에
이 두 보정 파일만 materialize한 별도 테스트 snapshot에서 재검사한다. 메인 migration은
가져오거나 되돌리지 않는다.
