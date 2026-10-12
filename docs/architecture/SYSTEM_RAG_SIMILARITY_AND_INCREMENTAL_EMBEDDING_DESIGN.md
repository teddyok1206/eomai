# GraphRAG·문항 유사도 통합과 증분 임베딩 설계

작성일: 2026-10-12 UTC.
기준 source: `9491819683c7a0d72e653d63b15668367432442a`.
상태: **구현 계획**. 이 문서의 신규 기능은 아직 구현·운영 활성화된 기능이 아니다.
기간은 사용자 요청에 따른 **1~2일 규모의 집중 개발 계획**이며, 검증·권한·배포 gate를
생략하기 위한 마감이 아니다. 승인된 최초 유사도 설계 원문과 역사적 실행은 변경하지 않는다.

## 1. 목표와 대화에서 합의한 방향

관련 문항을 찾는 것에서 끝나지 않고, **각 기능이 필요한 순간에 관련 문항과
참고할 이유·차이·근거의 한계를 함께 받게 한다.**

- GraphRAG는 개념·출처·교육과정·근거를 연결하고 실제 이용 가능한 자료인지 확인한다.
- 로컬 임베딩은 표현이나 소재가 달라도 참고할 만한 조건·추론을 가진 후보를 찾는다.
- Codex는 후보의 어느 부분이 이번 작업에 도움이 되는지, 무엇이 다르거나 부족한지 설명한다.
- 교과서는 개념과 설명의 근거, 기출·등록 문항은 출제 방식과 풀이 착상의 사례로 활용한다.
- 숫자 하나로 과학적 정확성·전이·승인·표절을 판단하지 않는다. 사용자 안내뿐 아니라
  시스템의 자동 의사결정도 이 원칙을 지킨다.
- 각 화면에 검색 코드를 복사하지 않는다. 기존 Catalog·Orchestrator 경계에 공통 후보
  조회·근거 전달 use case를 두고, 각 기능은 목적에 맞는 typed 요청만 보낸다.
- 권한, revision/hash 확인, 중복 처리, 결과 재사용은 공통 경계의 책임이다.
- 결합 순서는 **공통 전달 경로 → 기출변형 → 신규 출제·검토 → ChatGPT·시험지 구성**이다.
- 추가 요청: 같은 로컬 모델·입력으로 CPU/GPU 임베딩을 실측 비교하고, 정확성·격리·
  capacity gate를 통과하면서 성능이 우수하면 GPU를 기본 실행 방식으로 활성화한다.

| 기존 기능 | 결합할 내용 | 하지 않는 판단 |
|---|---|---|
| 신규 출제 | 평가 목표와 연결된 기출 후보, 참고할 조건·추론, 다른 점을 출제 근거로 제공 | 높은 점수를 좋은 문제/정답으로 간주 |
| 1:1 기출변형 | 원문에서 유지할 착상과 바꿀 조건·추가 추론을 구분 | 숫자·이름 변경만으로 새 출제 가치 확정 |
| 검토·재교 | 조건 누락, 잘못된 변형, 지나친 반복을 관련 문항과 비교 | 점수만으로 차단·승인; 기존 최대3교 흐름 대체 |
| 일반→ChatGPT | 소재는 달라도 풀이 아이디어가 연결되는 문항을 찾아 출처와 함께 설명 | 검색 허가를 출제·승인·삭제 권한으로 확대 |
| 25문항 구성 | 같은 개념과 같은 착상의 반복을 분리해 점검 | 한 문항 문제 때문에 전체 자동 재생성 |
| 문서 검토의 후속 확장 | 구조화된 문항 위치를 기준으로 관련 사례를 참고 | 개인 업로드를 승인 없이 공용 corpus에 편입 |

이 연결은 원본 풀이보고서, 정본 문항, Graph 근거·영수증을 활용하는 **보조층**이다.
기존 검색·출제·검토·사람 승인·HWPX 의미를 대체하지 않는다.

## 2. 현재 재사용할 수 있는 것과 신규 구현할 것

현재 기능은 실제 승인 기출520개/표현1560개의 bounded BGE 실험, 고정 두 쌍의
정본 비교·근거 검증·동일 요청 재전송까지 완료했다. 상세 증거는
[최종 검증 보고서](../status/ITEM_INFERENCE_TRANSFER_FINAL_ACCEPTANCE_2026-10-12.md)에 있다.
이는 **상시 운영 벡터 인덱스나 자동 증분 갱신의 완료 증거가 아니다.**

기존 실험은 임시 vector matrix를 계산하고 순위·측정 결과를 보관한다. 영속 vector
Artifact와 운영 source-to-vector 등록부는 아직 없다. 따라서 영속 인덱스의 최초 구축에는
현재 허용된 자료를 한 번 벡터화하는 별도 실행이 필요하다. 옛 점수로 벡터를 복원하거나,
기존520개 실험을 새 인덱스의 완료 기록으로 바꾸지 않는다.

| 경계 | 재사용 | 추가할 경계 |
|---|---|---|
| 자료 승인·출처 해석 | Catalog의 정본 source/report/Graph/policy resolver | 승인 source와 임베딩 coverage의 작은 관계 |
| 비교 표현 | 승인 report의 deterministic projection·세 view | 지속적인 revision 단위 갱신 |
| 수치 계산 | 격리 offline 모델·무절단·차원/finite/norm 검증 | 재사용 가능한 vector Artifact |
| 실행 | 기존 Job/command/claim/lease/idempotency | 명시적인 증분 작업 purpose와 admission |
| 저장 | Orchestrator의 검증·Artifact commit | vector member/인덱스 manifest·binding |
| 검색 | 공식 lexical/Graph 검색과 실제 사용자 재인가 | 선택적 vector 후보 adapter·공통 전달 결과 |

기존 Item 비교 표현은 `PAST_EXAM/APPROVED_ITEM`과 승인된 풀이보고서에 대한 계약이다.
교과서/document source를 Item인 것처럼 넣지 않는다. 교과서는 기존 EducationalDocument
resolver와 별도 chunk 표현을 사용해야 한다. 새 source class 지원은 별도 successor와
검증이 필요하며 인덱싱 자체가 API·정책의 지원 범위를 넓히지는 않는다.

## 3. 증분 갱신의 의미

사용자가 말한 incremental algorithm은 다음 의미로 구현한다.

1. 신규·개정된 **승인 revision**만 파악한다.
2. 실제 인코딩 입력이 같은 기존 벡터는 재사용한다.
3. 빠진 벡터만 계산한다.
4. immutable vector shard와 source binding을 등록한다.
5. compatible 인덱스의 새 revision을 만들고 검증 후 current pointer를 전진시킨다.

이는 **모델 가중치의 온라인 학습/파인튜닝이 아니다.** 고정 모델로 데이터를 벡터화해
검색 자료를 축적한다. 모델을 새로 학습하는 작업은 별도 목적·데이터·검증이 필요하다.

| 변경 | 증분 처리 |
|---|---|
| 새 승인 자료 | 필요한 view/chunk의 벡터만 생성 |
| source/report revision 변경 | 새 표현과 관계 생성; 실제 입력 text가 같으면 계산 재사용 |
| Graph에 새 자료 추가 | membership·coverage 갱신; 관련 없는 자료 전부 재인코딩 금지 |
| source 권한 철회·폐기 | 현재 검색 대상에서 제외; 불변 이력은 보존 |
| 모델·tokenizer·pooling·prefix·정규화 변경 | 별도 encoder space 구축·검증; 기존 space와 혼합 금지 |
| view/chunk 표현 규칙 변경 | 새 view recipe/namespace; 과거 표현의 의미 덮어쓰기 금지 |

### Graph revision 변경과 벡터 계산을 분리한다

현재 profile은 Graph pin도 hash에 포함한다. Graph가 달라졌다는 이유로 profile hash만
비교하면 모든 문항을 불필요하게 재계산할 수 있다. 따라서 다음 두 identity를 구분한다.

- **source association:** source/report/profile/Graph/policy의 exact revision·hash와 lifecycle.
- **encoding identity:** storage 격리 범위, encoder space, exact 인코딩 입력 text hash.

같은 encoding identity의 수치 Artifact는 재사용할 수 있다. 그러나 새 Graph/profile의
관계는 별도로 검증·등록한다. 서로 다른 source를 같은 문항으로 병합하거나 새 권한을
옛 벡터의 존재로 증명하지 않는다. normalization은 숫자·단위·부정·조건을 없애지 않는다.

## 4. 학습 완료와 자동 임베딩을 연결하는 흐름

```text
자료 업로드 → 기존 추출·분석·검증·승인 → 정본 등록 → 기존 Graph 출판
                                                     │
                            commit된 source/membership 차이 확인
                                                     │
                            기존 Orchestrator의 증분 Job admission
                                                     │
                         Catalog의 exact source 해석·표현·재인가
                                                     │
                     격리된 로컬 encoder → local vector 결과
                                                     │
                      Orchestrator 검증·vector Artifact commit
                                                     │
                      Catalog binding·인덱스 successor 등록
                                                     │
                           기존 기능의 공통 후보·근거 조회
```

업로드, PDF 변환, 분석 결과 생성만으로 검색 가능한 자료가 되지 않는다. 가장 안전한
기본 시작점은 **commit된 Graph publication과 exact source membership**이다.
등록·승인·출판의 각 단계를 분리하고, 승인대기 Item의 Preview/HWPX 이용 자격을 공용
RAG·vector 검색 자격으로 확대하지 않는다.

임베딩은 원 학습 transaction 밖의 후속 작업이다. 임베딩이 대기/실패해도 이미 성공한
원 학습을 실패로 바꾸지 않는다. UI에는 학습 상태와 검색 준비 상태를 각각 표시한다.
자료가 정상 학습됐지만 벡터 준비 전인 상태를 API 장애로 취급하지 않는다.

### 알림 유실과 중복을 견디는 최소 연결

현재 Catalog에는 승인/Graph publication의 durable 기록이 있고 별도 범용 outbox 구현은
확인하지 못했다. 첫 범위에서는 기존 기록을 reconcile하는 후속 owner use case를 사용한다.

- 알림은 빠르게 작업을 시작시키는 힌트다. 정본 완료 증거는 commit된 기록이다.
- Catalog가 공식 query로 누락된 source/view/space 관계를 반환한다.
- Orchestrator가 기존 지원 queue에 고정 key의 작업을 접수한다. Catalog는 Runner
  테이블을 직접 쓰지 않는다.
- 같은 source 사건이 반복돼도 unique encoding/binding key와 기존 idempotency로
  동일 결과를 재사용한다.
- 재시작·알림 유실은 bounded reconciliation으로 복구한다. timestamp watermark만으로
  완결을 판정하지 않는다. 지연 commit·같은 시각 사건을 놓치지 않도록 missing-binding
  조회가 최종 기준이며 cursor는 최적화 수단이다.
- 새 broker·queue·scheduler framework를 먼저 도입하지 않는다. event outbox가 실제로
  필요해지면 기존 source owner transaction에서 설계·검증한다.

## 5. source 종류별 표현과 eligibility

| 자료 | 표현 단위 | 기본 gate |
|---|---|---|
| 기출 | 정본 Item question text, 승인 report의 조건·관계·추론·오개념, metadata | exact occurrence/source, 승인 분석·report, Graph membership·현재 정책 |
| 생성 문항 | 위 Item 표현; 기출과 별도 lineage | 해당 revision의 공식 승인·active 상태, 허용된 Graph 출판, accepted V10 풀이보고서 |
| 교과서 | 승인 document revision의 page/paragraph/표·수식·개념 anchor chunk | document 승인·접근/처리 권한·정본 텍스트·Graph membership |
| 개인 검토 업로드 | 기본적으로 공용 인덱싱 제외 | 사용자가 자료 학습으로 별도 편입하고 공식 gate를 통과할 때만 추가 |
| 개인 ChatGPT 대화 | 자동 학습·공용 인덱싱 제외 | 대화 삭제/조회가 자료 corpus 변경이 되지 않음 |

현재 Item의 `CONTENT_ONLY/CONCRETE_FACETS/METADATA_ONLY`는 서로 다른 view다. 교과서의
설명 chunk를 풀이보고서나 decisive claim으로 위장하지 않는다. 같은 차원이라고 서로
다른 view/purpose 점수를 임의로 합치지 않는다.

현재 Item adapter는 accepted V10 풀이보고서가 있는 revision만 profile로 구성한다.
승인·Graph 출판만 끝난 신규 Item은 자동 인덱싱 완료로 표시하지 않는다. 보고서가 없는
경우와 보고서는 있으나 핵심 추론 후보가 없는 경우를 분리하고 부분 coverage를 기록한다.
설계상 보고서 대기는 `NEEDS_ACCEPTED_SOLUTION_REPORT / PROFILE_UNAVAILABLE`로 표현하되,
이는 새 계약의 제안 상태이며 현재 배포된 enum이라는 뜻이 아니다. 보고서 없는 Item을
독립 `CONTENT_ONLY`로 인덱싱하려면 별도 successor 계약과 projection 검증이 필요하다.

overflow는 명시적인 unavailable/blocked다. Item의 핵심 조건·단위를 잘라서 fit시키지
않는다. document chunk 분할은 원 source/anchor로 돌아갈 수 있는 별도 released recipe다.

기존520개 profile의 핵심 추론 후보 있음425/없음95는 과거 고정 실험의 관측이다.
새 corpus 수의 상수가 아니다. 후보가 없어도 다른 available view는 인덱싱할 수 있지만
CRUX 근거 부족은 그대로 표시한다. 새 가짜 착상이나 자동 긍정 판단으로 채우지 않는다.

## 6. 공통 후보 조회·근거 전달 use case

각 소비자는 목적, query/source pin, 허용 source 종류, concept/unit 범위, view와 budget을
typed 요청으로 전달한다. 실제 actor·권한은 API/application의 인증 경계에서만 정한다.

1. 기존 Catalog의 공식 resolver로 현재 허용된 모집단을 결정한다.
2. 기존 Graph/lexical 후보와 optional vector 후보를 얻는다. vector가 Graph top64 안에서만
   검색하도록 제한해 다른 소재·개념의 구조적 후보를 원천 차단하지 않는다. 다만 모두
   같은 실제 권한·released source 정책의 eligible 모집단 안에 있어야 한다.
3. exact source/revision을 set/map으로 합치고 각 검색 방식·view의 순위와 score를 분리한다.
4. 상위 bounded 후보만 source를 재인가·물리화한다.
5. 필요할 때만 Codex 비교를 실행한다. 숫자·근거 없는 문장은 source Evidence가 아니다.
6. 기존 Graph Evidence/영수증과 유사도 보조 설명을 분리해서 소비자에 전달한다.

출력은 작은 pointer·typed 설명이다. 정본 문항/보고서 전체를 여러 서비스에 복제하지
않는다. 조건 대응·차이·추가 추론과 `INSUFFICIENT`를 포함하고 모델 가설임을 명시한다.
검색 가능한 자료라도 변형·복제·출판에는 목적별 권한을 다시 확인한다.

기존 기능의 optional 경로에서는 vector 미준비를 명시하고 정상 GraphRAG 경로를 유지한다.
유사도 조회 자체가 필수인 요청은 explicit unavailable로 응답한다. 누락된 인덱스를
latest나 다른 space로 바꿔 성공처럼 표현하지 않는다.

## 7. 데이터·Artifact·계약 설계

### 7.1 정본과 작은 관계

정본은 기존 source Item/document revision, 승인 analysis/report, Graph/policy와 그
Artifact다. vector와 인덱스는 재생성 가능한 보조 파생물이다. 지속 저장하므로 모델·표현
recipe·입력 hash를 pin하고 source 개정/폐기 시 association 갱신 규칙을 갖는다.

- encoder space는 모델 logical/revision ID·manifest hash, tokenizer/runtime, pooling,
  prefix, 차원, dtype, 정규화·overflow 정책을 pin한 frozen value의 fingerprint다.
- view namespace는 source projection/renderer/chunk recipe의 pin과 목적을 구분한다.
- vector shard는 immutable Artifact로 저장한다. manifest가 행 순서·차원·dtype·view·space·
  text hash 및 source-binding pointers를 검증한다. raw vector SHA와 semantic input hash는 다르다.
- 인덱스는 logical identity와 immutable revision을 갖고 ordered shard/member pointers를
  참조한다. shard 전체 bytes를 매 revision마다 다시 복사하지 않는다.
- PostgreSQL에는 identity·revision·hash·관계·상태·Artifact pointer만 저장한다.
  raw vectors/PDF/PNG/원본 문항/긴 보고서를 DB에 넣지 않는다.
- 단순 immutable space value에 독립 라이프사이클이 없으면 새 registry/table부터 만들지
  않는다. 현재 공간의 public 모델·recipe pointer를 먼저 재사용한다.

### 7.1.1 A단계의 수치 member 포맷

기존 canonical JSON serializer는 float를 허용하지 않는다. 이 규칙을 완화하거나 DB의
JSON 배열에 벡터를 넣지 않는다. 구현된 native 실행 결과는 같은 file-set Artifact의 primary
`result.json`(실행 기록), 재사용 component `shard.json`(행·수치 member의 manifest),
`vectors.f32`(유일한 수치 bytes)로 나누며, 기존 `ControlFileSetPublisher`만 commit한다.
bounded shard metadata가 실행 기록에 포함되는 것은 명시적인 검증·게시 경계다. 벡터 bytes나
원문을 중복 보관하지 않으며 기존 단일 JSON ArtifactManifest의 의미도 바꾸지 않는다.

수치 member는 header 없는 row-major float32 little-endian이다. JSON에는 정수 행 번호·
차원·바이트 수, exact 입력 및 encoding identity, raw member SHA만 기록한다. 외부
Artifact manifest SHA, semantic JSON hash, binary raw SHA는 서로 다른 값이다. commit 전
descriptor는 자기 Artifact pointer를 요구하지 않고, commit 후 공식 member pointer로 참조한다.

수치 codec의 주 작업은 bounded 순서 직렬화와 한 번의 검증이다. 표준 `struct`와 기존 SHA
함수를 사용하며 신규 dependency는 없다. shape·실제 길이·raw SHA·finite·L2 단위 norm을
확인하고 보관된 값을 재정규화해 손상을 숨기지 않는다. float32 반올림을 고려한 norm의
절대 오차 한도는 `1e-5`다. 내부 codec 상한은 3,072행×4,096차원이고 실제 모델/작업
계약의 더 작은 bound를 별도로 적용한다. codec은 순수 bytes 경계이며 filesystem·DB·
권한을 소유하지 않는다. 시간은 O(Nd), binary 공간은 O(Nd); source lifetime과 row 참조의
동시성·idempotency는 아래 Catalog binding/Orchestrator transaction 경계의 책임이다.
단순 JSON float 배열은 canonical 규칙·binary DB 금지·반복 복사 방지와 맞지 않아 사용하지 않는다.

### 7.2 프로토콜 우선

구현 전 필요한 최소 successor를 JSON Schema2020-12와 Pydantic으로 먼저 정의한다.
아래는 설계 항목이지 현재 등록·활성화된 schema 이름이 아니다.

1. 증분 vector 작업의 typed 입력/결과: exact sources·model/recipe·expected input-set hash,
   workspace manifest와 local result pointers. actor/경로/권한을 모델에 맡기지 않는다.
2. vector Artifact/index manifest: space/view·ordered rows/shards·raw hash·차원/크기,
   canonical serialization과 source association closure.
3. 공통 후보/보조 설명 context: 기존 Evidence receipt와 분리된 search provenance·
   candidate pointers·comparison references·limitations.

기존 identifier, source/member pointer, model manifest와 frozen view recipe를 재사용한다.
released Item/role/Pack/definition bytes를 수정하지 않는다. 입력 의미가 달라지는 소비자는
명시적인 compatible successor와 activation을 사용한다. 컨텐츠팀장 원문2개는 변경하지 않는다.

### 7.3 접근 패턴·인덱스·복잡도

- exact key lookup: source revision/view/space/encoding identity의 indexed binding.
- deduplication: unique key와 set; 다른 source identity를 text hash로 병합하지 않는다.
- delta processing: published eligible source와 missing-binding의 indexed anti-join.
- 작업 처리: 기존 indexed FIFO/priority·claim/lease·idempotency.
- 출판: ordered immutable shard manifest와 current-pointer compare-and-swap.
- 검색: 목적·권한·source membership을 먼저 확인한 후보에 exact cosine.

예상 relation 수는 source 수×available view/chunk 수다. source/Graph/model key의 B-tree,
binding composite unique/FK와 필요할 때의 pending partial index를 먼저 검토한다.
실제 schema·index 추가는 query plan과 기존 모델 조사를 거친다. N+1 source 조회를 피하고
bounded batch resolution을 사용한다. vector comparison은 O(Nd), shard storage는 O(Nd)다.
신경망 인코딩 비용은 별도로 실측하며 O(Nd)로 단순화하지 않는다.
초기에는 exact search를 사용하고 ANN/vector DB는 측정된 병목이 있을 때만 검토한다.

### 7.4 트랜잭션·동시성·실패

Catalog는 eligibility와 binding·인덱스 등록을, Orchestrator는 실행·staging·Artifact commit을
소유한다. source 승인 transaction에 긴 encoder를 넣지 않는다. cross-service 출판은
분산 원자성으로 표현하지 않고 deterministic replay·receipt·reconciliation으로 복구한다.

- 두 controller가 같은 source를 발견해도 같은 encoding/binding identity와 claim만 생성한다.
- timeout은 미처리 증명이 아니다. 기존 Job/command/key를 조회·replay하고 새 key로 우회하지 않는다.
- lease 만료만으로 이미 실행된 추론을 반복하지 않는다. held lease와 결과 commit을 함께 확인한다.
- vector commit 후 association 등록 실패는 같은 Artifact를 재인가·등록한다. 재인코딩하지 않는다.
- 두 인덱스 publisher의 CAS 충돌은 명시적으로 재조정한다. 기존 immutable revision은 덮지 않는다.
- 실패 이력은 유지한다. source 개정은 새 binding이지 이전 실패의 성공 재해석이 아니다.
- revoke/retire/stale/hash mismatch는 조회 시에도 재검증한다. 인덱스는 권한 캐시가 아니다.
- 이전 실패와 신규 차단의 원인이 같을 때만 supported retry를 사용한다. 무한 재시도는 없다.

신규 dependency는 기본적으로 없다. core/domain은 PostgreSQL·NAS·torch·HTTP를 import하지
않고 기존 application port/infra adapter 방향을 유지한다. 첫 회귀는 기존 CPU 격리 환경을
재사용하고 아래 GPU 비교 gate를 통과하면 기본 device를 갱신한다. encoder·worker는
DB/NAS/network에 직접 접근하지 않는다. Orchestrator만 commit한다.

## 8. 자동화의 권한·인증·capacity

상시 인덱싱은 개발자의 `guiadmin` 로그인 세션이나 root Codex auth 복사에 의존하지 않는다.
released 목적별 indexing service identity/정책이 필요하면 공식 control 경계에서 최소 권한으로
명시 등록한다. 이것은 새 authority 설계이며 현재 활성화 사실이 아니다. worker에 ADMIN을
사칭하게 하거나 sudo/Docker/eom group·NAS 접근을 부여하지 않는다.

각 검색은 실제 사용자 권한으로 재인가한다. background job의 실행 권한을 사용자에게
양도하지 않는다. query 결과·cache hit·source count에서 비허용 source의 존재도 노출하지 않는다.

CPU thread/memory/time 제한과 격리 launcher는 기존 CPU resource profile을 재사용한다.
신규 indexing purpose의 concurrency/admission은 별도 구현·release gate이며, 기존 Codex
WorkerCapacityPolicy가 이미 이 작업을 허용한다고 가정하지 않는다. 기존 Job/command와 CPU
실행 연결을 먼저 확인하고 지원되지 않는 종류는 명시적 successor로 추가한다. 작은 bounded
batch와 대화형 작업 우선순위를 사용하며 새 queue/framework를 먼저 만들지 않는다.
GPU 전환은 별도 GPU lease/admission이 필요하다. 수치 인코딩만을 위해 Codex 대화 슬롯을
상시 점유하지 않는다.

### 8.1 CPU/GPU 비교와 기본 device 결정 — 사용자 추가 요청

GPU 사용 가능성을 실제 설치된 모델·CUDA runtime·격리 launcher·GPU lease로 확인한다.
단순히 torch에서 CUDA가 보인다는 이유만으로 활성화하지 않는다. 외부 LLM API와 새
모델 다운로드 없이 현재 pin된 로컬 모델을 사용하고, Codex 슬롯과 GPU capacity는 구분한다.

- 동일한 승인 입력·view recipe·모델 revision·float32/L2/무절단 조건으로 CPU/GPU를 비교한다.
  dtype·TF32·truncation을 몰래 바꿔 속도 향상으로 보고하지 않는다.
  현재 설치된 CPU 환경은 `torch 2.7.1+cpu`이므로 CUDA 실행은 별도 보호 runtime이 필요하다.
  CPU/CUDA package flavor 때문에 model-bundle runtime pin이 달라질 경우 bundle revision은
  명시적 successor로 구분하되, 비교하는 weights/tokenizer의 upstream revision과 모든 파일
  SHA는 동일하게 유지한다. 기존 CPU manifest·격리 환경을 바꾸지 않는다.
- 작은 synthetic 입력의 shape/finite/norm 검증 후, 승인된 bounded corpus 입력으로 batch
  인코딩과 query 경로를 실측한다. 최초 seed 전체를 두 번 무작정 재실행하지 않는다.
- 모델 로드 포함 cold latency, warm encode latency, end-to-end 시간, texts/s, CPU RAM,
  GPU VRAM과 resource contention을 구분한다. 모델 warm 유지는 구현된 경우에만 측정한다.
- 부동소수점 device 차이를 bit-identical SHA로 요구하지 않는다. 동일 정본 입력을 보존하고
  cosine 오차·순위/동점 일관성·기존 불변조건을 검증한다. 실험 전 허용 오차와 반복 횟수를
  고정하고 사후 결과에 맞춰 gate를 느슨하게 바꾸지 않는다. 교육적 품질 향상으로 해석하지 않는다.
- 수치 실행 backend/precision/runtime 차이는 encoder-space identity에 반영한다. GPU가
  CPU 벡터와 같은 차원이라는 이유로 서로 다른 space의 vector를 조용히 섞지 않는다.
- GPU가 비교 workload에서 실측 우수하고 격리·권한·lease·기존 이미지 작업 회귀를 통과하면
  compatible release와 명시적 실행 policy로 기본 device를 GPU로 바꾼다. 필요하면 GPU
  space를 증분 구축·검증한 뒤 current index를 전환하고 기존 CPU space와 rollback을 보존한다.
- GPU unavailable/경합 시 CPU 사용은 사전에 정의한 admission 정책으로만 허용하며 선택
  device·대기/대체 사유를 기록한다. hash/권한/결과 무결성 오류를 CPU retry로 숨기지 않는다.

완료 증거는 동일 입력 hash·모델/runtime/device pin, benchmark 결과, 정확성/검색 일관성,
lease·resource 회귀와 기본 policy의 실제 활성 상태다. GPU가 개선되지 않거나 지원 gate를
통과하지 못하면 CPU를 유지하고 실제 이유를 기록한다. GPU가 더 좋으면 기본 활성화까지
이번 goal 범위이며, 비교만 하고 요청을 완료했다고 보고하지 않는다.

개발 인증은 같은 실제 operator/session을 supported refresh와 `/me`로 확인하며 이어간다.
비밀번호·토큰을 저장해 다시 로그인하거나 fresh-auth·권한·TTL을 무력화하지 않는다.
Linux sudo는 별도 인증이며 동일 operator pane을 재사용한다. 보안상 만료·철회되거나
배포 때문에 안전한 session continuation이 없으면 그때만 필요한 재인증을 명시한다.
‘인증 한 번’은 영구 권한이나 무기한 NOPASSWD 설정을 뜻하지 않는다.

## 9. 1~2일 구현 목표와 순서

기간 가정은 집중 개발·Codex 지원과 필요한 운영 인증의 가용성을 전제로 한다.
시간보다 exit gate가 우선이다. 범위가 커지면 핵심 수직 경로를 닫고 나머지를 미완료로
보고한다. 완료하지 않은 연결을 deadline 때문에 PASS로 표시하지 않는다.

### 착수 전 — 문서·GitHub·안전 정리·인증

1. 이 설계와 README를 갱신하고 commit/push한다.
2. 실제 불필요한 로컬 산출물만 목록·owner·사용 여부를 확인해 recoverable하게 정리한다.
   원본 corpus/520개 이력·정식 Artifact·원 실패·모델·배포/rollback 자료는 보존한다.
3. 기존 pane·프로세스·인증 상태를 확인하고 동일 작업 pane을 준비한다.
4. 실제 변경이 필요한 schema/DB/role/모델 실행·배포 범위를 preflight로 고정한다.

### A. 공통 계약·영속 인덱스 첫 수직 경로 — 약3~5시간 가정

- 최소 schema/frozen model과 current source/space/view closure tests를 먼저 추가한다.
- 기존 local encoder/Artifact owner를 재사용해 vector shard·binding/index manifest를 구성한다.
- 1~2개 synthetic/disposable 입력으로 commit/replay·old retrieval compatibility를 확인한다.
- 기존 Graph 출처 및 권한 의미가 바뀌지 않는 것을 검증한다.

Exit: 바이트와 pointer가 검증되는 vector 결과를 기존 owner가 등록·조회할 수 있다.

### B. 자료 학습의 자동 증분 연결 — 약5~8시간 가정

- committed Graph/source 변화 → 공식 missing-binding query → 기존 Job admission을 연결한다.
- 재시작·중복 발견·늦은 commit·권한 철회·개정·model/view 전환을 회귀한다.
- 최초 seed는 별도 승인된 실행으로 수행하고 이후 source1개 추가/개정으로 전체 재계산이
  일어나지 않음을 실제 encode count와 Artifact/key로 확인한다.
- 첫 운영 source 범위는 현재 Item adapter의 기출/승인 문항이다. 교과서는 별도 document
  projection 계약이 검증되기 전까지 `NOT_SUPPORTED_BY_THIS_INDEX`로 표시한다.
- accepted V10 보고서가 없는 신규 승인 Item은 보고서 대기/부분 coverage로 남긴다.
  기존 supported 분석 경로에서 보고서가 승인된 뒤 같은 source 관계를 reconcile한다.
  보고서 대기를 학습 실패나 임베딩 성공으로 재해석하지 않는다.

Exit: 원 학습 성공을 보존하면서 새 source만 자동 준비되고, 같은 입력은 재사용된다.

### C. 기존 기능의 공통 소비 연결 — 약4~6시간 가정

1. 기출변형에서 exact 원문과 관련 후보의 유지 착상·차이·추가 추론을 전달한다.
2. 신규 출제·검토에서 같은 공통 context를 사용하며 최대3교·기존 RAG receipt를 유지한다.
3. ChatGPT에는 read-only 목적의 후보·출처·한계 설명을 연결한다.
4. 25문항은 출판/승인 의미를 바꾸지 않고 반복 착상 참고 관측을 연결한다.

모든 소비자를 동시에 새 prompt/정책으로 재출시하지 않는다. 시간 내 실제 연결·회귀가
끝난 것만 LIVE_VERIFIED로 기록한다. 나머지는 계약/adapter 준비와 운영 미활성을 구분한다.
별도 교과서 chunk 인덱스·PDF 검토의 문항 matching·고급 시험지 자동 편성은 후속 범위다.

Exit: 최소 기출변형의 실제 공통 경로가 닫히고 다른 소비자의 적용/미적용 상태가 정확하다.

### D. 회귀·배포·실제 증분 확인 — 약3~5시간 가정

- 위 CPU/GPU 비교를 실행하고 실측 우수한 device를 기본으로 선택한다. GPU 우수 시
  격리 실행·lease·space 전환·rollback·운영 기본값 활성화까지 검증한다.
- formatter/linter/strict type checker·focused tests·dependency/hash compatibility를 통과한다.
- DB mutation tests는 disposable DB에서만 실행한다. 운영 DB로 pytest하지 않는다.
- compatible release set과 rollback을 고정하고 필요한 component만 배포한다.
- 실제 허용 source의 증분 작업/재전송/후보 조회를 검증한다. 새25문항/HWPX 전체 생성은
  이번 인덱스 검증에 필요하지 않으며 별도 product canary일 때만 수행한다.
- source/installed/active policy와 각 소비자의 활성화 상태를 구분해 README·Slack에 보고한다.

Exit: 준비됨·대기·실패·차단 coverage가 정확하고, 기존 기능은 회귀 없이 유지된다.

## 10. 필수 테스트와 전체 완료 기준

- missing/stale target·schema/media/hash mismatch·immutable revision·duplicate refs.
- 같은 사건/입력의 반복 및 concurrent claim에서 추가 인코딩·binding 중복 없음.
- crash 전후·알림 유실·late commit·동일 timestamp·cursor 진행 중 미완료 source 복구.
- source/report 개정과 Graph-only 변경 시 필요한 부분만 계산한다.
- 모델/차원/recipe가 다른 vector는 혼합하지 않는다. float finite/norm/차원·행 순서 검증.
- 긴 입력·수치·단위·부정 보존, 무절단, source chunk→anchor 재현.
- revoke·소유권 변경·권한 부족·answer-bearing/출판 정책 부정 사례.
- vector 준비 실패가 학습 성공·기존 GraphRAG 기능을 바꾸지 않는다.
- partial index coverage를 전체 완료로 표시하지 않는다. 미래 corpus 수를520으로 고정하지 않는다.
- raw binary가 DB에 없고 worker DB/NAS 접근과 core ML import가 없다.
- pinned historical replay·same-key publication·Artifact commit 후 metadata 실패 복구.
- consumer별 요청/결과 포맷·bounded context·prompt version·RAG receipt 정합성.
- 최초 seed와 delta encode/reuse count, CPU/메모리/지연을 따로 측정한다.
- CPU/GPU 동일 입력 비교, device별 numerical space 분리, query 순위·float 오차,
  GPU lease 경합·미가용의 명시적 정책, 기본 device 활성화와 rollback을 검증한다.

전체 보고는 `SOURCE_PASS / DISPOSABLE_DB_PASS / INSTALLED / ACTIVE / LIVE_VERIFIED /
NOT_IMPLEMENTED / NOT_EVALUATED`를 구분한다. 기존 corpus의 학습 완료, vector coverage,
착상 비교 근거 coverage와 교육 품질은 서로 다른 분모·상태다.

## 11. 코드 근거와 관련 문서

- [증분 임베딩의 non-Codex 실행 경계](INCREMENTAL_EMBEDDING_EXECUTION_BOUNDARY.md):
  기존 queue를 재사용하는 전용 실행 목적·DB/owner 변경과 CPU/GPU admission 설계.
- [검증된 첫 소스·임시 DB checkpoint](../status/SYSTEM_RAG_INCREMENTAL_EMBEDDING_CHECKPOINT_2026-10-12.md):
  구현·실행한 gate와 아직 없는 운영 연결을 구분한다.
- [영속 registry 설계](INCREMENTAL_EMBEDDING_REGISTRY_DESIGN.md): pointer-only 관계와
  exact-key reservation·등록/CAS·현재 미구현 service authority·paging 경계.
- [CPU/GPU runtime·기본값 전환 설계](INCREMENTAL_EMBEDDING_GPU_RUNTIME_DESIGN.md):
  동일 payload, 별도 보호 runtime과 physical lease, 사전 benchmark·활성화·rollback 기준.
- `services/catalog_service/eom_catalog_service/knowledge_analysis_service.py`: 승인 분석·이벤트 transaction.
- `services/catalog_service/eom_catalog_service/registry_service.py`: Item 승인·소유된 상태 변경.
- `services/catalog_service/eom_catalog_service/knowledge_graph_publication_service.py`: source membership·Graph 출판 transaction.
- `services/workflow_runner/eom_workflow_runner/repository.py`: 공개 enqueue·indexed claim/lease.
- `services/catalog_service/eom_catalog_service/inference_transfer_catalog_adapter.py`: 공식 source/actor 해석.
- `services/catalog_service/eom_catalog_service/inference_transfer_projection.py`: 승인 report projection.
- `services/catalog_service/eom_catalog_service/inference_transfer_item_projection.py`: question-only 표현/metadata.
- `services/catalog_service/eom_catalog_service/local_embedding_adapter.py`: optional offline encoder.
- `services/orchestrator/eom_orchestrator/inference_transfer_experiment_artifacts.py`: 기존 결과 Artifact owner.
- [최초 착상 전이 설계 원문](ITEM_INFERENCE_TRANSFER_DESIGN_ORIGINAL.md).
- [실험 계약과 현재 범위](ITEM_INFERENCE_TRANSFER_EXPERIMENT.md).
- [권한이 적용된 snapshot](ITEM_INFERENCE_TRANSFER_AUTHORIZED_SNAPSHOT.md).
- [교과서 GraphRAG 연결 경계](GENERAL_CHAT_TEXTBOOK_RAG_DESIGN.md).

## 부록 — ChatGPT 기능에서 대화 삭제 추가하기

사용자가 요청한 별도 후속 기능이며 문서의 마지막 항목으로 관리한다. 위 핵심 증분
인덱스의 완료를 대화 삭제 기능과 혼동하지 않는다.

현재 general-chat에는 list/create/read/turn submit/grounding이 있고 delete/archive owner
operation은 확인되지 않았다. 실제 operator 소유권은 기존 `owned()` 경계가 확인한다.
conversation/turn FK는 RESTRICT이며 owner DB role에는 DELETE 권한이 없다.

첫 구현은 **본인 대화의 논리 삭제**로 한다. 일반 목록·열기·재전송에서 숨기되 정본
실행·transcript·근거 Artifact·감사 이력은 보존한다. 영구 폐기와 혼동하지 않도록 안내한다.

- 기존 Chat owner에 typed 삭제 command/result·permission·expected-version·idempotency를 정의한다.
- 소유자가 아닌 대화와 없는 대화는 같은 안전한404로 응답하고 존재 여부를 노출하지 않는다.
- 첫 범위에서는 답변이 QUEUED/CLAIMED/RUNNING/COMMITTING이면 삭제를 명시적으로 거절하고
  답변 종료 후 가능하다고 안내한다. 진행 작업을 임의 CANCELLED로 바꾸지 않는다.
- terminal 확인과 논리 삭제 metadata 전환은 turn submit/claim과 같은 conversation 잠금과
  transaction 경계에서 수행한다. 사전 확인 뒤 새 turn이 끼어드는 경쟁을 허용하지 않는다.
  DB DELETE 권한을 추가하거나 Artifact/외부 thread를 직접 지우지 않는다.
- GUI에 삭제 버튼·확인·실패 복구 안내를 추가한다. 성공 후 선택·초안·polling·epoch를
  비워 늦은 응답이 대화를 화면에 다시 표시하지 못하게 한다.
- 삭제된 대화의 접근/turn 재전송·중복 삭제·delete-vs-submit/claim 경쟁·삭제 후 admission/replay
  차단·다른 사용자·late response를 회귀한다.
- 개인 대화·message·grounding Artifact는 자료 학습·공용 임베딩에 자동 편입하지 않는다.

완료 기준: 본인 terminal 대화를 삭제하면 목록/열기/재전송에서 제외되고, 다른 사용자
대화와 불변 실행·자료 corpus·벡터 인덱스에는 영향이 없다.
