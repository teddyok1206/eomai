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
