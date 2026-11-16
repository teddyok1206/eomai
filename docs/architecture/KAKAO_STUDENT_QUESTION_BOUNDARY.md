# KakaoTalk 학생·질문 편집 경계

기준: Kakao 채널 통합 설계서 §§7–9. 구현 중인 결정이며 운영 활성화 증거가 아니다.

## 학생 디렉터리

- Catalog가 현재 operator 소유 학생과 표시 revision을 관리한다. 이름은 식별자가
  아니므로 동명이인을 허용한다. 학생 생성/이름 변경은 원본 대화나 문항 DB를 수정하지 않는다.
- 정본은 student logical row, 작은 immutable display revision, immutable command receipt다.
  `student_id`, `display_revision_id`, 표시 정보의 SHA-256을 분리한다. 학생 표시 이름은
  이 private 테이블에만 저장하며 Job metadata와 일반 log에 복제하지 않는다.
- 주요 접근은 owner+student ID 조회, owner+student ID keyset 목록, owner+intent key
  재전송, 짧은 row lock/CAS 변경이다. B-tree/unique constraint로 O(log N + page size),
  공간 O(학생 수 + 변경 수)이다. 한 번에 최대 100명만 반환한다.
- current/previous/result revision은 같은 학생과 연결하는 composite FK로 보호한다.
  여러 명이 같은 이름을 써도 병합하지 않는다. 변경 transaction에는 현재 세션·권한
  확인, intent lock, CAS, 새 revision·receipt·current pointer 갱신만 들어간다.
- 재전송은 현재 권한을 다시 확인하되 원래 result revision을 반환한다. 같은 key의
  다른 요청은 conflict다. 동시 이름 변경은 하나만 성공하며 stale 부모는 412로 연결한다.
- retired 학생은 신규 mapping/packet에 사용할 수 없지만 기존 packet의 정확한 표시
  revision은 보존한다. retirement는 물리 삭제가 아니다.
- 별도 student system/framework나 문항/Graph 엔티티 재사용은 하지 않는다. 이름 한 열만
  갱신하는 대안은 이미 출력한 자료의 학생 표시를 바꾸므로 revision이 필요하다.

## 질문·packet 및 runtime 연결

질문과 packet의 큰 선택 목록/본문은 Artifact manifest다. 작은 source/학생/mapping
revision pins와 조회 projection만 DB에 둔다. 질문 편집은 순수 규칙에서 먼저 검증하고
발행 후 짧은 CAS로 수락한다. split/merge는 같은 binding·room·student만 허용한다.
source occurrence와 표시 교정을 분리하며 미확보 사진은 required set에서 제거하지 않는다.

Catalog → Orchestrator가 staged inputs/실행 fence를 소유하고 worker는 로컬 typed command만
실행한다. offline renderer, 카카오 browser, 원격 gateway는 서로 다른 권한이다.
고정된 packet/student subset 이외의 정보를 worker가 조회하거나 추론하지 않는다.
이 문서는 private runtime 설치·실제 카카오 capability·동시성 PASS를 대신하지 않는다.

### 질문과 packet의 Artifact 발행

- `kakao_question_publication.py`는 순수 편집 결과를 기존 Catalog Artifact owner에
  전달한다. 새 registry/commit engine을 만들지 않는다. 질문은 원문 포인터·선택/교정,
  packet은 exact 질문 revision의 순서를 발행하며 사진/CSV를 복사하지 않는다.
- 질문 logical/revision과 Artifact logical/revision/hash를 각각 유지한다. publication Job은
  수집 task·사용자 편집 명령과 별도다. 일반 Job metadata는 식별자/hash/count만 담는다.
- 비용은 O(manifest bytes + 선택 block 수), packet은 O(선택 질문 수)다. 입력은
  200개 이하 immutable question pointers이고 큰 본문은 별도 Artifact에 남는다.
- 현재 권한·mapping/source·fence는 호출 use case가 발행 전/직전/직후 재확인한다.
  callback 자체는 권한 증명이 아니며 adapter를 public endpoint로 직접 노출하지 않는다.
  packet의 blockers/학생/순서는 exact 질문들로 다시 계산해 비교한다.
- 기존 publication의 logical revision별 멱등 key와 request hash를 쓴다. 응답 손실 뒤에는
  같은 revision을 재전송하고 내용이 바뀌면 conflict다. 발행 후 권한/CAS 실패는
  미채택 Artifact로 남기고 현재 질문 pointer를 바꾸거나 결과를 공개하지 않는다.
- DB current pointer 수락은 이후 짧은 별도 transaction이다. 발행 중 DB row lock은 없다.
  단순 overwrite 대안은 과거 packet/다운로드와 동시 편집을 깨므로 사용하지 않는다.

`kakao_render_projection.py`는 owner가 이미 권한·수명주기를 확인한 packet의 한 학생
subset만 PDF local manifest로 투영한다. immutable question과 정규화 source는 keyed map으로
한 번 찾고, 본문 span은 명시적 worker 입력 경계에서만 물질화한다. 이미지 Artifact pointer와
로컬 member의 hash/media가 맞아야 하며 다른 학생의 추가 입력은 거부한다. 원본 회전/crop
지시는 renderer DTO로 전달하고 원본 bytes를 바꾸지 않는다. 이 순수 투영 자체는 인증,
NAS read, DB claim, worker 실행을 하지 않는다. 원래 question order·text/image interleaving·
reply 포함 정책을 보존하며 미확정 날짜는 임의 날짜로 대체하지 않는다.
