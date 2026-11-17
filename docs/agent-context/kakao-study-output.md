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
`cli.py`는 exact schema family로 두 입력을 구분하며 모르는 family를 최신으로 추정하지 않는다.
원문 crop/삭제나 질문의 임의 다중 쪽 전환 대신 검토 상태를 반환한다.

`pdf_contracts.py`는 두 family의 작은 exact 해석 함수이며 실행/권한을 부여하지 않는다.
기존 `prepare_kakao_pdf_inputs`는 내부 typed layout policy로 두 projection을 고르되,
권한·고유 사진/폰트 읽기를 공유한다. 기본값은 v1이다. 기존 Orchestrator executor/launcher와
Catalog publisher도 두 family를 사용하고 원래의 claim/stopped proof·member closure·현재
권한을 유지한다. study의 쪽수는 전체 section receipt, v1은 기존1질문1쪽 규칙으로 검사한다.
동일 완료본의 복구·Artifact 발행 replay는 원래 파일만 재검증하며 worker를 재실행하지 않는다.

소스 backend와 별도 non-editable wheel은 연결됐지만, **운영의 저장 export profile·API/Web은
아직 새 family로 활성 연결하지 않았다**. 현재 v1 delivery의 현재-claim callback도 다른
family를 명시 거부한다. 실제 카카오 자동 수집/Studio PDF 성공으로 보고하지 않는다.
기존 v1 의미와 schema bytes, 실패/완료 기록은 유지한다. 다음은 같은 저장/공개 owner의
profile과 결과 계약을 새 family에 연결하고 실제 수신 source로 재생 PDF를 확인하는 것이다.

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
- `test_kakao_stored_student_pdf.py`: 공식 guarded 임시 DB의 저장/재구성된 학생 subset을
  새 projection으로 읽으며, 이미 고정한 v1 입력을 덮지 않는지 확인한다. 두 출력 profile의
  학생 격리·고유 사진1회 stage·역할별 사진 use/긴 답변과 실제 Artifact 재조회도 검사한다.

샘플 제작용 staging 프로그램·수동 행 선택·사진 내용 대조는 운영 파이프라인이 아니다.
원격 로그인/selector/사진 occurrence 미확정은 정직하게 남기고 코드 상수나 model 추정으로
채우지 않는다. 다음 출력 구현도 기존 renderer/executor/publication owner를 확장한다.
