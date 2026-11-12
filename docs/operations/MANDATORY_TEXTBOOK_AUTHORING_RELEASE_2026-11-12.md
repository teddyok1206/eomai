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
