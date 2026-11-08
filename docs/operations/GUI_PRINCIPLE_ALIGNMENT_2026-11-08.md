# Scientific Studio GUI 원칙 재점검

## 범위와 기준

기준 source: `5b96399c`. 사용자가 요청한 초기 원칙 재적용이며 제품 재설계가 아니다.
정본은 `docs/product/EOM_SCIENTIFIC_WORKBENCH_DESIGN_SYSTEM.md`, 표현 사전,
ADR 0170과 `docs/architecture/GUI_GUIDE_MODE.md`다.

화면의 상태·권한·API·정본·멱등 요청·GPU/슬롯 실행은 바꾸지 않는다. Web static
표현만 수정하고 Web wheel만 배포한다. 기존 서버 계약과 API 설치본은 유지한다.
접근 패턴은 DOM 스타일 적용과 작은 상태/안내 사전의 key lookup이다. 기존 CSS 토큰,
native controls/details, 사전과 안내 모듈을 재사용하며 DB·캐시·새 UI framework는 없다.

## 화면 전수 대조와 수정 범위

| 화면 | 확인한 원칙/차이 | 처리 |
| --- | --- | --- |
| 로그인·내 계정·관리자 계정 | 공통 입력 크기, 권한 분리, 비밀번호 경고 | 유지, 브라우저 회귀 |
| 작업함·새 문항 요청·제작 진행·완성 문항 | 콘텐츠 우선, ID 접기, 단일 요구 입력, 원본 미리보기 | 유지, 기존 회귀 |
| HWPX | ID 복구 경로·승인 경계·원본 문서 스타일 | 유지, 기존 회귀 |
| DB 조회·배치·유사도 | 작은 pill 필터 버튼, 별도 둥글기, 후속 안내 누락 | 40px/공통 토큰, 조립·검색 안내 보강; 5자리 번호 유지 |
| 자료 학습 | 공통 입력 스타일·panel 여백 누락, 미등록 CSS 토큰, 구현 용어 banner, 상태 번역 별도 사전 | 기존 입력/표 스타일·표현 사전 재사용, 기술 설명 접기 |
| Map | 검색 입력 기본 브라우저 스타일, 작은 pill 버튼, gradient·별도 detail class, 12px 상세 | 공통 입력/버튼/상세, 단색 배경·읽기 크기·안내 |
| ChatGPT | 자료 검색 입력 기본 스타일, 별도 색상/둥글기 | 공통 토큰; 대화 내용·Markdown·독립 scroll 유지 |
| 자료 검토 | 실제 보라색 주석과 ‘빨간 상자’ 설명 불일치 | 주석 위치 안내 수정; 빨간 교정 글자 설명은 유지 |
| 품질 평가 | 제목을 반복하는 상시 설명 | 반복 설명 제거, 안내 모드 설명 유지 |
| 슬롯·운영 데이터·학습 품질·고객센터 | 관리자 진단/경고/정확한 복구 ID 필요 | 유지, 화면/기존 회귀 |

공통 입력 기본값은 낮은 specificity의 `:where`로 적용한다. 체크박스·라디오·숨김
필드는 제외하며 검색 바·채팅 입력 같은 의도된 조합은 기존 component rule이 우선한다.
임의로 모든 테두리/문서 스타일을 일괄 변경하지 않는다. 상태 번역은 표현 사전에
추가하되 원본 enum 비교/요청은 그대로이며, 알 수 없는 값은 정상으로 표시하지 않는다.

## 검증과 운영

전체 Web 회귀와 실제 Chromium의 desktop/mobile 화면·키보드·안내 모드·안전한 텍스트
표현·숨김 상태를 검사한다. 합성 API를 쓰는 화면 테스트와 실제 HTTPS 설치 확인은
구분한다. 설치 wheel/RECORD/서비스 identity와 이전 Web rollback wheel을 확인한다.
Web 재시작으로 기존 브라우저 세션은 재로그인이 필요할 수 있다. 다른 service PID와
runtime pin을 보존한다. 완료 결과는 이 문서 아래에 덧붙인다.

## 소스 검증

- 전체 Web suite: **466 PASS**, 기존 Chromium opt-in 검사도 켜서 실행. 외부 서비스·모델 호출 없음.
- 추가 whole-shell 검사: 17화면 × 1440/390px, 총 34개 viewport 검사. 입력 높이/반경,
  체크박스 보존, 두 파일 입력 정렬, 안내 OFF/키보드/Escape/레이아웃 유지 검증.
- 합성 자료 학습 API로 기존 접수 재전송·원본 재업로드 방지·pause/resume·실패 successor·
  계정 변경의 늦은 응답 거부를 유지하고, 실제 공통 presenter의 미등록 상태 표시 검증.
- Map 범례가 selector 우선순위 때문에 모두 회색으로 보이던 문제를 관찰해, node/ring/범례가
  한 layer color 값을 사용하도록 수정. 색뿐 아니라 종류명/선택 상태도 유지한다.
- Ruff lint/format, release integrity와 신규 Python test의 mypy, context 13개 PASS.
- 기존 테스트 fixture 3곳의 drift(숨은 관리 subview, 축약 property 경계, 새 controller stub)
  수정. 테스트를 통과시키기 위해 운영 기능이나 검증 assertion을 없애지 않았다.
- Starlette의 기존 httpx deprecation warning 1건은 UI 범위 밖이므로 dependency 변경 없음.

표현 사전 schema는 optional `material_learning` domain만 추가했다. API/worker protocol과
영속 schema는 바뀌지 않는다. shared CSS 기본값을 추가하고 기존 component rule을 직접
수정했으며, 별도 theme override 파일이나 중복 스타일 계층을 만들지 않았다.
