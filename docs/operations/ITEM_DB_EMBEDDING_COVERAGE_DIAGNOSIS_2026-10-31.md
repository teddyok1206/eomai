# DB 검색 준비 안내의 실제 범위 점검

조회 시각: 2026-10-31 07:46:03 UTC. 운영 메타데이터 read-only snapshot이다.
모델 추론·INDEX 재시작·추가 query 제출·DB row 수정·권한 변경은 하지 않았다.
API role은 encoding 테이블을 읽을 수 없어 해당 거부를 보존했고, INDEX owner가
이미 쓰는 Catalog credential/service identity로 SELECT만 수행했다. 임의 사용자
권한이나 WORKER/ADMIN actor를 만들지 않았다.

## 서로 다른 분모

- 가져온 창작 원본의 current revision이 있는 source 행: 1,297.
- Registry ACTIVE Item: 804. RETIRED 237은 이 분모와 별도다.
- 현재 Graph source pointer의 distinct Item revision:
  PAST_EXAM 520, APPROVED_ITEM 280. APPROVED_ITEM은 기출이 아닌 등록 Item
  범주이며 이 수치만으로 전부 창작 또는 전부 AI라고 분류하지 않는다.
- 현재 창작 cohort의 파생 상태(07:30 UTC): 111/1,053 PROCESSING.
  이 heartbeat를 전체 Graph 정본 집계나 완료 영수증으로 대체하지 않는다.

후속 서비스 점검에서 실제 owner가 **07:39:40 UTC에 exit 78로 중단**된 것을
확인했다. 마지막 상태는 114/1,053, 고유번호 11338의
`CREATIVE_COHORT_EXTRACTION_TERMINAL_FAILURE`다. 07:30의 PROCESSING heartbeat가
그 이후에도 작업 중이라는 증거는 아니다. 같은 시각의 GPU INDEX/QUERY는 active이고
기존 PID가 유지됐다. 이 점검으로 실패 history를 변경하거나 재시작하지 않았다.

## 임베딩 생성과 실제 DB 검색을 분리해야 함

기존 `accepted-solution-comparison/1.0`의 기출 520개는 두 embedding space에서
CONTENT_ONLY / CONCRETE_FACETS / METADATA_ONLY 각 view에 모두 source binding이
있다. 같은 문항의 여러 view/space/history를 문항 수로 합산하지 않는다.

DB 검색의 initial selection은 public namespace와 `public-solution-text/1.0`을
사용한다. 이 경로의 현재 등록 수는 다음과 같다.

| 계산 space 접두 hash | 공개 encoding 행 | 기출 distinct revision | 등록 Item distinct revision |
| --- | ---: | ---: | ---: |
| `39bc2c310299` | 28 | 16 | 12 |
| `8a2fcad6f075` | 4 | 3 | 1 |

두 space의 문항은 중복될 수 있으므로 28+4=32문항이라고 표현하지 않는다.
기존 비공개/기존 projection의 520 binding을 공개 검색의 520 coverage로
표현하거나 현재 검색 설정을 검증하지 않고 다른 namespace로 우회하지 않는다.

현재 index head 14개의 Graph pin은 모두 조회 당시 active Graph와 달랐다.
source binding 중 exact current Graph에 묶인 행도 0이었다. 새 Graph가 순차
출판되는 동안 기존 encoding bytes를 재사용할 수 있어도, current source/policy
재검증 및 새 binding/index publication 없이는 현재 검색 가능한 상태가 아니다.
이는 자료가 없다는 사실과 다른 연결/발행 지연이다. 이미 핀된 과거 query의
정상 여부까지 이 관찰만으로 실패라고 단정하지 않는다.

## 왜 같은 안내가 뜨는가

`CatalogItemDbSimilaritySelection`은 선택 Item의 등록과 공개 풀이/검색 근거를
해석한다. `NOT_REGISTERED`, `NOT_INDEXED`, 일반 `UNAVAILABLE` 세 상태를 현재
API가 모두 ‘풀이보고서와 검색 자료가 아직 준비되지 않았습니다’로 보여 준다.
그 문구만으로 풀이보고서가 없다고 결론내릴 수 없다.

후속은 기존 520 index 전체 재계산보다 먼저 (1) 공개 풀이 projection 등록 확대,
(2) 새 Graph별 기존 encoding 재사용+membership refresh 발행,
(3) 세 원인에 따른 정확한 화면 안내를 기존 application 경계에서 확인하는 것이다.
이 문서는 그 후속 운영 변경의 실행·승인 또는 완료 증거가 아니다.
