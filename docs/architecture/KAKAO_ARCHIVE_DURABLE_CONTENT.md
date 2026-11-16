# KakaoTalk: 원본에서 질문·학생별 PDF까지의 저장 연결

상태: **원본·질문·packet·출력 저장 owner의 소스/격리 검증, 공개 연결·분할/병합은 후속**.
실제 카카오 수집·운영 수락 증거는 아니다. 최초 설계 기준 소스는
`4d190c32a01de55a4f19fc1c3697ec48762615d4`이며, 이 문서 작성은 런타임 설치·활성화를 변경하지 않는다.
상위 요구사항은 [전체 명세](KAKAO_CHANNEL_ARCHIVE_STUDIO_IMPLEMENTATION_SPEC.md) §§7–10,
수집 권한은 [수집 실행 경계](KAKAO_COLLECTION_EXECUTION_BOUNDARY.md)를 따른다.

## 1. 책임·범위: 두 owner로 사용자 경로 연결

구현할 경로는 `수락한 원본 → 질문 목록/검토 → 선택한 질문 묶음 → 학생별 PDF/페이지 열람`이다.
다음 두 Catalog 응용 책임만 추가한다. 각각의 테이블마다 서비스·repository·queue를 만들지 않는다.

- **콘텐츠 owner**: 원본 수락, occurrence/첨부 대응, 질문 revision·수정·분할·병합, packet 발행·조회.
- **출력 owner**: exact packet/student 입력의 export 접수·claim·복구·결과 수락·다운로드 권한.

Orchestrator는 로컬 실행·staging을 담당한다. Catalog는 기존 Artifact 서비스로 검증된 결과의 발행을
요청하고 도메인에 채택한다. worker는 DB/NAS에 접근하지 않는다. 새 범용 작업 큐, source registry,
LLM/OCR/Graph/embedding 경로는 추가하지 않는다. 수집 schedule과 물리 purge는 이번 저장 연결의 선행조건이 아니다.

### 기준 소스에서 재사용할 실제 구현

| 이미 있는 경계 | 실제 코드 | 아직 없는 연결 |
| --- | --- | --- |
| 소유자·학생·방·불변 mapping | `kakao_archive_service.py`, `kakao_student_service.py`, `kakao_room_service.py` | 수락한 대화 snapshot의 durable 소속 |
| 원본 재파싱·Artifact 발행 | `kakao_archive_intake.publish_kakao_capture` | publication을 canonical source로 채택하는 transaction |
| 보수적 snapshot 정합 | `kakao_message_alignment.align_kakao_snapshots` | proposal을 occurrence ID와 함께 고정한 decision |
| 후보/편집/packet 순수 규칙 | `kakao_question_rules.py`, `kakao_question_editing.py` | current pointer·revision history·CAS·목록 |
| 질문/packet Artifact 발행 | `kakao_question_publication.py` | 발행 결과의 DB 채택·공개 조회 |
| 학생별 정확한 렌더 입력 | `kakao_render_projection.project_kakao_student_render` | 허가된 packet/원본 resolver |
| 격리 PDF 실행·정지 결과 복구 | Orchestrator `kakao_pdf_execution.KakaoPdfExecutor` | durable export intent/attempt·실제 실행 조립 |
| 검증된 PDF/PNG/layout 발행 | `kakao_pdf_publication.publish_kakao_pdf` | immutable export 결과 등록·인증 다운로드 |

위 Catalog 파일의 기본 경로는 `services/catalog_service/eom_catalog_service/`이다.
현재 정규화 Artifact는 기존 `message-normalization-v1` JSON 계약을 사용한다. 상위 명세의 예시
`messages.jsonl`을 근거로 이미 발행된 JSON을 다른 포맷으로 재해석하거나 두 번째 정규화기를 만들지 않는다.

## 2. 정본과 실제 원본 수락 조건

원본 CSV/사진 및 정규화·대응·질문·packet·출력 manifest는 Artifact가 정본이다.
PG는 owner/소속, exact pointer, 현재 revision, 작은 projection, command/attempt 상태를 보유한다.
`approved=true`, CSV 파싱 성공, worker의 `channel_verified` 주장만으로 source 권한을 만들지 않는다.

**현재 미충족 의존**: DRAFT binding의 수동 로그인 준비는 채널 검증/ACTIVE 승격이나 수집 허가가 아니다.
실제 채널 capability 확인·실행 claim과 연결된 수집 owner/adapter가 아직 없으므로,
다음 내부 수락 함수의 실제 운영 호출자는 아직 연결할 수 없다. 이를 fake ACTIVE나 fixture 업로드로 대신하지 않는다.

내부 `accept_source`에는 현재 actor/owner, accepted room, 고정된 capture command/result·capability
증거 pointer, 실행 attempt/fence 및 mandatory admission-authorizer가 필요하다. authorizer는
worker가 보낸 bool을 검사하는 함수가 아니라 실제로 수락한 실행/권한/room 관측과 exact pin을 대조한다.
결과가 capability보다 강한 원본 품질·방 identity·전체 이력·timezone 증명을 주장하면 거부한다.
이 callback의 구현과 실제 수집 연결 전에는 HTTP source 등록/수집 시작을 활성화하지 않는다.
초기 개발의 synthetic fixture는 disposable DB/Artifact 시험에만 사용한다.

## 3. logical identity·revision·hash

기존 `kakaosnapshotrev_`, `kakaonormalizationrev_`, `kakaomessage_`, `kakaoattachment_`,
`kakaoattachmentrev_`, `kakaoquestion_`/`kakaoquestionrev_`, `kakaopacket_`/`kakaopacketrev_`
형식을 그대로 쓴다. source 수락 revision(`kakaosourcerev_`)은 이들을 연결한 **판단의 revision**이며
raw snapshot 또는 normalization identity의 대체물이 아니다. export ID와 결과 revision도 분리한다.

- 최초 snapshot의 각 row에 occurrence ID를 할당하고 `(snapshot revision, row ordinal)` 대응을 고정한다.
  같은 시각·같은 문장을 두 번 보낸 행은 둘이다. 이전 ID 재사용은 수락한 정합 결정이 있을 때만 한다.
- 새 수집은 이전 source revision을 참조한다. 최신 snapshot이 일부 이력만 보인다고 과거 질문을 삭제하지 않는다.
  ambiguity는 snapshot-only/unresolved로 보존하며 전체 이력의 무중복을 주장하지 않는다.
- 사진 blob은 binding+bytes SHA로 재사용한다. 메시지별 attachment identity/association/품질 판단은
  별개이다. 늦게 온 사진은 새 source/attachment revision이며 기존 confirmed 질문·packet을 바꾸지 않는다.
- 질문 수정은 같은 logical ID의 새 revision, split/merge는 새 logical ID들과 provenance이다.
  학생 표시 이름은 identity가 아니며 기존 student/display/mapping revision을 정확히 pin한다.
- packet은 ordered exact question revisions이다. 나중에 날짜 검색이나 current question 조회로 재구성하지 않는다.

## 4. 필수 pointer와 resolver

모든 영구 파일 참조는 기존 `ArtifactMemberPointer`를 사용한다. source 수락 manifest는 raw/snapshot/
normalization, row→occurrence 대응, 이전 대응 근거, attachment revision→blob pointer와
미확보·미확정 이유를 포함한다. 본문·이미지 bytes와 signed URL은 넣지 않는다.

resolver는 owner/binding/room 소속, lifecycle, revision 존재, schema/media/hash, publication receipt를
검증한다. 실제 파일을 읽을 때 `CatalogArtifactService.open_verified_member` 경계를 재사용한다.
DB 채택 전후 및 멱등 재조회에서도 현재 권한과 pointer를 검사하며 dangling/stale는 명시 오류다.
원문·첨부를 빠뜨려 `FINAL` blocker를 없애거나 latest pointer로 대체하지 않는다.

root가 추가하는 `media-blob-v1`/`kakao_media.py`/`kakao_media_publication.py`를 재사용한다.
blob metadata에는 바이트에 고유한 값만 두고 방/수집시각/파일명/quality 결정을 dedup request에 섞지 않는다.
원본 수정 없이 명시적인 image transform만 기존 renderer에 전달한다.

첫 저장 slice의 공개 응용 경계는 `KakaoSourceService.resolve_question_source(actor, binding, room,
source_revision_id=...)`다. 수락된 exact resolution을 읽고 pinned normalization을 한 번 해석하여
기존 `ResolvedKakaoQuestionSource`에 occurrence·가용 첨부 map을 제공한다. 반환 직전 현재 권한과
Artifact metadata를 다시 검사한다. 이후 질문/packet owner는 같은 요청 안에서 고유 source revision마다
이 함수를 한 번 호출하고 여러 질문에 재사용한다. 자료 재복사, 숨겨진 latest 조회, 새 권한 위임은 없다.

## 5. 접근 패턴과 최소 저장 구조

주 경로는 owner+binding key lookup, 방별 source revision chain, cursor 목록, 질문 CAS,
ordered packet iteration, export concurrent claim이다. 메시지 전문 검색이나 새로운 Graph는 필요 없다.

| 추가 record 제안 | 작은 저장값·관계 | 실제 필요 단계 |
| --- | --- | --- |
| `KakaoSourceHeadRecord` | owner/binding/room, current accepted source revision, version | 첫 source 수락 |
| `KakaoSourceRevisionRecord` | 이전 revision, snapshot/normalization IDs, source resolution manifest pointer, publication job IDs, observed UTC/row count/coverage | 첫 source 수락 |
| `KakaoSourceCommandRecord` | owner/room/key/request SHA, 미리 할당한 source identity·시각, 단계·완료 시각 | source 수락의 멱등 처리만 |
| `KakaoQuestionRecord` + `KakaoQuestionRevisionRecord` | current/version/lifecycle; 불변 manifest pointer·previous·학생/mapping pins·기간/검토/blocker projection | 질문 목록·편집 |
| `KakaoPacketRecord` + `KakaoPacketRevisionRecord` | current/version; 불변 manifest pointer·기간/mode/count·작성자 | 묶음 발행 |
| `KakaoExportRecord` + `KakaoExportAttemptRecord` + `KakaoExportRevisionRecord` | 고정 build key/packet/student, claim/fence/lease/상태; attempt input/result pins; accepted PDF/layout/preview receipt pointer | 출력 접수·복구 |

처음부터 위 표 전체를 migration으로 추가하지 않는다. 첫 구현은 source head/revision/command 3개에 한정한다.
메시지마다 본문 DB row를 만들지 않고 immutable source-resolution manifest가 occurrence registry와
attachment association을 소유한다. 질문 목록에 필요한 작은 값만 question projection에 둔다.
큰 ordered selection/페이지 목록은 manifest 정본이며 JSONB 본문 캐시나 별도 ref_count를 만들지 않는다.

## 6. 자료구조·인덱스

- source head `UNIQUE(owner,binding,room)`; revision `UNIQUE(binding,room,source_revision_id)` 및
  같은 소속의 previous/head composite FK, Artifact revision/publication Job FK. snapshot/normalization ID는
  대응하는 pinned manifest와 함께 검증한다(아직 없는 snapshot 전용 DB table을 FK 대상으로 가정하지 않는다).
  source revision은 append-only, current만 CAS로 바꾼다.
- command `UNIQUE(owner,scope,idempotency_key)` + request hash. 기존 `lock_kakao_intent`를 재사용한다.
- 질문 목록 B-tree `(owner,binding,student_id,first_student_at_utc,question_id)`와
  `(owner,binding,room_id,question_id)`; 실제 검토 상태 필터의 query plan을 보고 필요한 인덱스만 추가한다.
  page cursor는 정렬값+ID이며 null time 질문은 별도 미확정 필터로 조회한다.
- revision의 logical parent/owner/binding은 composite FK로 보호한다. packet의 ordered refs는
  manifest에서 map/set으로 검증하고 필요한 exact revision을 한 번의 batch 조회로 해석한다.
- export `(owner,binding,build_key)` dedup 및 `UNIQUE(export_id,attempt_number)`;
  진행 상태/claim 가능 시각 partial index. 같은 export에 살아 있는 attempt는 하나이다.

## 7. 복잡도·규모·materialization

기존 bound(원본 CSV 32 MiB, normalization 행 100,000 이하, packet 200 questions 이하)를 유지한다.
처음 원본 수락·정합은 `O(M+P)`(현재/이전 메시지 수), row·attachment lookup은 map으로 `O(1)` 평균이다.
질문 목록은 indexed `O(log Q + page_size)`이며 목록마다 원본 JSON을 파싱하지 않는다.
질문/packet 본문 해석은 **고유 normalization별 한 번** 검증/파싱 후 선택 block들을 처리한다.
출력 입력 materialization은 고유 bytes 수에 비례하며 canonical 파일을 packet마다 다시 복제하지 않는다.

큰 원본은 최초 parse 비용이 남는다. 이 단계에서는 새 영속 cache/검색 엔진을 추가하지 않는다.
요청별 총 source bytes/질문 수/출력 bytes budget을 검사하고 초과는 명시 거부한다. 조용히 일부를 잘라 성공시키지 않는다.
100,000행 fixture와 200질문 공통 source fixture로 parse 횟수·메모리 bound·query 수를 확인한다.
raw 메시지 무제한 목록 API는 첫 slice에서 제공하지 않는다. 필요할 때 exact member에 대한 seek index를
별도 materialization으로 설계하며, 현재 JSON 전체를 행별로 반복 파싱하는 구현은 만들지 않는다.

## 8. transaction·동시성

공통 순서는 다음과 같다. 파일/프로세스 I/O 중 DB transaction과 row lock을 유지하지 않는다.

1. 현재 actor/owner를 검증하고 intent key를 잠근다. request SHA·현재 source/question/packet의 expected
   revision/version을 검사하고 서버 발급 결과 IDs·작성 시각을 작은 intent로 예약한다.
2. transaction 밖에서 exact 원본/manifest를 해석하고 기존 순수 함수로 결과를 만든다. 동일 intent 재개 시
   IDs/시각과 occurrence 할당이 동일하도록 저장된 할당 기준을 사용한다. 본문 hash에서 identity를 만들지 않는다.
3. 현재 권한을 다시 확인하며 기존 Artifact publisher로 불변 결과를 발행한다.
4. 짧은 transaction에서 intent/current 권한/expected pins를 재검사하고 revision·current·receipt를 원자적으로 채택한다.
   CAS 실패 시 기존 current는 유지하고 선발행 Artifact는 미채택 결과로 남긴다.

잠금 순서는 binding → room/source head → 학생(필요 시) → question ID 정렬 → packet/export이다.
기존 학생·방 owner의 순서와 충돌하지 않아야 한다. split/merge는 한 command 안에서 모든 입력 CAS와
신규 질문들 및 입력 `SUPERSEDED` 전환을 함께 확정한다. superseded 원본의 과거 packet 참조는 유효하다.
source 재수락은 기존 confirmed 질문을 덮어쓰지 않는다. 변경 영향은 별도 stale 표시/검토 제안으로 남긴다.
미검토 후보도 provenance 없이 새 원본으로 교체하지 않는다.

## 9. 계층·스키마·응용/API 계획

### 질문 분할·병합 입력 연결

분할·병합은 기존 `split_question`/`merge_questions`를 재사용한다. 화면이 전체 원문,
사진 pointer, 학생/권한/작성자 또는 결과 ID를 다시 제출하지 않는다. 새
`question-compose-v1` 명령은 binding/room과 입력 질문의 exact revision/version,
분할할 block ID 또는 원문 code point 구간만 받는다. 병합 입력 순서는 출력 순서다.
원문은 accepted question/source Artifact이며 명령은 원문을 대체하지 않는다.

Catalog의 `kakao_question_selections.py`가 이미 읽은 질문들을 ID map으로 대조하고
block selector를 기존 블록으로 해석한다. 학생·원문 hash·사진 연결·표시 수정은 입력에서
물려받는다. 부분 text span의 새 block ID는 예약된 결과 질문 ID와 순번에서 만들고
같은 예약을 재실행해도 바뀌지 않는다. UTF-16 위치를 원문 code point로 간주하지 않는다.
표시 문구를 이미 고친 block은 전체를 옮길 수 있지만, 그 표시문 위치를 원문 위치로
추측해 나눌 수는 없다. 사진은 전체 block을 한 번만 옮긴다.

주 접근은 exact ID/version 조회, ordered partition, 누락/중복 검사다. 입력 100질문,
출력 100질문, 질문당 기존 230블록 제한을 유지한다. map/set 구성은 O(B+Q),
기존 source-span coverage 정렬은 O(B log B)이고 추가 공간은 O(B+Q)다.
새 검색·cache·worker·의존성은 필요 없다. 공개 JSON Schema는 선택 입력만 정의하고
owner의 실제 권한 검사·원본 해석·CAS를 대신하지 않는다.

저장 owner는 기존 reserve→Artifact I/O→재인가/CAS 순서를 유지한다. 입력 전체의
current/version을 검증하고 결과 ID/시각을 같은 command에 예약한 뒤 한 transaction에서
새 질문들과 입력 SUPERSEDED를 함께 채택해야 한다. 실패하면 어떤 입력도 일부만
교체하지 않는다. 원래 question revision과 packet 참조·수집 origin의 중복 방지 연결은
보존한다. 두 개의 독립 CREATE 호출로 분할을 흉내 내는 대안은 부분 저장과 재수집 중복을
막지 못하므로 사용하지 않는다. **이 입력 연결만으로 저장/API/GUI가 활성화되지는 않는다.**

저장 확장은 기존 question aggregate 안에 composition command·ordered input·reserved
output의 작은 세 관계만 추가한다. command는 owner/room/key/request SHA와 mapping·시각을
고정하고, 입력은 exact question/revision/version, 출력은 서버 예약 ID만 가진다.
본문·분할 selector·사진 bytes는 DB에 복사하지 않는다. 재시도는 같은 명령 hash와 예약을
사용하며, 결과 manifest의 provenance가 원래 입력을 가리킨다. 완료 command가 작은 receipt다.

원래 source 후보의 origin 세 필드와 `UNIQUE(room,occurrence)`는 유지한다. 조합으로
만든 질문만 source origin 대신 composition output FK를 가진다. 가짜 occurrence를 만들지
않는다. 기존 질문 revision의 단일 command FK는 보존하고 조합 결과에만 별도 output FK를
허용한다(둘 중 정확히 하나). 입력 head에는 `superseded_by_composition_id`를 한 번 기록한다.
이는 current revision을 덮는 변경이 아니라 후속 질문으로 대체됐다는 관계이며, content
resource_version은 그대로다. 이후 편집/재조합은 거부하고 exact 과거 조회·packet은 유지한다.
목록은 같은 indexed page에서 superseded를 제외하고, 원래 수집 origin은 계속 중복을 막는다.

기존 room 잠금 아래 입력 ID 정렬로 CAS하고 모든 출력/입력 대체/command 완료를 한 번에
채택한다. 새 queue·lease는 없다. lookup·정렬은 O(Q log Q), 최대100 입력/출력이며 source
해석은 기존 batch resolver를 재사용한다. command replay UNIQUE, input exact revision FK,
output 예약 UNIQUE와 immutable trigger를 사용한다. migration rollback은 composition
이력이 하나라도 있으면 거부한다. 이 변경은 isolated DB에서 먼저 검증하며 현재 MANUAL
운영 연결과 별개다.

공개 조합 명령은 기존 API-peer socket에 추가하는
`catalog-kakao-question-compose-v1`의 한 operation으로 전달한다. released
`catalog-kakao-question-v1` bytes/읽기·사진 의미는 바꾸지 않는다. API/BFF의
`POST /kakao-archive/questions/compose`는 실제 session·EDIT 권한과 같은 idempotency key를
전달한다. 각 입력의 exact revision/version 전체가 하나의 CAS이므로 하나의 HTTP ETag로
병합의 모든 부모를 대신하지 않는다. owner가 요청한 입력·출력 수·소속을 대조하고,
응답 transport도 그 상관관계만 검사한다. 새 DB/queue/worker authority는 없다.
공개 요청의 byte 상한은 기존 Catalog frame, 질문 수/분할 수는 기존 bounded DTO를 사용한다.
비용은 기존 조합 owner와 source batch 해석에 선형이며 공개 adapter에서 원문을 재구성하지
않는다. 기존 application construction에 같은 Artifact/source owner를 주입한다.
raw Artifact 쓰기나 독립 CREATE를 Web에 노출하는 단순 대안은 권한·원자적 대체와 중복 방지
경계를 깨므로 사용하지 않는다. RPC/API/BFF의 소스 연결과 운영 활성화는 구별한다.

### 화면의 질문 나누기·합치기 연결

화면은 위 `/questions/compose`와 현재 질문 v1 projection을 재사용한다. 원문 span의 절대
offset을 v1이 제공하지 않으므로 첫 UI는 **메시지/사진 block 사이**에서 나누고, 합치기는
사용자가 고른 질문의 명시적 순서를 전달한다. 문자열 내부 offset을 0부터 추측하거나
표시문을 원문으로 다시 등록하지 않는다. block 내부 구간 편집은 exact source selection을
노출하는 별도 후속 계약이 필요하다.

별도 JS module이 작은 입력 ID/revision/version·block ID·미확정 요청 key만 관리한다.
정본·중복 방지·학생/방 범위·원자적 저장은 기존 Catalog owner 책임이다. 배열 순회와
ID set/map으로 최대100개 질문/230개 block을 처리하며 새 DB/queue/cache는 없다.
응답 유실은 같은 key/body로 확인하고, 저장 완료 후 목록 갱신만 실패한 경우에는 저장된
출력 열기만 재시도한다. 새 POST로 다시 조합하지 않는다. 같은 owner의 화면 이동 중
미확정 intent를 보존하고 owner 변경 시 제거한다. 원문/비밀값을 browser storage에 넣지 않는다.

순서는 **JSON Schema → frozen DTO → owner/ORM → Catalog RPC → API/BFF → GUI**이다.
기존 `question-manifest-v1`, `question-edit-v1`, `question-packet-v1`, worker render 계약은 재사용한다.
source-resolution/source-admission, 콘텐츠 command/page, export request/status/output receipt에 필요한
새 계약만 추가하고 canonical/mirror/hash를 함께 검증한다. worker에는 Catalog actor/DB model을 넘기지 않는다.

| owner 인터페이스 제안 | 공개 연결 |
| --- | --- |
| `accept_source(actor, admission, *, idempotency_key)` | **내부 전용**. 실 수집 권한 owner 연결 전 HTTP 없음 |
| `get_source(actor,binding,room,source_revision_id)` | owner 전용 조회. arbitrary Artifact ID나 파일 path 입력 없음 |
| `create_candidate_questions` / `get_question` / `list_questions` | accepted source를 사용한 후보 목록·exact revision 상세 |
| `edit_question` / `compose_questions` | 기존 strict edit command와 다중 expected revision/version; 412 CAS |
| `publish_packet` / `get_packet` / `list_packets` | ordered exact question refs, 사용자 KST 기간, DRAFT/FINAL |
| `request_export` / `get_export` / `list_exports` | packet revision + 필수 student + mode/layout; 접수 202 |
| `claim_export` / `accept_export` / `reconcile_export` | 내부 전용. 저장된 intent/attempt/fence에서 권한·실행 pin 도출 |
| `open_export_pdf` / `open_export_page` / `open_attachment` | domain ID+revision을 권한 확인한 뒤 verified stream으로 열기 |

외부 경로는 명세 §10.7의 `/kakao-archive/questions`, `/question-packets`, `/exports`를 따른다.
현재 API의 CommandResult/ETag/Idempotency-Key·BFF CSRF를 그대로 쓴다. generic Artifact download로
우회하거나 다른 owner의 자료를 ADMIN이라는 이유로 공개하지 않는다. private response는 `no-store`이며
NAS 경로/쿠키/본문을 log·URL에 싣지 않는다. GUI는 실제 capability가 생긴 동작만 활성화한다.

### 실제 질문 열람·검토의 공개 연결

기존 API-only Catalog socket에 질문 operation family를 추가한다. 책임은 실제 API actor를
기존 question owner에 전달하고 검증한 결과를 공개 read projection으로 내보내는 것이다.
정본·논리/revision·Artifact/hash는 위 §§2–4 그대로이며 새 DB/registry/queue는 없다.
목록은 기존 indexed metadata page, 상세는 exact question revision과 고유 source 한 번 해석,
사진은 그 질문 revision에 실제 포함된 attachment occurrence로만 연다. 비용은 목록 page와
선택 block/source/file bytes에 선형이다. 원문을 DB나 별도 preview Artifact에 복사하지 않는다.

현재 owner/session/source 권한을 유지하며 사진 FD를 연 뒤에도 closure metadata를 다시
확인한다. browser의 임의 Artifact/member/path·역할·실행 권한 주장은 받지 않는다.
검토 저장은 기존 reserve→I/O→CAS와 같은 key replay를 재사용하며 If-Match를 요구한다.
공개 확인/제외 명령은 서버의 actor/시각으로 기록한다. 기존 내부 EDIT와 사진 품질 수락의
서버 stamp를 구별하며, 브라우저가 actor/시각을 채워야만 하는 버튼은 만들지 않는다.
API/BFF는 transport와 presentation validation만 담당한다. binary 스트림은 기존 verified
member/프록시의 length·SHA 검사 경계를 재사용하며 새로운 파일 서버를 만들지 않는다.
소스 조회 성공만으로 실제 수집 capability나 전체 이력 확보를 선언하지 않는다.

### 학생 묶음·PDF의 공개 연결과 실행

같은 API-only socket에 닫힌 delivery operation family를 추가한다. 기존 packet/export
저장 owner가 정본과 멱등·동시성·현재 권한을 그대로 소유하며 새 DB·공용 queue는 없다.
packet 상세는 저장 descriptor와 exact 질문 참조, 해당 snapshot의 학생별 이름/개수만
반환한다. 학생 표시 이름은 identity가 아니며 PDF 접수는 packet revision과 student ID를 받는다.
출력 상태 조회/목록과 exact 완료 revision의 PDF 읽기는 실행을 시작하지 않는다.

Catalog의 bounded 실행 adapter가 접수된 PENDING export의 기존 단일 승자 claim을 받아
입력을 물질화하고 Orchestrator executor→기존 publisher→export 채택으로 연결한다.
HTTP에는 argv·font 경로·runtime profile·성공 stamp를 받지 않는다. 긴 작업은 DB lock과
요청 수명 밖에서 실행하며 현재 원본 권한을 각 기존 경계에서 재검사한다. 실행 중인
동일 export는 중복 제출하지 않는다. in-process 대기는 작은 실행 힌트일 뿐 정본이 아니며
중단 뒤 PENDING은 동일 접수 replay로 재개하고 RUNNING은 실제 종료/기존 command 확인
후 원래 결과 수락만 복구한다. 실패 이력을 성공으로 바꾸거나 GET에서 재렌더하지 않는다.

목록·idempotency·claim은 기존 indexed lookup/keyset이며 선택/물질화는 O(질문+고유
원본 bytes)다. 실행 힌트는 bounded keyed membership이고 원문·사진을 복제하지 않는다.
API 안의 동기 렌더는 요청 timeout과 장기 작업을 결합하고, 새 범용 scheduler는 기존
owner와 중복되므로 채택하지 않는다. 실제 보호 runtime을 검증하지 않은 구성에서는
PDF 실행만 명시적으로 unavailable이며 저장된 packet 읽기까지 막지 않는다.

PDF runtime은 기존 root 설치 NotoSansCJKkr OTF를 explicit hash/size로 pin한다. 새 font
다운로드·모델 호출·worker 권한 확대는 없다. 0700 workspace 부모는 Catalog의 기본
group이며 attempt의 input/output만 renderer group으로 공유한다. Catalog에 이 좁은
group을 추가할 뿐 renderer를 Catalog/NAS/eom group에 추가하지 않는다. 실행은 별도
명시적 `EOM_KAKAO_PDF_MODE=ENABLED`와 renderer/template/font pins가 모두 있을 때만 켠다.
정지/복구는 exact 고정 unit의 MainPID/state와 실제 absent/empty cgroup을 확인한다.

## 10. 실패·재시도·멱등·출력 수명

### MANUAL 내보내기 파일 수신 — 2026-11-16 실증 후속

1. 책임은 기존 browser driver의 local download adapter다. 사람이 승인해 누른
   내보내기/사진 다운로드를 수신할 뿐 방을 열거나 버튼을 누르거나 원본 수락 권한을 만들지 않는다.
2. 다운로드 bytes는 아직 untrusted local staging이다. canonical source는 기존 Catalog가
   현재 owner/fence와 실제 채널·방·capture 근거를 검증해 발행한 Artifact revision이다.
3. 각 download에 별도 capture ID를 부여하고 실제 profile/browser run/epoch와 연결한다.
   start/result receipt는 별도 파일로 한 번씩 쓰며 시작 기록을 완료 기록으로 덮지 않는다.
4. 결과는 고정 local member·byte count·SHA와 원래 suggested filename만 가진다. URL,
   cookie·session·인증정보는 받지 않는다. filename은 identity나 경로·메시지 join key가 아니다.
   page instance ID는 browser 안의 창 구분일 뿐 provider room identity가 아니다.
5. 연산은 page별 event subscription, capture ID key lookup, 제한된 진행 파일 관측,
   완료 파일의 한 번 streaming hash/copy다. event 처리에 DOM 전체 스캔이나 DB 조회가 없다.
6. process-local map/set은 실행 중 작업만 관리한다. 보관은 기존 profile 전용 UID가 쓰는
   `/var/lib/eom-kakao/downloads/<browser_run>/<capture>/`와 작은 immutable JSON receipt다.
   부모는 root 설치·setgid control group read-only이며 Catalog가 정식 수락할 수 있다.
7. 파일 하나당32MiB, 한 MANUAL run 최대16건·수락 bytes128MiB, 다운로드 대기60초다.
   incoming 크기도 관측해 넘으면 취소한다. 이는 수락/취소 상한이지 OS disk hard quota가
   아니다. 네트워크/파일 I/O 사이 잠깐의 초과 가능성을 숨기지 않고 temp 파일은 context가 정리한다.
   완료 해시는 O(bytes), 메모리는 고정 chunk, monitoring은 O(진행 파일 수)이며 수가 제한된다.
8. DB transaction/새 queue는 없다. 이미 supervisor가 가진 profile flock과 실제 run fence를
   재사용한다. 중단 시 먼저 download cancel/reap와 FAILED receipt, 그 뒤 context를 닫는다.
   완료 payload는 context 종료 후에도 남고 완료 receipt 없는 파일은 수집 성공이 아니다.
9. pure schema/model은 기존 worker-contract package, SDK·파일 adapter는 collector에 둔다.
   worker는 NAS/DB를 읽거나 쓰지 않는다. 기존 설치 layout/unit의 writable path만 좁게 추가한다.
10. 같은 download event는 하나의 task만 만든다. 새 실제 내보내기는 새 capture이며
    기존 실패/부분 bytes를 성공으로 바꾸거나 filename으로 dedup하지 않는다. 종료된 run을
    재시작해 클릭을 재생하지 않는다. 이후 owner admission은 기존 source 멱등 계약을 사용한다.
11. `accept_downloads=True`만 켜는 대안은 context 종료 때 파일이 사라지고 파일/방 연결과
    실패 증거가 없다. 별도 download server나 AI 판독은 필요 없으며 도입하지 않는다.

이 MANUAL 보관은 CSV·사진 자동 수집/정합 또는 accepted source의 대체 증거가 아니다.
실제 버튼 다운로드와 격리 fixture 다운로드는 별도 검증한다. 기본80%/window manager 개선은
별도 display 책임이며 다운로드를 위해 현재 profile/비밀번호를 수정하지 않는다.

### 채널 선택은 데이터이며 특정 채널을 코드에 고정하지 않는다

사용자가 다른 채널로 바꿀 수 있어야 하므로 채널 이름/ID를 조건문·기본값·수집 selector에
하드코딩하지 않는다. UI의 이름은 identity가 아니다. 동명 연결은 같은 목록 안의 번호로
구분하지만 실제 요청은 기존 exact source-binding ID를 그대로 사용한다. 표시 번호는
권한이나 영구 identity가 아니며 전체 row를 map으로 한 번 집계한다.

현재 primary profile의 owner/binding fence는 서버 저장 설정이다. 이를 현재 채널명으로
대체하거나 DB row를 수동 변경해 우회하지 않는다. 향후 다른 채널로 전환하는 use case는
현재 연결이 실제 STOPPED이고 유효 lease·process·lock이 없을 때 같은 owner의 명시적
선택으로만 수행한다. 과거 lease/수집/질문의 binding과 실패 기록은 보존한다. 현재
profile/lease 복합 FK는 assignment history successor와 대조해야 하므로 단순 UPDATE를
새 채널 전환 기능이라고 간주하지 않는다. 이 확장 경계는 실제 첫 방 수집 뒤의 후속이며
아직 구현 완료/활성화로 선언하지 않는다.

START의 명시적 PROFILE_UNAVAILABLE 거절은 lease를 만들기 전의 거절이다. UI는 선택을
수정할 수 있게 하되 응답 유실·timeout은 기존 key/body를 유지한다. 어느 경우에도
다른 owner로 재요청하거나 서버 배정을 자동 변경하지 않는다.

- 같은 intent+같은 request는 원래 결과/진행을 반환한다. 다른 내용은 409이며 새 ID로 우회하지 않는다.
- Artifact 발행 뒤 DB 채택 전 중단은 publication key/receipt를 재검증하여 **같은 결과를 채택**한다.
  기존 `CatalogArtifactService.commit_file_set`의 COMMITTING 복구를 재사용한다.
- export는 `QUEUED → RUNNING → PUBLISHING → COMPLETED`로 구분한다. 현재 권한/실행 환경이
  미준비면 시작하지 않고 이유를 표시한다. retry는 새 attempt이며 과거 FAILED attempt는 보존한다.
- worker timeout은 실패/미실행 증거가 아니다. 원래 attempt의 정지·완료 파일을 확인하고
  `KakaoPdfExecutor.recover_finished`로 검증한다. 정지 미확인 시 새 attempt를 띄우지 않는다.
- 출력 build key는 binding/packet revision/student/subset hash/mode/layout/renderer release/font/options를
  포함한다. 다른 학생이나 DRAFT 결과를 FINAL로 재사용하지 않는다.
- 정확한 학생 subset을 `packet_student_subset`으로 resolve하고 기존 render projection/executor/publisher를
  연결한다. `page_count == subset questions` 및 각 페이지/이미지 layout receipt를 검증한 후만 수락한다.
- 명세 §9.3에 따라 날짜 미확정 질문도 `DRAFT`에서는 머리말에 **날짜 확인 필요**를 표시해 출력한다.
  worker 입력의 `header_date=null`을 그대로 유지하며 오늘 날짜·수집 시각으로 추정하지 않는다.
  `FINAL`은 기존 `TIMEZONE_UNVERIFIED` blocker와 worker 입력 검증에서 계속 거부한다.
- session 기반 현재 권한은 기존 `authorize_kakao_actor`/저장 intent용 identity lookup으로 확인한다.
  만료된 session을 인증된 것으로 간주하지 않는다. 장기 schedule용 권한 수명은 별도 collector owner가
  정의해야 하며 이 기능이 worker ADMIN impersonation이나 무기한 session을 추가하지 않는다.
- rename/remap은 기존 packet의 표시를 바꾸지 않는다. 현재 source 접근 철회/삭제는 과거 PDF도 막는다.
  기존 packet이 참조한 immutable 기록과 현재 접근 권한을 서로 혼동하지 않는다.

## 11. 더 단순한 대안과 채택하지 않는 이유

파일만 저장하고 매번 전체 CSV를 다시 묶는 방식은 수동 수정·stable occurrence·이력·멱등을 잃는다.
반대로 메시지/첨부/모든 상태별 service·table·queue를 만드는 방식은 지금 필요한 연결보다 크다.
따라서 Artifact manifest와 작은 indexed current/revision/intent로 연결하고 기존 검증 함수를 호출한다.
원본부터 PDF까지 한 HTTP transaction으로 처리하지 않는 이유는 I/O 중단·권한 철회·재전송을 구별해야 하기 때문이다.

## 구현 순서와 완료 증거

1. **첫 slice: durable source admission/read.** source-resolution/admission schema, DTO, 위 3개 source/command
   table와 필요한 migration, mandatory 권한 adapter, existing capture/media publication 연결 및 exact read.
   source caller가 아직 연결되지 않았다는 상태를 유지한다. runtime 설치/selector/채널 확인은 별도 실제 의존이다.
2. **질문 owner.** accepted source → 기존 turn_v1 → 최초 UNREVIEWED revision → 목록/상세/확정·제외·수정.
   이어서 동일 binding/room/student의 split/merge를 연결한다. owner API/GUI는 이 안정된 DTO에 병렬 연결한다.
3. **packet owner.** 선택 목록·기간·답변 포함 설정 → exact immutable packet. 한 packet의 두 학생을 각각 해석하고
   순서·미확정 blocker·학생 표시 pin이 원본과 일치하는지 확인한다.
4. **출력 owner.** 접수/claim → 기존 local renderer → Artifact 발행·수락 → 같은 export의 PDF/페이지 조회.
   새 렌더 없이 재조회·응답 유실 복구. 마지막에 실제 수집 1방 → 검토 → 학생별 PDF 다운로드까지 연결한다.

검증은 source/schema parity·잘못된 pointer/권한·같은 문장 중복 보존·unknown/timezone/missing 첨부를
먼저 고정한다. disposable PostgreSQL에서 같은 key 동시 수락, competing CAS, publication 이후 중단,
split/merge 원자성, immutable history, revoke/rename/remap 경쟁, export 중복 claim/중단/재조회와
작은 DB payload를 검사한다. 동일 packet의 학생 2명·권한이 다른 owner 2명·원본 사진 포함 fixture로
API/BFF/Chromium→PDF/PNG 경로를 확인한다. 운영 원본과 실제 학생 PDF 확인 전에는 live PASS로 보고하지 않는다.

### 질문 owner의 첫 저장 연결

기존 question-manifest/edit bytes는 유지하고 `question-store-v1`에 생성·변경 요청과 작은
저장 descriptor를 정의한다. 최초 생성은 accepted source revision과 후보 ordinal을 명시한다.
원본 해석은 공개 `resolve_question_source`를 사용한다. source의 첫 학생 occurrence를 origin으로
기록하되 그것을 question ID로 사용하지 않는다. 같은 방·규칙·origin을 새 수집이나 다른 key로
다시 생성하면 기존 질문을 덮어쓰는 대신 명시적 중복 오류를 반환한다. 새 증거의 반영 제안과
분할/병합은 후속 명령이며 이 중복 방지 자체를 source stale 처리 완료로 간주하지 않는다.

저장은 question head/revision/command 세 테이블이다. head의 origin과 최초 source FK는 유지하고,
revision에는 작은 review/time/student/mapping projection과 manifest pointer만 둔다. 추가 source는
manifest의 normalization pins를 source의 기존 unique index로 batch resolution한다. source 본문,
선택 block, 사진은 DB에 복제하지 않는다. 목록은 방별 `(owner,binding,room,question_id)`와
전체 `(owner,binding,question_id)` B-tree keyset이며
본문 상세만 파일을 읽는다. 기간·학생 검색이 실제 붙을 때 해당 composite index를 추가한다.

잠금은 기존 intent → binding → room → question 순서다. CREATE/EDIT reservation이 서버 ID·시각·
mapping pin·expected version을 고정하고, I/O 밖의 publication 뒤 동일 command를 CAS로 채택한다.
재전송은 원래 revision을 반환하고, 현재가 나중 버전이어도 최신 결과로 바꾸지 않는다. 새 수정은
현재 mapping을 확인하되 역사적 읽기는 당시 pin을 보존한다. source lifecycle과 현재 권한은
I/O 전후 확인한다. 다른 key의 competing edit는 한 번만 current를 바꿀 수 있다.

이 단계는 컬렉션이나 worker 실행 큐를 추가하지 않는다. 한 후보 생성의 원본 해석 비용은 원본
크기에 선형이다. 추후 수집 owner의 일괄 후보 생성은 고유 source당 한 번 해석한 context를
재사용하도록 연결해야 하며, 모든 후보마다 전체 source를 재해석하는 loop는 허용하지 않는다.
단순 파일 저장만으로는 stable ID·수동 수정·중단 후 같은 결과 채택을 보장할 수 없으므로 작은
reservation과 불변 revision을 사용한다. 최초 저장·exact read·확정/제외/수정의 소스와 임시 DB
검증은 진행했으며, 공개 API/GUI·분할/병합·운영 배포는 아직 후속이다. `resolve_questions`는
ordered exact revision 집합을 indexed batch 조회하고 고유 source당 한 번씩만 해석한다.
같은 원본의 여러 질문/버전을 읽을 때 원본 parse 수가 증가하지 않는 회귀 검사를 둔다.

여기서 저장 명령은 Catalog 내부의 exact 편집 자료다. 공개 편집 API는 사용자 의도와
서버 작성 근거를 구분해야 한다. 특히 사진 품질 수용의 actor/시각은 인증된 operator와
해당 command reservation에서 부여하며, 브라우저가 보낸 `accepted_by`/시각을 새 결정의
권한으로 사용하지 않는다. 이미 수락한 사진 품질 pin의 재표시와 새로운 품질 수용은 구별한다.

### Packet 저장 연결의 구체화

묶음은 기존 packet manifest를 정본으로 하고 작은 head/revision/command 세 record로 연결한다.
CREATE와 REVISE는 별도 typed 명령이다. 선택은 ordered exact question refs, KST 양끝 날짜,
DRAFT/FINAL 및 답변 포함 여부이며 표시 제목은 작은 불변 revision 값이다. 사용자 입력으로
collection completeness를 받지 않고 실제 수집 owner가 연결되기 전 coverage는 UNKNOWN이다.
새 큐·사진 복사·worker 권한은 추가하지 않는다.

예약은 owner/scope/key unique와 기존 intent 잠금을 재사용하고, binding → packet 순서로
짧게 잠근다. ID·시각 예약 뒤 질문 batch resolver와 기존 packet publisher를 transaction 밖에서
호출하고 원래 parent/version을 CAS로 채택한다. 같은 intent는 과거 결과를 반환하고 다른
내용은 충돌이며, 선발행 뒤 중단도 같은 IDs/Artifact를 채택한다. revision/current/version의
composite FK와 불변 trigger가 이 경계를 보강한다.

목록은 owner+binding+packet ID의 B-tree keyset이고 O(log P + page size)다. 상세는 packet
manifest 한 개만 읽고 현재 권한·선택 room·Artifact metadata를 재검사한다. 출력용 student
resolver는 그 학생의 exact subset만 질문 batch resolver에 보내며 다른 학생의 원본을
worker에 넘기지 않는다. 고유 source parse는 요청당 한 번이고 전체 입력 bound를 유지한다.
파일만 발행하는 대안은 저장/새로고침/CAS/중단 복구를 제공하지 못하므로 채택하지 않는다.
