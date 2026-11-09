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

## 운영 반영

- 주 변경 commit `3c9e30d79a5e5a0d1c1b50c045c95c76076abf6c`, 모바일 동의란 정렬 후속
  `264d71d9affb6598c48a8ea881d531466884aeb1`. 두 commit 모두 main에 push.
- 최종 Web wheel SHA-256:
  `f6e99e2d99fff75bcb4f996bfe9069672a38f8508de238bd9a0a364cff3f4ee5`.
  non-editable 설치 시뮬레이션·실제 `eom-web` identity에서 62개 파일/RECORD 검증.
- 마지막 모바일 정렬은 관련 31 tests와 17화면/34 viewport 검사를 다시 통과.
- 이전 Web `9810efd6` 대비 runtime 변경은 static 파일 8개와 build metadata/RECORD뿐이다.
  Python BFF, API 계약·권한·세션 정책·DB·worker·검색 계산은 변경하지 않았다.
- 실제 HTTPS login 200, ready READY, 배포한 public assets와 wheel bytes 일치.
  실제 Chromium HTTPS 로그인 화면 PC/모바일 검사 및 anonymous session 401 확인.
  비밀번호 입력·실패 로그인·사용자 mutation은 수행하지 않았다.
- API/Catalog/QUERY/INDEX/creative/material/chat/HWPX의 PID와 InvocationID 보존.
  Web만 stop → 검증된 wheel 설치 → start 했으며 다른 서비스를 재시작하지 않았다.
- 보호된 배포/rollback 기록: `/var/lib/eom-gui-principles-release-20261108`,
  `/var/lib/eom-gui-principles-final-release-20261108`.

화면 interaction 검증은 합성 API 기반이며, 운영 로그인 뒤 개별 사용자 업무를 새로
실행했다는 의미는 아니다. UI 변경으로 실제 문항·검색·학습 작업을 생성하지 않았다.
기존 개인정보나 문항 본문이 없는 합성 화면과 로그인 화면만 검수/감사 자료로 남긴다.

최종 활성화: **2026-11-08 18:22:55 UTC**. NAS 감사 Artifact:
`artifact_5f691d3113514993bf5c64b3bd71de2a` /
`rev_614196429b5040e8ac6df7ea1074300e` — 21 members, 기존 Catalog→Orchestrator
commit owner로 저장하고 전 member hash/byte 재읽기 PASS. 해당 note의 hash는
`sha256:ff96e835acbedffbd56368fe3adc994f5a54ff4d030956e3e7be5b0319532073`이며
이 자기참조 감사 위치 문단을 덧붙이기 전의 기록이다.
첫 감사 스크립트의 선택적 Pillow import는 미설치 환경에서 멈췄고 저장 전이었다.
기존 PNG 감사 형식을 재사용해 다시 저장했으며, 의존성 추가나 운영 변경은 없었다.

## 2026-11-09 — 시각적 위계와 DB·Excel 여백 개선

기준 source `2ed6df53`. 위의 11월 8일 acceptance를 덮지 않는 후속 표현 개선이다.
설계 기준은 디자인 시스템 §10이며, 기존 API·권한·요청·정본·수치 계산은 그대로다.

- 상단 ID 열기를 native disclosure로 접고, 정상 상태 표시의 배경/테두리만 줄였다.
  경고·오류는 작은 화면에서도 숨기지 않는다. 메뉴 17개는 text label과 권한을 유지한
  로컬 SVG로 통일했다. 다운로드 icon/font/dependency는 없다.
- DB 필터·검색 footer를 정돈하여 결과를 먼저 볼 수 있게 했다. 선택형 조건·콘텐츠 사용
  필터·export·조회/배치/유사도 연결은 제거하지 않았다.
- Excel은 문항 내용 열을 우선하고 행 작업을 조회/편집 두 묶음으로 정돈했다.
  모든 작업과 40px 클릭 영역을 보존했다. 인쇄/출력 체크박스에 text input 폭이 적용되어
  회차 글자가 세로로 꺾이던 selector 충돌을 수정했다.
- 중간 화면 폭 검증에서 완성 문항·자료 검토·품질 평가·고객센터의 최소 grid 폭이
  가용 너비보다 큰 기존 문제를 찾아, 기존 반응형 규칙에서 한 열 전환 시점을 조정했다.
  문항의 원본 그림·출판 레이아웃은 변경하지 않았다.

검증:

- 전체 source-backed Web suite **489 PASS**, 실제 Chromium opt-in 포함.
- 18화면 × 1440/1360/1024/390px = **72개 배치 PASS**. 키보드 ID 열기·접기·포커스,
  경고/오류 노출, 긴 문항 이름, 안내 모드, 기존 폼과 모바일 넘침 검증.
- DB 합성 fixture의 필터 form 높이 236px(모바일 282px), 결과 시작 위치 571px
  (모바일 602px). 실제 데이터/필터 상태에 따라 높이는 달라진다.
- Excel 1,200문항·동일 요청 재전송·복사·교체·계정 변경 응답 처리 회귀 유지.
  20개 인쇄/출력 회차와 긴 label, 1440px 문항 열/행 작업 크기 검증.
- Ruff lint/format, Python test mypy, 변경 JS의 module syntax, diff 검사 PASS.
- 최초 전체 검사 3건 실패: 기존 guide/request fixture에 Excel CSS가 누락된 2건과
  Map의 옛 문자 icon 기대값 1건. 실제 CSS 자산을 제공하고 SVG/접근성 이름 검사로
  갱신한 뒤 전체 suite 재실행 PASS. 오류 무시나 상품 검증 완화는 하지 않았다.
- 기존 Starlette/httpx deprecation warning 1건은 유지했다. 최초 Node 검사는 ES module을
  CommonJS로 해석한 invocation 오류였으며 module mode로 다시 검사했다.

운영 계획: 기존 Web `3af025f0`와 같은 BFF/계약을 유지하는 Web-only wheel 배포.
API `87a78e54`, QUERY, INDEX, creative worker는 설치·재시작하지 않는다.
이전 Web wheel SHA-256
`c4f7b7f69e69445ed3f6c1beaff01061db66aef7a2568a28d5729ffc8f3b30ea`를 확인했다.
Web 세션은 메모리 기반이므로 재시작 후 재로그인이 필요할 수 있다. 배포 결과는
아래에 별도 기록하며 소스/합성 브라우저 PASS를 운영 로그인 acceptance로 간주하지 않는다.

### 후속 운영 반영 결과

- 활성화: **2026-11-09 18:16:29 UTC**. source
  `098d7d5c684a12f29c0217e284daa98ae94d04b2`, Web wheel SHA-256
  `65e6613a96a71bb6fa78419c3152d922718ae4e3c3fbdad81acb410e10c82bfa`.
- wheel inventory/RECORD, 전용 Web interpreter import, non-editable 설치 시뮬레이션,
  실제 `eom-web` identity에서 **72개 package member 검증 PASS**.
- 기존 installer로 Web만 stop/install/start. 운영 변경 구간 18:16:26–18:16:29 UTC.
  Web PID `2639649` → `2857633`, 실제 live/ready 및 HTTPS 로그인 HTTP 200.
- API `2638304`, QUERY `2638500`, INDEX `2719114`, creative `2639715`의 PID와
  InvocationID 모두 보존. migration·정본·모델·GPU 실행 변경 없음.
- 실제 HTTPS에서 index/login/styles/Excel CSS·JS/app/기존 preset JS 7개가 wheel bytes와
  정확히 일치했다. anonymous session은 401, 실제 Chromium의 HTTPS 로그인 화면
  1440/390px 모두 정상이며 JS 오류/가로 넘침 없음.
- 보호된 실행/rollback 기록: `/var/lib/eom-gui-workbench-release-20261109`.
  rollback wheel은 보존했고 rollback은 실행하지 않았다.
- 개별 업무 interaction은 앞선 합성 API 브라우저 회귀로 검증했다. 배포 확인을 위해
  실제 사용자 문항·검색·편성·로그인을 생성하거나 기존 실패 이력을 바꾸지 않았다.
