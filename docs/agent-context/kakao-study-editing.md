# KakaoTalk 개념·설명 자료의 공개 저장과 PDF

개발용 길잡이다. [설계16절](../architecture/KAKAO_QUESTION_STUDY_PACKET_DESIGN.md#16-저장한-개념-자료의-공개-편집pdf-transport)과
[체크포인트](../operations/KAKAO_ARCHIVE_IMPLEMENTATION_CHECKPOINT.md)가 범위 설명이다.
현재 source에 연결됐으며 운영 활성화·실제 교과서/모델 성공을 뜻하지 않는다.

## 담당과 흐름

`kakao_delivery_rpc.py`의 새 `catalog-kakao-study-v1`은 기존 API-peer socket을 쓴다.
저장/수정·exact revision read·keyset 목록·PDF 요청/조회와 학생별 빈 편집 양식 읽기다.
기존 delivery1/2 및 study-store/export bytes를 바꾸지 않는다. 응답의 operation/request/
binding/student/packet/revision을 검사한다. 기존 UDS4MiB 한도를 넘으면 명시 실패한다.

API `routers/kakao_deliveries.py`는 기존 actor context/RBAC/If-Match/Idempotency-Key를
전달한다. BFF `kakao_delivery_routes.py`는 기존 cookie/CSRF와 같은 HTTP gateway를 쓴다.
Web의 `kakao_study_contracts.py`는 presentation DTO이며 source 해석이나 저장 규칙이 아니다.
`KakaoDeliveryApplication`은 기존 study/export owner만 호출한다. GET은 제작을 시작하지 않는다.

양식 읽기는 `packets.resolve_student`의 정확한 subset에서 순서대로 빈 edit를 만든다.
가짜 study ID/revision을 만들지 않는다. UI가 전체 질문을 다시 N+1 조회해 학생을 추측하지 않는다.
저장 read에는 편집 값만 있고 원래 질문/교재/model result body는 복제하지 않는다.

`kakao-study-editor.js`는 `kakao-publications.js`의 학생별 `개념·설명 편집`에서 열린다.
직접 쓴 메모와 이미 선택된 개념의 수정 설명을 저장하고, 저장본을 다시 열어 새 revision을
만든다. source 인용/crop/원문을 편집하지 않는다. 네트워크 실패 시 같은 key/body를 다시
확인하고, 경쟁 parent는 기존 저장본을 다시 열도록 한다. 채널/학생/owner/permission 변경은
타이머와 이전 응답을 폐기한다. 완료 PDF 재조회는 새 POST/모델/렌더를 하지 않는다.

PDF 파일은 새 다운로드 endpoint를 만들지 않고 기존 `/exports/{id}/file`에서 현재 권한과
source를 확인한다. 표시할 관련 개념의 실제 추천/선택·이미지 미리보기 UI는 후속이다.
모델 task ID를 사용자가 직접 입력하는 칸이나 임의 교재/경로 입력을 만들지 않는다.

## 검증과 남은 gate

- `test_kakao_study_delivery_rpc.py`: 닫힌 envelope/mirror/hash·기존 owner 호출·상관 오류 거부.
- `test_kakao_study_gateway.py`: API/Web 값 정렬·다른 학생/버전/source 응답 거부.
- `test_kakao_study_delivery_http.py`: 실제 BFF→API→UDS→disposable DB/Artifact→same-user
  child PDF→현재 권한 다운로드·수정/재조회/서비스 재구성·단일 렌더. 질문/메모는 합성이다.
- `kakao_study_editor_browser_checks.mjs`: 실제 Chromium의 편집·응답 유실 replay·새 revision·
  PDF 재조회·safe DOM·작은 화면·늦은 다른 학생 응답 폐기. 실제 Kakao/교재/모델이 아니다.
- 실제 추천 preset/자동 PLAN→COMPOSE·모델 완료본의 화면 선택/이미지·최종 실제 샘플·
  호환 운영 배포는 남아 있다. 일반 수집/질문 구성/PDF는 비AI 구조를 유지한다.
