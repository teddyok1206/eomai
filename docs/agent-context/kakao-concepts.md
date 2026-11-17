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

## 아직 실제로 연결되지 않은 것

- 현재 Graph scope 선택/PLAN 실행 제어를 제공하는 공개 API·화면 composition.
- Runner↔Catalog의 현재 source 검사를 전달하는 small authorization RPC와 실행 context.
  그래서 `PlatformRoleJobExecutor`의 미활성 거부를 아직 제거하지 않는다.
- 실제 preset/지침 발행·공유 슬롯 model run, PLAN→GraphRAG→COMPOSE 진행 coordinator.
- COMPOSE provenance/원본 page·capture 발행, saved-study 저장·Studio 편집/새 PDF 연결.
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

다음 구현은 **small source-authorization RPC→기존 Runner/Orchestrator 실제 실행**에 집중한다.
새 source owner·queue·독립 Codex 프로세스를 더 만들지 않는다.
