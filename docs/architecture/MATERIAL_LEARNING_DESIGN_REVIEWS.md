# 통합 자료 학습 설계 검토

대상: [통합 업로드 설계](MATERIAL_LEARNING_UPLOAD_PIPELINE.md).
사용자 요청에 따라 초안 이후 구현 전에 **두 차례** 검토한다.
검토는 실제 현재 코드와 비교하며, 다른 에이전트나 외부 검토자가 수행했다고 주장하지 않는다.

## 1차 검토 입력과 출처 의미

2026-11-05 UTC. D0 검토. 범위는 입력 형식, 지식/문항의 분리, 그림, 해설 대응,
권리와 문항 출처다. 아래 결정을 D1에 반영한 뒤 2차 검토를 진행한다.

| 발견 | 코드 근거 | 설계 반영 |
| --- | --- | --- |
| REFERENCE_BOOK 계약이 있다고 등록이 가능한 것은 아님 | EducationalDocumentService `_validate_request`는 TEXTBOOK만 허용 | 기존 교과서 요청을 변조하지 않고 문서 owner의 additive 등록 경로를 사용 |
| 교과서 권리 확인은 구매·협상 기반으로 고정 | educational-document-rights-attestation/1.0의 basis/permitted uses | 사용자 업로드를 그 사실로 간주하지 않음. 내부 처리 권한의 실제 actor/source-bound 확인을 별도 successor로 표현하고 withdrawal을 유지 |
| 기존 창작 입력은 Notion·5자리 번호·교정 차수에 결합 | ExternalItemLearningSource | 가짜 엑셀 행을 만들지 않음. 자료의 source/page/picture pointer를 받는 별도 입력 계약과 기존 Orchestrator 확장으로 연결 |
| 기출 추출 입력은 회차·검토된 bundle에 결합 | LegacyItemExtractionRequest와 AssessmentSourceBundleRevision | 사설 시험지/문제집에 가짜 회차를 발급하지 않음. canonical Item/출처 규칙과 추출 검증을 재사용 |
| 일반 Item은 객관식·서답형을 이미 지원 | assessment_item.py | 자료의 원래 선택지 수/서답형 보존. 출제용 5지선다와 content-team 고정 profile로 변환하지 않음 |
| 번호는 문제집 안에서도 반복됨 | legacy/external contract의 item_number는 단일 범위 번호 | material revision + source role + section/locator로 stable unit key. 5자리 고유번호를 임의로 창작하지 않음 |
| 같은 페이지에 설명과 문제가 공존 | 기존 document source는 물리 페이지 범위 | 페이지의 중복 evidence 사용은 허용하되 Item 정본은 단위별 한 개. 설명을 얻으려고 페이지의 문제/그림을 잘라 없애지 않음 |
| 별도/책 끝 해설은 번호만으로 매칭할 수 없음 | paired review의 source-role/page 보존과 원본 region 규칙 | source role·장/범위·관찰 anchor로 index한 대응 후보를 검증. 불명확한 대응은 기록하고 독립 문제 처리는 계속 |
| 한글 내장 binary와 본문 사용 개체는 다름 | office_picture_use_extraction/publication | viewport/회전/주변 label과 실제 picture use 선택. 참고 영역의 한 사용 때문에 본문 공유 member를 삭제하지 않음 |
| 기존 참고서 source-class는 INTERNAL_GUIDE | knowledge_analysis_sources.py의 document kind mapping | 이름만 TEXTBOOK으로 위장하지 않음. 해당 class와 실제 문서 종류를 유지하고 released retrieval policy 범위를 명시 |

### 1차 확정 사항

- 원본/파생 PDF·페이지·Office picture catalog는 자료마다 한 번 등록하고 모든 단위가
  pointer로 참조한다. 각 문항/단원마다 책 PDF를 새 Artifact로 복사하지 않는다.
- 발견 단계는 canonical content를 출판하지 않는다. 원문 위치·구성·문제/해설 연결 계획을
  반환하고, 기술 검증된 계획의 각 단위를 기존 엔진으로 실행한다.
- 원문 정답/해설이 없을 때 독립 풀이를 수행할 수 있지만 SOURCE_GIVEN과 MODEL_SOLVED를
  반드시 구분한다. 잘못 매칭한 해설이나 생성 풀이를 원문이라고 저장하지 않는다.
- 내용상 문제는 공개 풀이/관찰 경고로 보존한다. 기술적으로 읽거나 구조화할 수 없는
  단위는 명시적 예외이며 전체 책의 다른 단위와 분리한다.
- 일부 페이지에 설명과 문제가 함께 있다는 이유로 하나의 채널을 누락하지 않는다.
  지식은 원문 페이지의 개념/관계 증거, 문항은 별도 Item 구조로 연결한다.
- 공식 출제 기관/회차를 확인한 경우만 PAST_EXAM으로 등록한다. 사설·교재 수록 문항은
  외부 창작이고 시스템 AI 생성 문항과 구분한다. 확인되지 않은 source claims는 관찰값이다.

1차 판정: **D1 반영 후 2차 검토 진행 가능**. 실행 계약/worker 코드 구현은 아직 시작하지 않음.

## 2차 검토 실행과 복구

2026-11-05 UTC. D1을 실행·복구 및 유지보수 관점에서 다시 검토했다.
실행 테스트 결과가 아니라 현행 구현을 대조한 설계 검토다.

| 발견 | 코드 근거 | D2 결정 |
| --- | --- | --- |
| 일반 page bundle을 기존 문서 source V4에 넣을 수 없음 | V4는 textbook bundle 2.0과 rights 1.0 schema/member를 고정 | 문서 owner의 일반 등록과 source successor를 추가. 기존 교과서 source의 의미는 보존 |
| 6개 슬롯 설정과 동시 실행 수는 다름 | WorkerCapacityPolicyV6의 max_active_codex/knowledge_analysis=4, ControlService global held count | 신규 학습은 max 1이며 전체 4를 공유. 기존 작업을 끊거나 5번째 실행을 우회 허용하지 않음 |
| Office review intake는 자료 원본 보존까지 이미 지원 | ingest(durable_source=True), 실제 형식 검사·bounded converter | 검토 Workflow를 시작하지 않고 이 owner의 준비 기능을 재사용. 별도 Office converter를 만들지 않음 |
| 새 자료 Item이 현재 DB 창작 목록에 자동 표시되지 않음 | creative_list의 notion-integrated-science namespace와 32개 원본 열 | 일반 자료 Item용 additive projection을 기존 창작 목록에 결합. 가짜 Notion row와 AI 분류 금지 |
| 원본 문서 derivation 모델은 이미 있음 | ItemOriginDerivation.DOCUMENT_REVISION | 기존 출처 계약 재사용. 동일 의미의 새 provenance framework 불필요 |
| 문서와 문항은 다른 Graph 진입 경로 | 공통 publication은 accepted analysis 집합; automatic Item publisher는 Item source만 허용 | 각 기존 owner로 진입하고 같은 공통 snapshot으로 합침. 별도 교재 Graph를 만들지 않음 |
| Registry replay는 key를 먼저 조회함 | RegistryService.register의 replay path | key뿐 아니라 unit/source/result hash도 학습 owner가 대조. 같은 key의 다른 내용은 충돌 |
| Graph 현재 revision은 창작 등록 중 바뀔 수 있음 | 공통 writer의 expected-current CAS | 충돌 시 최신 부모를 명시적으로 다시 읽어 publication만 retry. 모델 결과/Item은 보존 |
| 기존 AI model 출력과 후속 deterministic 장애는 다르게 복구해야 함 | Workflow terminal history, Artifact/Registry의 멱등 경계 | 학습 task attempt와 각 child pointer를 보존. 실패를 성공으로 바꾸거나 전체 책 재실행 금지 |
| API 교체는 QUERY service/provider pin에 영향 | 현재 Requires=eom-api와 provider 코드 hash 검증 | 기존 호환 릴리스 절차로 함께 갱신. INDEX 수치 환경/PID는 유지하고 실제 업로드 canary까지 검증 |

### 2차 확정 사항

- 작은 immutable 값은 typed value로 유지하고 자료·단위·child 실행만 pointer로 연결한다.
  전체 책/그림/result JSON을 DB나 여러 child에 반복 저장하지 않는다.
- 문항 대응은 section/역할/원문 locator를 key로 한 map과 sparse 후보로 구성한다.
  반복 번호를 전역 key로 쓰거나 모든 문항×모든 해설을 무조건 비교하지 않는다.
- source/current lifecycle과 실제 사용자 권한은 제출·해결·공개 조회 경계에서 확인한다.
  브라우저 세션을 장기 프로세스의 실행 자격으로 복제하지 않는다.
- 문항 등록/풀이/Graph/임베딩 상태를 따로 표시한다. 모든 페이지 coverage와 모든 단위의
  처리/예외를 집계해야 완료이며 단순 worker terminal success를 전체 완료로 오해하지 않는다.
- 1차/2차는 같은 주 에이전트가 다른 관점에서 수행한 코드 대조 검토다. 별도 외부 검수나
  사용자 교육 품질 검토를 완료했다고 주장하지 않는다.

2차 판정: **D2 반영, schema-first 구현 착수 가능**. 운영 완료 판정은 실제 배포와
제한된 업로드 흐름이 성공한 후에만 한다. 현재 단계는 설계 완료이지 기능 완료가 아니다.
