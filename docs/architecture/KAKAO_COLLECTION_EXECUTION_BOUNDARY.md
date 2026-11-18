# KakaoTalk 수집 실행 계약

기준: `KAKAO_CHANNEL_ARCHIVE_STUDIO_IMPLEMENTATION_SPEC.md` §§4–6.
이 문서는 source 계약이며 실제 카카오 capability·로그인·운영 활성화 증거가 아니다.

## 실제 사진의 CSV occurrence 제안 — 2026-11-18

1. Catalog의 순수 정합 함수는 이미 검증해 읽은 두 MANUAL 수신물에서 단일 사진의 CSV
   row ordinal을 제안한다. 클릭·원본 수락·첨부 발행은 담당하지 않는다.
2. 정본은 기존 수신 reader가 확인한 CSV/사진 bytes와 각각의 관측 receipt이다.
3. 새 wire/DB 계약 없이 기존 receipt/정규화 pointer에 대한 내부 값만 반환한다.
4. 원 run/fence/page/profile, 각 capture, CSV hash와 byte 길이, 같은 문서 및 관측된
   단일 room identity를 대조한다. 현재 사용자 권한 확인은 호출 owner에 남는다.
5. DOM의 주 접근은 parent→메시지 group과 target path exact lookup, CSV의 주 접근은
   원래 row 순서에서 정확한 연속 부분열 검색이다. 원래 순서를 정렬하지 않는다.
6. DOM을 한 번 분류하고, 사진 전후의 연속 후보를 KMP로 양방향 검색한다. 같은 문장이
   반복돼도 row를 합치지 않는다. 전체 DOM/CSV 자료를 결과에 복제하지 않는다.
7. 시간은 관측 노드/CSV rows와 읽을 문자열 길이에 선형, 공간은 DOM과 검색 패턴 크기에
   선형이다. 현재 observation 노드2048, CSV100,000행 상한을 그대로 사용한다.
8. DB transaction이나 쓰기는 없다. 두 관측은 받은 같은 자료를 다시 읽어 재현한다.
9. Catalog 순수 함수→기존 수신 자료 값과 계약 방향이다. browser SDK/파일/권한은 읽지 않는다.
10. 앞뒤 정확한 텍스트가 서로 다르고, 양방향 통틀어 연속 패턴이 딱 한 곳이면
    `SEQUENCE_INFERRED`다. DOM truncation·더보기·혼합 text·앨범·다른 방·모호한 위치는
    추측하지 않는다. 시각·역할·원본 화질·방 전체 수집의 확인으로 확대하지 않는다.
11. `사진` 문자열, 파일명, timestamp 근접성이나 같은 방의 첫 row만으로 연결하면 반복
    메시지 또는 앨범에서 섞일 수 있다. 불확실하면 명시적 미확정이 더 단순하고 안전하다.

### 기존 수신물 owner에서 두 파일을 검증하는 경계

기존 `KakaoCaptureIntakeService`가 실제 operator의 binding/lease에 속한 CSV·사진 capture
두 ID만 선택해 검증한다. 새 API·DB model·권한·Artifact revision은 만들지 않는다. 정본은
기존 MANUAL lease, 실제 수신 receipt/관측, 보호된 두 payload다. 이름으로 쌍을 찾거나
정규화 revision을 꾸며내지 않는다. 기존 CSV parser의 공통 헤더/행 검증으로 raw ordinal을
읽되, 검증 전 단계에서 role·시간대·정본 ID를 할당하지 않는다. 기존 reader가 각 payload의
UID/GID/mode/hash/크기를 검사하고 같은 authorize를 파일 I/O 전후에 수행한다. reader는
receipt의 전송 상태와 actual payload를 대조하고, owner는 원래 lease 시간과 관측 종류도 확인한다.
고정 ID 두 건 lookup, 1회 payload/CSV 파싱, O(rows+bytes) 정합이고 별도 cache/queue는 없다.
파일 I/O 중 DB lock을 잡지 않으며 늦은 세션 철회나 lease 변경은 결과 전에 감지한다. 순수
검사는 제안 또는 미확정을 반환하고, 실패/입력 유실을 원본 수락 성공으로 바꾸지 않는다.
목록에서 최근 자료를 자동 결합하는 대안은 범위를 넘고 다른 방을 섞을 수 있어 선택하지 않는다.

Studio의 받은 자료에서 동일 연결·동일 로그인 회차의 CSV와 사진을 명시적으로 고른다.
기존 관리자 조회와 Catalog socket에 쓰기 없는 확인 경로만 추가한다. released 목록/방 확인
schema는 유지하고, 새 operation의 contract는 exact binding/lease/두 capture ID와
미확정 또는 행 번호만 전달한다. API/BFF는 응답의 두 ID와 binding/lease까지 반드시
대조한다. 목록은 여전히 payload를 읽지 않고 두 ID를 골랐을 때만 실제 읽는다.
응답은 no-store이고, 다른 선택/계정으로 이동한 뒤 도착한 결과를 표시하지 않는다.
현재 권한, 파일·parse 한도, 입력 오류 및 미확정의 의미는 위 owner 검사를 그대로 사용한다.
이 확인으로 원본을 새로 수집하거나 학생·질문을 저장하지 않는다.

## 실제 방 관측에서 확인한 수집 adapter 보완 — 2026-11-18

1. 책임은 기존 MANUAL download/읽기 전용 DOM adapter다. 새 수집 권한·클릭·로그인이나
   source 수락을 추가하지 않는다. 실제로 받은 CSV보다 화면의 loaded message 수가 작을 수
   있으므로 현재 DOM만으로 전체 이력을 수집했다고 선언하지 않는다.
2. 정본은 기존 원본 download/observation receipt다. 새 관측은 새 capture identity로 저장하고
   기존 UNAVAILABLE target이나 과거 source/질문/PDF는 재해석·수정하지 않는다.
3. 기존 observation1.0의 text는 관측한 text 조각이다. leaf element만 보던 구현을 direct text/
   BR node까지 읽도록 수정하되 기존 schema bytes·상한·편집/인증 subtree 제외를 유지한다.
4. 사진은 실제 같은 페이지의 GET→redirect→download event에서 확인한 최초 same-origin
   image endpoint path만 보완한다. 최종 signed CDN URL·query·header/cookie는 저장하지 않는다.
   URL만 있는 CDN download나 다른 페이지/만료/모호한 chain은 여전히 UNAVAILABLE다.
5. 주요 접근은 page/request identity lookup, redirect predecessor lookup와 최종 URL hash의
   일회성 correlation이다. SDK 이벤트의 실제 request 객체도 비교해 object-id 재사용을 막는다.
6. 기존 run-local owner 안에서 최대64건/60초의 OrderedDict와 URL-hash→request-key set을
   사용한다. source/profile/room registry나 persistent cache·queue는 만들지 않는다.
7. lookup은 평균 O(1), expiry/eviction은 amortized O(1), 모호한 match 정리는 O(k≤64)다.
   DOM direct-text 순회도 별도 전역8192 child-node 상한을 두고 큰 subtree를 반복 읽지 않는다.
8. 같은 asyncio event loop의 synchronous request/download callback에서 cache를 갱신·소비한다.
   DB transaction은 없고 worker는 기존 로컬 결과만 쓴다. close 후 새 요청은 저장하지 않는다.
9. collector SDK adapter→기존 pure contract 방향이다. 네트워크를 새로 호출하거나 공개 API가
   request path/authority를 주입하게 하지 않는다. 실제 원본 수락·현재 권한은 Catalog가 담당한다.
10. redirect method/origin/chain/page가 맞지 않거나 둘 이상이면 상관을 거부한다. metadata
    미확인을 사진 성공/원본 화질 증명으로 승격하지 않는다. 기존 download 실패/중복 event
    구분·원본 hash 검증과 16개 MANUAL 실행 상한은 유지한다.
11. filename·시간 근접성만으로 연결하는 대안은 다른 메시지 사진을 섞을 수 있다. raw signed
    URL 저장이나 외부 cookie 복사는 불필요하다. 이 보완 자체가 AUTO/전체 방 수집의 완료는 아니다.

## 기존 수락 owner의 운영 조립 — 2026-11-17

1. 책임은 Catalog composition에서 이미 구현한 collection attempt/source owner를 질문
   읽기·저장에 연결하는 것이다. 브라우저 시작·AUTO dispatch·공개 authority 입력은 추가하지 않는다.
2. 정본은 기존 accepted run/result/report/source Artifact와 현재 DB의 권한·실행 pin이다.
3. 기존 logical/revision/Artifact/hash 모델을 그대로 사용하며 새 wire·DB 변경은 없다.
4. 명시적인 `EOM_KAKAO_COLLECTION_ADAPTER_SHA256`와 기존 `EOM_KAKAO_PROFILE_ID`를
   검증한 경우에만 owner를 조립한다. browser driver hash를 adapter hash로 대신하지 않는다.
5. 주 접근은 설정 key lookup와 기존 attempt/source의 exact indexed lookup다.
6. 작은 environment mapping과 기존 owner/index를 재사용하며 새 cache·queue는 없다.
7. 설정 검사는 O(1), 실제 원본 검증 비용과 크기 상한은 기존 owner가 그대로 담당한다.
8. 구성 시 DB/파일/브라우저 변경은 없고 기존 publication·source CAS transaction을 유지한다.
9. runner→composition→application owner 방향이며 worker/OS 구현은 필요한 실행 경계에서만
   import한다. 질문·개념·편집은 같은 source/Artifact owner를 재사용한다.
10. 설정 key 미지정은 기존 admission-disabled 동작이다. 명시했지만 불완전/잘못된 pin이면
    구성 오류이며 조용히 다른 pin/권한으로 대체하지 않는다. 실제 accepted attempt·현재 권한은
    호출마다 검사하고 source order UNKNOWN은 여전히 질문 저장을 막는다.
11. 기존 무조건 거부 callback을 계속 쓰면 올바른 accepted result도 운영 질문 경로로
    연결할 수 없다. 허용 boolean이나 가짜 API session 대신 실제 owner를 명시적으로 주입한다.
    이 조립 자체는 AUTO·MANUAL source 수락이나 실제 카카오 검증의 완료 증거가 아니다.

## 호환 운영 릴리스 준비 — 2026-11-17

1. 책임은 기존 release operator의 exact migration callback·설치 검증이다. 수집/브라우저
   실행 권한이나 일반 shell 명령을 추가하지 않는다.
2. 정본은 검토한 source commit/tree/archive와 각 component wheel/RECORD, 실제 DB revision이다.
3. 기존 context/admission1.27 bytes는 보존하고0093용1.28 successor만 추가한다.
4. source/runtime fingerprint,4개 wheel의 identity/hash와 installed package parity를 재사용한다.
5. 주 접근은 고정 callback enum/map lookup와 정확한 predecessor/target revision 조회다.
6. 기존 immutable mapping과 배포 manifest를 사용하며 새 DB/queue/index는 없다.
7. metadata 조회는 O(1), package verification은 기존대로 전체 파일 byte 수에 선형이다.
8. 0087→0093만 명시적으로 허용하고 이미0093이면 no-op 재확인한다. 실제 설치 전 기존
   MANUAL/AUTO 실행·profile lock·변경 중 claim을 확인하고 기존 배포 절차의 정지/복구 경계를 따른다.
9. shell presentation → root-protected operator → 기존 migration/role bootstrap 순서를 유지한다.
10. 알 수 없는 DB revision·source/runtime 불일치는 중단한다. timeout이면 실제 revision과
    설치 상태부터 확인하며 무조건 재업그레이드/다운그레이드하지 않는다. 실패 이력은 보존한다.
11. 기존0087 context를 넓히는 대안은 과거 승인 의미를 바꾸므로 제외한다. 별도 배포 framework는
    필요 없다. 이 source 준비는 운영 migration/서비스 재시작이나 AUTO 활성화가 아니다.

## Studio 수신 자료 확인 — 2026-11-16

기존 owner의 `KakaoRoomIntakeService.confirm_room`을 공개 경계에 연결한다. GET은 현재
관리자의 선택 binding에 속한 최근8개 MANUAL lease의 로컬 receipt만 bounded하게 읽는다.
각 lease 최대1,000개 directory entry, 전체50개 항목 상한을 두고 잘린 목록은 명시한다.
이는 최근 수신물 선택 화면이지 전체 방 inventory·수집 완전성·본문 검증 증거가 아니다.
목록은 사진/CSV bytes를 읽지 않으며 각 항목에 원래 lease/capture ID와 시각·상태만 둔다.

외부 파일은 기존 Orchestrator 로컬 입력 adapter가 UID/GID/mode·종류/link·원래 fence/run
marker·receipt/관측 identity를 검사한다. 공개 응답에는 URL·provider key·인증정보·DOM
본문·파일 경로를 넣지 않는다. room path를 실제로 관측한 항목만 작은 preview hash를 준다.
확인 POST는 화면의 hash·binding version·사용자의 채널/방 확인을 받고 기존 private
confirmation을 서버에서 구성한다. hash는 권한 token이 아니며 실제 사용자 권한과 원래
lease를 다시 검사한다. 수락 시에만 실제 payload hash를 읽어 확인한다. 파일명이 room이나
메시지 identity가 되지 않는다. 실제 CSV/사진 source 수락·학생 연결·AUTO 활성화와 구분한다.

정본은 기존 room intake proof/observation Artifact와 admission receipt다. 새 DB/queue/cache는
추가하지 않으며 같은 key 완료 재조회는 canonical proof에서 원래 입력을 복원한다. local
workspace가 사라져도 완료 receipt를 새로 만들지 않는다. 미완료 확인은 현재 metadata를
다시 대조하며 준비 hash가 바뀌면 명시적으로 거부한다. 파일 I/O 동안 DB lock은 없다.

주요 접근은 기존 owner index로 범위를 제한한 binding의 recent lease 조회와 bounded
directory iteration, capture ID exact lookup다. 사용자 MANUAL 이력 M(일반적으로1,000 미만)의
top8 정렬은 O(M log8), lease8/capture50 metadata 읽기와 작은 O(n log n) 시각 정렬이다.
AUTO 주기 수집 이력 전체를 이 UI 조회로 스캔하지 않는다. 실측상 M이 커져 병목이면 현재
query plan을 보고 owner/binding/시각 composite index를 검토한다. payload 복사·원문 parse·
모델 실행은 없다. 기존 Catalog API-peer socket →
API → Studio BFF를 사용한다. worker가 DB/NAS를 쓰거나 공용 shell/browser 명령을 받지 않는다.
임의 경로/JSON 업로드로 기존 owner를 우회하는 더 단순한 대안은 권한·원래 수신 증거가 없다.

## 수집 attempt와 source 수락 연결 — 2026-11-16

기존 run/room task와 공유 browser epoch에 최초 attempt를 하나씩 예약한다. 별도 큐나
실행 framework는 만들지 않는다. command/attempt/snapshot/normalization identity를 DB의
작은 metadata에 먼저 예약하고, 기존 worker C1 command와 실제 inventory/capability의
정확한 Artifact를 확인한 뒤 command를 고정한다. 재조회는 원래 attempt를 돌려주며,
미확인 실행이나 FAILED를 새 identity/성공으로 바꾸지 않는다. successor retry는 별도 명시
절차이며 이 최초 연결에서 암묵적으로 실행하지 않는다.

정본은 기존 Artifact owner의 command/result/report 파일이다. owner는 파일 I/O를 lock
밖에서 수행하고 현재 계정·policy·adapter·profile fence를 다시 검사해 작은 pointer만
채택한다. worker JSON만으로 source 권한을 얻지 못하며, source admission callback은
실제로 채택된 attempt의 command/capability/result/report와 room/snapshot identity를 대조한다.
원본 CSV/사진의 byte·관측·attachment coverage 검증은 기존 source owner가 계속 담당한다.
결과 proof 수락과 원본 검증은 다르다. 기존 source owner의 실제 revision 수락 후에만
task를 LOCAL_ACCEPTED로 진행하며, 이것도 질문 저장이나 run 전체 완료는 아니다.
inventory는 command마다 JSON을 복사하지 않고 별도 canonical Artifact의 작은 pointer로
고정한다. worker의 local inventory member는 명시적 입력 materialization에서만 만든다.

접근은 task/attempt PK lookup와 task별 unique claim, run→browser exact FK다. attempt당
O(1) metadata, member 검증은 bounded O(n)이다. task row lock 후 원래 attempt를 재조회하고,
browser 관측은 이미 pin된 epoch와 실제 profile gate를 사용한다. command/result 파일이나
대화 원문·사진은 DB에 넣지 않는다. dependency는 Catalog application→contracts/Artifact
owner이고 browser·로컬 workspace 동작은 Orchestrator adapter에 남는다. 단순히 caller가
전달한 fence만 믿는 대안은 실제 접수된 작업·결과의 증거가 없어 source authority에 부족하다.
실제 AUTO 시작·selector·주기 실행을 이 저장 연결만으로 활성화하지 않는다.

## 책임과 정본

### 수락 원본의 질문 후보 자동 저장 — 2026-11-17

1. 기존 `KakaoQuestionService`가 수락 source의 결정론적 후보를 기존 최초 저장 use case로
   연결한다. 수집/모델/수동 편집/packet 생성은 이 입구의 책임이 아니다.
2. 정본은 exact source resolution·원문/정규화 Artifact와 기존 질문 revision이다.
   순서가 미확인인 source는 기존 오류를 유지하며 발신 방향·사진 관측을 승격하지 않는다.
3. 기존 question-create/1.0 JSON Schema와 command/origin unique를 재사용한다. 새 wire,
   DB migration, queue나 권한 token은 만들지 않는다. 반환값은 내부 작은 frozen 값이다.
4. API는 현재 로그인, background는 실제 accepted attempt의 현재 owner/ADMIN/READ/COLLECT에
   EDIT도 확인한다. 해당 binding/room/capture만 허용하며 다른 source나 수동 편집은 위임하지 않는다.
5. 주 접근은 source exact lookup, candidate 순서 순회, bounded origin membership와 key replay다.
6. source당 한 번 해석한 map과 기존 `(room_id, origin_occurrence_id)` unique/index를 사용한다.
   한 호출은 최대100개 후보이고 기존 origin은 한 번의 bounded IN 조회로 확인한다.
7. 한 호출은 source rows/bytes에 선형 해석 + 선택 후보 수의 indexed 저장이다. 각 저장의
   기존 pointer metadata 재검사 비용 O(P)는 유지하므로 전체 O(N + K·P)이며 K≤100이다.
   다음 호출은 cursor로 이어가지만 source context는 다시 검증한다. 큰 이력 cache나 payload
   복제는 없다. 원본 parse/hash를 후보마다 반복하지 않는다.
8. 기존 intent→binding/room 잠금·예약→lock 밖 Artifact 발행→현재 권한/source 재확인→CAS
   채택을 그대로 사용한다. source/candidate의 고정 key로 발행 직후 중단도 복구한다.
9. Catalog application→기존 authorization/source/question/Artifact owner 방향이다. worker는
   authority·학생 mapping·질문 ID를 정하거나 DB/NAS에 쓰지 않는다.
10. 기존 origin은 현재 질문을 덮지 않고 건너뛴다. 분할/병합으로 supersede된 원본과 제외도
    그대로 보존한다. 경합 중 최초 생성에 진 경우도 실제 origin을 재확인한 뒤에만 건너뛴다.
    mapping 변경/권한 철회/해시 불일치는 명시적 오류이며 실패를 성공으로 바꾸지 않는다.
    규칙이 해석하지 못한 row ordinal도 결과에 남겨 후보0개를 완전 수집으로 오인하지 않는다.
11. API actor를 꾸미거나 질문 row를 직접 생성하는 대안은 인증/기존 편집 규칙을 우회한다.
    기존 저장 owner의 API/accepted-source 권한 port만 재사용한다. 이 연결 자체는 실제
    카카오 관측·AUTO dispatcher·전체 방 주기 수집·운영 활성화 완료 증거가 아니다.

### C1 결과 파일의 발행과 원 attempt 수락 — 2026-11-17

1. 기존 attempt application이 COMMAND_READY의 실제 command/capability/현재 owner를 확인한
   뒤 Orchestrator의 고정 `outputs/result.json` reader를 호출한다. 브라우저 실행 권한은 없다.
2. 결과 JSON은 untrusted proposal이고, canonical command와 capability ceiling·fence·room/
   snapshot/normalization 및 report 해시·크기를 기존 C1 validator로 검증한 뒤에만 발행한다.
3. 기존 C1 schema·attempt/result pointer·Artifact 모델을 그대로 사용한다. 새 테이블/queue/
   RPC는 없고, 결과 제안과 정본 source 수락의 차이를 유지한다.
4. 결과32KiB/report4MiB 상한·canonical JSON·closed member·현재 pins를 I/O/발행 전후 확인한다.
   FAILED/PAUSED/CANCELLED도 원 결과 그대로 보관하고 사진/source 성공으로 승격하지 않는다.
5. 접근은 attempt PK와 공식 file-set publisher의 unique idempotency key lookup다.
6. 기존 `ControlFileSetPublisher`의 최초 관측 시각·exact completed lookup·publication lock을
   사용한다. 별도 Artifact 조회기·직접 Job 수정·새 결과 registry를 만들지 않는다.
7. metadata O(1), 결과/report의 parse·hash 비용은 bounded byte 수에 선형이다. CSV/사진을
   결과 Artifact에 복사하지 않으며, 그 원본은 다음 기존 source owner가 발행한다.
8. 파일/NAS I/O는 DB lock 밖이다. 결과 Artifact 발행 후 원 attempt 수락 전에 중단되면
   같은 publication key의 정본을 읽어 기존 `accept_result`만 재개한다. 새 worker 실행은 없다.
9. Catalog application→pure C1/Artifact owner와 Orchestrator OS adapter 방향을 유지한다.
   source commit은 설치한 controller의 실제 release 값이며 ambient Git을 읽지 않는다.
10. 이미 RESULT_ACCEPTED인 내부 metadata 재조회는 기존 get_attempt와 같고 source 권한을
    주지 않는다. 그 뒤 source 작업은 기존 accepted access의 현재 권한 검사로 진행한다.
    terminal/incomplete publication은 성공/없음으로 바꾸지 않으며 supported same-key 복구만 한다.
11. local result를 읽은 뒤 임의 caller가 Artifact를 먼저 만들어 주던 대안은 collector의
    정상 결과 경로와 중단 복구를 연결하지 못한다. 기존 publisher/application을 조합한다.

### 고정된 로컬 수집 출력에서 source 채택까지 — 2026-11-17

1. Orchestrator의 filesystem adapter는 configured root 아래 exact accepted attempt의
   `outputs/` member만 읽는다. Catalog composition은 이 reader와 기존 source application을
   연결한다. reader 자체는 수집·source 권한·Artifact 발행을 하지 않는다.
2. 정본은 기존 Catalog가 수락한 command/result/report와 그 안의 member SHA다. 로컬
   workspace는 untrusted materialization이다. 파일 경로나 파일명이 identity가 아니다.
3. 기존 attempt/run/source revision을 사용한다. root/UID/GID는 설치한 trusted composition
   설정이고 public API/worker가 선택하지 않는다. 새 wire/DB/queue/authority는 없다.
4. root는 core-owned2750, attempt와 하위 출력 directory는 worker-owned750, member는
   worker-owned640/control group이다. 기존 OS adapter로 symlink·다중 link·위험 권한·크기·
   읽는 동안의 변경을 거부하고, exact member 크기/SHA를 확인한다. 오류에는 경로를 넣지 않는다.
5. 접근은 validated attempt ID/direct member lookup다. directory 전체를 탐색하거나 복사하지 않는다.
6. 기존 `protected_directory`/`read_protected`와 typed `LocalMember`/`CsvMember`를 재사용한다.
   복사본 index/cache·새 generic filesystem framework는 만들지 않는다.
7. metadata는 경로 깊이에 선형, 실제 bytes 검증은 O(member bytes)다. 전체 입력 예산은
   기존 C1 report의256MiB, CSV32MiB 상한과 publisher의 closed member set이 계속 보호한다.
8. 파일 I/O 중 DB lock을 보관하지 않는다. application의 현재 owner/pin 재검사와 source
   CAS/멱등 발행·task 채택을 재사용한다. 같은 member의 모든 bytes는 단일 read에서 반환한다.
9. Catalog composition→기존 attempt/source use case 및 Orchestrator OS adapter 방향이다.
   worker는 staged local output만 제공하고 PostgreSQL/NAS·다른 worker를 호출하지 않는다.
10. adapter 생성은 lazy이며 completed source replay에 파일 존재를 요구하지 않는다.
    missing/변조/다른 attempt는 실패이지 재다운로드나 FAILED 성공 변경의 이유가 아니다.
11. 임의 `Path.read_bytes()` callback은 실제 file type/owner/link/범위 검사가 없어 부족하다.
    이 연결은 실제 browser/selector·원문 발신 방향/사진 occurrence 확인을 대체하지 않으며,
    설치하지 않은 root를 추측해 읽거나 AUTO를 활성화하지 않는다.

### 수락된 run의 background 원본 권한 — 2026-11-17

1. 수집 application이 이미 수락한 특정 RESULT_ACCEPTED attempt의 원본 발행/채택만
   계속한다. 공개 API의 로그인/다운로드·새 수집 요청 권한은 바꾸지 않는다.
2. 권한의 정본은 실제 run/attempt·현재 Identity·binding/room·고정 policy/capability와
   원 command/result/report Artifact다. 브라우저/worker가 선언한 owner는 쓰지 않는다.
3. 기존 run/task/attempt와 source revision 모델을 유지한다. 세션·토큰·새 authority row는 없다.
4. internal source authorization port는 API actor adapter와 accepted collection adapter 두
   실제 용도만 지원한다. background 객체는 worker JSON/HTTP DTO가 아니며 attempt 범위에
   고정된다. 현재 owner와 모든 pin은 각 I/O/commit 경계에서 다시 확인한다.
5. 접근은 attempt/run PK와 기존 unique source replay lookup이다. 순회/새 큐는 없다.
6. 같은 SourceService의 예약·원문 검증·발행·CAS를 재사용하고 API/배경 권한만 명시적으로
   분리한다. binding/room lifecycle·잠금 규칙은 기존 authorization owner에 한 번 둔다.
7. metadata는 indexed O(1), 실제 입력의 byte/row/pixel 선형 검증 비용은 기존과 같다.
8. 현재 binding→profile→run→browser→task 잠금 순서와 기존 source의 짧은 transaction을
   유지한다. background 객체를 만들 때 DB lock이나 mutable ORM session을 보관하지 않는다.
9. Catalog application/authorization adapter→기존 contracts/Identity repository 방향이다.
   worker는 DB/NAS/Identity·타 worker와 통신하지 않는다. 새 cross-service 메시지는 없다.
10. 정상 logout/HTTP 만료는 접수된 정확한 작업의 실행 권한을 없애지 않는다. 계정 중지·역할
    철회·원본/채널 폐기·잘못된 policy/adapter/fence·FAILED/미수락 결과는 거부한다. terminal
    run의 새 발행은 거부하고, 이미 수락된 source의 같은 요청 재조회/채택 복구만 허용한다.
    원래 실패·원문·Artifact·수동 질문 편집은 변경하지 않는다.
11. 기존 API 세션을 연장/가장하거나 system/ADMIN actor를 만드는 대안은 인증과 accepted
    intent를 혼동하므로 사용하지 않는다. 별도 source 저장소/우회 발행 framework도 만들지 않는다.

### 수락된 수집 결과에서 원본 자료 발행까지 — 2026-11-17

1. 책임은 기존 collection attempt application과 Catalog의 원본/사진 발행 adapter다.
   브라우저를 시작하거나 worker에게 DB/NAS 권한을 주지 않는다.
2. 정본은 실제 attempt가 채택한 command/capability/result/report Artifact와 그 report의
   exact 로컬 출력이다. caller가 전달한 worker identity를 새 권한으로 받지 않는다.
3. 원래 run/task/attempt/snapshot/normalization ID를 그대로 사용한다. 원본·사진 발행과
   source revision 채택은 기존 각 owner가 맡는다. 새 entity/table/queue는 없다.
4. 현재 actor·owner·run pins와 accepted result 포인터를 I/O 전후 확인한다. 로컬 reader는
   trusted Orchestrator 조립 지점이 제공하며 report member 밖의 path를 받지 않는다.
   bytes/hash/size/JSON·원문 재파싱과 media decode는 기존 발행/수락 owner가 재검증한다.
5. 주 접근은 attempt PK·unique(binding,capture_attempt)·source revision PK다.
6. 기존 unique index와 report member map/사진 hash map을 사용한다. DB에 원문을 복제하지 않는다.
7. 파일 검증/발행은 bounded O(bytes+rows+pixels), metadata lookup은 indexed O(1)이다.
   같은 이미지의 여러 occurrence는 따로 남기되 같은 bytes의 발행은 재사용한다.
8. 파일 I/O는 DB lock 밖에서 수행한다. source와 task 채택은 기존 짧은 두 transaction이며
   분산 atomic이라고 부르지 않는다. source head precondition은 명시적 입력으로 고정한다.
9. application→기존 Catalog Artifact/원본/사진 adapter와 contracts 방향이다. 새 cross-service
   wire family는 없고 기존 CaptureResult/SourceAdmission을 사용한다.
10. 같은 key·원래 source precondition의 완료 replay는 저장한 source admission을 재인가하고
    task 채택만 복구한다. 로컬 파일·parser·decoder를 다시 호출하지 않는다. 중간 발행 후
    중단은 같은 snapshot/normalization/media 발행 key를 재사용한다. 실패/취소 결과·다른
    owner/key/precondition·철회된 원본을 거부하고 역사적 실패를 성공으로 고치지 않는다.
11. 호출자가 직접 Artifact를 조립하는 대안은 authority 확인과 중단 복구가 분산되므로
    작은 한 use case로 연결한다. 이 연결만으로 실제 collector·selector·AUTO를 활성화하지 않는다.

### 최초 browser 관측과 최신 상태 확인 분리 — 2026-11-17

실제 수신물 진단에서 다운로드19:11 뒤 RENEW가 `browser_observed_at`을19:16으로 갱신해
기존 intake의 하한 검사가 정상 과거 수신물을 거부했다. 이 필드를 최초 시각으로 재해석하거나
latest 갱신을 멈춰 gateway 관측 시각을 거짓으로 만들지 않는다.

1. 기존 MANUAL session owner에 nullable `browser_first_observed_at` 한 열을 추가한다.
2. 정본은 실제 browser observer가 처음 확인해 `prepare_gateway`가 채택한 UTC 시각이다.
3. lease/run/fence/command identity는 그대로이며 새 entity/revision을 만들지 않는다.
4. 최초와 최신 시각·고정 invocation/start pin을 함께 검증한다. source/Artifact 검사는 유지한다.
5. access는 기존 session PK/owner index lookup이다. 별도 검색·스캔·cache/index는 없다.
6. 최초 값은 단일 nullable timestamp이고 최신 관측은 기존 필드다.
7. time/space 증가는 row당 O(1)이며 lease별 주기 관측 횟수에 무관하다.
8. 기존 첫 browser 채택 transaction에서 한 번 설정하며 DB trigger가 재기록/사후 추정을 막는다.
9. domain 계약과 worker 메시지는 바꾸지 않고 Catalog persistence/application owner만 확장한다.
10. 새 intake는 최초 값을 하한으로 쓴다. 역사적 NULL은 보존하고 기존 latest 관측의 보수적
    하한만 사용한다. 과거 row에 created_at/CSV/현시각을 추측 backfill하지 않는다. 만료·종료·
    잘못된 fence는 계속 거부하며 같은 요청 복구는 기존 source idempotency를 따른다.
11. 최초 값을 latest 필드에 고정하는 대안은 복합 runtime 관측의 시각 의미를 깨고, lease 생성
    시각으로 하한을 넓히는 대안은 실제 browser 관측 증거가 없어 사용하지 않는다.

additive0097 migration과 기존 보호 release context의 successor로 검증·배포한다. 새 최초
값이 있는 운영 이력은 downgrade로 버리지 않는다. 현재 로컬 preview 읽기는 이 migration의
운영 적용/과거 source 수락을 대신하지 않는다.

### 원본 수락 후 task 채택의 단일 application 입구 — 2026-11-17

`KakaoCollectionAttemptService.admit_capture_source`는 기존 source admission 계약과
`KakaoSourceService.admit_source`→`accept_source_revision`을 순서대로 호출한다. 별도 wire
schema/queue/table은 추가하지 않는다. 각 owner의 현재 권한·실제 accepted capture callback·
raw 재파싱/hash·immutable Artifact·head CAS가 정본이며 새 입구가 authority를 만들지 않는다.
logical source/immutable revision/Artifact/hash는 기존 계약대로 분리된다. 입력은 기존의
exact command/capability/result/report/source pointers와 원래 idempotency key다.

접근은 attempt/room/source PK·기존 unique replay key이며 추가 상태/캐시는 없다. metadata는
indexed O(1), 원본 검증은 기존 byte/row 수에 선형이다. 긴 file I/O는 source owner의 lock
밖이고 source 채택과 task 채택은 기존의 두 짧은 transaction이다. 이를 분산 atomic이라고
부르지 않는다. source commit 직후 task 채택 전에 중단돼도 같은 입력/key는 원 revision을
재조회한 뒤 원 task만 채택한다. 새 다운로드·snapshot·attempt나 FAILED 성공 변경은 없다.
현재 사용자 철회/다른 owner/다른 pointer는 기존 경계에서 거부한다. application→기존
application owner→계약/Artifact adapter 방향을 유지한다. caller마다 두 호출을 반복하는
대안은 중단 후 한쪽만 재개하기 쉬워 이 작은 use case로 묶는다. 실제 collector/selector나
운영 source admission 활성화는 별도이며 이 입구의 source 존재로 성공을 주장하지 않는다.

Catalog는 현재 사용자·binding 권한과 lifecycle, capability revision, 결과 발행의
소유자다. Orchestrator는 task/attempt/fence, 프로세스·profile 잠금과 local workspace를
관리한다. Collector는 승인된 화면을 관측해 local CSV/첨부/작은 결과 manifest만
제출한다. worker 간 통신, PostgreSQL·NAS 접근, 메시지 전송·차단·상태 변경은 없다.
브라우저 인증은 보호된 profile에 있고 command/result에 cookie·URL·비밀번호를 넣지 않는다.

정본은 발행된 raw CSV와 첨부 Artifact다. worker 결과와 정규화는 별도 파생물이다.
이 단계의 `CaptureCapability`는 owner가 검증한 관측과 release의 exact pin이며,
임의 worker/client가 제공한 JSON만으로 실행 권한·채널 검증을 얻을 수 없다.
새 capability를 발행하고 활성화하는 application은 별도 현재 권한 검사를 해야 한다.

## identity와 작은 계약

- binding/room/snapshot ID는 기존 Catalog 계약을 따른다.
- run/task/command/attempt ID와 증가하는 fence는 별개다.
- capability는 `kakaocapabilityrev_…`와 canonical SHA, adapter release SHA를 함께 pin한다.
- inventory는 `kakaoinventoryrev_…`; 수집 room은 해당 inventory의 확인된 내부 room이다.
- 출력은 ASCII relative path·size·SHA·detected media의 local member만 받는다.
  CSV는 32 MiB, 각 이미지 64 MiB, room 전체 256 MiB, CSV 100,000행,
  첨부 2,000건을 초기 상한으로 둔다. 이는 사용량 추정이 아니라 검증 예산이다.
- 원문 본문과 외부 서명 URL, 원본 파일명, DB/NAS 경로를 명령·결과에 넣지 않는다.
  CSV 원문은 raw member에, 방향/정합 관측은 별도 bounded JSON member에 둔다.

## 주요 접근과 구조

실행은 exact ID lookup, 정렬된 목록 순회, membership/중복 검사다. dict/set으로
scope/room/첨부 ID와 local member를 O(n)에 확인하고, 순서는 tuple로 유지한다.
같은 SHA의 반복 사진은 서로 다른 occurrence로 보존한다. 같은 path는 동일 bytes의
재사용일 때만 허용하며 서로 다른 hash/media를 가리킬 수 없다. unresolved 목록은
확인된 room/attachment 목록과 분리하되 coverage에서 사라지지 않는다.

작은 capability·command·result는 immutable value다. 긴 inventory/첨부 관측 JSON은
local member로 넘겨 owner materialization boundary에서 한 번 검증한다. 이 pure
module은 DB/파일 읽기/브라우저 실행을 하지 않으며 새 queue·scheduler를 만들지 않는다.

## 완전성·발신 방향

목록 complete는 확인된 전체 scope, filter 초기화 증거, 명시적 목록 끝,
loading 없음, 두 번째 pass의 신규 room 없음, unresolved 없음을 모두 요구한다.
종료를 못 증명한 반복 scroll은 complete가 아니다. inventory는 단일 시점의
원자적 snapshot이라고 주장하지 않고 시작/종료/reconciliation UTC를 남긴다.

CSV 순서·timezone·방향은 unknown을 허용한다. `USER` 이름으로 role을 추정하지 않는다.
정규화 parser는 별도 owner 경계에서 raw CSV를 재파싱한다. worker row count와 관측
JSON은 검증해야 할 주장이다. `사진` 행에 파일이 없다고 사진이 없었던 것으로 처리하지
않고 attachment inventory coverage와 unresolved 상태를 보존한다. 원본 확보와
PNG/JPEG/WebP 렌더 지원은 별개이며 지원하지 않는 파일은 unresolved로 남긴다.

## 상태·동시성·실패

도메인 run 상태와 허용 전이는 명시적 표로 둔다. 기존 global Job enum은 바꾸지 않는다.
활성 상태에서 중단/취소는 먼저 PAUSING이고, checkpoint+process/profile stop 관측 후
PAUSED/CANCELLED가 된다. lease 시간 만료 자체는 프로세스 종료 증거가 아니다.
DB의 atomic claim/최신 fence와 OS profile lock을 모두 owner가 확인해야 하며 이 pure
계약은 그 확인을 대신하지 않는다.

timeout이면 원래 command/attempt 조회가 먼저다. 유효 결과는 재발행이 아니라
같은 publication intent를 이어간다. 결과 처리가 불명확한 동안 새 attempt는 없다.
네트워크 오류의 재시도는 최대 3회, 이전 process/profile stop 확인 이후에만 허용한다.
AUTH_REQUIRED는 로그인 자동 반복 금지, UI_CHANGED/HASH_MISMATCH는 점검 대기,
ACCESS_DENIED는 권한 변화 전 반복 금지다. NAS 발행 실패는 local 결과를 보존하고
publication recovery를 사용하며 재수집하지 않는다. FAILED 기록은 변경하지 않는다.

## 수락과 단순 대안

command/result exact identity·capability hash·현재 fence → local 파일 type/link/크기/hash
→ core staging → 현재 ACL/lifecycle → 기존 Artifact commit → domain pointer 연결 순이다.
외부 다운로드 동안 DB transaction을 유지하지 않는다. NAS와 domain DB를 단일 atomic
transaction이라고 부르지 않으며 기존 publication idempotency로 중간 실패를 복구한다.

더 간단한 `성공 여부 + CSV 경로`만으로는 어느 채널/시점/attempt의 결과인지, 사진·목록이
누락됐는지, timeout 뒤 중복 실행인지 구분할 수 없다. 반대로 selector registry·새 workflow
framework는 현재 필요 없으므로 만들지 않는다. 실제 capability 실증 전 운영 자동 수집은
활성화하지 않는다.

## 다음 구현: 최소 영속 owner 경계

이 절은 2026-11-16 소스 재검토의 설계 제안이다. 아직 아래 DB·scheduler·collector가
구현되거나 설치됐다는 뜻이 아니다. 기존 binding은 DRAFT/RETIRED뿐이고 capability는
NOT_VERIFIED다. 다음 담당자는 실제 최신 migration head와 공유 diff를 먼저 확인한다.

### 이미 있는 것을 재사용할 위치

| 기존 코드 | 재사용하는 책임 | 재사용하지 않는 것 |
| --- | --- | --- |
| `kakao_archive_authorization.authorize_kakao_actor` | 실제 API actor/session·현재 permission·owner 확인 | worker가 전달한 operator나 role을 authority로 사용 |
| `kakao_archive_commands.lock_kakao_intent`, `kakao_command_sha256` | 짧은 owner/scope/key 잠금과 같은 요청 replay | 다운로드 동안 transaction 유지 |
| `kakao_student_models`, `kakao_student_service` | owner별 학생·불변 display revision·CAS 패턴 | 이름 중복 제거, 다른 owner 학생 연결 |
| `material_learning_store.claim_next_material_run`, `lock_material_run` | indexed `FOR UPDATE SKIP LOCKED`, lease 검증 **패턴** | 카카오를 material learning task로 등록하거나 그대로 재사용 |
| `material_learning_coordinator.authorize` | 저장된 run owner로 현재 권한을 다시 확인하는 **패턴** | 오래된 API session이 계속 유효하다고 간주 |
| `CatalogArtifactService.commit_file_set` | publication lock, exact idempotency, COMMITTING 복구 | collection run과 publication Job을 같은 ID로 간주 |
| `kakao_archive_intake.publish_kakao_capture` | raw hash·재파싱 일치 확인, raw/normalization 별도 발행 | arbitrary worker normalization만 믿고 정본 등록 |
| `kakao_pdf_execution.KakaoPdfExecutor` | core local staging, exact command/result, stopped-attempt recovery **패턴** | renderer 프로세스에 카카오 profile·network 권한 부여 |
| `capture`, `kakao_remote` pure 계약 | 상태 전이, exact capability, fence, stop receipt 검증 | bool receipt만으로 실제 종료·권한·채널 검증을 대체 |

`JobRecord`는 닫힌 실행 상태와 Artifact publication을 이미 소유한다. 신규 run의
AUTH_REQUIRED/PAUSING/PARTIAL을 여기에 추가하지 않는다. PDF/수집 실행은 새 source별
도메인 run/task의 pointer·상태로 관리하고, canonical 발행 Job ID는 별도 FK로 연결한다.
일반 Codex worker slot을 카카오 브라우저 슬롯인 것처럼 등록하지 않는다.

### 실제 수집을 시작하기 전에 필요한 authority

1. 현재 owner가 만든 binding과 보호된 profile의 연결은 owner runtime inventory다.
   public request·collector 결과의 profile 경로나 owner 주장은 받지 않는다.
2. 실제 원격 로그인 후 **예상 채널 ↔ 현재 열린 채널**을 비교할 관측 근거가 필요하다.
   사용자 확인과 adapter가 관측한 source identity/evidence를 작은 immutable verification
   receipt로 남긴다. 확인된 안정 ID가 없으면 수동 context 연결이며 이름 유사도로 대체하지
   않는다. 이 경우 자동 재접속에서 동일 채널을 재검증할 수 있는지 실증 전에는 보류한다.
3. 그 verification에 연결된 capability Artifact와 installed adapter release hash를
   Catalog가 확인한 뒤에만 binding ACTIVE 전이를 허용한다. `channel_verified=true`인
   임의 JSON 업로드나 worker self-report만으로 ACTIVE가 될 수 없다.
4. API command는 기존 실제 session 검증을 사용한다. 오래 걸리는 run과 schedule은
   **이미 저장된 owner의 실행 의도**를 현재 Identity ACTIVE/permission/binding grant에
   다시 대조한다. `authorize_kakao_actor`를 허위 actor/session으로 우회하지 않는다.
   별도 Catalog background authorizer는 run ID로 owner를 읽으며 operator ID를 worker에서
   받지 않는다. scope는 현재 ACTIVE binding과 해당 run의 exact capability/policy다.
5. Orchestrator의 실제 peer/launcher만 attempt admission을 요청한다. Catalog의 current
   lease/fence와 runtime owner의 process/profile-lock 관측이 함께 맞아야 한다. 현재
   `ProfileStopReceipt`는 값 모델이므로 receipt를 만들 수 있다는 것이 종료 증거는 아니다.

실제 채널·CSV 범위·사진 다운로드 실증 없이 2–3을 통과했다고 표시하지 않는다.
이 authority가 아직 없는 동안 학생·질문·packet 같은 독립 기능의 source/DB 검증은
합성 fixture로 진행할 수 있지만, 운영 방 수집·자동 스케줄은 비활성 상태다.

### 권장 최소 테이블과 조회 패턴

기존 binding/student 테이블은 유지한다. 다음 표는 한 번에 전부 추가하라는 지시가 아니라
후속 migration을 나눌 최소 aggregate 경계다. 본문·사진·전체 room 목록 JSON은 넣지 않는다.

| 작은 record | 핵심 필드·제약 | 주요 인덱스/용도 |
| --- | --- | --- |
| capability revision | binding, revision, adapter SHA, verification/manifest Artifact pointer, observed/accepted UTC, accepted owner | unique(binding,revision), exact Artifact composite FK; current pointer만 binding에 추가 |
| room | owner+binding, server-issued room ID, verified identity method/key, identity evidence pointer, current mapping rev nullable, resource_version, lifecycle, last_observed UTC | unique(binding,verified provider identity key) **verified일 때만**; (binding,last_observed,room) keyset |
| room-student mapping revision | binding/room, mapping rev, previous rev, student ID 또는 명시적 UNMAPPED, exact display rev, actor/time, reason, request hash/key, result version | unique(room,revision number), unique(owner,room,idempotency key); room/binding/owner, student/owner, student/display composite FK |
| collection run | run, owner, binding, policy/capability pins, state, current inventory pointer, active task, created/update UTC, next event sequence | owner+idempotency key/request hash; partial unique(binding) for nonterminal run; (state,created,run) |
| room task | task, run, room, operation, state, current attempt, ordinal, result pointer | unique(run,room,operation); (run,state,ordinal); inventory task는 room NULL인 별도 부분 unique |
| attempt | attempt, task, attempt number, command hash, profile/browser IDs, fence, lease owner/token/expiry, outcome/error, local-result receipt pointer, publication linkage | unique(task,attempt number), unique(command); (state,lease expiry,task); terminal history는 불변. profile/fence unique는 실제 browser epoch가 소유 |
| snapshot acceptance | snapshot/normalization revision, binding/room, accepted attempt, raw/normalization exact pointers, row count, observed time, source scope/timezone/order | unique(snapshot), unique(normalization), (room,observed,snapshot); publication Job FK 별도 |
| media blob | binding, SHA, size/MIME/dimensions, original exact pointer | unique(binding,SHA); 다른 binding 전역 dedup 없음 |

binding별 browser 모드·증가 fence는 실제 원격 lease persistence와 **한 owner record**에서
조정한다. collection 전용 profile gate를 하나 더 만들어 MANUAL과 AUTO가 서로 다른
배타성 테이블을 보게 하지 않는다. pending task를 모두 claim하는 별도 queue도 만들지
않고, run row를 claim한 owner가 현재 task 하나를 고른다. 초기 전체 동시 run 1 제한은
기존 owner tick의 고정 설정으로 충분하며 범용 capacity framework는 추가하지 않는다.

mapping revision 자체가 immutable 명령 결과를 담을 수 있으므로 이를 위해 별도 범용
command bus를 만들 필요는 없다. 다만 실제 public API의 create/read/rename/replay 모양에
맞추기 위해 기존 student command receipt 구조를 그대로 택하는 것도 가능하다. 둘을
동시에 도입하지 않는다. 이벤트가 필요하면 run의 monotonic sequence 아래 작은 ID·state·
error만 append하고 다른 도메인의 이벤트 테이블에 카카오 본문을 넣지 않는다.

### Worker room ID를 정본으로 바로 수락하지 않기

worker inventory의 room ID는 proposed reference다. 타 binding의 기존 ID를 제시했다고
그 방을 가져오거나 update하지 않는다. 수락 owner가 verified source identity를 binding
범위 안에서 lookup하고, 새 방이면 canonical room ID를 발급한다. 안정 ID를 확보하지 못한
항목은 unresolved로 보존하고 사람이 확인한 context mapping 없이는 기존 방과 합치지 않는다.
닉네임·정렬 순서·마지막 메시지·CSV hash는 영구 room identity가 아니다.

raw inventory와 **accepted inventory/identity mapping manifest**는 별도 revision이다.
후자는 raw exact pointer와 proposed observation→canonical room 대응을 pin하고, 이후
CaptureCommand가 사용하는 room ID와 inventory revision을 고정한다. worker의 기존 결과
파일을 제자리 수정하지 않는다. 현재 pure `CaptureInventory`는 관측 proposal 계약이며,
owner가 그 객체를 파싱했다는 사실만으로 source identity acceptance를 얻지 않는다.

### 가장 짧은 구현·transaction 순서

1. room+mapping 저장/조회부터 구현한다. owner 일치와 composite FK, same-key replay,
   두 동시 mapping CAS를 disposable DB에서 검사한다. 이 단계는 collector를 실행하지 않는다.
2. capability/verification 발행·수락을 연결한다. DRAFT에서 ACTIVE로 가는 guarded command와
   실제 current source authorizer가 있어야 다음 단계를 켠다. 단순 표시용 READY는 부족하다.
3. run intent를 실제 API actor로 접수한다. 짧은 key lock 안에서 owner/binding/policy와
   request hash를 확인하고 run/task identity를 고정한다. 같은 key는 같은 run을 돌려준다.
4. owner tick은 row lock으로 run/task를 claim하고 command/attempt/fence를 기록한 뒤
   transaction을 닫는다. 이전 process/profile 종료가 불명확하면 recovery로 보내고 launch하지
   않는다. 브라우저 실행 중 DB lock을 유지하지 않는다.
5. Orchestrator가 capability/input hash·실제 profile lock을 검증하고 local collector를 실행한다.
   result는 exact command/fence/capability와 파일 bytes 검사를 통과한 뒤 core staging에 둔다.
   unknown capability가 full/verified/original로 승격된 worker 결과는 거부한다.
6. Catalog는 현 권한·binding ACTIVE·pinned capability lifecycle을 재검사하고 기존 Artifact
   publication 경계로 raw inventory/CSV/사진을 발행한다. publication은 수집과 다른 Job이다.
7. 짧은 domain transaction에서 같은 current attempt/fence를 다시 확인하고 exact pointer,
   room mapping, snapshot acceptance, task state/checkpoint를 함께 연결한다. publication 후
   이 transaction이 실패하면 미채택 Artifact를 보존하고 **같은 attempt의 accept**만 재개한다.
8. normalize/candidate/question은 accepted pointer에서 만든다. owner-issued occurrence IDs와
   alignment receipt를 고정하고, 매번 이름/본문 hash로 새 identity를 추측하지 않는다.

### 필수 부정·복구 검사

- 다른 owner/binding/room/student/Artifact revision, retired source, expired public session 거부.
- 저장된 background intent가 있어도 owner 비활성/권한 철회 뒤 claim·accept·download 거부.
- 두 claim 경합, manual/auto 경합, lease 만료지만 process 생존, 늦은 이전 fence 결과 거부.
- worker가 타 room ID를 끼워 넣기, unknown source identity를 stable로 승격, 일부 scope를
  빠뜨리고 inventory complete 주장, unsupported 첨부를 누락시키는 결과 거부.
- publication 성공 후 domain commit 전 중단 → 원래 publication pointer 연결, 재수집 0회.
- 정규화 raw 재파싱 불일치, source hash 불일치, 동일 문구/동일 사진의 서로 다른 occurrence 보존.
- 원본 rows/Artifact/FAILED 기록 변경 없음; Item·Graph·임베딩 호출 0회.
- owner/room keyset page, bound 10,000-room inventory의 선형 검증; 불필요한 N+1·전체 history LCS 없음.

source 프로토콜 검사는 63개, 기존 remote 회귀와 합쳐 146개가 통과했다. 이는 위 신규 영속
owner·Kakao runtime·운영 배포를 검증한 수치가 아니다. 그 단계의 검사와 실증은 각각 별도다.

### 0082의 제한된 구현 범위

첫 영속 slice는 room, immutable mapping revision, internal admission receipt의 3개 테이블이다.
공개 room create나 channel activate API는 없다. Catalog 내부 admission은 현재 실제 actor와
필수 owner-authority callback, 발행된 room-observation Artifact의 exact schema/hash/상태를
모두 검사한다. callback은 이미 검증한 source bytes와 현재 runtime/source authority를
대조하며 transaction 안에서 긴 파일 I/O를 하지 않는다. DRAFT binding에 자료를 연결해도
채널이 ACTIVE가 된 것으로 표시하지 않는다. RETIRED binding은 새 admission/mapping을 거부한다.

처음 확인한 room identity/display/evidence는 보존하고, 같은 verified source identity의
재접수는 기존 room과 해당 시점 mapping을 반환한다. worker의 변경된 이름/ID로 기존 방을
덮지 않는다. 주기적 재관측 이력은 후속 snapshot owner가 관리한다. mapping 수정만 current
pointer/version을 CAS 갱신한다. immutable mapping revision이 명령 key/hash를 보유하므로
mapping 전용 command 테이블을 또 만들지 않는다. 최초 UNMAPPED revision은 public key가 없다.

admission과 mapping은 owner/scope/key 잠금 뒤 binding → room → student 순서로 짧게 잠근다.
같은 source identity 동시 admission은 binding 내 identity 잠금과 unique constraint가 막고,
두 mapping 수정은 room lock+expected revision/version으로 하나만 수락한다. 이름으로 identity를
추정하지 않으며 public mapping은 같은 owner의 현재 ACTIVE student/display revision만 받는다.
이전 mapping 조회와 same-key replay는 나중의 rename/unmap으로 내용이 바뀌지 않는다.

## 실제 내보내기 경험에 따른 실행 방식 결정 — 2026-11-16

실제 방에서 CSV와 사진2건의 download event·로컬 보존·hash를 확인했다. 이것은 전체 방
수집이나 사진 occurrence 정합의 완료 증거가 아니다. 사용자 승인 아래 화면을 읽고 누른
개발용 좌표를 운영 selector로 승격하지 않는다.

**반복 수집에는 결정론적 Playwright adapter를 사용하고 전용 Codex 슬롯은 배정하지 않는다.**
CSV 내보내기와 사진 내려받기는 관측 가능한 고정 업무이며 모델의 판단이 필요한 작업이 아니다.
AI가 임의 클릭을 계획하면 인접한 차단/신고/상담 완료 기능의 위험과 재현성 비용이 커진다.
Codex는 개발·장애 원인 분석에만 사용한다. 실제 UI에서 검증한 label/DOM·채널/방 identity를
고정된 동작으로 구현하고, 일치 개수·현재 방·다운로드 결과가 예상과 다르면 `UI_CHANGED` 등으로
멈춘다. 추측 클릭·일반적인 브라우저 명령 실행 도구·메시지 입력/전송 경로는 추가하지 않는다.
이는 기존 ‘운영 수집·질문 구성·PDF에 AI를 쓰지 않는다’는 결정을 유지한다.

### 코드 수집과 전용 Codex 슬롯의 비교·적용 범위

사용자는 사진 확보 성공 여부와 별개로 두 방식을 비교하고 EOM 원칙에 맞게 정리하도록
요청했다. 현재 판단은 **고정 코드 수집을 계속 구현하고, 운영 전용 Codex 슬롯/프롬프트를
추가하지 않는 것**이다. 이는 실제 전체 방 자동 수집이 검증됐다는 결론은 아니다.

| 판단 기준 | 기존 고정 코드 경로 | 전용 Codex 슬롯을 수집자로 쓰는 경로 |
| --- | --- | --- |
| 반복 업무 | 확인한 방 열기·내보내기·다운로드·순회에 한정 | 동일 동작에 모델 판단·결과 검증·사용량 관리가 추가됨 |
| 위험 동작 | 코드에 없는 클릭/키 입력 경로를 만들지 않음. 검증된 selector 불일치는 중단 | 전용 프롬프트만으로 오클릭·전송 금지를 강제할 수 없어 결국 같은 실행 guard가 필요함 |
| 재시도 | 원래 command/fence/수신 receipt와 publication을 재조회 | 모델의 새 판단이 원래 요청과 같은 실행인지 별도로 입증해야 함 |
| UI 변경 | `UI_CHANGED`와 확인된 관측을 남기고 점검 | 화면 해석이 가능하더라도 새 selector의 운영 검증을 대체하지 못함 |
| 책임·유지보수 | 기존 Catalog/Orchestrator/collector/Artifact/PDF owner를 사용 | 별도 슬롯·프롬프트·모델/추론 설정·출력/권한 검증을 추가 관리해야 함 |

전용 모델이 필요한 의미 판단 업무는 현재 요구에 없다. 질문 후보는 기존 결정론적 규칙으로
구성하고 애매한 분할·학생 연결·사진 누락은 명시적으로 검토 대상으로 남긴다. 이 기능을
GraphRAG/문항 출제 슬롯이나 외부 LLM에 연결하지 않는다. 개발 중 Codex가 실제 화면을
관찰한 사실도 무인 운영용 selector/권한 검증을 통과한 것으로 취급하지 않는다.

운영용 adapter의 동작 집합은 방 열기/닫기, 내보내기 메뉴, 파일 내려받기와 스크롤뿐이다.
실제 확인한 대상의 종류·일치 수·채널/방 context·다운로드 결과를 매 단계 검사해야 하며,
불명확한 경우 다른 위치를 추측해서 누르지 않는다. 메시지 편집/전송·차단/신고·상담 완료·
담당자/설정 변경은 집합에 넣지 않는다. 로그인/2단계 인증은 기존 사용자 원격 화면 경계에
남긴다. 현재 MANUAL driver의 download 관측은 입력/클릭 메서드를 노출하지 않으며,
실제 자동 selector·전체 방 목록·사진 occurrence 실증 전 AUTO는 계속 비활성이다.

확보하지 못한 사진이나 불명확한 메시지 연결은 incomplete로 보존하고, 텍스트와 사진을
억지로 짝짓거나 모델이 추측하게 하지 않는다. 코드만으로 필요한 UI identity를 관측할 수
없는 경우에는 그 제약을 보고하고 수동 확인 경로를 쓴다. 전용 AI 슬롯으로 조용히 우회하지 않는다.

### 로컬 수신물의 owner 입력 경계

1. 책임: 기존 Orchestrator OS adapter가 browser의 로컬 수신 파일을 읽고, 기존 Catalog
   source/media publisher에 넘길 검증된 입력을 만든다. 새 수집 서비스/큐/registry는 없다.
2. 정본: 로컬 수신물은 untrusted staging이다. canonical source는 별도 실제 권한·방/메시지
   정합 검증 후 기존 Artifact owner가 발행한 revision이다. 읽기 성공은 admission 권한이 아니다.
3. identity: 기존 `manual-download-v1`의 capture/profile/browser-run/fence/page-instance와
   payload SHA를 재사용한다. page instance나 filename을 provider room/message ID로 쓰지 않는다.
4. resolution: exact fence와 run marker, STARTED/terminal receipt의 identity, 고정 member,
   UID/GID/mode·종류·단일 link·symlink 없음·크기·SHA를 검사한다. 경로 입력은 서버 설정과
   검증된 ID로만 구성한다. payload나 receipt가 없거나 바뀌면 명시적으로 거부한다.
5. access/구조: capture ID의 직접 directory lookup과 bounded streaming/read다. O(file bytes),
   최대32MiB 입력을 owner materialization 경계에서 한 번 읽는다. 반복 목록 탐색이나 재다운로드는 없다.
6. persistence/concurrency: DB와 worker output은 변경하지 않는다. 읽기 FD 전후 metadata를
   대조하고, consumer는 반환된 고정 receipt/bytes를 사용한다. source 수락은 기존 짧은 CAS와
   publication 멱등 계약이 담당하며 이 reader가 claim·권한·성공 상태를 만들지 않는다.
7. dependency: pure 계약 → Orchestrator filesystem adapter → Catalog application 방향을 유지한다.
   Catalog가 collector private module을 import하거나 worker가 Catalog/NAS를 호출하지 않는다.
8. failure/retry: 미완료/FAILED·다른 run/fence·변조·위험한 파일은 읽기 오류다. 같은 검증된
   capture를 다시 읽을 수 있지만 재클릭/새 capture 생성/과거 FAILED 재해석은 하지 않는다.
9. 단순 대안: 임의 경로와 `read_bytes()`만 넘기면 잘못된 실행·완료 전 파일·위험 경로를
   구별하지 못한다. 기존 OS file 검증과 작은 수신 계약을 확장하며 범용 storage layer는 만들지 않는다.

MANUAL 세션이 종료되어도 이미 RECEIVED인 수신물은 검증할 수 있다. 이것은 세션 만료 뒤
자동 수집을 허용하거나 현재 owner/source 권한 확인을 생략하라는 뜻이 아니다. 실제 사진은
메시지별 관측과 연결하고, 남은 사진을 확보하지 못하면 incomplete로 보존한다.

### 다운로드 순간의 제한된 DOM 관측

실제 CSV는 blob 다운로드이고 사진은 방별 읽기 URL에서 CDN으로 redirect한다. 파일명과
page instance만으로 메시지 occurrence를 알 수 없으므로, 기존 MANUAL download receiver가
같은 download event의 page를 읽어 별도 `page-observation.json`을 남긴다. schema를 먼저
정의하며 이것은 untrusted local evidence다. 단순히 저장됐다고 provider identity나 source
권한이 확인된 것은 아니다. 이 관측은 새 명령 queue, 외부 디버그 포트나 범용 JS 실행 API가 아니다.

- exact capture/profile/run/fence/page instance를 기존 STARTED receipt와 연결한다. page URL은
  실제 관측된 `https://business.kakao.com` origin과 query/fragment를 뺀 path만 허용한다.
  download target은 같은 origin path 또는 blob 여부만 남긴다. CDN 서명 URL은 남기지 않는다.
- DOM은 고정된 read-only expression 하나로 한 번 읽는다. 값·cookie/storage·script·HTML·
  event handler·임의 attribute는 읽지 않는다. form/input/textarea/contenteditable/iframe
  subtree는 제외한다. tag/class/role/명시적 label, bounded leaf text, 소수 data identity,
  같은 origin의 link path와 image 존재 여부만 기록한다. image src·CDN URL은 저장하지 않으며
  이 관측은 사진 bytes의 대체물이 아니다.
- 시간은1.5초, 최대2,048개 element·65,536 text code point·최대1MiB JSON이다. 초과/clip은
  `truncated`로 표시하며 완전한 관측으로 사용하지 않는다. 페이지 종료·다른 origin·timeout은
  명시적인 UNAVAILABLE이다. DOM 관측 실패 자체로 정상 다운로드 bytes를 버리지 않는다.
  이 제한된 DOM text로 질문 본문을 만들지 않고, 원본 CSV 전체를 기존 parser로 읽는다.
  node index/parent index는 해당 snapshot의 임시 배치 값이며 메시지의 logical identity가 아니다.
- 실제 SDK page가 전달한 결과라도 schema/한계/identity를 확인한다. raw DOM 예외·URL·
  대화 원문은 log로 출력하지 않는다. 파일은 기존 수신 directory의 write-once0640이다.
  기존 file 수신 상태와 FAILED 기록은 바꾸지 않고, disk/receipt 쓰기 실패는 기존 수신 경계에서
  오류로 처리한다. worker는 NAS/DB에 쓰지 않는다.
- 주 access는 download event별 한 번의 bounded DOM 순회와 capture ID lookup이다.
  관측은 O(scanned DOM nodes + emitted text), 최대8,192 node를 검사한다. parent 관계는
  map으로 만들고 전체 DOM 복제·재파싱·주기적인 전체 화면 dump는 하지 않는다.
- 별도 control service나 전용 Codex 슬롯을 여는 대안은 과하다. 기존 receiver의 page callback과
  보호된 로컬 receipt helper를 재사용한다. 실제 DOM/selector 실증 전 자동 클릭·수집은 켜지 않는다.

#### 다운로드 이벤트와 DOM 관측 사이의 화면 이동

`receive`는 SDK download callback 안에서 query/fragment/credentials 없는 page path를
동기적으로 고정한다. 비동기 관측을 시작할 때의 page path, 관측된 document path와 관측 후
page path가 모두 같을 때만 DOM을 수신물에 붙인다. path가 바뀌었거나 일치하지 않으면 기존
`UNAVAILABLE/OBSERVATION_INVALID`로 남기며, 정상 수신 bytes와 원래 receipt는 보존한다.
다른 방 화면을 읽었을 때 재관측·추측 연결·재다운로드로 덮지 않는다.

이는 기존 collector의 관측 adapter가 소유하는 O(1) path 비교다. schema/DB/API·새 registry나
service를 추가하지 않는다. **같은 path 안에서 바뀌는 UI나 방/메시지 identity의 증명은 아니다.**
미래 source 수락은 여전히 실제 provider identity와 occurrence 관측을 별도로 확인해야 하며,
이 검사만으로 capability를 상향하거나 기존 실제 수신물에 DOM을 소급해서 붙이지 않는다.

## 관측한 MANUAL 방을 기존 방 디렉터리에 수락하기

첫 실제 방 등록은 `KakaoRoomService.admit_room`과 기존 admission receipt를 재사용한다.
새 수집 tracker/큐나 범용 승인 service는 만들지 않는다. 방 등록은 CSV/사진 source 수락,
학생 연결, capability 검증, AUTO 활성화와 서로 다른 단계다. DRAFT 연결을 fake ACTIVE로
바꾸지 않고, 사용자 확인이 필요한 작은 경로를 명시적으로 `MANUAL_CONFIRMED`로 기록한다.

1. 책임/정본: Catalog의 `KakaoRoomIntakeService`가 실제 현재 owner·COLLECT/ADMIN을 확인하고
   보호된 MANUAL 수신물을 읽어 기존 Artifact owner와 Room application을 연결한다. 원문 DOM/
   수신 receipt는 private Artifact에, canonical room/최초 mapping은 기존 room 테이블에 둔다.
2. 입력/identity: schema-first 명령은 binding/lease/capture ID, 사용자가 확인할 channel/room
   provider key, 표시 이름과 binding version만 받는다. 파일 path·권한·profile/fence·Artifact
   pointer를 클라이언트가 정하지 않는다. provider key는 canonical room ID가 아니며 기존
   room owner가 별도 ID를 발급한다. 이름으로 방/학생을 합치지 않는다.
3. 근거: actual SDK download target에서 관측된 `/api/profiles/<channel>/chats/<room>/…/image`
   구조와 document의 channel path가 맞아야 한다. query/서명 URL·filename은 join key가 아니다.
   현재 확실히 관측하지 않은 문서의 room URL suffix나 selector는 추측하지 않는다. 그 근거가
   없는 CSV/blob/text-only 방은 이 단계에서 IDENTITY_UNAVAILABLE이며 최종 제품의 남은 의존이다.
4. 수신 접근: 현재 operator의 새로운 유효 세션으로 자기 소유 과거 capture를 확인할 수 있다.
   이것은 원격 화면을 다시 여는 권한이 아니다. remote `_owned`/TTL/session 일치 규칙은 그대로다.
   원래 lease의 owner/binding/fence·실제 browser 관측 및 capture 시각을 확인하며 ENDED/실패
   이력은 수정하지 않는다. 과거 VNC의 30초 grant를 현재 원격 접근 권한으로 재사용하지 않는다.
5. materialization: 기존 Orchestrator reader로 원래 payload·receipt·DOM의 hash/종류/UID/GID/
   mode를 검사한다. room proof는 원래 receipt/관측 bytes를 pointer와 SHA로 연결한 작은 값이다.
   새 JPEG 복사·재다운로드·NAS writer는 없다. 질문 본문은 나중에 원본 CSV에서 만든다.
6. 저장/동시성: existing Artifact publication의 같은 owner/binding/key를 재사용하고, 마지막
   `admit_room` transaction에서 actual source callback과 현재 ACL/lifecycle을 재검사한다.
   canonical channel 고정에는 immutable `kakao_manual_channel_pins` 한 테이블만 추가한다.
   owner+binding unique/FK와 evidence Artifact FK로 첫 channel identity를 고정한다. 같은
   binding의 다른 channel은 명시적으로 거부하며 전환은 다른 binding의 별도 작업이다.
7. access/복잡도: owner/binding/lease/capture의 indexed lookup, 기존 admission key lookup과
   bounded 파일 읽기다. 첫 수락 O(bytes), 완료 재조회는 작은 canonical proof만 해석하고
   원본 payload를 다시 hash/read하지 않는다. node/대화 전체 검색이나 N+1은 없다.
8. transaction: 긴 file I/O·Artifact 발행 중 DB lock을 잡지 않는다. 방의 기존 intent/binding
   잠금 뒤 channel-pin intent를 직렬화하고 pin과 room/admission을 한 transaction에 채택한다.
   source 발행 후 중단은 같은 key/publication으로 이어가고 실패를 성공으로 바꾸지 않는다.
9. replay: 기존 room admission의 exact evidence를 찾아 실제 owner/원래 명령/hash·source 접근을
   다시 검증한다. 완료본은 worker staging이 정리된 뒤에도 canonical Artifact로 재조회한다.
   확인 전에 바뀐 binding version은 거부하되 이미 완료된 receipt는 이후 policy edit로 바꾸지 않는다.
10. 계층: HTTP/CLI가 invariant를 구현하지 않는다. Catalog application → 기존 room/manual
    metadata/read·Artifact/Orchestrator adapter → pure 계약 방향을 유지한다. worker는 이
    테이블·NAS·Identity에 접근하지 않고 이 기능에 Codex 슬롯/AI를 추가하지 않는다.
11. 단순 대안: boolean callback 허용이나 이름/filename 매칭은 근거가 없다. 별도 intake queue와
    다중 command 테이블은 기존 admission/publication receipt와 중복이다. 작은 channel pin만
    새로 두고 나머지는 현재 owner를 재사용한다. 이 절은 source 구현 설계이며 운영 승인 증거가 아니다.

## MANUAL 방 근거에서 수집 capability를 고정하는 최소 owner

1. 책임은 Catalog의 `KakaoCapabilityService`다. 이미 수락된 MANUAL room observation과
   그 source proof를 검증해 기존 worker `CaptureCapability`를 발행한다. 임의 capability JSON,
   worker bool, 사용자 path·adapter hash를 받지 않는다. 현재 actor/ADMIN/COLLECT 검사는 필수다.
2. 정본은 기존 Artifact의 방 관측·원래 수신 proof와 새 capability JSON/verification이다.
   DB에는 불변 수락 한 row만 두고 본문·사진·전체 관측 JSON은 넣지 않는다.
3. capability revision은 owner/binding/idempotency key에 대한 독립 UUID다. 파일 SHA와 다르며,
   Artifact/revision도 별개다. 동일 명령의 발행 중단을 이어가기 위해 UUID5로 예약 identity를
   결정하되 request hash 충돌은 기존 publication과 DB unique로 거부한다.
4. 원래 방 관측·proof의 schema/media/hash와 방·채널 pin·MANUAL lease/fence·시각·현재 권한을
   재검사한다. completed replay는 채택한 Artifact만 읽고 temporary download 파일을 요구하지 않는다.
   바뀐 정책/version은 새 수락 전에 확인하고 과거 완료 receipt를 최신 값으로 바꾸지 않는다.
5. access는 owner/binding/key와 exact capability revision의 indexed lookup, bounded JSON 읽기다.
   `kakao_capability_acceptances` 한 테이블만 추가한다. mutable current/activation head나 새 큐는
   아직 필요 없으며 이후 collection run이 사용할 exact revision을 명시적으로 pin한다.
6. 첫 관측의 검증 비용은 작은 JSON bytes에 선형, metadata lookup은 indexed O(log n)이다.
   동일 수신 JPEG를 다시 복사·decode·hash하지 않고 원래 proof pointer를 worker input 경계에서 해석한다.
   초기 수백 binding·수만 capability revision을 가정하며, 이는 설계 규모이고 현재 운영 수치가 아니다.
7. 파일 발행 동안 DB lock을 잡지 않는다. 현재 scope 확인 → 기존 idempotent publication →
   짧은 owner/key 잠금과 늦은 재인가 → 불변 수락 row 순이다. 같은 key의 동시 요청은 같은 revision이다.
8. worker에는 기존 `capability.json`과 `inputs/manual-room-proof.json` local member만 전달할 수
   있게 한다. 이 절의 owner는 아직 worker를 실행하거나 NAS 경로/권한을 worker에게 주지 않는다.
9. MANUAL proof가 확인하는 것은 채널과 그 방뿐이다. 내부 scope `MANUAL_SELECTED_ROOM`은
   사용자가 확인한 단일 방을 뜻하며 카카오 UI 필터명이나 전체 방 목록이 아니다. CSV 범위·순서·
   시간대·발신 방향·메시지 identity·album·원본 화질·읽음 여부는 UNKNOWN으로 고정한다.
   더 강한 관측은 실제 adapter 실증에 따른 successor이며 임의 request로 상향하지 않는다.
10. 실패/중단은 원래 Artifact와 기록을 보존한다. 첫 수락 중 binding version/권한 변경은
    채택하지 않으며 재발행/새 작업으로 우회하지 않는다. 조회는 실행·activation·로그인을 하지 않는다.
11. 수락된 capability는 **자동 수집 활성화가 아니다**. 기존 DRAFT/NOT_VERIFIED DTO를 고쳐
    ACTIVE로 위장하지 않는다. 완전한 collection owner/원격 실행/실제 UI capability 검증과 guarded
    activation이 남아 있다. 별도 registry framework나 boolean 승인 callback보다 이 작은 owner와
    기존 Artifact/Room/Identity 경계를 재사용하는 방식이 단순하다.

2026-11-16에 열람한 [카카오 공식 채팅 가이드](https://kakaobusiness.gitbook.io/main/channel/run/chat)의
목록 필터 설명은 기간 조건을 최근 대화 시점 기준으로 안내한다. 이를 질문 기간으로 그대로
적용하면 필요한 방을 누락할 수 있다는 것은 설계상 추론이다. 따라서 전체 방 수집과 질문 단위
구성 뒤의 출력 기간 선택을 분리한다. 열람한 가이드에서는 CSV `USER` 열의 발신 방향 의미나
실제 export 범위의 검증 근거를 확인하지 못했으므로, 문서만으로 capability를 상향하지 않는다.

## Collection intent와 공용 profile gate 연결

1. Catalog collection owner가 현재 실제 ADMIN/READ/COLLECT로 단일 방 수집 의도를 접수한다.
   첫 public command는 `KakaoRoomCollectionCreate`다. 이는 전체 방 수집의 대체물이 아니라
   실제 한 방 실증을 위한 첫 단계이며, 전체 목록 수집·주기 실행은 여전히 완료 조건이다.
2. 원본은 기존 Artifact이며 run/task/attempt/browser epoch에는 작은 ID·pin·state만 저장한다.
   새로운 범용 큐나 Job 상태 enum을 만들지 않는다. 처음 선택한 room/capability/policy는 불변이다.
3. 하나의 run이 순서 있는 task를 소유하고 한 번에 하나만 실행한다. browser epoch는 실제
   persistent context의 identity/lifecycle이다. 여러 방의 command가 같은 browser/fence를 사용할
   수 있으므로 `unique(profile,fence)`는 browser epoch에 두고 attempt에 두지 않는다.
4. profile은 기존 `kakao_profile_runtime` 한 gate를 재사용한다. AUTO current-browser pointer만
   추가하고 MANUAL lease와 동시에 소유할 수 없게 한다. DB 예약 뒤 실제 OS 시작/종료는 기존
   Orchestrator adapter가 관측한다. 시간 만료나 DB 예약 자체를 프로세스 실행·종료로 보지 않는다.
5. primary access는 owner/binding/key replay, active run lookup, run별 ordered task claim, exact
   epoch/attempt lookup이다. unique/partial B-tree와 FK를 사용한다. 초기 수천 방/run, 수만
   attempt 이력을 가정하며 본문 list scan이나 N+1은 없다. 상태 집계는 run별 bounded aggregate다.
6. source/파일 I/O 중 DB lock은 잡지 않는다. profile 예약 순서는 binding → 기존 installed-profile
   advisory gate → profile → run이다. 실제 runtime을 관측한 뒤 같은 epoch/pointer를 CAS로 수락한다.
   source 발행은 기존 publication intent를 재사용하며 worker 재실행과 구분한다.
7. background 권한은 원래 HTTP session의 만료와 분리한다. owner는 **저장된 run/task 참조**에서
   읽고 현재 Identity ACTIVE/ADMIN/READ/COLLECT·binding·capability·policy를 재검사한다. worker가
   owner/role/session을 주장하거나 새 OPERATOR ActorContext를 가장하지 않는다. 내부 참조는
   public RPC/worker 입력에서 생성할 수 없다. 공개 요청의 기존 session 검증은 그대로 유지한다.
8. 첫 actual binding/profile owner는 보존한다. 같은 Studio owner가 STOPPED profile로 다른
   자기 binding을 선택할 수 있도록 MANUAL history의 profile FK와 binding FK를 분리한다.
   과거 lease를 현재 binding에 종속시키지 않으며 다른 owner로 profile을 넘기지 않는다.
   actual channel identity는 기존 수락 proof와 매 실행 관측으로 검증하고 이름으로 선택하지 않는다.
9. unknown dispatch/살아 있는 worker는 같은 epoch를 조회한다. 새 browser/attempt를 자동
   생성하지 않는다. 명시적 중단·권한 상실은 profile을 붙잡은 채 종료 관측을 거치며 FAILED는
   보존한다. 이미 검증된 local output의 발행 복구와 실제 재수집 retry는 다른 경계다.
10. 계층은 기존 API → Catalog application/state → typed contract, Orchestrator OS adapter다.
    worker는 local command/result만 사용한다. 새 browser service나 Codex 슬롯을 추가하지 않는다.
11. 더 단순한 run row 하나에 모든 방/프로세스/attempt를 덮어쓰면 재개 위치와 실제 프로세스
    identity를 잃는다. 반대로 room마다 브라우저를 재시작하는 구조도 불필요하다. 작은 run/task/
    attempt/epoch 관계만 두고 실제 UI selector·source 수락·전체 방 실행은 각 단계에서 검증한다.

### 0091의 첫 구현 범위: 수집 의도와 방별 checkpoint

`collection-intent-v1` schema를 먼저 정의하고 `KakaoCollectionService`가 현재 실제 API
actor의 ADMIN/READ/COLLECT·binding/room 권한으로 한 방의 의도를 접수한다. 실제 수락된
capability owner의 canonical proof를 DB lock 밖에서 해석한 뒤, 같은 방·scope·설치 adapter를
확인한다. 짧은 owner/key → binding → room transaction에서 늦은 권한/version을 다시 확인하고
run과 첫 QUEUED task를 함께 저장한다. 첫 단계의 scope는 MANUAL_SELECTED_ROOM이며 전체
방 inventory의 대체물이 아니다. 실제 수집 활성화·브라우저 실행·정본 수락 권한을 만들지 않는다.

DB에는 `kakao_collection_runs`와 `kakao_collection_tasks` 두 작은 metadata 테이블만 추가한다.
run은 원래 request/version·policy hash·capability revision·adapter pin·owner를 보존하고
current state/version만 이후 갱신할 수 있다. task는 방/순서 identity를 보존한다. 기존 room/
capability/policy FK, same-key unique, nonterminal binding partial unique와 (run,state,ordinal)
인덱스를 사용한다. deferred 초기 task guard가 run만 저장되는 것을 막으며 terminal row·원래
pin·순서의 UPDATE/DELETE를 거부한다. 본문/사진/큰 JSON·NAS path·인증정보를 넣지 않는다.

접근 패턴은 indexed exact run/key lookup·방별 중복 차단과 정렬된 checkpoint다. 수락/재조회는
고정 개수의 indexed metadata 조회이며 첫 capability 해석만 bounded JSON bytes에 선형이다.
초기 scale은 연결당 수천 방·수만 attempt를 가정한다. 같은 요청 replay와 상태 GET은 이미
수락된 capability를 새 파일로 발행하거나 브라우저를 실행하지 않는다. 요청 body가 다르면
conflict이고 다른 key의 unfinished run은 명시적 pending 오류다. 더 단순한 process-local dict는
재시작/동시 접수에 부족하며, 별도 command table/queue는 원래 run receipt와 중복이라 만들지 않는다.

`read_background_intent`는 오직 trusted owner composition의 **준비용 metadata read**다.
owner는 저장된 run에서 읽고 Identity의 현재 ACTIVE/ADMIN/READ/COLLECT를 재확인한다.
원래 HTTP 세션의 만료를 무시한 새 ActorContext/session을 만들지 않으며, public 조회는 계속
유효한 현재 session을 요구한다. 계정/권한 철회·retired binding/room·정책 변경·adapter 불일치·
terminal run은 신규 준비를 거부한다. 과거 receipt는 최신 정책/adapter로 바꾸지 않는다.

이 metadata에는 actual attempt/profile fence·원본 source authority가 없다. 전체 capability
evidence closure의 byte materialization/재인가는 실제 실행·수락 직전에 기존 owner가 수행해야
한다. **이 read만으로 browser launch/source admission을 허용하면 안 된다.** 기존 공용 profile
gate의 AUTO 소유, 실제 epoch/attempt, guarded activation과 full inventory·주기 실행은 다음
구현이다. 이 첫 단계가 검증돼도 DRAFT/NOT_VERIFIED·AUTO 비활성은 그대로다.

### 다음 연결: 공용 프로필과 실제 collection browser epoch

- 기존 `kakao_profile_runtime`을 단일 gate로 유지한다. collection browser epoch 한 테이블과
  profile/run의 current pointer만 추가한다. worker task/attempt, source authority나 별도 queue를
  이 record로 대체하지 않는다. epoch는 process lifetime, task는 수집 작업 identity다.
- worker가 받는 고정 입력은 기존 `ProfileFence` schema를 재사용한다. owner 간 intent/
  running/closure 관측은 새 `collection-browser-v1`의 작은 typed metadata이며 public/worker가
  보낸 bool을 authority로 받지 않는다. 실제 OS 관측 callback은 필수이고 lock 밖에서 실행한다.
- same-owner의 다른 binding 전환을 위해 MANUAL history의 (owner,binding,profile) FK를
  (owner,profile)와 (owner,binding)로 분리한다. 과거 lease/수신물은 수정하지 않는다. 실제 정지·
  profile lock 해제 확인 전이나 다른 owner로는 바꾸지 않는다. 채널 identity는 별도 관측이다.
- binding → 기존 installed-profile advisory gate → profile → run → epoch 순서로 잠근다.
  시작 예약은 AUTO 소유와 증가 fence를 원자적으로 고정한다. 재조회는 같은 epoch를 반환하고
  불명확한 이전 dispatch/이미 CLOSED인 원래 run을 새 browser로 자동 재생성하지 않는다.
- (profile,fence), (run,epoch_number), non-CLOSED profile의 partial unique와 exact current
  FK를 사용한다. 접근은 indexed lookup이며 큰 payload·원문·사진·인증정보는 저장하지 않는다.
  수천 방을 같은 browser lifetime에서 순회할 수 있고 room마다 browser를 재시작하지 않는다.
- PREPARING/RUNNING/STOPPING/CLOSED와 version으로 관리한다. running 관측의 실제 boot/
  invocation/PID/monotonic start가 고정되고, stop timeout은 CLOSED가 아니다. 종료 callback의
  정확한 실행·gateway 정지·profile lock 해제·freshness를 확인해야만 profile을 반환한다.
- closure와 cleanup은 이미 접수된 epoch로 수행하므로 계정/정책 철회 뒤에도 실제 프로세스를
  정지할 수 있다. 새 실행 준비/수락은 현재 accepted run의 권한·policy/adapter pin을 재검사한다.
  HTTP session이나 worker actor를 가장하지 않는다. terminal epoch와 과거 실패는 보존한다.
- epoch 예약/시작만으로 상위 run이나 문항 수집이 완료되지 않는다. parent run의 수집 상태는
  실제 command/task owner가 관리한다. browser 종료는 current pointer만 반환하며 자동 retry·
  source 수락·guarded activation은 후속 경계다. DRAFT의 예약도 AUTO 실증/활성화가 아니다.
- 이 claim은 실제 방→CSV/사진→질문/PDF 경로를 위한 선행 저장 경계다. 현재 core/remote와
  같은 OS adapter를 재사용하고, 실제 selector나 원격 브라우저를 fixture 근거로 활성화하지 않는다.
- process-local bool lock이나 두 번째 AUTO 전용 mutex는 재시작/MANUAL 경합에 부족하다.
  반대로 browser record에 방별 result를 복제하거나 새 runtime service를 만드는 것도 불필요하다.
