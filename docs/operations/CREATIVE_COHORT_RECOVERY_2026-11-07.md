# 창작 등록 보류 복구 — 2026-11-07

## 확인한 문제와 운영 반영

원래 1,053개 모집단의 producer는 1,029건 검증·24건 보류로 보고했다. 그러나 현재
공유 Graph의 창작 문항은 1,030건이었다. 별도 공식 retry로 이미 승인·Graph 등록한
12113을 최초 FAILED 분석만 읽어 다시 보류하던 deterministic 연결 결함을 확인했다.

코드/설치 source: `6272329a1cce31e6393278be12297bb7f8ccccc7`.
`KnowledgeAnalysisApplicationService.resolve_retry`가 원 predecessor chain과 정확한
source/operator/preset/policy/hash만 따라간다. 기존 FAILED를 성공으로 바꾸지 않으며,
retry나 모델 요청을 스스로 만들지 않는다. 원래 accepted retry의 실제 설치본 조회 PASS.

기존 successor 준비의 별도 `creative-execution-recovery/1.0` route로 실패한 5건을
명시적으로 한 번 재개했다. 실제 process 부재, 원 Job·step·Workflow, 원본과 실행 핀,
commit 이력/Artifact/command/lease 부재를 확인한다. 원 실패와 고아 RUNNING metadata를
성공으로 재해석하지 않는다. 새 요청은 원래 Orchestrator queue/4슬롯 capacity가 실행한다.

2026-11-07 06:29:57 UTC 실제 관측: 03·04·05·06에 새 4개 Job의 RUNNING/유효 lease,
worker unit과 Codex process를 확인했다. 복구 대상 5건 중 1건은 REQUESTED로 대기했다.
이것은 5건 전체의 등록 완료 증거가 아니다. 이후 상태는 기존 10분 observer로 확인한다.

## 실행 대상과 보존

| 고유번호 | 원래 상태 | 이번 조치 |
| --- | --- | --- |
| 12113 | 원 분석 FAILED, 명시적 retry ACCEPTED·Graph 등록 | 정확한 retry 읽기 연결, 모델 재생성 없음 |
| 11737, 11741, 11742 | WORKER_EXEC_FAILED, 실제 unit 종료 | 공식 같은-input successor 1건씩 제출 |
| 11828, 11829 | Workflow/step FAILED, Job은 과거 RUNNING, 실제 unit 없음 | 별도 terminal-execution proof로 successor 1건씩 제출 |

세 execution failure의 과거 stderr에는 사용량 제한 관련 표식이 있었다. 이는 당시 실패
분류이지 현재 사용량의 증명은 아니다. 이번에는 실제 새 process/lease로 재개를 확인했다.

새 설치 prefix는 `/opt/eom/embedding-owner-releases/6272329a1cce31e6393278be12297bb7f8ccccc7/site-packages`.
기존 creative unit의 prefix만 교체하고 같은 cohort revision·환경 설정을 유지했다.
API/Web/Catalog/INDEX/QUERY/material/4개 Workflow Runner의 PID·InvocationID는 전후 동일했다.
DB migration, 원본 변경, 벡터 삭제, GPU 재시작은 없었다.

producer의 실행별 `verified_count`는 재시작 후 다시 검증하며 올라가는 값이다. 재시작 직후
0은 누적 Graph 삭제가 아니다. 기존 reporter의 누적 Graph 집계와 혼합하지 않는다.

## 남은 입력 보류 — 완료로 표시하지 않음

| 분류 | 고유번호 | 확인 결과 |
| --- | --- | --- |
| 원문 선택지 목록 부재 | 11416, 11421, 11652 | worker 완료 결과가 proposal 없이 명시적 보류. 선택지를 추측해 등록하지 않음 |
| 페이지/표의 관찰 내용 불완전 | 11768, 12017 | 표 대응 관계 또는 문항 뒷부분 누락이 기록됨. 원본 재확인 필요 |
| native 그림 표현 한계 | 11743, 11763, 12241, 12266, 12281, 12282, 12310 | 효과·도형·묶음/배치 그림의 정확한 native use가 미해결. crop/참고란 대체 그림으로 강행하지 않음 |
| 최신 변환에서도 PDF 검증 실패 | 11400, 11584, 11643, 12201 | 실제 HWP/OLE signature 확인. choice-layout-v3 probe에서 OUTPUT_INVALID. 원본 손상으로 확정하지 않음 |
| 최신 PDF 후보 준비, 기존 입력 경로에는 미연결 | 11669, 11753 | choice-layout-v3로 공식 PDF Artifact 생성·열기 PASS. 과거 legacy-v1 source pin을 몰래 대체하지 않음 |

합계 18건은 아직 등록 완료가 아니다. 새 PDF 2건은 GUI 최신 preview에서 사용할 수 있는
별도 generation이며, 기존 학습 driver의 legacy-v1 입력을 복구한 것으로 세지 않는다.
이 범위를 닫으려면 미처리 원본의 명시적 현행 conversion-profile 입력과 그 exact preview
재인가를 공유 authorizer/worker materialization 경계에서 지원해야 한다. 기존 실행과
완료 원본의 pin을 변경하는 방식으로 처리하지 않는다. native 효과/도형 합성은 별도
parser 지원 경계이며 같은 모델 요청을 반복하는 것으로 해결됐다고 주장하지 않는다.

## 검증

- focused source tests: retry read·cohort cached failure·successor proof·과거 recovery·정기 관측·schema resource.
- disposable PostgreSQL: 같은 원 run의 concurrent retry 생성/조회, accepted 재조회,
  original FAILED/version 불변, 단일 successor, predecessor index EXPLAIN 및 기존 Graph/DB 회귀 PASS.
- formatter/linter, 변경 6 module의 mypy `--follow-imports=silent`, canonical/mirror schema audit PASS.
  일반 follow-imports에서는 기존 material request union 관련 6개 오류가 다른 3개 모듈에서
  보였다. 이를 이번 수정의 오류로 숨기거나 무관한 코드를 같이 변경하지 않았다.
- 비편집 설치 wheel build/RECORD와 실제 root-owned prefix origin/hash, 원래 accepted retry 조회 PASS.
- 4개 실제 Codex process와 같은 Job/slot의 유효 lease 확인. 전체 처리/교육 품질 승인은 별도다.

## 감사와 rollback

운영 원본 기록: `/var/lib/eom-creative-recovery-20261107/`의 `before.json`,
`creative.service.before`, `staged.json`, `preflight.json`, `intent.json`, `applied.json`.
일시 진단 stdout은 root/operator 한정이며 credential·worker prompt를 복사하지 않는다.

rollback은 새 creative owner를 정상 drain한 뒤 보관된 이전 unit bytes를 복원하고
daemon-reload/start하는 범위다. 원본/새 Workflow·분석/accepted Artifact/실패 이력과
기존 GPU 실행은 삭제하거나 되돌리지 않는다. 진행 중 worker는 기존 queue/owner가 소유한다.
