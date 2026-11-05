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
