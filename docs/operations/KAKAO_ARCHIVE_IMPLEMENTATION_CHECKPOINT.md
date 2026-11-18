# KakaoTalk 구현 체크포인트

## 사진 출처·행 정합 운영 설치 — 선택한 방만

`919164330fcb41f580f1169400e574491511a627`의 Platform wheel을 Catalog 전용
설치 경로에 넣고, 같은 커밋의 수집기 wheel과 함께 반영했다. Catalog 전용 closure의
나머지 세 wheel은 기존 `cf5c5806`의 정확한 API·계약 payload를 유지한다. 공유 API·Web·
QUERY 서비스는 재시작하지 않았고 기존 PID와 설치를 유지했다. DB head `20261117_0097`,
기존 INDEX 및 자료 학습의 실행/구성, Kakao PDF·원격 프로필·원본은 유지했다.

적용 직전 기존 보호된 검사에서 작업과 비종료 Kakao 수집이 없었고, 서비스가 실제 종료된
브라우저의 프로필 잠금 아래 수집기를 교체했다. 설치 member 및 Catalog socket, API Ready
200·Studio HTTPS 200, 비로그인 수집 조회의 API/Web 401을 확인했다. `ONE_ROOM`만
활성 상태이며 실제 카카오 창을 열거나 새 수집을 요청하지 않았다. 전체 방·주기 수집과
실제 사진 연결·학생 PDF는 검증되지 않았다.

설치·복구 증거: `/var/lib/eom-kakao-catalog-collector-release-91916433/`.
정확한 기존 Catalog 경로와 drop-in·기존 수집기 wheel로만 복구하며, 새 claim이 들어가면
진행 중인 실행을 중단하거나 새 이력을 덮어쓰지 않는다.

## 사진 출처·행 정합의 호환 릴리스 후보

후보 커밋 `919164330fcb41f580f1169400e574491511a627`로 공식 API build-only와
wheel RECORD 검증, 별도 설치 경로의 API/Catalog import를 통과했다. 설치 중인
`cf5c5806`의 payload와 비교하면 Platform은 `kakao_photo_alignment.py` 한 파일,
API는 빌드 식별 메타데이터만 다르며 API/Kakao 계약 payload·Web 소스·OpenAPI·migration은
동일하다. 같은 커밋의 수집기 wheel은 별도 설치 경로에서 검증했다.

| 후보 wheel | SHA-256 |
| --- | --- |
| Platform | `0a9b93611039b012f269ca2e6eb9ac5a039729596811e1525d1f4a85a84e661c` |
| Application API | `a5521caaf48854b6db8ac0f30975bcbe35c252746550e038e0e95fc0a74e30f8` |
| API contracts | `534eb18cc89feae4c2f4cbe7bc6d89318e2e35660614a8ce0a172f6bab95fbb2` |
| Kakao contracts | `da1d5584803fe0fa2bc49c5e72adc5c693bba62b5e1066ef33cd113ec5c710b9` |
| Kakao collector | `1ec6e6db7d230aba506d0d20b101fe8e6a1cfb1b29722e1c7085f2e91acd7f52` |

읽기 전용 운영 확인에서 기존 브라우저·원격 프로세스와 활성 worker/command,
HWPX·채팅·카카오 PDF 대상이 없었다. 이 조회는 배포 시점에 재확인한다.
다음은 기존 보호된 호환 배포 경계에서 공용 Platform 소비자와 실시간 owner pin을
함께 검증하고 선택 방 수집기만 연결하는 것이다. 현재 운영 설치/권한/정본 변경이나
새 provider 접근은 없었다.

## 직접 CDN 전송의 사진 출처 확인 — 소스·격리 Chromium 검증

고정 AUTO 클릭에서 선택한 사진 링크/표시 이미지 주소를 메모리에서만 확인한다.
다른 카드와 겹치지 않는 정확한 주소와 같은 페이지의 직접 CDN GET·다운로드 완료가
모두 맞을 때만 기존 사진 증거를 만든다. 주소 누락·쿼리 불일치·다른 카드와 공유는
계속 미확정으로 남고, 검증된 CSV를 별도로 받을 수 있다. 새 요청·재클릭·URL 저장·
MANUAL 출처 판정 변경·스키마 변경은 없다. 격리 Chromium 양성/거부와 집중 회귀
88건을 통과했다. 이 변경은 실제 카카오의 최종 주소가 카드에 나타난다는 증거가
아니며, 운영 설치나 기존 보관 사진의 소급 연결은 수행하지 않았다.

## 같은 방의 실제 사진·CSV 대조와 본문 앵커 수정

같은 MANUAL 회차·창·방에서 사진 1개와 CSV 1개를 확보하고 파일 무결성을 확인했다.
CSV는 48행·사진 표시 7행이고, 두 화면 관측의 사진 경로 6개와 순서는 같았다.
운영 정합은 말풍선 본문 35개가 자식 span에 들어온 형태를 읽지 못해 0/6이었고,
단일 span 본문 후보를 지원한 소스로 보존 실자료를 오프라인 대조하니 4/6이 서로 다른
CSV 행과 유일하게 대응했다. 관련 집중 검사 92건 통과. 원래 받은 파일의 말풍선 출처,
운영 수정본 설치, 정본 등록, 학생 PDF 발행과 전체 방 수집은 아직 미확정이다.
메시지 전송·설정 변경·세션 재실행은 하지 않았다.
[보존 실자료 대조 범위](KAKAO_PHOTO_OCCURRENCE_DIAGNOSTIC_2026-11-18.md)

## 최신 사진 묶음의 CSV 행 대조 — 소스·임시 DB 검증

원래 사진 말풍선이 이미 확인된 경우, 사진이 대화 끝에 붙어 있어도 앞선 완전한 두 문장과
연속된 사진 순서를 CSV에 대조할 수 있다. 사진과 CSV를 받을 때 같은 사진 식별자·문장이
일치하고 전체 CSV에서 해당 끝 구간이 유일할 때만 적용한다. 예전 사진이 화면에 없더라도
최근 구간이 일치하면 정합하고, 중간 누락·추가 행·사진 순서 변경·앨범·출처 미확정은 거부한다.
집중 검사 89건 통과. 별도 임시 PostgreSQL에서 기존 양쪽 앵커와 최신 사진 묶음의 두 케이스
모두 실제 파일→지정 행→원본 채택→같은 키 재조회를 검증했다.
이전 실방 사진의 출처를 새로 입증하지 않았고, 운영 세션·설치본·정본은 변경하지 않았다.

## 출처 미확정 사진과 CSV 수집 분리 — 소스·격리 검증

사진 버튼 이후 같은 페이지에서 허용 CDN GET과 단일 다운로드 완료가 확인됐지만 원래 사진
요청과의 연결이 없으면, 사진은 저장·연결하지 않고 남은 사진과 함께 미확정으로 센다.
다른 사진 버튼은 누르지 않고 기존 CSV 경로를 한 번 진행한다. 성공한 CSV와 검증된 사진만
기존 부분 수집 영수증에 들어간다. 중복 이벤트, 범위 이동, 실패 및 만료는 계속 중단한다.
검증된 이미지 연결, 정본 권한·revision·스키마, MANUAL 및 기존 수신물은 변경하지 않았다.
격리 Chromium의 직접 CDN 재현을 포함한 집중 검사 84건과 변경 모듈 타입 검사를 통과했다.
소스 체크포인트이며 기존 운영 브라우저를 유지했다. 새 운영 수집, 실제 사진 정합, 학생 PDF
발행이나 전체 방·예약 활성화는 이 변경에서 확인하지 않았다.

## 화면 사진 필드 대조 — 한 방에서 실제 재검증, 출처 미확정

운영 `8e819752`의 관리자 MANUAL 세션에서 이전과 같은 방의 사진 한 장을 받았다.
294,841 bytes로 수신 무결성이 통과했고 이전 수신과 SHA-256이 같았다. 최종 요청은 같은
창에서 관측됐지만 원래 사진 GET으로 연결되지 않았다. 새 화면 비교도 `UNAVAILABLE`로
끝났다. 이는 화면 주소가 일치하지 않았다는 `NONE` 판정이 아니다. 별도로 보존된 DOM
관측에는 방 범위가 맞는 원래 사진 링크 6개와 각 링크에 대응하는 미리보기 이미지 하나가
있었으나, 이 구조만으로 정확한 다운로드 주소나 사진의 CSV 행을 확정할 수 없다.
이번에는 CSV를 다시 내보내지 않았고 메시지 전송·설정 변경·정본 등록·PDF 발행도 없었다.
다음 검증은 원래 사진 버튼과 최종 전송을 연결하는 직접 근거를 확보하는 것이다.
[진단 해석과 확인 한계](KAKAO_PHOTO_OCCURRENCE_DIAGNOSTIC_2026-11-18.md)

## 다운로드 주소와 화면 사진 필드 대조 — 수집기 운영 반영 기록

실방이 종료된 뒤 직접 다운로드 주소가 같은 방의 사진 링크 또는 표시 이미지에 명시됐는지
보는 선택적 MANUAL 진단을 작성했다. 주소/쿼리/식별자는 내보내지 않으며 `PHOTO_LINK`,
`DISPLAYED_IMAGE`, `NONE`, `MULTIPLE_CARDS` 등을 기록해 다음 조사 경로를 나눈다.
기존 사진 정합 권한과 수신 결과는 바꾸지 않았다. 격리 브라우저를 포함한 68건 통과.
`8e819752` 수집기만 운영에 반영하고 해당 wheel의 SHA로 `ONE_ROOM` 실행 pin을 갱신했다.
API·Web은 기존 `cf5c5806`을 유지한다. 브라우저 패키지/설치 런타임과 Studio HTTPS·API
Ready를 검증했다. 운영 카카오 브라우저와 원격 세션을 열거나 사진을 요청하지 않았으므로
새 진단의 실제 화면 결과는 아직 없다. 전체 방 및 예약 수집은 계속 비활성이다.

## 실방 사진 재검증 — 원래 요청 연결 없음으로 확인

`44b643e2` MANUAL 세션에서 한 방의 사진과 CSV를 각각 한 번 수신했다. 파일 무결성과
이전 수신과의 동일 SHA를 확인했다. 새 진단은 `INITIAL_PHOTO_REQUEST_NOT_OBSERVED`,
같은 페이지의 최종 주소 관측, 원래 GET 연결 미확정, 후보 0건으로 나왔다. 메시지 전송·
설정 변경·정본 등록·학생 PDF 발행은 없었다. 실제 카카오에서 CSV 행 정합은 아직 못 했다.
격리 Chromium에 직접 CDN 다운로드 모양을 추가해 MANUAL 원본 보존과 자동 경로의
미확정 중단을 확인했다. 집중 테스트 60건과 별도 disposable PostgreSQL의 수락·학생별
PDF·권한 검사·재조회 회귀 9건이 통과했다.
[진단 해석과 범위](KAKAO_PHOTO_OCCURRENCE_DIAGNOSTIC_2026-11-18.md)

## 사진 출처 거부 사유 기록 — 수집기 운영 반영, 실방 재검증 전

MANUAL 수집기의 `origin-diagnostic.txt`는 보호된 원 수신 폴더에 남는 운영 진단 한 줄이다.
출처가 미확정일 때만 후보 0/1/복수, 원래 GET과 주소 일치의 관측 여부, 거부 사유를 기록한다.
URL·해시·페이지 ID·대화·파일명은 포함하지 않는다. 쓰기에 실패해도 수신 파일·결과를
바꾸지 않고, 브라우저 stderr 차단과 기존 정합 조건을 유지한다. 집중 검사 65건 통과.
[상세 진단과 다음 실증 기준](KAKAO_PHOTO_OCCURRENCE_DIAGNOSTIC_2026-11-18.md)을 따른다.

`44b643e2` 수집기 wheel만 운영에 반영했고 그 wheel의 exact SHA로 선택 방 수집 pin을
갱신했다. 별도 대화창 대응도 이 wheel에 포함했다. API·Web은 `cf5c5806` 유지, 카카오
계약·PDF·원격 환경과 권한은 변경하지 않았다. 설치 member·운영 런타임·API Ready/Studio
HTTPS 200을 확인했다. 준비 완료 시 카카오 브라우저와 원격 연결은 종료 상태였고, 실제
새 다운로드나 PDF 생성은 하지 않았다. 전체 방·주기 수집은 비활성이다.

## 2026-11-18 배포 후 실제 한 방 수신·별도 창 관측

관리자 MANUAL 세션의 목록에서 대화방 한 곳을 열었다. 대화 내보내기 CSV 1건(48행)과
사진 1건을 실제로 받고 고정 수신 기록의 크기·SHA-256과 대조했다. 카카오에 메시지를 보내거나
상담·채널 설정을 변경하지 않았다. 목록에 진행 중 상담 필터가 있어 전체 방 목록은 아니다.

- 실제 카카오가 목록과 별도의 브라우저 창에 대화방을 연다. 두 수신 관측은 동일한 방 경로와
  각 사진 링크의 방 ID를 가졌다. 그러나 사진 download receipt의 origin은 `UNAVAILABLE`이고
  정확한 말풍선·CSV 행 연결을 검증하지 못했다. 사진과 CSV는 보호된 수신 위치에 남겨 두고,
  소급 연결·정본 source 발행·학생 PDF 생성은 하지 않았다.
- 단일 방 AUTO를 연결한 소스는 이제 선택 click에서 열린 popup만 관측하며, 정확한 provider와
  room 경로·기존 방 확인을 통과한 창에서만 다운로드로 간다. 다른 방으로 열린 창, 복수 popup,
  모호한 접근은 재클릭하지 않는다. 이 후속 소스는 운영 browser를 재시작하지 않았으며 아직
  미배포다. 실제 목록 selector 및 사진 download 출처는 별개로 더 확인해야 한다.
- 격리 Chromium으로 올바른 별도 창의 CSV·사진 수신과 다른 방 창 수신 거부를 실행했다.
  관련 source 및 개발 문맥 검사 28건과 변경 모듈 타입 검사가 통과했다.
- [사진 수신과 메시지 연결 근거 상세 보고](KAKAO_PHOTO_OCCURRENCE_DIAGNOSTIC_2026-11-18.md)

## 2026-11-18 한 방 수집 운영 설치·활성화

- 설치 정본은 `cf5c5806d1d3e7133b611b188783a94af5787f99`. 기존 보호된 operator가
  worker/command/chat 실행 0건과 DB `20261117_0097`을 확인하고 API·Web·Catalog 호환
  조합을 반영했다. migration head는 유지했으며 API isolation 검사를 통과했다.
- 전용 browser 환경에 동일 release의 Kakao 계약과 한 방 수집기 wheel만 설치해 기존 수집기
  구성과 호환성을 확인했다. 기존 PDF worker·원격 런타임·프로필과 INDEX/QUERY는 유지했다.
  설치 증거는 `/var/lib/eom-kakao-collector-release-cf5c5806/installed.json`에 있다.
- Catalog에 `ONE_ROOM`만 활성화했다. 활성화 직전 미완료 수집 0건, 활성화 직후 API Ready
  200·Studio HTTPS 200·인증 없는 수집 조회 401·카카오 browser와 remote inactive를 확인했다.
  운영 플래그는 `/etc/systemd/system/eom-catalog-application-runner.service.d/56-eom-kakao-one-room.conf`다.
  전체 방·주기 수집은 비활성이고, 실제 카카오 방 열기·다운로드·학생 PDF 발행은 시도하지 않았다.
- 별도 합성 임시 PostgreSQL에서는 수집 receipt 채택, CSV·사진 occurrence 보존, 학생별 출력
  분리, Studio 다운로드 권한·재조회 9건이 통과했다. 실제 카카오 계정으로 이 경로가 끝까지
  실행됐다는 증거는 아니다. 다음 검증은 관리자 원격 로그인 후 한 방의 정확한 CSV·사진을
  등록하고 질문·학생 PDF까지 이어보는 것이다.

## 단일 방 수신 영수증 오류의 종료 처리

기존 고정 경로의 수신 영수증 bytes가 계약 위반으로 해석되지 않으면, 사용 중인 browser
fence의 실제 종료를 먼저 확인한 뒤 같은 run을 실패로 기록한다. 같은 시도를 다시 뜨게
하거나 수신물·수락된 원본·실패 이력을 바꾸지 않는다. 경로 보호나 설치 schema 문제는
이 실패 전이에 넣지 않는다. 새 wire, DB migration 또는 운영 활성화는 포함하지 않는다.

소스 집중 검사는 누락·손상·경로 보호 구분, 같은 완료본 복구 및 browser 경계를 포함한다.
guarded 임시 PostgreSQL에는 종료 전/종료 시 손상 영수증, 수신 없음과 정상 채택·재조회
회귀를 추가했다. 실제 카카오 방이나 운영 학생 PDF를 새로 확인한 것은 아니다.

## 2026-11-18 Studio 등록 방 수집 패널

Studio ‘대화방’ 패널에서 수동 확인된 선택 방의 수집 시작·상태 확인을 기존 BFF/HTTP에
연결했다. 관리자와 CSRF가 있는 시작만 허용되고, 수신이 불명확한 POST는 같은 탭의
같은 요청 키·binding 조건으로만 수동 재확인한다. 접수 뒤는 GET만 쓴다. 방/계정 전환 시
늦게 온 상태는 현재 화면에 쓰지 않고, 열린 방의 이름과 읽음 표시 가능성을 알려 준다.

격리 Chromium에서 새로고침 전후 동일 POST, 접수 뒤 GET만 사용, 늦은 응답 격리와 명시
재수집 시 새 키를 검증했다. Studio cookie/CSRF/API 경계4 PASS, Kakao 기본 브라우저
회귀와 GUI 원칙 browser 검사, mypy·Ruff·개발 문맥 PASS. 운영 활성화·실제 카카오 수집·
학생 PDF는 이 체크포인트에 포함되지 않는다.

## 2026-11-18 단일 방 작업 접수·상태 API와 기존 Catalog 실행 연결

기존 로그인/권한·binding ETag·멱등 키로 대화방 1개 수집을 접수하는 POST와 부작용 없는
GET을 추가했다. API→기존 API-peer socket→Catalog owner로만 들어가며 URL·provider 키·
브라우저 명령이 API를 통과하지 않는다. 동일 요청은 새 run을 만들지 않는다.

설치를 명시한 `ONE_ROOM`에서만 기존 Catalog 프로세스가 pending run을 진전시킨다. 기존
browser fence/attempt로 재개하고, 파일 없는 실제 종료는 실패를 남긴다. 원본 발행 재시도는
같은 capture의 기존 원본 명령과 CAS를 쓴다. 별도 DB/migration/service는 추가하지 않았다.

HTTP→실제 보호 Unix socket 및 읽기/권한 검사 집중22 PASS, disposable DB에서 동일 요청·
조회·종료 후 실패·원본 재조회 확인, 변경 파일 mypy와 Ruff, JSON Schema audit, OpenAPI
비파괴 비교 PASS. 전체 import를 따라가는 mypy에는 변경하지 않은 workflow/RAG 모듈의
타입 오류가 있으며 이 작업에서 수정하지 않았다. 소스/명세만 반영했고 Studio 버튼,
실제 운영 활성화·카카오 한 방·학생 PDF는 아직 검증 전이다.

## 2026-11-18 등록 방 증거의 C1 명령 발행·재조회

기존 수락 run/task와 등록된 방의 capability→room proof→page observation을 exact pointer와
해시로 따라가 C1 명령과 부분 inventory를 한 Artifact로 발행·pin했다. route는 원래 카카오
관측에서만 가져오고 방 이름/URL/추가 인증을 입력받지 않는다. 큰 DOM이나 capability를
복제하지 않고 선택 근거는 기존 verification artifact pointer만 남긴다.

`start_registered_room`이 이 명령을 기존 같은 브라우저 dispatch에 넘긴다. disposable
PostgreSQL에서 발행 후 pin 이전 중단, 동일 파일·attempt 복구, 보호된 writer의 재인가,
원본 수락 회귀 등67 PASS. mypy/Ruff와 문맥13 PASS. 이 경로는 선택된 한 방에 한정되며
운영 진입·카카오 실제 수집·학생 PDF는 아직 미검증이다. 운영 DB 또는 실제 카카오 계정·
인증정보를 변경하지 않았다.

## 2026-11-18 같은 수집 작업의 브라우저 수명·원본 채택 연결

수락된 단일 방 run의 profile reserve → 실제 OS 시작/관측 → 원래 attempt → 고정
command dispatch를 연결했다. 직전 MANUAL/AUTO를 넘겨받을 때는 보호된 OS fence의
exact DB 종료 기록과 실제 process closure를 모두 요구한다. start 응답이 유실되어도
같은 staged epoch를 관측하며 같은 수집을 다시 시작하지 않는다.

완료는 로컬 receipt → exact browser 종료 확인 → 기존 source 발행/채택 → 실제 C1
coverage의 `PARTIAL`/`COMPLETED` 순이다. receipt가 없고 같은 프로세스가 확인될 때만
대기하며, 종료됐는데 파일도 없으면 명시 오류다. 실패 이력이나 파일을 지우지 않는다.
저장본 재조회는 local receipt가 없어도 같은 정본과 결과를 재사용한다.

브라우저 어댑터 및 기존 runtime 단위117 PASS, guarded disposable PostgreSQL에서
브라우저 저장·원본 수락47 PASS, mypy/Ruff 및 개발 문맥13 PASS다. 이 단계는 운영
미배포이며 실제 카카오 동작은 검증하지 않았다. 다음은 실제 선택 방 증거에서 C1
입력을 발행하고 기존 운영 진입을 연결해 한 방 수집→질문→학생 PDF를 수행하는 것이다.

## 2026-11-18 AUTO 브라우저의 단일 방 명령과 guarded 수집

기존 supervisor/profile lock 아래 동일 pin의 headless Chromium이 정확한 AUTO epoch의
등록된 C1 명령을 받는다. 기존 control lock 아래 고정 파일 하나를 원자 발행하며 다른
명령으로 덮어쓰지 않는다. 고정 channel route와 안정 ID가 있는 방만 열고, 표시된 popup을
다시 검사해 기존 CSV/사진 수신 증거를 남긴다. 로그인 redirect·모호한 UI·다른 방인 경우
수집으로 가지 않는다. MANUAL 경로·프로필 자격증명·운영 DB를 바꾸지 않았다.

격리 TLS/Chromium에서 동일 표시명의 방을 구분하고 사진이 있는 방과 텍스트만 있는 방의
다운로드, 위험 동작 호출 0건을 확인했다. disposable PostgreSQL에서는 현재 room/attempt
dispatch 준비, 방 불일치, 수락 뒤 새 dispatch 거부와 원본 채택/재조회를 검증했다.
집중 소스236 PASS, 임시 DB51 PASS, mypy/Ruff와 schema audit PASS. 기존 MANUAL 회귀의
X11 fixture가 설치 invariant를 누락해 가짜 경로에서 실패했던 부분은 fixture만 바로잡았다.

소스 반영이며 운영 driver나 AUTO를 활성화하지 않았다. 실제 카카오의 목록 row 안정 ID와
읽음 효과는 합성 fixture로 증명되지 않는다. 다음은 기존 collection owner의 시작·관측·
종료 및 동일 명령으로 수신물 채택을 한 경로로 운영 연결하고 실제 한 방에서 확인하는 것이다.

## 2026-11-18 수집기 다운로드 증거의 프로세스 인계

열린 방 수집기가 command SHA와 exact CSV/사진 관측을 붙인 `open-room.json`을 고정 작업
폴더에 한 번 기록한다. 기존 Orchestrator UID/GID/경로 guard에서 읽고 현재 등록 방과
고정 command에 부합할 때만 Catalog의 기존 C1 발행·수락·원본 채택으로 넘긴다. 임시
결과/정규화 파일을 중복 생성하지 않고, 완료 재조회는 영수증 없이도 작동한다.

격리 Chromium에서 실제 loopback TLS 사진 다운로드, CSV blob, 고정 영수증, 중복 실행
거부를 검사했다. 임시 PostgreSQL에서는 동일 영수증 구조로 원본 수락/재조회 및 잘못된
방·명령 거부를 검사했다. 소스 집중131 PASS, disposable DB25 PASS, mypy/format/lint와
canonical schema/mirror audit PASS. 운영 DB·브라우저·카카오 계정은 변경하지 않았다.
실제 고정 AUTO browser driver가 현재 세션의 방을 열어 이 작업을 호출하는 연결과 실제
질문→학생 PDF는 아직 검증 전이다.

## 2026-11-18 다운로드 증거에서 C1 수락까지 격리 검증

Catalog의 기존 C1 제안 담당에 CSV/사진 수신 member 검증과 사진 행 연결을 붙였다.
같은 방과 완전한 앞뒤 텍스트가 유일한 행만 `SEQUENCE_INFERRED`로 넣고, 다른 방·중복
후보·관측 부족은 미연결 건수로 남긴다. 파일명으로 연결하거나 확인되지 않은 발화자·
시간대·수집 범위를 추정하지 않아 전체 상태는 여전히 `PARTIAL`이다.

합성 CSV와 실제 PNG 작업 파일 → disposable PostgreSQL의 기존 C1 수락을 통과했다.
같은 PNG가 2개 행에 등장해도 첨부 ID는 각각 다르고 원본 Artifact는 재사용한다.
같은 요청 재조회에서 재등록하지 않고, 허용하지 않은 경로·hash 불일치도 차단한다.
소스 변경만이며 운영 원본·실패 이력을 변경하지 않았다. 실제 카카오 자동 실행과 그
결과의 학생 PDF는 미검증이다. 다음 통합은 기존 attempt가 실제 수집기에 작업을 전달하고
그 수신물을 같은 fence로 가져오는 연결이다.

## 2026-11-18 이미 열린 한 방의 사진·CSV 수집 순서

기존 scope 확인과 로컬 전송을 `capture_open_room`으로 연결했다. 열린 방의 동일 channel·
room path 근거에서 사진 후보 최대6개를 순서대로 받고, 기존에 열려 있지 않은 메뉴의
CSV 내보내기를 한 번만 실행한다. 앨범/중복/상한 밖의 사진은 미확정이며, 현재 화면 밖
이력은 완전했다고 보고하지 않는다. 같은 attempt directory로 재실행하거나 다른 방을
자동 열지 않는다. 중간 전송이 불확실하면 받은 파일은 보존하고 후속 동작은 중지한다.

격리 Chromium에서 동일 로컬 attempt의 실제 302 사진 다운로드와 CSV blob 저장,
두 번째 실행 거부를 확인했다. 미확정 앨범/중복 링크/다른 방/잘린 DOM/부분 보존의
단위 검사까지 집중89 PASS, mypy/Ruff 및 개발 문맥13 PASS다. 이 변경은 소스 전용이다.
실제 카카오 세션은 닫혀 있고 DB/NAS 등록·질문 PDF와 운영 AUTO는 이 단계에서 실행
또는 갱신하지 않았다.

## 2026-11-18 고정 읽기 동작과 로컬 다운로드 연결

작업 위치에 write-once 시작 표시를 남긴 뒤 고정 동작을 한 번 실행한다. 동일 페이지의
CSV blob 또는 exact image GET/redirect를 실제 SDK event와 연결해, 확인된 파일만 기존
보호된 copy의 hash/bytes와 제한된 화면 관측으로 반환한다. 중복/불확실한 이벤트는
같은 시작 표시에서 자동 재클릭하지 않는다. 기존 MANUAL 저장·receipt는 그대로다.

격리 Chromium의 실제 CSV blob 수신, loopback HTTPS302의 사진 bytes/관측, 이전
MANUAL 수신과 timeout 재개·다른 transfer·복수 event 차단을 확인했다. 관련82 PASS,
strict mypy/Ruff PASS다. fixture의 setgid 상속은 임시 incoming을 기존 mode0700으로
만들어 수정했으며 운영 권한 검사는 완화하지 않았다. 소스 테스트만 수행했으며 실제
카카오·AUTO 실행·원본 등록·학생 PDF 활성화는 이 변경으로 이루어지지 않았다.

## 2026-11-18 열린 방의 고정 읽기 동작

실제 관측한 열린 방 메뉴·대화 내보내기의 내 PC 저장·단일 사진 다운로드만 실행할 수
있는 collector adapter를 추가했다. 실제 채널/방 key는 하드코딩하지 않는다. 같은 도메인·
채널 route와 사진 endpoint가 가리키는 방을 대조하고, 버튼이 중복되거나 가려졌으면
누르지 않는다. 메시지 및 상담 변경 동작은 없다. 클릭 요청과 download 성공을 구분한다.

격리 Chromium에서 CSV 및 사진 download event와 bytes, 클릭 수, 잘못된 방·텍스트·오버레이·
편집 요소·중복 popup 거부를 확인했다. 별도 loopback TLS fixture는 새 동작으로 시작한
사진의 실제 302와 관측 receipt까지 확인했다. 집중64 PASS, mypy·Ruff PASS다. 테스트
fixture의 초기 invocation 및 브라우저 가로채기 경계 실패는 운영 실행이 아니다.
운영 배포나 실제 카카오 방에서 새 click은 없었으며 AUTO/정식 원본·PDF는 미완료다.

## 2026-11-18 한 방 부분 수집 결과와 정식 원본 등록 경계

이미 고정된 C1 command/capability/inventory, 실제 CSV bytes, 행 관측과 사진 pointer로
기존 normalization·room-report·result를 조립하는 순수 함수를 추가했다. 두 문서가 서로
다른 사진 순서나 행을 받지 않도록 동일 evidence에서 만들며, 미확정 정보를 추정하거나
부분 수집을 완료로 승격하지 않는다. 기존 C1 bytes/schema 변경, runtime 실행/권한
부여, 공개 입구·운영 변경은 없다.

기존 guarded local workspace→result 수락→원본 Artifact→task 채택에 이 함수의 합성
출력을 실제로 넣었다. 같은 시각·본문의 CSV 두 행과 같은 사진 bytes의 별도 occurrence
두 건을 보존했으며, 원본 그림은 재사용하고 같은 요청은 이미 채택한 정본을 재조회했다.
unit/C1 66 PASS, 임시 DB 23 PASS, context13·mypy·Ruff PASS다. 실제 카카오 원격 세션은
여전히 닫혀 있었고, 실제 room source/PDF·전체방 주기 실행은 미완료다.

## 2026-11-18 Studio 사진 위치 확인 운영 반영

source `5a480ab99302f3de9939beb7aa36602ad422d215`의 API/platform/API contracts와 Web을
호환 묶음으로 설치했다. 운영 0097 검증, 보호된 source/wheel admission, installed wheel
member/RECORD, Web offline 폐쇄 설치와 service UID 파일110건, API namespace 검사가 통과했다.
API/Web/Catalog/QUERY가 새 프로세스로 준비됐고 HTTPS Studio 로그인200·API READY200,
새 조회 경로의 비로그인401 및 실제 배포 JS SHA의 source 일치를 확인했다.

PDF worker/layout·collector/profile/auth·기존 원본/실패 이력을 그대로 유지했다. AUTO는
비활성이다. QUERY의 provider/source pin만 호환 갱신하고 수치 runtime은 보존했다.
INDEX·자료 학습·창작 학습은 배포 전부터 FAILED/PID0인 별도 상태였고 복구나 재시작하지 않았다.
보호된 release 기록은 `/var/lib/eom-kakao-capture-release-study-5a480ab9/api/activated.json`,
설치 기록은 `staging/kakao-photo-check-{stage,activate}-5a480ab9.log`다.

운영 endpoint와 asset 검증은 실제 카카오 인증/사진 정합/PDF 실증이 아니다. 다음은 같은
프로필의 실제 방에서 새 CSV·사진 수신과 행 연결을 확인하는 것이다. 과거 관측을 새
receipt로 바꿔 쓰지 않는다.

## 2026-11-18 Studio 받은 자료에서 사진 위치 확인

같은 수집 회차의 CSV·사진을 고르면 Studio → API → Catalog socket → 보호된 local reader로
확인한다. 응답은 원 선택의 두 capture/lease/binding과 CSV 행 번호 또는 미확정뿐이다.
조회 후에는 원본·대화방·질문·PDF가 저장되지 않는다. 기존 방 확인과 받은 자료 목록의
wire는 그대로고, OpenAPI 비교에서 새 GET 1건만 추가됐다. UI는 새 선택/로그아웃 후
늦은 응답을 표시하지 않는다.

격리 Chromium의 실제 선택/재조회/미확정/늦은 응답 검증과 disposable PostgreSQL의
실제 Studio→API→socket→파일 정합 경계가 통과했다. 집중 56 PASS(별도 후보 화면의
full Chromium 실행 파일이 없는 1건 제외), 임시 DB 28 PASS, strict mypy10개, Ruff와
schema audit PASS다. 이 절의 실제 카카오 연결과 새 PDF
생성·다운로드는 아직 미확인이다. 운영의 기존 profile/수집 원본·활성 설정은 바꾸지 않았다.

## 2026-11-18 보호된 실제 수신물 reader와 사진 정합의 연결

Catalog 내부 `inspect_photo_occurrence`가 현재 운영자의 exact binding/원 MANUAL lease로
CSV와 사진 capture 두 건을 읽는다. 실제 보호된 reader로 UID/GID/mode/hash/크기를 확인하고,
공통 strict CSV parser에서 새 revision을 생성하지 않고 원래 행만 읽는다. 같은 사용자/lease
검사를 결과 반환 직전에도 다시 수행한다. 공개 API, browser 동작, 원본 등록, DB/NAS 쓰기,
기존 실패 기록 수정, AUTO 활성화는 없다.

unit 87 PASS, guarded disposable PostgreSQL 38 PASS(수신·방·PDF HTTP 회귀 포함),
strict mypy 4개·Ruff PASS다. 새 임시 DB 사례는 검증한 두 payload의 정확한 row 1건,
동일 입력 재조회와 Artifact 0개 추가, 타 운영자·변조 파일·늦은 권한 철회를 확인했다.
기존 합성 경로의 사진이 있는 학생 PDF 다운로드·동일 결과 재조회도 검증했다. 실제 카카오
재연결과 새 capture는 없었고, 이 변경은 source-only다. 실제 source 수락→Studio PDF와
전체 방 자동 수집은 별도 미완료다.

## 2026-11-18 사진–CSV 행 정합 준비

실제 한 방에서 확인한 단일 사진과 앨범의 DOM 모양을 분리했다. 정합은 기존 수신 proof의
run/fence/page, 두 관측의 같은 방과 exact CSV hash를 확인한다. 단일 사진 아이콘에서 얻은
target이 한 메시지에만 있고, 그 사진을 감싸는 서로 다른 완전 텍스트 사이의 연속 패턴이
CSV 전체의 두 방향에서 단 한 번 나타날 때만 `SEQUENCE_INFERRED`를 반환한다. 동일 시각·
동일 `사진` 행의 개수와 순서를 유지한다. 앨범·더보기·중첩 텍스트·혼합 방·잘린 DOM·
아직 target을 얻지 못한 옛 수신물은 미확정이다. 채팅 내용과 실제 방 key는 커밋하지 않았다.

합성 정합21건 및 기존 CSV/관측/Chromium 회귀 포함101 PASS, strict mypy와 Ruff PASS다.
정합 함수는 source-only이며 공개 API·운영 수락은 아직 연결하지 않았다. 직전 collector
배포는 유지하고 browser/remote inactive를 다시 확인했다. 새 사진 관측, 실제 source/PDF,
전체 방 자동화는 아직 미확인이다. 기존 수신 파일과 PDF는 수정하지 않았다.

## 2026-11-18 관측 수집기 호환 운영 반영

source `04d417bcd57335895056f0e0ebf537d9962f206d`를 커밋·푸시하고 collector/contracts
두 wheel을 browser 전용 prefix에 반영했다. 실제 source/fixture 변경은 아래 절에 기록한다.
API/Web/Catalog 코드·DB0097·PDF worker와 활성 layout은 바꾸지 않았다. Catalog만 설치 창에서
정지·재기동했고 실제 새 MainPID의 active·socket 준비와 `NeedDaemonReload=no`를 확인했다.
HTTPS Studio 페이지200은 인증된 카카오/PDF 검증과 구분한다.

- 최초 설치 시도는 오래된53cb1a1e 통합 manifest와 현재 runtime hash 차이를 감지해 **설치 전**
  멈췄다. 실제 browser는 이미 승인된eda2a1b0의 exact tree/wheel과 일치했다. PDF는 별도
  승인된c93f78f7의d18fa035 worker·a3ee8722 template을 사용 중이었다. 이를 변조/장애로
  간주하거나 옛 PDF로 후퇴하지 않고 실제 component별 release set을 대조했다.
- 두 번째 시도도 개발 build의 `/tmp` 경로에 운영 protected-file reader를 잘못 적용해
  **운영 패키지 변경 전** 중단됐다. 기존 helper/실패 로그는 보존했다. 후속 instance는 입력
  wheel SHA 검사→root-private 복사→같은 SHA 재검증의 기존 설치 경계를 사용한다.
- 세 번째 instance는 실제 predecessor hash와 별도 PDF wheel member를 먼저 검사했다.
  browser 두 wheel의 offline 설치·모든 wheel member byte 비교·pip check·실제 interpreter
  import와 공식 installer stage/verify가 PASS다. 다른 desired config가 현재 bytes와
  일치함을 검사하고 PDF runtime/env/template/activation·최초 profile receipt를 보존했다.
  INDEX/QUERY pin·원본·기존 실패 이력·인증 파일을 바꾸거나 AUTO를 활성화하지 않았다.
- collector wheel SHA는
  `008eaa6aa4ceb7de7f2ce575f49a7d0a20619969d8351d16ff0b424b994bc22f`,
  contracts wheel SHA는
  `318d927a5bc50fc8ba613beec90c94bbe23ecbd485507d22b5770efb82b87833`다.

보호된 설치 receipt는 `/var/lib/eom-kakao-observation-release-04d417bc-v3/installed.json`,
실행 로그는 `staging/kakao-observation-release-04d417bc-v3-20261118.log`다. 앞선 두 설치 실패와
read-only component 대조 결과도 보존한다. 이번 반영은 **adapter 설치 성공**이지 실제 새
사진→메시지 occurrence 연결이나 source 수락→Studio PDF 성공이 아니다. 기존 profile로
다시 원격 화면을 열어 direct text와 실제 redirect 증거를 받는 것이 다음 검증이다.

## 2026-11-18 실제 한 방 CSV·사진 수신과 관측 adapter 수정

사용자가 실제 채팅 목록을 연 상태에서 원격 browser/remote의 active MainPID와 화면을
확인했다. 목록에는 `진행 중 상담` 필터가 있었으므로 전체 접근 방 inventory로 취급하지
않았다. 실제 보이는 row만 열고 메뉴·스크롤·CSV 내보내기·사진 다운로드를 수행했다.
메시지 입력/전송·답장·차단·상담 완료·방 나가기는 하지 않았다. 채널/학생 이름을 코드에
고정하거나 실제 대화/사진 내용을 Git·Slack에 넣지 않는다.

- 새 CSV1건(66,258bytes)과 사진1건(3,093,525bytes)이 실제 로컬 `RECEIVED`다.
  immutable download/DOM receipt와 원 bytes는 보존한다. CSV의 DATE/USER/MESSAGE155행 중
  문자 그대로 `사진`인 행은51개지만 실제 파일/album 개수나 확인된 attachment로 세지 않는다.
- 이때의 DOM은 item_chat41개와 사진 링크14개다. bounded observation의 truncated=false는
  현재 로드된 tree의 상한 미도달이지 CSV 전체 이력의 완전성 증거가 아니다. 화면 추가 로드와
  CSV 순서/행 연결·context bounds 검증이 필요하며 번호를 맞춰 강제로 연결하지 않는다.
- 실제 사진 링크는 같은 message 영역의 same-origin image endpoint다. 최종 SDK download
  URL이 CDN으로 이동해 기존 target이 UNAVAILABLE인 것을 재현했다. CSV/사진의 파일명은
  association 근거로 사용하지 않는다. 현재 receipt를 SOURCE_VERIFIED로 고쳐 쓰지 않는다.
- body26개와 시각의 direct text가 child element/BR 때문에 기존 leaf-only 표현에서 빠지는
  결함도 확인했다. 기존 관측의 source bytes를 바꾸지 않고 새 관측 adapter를 수정했다.

수정은 기존 collector owner의 direct text/BR 읽기와 page-local GET redirect correlation이다.
노드/문자 상한·편집/인증 subtree 제외·MANUAL16건 예산은 유지한다. 실제 Request predecessor,
페이지/원래 URI,64건·최근 leg60초·8redirect 한도를 확인하고 모호한 후보는 소비 후 거부한다.
최종 signed query/header/cookie는 결과에 저장하지 않으며 새 네트워크 요청·권한/queue/schema는
추가하지 않았다. direct CDN URL만 있는 경우는 그대로 UNAVAILABLE다.

검증: 관련 source277 PASS, 실제 로컬 TLS302→CDN 역할의 임시 Chromium fixture PASS,
guarded disposable PostgreSQL의 수신/방 경계24 PASS, strict mypy3개·문맥13건·Ruff/format PASS다.
277건은 browser fixture를 포함한다. 마지막 추가 private-subtree fixture도 별도로 통과했다.
최종 browser fixture는 loopback CONNECT proxy와 임시 인증서를 사용하며 DNS 외부 해석을
막는다. 별도 브라우저의 임시 self-signed 인증서 허용은 fixture에만 있고 운영 TLS는 바꾸지 않았다.
실제 Chrome download 파일이 group-writable인 최초 fixture는 production과 같은 UMask0077을
설정해 고쳤다. 파일 permission 검증을 느슨하게 하지 않았다. 최초 source invocation의
PYTHONPATH/없는 test 경로 오류와 redirect/TLS fixture 실패 로그도 보존한다.

증거: `staging/kakao-source-observation-fix-{focused-v2,db,types-final,context,browser-final}-20261118.log`,
실제 수신의 내용 없는 구조 대조는 `staging/kakao-live-{dom-structure,row-evidence}-20261118.*`다.
화면/원 CSV/사진은 private staging 및 기존 로컬 수신 저장소에만 있으며 공개 evidence가 아니다.

**이 절의 수정은 아직 source-only다.** 현재 API/Web4f778cb4·DB0097과 실행 pin은 그대로다.
원격 연결은 추가 확인 시 inactive/MainPID0이었다. 수정본을 별도 wheel과
설치 manifest로 검증·반영한 뒤 기존 로그인 profile을 재사용해 같은 방에서 실제 재검증한다.
로그인/권한을 위조해 source를 등록하지 않는다. AUTO driver·실제 source→Studio PDF·전체 방
주기 수집은 아직 미완료이며 기존 preview PDF를 그 성공으로 재분류하지 않는다.

## 2026-11-17 21:26 UTC 호환 운영 반영과 실제 수집 대기

운영 core/API/Web/Catalog/Runner/QUERY source는
`4f778cb4f3454c4e52279b229c3ee689d092fa60`로 반영했다. API/Web의 실제 설치 build-info가
같은 commit이고 새 MainPID로 실행 중이다. 기존 protected release operator의 source archive/
wheel admission, 별도 Web offline 설치 simulation·service identity110개 파일, 실제 API
namespace 검사와 DB0097 read-only 검증이 통과했다. HTTPS 로그인 화면200과 API READY도
확인했으나 **이번 release의 실제 사용자 로그인/실제 카카오 검증을 대신하지 않는다**.

- 새 API build는 공식 OpenAPI 갱신 후 통과했다. 새 wire predecessor/명세의 의미를 바꾸거나
  schema0097을 다시 upgrade하지 않았다. runtime 교체 중 API/Web은 잠시 중지했으며,
  current worker/command/chat0과 transient process 부재를 기존 guard로 확인했다.
- creative는 기존 지원 SIGINT로 배치를 drain한 뒤 이전 active 상태로 복원했다. 기존
  INDEX는 배포 전부터 failed/MainPID0이었으며 원 Invocation/config·수치 실행 pin을 그대로
  보존했다. GPU 재개를 주장하지 않는다. QUERY의 API provider/source closure만 호환 갱신했고
  수치 모델·실행 설정의 나머지 필드는 기존 codec으로 동등성을 검사했다.
- worker helper `b324019c…`, PDF worker `d18fa035…`, PDF layout/activation, MANUAL 설정과
  인증·기존 Artifact는 보존했다. AUTO와 shared concept continuation은 켜지 않았다.
  collection adapter 설정도 미지정 그대로라 실제 수락 authority를 임의로 활성화하지 않았다.
- 과거 배포 스크립트에서 API 정지 중 호출했던 isolation 검사는 이번 reviewed release
  instance에서 실제 API READY 이후에 호출했다. 최초 설치와 후속 verify가 모두 통과했다.
  새 운영 배포 framework나 상시 서비스는 추가하지 않았다.

증거는 `staging/kakao-4f778cb4-{api-build,web-build,stage,drain,activate,verify}-20261117.log`,
보호된 release receipt는 `/var/lib/eom-kakao-capture-release-study-4f778cb4/api/activated.json`과
기존 `/var/lib/eom-api/deployments/`다. 이번 release의 운영 side effect는 재시도하지 않았다.

실제 수집의 다음 단계는 여전히 **미완료**다. `132f11d4`·`95a270d5` 체크포인트에 이어
이번에도 browser/remote inactive/MainPID0이며 실제 화면 재연결 응답은 아직 없다. 과거
고정 download root를 기존 protected reader와 실제 browser UID로 읽기 전용 검사했지만,
현재 형식의 적격 `page-observation.json`은0건이었다. 이는 수신 CSV/사진이 없거나 유실됐다는
판정이 아니며, source 권한/전체 방 inventory/사진 연결 증거로 사용하지 않는다. 계정·DB·
browser·payload에 쓰지 않았고 메시지·이름·전체 URL은 검사 결과에 출력하지 않았다.
증거: `staging/kakao-archived-dom-structure-20261117.{jsonl,err}`.

전체 목표를 완료 처리하지 않는다. 실제 UI selector·CSV 범위·사진 occurrence 연결은 확인되지
않았고 AUTO driver 실행·모든 접근 방의 주기 수집·실제 원본의 Studio PDF 재조회/다운로드도
남아 있다. 추정 selector나 합성 source를 운영 성공으로 바꾸지 않는다. 다음 사용자 동작은
Studio `일반 → KakaoTalk`에서 기존 연결의 `카카오 로그인 준비`를 누르고 방 하나를 열어
화면을 유지하는 것이다. Linux/Studio 비밀번호 변경이나 메시지 전송은 필요 없다.

## 2026-11-17 후속 기능의 호환 운영 빌드 준비

`95a270d5`의 공식 API build-only 검사가 installed-wheel OpenAPI와 새 질문 source refresh
route의 불일치를 설치 전에 거부했다. 운영 쓰기/설치는0이다. 기존 `export_openapi.sh`로
현재 명세와 SHA를 생성했으며 추가 경로는 `/questions/{question_id}/refresh-source` 하나다.
기존 경로 삭제·breaking change0, API 명세/질문 갱신 회귀30건 PASS다. 기존 released worker/
메시지 schema bytes는 변경하지 않았고 실패 build 로그도 보존한다.

Web의95a270d5 wheel closure·별도 설치 simulation은 통과했다. 수정된 clean commit으로
API/Web을 다시 빌드한 뒤 기존 protected release operator로 조립한다. 현재 단계는 운영
배포/사용자 로그인/실제 카카오 검증 증거가 아니다. collection adapter 설정은 미지정 상태를
유지하며 AUTO를 켜거나 MANUAL 관측을 AUTO 성공으로 재분류하지 않는다. 기존 수치 runtime과
실행·인증·완료 Artifact는 보존한다. 새 실제 수집/전체 방 주기 실행은 별도 미완료 gate다.

## 2026-11-17 실제 수락 owner를 질문 runtime에 조립

기준 source는 `132f11d4`다. 운영용 `build_kakao_question_application`이 capture admission을
항상 거부하는 owner만 만들던 연결 공백을 보완했다. 기존 attempt owner의 공개 read-only
`sources`를 질문·읽기·편집·개념에 함께 주입하며 별도 source 저장소를 만들지 않는다.
`application_runner`는 명시적인 collection adapter SHA와 기존 profile ID가 있을 때만
실제 owner를 조립한다. 미지정은 기존 비활성, 잘못 명시한 pin은 구성 오류다. browser driver
SHA로 대신하지 않는다. 새 schema·migration·queue·dependency·모델 실행은 없다.

- 구성만으로 browser/collector/source admission을 실행하지 않는다. 실제 RESULT_ACCEPTED
  capture와 현재 owner/권한·원 policy/result/report를 기존 application에서 다시 확인한다.
- 임시 DB에서 실제 accepted result→source 발행/채택→질문 source resolution까지 연결했다.
  확인되지 않은 CSV 순서는 여전히 `SOURCE_ORDER_UNVERIFIED`이며 성공 fixture를 만들려고
  capability를 승격하지 않았다. 기존 known-order 저장·질문→PDF 검사는 별도로 유지한다.
- 정상 logout 이후 같은 원본을 완료하고 controller를 다시 만들어도 같은 key의 완료본을
  읽는다. workspace 재독해·중복 Artifact·새 HTTP session은 없고 공개 source read에는
  현재 로그인이 필요하다. 다른 profile의 accepted-run 접근과 변경된 adapter의 원본 발행은
  payload 읽기 전에 거부된다.
- source/compatibility·cold import 단위123건, 별도 설치 wheel/import3건, 의존 방향12건,
  strict mypy4개와 개발 문맥13건이 통과했다. 기존 guarded runner에 새 DB 검사를 추가했다.
  첫 focused 명령은 runner 목록 누락으로0건 선택돼 실패했고, 목록을 수정한 뒤2건 통과했다.
  이 최초 실패 로그도 보존하며 실행하지 않은 검사를 PASS로 세지 않는다.

최종 guarded disposable PostgreSQL 전체 **475 PASS**(439.27초)다. 이후 추가한 adapter
pin 음성 검사를 포함한 현재 연결 집중 **3 PASS**(11.11초)도 확인했다. 이3건 중 기존2건은
전체475건과 겹치므로 합산하지 않는다. 증거는
`staging/kakao-admission-composition-{full-db,final-db,verified-unit,installed-wheel,dependency,final-types,verified-context}-20261117.log`다.

기존 PDF6종(원17쪽+비교본3/6/7/4/6쪽)의 실제 파일을 다시 읽어 페이지 수·image use·
페이지 밖 text/image block0을 확인했다. 기존 원17쪽 SHA도 보존됐다. 비교본 중 질문·조교
답변/시각·참고자료 안내3쪽은 raster preview로 직접 확인했다. 이는 기존 고정 입력의 출력
검사이지 새 카카오 수집/GraphRAG/공식 Studio export가 아니다. 별도 신규 PDF를 중복
생성하지 않았고 앞의5종 링크·제한사항을 그대로 유지한다.

**SOURCE_ONLY_NOT_DEPLOYED**다. 현재 운영 `7533ca8f…`/DB0097·인증·기존 실행 pin은
변경하지 않았다. 원격 browser/remote는 확인 시 inactive/MainPID0이므로 새 실제 한 방
CSV/사진 수집은 재연결 후 검증한다. AUTO/shared concept은 비활성이며 전체 방 주기 수집과
실제 학생 PDF의 Studio 재조회/다운로드는 여전히 원래 goal의 미완료 gate다.

## 2026-11-17 늦게 받은 답변·사진의 명시적 새 검토본

`refresh_question_source`는 같은 학생/방의 exact 새 수락 source/candidate를 기존 질문의
새 UNREVIEWED revision으로 저장한다. 사람의 parent/version/mapping pin과 표시 편집 대체
동의를 필수로 받고, 기존 command 예약→Artifact 발행→CAS 채택을 재사용한다. 자동 수집이나
background 권한으로 기존 질문을 갱신하지 않는다. 새 DB/queue/worker와 외부 AI 호출은 없다.

- 독립 additive `question-source-refresh-v1`은 명령과 기존 API-peer socket의 새 operation을
  정의한다. 기존 question store/manifest/RPC schema bytes를 수정하지 않았다. 이전 question/
  packet/PDF는 원 revision에 고정되며 새 검토본은 다시 확인하기 전 최종 출력 대상이 아니다.
- 현재 원/새 source와 parent manifest의 존재·hash/schema·상태/권한을 다시 검사한다.
  첫 학생 occurrence가 다르거나 분할/병합된 원본이면 거부한다. 출처가 애매한 동일 문구를
  같은 메시지라고 강제하지 않는다. 갱신 발행 중 수동 편집이 이기면 CAS 실패로 기존 결정을 보존한다.
- 기존 API/BFF에 `POST /questions/{id}/refresh-source`를 연결했다. CSRF·If-Match·같은 요청
  key/body를 유지하고 결과의 학생 mapping·parent/version/검토 전 상태를 확인한다.
  후보 화면은 기존 질문을 연 뒤 ‘이 원본으로 새 검토본 준비’→동의→저장을 사용한다.
  수신 원본을 다시 조회하거나 방/계정을 바꾸면 준비 상태를 비워 오래된 입력을 제출하지 않는다.
- 임시 DB의 실제 HTTP/BFF/API-peer socket/owner를 통과했다. 서비스 재구성 뒤 같은 명령
  재전송도 같은 결과를 읽는다. 합성 CSV의 늦은 조교 답변·PNG가 새 질문→확인→packet→
  실제 별도 subprocess renderer→Artifact에 들어가며, 선택하지 않은 다른 후보는 PDF에
  들어가지 않는다. 이 검사는 보호된 systemd sandbox의 별도 승인 증거는 아니다.
- 합성 실제 Chromium 검사에서 동의 전 저장 금지·응답 유실/화면 열기 실패 후 같은 key의
  복구·완료 후 재열기 무POST·계정 전환/늦은 응답·좁은 화면·안전한 textContent를 확인했다.
  실제 Kakao 페이지/원격 profile이나 인증정보를 사용하지 않았다.

최초 테스트의 반복 문구만 있는 원본은 기존 정합 규칙에서 origin 연결이 불확실해 거부됐다.
성공 fixture를 서로 다른 anchor가 있는 합성 원본으로 바꿨으며 정합/권한 기준을 낮추지 않았다.
다른 초기 실패는 편집 명령 fixture의 필수 필드와 PDF 결과 manifest의 출력 참조 방식이었다.
승인 Artifact를 바꾸려던 음성 fixture도 기존 DB 불변 trigger가 거부했다. 해당 검사는 승인
row/trigger를 바꾸지 않고 기존 metadata read 경계의 실패를 주입하도록 정정했다. 실패 로그는 보존한다.
오래된 Node/Playwright의 브라우저 캐시는 없어, 별도 설치 없이 이미 설치된1.65.2의 Node와
Chromium을 합성 화면 검사에 재사용했다. 운영 browser driver/설정·모델·GPU는 바꾸지 않았다.

검증 증거: `staging/kakao-question-refresh-{verified-full-db,final-unit,browser-final,types-final-v2,context}-20261117.log`.
최종 guarded disposable PostgreSQL **473 PASS**(431.80초), source/API/BFF/별도 설치 wheel/
의존 방향·계약 호환 **174 PASS**, 실제 Chromium 합성 화면 PASS, strict mypy10개·개발 문맥
13건·Ruff/format/diff PASS다. 실제 카카오/HTTPS 로그인 검증이나 운영 활성화 증거는 아니다.
그 전 전체472 PASS와 초기 실패·집중 재실행 로그도 각각 보존한다. 기준 source는 `bd9682c7`이며
이 절을 포함한 commit은 Git history와 milestone 보고에서 확인한다.

**운영 미배포**다. 운영 core/API/Web `7533ca8f…`/DB0097과 기존 실행 pin·인증은 유지했고,
실제 카카오 새 방 수집·공유 개념 모델·정식 Studio PDF를 새로 실행한 것은 아니다. 기존5종
비교 PDF/17쪽 preview도 새 수집 결과로 바꾸지 않았다. 원격 browser/remote는 확인 시
inactive/MainPID0이어서 실제 방의 추가 CSV/사진 대응은 재연결 후 확인해야 한다.
실제 한 방 수집→source→질문/Studio PDF와 전체 접근 방·주기 수집은 원래 goal에 남아 있다.

## 2026-11-17 수락 원본의 후보 자동 저장과 실제 PDF 회귀

`KakaoQuestionService.create_source_candidates`가 한 번 해석한 exact 수락 source의 최대100개
후보를 기존 CREATE 예약·Artifact 발행·CAS에 연결한다. 새 DB/queue/wire/worker는 없다.
고정 source/candidate key와 bounded origin IN lookup을 사용하며 다음 ordinal과 미해석 row를
작은 내부 결과로 반환한다. 사진·CSV·질문 본문을 DB에 다시 넣지 않는다.

- API는 실제 현재 로그인을 유지한다. 내부 accepted collection access는 원 capture의
  현재 owner·ADMIN/READ/COLLECT와 **EDIT**까지 검사한다. source 권한 port가 authorized
  room metadata를 함께 돌려주도록 재사용했으며, 세션/인증/worker 권한을 만들지 않는다.
  background 권한으로 수동 검토·편집하거나 PDF를 다운로드하지 못한다.
- 기존 origin은 제외·수동 편집·분할/병합 supersession 여부와 무관하게 보존한다. 경합에서
  다른 저장이 이기면 실제 committed origin을 재확인한 경우만 건너뛴다. 발행 직후 중단은
  같은 예약·Artifact를 채택하고, 다른 source/학생 mapping/권한 변경은 명시적으로 거부한다.
- source order UNKNOWN은 기존 오류를 유지한다. 순서는 알지만 발신자를 모르는 row도
  반환하므로 후보0개를 수집/업무 전체 완료로 간주하지 않는다. 사진 대응을 승격하지 않는다.
- **전체 guarded disposable PostgreSQL454 PASS**, source/별도 설치 wheel·의존 방향
  **126 PASS**, 개발 문맥13 PASS, strict mypy6개·Ruff/format/diff PASS다.
  새 자동 저장 경로도 기존 CSV/동일 사진의 서로 다른 occurrence→질문 확인→packet→실제
  worker의 기본/역할별 PDF 두 형식을 통과했다. 운영 DB에 pytest를 실행하지 않았다.
- known-order 원본은 합성 accepted-source fixture로, background 질문 저장은 명시적인
  테스트 권한 adapter로 검사했다. **실제 collection acceptance owner**의 별도 검사는
  EDIT 범위와 UNKNOWN order의 질문 미생성을 확인한다. 전자를 실제 Kakao/AUTO 수집의
  성공 증거로 확대하지 않는다. 공개 API/다운로드의 세션 만료·권한 회귀는 전체 suite에 포함된다.

최초 집중 검사에서 SQLAlchemy 결과의 dict 변환 오류를 확인해 명시적 pair comprehension으로
수정했다. 테스트의 provenance 접근과 API read에 내부 adapter를 넣던 잘못된 검증 호출도
정정했으며 최초 실패 로그는 보존했다. 문맥 index 상한 검사는 새 테스트를 수집 주제로 배치해
통과시켰고 schema 제한을 늘리지 않았다. 권한/원본/PDF 검증을 완화하지 않았다.

증거: `staging/kakao-candidate-autosave-{focused*,full-db,unit,types*,context*}-20261117.log`.
기준 source는 `4c96778e`; 변경 commit은 이 절의 Git history와 milestone 보고에서 확인한다.
현재 운영 `7533ca8f…`/DB0097·기존 worker/QUERY/GPU pin은 변경하지 않았다. 이번 source도
아직 미배포이며 AUTO dispatcher·전체 방 주기 수집을 활성화하거나 새 모델을 실행하지 않았다.
앞서 만든 비교 PDF5종과 원17쪽 preview는 그대로 보존하며 새 수집/정식 export로 바꾸지 않는다.

남은 확인: 이번 입구는 **최초 저장**이며 기존 UNREVIEWED 질문도 자동 재작성하지 않는다.
후속 snapshot에 늦게 들어온 답변의 반영은 기존 수동 결정 보존과 함께 별도 명시적 revision
흐름으로 닫아야 한다. 다음 우선 경로는 실제 방의 발신 방향·CSV/사진 occurrence 관측을
근거로 수집→저장 질문→Studio packet/PDF를 검증하는 것이다. 전체 goal은 미완료다.

## 2026-11-17 실제 로컬 result 파일 수락과 출력 비교5종

### C1 proposal→결과 Artifact→attempt→원본 source/task

`admit_staged_kakao_capture_source`가 이제 COMMAND_READY의 worker `outputs/result.json`도
직접 받는다. 기존 typed C1/canonical bytes·실제 command/capability/fence·report hash/크기를
검증하고, `ControlFileSetPublisher`의 exact first-observation/key lookup으로 result/report를
발행한 뒤 기존 `accept_result`에 채택한다. 그 다음 이전 원본·사진 source owner를 사용한다.
새 DB/queue/wire/worker 실행이나 실패 이력 수정은 없다.

- 결과 Artifact 발행 후 attempt 채택 직전 중단은 로컬 result/report 없이 원 발행본을
  읽어 복구한다. 이미 수락한 작은 내부 metadata read는 source 권한을 만들지 않는다.
  source 단계는 실제 현재 계정·권한·원 pins를 다시 검사한다. 실패/일시중지/취소 결과는
  저장하지만 성공 source로 승격하지 않으며, 바뀐 로컬 성공 파일로 덮지 않는다.
- 전체 guarded disposable PostgreSQL **432 PASS**, 그 안의 실제 파일 ingress 집중
  **22 PASS**다. 기존 fixture의 결과 발행을 분리해, 이 집중 검사는 테스트가 먼저 결과
  Artifact를 만들어 주지 않고 실제 local proposal→결과 보관→source/task를 통과한다.
  source/wheel/OS/의존 방향 **136 PASS**, strict mypy4개·Ruff/format/diff PASS다.
- 초기 집중 검사에서 공식 control publisher의 `control_` type 경계를 확인해 새 미출시
  publication type을 그 계약에 맞췄다. publisher의 허용 범위나 기존 type을 넓히지 않았다.
  실패 로그는 보존했다. root·UID·group·filesystem 권한은 완화하지 않았다.

증거: `staging/kakao-result-ingress-{db-focused,full-db,unit,types}-20261117.log`와 최초 실패/
수정 재실행 로그다. 합성 browser/capability 관측이며 실제 파일·저장·Artifact owner를 쓴다.
이 source 변경은 아직 운영 미설치이고 기존 API/Web/DB·GPU/슬롯 pin은 변경하지 않았다.

### 실제 카카오 화면의 좁은 관측

사용자가 새 MANUAL에서 로그인해 채팅방을 열었다고 알렸고, read-only screenshot에서
실제 방/대화를 확인했다. 개발 화면 관측은 입력/클릭/키보드/전송0이었다. 그 뒤 browser/
remote가 각각 MainPID0/inactive로 정상 종료됐다. unit 기록은18:50:27/28 UTC 시작,
18:55:51/52 종료이며 API의 마지막 실제 RENEW 완료는18:55:21이다.30초 lease와 일치한다.
UI background timer 제한 가능성은 **추정**이며 구체적인 클라이언트 원인은 미확정이다.
인증 실패로 단정하거나 lease/권한을 완화하지 않았다. 원래 프로필/인증·실패 이력은 보존했다.
사용자에게 Studio를 보이는 별도 창으로 유지한 재연결을 요청했다. 그 사이 미확인 새 방의
사진/발신 방향/범위를 추측해 source로 등록하거나 AUTO를 시작하지 않았다.

### 기존 보관 입력으로 만든5개 실제 PDF 비교

사용자의 추가 샘플 요청에 따라 원래17쪽 preview의 **고정 입력**을 재사용해 설치된
`KakaoPdfExecutor`/fixed isolated worker와 기존 core Artifact publisher로 출력했다.
수작업 PDF 합치기/새 수집/새 retrieval·model 실행은 없으며 정식 Studio export가 아니다.
수동 사진 대응·첫 질문 사진 미확보·시간대 미확정과 관련 교재의 부분적 관련성은 그대로다.

| 비교 | 쪽수 | Artifact / revision |
| --- | ---: | --- |
| 질문만 |3|`artifact_abc7e79963a6461f84ffe48b1459782e` / `rev_fcd01856cadf420eb63985665422d38f`|
| 질문·조교 답변 |6|`artifact_aaf3f9b49674454cbbc2ebbfeb128fa1` / `rev_fa2c900ed72f466ca182ad97e04f6d9c`|
| 첫 질문·기존 교재 참고 |7|`artifact_ed9240003f3d4b278f1f89718d22a9ae` / `rev_54db3034ecf14f9e8b9de1a3e0c0b77a`|
| 둘째 질문·교재 근거 미확보 표시 |4|`artifact_ac4a23d557b746d8b305936daf85fd58` / `rev_5a880ec0e6e943b0bbca9cce7e8aaa3c`|
| 셋째 질문·기존 교재 참고 |6|`artifact_5764111fb302457baaf99f8e121a5484` / `rev_cd568867b8a241efbdc362de57fe2a03`|

각 PDF는 질문당 STUDENT1쪽·원본 사진 배치 수·본문 glyph 보존과 동일 결과 복구를 검사했다.
대표 질문/답변/교재 페이지 PNG7개를 직접 확인했다. 첫 추가 검사에서 단순 Unicode
substring이 CJK font의 hyphen/ellipsis/compatibility Jamo reverse-CMap alias를 오판했다.
설치 writer의 기존 판정과 같은 **고정 font의 정확한 nonzero glyph ID**로 비교 검사를
바로잡고, 첫 완료 worker는 재실행하지 않고 원 결과를 복구했다. source text·renderer·font
bytes는 바꾸지 않았고 최초 검사 실패 로그도 남겼다.

확인한 출력 UX 한계: 첫 교재 참고 샘플의 마지막 쪽은 출처 문구만 별도 pagination된다.
이미지 누락/본문 잘림은 아니지만 caption과 이미지가 함께 배치되도록 기존 study pagination
owner에서 개선할 후보로 기록한다. 이를 이유로 PDF bytes/이전 acceptance를 덮지 않는다.

증거: `staging/kakao-pdf-variants-{20261117.log,summary-20261117.json}`, 첫 검사·font alias
진단 로그와 각 immutable Artifact의 PDF/layout/PNG다. worker render5회·완료 결과 복구는
별도이며 source 수락/새 교재 검색/model 실행0이다. 실제 새 방→질문 저장→공유 개념 추천→
Studio PDF 및 전체 방 주기 수집은 여전히 남은 goal이다.

## 2026-11-17 고정된 로컬 수집 파일→source/task 연결

`admit_staged_kakao_capture_source`가 실제 accepted attempt의 내부 권한과 Orchestrator의
`KakaoCaptureOutputReader`를 기존 원본 발행/채택 application에 연결한다. 기존 C1의
`outputs/` member와 SHA를 사용한다. root/UID/GID는 trusted 설치 설정이며 worker/public
요청에서 받지 않는다. 파일을 찾는다고 수집 권한이나 발신자·사진 대응이 생기지 않는다.

- reader는 기존 OS guard로 root/attempt/출력 directory와 단일 member의 종류·소유권·
  control group·정확한 권한·symlink/hardlink·읽기 중 변경·크기/SHA를 검사한다. 디렉터리
  전체 스캔·재다운로드·추측 경로·NAS 쓰기·새 queue/schema/DB는 없다. 다른 attempt의 파일로
  fallback하지 않는다. 기본 server import에서는 선택적 collector 구현을 지연 import한다.
- actual staged CSV·정규화·PNG→기존 Artifact→source→LOCAL_ACCEPTED를 임시 DB에서
  검증했다. 동일 bytes의 사진 두 occurrence와 동일 문장의 두 occurrence는 각각 보존한다.
  같은 결과의 재조회·source commit 후 중단 복구는 로컬 파일이 없어도 원 revision을 사용한다.
  현재 권한 철회·경합·파일 변조와 key/precondition 변경도 검사한다.
- 수집/source owner 회귀 **85 PASS**(새 실제 파일 연결10건 포함)다. 별도 설치 wheel/
  의존 방향·문맥과 OS file guard **134 PASS**다. strict mypy2개와 집중 파일 guard
  **77 PASS**(134건에 포함)다. 입력·browser/capability 관측은 합성이다.
- 최초 파일 검증 실패는 fixture directory가 parent의 SGID를 상속했는데 정확한 최종 mode를
  설정하지 않아 발생했다. 기존 worker staging 방식처럼 fixture의 최종 chmod를 명시하고
  재실행했다. 운영의 file/UID/mode 검사와 오류 로그는 유지했다.

이 소스는 아직 운영 미설치이며 실제 C1 collector/periodic loop를 실행하지 않았다. 실제
운영 browser/remote는 상태 조회 시 모두 inactive/MainPID0이었다. 실제 selector와 사진
occurrence를 확인하려고 사용자에게 Studio의 기존 원격 로그인/한 방 열기 요청을 보냈다.
채팅 전송·답장·차단/신고·인증정보 변경은 하지 않았다. 원본을 새로 수집했다거나 이미 있는
로컬17쪽 샘플을 정식 Studio export로 등록했다고 주장하지 않는다.

증거: `staging/kakao-staged-capture-{input-db-corrected,regression-db,input-unit-final,input-types-final,boundary-unit-final}-20261117.log`.
다음은 실제 카카오에서 확인한 메시지 방향/CSV 범위/사진 occurrence를 원 C1에 기록하고,
이 source 입력→저장 질문→학생 packet→Studio PDF를 연결하는 검증이다. 전체 방 주기 수집과
공유 개념 모델 실증도 원래 목표에 남아 있다.

## 2026-11-17 수락된 수집의 로그인 만료 독립 복구

`accepted_source_access`는 trusted controller가 실제 RESULT_ACCEPTED attempt에서만 얻는
내부 source 권한 adapter다. 기존 `KakaoSourceService`의 예약·검증·Artifact 발행·CAS·task
채택은 그대로 재사용한다. HTTP 세션/토큰을 만들거나 연장하지 않는다. 공개 source/PDF
조회·다운로드는 기존 실제 API 로그인 검사를 유지한다.

- 정상 logout·idle/absolute 만료 후에도 정확한 accepted run의 원본 발행/채택을 이어간다.
  현재 owner·ADMIN/READ/COLLECT·binding/room lifecycle과 command/capability/result/report
  pins를 매 경계에서 재검사한다. background read는 그 attempt의 source만 반환한다.
- source commit 직후 controller 중단→세션 종료→service 재구성에서도 원 revision과 task만
  복구하고 worker 파일/원본·사진 재발행·새 API 세션은 만들지 않는다. terminal run은 완료
  source의 exact replay만 허용하고 새 발행은 차단한다. FAILED/미수락 결과는 권한을 못 얻는다.
- 집중 임시 DB **29 PASS**, 소스·의존 방향·별도 설치 wheel **103 PASS**, 실제 API route/
  pure 계약·문맥·배포 callback 검사 **156 PASS**, strict mypy5개·Ruff/format/diff PASS다.
  전체 Kakao 임시 DB 회귀 **410 PASS**(집중29건 포함,366.51초)다. 공개 질문·packet·PDF/
  개념 편집·현재 권한 다운로드 회귀까지 통과했지만 실제 카카오/모델 성공 증거는 아니다.
- 집중 검사에서 현재 권한 철회 오류를 일반 evidence 오류로 덮던 catch 순서를 확인해
  기존 `KakaoArchiveError`를 그대로 전달하도록 수정했다. 새 테스트의 짧은 멱등 key도
  원래 계약에 맞게 고쳤으며 최초 실패 로그를 보존했다. 거부/권한 검사를 완화하지 않았다.
- 추가 검사에서 기본 배포 준비는0094, 테스트 기대는0087에 남아 있음을 확인했다.
  배포 준비는 기존 exact `MIGRATION_VERIFY_0097` callback으로 맞추고, 회귀는 정본
  `CURRENT_MIGRATION_REVISION`과 대조하게 했다. 이전 callback/schema의 의미·bytes는
  그대로이며 migration을 실행하거나 새 revision을 추가한 것이 아니다.

증거: `staging/kakao-background-source-{db-final,full-db,unit-final,transport-final,types-final}-20261117.log`.
입력/브라우저 관측은 합성이며 실제 source/Artifact/Identity 저장 owner로 검증한다. 이 수정은
아직 운영 미설치다. 기존 운영 source `7533ca8f…`/DB0097, GPU/슬롯·인증·원본·실패 이력은
변경하지 않았다. AUTO/개념 continuation도 아직 비활성이며 전체 goal은 미완료다.

다음 검증은 trusted collector 출력 reader와 실제 관측 결과를 이 source 경로에 연결한 뒤,
확인된 메시지 방향/사진 occurrence→저장 질문→Studio 편집·학생별 PDF로 이어지는 수직 경로다.
로컬17쪽 샘플은 그대로 보존하며 정식 accepted source/Studio export 성공으로 재분류하지 않는다.

## 2026-11-17 수집 결과→원본 발행→task 채택 연결

`KakaoCollectionAttemptService.publish_and_admit_capture_source`가 실제 RESULT_ACCEPTED의
command/capability/result/report를 읽고, 기존 CSV·정규화·사진 publisher와 source/task 채택을
잇는다. caller는 고정 source precondition/key와 trusted Orchestrator local reader만 제공한다.
worker가 제시한 actor/path/권한을 사용하거나 새 source authority를 만들어 주지 않는다.

- `completed_capture_source`는 unique(binding,capture_attempt)의 exact 완료 revision을
  읽는다. 같은 요청 replay와 source commit 뒤 task 채택 전 중단은 로컬 파일/파싱/사진
  decoder 없이 원래 admission을 현재 권한으로 재인가하고 task 연결만 복구한다.
- 서로 다른 사진 occurrence가 같은 bytes를 사용하면 한 canonical blob을 참조한다.
  실제 SHA/크기·media·원문 재파싱과 source ceiling 검사는 기존 owner가 유지한다.
  UNKNOWN 화질/발신자·미확정 시간대·PARTIAL을 검증된 전체 수집으로 승격하지 않는다.
- 전체 disposable DB **381 PASS**, 그 안의 수집 attempt 집중 **26 PASS**로
  중간 발행/채택 직전 중단, 두 호출 경합, 다른 계정,
  읽기 중 권한 철회·변조와 로컬 파일 없는 완료 replay를 확인했다. 원문·사진·Artifact
  publisher와 source/task 저장은 실제 코드이고 브라우저 관측·입력/worker는 합성이다.
- 별도 설치 wheel의 feature-off 검사에서 기존 개념 adapter의 eager import를 발견했다.
  실제 입력 발행/worker context·추천 RPC/개념 선택 실행 경계로 import를 옮겼다.
  선택적 Kakao/Playwright/Pillow를 명시 거부한 새 process에서 기본 server import와
  DISABLED 질문·출력 application 생성까지 검증했다. 별도 plugin framework는 만들지 않았다.
- 소스/계약/PDF·개념·경계·설치본 **567 PASS**, strict mypy8개 및 Ruff/format/diff PASS다.
  초기 실패의 잘못된 테스트 IAM 필드와 이동한 adapter의 mock 위치를 고쳤고 원래 실패
  로그는 보존했다. 권한 검사·수락 조건·의미 있는 negative case를 제거하지 않았다.

증거: `staging/kakao-capture-publication-{db-corrected,optional-db-corrected,unit-verified,types-verified,context-final}-20261117.log`,
설치본 최초 실패/수정 로그와 전체 DB 검증 로그다. 이 소스는 아직 운영 미설치이며 실제
운영 source는 `7533ca8f…`/DB0097이다. 기존 GPU/슬롯/원본/실패 이력은 변경하지 않았다.

다음 실제 경계는 장기 collection의 **수락된 run 기반 background source 권한**이다.
현재 foreground source application은 실제 API session을 요구한다. 자동·주기 수집을 위해
가짜 API actor/session이나 관리자 토큰을 만들지 않고, accepted run에서 읽은 owner와
현재 계정·역할·binding/room·policy/adapter·attempt/fence pins를 재인가하는 명시적 경계를
기존 source 저장/멱등 owner에 연결해야 한다. 이후 trusted local output reader/collector,
실제 발신 방향·사진 occurrence 관측과 저장 질문·Studio PDF의 수직 검증을 이어간다.
전체 방 주기 수집·실제 공유 모델은 아직 완료되지 않았으며 AUTO/continuation도 비활성이다.

## 2026-11-17 17:41 UTC 호환 설치와 개념 프리셋 복구

실제 API·Web·Catalog/Runner 및 QUERY의 API-provider 호환 source는
`7533ca8f4d699fe82dcf4925fc3d31d1849f1b38`로 반영했다. DB는0097이며 최초 관측 열의
좁은 Catalog UPDATE 권한도 기존 role owner로 적용했다. 기존 PDF worker/template와
MANUAL 설정·프로필 인증은 그대로다. 새 core는 source commit 직후 수집 task 채택 복구와
최초 교재 개념 프리셋 draft 순서 수정도 포함한다.

- clean API/Web build·wheel/RECORD/격리 설치 검증 후 실제 claim0을 확인하고 creative를
  지원된 SIGINT로 drain했다. 원래 INDEX는 배포 전부터 failed/MainPID0이었으며 원래
  invocation과 파일 pins를 보존했다. 임베딩 재개·성공을 이 릴리스의 결과로 보고하지 않는다.
- 첫 활성화에서 API를 멈춘 채 실제 API namespace 격리 검사를 호출한 **배포 순서 오류**가
  발생했다. wheel과 DB0097·role 적용 상태를 확인한 뒤 재설치/DDL 재실행 없이 기존 릴리스를
  이어갔다. 이어진 HTTP 확인도 process 존재만 확인하고 너무 일찍 호출해 한 번 거절됐다.
  실제 HTTP READY를 기다린 뒤 **같은 격리 검사 PASS**를 확인하고 나머지 서비스를 올렸다.
  두 중단 로그·보호된 recovery receipt와 적용 전 config는 보존했다. 검사를 생략하지 않았다.
- 현재 API/Catalog·채팅 worker/owner·QUERY·HWPX·Web/Runner·creative는 재개했고,
  HTTPS 로그인 페이지200을 확인했다. 이는 실제 HTTPS 사용자 로그인/개념 모델 검증과 다르다.
- 원래 `4b066281…`의 발행 시각·support baseline·지침/definition·멱등 입력을 유지한 채,
  수정된 bootstrap owner로 원 개념 추천 프리셋 발행을 복구했다.
  `execpresetrev_607406cb04e94650afc982882950bcb8`, 실제 발행 PASS / 새 모델 실행0이다.
  원래 실패를 성공으로 바꾸거나 새 baseline으로 우회하지 않았다.

증거: `staging/kakao-concepts-{api-build,web-build,stage,drain,activate,recovery,receiver-recovery}-7533ca8f.log`,
`staging/kakao-concepts-control-resume-7533ca8f.log`와 보호된 deployment/activation receipt다.
일반 AUTO 수집과 공유 개념 continuation은 아직 비활성이다. 다음 우선 경계는 실제 원본
수락→저장 질문→공유 슬롯 PLAN/COMPOSE→Studio에서 편집·PDF 재조회/다운로드이며,
로컬 샘플/프리셋 발행으로 그 성공을 대체하지 않는다. 전체 방 주기 수집도 미완료다.

## 2026-11-17 교과서 보강 로컬 샘플 PDF 발행 완료

사용자가 요청한 실제 보관 CSV/사진을 기존 installed study renderer와 고정 PDF 실행기로
출력하고 core Artifact publisher로 발행했다. worker의 NAS 쓰기나 수동 PDF 조립은 없다.
질문3건·사진2장·CSV 조교 답변·원문 기록 정보와 교과서 기초 참고 자료2쪽을 포함한다.
별 질량·밝기 질문의 빅뱅 검색 결과는 수동 관련성 검토에서 제외했으며, 해당 질문에 적합한
교재 근거 미확보를 표시했다. 분석 발췌와 원본 페이지를 구별하고 실제 pin/hash를 보존했다.

- 실제 보호된 worker 결과 **COMPLETED/17쪽**이며 같은 결과 복구는
  `SAME_BYTES_NO_RELAUNCH`다. 질문은 각1쪽, 조교 답변·관련 자료는 후속 쪽에 배치했다.
- 발행: `artifact_54bba3d8a56949d08d84978e7d0e8c59`,
  `rev_e7bc1035319b4f43b05afc18aed73d85`,
  PDF SHA `de6ed25a6a36d9e31f68d10254d24087f6d188e1d9d2598a90d8279c3fb1be7c`.
  정본은 NAS Artifact의 `report.pdf`이며 이전 샘플을 덮어쓰지 않았다.
- PDF 본문 추출과 질문 사진·교과서 전체 쪽 PNG를 직접 확인했다. 첫 질문 사진 미확보,
  나머지 사진의 수동 대응·시간대 미확정을 표시했다. 없는 조교 사진을 만들지 않았다.
- Artifact 형식은 명시적 `kakao-local-study-preview`다. 정식 accepted source/question/
  packet/Studio export로 등록했다고 주장하지 않는다. 이 출력에서 새 모델 실행은0이다.
  실제 공유 슬롯 PLAN/COMPOSE와 정식 Studio 재조회·다운로드는 별도 남은 검증이다.

증거: `staging/kakao-textbook-{preview-4b066281-v2,sample-inspection-4b066281,sample-render-4b066281}.log`,
`staging/kakao-textbook-sample-published-4b066281.jsonl`과 정본 Artifact의 layout·manifest다.
학생 대화·사진·프롬프트·원문 분석은 Git/Slack에 복사하지 않았다.

## 2026-11-17 최초 관측 보존 수정·실제 교과서 조회

MANUAL의 최초 browser 관측과 최신 RENEW 관측을 분리하는 nullable 열과 DB 불변성
보호를 추가했다. 새 첫 관측에서만 실제 observer UTC를 채택하며 기존 이력의 NULL은
그대로 둔다. 수신 시각 하한은 최초 관측을 사용하고, 과거 미기록은 보수적인 기존 최신
시각으로 판정한다. lease/fence/현재 권한·종료 검사는 완화하지 않았다.

- guarded disposable PostgreSQL 전체 **370 PASS**다. 실제 저장 owner에서 갱신 전 수신물
  허용·최초 전/만료 후 거부, 값 변경/삭제·역사적 추정 backfill 거부와 rollback-only 별도
  schema의0096→0097 왕복·이력 손실 거부를 검사했다. 운영 DB에서 pytest하지 않았다.
- release context1.32는0096→0097과 동일 head만 허용한다. 과거 context1.31 bytes와
  callback 의미는 보존했다. release/권한/문맥/경계 집중 **110 PASS**, 새 source strict
  mypy5개 PASS다. 첫 권한 회귀의 예상 allowlist 누락1 FAIL은 테스트에서 정확한 새 열을
  반영한 뒤 재검증했으며 실패 로그도 보존했다. 테이블 전체 UPDATE 권한을 주지 않았다.
- 아직 이 source 수정은 운영 미배포다. 실제 installed API/Web은 `4b066281…`, DB0096이며
  보호된 source archive/wheel 검증·호환 배포는 후속이다.
- 실제 사용자 재인증 후 공식 authoring Graph/policy와 accepted textbook reader로 세 질문의
  교재 분석/원본 PNG를 읽었다. 해당 테스트 세션만 로그아웃했다. 원본을 재수집·등록하거나
  모델을 실행하지 않았다. 이는 정식 질문/개념 task/Studio PDF export 성공이 아니다.
- 픽셀을 직접 검토해 지구시스템/엘니뇨 자료 두 쪽은 기초 참고용으로 사용하고, 별의
  질량·밝기 질문에 검색된 빅뱅 자료는 관련성이 부족해 샘플에서 제외했다. 이 수동 샘플
  관련성 판단을 자동 selector나 실제 모델 검증으로 보고하지 않는다. 출력은 기존 installed
  study PDF executor/worker와 core Artifact publisher로 진행하며 샘플 한정 상태를 유지한다.

증거는 `staging/kakao-first-browser-{observation-full-db,observation-types,release-unit-final}-20261117.log`,
`staging/kakao-textbook-preview-4b066281-v2.log`와 샘플 검사·출력 로그다. 원본 사진 미확보와
수동 사진 대응·원문 시간대 미확정은 그대로다. 실제 개념 모델/정식 수집 수락·전체 방 주기
수집과 최종 운영 검증은 남아 있으며 전체 goal을 완료 처리하지 않았다.

## 2026-11-17 원본 수락→수집 task 채택의 중단 복구 연결

기존 `KakaoCollectionAttemptService`에 `admit_capture_source`를 추가했다. 기존 source
admission 계약을 그대로 받아 `KakaoSourceService.admit_source`와 원 task 채택을 순서대로
호출한다. 새 wire family·DB/queue·collector는 없다. 실제 accepted capture callback·현재
사용자·source hash/CAS 검사는 원 owner에 남는다. 저장 직후 중단되면 같은 입력/key가 원
revision을 읽고 task만 채택한다. 정식 source가 없는 로컬 샘플을 이 입구로 우회 등록하지 않는다.

- guarded disposable PostgreSQL 전체 **365 PASS**, 해당 수집 attempt 집중 **15 PASS**
  (전체에 포함), 경계/문맥25 PASS, strict mypy·Ruff/format/diff PASS다.
- 새 검사는 실제 source/Artifact 저장 뒤 task 채택 전에 중단·서비스 재구성·같은 key 재조회와
  두 호출 경합, 다른 owner/미수락 결과 거부를 검사한다. 반복된 동일 시각·동일 문장의 두
  occurrence는 보존하고 완료 복구에서 Artifact 수는 늘지 않는다. 수집 입력/관측은 합성이다.
- 증거: `staging/kakao-collection-source-adoption{-full-db,-types,-boundaries}-20261117.log`와
  집중 `staging/kakao-collection-source-adoption-20261117.log`다. 이 변경은 아직 운영에
  설치하지 않았다. 실제 collector/원본 수락·카카오/PDF 성공 증거는 아니다.

### 실제 샘플 조회에서 발견한 관측 시각 문제

사용자의 Studio 로그인은 성공했으나 로컬 샘플이 canonical 수락용 시간 검사를 불필요하게
호출해 `KAKAO_ARCHIVE_MANUAL_CAPTURE_STALE`로 종료됐다. 보호된 읽기 전용 진단에서 수신
CSV는2026-11-16 19:11:37 UTC에 완료됐고, 같은 run의 저장된 `browser_observed_at`은
19:16:18 UTC였다. `renew_session`이 latest 관측을 이 필드에 갱신하는데 기존 intake가 이를
first-ready 하한으로 해석한다. 다운로드/계정 오류로 단정하거나 과거 row를 고치지 않았다.

로컬 preview는 기존 Orchestrator의 retained-download reader(종료된 run의 보관 bytes 읽기
지원), 실제 현재 사용자/owner·권한, 원 fence/receipt/CSV hash와 교재 pins로 읽는다. 이
preview에서만 canonical admission 시간 검사를 제거했고 원본 등록/운영 검사/이력은 그대로다.
첫 실패 파일·로그와 실제 권한 조회는 보존하고 새 v2 sample materialization을 분리했다.
이는 정식 수집 수락을 완화한 것이 아니다. 첫 검증 세션은 종료됐으며 재인증 입력을 준비했다.

운영 intake의 시간 해석은 별도 후속 수정 대상이다. 최초 browser-ready 증거와 latest 관측을
분리해 보존해야 하며, 최초 시각을 현재 timestamp·CSV 시각·추측으로 역사적 row에 backfill하지
않는다. 새로운 정상 수집과 갱신 이후 과거 다운로드 수락을 함께 회귀 검증한다. 이 항목과
실제 교과서 보강 PDF·공유 모델/정식 질문 출력 및 전체 방 주기 수집은 아직 미완료다.

## 2026-11-17 교과서 보강 호환 릴리스 — 설치 완료, 실제 샘플 진행 중

운영 compatible set은 `4b066281b345a14ffeb6e5893b3895cc6e0f2c66`이다. 앞선 설치 전
검사에서 OpenAPI snapshot과 새 definition의 admission 검사 누락을 각각 확인·수정했다.
실패한 build 로그는 보존했으며 검사 자체를 완화하지 않았다. admission 집중49 PASS와
API/Web의 새 clean-commit build-only·독립 설치 검사를 통과한 뒤 반영했다.

- 기존 보호된 release operator context1.31로 정확한 DB0093→0096 전환·확인과 제한된
  API/Catalog/HWPX role 조정을 수행했다. wheel/RECORD 검증 후 API·Web·Catalog/Runner·
  chat와 QUERY의 호환 source/config pins를 기존 절차로 인계했다. QUERY 수치 설정은 보존했다.
- 실제 claim/작업0을 확인하고 creative를 지원된 SIGINT로 drain했다. API/Catalog→chat worker→
  chat owner/source socket→QUERY→Web/Runner 순서로 시작하고 creative도 재개했다.
  API READY·HTTPS 로그인 페이지200을 확인했다. 이는 실제 HTTPS 사용자 로그인 검증이 아니다.
- 고정 worker helper는 원 hash를 검증·보존한 뒤 새 source의 `b324019c…`로 반영했다.
  PDF renderer `d18fa035…`와 PDF 활성 설정은 바꾸지 않았다. INDEX는 배포 전부터
  failed/MainPID0이었고 기존 Invocation `aada2a6ef82043e4a15ae68f6dd73f20`와 설정·핀을
  그대로 보존했다. 이 배포로 GPU 재개를 주장하지 않는다.
- 운영에서 새 추천 definition과 지침/bundle 발행까지 진행했으나 새 role protocol을
  draft 검사보다 늦게 등록하는 첫 설치 순서 문제로 `CONTROL_PROTOCOL_POINTER_MISSING`이
  발생했다. 새 모델 실행0이며 추천은 비활성이다. 원래 발행 시각·baseline/key와 산출물은
  보존하고 같은 요청으로 복구한다. source에서 등록을 기존 짧은 draft transaction의 검사
  앞으로 옮겼다. 임시 DB의 순서 재현 검사1 PASS, 발행 집중 회귀8 PASS와 strict mypy·
  Ruff/format PASS다.1건은8건에 포함된다. 이 source 후속의 설치 반영은 별도다.

설치 증거는 `staging/kakao-concepts-{api-build,web-build,stage,drain,activate}-4b066281.log`,
프리셋 baseline/발행 실패는 `staging/kakao-concepts-control-{baseline,publish}-4b066281.log`다.
보호된 배포 receipt와 기존 config/helper bytes도 해당 release owner 아래 보존했다.

사용자 요청의 실제 CSV/사진 샘플은 아직 정식 accepted source/question으로 등록된 자료가
아니다. 현재 production composition의 source admission은 비활성이므로, 이 샘플을 가짜
capture authority나 synthetic question으로 등록해 모델 성공을 만들지 않는다. 원본 수락
연결과 실제 질문→공유 슬롯→정식 PDF는 여전히 남은 gate다. 우선 실제 사용자 로그인으로
현재 출제와 동일한 공식 Catalog Graph/policy·accepted textbook reader를 사용해 관련
통합과학 근거와 원본 PNG를 조회하는 **명시적 로컬 샘플**을 준비했다. 세션/권한을 만들거나
저장하지 않고 현재 인증과 원 수신 CSV hash를 확인하며 읽고 해당 검증 세션만 종료한다.
그 결과를 정식 저장 질문/Studio export나 실제 모델 검증으로 확대 보고하지 않는다.

최종 교과서 보강 샘플 PDF·링크는 아직 미완료다. 첫 질문의 사진 미확보, 두 사진의 수동 내용
대조와 provider occurrence 미확정, 원 시각대 미확정은 보존한다. 적절한 지구과학 근거가
없으면 통합과학의 관련 기초 개념만 제시하고 정답 근거인 것처럼 쓰지 않는다. README 최종
정리와 실제 전체 방/주기 수집도 남아 있으며 원래 goal을 완료 처리하지 않았다.

## 2026-11-17 실제 빌드에서 API 명세 정렬

`b3749ce0`의 API build-only 검사가 새 study/concept 경로와 과거 OpenAPI snapshot의 차이로
설치 전에 거부됐다. 테스트·wheel import를 운영 readiness로 대체하지 않고 기존 exporter로
현재 명세와 SHA를 다시 생성했다. pure Kakao contracts도 exporter의 명시적 source closure에
포함했다. 기존 released message schema bytes는 변경하지 않았다.

- API OpenAPI의 보안/멱등/결정론·현재 route 비교 **7 PASS**, 기존 snapshot 대비 지원하는
  breaking 검사 PASS, 문맥 검사·bash/diff PASS다. 새 명세 SHA는
  `fcb074f6f0e68b3cdce866568f79c06b3c3a9996148d92ebd66a4a9e74f99d42`다.
- 실패한 build 로그는 `staging/kakao-concepts-api-build-b3749ce0.log`로 보존했다.
  이 실패 과정에서 운영 설치/DB 변경/모델 실행은0이다. Web build-only는 통과했지만
  수정된 명세와 같은 새 source commit으로 양쪽 릴리스를 다시 만든다.
- 관련 증거는 `staging/kakao-concepts-openapi-{export,tests,breaking,context}-20261117.log`다.
  새 릴리스 설치·실제 추천/교과서 샘플·최종 PDF와 전체 원래 goal은 여전히 진행 중이다.

## 2026-11-17 공유 추천 프리셋의 실제 운영 발행 준비

source `0f15c85cc650df8cee5bf787ed52b6136355816c` 후속이다. 빠져 있던 추천 지침/프리셋
발행을 `eomctl control-plane bootstrap-kakao-concepts`로 연결했다. 기존 Control publisher와
draft→NON_LIVE 계약 검사→release를 사용하며 모델/계정/slot/capacity 발행기를 새로 만들지 않는다.

- 검토한 source commit/지침/UTC 시각과 current support preset의 exact revision/hash가 입력이다.
  현재 모델 후보·PLATFORM pointer·shared1.7 capacity를 그대로 쓰고 추천 ROLE 지침만 발행한다.
  기존 preset/슬롯06 예약·auth binding/capacity는 수정하지 않는다. admitted1.41 definition이
  먼저 있어야 한다. runtime은 발행된 pointers를 읽으며 Git/config 파일에 의존하지 않는다.
- 기존 process-safe publication lock과 짧은 Control adoption lock을 재사용한다. 같은 입력은
  같은 Artifact/draft/release이며 경쟁 publisher도 하나만 채택한다. 바뀐 baseline/다른 기존
  정책은 명시 거부한다. 이 최초 발행 도구를 임의 정책을 덮는 범용 updater로 쓰지 않는다.
- 임시 PostgreSQL 전체 **360 PASS**, 그중 발행 집중 **7 PASS/353 deselected**, source/CLI/
  문맥 집중 **40 PASS**, 독립 설치 wheel **10 PASS**, strict mypy2개·Ruff/format/bash/diff PASS다.
  별도 CLI2 검사는40에 포함되므로 합산하지 않는다. 발행 경쟁·replay·stale baseline/
  policy conflict·기존 auth/capacity 개수 보존을 검사했다. 새 target key만 fixture별 scope하며
  이전 합성 이력을 수정하지 않았다. PLATFORM은 합성 control metadata이며 실제 모델/교재
  성공 증거가 아니다. 평가 보고는 NON_LIVE/CONTRACT_VALIDATION이고 품질 점수가 없다.
- 초기 발행 검사에서 지침 helper의 이중 hash key가128자 상한을 넘음과 UTC 문자열
  정규화 전후 보고 hash 차이를 발견했다. 공개 byte publisher의 단일 key와 기존 typed
  EvaluationReport 정규화를 사용해 고쳤다. 입력 상한/기존 serializer를 느슨하게 하지 않았다.

증거: `staging/kakao-concept-bootstrap-{focused-db-final,full-db,source,cli,wheel,
final-types,lint}-20261117.log`. 이 단계의 실제 모델/운영 migration/재시작은0이다.

운영 읽기 전용 점검에서는 API/Web 모두 `c93f78f7df43ee261566c40e6a1dbf4d3f501ddf`,
DB0093, held worker0/active command0/chat0을 확인했다. browser/remote는 inactive다.
INDEX owner는 이 점검 전에 이미 failed/MainPID0(종료 시각2026-11-16 01:19 UTC)이었고
현재 GPU compute process는 없었다. 이번 작업으로 재시작/실패 기록 정리는 하지 않았다.
기존 INDEX pin·설정과 자료는 호환 배포에서도 보존한다. 세부 비밀값 없는 점검은
`staging/kakao-concept-live-preflight-20261117.log`다.

다음은 새 compatible release set의 빌드·보호된 설치/DB0096 전환·추천 활성화와 실제
교과서/수신 질문·사진 샘플이다. 최종 PDF 링크·README와 실제 운영 사용자 경로 검증은
아직 남아 있다. 원래 goal의 실제 한 방/전체 방 주기 수집도 남아 있으며 전체 완료가 아니다.

## 2026-11-17 추천 API·교과서 원본 그림·Studio 선택 연결 — source 검증, 운영 미배포

source `7bb3f6b6f42202517d1643dcb7b02adecab9e7c4` 후속이다. 질문별 개념 추천 시작,
진행/완료 읽기·추천 작업 목록과 교과서 원본 PNG를 기존 API/BFF에 연결했다. Studio에서
설명/근거·원본 페이지와 선택 범위를 보고 block/capture를 골라 기존 저장 편집본/PDF에
넣을 수 있다. **실제 모델/교과서로 만든 마지막 샘플 PDF와 운영 활성화는 아직 남았다.**

- 설계18절과 새 `catalog-kakao-concept-v1` Schema2020-12/mirror를 먼저 정의했다.
  SHA는 `sha256:edc833881da8be50731d2e13e4fec4d6c33e8660626ab45fc6c19a4cddcbe644`다.
  기존 create/stored 계약·schema bytes·DB0096을 재사용하며 새 migration/dependency/queue는 없다.
- POST는 실제 actor와 기존 task/Workflow 제출을 사용한다. 같은 key/body는 원 작업이며
  continuation 비활성에서는 시작을 거부한다. GET/이전 결과 조회는 모델을 실행하지 않는다.
  목록은 기존 B-tree keyset이고 UUID 순서를 최신순으로 표시하지 않는다.
- 완료 결과의 원문 인용/승인 분석/모델 초안을 구분하고 실제 교재 page key만 PNG로 읽는다.
  현재 source와 권한·hash/media/크기를 다시 검사한다. 임의 source/path/slot/권한 입력과
  다른 질문의 응답은 거부한다. 원 worker 입력/전체 분석을 공개 JSON에 복사하지 않는다.
- 추천 선택은 기존 메모를 보존하고 작은 block/capture index만 편집본에 반영한다.
  불확실한 POST는 같은 key/body를 재확인하며 학생/계정/권한/양식 변경은 timer와 늦은
  응답을 폐기한다. 적합한 교재가 없으면 NO_MATCH/한계를 표시하며 가짜 그림을 만들지 않는다.
- 새 실제 COMPOSE 저장 테스트에서 소수 crop 좌표가 기존 integer-only 메시지 serializer에
  거부됨을 확인했다. 개념 결과 adapter의 finite-number Artifact 입구를 분리하고 공통
  staging/commit을 재사용했다. job/artifact/revision identity와 canonical bytes·중복 key/
  NaN을 검사하며 기존 메시지/control/manifest 규칙은 변경하지 않았다. DB는 작은 header다.
  이는 운영 장애를 재현·복구한 증거가 아니라 활성화 전 source 통합 검사에서 잡은 오류다.
- 최종 source **804 PASS**, guarded disposable DB 전체 **353 PASS**, 마지막 공개 HTTP
  집중 **2 PASS/351 deselected**, 실제 Chromium 합성 화면 **11 PASS**, 독립 설치 wheel
  **10 PASS**, strict mypy12개/Ruff/format/diff/bash PASS다. DB 두 검사는 중복이다.
  공개 HTTP 검사는 실제 BFF→API→UDS→DB·canonical Job Artifact의 PLAN replay/진행·완료
  COMPOSE/원본 PNG 반복 조회/잘못된 page 거부다. **모델 출력과 교재 discovery는 합성**이다.
  별도 OS UID/systemd·실제 교재/카카오/모델 성공으로 확대하지 않는다.
- 문맥/권한/release-boundary **41 PASS**, wire audit1498 canonical/1140 mirror/13099 refs다.
  초기 pytest 예약 인자/fixture 속성과 문맥 index 경로 상한 오류도 수정·재검증했고,
  최초 소수 좌표 저장 실패를 포함한 개발 로그는 보존했다. 실제 실행 실패 이력은 바꾸지 않았다.

증거: `staging/kakao-concept-public-{final-source,full-db,final-http-db,final-wheel,
final-browser,final-types-all,context-boundaries-final,wire}-20261117.log`와
`staging/kakao-concept-picker-browser-20261117.log`.
실제 모델/GPU 실행·운영 migration/설치/재시작·카카오 조작·로그인 요청은0이다.

다음은 기존 Control owner로 실제 추천 preset/지침을 발행하고, 보호된 호환 API/platform/
Catalog/Runner/Web 묶음과 SHARED continuation을 활성화해 실제 수신 질문·사진에 적절한
통합과학 교과서 근거를 붙인 PDF를 만드는 것이다. 최종 PDF를 직접 확인하고 링크를
전달한 뒤 README/운영 증거를 마무리한다. 최초 사진 미확보·원 시각/역할/첨부 연결의
미확인 상태는 정직하게 유지한다. 원래 goal의 실제 한 방 occurrence/전체 방·주기 수집도
남아 있으며 AUTO는 활성화하지 않았다. 이 source 체크포인트를 전체 완료로 보고하지 않는다.

## 2026-11-17 완료 PLAN→공식 교재→COMPOSE 자동 continuation — source 검증, 운영 미활성

source `d0c2f513431f0051e59c952d0fd4543bf467184a` 후속이다. 실제 actor의 task 수락·PLAN
입력 준비·기존 Workflow 제출을 하나의 start use case로 연결했고, 완료 PLAN 뒤 교재 읽기와
COMPOSE 제출을 background continuation으로 이었다. **추천 공개 API/화면·실제 preset 발행/
공유 모델 실행·교재 보강 최종 샘플과 운영 배포는 아직 남았다.** 전체 goal 완료가 아니다.

- 설계17절을 먼저 작성했다. 새 DB/queue/worker protocol은 없고 기존 task/phase·Workflow/
  Job/Artifact owner를 쓴다. 작은 candidate/metadata와 process-local cursor/tick lock만 추가했다.
  긴 교재/PNG I/O는 transaction 밖이며 API/source-authorization socket과 다른 thread다.
- 저장한 실제 owner/current 권한으로 이어가며 로그아웃한 HTTP session을 가장하지 않는다.
  PLANNED만 다음 단계로 보낸다. NEEDS_INPUT/FAILED/CANCELLED를 새 모델/identity로 자동
  재실행하거나 과거 결과를 고치지 않는다. GET/완료 replay도 새 계산을 시작하지 않는다.
- 첫 PLAN replay는 원래 definition/preset을 읽고 공통 `validated_preset`을 재사용한다.
  두 phase 사이 current preset이 달라지면 초기 구현은 명시 거부하며 최신 모델을 몰래 쓰지
  않는다. 이 current 변경 흡수는 지원한다고 보고하지 않으며 activation 때 pin을 확인한다.
- 운영 권한의 정적 대조에서 Catalog의 SELECT-only preset 경로가 UPDATE 권한도 요구하는
  행 잠금을 호출함을 발견했다. 공통 resolver의 같은 검증 body에 명시적 read/lock 인터페이스를
  두고, 이 source-owned plan만 읽은 시점의 released revision을 pin하도록 수정했다. 기존
  관리자/다른 실행의 row lock은 그대로다. Catalog 권한·DB schema를 넓히지 않았다. SQL과
  기존 잠금 회귀를 검사했으며 **실제 운영에서 발생한 오류를 복구했다고 보고하지 않는다**.
- composition은 `EOM_KAKAO_CONCEPT_MODE=SHARED`에서만 continuation을 만들고 default는
  DISABLED다. 일반 collection AUTO와 별개다. 종료/예외 시 stopping event를 먼저 set해
  resident thread를 멈춘 뒤 engine을 정리하는 회귀도 추가했다. 실제 운영 mode는 변경하지 않았다.
- guarded disposable DB 전체 **351 PASS**, 공통 preset reader 재사용 후 최종 집중 **8 PASS/
  343 deselected**다. 두 검사는 중복되므로 합산하지 않는다. 실제 완료 Job/result Artifact와
  PNG→COMPOSE 입력/Workflow/command, logout/서비스 재구성·독립 coordinator 두 개의 동시
  DB 세션 경쟁·단일 command, 계정 중지/설정 변경 거부·원 PLAN replay와 새 PLAN start를
  검사했다. source/Workflow/claim은 실제 DB이며 **PLAN 내용과 교재 discovery는 합성**이다.
  별도 OS UID/systemd 프로세스·실제 모델/교재 검증이라고 확대하지 않는다.
- 후보 조회는 결과 본문을 읽지 않는 작은 sparse join과 LIMIT1이다. 기존 PK/FK/unique
  index를 사용하는 경로를 EXPLAIN으로 검사했다. enable_seqscan=off인 시험이므로 운영 planner
  선택/대량 throughput을 입증한 것은 아니다. 현재 query는 history에 선형 비용을 가질 수 있다.
- 최종 source **751 PASS**, 독립 설치 wheel **10 PASS**, strict mypy6개·Ruff/format/diff
  PASS와 문맥/wire **16 PASS**다. 공통 resolver/모델 선택·다른 자료 학습 회귀를 포함했다.
  최초 DB3 실패는 잘못된 계정 fixture column과 이전 합성
  이력이 남는 DB에서 전역 IDLE/선택 task를 가정한 검사였다. fixture query만 범위 제한해
  고쳤으며 실제 source/claim/production selector는 완화하지 않았다. read 경로 변경 후 unit13은
  다른 purpose의 ‘FOR UPDATE 필수’ fixture를 재사용한 가정이었다. 해당 purpose fixture만
  read/lock 양쪽을 검사하도록 고치고 최종751을 재실행했다. 초기 실패 로그도 보존했다.

증거: `staging/kakao-concept-continuation-{final-regression,full-db,read-preset-db,
read-preset-wheel,read-preset-types,final-context-wire}-20261117.log`.
실제 모델/GPU/운영 migration·배포·카카오 조작은0이다.
다음은 공개 추천 시작/조회·완료 개념/원본 페이지의 화면 선택을 연결하고 실제 shared slot과
교재로 샘플을 생성하는 것이다. 사용자 수신 CSV/사진·원 시각의 미확인 상태를 유지하며,
관련 있는 기초 개념만 붙이고 심화 내용의 근거를 발명하지 않는다. 최종 PDF를 직접 확인하고
링크를 전달한 뒤 README·호환 운영 배포/실제 검증을 마무리한다. 전체 방 주기 수집과 실제
카카오 occurrence 확인도 원래 goal에 남아 있고, 현재 AUTO 활성화를 선언하지 않는다.

## 2026-11-17 개념·설명 편집 화면→공개 저장·수정→PDF 연결 — source 검증, 운영 미배포

source `6766c52145630b66e064983699fe350e23a81e83` 후속이다. 기존 Catalog delivery socket과
API/BFF·Studio 학생별 PDF 화면에 저장한 개념·설명 자료를 연결했다. 실제 API와 저장소를
통해 편집/수정본 재열람·동일 PDF 재조회/권한 검사 다운로드까지 동작한다. **실제 공유
슬롯의 자동 추천·교재 결과 선택/그림 화면·최종 실제 교재 보강 샘플과 운영 배포는 남았다.**

- 설계16절을 먼저 기록하고 `catalog-kakao-study-v1` Schema2020-12/mirror를 추가했다.
  SHA는 `sha256:3c74e17b21e342dc98908580f0aeb31aa35d494bfba6aabaf52f9ec7e7ac31c0`다.
  기존 delivery1/2·study-store/export bytes는 보존했다. 기존 owner의 저장/조회/목록과 study
  PDF 요청/조회, 학생 subset의 빈 편집 양식 읽기만 공개했다. 새 DB/queue/worker는 없다.
- API actor/current permission·If-Match·idempotency와 BFF cookie/CSRF를 그대로 쓴다. 응답의
  operation/request/binding/student/packet/revision을 검사하며 caller의 slot/권한/path/latest를
  받지 않는다. 기본4MiB transport 한도를 늘리거나 내용을 잘라 성공시키지 않았다.
- 양식은 packet owner의 정확한 학생 subset에서 준비하며 가짜 study ID를 만들지 않는다.
  UI가 전체 질문을 N+1로 다시 읽어 학생을 추측하지 않는다. 공개 read는 편집 값만 반환한다.
  PDF 파일은 기존 export download로 받으며 GET/완료 replay가 새 렌더를 만들지 않는다.
- Studio `개념·설명 편집`에서 메모·선택된 개념의 수정 설명을 저장/재열람하고 새 버전을 만든다.
  저장하지 않은 수정으로 옛 PDF가 새 결과인 것처럼 출력되지 않게 막았다. 응답 유실은 같은
  key/body 확인, 학생/채널/owner/permission 전환은 늦은 응답·타이머와 private fields 제거다.
  원본 질문·답변·인용/crop을 제자리 수정하거나 task ID 입력칸을 추가하지 않았다.
- source **675 PASS**, guarded disposable PostgreSQL 전체 **344 PASS**다. 신규 HTTP4는
  전체344에 포함된다. 실제 BFF→API→UDS→저장/CAS/replay·서비스 재구성→same-user child PDF→
  Artifact→재다운로드·source/current session 철회와 단일 렌더를 검사했다. 질문/메모는 합성이다.
- Web/기존 Kakao 브라우저 회귀 **47 PASS**, 새 gateway16을 포함한 집중 **68 PASS**다.
  집중 검사의 unit52는 source675와 겹치므로 합산하지 않는다. 최종 편집 화면의 실제 Chromium
  검사도 PASS다. safe DOM·모바일 너비·응답 유실·학생 전환·완료 PDF 재조회/추가 POST 없음과
  저장 전 PDF 차단을 확인했다. **실제 카카오/모델/교재·운영 HTTPS 증거는 아니다.**
- 독립 설치 wheel **10 PASS**, strict mypy7개·Ruff/format/diff/bash PASS, 문맥/wire16 PASS다.
  audit1497 canonical/1139 mirror/13082 refs다. 초기 unit의 pytest 예약 인자명, type narrowing,
  브라우저 실행 경로는 수정·재검증했으며 로그를 보존했다. 새 dependency는 없다.

증거: `staging/kakao-study-http-{full-source,full-db,web,gateway-focused,installed-wheel,
final-types,context-wire,wire}-20261117.log`, `staging/kakao-study-editor-browser-final-20261117.log`.
GPU/기존 슬롯·운영 DB/권한/인증 파일을 바꾸지 않았다. 새 schema와 source 공개 연결은 실제
운영 activation이 아니다. 다음은 공유 슬롯의 preset/자동 PLAN→공식 교재 검색→COMPOSE와
완료 결과의 화면 선택·이미지 연결을 닫아, 실제 CSV/사진/시각에 관련 있는 통합과학 개념을
보강한 최종 PDF를 만들고 직접 확인·링크 전달하는 것이다. 교과서가 뒷받침하는 범위를 넘는
지구과학 심화 내용은 교재 근거처럼 표시하지 않는다. 이후 README·호환 운영 배포를 진행하며
전체 방/주기 수집도 원래 goal에 남겨 둔다. 전체 완료·AUTO 활성화를 선언하지 않는다.

## 2026-11-17 저장한 편집본→기존 PDF 실행·발행·다운로드 — source 검증, 운영 미배포

source `8bed83ed`의 후속이다. 기존 Export/claim/renderer/Artifact/download owner에 저장한
study revision을 연결했다. application 호출로 실제 저장본을 PDF로 만들고 같은 완료본을 다시
읽고 다운로드할 수 있다. **공개 RPC/API·Studio 편집/추천 화면, 실제 슬롯·교재와 수신 자료의
최종 샘플, 운영 배포는 아직 후속이다.** 이 source 검증을 전체 목표 완료로 보고하지 않는다.

- 새 `study-export-v1`의 작은 pin/create/wrapper/mutation을 Schema2020-12와 mirror/typed
  DTO로 먼저 정의했다. SHA는
  `sha256:8b2e35b043d4414c5252025bc6e57256a6c268a3981f0e7120e0d65cb2b77a7d`다.
  요청은 binding과 study ID/revision/manifest SHA뿐이며 packet/student는 study owner에서
  해석한다. 기존 export family1/2의 schema bytes와 serialized body는 그대로다.
- DB0096의 optional immutable `kakao_export_studies`는 기존 export에 작은 source pin만
  연결한다. tenant/주문·revision FK와 index, claim 이전의 동일 packet/student/profile/hash
  초기 연결만 허용하는 trigger를 사용한다. 같은 새 명령·profile/subset에서 build hash를 다시
  계산해 link 변조·기존 plain 출력의 재해석을 차단한다. 본문/그림은 DB에 넣지 않는다.
- 긴 study/교재/원문 해석은 lock 밖, CAS/claim 안에서는 study owner의 public metadata reader로
  정확한 관계를 검사한다. 실행 전후·발행·다운로드는 현재 source를 재인가한다. 저장본의 새
  revision이 생겨도 옛 PDF와 source pin은 바뀌지 않는다. 완료 replay는 준비/모델/렌더가 없다.
- 새 입력 adapter는 저장한 block/capture 순서·수정 설명·메모만 붙인다. 원 질문/답변·시각/
  source 인용은 유지한다. 원본 page와 전체 crop은 private temp에 준비하고 선택한 고유 PNG만
  최종 input boundary로 stage한다. bytes budget은 누적 제한하고 같은 PNG의 사용만 구분한다.
  새 worker/렌더러/queue·영구 그림 사본을 만들지 않는다. 기존 FINAL 품질 검사는 유지한다.
- 공식 guarded disposable DB 전체 **340 PASS**다. 저장본→실제 same-user child renderer→
  PDF Artifact 발행→권한 검사 다운로드·재조회/완료 replay와 단일 claim을 검증했다. 실제 PNG/
  crop이 PDF에 내장되고 인쇄 쪽수 미확인/출처/AI 초안 라벨·선택 그림만 worker에 전달됨도
  확인했다. **채팅·completed-concept·교재 reader는 합성**이며 protected UID/systemd나 실제
  카카오/교재/모델 실증이 아니다. source 거절 후 다운로드 차단·기존 완료 이력 보존, 다른 학생
  link SQL 거부·immutable link·rollback-only 별도 schema의 migration 왕복/이력 보호도 검사했다.
- 최종 source **644 PASS**, 독립 설치 wheel **10 PASS**, strict mypy9개·Ruff/format/diff/
  bash syntax PASS다. 문맥/wire 회귀 **16 PASS**, audit1496 canonical/1138 mirror/13051 refs다.
  최초 신규 unit 수집1건은 잘못된 fixture import명을 수정했다. source/권한/이력 guard를 완화하지
  않았으며 실패 로그를 보존했다. focused7은 전체340에 포함되므로 별도 합산하지 않는다.
- release context1.31/schema SHA는
  `sha256:b28b83792865f13b79460ea7b21e11f5e8b9d4ed5d69c26d632541c94529a09e`다.
  target0096과 명시적0093/94/95→0096·같은0096 확인만 지원한다. predecessor bytes를 바꾸지
  않았고 설치/운영 migration을 실행하지 않았다. 현재 GPU·슬롯 실행에는 영향을 주지 않았다.

증거: `staging/kakao-study-export-{full-source,full-db,installed-wheel,final-types,wire,
context-wire,current-chain-db}-20261117.log`. 실제 model/GPU·운영 수집/HTTP canary는0이다.
다음은 공개 API/Studio와 공유 슬롯의 자동 PLAN→COMPOSE 진행을 연결하고, 관련 있는 실제
교과서 근거를 수신 CSV·사진·메타데이터에 붙인 PDF를 반복 생성해 열어 보고 링크를 전달하는
것이다. 그 뒤 README 정리·호환 운영 배포/실제 검증을 마무리한다. 실제 한 방/전체 방의 주기
수집 gate도 전체 목표에 남아 있으며 현재 AUTO를 활성화했다고 보고하지 않는다.

## 2026-11-17 학생별 개념 자료의 영속 저장·편집 revision — source 검증, 운영 미배포

source `840b4d33` 후속이다. 기존 packet/student subset에 개념 block/capture 선택·제목/설명
수정·직접 쓴 메모를 별도 study manifest로 저장하고, 서비스 재구성·이전 revision 조회·동시
편집/재전송을 처리하는 Catalog owner를 구현했다. **공개 API/Studio 편집·저장 revision의
공식 PDF와 실제 교재 보강 샘플은 아직 후속이다.** 운영을 바꾸거나 전체 goal을 완료하지 않았다.

- 먼저 `study-store-v1` Schema2020-12·mirror와 typed DTO를 정의했다. SHA는
  `sha256:2baa1b8d18839c21367884da9a14999b8748b2f9925cfd520776b3a278eea5ce`다.
  입력은 선택 index/수정 설명/메모이며 임의 source·경로·인용/slot/권한은 받지 않는다.
  exact 완료 COMPOSE 결과 pin은 source owner가 채운다. 원 질문·교재·사진·모델 결과 전체를
  study나 DB에 복제하지 않는다. private 입력을 schema 예외 문자열에 출력하지 않도록 했다.
- DB0095는 작은 study head/revision/command 세 표다. FK/unique·immutable revision·head CAS,
  command replay·index-backed owner/binding 목록을 사용한다. row에 JSON/binary 본문은 없다.
  긴 packet/concept 해석·Artifact 발행은 lock 밖, 이후 짧은 adoption CAS와 현재 source 재조회다.
  같은 요청/발행 뒤 중단은 원 ID/Artifact이며 경쟁 수정은 기존 편집을 덮지 않는다.
- packet/student는 한 study에서 고정한다. 질문 subset·다른 학생·없는 block/capture·잘못된
  concept question/result·현재 source 거절을 검사한다. 일반 메모 저장은 추천 runtime 없이도
  가능하고 선택적 Codex 기능이 없으면 그 선택만 명시 거부한다. 기존 Delivery composition에
  같은 packet/source/concept owner로 연결했으나 공개 화면·공식 export는 아직 연결하지 않았다.
- 새 release context1.30/schema SHA는
  `sha256:77d0e349c6a2f4bf30fbc70b09534ebfded1b8758a92d9be564304bb4442fdd3`다.
  동일0095 확인 또는 명시적0093→0095/0094→0095만 허용한다. 기존 context/schema bytes와
  실패 기록은 유지한다. 이 설치·migration callback은 소스 검증이며 운영 실행하지 않았다.
- guarded disposable DB 전체 **332 PASS**, 최종 추가/집중 **15 PASS/318 deselected**다.
  겹치는 검사를 합산하지 않는다. 실제 packet/Artifact 저장·재구성·동시 동일 요청/경쟁 수정·
  발행 직후 중단/replay·session 철회·immutable SQL 보호·query plan·rollback-only 별도 schema의
  migration 왕복/이력 존재 시 downgrade 거부를 확인했다. **completed-concept port는 합성**이며
  실제 슬롯/교재 성공으로 보고하지 않는다. 운영 DB에는 테스트하지 않았다.
- 최종 소스 **603 PASS**, 독립 설치 wheel **10 PASS**, strict mypy6개·Ruff/format/diff/bash
  검사를 통과했다. 문맥/wire 회귀 **16 PASS**, audit1494 canonical/1137 mirror/13022 refs다.
  초기 DB metadata 검사1건은 독립 compose test의 신규 model import 누락, release 검사1건은
  shell callback 순서 기대 오류였다. 첫 합동 source의1건은 새 schema가 먼저 거부한 오류를
  안정적 ValueError로 감싸지 못한 부분이며 private 예외 처리와 회귀로 수정했다. 로그는 보존했다.

증거: `staging/kakao-saved-study-{full-db,final-focused-db,final-source,final-wheel,final-types,
wire,context-wire}-20261117.log`. 실제 모델/GPU·운영 migration/배포 실행은0이다.
다음은 저장한 선택을 원본 capture·기존 renderer에 붙이는 공식 export와 공개 편집/추천 실행
경로다. 실제 수신 CSV/사진·메타데이터에 관련 교재 근거를 붙인 반복 가능한 PDF를 열어 보고
링크를 전달한 뒤, README 정리·호환 배포/실제 검증을 이어간다. 실제 한 방/전체 방 수집 gate도
전체 목표에 남아 있다. 부분 source 검증을 전체 완료로 간주하지 않는다.

## 2026-11-17 교재 설명·원본 capture→기존 PDF 보강 block — source 검증, 운영 미활성

source `f6eefe93`의 후속이다. `kakao_concept_study.py`가 완료 COMPOSE와 현재 재인가한
교재·실제 capture를 기존 `StudySupplement`로 변환한다. 개념 설명·질문과의 연결·출처·
교재 원문 발췌·원본 PNG의 물리 페이지·조교 답변 확인 메모·근거의 한계를 구분한다.
학생 질문·사진/조교 답변·원래 시기는 변경하지 않으며 추천을 교재의 정답 보증으로 쓰지 않는다.

- 기존 page owner의 원본 PNG/crop·crop bounds 규칙을 재사용한다. 새 source·검색기·queue·
  DB/schema는 없다. 근거 본문/원본 page metadata 검사는 공통 함수로 모아 재사용했다.
  같은 crop member는 한 번 준비하고 여러 render use만 구분한다. 이 표시 ID가 카카오
  첨부 DB의 등록이나 canonical 학습자료 revision을 뜻하지는 않는다.
- 그림을 못 찾은 text-only 근거는 그림을 만들지 않는다. NO_MATCH도 학습 주제와 한계를
  표시하며 가짜 교재 인용/그림을 넣지 않는다. 원문 인용과 승인 분석·모델 설명을 구별한다.
- 새 capture의 quality_accepted는 false다. 원본 decode/crop 성공을 인간 편집 품질 승인으로
  확대하지 않는다. DRAFT PDF는 가능하나 기존 FINAL 품질/레이아웃 검사는 그대로다.
- 합성 교재의 **실제 PNG→crop→PDF 내장·PDF 재열람**과 기존 layout receipt 검사를 통과했다.
  질문/답변 다음에 보강 자료가 나오며 출처·물리 페이지·AI 초안 라벨과 원본 crop 크기가
  PDF에 보존됨을 확인했다. 이는 실제 교과서 검색·Codex 결과나 사용자가 받을 최종 PDF가 아니다.
- 최종 소스 **519 PASS**, disposable DB focused **19 PASS/300 deselected**, 독립 설치
  wheel+개발 문맥 **23 PASS**, strict mypy3개·Ruff/format/diff PASS다. 직전 전체 DB319 PASS와
  focused19는 겹치므로 합산하지 않는다. 초기2개 실패는 예상보다 앞서 동작한 metadata guard의
  테스트 위치와 context-manager mock 누락을 고쳤다. source/permission 보호를 완화하지 않았다.
  로그는 `staging/kakao-concept-study-{initial,regression,notes,full-source,focused-db,
  wheel-context,final-types}-20261117.log`다. 실제 모델·운영 DB·GPU side effect는0이다.

로컬 초안 생성은 연결됐으나 **canonical saved-study/Studio 편집·공식 export·실제 샘플 링크는
여전히 남아 있다.** 운영은 `c93f78f7` 그대로다. 다음은 이 저장·편집·출력 경로를 연결하고
실제 수신 자료와 적절한 실제 교재 근거로 반복 생성한 PDF를 전달하는 것이다. README 정리와
호환 운영 배포도 그 사용자 경로 검증 뒤 이어간다. 전체 goal 완료로 보고하지 않는다.

## 2026-11-17 PLAN 완료본→교재 근거·원본 PNG→저장된 COMPOSE 입력 — 운영 미활성

source `b92201b3`의 후속이다. 기존 질문·Task·Workflow·Artifact owner를 연결해 완료된
PLAN의 exact 결과와 공식 GraphRAG 교재 근거를 다음 COMPOSE 입력으로 저장하고,
서비스 재구성·HTTP logout 뒤에도 같은 accepted 작업을 이어갈 수 있게 했다.
**실제 교재 검색·Codex 실행·saved-study 편집/최종 PDF는 아직 완료하지 않았다.**
현재 운영은 `c93f78f7`/DB0093 그대로이며 이 변경을 운영 배포했다고 보고하지 않는다.

- 새 `concept-knowledge/1.0` Schema2020-12·mirror·typed DTO를 먼저 정의했다. SHA는
  `sha256:0e538225f8d9967501a5d04e17ce135edee0b78c5817aa06b6b76585bc16e56d`다.
  교재 source/accepted-result/normalized-text·Graph/policy·원본 page·PLAN 결과의 정확한
  revision/hash를 작은 provenance로 고정한다. `request.json`과 `knowledge.json`만 같은
  기존 Artifact 발행에 넣으며 사진/교재 PNG를 복사해 정본을 중복 저장하지 않는다.
- 최초 Graph scope는 현재 출제 preset의 검증된 retrieval policy/허용 corpus에서 한 번
  선택한다. 이후 공식 source resolver는 저장한 교재/node/anchor/분석 hash만 재인가하며
  재검색이나 최신 교재 대체를 하지 않는다. TEXTBOOK 외 source를 교재로 위장하지 않는다.
- 완료 Workflow/step/Job/Artifact와 실제 role request/result를 대조하는 reader를 추가했다.
  실패/진행 중/다른 purpose 결과는 받지 않는다. 원본 PNG가 없는 text-only source는
  존재하지 않는 그림을 만들지 않는다. 실제 페이지 metadata와 ordered file closure도 검사한다.
- accepted Task의 실제 owner/current 권한으로 background COMPOSE 준비·Workflow 제출을
  연결했다. 만료 API session이나 WORKER/ADMIN 권한을 만들어내지 않는다. 같은 phase는
  원 request/Workflow를 재사용하고 계정/권한/source 철회는 차단한다. 새 queue/migration은 없다.
- 사용자의 통합과학 교과서→지구과학 Q&A 요청에 맞춰 전용 추천 지침에 관련 기초 개념과
  원문이 실제로 뒷받침하는 범위를 구분하도록 추가했다. 억지 연결·없는 심화 근거를 금지한다.
  컨텐츠팀장 지침은 변경하지 않았으며 이 전용 지침도 아직 운영 발행/활성화하지 않았다.
- guarded disposable DB 전체 **319 PASS**, 최종 schema·background continuation focused
  **19 PASS/300 deselected**다(중복 집계하지 않는다). 실제 Job 결과 Artifact→등록 PNG→
  COMPOSE 저장·재구성·logout 후 같은 Workflow 제출을 검사했다. **PLAN 결과·교재 discovery·
  capability는 합성**이며 실제 교재/모델 성공의 대체 증거가 아니다. 초기 합성 V5 source의
  chunk manifest membership 누락은 fixture를 고쳤고 source guard를 완화하지 않았다.
- 최종 소스 **443 PASS**, 독립 설치 wheel **10 PASS**, strict mypy9개·Ruff/format/diff PASS,
  문맥/wire 회귀 **16 PASS**다. wire audit는1492 canonical/1136 mirror/12954 refs다.
  테스트·log는 `staging/kakao-concept-composition-{full-db,final-db,final-source,final-wheel,
  final-types,wire-audit,context-wire}-20261117.log`다. 운영 DB·모델·GPU 실행은0이다.

다음은 **실제 preset/자동 coordinator·공개 API→COMPOSE 완료→saved-study/Studio 편집→PDF**의
사용자 경로다. 실제 수신 CSV/사진·메타데이터와 관련 있는 실제 교재 근거/그림으로 최종
샘플 PDF를 반복 생성해 열어 보고 링크를 전달한다. 부적절한 교재를 억지로 넣지 않는다.
그 뒤 README·커밋/푸시·호환 운영 배포를 마무리한다. 실제 한 방/전체 방 주기 수집 gate도
전체 goal에 남아 있다. 이 체크포인트를 전체 완료나 운영 활성화로 간주하지 않는다.

## 2026-11-17 공유 슬롯의 실제 purpose 실행 연결 — source 검증, 운영 미활성

source 기준 `bcc6ba70`의 후속이다. Runner의 임시 미활성 거부를 실제 Catalog source 재인가
adapter로 대체했고, 기존 Orchestrator의 claim/lease→prepare→실행→검증→Artifact 발행과
중단 결과 복구에 PLAN/COMPOSE를 연결했다. **실제 모델·운영 API/화면 활성화는 아직 아니다.**
현재 운영 release는 아래 `c93f78f7`이며 GPU/기존 슬롯·실패 이력은 변경하지 않았다.

- 먼저 작은 `concept-authorization-v1` Schema2020-12/mirror/닫힌 DTO를 추가했다. SHA는
  `sha256:9d444d554d755f98a650ad981d195218263d52894abbf626696831c077c2e94b`다.
  요청은 Workflow/step/plan ID와 plan/Work hash만 포함한다. Catalog가 저장한 human owner·
  original/current request·정의·plan42·accepted phase link를 확인한 뒤 기존 task authority로
  원 질문·source closure/Artifact와 현재 계정·권한을 확인한다. 취소 Workflow는 거부한다.
  socket은 Runner UID의 이 operation만 허용한다. API/채팅/worker 권한을 넓히지 않았다.
- accepted intent는 I/O lock 밖에서 canonical bytes/hash로 읽는다. 원 session은 감사 provenance
  그대로이며 현재 계정/room/source는 매번 검사한다. source 재인가 기본 composition에는 가짜
  Graph scope를 넣지 않았다. official scope provider가 없으면 새 추천 task 생성은 명시 거부한다.
- Runner는 공개 plan validator·Core Artifact resolver로 exact private request를 읽고 실행 context를
  전달한다. prepare 단계/복구/replay/실행 전후/채택 직전에 source를 검사한다. 일반 support 실행,
  전용 슬롯이나 새로운 queue로 우회하지 않는다. workload 분류에서 새 request가 CODEX로
  분류되던 연결 누락도 검사로 발견해 KNOWLEDGE_ANALYSIS로 수정했다.
- COMPOSE는 actual E/page를 generation schema에 묶고, 결과에서도 actual request로 quote·
  page/crop/citation·task/hash를 검사한다. 존재하지 않는 근거는 Artifact에 채택하지 않는다.
  긴 설명·인용/crop은 canonical Artifact에, DB에는 기존 role metadata header만 남긴다.
- 종료된 결과 복구는 기존 fixed-unit 종료 확인 경로다. terminal 성공/실패 replay는 모델을
  재실행하지 않고 실패 이력을 바꾸지 않는다. source 철회를 replay로 우회하지 않는다.
- guarded disposable DB Kakao 전체318 PASS다. 추가 actual-concept 검사는 기존 question/source·
  실제 released preset/plan42·Job/step binding·공유 capacity와 동시 동일 Job claim의 lease1개를
  검증했다. 슬롯01–05만 허용했고6번을 쓰지 않았다. logout 후 accepted work 재인가와 현재 계정
  중지 시 거부도 검사했다. **capability observation은 합성이며 Codex/systemd 실행은0이다.**
- 소스 회귀377 PASS, 별도 설치 wheel12 PASS, strict mypy10개·Ruff/format/diff PASS다. 현재
  cancellation/input-error 처리까지 반영한 source-authority/claim/logout DB focused2 PASS도
  재확인했다(전체318과 겹치므로 합산하지 않는다). wire audit1491 canonical/1135 mirror/
  12938 refs와 개발 문맥/wire 회귀16 PASS다. synthetic worker로 두 phase의 기존 실행/발행
  경로와 변조·철회·재조회·복구를 검증하며 실제 model success를 뜻하지 않는다.
  초기 fixture의 canonical definition dump, capacity 날짜 normalization, protocol 선등록 누락은
  수정했고 guard를 완화하지 않았다. 같은 로그를 성공으로 덮어쓰지 않았다.

증거: `staging/kakao-concept-execution-all-source-20261117.log`,
`staging/kakao-concept-execution-full-db-20261117.log`,
`staging/kakao-concept-execution-current-db-20261117.log`,
`staging/kakao-concept-execution-wheel-current-20261117.log`,
`staging/kakao-concept-execution-final-mypy-20261117.log`,
`staging/kakao-concept-execution-context-wire-20261117.log`.

**다음 한 경로:** 실제 Graph scope/preset 구성→공유 슬롯 PLAN 결과→기존 GraphRAG·교과서 원본
PNG→COMPOSE→saved-study/Studio 편집·PDF를 연결한다. 그 뒤 현재 사용자 요청대로 README 정리,
커밋/푸시와 호환 운영 배포·실제 새 요청을 검증한다. 지금은 그 후속을 완료/배포했다고 표시하지
않는다. 실제 CSV/사진의 최종 반복 출력 PDF·링크와 한 방/전체 방 주기 수집도 전체 goal에 남는다.

## 2026-11-17 실제 질문 원본의 추천 task·PLAN 저장/Workflow 제출 — 운영 미활성

직전 source `08a53219` 후속이다. 기존 실제 question/source/Artifact owner를 사용하는
`KakaoConceptTaskService`를 추가했다. 이제 내부 application 호출로 원래 질문 revision을
선택해 private intent와 PLAN request를 저장·재조회하고, source authority를 검사하면서
기존 Workflow/START command에 한 번만 연결할 수 있다. 공개 API/화면·실제 모델은 아직
연결하지 않았으며 운영은 아래 `c93f78f7` 그대로다.

- behavior 전에 `concept-task-store-v1` JSON Schema2020-12와 mirror를 정의했다. SHA는
  `sha256:3aa2f8cca2d01af138ec82e5869e6c65919cd327d21177113638dc78423c80b8`다.
  공개 생성 입력은 exact 질문/version·사용자 지시·optional study revision뿐이며, operator/
  session/slot/Graph/policy/Work 권한을 입력받지 않는다. 아직 저장 owner가 없는 non-null
  study revision은 현재 adapter가 검증하지 못하므로 명시 거부한다.
- task의 같은 owner/key는 원래 identity·Graph scope이고 다른 본문은 conflict다. question/
  source/사진은 복제하지 않는다. private intent에는 정확한 question/source closure와 실제
  사용자 지시·서버의 Graph/policy pins를, phase에는 작은 기존 Work를 사용한다. request와
  intent JSON만 Artifact owner로 발행하며 원문/사진 bytes·worker 결과를 DB에 넣지 않는다.
  `PREPARED`는 입력 준비 상태이지 모델 완료 상태가 아니다.
- PLAN은 기존 역할별 source projector를 재사용한다. 학생/조교 text·사진 occurrence는 구분하고
  같은 canonical 사진 pointer는 한 번 읽어 같은 local member로 참조한다. 실제 decode/media/
  hash/길이·image bounds를 검사한다. 실제 PNG가 포함된 합성 입력도 저장한 request에서 읽었다.
- source authority는 accepted task에서만 owner를 얻어 현재 계정/권한·binding/room·원래
  source closure·question/Work/Artifact를 검사한다. synthetic HTTP actor나 WORKER/ADMIN
  권한을 만들지 않는다. 최초 session ID는 변경하지 않는 감사 provenance이며 단순 HTTP
  만료/로그아웃은 수락한 bounded 작업을 새 계산으로 만들거나 취소하지 않는다. 계정 중지·
  권한/source 철회는 차단하고, 공개 조회/다운로드는 실제 현재 API session을 요구한다.
- Catalog composition은 public `submit_kakao_concept_workflow`를 사용하며 Workflow/command/
  plan의 private table mutation을 복제하지 않는다. Catalog가 자기 phase의 workflow pointer만
  한 번 채택한다. 새 queue/전용 슬롯이 없다. Task/phase는 DB0094의 FK/unique/index·불변
  trigger로 보호하고, 긴 I/O/발행은 lock 밖이다. 같은 발행 후 중단은 원 Artifact로 복구한다.
- 공식 guarded 임시 DB의 Kakao 전체 **317 PASS**, source 회귀 **299 PASS**다. 신규 저장
  검사는 실제 기존 질문/source/Artifact·동시 중복 방지·서비스 재구성·발행 후 중단/재개·
  학생/조교 사진3 use의 binary1 참조·source authority·실제 Workflow/command 저장을 검증한다.
  **Graph scope와 실행 preset/plan port는 합성**이며 실제 교재 검색·model run 증거가 아니다.
  schema roundtrip은 같은 disposable DB의 rollback-only 별도 schema에서 수행했고, 비어 있을
  때만 downgrade·이력 존재 시 거부와 기존 app head/history 보존을 확인했다.
- strict mypy10개·Ruff/format/diff/bash syntax, wire audit1490 canonical/1134 mirror/12931 refs와
  별도 설치 wheel10 PASS다. source/package 검사와 운영 성공은 구별한다. 초기 invocation/fixture의 actor
  field와 immutable Artifact UPDATE 기대 오류는 수정했고, DB 보호를 완화하지 않았다.
  같은 disposable DB에서 DDL roundtrip과 다른 pytest process를 병렬 실행해 발생한 검사
  deadlock도 기록했다. 이후 전체 검사는 직렬317 PASS이며 이를 runtime 장애로 분류하지 않는다.
- release context1.29/schema SHA
  `sha256:28027d16285ddbd420d22a9d73dedbee5ef5cd3244aa4dcc587e0e2bac4f5b0f`는
  exact0093→0094 또는 동일0094만 허용한다. predecessor bytes는 그대로다. 기존 Catalog
  runtime에 두 표의 SELECT/INSERT와 pointer/link column UPDATE만 추가했다. 운영 migration/
  설치·권한 갱신은 **미실행**이다. 실제 배포 전에 현재 실행 pins·0094 head 호환 release set을
  재확인해야 하며 진행 중 GPU/slot을 source HEAD로 교체하지 않는다.

**다음 한 경로:** 작은 Catalog source-authorization RPC→기존 Runner client/Orchestrator의
실제 purpose 실행 context를 연결한다. Task source owner는 생겼지만 실행 composition이 아직
없으므로 executor의 미활성 거부는 유지한다. 이후 PLAN→공식 GraphRAG/원본 page→COMPOSE,
saved-study 저장/Studio 편집·새 PDF와 실제 슬롯1건을 실증한다. 마지막 실제 CSV/사진 PDF
제작·링크와 실제 한 방→전체 방 주기 수집도 전체 goal에 그대로 남는다. 이번 source 작업의
모델/GPU/운영 HTTP 실행은0이며 운영 데이터·기존 실행·실패 이력은 변경하지 않았다.

## 2026-11-17 원본 사진·교과서 PNG의 실제 image-input 경로 — 슬롯/운영은 미활성

직전 source `0a112344` 후속이다. 선택 질문의 사진과 교과서 page PNG를 함께 private worker
input으로 전달하는 경로를 기존 execution materializer/fixed worker에 추가했다. 모델에
파일 경로만 적어 보내는 방식이 아니라, 해시 확인한 파일의 실제 `--image` 인자를 검증했다.
현재 운영은 아래 `c93f78f7` 그대로이며 새 추천 endpoint/슬롯을 활성화하지 않았다.

- 먼저 image manifest6의 JSON Schema2020-12·packaged mirror를 추가했다. schema SHA는
  `sha256:db624a3f031646a78c22b01e84e9824d2544ba036f24b66905da0abce16930df`다.
  학생 사진의 PNG/JPEG/WebP와 원래 교과서 PNG를 변환 없이 전달하며, 가짜 physical-page
  번호를 붙이거나 질문 manifest/학생 명부를 worker에 복사하지 않는다. PLAN/COMPOSE 모두
  exact task/phase/request hash·참조 member closure를 읽고, 실제 source-owner callback을
  materialization/allowlist 해석 전후에 요구한다. source 거절을 다른 권한으로 우회하지 않는다.
- 기존 plan42/instruction/AGENTS/invocation owner와 source pointer 검사를 재사용한다.
  image는 하나씩 full decode·단일 frame/방향/실제 크기·media/hash/길이를 검사한다.
  request/이미지는 exclusive write이며 완료한 입력을 덮지 않는다. 파일당64MiB/64M pixels,
  최대72개·총128MiB/256M pixels다. 누락·stale·허가 철회·과대 입력은 실행 전에 실패한다.
- root-installed fixed worker는 stdlib-only를 유지한다. 원래1–5 입력과 PNG 동작을 보존하고,
  manifest6의 exact index/plan/path/hash/권한/길이와 PNG/JPEG/WebP bounded container header를
  재확인한다. full decode는 core가 맡으며 header 검사에 전체 compressed frame 사본을
  만들지 않는다. 새 helper SHA는
  `b324019c47eec0a1a96aeb39cd53b1ac5b51299dc0c4b86e3fa525c5ebe2b58f`다.
  이 helper와 platform은 향후 같은 호환 release에서 설치해야 한다. 지금 실행 중인 helper나
  슬롯/GPU pin을 교체하지 않았다. 새 queue/DB/migration/dependency도 없다.
- source 회귀308 PASS, 주변 공유 capacity/교재·page·별도 wheel 회귀256 PASS다.
  실제 입력 경로의 추가 검사 결과는 `staging/kakao-concept-inputs-complete-20261117.log`에
  별도 보존한다. 검사 묶음은 서로 겹치므로 합산한 고유 테스트 수라고 주장하지 않는다.
  strict mypy6개·Ruff/format/diff, schema audit1488 canonical/1133 mirror/12886 refs PASS다.
  guarded disposable DB에서는 기존 Workflow/command 생성·동시성·replay9 PASS를 재확인했다.
  이 DB 검사는 synthetic source/plan port이며 실제 슬롯/교재 사용 증거가 아니다.
- 첫 검사의 새 fixture에 기존 instruction record의 pinned manifest revision이 없었던 문제를
  보완했다. 별도 설치본 검사는 모든 optional role schema까지 읽으므로 현재 pure Kakao
  contract wheel도 격리 설치하도록 fixture를 수정했다(10 PASS). 기본 platform에 선택 기능을
  필수 의존으로 넣거나 검사/권한/hash guard를 낮추지 않았다. 초기 실패 로그도 staging에 남겼다.

**다음 한 경로:** Catalog의 실제 추천 task/source owner가 현재 operator·질문·교재 권한으로
request Artifact를 발행/재확인하도록 연결하고, 기존 Runner/Orchestrator의 새 purpose adapter를
실행 가능하게 만든다. 아직 그 source composition이 없으므로 executor의 명시 거부는 유지한다.
그 뒤 shared slot PLAN→공식 GraphRAG/원본 page→COMPOSE→불변 study 저장/Studio 편집→새 PDF를
실증한다. 부분 source를 전체 완료로 표시하지 않는다. 마지막 실제 CSV/사진 PDF 제작·링크와
실제 한 방/전체 방 주기 수집도 계속 남아 있다. 이번 변경의 모델/GPU/운영 HTTP 실행은0이다.

## 2026-11-17 공유 개념 Workflow의 저장·제출 경계 — 실제 실행/운영 미활성

직전 source `4ccb8004` 후속이다. 기존 Workflow/command·preset lock·capacity owner를 사용해
한 질문의 PLAN/COMPOSE child를 저장·제출하는 source를 추가했다. 실제 모델 실행이나 운영
기능 활성화를 완료한 것은 아니다. 현재 운영에는 이 변경을 설치하지 않았다.

- behavior 전에 pointer-only `kakao-concept-work/1.0`, role `workflow-role/1.41.0`와 plan42를
  additive하게 정의했다. Work SHA는
  `sha256:1c65bc31f7ffa82ec7a0bd3230db4744e79981d098867d124cdf9dd7f9c159f4`,
  plan schema SHA는
  `sha256:9e210d5f8281ec9c2db6558aabae4fc5e3a6cb769cfb927952bd0e9e28f1a40c`다.
  task/phase/binding/question/request pointer·고유 local-file map만 DB/plan에 남기며 실제 질문·
  그림 bytes는 Artifact/private input 경계에 둔다. canonical request hash와 정확한 참조
  member 집합, media/길이·page dimensions를 대조한다. 미참조 파일·다른 질문·phase를 거부한다.
- `kakao-concepts.v1`은 support one-step·attempt1이다. PLAN/COMPOSE 각각 같은 정의의
  별도 child이며 별도 worker 서비스/queue가 없다. 기존 source owner의 실제 operator 검사를
  admission 전후에 요구하고, 다른 purpose의 권한이나 arbitrary context를 받을 수 없다.
- plan owner가 현재 preset을 lock하고 P1.7 shared capacity의 실제 검증 owner를 사용한다.
  일반01–05의 support pool만 허용하고 예약06/다른 pool·구 정책으로 조용히 대체하지 않는다.
  실행 이력은 원래 모델/지침/work pin을 유지한다. command는 기존 START owner로 멱등
  enqueue하며 역할 step을 만드는 별도 factory를 복제하지 않는다.
- optional typed result decoder는 canonical schema가 요구하는 완전한 payload를 읽으며,
  ordinary core import/과거 역할 읽기는 Kakao contract/worker 설치를 요구하지 않는다.
  generation에서 표현할 수 없는 status 조건은 canonical/Pydantic 사후 검증에 유지한다.
  실제 source adapter/전용 input materializer가 아직 없으므로 executor는 이 purpose를 명시
  거부한다. 이 barrier 없이 일반 support prompt로 fallback시키지 않는다.
- source 회귀252 PASS, strict mypy12개·Ruff/format/diff PASS다. 공식 guarded 임시 DB에서
  Kakao 전체301 PASS(신규 저장9 포함)다. 새9개는 실제 Workflow/command transaction,
  concurrent duplicate 방지·재구성 후 replay·늦은 권한 거절의 savepoint rollback·기존 FAILED
  보존을 검증한다. **source/plan port는 합성**이며 실제 모델·권한·plan DB/slot 실증이 아니다.
  코드 기반 과거41개 role bundle hash를 `4ccb8004`와 대조해 변경0을 확인했다. wire audit는
  1487 canonical/1132 mirror/12886 refs PASS다. 새 migration/운영 DB 변경은 없다.
- 초기 검사 선택/fixture의 worker import·UTC 정규화 hash·resource 위치 오류는 source에서
  수정했다. DB 시험을 통과시키려고 core에 PDF worker 의존성을 추가하거나 hash/권한/
  resource guard를 완화하지 않았다. 실패/재검증 로그는 staging에 구별해 남겼다.

**다음 핵심:** parent 추천 source owner의 현재 실제 권한·canonical 입력을 기존 Orchestrator에
연결하고, 사진/교재 PNG를 실제 Codex image inputs로 전달한 뒤 해당 executor barrier를
교체한다. role/preset/worker/pure 계약의 compatible 설치·실제 공유 슬롯1건·공식 교재 검색·
study 저장·편집·새 PDF를 연결해야 한다. 실제 슬롯 실행을 했다고 보고하지 않는다. 마지막
실제 CSV/사진 PDF와 실제 한 방/모든 방 주기 수집도 여전히 전체 goal의 필수 gate다.

## 2026-11-17 교과서 원본 PNG·캡처 source 연결 — 실행/운영 미활성

직전 `574bcd8b` 후속이다. 사용자 허용에 따라 `KakaoConceptKnowledgeReader.prepare_pages`와
`prepare_captures`를 기존 official retrieval/source owner에 연결했다. 새로운 수집·검색 엔진이나
worker/NAS 권한은 만들지 않았다. 운영 release는 아래 `c93f78f7` 그대로다.

- 기존 `item_textbook_context`의 typed 결과에 승인된 page-image observation을 보존한다.
  예전 출제 Markdown bytes/의미는 바꾸지 않는다. V4 교과서와 업로드 자료 V5 모두 원래
  Artifact/revision/member/schema/media/hash·실제 dimensions를 유지한다.
- 선택된 Graph anchor와 실제 observation/member로 쪽을 고르고, 기존 Artifact reader가
  원본 PNG를 읽는다. 지문 locator로 쪽수/좌표를 추측하지 않는다. 원본 PNG가 없는 과거
  text-only 근거는 미열람이며 캡처를 만들지 않는다. 일부 쪽 미제공도 표시한다.
- 기존 현재 operator/질문/Graph/policy/source 검사를 전후 수행한다. private local root만
  허용하고 NAS로 쓰지 않는다. 같은 canonical member는 한 번만 읽어 stage한다. PNG의
  hash/길이·실제 decode/크기/단일 프레임/방향을 검증하며 source aliases의 metadata도 대조한다.
- 유효한 exact COMPOSE 결과와 실제 제공한 page에서만 crop한다. 원본 pixels를 회전·축소·
  재배치하지 않고, 좌표를 바깥쪽 정수 bounds로 변환한다. 같은 원본/범위의 crop은 재사용한다.
  결과는 source pointer·pixel bounds·고정 profile·결과 hash가 분리된 **미채택 로컬 derivative**다.
  현재 이것만으로 저장한 study revision·정식 Artifact·학생 PDF가 생기는 것은 아니다.
- 관련 신규/기존 source 회귀 **256 PASS**, strict mypy3개·Ruff/format/diff PASS다. 실제 합성
  PNG pixels와 crop pixels를 대조하고, 권한 철회·위조 source/hash/observation·stale context·
  불안전 경로·원문 없음/부분 제공·alias/crop dedup·옛 출제/Chat·PDF 회귀를 검증했다.
  개발 중 annotation import와 PNG `getexif()`→`verify()` 호출 순서 문제는 테스트에서 발견해
  수정했다. production 실행/권한 검사를 낮추지 않았고 실패 로그도 staging에 보존했다.

**남은 핵심:** 공유01–05 Workflow/프리셋/claim의 실제 실행, 불변 study 저장·편집, 이 page/crop의
발행/새 PDF 연결과 실제 슬롯1건. 이번 source가 실제 교과서 검색·모델 실행·사용자 PDF의
end-to-end 완료를 증명하지 않는다. 실제 카카오 한 방/전체 방 수집과 최종 실제 샘플 PDF도
계속 남겨 둔다. API/schema/DB/migration·운영 인증/실패/기존 실행은 이번에 변경하지 않았다.

## 2026-11-17 유휴 Codex 슬롯의 개념 보강 착수 — source, 실행 미활성

사용자가 전용 상시 슬롯이 아닌 남는 공유 슬롯과 이 기능 전용 프롬프트를 요구했고,
교과서 원문 이미지 사용도 허용했다. 기존 수집·질문 구성·일반 출력은 계속 비AI다.
선택적 추천만 PLAN→공식 GraphRAG→COMPOSE의 두 작은 단계로 구현한다.

- behavior 전에 `concept-assistance-v1` JSON Schema2020-12와 packaged mirror를 정의했다.
  SHA는 `sha256:d0975dcedc5a8b51935fe2695f385e79c85377d952aa89b3d9291a45502abfda`다.
  frozen DTO/closed registry가 task/request hash·phase·질문 pin·로컬 member·근거/페이지 key·
  원문 인용과 crop 범위를 검사한다. worker 입력에는 명부/계정/인증/slot 선택 필드가 없다.
  실제 근거가 없으면 NO_MATCH이며 source를 찾은 것으로 포장하지 않는다.
- 전용 역할 지침 source는 `config/control-plane/kakao-concepts-v1/instructions/kakao-concepts.md`다.
  PLAN은 질문·사진에서 필요한 개념만 찾으며 검색했다고 주장하지 않는다. COMPOSE는
  materialize된 근거와 실제 제공 페이지만 보고 초안을 제안한다. 분석 글과 원문 인용을
  구분하고, 조교 답변을 수정하지 않으며 카카오 조작·메시지 전송도 금지한다.
- 채팅 전용 구 read contract는 uploaded-material source V5/accepted12를 온전히 표현하지
  못하므로 거기에 새 기능을 결합하지 않았다. 임시 Chat consumer 확장안은 제거했으며
  기존 Chat source/wire는 변경하지 않았다. 출제 owner의 `retrieve_material_read_only`가
  기존 ranking/권한/source 해석의 명시적 uploaded-family 읽기를 재사용한다.
  `resolve_item_textbook_context`는 기존 Graph/source/accepted-result/anchor 검증을 typed
  결과로 제공하고, 과거 출제 Markdown도 같은 결과에서 유지한다. 별도 검색 엔진은 없다.
- `kakao_concept_knowledge`가 실제 operator/session/채널 권한과 현재 role/permission,
  고정 Graph/policy를 검사한다. 최대3개 교재 분석을 함께 materialize하고 원래 source/
  rights/Artifact/anchor pins를 core에 보존한다. worker에는 작은 E1~E3 key/분석 글만
  투영하며 원문 page/이미지를 보았다고 주장하지 않는다. 현재 권한·원래 question callback과
  같은 근거 재해석을 전후 검사한다. 새 queue·DB·migration·별도 worker 서비스는 없다.
- 최종 source152 PASS, strict mypy5개·Ruff/format/diff PASS다. 신규 V5/12 source와 rights
  pointer 보존·query source-family 구분·기존 출제 Markdown/Chat 회귀를 포함한다. 초기
  fixture ID/JSON escape 기대값·공개 type import와 typing 오류는 source 단계에서 수정했다.
  wire audit1483 canonical/1128 mirror/12867 refs가 PASS다.
- 공식 guarded disposable DB의 공유 knowledge query/권한/index 경계140 PASS다. 처음 선택한
  임시 DB에는 runtime role env가 없어 실행 전에 거절됐고, 공식 `--reconcile`로 **그 임시 DB만**
  준비한 뒤 다시 실행했다. 운영 DB 테스트나 운영 role/auth 변경은 없었다. 이140개가 신규
  Kakao 추천의 실제 DB/Workflow/슬롯/화면 성공을 증명하는 것은 아니다.

**미완료:** 기존 Workflow/프리셋/01–05 공유 claim 연결, 교재 실제 page/이미지와 crop owner,
불변 study 저장·Studio 편집·새 PDF, 실제 슬롯1건 실증이다. 현재 보강 프리셋·도구·모델은
발행/활성화하지 않았다. 마지막 실제 CSV·사진 PDF와 실제 한 방→전체 방 주기 수집도
별도 완료 gate로 유지한다. 운영은 아래 `c93f78f7` 호환 배포 그대로이며 소스 존재나 테스트를
추천 기능 운영 완료로 보고하지 않는다.

## 2026-11-17 역할별 PDF 호환 운영 배포

source `c93f78f7df43ee261566c40e6a1dbf4d3f501ddf`를 커밋·푸시하고 API/platform/contracts,
Catalog·QUERY·공유 실행 소비자, Web과 PDF worker를 호환 묶음으로 반영했다. migration은
0093 그대로다. `EOM_KAKAO_PDF_LAYOUT_POLICY=student-study-a4/1.0`을 명시 활성화했으며,
과거 v1 이력·실패·원본·인증·MANUAL 설정과 AUTO 비활성을 보존했다.

- API·Web 공식 clean-commit build/RECORD 및 Web105개 installed file·offline closure PASS다.
  source 없는 격리 core/worker 설치본의 실제 `fixed_render` 입력과5쪽/동일 완료본 복구가
  PASS다. 두 prefix의 `pip check`도 통과했다. 첫 local 설치는 같은 package version 탓에
  상속 설치본을 건너뛰어, 격리 prefix에 exact wheel을 명시 재설치한 뒤 검사했다. probe의
  worker import·group-writable 옛 fixture 선택 오류는 실제 dispatch 전 수정했으며 실패 로그를
  보존했다. 운영 검증을 통과시키려고 파일 권한·hash 검사를 낮추지 않았다.
- protected stage/admission·정상 producer drain 후 한 번 activate했다. API/Web은 함께 정지한
  구간에 설치해 새 응답과 옛 Web의 혼합 실행을 피했다. API0093 확인·최소 권한 reconcile·
  새 QUERY provider/code pin 검증·공유 서비스 재개·HTTPS login route가 PASS다.
  `staging/kakao-study-{stage,admit,prepare,drain,activate,verify}-c93f78f7.log`와
  `/var/lib/eom-kakao-capture-release-study-c93f78f7/api/activated.json`이 증거다.
- 새 PDF worker SHA는
  `sha256:d18fa035047dbabdcf98782246730308b1ecc9cf11e5a75828d1f71209ef3916`이다.
  전용 Catalog UID가 실제 fixed systemd/worker UID로 합성5쪽을 실행·정지하고 같은 output만
  복구했다. `staging/kakao-study-fixed-canary-prepare-2-c93f78f7.log`와
  `/var/lib/eom-kakao-study-canary-c93f78f7/accepted.json`에 기록했다. 사전 script의 존재하지
  않는 group 이름은 dispatch 전에 실제 계정의 primary GID를 사용하도록 수정했다.
  이는 **운영 sandbox 출력 증거**이지 실제 사용자 source 수락·Studio 다운로드 증거가 아니다.
- 추가 guarded disposable DB14 PASS(278 명시 deselect), dependency12 PASS다. 첫 pytest 선택
  인자 인용 오류는 test 수집 전 수정하고 로그를 보존했다. production DB를 pytest에 쓰지 않았다.
- INDEX와 자료 학습 owner는 배포 전부터 FAILED/PID0였고 같은 Invocation/config를 보존했다.
  이 배포가 GPU/학습을 복구했다는 뜻이 아니다. API/Web/Catalog/QUERY/creative는 새 PID로
  active이며 `NeedDaemonReload=no`를 확인했다. 별도 Kakao 로그인/수집은 수행하지 않았다.

다음은 보존한 실제 CSV/사진으로 새 출력 경로의 샘플을 만들고, 사용자가 요청한 공유 유휴
슬롯의 전용 개념 보강 프롬프트·공식 GraphRAG·저장/편집을 연결하는 것이다. 실제 한 방→
전체 방 주기 수집/사진 occurrence 정합은 여전히 미완료이며 전체 goal을 완료 처리하지 않는다.

### 최종 사용자 PDF 산출물 — 아직 미완료

사용자가 2026-11-17 재확인했다. 최종 마무리할 때 **보존 중인 실제 CSV·사진·metadata로
PDF 한 개를 만들어 파일 링크로 제공**한다. 가능한 처리는 시스템의 원본 확인·질문 편집·
packet/export/render/파일 발행 코드로 재생한다. 기존 수동 행 선택/답변 쪽 합치기 샘플을
이 완료 증거로 대체하지 않는다. 학생/조교 사진·질문/답변·시기 정보·관련 자료의 구분,
사진 미확보·정합 미확정과 교재 보강의 실제 포함 범위를 정직하게 표시한다. 새 PDF를
직접 열고 쪽수·그림/본문 무잘림·SHA/재조회·다운로드를 확인한 뒤 해당 링크를 보고한다.

## 2026-11-17 study export 저장/공개 API·Studio source 연결 — 운영 활성화 전

### 고정 실행 진입점의 추가 점검

배포 전 대조에서 CLI만 새 family를 받으며 운영 unit의 `fixed_render`는 기존 v1만 받는
누락을 발견했다. 두 entrypoint가 기존 exact parser와 작은 typed `rendering.render_pdf`
dispatch를 공유하도록 수정했다. 새 queue/schema/실행 권한은 없으며 고정 attempt·로컬
파일 검사를 유지한다. fixed study의 실제 PDF·답변/metadata·같은 attempt 덮어쓰기 거부,
unknown/mixed family·다른 attempt·unsafe request 거부, overflow의 terminal review receipt를
검사했다. 관련 기존/신규124 PASS, strict mypy3개·Ruff/format PASS다. 운영 설치 전 발견한
source 결함이며 이전 CLI/합성 검증을 실제 fixed systemd 성공으로 확대하지 않는다.

새 질문/답변 PDF가 기존 export owner와 API/BFF/Studio에 연결됐다. 기존 요청·DB·queue·
v1 schema bytes는 유지했고 두 additive 응답 schema만 추가했다. 운영의 설치/활성 pin은
아직 바꾸지 않았으므로 **운영 사용자 새 PDF·실제 카카오 수집 완료로 세지 않는다**.

1. `export-store-v2` SHA
   `sha256:f02c5fd52c8680362c04811577aecee90ada6aeb638abc2a286281bd9eb0ed61`,
   `catalog-kakao-delivery-v2` SHA
   `sha256:f3962c527fccda6ef672ce669404ec72dab01d49db3794657d5e95acbcf0c052`를
   behavior 전에 정의·mirror/pin했다. 공통 필드는 v1을 참조하고 같은 typed DTO가 두 정확한
   version을 읽는다. tag/profile/layout 혼합은 Catalog와 Web에서 거부한다. raw schema의
   전체 input을 담는 예외는 stored-export owner의 안정된 오류로 바꿔 전달한다.
2. row의 정확한 profile이 command/output family를 결정하고 완료본의 실제 쪽수·layout SHA·
   publication provenance를 대조한다. 같은 key는 예전 profile의 원래 결과이며 새 key/새
   policy는 다른 build다. v1/v2 혼합 목록·재시작·동시 claim·권한 철회/FD 닫기와 실패 이력은
   기존 owner가 보호한다. saved study owner 전에는 non-null study revision bind를 거부한다.
3. 기존 composition의 `EOM_KAKAO_PDF_LAYOUT_POLICY=student-study-a4/1.0`을 명시해야
   신규 출력이 전환된다. 기본값은 여전히v1이다. 새 worker/core/API/Web 호환 설치 및 고정
   systemd 실행 검증 이전에는 flag만 바꾸지 않는다. 새로운 DB migration은 없다.
4. source 묶음183 PASS, 최종 public contract/composition 묶음115 PASS 및 신규 설정/문맥27
   PASS다(겹침 합산 안 함). strict mypy6개·Ruff/format/diff, wire audit1482 canonical/
   1127 mirror/12839 refs가 통과했다. 잘못 잡은 jsonschema 예외 타입과 JobRecord 대신
   Artifact Revision의 result를 읽어야 하는 타입 오류는 source 단계에서 수정했으며 운영
   재시도·기록 변경은 없었다.
5. 공식 guarded disposable PostgreSQL에서 기존/v2를 함께 실행해292 PASS다.
   `staging/kakao-study-export-final-disposable-20261117.log`에 보존했다. 최종 Web DTO 확인
   이후 공식 runner의 pytest 선택으로 BFF 다운로드 두 profile+긴 조교 답변을3 PASS로
   재확인했다(`staging/kakao-study-export-web-final-20261117.log`, 나머지289개는 명시 deselect).
   실제 HTTP/UDS/DB/worker로 학생·조교 사진과90줄 원문 답변/기록 정보를 여러 쪽 PDF로
   저장·다운로드하고 실제 쪽수·동일 결과 replay/IDLE을 확인했다. synthetic이며 실제 계정
   source 수락·새 release systemd 실증을 대체하지 않는다. 기존 FastAPI/httpx 경고1건은 남았다.
6. 실제 Chromium의 익명 fixture에서 새 packet의 답변 포함 default·기존 선택 보존·새 출력
   형식 표시·완료본 링크/조회·중복 없는 재전송과 stale 화면/권한 제거가 PASS다. host Node18은
   설치 Playwright와 안 맞아 브라우저 시작 전에 거절됐고, 보호된 browser prefix의 기존
   Node26/Chromium1255를 명시해 실행했다. 새 browser/패키지를 다운받거나 카카오 profile을
   열지 않았다. 이는 실제 브라우저 fixture이지 실제 운영 HTTPS/카카오 계정 검증은 아니다.
7. 운영 service/인증/원본·실패 이력·GPU/슬롯·벡터는 변경하지 않았다. 다음은 이 호환 source를
   실제 설치 묶음으로 검증·활성화하고 보관 수신물을 같은 처리 경로로 재생하는 것이다.
   선택적 개념 편집/추천과 실제 한 방→전체 방 주기 수집/사진 정합은 여전히 남아 있다.
8. 배포용 cached OpenAPI도 공식 exporter로 갱신했다. 변경은 export/profile/mutation/page의
   명시적 응답 enum 네 개뿐이며 routes와 나머지 root 계약은 동일하다. predecessor breaking
   검사와 API 계약7개가 PASS다. 이 파일 갱신 역시 운영 설치/활성화 증거는 아니다.

## 2026-11-17 새 PDF family의 기존 입력·복구·발행 연결 — 운영 미활성

기존 Catalog materializer·Orchestrator executor/고정 launcher·Artifact publisher가 새 study
입력도 처리하도록 연결했다. 작은 pure `pdf_contracts`에서 exact command family에 맞는
manifest/result/layout만 해석한다. 별도 executor/queue/DB/NAS writer는 만들지 않았다.
v1의 저장 profile·공개 API/Web은 기존 의미를 유지하고 다른 family를 조용히 실행하지 않는다.
즉 **backend source 연결이 완료된 것이며 새 Studio PDF·실제 카카오 수집 완료는 아니다**.

1. `prepare_kakao_pdf_inputs`가 내부 typed layout policy로 기존 두 projection을 선택한다.
   현재 권한·학생 subset·고유 binary/font 검사는 같은 코드이며 default는 v1이다. 기존
   중복 pointer key 함수를 제거하고 공개 해석 함수를 재사용했다. 사진을 두 역할에서 쓰더라도
   파일 materialization은 한 번이고 각 use/원문 pointer는 유지한다.
2. 실행·정지 확인·복구는 원래 exact attempt/fence와 member/owner/hash 경계를 그대로 쓴다.
   완료한 study 쪽수는 모든 section receipt로 검증하며, v1은 기존1질문1쪽 규칙을 유지한다.
   발행의 PDF/PNG media pointer는 기존 계약, layout pointer는 exact family의 schema URI다.
   study publication에만 family/layout policy/study revision provenance를 추가한다. 기존 v1
   요청의 publication key/body 의미·과거 receipt는 변경하지 않았다.
3. 직접/기존 source232 PASS, 새 실행 focused와 문맥 검증, strict mypy6개·Ruff/format·diff
   검사를 수행했다. 공식 guarded 임시 PostgreSQL276 PASS(기존 FastAPI/httpx 경고1건)다.
   `staging/kakao-study-execution-disposable-20261117.log`에 보존했다. 실제 저장한 source/질문/
   packet을 다시 읽어 두 profile에서 학생 격리·사진 use·긴 조교 답변/시각 기록·PDF Artifact
   재조회와 같은 완료 파일 복구를 검사했다. HTTP tests는 **기존 v1**이며 새 공개 API 성공을
   대체하지 않는다. 운영 DB 테스트·새 migration은 없었다.
4. 별도 candidate venv에서 platform/contracts/worker wheel을 non-editable 설치했다.
   source 없는 `python -I -B`, wheel/설치 RECORD, core·publisher/worker import 위치와
   `pip check` PASS다. 실제 Noto 합성5쪽을 child process1회로 만들고 core가 같은 파일을
   복구했다. 이는 same-user local process 검증이지 fixed systemd/전용 UID의 새 release
   검증이 아니다. 첫 probe는 candidate pip가 종료되기 전에 시작해 import 단계에서 거부됐다.
   설치 완료를 같은 handle로 확인한 뒤 재검증했으며 그때까지 render/서비스 변경은 없었다.
   증거는 `/tmp/eom-kakao-study-execution.VipQvnt4/result.json`이다.
   - platform `sha256:3cd7dd0afecdc94ae1cf3771e831fe7cd80e020ce86d64c7eabbb0b0dc755afd`
   - contracts `sha256:27135ac4b9028e5ae3b3e4d3adfc8d1b2ffdafb971f514dee38d28a906307bdc`
   - worker `sha256:9939c7b6d17d74dd0b15764cce1b1b621dcfa74b06a2fe8cd466e74a4255c450`
5. 운영 prefix/설치 pin·service·source/실패 이력·카카오 브라우저/인증·GPU/슬롯/벡터는
   변경하지 않았다. 다음은 기존 export owner의 저장 profile/결과 계약과 공개 화면을 새 family에
   연결하고, 보존 CSV·사진·metadata를 기존 source 확인/질문 편집 흐름으로 재생하는 것이다.
   sample1 사진 미확보, provider 정합과 현행 turn 후보 경계의 한계는 그대로 표시한다.
   선택적 교재 보강 편집/근거 선택과 실제 한 방→전체 방 주기 수집도 여전히 남아 있다.

## 2026-11-17 역할별 실제 PDF 출력 구현 — 운영 비활성

질문1쪽→조교 사진/답변/기록 정보→관련 개념 쪽의 결정론적 출력을 기존 PDF worker에
연결했다. 기존 v1 page writer·font readback·EXIF/transform·로컬 member/hash 검증을 재사용하며
source 역할 추정·NAS 쓰기·AI 호출은 없다. 새 CLI는 exact study schema family만 선택한다.
고정 실행기·출력 profile·저장/API/Web에는 아직 활성 연결하지 않았다. 새 수집·실제 카카오
사진 정합·전체 방 주기 실행/Studio PDF 완료가 아니며 전체 goal도 미완료다.

- JSON Schema2020-12 `worker-study-layout-v1`을 behavior보다 먼저 정의했다.
  SHA는 `sha256:b2cb10bed3940628cd651e2c37d43eb461d2a0b3effa24217d6ec74acce615fd`다.
  원문 offset 범위가 연속으로 전체를 덮는지, 사진 use·순서·pin·geometry/최소 크기를 core가
  검사한다. 학생 질문은1쪽, 긴 답변/보강은11pt로 넘기며 무단 crop/원문 삭제는 하지 않는다.
- 새/기존 관련 source253개 PASS, strict mypy7개·Ruff/format·diff 검사 PASS다. 첫 import의
  공개 type 경로 오류와 불가능한 input order를 양성 fixture로 만든 오류는 개발 검증에서
  수정했고 최종 전체를 다시 실행했다. 운영/이전 실패 이력은 변경하지 않았다.
  wire audit는1480 canonical/1125 mirror/12796 refs다. DB/schema 변경이 없어 이번에는
  새 DB mutation·임시 DB 재실행을 하지 않았으며, 이전 저장/HTTP 검증을 새 출력 PASS로
  재해석하지 않는다.
- 새 contracts wheel `sha256:655e59470209f29b0d044a35740bece903128687f1181c10b56faec414ab3fb7`,
  worker wheel `sha256:ff0a6d217f37738e7288a36272ca5dab2eacb90457ebb5f76893a6b469665712`를
  별도 non-editable venv에 설치했다. source 없는 `python -I -B`, 전체 wheel/설치 RECORD,
  Catalog/SQLAlchemy 부재·`pip check`를 확인하고 실제 설치 Noto font로5쪽 PDF를 만들었다.
  질문1쪽·학생/조교 사진 각각1회·긴 답변/metadata·직접 작성 보강 쪽, 원문 범위·모든 output
  SHA가 PASS다. PNG3쪽을 직접 보았으며 합성 사례 검수이지 실제 카카오 acceptance가 아니다.
  격리 증거는 `/tmp/eom-kakao-study-render.25kXMGQx/result.json`이다. 운영 설치본은 바꾸지 않았다.
- 샘플1번은 CSV 첫 행에 사진 표식이 있으며 받은 사진2건에는 해당 사진이 없다.
  **원래 사진 없음이 아니라 미수집/미확보**다. 재다운로드 가능/삭제 여부는 미확인이다.
  상세 대조와 후속 자동 코드 샘플 요구는
  [반복 출력 점검](../architecture/KAKAO_ARCHIVE_REPEATABLE_OUTPUT_AUDIT.md#첫-질문-사진-재확인--2026-11-17)에 기록했다.
- 다음은 기존 materialization/executor/publication의 family 연결과 저장된 CSV·사진·metadata의
  재생 PDF다. 수동 질문 행 선택/사진 내용 대조를 자동 수집 완료로 취급하지 않는다.
  실제 카카오 재로그인/클릭·메시지 전송·운영 service 재시작·GPU/슬롯/벡터 변경은 없었다.

## 2026-11-17 역할·시각 보존 후속 입력의 source 연결 — 운영 비활성

source `e53ae0cbdb7306130f31ff21a8781a67b132fca8`를 커밋·푸시했다. 새 pure-contract wheel
SHA는 `sha256:1f2de8a4a3cf2e2a37f11b06b45372bedce0dedd429874955b86136d7cc1883d`다.
별도 `/tmp/eom-kakao-study-wheel.9VoVCIF6/venv`의 source 없는 `python -I`에서 새 module과
packaged schema·전체 RECORD·합성 metadata 읽기가 통과했다. Catalog/SQLAlchemy가 없는
격리 PDF 설치본을 기반으로 했고 `pip check`도 통과했다. 같은0.1.0인 parent 설치본 때문에
첫 후보 설치가 skip된 것은 import/location 검사에서 거부됐으며, **별도 후보 venv에만**
명시 설치해 다시 확인했다. 운영 prefix는 바꾸지 않았다. 결과는
`staging/kakao-study-installed-e53ae0cb.json`이며 실제 PDF render/운영 활성화 증거는 아니다.

1. 샘플의 수동 행/사진 선택을 운영 기능으로 복사하지 않고, 기존 exact packet/student/source
   해석을 공통 owner로 분리했다. 새 `project_kakao_student_study`는 같은 저장 원본에서 학생/
   조교 본문과 사진을 나누며 message occurrence·kind·raw date·timezone·UTC를 보존한다.
   답변 포함 여부는 기존 packet 선택을 따른다. 새 채널/학생/날짜·CSV 행 번호 하드코딩은 없다.
2. JSON Schema2020-12 `worker-study-render-v1`과 frozen DTO를 먼저 정의했다. 기존 v1의
   schema bytes는 그대로이며 member·image·content/terminal closure 규칙을 재사용한다.
   source role/metadata의 exact membership·시각 불일치·없는 source/image·다른 학생·같은 binary의
   독립 photo use·중복 member/경로 충돌을 검증한다. 교재 표시 citation은 검색 권한이 아니다.
3. 일반 질문/답변은 study revision 없이 투영할 수 있지만, 보강 block은 저장한 자료 revision을
   요구한다. 이번 source projection은 임의 note/citation 입력을 받지 않는다. 실제 저장/근거
   owner와 worker 실행을 연결하기 전에 모델 출력이나 사용자 원고를 교재 근거로 수락하지 않는다.
4. predecessor 정의의 닫힌 in-memory schema registry에 기존 jsonschema의 설치 의존인
   `referencing>=0.37,<0.38`을 명시했다. API/격리 PDF에 이미0.37.0이 있으며 이번 작업에서
   운영 package 설치·업그레이드는 하지 않았다. schema의 네트워크 조회와 Git fallback은 없다.
5. 새 순수 계약/projection29개와 기존 v1 관련136개 회귀가 각각 통과했고, 문맥·package 검증을
   포함한 최종 source 묶음188 PASS다. 겹치는 수치는 합산하지 않는다. 공식 guarded
   임시 PostgreSQL에서는 기존 HTTP→질문→packet→PDF/file GET과 저장된 학생 subset의
   후속 projection/재구성 검증을 포함해274 PASS다. 운영 DB를 테스트하지 않았다.
   strict mypy5개·Ruff/format과 wire audit1479 canonical/1124 mirror/12785 refs도 통과했다.
6. **새 family의 고정 worker entry/renderer·export profile·API/Web·개념 편집은 아직 미연결**이다.
   이 source 경계를 실제 사용자 새 PDF나 전체 자동화 성공으로 표시하지 않는다. 이번 turn에는
   운영 service 재시작·카카오 조작·원문/실패 이력·GPU/벡터 변경이나 AI 실행을 하지 않았다.
   다음은 이 typed 입력을 기존 PDF 엔진의 질문/답변/보강 쪽 출력으로 연결하는 것이다.

## 2026-11-17 반복 자동화 점검 — 샘플의 수작업을 완료로 세지 않음

사용자가 일회성 개발 에이전트 판단을 반복 기능으로 오인하지 않도록 점검을 요청했다.
[점검 문서](../architecture/KAKAO_ARCHIVE_REPEATABLE_OUTPUT_AUDIT.md)에 실제 source와
샘플을 대조해 수동 사진 연결·질문 행 선택·답변/metadata 보고 조립·미연결 교재 보강을
분리했다. 샘플은 실제6쪽 결과지만 공식 Studio export나 완전 자동화 완료가 아니다.

기존 turn_v1에서 답변 뒤 감사 인사와 며칠 뒤 질문이 같은 후보에 들어가 기간 선택이
달라질 수 있음을 익명 fixture로 재현했다. 현행 released 규칙을 바꾸지 않고 한계 회귀를
남겼으며 관련47개 검사가 통과했다. 다음은 기존 source owner의 실제 role/사진 정합과
얇은 successor의 여섯 구성 편집/출력 연결이다. 학생/원본·실패 이력·GPU는 변경하지 않았다.

## 2026-11-17 보호 PDF 검증 완료·실제 수신 자료 샘플

1. source `76032729af2d80e2457906b7cdee6b78de2b3cd1`의 PDF worker wheel
   `sha256:2b60819f4f2d8660ab980da737600e097e98615a472e33fe7e2585f5741d419e`를 offline/no-deps로
   설치하고 Catalog와 renderer의 release pin을 함께 반영했다. API/Web/QUERY는f34e50cc
   설치본을 유지한다. 새 DB/migration·브라우저/원격 화면·인증·GPU 변경은 없다.
   설치 기록은 `/var/lib/eom-kakao-pdf-readback-76032729/installed.json`이다.
2. 실제 Noto glyph의 ToUnicode 역매핑을 개별 문자 목록 대신 exact nonzero glyph ID로
   검증한다. 원문 codepoint와 layout coverage는 그대로다. 관련152개 회귀, Ruff/format,
   strict mypy, 별도 non-editable 설치본의 실제 Noto/ellipsis/Jamo PDF가 통과했다.
3. 이전 합성2질문·사진2개의 worker는 정상 출력했다. 검증 프로그램의 잘못된 primary GID와
   NBSP substring assertion 때문에 후처리만 실패했고, 같은 정지 attempt의 accepted 결과를
   올바른 shared GID로 재검증했다. **새 렌더 없이 같은 bytes 재수락·중복 dispatch 거부 PASS**다.
   원래 exit2/INVALID_INPUT·개발 검증 실패 로그는 보존했다.
4. 사용자 요청으로 retained CSV1개·JPEG2개를 기존 Orchestrator reader로 다시 확인했다.
   기존 원본을 바꾸거나 source admission/학생 등록을 만들지 않았다. 수신10행에서 수동으로
   고른 질문3묶음을 전용 UID/고정 systemd sandbox로3쪽 렌더했다. 사진2장 무crop,
   input/output hash·같은 결과 복구·중복 실행 거부 PASS다. 일반 source owner의 수락이나
   provider 사진 occurrence 정합, Studio 다운로드 완료로 보고하지 않는다.
5. core가 질문3쪽에 조교 답변 원문3쪽을 붙인 **6쪽 비공개 샘플 PDF**를 NAS에 보관했다.
   학생 소개는 표시에서 제외했고 원본 CSV는 보존한다. 질문/답변 원문, 사진, 시각 metadata를
   구분한다. 사진2장은 내용 직접 대조로 배치했고 첫 질문의 사진1장은 미확보다. CSV에
   조교 사진 표식은 없었다. 조교 원문의 오탈자·주장을 새 해설로 고치지 않았다.
   관련 교재 원문/캡처는 **아직 미포함**이며 자료에도 개념 보강 전으로 표시한다.
6. 정본 보고 파일은 `/mnt/nas/eom/user-deliverables/kakao-sample-20261117/`의
   `카카오_질문답변_샘플.pdf`, `미리보기.png`, `manifest.json`이다. file hash·6쪽/사진2장·
   답변의 실제 glyph readback과 무overflow를 확인하고 contact sheet도 직접 열어 확인했다.
   이는 사용자 요청 샘플이며 Catalog packet/export를 가장하지 않는다.
7. 개념 보강 Codex 프롬프트 초안을 별도 설계 문서에 작성했다. 학생/조교 사진, metadata,
   조교 원문과 새 설명, 승인 분석과 실제 원문 pixels를 구별한다. 현재 추천 worker/schema/
   프리셋·도구는 미활성이다. 수집/일반 PDF의 비AI 계약은 그대로다.
8. Catalog active·API READY 확인. INDEX는 기존 FAILED/Invocation
   `aada2a6ef82043e4a15ae68f6dd73f20` 그대로이며 이번 작업으로 복구했다고 하지 않는다.
   실제 새 방의 정합/수락→Studio PDF와 모든 방 주기 수집은 여전히 미완료다. 전체 goal은 유지한다.

## 2026-11-17 PDF 설정 반영과 실제 설치 폰트의 readback

- `186a2212f08e8a743ae28a899ef7724cbee844f1`을 커밋·푸시했다. private0755 template와
  Catalog 기대 hash를 함께 반영했다. systemd reload 응답20초가 만료됐지만 실제 reload는
  완료돼 있었고, 재설치를 반복하지 않고 파일/hash·NeedDaemonReload=no를 확인한 뒤
  중지된 Catalog만 다시 시작했다. Catalog active/socket·API READY와 기존 API/Web/QUERY,
  GPU INDEX Invocation·runtime/config 보존을 확인했다. 별도 관측 receipt는
  `/var/lib/eom-kakao-pdf-delta-186a2212/activation-observed.json`이다.
- 원래 worker exit2와 다른 **새 합성 attempt**
  `kakaoattempt_31d9262cef6d489c9bbda8809460d3c0`은 실제 전용 UID/systemd 실행을 마쳤으나
  `INVALID_INPUT / KAKAO_RENDER_TEXT_READBACK_MISMATCH`를 반환했다. 이를 성공 PDF로
  표시하거나 같은 attempt를 재실행하지 않았다. 실제 카카오 원본·DB/export는 사용하지 않았다.
- 설치 Noto CJK의 날짜 `-`가 같은 glyph인U+2011로 추출되는 것이 원인이다. source renderer의
  readback만 exact font의 이 두 문자 shared nonzero glyph에 한해 허용하도록 고쳤다.
  수학 minus·본문 변경·누락·중복 거부 회귀와 관련137개 검증, strict mypy가 통과했다.
  실제 설치 Noto bytes를 입력한 source PDF2쪽/사진2개도 통과했다. **새 worker wheel의
  보호 설치·새 합성 attempt·중복 없는 재수락은 아직 다음 단계**다. 합성/source PASS를
  실제 카카오나 최종 사용자 PDF 완료로 확대하지 않는다.

## 2026-11-17 재로그인 없는 보호 PDF 검증에서 확인한 실행 경계

- 기존 활성 PDF template와 전용 Catalog/renderer UID로 합성 질문2개·사진2개의 첫 실제
  systemd 실행을 했다. 실제 카카오/DB/export 생성은 아니며, `kakaoattempt_b1659d84b46a4985b0a406eca4dae894`
  는 worker exit2로 실패해 그대로 보존했다. 동일 실패 attempt를 다시 렌더하거나 성공으로 바꾸지 않았다.
- 그 전에 보호 준비 프로그램의 PIL import가 실패했고, 실제 `python -I` 사진 inspector도
  `KAKAO_ARCHIVE_MEDIA_DECODER_UNAVAILABLE`이었다. 이미 선언된 Pillow11.3.0이 API/Catalog
  환경 lock/설치에 없었던 것이다. 기존 승인 wheel SHA
  `sha256:676b2815362456b5b3216b4fd5bd89d362100dc6f4945154ff172e206a22c024`만 사용해 별도
  설치 후보에서 검증한 뒤 해당 단일 의존성을 반영했다. 다른 package 업그레이드·서비스
  재시작은 없었고 실제 `-I` PNG/JPEG/WebP inspector와 `pip check`, 관련44개 회귀가 통과했다.
- 첫 PDF 실패는 읽기 전용 namespace probe로 원인을 분리했다. 실제 worker UID975/GID970/
  groups970에서 parent0711은 direct input open=true지만 descriptor walk=false였다.
  같은 격리의0755 후보에서는 둘 다true, NAS·secret·source·Catalog state·AF_INET 차단과
  실제 host에 만든 synthetic peer directory의 namespace 비노출이 모두true다.
  진단은 FAILED input을 읽기만 했으며 원래 output에 쓰지 않았다.
- source template를 private read-only0755로 맞추고 공동 권한 계약을 회귀로 추가했다.
  격리 해제·worker group 추가·descriptor 안전 검사 우회는 없다. 현재 이 template 수정은
  운영 미반영이며 새 hash/Catalog pin의 paired 설치와 새 합성 attempt 검증이 다음 단계다.
- 보존 증거는 `staging/kakao-pdf-protected-*20261117.log`,
  `staging/kakao-pdf-permission-probe-v[12]*20261117.log`와 root-private
  `/var/lib/eom-kakao-pdf-check-20261117`다. 학생/교재 원본·카카오 로그인·GPU는 건드리지 않았다.

## 2026-11-17 사용자 추가 요구 — 개념 보강·편집 자료

사용자가 단순 PDF 보관을 넘어 관련 개념 교재의 근거/캡처와 Codex 추천, 자료 편집을
요청했다. 두 확인 답변은 **Studio 편집 후 PDF**와 **질문1쪽+필요한 개념 추가쪽**이다.
HWPX를 새로 만드는 범위는 아니다. 원문/일반 PDF와 보강 자료 revision을 구별한다.

후속 [설계](../architecture/KAKAO_QUESTION_STUDY_PACKET_DESIGN.md)에 경계·11항 설계 계약·
단계/검증을 기록했다. 수집·질문 구성은 기존 비AI이며 새 선택적 개념 추천에만 공유 Codex
슬롯과 실제 기존 GraphRAG를 사용한다. 교재 원문 pixels/쪽수를 확인하지 않고 분석 텍스트를
캡처 근거로 꾸미지 않는다. 현재 이 확장의 schema/DB/worker/운영 활성화는 아직 없다.
기존 전체 방 주기 수집 목표를 축소하거나 실제 카카오 검증을 대체하지 않는다.

## 2026-11-17 02:59 UTC 원본 후보 화면·저장 연결 운영 반영

1. source `f34e50ccd35d9920d88bc978492636e3dc817ac0`를 커밋·푸시하고 API/Catalog/platform/
   QUERY owner·Web의 같은 source 호환 release로 설치했다. 아래 후보→기존 저장/PDF의
   합성273개 임시 DB 검증을 유지한다. actual selector나 source 수락을 이 설치가 승인하지 않는다.
2. clean source의 API4-wheel/RECORD와 Web offline closure·service identity105개 파일·
   source-isolated 설치 검증 PASS다. API 후보는
   `/tmp/eom-api-build/f34e50ccd35d9920d88bc978492636e3dc817ac0.UpOtd3/dist`, Web 후보는
   `/tmp/eom-web-gui-build/f34e50ccd35d9920d88bc978492636e3dc817ac0.DTeVxj/dist`다.
   protected ADMIT·MIGRATION_VERIFY_0093·API_ISOLATION_VERIFY와 설치 member/hash 검사를
   통과했다. DB는0093 그대로이며 upgrade/downgrade나 테스트를 운영 DB에 실행하지 않았다.
3. Web을 명시적으로 재시작하고 source build-info의 API/Web 일치, HTTPS 로그인200·API
   READY200, 새 후보·상위 JS의 source/HTTP SHA 일치, 새 후보 경로의 비로그인401을 확인했다.
   후보 JS SHA는 `sha256:133a647bda3223f7c7f3a63af76f36322a03125c53bbc224f0ac3e7571115798`다.
   이 검증은 실제 사용자 질문 저장/PDF나 실제 카카오 수집의 성공 증거가 아니다.
4. 기존 인증을 재사용해 추가 비밀번호 요청 없이 설치했다. 기존 creative producer는
   지원된 SIGINT drain 후 정상 재시작했다. API/Web/Catalog/QUERY/chat/creative는 active다.
   카카오 browser/remote와 collector 설치본·인증정보는 그대로다. GPU INDEX의 배포 전
   FAILED/Invocation·수치 runtime/config도 보존했다. 원본·수동 편집·실패 기록을 변경하지 않았다.
5. **MANUAL 유지·AUTO 비활성**이다. 실제 새 한 방의 CSV·사진 occurrence→학생 PDF와
   전체 방의 누락 없는 주기 수집은 여전히 미완료다. 이미 요청한 카카오 연결 재개를 기다리며,
   새로운 source 사실을 합성 시험이나 이름으로 추정하지 않는다. 전체 goal은 완료하지 않는다.
6. 배포 증거는 `/var/lib/eom-kakao-capture-release-f34e50cc/{stage.json,api/activated.json}`와
   `staging/kakao-capture-*-f34e50cc.log`다. 기존66e28b36 호환 설치본과 before config를
   rollback 근거로 보존했다. 다음 실증은 실제 방의 새 관측에서 시작한다.

## 2026-11-17 수락 원본의 질문 후보 → 기존 저장/PDF 연결

1. **이번 source 범위:** 선택한 방의 수락 원본에서 질문 후보를 찾고, 기존 CREATE API로
   저장·열람한다. 후보 번호·짧은 원문 미리보기·학생/답변/사진 수·저장 여부를 표시한다.
   학생이 연결된 방만 화면에서 저장하며 이미 나누거나 합친 origin은 다시 등록하지 않는다.
   사진 다운로드·카카오 수집·capability 확인을 이 버튼이 대신하지 않는다.
2. **기존 구조:** 순수 후보 규칙과 원본/질문 owner, API-peer socket·API·BFF, 기존 Artifact/
   CREATE 멱등·origin unique·CAS를 재사용했다. 새 DB/migration/queue/worker/cache/AI/의존성은
   없다. 기존 순수 `question-candidates-v1`과 공개 페이지의 이름 충돌을 정리해 전자는 원래
   bytes를 보존하고 additive `question-candidate-page-v1`을 따로 정의했다.
3. **원본/복구:** 최초 current selection 이후 exact source revision/hash와 mapping을 고정한다.
   실패 뒤 재조회도 pin을 유지하며, 다음 페이지에 source pin이 없으면 거부한다. 빈 방은
   원본 없음으로 표시하고, 미확정 원문 순서는 explicit409다. 같은 flat CREATE의 정렬된
   필드로 key를 정해 새로고침·응답 유실 뒤에도 원 요청을 재사용한다. 저장 성공 뒤 화면
   열기 실패는 같은 저장을 다시 하지 않는다. READ+EDIT·owner/source 권한을 I/O 뒤 재확인한다.
4. **합성 실증:** 실제 BFF→API→socket→guarded PostgreSQL에서 조회 자체의 무변경,
   저장/replay·분할된 origin의 재등록 거부·서비스 재구성 뒤 읽기, 새 source 수락 뒤에도
   옛 pin 유지, 없는 source의 latest 대체 없음, late session 철회와 빈 방을 확인했다.
   기존 Studio HTTP 출력 시험도 후보 조회에서 시작하도록 보강해 합성 CSV/사진2개→질문
   저장→packet→별도 로컬 렌더 프로세스→학생 PDF 다운로드/같은 bytes 재조회까지 통과했다.
   이는 전용 UID sandbox나 실제 카카오 방의 성공으로 확대하지 않는다.
5. **브라우저:** 실제 Chromium 합성 화면에서 유실 응답의 같은 key/body, reload 뒤 같은 key,
   저장 완료 후 열기만 재시도, 조회 실패 뒤 원본 pin 보존, 타 계정 늦은 응답 차단,
   textContent/XSS·390px·외부 요청 없음이 통과했다. 관련 source/API/BFF/Chromium/wheel104
   PASS, 최종 공식 임시 DB273 PASS(이전 반복272 PASS), OpenAPI/schema10 PASS,
   개발 문맥/API-peer44 PASS, Web 설치 경계15 PASS다. 겹치는 수치는 합산하지 않는다.
   핵심13개 strict mypy·Ruff/format, schema audit1478/1123/12727, OpenAPI 비파괴 비교 PASS다.
6. **운영/실제 계정:** 이번 변경은 아직 미배포이며 운영 source는66e28b36이다. 새 카카오
   로그인·다운로드·source 수락은 실행하지 않았다. 기존 비밀정보/실패 기록·문항·벡터를
   변경하지 않았다. 실제 한 방 사진 occurrence→PDF와 전체 방 주기 수집은 여전히 미완료다.
7. **다음:** 이 source의 clean build/설치 검증 후 공유 API·Web의 호환 release로 반영한다.
   사용자 원격 로그인 요청은 중복하지 않는다. 실제 화면에서 확인하지 않은 selector·사진
   대응을 승인된 사실로 만들지 않고 실제 새 관측을 받아 한 방의 전체 경로를 실증한다.

## 2026-11-17 02:13 UTC 문장 내부 나누기 호환 운영 반영

1. source `66e28b36919b33179ca0af85fe615cbb51fcdc7d`를 커밋·푸시했다. 동일 source의 API/
   Catalog/platform/QUERY owner와 Web을 호환 묶음으로 설치했다. collector/browser는 기존
   eda2a1b0 설치본을 유지한다. 새 DB migration은 없고 실제0093 확인만 수행했다.
2. 공식 API4-wheel/RECORD 검사, Web offline closure·service identity104개 파일·source-isolated
   설치 검사 PASS다. API 후보는 `/tmp/eom-api-build/66e28b36919b33179ca0af85fe615cbb51fcdc7d.aR6kLM/dist`,
   Web 후보는 `/tmp/eom-web-gui-build/66e28b36919b33179ca0af85fe615cbb51fcdc7d.qoS89n/dist`다.
   실제 protected operator ADMIT·MIGRATION_VERIFY_0093·API_ISOLATION_VERIFY가 통과했고,
   API 설치 member/hash와 기존 QUERY 수치 runtime/config 보존을 확인했다.
3. Web installer 뒤 Web 프로세스를 명시적으로 재시작했다. 새 MainPID/start 시각,
   API/Web build-info의 source 일치, 실제 HTTPS 로그인200과 새 JS SHA
   `sha256:81b8a67680c8f7a636e2f3f6f7962b4ef7bb54fc32b87648d1e885fb36e6010d`,
   새 edit-context 경로의 비로그인401을 확인했다. 이 검사들은 인증된 실제 질문 편집/PDF
   성공을 대체하지 않는다. 이번 배포에 추가 로그인이나 비밀번호 변경은 없었다.
4. 원래 실행0 확인 후 creative producer를 지원된 SIGINT로 drain했고 배포 뒤 다시 시작했다.
   API/Web/Catalog/QUERY/chat/creative는 active다. 기존 GPU INDEX는 배포 전부터 FAILED이며
   같은 Invocation·설정 pin을 보존했다. 이번 Kakao 배포로 정상화했다고 보고하지 않는다.
5. 실제 카카오 browser/remote는 inactive이며 새 계정 수집을 하지 않았다. 원래 CSV/JPEG와
   모든 실패 기록을 보존했다. **MANUAL은 유지, AUTO는 비활성**이다. 실제 한 방의 새 관측/
   CSV·사진 occurrence 연결→학생 PDF와 전체 방의 누락 없는 주기 수집은 여전히 미완료다.
6. 배포 증거는 `/var/lib/eom-kakao-capture-release-66e28b36/{stage.json,api/activated.json}`와
   `staging/kakao-capture-*-66e28b36.log`다. 기존0093 호환 release와 before config를 rollback
   근거로 보존한다. 사용자에게 이미 보낸 원격 로그인 요청을 중복 생성하지 않고 실제 관측을
   받은 뒤 다음 수직 경로를 이어간다. 전용 Codex 수집 슬롯/프롬프트는 추가하지 않는다.

## 2026-11-17 문장 내부 나누기 공개 연결 — 소스 검증

1. **사용 가능해질 범위:** 기존 질문 편집에서 `문장 안에서 나누기`를 열고 커서 위치를
   지정해 하나의 메시지를 여러 질문으로 저장한다. 기존 메시지/사진 사이 나누기·병합·확인/
   제외는 유지한다. 분할은 새 질문 revision이며 원문과 기존 packet은 덮지 않는다.
2. **구조:** 기존 reads/compose owner와 API-peer·API·BFF를 재사용했다. released 질문 v1
   bytes를 보존하고 exact revision의 원문 span만 읽는 작은 additive 계약을 먼저 정의했다.
   현재 READ+EDIT·owner·source lifecycle/hash를 다시 확인한다. DB migration, 새로운 queue/
   worker/AI/외부 의존성은 없다. 표시문 교정 UI까지 완료했다고 주장하지 않는다.
3. **검증:** 실제 Chromium 합성 입력에서 이모지·조합 한글·CRLF 원문을 보존하며 나누기,
   원문 offset이0이 아닌 재분할, 응답 유실의 같은 key/body 재확인, stale version/타 계정
   늦은 응답 차단과390px 화면을 확인했다. 임시 PostgreSQL의 실제 BFF→API→socket→owner
   경로에서 저장·서비스 재구성 뒤 읽기·중복 없음·권한 철회를 확인했다. 일반 READ-only 및
   EDIT-only 계정의 context 거부도 통과했다. 최종 공식 임시 DB suite269 PASS, 앞선 반복268
   PASS다. API/BFF·계약·실제 Chromium·offline wheel 회귀148 PASS, OpenAPI/schema audit
   회귀10 PASS, 개발 문맥13 PASS, 핵심11개 strict mypy·Ruff/format·shell syntax PASS다.
   schema audit1477 canonical/1122 mirror/12720 reference, 기존 OpenAPI 비파괴 비교 PASS다.
   겹치는 suite 수치는 합산하지 않는다. 기존 Starlette 경고1개는 유지하며 운영 DB에는
   테스트하지 않았다.
4. **발견/수정:** 새 OpenAPI의 permission 선언은 기존 프레임워크대로 한 개(EDIT)만 두고
   READ는 기존 source owner에서 계속 강제했다. 이 선언 중복의 fixture 초기화 오류를
   운영 장애로 기록하지 않는다. 반복 임시 DB 검사에서 테스트용 custom role이 seed 검사에
   섞이는 것을 발견해 해당 역할을 finally에서 정확히 정리하고 bootstrap 검사는 built-in
   grant만 확인하도록 고쳤다. 운영 RBAC를 변경하거나 검사를 끄지 않았다.
5. **운영/실제 계정:** 이번 확장은 아직 소스 변경이며 운영은 아래01:12 UTC 호환 release다.
   실제 browser/remote는 inactive임을 확인했다. 카카오 로그인·추가 다운로드·사진 대응·학생
   PDF 실증은 수행하지 않았고, 옛 수신물의 없는 관측을 소급 생성하지 않았다. AUTO는 비활성이다.
6. **다음:** 같은 clean source의 설치 wheel 검증과 호환 릴리스 준비를 한다. 실제 한 방
   CSV/사진 occurrence→학생 PDF와 전체 방/주기 실행은 여전히 미완료다. 사용자 로그인 요청은
   이미 전달했으며 중복 요청하지 않았다. 코드 중심 수집/Codex 개발·진단 결정을 유지한다.

## 2026-11-17 01:12 UTC 수신 자료 확인 경로 운영 반영

1. **이번 운영 범위:** API/Catalog/platform/QUERY 공유 owner는
   `eda2a1b084e95d848fea7e9369b126df21cf6b93`, Web은
   `1da58229277f5908fa4737156a4ce89207d55b18`이다. 기존 protected operator1.28에서
   실제0087→0093 migration, exact-head verify, API/Catalog/HWPX role 갱신을 통과했다.
  4개 wheel의 설치 member를 대조했으며 source checkout을 runtime에 연결하지 않았다.
   공개 수신 목록/명시적 방 확인 저장이 새 화면·API에 연결됐지만 실제 계정 성공은 아래와 구분한다.
2. **검증:** 앞의 source/임시 DB/실제 Chromium 합성 PASS를 유지한다. 운영에서는
   `API_ISOLATION_VERIFY`, API READY, HTTPS 로그인 페이지200, 실제 새 JS의 SHA와 설치본
   일치, 새 수신 목록 경로의 비로그인401을 확인했다. Web104개 파일의 service-identity/
   RECORD·offline closure 검사도 통과했다. 이 검사들은 인증된 방 저장·PDF 성공의 대체가 아니다.
3. **실제 계정:** 이번에는 새 카카오 로그인·수집·사진 연결·PDF를 실행하지 않았다. 기존 CSV/
   JPEG3건과 실패 이력·인증정보는 보존했다. DOM 관측이 없는 옛 자료를 새 방 근거로 만들지 않는다.
   실제 한 방의 최신 관측과 학생별 PDF, 전체 방 inventory/주기 실행은 아직 미완료다.
4. **수신부 후속:** source0c65a608의 event-path guard까지 포함한 같은 source의 collector/
   pure contracts를, MANUAL·remote가 실제 종료되고 profile flock을 확보한 상태에서 갱신했다.
   공식 installer의 stage/verify·runtime/payload fingerprint·wheel parity·pip check와
   실제 설치 함수의 `event_path` signature 확인이 통과했다. 수신부 source 회귀96 PASS와
   별도 opt-in 익명 실제 Chromium2 PASS, source-isolated wheel 검사 PASS다.
   실제 카카오 방에 대한 selector/사진 정합을 검증한 것은 아니며 AUTO는 계속 비활성이다.
5. **발견/수정:** Web 공식 installer는 파일 설치/검증까지만 담당한다. 이번 운영 instance에서
   설치 뒤 프로세스 재시작을 빠뜨려 새 JS는200인데 새 HTTP 경로가404인 상태를 발견했다.
   재설치하지 않고 Web만 정상 재시작해 새 MainPID/start 시각과 같은 경로401을 확인했다.
   이후 checkpoint는 파일 SHA만으로 화면 활성화를 선언하지 않고 실제 새 route를 확인한다.
6. **기존 작업과 다음:** 접수 중 worker/command/chat0, 수치/HWPX transient 없음 확인 후
   기존 creative producer에 지원된 SIGINT drain을 요청해 정상 종료하고 배포 뒤 다시 시작했다.
   API/Web/Catalog/QUERY/creative는 현재 active다. INDEX는 배포 **전부터 FAILED/MainPID0**였고
   같은 Invocation과 설정 hash를 보존했다. 이를 배포 성공으로 정상화하거나 재개하지 않았다.
   사용자가 Studio에서 기존 연결의 원격 로그인을 준비하고 방 하나를 열도록 한 번 요청했다.
   해당 실제 관측을 받은 뒤 CSV/사진→질문→학생 PDF 검증을 이어간다. 전체 goal은 미완료다.

배포 증거는 기존 root-private owner 형식을 사용한다.
`/var/lib/eom-kakao-capture-release-eda2a1b0/{stage.json,api/activated.json}`와
`/var/lib/eom-kakao-navigation-guard-release-eda2a1b0/installed.json`에 저장했고, 비밀 없는
개발 실행 로그는 `staging/kakao-capture-*-eda2a1b0.log` /
`staging/kakao-navigation-release-eda2a1b0.log`다. 대화 원문·사진·프로필/인증정보는 Git/Slack에 넣지 않는다.

## 2026-11-17 운영 설치 전0093 호환 callback 준비

- 기존 protected release operator에 context/admission1.28을 추가했다.1.27 schema bytes/hash는
  바꾸지 않았다.4개 wheel·source/runtime fingerprint·installed payload 검증을 그대로 사용한다.
  callback은 정확한0087→0093 upgrade와0093 verify뿐이며 중간/다른 revision을 추측해 이어가지 않는다.
  이미0093이면 같은 요청의 확인은 no-op다. 배포 shell의 사전 검사도 source head0093과 맞췄다.
- 전체 release operator·schema audit 회귀 **448 PASS**, strict mypy·Ruff/format·shell syntax
  PASS다. 임시 DB의 공식 `migrate`는 **0093→0092→0093** 왕복과 composed metadata PASS다.
  callback predecessor 검사는 fake engine의 명시적 단위 검증이며, 이것을 실제 운영0087→0093
  migration 성공으로 보고하지 않는다. 이전262개 임시 DB owner/동시성 검증은 별도다.
- 새 DB migration이나 일반 실행 명령을 추가하지 않았고, 운영 DB/schema·API/Web/collector·
  GPU INDEX/QUERY·카카오 profile·인증정보에는 변경이 없다. 실제 배포에는 현재 설치 상태와
  실행 중 작업을 확인하고 기존 protected operator staging/정지/복구 절차를 따라야 한다.
  새 수집 기능을 배포하더라도 실제 selector/capability가 검증되기 전 AUTO는 비활성이다.

## 2026-11-17 Studio 수신 자료 목록 → 방 확인 저장

- 최근 MANUAL 세션의 수신 receipt를 `일반 → KakaoTalk`에서 조회하고, 사용자가 채널·방을
  명시적으로 확인한 항목을 기존 `KakaoRoomIntakeService`로 저장하는 경로를 연결했다.
  실제 BFF → API → API-peer 전용 Catalog socket → application owner → PostgreSQL을
  익명 합성 입력으로 검증했다. 목록은 최근8개 세션/전체50건, 세션당 directory entry1,000개
  상한이며 잘린 목록을 표시한다. GET은 사진·CSV payload를 읽거나 카카오를 조작하지 않는다.
- schema/mirror를 먼저 정의했고 공개 DTO에는 URL/provider key/파일 경로/원본 파일명/DOM/
  인증정보를 넣지 않았다. preview SHA는 원래 receipt/관측/owner/binding/lease/capture를
  고정할 뿐 실행 권한이 아니다. 현재 ADMIN/COLLECT·owner·binding과 원래 fence/관측을
  I/O 뒤에도 다시 검사한다. 기존 room proof/Artifact와 admission을 재사용하며 새 테이블,
  migration, queue, cache, service, dependency 또는 Codex 슬롯은 추가하지 않았다.
- 확인 POST에서만 실제 payload를 읽어 검증한다. 완료 요청은 canonical proof를 읽으므로
  로컬 workspace가 제거된 뒤에도 원래 room과 receipt를 재조회한다. 같은 key의 다른 입력,
  stale preview/ETag, 확인란 false, 타 계정/late 권한 철회는 거부한다. CSRF 없이 저장하지 않는다.
  방 저장은 CSV/사진 source 수락·학생 연결·질문 생성·capability 승격·AUTO 시작과 다르다.
- 실제 headless Chromium의 합성 화면에서 응답 유실 뒤 동일 body/key 재확인·중복 저장 없음,
  새로고침 후 요청 재전송 없음, 다른 owner의 늦은 응답 차단, 390px 화면을 검증했다.
  기존 MANUAL download의 미완료/실패/보호 경로 검사도 유지한다. 과거 실제 수신3건은
  DOM 관측 도입 전 자료이므로 이 화면에서도 `NO_OBSERVATION`이며 방 근거를 소급 생성하지 않는다.
- 최종 guarded disposable PostgreSQL **262 PASS**(새 HTTP/owner7개 포함), 실제 Chromium/
  새 RPC/로컬 입력 회귀 **61 PASS**, room/collection 계약·offline platform wheel 회귀
  **141 PASS**다. 이 수치는 서로 겹치는 범위가 있으므로 합산하지 않는다. strict mypy15개,
  Ruff/format26개, shell syntax, OpenAPI 비파괴 비교와 schema audit1475/1121/12686 PASS다.
  기존 Starlette TestClient deprecation warning1건은 남는다. 운영 DB에 테스트하지 않았다.
- 개발 중 HTTP fixture의 중복 임시 디렉터리, browser fixture의 새 asset 누락, false 확인란이
  schema 예외로 빠지는 문제를 각각 fixture 재사용·asset 목록 정렬·명시적 입력 검증으로 수정했다.
  권한 guard나 immutable trigger를 끄지 않았으며 이 실패들을 실제 카카오 장애로 분류하지 않는다.
- **이번 체크포인트는 소스 검증이며 아직 운영 미반영**이다. source head0093과 기존 운영
  DB0087의 차이가 있으므로 기존0087 전용 release operator로 설치하지 않는다. 새 호환 release
  검토·설치본 검증 후 배포한다. 실제 browser/remote는 MainPID0·inactive·정상 종료를 확인했고
  새 로그인·카카오 클릭·메시지 전송·GPU INDEX/QUERY 변경을 하지 않았다.
- 다음은 호환 설치 준비와 새 실제 관측의 연결이다. 실제 한 방 CSV/사진 occurrence→학생 PDF,
  전체 방 inventory·selector·주기 실행은 아직 미완료이며 합성 PASS로 대체하지 않는다.
  실행 방식은 기존 고정 Playwright adapter, Codex는 개발/진단이라는 결정을 유지한다.
- `94b69842`의 API4-wheel/RECORD 검사와 push는 완료했다. 첫 Web wheel 검사는 새 JS는
  포함됐지만 Python DTO/route2개의 고정 파일 목록 누락으로 설치 전에 거부됐다. 두 파일을
  명시적 inventory에 추가하며 guard를 완화하지 않는다. 실패 빌드는 보존하고 수정 commit에서
  공식 Web build와 source-isolated 설치 검증을 다시 수행한다. 운영 설치는 실행하지 않았다.
- 수정 commit `1da58229277f5908fa4737156a4ce89207d55b18`은 push 완료다. 같은 source의
  API4-wheel/RECORD 검사와 Web offline dependency closure·RECORD·source-isolated104개 파일
  설치 검증이 PASS다. Web inventory/배포 회귀15개도 PASS다. API 후보는
  `/tmp/eom-api-build/1da58229277f5908fa4737156a4ce89207d55b18.H6IYqI/dist`, Web 후보는
  `/tmp/eom-web-gui-build/1da58229277f5908fa4737156a4ce89207d55b18.cRwOpT/dist`다.
  Web wheel SHA는 `sha256:1b9eb918759c19bb5a6bfa0f33053288523e1c6b8b9f698d5352d850acf0b600`.
  이는 설치 **시뮬레이션**이며 운영 배포·카카오 실제 방/PDF 검증을 뜻하지 않는다.

## 2026-11-16 collection command/result에서 기존 원본 등록으로 연결

- `collection-attempt-v1` schema/mirror를 먼저 정의하고 기존 room task와 RUNNING browser
  epoch에 최초 command/attempt/snapshot/normalization identity를 한 번 예약하는 owner를
  추가했다. DB0093의 한 테이블은 작은 metadata와 exact Artifact pointer만 보관한다.
  새 queue·scheduler·Codex 슬롯·외부 AI·provider selector는 추가하지 않았다.
- command/inventory와 기존 canonical capability를 Artifact owner로 읽어 확인한 뒤 현재
  권한·policy·adapter·profile fence를 다시 검사해 command를 고정한다. 파일 I/O는 DB lock
  밖이다. Browser owner와 실제 두 번째 use case가 생긴 동일 lock 순서를 application 함수로
  공유했으며 private module 호출이나 별도 AUTO lock을 만들지 않았다.
- 최종 pointer 점검에서 inventory를 command 파일 묶음에 같이 넣도록 한 최초 내부 연결을
  수정했다. inventory는 한 canonical Artifact로 보관하고 command에는 복사하지 않는다.
  DB에는 그 exact ID/revision/hash만 고정하며 같은 bytes의 다른 identity로 바꾸기도 거부한다.
  source 전용·운영 미적용0093을 이 형태로 정리해 임시 DB 왕복·회귀를 다시 수행했다.
- result/report의 계약·hash·원래 execution/room identity를 검증해 증거를 채택한다. 결과
  proof 수락만으로 원본·질문·run 완료를 표시하지 않는다. 기존 `KakaoSourceService`의
  mandatory callback을 실제 accepted attempt에 연결했고, 원본 owner가 CSV 재파싱·동일
  메시지 발생 수·사진 coverage·Artifact lifecycle을 검증하여 revision을 수락한 뒤에만
  task가 LOCAL_ACCEPTED다. source owner/worker C1의 기존 계약 bytes는 바꾸지 않았다.
- 실제 이 callback을 사용한 **익명 합성 CSV→accepted source revision→정확한 재조회**가
  통과했다. 같은 시각/이름/본문2행은 서로 다른 occurrence로 남고 같은 요청은 원래 revision을
  반환한다. 다른 계정/위조 fence는 거부한다. 동시 claim/result 수락, 다른 pointer로 실패
  바꾸기 거부, 정상 종료 후 늦은 결과 수락, I/O 중 권한 철회도 집중 임시 DB에서 검증했다.
  임의 no-op source authorizer로 이 연결의 성공을 대신하지 않았다.
- 첫 전체 DB 검사에서 기존244개 PASS/새7개 FAIL은 기존 browser harness가 MANUAL 종료용으로
  가상 UTC를 전진시킨 뒤 새 실제-clock owner를 즉시 부른 시간 불일치였다. source/DB의
  관측 시각 guard는 유지하고 이 integration fixture가 실제 시각에 맞도록 최대2초 미만
  동기화했다. 운영에서는 시계가 관측보다 뒤면 명시적 OBSERVATION_STALE이며 가짜 시각을
  만들지 않는다. 최종 검사 수와 package 검증은 아래 결과에 기록한다.
- 이번 실제 카카오 계정에서 새 방/CSV/사진을 수집하거나 PDF까지 검증한 것은 아니다.
  기존 실제 CSV·JPEG·FAILED 이력·인증정보는 그대로다. source의 현재 capability는 여전히
  미확인 CSV 순서·시간대·발신 역할을 UNKNOWN으로 보존한다. 이 값으로 질문 후보를 억지로
  만들어 전체 흐름 PASS로 표시하지 않았다. 실제 관측을 통한 capability 보강이 필요하다.
- **운영 미반영**이며 source admission은 read-only 기본 composition에 임의 활성화하지
  않았다. 공개 collection API/Studio 연결·실제 AUTO 시작/selector·권한 있는 현재 방 수집과
  사진 occurrence 정합→학생 PDF·전체 방/주기 수집은 남는다. source 저장의 성공을 목표
  완료로 간주하지 않는다. 기존 운영 DB0087·API/Web·GPU runtime pin은 변경하지 않았다.
- 검증 결과: 새 capture owner11개를 포함한 전체 guarded DB **255 PASS**,
  순수 계약/OS adapter/권한/의존성/문맥264 PASS,
  wire audit/실제 offline wheel inventory4 PASS, strict mypy5 source·Ruff/format·shell syntax
  PASS, guarded migration0093 적용→되돌림→재적용 PASS.
  기존 TestClient deprecation warning1건이다. 실제 browser/remote도 MainPID0·inactive·
  정상 종료를 확인했으며 새 로그인이나 카카오 조작은 수행하지 않았다.

## 2026-11-16 공용 profile gate·collection browser lifetime 저장 연결

- 기존 MANUAL과 같은 `kakao_profile_runtime` gate/advisory lock을 사용해 collection browser
  epoch를 예약·재조회하고, 실제 관측 뒤 RUNNING/STOPPING/CLOSED를 수락하는 owner를 추가했다.
  `collection-browser-v1` schema/mirror를 먼저 정의했고, worker 입력은 기존 ProfileFence와
  canonical hash를 그대로 재사용한다. DB0092에는 browser lifetime 한 테이블과 profile/run의
  exact current pointer만 추가했다. 별도 AUTO mutex·queue·runtime service는 만들지 않았다.
- 같은 run의 동시 예약은 같은 epoch이며, CLOSED/불명확한 실행의 재조회도 새 browser를
  만들지 않는다. 실제 callback은 lock 밖에서 실행하고 현재 version/fence·boot/invocation/
  PID/monotonic start를 다시 대조한다. 미확인 종료/timeout이면 profile을 반환하지 않는다.
  현재 owner/policy/adapter 권한은 공유 application 함수로 모아 두 기존 owner가 재사용한다.
  정지 cleanup은 권한 철회 뒤에도 접수된 exact epoch로 수행할 수 있다.
- MANUAL history의 profile FK와 binding FK를 분리해 같은 사용자가 실제 정지한 profile로
  다른 자기 연결을 고를 수 있게 했다. 과거 lease/수신 proof는 수정하지 않는다. 첫 DB 회귀의
  **239 PASS/1 FAIL**은 옛 profile assignment trigger가 이 전환을 여전히 막던 원인이었다.
  trigger를 제거하지 않고 owner/profile identity는 불변, binding만 STOPPED·새 fence의 새
  MANUAL/AUTO claim에서 바꿀 수 있게 좁혔다. active/새 fence 없음/다른 owner는 계속 거부한다.
- 기존 fixed OS adapter의 정확한 실행 관측·stop 후 재관측을 새 owner metadata로 반환하는
  Orchestrator adapter를 구현했다. 다른 invocation은 중지하지 않고, 실제 gateway가 예상과
  달리 살아 있으면 그 소유자의 정리 대상으로 남긴다. reboot/PRE_READY_FAILED/비정상 exit는
  성공으로 재해석하지 않으며 runtime error와 처음의 owner error를 보존한다. **새 browser
  start/selector는 이 adapter에 아직 없고, 실제 호스트에서 새 AUTO를 실행한 증거도 아니다.**
- 최종 guarded disposable PostgreSQL 회귀 **244 PASS**, source/계약/OS adapter 합성·권한/
  의존성/개발 문맥·offline installed wheel 회귀 **256 PASS**, strict mypy7 source·Ruff/format·
  shell syntax PASS다. 0092 적용→되돌림→재적용·ORM metadata 일치와 MANUAL/AUTO 경합,
  중복 관측·late 권한 철회·unknown stop·새 MANUAL 이후 old closure 재조회·실패 보존을 검증했다.
  개발 권한 검사의 옛 profile UPDATE 열 기대값1건도 새 current pointer/닫힌 binding 전환
  계약에 맞췄으며, table-wide UPDATE나 owner/command pin 수정 권한은 주지 않는다.
  기존 TestClient deprecation warning1건은 남는다. 운영 DB에는 pytest/migration을 하지 않았다.
- browser 이력이나 새 cross-binding history가 있는 DB의 downgrade는 먼저 검토를 요구하며,
  오래된 FK에 맞추려고 이력을 덮어쓰거나 지우지 않는다. 개발 문맥은 UI/PDF와 수집 실행으로
  나누어 기존 index 한도를 유지했고 runtime package/worker 입력에는 포함하지 않는다.
- **소스 검증이며 운영 미반영**이다. 운영 API/Catalog/Web·DB·GPU pins·실제 CSV/JPEG·
  FAILED 이력·인증정보를 바꾸지 않았다. 실제 browser/remote는 MainPID0·inactive·정상 종료다.
  실제 capture command/attempt와 source authority, 공개 collection API/Studio 연결, guarded
  activation·실제 방→학생 PDF·전체 방 주기 수집은 여전히 남아 있다. parent run은 예약/종료만으로
  COMPLETED가 되지 않으며 DRAFT/NOT_VERIFIED·AUTO 비활성도 유지한다. 목표는 미완료다.

## 2026-11-16 단일 방 collection 의도·재조회 저장 owner

- `collection-intent-v1` schema/mirror를 먼저 정의하고 `KakaoCollectionService`가 실제 현재
  API actor·ADMIN/READ/COLLECT, 수락된 방 capability proof와 설치 adapter pin을 확인해
  원래 policy/version·방·run identity를 고정하도록 연결했다. DB lock 밖에서 기존 capability
  owner의 파일 검증을 재사용하고, 마지막 transaction에서 권한·version을 다시 확인한다.
- DB0091의 작은 run/task 두 테이블에만 metadata를 저장한다. 같은 요청은 같은 run/task를
  돌려주고, 다른 key로 같은 연결에 unfinished run을 중복 접수하지 않는다. 상태 GET이나
  완료 접수 replay는 browser/파일 발행을 재실행하지 않는다. 최초 QUEUED 상태·첫 task의
  atomic adoption·원래 pin/순서·terminal/FAILED 불변성을 DB guard와 FK/unique로 보호한다.
  source bytes/사진·긴 JSON·NAS path·인증정보·새 queue/command bus는 추가하지 않았다.
- 기존 Identity의 현재 계정/permission 판정을 공통 함수로 추출해 public session 검증과
  저장된 run 준비가 같이 사용한다. public 요청은 계속 유효한 session이 필요하다. 내부
  준비는 owner를 실제 accepted row에서 읽으므로 API session 만료를 가짜 인증으로 우회하지
  않는다. 계정/role 철회·policy/adapter 변경·retired room/binding·terminal run은 새 준비를 거부한다.
  **준비 metadata는 actual profile/attempt fence나 source admission 권한이 아니다.**
- guarded disposable DB에서 same-key/다른-key 경합·저장 중 중단·원래 receipt 재조회·late
  권한 변경·세션 만료와 현재 role 철회·정책/adapter pin·다른 방 capability 거부·초기 task
  누락/불법 초기 성공·FAILED 보존을 확인했다. 실제 query plan의 partial unique index 사용
  가능성과 ORM/migration 일치도 검사했다. 0091 적용→되돌림→재적용은 이 임시 DB에서만 수행했다.
- PDF optional import 수정 이후의 최종 guarded DB 전체 회귀는 **223 PASS**다. 기존
  TestClient deprecation warning1건은 별도 의존성 교체 없이 그대로 기록한다. 운영 DB나 실제
  카카오 계정·원문을 이 persistence 테스트에 사용하지 않았다.
- schema/pure/권한/의존성/개발 문맥·실제 offline wheel inventory/설치 import **85 PASS**,
  strict mypy5 source·Ruff/format·shell syntax PASS다. 개발 문맥 index의 source/test 경로를
  추가하며 각각40개 한도를 넘긴 두 실패는 하위 helper 항목을 note에 남기고 index를 간추려
  해결했다. schema 한도를 늘리거나 검사 자체를 제거하지 않았다.
- wheel 회귀에서 선택 Kakao runtime을 차단하면 기존 PDF application의 annotation-only
  export import가 core Catalog 시작을 막는 결함을 발견했다. `TYPE_CHECKING`/지연 annotation으로
  바꾸고 실제 기능 활성화 import는 기존 composition에 그대로 뒀다. worker/Pillow/Playwright가
  없는 installed core import를 다시 통과했으며, 새 dependency나 가짜 fallback은 추가하지 않았다.
- **소스 검증이며 운영 미반영**이다. 공개 collection RPC/API/Studio 시작 버튼, 공용 profile
  AUTO claim/실제 epoch·attempt, source 권한·실제 방→학생 PDF, 전체 방/주기 실행은 남아 있다.
  DRAFT/NOT_VERIFIED·AUTO 비활성은 그대로이며 이번 작업으로 실제 카카오 수집 성공을 주장하지
  않는다. 운영 API/Catalog/Web·DB·GPU pins, 실제 수신물·FAILED 이력·사용자 인증정보는 변경하지
  않았다. 실제 원격 browser/remote MainPID0·정상 종료를 재확인했고 취침 중 로그인 요청은 없다.

## 2026-11-16 수집 실행 방식 재검토·화면 이동 중 수신 관측 보강

- 사용자의 코드/전용 Codex 슬롯 비교 요청을 기존 수집 실행 설계에 구체화했다. 반복 수집은
  기존 고정 Playwright adapter, Codex는 개발·진단으로 분리한다. 사진 확보 성공 여부와
  무관한 결정이며, 모델 슬롯/운영 프롬프트·새 서비스/registry·외부 LLM은 추가하지 않는다.
  확인하지 않은 selector나 전용 프롬프트만으로 위험 동작 금지를 보장한다고 주장하지 않는다.
- 기존 source에서 download callback 뒤 관측 coroutine 실행 전, 관측 중, 반환 document의
  path만 다른 세 경우를 회귀 테스트로 재현했다. 수정 전3건 모두 잘못된 DOM을 OBSERVED로
  기록했다. receiver가 event 시점의 정제된 path를 고정하고 observer가 전/후·document를
  대조하도록 고쳤다. 불일치는 기존 UNAVAILABLE/OBSERVATION_INVALID이며 정상 bytes와
  원래 수신 이력은 보존한다. query/credential은 저장하지 않으며 unsupported origin이
  나중의 화면 이동으로 지원된 관측이 될 수 없다.
- 이 검사는 같은 path에서의 UI 변경, provider 방/메시지 identity나 사진 occurrence 정합의
  증명이 아니다. 해당 실제 관측/수락 gate는 남아 있고 AUTO는 비활성이다. 과거 실제
  CSV/JPEG에 새 DOM을 소급해서 붙이지 않았다. schema/DB/API·권한·profile 설정 변경은 없다.
- 합동 **478 PASS**에는 실제 설치 Chromium을 사용한 익명 합성2검사가 포함된다. 실제 SDK
  다운로드 보존·SPA path 변경 전/후 거부·반복 occurrence·입력 필드 제외·위험 버튼 클릭0·
  외부 요청0을 확인했다. 새 browser 검사의 첫 실패1건은 fixture에 Start 대신 terminal Result를
  넘긴 오류였으며 올바른 원래 started receipt로 수정해 재검증했다. strict mypy2 source,
  Ruff/format·개발 문맥 검사도 PASS다. 이 변경은 DB를 수정하지 않으므로 앞서0090까지의
  disposable DB 결과를 보존하고 이번에 불필요하게 재실행하지 않았다.
- **소스 검증이며 운영 미반영**이다. 원격 browser/remote는 MainPID0·inactive·Result success를
  재확인했다. 운영 API/Catalog/Web·DB0087·GPU pins·실제 수신물·FAILED 이력과 사용자 인증은
  변경하지 않았다. 실제 방→source→학생 PDF·전체 방 주기 수집은 여전히 미완료다.
  다음 수직 경로는 이미 수락된 capability를 실제 collection 실행/현재 권한에 연결하는 것이다.

## 2026-11-16 확인된 MANUAL 방의 capability 수락 owner

- 먼저 `capability-verification-v1` schema/mirror와 frozen DTO를 정의했다. 요청은 이미 확인한
  binding/room/version만 받으며, caller가 capability bool·path·adapter hash를 주장하지 못한다.
  현재 operator/ADMIN/COLLECT·room·channel pin·원래 MANUAL proof의 owner/fence/시각을
  재검증하고 기존 Artifact publisher로 capability와 작은 verification만 발행한다.
- 새 DB0090에는 `kakao_capability_acceptances` 불변 한 테이블만 추가했다. 본문/사진이나
  mutable activation head·새 큐·command framework는 없다. 정확한 receipt의 PK/unique/FK와
  기존 immutable trigger를 사용한다. 조회·재전송은 원래 capability/Artifact revision을 유지한다.
- 확인된 단일 방은 내부 `MANUAL_SELECTED_ROOM` scope다. 카카오 UI 필터명·전체 방 목록
  또는 안정적인 메시지 ID를 확인했다고 주장하지 않는다. CSV 범위·순서·시간대·발신 방향·
  album·원본 화질·읽음 여부는 UNKNOWN이며 **DRAFT/NOT_VERIFIED·AUTO 비활성은 그대로**다.
  이후 더 많은 metadata를 인식해도 옛 UNKNOWN을 새 확정값으로 바꾸지 않고, 근거보다
  강한 주장은 거부한다. 실제 설치 adapter pin의 주입은 후속 composition gate다.
- 실제 guarded 임시 PostgreSQL에서 0090 적용→되돌림→재적용, ORM metadata 일치를 확인했다.
  source/DB 검증은 현재 합성 입력이며 실제 카카오 계정/원본·운영 DB에는 쓰지 않았다.
  동시 same-key/서로 다른 room 경합, 발행 직후 중단·정본 재사용, 늦은 권한/정책 변경,
  다른 owner, 근거 없는 approved room, 원래 파일 없음의 no-latest fallback과 불변 row를 검사했다.
- 첫 DB suite의192 PASS/5 FAIL은 다른 테스트의 receipt까지 전역 count한 fixture 오류였다.
  owner/binding으로 수를 한정하고 발행된 exact Artifact를 확인하도록 고쳤다. DB/원본 이력을
  지우거나 trigger를 풀지 않았다. 후속200 PASS와 pure/경계/문맥68 PASS, strict mypy3 source·
  Ruff/format·schema audit1470/mirror1116 PASS를 확인했다. 기존 TestClient warning1건은 남는다.
  최종 파일의200 PASS는 `staging/kakao-capability-0090-checked.log`, migration 왕복은
  `staging/kakao-capability-0090-migration.log`다. 별도 원격 browser/remote의 MainPID0·정상 종료와
  실제 HTTPS login GET200도 재확인했으며, 이를 카카오 로그인/수집 성공으로 해석하지 않는다.
- **소스 구현이며 운영 미반영**이다. API/Catalog/Web·운영 DB0087·GPU INDEX/QUERY와
  실제 CSV/JPEG·FAILED 기록은 보존했다. 이 owner는 실제 worker를 실행하거나 source 수락을
  허가하지 않는다. 다음은 exact capability를 pin한 collection intent/claim/fence와 현재 owner
  권한을 연결하여 실제 capture→source→질문→학생 PDF로 이어가는 단계다. 전체 목표는 미완료다.
- source `9980121fd7d498bdeea295c02b088db0f9932cef`는 main에 커밋·푸시했다. 공식 clean
  API4-wheel build/RECORD/inspection PASS 후, checkout 밖의 `python -I`에서 새 서비스·모델·
  계약/schema·source head를 실제 wheel 경로로 import하는 검사를 통과했다. DB/실제 계정
  접근은0이며 운영 설치나 전용 UID/sandbox 검사를 뜻하지 않는다. platform wheel SHA는
  `511bf10e0749ea08b0e878a556963cfa395336bec9f651d33dc19a635211cf0c`이고 위치는
  `/tmp/eom-api-build/9980121fd7d498bdeea295c02b088db0f9932cef.ym3EIU/dist/`다.

## 2026-11-16 질문 나누기·합치기 GUI 연결 소스 검증

- 기존 compose RPC/API/BFF·원자적 저장 owner를 그대로 사용하도록 Studio에 질문 나누기와
  순서 있는 합치기 편집 영역을 연결했다. 별도 DB/queue·worker·AI/의존성은 추가하지 않았다.
  source의 질문/방/학생 권한·CAS·불변 저장 규칙은 Catalog가 계속 소유한다.
- 질문 목록의 `합칠 목록에 추가`와 상세의 `질문 나누기 준비`를 제공한다. 합치기 순서는
  위/아래/빼기로 명시하며, 나누기는 메시지·사진 block 사이의 선택을 기존 BLOCK selector로
  보낸다. v1 projection에 없는 원문 절대 offset을 추측하지 않으며 **문장 내부 분할·표시문
  수정 UI는 아직 미구현**이다. 원문/사진을 다시 등록하거나 기존 packet/PDF를 변경하지 않는다.
- 응답 유실 뒤 같은 key/body 재확인, 화면 닫기·다시 열기의 미확정 intent 보존, 성공 뒤
  목록 열기만 실패했을 때 새 POST 없는 결과 열기, 다른 owner/scope 응답 거부와 이전
  detached button 차단을 실제 Chromium 합성 입력으로 확인했다. 저장 중 다른 질문을
  선택하면 늦은 완료가 새 선택을 덮지 않고 사용자가 저장 결과 열기를 선택하도록 했다.
- controller 단독 검사 외에 실제 archive 화면의 split → 목록 재조회 → exact 새 질문 열기 →
  merge → 목록/상세 갱신도 합성 API로 검증했다. 이미 저장한 packet의 revision은 유지됐다.
  Kakao 브라우저·질문 BFF·wheel inventory·frontend/backend alignment·GUI 원칙 합동
  **46 PASS**, strict mypy1 source·Ruff·JS module syntax PASS다. 기존 TestClient warning1건은 남는다.
  처음 두 browser 호출은 기존 local browser cache 경로를 빠뜨린 환경 invocation 실패였으며,
  올바른 기존 cache로 재실행했다. 새 browser/dependency를 설치하거나 실패를 숨기지 않았다.
- **운영 미반영**이다. API/Catalog/Web·DB0087·GPU pins, 실제 CSV/JPEG3건과 실패 이력은
  보존했다. 실제 source 수집 authority→질문 저장, 새 GUI를 지원하는 호환 운영 릴리스,
  실제 방→학생 PDF·다운로드와 전체 방 주기 수집은 여전히 남아 있다.
- source `8cd61162b8bc18f49fe6f0a681195c60555c56bc`를 커밋·푸시했다. clean source의 공식
  Web build/101개 file의 RECORD·offline 설치 simulation·pip check가 PASS다. wheel SHA는
  `af7be9f083f50c62daba02a864143ce9478fdcbc5cca0feb3bf811835f7bf1dc`, closure SHA는
  `b252f08bbf2afc5c89bcf4cb58e9ac9ed13b8f6d98668d56a26689f352c78b42`다. 위치는
  `/tmp/eom-web-gui-build/8cd61162b8bc18f49fe6f0a681195c60555c56bc.3MjiY3/dist/`이며
  `staging/kakao-question-composer-wheel.log`가 개발 증거다. 별도 pure/RPC/편집/문맥88개도 PASS다.
  현재 원격 browser/remote는 MainPID0·정상 종료 상태를 재확인했다. 카카오 재로그인·수집,
  사용자 계정 변경이나 GPU runtime 재시작은 하지 않았다.

## 2026-11-16 MANUAL 관측 → 기존 방 등록의 내부 연결 검증

- `manual-room-intake-v1` schema와 frozen DTO를 먼저 정의하고, 기존 수신 reader → Artifact
  publisher → `KakaoRoomService.admit_room`을 연결했다. 공개 create endpoint나 별도 수집
  queue/실행 tracker는 추가하지 않았다. canonical room은 기존 owner가 만들며 최초 학생
  mapping은 UNMAPPED다. DRAFT·capability·AUTO를 활성 상태로 위장하지 않는다.
- 현재 owner/권한·실제 과거 lease/fence·capture 시각과 사진 download의 방별 path/현재
  document 채널을 대조한다. 이름·파일명·화면 순서로 방을 추측하지 않는다. 작은 immutable
  `kakao_manual_channel_pins` 한 테이블(0089)로 같은 연결에 다른 채널이 섞이지 않게 한다.
  사진/CSV 본문은 여기에 복사하지 않고 원래 receipt/DOM과 작은 proof만 발행한다.
- 같은 요청은 기존 admission/publication을 재사용한다. 완료 후 staging이 없어도 canonical
  evidence로 재조회하며, 발행 중 중단·동시 요청·응답 유실에서도 원래 identity를 유지한다.
  현재 owner의 새 인증 세션으로 과거 capture를 확인할 수 있지만, 이전 remote 화면의 session
  제한·TTL·ENDED 기록은 그대로다. source 수락/사진 occurrence 연결은 별도 후속 책임이다.
- 공식 guarded disposable PostgreSQL suite **185 PASS**, 관련 pure/reader/room/의존성 unit
  **146 PASS**, strict mypy6 source·Ruff/format·wire schema audit PASS다. 0089의 적용→되돌림→
  재적용과 ORM metadata 일치도 확인했다. 실제 사용자·운영 DB·실제 카카오 자료는 테스트하지 않았다.
  첫 실행의184 PASS/1 FAIL은 이미 승인된 Artifact를 UPDATE하려던 부정 fixture가 기존
  immutable trigger에 막힌 경우다. 실제 불변성을 확인하는 테스트로 고쳤으며 trigger를 풀거나
  원본을 변경하지 않았다. 기존 TestClient deprecation warning1건은 남아 있다.
- 이 변경은 **소스 검증이며 운영 미배포**다. 운영 DB0087·API/Catalog/Web·GPU pins와
  collector53cb1a1e는 유지한다. 0088/0089는 후속 compatible release에서 함께 반영해야 한다.
  원래 실제 CSV/JPEG에는 이번 DOM 관측이 없으므로 새 proof를 소급해서 붙이지 않았다.
- 사용자 요청의 코드/전용 Codex 슬롯 비교는 `KAKAO_COLLECTION_EXECUTION_BOUNDARY.md`의
  실행 방식 결정에 기록했다. 반복 수집은 검증된 고정 Playwright adapter가 담당하고 전용
  Codex 슬롯은 사용하지 않는다. 실제 UI와 불일치하면 중단하며, 메시지 전송/임의 클릭 경로는
  만들지 않는다. 실제 방→학생 PDF와 전체 방 주기 수집은 아직 완료가 아니다.

## 2026-11-16 20:00 UTC DOM 관측 browser 설치·격리 headed 검증 PASS

- source `53cb1a1e7fade4b6d97160f67a67411df1d7d7b1`를 커밋·푸시하고, stopped-profile
  경계에서 collector/pure-contract 두 wheel만 전용 browser prefix에 설치했다. wheel SHA는
  각각 `3a6b1544d1699530050530c2f6b021c347db5a4ec61d37ab83fd55ff8dac0f69`,
  `36305180d6863becdd8c9ea9c64c8136e229f69d1e93e89f60583766cf97d565`다.
  현재 runtime prefix fingerprint·wheel bytes/RECORD·pip check·공식 stage/verify를 확인했고,
  이전 package/config와 manifest rollback 위치도 보존했다. receipt는
  `/var/lib/eom-kakao-observation-release-53cb1a1e/installed.json`이다.
- 배포 중 기존 지원 preflight로 실행/lease/native 작업이 없는 시점을 확인했다. Catalog만
  config 재조회 목적으로 재기동했고 API/Web·DB0087 및 INDEX/QUERY pin은 유지했다.
  browser/remote는 그대로 STOPPED, HTTPS `/studio/login` GET200이다. profile·인증정보·
  이전 실패/실제 CSV·사진을 바꾸거나 카카오 로그인·원격 session을 새로 만들지 않았다.
- 실제 설치본의 `run_manual`/Xvnc readiness/SDK launch→download event→DOM projection→
  byte/hash/receipt→context close를 전용 UID와 동일 보안 sandbox에서 두 cycle 실행했다.
  실제 profile/NAS는 mask하고 private network와 익명 fulfilled HTTP/blob fixture만 사용했다.
  source Git checkout/운영 계정 로그인/실제 카카오 요청을 input으로 쓰지 않았다.
- 합성 capture4건의 RECEIVED와 원래 bytes/hash·exact page 연결·관측 OBSERVED/BLOB·
  반복 text2개의 별도 parent·입력 field 제외·위험 버튼 클릭0·종료 후 보존·endpoint cleanup이
  PASS이며 process exit0이다. `staging/kakao-observation-installed-headed-53cb1a1e.log`와
  `/var/lib/eom-kakao-headed-observation-probe-53cb1a1e/`가 합성 증거다.
- **이는 실제 카카오 DOM/selector나 사진 occurrence 정합 PASS가 아니다.** 현재 수집의
  다음 병목은 확인된 provider 채널/방 관측을 받아 실제 source admission을 허가하는 기존
  Catalog owner 연결이다. 단순 callback 허용·DRAFT를 fake ACTIVE로 바꾸기·과거 capture에
  새 DOM을 붙이기는 하지 않는다. 그 owner/질문→packet→PDF 연결을 진행하며, 전체 방/주기
  수집의 AUTO 활성화와 실제 학생 PDF는 여전히 미완료다. 취침 중 사용자에게 로그인 요청하지 않았다.

## 2026-11-16 제한된 다운로드 DOM 관측 소스·실제 Chromium 합성 검증

- 수신 파일의 방/메시지 연결에 필요한 실제 DOM 근거를 수집하도록, 새 closed JSON Schema
  `manual-page-observation-v1`을 먼저 정의했다. 기존 download-v1 bytes·실패 receipt는 유지한다.
  collector는 download event의 실제 page에서 코드 소유 read-only expression 하나만 실행한다.
  click/key/message/network 도구나 공개 JS 실행 API를 추가하지 않았다.
- query/fragment 없는 실제 business origin path, 소수 identity attribute, node의 class/role/
  label·leaf text·같은 origin link path·image 존재 여부만 bounded receipt로 남긴다.
  form/input/textarea/contenteditable/iframe/script(HTML·SVG)는 제외한다. cookie/storage,
  event handler·image src·signed CDN URL은 읽어 저장하지 않는다. CSV 본문과 사진 bytes는
  이 제한된 DOM excerpt로 대체하지 않는다. 임시 node index를 logical message ID로 쓰지 않는다.
- 최대8,192 node 검사/2,048 node 출력/65,536 text code point/1MiB JSON·1.5초 한도를
  적용한다. clip은 truncated, timeout/다른 origin/페이지 종료는 UNAVAILABLE이며 정상 다운로드
  bytes를 버리지 않는다. 종료 시 실제 관측 coroutine을 취소·회수하고 원래 수신 실패를 보존한다.
- 로컬 metadata writer만 별도 책임으로 분리해 receiver와 관측에서 재사용했다. Orchestrator
  reader는 선택적 관측을 exact capture/profile/run/fence/page와 STARTED~완료 시각에 대조한다.
  과거 관측 없음은 UNKNOWN이며 새 관측/현재 방을 과거 파일에 자동으로 끼워 넣지 않는다.
- source/runtime/installer/순수 계약/문맥 및 opt-in 실제 Chromium 합성 입력 **416 PASS**,
  Ruff·formatter·strict mypy5 source PASS, schema audit1468/mirror1114 PASS다. 실제 Chromium
  두 검사는 빈 profile·로컬 fulfilled HTML/data/blob만 사용하며 외부 전송0이다. 반복 문자열의
  서로 다른 occurrence2개, 필드 제외, 위험 버튼 클릭0, hidden9,000개/출력 수/Unicode bound,
  context 종료 뒤 원래 bytes/관측 receipt 보존을 확인했다.
- 첫 실제 엔진 검사는 blob link의 URL origin만 맞아 full blob path가 반환되는 소스 오류를
  잡았다. same-origin HTTPS path만 허용하도록 고쳐 재검증했다. 합성 HTML charset 미선언도
  UTF-8로 바로잡았다. 운영 원본·실패 기록을 바꿔 검사를 통과시키지 않았다.
- **현재 소스 검증 단계이며 운영 미반영**이다. API/Catalog/Web·DB0087과 INDEX/QUERY pin,
  사용자 profile/인증정보는 유지한다. 다음은 stopped-profile 경계의 collector+pure-contract
  wheel 배포·격리 설치본 검사다. 실제 카카오 DOM·selector/사진 정합·source 수락·학생 PDF와
  전체 방 주기 수집은 아직 미완료이고 AUTO는 비활성이다. 사용자는 취침 중이며 로그인 요청은 없다.

## 2026-11-16 실제 사진2건 수신·보존 및 입력 검증 소스

- 같은 실제 방에서 표시된 사진 각각의 내려받기 아이콘을 확인한 뒤, 사진2건을 받았다.
  완료 receipt의 원본 크기는3,153,794/740,115byte이며 SHA를 대조했다. 격리 PDF 환경의
  Pillow로 실제 JPEG 전체 decode·단일 frame·3061×3012/1791×1572 크기를 확인했다.
  API 환경에서의 첫 decode 진단은 선택 Pillow 미설치로 시작 전 실패했으며, API의 운영
  의존성을 임의 설치하지 않고 이미 decoder가 있는 환경에서 read-only로 확인했다.
- browser/remote는 이후 MainPID0, Result success/exit0이다. 종료 후에도 CSV1건·JPEG2건의
  payload/완료 receipt와 hash가 보존된다. 사진 표식3개 중1개는 아직 미확보다. 단순 수신·
  픽셀 decode와 메시지별 사진 연결·실제 source 수락·학생 PDF 완료를 구분한다.
  원문 없는 진단은 `staging/kakao-1926-retained.json`, `staging/kakao-1928-media-decoded.json`이다.
- 사용자는 취침 전 사진 내려받기·스크롤을 허용했으며, 메시지 전송·차단·신고·상담 완료 등은
  금지 상태로 유지했다. 추가 로그인·원격 세션 임의 재시작 없이 독립 소스 작업을 진행한다.
- 기존 설계의 결정론적 Playwright 수집을 유지하며 전용 Codex 슬롯은 배정하지 않기로 했다.
  근거와 안전한 DOM 동작·입력 경계는 `KAKAO_COLLECTION_EXECUTION_BOUNDARY.md`에 기록했다.
  개발용 화면 좌표를 자동 수집 selector로 사용하지 않는다.
- source에는 기존 수신 계약을 소비하는 Orchestrator reader를 추가했다. 작은 exact ID lookup,
  FD 전후 metadata·권한·run/fence·STARTED/terminal identity·payload size/hash를 확인하며
  읽기만 한다. 기존 OS reader의 optional GID/mode 검사도 재사용한다. 새 DB/queue/의존성,
  source 권한 우회, browser 임의 조작이나 자동 admission은 없다.
- 신규 부정/재조회/동시 읽기39개를 포함한 관련 runtime 회귀 **244 PASS**, Ruff·formatter·
  strict mypy2 source PASS다. 이 reader는 **소스 구현이며 아직 운영 application에 연결하지
  않았다.** source 수집 authority·사진 occurrence 정합과 기존 질문/packet/PDF 연결이 다음이다.
- source commit `dc3cf8c74d0e7e22b9a9a39ab98bcff90f29672f`는 main에 커밋·푸시했다.
  clean source에서 만든 platform wheel의 SHA는
  `0fbb4176b44883008c47ef93dfb04dfa7cfdc3042d63569a6a651c1a84e00c65`다.
  reader·OS adapter·package init 세 member의 RECORD/hash를 대조하고 별도 root-owned
  prefix에만 풀었다. 그 code와 기존 browser pure-contract 설치본으로 정상 Catalog UID에서
  실제 보존 CSV/JPEG3건의 읽기·동일 capture 재조회·다른 fence 거부를 확인했다.
  receipt는 `/var/lib/eom-kakao-input-canary-dc3cf8c7/manifest.json`, 원문 없는 결과는
  `staging/kakao-input-wheel-dc3cf8c7.json`이다. 이는 **격리 wheel-member read 검사**이며
  platform/API의 운영 설치나 정본 publication을 의미하지 않는다. 운영 pin은 바꾸지 않았다.
- 종료된 browser의 다운로드 metadata만 read-only로 확인했다. CSV는 blob 다운로드이고,
  사진은 실제 `business.kakao.com`의 방별 이미지 경로에서 `k.kakaocdn.net`으로 redirect했다.
  사진2건의 profile/room 경로 component는 같았다. URL·서명값·credentials query 값은
  진단에 출력/저장하지 않았고, 이 경로만으로 CSV 행/사진 occurrence 연결이나 방 identity
  안정성을 증명하지 않는다. 전체 cookie/profile 내용은 읽거나 변경하지 않았다.

## 2026-11-16 19:11 UTC 실제 카카오 CSV 수신 PASS

- 사용자가 기존 연결의 MANUAL 화면을 다시 준비한 뒤, 실제 열린 방에서 `대화 내보내기 →
  내 PC 저장`을 실행했다. 현재 browser run의 완료 receipt가 `RECEIVED`이며 5,723byte의
  원본 파일이 로컬 staging에 보존됐다. Catalog 서비스 계정으로 크기와 SHA-256을 대조했다.
- UTF-8 CSV의 열은 `DATE,USER,MESSAGE`, 대화 행은10개이며 모든 행 너비가3이다.
  대화·학생 이름·파일명·원본 screenshot은 Git/Slack에 저장하지 않는다. 증거는 보호된
  `/var/lib/eom-kakao/downloads/`의 해당 run receipt/payload이며, 원문 없는 진단은
  `staging/kakao-1914-download-after.json`이다. 기존 수신 실패 기록은 그대로 보존했다.
- 첫 pointer click은 sidebar의 scroll 정착 전 위치여서 download event가 없었다. 다시
  최신 화면에서 버튼 hover를 확인하고 정확한 버튼을 눌렀으며, 실제 download event와
  완료 capture는1건이다. 키보드 입력·메시지 전송·상담 상태 변경은0이다.
- CSV 안에 `사진` 표식이3개 있으나 **사진 원본 확보·메시지 attachment occurrence 연결·
  source admission·학생 PDF는 아직 PASS가 아니다.** 이 수신만으로 전체 방·기간·방향·
  timezone 완전성을 주장하거나 AUTO를 켜지 않는다. 다음은 실제 사진 확보와 메시지 연결이다.
- 이번 실증 중 runtime/API/Web/DB/GPU pin·인증 파일·채널 설정은 변경하지 않았다.

## 2026-11-16 19:01 UTC 설치본 headed 수신·종료 후 보존 PASS

- stopped profile에서 `77fc7c0d6dbd190e20f8975788bca41e760e9f09`의 collector wheel
  `sha256:80c396e1db0318de353a6842cef8d8322775219a9fc7a410549d4765ff694c75`을
  후속 설치했다. pure contracts는 앞선3fbece8c 설치본을 유지한다. source138개 검사와
  후속61개 focused 검사가 통과했고, 공식 설치 stage/verify·wheel member/RECORD·전체
  prefix fingerprint/pip check와 HTTPS Studio login200을 확인했다.
- release receipt는 `/var/lib/eom-kakao-download-release-77fc7c0d/installed.json`이다.
  API/Catalog8e2e11eb·Web636e39fa·DB0087·GPU INDEX/QUERY pin은 유지한다. Catalog만
  stopped-browser 릴리스 검증 뒤 재기동했고, 원래 profile/비밀번호/실패 이력은 보존한다.
- 실제 설치 `run_manual`/Xvnc/SDK/다운로드 수신/streaming hash/receipt/close를 전용 UID·
  `NoNewPrivileges`/`RestrictSUIDSGID`/PrivateTmp/PrivateDevices 아래에서 두 번 실행했다.
  실제 profile과 NAS를 mask하고 network를 격리했다. 새 합성 staging 위치와 익명 UI
  exercise만 주입했으며 launch/readiness나 다운로드 완료를 mock으로 바꾸지 않았다.
- 두 cycle에서 합성 CSV 총4건의 수신·byte/hash·context 종료 후 보존과 VNC endpoint
  cleanup이 PASS, process exit0이다. 기존 두 실패 canary는 각각 보존했다. 새 검증 기록은
  `staging/kakao-download-installed-headed-77fc7c0d.log`와 root 보관된 전용 canary receipt다.
- **실제 카카오 CSV·사진·학생 PDF는 여전히 미검증**이다. 사용자에게 이제 같은 연결의
  MANUAL을 열어 달라고 한 번 요청했다. 다음은 기존 승인 범위의 실제 내보내기1회와 파일
  수신·원문 포맷 검증이다. 내보내기 source를 방/사진 occurrence에 연결한 것으로 가정하지 않는다.
  기본80%/창 장식은 아직 미적용이며 다운로드 수정 성공과 섞어 보고하지 않는다.

## 2026-11-16 MANUAL 다운로드 배포·sandbox 후속

- `3fbece8c` collector/pure-contract wheel을 stopped profile에서 전용 browser 환경에만
  설치했다. wheel bytes·전체 환경 fingerprint·pip check, 공식 installer stage/verify와
  HTTPS Studio login200을 확인했다. API/Web/DB0087·INDEX/QUERY와 인증/profile은 유지했다.
  설치 receipt는 `/var/lib/eom-kakao-download-release-3fbece8c/installed.json`이다.
- 실제 profile/network를 가린 전용 UID headed 검사에서 두 실패를 보존했다. 첫 검사에선
  검증 스크립트의 root 전용 부모 때문에 Python 시작 전에 거부됐다. 두 번째는 설치된
  driver까지 도달했으나 `RestrictSUIDSGID=yes`가 worker의 mkdir2750 요청을 거부했다.
  이는 source/same-user 시험만으로 설치 sandbox 성공을 주장하면 안 되는 실제 사례다.
- 후속 source는 worker mkdir/chmod에 setgid를 요청하지 않고0750 directory와 기존
  control group의 명시적 chown,0640 파일을 사용한다. root가 설치하는 부모만2750이다.
  worker의 기존 그룹 membership을 재사용하며 systemd 보안 정책·NAS/DB 금지·계정 권한을
  풀지 않는다. 같은 환경 회귀와 새 설치 검증 전 사용자 재로그인을 요청하지 않는다.
  실제 카카오 CSV 수신은 아직 PENDING이다.

## 2026-11-16 18:50 UTC MANUAL 다운로드 수신 source·실제 Chromium 합성 검증

- 다운로드 차단 원인을 기존 MANUAL driver에서 수정했다. JSON Schema 2020-12/frozen
  download receipt를 먼저 정의한 뒤, SDK event 수신→로컬 고정 member→완료 byte/hash→별도
  terminal receipt로 연결했다. 시작/실패 기록과 기존 profile/인증정보는 덮지 않는다.
- 실제 설치 Chromium으로 익명 data-URL CSV 2건을 내려받았다. 같은 filename이지만 다른
  capture를 유지하며, context 종료 뒤에도 결과 byte/hash와 파일이 보존되는 것을 검증했다.
  sandbox는 켜져 있고 실제 카카오 profile·대화·외부 네트워크 자료는 사용하지 않았다.
- empty/oversize/timeout/취소/위험 경로/중복 event/즉시 종료와 installer/runtime 검사
  **138 PASS**, source3개 strict mypy·Ruff 및 schema audit1467/mirror1113 PASS다.
  첫 합성 Chromium 검사는 headless-shell 미설치와 test process의 다른 umask 때문에
  실패했다. 기존 설치 Chromium과 운영과 같은0077 umask로 명시해 재검증했으며,
  실제 boundary의 파일 권한 검사·sandbox를 해제하지 않았다.
- root 설치 download directory는 browser UID/control group의2750이고, browser unit에
  그 path만 쓰기를 추가한다. 기존 private profile·NAS/DB 접근 금지는 그대로다. installer는
  layout 위치 변경이 lock owner에 영향을 주지 않도록 path map으로 identity를 조회한다.
- **현재는 source 검증 완료이며 운영 반영은 다음 단계**다. API/Catalog/Web·DB0087,
  INDEX/QUERY pin은 바꾸지 않는다. stopped-profile 경계에서 browser collector와 그 pure
  contract wheel만 같은 release로 설치하고 실제 설치본 합성 수신까지 확인할 예정이다.
  사용자의 실제 CSV 재시도/학생 PDF는 아직 PASS가 아니다. 로그인 요청은 설치 검증 뒤다.

## 2026-11-16 18:36 UTC 실제 내보내기 시도·공개 질문 조합 연결

- 사용자가 번역 팝업을 직접 닫았고, 방 우측 위 메뉴 열기→스크롤과 내보내기 버튼 실행을
  순서대로 추가 허용했다. 화면 확인 후 해당 메뉴만 열고 세로 wheel 3회, `내 PC 저장`
  hover를 실제 cursor 포함 screenshot으로 검증한 뒤, 사용자 승인 아래 내보내기를 1회 눌렀다.
  메시지/키 입력·상담 완료·채팅방 나가기는 0이다. 좌표는 일회성 실증에만 사용했고 실제
  collector selector나 다른 채널/방 identity로 하드코딩하지 않는다.
- **이번 실제 내보내기는 성공하지 않았다.** 정지한 browser의 History 다운로드 metadata를
  read-only로 확인했다. 시도 시각18:31:14 UTC, total5723byte, received0byte, state2,
  interrupt_reason40이다. URI·대화·이름·파일명·인증정보는 진단 출력에서 제외했다.
  설치 MANUAL driver가 `accept_downloads=False`인 것을 확인했다. 다음 우선 작업은
  명시적 다운로드 수락·bounded local staging·hash/receipt 보존 연결이며, 단순 버튼 성공을
  source 수집 성공으로 보고하지 않는다. 파일 수신 전 재접속/반복 클릭은 요청하지 않았다.
- browser/remote는 이후 MainPID0/Result success·종료 code0, profile STOPPED·lease NULL로
  관측됐다. 이전 STOP_UNCONFIRMED 이력은 ENDED 상태로 보존했다. 최대20분 정책은 source에
  있지만 실제 종료 원인이 시간 만료였다고 단정하지 않는다. 실패를 성공으로 바꾸지 않았다.
- 사용자 제안에 따라 다음 display release는 기본80% 축소와 창 크기/창 장식을 함께
  검증할 예정이다. **아직 적용하지 않았고** 기존 profile/비밀번호·배율을 수정하지 않았다.
- source는 atomic composition owner를 실제 Catalog API-peer socket→API→Web BFF에 연결했다.
  새 closed RPC/JSON Schema를 추가했으며 released question-v1 wire bytes는 유지한다.
  사용자/session 권한·CSRF·input별 revision/version CAS·동일 key replay·정확한 출력 연결을
  검사한다. 공개 API의 현재 operation과 OpenAPI snapshot/hash를 함께 갱신했다.
- 새 disposable PostgreSQL의 실제 BFF→HTTP→socket→owner 경로에서 분할→재전송→목록→
  병합→server 재생성→저장 결과 재조회가 통과했다. CSRF 거부·이전 parent412·같은 key의
  다른 body409도 확인했다. 전체 Kakao integration **168 PASS**, RPC/API/BFF·경계 source
  **70 PASS**, 추가 gateway/OpenAPI **29 PASS**, strict mypy6 source PASS다. 테스트 집합은
  중복되므로 합산하지 않는다. schema1466/mirror1112 audit도 통과했다.
- **이번 변경은 소스만이며 운영 미배포다.** DB0087·기존 compatible set·AUTO 비활성 상태는
  유지한다. 질문 조합 GUI·표시 교정 연결, 다운로드 수신, 실제 source/사진 occurrence·학생 PDF,
  전체 방/주기 수집은 여전히 남아 있다. 다음 행동은 로그인 반복이 아니라 다운로드 수신 구현이다.

## 2026-11-16 18:17 UTC 클릭 없는 스크롤 확인·질문 조합 저장

- 사용자는 실제 카카오 화면에 **마우스 이동·스크롤만 허용하고 클릭은 금지**했다.
  그 범위에서 먼저 스크롤만 검증했다. 이후 **채팅방 열기·닫기와 내보내기 버튼 hover**를
  추가 허용하여 방 하나를 여는 클릭 1회만 실행했다. 키 입력·메시지 전송·내보내기 실행은
  하지 않았다. 번역 팝업이 방 메뉴를 가려, 그 팝업 닫기/방 정보 메뉴 열기는 별도로 확인 중이다.
  아직 내보내기에 hover했다고 주장하지 않는다. 합성 입력 개발은 계속 가능하다.
- 기존 MANUAL은 ENDED/profile STOPPED·실제 프로세스 없음으로 확인했다. 원래
  STOP_UNCONFIRMED 이력은 그대로 두었고, 사용자가 새 연결을 시작한 뒤 ACTIVE를 확인했다.
  연결을 개발자가 임의로 되살리거나 TTL/인증정보를 바꾸지 않았다.
- 실제 화면에서 채팅방 목록의 세로 wheel 3회만 수행했다. 전후 화면에서 목록 내부만
  이동한 것을 확인했고 click/key/message는 0이다. 전체 방 inventory·CSV·사진 수집 검증은
  아니다. screenshot 원문·이름·대화는 Git/Slack에 저장하지 않는다.
- 원격 화면은 1440×960인데 현재 Chromium 창은 그보다 좁다. window manager 부재와
  창 크기를 함께 정리해야 하며, Chromium 100% 기준과 창 장식/크기 고정은 **미구현**이다.
  현재 배율·창 위치·크기와 사용자 프로필은 변경하지 않았다. 좌표를 실제 수집 selector로
  채택하거나 지금 보이는 상담 필터를 전체 방이라고 간주하지 않는다.
- source에는 JSON Schema/frozen 결과 DTO → 질문 조합 저장 owner → DB0088을 추가했다.
  동일 요청은 같은 출력 ID/Artifact를 재사용하고, 분할/병합의 모든 출력과 입력 대체를
  원자적으로 채택한다. 과거 질문 revision·packet·source origin 중복 방지 기록은 보존한다.
  소스 철회·세션 만료·학생 mapping 변경·다른 편집 경합은 수락 직전에 다시 확인한다.
- 새 disposable DB의 전체 migration·0088 되돌리기/재적용과 Kakao 저장/HTTP/PDF/metadata
  **167 PASS**, focused 계약/편집 **137 PASS**, strict mypy4개/Ruff PASS다.
  초기 테스트에서 fixture import 누락과 JSON Schema 예외 분류를 수정했다. 기존 오래된
  disposable DB의 source 완료 시각 CHECK가 현재 source와 달라 한 건 실패한 것은 metadata로
  확인한 뒤 새 DB에서 전체 migration으로 재검증했다. 운영 결함으로 추정해 상태를 고치지 않았다.
- 이번 저장 소스는 **운영 미배포**다. 공개 split/merge API·BFF·GUI와 compatible release는
  후속이며 현재 MANUAL/PDF 운영 설치와 AUTO 비활성 상태는 유지한다. 실제 한 방 수집부터
  학생 PDF까지의 완료와 전체 방 주기 수집도 아직 남아 있다.

## 2026-11-16 17:49 UTC 사용자 채팅방 열림 확인·분할/병합 선택 입력

- 사용자가 원격 화면에서 카카오 채팅방을 열었다고 확인했다. 실제 browser/remote unit도
  17:42:48/49 UTC 이후 ACTIVE이며 PID가 존재한다. 이는 **USER_VERIFIED 로그인·화면**
  증거다. 실제 채널/방 selector·CSV 범위·사진 occurrence 연결은 아직 확인하지 않았고,
  수집 또는 학생 PDF 완료로 확대하지 않는다. 메시지는 보내지 않았다.
- 사용자가 연 연결은 유지한다. 아래 source 작업으로 현재 Catalog/browser를 재시작하거나
  MANUAL 권한·profile/인증 파일·기존 실패 이력을 변경하지 않았다. 실제 화면의 메뉴 위치를
  확인하기 위한 사용자 screenshot을 요청했으며, 로그인 인증정보는 요청하지 않았다.
- JSON Schema 2020-12 `question-compose-v1`과 frozen selection DTO를 추가했다.
  Catalog의 `kakao_question_selections.py`가 exact revision/version과 작은 block/span
  선택을 기존 `split_question`/`merge_questions`에 연결한다. 원문·사진 pointer·authority·
  결과 ID는 browser 입력이 아니다. 같은 서버 예약으로 동일한 manifest를 재구성한다.
- source 검증 **141 PASS**: canonical/mirror/hash, wire 입력 거부, source hash·부모
  version 불일치, 글/사진 coverage, Unicode 경계, display override 보존, 학생 격리,
  미확보 사진의 FINAL 차단, 원문 반복 occurrence 보존 및 기존 API import/route 회귀다.
  초기 테스트의 미확보 사진 기대값은 review reason이 아니라 기존 FINAL blocker를
  확인하도록 고쳤다. 운영 실패/원본을 수정하지 않았다.
- Ruff·formatter·strict mypy 두 source PASS, wire audit1464개 canonical/1110개 mirror
  참조 검사 PASS. **다중 질문 원자적 저장·SUPERSEDED 전환·공개 split/merge API/GUI는
  후속이며 아직 활성 기능이 아니다.** 운영 release는 위 로그인 수정 compatible set 그대로다.

## 2026-11-16 17:36 UTC X11 수정 운영 반영·installed empty canary 완료

- collector `41bbbaa9d4f31971ab1a3ecb4e489494c167f874` wheel
  `sha256:58bc7286d3723d93f570aba346cce10020abe9ddc5cf15b07c3e42e67578fe23`을
  stopped profile 경계에서 설치했다. wheel member bytes/RECORD와 전체 prefix fingerprint,
  기존 installer stage/verify를 통과하고 Catalog를 재기동했다. 설치 receipt는
  `/var/lib/eom-kakao-x11-release-41bbbaa9/installed.json`이다.
- 실제 설치본의 `run_manual`·X11 directory 준비·Xvnc argv·readiness·Chromium launch/close를
  그대로 사용한 네 번째 empty canary가 두 번 모두 PASS다. 배포 이후 launch/readiness를
  test stub으로 바꾸지 않았다. 새 합성 profile 경로와 전용 canary cgroup/동일 flock 검사만
  재배정했다. 실제 profile은 mask하고 PrivateNetwork를 켜므로 실제 카카오 인증정보와
  대화를 읽지 않는다. 이 검증은 production lease/현재 사용자 권한 실증의 대체물이 아니다.
- canary의 두 반복에서 actual headed Chromium의 정상 시작·정상 close, Xvnc의 정상
  종료, 죽은 VNC endpoint 정리와 X11 endpoint 부재를 확인했다. 새 설치 unit에도
  browser/remote `ExecStopPost`가 반영돼 있다. 과거 unit FAILED/lease 이력은 보존한다.
- 현재 component map은 API/Catalog8e2e11eb, Web636e39fa, browser41bbbaa9,
  gateway/unit01e04fff, DB0087이다. 전체 component가 같은 SHA라고 보고하지 않는다.
  Catalog active와 실제 HTTPS `/studio/login`200을 확인했고 기존 INDEX/QUERY 설치 pin을
  변경하지 않았다. MANUAL/PDF ENABLED·AUTO collection DISABLED 상태는 유지한다.
- source focused219개 및 관련 후속110개 PASS, strict mypy2개/Ruff PASS다. 중복된
  테스트 집합을 더해 독립 검증 수라고 보고하지 않는다.
- 사용자에게 기존 배정 연결에서 새 MANUAL 시작·로그인만 요청했다. **실제 카카오 로그인,
  한 방 CSV/사진 수집, 실제 학생 PDF, 전체 주기 수집은 아직 NOT_VERIFIED**다.
  메시지 전송은0이며 비밀번호·프로필·계정·실패 기록을 변경하지 않았다.

## 2026-11-16 실제 empty headed runtime에서 확인한 X11 시작 실패

- endpoint cleanup `01e04fff`를 두 전용 role에 반영하고 stage/verify·Catalog 재기동을
  완료했다. receipt는 `/var/lib/eom-kakao-endpoint-release-01e04fff/installed.json`이다.
  API/Web/pure contracts·기존 GPU 환경은 변경하지 않았고 profile/인증/실패 이력은 보존했다.
- 사용자에게 재시도를 요청하기 전에 실제 설치 Playwright/Xvnc를 같은 UID·PrivateTmp·
  PrivateDevices·NoNewPrivileges로 빈 프로필에서 실행했다. 실제 profile은 mask하고
  PrivateNetwork를 켰다. 초기2개 canary는 실패했으며 원래 기술 기록을 보존한다.
- RFB가 listen한 직후 Xvnc가 host NVIDIA EGL/GLX 초기화에서 SIGSEGV로 종료되는 것을
  synthetic-only stderr에서 확인했다. 사설 `/tmp/.X11-unix` 부재도 함께 확인했다.
  이는 계정 비밀번호나 카카오 권한 문제의 증거가 아니다.
- 사설 X11 directory 준비와 Xvnc의 GLX 비활성화만 적용한 세 번째 격리 canary에서는
  **authenticated X11 접속·headed Chromium 시작·정상 종료·소켓 정리 2회 PASS**다.
  Chromium sandbox는 켜진 상태이며 `--no-sandbox`·GPU driver 수정·외부 접속은 없다.
- source는 이 설정을 driver owner에 두고 RFB 뒤의 실제 X11 접속을 확인하도록 한다.
  기존 host `x11-utils 7.7+6build2`의 `xdpyinfo`를 재사용하는 이유는 socket 존재와 정상
  인증된 display 준비를 구별하기 위해서다. 새 Python 의존이나 상시 daemon은 없다.
  짧은 probe의 stdout/stderr는 버리고 취소 시 kill/reap한다.
- 위 canary는 아직 새 source wheel의 설치 완료나 실제 카카오 로그인 PASS가 아니다.
  후속 installed wheel의 launch/readiness를 override하지 않은 같은 canary를 확인한 뒤
  사용자에게 재시도를 요청한다.

## 2026-11-16 MANUAL 반복 시작·종료 경계 — 소스 후속

실제 첫 Chromium 시작의 root-owned HOME에서는 Crashpad `--database is required`와
SIGTRAP이 발생했다. 같은 UID·NoNewPrivileges·PrivateNetwork의 빈 프로필에서 HOME만
private writable profile로 바꾸었을 때 empty HTML 출력이 성공했다. `641d9fde`로 이를
운영 browser role에 반영했으며 sandbox/user namespace를 해제하지 않았다. 이 offline
headless 증거는 카카오 로그인이나 headed 브라우저 전체 경로의 PASS가 아니다.

후속 실제 요청에서는 종료된 gateway의 `KAKAO_GATEWAY_SOCKET_EXISTS`를 확인했다.
profile은 STOPPED·current lease NULL·flock 해제였고, 실패 lease는 ENDED로 보존됐다.
directory 보존과 socket 수명 처리를 분리하는 수정은 다음과 같다.

- 책임/정본: 각 browser/gateway runtime이 자신의 고정 Unix endpoint를 systemd
  `ExecStopPost`에서 정리한다. DB·lease·profile·인증정보·request 감사본은 수정하지 않는다.
- identity/해석: 고정 unit cgroup 또는 정확한 `.control` subgroup, 실행 UID/group,
  socket type·단일 link·mode·inode를 확인한다. 연결이 실제 거절된 socket만 제거하고
  unlink 직전 같은 device/inode/owner/group/link/mode를 대조한다. live endpoint는 거부한다.
- 접근/복잡도: 고정 path 한 개의 O(1) stat/connect/unlink다. 별도 DB/index/cache/queue,
  schema·wire contract·dependency는 추가하지 않는다. browser는 기존 profile flock도 쓴다.
- 동시성/실패: 실제 unit 자식 종료 이후 hook이 수행된다. lock 경합·접속 성공·종류/소유권
  불일치는 명시적 실패이며 타 endpoint를 지우거나 새 lease를 만들어 우회하지 않는다.
  종료 기록을 지우지 않고 기존 owner coordinator가 원래 실패를 관측한다.
- 단순 대안: directory를 무조건 지우면 request 감사본이 사라지고, 시작 때 임의 unlink하면
  아직 살아 있는 runtime을 훼손할 수 있다. 기존 service lifecycle 안의 좁은 hook을 선택했다.

소스 검증은 actual local Unix socket·flock과 synthetic fixed-scope identity를 사용한다.
이는 실제 카카오 계정/CSV/사진 수집 PASS가 아니다. 운영 role 교체 후에는 network와 실제
profile을 격리한 empty headed browser의 반복 시작·종료를 먼저 확인하고 사용자 재시도를 요청한다.

## 2026-11-16 동명 연결 선택·확정 거절 UI 후속

사용자 문의 `webreq_a87c42c7e6651f6705653995`의 PROFILE_UNAVAILABLE를 확인했다.
read-only 기술 metadata에서 같은 owner·같은 표시 이름의 DRAFT binding 두 개와,
primary profile이 그중 하나에만 배정된 것을 확인했다. 원래 profile은 STOPPED,
current lease는 NULL, flock은 해제됐고 이전 실패 lease 두 개는 ENDED 이력을 보존한다.
사용자가 알려준 로그인 ID/채널 이름은 배정된 표시 이름과 같았지만 이름 자체는 ID가 아니다.

- `636e39fa`에서 동명 표시만 `연결 1/2`로 구분했다. 실제 API 요청은 기존 binding ID를
  그대로 사용하며 name/ID를 hardcode하거나 원본/배정을 합치지 않는다. map 집계 O(n)이다.
- START의 명시적 PROFILE_UNAVAILABLE 거절에서만 UI 선택을 다시 열었다. 응답 유실,
  timeout·불확실한 처리 여부는 기존 key/body를 유지한다. 서버의 ownership/fence와
  프로필 배정, 실패 이력은 변경하지 않았다. 다른 채널로의 명시적 전환은 별도 후속이다.
- UI/API presentation·실제 Chromium 검증33개 PASS와 공식 Web offline closure/실제
  설치100 member 검사를 통과했다. Web636e39fa를 설치·재기동했고 HTTPS login200이다.
  API/Catalog8e, gateway codec352, remote unit692b는 이번 Web 배포에서 변경하지 않았다.
- 사용자에게 현재 서버 profile이 배정된 구분 항목으로 다시 시도하도록 요청했다.
  **실제 카카오 로그인·수집·학생 PDF는 아직 검증 대기**다. 특정 채널로 고정한 해결이 아니다.


## 실제 첫 MANUAL 시작에서 확인한 후속 수정 — 진행 중

사용자가 `카카오 로그인 준비`를 눌렀으나 원격 화면의 최초 시작이 ERROR로 끝났다.
아직 카카오 인증에 도달하지 않았으며 기존 실패/lease/fence 기록을 보존한다.

- noVNC1.6.0의 정상 빈 `.gitmodules`가 기존 nonempty grant reader의 공통 조건에
  걸렸다. source tree를 임의 삭제하지 않고 static asset 검사에만 최소0byte를 명시했다.
  grant/revocation·실행 interpreter·필수 HTML/JS는 여전히 nonempty다. wire schema,
  profile/lease/권한, 고정 asset path·hash·size bound는 바꾸지 않는다.
- 설계서의 별도 VncAuth 비밀번호는 installer가 의도적으로 만들지 않는다. 운영 활성화
  전에 이 provisioning 확인이 빠져 있었다. 기존 TigerVNC 도구의 stdin으로만 암호를
  전달하는 일회성 `scripts/kakao/provision_vnc_password.py`를 추가했다. 현재 profile
  lock·실제 중지 확인 아래 고정 경로600의 새 파일만 생성하며 기존 비밀번호는 덮지 않는다.
  계정 로그인/변경이나 브라우저 시작은 하지 않는다. argv/URL/로그/Artifact/Git에 값이 없다.
- 사용자에게 전용 비밀번호 입력을 요청했다. 이는 Linux·Studio·카카오 비밀번호가 아니며
  실제 noVNC 화면에서도 수동 입력한다. 코드가 암호를 조회해 대신 로그인하지 않는다.
- gateway/OS adapter/coordinator/암호 helper **112 PASS**, source3개 mypy와 Ruff PASS다.
  source 수정 후 새 gateway wheel과 별도 설치 successor 검증을 진행한다. 이 단락은
  아직 실제 카카오 로그인 또는 source 수정 운영 완료의 선언이 아니다.

후속 운영 반영:

- `c352037e`의 gateway wheel `sha256:c2ddb3d6789bc65b90c354433f1bfd6b017a32dedbbf6724f0085a758af74e36`을
  실제 미실행/중지 상태에서 설치하고 Supervisor source pin을 갱신했다. API/Web/pure
  contracts는 바꾸지 않았다. VNC 비밀번호는 worker 소유600·8byte·단일 link의 metadata만
  확인했으며 값을 조회하지 않았다.
- 첫 후속 설치 verify는 실패한 systemd gateway 종료 시 `/run/eom-kakao-remote`가
  삭제된 것을 확인했다. 실제 runtime lifecycle 문제이며, root가 DB 상태를 수정해
  성공으로 표시하지 않았다. `692b3bfd`에서 gateway도 browser와 같이
  `RuntimeDirectoryPreserve=yes`로 정렬했다. 빈 실행 폴더만 유지하며 socket/process
  종료·fence 검사는 그대로다. gateway/installer87개 검사 PASS다.
- 현재 worker source는 c352, remote unit source는692b다. 새 successor manifest와
  source pin을 명시적으로 적용해 stage/verify 후 Catalog를 재기동했다. 운영 evidence는
  `/var/lib/eom-kakao-gateway-release-c352037e/installed.json`, 현재 설치 검증 입력은 같은
  폴더의 `install-manifest-runtime-dir.json`과 `payload`다. 최초 publication/manifest는
  역사적 predecessor로 보존하며, 최초 hash를 현재 successor의 검증값으로 사용하지 않는다.
- Catalog/API/Web/Caddy 및 HTTPS login은 정상이다. 실패한 MANUAL intent는 여전히
  원래 기록이며 사용자가 `로그인 연결 종료 → 카카오 로그인 준비`로 새 연결을 여는
  supported 경로를 안내했다. 실제 카카오 로그인/한 방/CSV·사진/PDF는 아직 NOT_VERIFIED다.


## 2026-11-16 보호 runtime 설치·MANUAL/PDF 활성화

- API/Web/Catalog/QUERY 운영 source는 `8e2e11eb`, DB0087이다. build gate는
  `0b1b3c2c`, 설치 owner-group 수정은 `157d7c7e`로 각각 커밋·푸시했다. 각 component의
  source를 같은 SHA라고 단정하지 않는다. 전용 runtime package 코드는 eb9→8e 사이
  변경 없음을 Git diff로 확인하고 eb9에서 만든 새 4-wheel을 실제 전용 prefix에 설치했다.
- browser/remote/pdf의 `pip check`, 5개 runtime/asset tree fingerprint, root inode
  publication과 별도 installer stage/verify, 실제 전용 UID·group·systemd template
  검증을 완료했다. 원래 builder tree는 `/opt/eom/.kakao-runtime-publish-3jjj0s70`에
  복구/감사를 위해 보존했다. source 원본·인증정보를 worker에게 복사하지 않았다.
- 최초 stage는 Catalog owner를 render group에 추가한 뒤 동일 owner를 금지하던 installer
  allowlist 불일치에서 중단됐다. worker 권한을 넓히지 않고 owner의 좁은 I/O group만
  허용하도록 수정했다. renderer/타 worker/임의 계정 분리 포함 installer **47 PASS** 후
  동일 manifest의 stage/verify를 완료했다. 실패 기록은 보존했다.
- 설치 manifest SHA는 `sha256:fad5939db96ddab355607e13a4ea0170d94b346d7340ae69d1df1654bcdb32c7`,
  publication plan SHA는 `sha256:8d40ce61453790e29b3c3ad108c34d4381da5aaef470ca86483324620e61237e`다.
  installer source157d의 별도 SHA는 `sha256:5aaf7dfea16f8a58ebbd1cfd109e0ef7ee638a3cc38e7358739c70259c44d504`다.
- 실제 설치 noVNC inventory에서 Web의 exact static path allowlist를 구성하고, 기존
  Caddy route에 현재 owner/session/lease 검사를 통과하는 private UDS 경로만 연결했다.
  Catalog MANUAL/PDF만 ENABLED이며 **AUTO collection은 여전히 비활성**이다.
  Catalog/Web/Caddy 재기동 후 공개 HTTPS login200, API READY, 무인증 remote401을 확인했다.
- 운영 기록은 `/var/lib/eom-kakao-runtime-activation-157d7c7e/activated.json`이다.
  기존 Caddy/Web 설정은 같은 private directory에 복구용으로 보존했다. 개인 인증정보나
  실제 대화·사진을 개발 Git/Slack에 넣지 않았다.
- 사용자에게 `일반 → KakaoTalk → 카카오 로그인 준비`의 실제 로그인 요청을 보냈다.
  **실제 카카오 로그인/한 방/CSV/사진/학생 PDF는 아직 NOT_VERIFIED**다. 실제 로그인과
  2단계 인증을 관측하지 않은 상태를 전체 업무 성공으로 보고하지 않는다. 메시지 전송은 금지다.


## 2026-11-16 후속 운영 release — 학생별 PDF 연결 소스 반영

1. 실제 사용 경로: `eb9e7e1f`에 질문 선택/packet/PDF API·BFF·Studio 연결을 커밋·푸시했다.
   설치 기동 import 결함을 `8e2e11eb95d618cfcd7ee8f7ae810297d96b674e`에서 수정·푸시했으며,
   **현재 API·Web·Catalog/QUERY 호환 release는 8e2e11eb, 운영 DB는0087**이다.
   Web은 공식 offline closure 설치 후 명시적으로 재기동했다. 공개 HTTPS login200과
   API READY를 확인했다. 이것은 아직 실제 학생 자료 PDF 생성의 증거가 아니다.
2. 합성 검증: 아래152개 PostgreSQL 검증을 보존한다. 전체 Kakao source/API/BFF·브라우저·
   의존성/개발 문맥·배포 검사는 재실행 **1426 PASS / 132.25초**였다. 이후 실제 기동에서
   드러난 optional renderer annotation import를 수정했고 disabled composition 직접 생성
   등21개, 배포/기동 경계69개 및 mypy를 통과했다. 겹치는 검사를 합산하지 않는다.
3. 실제 카카오 계정 검증: **NOT_PERFORMED**. 사용자 계정에 접속하거나 대화를 전송하지 않았다.
4. 운영 활성 범위: API/GUI와 저장 schema만 반영했다. AUTO 수집·MANUAL 원격 화면·PDF
   보호 실행은 아직 비활성이다. 전용 browser/remote/pdf의 새 wheel과 dependency 검사를
   마쳤고 별도 보호 runtime publication/설치를 진행한다. 기출·창작·벡터 정본을 변경하지 않았다.
5. 다음: 보호 runtime·현재 권한 Caddy 경로 → 사용자의 실제 카카오 로그인 → 관리자 권한으로
   한 방의 조회/CSV/사진 occurrence → 저장 질문/학생 PDF의 실제 재조회·다운로드를 검증한다.
   atomic 분할/병합 저장 및 전체 방 주기 수집도 남아 있다. 부분 배포로 goal을 완료하지 않는다.
6. 실패/복구: 최초 eb9 배포는 Catalog의 TYPE_CHECKING 전용 class를 postponed annotation
   없이 참조해 중단됐다. 실패 로그/시작 marker는 보존했다. source0087을 되돌리지 않고
   successor 설치본의 실제 Catalog runner import를 확인한 뒤8e 호환 set으로 복구했다.
   successor 첫 실행의 admission receipt 누락도 원래 기록과 config-before SHA/head를
   확인하고 같은 배포의 명시적 복구로 처리했다. 이미 적용한 migration을 재실행하지 않았다.
   공식 API wheel/실제 설치 검사에도 Catalog runner import를 추가해 재발을 차단한다.

운영 evidence 위치는 `/var/lib/eom-kakao-delivery-release-8e2e11eb/api`와
`/var/lib/eom-api/deployments/8e2e11eb95d618cfcd7ee8f7ae810297d96b674e.json`이다.
이전 eb9 실패 및 원래 source/설정 백업도 별도 control directory에 보존했다.
INDEX/자료학습은 배포 전 FAILED였던 상태/설치 pin을 그대로 보존했으며 이번 작업에서
복구·재개했다고 주장하지 않는다. creative producer는 지원된 drain 후 새 호환 source로 재개했다.


## 진행 중간 저장 — 학생별 PDF의 실제 API·저장·Studio 다운로드 연결

기준 commit은 `4ba17415`다. 새 delivery wire schema를 먼저 정의하고 기존
packet/export owner, PDF executor/publisher와 Studio BFF를 연결했다. 새 migration이나
AI 호출, 별도 저장소·큐 framework는 추가하지 않았다. **아래는 합성 검증이며 실제 카카오
수집 또는 운영 활성화의 증거가 아니다.**

- 수락된 CSV/사진 → 질문 확인 저장 → exact 질문·기간 packet 저장 → 학생 PDF 요청 →
  별도 PDF subprocess → 기존 Artifact owner → 권한 검사된 HTTP/BFF 다운로드까지 연결했다.
  같은 사진 byte가 여러 메시지에 쓰인 경우 occurrence 수와 학생별 구성을 유지한다.
- Studio는 저장한 자료와 PDF 기록을 다시 읽는다. POST 응답 유실은 동일 body/key로
  확인하고, GET 상태 조회·완료 기록 재열기는 새 계산을 시작하지 않는다. 원래 publication
  이후 DB 채택 중단은 동일 attempt/command의 저장만 복구하며 재렌더하지 않는다.
- process-local bounded deque/set은 DB 작업을 깨우는 hint다. 영속 정본은 기존 export
  record이고, 재시작 뒤 명시적 원 요청 replay가 PENDING/RUNNING 복구를 깨운다.
- Catalog의 private staging parent는 기존 primary GID를 유지하고 per-attempt에만 좁은
  render group을 적용했다. 실제 cgroup 종료 확인과 종료된 원 unit의 명시적 close를
  구분한다. worker에는 DB/NAS 권한을 주지 않는다. 이 소스 검증은 운영 sandbox PASS가 아니다.
- guarded disposable PostgreSQL 최종 실행 **152 PASS / 76.81초**. 실제 API/UDS/PG와
  Studio BFF 경로, 분리 PDF process, 다운로드 동일 SHA, session 철회 후 거부,
  publication 중단/replay 무재렌더를 포함한다. 인증은 합성 fixture다.
- 새 source·브라우저 focused **26 PASS**는 FINAL 거절 뒤 수정 가능, 응답 유실 시 동일
  요청 유지, 새로고침 후 PDF 기록 재열기까지 검사한다. focused mypy 11개 PASS다.
  전체 source 회귀 첫 실행은 **1425 PASS / 1 FAIL**였으며 실패는 배포 검사의 옛0084
  기대값이었다. 현재 source0087과 기존 공식 installer callback을 대조해 정렬했다.
  수정 후 release/context/delivery 집중 검사는 **45 PASS**, schema audit는
  canonical1463 / mirror1109 / reference12550 PASS다. 개발 index의 경로 상한을 넘긴
  첫 문맥 수정은 경로를 중복 나열하지 않도록 정리했으며 runtime 계약은 바꾸지 않았다.
- 질문 분할/병합의 영속 API 연결, 실제 수집 source admission, 실제 한 방과 전체 방 주기
  수집은 남아 있다. 이 체크포인트로 전체 goal을 완료 처리하지 않는다.
- 사용자 운영 지시: 실제 카카오는 **조회·CSV/사진 다운로드만** 수행한다. 메시지 전송,
  답장, 담당자·상태 변경, 차단/삭제/나가기는 금지다. 로그인/2단계 인증은 사용자가 한다.
  방 열기의 불가피한 읽음 효과는 관측 후 알리며 되돌리기 mutation을 하지 않는다.


## 진행 중간 저장 — 실제 질문 API·Studio 열람/확인 저장 연결

`b84952fa` 이후 기존 source/question owner를 API-only Catalog socket과 실제 API/BFF에
연결했다. 새 queue·DB migration·파일 서버·AI 호출은 없다. 이번 단계는 **합성 자료의
저장→Studio HTTP 열람/검토 저장** 완료이며 실제 카카오 수집·PDF 다운로드의 완료가 아니다.

- 질문 목록은 작은 metadata만 읽고, 상세는 exact question revision에서 원문 span과 사진
  occurrence를 해석한다. 두 개의 동일 메시지와 같은 PNG의 두 첨부 identity를 보존한다.
  deep link에 room hint가 없어도 실제 room을 다시 인가하며 잘못된 room은 거부한다.
- 사진 URL은 질문/revision/attachment ID만 받고 임의 Artifact/member/path를 받지 않는다.
  현재 owner/session/source를 FD 열기 전후 다시 확인하고, 기존 bounded length/SHA proxy를
  거친 same-origin 원본 bytes만 화면에 내보낸다. 다른 학생/owner의 사진은 보이지 않는다.
- 일반 확인/제외는 기존 parent·If-Match·멱등 key를 사용한다. 브라우저는 응답 유실 시
  동일 body/key로 다시 확인하며 다른 내용으로 바꾸지 않는다. 저장한 revision과 상태는
  새로고침·새 service instance 뒤에도 유지된다. 원문·사진은 바꾸지 않는다.
  공개 리뷰로 클라이언트가 만든 actor/시각/사진 품질 수용 stamp를 받지 않는다.
- 기존 채널의 현재 수집 불가와 수락된 질문의 읽기 불가를 구분했다. DRAFT history 열람은
  현재 backend 권한을 확인하지만 collection/export capability를 활성화하지 않는다.
- 공식 guarded disposable PostgreSQL **149 PASS (64.81초)**. 그중 새 합성 검사는 실제
  Studio BFF→HTTP gateway→API→API-peer UDS→Catalog owner→PG/Artifact를 통과해
  생성/replay·원문/사진·확인 저장/replay·목록 재조회를 수행한다. HTTP 인증은 합성 fixture이고
  Catalog는 실제 임시 Identity session/권한을 재검사한다. HTTPS/live 인증 증거는 아니다.
- Kakao source/API/BFF·브라우저·권한/의존성/문맥/배포/표시 검사 **1347 PASS**.
  이어 추가한 다섯 API-peer 거부 분기를 포함한 질문 HTTP 집중 검사 **13 PASS**다.
  겹치는 수를 합산하지 않는다. 변경 core 9개 focused mypy, Ruff/format, shell와 schema
  audit(1462 canonical / 1108 mirror / 12537 reference) PASS다.
- 최초 브라우저 실행은 ambient Node18과 headless shell이 없는 새 runtime을 잘못 선택해
  실행 전 실패했다. 기존 설치된 Playwright/Chromium test 환경으로 재실행했다. 첫 신규
  BFF fixture의 중복 Host와 publisher filename 추정도 수정해 실제 계약과 대조했다.
  통합 검사의 Web source 경로 누락은 해당 guarded purpose 안에서만 보완했다.
  기존 Starlette/httpx deprecation warning은 유지하며 운영 의존성은 바꾸지 않았다.
- 운영 DB는 여전히 **0084**, source head는 **0087**이다. 이번 API/Web/Catalog 소스는
  아직 배포하지 않았다. 앞선 83203f88 wheel 준비본에는 이번 연결이 없으므로 새 후보로
  다시 빌드해야 한다. 실제 카카오 계정 검증은 **NOT_PERFORMED**, AUTO/MANUAL 비활성이다.
- 다음은 packet/export의 API·실행 coordinator·Studio PDF 다운로드를 이어 붙여 합성 입력의
  첫 사용자 경로를 닫는 것이다. source 후보 수락 연결과 atomic 분할/병합도 남아 있다.
  그 뒤 호환 release/보호 runtime 배포와 실제 한 방→전체 주기 수집 검증을 진행한다.

후속 설치 패키지 검사에서 c081dd76의 committed OpenAPI가 신규 질문 routes보다 이전인 것을
확인했다. 공식 source exporter로 명세/hash를 갱신한다. 또한 공식 installer의 migration
verify callback이 source head0087이 아닌0084를 가리키던 것을0087로 정렬하고, 기존0083까지
고정돼 있던 배포 회귀 검사의 기대값/closed callback 집합을 실제 지원된0084/0087과 대조한다.
이 수정은 추가 migration 실행이나 운영 변경이 아니며 새 wheel 검증 뒤 후속 release에 포함한다.

위 정렬은 `36174ceb7f2e9e70f41165effe222e9d9788e589`로 커밋·푸시했고 OpenAPI/배포
회귀 **56 PASS**를 확인했다. 같은 commit의 공식 API four-wheel build/RECORD/격리 import·
OpenAPI 검사는 PASS다. UI는 `c081dd76e0f1a56b91d48209689f3cc9c5f2a5ae`의 공식 Web wheel
closure/빈 환경 offline 설치/97 runtime member 검증이 PASS다. API build 위치는
`/tmp/eom-api-build/36174ceb7f2e9e70f41165effe222e9d9788e589.CzFLjX/dist`, Web은
`/tmp/eom-web-gui-build/c081dd76e0f1a56b91d48209689f3cc9c5f2a5ae.W5MlXf/dist`다.
이 패키지 검증은 아직 운영 migration·서비스 교체·실제 질문 PDF 제공의 증거가 아니다.

## 진행 중간 저장 — 영속 출력 요청·claim·현재 권한 파일 열기

`99f97a65` 뒤에 기존 PDF executor/publisher를 바꾸지 않고 export 저장 owner를 연결했다.
이번 완료 범위는 **저장 use case와 실제 PDF 파일 adapter의 합성 입력 검증**이다.
API/BFF/GUI 출력 경로와 보호 worker 활성화, 실제 카카오 수집은 여전히 미연결이다.

- 한 학생의 exact packet revision/subset와 renderer/font/layout pin으로 build를 고정한다.
  같은 요청은 원래 ID를 재사용하고 같은 build의 다른 key도 작은 receipt만 추가한다.
  배포 뒤 renderer profile이 달라져도 이전 key는 이전 요청·출력과 연결된다.
- 실제 동시 접수와 claim에서 한 export·한 실행 승자만 생성된다. 조회/접수 replay는
  렌더를 시작하지 않는다. 긴 파일 I/O 중에는 DB row lock을 잡지 않는다.
- 실제 PDF 발행 뒤 새 service instance가 DB 채택만 이어서 수행했다. 완료 목록·상세와
  같은 PDF 파일을 두 번 다시 열어도 render 호출은 1회였다. 현재 session/source 검사를
  파일 FD를 열기 전후에 수행하며, 열기 중 권한 철회 시 FD도 닫는 것을 확인했다.
- 실제 프로세스 정지 callback이 거부하면 RUNNING을 보존한다. 명시적인 exact 실패
  attempt retry만 새 attempt/fence를 만들며 기존 FAILED 기록을 수정하지 않는다.
  다른 학생/바뀐 command/다른 hash의 출력은 채택하지 않는다.
- 최초 query-plan 추가 검사만 143 PASS/1 FAIL이었다. 작은 fixture에서 optimizer가
  동등하게 유효한 owner index를 고른 것을 잘못 실패로 판정한 경우였다. 실제 indexed
  lookup과 정확한 unique build B-tree 정의를 함께 검사하도록 고쳤다. 목록용 index는
  기존 unique(owner,binding,export)가 같은 연산을 지원하므로 중복 생성하지 않는다.
- 변경된 미출시 migration을 **새로운** 공식 guarded disposable DB에 처음부터 적용했다.
  최종 PostgreSQL **144 PASS (55.37초)**, 합동 소스/권한/배포 경계 **1186 PASS**, mypy
  4개 core와 formatter/linter/shell 검사 PASS다. schema audit는 canonical 1461 /
  mirror 1107 / reference 12525 PASS다. 기존 테스트 결과와 수를 합산하지 않는다.
- source head는 `20261116_0087`이다. 운영 반영용 context/admission 1.27과 exact
  0084→0087/0087 read-only callback을 기존 operator에 추가했다. 1.26 bytes/의미는
  보존했다. **아직 운영 적용하지 않았고** 실제 운영은 앞선 0084 release 그대로다.
  새 source를 옛 exact-head context로 설치하지 않는다.
- 다음은 이 owner를 실제 API·Studio와 실행 coordinator에 연결하고 같은 합성 입력의
  인증 다운로드를 완주하는 것이다. 그 뒤 호환 운영 release/보호 renderer를 적용하고,
  원격 화면에서 사용자 카카오 관리자 로그인 → 실제 한 방 수집/PDF → 전체 주기 수집으로 간다.

소스 변경은 `83203f881f8e6f4cbf27a6bfb109cb717db62dc2`로 커밋·푸시했다. 이 정확한
commit의 공식 API four-wheel build/RECORD 검증을 통과했고 protected operator source/wheel
staging도 준비했다. 이 준비는 ADMIT/DDL 적용/서비스 교체가 아니다. 현재 운영 DB 0084와
API/Web은 변경하지 않았다. 후속 API·Studio 연결 전 준비본을 전체 기능 운영 완료로 보고하지 않는다.

## 진행 중간 저장 — 저장된 대화·사진에서 학생별 PDF까지

`871e2df3` 뒤에 기존 source/question/packet owner와 renderer/Artifact publisher를 연결했다.
이 단계는 **실제 저장소와 별도 PDF subprocess를 사용하는 합성 입력 검증**이다. Studio의
다운로드 API, 보호된 운영 worker, 실제 카카오 계정 수집의 완료를 뜻하지 않는다.

- `resolve_student`의 exact selection만 local staging 아래 새 전용 입력 디렉터리에
  물질화한다. 원본 사진은 검증된 Artifact FD에서 고유 pointer별 한 번 읽고 bytes를
  바꾸지 않는다. 같은 PNG가 두 메시지에 붙은 경우 binary는 한 번 읽되 사진 occurrence
  두 개와 순서는 실제 PDF에도 남는다. NAS를 worker 입력 폴더로 사용하는 것은 거부한다.
- 임시 PostgreSQL의 CSV·사진 수락 → 질문 저장·확정 → FINAL packet → 실제 PDF 렌더 →
  canonical Artifact 발행·검증된 파일 재조회가 통과했다. 같은 이름의 서로 다른 학생을
  별도 한 페이지 PDF로 출력하고 다른 학생의 문장이 섞이지 않음을 확인했다.
- 같은 완료 attempt의 publication replay는 같은 output pointer를 반환하며 추가 render를
  하지 않는다. 이는 아직 없는 HTTP export 요청의 멱등 검증을 대체하지 않는다.
- 다른 학생 selection, 잘못된 font hash, 파일/디렉터리 링크, NAS 입력 경로, 기존 파일이
  있는 입력 폴더를 거부한다. 물질화 뒤 session이 철회되면 결과를 반환하지 않고 실패한
  staging을 보존한다. PDF subprocess에는 DB URL·인증정보를 상속하지 않는다.
- 공식 guarded PostgreSQL 최종 검사 **135 PASS (42.62초)**, 변경 Python formatter/linter,
  입력 adapter mypy 및 `git diff --check` PASS다. 앞선 동일 경계의 134 PASS 뒤 NAS 경로
  거부 검사를 추가한 결과이며, 겹치는 수를 합산하지 않는다. 기존 source unit 1081 PASS와
  개발 문맥 13 PASS도 참조한다.
- wire schema·DB migration·운영 runtime을 추가 변경하지 않았다. source head는 0086,
  운영은 앞서 기록한 0084 release 그대로다. 다음 연결은 영속 export 접수·완료 pointer와
  현재 권한을 확인하는 API/Studio 조회·다운로드이며, 실제 카카오 한 방/전체 수집도 남는다.

## 진행 중간 저장 — packet owner, 0a812810 이후 소스 작업

사용자가 goal을 다시 등록하면서 검증·커밋·푸시·운영 배포를 명시했다. 전체 범위는
합성 입력의 PDF·Studio 다운로드 완주 후 실제 카카오 한 방, 전체 방 주기 수집까지다.
이 중간 저장은 그 완료를 뜻하지 않으며 추가 로그인은 아직 요청하지 않았다.

- 기존 질문 batch resolver와 packet publisher를 재사용해 선택한 exact question revisions,
  순서, KST 기간, 답변 포함 설정, DRAFT/FINAL을 저장하는 packet owner를 추가했다.
  제목은 작은 불변 DB revision 값이며 원문·사진·큰 선택 목록은 복사하지 않는다.
- 같은 요청 동시 접수, 발행 직후 중단·원래 Artifact 재사용, competing parent/version CAS,
  과거 packet 재조회, 이후 질문 수정 뒤에도 원래 선택 유지가 실제 임시 DB에서 통과했다.
- 합성 학생 2명의 질문을 같은 packet에 저장하고 새 service instance로 다시 열었다.
  `resolve_student`가 해당 학생의 exact question/source만 반환하며 같은 표시 이름으로
  학생을 합치지 않는 것을 확인했다. 잘못된 학생·다른 owner·철회된 session은 거부한다.
- 여러 방 접근은 기존 현재 Identity/binding 확인과 indexed room batch로 연결했다.
  source closure의 현재 권한/metadata를 확인하되 방마다 같은 Identity 조회를 반복하지 않는다.
- 최종 source unit·권한·문맥·이전 계약 **1081 PASS**, 공식 guarded PostgreSQL
  **126 PASS**, 변경 core 5개 mypy·formatter/linter와 schema audit PASS다.
  canonical 1459 / mirror 1106 / reference 12499이며 겹치는 테스트 수는 합산하지 않는다.
- 새 source head `20261116_0086`은 disposable DB에만 적용했다. 실제 운영은 기존
  0084 compatible release 그대로이며 AUTO/MANUAL과 실제 질문 PDF 제공을 활성화하지 않았다.
  공개 API/GUI, atomic 분할/병합, export claim/실제 renderer/private download와
  카카오 관리자 계정의 한 방/전체 방·주기 실증은 계속 남는다.

## 진행 중간 저장 — 질문 owner, 832a4803 이후 소스 작업

외부 검토 기준 뒤에 추가한 **질문 저장 use case의 소스/격리 검증**이다. 다음 사용자
체크포인트의 목표는 계속 CSV·사진 → 편집 → packet → 학생별 PDF·Studio 다운로드이며,
아래 중간 저장을 그 경로의 완료나 운영 활성화로 보고하지 않는다.

- accepted source의 `turn_v1` 후보를 새 논리 질문으로 등록하고, exact revision의 본문
  조회·확정/제외/선택 수정과 metadata 목록을 저장하는 owner를 추가했다. 생성 ID·시각·
  mapping pin을 예약한 뒤 I/O 밖에서 기존 publisher를 사용하고 CAS로 채택한다.
- 동일 intent 동시 접수·다른 intent의 competing edit·발행 직후 중단/재전송을 실제 임시
  PostgreSQL에서 확인했다. 중단 재개는 원래 논리/revision/Artifact pointer를 재사용한다.
  같은 시각·동일 문장인 두 occurrence도 두 개로 유지하며 DB에는 본문/사진을 넣지 않는다.
- packet/export용 exact batch resolver는 입력 순서를 유지하고 고유 source당 한 번 해석한다.
  같은 질문의 서로 다른 두 저장 버전을 읽어도 원본 resolution 해석 호출은 한 번이다.
  현재 binding/room/Identity 권한과 accepted source closure를 I/O 뒤 다시 확인한다.
- 첫 합동 DB 실행은 110 PASS/2 FAIL이었다. 새 head 상수 갱신 누락과, 테스트가 불변
  Artifact approval을 수정하려던 잘못된 fixture였다. source 철회는 실제 binding retirement
  use case로 검증하도록 바로잡았으며 immutable guard를 해제하지 않았다.
- 수정·batch resolver와 재기동 후 표시 교정 보존 확인 뒤 공식 disposable DB 검사 **115 PASS**, Kakao 관련 전체 unit과
  권한/의존성/개발 문맥/이전 release 계약 검사 **1062 PASS**다. unit 전체의 첫 invocation은
  선택적 Pillow가 없는 API interpreter여서 collection 오류였다. 기존 테스트용 Pillow
  11.3.0 materialization을 명시해 재실행했으며 운영 API 의존성은 바꾸지 않았다.
  변경 5개 core 모듈 mypy, formatter/linter, canonical/mirror/reference audit도 PASS다.
- source migration은 `20261116_0085`이며 실제 적용은 guarded disposable DB에만 했다.
  운영은 앞선 0084 compatible set 그대로다. 이후 운영 반영 전 새 head의 compatible
  release/context를 준비해야 하며, 1.26/0084로 새 소스를 배포하지 않는다.
- 아직 미연결: 공개 질문 API/GUI, 분할·병합의 atomic adoption, packet/export owner와
  인증 파일 다운로드, 실제 카카오 로그인·한 방/전체 방 수집·정기 실행.
  실제 카카오 계정 실증은 여전히 NOT_PERFORMED이며 추가 인증 요청은 아직 하지 않았다.

## 운영 부분 배포 결과 — 2026-11-16 10:55 UTC

사용자가 요청한 **미완성 기능의 부분 운영 배포**를 완료했다. 전체 KakaoTalk goal은
계속 진행 중이며, 이번 결과를 카카오 로그인·실제 대화 수집·학생별 PDF 완성으로
해석하지 않는다.

- API/platform/Catalog/QUERY와 기존 runner의 설치 source는
  `e355e7de8c7ffa1c3534717d754ed58d08b3e1d6`, Web은
  `8d8823a6da47c714f82015bb2a64b7dbb835e7df`인 호환 묶음이다. 마지막 source 변경은
  백엔드 권한 검사이므로 동일 UI를 다시 빌드하지 않았다. 실제 DB head는 `20261116_0084`다.
- `일반 → KakaoTalk`의 연결 준비·학생/방 화면과 해당 API/BFF를 반영했다. 새 화면 JS의
  HTTPS 응답 SHA는 source와 일치하고, 비로그인 source-binding 조회는 HTTP 401이다.
  실제 사용자 세션으로 설정/학생 CRUD를 수행한 live acceptance는 아직 별도 미확인이다.
  이후 사용자가 운영 GUI를 직접 확인하고 화면이 좋다고 응답했다. 이는 화면 확인 결과이며
  아직 실행하지 않은 카카오 수집·질문 저장·PDF 출력의 성공으로 확대하지 않는다.
- API 직접 ready와 HTTPS BFF ready, HTTPS 로그인 페이지는 정상이다. Catalog·QUERY·
  채팅 owner/worker·HWPX·네 개 Workflow runner와 creative owner의 active 상태를 확인했다.
  active/ready는 새 카카오 업무의 전체 성공이나 모델 작업 완료를 뜻하지 않는다.
- AUTO 수집과 MANUAL 원격 로그인은 비활성이다. 기존 브라우저 인증·비밀번호·채팅 모델을
  변경하지 않았다. 아직 준비본인 전용 runtime을 활성 release로 표시하거나 게시하지 않았다.
  질문/packet/export의 영속 owner와 실제 PDF 제공은 다음 구현으로 남는다.
- 최초 `8d8823a6` 반영 뒤 Catalog 시작이 기존 Identity fence와 충돌했다. 원인은 Kakao
  권한 확인에 필요한 세션 metadata 5열 읽기와, 이전 fence의 모든 세션 열 읽기 금지가
  양립하지 않는 것이었다. `e355e7de`에서 Identity가 정확한 5열 목록을 소유하고 Catalog
  grant와 fence가 함께 사용하도록 수정했다. 전체 세션 조회·추가 열·token/credential 읽기·
  IAM 쓰기 금지는 유지하며 actor/업무 권한을 넓히지 않았다. 최초 실패 기록은 보존했다.
- 이 수정은 SQL/설치/grant 집중 검사 60 PASS, 관련 fence 검사 93 PASS와 별도 disposable
  PostgreSQL 16 PASS를 통과했다. 실제 DB 검사는 허용된 metadata와 추가 열·전체 SELECT·
  UPDATE 거부를 함께 확인한다. 겹치는 테스트 수를 합산하지 않는다.
- 최종 배포의 `activated.json`, 설치 member 검사와 변경 전후 설정 hash는 protected release
  기록에 보존했다. 최초 migration/admission 기록과 수정 release의 기록은 별개다.
  수정 source 자체의 `ADMIT`와 배포 후 `API_ISOLATION_VERIFY`도 PASS다. 이것을 최초
  migration을 다시 실행한 증거로 해석하지 않는다. 새 schema에 옛 exact-head API를
  다시 올리는 rollback은 하지 않는다.
- INDEX와 자료 학습 owner는 이번 배포 **이전부터 FAILED**였으며 같은 Invocation을
  보존했다. numerical runtime/INDEX 설정은 바꾸지 않았고 이번 배포로 복구했다고
  보고하지 않는다. 기존 정본·풀이·벡터·실패 이력도 수정하지 않았다.

## 운영 부분 배포 요청 — 2026-11-16

사용자가 전체 기능 완성 전에 운영 배포를 요청했다. 소스의 0084와 호환되는
release context 1.26을 추가하고 기존 배포 경계를 재사용한다. 수집/질문/packet/export
후속 owner 완료를 기다리는 것이 이번 부분 배포의 선행조건은 아니다.
단, 브라우저 MANUAL runtime·remote transport·자동 수집은 비활성 상태로 유지한다.
현재 가능한 연결 준비·학생/방 조회 화면과 실제 미완성 기능을 구별한다.
팀원의 미사용 약속을 권한·기능 차단의 대체물로 사용하지 않는다.
기존 운영 0079에서 0084로 전환하며, 적용 후 구형 exact-head API를 그대로 복구하지 않는다.
운영 완료 여부·설치 commit·실제 health는 배포 후 별도 기록한다.

## 최신 후속 — 2026-11-16 원본 수락과 질문 입력 연결

이번 변경은 `4d190c32` 이후의 **소스/임시 DB 검증 단계**다. 실제 카카오 로그인,
collector activation, 운영 DB migration 및 사용자 PDF 다운로드 성공을 뜻하지 않는다.

- 원본 CSV·정규화·사진과 실제 capture command/result/capability/attempt/fence를 연결하는
  source 수락 owner를 추가했다. occurrence는 같은 문장이라도 별개로 보존하며, 새 snapshot은
  이전 revision을 덮지 않는다. 검증되지 않은 발신 역할·provider ID·문맥 완전성의 과대 주장을 거부한다.
- 사진은 PNG/JPEG/WebP의 실제 decode·크기·정적 이미지 여부를 검사하고 원본 bytes·EXIF·SHA를
  보존한다. 같은 blob의 여러 첨부 occurrence는 유지하되 해당 요청에서 검증용 원본/receipt를
  한 번씩만 읽는다. 원본/긴 본문은 Artifact, DB에는 작은 identity·pointer·상태만 저장한다.
- `resolve_question_source`가 수락된 exact revision을 기존 질문 후보 규칙에 연결한다.
  현재 owner 권한·원본 lifecycle을 I/O 이후에도 확인한다. 질문/packet의 durable 편집·발행 owner와
  공개 API/GUI 연결은 아직 후속이며, 이 resolver 자체를 전체 기능 완료로 표시하지 않는다.
- 초기 설치에는 Catalog의 필요한 sandbox 경로/control group과 Caddy proxy group을 명시한다.
  최초 profile receipt의 설치 SHA는 후속 manifest로 바꾸지 않고 stage/verify 때 다시 대조한다.
  MANUAL driver는 실제 supervisor/profile lock 아래에서 매 실행 Xauthority를 준비한다.
  기존 VNC/Kakao 인증을 복사하거나 수정한 것이 아니다.
- 미확정 날짜 DRAFT는 실제 한 페이지 PDF에서 `날짜 확인 필요`를 표시하며 사진·본문을 유지한다.
  FINAL의 미확정 날짜 차단은 유지한다. 이 미출시 render 계약 변경으로 이전 준비본의
  pure contracts/PDF worker/관련 collector wheel은 활성화 전 새 source로 재빌드해야 한다.
- 최초 DB 합동 검사는 9 FAIL/69 PASS였다. 새 owner metadata 등록 누락 1개와
  batch pointer 조회로 변경된 테스트 주입 형식 8개를 수정했다. 다음 실행의 3 FAIL/90 PASS는
  병렬 개발 중 render schema/hash 교체와 겹친 검사였으며 해당 결과를 최종 PASS로 사용하지 않는다.
- 최종 0084는 새 disposable DB `/tmp/eom-api-testdb-20261116102051_6b2f2fd4`에서
  fresh upgrade → downgrade 0083 → upgrade 0084를 통과했다. 앞선 임시 DB 기록은 보존했다.
  운영 DB·기존 문항·임베딩 결과와 서비스 실행에는 변경이 없다.
- 동결 후 재검증: Kakao unit/API·설치 wheel·개발 문맥 **1100 PASS**, 공식 disposable
  PostgreSQL **98 PASS**(신규 source 20개 포함), schema audit 1456 canonical / 1104 mirror /
  12462 reference PASS. source 6개 모듈과 media 2개 모듈 mypy, 변경 경계 Ruff/format PASS.
  기존 Starlette/httpx deprecation warning 1개는 남아 있다. 겹치는 집중 검사를 합산하지 않는다.
- 이 체크포인트의 소스를 현재 release context 1.25/0083로 운영 배포하면 안 된다.
  source 0084와 후속 owner를 포함한 최종 compatible release/context 및 전용 runtime wheel을
  확정한 뒤 설치·migration·활성화를 진행한다. 기존 4d190c32 준비본의 fingerprint를 새 소스의
  검증 결과로 사용하지 않는다.

다음 구현은 기존 질문 생성/편집/publisher를 current/revision/CAS owner에 연결하고,
그 후 immutable packet과 학생별 export/download를 연결하는 순서다. source command는
source 전용이며 capture 필드를 nullable로 늘린 범용 질문/출력 큐로 확장하지 않는다.

## 최신 후속 — 2026-11-16 runtime coordinator·현재 접속 승인

기준 source checkpoint는 `7fe0c345d3b5c95c42c72ae67e371be0988bb92c`다.
다음은 소스/격리 검증 결과이며 아직 운영 설치·카카오 인증·실제 수집 결과가 아니다.

- Catalog 현재 MANUAL intent와 고정 browser/gateway를 연결했다. 별도 bounded thread가
  같은 실행의 준비·종료를 관측하며 원래 Catalog 업무 loop를 막지 않는다. 시작 응답 유실은
  원래 staged 실행을 확인하며 새 launch로 우회하지 않는다. 만료는 기존 gateway stop으로
  즉시 닫고 browser 종료를 확인한다. 실패 이력을 성공으로 바꾸지 않는다.
- private `AUTHORIZE_KAKAO_MANUAL`은 단순 history READ와 분리된다. 현재 owner/session/
  fence/TTL → 실제 OS 관측 → 같은 revision과 권한을 다시 검사한다. API/BFF는 성공 때만
  빈 204를 반환한다. noVNC asset과 WebSocket 모두 이 경계를 통과하며 읽기는 갱신하지 않는다.
- 독립 검토에서 병렬 asset·heartbeat의 읽기 lock 충돌을 재현했다. 실제 read observation만
  짧게 직렬화하고 매 요청의 새 관측·현재 권한 검사를 보존했다. 권한 캐시나 503 무시로
  덮지 않았다. coordinator/OS/remote 집중 검사 **304 PASS**, 관련 8개 모듈 mypy PASS.
- 공식 disposable DB 후속 검사 **78 PASS**: 5개 실제 admission/predecessor 검사를 추가했다.
  통합 수정 중 import 누락으로 처음 22 FAIL/56 PASS가 발생했고, `ProfileFence` import를
  복원한 뒤 같은 공식 경로로 78개를 재검증했다. 운영 DB는 사용하지 않았다.
- WebSession은 작은 lease pointer와 응답 generation만 보관한다. 늦은 read·logout·END가
  이전 화면을 되살리지 못한다. Caddy opt-in template의 실제 로컬 proxy 검사도 수행했다.
  HTTPS origin·정적 파일 allowlist 설정은 기본 생략이며 Secure cookie·허용 host를 요구한다.
  화면은 boolean 표시 설정만 읽는다. 실제 ACTIVE lease 없이 원격 iframe이 열리지 않는다.
- Web 설정/현재 admission·실제 Chromium/remote 규칙 **136 PASS** 후, 주입 경로의 동일
  HTTPS 설정 검사를 보강해 설정/admission **49 PASS**를 확인했다. 기존 Starlette/httpx
  deprecation warning은 남아 있으며 이 변경에서 무관한 의존성을 교체하지 않았다.
- API 배포 입력은 새 context 1.25에서만 pure Kakao contracts를 포함한 정확한 4개 wheel과
  migration 0083을 사용한다. historical context 1.0–1.24의 bytes/3-wheel 의미는 보존했다.
  관련 API 배포 검증 **120 PASS**, 실제 별도 설치 wheel/import 검증 PASS다. dirty source의
  임시 build는 테스트용이며 final release로 재사용하지 않는다.
- 합동 검사 첫 실행은 **646 PASS/1 FAIL**이었다. 실패는 개발 문맥 index의 경로 43개가
  자체 40개 상한을 넘은 것으로, 중복 탐색 경로를 줄인 뒤 문맥 검사 **13 PASS**다.
  운영 기능 오류가 아니며 상한을 완화해 통과시키지 않았다.
- 후속 최종 합동 검사 **693 PASS**(API/BFF·현재 접속 승인·Chromium/Caddy·설치 wheel·
  배포/의존성/개발 문맥 포함), 실제 disposable PostgreSQL 78 PASS와 별도다. root의
  Web/pure-contract 4개 모듈 mypy·Ruff/format도 PASS다.
- Web은 기존 API 환경에 기대지 않는 빈 Web interpreter venv에서 30개 exact wheel을
  오프라인 설치하고 `pip check`, 실제 app/contract import, 95개 RECORD 검사를 통과했다.
  기존 third-party 버전은 유지하며 jsonschema의 빠진 의존성만 완전한 잠금 목록에 포함했다.
  운영 installer는 root 보호 source snapshot의 helper/lock을 독립 SHA로 검증한다.
- 고정 초기 publisher는 3개 전용 Conda prefix와 Playwright/noVNC 두 경로만 준비·검증·
  새 root inode로 게시한다. 기존 install manifest를 참조하며 기존 prefix 업그레이드나
  서비스 활성화는 하지 않는다. 관련 installer/publisher **62 PASS**, 독립 검토에서 실제
  임시 3환경의 isolated dependency 검사와 5개 tree fingerprint도 PASS다. 실제 `/opt`
  게시·apt 설치·계정 생성은 아직 실행하지 않았다. 중간 실패는 검증되지 않은 설치 상태로
  보존하고 성공 receipt를 만들지 않으며, 이를 자동 배포 성공으로 취급하지 않는다.
- 아직 남은 경계: 전용 prefix의 root 보호 설치·실제 UID/systemd/VNC·Caddy 연결, 최종
  clean-commit 호환 release 및 운영 migration, 카카오 실제 로그인/selector/한 방 수집,
  원본 수락·질문/packet/export 영속 owner 연결과 실제 PDF 제공. 구현·시험 성공을 전체
  운영 완료로 표시하지 않는다. 기존 문항/임베딩/인증 자료에는 변경이 없다.

### 다음 영속 연결의 최소 순서

0080–0083은 binding/student/room/manual owner까지만 제공한다. 공개된 질문·packet
화면 fixture와 Artifact 발행 helper가 DB 수락까지 구현했다는 뜻은 아니다.

1. source 수락 owner가 actual attempt/fence 또는 명시 수동입력 provenance, 현재 owner/
   binding/room을 검사하고 snapshot/normalization/occurrence ID를 먼저 예약한다.
   기존 parser·capture publisher를 사용하고 사진 blob은 binding+SHA로만 dedup한다.
2. 정규화·alignment·원문·사진은 Artifact, DB에는 exact pointer와 occurrence 관계만 둔다.
   기존 `ResolvedKakaoQuestionSource`를 영속 resolver에서 구성해 source 권한을 재검사한다.
3. 기존 질문 생성/편집/분할/병합·publisher를 수락 owner에 연결한다. split/merge의 입력
   supersede와 결과 current pointer는 한 transaction이며 수동 편집을 재수집으로 덮지 않는다.
4. packet은 선택한 exact question/student/mapping/기간/mode를 고정한다. export는 이 pin과
   renderer/font/layout을 예약한 뒤 기존 PDF executor·publisher로 처리한다.
5. same intent는 예약 ID·기존 publication key/완료 attempt를 재조회한다. Job metadata에는
   ID/hash/count만 남기고 새 queue/framework나 원문 JSONB를 만들지 않는다. CAS 실패는
   원래 current를 보존한다. source ACL을 확인한 private download만 기존 media transport에 잇는다.

이 후속 단계의 schema/DDL은 아직 추가하지 않았다. 먼저 합성 CSV·사진 2개 → 질문 편집 →
학생별 packet/PDF·PNG → 재조회 추가 render 0을 disposable DB와 실제 local PDF로 닫는다.
날짜가 확인되지 않은 DRAFT는 날짜 추측 대신 명시적 미확인 표시가 필요하다. 현재 render
projection의 DATE_UNVERIFIED 거부가 이 설계와 다르므로 해당 경계를 구현할 때 정합시킨다.
실제 카카오 selector·완전성·사진 연결 capability는 로그인 전 UNKNOWN을 유지한다.

## 최신 체크포인트 — 2026-11-16 MANUAL 연결·설치 전 경계

- 이전 source checkpoint `1e33207c` 이후 수동 로그인 의도/짧은 접근 허가를 저장하는
  Catalog owner와 0083 migration, 실제 API/RPC/BFF 및 화면 controller를 추가했다.
  시작 접수는 PREPARING이며 실제 browser와 gateway 준비 확인 없이 ACTIVE가 되지 않는다.
  현재 사용자·Identity session·ADMIN/remote 권한·binding owner를 다시 확인한다.
- protected 프로필 최초 설치 증거와 실제 flock, browser/gateway의 boot·invocation·cgroup·
  systemd Job 관측을 연결했다. PID 0/비활성이라도 queued Job이 있으면 인계하지 않는다.
  만료·응답 유실·이전 실행 실패를 성공이나 새 실행 권한으로 바꾸지 않는다.
- MANUAL Playwright/Xvnc driver와 별도 UDS gateway supervisor를 구현했다. gateway 종료는
  이미 열린 stream도 닫으며, 같은 grant 재읽기는 TTL을 연장하지 않는다. Catalog에는 raw
  VNC/profile cookie 접근 권한을 주지 않는다. AUTO collector/실제 selector는 후속 범위다.
- 새 Kakao 전용 환경은 `/opt/eom/conda/envs/eom-kakao-*`를 사용한다. 기존 `/srv` 환경의
  소유권을 완화하지 않는다. 고정 installer는 준비된 보호 prefix만 소비하며, 최초 profile
  receipt는 runtime 업그레이드에서도 보존한다. 실제 prefix 준비·설치는 아직 하지 않았다.
- 합동 source/API/BFF/Chromium/계약·의존성 검사 **973 PASS**, 공식 guarded disposable
  PostgreSQL **73 PASS**. 후자는 동시 접수·동일 key 재전송·갱신/종료 경합과 현재 모드
  검사까지 포함한다. 별도 설치·driver/browser/PDF 묶음 **192 PASS**, 프로필/RPC/API
  독립 검토 **47 PASS**. 겹치는 검사는 합산한 고유 테스트 수로 표현하지 않는다.
- 별도 집중 리뷰에서 잔존 gateway `.next` 파일을 최초 실행으로 오인할 수 있는 경계를
  재현해 고쳤다. 같은 파일 관측 규칙을 재사용하며 추가 3개 부정 검사를 포함한 관련
  **176 PASS**를 확인했다. 잔존 파일을 삭제하거나 실행을 강행하지 않는다.
- 전역 import 추적 mypy는 이번에 변경하지 않은 `command_adapter.py`에서 기존
  WorkflowRequest union 접근 오류 6개를 보고했다. Kakao 변경 모듈 검사는 별도로
  수행하며 이 무관한 오류를 감추기 위해 출제/자료 학습 코드를 수정하지 않는다.
- 아직 남은 활성화 경계: Catalog runtime coordinator 조립, 현재 lease의 Caddy admission,
  전용 runtime 실제 설치·UID/sandbox 검사와 호환 migration release. `remoteViewEnabled`는
  기본 꺼짐이며 소스 테스트를 운영 화면·카카오 로그인 성공으로 보고하지 않는다.
- 운영 migration·배포·카카오 로그인·수집은 이 체크포인트에서 실행하지 않았다. 기존 문항,
  GPU 실행·정본·실패 이력 및 인증 자료는 변경하지 않았다.

## 2026-11-16 착수

사용자가 제공한 [설계 정본](../architecture/KAKAO_CHANNEL_ARCHIVE_STUDIO_IMPLEMENTATION_SPEC.md)을
현재 `6d7fcde708a637aec61a1031042b2b7ae4ba1089` 기준으로 구현한다.
이 문서는 구현 진행 기록이며 운영 활성화·카카오 수집 성공 증거가 아니다.

사용자 확정 변경: 메뉴 위치는 **일반 → KakaoTalk**이다. 설계서의 사용자용
`학생 질문` 명칭보다 이 결정이 우선한다. 내부 feature/route는 `kakao-archive`를
유지하고 작업 설명은 쉬운 한국어로 제공한다. 원본 설계 문서는 보존한다.

## 작은 구현 결정

- 책임: 기존 Studio/BFF → API → Catalog 업무 소유자 → Orchestrator 격리 실행·발행.
  학생 질문은 Item/Graph/자료 학습과 다른 비공개 업무이며 그 실행 경로를 호출하지 않는다.
- 정본: 원본 CSV/사진과 긴 본문·질문/발행 manifest는 기존 Artifact. DB는 소유자,
  논리 identity, immutable revision, 상태·색인·exact pointer만 저장한다.
- 새 binding은 DRAFT, 자동 수집은 꺼짐. 실제 채널 관측 전 ACTIVE를 만들지 않는다.
  모든 접근은 현재 operator 권한과 owner를 확인하며 ADMIN에도 타인 원문을 공개하지 않는다.
- 초기 구현은 CSV 정규화·질문 후보, offline PDF, 화면 controller를 독립 검증한다.
  미구현 route를 화면에 활성화하거나 fixture 성공을 카카오 실증으로 보고하지 않는다.
- snapshot ordinal은 occurrence 정체성이며 같은 시각·같은 내용도 지우지 않는다.
  안정 ID가 없으면 bounded alignment/snapshot-only로 남기고 이름으로 역할을 추측하지 않는다.
- 조회는 owner/binding을 먼저 제한한 keyset/index 조회. 원문 순회는 O(N), 동일 bytes 조회는
  binding+SHA unique lookup, 장기 전체 O(N²) 비교를 만들지 않는다.
- 변경은 owner별 멱등 key와 request SHA, 짧은 transaction/CAS, 명시적 transition으로 처리.
  브라우저·파일 변환 동안 DB 잠금을 유지하지 않는다. worker 결과와 publication Job은 분리한다.
- 작은 불변 정책 값은 frozen DTO로 충분하다. 별도 queue/framework/DB/AI 서비스를 추가하지 않는다.
- 새 worker pure-contract wheel은 isolated PDF/browser가 Catalog·DB 의존 없이 실행하기 위한
  실제 배포 경계다. PyMuPDF는 기존 의존성을 재사용하고 browser 의존은 후속 전용 runtime에 한정한다.
- 카카오 selector·계정 capability는 아직 UNKNOWN. 인증 없이 구현할 수 있는 부분을 먼저
  완료하고, 수동 로그인은 실제 private runtime과 한 방 실증 준비 후 요청한다.

## 단계

1. P1 계약·CSV/정합/질문 규칙·offline PDF와 익명 fixture 검증 — 소스 검증 PASS.
   별도 설치 worker의 PDF 출력은 확인했지만 운영 sandbox·Artifact 발행 연결은 아직 미완료다.
2. P2 Catalog 저장·권한·UI/API 연결 — DRAFT binding 경계 소스 구현·검증 완료,
   binding·학생 disposable DB 검증 PASS. 학생 화면 연결과 대화/질문/묶음 영속 연결 진행 중.
3. P3 private browser·원격 lease·수동 인증 안전 경계 — pure 계약/종료·복구 규칙 검증,
   실제 browser/gateway 설치·영속 owner 연결은 대기.
4. P4 실제 한 방의 CSV·복수 사진 실증 — 인증 요청은 여기 직전에.
5. P5 전체 방·주기 수집·복구, P6 학생별 최종 PDF, P7 호환 설치·live 검증 — 대기.

기존 김병훈 문항 작업과 GPU INDEX는 마지막 조회에서 오류 종료 상태다. 완료된 정본·
풀이·벡터·실패 이력은 보존하며 정상 모니터링 중이라고 표현하지 않는다. 이번 새 기능의
소스 구현은 그 복구를 기다릴 필요가 없고, 공유 설치본 변경은 실제 실행 상태와 조율한다.

## P2 제한된 binding 저장 경계

- Catalog가 owner별 연결 설정만 저장한다. 현재 구현 범위는 DRAFT 생성/조회,
  정책 successor와 RETIRE이며 실제 채널 검증·수집·schedule 활성화는 포함하지 않는다.
  브라우저의 채널 확인 주장을 ACTIVE 근거로 받아들이는 명령은 만들지 않는다.
- 정본은 binding의 owner/lifecycle/current pointer, 작은 immutable 정책 revision,
  immutable command receipt 세 테이블이다. 대화·학생·파일·인증정보는 여기에 없다.
  논리 ID와 정책 revision ID 및 canonical 정책 SHA를 분리한다.
- owner+binding key 조회와 owner+binding ID keyset 목록은 B-tree를 사용해
  O(log B + page size), 명령 재전송은 owner+scope+key unique 조회를 사용한다.
  정책 previous/current pointer는 같은 binding의 revision만 composite FK로 연결한다.
- 한 명령은 짧은 transaction에서 현재 Identity permission/ADMIN 역할/세션과 owner를
  확인하고 멱등 request SHA, resource_version/parent CAS, 정책·receipt를 함께 확정한다.
  동일 intent advisory lock과 unique 제약으로 concurrent replay를 합친다. DB 잠금 중
  browser/NAS/worker 작업은 없다. 권한 조회는 Identity의 기존 repository를 재사용한다.
- 같은 key의 다른 내용은 conflict, stale parent/version은 precondition failure다.
  replay는 현재 권한을 재확인하고 원래 result revision을 반환한다. RETIRE는 삭제가
  아니며 정책·receipt UPDATE/DELETE는 기존 immutable trigger로 금지한다.
- 현재 DB 인증과 짧은 application transaction을 사용하며 별도 ACL framework,
  scheduling queue, auth store 또는 generic event-sourcing을 추가하지 않는다.
  하나의 가변 정책 행만 두는 대안은 재전송·기존 실행 pin을 보존할 수 없어 제외한다.
- migration은 새 0080과 ADMIN 전용 5개 permission seed로 한정한다. source/DDL 검사와
  실제 disposable PostgreSQL 동시성 PASS를 구분하며 운영 migration은 별도 단계다.

P2 초기 소스 검증: binding 계약·파서/질문·Catalog 최소 권한·기존 bootstrap 회귀 80개 PASS,
새 owner 소스 5개 mypy PASS, Ruff/format PASS. 당시 PostgreSQL 13개는 임시 DB 준비 전
SKIPPED였다. 아래 후속 실제 검증이 이 미실행 경계를 닫으며 초기 결과를 소급 변경하지 않는다.
Catalog 설치 권한은 새 테이블 3개 SELECT/INSERT 및 binding만 UPDATE다. 현재 세션
확인은 `api_sessions`의 ID·owner·철회·만료 5개 열 SELECT만 추가하며 token/credential
조회, Identity 변경, API/worker의 archive DB 권한은 추가하지 않는다.

## 일반 → KakaoTalk 화면과 HTTP 경계

- 기존 Studio 메뉴·안내 모드·권한·뒤로가기 경로에 `일반 → KakaoTalk`을 연결했다.
  기존 세션 owner가 바뀌거나 종료되면 선택과 원문 화면을 비운다.
- 현재 공개 API는 연결 초안 생성/조회/정책 변경/종료뿐이다. BFF는 실제 공개된
  DRAFT/RETIRED DTO를 사용하며, NOT_VERIFIED에서는 방 조회·수집·원격 로그인·PDF
  요청을 호출하지 않는다. 후속 화면 fixture는 그 API가 운영에 존재한다는 증거가 아니다.
- API → private Catalog RPC → Catalog owner를 기존 경계에 추가했다. 실제 세션,
  권한·owner, 멱등 key, If-Match/CAS, reply identity·policy pin을 검증한다.
- 합동 검증 200개 PASS: CSV·질문 규칙·Artifact intake·binding/RPC·offline PDF·
  실제 API/BFF HTTP·Chromium 화면·개발 문맥·의존성 경계. HTTP 항목은 실제
  TestClient/gateway와 가짜 Catalog owner를 결합한 것이며 운영 DB 검증이 아니다.
- 별도 기존 shell/안내 모드/어휘/route/배포 파일 목록 회귀 54개 PASS.
- 소스 OpenAPI와 schema mirror를 갱신했다. 운영 설치본·migration·카카오 인증은
  변경하지 않았으며, 실제 수집/학생별 발행/live PASS는 아직 선언하지 않는다.
- 다음 설치 전 필수: 0081까지 지원하는 release context,
  호환 platform/API/Web 및 private runtime 검증. 현재 0079 배포 절차를 그대로
  사용해 새 migration을 설치하지 않는다.

## 2026-11-16 학생 디렉터리·실제 PostgreSQL 후속

- `kakao_students.py`와 Catalog 학생 서비스·0081 migration을 추가했다. 이름은 key가
  아니며 동명이인, 표시 이름 successor, 소속 owner 확인, retirement, exact revision
  조회를 지원한다. large content/사진/credential을 DB에 넣지 않는다.
- 학생·binding의 멱등 잠금/정규 직렬화만 좁은 공통 함수로 재사용했다. 현재 권한 확인과
  domain별 state/CAS는 담당 서비스에 남겼다. 별도 generic repository/queue는 없다.
- Linux 인증 후 공식 guarded prepare로 생성한 임시 DB:
  `/tmp/eom-api-testdb-20261116044952_78727a2c`.
  운영 DB에는 연결하거나 migration을 적용하지 않았다.
- 처음 실제 실행: 18 PASS / 3 FAIL. 변경 차단 자체는 작동했지만 테스트가 PostgreSQL
  드라이버의 `ProgrammingError`를 `InternalError`로 예상했고, 좁은 metadata 검사가
  무관한 미등록 ORM의 FK까지 정렬했다. 예외의 실제 immutable 메시지를 검증하도록
  고치고 이 owner의 직접 metadata 비교와 별도 전체 composition 검사를 분리했다.
- 재실행 21 PASS, 이어 전체 Alembic/ORM composition 포함 **22 PASS**. 4개 동시 생성은
  한 identity/receipt, 같은 부모의 동시 이름 변경은 한 successor, exact replay와
  이전 표시 revision 보존, 타인 ADMIN·철회된 세션 거부, immutable trigger·composite FK,
  keyset 3페이지의 일정한 join 조회까지 실제 PostgreSQL에서 확인했다.
- 학생 소스/계약·기존 binding 회귀 81 PASS, owner 관련 5개 소스 mypy PASS.
- 임시 DB는 다음 같은 기능의 영속 검증에 사용할 수 있게 아직 보존 중이다. cleanup은
  실행 완료 후 별도로 기록한다. 이 PASS가 카카오 수집·원격 인증·운영 배포를 뜻하지 않는다.
- 학생 public RPC/API/BFF/UI, private remote lease와 PDF 실행 adapter를 연결 중이다.
  카카오 실제 계정 로그인은 아직 요청하지 않았다.

## 2026-11-16 P2 화면·질문/PDF 연결 체크포인트

- 학생 생성/목록/정확한 revision 조회/이름 변경/사용 중지를 기존 Catalog socket,
  API/BFF, `일반 → KakaoTalk`에 연결했다. 방 mapping을 이름으로 추측하지 않는다.
  현재 READ/EDIT 권한과 owner를 검사하며 표시 이름이 같은 학생도 별개 identity다.
- 학생 controller는 채널 선택과 독립된 owner/응답 순서 검사를 사용한다. 계정 변경,
  권한 철회·늦은 응답, 이전 revision에 대한 변경, 같은 intent 재조회가 검증됐다.
  미확정 intent는 같은 페이지 이동에서는 유지하지만 hard reload/login reset 이후
  복구는 아직 영속 owner/조회 UX 연결이 필요하다. browser에 개인 원문/세션을 저장하지 않았다.
- 순수 질문 편집·분할/병합·packet 선택과 기존 Artifact 발행 adapter를 연결했다.
  원문·사진을 packet마다 복사하지 않으며 source span/hash와 사진 occurrence/revision,
  학생·mapping pin, FINAL blockers를 exact 질문에서 재검증한다.
- 학생 subset → local render projection → 실제 한글·사진 PDF/PNG까지 익명 fixture로
  통과했다. 문장→사진→문장 순서, 명시적 회전/crop, 원본 불변, 파생 hash를 보존한다.
  같은 요청의 worker 재실행이 아니라 동일한 종료 attempt 결과 수락 복구를 구현했다.
- 통합에서 발견해 수정한 두 문제: PDF 하단 float 누적 `790.0000000000001`은
  조판 좌표를 1e-6 pt로 고정해 실제 790 pt 경계를 유지했다. 또한 packet의 binding만
  다른 값으로 바꿀 수 있던 projection 검사를 추가했다. 각각 실제 PDF와 부정 fixture로 확인했다.
- 수집 command/result·capability·inventory의 순수 계약도 추가했다. worker 결과가
  미확인 capability를 full-history/원본 화질/확인된 방향으로 승격할 수 없으며,
  unsupported 사진도 실패 사유와 함께 남긴다. 실제 selector·수집 실행은 아직 없다.
- 최종 합동 소스 검증 **582 PASS**: Kakao 계약·파서·권한·RPC/API/BFF, 실제 Chromium,
  질문/packet·local PDF·중단 후 수락·remote/capture 규칙, 설치 platform wheel import,
  OpenAPI·개발 문맥·의존성 경계. 앞의 disposable PostgreSQL **22 PASS**와 별도다.
- 기존 shell/GUI 회귀 25 PASS/1 environment SKIP 후, 같은 opt-in Playwright 환경으로
  해당 파일을 다시 실행해 **4 PASS**. 전체 582 검사에는 Kakao 실제 Chromium이 포함된다.
  FastAPI TestClient의 기존 Starlette/httpx deprecation warning 하나는 남으며 새 의존 설치로 우회하지 않았다.
- schema audit: canonical 1441 / mirror 1092 / reference 12326 PASS. Ruff 64개 파일·format PASS.
  별도 non-editable pure-contract/worker wheel에서도 실제 한글·사진 PDF 생성 PASS.
  이는 같은 사용자 권한의 로컬 설치 검증이며 전용 UID/systemd sandbox PASS가 아니다.
- 설치 worker의 collection schema는 소스와 같은
  `sha256:9c9cd7cc4438a194acd157775261b4ac846e0b7ab12ee2aa05e79560777746ce`다.
  render/layout은 각 package-owned hash로 검증한다. 사진 원본이나 실제 학생 자료는 사용하지 않았다.
- 남은 핵심: Catalog room·불변 학생 mapping/원본 수락, 저장된 owner intent 기반 주기
  실행·fence, private 파일 전달과 question/packet/export 영속 연결, 브라우저/원격 runtime,
  실제 capability/CSV·사진 실증, 호환 운영 배포. 현재 학생/API 소스 PASS를 전체 완료로 보지 않는다.
- 다음 한 가지는 room·학생 mapping 저장 경계다. 검증된 binding별 source identity만
  canonical room으로 연결하고 worker가 제안한 room ID나 닉네임을 정본으로 믿지 않는다.
  자세한 최소 순서는 `KAKAO_COLLECTION_EXECUTION_BOUNDARY.md`에 기록했다.
- 운영 API/Web/Catalog·카카오 계정·기존 문항/벡터에는 변경이 없다. 새 로그인 요청도 없다.

## 2026-11-16 P2 방 연결·PDF 발행 및 P3 프로세스 경계

기준은 로컬 구현 체크포인트 `d37dc7dd` 이후 변경이다. **운영 배포·실제 카카오 수집은
아직 하지 않았다.** 이번 검증에는 합성 이름/대화/그림만 사용했다.

- 확인된 방의 canonical identity와 학생 mapping을 0082에 저장한다. 최초 원본·관측
  Artifact를 현재 owner 권한으로 재확인하며, 공개 임의 방 생성 API는 없다. 이름으로
  학생/방을 합치지 않는다. 연결·해제는 version/parent CAS, exact 학생 표시 revision,
  같은 요청 재확인과 불변 이력을 유지한다. 목록은 기존 unique B-tree와 한 bounded join을
  사용하며 같은 열의 중복 index는 만들지 않았다.
- Studio 방 목록·학생 연결·해제까지 기존 RPC/API/BFF에 연결했다. 새로고침 후 확정된
  DB 상태를 읽고 늦은 응답·다른 owner 응답을 차단한다. 미확정 변경의 intent 복구는 같은
  페이지 세션 범위이며, 새로고침을 넘는 미확정 intent 복구까지 구현했다고 주장하지 않는다.
  학생·방 이름과 사유의 길이는 UTF-16 길이가 아닌 schema의 Unicode code point 기준으로
  맞췄고, 이모지·ZWJ 조합을 실제 Chromium에서 확인했다.
- `kakao_pdf_publication.py`가 core에 수락된 PDF/PNG/layout을 기존 Artifact owner로
  발행한다. export+attempt의 원래 발행을 재사용하며 재렌더하거나 PDF를 다른 정본으로
  복사하지 않는다. DB/Job에는 ID·hash·count만 저장한다. 실제 export DB 수락과 비공개
  다운로드 use case는 다음 단계이며 이 helper의 PASS와 구분한다.
- 최초 PDF 소스 검사에서 5 FAIL/13 PASS를 확인했다. 유효한 원본 render JSON의 생략된
  optional field가 Pydantic 직렬화에서 추가되어 hash가 달라지는 문제였다. 원래 입력
  bytes를 검증하도록 수정했으며, whitespace/생략 필드도 보존하는 18개 focused 검사가
  통과했다. 입력 hash 검사를 제거하거나 옛 결과를 변경하지 않았다.
- 실제 임시 DB에서 0082 적용·되돌리기·재적용을 확인했다. 첫 migration 검사에서 source의
  예상 head가 0079였던 차이를 발견하여 `CURRENT_MIGRATION_REVISION`을 0082로 맞췄다.
  현재 운영 release operator의 0079 지원을 몰래 넓히지는 않았으며, 운영 설치에는 별도
  compatible release/context successor가 필요하다.
- 첫 통합 DB 검사: 40 PASS/8 FAIL. 하나는 좁은 metadata 테스트에 신규 Artifact FK의
  dependency가 빠진 경우였고, 일곱은 negative fixture가 이미 승인된 Artifact를 직접
  UPDATE해 기존 immutable trigger가 차단한 경우였다. metadata 검사는 FK closure를
  포함하고, replay fault는 read boundary에서만 주입하도록 고쳤다. trigger/FK를 끄거나
  approved 정본을 수정하지 않았다. fault 제거 뒤 원래 정본의 replay도 확인한다.
- 후속 공식 guarded DB 검사 **48 PASS**: 기존 binding/학생, 신규 room 23개, PDF 발행
  3개, 전체 Alembic/ORM composition. 같은 키의 동시 admission·mapping, 경쟁 CAS·학생
  rename 경합, 권한·source 검증, publication 중단/응답 유실·재조회와 원본 불변을 확인했다.
  disposable DB는 후속 검증을 위해 보존하며 운영 DB 테스트는 하지 않았다.
- 합동 소스 검사 **733 PASS**: 계약·RPC/API/BFF·Chromium·PDF·설치 platform wheel·
  OpenAPI·의존성/개발 문맥. 이후 browser/room/context의 최종 변경 검사는 **93 PASS**.
  새 핵심 소스 14개 strict mypy PASS, Ruff/format와 shell syntax PASS.
  기존 Starlette TestClient deprecation warning 한 건은 별도 의존 교체 없이 유지했다.
  schema audit는 canonical 1445 / mirror 1096 / reference 12390 PASS다.

### 별도 브라우저 실행 경계

- AUTO/MANUAL은 하나의 고정 unit과 실제 profile flock을 공유한다. fixed driver만
  실행하고, 현재 owner/fence 확인과 실제 invocation/boot/cgroup 종료를 요구한다.
  초기화 marker·per-run 입력을 보존하여 불확실한 시작을 새 실행으로 위장하지 않는다.
- 실제 subprocess 검사에서 SIGTERM 처리 중 driver가 7로 종료한 것을 supervisor가 0으로
  덮던 결함을 발견해 수정했다. 정상 close/flush, 실패 종료, 강제 timeout을 구별한다.
  supervisor/OS adapter 61개 검사와 별도 non-editable wheel 검증을 통과했다.
  이는 현재 사용자 권한의 local 검증이지 전용 UID/systemd sandbox의 live PASS가 아니다.
- collector wheel SHA:
  `sha256:4a07a87776bb547b3f7e7a1e65697a34318e67ee525cf9f52dbd8a124268ab29`.
  검증 설치 위치는 `/tmp/eom-kakao-browser-verified.FckefOrG`다.
- actual driver·Playwright/Xvnc/gateway·전용 계정은 아직 없다. `systemd-analyze verify`도
  미설치 전용 interpreter를 지적하므로 전체 unit 설치 PASS로 기록하지 않는다.
  READY 이전 시작 실패의 staged intent는 후속 owner reconcile이 필요하다.

### 다음 실제 경로

1. MANUAL browser driver와 private gateway/현재 사용자 lease를 연결해 안전한 로그인
   화면을 준비한다. 실제 설치·권한/종료 검증 전 원격 화면을 공개하지 않는다.
2. accepted collection run/capability에서 snapshot·occurrence·첨부 연결을 수락하는
   owner를 구현한다. `ResolvedKakaoQuestionSource`를 만들었다는 것만으로 원문 권한을
   얻지 않으며, worker의 source identity 주장을 바로 canonical source로 받지 않는다.
3. 고정된 질문 intent/revision → 기존 pure 편집/Artifact 발행 → 짧은 재검증 CAS →
   packet → 한 학생 PDF로 연결한다. 이 수직 경로를 확인한 뒤 전체/주기 수집으로 확장한다.

추가 비밀번호 요청 없이 가능한 부분을 계속 구현한다. 기존 문항·GPU 완료 데이터·실패
이력은 보존하며, 이 체크포인트를 전체 goal 완료 또는 운영 활성화로 보고하지 않는다.

## 2026-11-16 06:41 UTC 전용 환경 준비

- source `4d190c32a01de55a4f19fc1c3697ec48762615d4`의 공식 API 4-wheel 빌드와
  Web offline wheel closure 빌드를 완료했다. 설치·운영 활성화는 아직 수행하지 않았다.
- browser/remote/pdf 전용 Conda 환경을 각각 최종 prefix에 직접 생성하고, 검증된
  오프라인 wheel만 설치했다. 세 환경의 `pip check`가 통과했다. 임시 venv를 운영
  경로로 복사하거나 기존 API/GPU 환경을 업그레이드하지 않았다.
- 원격 화면용 TigerVNC 1.13.1+dfsg-2build2와 해당 의존 4개 패키지만 설치했다.
  기존 패키지 업그레이드·삭제는 0이며 unrelated service restart는 하지 않았다.
- 최초 fingerprint는 Conda archive의 group-writable 파일 때문에 거부됐다. 이번에
  만든 eom 소유 준비본에 한해서 group/other write 및 set-id bit를 제거했고,
  5개 runtime/asset tree fingerprint가 통과했다. byte 변경이나 기존 서비스 변경은 없다.
- 아직 root-protected runtime 게시, 전용 service 활성화, DB migration, 카카오 로그인·
  수집은 미실행이다. 실제 실행 전에 발견한 Catalog sandbox write-path와 일회성
  Xauthority 준비 누락을 기존 installer/driver에서 보완한다.
- 자세한 준비 기록은 `staging/kakao-runtime-4d190c32/preparation-receipt.json`,
  wheel/RECORD/별도 PDF 출력 검사는 `/tmp/eom-kakao-release-4d190c32.93KcwwE4`다.
  이 경로들은 개발 증거이며 runtime authority 또는 활성화 선언이 아니다.

### 사진 blob 발행의 짧은 설계

1. 책임은 Catalog의 기존 Artifact 발행 adapter다. 사진 byte 검증·원본 보관만 맡고,
   방/메시지 연결·권한·DB 채택은 콘텐츠 owner에 남긴다.
2. 정본은 변경하지 않은 원본 이미지와 byte 고유 속성만 담은 작은 receipt다.
3. binding 범위 blob 논리 identity는 DB owner가 맡는다. Artifact/revision/hash와
   attachment occurrence/revision을 분리한다. 같은 사진의 새 관측은 별도 association이다.
4. SHA·크기·실제 MIME·decode 크기를 대조하고 고정 member명으로 exact pointer를 반환한다.
   호출 전/발행 직전/반환 전의 현재 source 권한 검사는 필수 callback이다.
5. 주요 연산은 binding+SHA 중복 확인, 처음 byte hash/decode, exact member 조회다.
6. 기존 Artifact publication 멱등 key와 후속 owner의 unique(binding,SHA)를 사용한다.
7. 사진 하나당 O(bytes+pixels), 명시적 byte/pixel 상한, 요청별 한 번의 검증이다.
   공개 조회마다 다시 decode하지 않는다. 원본 이름을 검색 key로 사용하지 않는다.
8. 대용량 검증·Artifact 발행 중 DB row lock은 잡지 않는다. 발행 후 owner가 재검증하고
   짧은 transaction으로 pointer를 채택한다. byte를 DB에 저장하지 않는다.
9. 순수 receipt 계약은 Catalog contracts, 이미지 decode/발행은 Catalog adapter다.
   실제 PyMuPDF 1.26.7의 `image_profile(bytes)`가 정상 PNG/JPEG에도 native binding
   TypeError를 내는 것을 재현했다. private C API 우회나 별도 이미지 파서를 만들지 않고
   PDF worker와 같은 Pillow 11.3.0을 선택적 `kakao-runtime` 의존으로 재사용한다.
   운영 활성화 전 이 의존 설치를 검증해야 하며, feature-off import는 요구하지 않는다.
   worker→NAS, domain→filesystem 의존을 추가하지 않는다.
10. 같은 binding+SHA의 재전송은 같은 발행을 재사용한다. 손상·형식·크기·권한·hash 오류는
    명시적으로 실패한다. 실패 이력을 성공으로 바꾸거나 byte를 보정하지 않는다.
11. 방·시간·파일명을 blob receipt에 넣는 더 단순한 대안은 같은 사진 재수집 때 request
    hash를 바꾸고 중복 보관을 유발하므로 제외한다. 별도 blob 저장소/framework는 불필요하다.
