# KakaoTalk 질문 자료의 개념 보강·Studio 편집

상태: **2026-11-17 역할별 PDF·저장/공개 연결은 호환 운영 배포와 합성 fixed-systemd 검증을
완료했다. 실제 수신 자료의 반복 출력·개념 보강 편집/추천은 아직 미완료다.**

기존 [명세](KAKAO_CHANNEL_ARCHIVE_STUDIO_IMPLEMENTATION_SPEC.md)와
[저장/PDF 연결](KAKAO_ARCHIVE_DURABLE_CONTENT.md)을 확장한다. 수집·질문 구성·일반 PDF에
AI를 쓰지 않는 기존 경계는 유지한다. 사용자가 이번에 요청한 Codex 개념 추천은 **별도의
선택적 보강 단계**다. 이 문서가 기존 수집 권한이나 released 계약의 의미를 바꾸지 않는다.

## 1. 확정된 사용자 흐름

사용자는 2026-11-17 다음 두 항목을 선택했다.

- **Studio에서 편집한 뒤 PDF 다운로드.** 이번 범위에서 HWPX 편집본을 새로 만들지 않는다.
- **질문 본문 1쪽 + 필요한 개념 설명 쪽 추가.** 글씨·사진을 무리하게 줄이거나 자르지 않는다.

```text
수락한 대화·사진 → 질문 저장/검토 → 학생·기간의 기존 packet
  → 질문별 ‘관련 개념 추천’(선택)
  → 내부 교재 근거·실제 페이지 확인 → 개념 설명/원문 캡처 초안
  → Studio에서 선택·빼기·교체·순서·설명 편집 → 별도 불변 학습자료 revision
  → 학생별 PDF: 질문1쪽 → 해당 질문의 개념 쪽들 → 다음 질문1쪽 → …
```

원래 질문·일반 질문 PDF는 그대로다. 자동 추천을 쓰지 않고 사용자가 직접 관련 개념을
선택하거나 설명을 작성해도 같은 자료로 편집할 수 있어야 한다. 내용 확장 때문에 카카오
로그인·원문 보관이 Codex 사용량이나 모델 가용성에 의존하게 만들지 않는다.

### 사용자 확인 구성 — 2026-11-17

최종 자료는 **학생 사진(있으면) → 학생 질문 → 조교 사진(있으면) → 조교 답변 →
질문·답변 시기 등의 기록 정보 → 관련 개념 자료**를 구분한다. 질문은1쪽을 기본으로,
답변·개념이 길면 뒤쪽에 붙이며 축소/잘림으로 맞추지 않는다.

사진은 실제 발신 메시지의 occurrence와 역할로 구분한다. 없는 사진 칸을 만들지 않으며,
사진 표식은 있는데 원본을 못 받은 경우는 ‘사진 미확보’다. 발신자·연결 미확정은 UNKNOWN으로
남긴다. 파일명이나 내용이 닮았다는 이유만으로 자동 정합이 검증됐다고 하지 않는다.
조교 답변은 원문을 보존하고, 별도의 교재 근거/검토 의견과 혼동하지 않는다. 시각의 원문
시간대가 미확정이면 임의 UTC/서울 시각 변환을 하지 않는다.

이번 수신 샘플 CSV에는 질문3묶음/답변3건/학생의 사진 표식3개가 있고 원본 사진2장만
확보됐다. 조교의 사진 표식은 없다. 샘플의 사진2장은 직접 내용 대조한 배치이며 provider
메시지 연결 검증을 대체하지 않는다. 교재 원문을 아직 확인하지 않은 샘플에는 ‘개념 보강 전’을
표시하고, 추천 프롬프트를 준비했다는 이유로 교재 캡처가 들어갔다고 보고하지 않는다.

## 2. 화면과 편집 단위

기존 KakaoTalk 질문 검토/만든 자료에서 ‘개념 보강 자료 만들기’를 연다. 새 메뉴·문서 편집
플랫폼을 만들지 않고 기존 질문 선택·학생·기간·packet 열람을 재사용한다.

- 질문 원문·사진은 읽기 전용으로 보여준다. 원문 교정은 기존 질문 owner의 명시적 수정과
  새 revision으로 수행하며, 보강 편집이 원문이나 수동 분할·병합 결과를 덮지 않는다.
- 질문마다 관련 개념 목록, 추천 이유, 교재 이름·쪽수, 설명문과 원문 캡처 미리보기를 보여준다.
- 개념 넣기/빼기, 다른 근거로 교체, 순서 변경, 제목·설명·교사 메모 편집을 제공한다.
  원문 캡처의 pixels는 편집하지 않는다. 범위를 바꾸면 새 검증된 derivative를 만든다.
- ‘저장’은 새 자료 revision이다. 새로고침/서비스 재시작 뒤 같은 편집본을 다시 연다.
  ‘PDF 만들기’는 현재 저장한 exact revision을 고정한다. 미저장 화면을 출력 완료로 표시하지 않는다.
- 후보가 없거나 위치가 미확정이면 그 사유를 표시한다. 빈 개념 칸·없는 그림·모델 추측을
  교재에서 찾은 사실처럼 채우지 않는다. 추천 실패 후에도 기존 자료 편집·출력은 계속 가능하다.

## 3. Codex와 GraphRAG의 역할

### 추천은 기존 유휴 슬롯과 orchestrator를 사용

전용 상시 슬롯·별도 AI 서버를 만들지 않는다. 기존 공유 슬롯 admission/claim/lease,
관리자 모델·추론 설정과 usage/recovery 경계를 재사용한다. 수집용 슬롯을 두자는 뜻이 아니다.
새 작업 계약/프리셋은 구현 때 기존 supported workflow에 맞춰 additive하게 정의한다.

Codex에는 **선택한 질문의 필요한 본문·사진과 사용자 지시**만 전달한다. 전체 채팅방,
학생 명부·연락처·다른 학생의 대화를 통째로 보내지 않는다. 필요한 사진은 현재 operator의
권한으로 core가 해석한 로컬 staged input이며 worker가 NAS/DB에 직접 접근하지 않는다.

### 근거를 찾는 순서

1. 질문의 평가 개념과 오개념 후보를 제안한다. 학생이 실제로 틀렸다는 판정을 만들어내지 않는다.
2. 기존 Catalog/Orchestrator GraphRAG retrieval/read 계약으로 선택된 개념 교재·교과서의
   승인된 근거를 검색한다. Graph·policy·source·accepted analysis revision/hash를 고정한다.
3. 분석 텍스트, 원문 인용, 모델의 설명을 구별한다. 분석만 읽었으면 원문 그림을 봤다고 말하지 않는다.
4. 필요한 원문 페이지/그림을 기존 source-resolution·page/media owner로 읽는다. 실제 페이지를
   보았을 때만 캡처 범위를 제안한다. worker의 임의 파일 경로/외부 URL은 받지 않는다.
5. 개념명·질문과의 관련성·설명 초안·근거 pin·캡처 제안을 구조화해 반환한다. 모델이 최종
   PDF를 임의로 편집하거나 Artifact를 등록하지 않는다. core가 검증해 편집 초안에 반영한다.

현재 일반 대화의 `retrieve_eom_knowledge`는 승인 분석 근거와 실제 원문 pixels 접근을
동일시하지 않는다. 실제 설치·노출된 tool 범위를 확인한 뒤 기존 공용 근거 경계를 확장한다.
이 문서의 이름만으로 도구가 활성화됐다고 간주하지 않는다.

채널명·과목·교육과정·교재를 하드코딩하지 않는다. 현재 접근 가능한 적절한 교재를 사용자가
선택할 수 있어야 한다. 다른 과목/교육과정의 자료밖에 없으면 그 한계를 표시하며 관련성이
있다는 모델 판단만으로 source policy를 넓히지 않는다. 자료가 없으면 기존 자료 학습으로
등록하는 경로를 안내하고 별도 교재 저장소·검색 엔진을 만들지 않는다.

## 4. 원문 캡처와 출처

캡처는 AI 생성 그림이 아니라 **확인된 내부 원본 페이지의 deterministic derivative**다.
source logical/revision, 원문 Artifact/revision/hash, 페이지 번호, 실제 page geometry와 회전,
crop 좌표계/범위, renderer profile, 결과 Artifact/revision/hash를 구분한다.

core의 기존 source/page adapter가 현재 권한·lifecycle·schema/media/hash와 crop bounds를
검증하고 격리 renderer로 생성한다. 문장·수식·표·그림·label이 잘리지 않는지 확인하며, 실제
좌표가 없으면 임의 사각형을 추측하지 않는다. 필요하면 사용자가 페이지에서 범위를 고른다.
기존 정확한 derivative는 pointer로 재사용하고 같은 이미지 bytes를 여러 DB row/NAS 폴더에
복제하지 않는다. staged 파일은 임시 materialization일 뿐 정본이 아니다.

각 캡처/설명 옆에는 확인된 교재 제목·쪽수·근거 구분을 표시한다. 페이지 ordinal과 인쇄 쪽수가
다르면 구분한다. 사용자가 작성한 설명과 교재 원문을 혼동하지 않는다. 내부 보관·출력 권한을
확인하고 외부 출판·재배포 권한까지 자동으로 부여하지 않는다.

## 5. 저장·출력 설계 계약

구현 전 기존 packet/export의 v1 제약을 다시 검토한다. 현재 v1은 한 질문1쪽의 schema/layout,
정확한 packet manifest와 export profile을 고정하므로 새 의미를 v1 bytes에 끼워 넣지 않는다.
학습자료는 기존 packet의 exact revision을 참조하는 얇은 successor로 모델링하고 같은
Catalog/Artifact/renderer owner를 확장한다. 아래는 구현 설계 기준이며 새 영속 schema 확정은 아니다.

1. **책임:** 학습자료 편집 owner는 질문별 보강 block·revision·현재 선택을, 기존 수집 owner는
   원문을, 근거 owner는 교재 resolution을, 출력 adapter/worker는 고정 manifest의 PDF를 맡는다.
2. **정본:** 원문 질문·교재는 기존 Artifact다. 편집한 자료 manifest와 설명은 immutable Artifact,
   DB는 작은 ID/state/version·관계·manifest/output pointer만 보관한다.
3. **identity:** 학습자료 logical ID, revision, 질문/packet revision, 추천 실행 ID, 캡처 Artifact
   revision, 출력 build ID와 SHA를 별개로 유지한다. 기존 일반 질문 PDF를 덮지 않는다.
4. **resolution:** 질문/교재 양쪽의 현재 사용자 권한·source lifecycle·exact pin을 입력/저장/
   출력/다운로드 때 검사한다. 철회·삭제·hash 불일치는 실패이며 latest로 대체하지 않는다.
5. **access:** exact 문서/질문 lookup, ordered block 편집, source membership, 같은 명령 replay,
   현재 revision의 CAS, 학생별 immutable subset 출력이 주요 경로다.
6. **구조:** block/근거는 keyed map과 ordered tuple, 중복은 set, 기존 indexed ID/owner lookup,
   unique build hash·command key와 revision 관계를 사용한다. 새 vector DB/범용 queue는 없다.
7. **규모/비용:** 기존 packet 최대200질문을 출발점으로 보강 block·쪽수·총 bytes 상한을 별도
   정한다. 출력은 질문+block+고유 source/입력 bytes에 선형이며 source당 한 번 resolve한다.
   렌더 중 모든 교재를 반복 탐색하거나 block별 DB/NAS N+1을 만들지 않는다.
8. **transaction:** 짧은 편집 CAS와 command 예약, lock 밖 retrieval/렌더/발행, 뒤의 현재 권한/
   revision 재확인·원자적 채택으로 나눈다. 오래된 추천이 사용자의 최신 편집을 덮지 않는다.
9. **dependency:** Studio/BFF→API→Catalog application→순수 typed 계약이다. GraphRAG와
   source/page 해석은 기존 adapter를 재사용하며 worker가 다른 worker와 직접 통신하지 않는다.
10. **실패/재시도:** 편집·추천·캡처·출력을 별도 결과로 기록한다. 모델 실패는 기존 편집본을
    파괴하지 않는다. 응답 유실은 같은 key/body, 완료 출력 재조회는 새 모델/렌더를 실행하지 않는다.
    새 원문/질문 revision의 채택은 사용자 선택이며 과거 자료를 조용히 갱신하지 않는다.
11. **대안:** PDF를 직접 제자리 수정하면 원문/출처/이력을 잃고, 독립 편집 플랫폼·전용 모델
    서버는 필요 없다. 기존 packet·출력 owner의 얇은 successor와 구조화 block 편집을 사용한다.

최종 PDF는 학생별 질문 순서에 따라 **질문 원본1쪽 → 해당 질문의 개념 쪽들**을 묶는다.
같은 학생의 선택한 질문 revision만 사용한다. 보강 페이지는 설명문을 읽을 수 있는 크기로
넘김 처리하며, 질문·사진을 잘라 1쪽에 맞추지 않는다. 원문 캡처가 한 쪽에 온전히 들어가지
않으면 검토 상태로 돌린다. 원래 v1 PDF 출력과 실패 이력은 계속 열람할 수 있어야 한다.

Codex 역할 지침의 개발용 초안은
[개념 보강 프롬프트](KAKAO_QUESTION_CONCEPT_ENRICHMENT_PROMPT_DRAFT.md)에 둔다.
해당 문서만으로 worker 도구·계약·실행을 활성화하지 않는다.

수동 샘플과 실제 반복 기능을 구분한
[자동 출력 점검](KAKAO_ARCHIVE_REPEATABLE_OUTPUT_AUDIT.md)을 구현 gate로 함께 사용한다.
개발자가 사진·질문 행을 골라 완성한 보고서는 공식 API/저장/출력의 자동화 acceptance가 아니다.

## 6. 구현·검증 순서

1. 현재 PDF 전용 UID/systemd sandbox의 실제 정상 출력·네트워크/인증정보/NAS/형제 작업
   접근 차단·동일 완료 결과 재수락을 합성 입력으로 검증한다. 실제 카카오 성공과 구분한다.
2. 확정된 편집 block/출처 pointer/successor render 계약을 JSON Schema2020-12부터 정의하고
   Pydantic·순수 규칙·fixture로 닫는다. 기존 v1 replay를 보존한다.
3. 수동 설명/이미지 보강 → 저장·새로고침·동시 편집 → 질문1쪽+개념 추가쪽 PDF를 먼저 연결한다.
4. 기존 GraphRAG로 근거 선택/캡처를 연결하고, 관련 근거가 없거나 철회된 경우를 검증한다.
5. 기존 공유 슬롯의 Codex 추천을 연결한다. 근거 없는 모델 결과·늦은 결과·같은 요청 replay,
   사용자 수정과 추천 경합·다른 학생 자료 혼입을 검증한다. 추천 자체를 과학적 정답 보증으로 삼지 않는다.
6. 비로그인·타 계정·권한 철회·구 source 접근과 secret-safe log, PDF 무잘림·source 쪽수·학생
   순서를 검증하고 호환 release로 배포한다. 실제 카카오 한 방/전체 수집 gate는 별도로 유지한다.

이 요구 추가가 실제 카카오 검증을 생략하거나 전체 goal을 작은 편집 기능으로 축소하는 뜻은
아니다. 원래 전체 방 주기 수집·보관·학생별 자료 목표와 함께 완료해야 한다.

### 2026-11-17 공유 슬롯의 개념 자료 찾기 구현 결정

사용자가 전용 상시 슬롯 대신 **남는 공유 슬롯 + 이 기능 전용 프롬프트**를 재확인했다.
카카오 수집/일반 PDF와 선택적 Codex 추천을 계속 분리한다. 구현 책임/절차는 다음과 같다.

1. 기존 질문 owner가 exact question revision과 source 접근을 해석한다. 이름·학교·연락처·
   학생 목록·전체 CSV는 worker envelope에 넣지 않고 선택 질문/조교 답변/사진만 stage한다.
2. 새 purpose는 기존 Workflow/Orchestrator/Content Pack의 얇은 작업으로 추가한다. 현재
   `SharedWorkerCapacityPolicy/1.7`의01–05 순환 claim·lease·모델 검증·host 상한을 재사용한다.
   06 채팅 예약·관리자 중지·기존 preset을 바꾸지 않는다. 슬롯이 없으면 대기하며 기능
   전용 worker 서비스/queue·별도 임의 Codex 프로세스를 만들지 않는다.
3. 기존 일반 worker는 로컬 입력/구조화 출력이므로, 대화 전용06 runtime이나 이름만 있는
   검색 tool을 재사용한 척하지 않는다. **PLAN → 기존 Catalog GraphRAG → COMPOSE**의
   순서로 한다. PLAN은 사진까지 읽어 검색 개념/질의를 제안하고, core가 현재 실제 operator와
   고정 Graph/policy/허용 교재로 공식 read-only retrieval/source-resolution을 호출한다.
   COMPOSE는 materialize된 근거/실제 페이지만 읽어 교사용 보강 초안을 만든다.
4. 검색한 source/analysis/Artifact/policy의 전체 pins는 core의 실행/저장 provenance가 가진다.
   worker에는 작은 근거 key와 검증된 설명/로컬 page member만 전달한다. 모델은 그 key만
   인용하고 임의 source ID·경로·URL·권한을 반환할 수 없다. 분석과 원문 인용을 구분하고,
   실제 페이지가 없는 경우에는 crop/쪽수를 만들어내지 않는다.
5. 두 단계 메시지를 JSON Schema2020-12/Pydantic으로 먼저 닫는다. task/question/request hash·
   exact input phase·근거 key·실제 page key/범위·인용문을 core가 대조한다. 새 request key로
   timeout을 우회하지 않는다. 같은 요청은 기존 phase/Job 결과를 재사용한다.
6. 추천 초안은 기존 packet을 참조하는 immutable study revision으로 저장한다. 원문 질문이나
   조교 답변을 고치지 않으며 current 편집 revision의 CAS로만 채택한다. 늦은 결과가 최신
   사용자 편집을 덮지 않는다. 저장/재조회/Studio 선택·편집/새 PDF 연결까지가 완료 범위다.
7. 주요 접근은 exact question/task/evidence lookup·ordered block 순회·동일 key replay다.
   bounded dict/set/tuple과 기존 indexed Job/Workflow/Artifact를 쓴다. 비용은 질문 텍스트+
   실제 staged bytes+선택 근거에 선형이며 교재 전체를 worker마다 복사/재검색하지 않는다.
   영속 편집 owner의 row/index/transaction은 구현 전 기존 packet/command 구조와 맞춰 별도
   구체화한다. 큰 본문/사진/로그는 DB가 아니라 기존 Artifact다.
8. source 미확보/근거 없음/페이지 미열람/권한 철회/한도 소진·잘못된 모델 출력은 구분한다.
   추천이 실패해도 일반 질문 PDF/수동 편집이 가능해야 한다. 교재 원문과 모델 설명을
   혼동하거나 빈 결과를 성공한 교재 찾기로 표시하지 않는다.
9. 의존 방향은 Studio→API→Catalog application→기존 Orchestrator→공유 worker이며,
   pure worker DTO는 DB/NAS/HTTP/권한 owner를 import하지 않는다. worker끼리 통신하지 않는다.
10. 검증은 source/schema·인용 위조/학생 격리·임시 DB의 claim/replay/편집 경합·실제 유휴
    슬롯1건·교재 근거→저장→재조회→PDF까지 구분한다. fixture PASS로 모델 실행/교재 검색
    성공을 주장하지 않는다. 과거 실패와 현재 GPU/등록 작업은 보존한다.
11. 대안인 질문 문자열만으로 바로 검색하기는 ‘이 그림이 궁금해요’ 같은 질문에서 실패하고,
    전용 채팅 runtime/브라우저 Codex에 모두 맡기기는 권한·출처·공유 슬롯 책임을 흐린다.
    기존 작업의 두 작은 단계와 공식 retrieval owner를 연결하는 구조를 선택한다.

연결 대조에서 채팅 전용 구 reader의 source-reference/accepted-result 범위가 새 자료 학습
V5/12를 온전히 표현하지 못함을 확인했다. 그 경로의 contract/권한을 임의로 넓히지 않는다.
`retrieve_material_read_only`가 출제의 `UPLOADED_MATERIAL_V1` source 해석을 명시 재사용하고,
기존 `item_textbook_context`의 Graph/source/accepted-result/anchor 검증 결과를 typed 값으로
받는다. 이전 출제 Markdown은 같은 typed 값에서 동일하게 출력한다. 교재 원문 PNG가 실제로
제공된 경우에만 page key/crop 제안을 허용하며 구 text-only source는 별도 원문 열람이 필요하다.
이 판단은 교재 이미지 사용을 제외하는 것이 아니다. 원문 해석·저장한 페이지와 실제 crop·
출처·자료 편집/PDF까지 이어서 연결해야 최종 개념 보강 완료다.

### 교과서 원본 이미지 전달·캡처 경계

사용자는 교과서 이미지 사용을 명시 허용했다. 기존 승인 분석의 page-image observation과
선택된 Graph anchor를 대조해 **원래 저장된 페이지 PNG**를 읽는다. 분석 문장·locator 문자열로
PDF 좌표/쪽수를 추측하지 않는다. page PNG가 없는 과거 text-only source는 원문 미열람으로
남긴다. 선택 anchor의 실제 member 또는 검증된 observation으로 쪽을 결정하며, 전체 범위가
4쪽 이하일 때는 그 bounded 범위 전체를 제공할 수 있다. 더 긴 범위를 임의 일부 쪽으로
대체하지 않는다. 근거3건·총12쪽·총96MiB 상한과 생략 여부를 명시한다.

- 정본은 기존 source/accepted analysis/Graph/policy와 그 page Artifact다. model에는 작은
  근거/page key·로컬 member만 전달하고 정본 pointer는 core가 보유한다. 동일 page member는
  map으로 한 번만 읽고 stage한다. 원문을 별도 Kakao 사진 Artifact로 재등록하지 않는다.
- 기존 source reader의 현재 사용자·질문·Graph·policy·권한/lifecycle 재확인을 전후에 수행한다.
  Artifact reader가 exact revision/schema/media/hash를 검사하고 PNG header/실제 decode/크기/
  단일 프레임/방향도 대조한다. stage 위치는 기존 private local root이며 NAS가 아니다.
- model crop은 actual staged page key와 검증된 COMPOSE 결과에만 적용한다. 좌표는 원본 PNG의
  좌상단 기준 정규화 값이며, 픽셀 변환은 바깥쪽 floor/ceil로 계산한다. 회전/축소/재배치를
  하지 않는다. core는 이 사각형이 과학적으로 적절하다고 보장하지 않으며 Studio에서 확인한다.
- crop은 명시적 derivative materialization 경계다. source pointer·원본 hash·pixel bounds·
  고정 crop profile·결과 hash를 분리하고 같은 source/bounds는 한 번만 만든다. 저장/출력에
  채택되기 전 로컬 결과는 정본/발행 결과가 아니다. 임의 모델 경로/URL을 해석하지 않는다.
- 비용은 선택 anchor/페이지와 실제 읽는 bytes·decode pixels·고유 crop 수에 선형이다.
  새 DB/index/queue/dependency는 없고 장시간 DB lock도 잡지 않는다. 실패 시 미채택 stage만
  남으며 질문·교재·기존 자료를 변경하지 않는다. 같은 완료 결과를 다시 읽는 owner는 이전
  immutable derivative pointer를 사용해야 하며 이 adapter로 조용히 재출력하지 않는다.
- 단순 대안인 분석 요약을 원문처럼 캡처하거나 PDF 전체를 매번 복사하기는 출처·pixels·
  비용을 보존하지 못한다. 기존 Artifact reader와 private file materializer를 재사용한다.

### 공유 Workflow 실행 입력의 구체화

실행 목적은 `kakao-concepts`이며 기존 자료 학습/고객 문의의 의미로 위장하지 않는다.
두 phase는 같은 one-step definition의 독립 child Workflow다. parent 추천 owner가 PLAN 결과를
공식 GraphRAG로 해석해 COMPOSE 입력을 만들고, worker끼리 통신하지 않는다. 기존 Workflow
command·Job·plan·claim/lease를 사용하며 새 queue나 전용 슬롯 서비스는 없다.

Work 입력에는 task/phase·binding·question revision/manifest와 **개념 request Artifact pointer +
필요한 파일 pointer 목록**만 둔다. 질문/교재 본문·사진은 기존 Artifact와 명시적 private workspace
경계에만 존재한다. 로컬 파일 목록은 request가 실제 참조한 member와 완전히 같아야 하며,
누락·중복 경로·추가 파일·hash/길이/media 불일치는 실행 전 거부한다. model은 임의 source
경로·권한·operator·slot을 지정하지 못한다. 같은 task/phase/request의 replay는 같은 child다.

새 role protocol/plan은 predecessor bytes를 보존하는 successor다. 선택적 Kakao contract wheel은
해당 role의 결과를 실제 읽을 때만 불러온다. 일반 workflow import가 Kakao browser/PDF/contract
설치를 요구하지 않게 한다. 현재 actor/source 재확인은 admission·materialization·result 채택
전후의 기존 adapter 경계가 맡고, 순수 DTO는 pointer/phase/hash coherence만 검증한다.

접근은 exact task/workflow/job lookup·작은 member map·ordered phase 이력이다. input 해석은
파일 수+JSON/실제 staged bytes에 선형이고, 기존 unique command/fingerprint와 CAS를 쓴다.
기존 plan/model/preset을 실행 도중 최신으로 대체하지 않으며 실패나 timeout에 새 identity로
자동 우회하지 않는다. 독립 동기 Codex 호출은 간단해 보여도 공유 슬롯·중단 복구·동시성
기록을 우회하므로 사용하지 않는다. DB/Studio 저장 owner와 실행 canary는 별도 완료 gate다.

### 원본 사진을 실제 Codex image input으로 전달

- 책임은 기존 Orchestrator input materializer와 root-installed fixed worker다. core가 현재
  질문/source 권한을 전후 재확인하고 request JSON과 참조한 image만 private workspace에
  stage한다. worker가 NAS/DB/외부 교재를 직접 읽거나 별도 슬롯을 선택하지 않는다.
- 정본은 Work가 pin한 request/image Artifact member다. `source/concepts/request.json`과
  `source/concepts/files/…`는 일시 입력이며 질문 manifest/학생 명부는 복사하지 않는다.
  원본 JPEG/WEBP를 PNG로 바꾸거나 교재 PNG에 가상의 question-page 번호를 붙이지 않는다.
- image manifest6은 exact plan ID, ordered input index와 local path/media/hash/bytes/dimensions만
  가진다. 기존1–5의 schema bytes·해석은 보존한다. 빈 image 집합에는 manifest를 만들지 않는다.
- request closure/path uniqueness는 map/set, index는1부터 연속 순서다. 최대72개/총128MiB,
  개별64MiB/64M pixels·총256M pixels다. 시간은 고유 입력 bytes+decode pixels에 선형이며
  사진은 한 장씩 검증·stage한다. 새 DB/cache/index/queue는 없다.
- core가 정확한 member/schema/media/hash/길이·실제 decode/크기/단일 frame/방향을 검사하고,
  stdlib-only fixed worker는 고정된 private 경로·파일 권한/크기/hash·format header를 재확인해
  실제 `--image` 인자로 연결한다. root helper에 Pillow/프로젝트 import를 추가하지 않는다.
- source 거절·불완전 request·다른 page metadata·잘못된 image는 명시 실패다. 입력 파일은
  exclusive write이며 실패한 workspace를 덮어 재사용하지 않는다. 실행 replay는 기존 Job/
  claim owner가 맡는다. feature adapter가 실제 연결되기 전 executor 거부는 유지한다.
- 파일 경로를 프롬프트에만 써두는 대안은 사진을 model에 보낸 증거가 아니고, 모든 입력을
  PNG로 바꾸는 대안은 불필요한 derivative/재해시/원본 관계를 만든다. 새 manifest successor로
  원본 bytes를 전달한다. fixed helper 교체는 기존 실행을 해치지 않는 호환 release에서 한다.

### 추천 요청의 영속 저장과 source authority

1. Catalog가 한 질문의 추천 task와 PLAN/COMPOSE phase를 소유한다. Workflow/command/Job/
   claim/lease는 기존 owner가 소유하며 task 표를 별도 실행 queue로 사용하지 않는다.
2. 정본은 exact question revision, 사용자 지시·서버가 고정한 Graph/policy의 intent Artifact,
   phase별 canonical request Artifact다. DB에는 ID/시각/요청 hash·작은 scope/Work pointer와
   phase workflow/result pointer만 둔다. 질문·교재·사진·모델 결과 본문을 DB에 복제하지 않는다.
3. task는 사용자 재시도 identity, phase는 (task, PLAN|COMPOSE)의 단일 append-only identity다.
   phase의 Work는 이미 정의한 pointer DTO를 그대로 사용한다. Catalog wire가 Workflow
   package를 import하지 않으며, 내부 application composition에서만 public Workflow API를 쓴다.
4. 실제 API actor/session으로 최초 요청을 수락한다. background source 검사는 그 수락한
   task의 owner에서만 출발해 기존 current-operator·binding/room·accepted source·question/
   Artifact 권한을 재검사한다. 최초 session ID는 감사 provenance이며, 단순 HTTP 만료/로그아웃은
   이미 수락한 bounded 작업을 새 요청으로 만들거나 취소하지 않는다. 계정 중지/권한·source
   철회는 계속 차단한다. 공개 조회/다운로드는 현재 실제 API session을 다시 검사한다. 임의
   operator/role/session 입력이나 synthetic HTTP ActorContext를 만들지 않는다.
5. 접근은 owner+idempotency key 중복 조회, task ID 조회, (task,phase) exact 조회와 bounded
   task history다. 기존 intent advisory lock, unique(owner,key), composite FK와 B-tree index를
   쓴다. task 수가 늘어도 key lookup은 O(log n), 한 task의 phase 해석은 최대2개다.
6. 긴 source read/decode/Artifact 발행은 row lock 밖이다. 예약→발행→짧은 재검증·채택이며
   같은 phase는 한 Work만 채택한다. 파일 발행 후 죽으면 같은 key로 원래 Artifact를 재사용한다.
7. parent는 phase의 workflow identity/result pointer를 불변 연결하며 실패 Workflow를 성공으로
   바꾸지 않는다. GET은 실행하지 않는다. 사용자 지시 변경/명시적 새 추천은 새 task다.
8. 동시 생성·동일 phase 채택·늦은 권한 철회·응답 유실·서비스 재구성·실패 보존을 임시 DB에서
   검사한다. 새로운 immutable row는 공식 migration으로만 추가한다.
9. 단순히 generic Job metadata에 원문과 결과를 넣는 대안은 private source owner·멱등
   요청·저장/실행 책임을 혼합한다. 별도 queue/framework 대신 두 작은 소유 테이블만 추가한다.

## 7. 역할·기록 정보를 유지하는 후속 PDF 입력 계약

`worker-study-render-v1`은 기존 `worker-question-render-v1`을 변경하지 않는 별도 family다.
책임은 **검증된 exact 질문 subset의 출력 입력**이며 수집·질문 구분·원문 수락 권한이 아니다.

- 정본은 기존 packet/question/source와 선택적으로 저장한 학습자료 revision이다. worker
  manifest는 렌더 입력 경계의 일시 materialization이며 새로운 질문/학생 정본이 아니다.
- binding·packet revision·student·question revision/subset hash와 optional study revision,
  command/attempt/fence·font/renderer/hash를 각각 pin한다. 자료 revision 없이 일반 질문·답변
  출력은 가능하지만 보강 block이 있으면 저장한 study revision을 반드시 요구한다.
- 학생과 조교 content를 따로 보존하고, text/image use마다 원래 message occurrence를 연결한다.
  metadata는 선택된 occurrence만 포함하며 role·raw date·timezone·resolved UTC를 유지한다.
  원문 없는 현시각·발신자 추정은 허용하지 않는다. worker가 source의 현재 권한을 부여하지 않는다.
- 보강 block은 별도 작은 값으로 title/content/origin과 검증된 근거의 표시용 citation을 받는다.
  실제 Graph/policy/source/analysis/Artifact pin과 접근 검사는 Catalog의 저장·해석 owner가 맡는다.
  worker에 원격 URL·NAS/DB path·검색 권한을 주지 않는다.
- 접근은 ordered 질문/section 순회와 occurrence/image member lookup이다. keyed map/set과
  immutable tuple을 사용해 O(질문+block+고유 member+입력 bytes)로 처리한다. 기존256MiB
  입력/출력·200쪽 안전 상한을 시작점으로 유지하고 넘으면 무잘림 검토 상태로 돌린다.
- 기존 source/질문 validation을 공통 순수 해석 함수에서 재사용한다. v1 출력과 새 출력이
  권한/identity·학생 subset·source closure 규칙을 따로 복제하지 않는다.
- 별도 queue·DB·scheduler를 만들지 않는다. 기존 저장/claim/짧은 CAS와 lock 밖 materialization,
  격리 실행·Artifact 발행을 후속 application 연결에서도 그대로 사용한다.
- 새 worker family와 이를 모르는 설치본을 혼합하지 않는다. 현재 family의 schema·DTO/projection
  구현은 운영 활성화가 아니다. 고정 entry/executor/export profile/API/Web까지 같은 지원 범위가
  연결된 뒤 호환 릴리스로 활성화한다. v1 실패·완료 이력은 그대로 해석한다.
- 모듈 방향은 Catalog application→순수 worker contracts이며 pure contracts는 Catalog/SQL/NAS를
  import하지 않는다. worker는 staged local member만 읽고 core만 최종 파일을 발행한다.
- 같은 요청은 기존 exact 결과를 읽고, 누락/권한 철회/hash·role·timestamp 불일치는 명시적 오류다.
  재조회·추천 실패를 새 렌더나 원문 변경으로 우회하지 않는다.
- 원래 role 정보를 지우고 출력 시 문장을 보고 되추론하는 대안은 더 불안정하다. 한 번의
  검증된 source resolution에서 role/metadata를 보존하는 얇은 projection을 선택한다.

## 8. 반복 가능한 쪽 나누기와 기존 PDF 엔진 재사용

새 layout receipt는 원래 v1 page geometry DTO를 재사용하되, section 종류·보강 block ID와
원문 span의 시작/끝을 별도 고정한다. core는 같은 input manifest에서 section을 재구성해
순서·전체 범위·사진 use·학생/질문 pin을 확인한다. 다른 family의 성공으로 해석하지 않는다.

- 학생 사진→질문은1쪽이다. 기존 measured layout의 고정 후보와45mm 이미지 최소 크기를
  유지하며 안 들어가면 검토 상태다. 임의 축소·crop·원문 삭제는 하지 않는다.
- 조교 사진→답변→기록 정보는 같은 section에서 흐른다. 조교 답변이 없으면 기록 정보를
  학생 section 뒤에 붙이며 빈 답변/사진 section을 만들지 않는다. 보강 section은 그 뒤다.
- 여러 쪽의 답변/보강은11pt 고정 line measurement로 한 번 wrap하고 순서대로 채운다.
  이미지가 남은 공간에 온전히 안 들어가면 다음 쪽으로 넘긴다. 가능한 쪽을 찾기 위해 전체
  원문을 반복 render하거나 탐색하지 않는다. 비용은 글자·사진 use·쪽수에 선형이다.
- 원문 span을 나눌 때 grapheme/CRLF 경계를 유지한다. 각 쪽 receipt에 원문 offset을 남겨
  이어진 범위가 정확히 전체가 되는지 core가 확인한다. 페이지 fragment는 같은 질문의
  표시 범위일 뿐 새 질문 ID/revision이 아니다.
- font/glyph·사진 EXIF/명시적 transform·decode budget, PDF write/readback·PNG와 member
  commit은 기존 worker 함수에서 재사용한다. v1도 동일한 공통 page writer를 호출하되
  v1 contract·one-question-one-page·기존 receipt 의미는 바꾸지 않는다.
- 사진 decoder는 고유 member+transform별 한 번 실행하고 여러 use는 참조한다. output은
  전체 layout/readback 검증 후에만 local commit하며 NAS/DB 발행은 기존 core owner다.
- page count/input/output/pixel 상한을 넘으면 성공 PDF를 일부만 발행하지 않는다. 고정 entry,
  executor, profile·API/Web 연결과 별도 설치 검증 전에는 새 family를 운영에 활성화하지 않는다.

## 9. 동일 실행·복구·발행 경로의 두 출력 family

- 책임은 기존 Orchestrator PDF executor와 Catalog PDF publisher다. 두 번째 executor/queue,
  NAS writer나 범용 plugin framework를 만들지 않는다. pure `pdf_contracts`의 작은 exact-family
  해석 함수가 이미 정의한 두 schema의 command/manifest/result/layout 짝을 검증한다.
- 정본은 저장한 exact export command와 입력/출력 Artifact다. 새 자료 revision은 새 family의
  manifest/layout에 pin하며 과거 v1 명령·결과를 재해석하지 않는다. 로컬 accepted 폴더는
  발행 경계의 임시 materialization이지 독립 문서/정본이 아니다.
- dominant access는 command family 분기, member path lookup, ordered page 순회와 같은
  attempt의 append-only 채택이다. bounded map/set/tuple과 기존 indexed export/attempt 및
  Artifact idempotency key를 그대로 쓴다. 새 DB/index/migration은 이 단계에 필요 없다.
- 입력 materialization도 기존 `prepare_kakao_pdf_inputs`를 사용한다. 내부의 명시적 typed
  layout policy로 두 projection을 고르고, 권한/선택 검증과 고유 사진/폰트 읽기는 공유한다.
  기본값은 기존 v1이며 GUI 요청이나 저장된 구 profile을 새 family로 조용히 전환하지 않는다.
- 비용은 input/output 고유 member bytes+쪽수에 선형이다. 원본 manifest JSON을 한 번
  decode하고 receipt 검사는 기존 pure 규칙을 호출한다. family별 복사·재렌더는 없다.
- 같은 command/attempt/fence를 staging 전에, 실행 전후와 발행 전후 재확인한다. 복구는
  원래 프로세스가 종료됐다는 기존 OS 증거를 요구하며 원래 output을 다시 검증할 뿐 dispatch
  하지 않는다. timeout만으로 새 실행/identity를 만들지 않는다.
- result의 family는 입력 command로 결정한다. worker의 다른 family 주장·학생/packet/study
  pin·텍스트/사진 누락·쪽수/파일/hash 불일치는 명시적 실패다. 새 family의 page count는
  원문 질문 수가 아니라 검증된 section layout의 쪽수이며, v1의1질문1쪽 제한은 유지한다.
- 파일 발행은 기존 Artifact owner와 PDF/PNG media 계약을 재사용하며 layout의 schema URI는
  exact family를 따른다. 새 family만 request에 study revision/family/layout policy를 추가해
  provenance를 고정한다. 기존 v1 publication의 key/request bytes 의미는 바꾸지 않는다.
- pure contracts는 infrastructure를 import하지 않고 Orchestrator/Artifact adapter가 호출한다.
  기존 GUI/export owner는 아직 v1만 생성하므로 새 family를 조용히 선택하거나 활성화하지 않는다.
  실제 설치 wheel·fixed launcher와 source owner/profile/API의 호환 활성화는 별도 gate다.
- 복제한 두 실행기는 권한/복구 규칙이 서로 달라질 수 있다. 실제 두 출력 family가 존재하는
  지금 필요한 작은 typed 분기만 추가하는 것이 더 단순한 대안이다.

## 10. 저장 export와 공개 화면의 호환 전환

기존 export owner/DB를 재사용한다. 새 layout policy는 저장 profile에 이미 들어갈 작은 값이며
기존 build hash·unique claim의 일부다. 신규 DB/queue/index는 필요 없다. request의 학생·packet
선택 의미는 같아 `export-create/1.0`을 유지하고 runtime/font/policy는 계속 서버가 결정한다.

- 기존 v1 schema bytes와 record는 보존한다. `export-store-v2`는 study profile/export/mutation과
  v1/v2를 함께 나열할 page만 추가하며 공통 필드는 predecessor 참조로 재사용한다. RPC v2도
  기존 요청·응답을 참조하고 세 가지 새 export 응답만 추가한다. API/Web이 모두 지원하는
  release에서만 새 policy를 활성화한다. 같은 Python DTO가 두 명시적 tag를 읽을 수 있지만
  tag/profile/layout 혼합은 검증 실패이며 implicit latest는 없다.
- 저장 row의 정확한 profile로 output version/layout URI를 결정한다. 운영 profile이 바뀌어도
  과거 완료본·같은 key replay는 원래 export revision/Artifact를 읽는다. 새 key의 새 profile은
  다른 build identity다. 오래된 RUNNING/PENDING을 새 runtime에 자동 재핀하지 않는다.
- 동일 row/attempt/command/current source의 짧은 CAS는 그대로다. `complete_export`는 검증된
  publication의 실제 preview/page 수를 저장하고 원래 publication job의 layout SHA·쪽수·family
  provenance를 대조한다. 새 record의 쪽수를 질문 개수로 덮지 않는다. v1은 기존1질문1쪽도 검사한다.
- 이번 공개 연결은 **기존 질문/답변/기록 정보**만 출력한다. saved study owner가 연결되기 전에는
  non-null study revision/supplement를 bind하지 못하게 한다. worker DTO의 지원을 원문/교재
  권한으로 오인하지 않는다. 개념 편집 저장은 이 source pin에 붙는 별도 후속 단계다.
- Studio 새 자료는 조교 답변 포함을 기본으로 제안하고 사용자가 끌 수 있다. 저장한 packet의
  선택은 그대로이며 읽기/다운로드·상태 확인으로 새 packet/렌더를 만들지 않는다. 과거 출력과
  새 질문/답변 출력을 쉽게 구별한다. 클라이언트는 권한·source invariant를 재구현하지 않는다.
- 비용은 bounded page 목록+source lookup이며 기존 indexed ID·build hash·ordered tuple을 쓴다.
  file dereference·현재 권한/생명주기·revision/hash 확인, 종료 증거와 실패/retry 보존은 기존
  owner가 유지한다. 배포 전 임시 PostgreSQL에서 동시 요청/재전송/중단/재시작/권한 철회와
  v1/v2 혼합 history를 검사하고 실제 source 실증과 구분한다.
- 단순히 v1의 쪽수나 layout 의미를 바꾸는 대안은 과거 결과를 오해하게 한다. 현재 두 wire
  family에 필요한 얇은 additive 응답만 추가하는 것이 기존 프레임워크 안의 가장 작은 변경이다.

## 11. 수락된 개념 작업의 실제 공유 슬롯 실행 연결

Catalog는 private task/phase의 현재 source 권한을, Runner는 저장 Workflow의 실행을,
Orchestrator는 입력 materialization·결과 검증·Artifact 발행을 담당한다. 새 queue나 전용
슬롯은 만들지 않는다. 정본은 이미 수락한 intent/phase Work와 exact Workflow·plan42다.

- 작은 Runner 전용 authorization RPC는 Workflow/step/plan ID와 plan/Work hash만 받는다.
  operator/session/task/권한을 요청에서 받지 않는다. Catalog가 저장한 human owner와 phase의
  workflow link를 따라 intent·원 질문·원 source closure·현재 계정/권한을 재검사한다.
- intent는 기존 Artifact owner로 lock 밖에서 읽고 canonical bytes/hash를 검증한다. 현재
  metadata/ACL은 호출마다 다시 확인한다. 긴 학생 내용·사진·교재가 RPC/DB로 복사되지 않는다.
  keyed ID lookup과 unique (task,phase)를 사용하며 비용은 bounded source closure에 선형이다.
- 기존 Catalog socket의 정확한 Runner UID에 이 operation만 추가한다. 일반 API/채팅/worker가
  background authority를 주장하지 못한다. 원 HTTP 만료는 accepted task를 바꾸지 않으며 실제
  계정/원본 철회는 실행 전·복구·결과 채택을 차단한다.
- Runner는 공개 plan validator와 기존 Core Artifact reader를 조합한 exact execution context를
  전달한다. Orchestrator가 기존 claim/lease·prepare/run·중단 복구 경로에서 재인가하고, pure
  request/result validator로 실제 E/page/quote/crop을 검사한 뒤에만 결과를 발행한다.
- 같은 요청은 기존 Job·Artifact를 재조회하며 실패 이력을 수정하거나 새 identity로 우회하지
  않는다. 새 DB/schema migration은 이 연결에 필요 없다. pure Kakao package는 해당 purpose에만
  lazy load하여 다른 Workflow의 설치 의존성을 늘리지 않는다.
- 단순 direct Codex 호출은 기존 claim/lease·source revocation·복구를 잃는다. 기존 material
  authorization의 transport 패턴만 재사용하고 purpose/DTO/검증은 분리하는 것이 작은 대안이다.

## 12. PLAN 결과에서 교재 근거를 붙여 COMPOSE 입력 만들기

책임은 기존 Catalog 추천 task와 공식 GraphRAG reader다. 초기 Graph scope는 현재 출제
프리셋의 검증된 retrieval policy와 그 허용 corpus의 active snapshot에서 한 번만 고정한다.
모델/브라우저가 policy·Graph를 지정하지 않는다. 수락 후 재개는 그 exact scope다.

- 정본은 accepted 질문 intent, 성공한 PLAN Workflow/step/Job의 canonical result, 공식 검색이
  해석한 accepted analysis/원문 page다. 새로운 source/검색 엔진이나 worker 통신은 없다.
- COMPOSE request Artifact의 sibling `knowledge.json`에 typed provenance를 둔다. 동일 immutable
  revision이 request hash와 PLAN result·Graph/policy/source/analysis·page pointer를 묶는다.
  Work/phase DB에는 기존 request Artifact pointer만 남기므로 새 migration/queue는 없다.
- provenance는 본문 사본이 아니라 작은 source/accepted-analysis/normalized-text pointer와 hash,
  node/anchor 선택·원본 page pin이다. 모델은 기존 작은 E/page key와 materialized 내용만 읽는다.
  질문/교재 원문과 crop을 새 원본으로 등록하거나 request만 보고 접근을 허가하지 않는다.
- dominant access는 (task,phase), Workflow/Job와 Artifact revision lookup, 최대3근거/12page의
  ordered iteration·map dedup다. 비용은 선택된 source closure·bytes에 선형이다. 기존 unique/CAS와
  Artifact idempotency key를 사용한다. 같은 완료 phase는 다시 검색·렌더하지 않는다.
- source reader는 매 실행/채택에서 actual owner의 현재 권한과 저장한 모든 pins를 공식 reader로
  재확인한다. scope를 최신으로 바꾸거나 source 부족을 일반 지식으로 메우지 않는다. 긴 원문
  준비/PNG decode·Artifact 발행은 phase row adoption lock 밖에서 수행한다.
- 실제 슬롯 실행과 공개 API·Studio 편집/PDF는 별도 검증한다. source 테스트/합성 근거를 실제
  교재 활용으로 보고하지 않는다. 실패/취소/NEEDS_INPUT은 기존 이력을 보존하고 중복 실행하지 않는다.
- 단순히 모델 설명과 그림 경로만 저장하는 대안은 정확한 교재/페이지·실행 근거를 잃는다.
  기존 file-set Artifact의 두 작은 member로 연결하는 것이 별도 DB aggregate보다 단순하다.

## 13. 검증된 COMPOSE 결과를 기존 PDF 보강 block으로 연결

Catalog의 작은 projection이 완료 COMPOSE·현재 재인가한 교재 provenance와 실제 준비한
capture를 기존 `StudySupplement`로 변환한다. 원본 질문/조교 답변은 변경하지 않는다.
설명은 MODEL_DRAFT, 교재 인용/원본 PNG는 확인한 출처와 물리 페이지를 각각 표시한다.
조교 답변 확인 메모·추천의 한계는 별도 block이며 관련 기초 개념을 정답 근거로 과장하지 않는다.

- 정본은 기존 phase 결과/COMPOSE request와 원본 PNG다. 출력용 attachment ID는 로컬 render
  use의 deterministic identity이며 카카오 메시지/첨부 DB 등록이나 source 권한을 뜻하지 않는다.
  draft는 exact task/question/phase-result pin과 crop provenance를 보유한다. saved-study owner가
  채택하기 전에는 독립적인 저장 revision·공식 export 완료로 표시하지 않는다.
- 입력은 이미 정의한 DTO이며 새 wire·DB·queue는 필요 없다. 긴 원문 decode와 crop은 기존
  page adapter에서 수행한다. projection은 keyed capture/evidence 조회와 ordered tuple로
  O(block+capture+text bytes), 원본 bytes는 고유 member별 한 번씩 준비한다.
- 같은 crop은 로컬 member를 공유하고 여러 표시 use만 구분한다. 실제 original/page/bounds/
  media/hash가 맞지 않으면 거부한다. 원문을 못 받은 경우 그림을 만들지 않는다. crop의
  `quality_accepted`는 false로 시작해 단순 decode를 사람의 편집 품질 승인으로 바꾸지 않는다.
  DRAFT 출력은 가능하지만 FINAL 품질/레이아웃 검사는 기존 규칙을 유지한다.
- 모든 I/O 전후에 accepted task와 현재 교재 권한을 재인가한다. 재조회는 모델을 재실행하지
  않으며 현재 local draft 준비는 canonical 발행/편집 CAS와 다르다. 저장·Studio 편집·공식
  export 연계는 별도 owner에서 이어간다. 근거 없는 경로/이미지를 붙이는 대안은 제외한다.

## 14. 학생별 packet의 개념 자료 저장·수정 owner

1. Catalog의 study application이 기존 exact packet/student subset에 붙는 편집본을 소유한다.
   수집/질문·Graph/Workflow·Artifact의 소유권을 가져오지 않는다. 일반 PDF는 영향받지 않는다.
2. 정본은 packet/question·완료 COMPOSE와 교재 provenance다. study manifest에는 원문이나
   모델 결과 전체를 복사하지 않고 exact result pin·선택 block/capture index·사용자 수정/메모만 둔다.
3. study logical ID→불변 revision→manifest Artifact/revision/hash와 작은 mutable head를 나눈다.
   packet/student는 한 study에서 불변이며 다른 packet으로 옮길 때는 새 study를 만든다.
4. 저장·조회·PDF 입력 준비/다운로드는 현재 사용자의 원 packet/질문/source와 모든 선택 task의
   정확한 COMPOSE 결과·Graph/교재 권한을 검사한다. 최신 결과나 다른 학생으로 대체하지 않는다.
5. 연산은 owner/binding/study ID lookup, ordered question/block 순회, command key replay,
   revision CAS와 bounded keyset history다. 기존 질문·packet·추천 owner를 호출해 source를 해석한다.
6. head/revision/command의 작은 세 표에 FK·unique(owner,key)·unique(study,version)·B-tree
   목록 index와 immutable revision/append-only command 보호를 둔다. 본문·사진은 DB에 없다.
7. 최대200질문·질문당8출력 block을 출발점으로 한다. block/evidence는 map/set/tuple,
   비용은 선택한 질문/task/source/편집 text에 선형이다. 원 packet 전체를 반복 scan하지 않는다.
8. 같은 command를 짧은 lock으로 예약하고, 긴 source 해석·manifest 발행은 lock 밖에서 한다.
   이후 현재 권한/source와 parent CAS를 재확인해 revision/head/command를 원자적으로 채택한다.
9. Studio→API→Catalog study service→기존 packet/concept/Artifact owner다. worker가 저장하거나
   다른 worker를 부르지 않는다. 별도 registry·queue·generic editor framework를 만들지 않는다.
10. 같은 key/body는 같은 ID/원래 revision이다. 발행 뒤 중단은 같은 Artifact를 재사용한다.
    바뀐 body는 conflict, 경쟁 parent는 precondition failure다. 이전 사용자 편집을 자동 추천으로
    덮지 않으며 실패/원본/기존 PDF를 수정하지 않는다.
11. 모델 결과 JSON을 UI에서만 편집하는 대안은 재시작/출처/동시 편집을 잃는다. 기존 packet의
    예약·발행·짧은 CAS 패턴을 재사용하는 얇은 study owner가 최소의 영속 경계다.

공개 편집 입력은 제목/설명/질문과의 관련성·block/capture 선택·직접 쓴 메모로 제한한다.
임의 source ID/파일 경로/인용문을 추가하는 입력은 없다. 인용·원본 그림은 저장한 task의 실제
결과와 교재에서만 파생한다. editable study는 source/모델 결과 자체를 바꾸지 않는다.

## 15. 저장한 study revision과 기존 PDF export 연결

1. 기존 ExportService/claim/renderer/publication/download를 확장한다. 별도 출력 엔진·queue는 없다.
2. 정본은 저장한 exact study manifest, 기존 packet/student subset과 PDF Artifact다. 새 명령은
   binding과 작은 study ID/revision/manifest hash pin만 받고 packet/student는 owner가 해석한다.
3. 기존 export ID에 optional 불변 study link를 한 번 연결한다. 출력 attempt/revision/hash와
   study logical/revision은 다르다. 같은 입력/renderer는 기존 build를 재사용한다.
4. 공개/다운로드와 실행 전후에 study owner로 현재 packet/질문·교재/task 권한을 재검사한다.
   metadata CAS 중에는 public metadata reader를 사용하며 긴 source read/decode는 lock 밖이다.
5. 접근은 export ID→study link의 indexed lookup, study revision lookup과 ordered 질문/block이다.
   새 link 표는 export PK·기존 export tenant FK·study revision FK·study 목록 index를 갖는다.
6. 작은 typed link만 DB에 두고 사진·교재·편집 body를 복제하지 않는다. link는 immutable이며
   claim이 시작된 export에 나중에 덧붙일 수 없다. 기존 v1/v2 schema bytes는 바꾸지 않는다.
7. 로컬 입력 비용은 원문 bytes+선택 질문/block/crop에 선형이다. 동일 crop member를 공유하고
   worker에는 최종 manifest가 사용하는 파일만 stage한다. 임시 원본 page는 worker에 넘기지 않는다.
8. 새 export와 link/alias를 같은 짧은 transaction으로 수락한다. 먼저 현재 study/source를 해석하고,
   출력은 기존 single-winner claim을 쓴다. saved study의 다음 revision은 다른 출력 identity다.
9. SourceStudy→PDF 입력 adapter가 기존 projection에 보강 값만 붙인다. 기존 source 역할/시각/
   학생 subset을 바꾸지 않는다. worker는 로컬 renderer이며 근거 검색/권한/저장을 맡지 않는다.
10. 같은 key/body는 같은 export다. GET/완료 replay는 새 모델·crop·렌더를 실행하지 않는다.
    source 철회/바뀐 pin·중단은 명시적 상태이며 기존 실패·완료·plain PDF 기록을 재해석하지 않는다.
11. 기존 Export 응답 family2는 같은 renderer/layout이므로 그대로 재사용하고 작은 study-export
    wrapper가 추가 source pin을 표현한다. 기존 DTO 전체의 serializer/구형 history를 다시 만드는
    대안보다 단순하며 exact study provenance도 잃지 않는다.

## 16. 저장한 개념 자료의 공개 편집·PDF transport

1. 기존 API-peer Catalog delivery RPC와 API/BFF session·CSRF를 확장한다. study/PDF owner의
   저장·권한·재실행 규칙은 transport에 복제하지 않는다. 새 service/queue/DB 표는 없다.
2. 정본은 study manifest와 기존 question/task/packet/Export Artifact다. 공개 read는 저장한
   revision의 작은 metadata와 편집 값만 반환하며 전체 원문/교재/사진 bytes를 복제하지 않는다.
3. 새 catalog-kakao-study-v1 family가 저장·조회·목록·study PDF 생성/조회 envelope를 정의한다.
   기존 delivery1/2, study-store/export schema bytes를 바꾸지 않고 해당 값을 참조한다.
4. 실제 API actor/session은 기존 request context에서만 얻는다. worker/chat UID에는 공개 operation을
   열지 않는다. 저장은 EDIT, PDF 생성/다운로드는 EXPORT, 조회는 READ와 source 현재 권한을 쓴다.
5. 정확한 study revision read와 owner/binding keyset 목록이 주요 연산이다. 기존 B-tree/index와
   immutable revision/CAS를 재사용하며 조회 비용은 선택 편집 값과 source 검증에 선형이다.
6. 공개 입력은 기존 typed edit/pin만 받는다. slot/권한/경로/임의 source를 받아 검색 경계를
   우회하지 않는다. 응답도 operation/request/binding/revision/student를 대조한다.
7. 긴 편집 body는 기존 4MiB socket 한도를 따른다. 한도를 넘은 요청/응답은 명시 거부하고
   줄이거나 잘라 성공시키지 않는다. 사진/교재 원문은 기존 권한 검사된 별도 읽기 경계다.
8. 저장 명령의 key와 If-Match는 API/BFF가 전달하고 실제 CAS/replay는 study owner가 수행한다.
   완료 PDF의 GET/재조회는 새 모델·렌더를 시작하지 않는다.
9. Studio→BFF→API→Catalog delivery→study/export owner 방향이다. BFF에는 presentation DTO와
   응답 상관 검사만 둔다. 새 편집 framework나 교재 검색기를 만들지 않는다.
10. 서비스 재시작/HTTP timeout 뒤 같은 key는 같은 저장본/출력이며 바뀐 본문은 conflict다.
    source 철회·틀린 revision·경쟁 수정은 안정된 오류로 반환하고 기존 history를 보존한다.
11. UI 임시 값만으로 PDF를 만드는 대안은 새로고침·출처·재현성을 잃는다. 이미 검증한 저장
    owner와 PDF 경로를 얇은 transport로 공개하는 것이 최소 구현이다. 실제 모델/교재·운영
    활성화는 이 source transport 검사와 별도의 gate로 기록한다.

## 17. 완료 PLAN의 자동 COMPOSE 진행

1. Catalog의 선택적 continuation은 이미 수락·제출된 PLAN의 완료를 읽고 기존 공개 Workflow
   제출 owner로 COMPOSE를 연결한다. 새 모델 실행기·실행 queue·슬롯 배정기를 만들지 않는다.
2. 정본은 task/phase의 불변 입력·Workflow/Job/Artifact 결과다. 진행은 기존 두 phase와 실행
   상태에서 파생한다. process-local 순회 cursor는 정본·재실행 승인·실패 상태가 아니다.
3. task→PLAN Workflow/plan/preset revision→검증된 결과→COMPOSE Work/Workflow를 구별한다.
   PLANNED가 아닌 완료 결과는 다음 모델로 보내지 않는다. FAILED/CANCELLED도 재실행하지 않는다.
4. accepted task의 실제 저장 owner/current 권한을 재확인한다. 원 HTTP session이 만료돼도
   가짜 actor를 만들지 않는다. 원 질문/사진·Graph/policy·교재 exact pin은 기존 owner가 검사한다.
5. 주요 조회는 준비된 PLAN과 미제출 COMPOSE의 sparse join, task PK 순서의 한 건 읽기다.
   phase PK(task,phase), workflow PK/phase의 unique workflow index를 재사용한다.
6. 작은 continuation 값과 process-local cursor만 사용한다. history 본문/모델 결과를 DB에
   복제하지 않는다. candidate 조회는 과거 phase 수에 선형일 수 있으며 초기 규모는 수천 task다.
   실제 query plan/처리량을 검사하며 근거 없이 새 scheduler/index/cache를 선행하지 않는다.
7. 한 tick은 한 task만 처리한다. process 내 tick lock은 중복 I/O를 줄일 뿐, 영속 단일 제출은
   기존 phase unique/Artifact idempotency/Workflow command key가 보장한다. 다중 process와
   재시작도 같은 입력/Workflow를 재사용한다. 긴 교재 읽기/crop은 transaction lock 밖이다.
8. 첫 PLAN은 실제 API actor가 task를 수락한 요청 안에서 준비·제출한다. 그 이전 중단은 같은
   POST/key로 복구하며, 다음 단계는 DB에서 재발견한다. GET은 모델을 시작하지 않는다.
9. continuation은 별도 background thread로 실행해 교재 I/O가 Catalog API/Runner의 source
   authorization socket 처리를 막지 않게 한다. worker가 worker를 호출하거나 NAS에 쓰지 않는다.
10. COMPOSE는 원 PLAN의 definition/preset identity를 대조한다. 초기 구현에서 사이에 current
    preset이 바뀌면 새 설정으로 대체하지 않고 명시 거부한다. 실패 기록을 성공으로 보정하거나
    새 task identity로 우회하지 않는다. 이 한계는 실제 activation 때 운영자가 확인한다.
11. 사용자가 계속 결과 확인을 눌러 다음 모델을 시작시키는 대안은 브라우저 종료/로그아웃에
    종속된다. 기존 DB phase와 공개 제출을 읽는 작은 continuation이 최소 자동 진행 경계다.
    일반 수집/질문/PDF 비AI 흐름과 기본 비활성 상태는 유지한다.

새 Catalog 실행의 preset pin은 읽은 시점의 released revision이다. Catalog에는 preset 변경
권한을 주지 않는다. `SELECT ... FOR UPDATE/SHARE`에도 UPDATE 권한이 필요하므로
([PostgreSQL SELECT 권한](https://www.postgresql.org/docs/current/sql-select.html)), 공통 resolver의
동일 검증 body를 쓰는 `read_current_execution_preset`으로 읽고 expected revision/hash를
대조한다. 기존 `lock_current_execution_preset`의 관리자/기존 실행 잠금은 유지한다. 설정이
그 직후 변경돼도 이미 해석한 revision이 최신으로 바뀌지 않는다. 이는 설정 변경과 제출을
하나의 atomic transaction으로 직렬화한다는 주장이 아니다. 영속 phase/Workflow의 단일
제출·원래 preset pin 재조회는 기존 계약대로 별도로 보호한다.

## 18. 추천 요청·완료 초안·교과서 그림의 공개 연결

1. 기존 concept task/Workflow owner를 API-peer transport로 공개한다. 별도 실행기나
   검색기를 만들지 않으며 시작만 POST이고 모든 GET은 읽기 전용이다.
2. 정본은 원 질문 revision, task intent, 두 phase Work와 완료 Job Artifact다. 공개 화면에는
   작은 task 식별·진행, 검증된 설명/인용/원본 페이지 정보만 투영한다. 원 worker 입력,
   권한, 파일 경로와 분석 본문 전체는 반환하지 않는다.
3. catalog-kakao-concept-v1은 별도 additive schema다. 기존 create/stored 계약은 참조하고
   기존 schema bytes는 유지한다. 생성은 실제 API actor와 같은 key/body를 사용한다.
4. 목록은 owner/binding/task ID의 기존 B-tree keyset, 상세는 task/phase PK, 원본 그림은
   task ID+완료 COMPOSE의 page key로 조회한다. UUID 순서는 최신순으로 표시하지 않는다.
5. 한 목록은 최대 100개 작은 값이며 결과 투영은 최대 6개 block/24개 capture다. 직접
   index lookup과 bounded iteration을 쓰고 전체 history/result를 읽지 않는다. 새 DB/index는 없다.
6. 원본 PNG는 기존 Artifact owner의 검증 stream을 통해 별도 전달한다. 실제 권한/현재
   source·exact 교재/페이지·hash/media/크기를 재검사하며 임의 artifact/member/path를 받지 않는다.
   썸네일 조회마다 모든 crop을 재생성하지 않는다. 최종 PDF crop은 기존 adapter 책임이다.
7. source 읽기/모델은 긴 DB 잠금 안에서 실행하지 않는다. start의 단일 제출은 기존
   task/phase unique·Workflow command가 보장한다. 읽기는 새 작업/실패 retry를 만들지 않는다.
8. Studio는 packet의 질문 pointer로 선택 질문만 조회해 실제 room/version을 얻는다.
   추천은 사용자 선택 전까지 편집본에 반영하지 않는다. 설명 메모를 보존하며 선택 block과
   capture index만 기존 StudyQuestionEdit에 저장한다. 다른 학생/늦은 응답을 버린다.
9. 현재 actor/session은 API context만 제공한다. 일반 worker/채팅 UID에는 이 공개 RPC를
   허용하지 않는다. owner·질문/source 철회는 stable error이며 다른 source/latest로 대체하지 않는다.
10. RESERVED/PREPARED는 모델 완료가 아니다. 실제 Workflow 실패/취소, PLAN의 NEEDS_INPUT,
    COMPOSE의 NO_MATCH/DRAFT_READY를 구분한다. 완료 result pin 없이 추천을 확정하지 않는다.
11. 매번 전체 교재나 crop을 JSON에 복사하는 대안은 비용/권한/재현성을 해친다. 작은
    공개 projection과 기존 binary boundary를 사용하는 것이 현재 흐름의 최소 연결이다.

실제 COMPOSE 저장 검증에서 normalized crop의 소수 좌표가 기존 integer-only 메시지
serializer에 거부됨을 확인했다. 메시지/제어/manifest canonical 규칙은 변경하지 않는다.
개념 결과 adapter만 기존 pure contract의 finite-number JSON serializer를 사용하고,
Artifact store의 명시적 serialized-result 입구에서 canonical bytes와 job/artifact/revision
identity를 대조한 뒤 동일 staging/commit 로직을 쓴다. 이 family의 결과 재조회와 공개 응답도
같은 finite-number encoding을 사용한다. DB에는 여전히 작은 결과 header만 두며,
schema/request/source 검증을 건너뛰거나 기존 실패를 성공으로 해석하지 않는다.
