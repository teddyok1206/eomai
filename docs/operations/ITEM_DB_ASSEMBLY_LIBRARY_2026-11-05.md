# 문항 DB 조립·선택형 필터 개선 체크포인트

2026-11-05 UTC. 조립 제목/목록 삭제/세 열 편집/선택형 필터의 구현과 검증 기록이다.
이 문단 작성 시 운영 활성화는 아직 전이다. 실제 설치와 사용자 확인은 아래에 후속 기록한다.

## 범위와 보존

- 저장 버튼 옆 제목 입력, 최근 저장본에 제목·시각·문항 수 표시. 제목 없는 기존 저장본도 유지.
- 삭제는 실제 소유자의 목록에서 제외하는 application 명령이다. 정본 문항, immutable 조립
  revision/placement, 기존·진행 중 HWPX는 보존한다. 삭제 재전송은 같은 key/revision/hash를 쓴다.
- 초안은 번호/문항 카드/편집의 세 열 표다. 위·아래·빼기·교체는 카드 밖 동작 열에 있다.
  교체는 조회에서 고른 문항을 원 pointer 위치에 넣고 저장본을 제자리 수정하지 않는다.
- 단원·분야·분류·학년·출제자 등 categorical14항목은 현재 실제 값을 선택한다. 원 Excel에는
  Notion 속성 타입 선언이 없으므로 타입을 복원했다고 주장하지 않는다. 줄글·수치 검색과
  직접 입력, 모든/하나 이상 조건 및 원문 복합 문자열은 보존한다.
- source, Graph, 풀이보고서, 공통 임베딩 형식과 HWPX renderer/합본/출제의도는 바꾸지 않는다.
  모델 호출·새 검색·GPU 인덱스 재생성은 없다.

## 설계와 책임

[기존 조립 설계](../architecture/CURATED_EDITABLE_HWPX_DELIVERY_PLAN.md)의 11항 설계를 따른다.
기존 Catalog application에 제목과 목록 노출 metadata만 추가했다. draft V2를 기존 V1 ordered
selection으로 정규화한다. frozen V1 manifest 및 이전 RPC/schema bytes는 보존한다.

migration `20261105_0073`은 논리 조립에 title/삭제 receipt, owner별 partial 최근 목록 index와
삭제 재전송 UNIQUE를 추가한다. accepted title/삭제 receipt는 trigger로 불변이다. rollback은
metadata가 없을 때만 DDL 왕복을 허용하며 실제 사용자 제목/삭제 이력을 버리는 downgrade는 거부한다.
운영 문제가 생기면 additive73 DDL을 남긴 채 이전 compatible package set으로 복구한다.

Web은 `item-db-assembly.js`로 초안/저장 목록/제작 버튼의 표시 책임을 분리했다.
API/BFF는 bounded typed 입력·소유자·CSRF·고정 pin을 전달하며 domain 규칙을 복제하지 않는다.
기존 projection의 선택지는 current source/COMPLETED import/namespace를 한 SQL DISTINCT/window
조회로 읽고 필드당 최대200개로 제한한다. 긴 원문 cell과 전체 문항/그림은 내려받지 않는다.
초과 또는 조회 실패 시 직접 입력은 사용할 수 있다. 새 dependency/queue/registry/cache는 없다.

release-operator1.20은 정확한72→73과 같은73검증만 추가한다. 이전1.19/72의 bytes·의미는 보존한다.

## 구현 검증

- JSON Schema2020-12/mirror/hash/폐쇄된 요청·응답, 정확한 버전·권한·멱등 key·title 포함 요청 hash.
- API/BFF·release successor·기존72/콜백 회귀131 PASS.
- Web/설치 파일 목록·V1 draft/manifest/resolution·의존 방향 회귀61 PASS.
- strict mypy 핵심14파일, ruff/formatter, wire audit PASS. 수들은 중복되므로 합산하지 않는다.
- actual Chromium에서 실제 저장소 HTML/CSS/controller와 합성 API를 연결해 제목 저장·재열기,
  세 열/모바일 overflow/교체/삭제 취소/삭제 응답 손실 후 같은 key재시도/선택형 조건을 확인했다.
  이는 실제 HTTPS 사용자 요청을 실행했다는 뜻은 아니다.
- guarded disposable PostgreSQL에서 migration 왕복, metadata composition, 동시 save/removal,
  소유자·철회·stale pin거부, 이력/원본 유지와 삭제 뒤 이미 접수된 delivery완료를 검사했다.
  최신 관련18 PASS, 보존 이력 때문에 빈 DB전용 왕복1 SKIP(최초 실행의 해당 검사와 공식
  migrate/downgrade/upgrade는 이미PASS). 운영 DB로 pytest를 돌리지 않았다.
- 기존 HWPX FIFO 회귀를 함께 실행할 때 새 library fixture가 REQUESTED build를 남긴 문제가
  확인됐다. fixture를 실제 application+renderer double로 끝내 독립 queue에 섞이지 않게 했다.
  운영 코드/실패 이력을 고쳐 통과시키지 않았다. 앞선 실패 로그는 보존했다.

## 실제 운영에서 남은 확인

호환 API/Catalog/Web wheel build·RECORD·실제 identity import와 보호된73 migration,
QUERY의 실제 API provider pin갱신 및 원 GPU INDEX/numerical/창작 inputs보존을 검증한 뒤 반영한다.
새 모델·문항 생성 없이 기존 문항으로 제목 저장/재열기/목록 삭제/선택형 검색을 확인한다.
완료 검색의 saved ranking 운영 수정은 앞서 별도로 배포했으며 재조회 실측은 독립 기록한다.
