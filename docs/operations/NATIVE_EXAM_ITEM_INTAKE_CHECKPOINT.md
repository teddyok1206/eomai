# 한글 시험지 문항 등록 구현과 검증 현황

2026-11-13 UTC. 목표는 18회 450문항의 문제·해설 native HWPX, 원본 Excel metadata,
기존 자료 학습·Registry·공개 풀이·공통 Graph·증분 임베딩 연결 및 운영 반영이다.
설계 정본은 `docs/architecture/NATIVE_EXAM_ITEM_INTAKE.md`다. 이 기록의 소스 후보와
실제 운영 활성화를 구별한다. 최신 상태는 아래 **호환 배포와 실제 UID 검증 완료**를 본다.
앞선 단계의 실패·대기 기록은 당시의 증거이며 덮어쓰지 않는다.

## 보존할 운영 경계

기준 HEAD는 `656c4d6a`이며 시작 worktree는 clean이었다. 실제 설치된 API/platform/Web은
이전 위험 수정 release `c8a851fe`다. 기존 INDEX/QUERY/창작/자료 학습 실행은 이 목표 때문에
재시작하지 않았다. 이번에 준비한 테스트 DB는 운영 DB가 아니다. 소스 변경을 설치 완료로
보고하거나, 구조 검사를 한글 프로그램의 육안 확인으로 확대하지 않는다.

사용자는 없는 고유번호 200개를 나중에 갱신한 Excel로 제공한다. 현재는 null이며 번호를
자동 발급하지 않는다. 원본 문제·해설 identity는 Excel hash나 외부 고유번호와 독립적이다.
후속 Excel은 같은 문항의 metadata revision으로 연결해야 한다. 기존 풀이·Graph·임베딩을
번호 추가 때문에 다시 만들지 않는다.

## 구현한 소스 후보

- `native_exam_archive.py` / `native_exam_workbook.py`: 안전한 ZIP inventory와 실제 XLSX
  읽기, 원문 셀·수식·좌표·중복 헤더 보존, optional 고유번호와 원본 단원 연결.
- Builder `native_item_split.py`: 직속 문단 번호, section 연속 범위, native 표·수식·그림,
  필요한 resource/binary/masterpage만 남기는 편집 가능한 fragment.
- `NativeDocumentReadProfile.NATIVE_SPLIT_V1`: 새 분리만 masterpage를 지원한다. 기존 merge와
  기본 parser의 STRICT 의미는 바꾸지 않는다.
- `NativeHwpReaderV2.java` / `NativeHwpConverterV2.java` / `native_conversion_v2.py`: 기존 HWP
  reader의 후행 record 무한 반복과 정확한 MEMO field 처리를 분리한 explicit successor.
  본문 native 보존과 auxiliary decoration 예외를 구분한다. V1 entrypoint/schema는 보존한다.
- `material_native_files.py` / `material_native_intake.py`: native 파일·분리 증거·원본 Excel
  포인터와 등록 metadata, intake/preparation/prepared의 명시적 successor.
- `material_intake_read.py`: 실제 committed Artifact member schema로 V1/V2를 선택한다.
  실패한 파싱을 V1이나 latest로 우회하지 않는다. 기존 source 권한 owner도 이 읽기를 쓴다.
- `material_native_resolution.py`: intake의 실제 XLSX 재독해와 native 파일·증거 검증.
- `material_native_publication.py`: 기존 Artifact owner로 각 문제/해설을 PRIMARY Artifact로
  저장한다. proof는 역할별 한 번, Excel 원본/해석은 공유한다. 재전송·번호 추가는 native
  파일을 재사용한다. 이 publisher 자체가 원문 보존 도구를 대체하지 않는다.
- `material_native_item_registration.py`와 기존 registration의 연결: 실제 material intake에서
  binding을 해석한다. 기존 V1 component 3개를 유지하고 native는 6개를 명시적으로 검증한다.
  native Pack `uploaded-material-item/1.1.0`과 metadata `@2.0`을 별도 pin한다.

자료 학습의 기존 QUESTION → REGISTERED → ANALYZING → PUBLISHING → GRAPH_READY 경로,
공개 풀이와 공통 embedding text를 재사용한다. 새 Codex executor·Graph·벡터 저장소·queue를
만들지 않는다. 원래 해설과 모델 풀이보고서는 구분한다. 현재 소스 후보에는 runtime용
native file tool/Orchestrator sandbox port와 실제 업로드 연결이 아직 구현 중이다.

## 실제 파일 검증

Archive SHA는 `b030605b9014efd248e0007c96f5d2cc07797bc4dcb96b3c2a988a5832b3da61`이다.
18개 XLSX, 450행, 고유번호 250개와 null 200개를 실제 재독해했다. 모든 source의 본문 번호
1–25 경계가 있으며 표 내부 번호는 다른 문항 시작으로 취급하지 않는다.

12회·14회 문제/해설 50쌍, 01회 해설 25개는 실제 native 분리·패키지/원문 subtree 검증을
통과했다. 추가로 원래 실패하던 01회 문제·06회 문제/해설의 V2 보존과 각 25개 분리를
독립 검증했다. Hancom open/render 육안 확인은 아직 기록하지 않았다.

전체 qualification 1차는 **36 source 중 29 PASS**, 문제 fragment **350**, 해설 fragment
**375**다. 완료가 아니며 아래 7건을 수정·재검증해야 한다. 산출물은 등록 전 local candidate다.

- 02회 문제/해설, 04회 문제/해설, 08회 해설: equation script CRLF가 writer에서 LFLF로
  바뀌어 보존 검사가 올바르게 거절했다. 02회 문제는 binary 1개도 추가 조사 중이다.
- 03회 문제: converter 자체 실패를 실제 stderr로 조사 중이다.
- 17회 문제: 원본에 한글 기본 empty event script 두 파일이 있다. 어떤 script도 실행하지
  않는다. 정확히 검증한 기본 template만 새 분리 profile에서 제외하도록 구현했고,
  해당 원본만 독립 재검증하여 **문제 25개 분리 PASS**를 확인했다(6.20초).
  `/tmp/eom-native-empty-script-ac_8jn_9/items`의 결과와 각 분리 영수증에는
  `excluded_source_parts` 2개가 기록된다. 원본 package와 본문 subtree는 보존하며,
  파생 출력의 Scripts 파일·manifest/spine 참조는 없다. 이 결과는 첫 전체 qualification의
  실패 기록을 수정하거나 전체 450쌍 완료를 의미하지 않는다.

17회에서 제외한 정확한 template identity:

- `Scripts/headerScripts`: 150바이트,
  `sha256:d24eb743b49a913f449c0a4e9ee6e6a9465c890298c769145dba831e7b13b4b0`.
- `Scripts/sourceScripts`: 80바이트,
  `sha256:6f558fdcd17d07a7d2f29478a6eb3d628c7e3c9c64f049dce4959426c17360d0`.
- 이유: `EXACT_EMPTY_HANCOM_SCRIPT_TEMPLATE_V1`. 내용 추가·주석 위장·Unicode·BOM·인코딩
  변경은 거절하며 기존 STRICT merge의 거부 동작은 유지한다.

V2 변환은 원문 전체 페이지의 동일 배치를 보장하지 않는다. 잘못된 미적용 머리말 장식은
`AUXILIARY_MASTERPAGE_FIELD_INVALID`, 적용 의미를 추정하지 않은 보조 바탕쪽은
`AUXILIARY_MASTERPAGE_APPLICATION_UNRESOLVED`로 남긴다. 본문 내용에는 이 예외를 적용하지
않는다. 원본 HWP와 auxiliary record 범위/hash·내용 증거를 보존한다.

## 재개용 위치

다음은 임시 검증 위치이며 canonical Artifact pointer가 아니다. NAS publication 전에는
운영 DB/Graph가 이 경로를 참조해서는 안 된다.

- 전체 staged 원본/격리 code snapshot/1차 결과:
  `/tmp/eom-native-exam-complete.XyhF6YfA`
- 실제 1차 기록: `staging/native-exam-complete-20261113.log` 및 workspace의
  `output/summary.json`. 격리 unit `eom-native-exam-complete-20261113`은 정상 종료했다.
- 대표 결과: `/tmp/eom-native-exam.C7o52xH9/split-pilot` 및
  `/tmp/eom-native-hwp-v2-split.04hyv369`.
- 이전 실패와 실제 V2 비교: `/tmp/eom-native-converter-diag.9Gwzo2HK`.
- 실제 source archive inventory/XLSX 읽기는 저장소 source와 explicit `eom-api` Python을 쓴다.
  native source tests는 `eom-hwpx` Python과 repository source path를 명시한다.

기존 Java 설치의 hash가 예전 converter bundle과 달라 첫 실행 전 검사가 거절했다.
공식 build/install로 현재 Java와 같은 기존 JAR의 bundle을 별도 설치했으며 기존 pin을
고쳐 쓰지 않았다. 이후 bounded V2 JAR도 별도 qualifier로 설치했다.

- Java 21.0.13 binary SHA: `7852a08212228be0d65e75926c4991a4eecf4ae94ec46704b4180e2d2b654a6a`.
- V2 최초 qualifier bundle: `bd1a28ae895b093a8aa44a15faf29b36e1c7552bf108371e85e24707c6604b3b`.
  후속 Java 보존 수정을 포함한 최종 bundle과 혼동하지 않는다.
- root/operator pane: tmux `EOM → 2번 native-exam`, pane `%116`. 다른 사용 중 창은 그대로다.

## 테스트와 남은 작업

### 전체 원본 재검증 (최종 V2 candidate)

새 실행 `eom-native-exam-final-20261113`은 **36/36 source PASS**, 문제 450개와 해설
450개, 총 **900개 편집 가능한 HWPX fragment**를 만들었다. 165.64초가 걸렸으며 원본
처음 실행의 7개 FAILED는 그대로 보존했다. 후속 독립 집계에서 900개 파일 각각의 실제
SHA/크기/문항번호/역할과 450개 Excel 행의 대응을 다시 확인했다. 고유번호 250개는 중복이
없고 미제공 200개는 null, 원본 단원은 정규화 기준 33개다. 이 결과는 한글 화면의 육안
검사나 운영 Item/Graph 등록 완료를 뜻하지 않는다.

- 최종 converter bundle: `8cb14806c28129598447028a56b81dc2440f1a904d8b7687350bf97777ff85e7`.
- 최종 local candidate: `/tmp/eom-native-exam-final.TeQmtWRv`.
- 기록: `staging/native-exam-final-20261113.log`, candidate의 `output/summary.json`.
- 03회 binary ID는 목록 위치가 아니라 실제 DocInfo storage ID+확장자로 읽는다. 02회 raw
  JPEG는 해당 binding의 압축 플래그로 해석한다. 5개 원본의 equation script CRLF는 writer가
  XML numeric entity로 보존하며 보존 검사기를 느슨하게 바꾸지 않았다.
- unbound binary 11개는 본문 그림으로 임의 결합하지 않고 원본에 보존된 member hash/크기로
  명시한다. 실제 본문에 연결된 binary는 원본 OLE의 독립 decoder hash와 대조했다.

임시 DB의 기존 material suite와 native 등록 3개를 포함한 재실행은 **47 PASS**였다.
후속 source stream/application 검사는 28 PASS다. 첫 후속 invocation은 설치된 옛 package를
잘못 수집해 collection ERROR가 났고, 명시적 repository source path로 수정해 재실행했다.
이는 운영 오류나 운영 등록의 증거가 아니다.

API/GUI와 native 문항의 읽기 경로는 소스 후보로 연결했다. 자료 학습의 기존 실제 operator
권한·run/task·Registry·풀이·Graph·공통 증분 embedding을 사용하며 새로운 executor나
등록 queue는 만들지 않는다. native Q/S 직접 다운로드와 기존 structured Item의 재출판
계약은 별개다. 기존 `CuratedNativeDocumentInput` V1을 다른 schema로 위장하지 않는다.

### 통합 후보·실제 설치본 gate

원문 분리 기반은 `8b76e95093dd0b6802344f670a73f41636b8fdfd`로 커밋했다. 이 commit의
Builder/contracts는 공식 clean worktree build로 wheel을 만들고 별도 root 소유 CPU
venv `/opt/eom/native-exam-tools/8b76e95093dd0b6802344f670a73f41636b8fdfd/runtime`에
설치했다. 기존 GPU 환경은 수정하지 않았으며 새 runtime은 base Python 표준 라이브러리만
참조한다. dependency wheel SHA와 설치 RECORD 1,787개를 검증했다. 이 설치가 application
운영 배포나 새 material run 접수를 뜻하지 않는다.

실제 저권한 sandbox에서 02/03회 HWP와 14/17회 HWPX 문제 100개를 새 설치본으로
처리했고, 앞서 qualification한 100개 fragment와 SHA가 모두 같았다. 첫 root 도구 검사만으로
Catalog API 계정의 권한을 승인하지 않는다. Catalog API는 비권한 계정이므로 고정 systemd
template·polkit start allowlist·별도 `eom-image` UID/정확한 작업 폴더 bind를 추가했다.
이 adapter의 실제 Catalog UID 검사와 secrets/NAS/다른 프로세스 접근 거부는 운영 반영 전
필수 gate이며 아직 실행 전이다. 서비스 자체에 root나 임의 transient unit 권한을 주지 않는다.

- 최종 통합 source gate: **651 PASS / browser opt-in 1 SKIP**.
  실제 Chromium 자료 학습/DB 검사는 별도로 PASS다. 기록:
  `staging/native-exam-final-source-gate-20261113.log`.
- 변경 core Python 48개 mypy PASS, 변경 Python 76개 Ruff/format PASS.
- 최신 실제 disposable DB gate: **52 PASS**. native metadata·원본 문제/해설 다운로드,
  immutable 승인 Artifact 차단·사용자 권한 철회, native intake2의 실제 EducationalDocument
  준비/재조회, 기존 풀이보고서·공통 embedding text projection까지 포함한다. 모델 결과와
  PDF extractor는 명시적 합성이며 실제 운영 모델/GPU 수치 완료로 확대하지 않는다.
  기록: `staging/native-exam-material-db-r5-20261113.log`.
- 이전 DB 실패 fixture는 UTC `Z` 정규화 전 hash 계산과 승인 Artifact를 직접 바꾸려던
  부정 테스트였다. fixture를 바로잡았으며 권리 hash·DB immutability guard는 완화하지 않았다.
- 독립 검토에서 native intake2를 intake1로만 읽던 기존 EducationalDocument owner를 찾아
  committed-schema reader로 연결했다. 발견 단계는 native bundle의 정확한 번호·원문 쌍으로
  누락·중복을 검증하고, 확인한 번호로만 QUESTION/SOLUTION을 연결한다. 정상화된 번호가
  같아도 다른 자료를 제목이나 전역 번호 유사도로 연결하지 않는다. 품질 문제는 해당 run만
  실패로 남기며 pointer/hash/permission 불일치는 STOP을 유지한다.
- 고유번호 추가 Excel의 metadata successor **UI/명령은 아직 미구현**이다. 지금은 원문
  identity 기반의 기존 indexed registration key/UNIQUE/lock을 사용해 중복 Item·새 풀이를
  막고 `MATERIAL_NATIVE_METADATA_UPDATE_REQUIRED`를 기록한다. 같은 작업의 정확한 재조회는
  기존 lineage를 검증한다. 후속 Excel을 신규 문항처럼 재접수하면 안 된다.

현재 운영 Item 등록·모델 풀이·Graph·신규 GPU embedding 실행은 아직 시작 전이다.
다음은 통합 commit/wheel, 기존 실행과 조율한 호환 배포, 실제 operator의 첫 등록·조회와
기존 풀이/Graph/INDEX 연결 확인이다. native 원본 Q/S 다운로드는 지원 후보지만 native
pair를 기존 개인 조립 출력에 합치는 successor는 이번 원문 등록과 구분된 후속 범위다.

### 첫 실제 Catalog UID 사전검증

통합 후보 `ea4fda8bafaea8547379e7e0fd1cc0000be20037`은 커밋·push와 API/Web wheel
검증을 통과했고, 별도 immutable owner prefix만 준비했다. 기존 운영 API/Web은 아직
`c8a851fe` 그대로이며 source 0079·인증·정본·모델·벡터는 변경하지 않았다.

고정 파일 도구 unit을 준비한 뒤 첫 실제 Catalog UID 검사에서 검증 fixture와 실제 systemd
directory 생성 규칙의 차이를 발견했다. `RuntimeDirectory=eom-native-exam/%i`의 중간 부모는
실제로 `root:root 0755`인데, worker가 `eom-image:eom-api 0700`으로 잘못 검사했다.
이 실패는 후보 사전검증이며 사용자 문항 등록 실패가 아니다. unit
`nativeexam_ea8b7d218cbe4dc8b39958c8e75e6ae8`과 그 local 입력·journal은 보존한다.

Catalog private staging 검증과 systemd runtime 검증을 별도 함수로 나누어 정확한 owner/
group/mode를 유지했다. 허용 범위를 넓히거나 root 권한을 주지 않았다. 새로운 실제-layout
회귀와 application 집중 **55 PASS**, 두 source mypy/Ruff PASS다. worker 로그는 검증된
`NATIVE_*` 코드만 출력하며 원문·예외 메시지·경로·credential은 기록하지 않는다.
이 수정은 새 commit/owner prefix에서 실제 UID 검사를 다시 통과해야 한다. 이전 candidate
prefix를 덮어쓰거나 실패를 성공으로 바꾸지 않는다.

검사기 자체도 systemd의 짧은 `(sd-exec)` 자격 전환 단계와 실제 실행된 Python을 구분하도록
수정했다. 실제 실행 후 잘못된 UID/GID는 계속 거부한다. namespace probe는 보호 경로를
열 수 있는지만 확인하고 어떤 보호 데이터도 읽지 않는다.

Native 초기 core/기존 merge·converter 회귀 90 PASS, material unit+reader 370 PASS를 확인했다.
테스트가 진행 중인 worktree에서 실행됐으므로 최종 변경 전체의 gate는 다시 실행해야 한다.

임시 DB `/tmp/eom-api-testdb-20261113180101_c346fad9`를 공식 도구로 준비·migration 왕복·
제한 계정 reconcile했다. 기존 material DB suite는 43 PASS와 schema metadata 수집 fixture
1 FAIL이었다. 새 ChatModelSettings owner의 model import 누락을 fixture에서 바로잡았고,
native 등록 3개를 포함한 재실행은 `staging/native-exam-material-db-r2-20261113.log`를 본다.
운영 DB를 pytest 대상으로 사용하지 않는다. 테스트가 모두 끝나면 공식 cleanup을 수행한다.

다음 실행 순서:

1. 1차 7개 실패 기록은 보존하고, 17회 독립 PASS 외 남은 원본의 담당 native adapter를
   수정·재검증한 뒤 전체 qualification을 새 실행으로 확인한다.
2. 전체 450쌍의 원문·meta·문제/해설 대응을 집계한다. 기존 실패 후보를 성공으로 고치지 않는다.
3. 보호된 native file tool/기존 sandbox port와 공식 source upload → publication → native intake
   연결을 끝내고 임시 DB의 중단·동시성·재전송 및 실제 wheel을 검증한다.
4. 실제 operator 인증으로 대표 등록·원본 다운로드·DB 열람·Graph·공통 embedding 입력을
   확인한 뒤 기존 자료 학습 lane에서 전체를 진행한다. root를 operator로 가장하지 않는다.
5. 검증된 입력·metadata 연결을 자료 학습 GUI에 반영하고 compatible release로 운영에 배포한다.
   기존 canonical·실패 이력·현재 실행은 보존한다. 이 완료 전 goal을 달성 처리하지 않는다.

Slack은 50쌍 native pilot milestone을 한 번 보고했다. 보고 ID는
`devreport_476a2d7a1ae04a8fbb93d431f34857e2`이며 HTTP200/SAVED였다. 반복 진행률 보고는
만들지 않는다. 중요한 발견·사용자 인증 필요·완료만 기존 정책에 따라 보고한다.

## 호환 배포와 실제 UID 검증 완료

2026-11-13 20:06 UTC 확인. 실제 API/platform/Web과 자료 학습 owner는
`7084bbc4fc3dd9d9b8eb5c075f3de801800bd033`으로 배포·활성화했다. 기존 교체 대상의
진행 중 worker/command/HWPX/chat/GPU 작업 0과 자료 준비 checkpoint의 quiescence를
확인한 뒤 기존 학습 owner를 SIGINT로 정상 drain했다. INDEX 파일·source·InvocationID,
인증·모델/슬롯 정책·기존 정본·실패 이력은 보존했다. DB는 `20261112_0079` 읽기 확인만
수행했고 migration/DDL은 없다.

- 실제 Catalog UID 988이 고정 parser unit을 호출하고 worker UID 984/GID 985가 실행했다.
  HWP 2개와 HWPX 2개, 총 100 fragment가 기존 qualification SHA와 모두 일치했다.
  namespace 안에서 NAS·API 환경 파일·Catalog 원본 staging·실제 Catalog 프로세스 환경에
  대한 16개 open 시도는 모두 거부됐다. 보호 데이터는 읽지 않았다.
  `staging/native-exam-actual-catalog-uid-preflight-r3-20261113.log`와 보호된
  `/var/lib/eom-native-exam-release-r2-20261113/native-preflight.json`이 증거다.
- 원문 parser는 기존 별도 CPU capsule/최종 converter bundle을 유지한다. 공유 GPU runtime
  package를 수정하지 않았다. root 소유 중간 runtime directory와 실제 worker leaf의 권한을
  구분한 수정도 이번 설치본에 포함됐다. 앞선 실패 unit·사전검증 이력은 보존한다.
- 공식 `ContentPackService.import_source/release`로 `uploaded-material-item/1.1.0`을
  출시하고, 실제 발급된 ID만 자료 학습의 optional native pin에 연결했다. 기존 1.0 Pack과
  모든 다른 release/전역 activation은 변경하지 않았다. Catalog는 고정 native 설정을 읽는다.
  `staging/native-exam-native-controls-stage-20261113.log`와 `...-verify-20261113.log`는 PASS다.
- API 준비 상태 READY, 관련 서비스 14개 active, 실제 HTTPS assets가 설치 wheel과 일치하고
  anonymous 신규 route는 거부됐다. `staging/native-exam-release-r2-postdeploy-20261113.json`.
  이는 실제 업로드·모델 풀이·Graph·벡터 저장 완료의 대체 증거가 아니다.
- 임시 DB는 공식 cleanup으로 제거했다. 52 PASS와 정리 기록은 각각
  `staging/native-exam-material-db-r5-20261113.log`,
  `staging/native-exam-testdb-cleanup-20261113.log`에 남아 있다.

배포 전부터 INDEX owner는 실행 PID가 없는 과거 failed 상태였고 이번 교체에서는 그대로
보존했다. 실제 자료 등록 후 기존 증분 INDEX의 pending/active 대상과 원인을 확인해야 하며,
현재 임베딩이 실행 중이라고 보고하지 않는다.

후속 읽기 진단에서 마지막 종료는 `TimeoutExpired`이며
`eom_orchestrator.inference_transfer_cpu_systemd:273`의 15초 `systemctl show` 관측이었다.
이것만으로 GPU 수치 계산 실패나 저장된 벡터 손상을 뜻하지 않는다. 기존 INDEX source
`47fc5366`과 이번 `7084bbc4`의 material lineage·approved Item source·공개 V11 풀이 선택
owner 네 파일에는 차이가 없다. 원본 한글/Excel을 가리키는 추가 component와 metadata2는
임베딩 입력을 별도 형식으로 바꾸지 않는다. 이 소스 호환 점검은 실제 신규 문항의 벡터
저장 완료를 증명하지 않는다. 원래 pending Workflow/parent와 retained unit을 공식 읽기/
관측으로 확인한 뒤 동일 pin의 기존 INDEX service를 재개한다. 실패 이력·완성 벡터를
수정하거나 새 key로 원래 실행을 우회하지 않는다.

다음 작업은 실제 operator 한 번의 로그인으로 원본 업로드·첫 회차 접수·native Q/S 다운로드와
DB 원본 metadata·공개 풀이·공통 Graph를 검증한 뒤 같은 세션에서 나머지 17회를 이어 넣는
것이다. 준비된 원문은 450쌍이지만 운영 Item 등록은 아직 시작 전이다. 완료하지 않은 모델
처리·임베딩을 완료로 표시하지 않는다. Hancom 자체 육안 검토는 NOT_RECORDED다.

배포 milestone Slack: `devreport_f475d2978462408fb73324545366424f` HTTP200/SAVED.
