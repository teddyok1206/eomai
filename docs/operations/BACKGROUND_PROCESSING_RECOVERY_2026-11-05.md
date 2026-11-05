# 창작 등록·GPU 임베딩 반복 중단 복구

2026-11-05 UTC. 기존 창작 모집단·보고서·Graph·벡터·실패 이력을 유지하고 실제 처리
재개를 확인하는 작업이다. HWPX 합본의 남은 AI 표본 검증을 이 복구로 대체하지 않는다.

## 재현한 원인

- 창작 publication의 대표 표시 문항은 11996이지만 실제 범위 초과는 같은 묶음의
  **11998**이었다. 저장된 동일 Graph·Evidence Bundle의 28개 seed로 재현했다.
  마지막 hop에서 8,010개 frontier의 연결을 읽은 뒤 170,568개 association을 세었다.
  SQL은 MINOR 목적지가 있는 edge만 선택했지만 Python이 그 edge를 다시 양방향으로
  확장해, 결과에 기여할 수 없는 비단원 목적지까지 계산한 것이 결함이다.
- GPU의 원래 수치 unit은 11월 4일 13:44:33 UTC에 SIGALRM으로 종료됐다. root controller의
  후속 `/proc` fence 오류가 채널 EOF로 전달됐다. 원 Workflow는 계속 RUNNING이고,
  재기동한 담당은 RECOVERY_REQUIRED를 반복했다. planning Job의 SUCCEEDED는 입력 연결
  완료이지 수치 성공이 아니다. 시간 초과의 세부 소요 단계와 공식 실패 복구는 후속 확인한다.

## 최소 설계

1. 책임은 기존 automatic curriculum alignment와 INDEX의 기존 실패 복구·source owner다.
   새 worker protocol, queue, 검색 engine은 만들지 않는다.
2. 정본은 저장된 Graph/Evidence/accepted report와 기존 encoding·수치 실행 이력이다.
3. 원 Item/analysis/Workflow/Artifact와 revision/hash를 유지한다. 완료를 임의 선언하지 않는다.
4. 원 Graph·policy·source·권한·hash 및 실제 수치 unit 종료 증거를 기존 담당에서 검증한다.
5. 주 접근은 제한된 3-hop graph traversal, indexed 원 실행 조회와 멱등 복구다.
6. 마지막 SQL hop에서 source→MINOR 방향을 명시한 두 SELECT의 UNION ALL을 쓴다.
   map/set 기반 multi-source shortest-path, 기존 FK/index와 모든 안전 한도를 유지한다.
7. 허용 edge 수에 선형인 탐색이며 불필요한 reverse leaf/seed 조합만 제거한다.
   단원 순위·거리·support가 무제한 BFS oracle과 같아야 한다.
8. Graph의 기존 CAS·단일 publication future와 INDEX의 기존 원 실행 잠금·recovery
   transaction을 재사용한다. 운영 DB에 pytest나 직접 row UPDATE를 실행하지 않는다.
9. 순수 정책·contract는 변경하지 않고 Catalog SQL adapter와 기존 application에 둔다.
10. 과거 실패는 보존하고 원 실행은 공식 reconcile/recovery로 닫는다. 이미 완료한
    보고서·벡터를 다시 만들거나 대기 루프를 성공으로 바꾸지 않는다.
11. 한도를 올리거나 서비스만 재시작하면 원인이 남는다. 유효한 단원 방향만 탐색하고
    실제 종료 원인을 처리하는 것이 더 작은 수정이다.

## 검증 상태

기존 설치본에서 새 frontier 양방향 회귀가 실패하는 것을 확인했다. 수정 source는
정방향·역방향 edge, 두 끝이 frontier인 경우, cycle과 실제 3-hop 단원을 포함한
oracle 비교 및 기존 정책 hash 회귀 33개가 통과했다. 운영 배포·실제 진척은 아직 별도다.

## 저장 검증의 원본 선택 범위

실제 INDEX stack에서 최종 등록 재검증의 candidate selection을 확인했다. 원 source
4개만 재검증해도 pointer/node materialized CTE는 전체 Graph에서 구성됐고, 이 작업을
수행하는 긴 transaction이 Graph append와 heartbeat를 기다리게 했다. 현재 권한·정본
잠금을 낮추지 않고 source revision의 정확한 analysis key 집합을 먼저 materialize해
기존 pointer 조회에 join한다. 최종 lifecycle·answer-bearing·occurrence·원본 revision
조건은 그대로 유지한다. 새 schema/index/cache는 없다. 기존 source-revision B-tree와
Graph/analysis pointer lookup을 이용하며 선택 K개에 필요한 pointer만 처리한다.

disposable PostgreSQL의 CUSTOM/GENERIC plan에서 전체520과 부분4/8의 동일 결과,
pointer/node CTE의 한 번 실행 및 실제 처리 row 수를 비교한 뒤 운영에 반영한다.
이 후보를 작성했다는 사실만으로 현재 실행의 처리 시간이 줄었다고 주장하지 않는다.

같은 root transaction의 반복 검증에는 기존 `PinnedArtifactReadContext.for_session`을
서비스 INDEX에서도 재사용한다. 인간 검색에서 이미 쓰는 bounded immutable byte/decoding
재사용이며 권한·source·policy·lease는 매번 실제 담당이 확인한다. 재사용 시 mutable
Artifact/producer provenance는 매 capture에서 새 SQL로 재검증한다. 같은 root에서는
처음 hash 검증을 마친 불변 bytes 스냅샷을 재사용하며 나중에 변경된 파일 bytes를 섞지
않는다. 새 root/새 materialization은 실제 파일을 다시 검증해 변조를 거부한다.
다른 설정이나 승인 철회까지 캐시해 통과시키지 않는다. 새 cache나 저장 테이블을
만들거나 무기한 메모리에 보관하지 않는다.

## 검증·실제 재개 기록

- Graph 수정 `ae62b3df`를 별도 설치 wheel/RECORD로 검증한 뒤 창작 owner만 호환
  반영했다. 동일 원 Graph/Evidence로 실패했던11998이 정상 단원3개를 반환했고,
  11996–12000의 실제 등록/공개 풀이 조회5건이 VERIFIED였다. 누적701→706이며
  재시작별 `verified_count=5`를 누적5개로 표시하지 않는다. 03–06 네 실제 slot lease를
  정기 관측에서도 확인했다. 이전 보류23개는 별도 이력이다.
- 기존 GPU 미종료 요청은 root 소유의 원 FAILED retirement 증거를 검증하고 지원된
  `recover_retired_indexing_workflow`로 정리했다. 동일 command 재호출 결과가 같고,
  기존 FAILED 이력·정본·벡터는 그대로였다. 직접 row UPDATE/성공 재해석/새 모델 호출0.
- 재개 뒤 원래 namespace의 새 CUDA Workflow
  `workflow_b7d146e2dce84615b52db5d474c6bf4d`는 실제 수치 실행과 저장을 거쳐
  03:11:33 UTC BATCH_COMPLETED였다. 이후 CPU standby도 진행했다. source 원문·모델·
  CPU/CUDA space·수치 환경은 바꾸지 않았다. 기출271/520과 전체 신규 encoding4건은
  서로 다른 모집단이므로 전자를275로 임의 보고하지 않는다.
- Graph source 집중71 PASS, 설치된 동일 suite의 단원 부분33 PASS, format/lint/mypy PASS.
  read reuse·관련 경계269 PASS와 추가 서비스 root/승인 철회/새 root 변조 거부3 PASS.
  source filter23 PASS, disposable PostgreSQL128 PASS와 migration72 왕복/cleanup PASS.
  시험 환경의 import/fixture 입력 수정 실패 로그는 보존했으며 운영 장애로 세지 않는다.
- 같은 PostgreSQL fixture의 pointer/node CTE 처리량은 전체520일 때10,400 rows,
  선택4일 때80 rows, 선택8일 때160 rows였다. CUSTOM/GENERIC 모두 한 번 실행하며
  결과가 동일했다. 선택4의 관측은36.740/17.482ms다. 운영 전체 지연 개선 수치는 아니다.
- py-spy0.4.1은 변경 없는 두 실제 process의 함수 stack만 nonblocking으로 관측하기
  위해 임시로 사용했다. locals/환경/인증/문항 내용은 수집하지 않았고 production
  interpreter나 requirements에는 설치하지 않았다. production 필수 의존성이 아니다.

수치 성공을 Workflow 완료로 바꾸거나 READY를 새 release의 실제 작업 완료로
대신하지 않는다. 조회 범위·root reader 개선의 운영 source와 후속 실제 완료는
배포 후 기록한다. GPU/창작 정기 관측·Slack 한 줄 보고는 계속 유지한다.
