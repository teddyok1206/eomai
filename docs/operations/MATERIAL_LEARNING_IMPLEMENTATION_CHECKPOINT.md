# 자료 학습 구현 checkpoint

2026-11-05 UTC. 사용자의 최종 범위는 운영 배포·제한된 실제 업로드 처리 확인까지다.
goal 카드의 초기 배포 금지 문구는 후속 사용자 지시로 대체됐다. 이 문서는 운영 완료
보고서가 아니며, 후보와 실제 운영을 혼동하지 않기 위한 중간 기록이다.

## 완료한 소스 후보

- D0 설계 후 R1·R2 검토와 D2 반영. 기존 교과서 구매 권리/기출 occurrence/Notion
  출처를 일반 자료에 만들어 넣지 않는다.
- `679e48c1`, `bdfb23e7`, `a349b143`, `df7419fb`, `acde0850`: 기본 계약·wheel 경계,
  실제 형식 기반 업로드, 작은 진행 상태, 긴 자료 준비/재개·공식 Document 등록,
  원래 Workflow/command/Job/slot/Artifact owner를 통한 발견·추출 실행 후보.
- 일반 설명은 source V5/request·result V12/receipt V11/role 1.38/plan V34로 기존
  knowledge-analysis·risk·proposal·shared Graph projection에 연결했다. 안정된
  proposal V6의 개념·관계 identity를 재사용한다. snapshot V10은 같은 Graph와 구조 V6를
  사용하며, 구 snapshot bytes를 수정하지 않는다.
- Catalog가 실제 저장된 child/업로더를 기준으로 원본·권리·문서·page chunk·선택 범위와
  현재 권한을 재인가한다. Worker는 로컬 staged PNG/text만 받는다. V34도 준비 후 실행,
  결과 commit 직전의 source fence를 통과해야 한다. 임의 actor 입력은 없다.
- page reader를 준비된 자료·canonical Document 양쪽의 공식 읽기에 재사용한다.
  선택 chunk당 한 번 읽고 페이지는 이분 탐색한다. child Workflow/analysis는 partial
  unique indexed lookup이다. 자료 role output은 NAS Artifact이고 DB에는 작은 receipt만 둔다.
- 일반 문항용 source-lineage 계약과 기존 Registry용 등록 Pack 후보를 추가했다.
  독립 풀이로 원문 정답을 바꾸지 않는 compiler와 native picture-use pointer resolver를
  공유한다. 이것은 실제 Item 등록/공개 풀이/INDEX 완료 증거가 아니다.

## 이번 checkpoint 검증

- 관련 schema/model, 실행 fence, 지식 staging, Graph projection/structure, 기존 resolver/
  materializer, 한글 picture-use, 원문 보존, 조회·runner source 회귀: **256 PASS**.
- 위 범위에는 일반 문항 lineage/Pack/compiler/native pointer 계약 **4 PASS**도 포함된다.
- 주요 후보 source 20개 mypy PASS. 전체 변경 Python formatter/linter를 적용한다.
- 공식 marker-guarded 새 disposable PostgreSQL의 candidate migration 0074 왕복과
  role/Workflow/task/intake/page 준비·재개·유일성/동시성: **25 PASS**.
- 앞선 package/설치 resource·의존 경계/계약 보존 suite **20 PASS**. 새 후속 diff의 최종
  전체 wheel/release 검증은 배포 전에 다시 한다.
- fixture는 가상 worker/제한된 로컬 파일 및 실제 임시 DB를 사용했다. 운영 DB를 pytest
  대상으로 쓰지 않았다. 아직 이 기능의 실제 모델/GPU 실행·운영 migration/배포는 0이다.

상세 로그는 Git에 넣지 않고 임시 작업 증거로 유지한다. 실패한 초기 schema reference/
fixture 실행도 성공으로 바꾸지 않았다. 최종 운영 보고서는 별도로 작성한다.

## 반드시 남은 일

1. 일반 설명 source의 retrieval/evidence 소비 연결과 공유 Graph 증분 publication을
   완성한다. source V5를 구 licensed bundle로 위장하거나 구 consumer에 억지로 넣지 않는다.
2. material task의 실제 완료 result를 읽어 Registry 등록·공개 풀이·Graph 및 기존 common
   incremental INDEX에 연결한다. native 그림/PDF 그림과 원문 위치, source quality 경고,
   창작/AI 구분 및 DB 조회를 유지한다.
3. bounded coordinator/설정·control release·한 AI lane/전역 capacity 4, pause/retry/replay,
   중단 시 기존 child 재조회를 구현·검증한다. 준비/등록/Graph 중 슬롯을 잡아두지 않는다.
4. schema/DB/중단·재전송·권한·실제 browser·source-free wheel 및 호환 release/rollback을
   검증한 뒤 운영에 배포한다. 0074는 아직 production 미적용이며 현재 head는 0073이다.
5. actual actor로 제한된 자료의 업로드→내용/문항→Graph→INDEX handoff와 같은 요청 재조회를
   확인한다. 결과 없는 health/READY를 실제 학습 성공으로 보고하지 않는다.

## 보존 및 배포 주의

기존 창작 producer와 GPU INDEX 실행은 계속 유지 중이다. 마지막 확인 22:16 UTC에
실제 worker lease 4개와 동일 producer/INDEX PID·invocation을 확인했다. 운영 분류의
source 보류 수는 36이며 이번 개발에서 수정하거나 성공으로 재해석하지 않았다.

새 image input V5 parser 때문에 protected worker helper의 hash가 바뀐다. 최종 배포는
진행 중 Codex 역할을 자연 완료시킨 뒤 helper와 영향을 받는 driver/runner prefix를
호환 set으로 맞춘다. 모델·입력·기존 cohort/실패 이력은 보존한다. 별도 numeric GPU INDEX는
같은 실행을 유지하며, 새 권리 정책으로 기존 RAG access policy를 조용히 확장하지 않는다.
