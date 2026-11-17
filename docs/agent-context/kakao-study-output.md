# KakaoTalk 역할별 출력과 개념 보강

개발 탐색용이다. [설계](../architecture/KAKAO_QUESTION_STUDY_PACKET_DESIGN.md)와
[반복 자동화 점검](../architecture/KAKAO_ARCHIVE_REPEATABLE_OUTPUT_AUDIT.md)이 작업 경계다.
기존 수집·질문 구성·일반 PDF는 비AI이며, 사용자 요청의 선택적 개념 추천만 향후 공유
Codex/공식 GraphRAG를 사용한다. source와 실제 설치/활성화는 별도다.

## 현재 후속 경계

`worker-study-render-v1.schema.json`은 기존 `worker-question-render-v1` bytes를 바꾸지 않는
독립 family다. pure `study.py`/`study_validation.py`가 hash-pinned packaged resource와
in-memory registry로 predecessor의 member/참조 정의를 재사용한다. 원격 schema 조회는 없다.
공통 content/terminal file closure 규칙은 `render.py`에 한 번 두고 두 family가 호출한다.

`StudyRenderManifest`는 binding/packet/student/question subset, optional 저장 자료 revision과
학생/조교 content를 나눈다. text/image use는 원래 message occurrence에 연결한다.
metadata는 선택된 occurrence만 포함하며 role/kind/raw date/timezone/검증 UTC를 보존한다.
다른 학생·미선택 메시지·발신자 추정·현시각 대체는 허용하지 않는다. 일반 출력은 보강이
없을 수 있지만 보강 block이 있으면 저장한 study revision이 필수다.

`kakao_render_projection.resolve_kakao_render_selection`은 기존 exact packet/student/source
검증의 공통 owner다. 기존 v1과 `kakao_study_projection.project_kakao_student_study`가 같은
해석을 사용한다. 이미지 member/hash/quality/transform 해석도 같은 public 함수로 재사용한다.
새 projection은 임의 notes/citation 인자를 받지 않으며 저장한 원본 질문만 변환한다.
권한·Artifact I/O·발행은 호출하는 기존 application owner가 담당한다.

`worker-study-layout-v1`은 기존 page geometry와 공통 `check_page_layout`을 재사용한다.
`study_layout.build_study_sections`가 역할별 순서·기록 정보·보강 출처 표시의 순수 owner다.
`check_study_layout`은 원문 span 범위를 순차 소비해 누락/중복·다른 질문/학생 pin을 거부한다.

worker `study_pages.py`는 학생 사진/질문1쪽과11pt 답변/보강 흐름을 계획한다. `study_pdf.py`가
기존 `question_pdf`의 이미지 cache·PDF/PNG writer·glyph/readback·로컬 commit을 재사용한다.
`cli.py`와 운영 unit의 `fixed_render.py`는 같은 `parse_pdf_command`/`rendering.render_pdf`를
사용한다. exact schema family로 두 입력을 구분하며 모르는 family를 최신으로 추정하지 않는다.
고정 실행기는 attempt/로컬 request 검사를 유지하고 검토 거절도 terminal receipt로 남긴다.
원문 crop/삭제나 질문의 임의 다중 쪽 전환 대신 검토 상태를 반환한다.

`pdf_contracts.py`는 두 family의 작은 exact 해석 함수이며 실행/권한을 부여하지 않는다.
기존 `prepare_kakao_pdf_inputs`는 내부 typed layout policy로 두 projection을 고르되,
권한·고유 사진/폰트 읽기를 공유한다. 기본값은 v1이다. 기존 Orchestrator executor/launcher와
Catalog publisher도 두 family를 사용하고 원래의 claim/stopped proof·member closure·현재
권한을 유지한다. study의 쪽수는 전체 section receipt, v1은 기존1질문1쪽 규칙으로 검사한다.
동일 완료본의 복구·Artifact 발행 replay는 원래 파일만 재검증하며 worker를 재실행하지 않는다.

저장/공개 source는 `export-store-v2`/`catalog-kakao-delivery-v2`에서 study 응답만 추가한다.
원래 request와 v1 schema bytes는 그대로이며 같은 DTO가 두 명시적 tag를 읽는다. tag/profile/
layout 혼합은 실패한다. 기존 ExportService/Delivery가 원래 profile의 정확한 command family를
사용하고 실제 publication의 쪽수·layout SHA·family 증거로 채택한다. 과거 key replay는
당시 결과이고, 새 policy의 새 key는 다른 build다. 목록은 v1/v2를 함께 열 수 있다.
현재 public owner는 질문/답변만 지원하므로 저장되지 않은 non-null study revision bind는
막는다. 교재 보강을 지원하는 worker DTO만으로 저장/출처 authority를 부여하지 않는다.

새 policy는 기존 composition의 `EOM_KAKAO_PDF_LAYOUT_POLICY`에서 명시 선택하며 default는
v1이다. Web은 두 출력 형식을 읽고 새 자료의 답변 포함을 기본으로 제안한다. source의
API/UDS/임시 DB/worker/다운로드와 실제 브라우저 fixture 검증은 **운영 활성화나 실제 카카오
실증이 아니다**. 새 profile을 호환 release로 활성화한 뒤 실제 수신 자료를 재생해야 한다.
기존 v1 의미와 schema bytes, 실패/완료 기록은 유지한다.

## 확인할 검사

- `test_kakao_study_render_contract.py`: 원 schema bytes 보존, 역할/시각·source closure,
  보강 revision/citation, member dedup/collision, result family와 no-network schema resolution.
- `test_kakao_study_projection.py`: 학생/조교 사진 분리, 같은 binary의 독립 use,
  exact 원문/시각·학생 격리·reply 선택·없는/잘못된 source/media pin.
- 기존 `test_kakao_render_projection.py`/`test_kakao_question_render.py`: v1 의미·출력 회귀.
- `test_kakao_study_pdf.py`: 실제 한글 PDF, 학생/조교 사진 분리·같은 member 재사용,
  긴 답변의 CRLF/combining 원문 범위·11pt 흐름, 기록 정보/출처, 누락 사진·overflow,
  stale pin·위조 coverage·순서·입력/출력 경계와 CLI family 선택.
- `test_kakao_study_execution.py`: 실제 child process, exact family·위조 layout 거부,
  중단/권한 복구·완료본 재발행에서 동일 파일/단일 실행 유지.
- `test_kakao_study_export_contracts.py`: v1 bytes·v2 additive 응답, tag/profile/layout 정합,
  혼합 목록·Web DTO·상관된 기존 RPC, 명시적 policy/default/잘못된 activation 설정 거부.
- `test_kakao_export_storage.py`/`test_kakao_delivery_http.py`: 양쪽 profile의 동시 요청/claim,
  중단/재전송/실패 보존·재시작/권한 철회·실제 BFF 다운로드. 긴 답변은 실제 쪽수를 저장한다.
- `test_kakao_stored_student_pdf.py`: 공식 guarded 임시 DB의 저장/재구성된 학생 subset을
  새 projection으로 읽으며, 이미 고정한 v1 입력을 덮지 않는지 확인한다. 두 출력 profile의
  학생 격리·고유 사진1회 stage·역할별 사진 use/긴 답변과 실제 Artifact 재조회도 검사한다.

샘플 제작용 staging 프로그램·수동 행 선택·사진 내용 대조는 운영 파이프라인이 아니다.
원격 로그인/selector/사진 occurrence 미확정은 정직하게 남기고 코드 상수나 model 추정으로
채우지 않는다. 다음 출력 구현도 기존 renderer/executor/publication owner를 확장한다.
