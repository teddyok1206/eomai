# KakaoTalk 질문 자료의 개념 보강·Studio 편집

상태: **2026-11-17 사용자 요구 확정, 후속 설계. 아직 구현·운영 활성화 아님.**

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
