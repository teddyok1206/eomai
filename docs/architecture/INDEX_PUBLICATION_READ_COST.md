# INDEX 게시 과정의 반복 해석 비용 줄이기

2026-11-09 UTC. 사용자 요구는 같은 임베딩 결과를 더 빨리 등록하는 것이다.
완료된 풀이보고서·벡터·실패 이력, 입력 projection, 모델, CPU/CUDA space,
수치 batch size와 현재 실행 pin은 변경하지 않는다.

## 관측과 범위

설치 INDEX `2229937a`의 15:08:53–15:56:51 UTC 로그에서 4-target 묶음은
2,872초였다. 같은 구간 자료 승인·풀이 읽기 stage는 각각361회, population SQL
재확인은33회였다. stage 누적 시간은 CPU/GPU owner thread의 겹친 구간을 포함하므로
전체 경과시간에 단순 합산하지 않는다. GPU 사용률0만으로 정지라고 판단하지 않는다.

Registry는 중복·경합 보호를 위해 정상 savepoint를 사용한다. 기존 INDEX read set은
savepoint에서 무조건 strict capture로 돌아가며, 등록 전·후 동일 source를 재해석한다.
수치 shard 또한 pointer/hash 검사와 별개인 JSON/Pydantic 해석이 반복된다. 실제
stack/동일 입력 benchmark로 비용을 나누고 효과가 없는 후보는 반영하지 않는다.

20초 nonblocking stack 표본의 active stack12.95초 중8.05초가 `Registry.combine`에
있었다. Catalog `validate_contract`가 매 호출 JSON Schema validator를 새로 만들며
설치 schema registry 전체를 합치는 비용이다. 검증 결과를 캐시하지 않고, 기존
hash-pinned schema별 validator/resolver만 bounded LRU로 재사용한다. 입력은 매번 같은
JSON Schema/format checker로 검증한다. schema/package가 바뀌면 새 설치 프로세스가
새 registry를 로드한다. 새 의존성이나 동적 schema 변경 기능은 없다.

## 설계 경계

1. 소유: Catalog의 INDEX population read set과 기존 Registry Artifact reader.
   Workflow/CAS/queue/numerical executor의 책임을 옮기지 않는다.
2. 정본: 현재 source·Graph·policy·Artifact·producer 관계 및 immutable bytes.
   재사용 값은 짧은 transaction-local 파생 값이며 별도 DB/NAS cache가 아니다.
3. 논리ID/revision/Artifact/hash와 source membership, text projection은 그대로다.
4. 매 fence의 실제 서비스 권한·현재 SQL dependency digest·Artifact provenance를 유지한다.
   현재 transaction frame이 바뀌거나 dirty/new/deleted session이면 strict로 돌아간다.
5. 지배 접근은 같은 scope 반복 조회, exact transaction identity 확인, bounded member lookup이다.
6. 기존 frozen capture와 session-local 단일 read set, 기존 bounded decoded-member LRU를 쓴다.
   새 framework/전역 registry/영속 cache/DB index는 없다.
7. source 해석은 같은 clean transaction frame에서1회, 관계 관측은 기존 각 fence에서
   O(N+관계수)로 유지한다. 메모리 상한과 source/page bounds를 늘리지 않는다.
8. root뿐 아니라 정확한 현재 savepoint 객체를 고정한다. commit/rollback/형제 savepoint/
   새 root로 넘어가면 이전 frame의 capture를 재사용하지 않는다. 인위적 flush는 없다.
9. 기존 일반 조회의 clean-root 요구는 유지한다. INDEX의 검증된 transaction frame용
   관측 진입점만 분리하고 동일 SQL row-observation 구현을 재사용한다.
10. 변경된 dependency/hash/권한은 기존 명시적 오류로 거부한다. 최신값 치환·재계산·
    무한 retry를 추가하지 않으며 실패 이력을 성공으로 바꾸지 않는다.
11. 단순 batch/window 확대는 과거16-target 시간 초과가 있어 이번 대안에서 제외한다.
    검증 생략·timeout 확대·cache 용량 확대 대신 같은 값의 반복 해석만 제거한다.

## 검증과 운영 인계

- 동일 입력 결과/serialization equality, 반복 parse/capture 호출 수, 변경·취소·삭제·
  권한·hash 거부, root/thread/scope와 savepoint commit/rollback/형제 경계 검사.
- disposable PostgreSQL에서 현재 관계 변경과 동시 변경, Registry 저장·재전송 검사.
  운영 DB에 pytest를 실행하지 않는다.
- source format/lint/type/focused tests 및 installed wheel 검증.
- 정상 진행 중인 INDEX는 같은 요청을 자연 완료하는 기존 graceful handoff를 사용한다.
  INDEX owner만 호환 교체하고 numerical runtime/API/Web/QUERY를 재시작하지 않는다.
- 완료 데이터의 기존 identity/hash 보존, 새 실제 batch의 완료와 단계별 시간으로
  효과를 보고한다. unit PASS만으로 운영 처리량 개선을 주장하지 않는다.

## 배포 전 결과

- 동일 schema의 작은 공개풀이 JSON1,000회 검증,3회 중앙값:
  기존0.5754초 → 규칙 재사용0.0347초(16.57배). 입력마다 실제 schema 검증은 그대로다.
  이는 CPU 규칙 구성 부분의 합성 측정이며 전체 batch 속도 개선율이 아니다.
- 동일 shard25회 읽기: JSON/model 해석50→2회, 수치 finite/L2 검사25→25회,
  출력 행 동일. 0.1080→0.00867초의 작은 fixture 측정이다.
- 동일 savepoint25회 조회: strict source capture1회, 현재 권한/provenance25회 유지.
  frame 전환/rollback/형제 및 concurrent source 변경은 별도 disposable DB로 검증했다.
- INDEX read set unit20 PASS, disposable PostgreSQL16 PASS. shard/Registry 관련169 PASS,
  최종 validator/encoding/delivery/read-set/dependency focused155 PASS. suite는 겹치므로
  합산하지 않는다. 추가 계약 resource 검증은 운영 보고에 기록한다.
- 최초 두 신규 테스트 실패는 date-time format 지원을 가정한 fixture 문제였다.
  기존 validator도 동일하게 그 형식을 검사하지 않는 설치 환경임을 확인했고,
  기존 내장 IPv4 format과 실제 cross-schema 잘못된 service ID로 동등성을 검사했다.
  runtime format 정책이나 dependency는 변경하지 않았다.
