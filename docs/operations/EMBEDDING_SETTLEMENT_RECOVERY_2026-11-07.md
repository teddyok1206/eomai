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

운영 설치·qualification·호환 전환과 실제 index commit은 후속 기록으로 구분한다.
