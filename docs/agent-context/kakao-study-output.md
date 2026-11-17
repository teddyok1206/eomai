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

새 schema/DTO/projection은 아직 고정 worker entry·export profile·API/Web에 활성 연결한
상태가 아니다. 이를 새 PDF 완성이나 실제 카카오 자동 수집 성공으로 보고하지 않는다.
source의 source/합성 검증과 protected renderer·실제 계정 end-to-end 증거를 구분한다.

## 확인할 검사

- `test_kakao_study_render_contract.py`: 원 schema bytes 보존, 역할/시각·source closure,
  보강 revision/citation, member dedup/collision, result family와 no-network schema resolution.
- `test_kakao_study_projection.py`: 학생/조교 사진 분리, 같은 binary의 독립 use,
  exact 원문/시각·학생 격리·reply 선택·없는/잘못된 source/media pin.
- 기존 `test_kakao_render_projection.py`/`test_kakao_question_render.py`: v1 의미·출력 회귀.
- `test_kakao_stored_student_pdf.py`: 공식 guarded 임시 DB의 저장/재구성된 학생 subset을
  새 projection으로 읽으며, 이미 고정한 v1 입력을 덮지 않는지 확인한다.

샘플 제작용 staging 프로그램·수동 행 선택·사진 내용 대조는 운영 파이프라인이 아니다.
원격 로그인/selector/사진 occurrence 미확정은 정직하게 남기고 코드 상수나 model 추정으로
채우지 않는다. 다음 출력 구현도 기존 renderer/executor/publication owner를 확장한다.
