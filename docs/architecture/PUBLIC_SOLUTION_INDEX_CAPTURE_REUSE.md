# 공개 풀이 INDEX의 반복 자료 읽기 줄이기

2026-11-09 UTC. 완료된 풀이보고서·encoding·binding·기존 index와 실패 이력은 변경하지 않는다.
새 모델 실행, 입력 문구 변경, vector 재생성, migration은 이 수정 범위가 아니다.

## 확인한 병목과 선택

운영 INDEX는 숫자 계산 뒤에도 전체 모집단을 여러 번 다시 읽고 검증한다. 읽기 전용
1,556건 profile에서 같은 root의 두 번째 순회에도 JSON Schema/Pydantic 검증이 반복됐다.
기존 decoded LRU만 확대하는 실험은 첫 69.87초, 다음 54.74초로 남았다. 이는 별도 진단
프로세스의 자료 조회 시간이며 GPU 계산 시간이나 개선된 운영 처리량이 아니다.
캐시 한도 확대를 운영 해법으로 채택하지 않는다. 현재 관리 프로세스의 2GiB 한도와
swap 사용도 확인했으므로 큰 모델/원문을 더 보관하는 방식은 피한다.

## 작은 설계

1. 책임: Catalog의 기존 공개 풀이 population capture. INDEX의 같은 root 트랜잭션에서
   이미 해석한 작은 capture를 재사용한다. QUERY·worker·벡터 엔진 책임은 바꾸지 않는다.
2. 정본: 현재 Graph/Item/분석·보고서/producer/Artifact 관계와 기존 immutable 파일.
   read set은 파생 메모리 값이며 DB·NAS·별도 영속 cache를 만들지 않는다.
3. logical/revision/Artifact/hash 구분과 CPU/CUDA space, recipe, model, 공개 풀이 text는 그대로다.
4. 매 사용마다 실제 service·policy·Graph 권한을 검사한다. 기존 completed ranking의
   source 의존관계 관측을 재사용해 Item·component·원본 기출 provenance·accepted V10/V11·
   창작 Workflow/step/plan·Artifact/job의 현재 digest를 비교한다. missing-report와
   unranked source도 포함한다. 다른 root/thread/설정/scope에는 재사용하지 않는다.
   savepoint·아직 flush되지 않은 변경이 있는 session에서는 기존 strict 경로를 쓴다.
5. 접근은 같은 exact 모집단의 반복 읽기와 동등성 검사다. 처음 한 번 strict capture,
   이후 원래 fence마다 indexed/bounded SQL observation을 사용한다. 동일한 capture 전후
   관측도 비교해 중간 변경을 거부한다.
6. 기존 keyset page와 정렬된 SQL row digest, frozen capture를 사용한다. root당 단일
   read set을 보관하며 원문/ORM/벡터를 추가 복사하지 않는다. SQL은 여전히 O(N+관계수),
   비싼 원문 해석은 root당 O(N) 한 번이다. 최대 모집단·page bounds는 유지한다.
7. 처음 strict reader가 원본 bytes/hash를 확인한다. 그 root 안에서만 재사용한다.
   다음 root는 다시 물리적 읽기와 전체 strict admission을 수행한다. 전역 authority
   cache나 권한·lifecycle 유예는 없다.
8. transaction·lease·claim·publication·재시도 소유자는 그대로다. 관측 불일치에는
   명시적 오류를 내고 최신 revision 대체나 자동 재계산을 하지 않는다.
9. 의존 방향은 Catalog infrastructure 안에서의 기존 observer 분리/재사용이다.
   domain이나 contracts에 DB/파일 의존성을 추가하지 않는다.
10. 테스트: 최초/후속 결과 equality, 동일 root의 strict capture 횟수, 모든 의존관계 변경,
    권한·root·thread·scope 경계, disposable PostgreSQL 관측/동시 변경, 실제 읽기 시간.
11. 단순한 대안인 cache 크기/timeout 확대는 반복 자료 구성 자체를 없애지 않는다.
    source 검증 생략도 불가하다. 기존 검증의 현재 상태 관측을 재사용하는 것으로 제한한다.

## 운영 인계

기존 계산을 끝낸 안전한 경계에서 설치본을 교체한다. 완료 encoding/report의 identity·hash
집합을 전후 비교하고 기존 행의 변경·삭제가 없음을 확인한다. 실제 다음 batch의
source 준비/commit/COMPLETED 시간과 GPU 상태를 따로 보고한다. 소스 테스트만으로
운영 병목 해결이나 전체 corpus 완료를 선언하지 않는다.

## 배포 전 검증

- 실제 1,556-source 읽기 전용 비교: 기존 strict capture 70.62/70.45초,
  같은 관계의 fresh SQL 관측 11.37/11.34초. 반복 읽기 부분의 약 6배 차이이며
  모델 연산이나 전체 batch 처리시간 개선율은 아니다.
- 관련 unit/dependency 264 PASS, 최종 composition/timing/context 84 PASS
  (서로 겹치는 suite이므로 합산하지 않는다).
- disposable PostgreSQL: source/Artifact/보고서·창작 provenance 변경, 동시 변경,
  saved ranking 재조회와 keyset/scale 79 PASS. 첫 실행의 SQL fixture 오류 3건은
  fixture만 수정했고 실패 보고서는 보존했다. 운영 DB에 pytest를 실행하지 않았다.
- Ruff·format·focused mypy 6개 source·diff 검사를 통과했다. 전체 import 추적 mypy의
  기존 미변경 두 모듈(`registered_review_embedding_capture`, `creative_learning_proposal`)
  union 오류 5건은 이 수정의 통과로 재분류하지 않는다.
- 운영 전 기존 encoding/binding/index revision/accepted analysis/registered report의
  모든 행을 key와 metadata hash로 고정했다. 배포 후 기존 행의 누락·변경이 없음을
  다시 대조한다. 이후 새 완료 행은 허용하며 정본이나 기존 vector를 삭제하지 않는다.

## 실제 저장점 호환성 보정과 준비된 CUDA publication 복구

첫 운영 후보는 Registry가 중복 등록을 보호하는 정상 savepoint를 거부했다. 최초 검증에서
이 실제 호출 조합을 놓쳤다. 기존 성공 자료는 보존됐으나 새 CUDA 4개는 수치 작업이
SUCCEEDED이고 INDEX_PREPARED인 채 저장이 중단됐다. 이 실패 로그를 삭제하지 않는다.

read set은 clean outer read transaction에서만 사용한다. 정상 savepoint나 아직 flush되지 않은
변경이 있는 session에서는 read set을 비우고 기존 strict capture를 그대로 실행한다. 기존 SQL
observation의 clean-root 조건을 완화하지 않는다. 실제 disposable DB에서 commit/rollback과
이 경로의 호출을 검사한다. 기존 등록 transaction/CAS는 바꾸지 않는다.

준비된 4개를 재계산하지 않기 위해 기존 `index_publication_recovery`의 publication-only
경계를 CPU와 CUDA 모두에 적용한다. 기존 JSON Schema 2020-12의 정확한 request/intent/
prepared command/current service+policy pins를 그대로 사용한다(장치를 CPU로 제한하지 않는
기존 wire 형식). 장치는 원래 hash-검증된 request에서 읽으며 양쪽 current grant의 모델·장치·
자료 범위가 동일해야 한다. root/schema-owner의 명시적 유지보수만 가능하며 일반 service
admission이나 worker 권한을 넓히지 않는다. 새 API·queue·schema·DB migration은 없다.

정본은 기존 immutable numerical receipts·준비된 index와 original Workflow다. indexed ID
조회와 기존 관계 잠금/registry CAS, 동등 source policy 검사, retained original source pins,
공식 Runner의 expired command 재claim·completion을 재사용한다. 원래 head가 이동했으면
거부하며 자동 최신 치환은 없다. `NoNumericalRecoveryExecution`의 모든 실행 메서드는
여전히 예외를 낸다. CPU/GPU 선택은 계산 권한이 아니다. 실패/완료 이력 재해석 없이
미완료 publication만 이어간다. 새 모델 실행/기존 vector 재생성보다 이 기존 경계를
장치에 독립적으로 적용하는 것이 작고 데이터 손실 없는 복구다.
