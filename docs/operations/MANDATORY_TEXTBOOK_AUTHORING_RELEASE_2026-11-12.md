# 교과서 필수 출제·공통 미리보기 운영 반영

2026-11-12 UTC. 사용자 승인에 따라 source `d1328814426d5d4da4e7a7ae7bc673f4969ec7fc`
(구현 `13659f03`)을 운영에 반영했다. 신규 문항 생성이나 과거 문항 재작성은 수행하지 않았다.

## 실제 적용 범위

- 새 문항 요청에서 일반 모드 선택을 제거했다. 새 생성 요청은 교과서를 포함하는
  공식 GraphRAG 준비 경로를 사용하며, 실제 교과서 근거가 없으면 일반 지식으로 우회하지 않는다.
- 별도 연동 지침 Pack `generated-knowledge-item/1.20.19`를 공식 Catalog
  import/release/activate 및 Orchestrator Artifact commit 경계로 등록·활성화했다.
  팀장 원문 프롬프트 두 개와 Pack18은 변경하지 않았다.
- CONTENT_TEAM_V2/V3 미리보기에서 완성 해설과 개별 ㄱㄴㄷ 해설을 중복 출력하지 않는다.
  BLOCKS_V1의 독립 해설, 정본 Item DTO와 HWPX는 그대로다.
- 기존 실행 replay와 고정된 revision/Pack을 유지한다. 과거 문제의 용어나 내용을
  이번 배포로 자동 교정한 것은 아니다.

## 호환 release set

| 구성 | 실제 상태 |
| --- | --- |
| API·shared platform·Catalog·runner | `d1328814` 설치 및 source/pointer 반영 |
| Web | `d1328814`, 설치 RECORD 73개 검증 |
| QUERY owner | 기존 `11d826d2` 유지, API provider hash만 호환 갱신 |
| QUERY controller / numerical | 기존 `377b196e` / `c915281e` 유지 |
| INDEX·자료 학습 설정/실행 identity | 배포 전후 동일 |
| DB migration | 없음, `20261110_0077` 유지 |

Pack release는 `packrel_a596b3c4cb7c4d019cc234ebe80b264e`, bundle SHA는
`sha256:05cec904252d36faf3fb82590b3344f2680953af1952fc3c1ea6ae223ccc7295`다.
공식 read-only resolver가 반환한 현재 knowledge preset은 revision 28이며,
TEXTBOOK·`integrated-science-textbooks`와 출제/검토 `EVIDENCE_CONTEXT`를 지원한다.
새 preset 발행·권한 확대는 하지 않았다.

기존 creative producer를 지원된 SIGINT drain으로 종료하고 worker/command/HWPX/chat/
native QUERY가 모두 비었음을 확인했다. 설치 후 Pack19를 활성화하고 API/Catalog →
채팅 worker → 채팅 owner → QUERY → Web 순서로 재개했다. 네 runner와 creative producer,
자료 학습, HWPX 서비스를 포함한 대상 서비스가 active임을 확인했다.

## 검증 근거와 한계

- 이전 source 검증: 출제/API/evidence/변형 269 PASS, Web·browser 부분 101 PASS,
  교과서 context·대화 RAG·자료 검토 129 PASS, disposable PostgreSQL plan 12 PASS.
  서로 다른 부분집합으로 합산하지 않는다.
- 배포 패키지 검사에서 OpenAPI 불일치를 발견해 공식 exporter로 갱신했다.
  OpenAPI 7 PASS 후 API build-only/설치 시뮬레이션을 다시 통과했다.
- 운영 API/platform/contracts wheel의 실제 설치 member 2,871개를 원 wheel과 대조했다.
- HTTPS `app.js`, `index.html`, `guide-content.js`가 새 Web wheel과 byte 단위로 일치했다.
  일반 모드 checkbox 부재 및 필수 grounding 요청 설정도 확인했다.
- HTTPS에서 내려받은 실제 renderer에 기존 회귀 harness를 적용했다. V2/V3 해설
  1회 출력, V1 유지, 문항 간 화면 전환, DTO 불변 모두 PASS다.
- API READY·HTTPS login 접근, Pack/preset 공식 조회, 서비스 listener 확인 PASS.
  신규 사용자 인증·문항 생성·GPU 실행은 하지 않았으며, 건강검사를 새 문항의
  과학적 품질이나 사람의 브라우저 사용 확인으로 대체하지 않는다.
- 배포 전 INDEX 서비스가 이미 failed/PID0이었다. 동일 상태·설정·identity를 보존했으며,
  이번 출제 배포가 임베딩을 복구하거나 새로 중단했다는 뜻은 아니다.

보호된 운영 증거·이전 설정·wheel 포인터·Pack activation은
`/var/lib/eom-mandatory-grounding-release-20261111`에 있다. 복구가 필요하면 기존
호환 release set과 `pack-before.json`의 활성 포인터를 함께 복구해야 한다.
기존 Item·Artifact·실패 이력·Graph·임베딩을 삭제하거나 고쳐 복구하지 않는다.

설계: [콘텐츠팀 원문과 출제 연동 지침](../architecture/CONTENT_TEAM_AUTHORING_PROMPT_V5_DESIGN.md).

## 후속 장애 수정 및 공통 HWPX 재검토 — 2026-11-12 02:48 UTC

사용자가 제시한 `hwpxbuild_b5c9fe156ad74c6c8192663901785c3f`와 교육과정 목록
`APPLICATION_API_UNAVAILABLE`를 별도로 조사했다. HWPX 실패는 위 배포 이전의 실행이다.

### 원인과 수정 범위

- HWPX: 정본에 구분된 탐구·발문을 다시 자유문장 파서에 넣으면서, 파서가 모르는
  마지막 질문이 탐구 결과 안에 남아 출력기가 거부했다. 전체/부분 인식 문구·줄바꿈·
  본문 안의 `①`도 같은 재파싱 경계를 깨뜨리는 것을 재현했다.
- 공통 `QuestionData` 투영으로 이미 검증된 필드를 직접 전달하도록 변경했다.
  문구별 발문 복구 함수는 제거했다. 단일·whole-exam·curated는 같은 경로를 사용한다.
- 템플릿의 중복 번호와 직접 선택형의 빈 보기 틀을 정확한 native 구조 검증 후 제거한다.
  curated에 따로 있던 번호 보정을 공통 경계로 모았다. 실제 내용이 있으면 삭제하지 않는다.
- 탐구 내부표가 정상 생성돼도 Manager가 미연결 표로 거부하고 Markdown 구분자를
  일반 글로 찾던 후속 오류도 재현·수정했다. 표의 값·차원·정렬·순서와 주변 줄글 순서를
  독립 검증한다. 기존 visual ordinal/receipt schema와 정본 inquiry hash 의미는 유지한다.
- 탐구 내부표의 좌/우/중앙 정렬도 기존 Builder 정렬 처리에서 동일하게 적용한다.
- 교육과정: 초기 schema registry를 동시 조회가 각각 생성하는 cold-start 경합을 재현했다.
  첫 병렬 조회는 약5.69초, 운영의 초기 GET도5.924초로 Web의5초 제한을 넘었다.
  기존 불변 리소스 검증을 API lifespan에서 한 번 완료한 뒤 readiness를 열도록 했다.
  제시된 정확한 `webreq_0237269a0ed8e543fbfdb0c8`를 Web journal과 직접 연결한 증거는
  없으며, 재현된 공통 초기화 문제를 수정한 것이다. 권한·timeout·hash 검증은 완화하지 않았다.

### 검증·실제 설치

- 구현 commit `a0c523c0` 및 공통 보강 `c0dafbe381e7d836a951c01d432250264fc72668`.
- HWPX 공통·수식·Markdown·handoff·단일·시험지·혼합 합본·독립 검증192 PASS.
  직접 선택형 추가 경계검사는 해당 신규 suite22 PASS로 별도 확인했다(중복 합산 금지).
- API startup/교육과정/OpenAPI17 PASS. 해당 파일의 기존 production-candidate 테스트1건은
  새 필수 `usage_filter`를 fixture가 넘기지 않는 선행 불일치로 분리했다.
  무관한 파일의 기존 광역 mypy 오류도 통과로 숨기지 않았다. 변경 owner의 focused mypy,
  Ruff/format PASS; 문맥/의존 경계24 PASS. DB 상태기계/DDL 변경은 없다.
- 최종 API/platform/contracts/Catalog/runner와 HWPX Builder는 `c0dafbe3` 설치.
  Web은 이전 `d1328814` 유지. QUERY owner/controller/numerical, Pack1.20.19, INDEX·자료
  학습 설정과 보존 대상 identity는 그대로다. API installed RECORD2,871개 검증 PASS.
- API READY, HTTPS login200(0.234초), 대상 서비스 재개 및 QUERY listener 확인 PASS.
  건강검사를 실제 로그인 계정의 교육과정 화면 확인으로 확대 해석하지 않는다.
- 원 실패 문항의 정확한 입력을 새 진단 workspace에 복사하여 실제 고정 systemd 격리
  HWPX 실행기(eom-hwpx, NAS/repository 접근 불가)로 생성하고, 설치된 별도 Manager로
  검증했다. 둘 다 PASS. 3×5 native 표·발문1회·중복 번호 없음·빈 보기 없음 확인.
  출력 SHA는 `sha256:20c1e5fe32b37e96797926f6572646dc3707865380aee20fce2546dde89575ee`,
  acceptance SHA는 `sha256:b6de973304b7c69ed0f3c4ef14bb74e93d790cc6c01af057305405b262e5de18`.
- 이 진단은 새 application build/Artifact 등록이나 사용자 다운로드 성공이 아니다.
  사용자에게 같은 문항의 명시적 재제작을 요청했다. 기존 세 실패 build는 FAILED 그대로이며
  입력·실패 result bytes도 변경되지 않았다. 신규 모델 실행·문항 내용/팀장 프롬프트 수정 없음.

최종 protected release evidence는 `/var/lib/eom-hwpx-shared-release-20261112`,
Builder 설치 기록은 `/var/lib/eom-hwpx/deployments/c0dafbe381e7d836a951c01d432250264fc72668.json`.
앞서 준비했던 `/var/lib/eom-curriculum-startup-release-20261112`는 API 미활성 후보이며
최종 설치 증거와 구분한다. 이전 호환 wheel/config와 실패 산출물은 삭제하지 않았다.
공통 설계는 [handoff 경계 보강](../architecture/CONTENT_TEAM_HWP_QUESTION_EDITOR_HANDOFF_V1.md)을 본다.
