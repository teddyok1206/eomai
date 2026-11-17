# KakaoTalk 질문의 선택적 교재 개념 추천

개발 탐색용이며 [설계](../architecture/KAKAO_QUESTION_STUDY_PACKET_DESIGN.md)와
[체크포인트](../operations/KAKAO_ARCHIVE_IMPLEMENTATION_CHECKPOINT.md)가 정본 설명이다.
수집·질문 구성·일반 PDF는 비AI다. 이 사용자 추가 요청만 유휴 공유 Codex 슬롯과 공식
GraphRAG로 PLAN→core 검색→COMPOSE를 수행한다. source 존재와 운영 활성화는 다르다.

## 현재 source owner

`kakao_concept_tasks.py`/`concept-task-store-v1`은 닫힌 공개 생성 DTO와 private intent,
작은 입력 준비 상태다. `PREPARED`는 **입력 준비**이지 모델 완료가 아니다. 사용자 요청에는
operator/session/slot/Graph policy/Work 입력을 받지 않는다. source pin과 실제 지시는
Artifact에 있고 DB에는 작은 scope/포인터·상태·원래 session ID(감사 provenance)만 있다.

`KakaoConceptTaskService`는 기존 question/source/Artifact owner를 사용해 exact 질문을
읽고, 요청/Graph scope를 한 번 예약하고 intent를 발행·채택한다. 같은 key는 원 task,
바뀐 본문은 conflict다. 재구성/재조회가 최신 Graph나 새 질문으로 원 요청을 바꾸지 않는다.
질문의 새 revision은 새 추천 요청이며, 기존 초안이나 원문을 자동 덮지 않는다.

`kakao_concept_publication.py`는 기존 역할별 source projection을 재사용해 학생/조교 text와
사진 occurrence를 분리한다. 사진은 원래 member pointer로 dedup하고 실제 media/hash/크기를
검사한다. request JSON만 Artifact로 발행하며 사진은 복사해 재보관하지 않는다. PLAN Work는
기존 exact request/member closure를 사용한다. 불가한 사진은 원래 상태를 남기고 만들어내지 않는다.

`KakaoConceptSourceAuthority`는 **수락된 task에서만** owner를 얻어 현재 계정/권한·binding/
room·원래 source closure·question/Work/Artifact를 재검사한다. background 의도는 원래 HTTP
session을 가장하지 않는다. 단순 로그아웃/HTTP 만료는 이미 수락한 exact 작업을 취소하거나
새 작업을 만들지 않는다. 계정 중지/권한 철회/source lifecycle은 차단한다. 공개 조회·다운로드는
여전히 실제 현재 API session을 요구한다. 원래 session ID는 변경하지 않는다.

`kakao_concept_workflow_submission.py`는 Catalog application composition에서 원래 public
`submit_kakao_concept_workflow`를 호출한다. Workflow/command/plan은 그 owner가 쓰고,
Catalog는 자기 phase의 workflow pointer만 한 번 채택한다. 별도 queue/step factory가 없다.
현행 Catalog runtime의 기존 public Workflow-use-case 권한을 재사용하고, 새 두 표에는
SELECT/INSERT와 intent pointer/phase link의 column-bounded UPDATE만 추가했다.

DB0094의 task와 (task,phase) row는 trigger/FK/unique로 identity·이미 채택한 입력을 보호한다.
긴 read/decode/발행은 transaction lock 밖이며 같은 key의 발행 후 중단은 원 Artifact로 복구한다.
phase에 저장한 Work는 작은 typed pointer이고 질문/worker result body가 아니다.
release context1.29는 exact0093→0094/동일 head만 허용한다. 옛 context/schema bytes는 보존한다.

## 아직 실제 운영으로 검증되지 않은 것

- 공개 API/화면 source는 아래와 같으며 아직 운영 배포·실제 모델 검증 전이다.
- 실제 preset/지침 발행·공유 슬롯 model run. 자동 continuation source는 아래와 같으며
  실제 운영 activation은 별도다.
- 실제 COMPOSE 완료 뒤 실제 교재 block/capture를 선택해 발행한 최종 사용자 PDF.
  공개 추천 선택·saved-study 저장/편집/PDF source 연결은 [설명 편집](kakao-study-editing.md)에 있다.
- 실제 카카오 occurrence 수락·전체 방 주기 수집과 마지막 실제 샘플 PDF.

실제 reader/page/crop/worker input/역할별 PDF는 [자료 출력 문맥](kakao-study-output.md)을 따른다.
worker를 직접 실행하거나 다른 support purpose로 fallback해 이 연결을 대신하지 않는다.

## 우선 확인할 검사

- `test_kakao_concept_tasks.py`: source schema/mirror·닫힌 요청·intent/source pin·상태.
- `test_kakao_concept_task_storage.py`: 공식 disposable PostgreSQL의 실제 question/source/
  Artifact→intent→PLAN 저장·동시 replay·중단 복구·서비스 재구성·학생/조교 사진 use·source
  authority·public 조회와 background 의도 구분. Workflow/command도 실제 저장하지만
  Graph scope와 실행 preset/plan port는 합성이다. 모델/운영 검증이라고 부르지 않는다.
- 같은 파일의 migration roundtrip은 disposable DB의 rollback-only 별도 schema를 사용한다.
  비어 있을 때만 downgrade되며 main app history/head는 유지한다. 같은 DB에서 이 DDL
  검사와 다른 pytest process를 병렬 실행하지 않는다. 별도 unit/static 검사만 병렬 가능하다.
- `test_release_operator_migration_0094.py`/`test_catalog_runtime_privileges.py`: exact release
  admission과 column-bounded grants. source unit PASS는 운영 migration/배포 승인 증거가 아니다.

## 공유 슬롯 실행 경계

`concept-authorization-v1`은 exact Workflow/step/plan ID와 plan/Work hash만 받는다.
`kakao_concept_authorization.py`는 저장한 human owner·original/current request·definition·plan42·
accepted phase link를 대조한 뒤 기존 task authority로 현재 source를 재검사한다. Runner UID의
이 operation만 socket에 허용한다. API/채팅/worker나 caller-supplied actor는 사용할 수 없다.
Catalog의 기본 composition은 현재 출제 프리셋의 검증된 retrieval policy와 허용 corpus의
active Graph를 초기 요청에서 한 번 pin한다. scope provider가 없는 별도 source-only adapter는
여전히 새 task를 만들 수 없다. 가짜 scope/API session으로 source 읽기를 성립시키지 않는다.

`kakao_concept_catalog_client.py`는 그 작은 RPC와 Core 공개 Artifact reader를 조합한다.
`KakaoConceptExecutionContext`는 canonical request를 한 번 읽고 실제 E/page/quote를 검증한다.
Runner의 임시 미활성 guard는 이 adapter로 대체됐다. 기존 Orchestrator의 ordinary 공유
claim/lease·prepare/run·중단 결과 복구·replay·Artifact 발행을 사용하며 generic support 실행으로
fallback하지 않는다. 실행 전후/채택 직전 source를 재인가한다. 실제 provided E/page만 generation
schema에 허용하고, pure input-aware 검사는 결과에서도 다시 수행한다.
취소한 Workflow는 거부하며 단순 HTTP session 만료를 계정/원본 철회와 혼동하지 않는다.

Job DB에는 기존 role metadata header만 넣고 긴 개념 설명·인용/crop은 canonical Artifact에 둔다.
완료/실패 terminal replay는 재실행하지 않으며 current permission 철회도 우회하지 않는다.
pure Kakao result/request behavior는 해당 purpose에만 lazy load한다. root fixed helper는 이전
image-input 변경 그대로다. 이 source 연결을 실제 운영 activation/model 성공으로 해석하지 않는다.

`test_kakao_concept_execution.py`/`test_kakao_concept_authorization.py`는 synthetic worker/storage로
이 연결을 검사한다. 저장 integration의 actual-concept 검사는 기존 question/source·실제 plan/
공유 capacity·동시 동일 Job claim/lease·현재 account 철회까지 disposable DB에서 검사한다.
capability observation은 합성이며 actual Codex/systemd 실행은 없다.

## PLAN 결과를 교재와 연결해 다음 단계로 준비

`kakao_concept_phase_results.py`는 exact child의 완료 Workflow/step/Job/Artifact와 role 입력·
결과를 대조해 canonical result를 읽는다. 실패·진행 중·다른 purpose/Job을 완료본으로 쓰지 않는다.
`kakao_concept_composition.py`는 공식 reader의 교재/실제 PNG로 COMPOSE request를 만들고 기존
Artifact의 `request.json` + `knowledge.json`에 함께 발행한다. 후자는 작은 source/accepted/
normalized-text·Graph/policy·PLAN-result·원본 page pin이다. DB는 기존 phase Work pointer다.

Source 재인가는 그 sibling provenance와 실제 PLAN 결과·같은 질문/지시·분석 hash·page use·
Work 파일 집합을 대조하고, 공식 `restore`로 정확한 교재만 재확인한다. 새 검색/최신 교재로
대체하지 않는다. 긴 준비/PNG decode/발행은 phase adoption lock 밖이다. 종료된 phase 준비를
다시 읽거나 서비스 재구성해도 새 검색/원본·request 발행을 하지 않는다. original PNG가 없는
text-only source는 한계를 보존한다. 과목 범위가 다르면 연결되는 기초 개념까지만 제안한다.

accepted source authority가 실제 저장 owner를 보유하므로 HTTP 만료 뒤에도 `prepare_accepted_compose`
와 `submit_accepted_kakao_concept_phase`로 같은 요청을 이어간다. 가짜 ActorContext/session을
만들지 않으며 현재 owner/계정·권한·source 검사는 유지한다. 공개 조회는 실제 API session이다.

`test_kakao_concept_composition.py`의 Graph/Workflow port는 합성이다. 저장 integration의 phase-result
검사는 실제 Job/Artifact 결과→등록된 PNG→COMPOSE 저장/서비스 재구성·logout 뒤 동일 Workflow
제출을 검증하지만 PLAN 출력·Graph/교재 discovery는 합성이다. 모델/실제 교재 검색 성공은 아니다.

다음 운영 검증은 **실행 preset·공개 API→실제 COMPOSE→화면에서 선택·새 PDF**에
집중한다. 실제 CSV/사진 샘플의 관련 교과서 보강·최종 PDF 링크도 남아 있다. 새 queue/독립
Codex 프로세스를 만들지 않는다.

`kakao_concept_study.py`는 완료 COMPOSE 결과와 현재 재인가한 교재/원본 capture를 기존
`StudySupplement`로 변환한다. 설명·관련성·검증된 인용·원본 PNG/물리 페이지·조교 답변
확인 메모·한계를 구분하며 원래 답변을 바꾸지 않는다. 로컬 render image use는 deterministic
ID이고 실제 카카오 첨부/저장 revision이 아니다. 단순 decode로 품질 승인을 만들어내지 않아
새 capture는 `quality_accepted=false`다. 실제 DRAFT PDF는 가능하나 FINAL 검사 규칙은 유지한다.

이 projection은 [공개 저장·편집/PDF](kakao-study-editing.md)의 입력 adapter로 연결됐으나 실제
모델/교재 실증을 대신하지 않는다. `test_kakao_concept_study.py`는 합성 개념/교재의 실제 PNG→crop→
PDF 내장·출처·질문/답변/개념 순서와 layout receipt를 검사한다. 실제 카카오/교재/모델 성공이나
사용자에게 전달할 최종 샘플이라고 보고하지 않는다.

## 학생별 편집본 저장 owner

`kakao_study_service.py`/`study-store-v1`은 exact packet/student와 선택한 질문별 task 결과에
사용자 block/capture 선택·제목/설명 수정·직접 쓴 메모를 붙인다. 모델 결과/질문·사진은 복사하지
않고 manifest Artifact에 결과 pin과 편집 값만 둔다. DB0095의 head/revision/command는 작은
pointer와 CAS/replay 상태다. 같은 key/body는 원 revision, 새 수정은 immutable revision이다.

기존 packet/concept/Artifact public owner로 현재 권한·exact source/result를 재확인하며 다른
학생/packet·없는 block/capture·바뀐 source를 거부한다. 긴 I/O/발행은 lock 밖이고 짧은 채택만
parent CAS다. 같은 발행 뒤 중단·동시 replay/편집·서비스 재구성을 검사한다. 세 표에는 binary/
JSON body를 두지 않는다. source test의 completed-concept port는 합성이고 actual slot은 아니다.

Delivery composition이 같은 packet/source owner로 study service를 구성한다. 추천 runtime이
없어도 직접 쓴 메모 저장은 가능하고 모델이 필요한 선택만 명시 거부한다. 공개 RPC/API·Studio
편집 source는 [설명 편집](kakao-study-editing.md)이다. release context1.30은 target0095와
정확한0093→0095 또는0094→0095/같은0095만 지원하며 predecessor bytes는 보존한다.
운영 migration/배포는 아직 수행하지 않았다.

`kakao_study_export.py`의 새 작은 source pin/wrapper는 기존 export family2를 재사용한다.
`KakaoExportService.request_study_export`가 study owner에서 packet/student를 해석하고 기존
build/alias/claim을 쓴다. DB0096의 optional immutable `kakao_export_studies`만 source pin을
연결한다. 현재 source의 read/실행 전후/발행/다운로드는 exact study와 교재를 재인가하고,
기존 일반 PDF body/schema bytes와 완료/실패 history는 바꾸지 않는다.

`kakao_study_pdf_inputs.py`는 저장한 block/capture 순서·제목/설명 수정·직접 쓴 메모만 기존
PDF 입력에 붙인다. 인용/그림·원본 질문/답변·시각은 수정하지 않는다. 임시 원본 page/전체
crop은 private temp에서 준비하고 선택한 고유 PNG만 최종 입력에 stage한다. byte budget은
누적으로 제한하며 같은 PNG는 질문별 use만 구분한다. 완료 replay는 준비/모델/렌더가 없다.

`test_kakao_study_export_storage.py`는 임시 DB의 저장본→실제 same-user child PDF→Artifact→
재조회/다운로드·단일 claim·현재 source 거절/이력 보존·학생 혼입 거부를 검사한다. 그림 경로도
실제 PNG/crop/PDF로 검사하지만 completed-concept/교재 byte reader는 합성 port다. protected
UID/systemd·실제 카카오·실제 모델/교재 성공으로 보고하지 않는다. 공개 API/Studio의 저장·출력
source는 [설명 편집](kakao-study-editing.md)이며 실제 샘플·운영 배포는 후속이다.
context1.31은 target0096 및 명시적0093/94/95에서만
전환/동일 head 확인을 지원한다. GPU/기존 슬롯·운영 DB에는 이 source 검사로 영향을 주지 않는다.

## 완료 PLAN의 자동 continuation — source 연결, 기본 비활성

`start_kakao_concept_task`는 실제 API actor의 intent→PLAN 입력 준비→기존 공개 Workflow
제출을 한 use case로 연결한다. 같은 POST/key는 같은 phase/Workflow/command다. 제출한
PLAN replay는 원 preset을 읽고 current로 대체하지 않는다. 공통 `validated_preset`을 재사용한다.
새 source-owned plan은 공통 resolver의 `read_current_execution_preset`으로 읽은 released
revision을 pin한다. Catalog에는 preset UPDATE 권한을 주지 않으며 기존 관리자/다른 실행의
`lock_current_execution_preset`은 원 잠금을 유지한다. source read와 설정 변경을 하나의
atomic transaction으로 직렬화하는 기능은 아니다.

`KakaoConceptCoordinator`는 완료 PLAN과 아직 미제출인 COMPOSE의 작은 candidate를 읽는다.
한 tick은 한 task이며 process-local cursor/tick lock은 영속 queue/실행 승인/실패 상태가 아니다.
실제 next-phase 단일 제출은 기존 unique phase·Artifact idempotency·Workflow/command owner다.
current owner/source를 재확인하고 검증된 PLANNED만 교재 reader→COMPOSE 준비·제출로 잇는다.
NEEDS_INPUT·실패/취소를 다음 모델이나 새 task로 재실행하지 않는다. 완료 자료도 바꾸지 않는다.

`EOM_KAKAO_CONCEPT_MODE=SHARED`가 명시된 composition만 별도 continuation thread를 만든다.
기본 DISABLED이며 잘못된 mode는 거부한다. 긴 교재 I/O가 API/Runner source authorization
socket을 막지 않는다. 종료/예외에서도 stopping event를 먼저 set하고 thread 종료를 기다린다.
설치/발행/모델 실행 성공은 source mode의 존재와 다르다.

두 phase 사이 current preset이 바뀌면 초기 구현은 원 pin과의 불일치로 명시 거부한다.
기존 PLAN replay는 가능하지만 새 COMPOSE가 최신 설정을 묵시 채택하지 않는다. 실행 중
preset 변경을 자유롭게 흡수하는 기능으로 보고하지 않는다. 일반 collection AUTO와 별개다.

## 공개 추천 시작·읽기·원본 페이지 — source 연결

새 `catalog-kakao-concept-v1`/`kakao_concept_rpc.py`는 API-peer 전용이다. 시작은 기존
`KakaoConceptCreate`와 같은 key/body로 위 use case를 호출하며 continuation이 비활성이면
새 작업을 받지 않는다. GET은 `kakao_concept_reads.py`의 작은 현재 권한 투영만 읽는다.
원본 입력·분석 전체/worker path를 응답에 넣지 않고 실제 Workflow 진행/실패·완료 pin,
설명/관련성·원문 인용과 분석 근거의 구분·실제 교재 page/crop 정보만 반환한다.

목록은 기존 owner/binding/task B-tree keyset이며 UUID 순서를 최신순으로 표시하지 않는다.
상세에서 원 source/교재를 재인가한다. 원본 PNG는 task+완료 capture page key만 받아
기존 Artifact FD/hash/media/크기를 검증해 별도 전달한다. 모든 crop을 재생성하지 않는다.
API/BFF session·CSRF/no-store와 exact 응답 상관 검사를 사용한다. 일반 worker/chat UID는
공개 operation을 호출할 수 없다. 새 DB/queue/dependency는 없다.

`kakao-concept-picker.js`는 [설명 편집](kakao-study-editing.md)의 질문별 추천/이전 작업/
진행·이미지 선택을 담당한다. 선택 전 기존 메모/원문을 바꾸지 않는다. 새 화면/학생/권한
전환은 timer/late response를 폐기하고, 불확실한 POST는 원 key/body를 재확인한다.

실제 COMPOSE 저장 검사에서 normalized 소수 좌표가 메시지 serializer에 거부됨을 발견했다.
`stage_kakao_concept_artifact`가 pure finite-number JSON을 명시적 `stage_serialized_artifact`
입구로 전달한다. bytes canonical/identity 검사 후 공통 staging/commit을 재사용한다.
메시지/control/manifest의 기존 integer-only 규칙은 바꾸지 않는다. 이 family의 canonical
결과 재조회/공개 응답도 finite-number encoding을 사용하며 DB는 작은 header만 저장한다.

`test_kakao_concept_http.py`는 실제 BFF→API→UDS→disposable DB·Artifact의 원 POST replay,
GET 무실행·완료 COMPOSE 설명/원본 PNG 재조회·unknown page 거부를 확인한다. Worker 출력과
교재 discovery는 합성이며 모델/운영 성공은 아니다. `test_kakao_concept_rpc.py`,
`test_kakao_concept_gateway.py`, `test_kakao_concept_artifact.py`와 Chromium 편집 검사가
상관·권한 입력 거부·소수 Artifact/정수 메시지 구분·선택/메모 보존을 보강한다.

`test_kakao_concept_continuation.py`와 storage의 continuation 검사는 실제 intent/Job 결과/
Artifact·교재 PNG→COMPOSE Workflow/command, logout/서비스 재구성·두 coordinator 경쟁과
current preset 변경·원래 실행 replay/계정 중지·index-capable bounded query를 확인한다.
교재 discovery/PLAN 내용은 합성이고 모델/운영 성공이 아니다. guarded DB는 이전 합성 이력을
유지하므로 새 fixture의 query만 범위 제한하며 실제 source/adoption/claim은 우회하지 않는다.
