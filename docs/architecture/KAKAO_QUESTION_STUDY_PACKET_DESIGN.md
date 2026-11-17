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
