# 개발 중 슬롯·GPU 간단 보고

사용자가 2026-11-04 UTC에 10분마다 슬롯·GPU 점검과 Slack 한 줄 보고를 요청했다.
이 요청에 한해 주기 보고를 수행하며, 평상시 개발 보고의 milestone 정책은 유지한다.
제품 runtime이나 자동 복구 기능이 아닌 제거 가능한 개발 관측이다.

기존 `eom-creative-learning-observe.timer`와 `eom-unified-embedding-observe.timer`의
읽기 전용 관측을 매 10분으로 조정했다. 별도 개발 report timer는 20초 뒤 결과를
요약한다. GPU observer의 기존 READ ONLY/15초 제한 metadata 조회에 활성 slot Job
집계만 추가했다. 새 모델/Workflow/queue 요청과 worker·INDEX 재시작은 없다.

보고는 완료 수, 원본별 등록 보류 수, 실행 중 slot Job 수, 기출 GPU binding 진행률,
GPU 순간 사용률을 구분한다. 과거 실패를 현재 장애로 세거나 GPU 0%를 연산 중이라고
표시하지 않는다. 관측 누락·오래된 결과는 확인 불가로 보고한다. 사용자 내용·인증·
worker 결과는 Slack에 보내지 않으며 기존 개발 reporter의 비밀값·전송 adapter를 쓴다.

설치 기록: `/var/lib/eom/development-background-monitor/20261104T160748Z/manifest.json`.
최초 실제 보고는 HTTP 200/SENT, 이후 10분 예약 timer active를 확인했다. 보고 프로세스는
NAS·저장소·worker home에 접근할 수 없고 journal의 bounded JSON만 읽는다.

보류 22건의 첫 분류는 추출 작업의 기존 실패 이력 11, 문항 내용 구조화 불가 6,
Office PDF 변환 결과 없음 5였다. 원본 손상으로 확정하거나 완료에 더하지 않는다.
이 기록은 해당 시점의 분류이며 이후 상태는 timer 관측으로 확인한다.

후속 점검에서 INDEX owner가 `EMBEDDING_BENCHMARK_CHANNEL_EOF`로 13:44 UTC 종료한
사실을 확인했다. 실행 중 수치 unit이 없음을 확인한 뒤 동일한 기존 owner unit을 공식
start로 재개했다. 새 계획/재임베딩/벡터 삭제는 없고 실제 기존 PID가 아닌 새 살아 있는
owner를 확인했다. reporter는 순간 GPU 0%뿐 아니라 INDEX owner active/MainPID도 확인해
계산 대기와 관리 프로세스 중단을 구분한다. 재개가 새 벡터 완료의 증명은 아니다.

중지: `eom-development-background-report.timer`를 stop/disable하고 두 observer timer의
`10-development-cadence.conf` drop-in만 제거하면 원래 30분 cadence로 복구할 수 있다.
INDEX·창작 처리 서비스나 정본은 삭제/중지하지 않는다. 원래 helper는 위 설치 기록의
backup pointer로 복구 가능하다. GPU observer가 transient인 점은 유지했다.

## 누적 등록 수와 실행별 카운터 구분

초기 reporter는 producer의 `verified_count`를 누적으로 잘못 표시했다. 이 값은 재시작 때
초기화되는 실행별 확인 수이며, 새 실행에서 0/2/6으로 보인 것은 정본 삭제가 아니다.
11월 4일 18:10 UTC에 frozen 1,053개 원본의 정식 등록 키와 현재 published Graph를
읽기 전용으로 대조했다. Graph 687개·문항 등록 690개였고, 배포 전 Graph 681개 중
현재 Graph에서 빠진 키는 0개였다. 이것은 해당 시각의 실제 DB 검사이지 미래의 고정 수가 아니다.

주기 보고는 기존 GPU metadata observer의 같은 read-only DB adapter를 확장해, 현재
published Graph·accepted analysis·creative-source-lineage component가 연결된 고유 문항을
집계한다. 원본 파일이나 모델 결과를 읽거나 복제하지 않으며 DB/권한/worker 변경이 없다.
고유 Item ID 집계와 indexed Graph/source/component join을 사용한다. 매 10분의 bounded
metadata query이며 카운터를 DB에 저장하지 않는다. scope는 현재 Graph 전체 창작 문항으로,
특정 cohort의 1,053개 분모와 섞지 않고 `창작 Graph 누적 N건`으로 표시한다.
조회 실패는 `누적 확인 필요`이며 실행별 숫자나 0으로 대체하지 않는다. 기존 GPU 집계는
이 부가 조회가 실패해도 보존한다. JSON observer의 추가 field는 개발 보고용 파생 값이지
worker 계약·원본 acceptance·완료 판정의 권한이 아니다. 새 서비스/queue/cache는 만들지 않는다.
