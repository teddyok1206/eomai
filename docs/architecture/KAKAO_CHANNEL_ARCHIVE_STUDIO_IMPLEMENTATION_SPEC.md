# 카카오톡 채널 대화 보관 및 학생별 질문 자료 생성 — Scientific Studio 통합 구현 설계서

- 문서 버전: 1.0 / 작성 기준일: 2026-11-14
- 대상 저장소: https://github.com/teddyok1206/eomai
- 소스 조사 기준 커밋: `6a824aa48967270cc116661813d3d734f2f16e4e`
- 대상 운영 환경: 모니터 없는 Linux 서버, Caddy, 기존 Scientific Studio
- 현재 외부 주소: https://eomai.duckdns.org/studio/
- 목적: 기존 시스템을 잘 아는 Codex 개발 세션에 전달할 상세 구현 명세
- 문서 상태: **저장소와 공개 문서, 실제 CSV 샘플을 조사한 구현 전 설계. 운영 서버 및 카카오 로그인 화면에서의 실증은 아직 하지 않았다.**
- 이 문서의 API·DB·모듈 이름 중 `kakao_archive` / `kakao-archive`로 시작하는 이름은 별도 설명이 없으면 **신규 제안**이다.

## 이 문서를 받는 구현 담당자에게

기존 Scientific Studio 안에 “학생 질문” 기능을 추가한다. 카카오 채널 관리자 화면에서 현재 계정에 허용된 모든 채팅방의 CSV와 사진을 주기적으로 수집하고, 학생별 질문 후보를 결정론적으로 묶은 뒤 검토·수정하여 질문 하나당 PDF 한 페이지로 출력한다. **운영 과정에 LLM, OCR, 임베딩, AI 분류를 사용하지 않는다.** 개발에 Codex를 사용하는 것과 운영 기능이 AI를 호출하는 것은 구분한다.

먼저 현재 작업 브랜치의 `AGENTS.md`와 `docs/agent-context/README.md`, 아래 실제 코드 경계를 읽는다. 이 문서가 조사한 커밋과 현재 HEAD의 차이를 확인하고, 이미 구현된 동등 기능이 있으면 그 책임 경계를 확장한다. 기존 서비스·권한·Artifact·배포 무결성을 우회하는 별도 앱을 만들지 않는다. 문서의 예시 설정은 운영 적용을 완료한 설정이 아니다.

개발은 **실제 관리자 권한으로 한 방의 CSV·복수 사진을 정확히 확보하는 검증**과 **익명 fixture로 전체 저장·검토·PDF 흐름을 구현하는 작업**을 병행할 수 있다. 카카오 계정 인증이 필요한 순간 외에는, 미확정 UI 선택자 때문에 DB·계약·레이아웃·권한 구현 전체를 멈출 필요가 없다.

### 근거 표시

| 표시 | 의미 |
|---|---|
| **확인** | 지정 커밋의 코드, 제공된 설정, 실제 CSV 또는 공개 공식 문서에서 확인 |
| **설계 결정** | 이 기능을 구현하기 위해 이 문서가 선택한 동작과 구조 |
| **초기값 제안** | 실측 후 조정할 수 있는 운영 수치. 사용자 승인 또는 현재 운영값으로 간주하지 않음 |
| **실사 필요** | 운영 서버, 로그인된 카카오 화면, 실제 데이터로 확인해야 할 사항 |
| **후속 범위** | 첫 완성 버전에 필수는 아니며, 해당 필요가 생길 때 별도로 구현 |

---

## 목차

- [1. 최종 목표와 완료 조건](#section-1)
- [2. 조사에서 확인한 사실과 아직 모르는 것](#section-2)
- [3. 실제 EOM 저장소에 맞춘 구조](#section-3)
- [4. 카카오 실증과 collector 계약](#section-4)
- [5. CSV·메시지·사진의 정합 처리](#section-5)
- [6. 작업 실행·스케줄·중단과 복구](#section-6)
- [7. 저장·정체성·권한·보존 설계](#section-7)
- [8. 학생 연결·질문 후보·기간 선택](#section-8)
- [9. 발행 묶음과 질문당 한 페이지 PDF](#section-9)
- [10. Scientific Studio에 추가할 화면·API·권한 경계](#section-10)
- [11. 런타임·원격 로그인·서버 배포 설계](#section-11)
- [12. 구현 파일·계약·배포 산출물](#section-12)
- [13. 구현 순서와 단계별 완료 증거](#section-13)
- [14. 테스트와 수용 기준](#section-14)
- [15. 용량·성능·운영](#section-15)
- [16. 설계 결정 기록](#section-16)
- [17. 구현 세션에 붙여 넣을 지시문](#section-17)
- [18. 출처와 조사 범위](#section-18)

<a id="section-1"></a>

## 1. 최종 목표와 완료 조건

### 1.1 사용자가 하려는 일

1. 서버가 주기적으로 카카오 채널의 접근 가능한 채팅방을 찾는다.
2. 각 방의 대화 내역을 CSV로 내보내고, 대화와 연결된 사진을 별도로 받는다.
3. 원본 자료를 보존하면서 조회 가능한 메시지·첨부·학생 관계를 만든다.
4. 특정 날짜 범위를 선택하면 해당 기간에 시작된 학생 질문을 추린다.
5. 사람이 학생 연결과 질문 경계를 확인하고 필요한 경우 나누거나 합친다.
6. 학생별로 질문을 정렬하여 **한 질문당 한 페이지**인 자료를 만든다.
7. Studio에서 미리보고 PDF를 내려받는다.
8. 카카오 재로그인이 필요할 때 같은 Studio 안의 제한된 원격 브라우저 화면으로 접속한다.

사용자의 카카오 권한은 **마스터가 아닌 관리자/매니저**다. 이 시스템은 마스터 권한이 생긴다고 가정하지 않으며, 기존 계정이 실제로 볼 수 있는 자료와 사용할 수 있는 내보내기·다운로드 기능만 대상으로 한다.

### 1.2 첫 완성 버전의 필수 범위

| 구분 | 필수 결과 |
|---|---|
| 수집 | 한 채널 binding에 대해 전체 접근 가능 방 목록을 조사하고 각 방 CSV를 수집 |
| 반복 실행 | 재시작·인증 만료·일부 방 실패 후 이미 완료된 결과를 보존하며 재개 |
| 사진 | 학생 사진의 다운로드, 말풍선 연결, 복수 사진 순서, 원본 바이트와 출처 보존 |
| 범위 표시 | 접근하지 못한 방, 미확보 사진, 미확정 메시지 관계를 별도 표시 |
| 학생 | 방과 학생을 명시적으로 연결하고 동명이인을 분리 |
| 질문 | 규칙 기반 후보 생성, 수동 분할·병합·제외·첨부 조정 |
| 기간 | Asia/Seoul 기준 시작일 포함·종료일 다음 날 미포함 정책 |
| 출력 | 학생별 PDF, 질문당 정확히 한 페이지, 글·사진 잘림 검증 |
| UI | 기존 Studio 메뉴·세션·권한·API·다운로드 방식에 통합 |
| 원격 화면 | 서버의 가상 화면을 Studio iframe에 표시하여 수동 인증 가능 |
| 운영 | 기존 PostgreSQL·Catalog·Orchestrator·NAS·배포 규칙에 맞춤 |
| AI 금지 | 수집부터 PDF까지 AI/OCR/임베딩 호출이 없음을 테스트로 보장 |

첫 운영 범위는 **한 카카오 계정, 한 채널 binding, 동시에 한 수집 브라우저**로 제한한다. DB의 binding 필드는 유지하되 여러 채널을 동시에 조작하는 범용 플랫폼은 미리 만들지 않는다.

학생에게 자료를 카카오톡·이메일로 자동 발송하는 기능은 포함하지 않는다. 사용자는 Studio에서 자료를 확인하고 내려받는다. HWPX·DOCX·자동 풀이·문제 OCR·내용 요약도 첫 범위에 포함하지 않는다.

### 1.3 “성공”의 정확한 의미

다음 네 가지 성공을 구분한다.

- **목록 조사 성공:** 이번 실행이 관측한 모든 접근 가능 목록 범위를 끝까지 확인했다.
- **CSV 확보 성공:** 특정 방에 대해 내보내기 파일을 받아 보존하고 파싱했다.
- **첨부 확보 성공:** 관측된 특정 사진을 실제 파일로 받아 메시지와 연결했다.
- **자료 발행 성공:** 선택된 질문의 원문·필수 사진·레이아웃 검증이 모두 통과했다.

CSV 하나를 받았다는 이유로 그 방의 과거 전체 사진을 받았다고 표시하지 않는다. 목록 조사가 끝났어도 이미 사라진 방이나 만료된 사진까지 복구했다는 뜻이 아니다.

최종 PDF는 아래 조건을 모두 충족해야 한다.

~~~text
PDF 페이지 수 = 선택한 질문 revision 수
각 질문의 필수 본문 조각이 모두 배치됨
각 질문의 필수 사진 occurrence가 모두 배치됨
다른 학생의 사진이 섞이지 않음
본문·사진·머리말·꼬리말 사이에 잘림과 겹침이 없음
최소 글자 크기·최소 사진 표시 기준을 지킴
모든 입력과 출력의 immutable pointer 및 hash가 기록됨
~~~

자료를 한 페이지에 담을 수 없으면 `NEEDS_LAYOUT_REVIEW`로 처리한다. 글을 자르거나, 사진을 누락하거나, 읽기 어려운 크기로 줄여서 성공 처리하지 않는다.

---

<a id="section-2"></a>

## 2. 조사에서 확인한 사실과 아직 모르는 것

### 2.1 카카오 API와 현재 전략

**확인:** 카카오 공식 개발자 지원 답변은 일반 채널 관리자센터의 1:1 채팅 내역 조회 API를 제공하지 않으며 대화 내보내기 기능을 사용하도록 안내한다. 이 문서는 “공개 API로 기존 방의 과거 대화와 원본 사진을 모두 조회할 수 있다”는 가정에 의존하지 않는다. [K1]

카카오톡 채널 개발자 API의 친구 관계 조회 등은 일반 관리자센터 채팅 내역 API와 다른 기능이다. 상담톡은 별도 도입·계약·상담 시스템의 영역이며, 기존 관리자센터의 과거 CSV·사진을 그대로 소급 조회할 수 있다는 증거가 아니다. [K2][K3]

**설계 결정:** 첫 collector는 로그인된 관리자 웹 화면의 내보내기·다운로드 동작을 Playwright로 자동화한다. 화면에서 실제로 발생한 읽기 요청을 관측해 안정적인 식별자를 보완할 수 있으나, 존재를 확인하지 않은 내부 API를 문서에 발명하거나 우회 호출하지 않는다.

상담톡 전환은 이 기능의 필수 조건으로 두지 않는다. 공식 안내에는 전환과 기존 관리자센터 채팅 이용에 관한 제약이 있으므로, 필요해질 때 과거 자료 보존과 운영 변화까지 별도 검토한다. [K3]

### 2.2 실제 CSV 샘플에서 확인한 결과

검토한 샘플은 UTF-8 계열 CSV로 다음 구조였다. 개인정보가 포함된 원본 파일명과 메시지 본문은 이 설계서에 재기재하지 않는다.

| 항목 | 확인 결과 |
|---|---|
| 열 | `DATE`, `USER`, `MESSAGE` |
| 데이터 행 | 26행 |
| 관측 기간 | 2026-09-08 15:50:26 ~ 2026-11-10 23:18:28 |
| 발신자 종류 | 표시 이름 기준 2종, 각각 18행 / 8행 |
| `사진` 표시 행 | 각각 5행 / 2행 |
| 파일명·URL 열 | 없음 |
| room/message/attachment ID 열 | 없음 |
| 명시적 시간대 열 | 없음 |
| 원본 SHA-256 | `sha256:7f02001870052008a3d0d28bb196070c9d6215bad03afd5cfa49deadc1ae9754` |

**따라서 이 샘플 CSV에서 사진 다운로드 기본 파일명을 찾아서 연결할 수는 없다.** `사진`이라는 표시만으로 사진 수, 파일명, 파일 바이트 또는 말풍선 ID를 복원할 수 없다. 또한 학생이 글자로 “사진”이라고 보낸 경우와 첨부 표시를 CSV만으로 확실하게 구분할 수 있다고 가정하지 않는다.

위 결과는 **검토한 사진 포함 CSV 샘플**에 관한 것이다. 일반 파일, 영상, 향후 포맷 변경까지 같은 방식이라고 단정하지 않는다. 실제 DOM 및 다운로드 이벤트에서 추가 증거를 확보해야 한다.

파일 다운로드 시 제공되는 `suggested_filename`은 별도로 저장할 유용한 메타데이터다. 그러나 브라우저의 충돌 회피 접미사, 서버 헤더, 다운로드 방식에 따라 달라질 수 있으므로 canonical ID나 CSV join key로 쓰지 않는다. Playwright의 다운로드 이벤트는 클릭 전에 대기시키고, context 종료 전 파일을 지정된 로컬 staging 위치로 저장해야 한다. [P1]

### 2.3 수집 범위에 영향을 주는 공식 안내

카카오 안내에서 다음을 확인했다. [K4]

- 방 목록의 기간 검색은 **마지막 대화 일시**에 관한 필터다. 원하는 메시지 기간과 동일하지 않다.
- 진행 중·완료, 담당자·라벨 등 목록 조건이 존재한다.
- 차단된 상대는 별도 목록에서 차단 전 대화를 볼 수 있다.
- 방 나가기는 목록에서 방을 사라지게 할 수 있다.
- 텍스트 대화 보관 안내와 첨부파일 원본 보존 기간은 같은 보장으로 취급할 수 없다.
- 사진 여러 장이 하나의 말풍선으로 묶일 수 있다.
- 관리자 추가 인증이 필요할 수 있다.

따라서 보고서 날짜를 카카오 목록 필터에 그대로 넣어 수집 범위를 줄이지 않는다. 수집 시각을 기준으로 접근 가능한 방을 먼저 조사하고, 날짜 필터는 수집된 메시지를 질문으로 구성한 뒤 적용한다.

### 2.4 실사 필요 항목과 fallback

| 미확정 항목 | 실증 방법 | 확인 실패 시 동작 |
|---|---|---|
| 관리자 계정의 각 기능 권한 | 실제 계정으로 목록·내보내기·사진 받기 확인 | 허용된 범위를 기록하고 해당 기능은 불가 표시 |
| 안정적 room ID | 주소·DOM·정상 화면 요청을 관측 | 수동 확인한 내부 room binding 사용, 이름으로 자동 병합 금지 |
| 안정적 message ID | 말풍선·응답의 ID와 재접속 후 동일성 확인 | snapshot ordinal 기반 보관과 보수적 순서 정합 |
| CSV 범위 | 과거 대화 로딩 전후 export 비교 | `EXPORT_SCOPE_UNKNOWN`; 전체 이력 보장 금지 |
| 사진 묶음 수·순서 | 복수 사진 말풍선의 viewer·download 비교 | 미확정 관계 검토, 한 행=한 장 가정 금지 |
| 원본과 thumbnail 차이 | 다운로드 파일 크기·해상도·UI 기능 비교 | `best_available` 또는 `thumbnail_only` 표시 |
| 시간대 | 실제 전송 시각·화면·CSV 비교 | raw 문자열 유지, `timezone_unverified` 표시 |
| 페이지/스크롤 종료 | 마지막 항목·추가 로딩·가상 목록 확인 | `ENUMERATION_INCOMPLETE` |
| 다운로드 기본 파일명 안정성 | 같은 파일 반복 다운로드 비교 | 메타데이터로만 저장 |
| 재로그인 후 프로필 유지 | 서비스 재시작 후 수동 확인 | `AUTH_REQUIRED`로 중단 후 원격 인증 |

이 표의 미확정 값을 `true`로 기본 설정하지 않는다. `unknown`은 `false`와도 구별한다.

---

<a id="section-3"></a>

## 3. 실제 EOM 저장소에 맞춘 구조

### 3.1 확인한 기존 구성

아래는 지정 커밋에서 확인한 실제 파일과 책임이다. 설치된 운영 release가 이 커밋과 같다는 의미는 아니다.

| 현재 책임 | 실제 소스 | 이번 기능의 사용 방식 |
|---|---|---|
| 저장소 공통 규칙 | `AGENTS.md` | protocol-first, Orchestrator 경유, NAS 소유권, UTC, immutable pointer |
| 개발 길잡이 | `docs/agent-context/README.md` | 관련 note 후 실제 코드 확인 |
| 모듈 경계 | `docs/architecture/MODULE_BOUNDARIES.md` | 기존 composition 경계 유지 |
| Studio 화면 | `apps/web_gui/eom_web_gui/static/index.html`, `app.js` | 새 view와 controller 연결 |
| Studio 경로 | `static/studio-route.js` | `/studio/?view=kakao-archive` |
| Studio BFF | `apps/web_gui/eom_web_gui/app.py` | 세션·CSRF·API gateway |
| Application API | `apps/application_api/eom_api/app.py` | 기존 `/api/v1`에 기능 router 추가 |
| API 권한 | `dependencies.py`, `operator_identity/contracts.py` | 실제 operator 및 신규 permission |
| Catalog IPC | `catalog_application_client.py`, `catalog_service/application_server.py` | typed command와 private Unix socket |
| 도메인 저장 | Catalog 모델 + Orchestrator `Base` | 기존 PostgreSQL/Alembic에 additive 모델 |
| Artifact 발행 | `CatalogArtifactService.commit_file_set` | CSV·사진·manifest·PDF 등록 |
| Artifact 구성요소 | `eom_protocol.artifact_members.ArtifactMemberPointer` | 파일 경로 대신 exact pointer |
| 외부 작업 격리 선례 | `orchestrator/visual_reference_acquisition.py` | typed local command, fixed unit, 결과 검증 |
| 문서 도구 | 루트 `pyproject.toml`의 PyMuPDF | 새 질문 PDF renderer의 기본 엔진 |
| Caddy | `config/caddy/Caddyfile` | 기존 route 보존, 원격 화면 분기만 추가 |

정확한 경로와 링크는 뒤의 구현 파일 목록 및 근거 목록에서 제공한다. [R1][R2][R3][R4][R5][R6][R7][R8]

### 3.2 구조 선택

**설계 결정:** 기존 Python 3.12, FastAPI, 정적 JavaScript ES module, PostgreSQL, Catalog, Orchestrator, NAS를 확장한다.

- 별도 React/Next.js 앱을 만들지 않는다.
- 독립 SQLite를 canonical DB로 두지 않는다.
- 별도 Redis/Celery와 범용 queue framework를 도입하지 않는다.
- Web/API 프로세스가 브라우저를 실행하거나 NAS에 직접 저장하지 않는다.
- 사진을 기존 ItemRegistry·material-learning·GraphRAG·AI 지원 상담에 자동 등록하지 않는다.
- 기존 HWPX 입력을 맞추기 위해 가짜 Item 또는 Kordoc을 만들지 않는다.

기존 `customer_support`, `general_chat`, `private_chat_*`는 카카오 대화 아카이브가 아니다. “상담” 또는 “private chat”이라는 이름만 보고 기존 AI 실행 경로를 재사용하지 않는다.

### 3.3 컴포넌트 배치

~~~mermaid
flowchart TD
    U["운영자 브라우저"] --> C["기존 Caddy"]
    C --> W["Studio BFF"]
    W --> A["Application API"]
    A --> K["Catalog 카카오 기능"]
    K --> D["기존 PostgreSQL"]
    K --> O["Orchestrator 실행·발행 경계"]
    O --> B["격리된 카카오 브라우저"]
    O --> R["격리된 PDF renderer"]
    O --> N["기존 NAS Artifact"]
    C --> V["인증된 원격 화면 gateway"]
    V --> B
~~~

이 그림은 논리적 책임 관계다. Catalog와 Orchestrator 사이에 새로운 HTTP microservice를 반드시 만들라는 뜻은 아니다. 현재 저장소는 공유 트랜잭션 및 명시적 adapter를 사용하는 composition을 이미 가지고 있다. 해당 기존 경계 안에서 새 좁은 use case를 구성한다. [R2]

### 3.4 책임과 의존 방향

| 구성요소 | 담당 | 가져서는 안 되는 책임 |
|---|---|---|
| `catalog_contracts/kakao_*.py` | frozen DTO, schema, identifier, 순수 값 | SQLAlchemy, subprocess, NAS, HTTP |
| Catalog 카카오 use case | 권한, run/task, 정합, 질문 revision, packet, 발행 승인 | DOM 클릭, 임의 shell 실행 |
| Orchestrator runtime adapter | 고정 worker 실행, staged 입력, fence, 결과 검증 | 질문 의미 추측, 학생 이름 추정 |
| 카카오 browser runtime | 프로필 소유, DOM 관측, export/download, local result | DB·NAS·AI·다른 worker 호출 |
| PDF worker | 고정된 질문·사진·폰트로 PDF/PNG/receipt 생성 | 카카오 세션, 인터넷, DB·NAS |
| API/BFF | 인증·권한·DTO·명령 접수·projection·파일 전달 | 수집 loop, CSV 병합, PDF 조판 |
| UI | 진행·누락 표시, 사람 검토, API 명령 | 권한 판정, 파일 경로 선택, 서버 임의 URL 지정 |

새로운 서비스 간 순환 import를 늘리지 않는다. 특히 저장소가 이미 알려진 기술 부채로 다루는 composition SCC를 새 기능의 핑계로 확대하지 않는다. 순수 정합·질문 규칙과 인프라 adapter는 서로 분리한다.

### 3.5 변경하지 않는 전역 계약

다음 코드가 이미 범용 확장점인 것처럼 다루면 안 된다.

- `eom_protocol.models.JobRequest`의 기존 `authoring_smoke` 계약.
- 기존 WorkflowRunner application step의 제한된 schema/step-key 제약.
- 기존 global `JobRecord.status` enum.
- 이미 발행된 schema 버전의 바이트.
- 현재 운영 서비스의 source pin·runtime integrity·권한 경계.

첫 버전은 Catalog의 **카카오 전용 run/task/coordinator**와 Orchestrator의 **좁은 외부 runtime adapter**를 사용한다. 기존 자료 학습 coordinator에서는 lease와 pointer 구조만 참고한다. AI workflow 자체는 호출하지 않는다.

`CatalogArtifactService.commit_file_set()`은 내부에서 publication용 JobRecord와 Artifact ID를 만든다. **collector 실행 attempt와 Artifact 발행 Job은 별개다.** 먼저 임의 JobRecord를 만든 뒤 이 함수가 그 Job을 받아서 마무리할 것이라고 가정하지 않는다. 실행은 카카오 task/attempt로 추적하고, 결과를 발행할 때 반환된 `publication_job_id`를 연결한다. [R5][R8]

---

<a id="section-4"></a>

## 4. 카카오 실증과 collector 계약

### 4.1 최초 실증 절차

실증은 로그인된 실제 관리자 권한으로 소수 방에서 수행한다. 개인정보가 담긴 화면·trace·HAR를 공개 저장소나 개발 보고에 넣지 않는다.

1. 현재 계정과 대상 채널을 사람이 확인하고 binding을 만든다.
2. 진행 중·완료·차단 목록 및 담당자/라벨/검색 조건을 조사한다.
3. 오래된 대화가 있는 방 한 개를 선택한다.
4. 과거 스크롤 전 CSV를 내보낸다.
5. 화면에서 과거 대화를 추가 로딩한 뒤 다시 내보낸다.
6. 두 파일의 행 수, 최초·최종 시각, 공통 구간, raw hash를 비교한다.
7. 학생 사진, 채널 측 사진, 복수 사진 묶음을 실제 다운로드한다.
8. 다운로드 직전의 room·bubble·방향·시각·album ordinal과 파일 결과를 같이 기록한다.
9. 재접속 후 room/message 식별자가 유지되는지 확인한다.
10. 확인 결과를 versioned capability receipt로 등록한다.

자동화 가능성의 실증과 **서비스에서 허용하는 사용 범위**의 확인은 별개다. 우회 인증·CAPTCHA 회피·권한 확대 없이 계정에 허용된 화면 기능을 대상으로 한다.

### 4.2 capability receipt

다음은 계약 형태를 설명하는 예시다. 실제 JSON Schema를 먼저 정의하며, 문자열형 placeholder를 운영 데이터로 사용하지 않는다.

~~~json
{
  "schema_version": "kakao-capabilities/1.0",
  "binding_id": "<server-issued-binding-id>",
  "adapter_revision": "<immutable-release-id>",
  "observed_at": "2026-11-14T00:00:00Z",
  "room_identity": "unknown",
  "message_identity": "unknown",
  "csv_scope": "unknown",
  "csv_direction": "unknown",
  "source_timezone": "unknown",
  "album_enumeration": "unknown",
  "original_download": "unknown",
  "visible_list_scopes": [],
  "evidence": []
}
~~~

검증 후의 enum 예:

| 필드 | 허용 값의 예 |
|---|---|
| `room_identity` | `stable_source_id` / `manual_binding` / `unknown` |
| `message_identity` | `stable_source_id` / `sequence_only` / `unknown` |
| `csv_scope` | `full_accessible_history` / `loaded_window` / `explicit_range` / `unknown` |
| `csv_direction` | `ascending` / `descending` / `unknown` |
| `source_timezone` | `Asia/Seoul` / `unknown` |
| `original_download` | `verified_ui_download` / `best_available` / `unavailable` / `unknown` |

“한 번 성공”은 모든 채널과 영구적인 UI 계약을 의미하지 않는다. adapter release, 카카오 화면 관측 시각, 검증 fixture를 pin한다. 화면 구조 변화 시 receipt를 다시 확인한다.

### 4.3 실제 UI adapter의 인터페이스

아래는 신규 adapter의 책임 예시이며 실제 카카오 선택자는 아니다.

~~~python
class KakaoChannelAdapter(Protocol):
    async def probe_session(self) -> SessionObservation: ...
    async def verify_channel(self, expected: ChannelIdentity) -> ChannelObservation: ...
    async def enumerate_rooms(self, scope: RoomScope) -> RoomInventoryResult: ...
    async def open_room(self, room: RoomLocator) -> RoomObservation: ...
    async def export_conversation(self, target: LocalOutputTarget) -> CsvDownloadResult: ...
    async def inspect_attachments(self, scope: MessageScope) -> AttachmentInventory: ...
    async def download_attachment(self, target: AttachmentLocator) -> LocalMediaResult: ...
~~~

구현 규칙:

- role·접근 가능한 이름·안정적인 attribute를 우선 사용한다.
- 임의로 변하는 class hash나 화면 좌표에만 의존하지 않는다.
- destructive action과 가까운 메뉴는 예상 label, count, dialog 제목을 검증한다.
- `locator.first()`로 다중 일치 오류를 숨기지 않는다.
- “내보내기” 클릭 전에 `expect_download`를 준비한다.
- 화면의 로딩 상태·spinner·네트워크 응답과 실제 데이터 변화를 조합한다.
- 고정 sleep만으로 완료를 판정하지 않는다.
- DOM guard 실패는 `UI_CHANGED`로 멈추며 안전하지 않은 다른 버튼을 추측해 누르지 않는다.

실제 UI에서 관측한 요청을 활용하는 최적화는 별도 adapter로 격리한다. 확인한 method·URL 패턴·요청 body·응답 schema를 기록하고, 로그인 세션과 동일한 권한으로 읽기만 수행한다. `/api/chats` 같은 가상의 카카오 endpoint는 구현하지 않는다.

### 4.4 방 목록 완전성

사용자의 “모든 채팅방”은 **이번 실행에서 현재 계정으로 열람 가능한 모든 목록 범위**로 정의한다.

1. binding의 예상 채널과 실제 채널을 대조한다.
2. 사용자 검색어·담당자·라벨·날짜 조건을 초기화하고 실제 적용 상태를 읽는다.
3. 조사한 진행 중·완료·차단 등 각 scope를 순회한다.
4. 가상 스크롤 또는 pagination을 끝까지 진행한다.
5. 관측한 stable room ID 또는 사람이 확인한 내부 room identity를 set에 추가한다. 아직 식별하지 못한 항목도 별도 unresolved inventory에 남겨 coverage에서 사라지지 않게 한다.
6. 명시적 종료 또는 검증된 pagination 종료를 확인한다.
7. 두 번째 안정화 pass로 새로 보인 ID와 순서 변경을 보완한다.
8. 목록 manifest를 발행한 뒤 각 방 task를 만든다.

종료조건 예:

~~~text
검증된 마지막 페이지/목록 끝 조건
AND pending loading 없음
AND 추가 안정화 pass에서 새 room ID 없음
~~~

단지 몇 번 스크롤해도 새 항목이 안 나왔다는 것은 종료의 충분조건이 아니다. 로딩 실패, 제한 응답, 목록 갱신이면 `ENUMERATION_STALLED`로 기록한다. 종료를 입증하지 못하면 `coverage.inventory_complete=false`다.

방을 열면 읽음 상태나 최근 순서가 바뀔 수 있다. 따라서 먼저 목록을 확보하고, 방을 처리한 뒤 마지막에 목록을 다시 확인한다. 동시에 새 메시지가 들어오는 화면은 원자적 snapshot이 아니다. manifest에 `inventory_started_at`, `inventory_finished_at`, `reconciliation_pass_at`를 남긴다.

수집기는 메시지 전송, 상태·담당자 변경, 차단, 채팅방 나가기를 실행하지 않는다. 방 열기에 수반되는 읽음 처리 여부는 실증하여 UI에 알려야 하며, 이를 되돌린다는 이유로 별도의 상태 변경을 자동 수행하지 않는다.

### 4.5 방별 수집 결과

각 방의 결과는 최소한 다음을 포함한다.

- 내부 room ID와 실제 외부 room 식별 근거.
- 수집 시각과 source observation interval.
- raw CSV local member 및 SHA-256.
- export scope와 timezone 확인 상태.
- 파싱된 행 수와 최초·최종 source 시각.
- 첨부 관측 목록, 실제 파일과 연결 근거.
- 실패·미확정·지원하지 않는 첨부 상태.
- 사용한 adapter/parser/capability revision.
- 작업 attempt와 fencing epoch.

collector는 이 결과를 **로컬 workspace에만** 쓴다. NAS 경로, DB DSN, Studio bearer, 다른 worker credential은 받지 않는다.

---

<a id="section-5"></a>

## 5. CSV·메시지·사진의 정합 처리

### 5.1 원본 보존과 파싱

- 다운로드한 CSV의 바이트를 그대로 원본 Artifact로 보존한다.
- `csv.DictReader`와 동등한 표준 parser로 따옴표·쉼표·필드 안 줄바꿈을 처리한다.
- `split(",")` 또는 `splitlines()`를 CSV parser 대신 사용하지 않는다.
- 먼저 UTF-8 BOM을 처리하며 UTF-8을 엄격히 decode한다.
- CP949 등 fallback은 실제 포맷 증거와 명시적 parser option이 있을 때만 사용한다.
- `errors="replace"`로 깨진 한글을 조용히 바꾸지 않는다.
- 필수 열 누락, 알 수 없는 시간 형식, 중복 header, 허용 한도 초과는 명시적 오류다.
- 추가 열은 원본과 schema observation에 보존하고, 검토 전 의미를 추측하지 않는다.
- Unicode 정규화·공백 제거·개행 변환을 raw hash 또는 메시지 identity에 몰래 적용하지 않는다.

정규화 projection은 원본과 별도다. 예를 들어 화면 표시용 개행을 통일하더라도 raw row의 재현 가능성을 보존해야 한다.

### 5.2 시간 처리

CSV의 `DATE`는 시간대 없는 문자열이었다. 원문을 보존한 뒤 실증한 timezone을 적용한다.

~~~text
raw_date_string: 카카오 CSV 그대로
source_timezone: 검증된 Asia/Seoul 또는 unknown
sent_at_utc: 검증된 timezone을 적용한 UTC
observed_at_utc: 수집기의 UTC 관측 시각
timestamp_precision: 예: second
~~~

timezone이 미확정이면 정확한 월 경계 분류를 확정하지 않는다. 운영자에게 확인할 수 있는 상태를 보여 준다. 시스템 timestamp는 UTC를 쓰고, 사용자가 날짜를 지정하고 읽는 화면에서는 Asia/Seoul을 사용한다.

### 5.3 발신 방향

`USER`의 표시 이름만으로 영구적인 학생/관리자 식별을 하지 않는다. 이름 변경, 동명이인, 채널명 변경이 가능하기 때문이다.

발신 역할은 `student`, `staff`, `system`, `unknown`으로 나눈다. DOM의 발신 방향과 source metadata를 우선 사용하고, CSV 표시값과 대조한 mapping revision을 남긴다.

“학생”은 이 시스템의 자료 생성 대상 역할이다. 채팅 상대가 실제 학생인지 보호자인지, 한 방에 여러 학생의 질문이 섞이는지는 운영자가 방과 학생을 연결하며 확인한다. 잘못된 관계를 이름 유사도로 자동 결정하지 않는다.

### 5.4 같은 메시지와 같은 내용은 다르다

다음 key로 메시지를 중복 제거하지 않는다.

~~~text
(room_id, timestamp, sender_name, text_hash)
~~~

같은 초에 동일 문구를 두 번 보낸 메시지는 둘 다 실제 메시지다. 사진 두 장이 같은 초에 올라오거나, 동일 사진을 다시 보낼 수도 있다.

identity의 우선순위:

1. 실제로 검증한 안정적 provider message ID.
2. 안정적 anchor 주변의 **순서·개수·주변 문맥**을 함께 이용한 제한된 sequence alignment.
3. 정합이 불확실하면 snapshot 내부 `(snapshot_revision_id, row_ordinal)`.
4. 필요한 경우 사람이 확인한 대응.

source ID가 없으면 `timestamp + body hash`는 후보 검색에만 사용한다. 그것을 unique constraint로 두지 않는다.

### 5.5 snapshot 간 정합 알고리즘

1. 원본 snapshot을 정규화하고 ascending source order를 확정한다.
2. source ID가 있으면 binding·room namespace 안에서 정확히 대응한다.
3. ID가 없는 구간은 앞뒤의 유일한 텍스트·시각·역할 anchor를 찾는다.
4. 해당 구간 내에서 순서를 보존하는 bounded alignment를 수행한다.
5. 반복되는 동일 값은 occurrence count를 유지한다.
6. 가능한 대응이 여러 개면 `AMBIGUOUS_MESSAGE_MATCH`로 남긴다.
7. 새 snapshot에서 사라진 행을 곧바로 삭제 메시지로 해석하지 않는다.
8. source에 명시적인 삭제 표시가 있을 때 별도 observation/revision으로 기록한다.

전체 이력에 무제한 O(n²) LCS를 매번 적용하지 않는다. anchor index와 겹치는 window를 사용하며, configured window를 넘거나 anchor가 없으면 snapshot-only mode로 남긴다.

**초기 버전의 중요한 fallback:** 어떤 기간을 한 개의 검증된 snapshot이 충분히 포함하면, 그 snapshot의 projection으로 질문을 만들 수 있다. 안정적 ID가 없다고 전체 기능을 포기할 필요는 없다. 반대로 애매한 여러 snapshot을 단순 이어 붙여 중복 없는 전체 이력이라고 주장하면 안 된다.

정합 수준은 최소 다음 enum으로 노출한다.

~~~text
SOURCE_VERIFIED
SEQUENCE_INFERRED
SNAPSHOT_ONLY
MANUAL_CONFIRMED
UNRESOLVED
~~~

`SEQUENCE_INFERRED`는 source ID와 동등한 보장이 아니다. packet manifest에 해당 수준과 원본 snapshot을 함께 pin한다.

### 5.6 사진의 연결 단위

사진 연결은 다운로드 순간에 다음 순서로 기록한다.

~~~text
binding
→ room
→ source message 또는 정확한 snapshot occurrence
→ attachment occurrence
→ album 내 ordinal
→ 실제 다운로드 결과
→ 원본 ArtifactMemberPointer
~~~

원본 파일 하나와 첨부 occurrence는 다르다. 동일 바이트가 여러 번 전송되면 파일 저장은 재사용할 수 있지만, 메시지와의 관계는 각각 유지한다.

CSV의 `사진` 행 하나는 0개, 1개 또는 여러 파일의 관측으로 이어질 수 있다. 0개가 “사진이 없었다”를 뜻하는지, “찾지 못했다”를 뜻하는지도 상태로 구분한다.

### 5.7 첨부 메타데이터

| 필드 | 의미 |
|---|---|
| `attachment_occurrence_id` | 해당 메시지에서 첨부된 사건의 내부 ID |
| `source_attachment_id` | 실증한 provider ID가 있을 때만 기록 |
| `album_ordinal` | 원래 묶음 안의 순서 |
| `association_evidence` | source ID / bubble context / sequence / 수동 확인 |
| `suggested_filename` | 다운로드 시 브라우저가 제안한 파일명 |
| `downloaded_local_name` | local staging 내부 이름; 외부 파일명과 구분 |
| `content_sha256` | 실제 파일 바이트의 SHA-256 |
| `media_type_detected` | 확장자만 믿지 않고 검증한 형식 |
| `width_px`, `height_px` | 실제 decode한 이미지 크기 |
| `quality_level` | original_verified / best_available / thumbnail_only / unknown |
| `availability` | available / expired / denied / not_found / pending / failed |
| `member_pointer` | 원본 파일의 exact ArtifactMemberPointer |

서버 내부 파일명은 ASCII ID 또는 content hash와 검증한 확장자를 사용한다. `suggested_filename`을 그대로 filesystem path에 붙이지 않는다.

`original_verified`는 **플랫폼이 제공하는 다운로드 원본을 확보했다**는 의미다. 카메라 원본과 바이트가 같거나 플랫폼 압축이 전혀 없다는 뜻은 아니다.

### 5.8 다운로드 검증과 만료

- 빈 파일, HTML 로그인 페이지, MIME 불일치, decode 실패를 사진 성공으로 처리하지 않는다.
- URL query에 토큰이 포함될 수 있으므로 일반 로그에 저장하지 않는다.
- signed URL은 영구 식별자가 아니다.
- 다운로드 401/403 시 먼저 로그인 상태를 확인한다.
- 정상 세션인데 오래된 URL만 실패하면 화면에서 새 링크를 얻어 한정 재시도한다.
- URL 문자열을 조작하여 만료·권한 제한을 우회하지 않는다.
- 실패는 `AUTH_REQUIRED`, `ACCESS_DENIED`, `SOURCE_EXPIRED` 등으로 분리한다.
- 부분 다운로드는 임시 파일로 받고, 완료·크기·hash 검증 후 결과 manifest에 넣는다.
- context를 닫기 전에 다운로드를 영속 local staging에 저장한다. [P1]

첫 버전은 JPG/PNG/WebP 등 실제 확인한 이미지 형식만 정상 미리보기·PDF 입력으로 허용한다. GIF, HEIC, SVG, 영상, PDF 첨부는 무조건 사진으로 재해석하지 않는다. 원본 확보 가능 여부와 render support를 별도 상태로 표시한다.

학생이 보낸 사진은 최종 자료의 기본 포함 대상이다. 채널 측 사진은 보관할 수 있지만 기본 질문 PDF에서는 제외하고 필요할 때 명시적으로 추가한다.

### 5.9 바이트 중복과 재수집

사진을 매번 새 Artifact에 복제하지 않는다. 같은 binding 안에서 이미 검증된 content hash와 media 정보를 가진 원본이 있으면 해당 포인터를 참조한다. 전역 hash 조회 API나 다른 binding의 자료 존재 여부를 노출하는 dedup는 만들지 않는다.

동일 사진의 존재를 다운로드 전에 식별할 수 없다면 네트워크 다운로드가 다시 발생할 수 있다. 이 경우에도 바이트 확보 후 hash 검증으로 canonical 저장의 중복을 피한다. 파일명이 같다는 이유로 다운로드를 생략하지 않는다.

---

<a id="section-6"></a>

## 6. 작업 실행·스케줄·중단과 복구

### 6.1 실행 단위

| 단위 | 책임 |
|---|---|
| source binding | 채널·소유 operator·수집 설정·capability revision |
| collection run | 한 번의 전체 방 조사 및 수집 의도 |
| room task | 한 방의 CSV와 첨부 조사/확보 |
| task attempt | 한 번의 실제 실행 및 fence |
| publication job | 기존 Artifact 서비스의 결과 발행 |
| checkpoint | 다음에 재개할 scope/room/단계 |
| remote lease | 특정 인증 세션의 제한된 수동 조작 권한 |

한 collection run의 성공과 한 publication job의 성공을 혼동하지 않는다. CSV 발행이 끝나도 일부 사진이 실패하면 room task 또는 run의 coverage가 부분 완료일 수 있다.

### 6.2 도메인 상태 머신

collection run의 신규 상태 예:

~~~mermaid
stateDiagram-v2
    [*] --> QUEUED
    QUEUED --> INVENTORY
    INVENTORY --> COLLECTING
    COLLECTING --> RECONCILING
    RECONCILING --> COMPLETED
    INVENTORY --> AUTH_REQUIRED
    COLLECTING --> AUTH_REQUIRED
    AUTH_REQUIRED --> QUEUED
    COLLECTING --> PAUSED
    PAUSED --> QUEUED
    RECONCILING --> PARTIAL
    INVENTORY --> FAILED
    COLLECTING --> FAILED
    QUEUED --> CANCELLED
    PAUSED --> CANCELLED
    AUTH_REQUIRED --> CANCELLED
~~~

이 diagram은 신규 도메인 상태다. global Job enum에 이 상태들을 추가하지 않는다. ACTIVE 단계에서 cancel을 요청하면 worker가 안전 지점에서 멈춘 뒤 `CANCELLED`로 전이하도록 별도 command/state transition table에 정의한다.

room task는 `PENDING → RUNNING → ACCEPTING → SUCCEEDED/PARTIAL/FAILED`를 기본으로 하며, 인증 대기는 run의 공통 상태로 올린다. 동일 binding의 모든 room task가 인증 재시도를 각각 반복하지 않는다.

### 6.3 DB claim과 물리 브라우저 잠금

동시에 하나의 collector만 같은 profile을 조작해야 한다.

- DB에는 binding별 활성 수집/수동 모드 배타성을 표현한다.
- claim에는 `lease_owner`, `lease_token`, `lease_expires_at`, 증가하는 `fence_epoch`를 포함한다.
- claim은 row lock 또는 기존 패턴에 맞춘 `FOR UPDATE SKIP LOCKED`로 획득한다.
- 브라우저 프로필은 별도 OS file lock으로도 보호한다.
- worker command에는 해당 fence를 넣고, 결과 수락 시 최신 fence와 일치하는지 확인한다.
- lease 만료만으로 같은 profile에 새 Chromium을 바로 시작하지 않는다.
- 기존 process/cgroup의 종료를 확인한 뒤 takeover한다.
- 오래된 worker가 늦게 돌아와도 결과 commit·상태 갱신을 허용하지 않는다.

브라우저 사용자 데이터 디렉터리를 동시에 여러 browser instance가 사용해서는 안 된다. Playwright persistent context에도 이 제한이 있다. [P2]

### 6.4 수동 조작과 자동 수집

runtime 모드는 `STOPPED`, `AUTO`, `PAUSING`, `MANUAL`, `AUTH_REQUIRED`, `ERROR`로 분리한다.

수동 모드 요청 절차:

1. Studio에서 CSRF 보호된 remote lease 요청.
2. 현재 operator·권한·binding 범위 검증.
3. 자동 수집 중이면 `PAUSING`, 현재 다운로드 또는 원자 작업의 안전 지점까지 기다림.
4. checkpoint 기록 후 자동 명령 실행권을 반환하고, browser를 정상 close/flush하여 기존 프로세스 종료를 확인한다.
5. manual fence와 OS profile lock 아래 headed browser를 열고, 유효한 manual lease의 gateway를 활성화한다. 초기 구현은 모드 전환마다 정상 재시작하는 단일 절차를 사용한다.
6. 사용자가 원격 화면에서 인증 또는 상태 확인.
7. “인증 확인 및 수집 재개” 요청.
8. lease·gateway·기존 WebSocket을 종료한 뒤 browser를 정상 close/flush하고 프로세스 종료를 확인한다.
9. 현재 권한과 재개 의도를 확인하고 새로운 AUTO fence·profile lock 아래 browser를 다시 열어 세션·채널을 probe한 뒤 수집을 재개한다. 권한 철회 시에는 자동 재개하지 않는다.

사용자가 원격 탭을 닫았다는 사실만으로 자동 수집을 즉시 재개하지 않는다. 명시적 재개 또는 설정된 lease 만료 후 인증·채널 상태 검증이 필요하다. 자동화 도중 사람의 클릭이 섞이지 않아야 한다.

### 6.5 scheduler

**설계 결정:** scheduler는 기존 owner 프로세스에 좁은 tick loop로 편입하고 PostgreSQL의 schedule/run 상태를 사용한다. 외부 cron이 직접 Playwright를 띄우는 구조로 만들지 않는다.

초기값 제안:

| 설정 | 초기값 |
|---|---|
| `enabled` | false; pilot 완료 후 운영자가 활성화 |
| 반복 간격 | 24시간; UI에서 변경 가능 |
| source timezone | Asia/Seoul, 단 CSV 시각 해석은 실증 필요 |
| binding당 동시 browser | 1 |
| browser당 동시 방 | 1 |
| 동시에 활성 전체 run | 1 |
| missed schedule | 여러 회차를 쌓지 않고 한 번의 catch-up으로 합침 |
| run 중 다음 주기 도래 | active run에 coalesce하고 다음 due 계산 |
| 자동 PDF 발행 | 기본 비활성; 수집과 발행 승인 분리 |

정기 실행도 수동 실행과 같은 command·idempotency·권한 경계를 통과한다. 최초 생성자의 영구 권한을 가정하지 않고 현재 operator의 ACTIVE 상태와 binding grant를 재확인한다.

첫 버전은 매 주기 전체 접근 가능 방에 대한 CSV 내보내기를 기본으로 한다. FULL과 REPEAT는 요청 mode이며 둘 다 전체 방을 대상으로 한다. 이 값은 coverage가 완전하다는 판정이 아니다. 최근 바뀐 방을 먼저 처리하는 것은 가능하지만, 목록의 last activity만으로 나머지 방을 영구 건너뛰는 최적화는 실증 전 도입하지 않는다. 목록 종료·scope·필수 첨부가 unknown이면 근거를 포함한 PARTIAL로 남긴다.

### 6.6 idempotency

- HTTP 접수: 기존 `Idempotency-Key` 계약 사용.
- 동일 key + 동일 request: 같은 run/command 결과.
- 동일 key + 다른 request: conflict.
- timer: `binding + schedule_revision + scheduled_slot`을 논리 intent key로 사용.
- room task: `run_id + room_id + operation_kind` unique.
- publication: 불변 입력 manifest와 정확한 결과 집합에 대한 key.
- 재다운로드한 결과가 달라졌다면 기존 key를 새 request로 재사용하지 않는다.
- PDF: binding + packet revision + student_id + 해당 학생의 ordered question revision subset hash + FINAL/DRAFT mode + layout revision + renderer release + font set hash에 대한 build key. cache hit에서도 현재 권한을 다시 확인한다.

네트워크 timeout은 서버가 요청을 받지 않았다는 증거가 아니다. UI는 같은 key로 재조회·재시도한다.

### 6.7 결과 수락과 Artifact commit

1. worker가 task-local output과 result manifest를 완성한다.
2. Orchestrator adapter가 command ID·attempt·fence·source binding을 확인한다.
3. 허용 workspace 경계, regular file, symlink/hardlink, 크기, media, hash를 확인한다.
4. core 소유 staging으로 materialize하며 복사된 결과의 hash를 다시 검증한다.
5. Catalog가 source 권한과 lifecycle을 다시 확인한다.
6. 기존 `CatalogArtifactService.commit_file_set`으로 canonical Artifact를 발행한다.
7. domain transaction에서 exact Artifact pointers와 observation을 연결한다.
8. task checkpoint와 이벤트를 기록한다.
9. local workspace를 보존 정책에 따라 정리한다.

카카오 다운로드 시간 동안 DB 트랜잭션을 열어 두지 않는다. NAS 발행과 도메인 row 연결은 하나의 완전한 분산 트랜잭션이라고 주장하지 않는다. 기존 publication intent/idempotency로 복구하고, domain accept를 재실행해 이미 발행된 pointer를 연결한다.

발행 완료 후 domain accept 전 프로세스가 죽어도 재수집할 필요가 없어야 한다. 공개되지 않은 orphan Artifact는 reconciliation으로 연결하거나 명시적 정리 대상으로 기록한다. 임의의 SQL row 수정으로 성공을 조작하지 않는다.

### 6.8 오류와 재시도 정책

아래 수치는 초기값 제안이며 운영 실측으로 조정한다.

| 오류 | 처리 | 자동 재시도 |
|---|---|---|
| 네트워크 일시 오류 | room attempt checkpoint, 짧은 지수 backoff | 최대 3회 |
| 제한 응답·비정상 증가 | binding 전체 속도 낮춤·대기 | 서버 안내 우선, 반복 시 일시 중지 |
| `AUTH_REQUIRED` | 수집 중단, 원격 인증 대기 | 로그인 시도 자동 반복 금지 |
| `ACCESS_DENIED` | 현재 scope 접근 불가 기록 | 권한 상태가 바뀌기 전 반복 금지 |
| `UI_CHANGED` | adapter 보호 정지 | 같은 selector 무한 재시도 금지 |
| `EXPORT_SCOPE_UNKNOWN` | 확보 자료 보존, completeness 미확정 | 실증 필요 |
| `AMBIGUOUS_MESSAGE_MATCH` | snapshot 보존, 검토 큐 | 자동 강제 병합 금지 |
| `ATTACHMENT_EXPIRED` | 사진 부재 이유 보존 | fresh link로 확인한 뒤 종료 |
| `HASH_MISMATCH` | 수락 금지, 격리 | 원인 확인 후 한정 재획득 |
| NAS 일시 불가 | local accepted result 보존 | 기존 commit recovery |
| 디스크 부족 | 새 다운로드 중지, checkpoint | 공간 회복 후 재개 |
| `NEEDS_LAYOUT_REVIEW` | PDF 발행 보류 | 같은 입력 무한 렌더 금지 |

`cancel`은 이미 확보한 원본을 삭제하지 않는다. `retry failed`는 실패 task만 대상으로 하되, binding 권한과 capability가 바뀌었으면 새 attempt에 새 관측 기준을 기록한다.

### 6.9 상태와 지표

UI와 운영 로그에 아래를 구분하여 보여 준다.

~~~text
rooms_discovered / rooms_exported / rooms_failed
inventory_complete / inventory_scopes_verified
csv_rows_observed / messages_source_verified / message_matches_unresolved
attachment_bubbles_observed / attachment_files_discovered
attachment_files_downloaded / attachments_unavailable / associations_unresolved
students_mapped / students_unmapped
question_candidates / questions_reviewed / questions_excluded
exports_succeeded / exports_layout_blocked
last_successful_inventory_at / last_completed_run_at / next_due_at
~~~

`downloaded/discovered`를 표시할 수는 있지만, 과거 전체에 몇 장이 있었는지 모르는 상황에서 “전체 사진 100% 백업”이라고 표시하지 않는다. 로그에는 ID·상태·수량·elapsed time·stable error code를 남기고 학생 이름·본문·cookie·signed URL은 남기지 않는다.

---

<a id="section-7"></a>

## 7. 저장·정체성·권한·보존 설계

이 절의 기존 코드 근거는 커밋 **6a824aa48967270cc116661813d3d734f2f16e4e**에 고정한다.
아래의 kakao_* 모듈·테이블·계약명은 **새 구현 제안**이며, 이미 운영 중인 기능을 뜻하지 않는다.
소스와 배포 설정을 읽어 확인한 사항과 실제 서버에서 검증해야 할 사항을 분리한다.

### 7.1 정본과 책임 경계

카카오 원본은 기존 Catalog·PostgreSQL·Artifact 경계에 통합한다.
별도 SQLite, 별도 NAS writer, 독립 object registry, 범용 event-sourcing 프레임워크를 추가하지 않는다.
PostgreSQL에는 identity, revision, 관계, 상태, 시간, 작은 검색 인덱스, hash, Artifact pointer를 저장한다.
원본 CSV, 정규화 메시지 본문, 사진, 큰 관측 증거, 편집 manifest, PDF 바이트는 Artifact에 저장한다.
메시지 전문을 Job.request, JobEvent.data, ArtifactRevision.result, application log에 복제하지 않는다.
Catalog는 도메인 권한·관계·검증을 소유하고, worker는 허용된 로컬 입력과 결과 파일만 취급한다.

기존 [CatalogArtifactService.commit_file_set()](https://github.com/teddyok1206/eomai/blob/6a824aa48967270cc116661813d3d734f2f16e4e/services/catalog_service/eom_catalog_service/artifacts.py#L468)이 파일 집합 발행의 출발점이다.
이 메서드는 내부에서 새 Job ID·Artifact ID·revision ID를 생성하고 publication Job을 등록한다.
근거는 [_commit_file_set_locked()의 ID 생성과 submit_structured_job()](https://github.com/teddyok1206/eomai/blob/6a824aa48967270cc116661813d3d734f2f16e4e/services/catalog_service/eom_catalog_service/artifacts.py#L522)이다.
이미 생성한 수집 실행 Job을 이 메서드에 넘겨 이어서 commit하는 인터페이스는 존재하지 않는다.
따라서 domain run/task/attempt와 **publication_job_id**를 분리하고, commit 반환값을 도메인 결과에 연결한다.
브라우저 수집 실행과 파일 발행 Job은 목적·재시도·수명주기가 서로 다르다.

발행 helper는 [Orchestrator의 stage_file_set_artifact()](https://github.com/teddyok1206/eomai/blob/6a824aa48967270cc116661813d3d734f2f16e4e/services/orchestrator/eom_orchestrator/artifacts.py#L145)와 [commit_file_set_artifact()](https://github.com/teddyok1206/eomai/blob/6a824aa48967270cc116661813d3d734f2f16e4e/services/orchestrator/eom_orchestrator/artifacts.py#L240)를 사용한다.
기존 staging, hash 검증, immutable destination 검증, fsync, atomic replace, COMMITTING 복구를 재사용한다.
collector와 renderer가 해당 helper를 직접 호출하거나 NAS·DB 자격증명을 받도록 만들지 않는다.
수집 결과는 검증된 작은 도메인 receipt와 Artifact pointer를 통해 다음 단계에 전달한다.

### 7.2 question / question_packet / export의 의미

| 용어 | 정체성 | 변경 방식 | 원본 관계 |
|---|---|---|---|
| question | 검토자가 확정하거나 편집하는 논리적 질문 | 같은 question_id 아래 새 question revision | 여러 메시지 occurrence와 원본 첨부를 참조 |
| question_packet | 기간·학생·정렬·포함 정책을 적용해 발행한 질문 묶음 | 선택을 바꾸면 새 packet revision | 정확한 question revision 목록을 고정 |
| export | 특정 packet revision 안의 학생 한 명을 렌더링한 실행 결과 | 새 입력·설정은 별도 export, 같은 요청 재시도는 동일 ID | 학생별 PDF·페이지 미리보기·layout receipt를 참조 |

question_id를 CSV 행 번호, 첫 메시지 시각, 텍스트 hash로 만들지 않는다.
question_revision_id와 Artifact revision ID도 서로 다른 식별자이다.
question_packet의 질문 목록은 “실행 때 최신 질문 검색”이라는 쿼리로 저장하지 않는다.
packet 발행 시점의 ordered question revision 목록을 immutable manifest에 기록한다.
export는 packet revision·student_id·renderer 설정을 고정하고, 나중의 질문 수정으로 기존 PDF를 바꾸지 않는다.
packet은 여러 학생을 포함할 수 있지만 하나의 export는 해당 packet에서 검증한 학생 한 명의 고정된 질문 subset만 사용한다.
POST exports에는 student_id가 필수이며 서버가 packet membership·학생 표시 revision·질문 소속을 다시 검증한다.
PDF 페이지 수는 packet 전체 질문 수가 아니라 **해당 export 학생 subset의 질문 revision 수**와 같아야 한다.
여러 학생 출력은 학생별 export 요청과 개별 진행 상태로 처리하며 ZIP·합본 PDF는 별도의 후속 파생 결과다.
단순 페이지 미리보기와 PDF 다운로드는 동일한 export 결과를 가리키게 한다.
export build/cache key에는 binding 범위, packet revision, student_id, 학생별 ordered question revision subset hash를 포함한다.
FINAL/DRAFT mode, layout revision, renderer release, font set hash와 실제 render option도 key의 입력이다.
같은 packet의 다른 학생 PDF 또는 DRAFT를 FINAL 결과로 재사용하지 않는다.
cache hit도 현재 source 권한·lifecycle을 다시 검증하며 과거 권한 receipt만으로 다운로드를 허용하지 않는다.

질문 split은 새 질문 ID들을 만들고, merge도 결과 질문의 새 ID를 만들어 입력 revision들을 provenance로 연결한다. MVP에서는 동일 binding·동일 room·확인된 동일 student의 질문에만 split/merge를 허용한다. 교차 방·교차 학생 병합은 거부하며 교차 방 기능은 후속 범위다.
원래 질문은 superseded 상태로 전환하되 이미 발행한 packet의 참조를 몰래 변경하지 않는다.
문구·사진 표시 순서·수동 분류 변경은 동일 질문의 새 revision으로 기록한다.
기간 밖 후속 답변을 보존했는지 등의 선택 근거는 packet 정책과 question manifest에 남긴다.
원문 교정본이 필요하더라도 원문 occurrence를 수정하지 않고 display override로 분리한다. 여러 입력을 바꾸는 split/merge는 하나의 composition command로 처리한다. 입력별 expected revision/version을 확인하고 신규 질문의 current pointer·입력 질문의 SUPERSEDED 상태·작은 composition receipt를 같은 도메인 transaction에서 확정한다. Artifact 선발행 후 이 transaction이 실패하면 기존 current pointer를 유지하고 미채택 Artifact로 관리한다.

### 7.3 식별자와 exact Artifact pointer

기존 [ArtifactMemberPointer](https://github.com/teddyok1206/eomai/blob/6a824aa48967270cc116661813d3d734f2f16e4e/packages/protocol/eom_protocol/artifact_members.py#L12)를 재사용한다.
필수 구성은 artifact_id, artifact_revision_id, member_path, schema_ref, media_type, sha256이다.
SHA-256 표현은 EOM의 **sha256:<64자리 소문자 hex>** 형식으로 통일한다.
bare hex, URL, 파일시스템 경로, 원래 다운로드 파일명을 영구 Artifact identity로 대체하지 않는다.
도메인 ID의 prefix와 길이는 구현 전에 schema·Pydantic·ORM에서 일치시킨다.
공개 API·BFF DTO의 source_binding_id와 이 절의 내부 binding_id는 **같은 서버 발급 ID 값**이다.
별도 identity를 발급하거나 이름으로 재매칭하지 않으며, adapter에서 명시적인 필드명 변환만 수행한다.

| 식별자 | 표현하는 것 | 같다고 보아서는 안 되는 것 |
|---|---|---|
| binding_id | EOM operator가 승인한 카카오 채널 연결과 접근 범위 | 채널 표시 이름 |
| room_id | binding 내부에서 관리하는 대화방 | 학생 이름 또는 CSV 파일명 |
| student_id | 표시 이름과 독립된 내부 학생 | 카카오 닉네임 또는 room_id |
| snapshot_revision_id | 특정 방에서 관측한 불변 원본 snapshot | CSV bytes hash만으로 계산한 수집 시도 |
| occurrence_id | 실제 메시지 한 번의 발생 | 발신자·시각·내용이 같은 다른 메시지 |
| blob_id | binding 안에 보관한 정확한 첨부 바이트 | 메시지 occurrence |
| question_revision_id | 특정 질문 편집 결정의 고정 상태 | 논리 question_id |
| packet_revision_id | 특정 선택·순서·정책의 고정 상태 | 기간 조건 문자열 |
| export_id | 고정된 입력으로 수행한 export | 논리 질문 또는 원본 사진 |
| export_revision_id | 수락한 PDF·페이지 preview·receipt의 불변 결과 | 실행 상태 또는 Artifact revision ID |

snapshot_revision_id는 불변 관측 identity이고 parser 변경으로 생기는 normalization revision과 다르다.
공개 attachment_id는 내부 attachment_occurrence_id와 같은 값이며 blob_id와 구분한다.
attachment_revision_id는 해당 occurrence의 연결·가용성·원본 pointer를 고정한 association receipt revision이다.
같은 첨부의 새 확인 결과는 새 attachment revision으로 기록하며 API는 요청한 부모 occurrence와 revision의 소속을 검증한다.
포인터를 읽을 때 존재, revision, 기대 artifact_type, schema, media type, hash, lifecycle을 검증한다.
권한이 있는 최신 revision을 찾는다는 이유로 pin된 revision을 대체하지 않는다.
아카이브 member는 source.csv, snapshot.json, messages.jsonl처럼 고정된 비식별 이름을 사용한다.
사진 member도 학생 이름·방 이름이 들어간 원래 다운로드 파일명으로 만들지 않는다.
관측한 원래 파일명은 필요할 때만 비공개 증거 metadata에 보관하며 연결 키로 사용하지 않는다.

### 7.4 Artifact의 저장 단위

**기본 단위는 방별 CSV snapshot, binding 범위 사진 blob, 질문 manifest, packet manifest, export 결과이다.**
채널 전체 사진을 매번 복사한 단일 거대 capture ZIP을 canonical storage로 만들지 않는다.
월별 packet을 만들 때 이미 보관된 모든 사진을 새로운 Artifact에 다시 복사하지 않는다.
사진 occurrence는 기존 blob의 exact pointer를 참조한다.

| 제안 artifact_type | 주요 member | 생성 시점 |
|---|---|---|
| kakao-room-snapshot | source.csv, snapshot.json | 방 하나의 CSV 확보와 관측 정보 검증 후 |
| kakao-message-normalization | messages.jsonl, parse-receipt.json | snapshot과 parser version을 고정해 파싱한 후 |
| kakao-media-blob | original.<검증 확장자>, media.json | binding 안에서 처음 확보한 바이트 |
| kakao-question-manifest | question.json | 후보 또는 수동 편집 revision 확정 후 |
| kakao-question-packet | packet.json | 학생·기간·질문 revision·순서 고정 후 |
| kakao-question-export | 학생 한 명의 report.pdf, export.json, layout.json | 해당 학생 subset의 렌더·완전성 검사 통과 후 |

페이지 PNG는 대용량일 수 있으므로 export와 결합된 별도 파생 Artifact로 발행해도 된다.
원본 사진의 SHA와 EXIF 보존 여부, 실제 MIME, 파일 크기, 디코딩된 크기를 media receipt에 기록한다.
blob의 media.json과 dedup publication request에는 hash·크기·MIME·decode 크기처럼 바이트에 고유한 정보만 넣는다.
방·메시지·다운로드 시각·제안 파일명·원본 품질 판정 근거는 attachment observation receipt에 둔다.
같은 바이트를 나중에 관측해도 binding+SHA 발행 key의 request hash가 시각·출처 때문에 달라지지 않아야 한다.
원본 사진은 그대로 보존하고, 회전·축소·잘라내기·metadata 제거는 명시적인 파생물로 취급한다.
PDF에는 표시용 파생 바이트를 사용할 수 있으나 원본 pointer와 변환 파라미터를 유지한다.
원본이 확보되지 않은 첨부는 missing/expired/unresolved 상태로 남기며 screenshot을 원본이라고 표시하지 않는다.
사진 문자열 marker 수와 파일 수가 같다는 검증은 만들지 않는다.

snapshot.json에는 binding/room/run/attempt, 수집 시각, CSV hash, 실제 관측 범위, 방 식별 근거, exporter 정보를 기록한다.
정규화 결과는 source snapshot pointer, parser version, timezone 해석, 행 번호, 순서, 역할 판정 근거를 기록한다.
파서 수정은 기존 정규화 파일을 덮어쓰는 대신 같은 snapshot에 대한 새 normalization revision을 만든다.
원본 snapshot의 byte hash는 파서나 학생 연결 수정에 따라 바뀌지 않는다.
불필요한 전체 DOM·네트워크 response를 기본 저장하지 않으며, 필요한 관측 증거도 크기와 필드 allowlist를 둔다.

### 7.5 PostgreSQL 모델: 작은 aggregate와 재생성 가능한 projection

공유 ORM은 [eom_orchestrator.models.Base](https://github.com/teddyok1206/eomai/blob/6a824aa48967270cc116661813d3d734f2f16e4e/services/orchestrator/eom_orchestrator/models.py#L38)이다.
새 모델은 services/catalog_service/eom_catalog_service/kakao_archive_models.py에 두고 Catalog가 소유한다.
아래는 aggregate 경계이며, 이름마다 독립 service·repository·queue를 만들라는 요구가 아니다.
MVP에서는 이 모델을 한 파일과 몇 개의 응용 서비스로 구현하고 복잡성이 실제 생길 때 분리한다.

| canonical aggregate | 최소 record 구성 | 정본으로 남기는 내용 |
|---|---|---|
| ChannelBinding | MVP는 owner binding, 팀 공유 grant는 후속 확장 | 소유자, source 범위, lifecycle, 권한 변경 이력 |
| Student | student 및 display revision | 내부 student_id, owner, 표시 정보, lifecycle |
| Room | room 및 확인된 student mapping revision | 외부 방 identity 근거와 Student 참조 |
| RoomSnapshot | immutable snapshot metadata | 원본 pointer, 관측 시점·범위, completeness |
| MediaBlob | binding별 blob metadata | 바이트 hash, 원본 pointer, 크기·형식 |
| MessageIdentity | occurrence registry와 alignment decision receipt | canonical 발생 ID와 snapshot 간 관계 |
| Question | logical record·immutable revisions·작은 composition receipt | 입력 occurrence, 첨부, 수동 편집 결정과 split/merge 결과 ID |
| QuestionPacket | logical record와 immutable revisions | 정확한 선택 결과, 순서, 기간·학생 정책 |
| Export | 실행 metadata와 export_revision_id를 갖는 immutable output receipt | packet/student pin, renderer 설정, 학생별 PDF와 layout 결과 |

메시지 본문, question 내용, packet의 큰 선택 목록은 Artifact manifest에 두고 PG에는 조회용 작은 projection을 둔다.
room/message/attachment의 모든 속성을 별도 revision 테이블로 정규화하는 과도한 설계를 피한다.
예를 들어 snapshot 행→occurrence 연결과 첨부 association은 typed alignment manifest 하나에 정본을 두고 projection을 재생성할 수 있다.
이 경우 occurrence ID를 재생성 때 새로 발급하지 않도록 ID 발급·교정 결정도 그 manifest에 포함한다.
반대로 업무상 자주 갱신·검토하는 질문 revision과 source grant는 단순 캐시에만 두지 않는다.
run/task/attempt 및 lease 모델은 실행 절의 정의를 따르며 여기서 두 번째 작업 큐를 추가하지 않는다.
MVP에서는 binding owner만 자료에 접근하며 Studio ADMIN이라는 이유만으로 다른 owner의 학생 자료를 열지 못한다.
Student는 owner 범위에서 식별하고 room mapping은 같은 허용 source 범위의 학생을 참조하게 한다.
학생 이름은 unique key가 아니며 이름 변경은 display revision으로 남긴다.
question/packet은 student_id, student display revision, room-to-student mapping revision을 고정한다.
기존 packet의 학생 표시는 이후 이름·mapping 교정에 따라 자동으로 바뀌지 않는다.

조회 projection에는 binding_id, room_id, occurrence_id, source timestamp, row_ordinal, role, kind를 둔다.
정규화 본문의 byte offset을 저장한다면 정확한 member pointer·hash·offset·length를 함께 묶는다.
offset은 UTF-8 정규화 member의 byte 기준이며 원본 CSV의 화면 행 번호나 문자 offset과 혼용하지 않는다.
본문 조각을 읽기 전 pointer와 범위를 검증하고, 큰 파일 전체를 모든 목록 요청마다 읽지 않는다.
room-to-student 연결은 사람 이름 문자열의 유사성으로 자동 합치지 않는다.
표시 이름이 바뀌거나 같은 이름이 여러 명일 때 manual binding과 미확정 상태를 지원한다.

기존 [LearningMaterialRevisionRecord](https://github.com/teddyok1206/eomai/blob/6a824aa48967270cc116661813d3d734f2f16e4e/services/catalog_service/eom_catalog_service/material_learning_models.py#L60)의 composite FK, owner별 idempotency, previous revision 패턴을 참고한다.
이 패턴을 참고하되 실제 카카오 대화를 learning material 또는 Item으로 등록하지 않는다.
Artifact의 generic approved 플래그는 공개 여부나 학생 정보 열람 권한을 표현하지 않는다.
기존 [ArtifactRecord/ArtifactRevisionRecord](https://github.com/teddyok1206/eomai/blob/6a824aa48967270cc116661813d3d734f2f16e4e/services/orchestrator/eom_orchestrator/models.py#L130)의 approved를 false로 바꾸는 방식으로 private 저장을 구현하지 않는다.

### 7.6 Snapshot 일치 판단과 사진 중복 제거

다음 unique key는 실제 메시지를 지우므로 금지한다: room_id + timestamp + sender + body_hash.
같은 시각에 같은 학생이 동일 문구를 두 번 보냈다면 occurrence는 두 개이다.
snapshot 내부 최초 관측 identity는 snapshot_revision_id + row_ordinal이며, 이 조합은 유일해야 한다.
CSV가 같아도 다음 날 다시 관측한 사실은 별개 capture attempt로 기록할 수 있다.
동일 바이트 재관측에서는 원본 Artifact pointer를 재사용해도 되지만 관측 시각·범위·run을 잃지 않는다.

안정적 message ID를 합법적으로 관측할 수 있으면 binding·room 범위에서 우선 사용한다.
관측할 수 없으면 message fingerprint를 anchor 후보로 쓰고, 순서를 보존하는 bounded overlap matching을 수행한다.
최소 비교 단위에는 timestamp 해석, sender role, 원문 종류, raw text hash, 인접 순서가 포함된다.
반복 문구 구간은 단일 hash로 강제 매칭하지 않고 multiplicity와 주변 anchor를 함께 확인한다.
동일 점수의 여러 정합이 가능하면 AMBIGUOUS 상태를 남겨 수동 검토하도록 한다.
삭제 표시, CSV 잘림, 오래된 구간의 미노출은 기존 occurrence의 삭제 증거로 단정하지 않는다.
매칭 전후 정규화 pointer, matcher version, 입력 범위, 선택 근거, ambiguity를 alignment receipt에 남긴다.
수동 수정은 새 receipt로 기존 결정을 supersede하며 원본 observation을 수정하지 않는다.

사진 blob의 중복 제거 범위는 **binding_id + sha256**이다.
크기·MIME·검증 결과와 실제 바이트 hash를 확인한 뒤 동일 binding의 기존 blob을 재사용한다.
학생 이름·다운로드 파일명·사진 marker 위치만으로 기존 blob을 연결하지 않는다.
별개의 첨부 occurrence가 같은 blob을 참조하는 것은 허용한다.
다른 binding 간 전역 dedup 조회와 blob 공유는 MVP에서 제공하지 않는다.
이 범위 제한은 다른 ACL의 파일 존재 여부가 노출되거나 소유권이 뒤섞이는 일을 막는다.
첨부 association은 observed message ID/DOM 위치/album 순서/수동 확인 등 연결 근거를 별도로 기록한다.
“파일 확보 완료”와 “어떤 메시지의 첨부인지 확인 완료”는 서로 다른 상태이다.
관측했지만 미확보·미확정인 첨부도 question 입력 manifest의 unresolved reference로 유지한다.
늦게 확보한 사진과 교정된 association은 새 observation/association revision으로 기록하고 current projection만 갱신한다.
기존 확정 question·packet·export에 사진을 몰래 끼우지 않고 새 질문 revision 검토→새 packet revision→새 export로 반영한다.

### 7.7 제약과 DDL 예시

다음은 migration 작성 방향을 보여 주는 일부 DDL이며 그대로 실행하는 완성 migration은 아니다.
실제 ID 길이·prefix·테이블 이름은 먼저 확정한 schema/Pydantic 모델과 일치시켜야 한다.
필수 schema_ref/media_type·감사 필드, 상태별 NOT NULL/CHECK, 일부 복합 FK·삭제 정책·참조 테이블 정의는 이 개념 스케치에서 생략했다.
생략한 제약이 선택 사항이라는 뜻은 아니며 기존 FK 대상의 실제 타입도 composed metadata로 확인한 후 migration에 반영한다.
본문 payload를 JSONB에 복제하기보다 아래처럼 revision과 exact pointer 관계를 강제한다.

~~~sql
CREATE TABLE kakao_questions (
    question_id text PRIMARY KEY,
    binding_id text NOT NULL REFERENCES kakao_channel_bindings(binding_id),
    room_id text NOT NULL REFERENCES kakao_rooms(room_id),
    current_revision_id text,
    resource_version bigint NOT NULL DEFAULT 1 CHECK (resource_version > 0),
    lifecycle_state text NOT NULL CHECK (lifecycle_state IN ('ACTIVE','SUPERSEDED','RETIRED')),
    UNIQUE (binding_id, question_id)
);

CREATE TABLE kakao_question_revisions (
    question_revision_id text PRIMARY KEY,
    question_id text NOT NULL REFERENCES kakao_questions(question_id) ON DELETE RESTRICT,
    revision_number integer NOT NULL CHECK (revision_number > 0),
    previous_revision_id text,
    artifact_id varchar(41) NOT NULL,
    artifact_revision_id varchar(36) NOT NULL,
    member_path varchar(512) NOT NULL,
    manifest_sha256 varchar(71) NOT NULL CHECK (manifest_sha256 ~ '^sha256:[0-9a-f]{64}$'),
    request_sha256 varchar(71) NOT NULL CHECK (request_sha256 ~ '^sha256:[0-9a-f]{64}$'),
    created_by text NOT NULL REFERENCES operators(operator_id) ON DELETE RESTRICT,
    idempotency_key varchar(128) NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (question_id, question_revision_id),
    UNIQUE (question_id, revision_number),
    UNIQUE (created_by, idempotency_key),
    FOREIGN KEY (artifact_id, artifact_revision_id)
      REFERENCES artifact_revisions(logical_artifact_id, revision_id) ON DELETE RESTRICT,
    FOREIGN KEY (question_id, previous_revision_id)
      REFERENCES kakao_question_revisions(question_id, question_revision_id) ON DELETE RESTRICT
);

ALTER TABLE kakao_questions ADD CONSTRAINT fk_kakao_question_current
  FOREIGN KEY (question_id, current_revision_id)
  REFERENCES kakao_question_revisions(question_id, question_revision_id) ON DELETE RESTRICT;

CREATE UNIQUE INDEX uq_kakao_snapshot_ordinal
  ON kakao_message_observations(snapshot_revision_id, row_ordinal);
CREATE UNIQUE INDEX uq_kakao_binding_blob
  ON kakao_media_blobs(binding_id, sha256);
CREATE INDEX ix_kakao_question_period
  ON kakao_question_projection(binding_id, first_student_at, question_id)
  WHERE lifecycle_state = 'ACTIVE';
~~~

room_id도 같은 binding에 속한다는 조건을 실제 migration의 (binding_id, room_id) composite FK로 보장한다.
위 DDL이 참조하는 기존 operators의 타입·FK 호환성은 SQLAlchemy metadata로 확인하며 문자열 타입을 추측하지 않는다.
previous_revision과 current_revision은 같은 question의 revision만 참조하게 한다.
question_packet의 선택 projection에는 (packet_revision_id, position) 유일성과 position의 양수·상한 제약을 둔다.
같은 question의 중복 게재가 필요하지 않다면 (packet_revision_id, question_id)도 unique로 제한한다.
immutable revision에는 UPDATE/DELETE를 거부하는 trigger를 두어 일반 API에서의 변경을 막는다.
기존 [0079 migration의 immutable trigger](https://github.com/teddyok1206/eomai/blob/6a824aa48967270cc116661813d3d734f2f16e4e/migrations/versions/20261112_0079_chat_model_settings.py#L49)를 참고하되 삭제 운영은 별도로 정의한다.

### 7.8 인덱스·계산량·동시 실행

| 조회 패턴 | 필요한 index·상한 | 목표 비용 |
|---|---|---|
| operator의 binding 목록 | owner_operator_id, lifecycle_state, binding_id | O(log B + page size) |
| binding의 room 목록 | binding_id, last_observed_at DESC, room_id | keyset pagination |
| room의 snapshot 이력 | room_id, observed_at DESC, snapshot_revision_id | O(log S + page size) |
| 기간 안의 question 후보 | binding_id, first_student_at, question_id | O(log Q + selected Q) |
| 동일 사진 재사용 | unique(binding_id, sha256) | O(log M) + 첫 hash O(bytes) |
| snapshot 행 표시 | unique(snapshot_revision_id, row_ordinal) | O(log N + page size) |
| packet 렌더 입력 | packet_revision_id, position | O(selected Q + selected attachments) |

전체 목록에는 큰 OFFSET 대신 안정적인 동률 정렬 키가 있는 keyset pagination을 사용한다.
binding의 권한 범위를 쿼리에서 먼저 제한하며 전체 자료를 가져온 뒤 다른 사용자 자료를 걸러내지 않는다.
Artifact pointer 해석은 [기존 PinnedArtifactReadContext](https://github.com/teddyok1206/eomai/blob/6a824aa48967270cc116661813d3d734f2f16e4e/services/catalog_service/eom_catalog_service/pinned_artifact_resolution.py#L463)의 작업 범위 batch/prefetch를 참고한다.
하나의 packet에 질문 수×사진 수만큼 DB/NAS 조회가 생기는 N+1 구조를 피한다.
순서 matching에 전체 이력의 무제한 O(N²)를 허용하지 않고 anchor, 비교 window, 최대 처리 건수로 범위를 제한한다.
상한 초과나 해소되지 않은 중복은 추측으로 성공 처리하지 않고 분할 처리 또는 검토 대상으로 반환한다.

question 편집의 내부 명령에는 expected_revision_id와 expected resource_version을 요구한다.
공개 API에서는 body의 parent_revision_id와 If-Match: "vN"을 검증해 이 내부 값으로 변환하며 두 입력이 현재 상태와 일치해야 한다.
새 revision manifest를 발행한 뒤 짧은 DB transaction에서 current_revision_id를 CAS 갱신한다.
갱신 행 수가 0이면 내부 revision conflict이며 공개 API에서는 **412 API_PRECONDITION_FAILED**로 매핑한다.
If-Match 누락은 428, 형식 오류·version 불일치는 412이며 다른 사람의 편집을 덮어쓰지 않는다.
같은 작업의 재전송은 owner/binding/operation scope를 포함한 idempotency key와 request hash로 구분한다.
같은 key인데 request hash가 다르면 **409 API_IDEMPOTENCY_CONFLICT**이며 이전 결과를 다른 요청에 재사용하지 않는다.
발행 후 CAS에 실패한 Artifact는 미채택 결과로 기록하고 기존 발행·보존 규칙에 따라 관리한다.

사진 발행은 (binding_id, sha256) 범위에서 기존 publication lock과 PG unique constraint를 함께 사용한다.
[artifact_publication_lock()](https://github.com/teddyok1206/eomai/blob/6a824aa48967270cc116661813d3d734f2f16e4e/services/orchestrator/eom_orchestrator/artifact_publication_lock.py#L11)은 PostgreSQL advisory lock이며 queue·lease·source authority를 만들지 않는다.
브라우저 profile lock, domain run lease, Artifact publication lock은 서로 다른 책임을 갖는다.
오래 걸리는 브라우저 조작·hash 계산·PDF 렌더링 중에는 DB row lock을 유지하지 않는다.
packet 발행은 선택 시점의 revision 목록을 고정하고 입력 권한·lifecycle을 짧은 transaction에서 재확인한다.
recovery에서도 현재 source 권한을 검사하며 권한이 유효할 때 시작했다는 사실만으로 결과를 공개하지 않는다.

### 7.9 protocol·migration 추가 규칙

새 계약은 schemas/kakao-archive/와 packages/catalog_contracts/eom_catalog_contracts/resources/kakao-archive/에 배치하는 안을 따른다.
JSON Schema 2020-12를 먼저 정의하고 additionalProperties, 최대 건수·문자 수, timezone, 상태 enum을 제한한다.
Pydantic 모델, canonical schema 복사본, package resource의 bytes/hash가 일치해야 한다.
[CATALOG_SCHEMA_RESOURCES](https://github.com/teddyok1206/eomai/blob/6a824aa48967270cc116661813d3d734f2f16e4e/packages/catalog_contracts/eom_catalog_contracts/validation.py#L35)에 version과 sha256을 등록한다.
[pyproject.toml의 package-data](https://github.com/teddyok1206/eomai/blob/6a824aa48967270cc116661813d3d734f2f16e4e/pyproject.toml#L89)에도 새 resource glob을 추가한다.
기존 schema version의 의미나 hash를 새 기능에 맞춰 바꾸지 않고 새 version으로 추가한다.

Artifact commit의 protocol_version/protocol_schema_hash도 명시하며 기존 catalog/1.1 정의를 변경하지 않는다.
새 계약군의 등록 방식과 version은 기존 Catalog protocol 등록 규칙에 맞춰 확정한다.
기존 [Catalog protocol 상수](https://github.com/teddyok1206/eomai/blob/6a824aa48967270cc116661813d3d734f2f16e4e/services/catalog_service/eom_catalog_service/artifacts.py#L55)를 새 계약의 hash로 바꾸지 않는다.
schema_ref는 eom://schemas/kakao-archive/…/1.0 같은 version 고정 URI로 하고 네트워크에서 해석하지 않는다.
parser, matcher, layout policy, renderer, font bytes의 version/hash를 manifest에 명시한다.

검사한 소스의 Alembic은 79개 revision이고 단일 head는 **20261112_0079**이다.
근거는 [0079의 revision/down_revision 선언](https://github.com/teddyok1206/eomai/blob/6a824aa48967270cc116661813d3d734f2f16e4e/migrations/versions/20261112_0079_chat_model_settings.py#L7)이며 운영 DB의 적용 상태를 확인한 것은 아니다.
구현할 때는 최신 branch의 head를 다시 확인해 후속 migration을 만들고 불필요한 별도 branch를 만들지 않는다.
[migrations/env.py](https://github.com/teddyok1206/eomai/blob/6a824aa48967270cc116661813d3d734f2f16e4e/migrations/env.py#L8)에 새 모델을 import한다.
[test_alembic_head_matches_composed_sqlalchemy_metadata()](https://github.com/teddyok1206/eomai/blob/6a824aa48967270cc116661813d3d734f2f16e4e/tests/integration/test_control_plane_persistence.py#L4257)로 composed metadata와의 차이를 검증한다.
기존 Job 상태 enum에 PAUSED_AUTH나 NEEDS_LAYOUT_REVIEW를 추가하지 않는다.
해당 상태는 새 domain run 또는 review 상태로 다루고 기존 JobRecord의 닫힌 실행 상태를 유지한다.

### 7.10 비공개 source 권한과 파일시스템 신뢰 경계

저장소에 범용 source_authorizations 테이블이 존재한다는 전제를 두지 않는다.
새 kakao_archive_authorization.py와 binding 단위 ACL을 구현하며 MVP의 ACL은 owner 일치와 현재 permission 검사다.
팀 공유 grant 테이블/API는 MVP의 필수 전제가 아니며 후속 버전에서 명시적인 source 범위로 추가한다.
기준은 기존 operator identity이며 확인되지 않은 workspace tenancy 프레임워크를 도입하지 않는다.
현재 operator 상태·권한·binding grant·room 소속·source lifecycle을 각 작업에서 확인한다.
카카오 매니저, Studio ADMIN, Linux 서비스 계정은 별개 권한이며 이 설계는 카카오 마스터 권한을 요구하거나 가정하지 않는다.
참고는 [CuratedDocumentAssemblyService._authorized_actor()](https://github.com/teddyok1206/eomai/blob/6a824aa48967270cc116661813d3d734f2f16e4e/services/catalog_service/eom_catalog_service/curated_document_assembly_service.py#L521)의 현재 권한 재조회다.
인증된 actor의 오래된 role snapshot이나 worker가 주장하는 접근 가능 여부를 그대로 신뢰하지 않는다.

사진·CSV·PDF·원본 export는 domain ID로 소속과 권한을 확인한 다음 exact pointer를 해석한다.
클라이언트가 보낸 Artifact ID를 generic download에 곧바로 연결하지 않는다.
approved=true는 Artifact 수용 조건이며 private access 허가가 아니다.
[artifact_identity_hints()](https://github.com/teddyok1206/eomai/blob/6a824aa48967270cc116661813d3d734f2f16e4e/services/catalog_service/eom_catalog_service/pinned_artifact_resolution.py#L89)도 source authorization을 수행하지 않는다고 명시한다.
다운로드에는 [open_verified_member()](https://github.com/teddyok1206/eomai/blob/6a824aa48967270cc116661813d3d734f2f16e4e/services/catalog_service/eom_catalog_service/artifacts.py#L805) 등의 검증된 stream을 사용하고 연결 종료 시 descriptor를 닫는다.
응답에 NAS 절대 경로, 인증 cookie, profile 위치, private debug URL을 노출하지 않는다.
private cache policy를 설정하며 공유 CDN·인증 없는 static mount에 원본이나 preview를 놓지 않는다.

**확인한 배포 설정에서 앱 사용자 간 권한 분리와 NAS 관리자로부터의 격리는 같은 보장이 아니다.**
[API unit](https://github.com/teddyok1206/eomai/blob/6a824aa48967270cc116661813d3d734f2f16e4e/infra/systemd/eom-api.service#L42)은 /mnt/nas를 InaccessiblePaths로 차단한다.
[Catalog unit](https://github.com/teddyok1206/eomai/blob/6a824aa48967270cc116661813d3d734f2f16e4e/infra/systemd/eom-catalog-application-runner.service#L8)은 eom-catalog-manager와 supplementary eom으로 실행되며 NAS 쓰기 권한과 UMask=0077을 갖는다.
한편 [NAS hardening 계약](https://github.com/teddyok1206/eomai/blob/6a824aa48967270cc116661813d3d734f2f16e4e/scripts/infra/harden_artifact_mount.sh#L35)은 CIFS의 forceuid/forcegid/nounix, file_mode=0660, dir_mode=0770, eom:eom을 요구한다.
따라서 개별 파일의 chmod만으로 binding 간 OS 수준 격리를 달성한다고 주장하지 않는다.
동일 eom group의 관리 서비스와 NAS 관리자는 현재 스토리지 신뢰 경계 안에 있다.
새 collector와 renderer에는 이 group이나 NAS mount를 부여하지 않고 exact input만 stage한다.
운영 도입 시 실제 mount option, service identity, supplementary group, worker의 읽기 차단을 실측한다.
관리 서비스·NAS 관리자로부터도 격리해야 한다면 암호화·키 관리·별도 private storage policy를 ADR로 설계하며 기존 mount를 임의로 바꾸지 않는다.

private-chat query Artifact나 GeneralChatConversation을 카카오 저장소로 재사용하지 않는다.
기존 [private_chat_query_artifact_read.py](https://github.com/teddyok1206/eomai/blob/6a824aa48967270cc116661813d3d734f2f16e4e/services/catalog_service/eom_catalog_service/private_chat_query_artifact_read.py#L91)는 embedding 수치 결과물을 다루는 별도 기능이다.
이 기능에서 [KnowledgeSnapshotAnalysisRecord](https://github.com/teddyok1206/eomai/blob/6a824aa48967270cc116661813d3d734f2f16e4e/services/catalog_service/eom_catalog_service/knowledge_graph_models.py#L192) source 등록, Item 생성, Graph 공개, embedding 생성을 수행하지 않는다.
private Artifact를 저장하는 것만으로 학습·RAG에 등록되지 않는다는 점을 부정 통합 테스트로 검증한다.

### 7.11 보존·삭제·백업

보존 policy는 binding에 version과 함께 설정하며 카카오에서 보이는 기간과 이미 저장한 원본의 보존 기간을 혼동하지 않는다.
원본, 파생 preview, PDF, debug evidence, 작업 임시 파일, backup은 별도 보존 대상 구분을 갖는다.
보존 일수·용량은 운영 입력으로 확정하고 근거 없는 영구 보존 또는 특정 일수를 코드에 고정하지 않는다.
용량 부족이나 삭제 예정이 있으면 상태·건수·가장 오래된 대상 시점을 표시하며 오래된 source를 조용히 삭제하지 않는다.
profile과 cookie는 원본 Artifact·packet·자료 export에 포함하지 않고 별도 인증 관리 대상으로 다룬다.

MVP의 일반 삭제는 logical retirement와 접근 중지로 구현하며 물리적으로 지웠다고 표시하지 않는다.
immutable history 보호와 개인정보 보존 종료는 다른 책임이며 후자를 불변성만을 이유로 방치하지 않는다.
물리 purge에는 대상·이유를 고정한 intent, 참조 closure, 재시도 가능한 실행, 삭제 receipt가 필요하다.
closure에는 CSV snapshot, 정규화 본문, 사진 blob, question manifest, packet, PDF, preview, 원본 bundle을 포함한다.
원본 CSV에서 특정 행만 제자리 수정한 뒤 이전 hash를 유지하려고 해서는 안 된다.
필요하면 별도 redacted successor를 만들고 원본 snapshot과 이를 포함한 파생물의 보존·실효를 명시적으로 처리한다.
같은 binding의 다른 occurrence가 같은 blob을 참조한다면 첨부 하나의 제외만으로 공유 blob을 지우지 않는다.
단순한 가변 ref_count에만 의존하지 않고 확정 revision 참조에서 도달 가능성을 검사한다.

기존 generic Artifact 행과 NAS 바이트 중 한쪽만 지우는 구현은 채택하지 않는다.
기존 recovery verifier가 DB inventory와 Artifact snapshot inventory의 일치를 요구하므로 물리 purge는 이 계약에도 영향을 준다.
따라서 운영에서 물리 purge를 활성화하기 전에 Artifact lifecycle/tombstone과 복구 검증의 처리를 전용 ADR·migration·테스트로 추가한다.
일반 runtime에서 immutable trigger를 끄는 API나 NAS의 임의 경로를 rm하는 기능을 만들지 않는다.
삭제 감사에는 최소 내부 ID·policy revision·시각·결과를 남기며 지운 본문이나 이름을 복제하지 않는다.
삭제한 source를 참조하는 과거 packet은 이유가 있는 unavailable 상태가 되며 다른 source로 자동 대체하지 않는다.
backup에 남는 기간까지 고려해 live_removed / backup_expiry_pending / purged 상태를 구분한다.

백업은 기존 [Database and Artifact recovery drill](https://github.com/teddyok1206/eomai/blob/6a824aa48967270cc116661813d3d734f2f16e4e/docs/operations/DATABASE_ARTIFACT_RECOVERY_DRILL.md#L5)에 통합한다.
PostgreSQL dump만 또는 NAS만 복원한 것을 성공으로 보지 않고 대응하는 immutable Artifact snapshot과 쌍으로 검증한다.
기존 [verify_recovery_pair.py](https://github.com/teddyok1206/eomai/blob/6a824aa48967270cc116661813d3d734f2f16e4e/scripts/infra/verify_recovery_pair.py#L56)의 manifest·inventory·hash 검증에 새 private source도 포함한다.
live NAS의 다른 directory로 복사한 것만으로 NAS 손실 대책을 갖췄다고 설명하지 않는다.
복원은 disposable DB에서 시험하고 missing pointer를 최신 revision으로 바꾸어 복구했다고 처리하지 않는다.
backup 복원 시에도 삭제·실효 ledger를 다시 적용해 지운 대화가 이용 가능한 상태로 되살아나지 않게 한다.

### 7.12 원본 export와 immutable manifest

PDF report export와 별도로 권한 있는 사용자가 증거를 내려받는 원본 bundle export를 정의할 수 있다.
이는 요청 시 구성하는 파생물이며 매 기간 packet에 사진 전체를 중복 보관해야 하는 이유가 아니다.
bundle에는 source CSV, 필요한 정규화 본문, 선택한 원본 사진, question/packet manifest, 검증 manifest를 포함한다.
인증 profile, cookie, service secret, 내부 NAS path, 다른 binding의 자료는 포함하지 않는다.
학생 표시 이름이 들어간 다운로드 파일명이 필요하면 사용자 설정으로 생성하고 canonical member 이름과 구분한다.

manifest에는 schema version, binding scope, packet revision, 선택 snapshot/question revision, member별 byte count와 sha256을 고정한다.
각 member와 원본 Artifact pointer의 대응, photo occurrence와 blob의 다대일 관계, 미확보·미해결 첨부도 기록한다.
CSV 확보 시각, source timezone 해석, parser/matcher version, 수동 교정 revision을 포함한다.
ZIP 내부에는 안전한 상대 경로와 opaque 내부 ID를 사용하며 절대 경로·../·symlink entry를 금지한다.
manifest 자체 hash는 자기 참조를 피하는 명시적인 canonicalization 규칙으로 계산한다.
manifest hash와 archive bytes hash는 다른 값이며 export receipt에 둘 다 저장한다.
snapshot completeness가 확인되지 않았다면 전체 이력 원본이라고 명명하지 않고 관측 범위와 누락을 표시한다.
생성 후 source 권한이 실효되면 과거 export URL을 알고 있다는 이유만으로 다시 다운로드할 수 없다.

### 7.13 저장 계층의 수용 기준

- 같은 publication key의 동시 실행·재전송이 충돌하지 않으며 서로 다른 request hash에는 conflict를 반환한다.
- NAS 발행 전후 중단을 기존 COMMITTING recovery로 복구하고 domain receipt와 publication_job_id를 다시 연결한다.
- 동시 편집에서 CAS에 실패한 쪽이 현재 question revision을 덮어쓰지 않는다.
- 같은 시각·본문을 두 번 보낸 메시지는 두 occurrence로 남으며 검증된 재관측 관계만 중복 표시에서 제외한다.
- 애매한 snapshot은 보존하고 검토 대상으로 표시하며, 미검증 병합을 중복 없는 전체 이력이라고 주장하지 않는다.
- 같은 사진을 두 번 보냈다면 두 attachment occurrence와 하나의 binding 내부 blob을 표현한다.
- 다른 binding의 같은 hash를 조회·추측·공유할 수 없으며 다른 operator의 pointer를 알아도 읽지 못한다.
- parser 변경 후에도 원본 CSV bytes, snapshot revision, 이미 발행한 packet의 입력 pin이 바뀌지 않는다.
- 원문·학생 이름·cookie가 generic Job metadata나 표준 log에 유출되지 않는다.
- Artifact approved와 private access를 구분하고 grant 실효 후 read/build/recovery/download를 거부한다.
- 실제 NAS mount와 worker sandbox를 확인하지 않고 OS 수준 완전 격리로 판정하지 않는다.
- 원본 사진·본문 변경은 새 revision/파생물로 추적되며 원본 bundle manifest로 hash를 검증할 수 있다.
- 한 export의 PDF·PNG·layout receipt는 한 학생의 같은 subset을 가리키며 페이지 수가 그 subset의 질문 수와 같다.
- DB와 Artifact snapshot 복구 쌍을 검증하고 삭제 ledger 적용 후의 비공개 상태를 재현한다.
- 저장·packet 발행·export 어느 경로에서도 LLM, OCR, embedding, Graph 등록을 호출하지 않는다.

구현 검증은 기존 Catalog Artifact recovery, pinned pointer, migration metadata, bounded download 테스트에 필요한 사례를 추가한다.
소스 검사는 운영 DB 적용 상태, 현재 NAS mount, 실제 카카오 session, collector 완전성을 확인한 증거가 아니다.

---

<a id="section-8"></a>

## 8. 학생 연결·질문 후보·기간 선택

### 8.1 학생 identity

학생은 표시 이름과 독립된 내부 ID를 갖는다. 학생이 닉네임을 바꾸거나, 이름이 같은 학생이 여러 명이거나, 한 학생이 방을 여러 개 사용해도 자료를 잘못 합치지 않아야 한다.

최소 학생 record:

~~~text
student_id
owner_operator_id
display_name
current_display_revision_id
lifecycle_state
created_at_utc
~~~

학생 연결은 `room_id → student_id`의 확인된 mapping revision으로 기록한다. 한 방을 여러 학생과 연결해야 하는 실제 사례가 나오면 메시지 범위별 mapping을 후속 설계한다. 첫 버전은 **한 방의 현재 학생 1명**을 기본으로 하며, 혼합 방은 자동 발행하지 않고 사람이 질문별 학생을 지정하게 한다.

매핑 교정이 과거 packet을 몰래 바꾸어서는 안 된다. 새 질문 후보는 새 mapping을 사용하고, 기존 packet은 발행 당시 학생 표시 revision과 mapping revision을 유지한다.

### 8.2 질문은 메시지 행과 다르다

대화의 실제 “질문 한 개”를 내용 이해 없이 항상 결정할 수는 없다. 이 시스템의 자동 결과는 **질문 후보**이며, 사람이 경계를 확인할 수 있어야 한다.

예를 들어 다음은 자동으로 하나의 후보가 될 수 있다.

~~~text
학생의 첫 문장
학생의 추가 설명
학생의 사진 묶음
학생의 마지막 질문 문장
이후 관리자 답변
~~~

관리자 답변은 후보의 context로 보관하지만, 기본 PDF에는 학생 메시지와 학생 사진만 출력한다. “답변 포함”을 선택한 경우에만 관리자 context를 명시적으로 넣는다.

한 메시지에 질문 두 개가 있을 수도 있고, 두 메시지가 같은 질문을 설명할 수도 있다. 사진 하나 안에 여러 문제가 들어 있을 수도 있다. 물음표 개수, 하루 단위, 고정 10분 간격만으로 확정 질문을 만들지 않는다.

### 8.3 기본 규칙 turn_v1

초기 자동 후보 규칙은 다음과 같이 고정하고 version을 부여한다.

1. 방의 메시지를 검증된 source 순서대로 읽는다.
2. 학생의 연속 발화를 한 student turn으로 묶는다.
3. 학생 사진 occurrence는 원래 메시지·album 순서대로 같은 turn에 붙인다.
4. 이어지는 관리자 발화를 그 후보의 reply context로 연결한다.
5. 다음 학생 turn이 시작되면 새로운 후보를 만든다.
6. 삭제 표시만 있는 turn, 시스템 알림만 있는 구간은 질문 후보에서 제외한다.
7. 발신 방향 미확정 또는 첨부 관계 미확정은 검토 대상으로 표시한다.
8. 아직 답변이 없는 마지막 학생 turn도 열린 후보로 유지한다.

서로 다른 날짜에 걸친 관리자 답변을 잘라 버리지 않는다. 오래 기다린 답변이 있을 수 있으므로, “24시간 이상 지났으면 다른 질문”이라는 규칙은 기본값이 아니다.

`감사합니다` 같은 짧은 응답이나 행정 문의는 `POSSIBLE_ACK`, `POSSIBLE_ADMINISTRATIVE` 검토 태그를 붙일 수 있다. 그 태그만으로 실제 학습 질문을 삭제하지 않는다. 사진이 붙은 짧은 메시지는 특히 자동 제외하지 않는다.

예외적으로 매우 긴 공백, 서로 떨어진 여러 사진, 예상보다 긴 student turn에는 `BOUNDARY_REVIEW`를 붙인다. 이것은 자동 분할 명령이 아니라 검토 근거다.

### 8.4 규칙 의사 코드

~~~python
def build_candidates(messages, policy):
    candidates = []
    active = None
    phase = "NONE"

    for message in messages:
        if message.role == "system":
            continue
        if message.role == "unknown":
            record_unresolved(message)
            continue

        if message.role == "student":
            if active is None or phase == "STAFF_REPLY":
                active = new_candidate(message)
                candidates.append(active)
            active.student_occurrences.append(message.pointer)
            active.attachments.extend(all_observed_student_attachment_refs(message))
            phase = "STUDENT_TURN"
        elif message.role == "staff":
            if active is not None:
                active.reply_context.append(message.pointer)
                phase = "STAFF_REPLY"

    return review_and_filter_deleted_only(candidates, policy)
~~~

실제 구현은 immutable output을 반환하는 순수 함수와 작은 명시적 상태 모델로 작성한다. 위 의사 코드의 mutable list는 설명용이다. 확보 여부와 무관하게 관측된 첨부 reference를 모두 보존한다. 미확보·연결 미확정 사진을 required set에서 빼서 성공으로 만들면 안 된다. 해당 상태는 FINAL 발행 blocker다. source의 삭제 상태, ambiguous sequence, unknown sender로 발생한 경계 불확실성을 결과 receipt에 포함한다.

`unknown` 메시지를 건너뛰었다고 앞뒤 학생 발화를 확정 병합하면 안 된다. 불확실 구간을 통과한 후보는 검토 전 발행할 수 없도록 `boundary_uncertain` 근거를 기록한다.

### 8.5 후보 identity와 수동 편집 유지

자동 후보의 identity는 첫 메시지 hash만으로 결정하지 않는다. 원본 occurrence 범위, 규칙 version, mapping revision과 대응 decision을 기록한다.

재수집 후:

- source ID가 같은 메시지에 첨부 증거만 추가되면 기존 후보와 관계를 유지할 수 있다.
- 기존 사람이 확정한 question revision은 자동으로 덮어쓰지 않는다.
- 새 내용이 생기면 수정 제안 또는 새 후보를 만든다.
- 원문 삭제·역할 변경·사진 연결 교정이 기존 확정 질문에 영향을 주면 `STALE_SOURCE`로 표시한다.
- 이미 발행한 packet과 PDF는 immutable하며 새 원문 상태를 묵시적으로 반영하지 않는다.
- 결과를 다시 발행하려면 새 question/packet revision을 명시적으로 선택한다.

원본 관측과 편집 의도는 따로 저장한다. 따라서 parser를 고친 뒤 projection을 다시 만들어도 사람의 분할·병합·제외 판단이 사라지지 않아야 한다.

### 8.6 수동 편집 동작

| 동작 | 저장 결과 |
|---|---|
| 질문 확정 | current question의 새 reviewed revision |
| 제외 | 이유가 있는 exclusion revision; 원본은 보존 |
| 두 질문 합치기 | 같은 binding·room·student에 한정한 새 question ID + 입력 revision provenance |
| 질문 나누기 | 새 question ID들 + 원래 revision provenance |
| 메시지 추가/제거 | 원본 occurrence pointer의 선택 변경 |
| 사진 이동/순서 변경 | attachment occurrence 선택·순서 변경 |
| 표시 문구 교정 | 원문과 별도의 display override |
| 사진 회전/자르기 | 원본 pointer + 명시적 transform revision |
| 학생 교정 | 확인된 student/mapping revision 변경 |

질문 내부에 원문 문장 일부만 선택할 필요가 있으면 `text_span`을 사용한다.

~~~json
{
  "source_occurrence_id": "<occurrence-id>",
  "source_normalization_revision_id": "<revision-id>",
  "start_codepoint": 0,
  "end_codepoint": 24
}
~~~

offset은 검증된 원문 Unicode code point의 반개구간으로 정의한다. JavaScript selection의 UTF-16 offset과 Python 문자열 인덱스를 그대로 섞지 않는다. surrogate pair·결합문자 경계를 자르지 않도록 변환·검증한다. 원문 전체 hash와 normalization revision을 pin하여 다른 문자열의 같은 offset을 가리키지 않게 한다.

사진을 수동 crop해도 원본은 유지한다. crop은 이미지의 실제 폭·높이에 대한 정규화 좌표와 orientation 처리 순서를 계약에 명시한다. 내용이 잘렸다는 사실을 감추기 위해 crop을 자동 적용하지 않는다.

### 8.7 날짜 필터는 후보 생성 후 적용

기본 기간 정책은 **해당 question revision에서 선택한 첫 학생 발화 시각**이다. split·merge·첫 메시지 제외 시 선택된 occurrence에서 다시 계산하며, 현재 후보 검색의 기간 귀속만 갱신한다. 이미 발행한 packet의 시각·선택은 바꾸지 않는다.

~~~text
1. 충분한 문맥을 포함한 방 이력으로 질문 후보 생성
2. 각 후보의 first_student_at_utc 결정
3. 사용자가 지정한 KST 날짜 범위를 UTC 반개구간으로 변환
4. start_utc <= first_student_at_utc < end_utc 를 적용
5. 선택된 질문의 전체 학생 발화·사진·필요 context를 유지
~~~

2026년 10월 전체를 선택한 예:

~~~json
{
  "timezone": "Asia/Seoul",
  "display_start_date": "2026-10-01",
  "display_end_date_inclusive": "2026-10-31",
  "range_start_utc": "2026-09-30T15:00:00Z",
  "range_end_utc_exclusive": "2026-10-31T15:00:00Z",
  "question_selection_policy": "first-student-message/1.0"
}
~~~

10월 31일 밤에 학생이 질문하고 11월 1일에 관리자가 답했다면 10월 질문으로 선택한다. 답변이 11월이라는 이유로 학생 사진이나 후속 context를 잃지 않게 한다.

먼저 10월의 CSV 행만 잘라 낸 뒤 그룹화하면 월 경계를 넘는 질문을 잘못 나눌 수 있다. raw 이력이 부족하면 기간의 시작·끝 경계가 완전하다는 사실도 주장하지 않는다.

후속 정책으로 `기간과 겹치는 질문`을 제공할 수 있으나, 기존 기본값을 조용히 바꾸지 않고 다른 versioned policy로 저장한다.

### 8.8 질문 조회·검토 화면의 최소 정보

각 후보에 아래를 표시한다.

- 학생과 연결 근거, 방 표시명.
- 질문 시작 시각과 원문 메시지 범위.
- 본문과 학생 사진, 사진 순서.
- 관리자 reply context의 접기/펼치기.
- 원본 snapshot의 수집 시각과 정합 수준.
- 미확보 첨부, 불확실한 경계, 삭제 관측, 미확정 발신 역할.
- 질문 확정/분할/병합/제외/사진 조정 버튼.
- 현재 revision과 저장 충돌 여부.
- 다음/이전 후보 이동과 다중 선택.

사진을 클릭하면 같은 source 범위의 인증된 원본 또는 고해상도 preview를 연다. 외부 카카오 signed URL을 UI에 넘기지 않는다.

---

<a id="section-9"></a>

## 9. 발행 묶음과 질문당 한 페이지 PDF

### 9.1 출력 단위

기본 제공물은 **학생별 PDF**다. 한 export는 한 packet revision에서 명시한 student_id의 질문 subset을 고정해 PDF 하나와 페이지 preview를 만든다. 한 학생의 선택 질문이 7개이면 7페이지 PDF가 된다. packet에 여러 학생이 있으면 학생별로 export를 접수하고, 각각의 질문 revision 목록을 output receipt에 pin한다. UI는 같은 학생별 intent key로 재개하며 학생별 접수·완료·실패를 표시한다. 다운로드용 ZIP 또는 합본 PDF는 후속 파생 출력이다.

기본 PDF에 표지·목차·빈 간지를 추가하지 않는다. 학생은 각 페이지 머리말과 manifest에 표시한다. 최종 페이지 수는 해당 export의 학생 subset 질문 수와 같다. 후속 합본을 구현할 때는 bookmark와 student range로 구분하고 합본 질문 수와 페이지 수를 일치시킨다.

PDF 생성 입력이 비어 있으면 `EMPTY_SELECTION`을 반환한다. 0페이지 문서나 성공처럼 보이는 빈 파일을 만들지 않는다.

### 9.2 packet은 선택의 snapshot

packet을 만들 때 다음을 고정한다.

- 선택 학생과 학생 표시 revision.
- 날짜 범위와 기간 선택 정책.
- ordered question ID + question revision ID.
- 각 질문의 원문 observation/normalization revision.
- 첨부 occurrence, 원본 blob pointer와 hash.
- source coverage와 누락 처리 결정.
- 관리자 답변 포함 여부.
- 발행 시점의 source 권한 확인 receipt.
- 질문 규칙·수동 편집 revision.
- 생성한 operator, 시각, request intent.

packet을 나중에 열거나 export할 때 날짜 검색을 다시 실행해 최신 질문을 끼워 넣지 않는다. 새 메시지를 반영하려면 새 packet revision을 만든다.

### 9.3 final과 draft

| 모드 | 용도 | 미확정 자료 |
|---|---|---|
| `FINAL` | 완성 자료 다운로드 | 선택 질문 검토, 학생·timezone·경계, 필수 사진 연결·품질 정책·레이아웃 검증 통과 필요 |
| `DRAFT` | 검토용 페이지 확인 | 누락·미확정 사유를 페이지에 명시하고 검토용 표시 |

draft도 내용 잘림을 허용하는 모드가 아니다. missing 사진은 “미확보 사진” placeholder와 사유를 표시할 수 있지만, 그것을 원본 사진처럼 다루지 않는다. 정기 수집 뒤 DRAFT를 자동 생성할 수 있고, FINAL 검토는 질문별 또는 선택 목록 전체에 대한 명시적 검토 완료로 기록할 수 있다. 의미상 학습 질문인지 자동으로 확인했다고 표시하지 않는다.

사진 품질은 기본적으로 플랫폼 원본 확보를 우선한다. best_available만 있다면 운영자가 해당 preview를 확인한 후 그 attachment revision에 제한된 품질 수용 결정을 남길 수 있다. 이를 source 원본 확인으로 바꾸지 않으며, 저해상도·thumbnail·미확정 품질은 결정 없이 FINAL에 자동 포함하지 않는다.

전체 collection run이 `PARTIAL`이어도 선택한 질문의 자료가 충분히 검증됐다면 해당 질문을 출력할 수 있다. 이때 packet에 선택 범위의 coverage와 채널 전체 수집의 부분 완료를 분리해서 기록한다. 무관한 방의 오류 때문에 검증된 학생 자료까지 항상 막을 필요는 없다.

### 9.4 renderer 선택

**설계 결정:** 첫 renderer는 저장소에 이미 의존성으로 선언된 **PyMuPDF**를 사용하는 별도 deterministic local worker로 구현한다. 기존 HWPX port와 PDF annotation renderer는 입력 의미가 달라 직접 재사용하지 않는다.

PyMuPDF의 텍스트 box·font 측정·이미지 배치 기능을 사용할 수 있다. 다만 최신 온라인 문서와 저장소의 `>=1.26.7,<1.27` 실행 범위가 다를 수 있으므로 실제 pin된 환경의 함수·한글 줄바꿈·폰트 embedding을 검증한다. [R9][M1][M2][M3]

HTML+Chromium은 후보 대안이다. 기본 PyMuPDF 실증에서 필요한 한글·특수문자·레이아웃을 만족하지 못할 때 ADR로 선택 이유를 기록하고 renderer adapter를 교체한다. 동일한 packet/layout/receipt 계약을 유지한다. 이 경우에도 카카오 로그인 profile과 출력 browser를 공유하지 않는다.

### 9.5 페이지 구조와 초기값

초기 레이아웃 정책 예시이며 실제 학생 사진으로 검토 후 조정한다.

| 요소 | 초기값 제안 |
|---|---|
| 용지 | A4 세로 |
| 여백 | 좌우·상하 12mm |
| 머리말 | 학생 표시명, 질문 번호, 질문 시작 날짜 |
| 본문 | 원문 보존, 기본 11pt, 최소 10pt |
| 행간 | 폰트 실제 metric에 맞춘 고정 정책 |
| 사진 | 원래 순서 유지, 비율 유지, 자동 crop 없음 |
| 관리자 답변 | 기본 미포함 |
| 꼬리말 | 자료 기간 또는 짧은 문서 식별자, 페이지 번호 |
| 표지/간지 | 기본 없음 |
| 폰트 | 승인한 한글 font file과 fallback set을 고정하고 SHA 기록 |

사진의 최소 표시 크기는 질문 유형에 따라 실제 검토해야 한다. 예를 들어 사진의 짧은 변 45mm 같은 기술적 기준을 두더라도 사진 속 작은 문제 글씨가 읽힌다는 보장이 되지 않는다. 자동 검증은 크기·해상도·잘림을 검사하고, 최종 가독성은 페이지 preview에서 사람이 판단한다.

### 9.6 조판 알고리즘

1. Catalog가 exact packet revision과 student_id의 subset을 resolve하고 source 권한을 재확인한다.
2. Orchestrator가 모든 필수 본문과 사진을 local workspace로 stage한다.
3. 격리된 renderer가 local 입력의 이미지 decode·orientation·실제 크기·hash를 검증한다.
4. 고정 font set의 glyph coverage를 확인한다.
5. 해당 질문의 본문을 실제 font metric으로 측정한다.
6. 허용 layout 후보를 정해진 순서로 평가한다.
7. 본문과 사진이 printable rectangle 안에 모두 들어가는지 확인한다.
8. 최소 글자·사진 크기와 무겹침 조건을 통과한 후보만 채택한다.
9. 각 질문에 대해 정확히 한 PDF page를 생성한다.
10. PDF를 다시 열어 페이지 수·크기·본문/사진 배치 receipt를 확인한다.
11. 페이지 PNG를 만들고 UI에서 같은 export를 확인할 수 있게 한다.
12. Catalog/Orchestrator가 local 결과를 검증한 뒤 PDF·manifest·layout receipt·preview를 기존 Artifact 경계로 발행한다. worker는 DB·NAS를 호출하지 않는다.

layout 후보 예:

~~~text
TEXT_TOP_IMAGE_STACK
TEXT_TOP_IMAGE_GRID_2COL
TEXT_LEFT_IMAGE_RIGHT
IMAGE_ONLY_WITH_HEADER
TEXT_ONLY
~~~

이 이름은 고정 layout enum의 예시다. 질문마다 무제한 임의 CSS를 입력받지 않는다. 후보 수와 font size step을 제한해 실행 시간을 예측 가능하게 한다.

본문 길이와 사진 수를 보고 한 페이지가 불가능해 보인다고 곧바로 내용을 줄이지 않는다. 실제 측정을 수행하고, 허용 후보가 없을 때 정확한 실패 원인을 반환한다.

### 9.7 잘림 방지

`page_count == question_count`만으로는 충분하지 않다. 한 페이지를 만들면서 본문을 자를 수도 있기 때문이다.

layout receipt에는 다음이 필요하다.

~~~json
{
  "question_revision_id": "<pinned-question-revision>",
  "page_number": 1,
  "layout_policy": "student-question-a4/1.0",
  "selected_layout": "TEXT_TOP_IMAGE_STACK",
  "text_blocks": [
    {
      "source_span_id": "<span-id>",
      "all_codepoints_accounted_for": true,
      "font_size_pt": 11,
      "bounds_pt": [34.02, 70.0, 561.26, 150.0]
    }
  ],
  "image_blocks": [
    {
      "attachment_occurrence_id": "<attachment-occurrence-id>",
      "source_sha256": "sha256:<64-hex>",
      "bounds_pt": [34.02, 165.0, 561.26, 720.0],
      "crop": null,
      "all_required_content_included": true
    }
  ],
  "overflow": false,
  "overlap": false,
  "missing_blocks": [],
  "unsupported_glyphs": []
}
~~~

위 좌표는 필드 의미 예시다. 모든 사진을 이 box에 억지로 늘리라는 뜻이 아니다. 실제 배치에서는 aspect ratio를 보존하고 맞는 rectangle을 계산한다.

PyMuPDF에서 textbox 삽입 결과가 음수 등 실패를 나타내면 성공으로 무시하지 않는다. 직접 줄을 배치하는 경우에도 모든 codepoint·개행·조합 문자의 처리 결과를 확인한다. 한글, 그리스 문자, 위첨자, 화살표, 학습용 기호, emoji 등 지원하지 못하는 glyph는 `UNSUPPORTED_GLYPH`로 표시한다. 자동 OCR·LaTeX 재해석으로 대체하지 않는다.

### 9.8 페이지 검증

필수 검증:

- 페이지 수와 질문 수.
- 페이지별 question revision 대응의 유일성.
- source text span과 실제 렌더링 block의 대응.
- 선택 사진 occurrence 수·순서와 배치 목록.
- printable bounds·overlap·clipping·unexpected blank page.
- font embedding 및 fixture의 한글/기호 출력.
- 손상 이미지, 과도한 픽셀 수, 잘못된 orientation.
- PDF 열기·페이지 rasterization 성공.
- 권한·source lifecycle·hash의 최종 재검증.

추출 텍스트 비교만으로 모든 시각적 품질을 입증했다고 보지 않는다. font encoding에 따라 추출과 화면이 다를 수 있으므로 대표 fixture의 rasterized preview를 사람이 함께 확인한다. 이미지 안의 글씨를 자동 의미 평가하지 않는다.

### 9.9 재현성과 cache

manifest에 다음을 pin한다.

~~~text
binding + packet revision + student_id + ordered question revision subset hash
FINAL/DRAFT mode + explicit quality acceptance decisions
message normalization + source snapshot references
attachment original hashes + display transforms
student display/mapping revisions
renderer release/build hash
layout policy revision
font file hashes
render options and page format
~~~

PDF 파일의 바이트가 항상 완전히 같다는 보장은 별도다. PDF timestamp·document ID·엔진 version이 결과를 바꿀 수 있다. 기본 목표는 **같은 불변 입력에서 같은 내용과 배치**를 재현하는 것이다. 동일 build key의 기존 검증 결과가 있으면 현재 source 권한·lifecycle을 다시 확인한 뒤 그 Artifact를 재사용한다. 다른 학생의 PDF 또는 DRAFT를 FINAL 결과로 재사용하지 않는다.

byte-identical output이 필요하면 metadata·ID 정규화 규칙과 pin된 엔진의 동작을 별도 검증한다. byte 동일성을 입증하기 위해 임의로 원본 의미나 서명 metadata를 훼손하지 않는다.

### 9.10 renderer 격리

PDF worker는 아래만 받는다.

- typed render command.
- pinned packet/layout manifest의 local materialization.
- 선택된 본문과 검증된 사진.
- 고정된 font 파일.
- 허용 output directory.

worker는 인터넷, 카카오 profile, Studio/API credential, PostgreSQL, NAS, 다른 worker home을 사용할 수 없다. 원격 URL을 주면 renderer가 직접 내려받는 인터페이스를 만들지 않는다.

본문을 HTML로 변환하는 대안을 선택하더라도 escaping을 적용하고 외부 resource loading을 차단한다. 원본 이미지 decode의 메모리·픽셀·시간 한도를 두고, 손상 파일 하나가 전체 운영 프로세스를 종료시키지 않도록 별도 process에서 처리한다.

---

<a id="section-10"></a>

## 10. Scientific Studio에 추가할 화면·API·권한 경계

### 10.1 조사 기준과 현재 구현의 범위

이 절의 **현재 구현**은 공개 저장소 `teddyok1206/eomai`의 commit `6a824aa48967270cc116661813d3d734f2f16e4e`를 직접 읽어 확인했다. 운영 서버에 설치된 wheel·활성 설정이 이 commit과 같다는 의미는 아니다. 아래 **신규 제안**의 파일·경로·schema·permission은 아직 존재하는 기능으로 취급하지 않는다.

현재 Studio는 정적 HTML·JavaScript ES module과 FastAPI BFF로 구성된다. BFF가 실제 Operator의 토큰으로 Application API를 호출하고, Application API가 담당 application owner와 통신한다. 신규 기능에도 이 경계를 사용한다. React·Next.js·별도 프런트엔드 서버·별도 공개 API 포트를 추가할 필요가 없다.

| 현재 책임 | 확인한 실제 소스 |
| --- | --- |
| HTML shell·메뉴·view | [static/index.html](https://github.com/teddyok1206/eomai/blob/6a824aa48967270cc116661813d3d734f2f16e4e/apps/web_gui/eom_web_gui/static/index.html) |
| 화면 lifecycle·공통 API 호출 | [static/app.js](https://github.com/teddyok1206/eomai/blob/6a824aa48967270cc116661813d3d734f2f16e4e/apps/web_gui/eom_web_gui/static/app.js) |
| query 기반 화면 경로 | [static/studio-route.js](https://github.com/teddyok1206/eomai/blob/6a824aa48967270cc116661813d3d734f2f16e4e/apps/web_gui/eom_web_gui/static/studio-route.js) |
| UI permission 표시 | [static/studio-permissions.js](https://github.com/teddyok1206/eomai/blob/6a824aa48967270cc116661813d3d734f2f16e4e/apps/web_gui/eom_web_gui/static/studio-permissions.js) |
| `/studio` BFF·cookie·CSRF | [eom_web_gui/app.py](https://github.com/teddyok1206/eomai/blob/6a824aa48967270cc116661813d3d734f2f16e4e/apps/web_gui/eom_web_gui/app.py) |
| BFF gateway·API token 갱신 | [eom_web_gui/gateways.py](https://github.com/teddyok1206/eomai/blob/6a824aa48967270cc116661813d3d734f2f16e4e/apps/web_gui/eom_web_gui/gateways.py) |
| 기능별 BFF route 분리 선례 | [content_workbook_routes.py](https://github.com/teddyok1206/eomai/blob/6a824aa48967270cc116661813d3d734f2f16e4e/apps/web_gui/eom_web_gui/content_workbook_routes.py) |
| Application API router 등록 | [eom_api/app.py](https://github.com/teddyok1206/eomai/blob/6a824aa48967270cc116661813d3d734f2f16e4e/apps/application_api/eom_api/app.py) |
| bearer 인증·권한·ETag | [eom_api/dependencies.py](https://github.com/teddyok1206/eomai/blob/6a824aa48967270cc116661813d3d734f2f16e4e/apps/application_api/eom_api/dependencies.py) |
| API 공통 응답·멱등 command | [routers/common.py](https://github.com/teddyok1206/eomai/blob/6a824aa48967270cc116661813d3d734f2f16e4e/apps/application_api/eom_api/routers/common.py) |
| 실제 `SingleResponse`·`CommandResult`·`ArtifactPointer` | [api_contracts/common.py](https://github.com/teddyok1206/eomai/blob/6a824aa48967270cc116661813d3d734f2f16e4e/packages/api_contracts/eom_api_contracts/common.py) |
| API 인증 세션 identity | [identity_service/tokens.py](https://github.com/teddyok1206/eomai/blob/6a824aa48967270cc116661813d3d734f2f16e4e/services/identity_service/eom_identity_service/tokens.py) 및 [eom_api/request_context.py](https://github.com/teddyok1206/eomai/blob/6a824aa48967270cc116661813d3d734f2f16e4e/apps/application_api/eom_api/request_context.py) |
| API 서비스 조합 | [eom_api/lifespan.py](https://github.com/teddyok1206/eomai/blob/6a824aa48967270cc116661813d3d734f2f16e4e/apps/application_api/eom_api/lifespan.py) |
| API→Catalog의 현재 IPC client | [catalog_application_client.py](https://github.com/teddyok1206/eomai/blob/6a824aa48967270cc116661813d3d734f2f16e4e/apps/application_api/eom_api/services/catalog_application_client.py) |
| RBAC 정본 enum·role 배정 | [operator_identity/contracts.py](https://github.com/teddyok1206/eomai/blob/6a824aa48967270cc116661813d3d734f2f16e4e/packages/operator_identity/eom_operator_identity/contracts.py) |

현재 URL 체계를 유지한 신규 진입점은 `/studio/?view=kakao-archive`로 정한다. 화면의 사용자용 이름은 **학생 질문**으로 한다. 내부 코드·schema·route의 feature 이름은 `kakao-archive`로 통일한다.

### 10.2 역방향 프록시와 공개 경로

[현재 Caddyfile](https://github.com/teddyok1206/eomai/blob/6a824aa48967270cc116661813d3d734f2f16e4e/config/caddy/Caddyfile)은 `eomai.duckdns.org`의 `/studio`와 `/studio/*`를 `127.0.0.1:8790`으로 전달한다. `/`는 `/studio/`로 redirect되고 나머지는 404다. Caddy admin은 `unix//run/caddy-admin/admin.sock`에 묶여 있다.

| 구간 | 사용 경로 |
| --- | --- |
| 사용자 화면 | `https://eomai.duckdns.org/studio/?view=kakao-archive` |
| 브라우저→BFF | `/studio/api/v1/kakao-archive/...` |
| BFF→기존 Application API | `http://127.0.0.1:8765/api/v1/kakao-archive/...` |
| BFF 정적 파일 | `/studio/assets/kakao-archive.js` 및 필요한 CSS |

BFF가 `/studio` prefix를 직접 소유하므로 `handle_path`나 rewrite로 prefix를 제거하지 않는다. 이 기능 때문에 8765·8780·수집기·VNC·CDP 포트를 일반 인터넷에 직접 노출하지 않는다. 수동 인증용 원격 화면도 기존 `/studio` 경계 아래에서 제한된 lease에 연결한다. 상세 원격 화면 전송 방식은 별도 원격 인증 설계를 따른다.

### 10.3 기능별 파일 변경 계획

아래 경로는 저장소 root 기준이다. `신규`는 구현할 경로 제안이고 `변경`은 조사한 기존 파일이다.

| 구분 | 경로 | 변경 책임 |
| --- | --- | --- |
| 신규 | `apps/web_gui/eom_web_gui/static/kakao-archive.js` | 학생 질문 화면 controller·선택·폴링·질문 구성과 표시 교정; 수집 원문 불변 |
| 신규 | `apps/web_gui/eom_web_gui/static/kakao-archive.css` | 필요한 기능별 레이아웃; 기존 semantic token 사용 |
| 변경 | `apps/web_gui/eom_web_gui/static/index.html` | 메뉴·view section·기능 CSS 참조 |
| 변경 | `apps/web_gui/eom_web_gui/static/app.js` | controller lifecycle·route 복구·기존 API helper의 opt-in ETag 노출 |
| 변경 | `apps/web_gui/eom_web_gui/static/studio-route.js` | view 허용 목록과 제한된 선택 ID round-trip |
| 변경 | `apps/web_gui/eom_web_gui/static/studio-permissions.js` | 수집·편집·출력·원격 인증 버튼의 permission 표시 |
| 변경 | `apps/web_gui/eom_web_gui/static/presentation-vocabulary.ko-KR.json` | 상태·오류 코드의 사용자용 문구 |
| 변경 | `apps/web_gui/eom_web_gui/static/guide-content.js` | 수집·학생 연결·질문 구성·출력 안내 |
| 신규 | `apps/web_gui/eom_web_gui/kakao_archive_routes.py` | 기능별 BFF route installer |
| 신규 | `apps/web_gui/eom_web_gui/kakao_archive_contracts.py` | browser 입력·BFF 응답의 strict DTO |
| 변경 | `apps/web_gui/eom_web_gui/app.py` | route installer 등록; 필요 시 한정된 preview 예외 |
| 변경 | `apps/web_gui/eom_web_gui/gateways.py` | typed feature 호출·ETag 등 필요한 upstream metadata 보존 |
| 변경 | `apps/web_gui/eom_web_gui/release_integrity.py` | 신규 runtime 파일의 필수 무결성 목록 |
| 신규 | `apps/application_api/eom_api/routers/kakao_archive.py` | 실제 operator로 인증된 command/query 경계 |
| 신규 | `apps/application_api/eom_api/services/kakao_archive_service.py` | API 입력을 담당 owner의 typed command/query로 변환 |
| 변경 | `apps/application_api/eom_api/app.py` | 신규 router import·등록 |
| 변경 | `apps/application_api/eom_api/lifespan.py` | 해당 application facade/client 구성 |
| 변경 | `apps/application_api/eom_api/services/catalog_application_client.py` | 신규 Catalog IPC 계약을 기존 인증·검증 경계로 전달 |
| 신규 | `packages/api_contracts/eom_api_contracts/kakao_archive.py` | public API의 versioned Pydantic model |
| 신규 | `schemas/api/v1/kakao-archive-v1.schema.json` | public JSON Schema 2020-12 정본 |
| 신규 | `packages/api_contracts/eom_api_contracts/schemas/kakao-archive-v1.schema.json` | 설치 package에 포함할 canonical schema mirror |
| 신규 | `packages/catalog_contracts/eom_catalog_contracts/kakao_archive.py` | API→Catalog 명령·질의·응답의 typed 계약 |
| 신규 | `schemas/kakao-archive/catalog-kakao-archive-request-v1.schema.json` 및 `catalog-kakao-archive-response-v1.schema.json` | Catalog IPC 정본; 기능 schema root 안에 배치 |
| 변경 | `packages/operator_identity/eom_operator_identity/contracts.py` | 신규 기능 permission |
| 신규 | `migrations/versions/<new_revision>_kakao_archive_rbac.py` | additive permission·role permission seed |
| 변경 | `api/openapi/eom-api-v1.openapi.json` 및 `.sha256` | 현재 route로 다시 생성한 공개 계약 |

Catalog의 영속화 owner, Orchestrator 수집 실행 및 Artifact commit 구현은 해당 backend 설계 절에서 정한다. 위 파일 목록을 이유로 API/BFF가 Catalog 테이블이나 NAS를 직접 수정하는 경로를 만들지 않는다. 도메인 모델·schema는 infrastructure를 import하지 않는다.

### 10.4 frontend lifecycle의 구체적인 접점

`kakao-archive.js`는 기존 `createMaterialLearning`·`createContentPlanning`처럼 주입받은 `document`, `api`, 상태 presenter를 사용한다. 최소 public interface는 `install()`, `setOwner(operatorId)`, `open()`, `close()`, `restoreLocation(route)`다.

1. `app.js` 상단에서 `createKakaoArchive`를 import하고 controller를 한 번 생성한다.
2. `UI_MODE_BY_VIEW`에 `"kakao-archive": "human"`을 추가한다.
3. `boot()`에서 event listener를 한 번만 설치한다.
4. `initializeSession()`에서 실제 `session.operator.operator_id`를 `setOwner()`로 전달한다.
5. `showView()`에서 해당 view를 열면 `open()`, 다른 view로 이동하면 `close()`를 호출한다.
6. `restoreStudioRoute()`에서 유효한 binding·room·question·packet·export 포인터를 복구한다.
7. `logout()`과 owner 변경에서 선택 상태·사진 preview URL·폴링·미완성 UI intent를 정리한다.
8. 비동기 결과를 반영하기 직전에 owner, active view, request generation, 선택 ID를 다시 확인한다.

현재 공통 `api()`는 same-origin cookie, `mutation: true`일 때의 CSRF, JSON 직렬화, 401 로그인 이동, 표준 오류 표현을 이미 담당한다. 신규 모듈이 별도 로그인·토큰 갱신 fetch 계층을 만들지 않는다. 현재 helper에는 `AbortSignal` 전달이 없으므로 이미 지원한다고 가정하지 않는다. 우선 기존 generation fence를 사용한다.

현재 helper는 성공 시 JSON 또는 Blob만 반환하므로 ETag를 이미 읽어 준다고 가정하지 않는다. 기존 반환형을 유지하면서 신규 opt-in `options.onResponseMetadata({etag, retryAfterSeconds})`를 추가하고 필요한 헤더만 검증해 전달한다. callback 반영에도 owner·request generation fence를 적용한다. `If-Match` 제출은 현재 지원하는 `options.headers`를 사용한다. metadata 전달과 BFF/gateway의 ETag 보존을 하나의 통합 테스트로 확인한다.

`close()`는 화면 polling만 중지하고 서버 수집 작업을 취소하지 않는다. 서버 작업의 중단·재개는 명시적인 command다. 페이지 새로고침 후에도 durable run을 다시 읽어 진행 상황을 복구한다. 제출 결과가 유실되면 동일 idempotency key로 확인하며 새 작업을 무조건 생성하지 않는다.

### 10.5 사용자 화면의 작업 흐름

| 영역 | 사용자가 하는 일 | 표시할 근거·상태 |
| --- | --- | --- |
| 연결·인증 | 최초 binding 생성, 수동 인증, 실제 채널 확인, 수집 주기 설정 | 확인 전 DRAFT, 고정된 채널 identity·카카오 세션 상태·lease 만료 시각 |
| 수집 | 최초 전체 수집, 전체 다시 수집과 기존 기록 병합, 중단·재개, 실패 사진 다시 받기 | 방·대화·사진 처리 수, 부분 완료 사유, 마지막 성공 시각 |
| 대화 | 방·기간·학생으로 검색하고 원문과 사진 확인 | 발신 주체·원문 시각·사진 상태·수집 출처 |
| 학생 연결 | 방을 기존 학생에 연결하거나 새 학생을 생성 | 이름과 별개인 student ID, mapping 이력, 미연결 방 |
| 질문 구성 | 여러 메시지·사진을 하나의 질문으로 선택·정렬 | 원문 참조, 확인되지 않은 사진 연결, 현재 revision |
| 발행 묶음 | 기간·학생으로 질문을 고르고 순서 확인; 여러 학생을 같은 packet에 포함 가능 | 포함한 정확한 question revision·학생 연결, 제외·미검토 항목 |
| 출력 | 학생별 PDF를 생성·검토·다운로드; 한 질문 한 페이지 | packet revision·student_id·학생별 선택 질문·접수/진행/성공/실패·읽기 어려운 페이지 |

**question은 개별 논리 질문**, **question-packet은 발행할 질문 revision들의 순서 있는 묶음**이다. 학생이 연속으로 보낸 메시지 세 개와 사진 두 장을 질문 하나로 구성할 수 있다. 그 질문을 여러 packet에서 참조할 수 있다. CSV 행, 채팅방, 질문, PDF 한 묶음을 같은 엔터티로 취급하지 않는다.

**export 하나는 packet revision 하나에서 `student_id` 하나에 해당하는 질문 revision 부분집합을 고정한 PDF와 페이지 preview들**이다. packet은 여러 학생을 포함할 수 있지만 출력은 학생별로 분리한다. `POST /exports`에는 `student_id`를 항상 명시한다. UI에서 단일 학생을 자동 선택할 수 있어도 API가 생략된 학생을 추측하지 않는다. packet에 pin된 학생 연결과 순서로 부분집합을 확정하고 그 정확한 question revision 목록을 출력 계획 receipt와 완료 manifest에 보존한다. 공통 `CommandResult`에 임의 필드를 추가하지 않고 `GET /exports/{export_id}`의 새 상세 계약에서 이 계획 receipt를 제공한다.

UI에서 여러 학생 생성을 선택하면 학생마다 별도의 idempotency key로 기존 export 접수를 반복하고, 해당 학생의 재시도에는 같은 key를 유지한다. 학생별 접수 여부·export ID·진행·결과를 따로 표시한다. 화면 중단 후에는 binding·packet revision·student·subset hash·FINAL/DRAFT mode·layout revision·renderer/font pin으로 같은 intent/build key의 기존 exports를 조회해 이미 접수된 작업을 복원하고 미접수 학생만 이어서 제출한다. 응답 유실로 접수 여부가 불명확하면 기존 작업 확인 또는 동일 key 재제출로 해소한다. 일부 실패·미접수 상태를 전체 성공으로 표시하지 않는다. MVP에 범용 배치 큐를 추가하지 않으며 ZIP·학생 합본은 이후 파생 옵션이다.

학생 닉네임만으로 학생을 자동 합치지 않는다. `students`는 내부 학생 identity, `student-mappings`는 카카오 source room/customer와 그 identity의 확인된 연결이다. 연결 수정은 기존 이력을 덮어쓰지 않으며 packet은 사용한 mapping revision과 question revision을 pin한다.

질문 원문은 기본적으로 그대로 유지한다. 사용자 편집 텍스트는 별도 question revision의 편집값이며 원문 관찰을 수정하지 않는다. AI 요약·답변 생성·OCR·의미 기반 자동 분류를 수행하지 않는다. 선택되지 않은 관리자 답장을 학생 질문에 자동으로 합치지 않는다.

`FULL`과 `REPEAT`는 둘 다 **매회 접근 가능한 전체 방을 다시 열거하고 각 방의 CSV를 다시 확보하는 모드**다. `REPEAT`는 새 snapshot을 기존 관측과 조정한다는 의미다. 최근 대화 시각은 처리 우선순위에만 사용하며, 오래되었다는 이유로 방이나 CSV를 생략하지 않는다. 실패 task만 재시도하는 `RETRY_FAILED`는 별도 command다.

### 10.6 BFF·Application API·Catalog IPC의 역할

BFF에는 `install_kakao_archive_routes(app, gateway, require_session, require_csrf, require_admin_session, require_admin_csrf)`를 추가한다. 새 signature는 제안이며, 주입할 session·CSRF·ADMIN dependency는 현재 `app.py`에 존재한다. 기능별 route 분리의 선례는 `content_workbook_routes.py`다. 거대한 `app.py`에 CSV parser·사진 매칭·조판 코드를 직접 넣지 않는다.

브라우저는 작은 command/query와 pinned pointer를 보낸다. BFF는 strict DTO를 검증하고 기존 `HttpApplicationGateway._authorized()`를 통해 실제 Operator의 bearer를 사용한다. Application API는 `Auth`와 `request_context.actor()`에서 identity를 확정한 후 Catalog IPC command를 구성한다.

현재 `Auth`는 `Annotated[AccessAuthentication, Depends(get_authentication)]`다. 실제 class는 `eom_identity_service.tokens.AccessAuthentication`이고, 인증 세션 필드는 **`session_id`**다. `RequestContext.actor()`가 이 값을 `ActorContext.session_id`로 복사하고 `operator.operator_id`·인증 시각·권한도 서버에서 도출한다. browser body가 제공한 actor·session·permission은 받지 않는다. BFF의 raw `eom_studio_session` cookie나 API access/refresh token을 archive·run·remote lease 테이블에 저장하지 않는다. BFF session 객체는 기존 web session store 안에만 존재한다.

Catalog IPC에는 서버가 도출한 `ActorContext`의 `operator_id`, `session_id`, `request_id`, `authentication_time`과 typed 요청을 전달하도록 신규 계약을 정의한다. 별도의 임의 `actor_id`를 실제 기존 필드처럼 사용하지 않는다. 기존 `CatalogApplicationClient`의 socket peer 검증·schema parse·응답 identity 검증 경계를 사용한다. `RequestContext.owner_capture()`는 별도 실제 인증 capture가 있어야 동작하므로 새 route에서 자동 제공된다고 가정하지 않는다. 신규 기능만을 위한 임의 HTTP proxy나 사용자 제공 Unix socket 경로를 받지 않는다.

Catalog는 조회·편집·학생 연결·질문 revision·packet 구성의 application owner를 맡는다. 장시간 수집·다운로드·렌더링은 durable command로 접수해 담당 실행 owner에 전달한다. HTTP handler가 브라우저 조작 전체가 끝날 때까지 기다리지 않으며, 일반 FastAPI `BackgroundTasks`만으로 영속 작업을 대신하지 않는다.

API→Catalog→Orchestrator의 구체적인 신규 command 등록은 각 owner의 versioned protocol에 추가한다. 현재 일반 채팅·자료 학습·고객센터 AI dispatch를 호출하지 않는다. 기존 고객센터의 `customer-support`는 Studio 지원 문의 workflow이므로 카카오 상담 archive를 집어넣는 통합 지점이 아니다.

### 10.7 신규 public endpoint 제안

아래 표의 suffix는 BFF `/studio/api/v1`와 Application API `/api/v1` 뒤에 붙는다. 모든 경로는 **신규 제안**이다. public 필드는 `source_binding_id`로 통일한다. 목록은 cursor·limit을 사용하고 필터 정렬 기준을 계약에 고정한다. raw 개인정보·검색어를 access log에 남기는 free-form URL 설계를 피한다. MVP는 binding owner만 접근하며 ADMIN 역할만으로 다른 owner의 학생 자료에 접근하지 못한다.

| Method·suffix | 입력·응답 핵심 | 동시성·권한 |
| --- | --- | --- |
| `GET /kakao-archive/source-bindings` | 현재 접근 가능한 binding의 ID·채널명·상태 | `read`; source scope 검증 |
| `POST /kakao-archive/source-bindings` | 표시명·초기 정책 → 서버 발급 ID의 DRAFT binding receipt | 현재 `ADMIN`+`collect`; key; owner·profile은 서버 도출 |
| `GET /kakao-archive/source-bindings/{source_binding_id}` | binding 상세·capability·최근 수집·정책·ETag | `read`; owner 검증 |
| `POST /kakao-archive/source-bindings/{source_binding_id}/commands` | VERIFY_CHANNEL/UPDATE_COLLECTION_POLICY/ENABLE_SCHEDULE/DISABLE_SCHEDULE/RETIRE → receipt | 현재 `ADMIN`+`collect`; owner; key+If-Match |
| `POST /kakao-archive/collection-runs` | source_binding_id·FULL/REPEAT·정책 revision → 접수 run; 둘 다 매회 전체 CSV | `collect`; Idempotency-Key; binding 실행 fence |
| `GET /kakao-archive/collection-runs` | source_binding_id·state·cursor → run 목록 | `read`; 제한된 projection |
| `GET /kakao-archive/collection-runs/{run_id}` | state·coverage·counters·checkpoint·error | `read`; ETag |
| `POST /kakao-archive/collection-runs/{run_id}/commands` | PAUSE/RESUME/CANCEL/RETRY_FAILED → command receipt | `collect`; key+If-Match; 허용 transition |
| `GET /kakao-archive/rooms` | source_binding_id·student·status·cursor → 방 목록 | `read`; 표시명과 ID 분리 |
| `GET /kakao-archive/rooms/{room_id}/messages` | cursor·방향·범위 → 순서 있는 대화·첨부 참조 | `read`; snapshot/revision 경계 명시 |
| `GET /kakao-archive/attachments/{attachment_id}/preview` | 필수 query revision_id → 이미지 bytes | `read`; 해당 logical attachment의 immutable revision·hash 검증 |
| `GET /kakao-archive/attachments/{attachment_id}/download` | 필수 query revision_id → 원본 bytes | `read`; source 권한·safe filename·no-store |
| `GET /kakao-archive/students` | 검색 조건·cursor → 내부 학생 목록 | `read`; 해당 source 범위로 제한 |
| `POST /kakao-archive/students` | 학생 표시명·선택 메타정보 → student identity | `edit`; key; 이름은 unique key 아님 |
| `PATCH /kakao-archive/students/{student_id}` | 변경 필드 → 새 resource version | `edit`; key+If-Match |
| `GET /kakao-archive/student-mappings` | source_binding_id/room/student → 연결 이력 | `read`; historical 상태 포함 가능 |
| `POST /kakao-archive/student-mappings` | source entity·student·확인 근거 → mapping revision | `edit`; key; 상충 active 연결 제약 |
| `POST /kakao-archive/student-mappings/{mapping_id}/revoke` | 철회 사유 → append-only 철회 기록 | `edit`; key+If-Match |
| `GET /kakao-archive/questions` | 학생·기간·검토 상태·cursor → 질문 목록 | `read`; 날짜 의미·mapping pin 명시 |
| `POST /kakao-archive/questions` | 원문·사진 포인터·순서 → question 및 최초 revision | `edit`; key; 참조 접근권한·hash |
| `POST /kakao-archive/questions/commands` | SPLIT/MERGE, 입력별 expected revision/version, 명시적 출력 구성 → composition receipt 포인터 | `edit`; key; 동일 binding·room·student; 다중 객체 CAS |
| `GET /kakao-archive/questions/commands/{composition_id}` | 고정 입력 revision, 생성 question ID 목록, superseded ID 목록, 처리 결과 | `read`; 해당 source owner·receipt 검증 |
| `GET /kakao-archive/questions/{question_id}` | logical question과 current revision pointer | `read`; current는 mutable pointer |
| `GET /kakao-archive/questions/{question_id}/revisions/{revision_id}` | immutable 원문/편집 block·출처 | `read`; 정확한 parent 관계 검증 |
| `POST /kakao-archive/questions/{question_id}/revisions` | parent revision·변경 block → 새 revision | `edit`; key+If-Match; 과거 revision 불변 |
| `GET /kakao-archive/question-packets` | 학생·기간·cursor → 발행 묶음 목록 | `read`; metadata-only 목록 |
| `POST /kakao-archive/question-packets` | 범위 설명·ordered question revision refs → packet revision | `edit`; key; 모든 선택을 다시 검증 |
| `GET /kakao-archive/question-packets/{packet_id}` | logical packet·current revision pointer·ETag | `read`; 편집용 current와 발행용 immutable pin 구분 |
| `GET /kakao-archive/question-packets/{packet_id}/revisions/{revision_id}` | 고정된 선택·순서·학생 연결·발행 정보 | `read`; latest로 대체하지 않음 |
| `POST /kakao-archive/question-packets/{packet_id}/revisions` | 새 선택·순서 → 새로운 immutable 묶음 revision | `edit`; key+If-Match |
| `POST /kakao-archive/exports` | packet_revision_id·필수 student_id·필수 mode(DRAFT/FINAL)·layout_revision_id → 학생 한 명의 export 접수 | `export`; 학생별 key; subset·품질 결정 revision·renderer/font pin |
| `GET /kakao-archive/exports` | source_binding_id·packet_revision_id·student_id·mode·layout_revision_id·state·cursor → export 목록 | `read`; 같은 intent/build key로 기존 접수·진행 복원 |
| `GET /kakao-archive/exports/{export_id}` | student_id·mode·고정 subset/품질 결정의 계획 receipt·진행·페이지·검증결과·완료 시 export_revision_id | `read`; 학생별 접수·실행·성공 구분 |
| `GET /kakao-archive/exports/{export_id}/pages/{page}/preview` | 필수 query revision_id → 검증한 페이지 이미지 | `read`; 해당 immutable export revision·bounded page·hash |
| `GET /kakao-archive/exports/{export_id}/download` | 필수 query revision_id → 최종 PDF bytes | `export`; source owner 재검사·hash |
| `POST /kakao-archive/remote-leases` | source_binding_id·목적 → 짧은 lease·같은 origin 경로 | 현재 `ADMIN`+`remote`; owner; key; API session binding |
| `GET /kakao-archive/remote-leases/{lease_id}` | 상태·만료·연결 가능 여부·ETag | 현재 `ADMIN`+`remote`; 해당 operator/session 한정 |
| `POST /kakao-archive/remote-leases/{lease_id}/renew` | heartbeat → 제한된 새 만료 시각·resource version | 현재 `ADMIN`+`remote`; owner/session; key+If-Match; absolute TTL |
| `POST /kakao-archive/remote-leases/{lease_id}/revoke` | 폐기 요청 → 종료 receipt | 현재 `ADMIN`+`remote`; owner/session; key; 멱등 종료 |

`remote/authorize`는 아래 별도 경계이므로 일반 수집·편집 endpoint와 구분한다. 생성·제어 요청에 actor·session ID를 body로 포함시키지 않는다. 팀 공유 grant API는 MVP에서 제공하지 않으며 후속 버전에서 명시적인 source 범위로만 확장한다.

최초 설정은 **DRAFT 생성 → 제한된 lease에서 카카오 수동 인증 → VERIFY_CHANNEL 실측 → 채널 identity 확정 → 수집·주기 활성화** 순서다. `VERIFY_CHANNEL`은 현재 profile의 실제 채널을 probe하고 사용자의 확인 대상과 대조한 receipt를 만든다. 확정된 binding을 다른 채널로 재지정하지 않는다. 잘못 연결했다면 RETIRE 후 새 binding을 만든다. DRAFT·미검증 binding에서 수집·schedule을 실행하지 않는다.

binding command는 `action`으로 구분한 strict union으로 정의한다. `UPDATE_COLLECTION_POLICY`는 새 immutable 정책 revision을 만들고, `ENABLE_SCHEDULE`은 검증된 현재 binding·정책 revision·주기만 받아 다음 실행 슬롯을 서버에서 계산한다. profile 디렉터리·실행 계정·actor·카카오 쿠키·임의 명령은 입력에 없다. `RETIRE`는 새 실행을 차단하고 schedule과 lease를 정리하되 이미 수집한 원문을 삭제하지 않는다.

질문 composition의 `SPLIT`/`MERGE`도 별도 strict union이다. UI가 여러 question 생성·supersede 요청을 연달아 보내서 원자성을 흉내 내지 않는다. 각 입력의 `question_id`·`revision_id`·`expected_resource_version`을 pin하고, 하나라도 바뀌었으면 전체 결정을 412로 거부한다. 다중 객체의 precondition은 단일 If-Match 값으로 대체하지 않는다. 응답은 기존 CommandResult가 가리키는 신규 composition receipt를 통해 결과 ID들을 제공하며 공통 DTO에 임의 필드를 추가하지 않는다. 작은 receipt는 Question aggregate의 일부이고 범용 workflow/queue를 새로 만들지 않는다. 고정 `questions/commands` 경로를 동적 `questions/{question_id}`보다 먼저 등록하고 route 충돌을 테스트한다.

### 10.8 요청·응답 계약과 revision 동시성

다음은 신규 계약의 형태를 설명하는 예다. ID prefix와 schema 이름은 구현 전 JSON Schema 2020-12로 확정하고 모든 consumer에 동일하게 적용한다.

```http
POST /studio/api/v1/kakao-archive/collection-runs
X-CSRF-Token: <현재 Studio 세션의 CSRF>
Idempotency-Key: kakao-collect-<재시도해도 유지할 UUID>
Content-Type: application/json
```

```json
{
  "schema_version": "kakao-archive-collection-create/1.0",
  "source_binding_id": "kakaobinding_11111111111111111111111111111111",
  "mode": "FULL",
  "collection_policy_revision_id": "kakaopolicyrev_22222222222222222222222222222222"
}
```

브라우저가 지정하는 policy revision은 서버가 접근·적합성을 검증한다. 숨겨진 기본값으로 사진 수집을 생략하지 않는다. 이 요청에는 쿠키, 비밀번호, CDP 주소, shell command, 다운로드 경로가 없다.

Application API의 접수 응답은 위에서 확인한 **기존 `SingleResponse[CommandResult]`의 실제 필드**를 사용한다. `CommandResult.status`의 허용 값은 `ACCEPTED`·`COMPLETED`, `ResponseMeta.api_version`은 `"1"`이다. 아래 feature별 resource_type·ID prefix·status_url은 신규 제안이며 이미 등록된 값이라는 뜻은 아니다. BFF는 별도 typed acceptance projection으로 풀어 제공할 수 있으나 필드를 임의로 유실시키지 않는다.

```json
{
  "data": {
    "command_id": "command_33333333333333333333333333333333",
    "resource_type": "kakao_collection_run",
    "resource_id": "kakaorun_44444444444444444444444444444444",
    "status": "ACCEPTED",
    "resource_version": 1,
    "status_url": "/api/v1/kakao-archive/collection-runs/kakaorun_44444444444444444444444444444444"
  },
  "meta": {"request_id": "apireq_55555555555555555555555555555555", "api_version": "1"}
}
```

202는 접수만 의미한다. BFF는 upstream `/api/v1/...` 상태 URL을 browser에게 그대로 이동시키지 말고 검증된 ID를 사용해 `/studio/api/v1/...`로 투영한다. 외부 URL 또는 사용자 입력 URL을 redirect하지 않는다.

현재 `dependencies.py`의 `etag(7)`은 **`"v7"`**을 만들고 `require_if_match()`는 정규식 `^"v(?P<version>[1-9][0-9]*)"$`을 검사한다. GET의 `ETag: "v7"`을 BFF가 보존해 UI에 전달하고 변경 요청은 `If-Match: "v7"`로 같은 값을 돌려준다. 누락은 428 `API_PRECONDITION_REQUIRED`, 형식 오류·version 불일치는 412 `API_PRECONDITION_FAILED`다.

질문 수정의 새 body 계약에는 `parent_revision_id`, 새 `ordered_blocks`를 둔다. 서버는 logical question의 current pointer를 잠근 상태에서 version·parent를 확인하고 새 immutable revision을 만든다. 같은 parent에서 다른 수정이 먼저 완료되었다면 412로 돌려주고 현재 내용을 다시 확인하게 한다. resource version은 동시성 제어값이고 revision ID는 immutable 자료 identity다. 과거 revision 파일을 덮어쓰지 않는다.

packet에는 기간·학생 선택 조건과 **실제 확정한 ordered question revision refs**를 함께 보존한다. 기간은 사용자에게 KST로 표시하고 시스템 경계는 timezone-aware UTC의 `[start, end)`로 기록한다. 출력 시 조건을 다시 실행해 최신 질문을 끼워 넣지 않는다. 변경된 내용을 반영하려면 새 packet revision과 새 export를 만든다.

멱등 key는 실제 operator·operation·path·정규화한 body에 묶는다. 동일 key와 다른 body는 409다. DB 변경과 command receipt의 atomic 경계를 application owner에서 정한다. API `run_command`의 receipt만으로 장시간 실행 결과의 정확히 한 번 완료가 자동 보장된다고 가정하지 않는다.

### 10.9 수동 원격 인증의 authorize 경계

BFF에 **`/studio/api/v1/kakao-archive/remote/authorize`**를 추가한다. 이것은 카카오 로그인 비밀번호를 받는 API가 아니라, 원격 인증 화면에 대한 프록시 요청이 현재 Studio 사용자에게 허용되는지 확인하는 경계다.

프록시 인증 방식에서는 GET을 사용하고, 현재 `eom_studio_session` cookie를 `require_admin_session`으로 확인한 뒤 `_authorized()`를 통해 Application API에 lease 검증을 요청한다. API는 **현재 ADMIN 역할과 `kakao_archive:remote` permission을 함께 검사**한다. BFF에 캐시된 역할만으로 허용하지 않는다. 일반 브라우저가 제출한 actor/session 또는 `X-Forwarded-User`를 신뢰하지 않는다. 프록시가 전달하는 원래 요청 경로·method header도 해당 proxy 경계에서 overwrite/검증되어야 한다.

Application API는 bearer로 다시 인증한 `authentication.operator.operator_id`와 **`authentication.session_id`**를 사용해 lease의 operator·API session·binding·상태·TTL을 비교한다. lease 생성 시에도 같은 identity를 서버가 도출한다. raw web cookie, bearer, refresh token을 lease row에 저장하지 않는다. lease ID 하나를 아는 것만으로 원격 화면에 접근할 수 없어야 한다.

성공 응답은 body 없는 204 등 proxy가 인식할 제한된 성공 상태로 하고, 실패는 401/403 또는 공개적으로 허용한 404로 끝낸다. 이 경계가 비밀번호·cookie·VNC secret·CDP endpoint를 응답하지 않게 한다. 다른 계정의 lease, 만료 lease, 철회된 API session은 거부한다.

WebSocket handshake의 authorize 성공만으로 lease 만료 후 연결 종료까지 해결되지는 않는다. 원격 실행 owner/proxy가 lease 만료·폐기를 관찰하고 살아 있는 연결을 닫아야 한다. lease 권한 검증과 원격 브라우저 종료는 별도 검증 항목이다. 브라우저 인증 자료를 archive artifact나 학생 자료에 포함하지 않는다.

열린 원격 화면은 `/remote-leases/{lease_id}/renew`에 bounded heartbeat를 보낸다. 매 갱신마다 현재 ADMIN·remote permission·binding owner·같은 API session·lease 상태를 다시 검사한다. 최초 생성 시 확정한 absolute 만료를 넘겨 연장하지 않으며 대상 binding·profile·operator·session을 바꿀 수 없다. heartbeat 유실·로그아웃·권한 회수·TTL 만료 시 연결을 닫고, 만료된 lease를 renew로 부활시키지 않는다. 새 lease 생성과 수집 재개는 별도 명령이다.

### 10.10 Permission·RBAC·공개 schema 변경

신규 `PermissionKey`는 `kakao_archive:read`, `kakao_archive:collect`, `kakao_archive:edit`, `kakao_archive:export`, `kakao_archive:remote`로 제안한다. 권한 배정은 기존 역할 정책에 명시적으로 추가한다. 처음에는 필요한 운영자에게만 열고 기존 VIEWER·AUTHOR 전체에게 학생 원문 접근을 암묵적으로 확장하지 않는다.

카카오 매니저, Linux 사용자, Studio ADMIN은 다른 권한이다. 이 기능은 카카오 매니저가 조회할 수 있는 범위 안에서 동작하지만 Studio에서는 실제 operator의 permission과 source-binding owner도 확인한다. UI 버튼을 숨기는 것만으로 권한 검사를 대신하지 않는다.

binding 생성·설정 commands는 **현재 ADMIN+collect**, 모든 remote lease·renew·authorize 경로는 **현재 ADMIN+remote**로 제한한다. API에서는 현재 실제 helper `require_permission(..., admin_only=True)`를 사용하고 기능 permission은 새 enum member로 정의한다. 이 ADMIN 전용 경로들의 BFF 변경 요청은 `require_admin_csrf`, 읽기·authorize는 `require_admin_session`을 사용한다. source owner 검사는 API/Catalog에서 별도로 수행한다. 새 `manage` permission을 만들지 않는다. 일반 조회·질문 구성·출력은 기존 session/CSRF dependency와 각각의 기능 permission·owner 검사를 적용한다.

현재 `ROLE_PERMISSIONS[ADMIN]`은 전체 `PermissionKey` 집합을 사용한다. enum만 수정해도 운영 DB permission row가 생기는 것은 아니므로 새 additive RBAC migration이 필요하다. 기존 migration이나 released schema bytes를 수정해 과거 의미를 바꾸지 않는다.

[현재 OpenAPI metadata 검사](https://github.com/teddyok1206/eomai/blob/6a824aa48967270cc116661813d3d734f2f16e4e/apps/application_api/eom_api/openapi.py)는 보호 route마다 고유한 `operation_id`와 정확히 하나의 `PermissionDependency`를 요구한다. 추가 permission은 기존 `x-eom-additional-permissions` 방식과 명시 검사로 다루고, 여러 dependency를 무작정 붙여 검사를 깨뜨리지 않는다.

schema에는 unknown field 금지, 명시적 discriminated action, ID 형식, 최대 배열 길이, cursor 길이, page 범위, enum·상태 transition, revision/hash pointer를 정의한다. schema→Pydantic→package mirror→IPC consumer→OpenAPI를 한 변경으로 맞춘다. 새 계약의 의미가 달라지면 successor version을 만든다.

### 10.11 오류·부분 완료·UI 재시도

| HTTP·예시 코드 | 의미 | UI 동작 |
| --- | --- | --- |
| 401 `AUTH_TOKEN_INVALID` | API 인증이 없거나 만료·철회됨 | 기존 로그인 흐름 사용; 원래 intent/key 보존 |
| 403 `PERMISSION_DENIED` | 기능 또는 source 범위 권한 없음 | 비활성·안내; 다른 계정으로 자동 대체 금지 |
| 404 `KAKAO_ARCHIVE_RESOURCE_NOT_FOUND` | 유효한 범위에 해당 포인터 없음 | 선택 해제·새로고침; 임의 최신 ID로 대체 금지 |
| 409 `KAKAO_ARCHIVE_COLLECTION_ACTIVE` | 같은 binding의 충돌하는 실행 | 기존 run 링크로 이동 |
| 409 `API_IDEMPOTENCY_CONFLICT` | 같은 key에 다른 내용 | 사용자 변경분과 원래 제출 intent를 구분 |
| 412 `API_PRECONDITION_FAILED` | 현재 logical revision/version 변경 | 새 revision 읽고 변경 비교 |
| 428 `API_PRECONDITION_REQUIRED` | 변경 요청에 If-Match가 없음 | 상세 조회의 ETag를 받아 명시적으로 다시 제출 |
| 422 `KAKAO_ARCHIVE_ASSOCIATION_AMBIGUOUS` | 질문·사진 연결을 확정할 근거 부족 | 원문과 후보 표시; 직접 선택 가능 |
| 429 `API_RATE_LIMITED` | 현재 경계의 요청 제한 | Retry-After와 polling backoff 적용 |
| 503 `KAKAO_ARCHIVE_EXECUTOR_UNAVAILABLE` | 실행 owner에 접수/조회 불가 | 접수 여부 확인; 새 key 무한 제출 금지 |
| run 상태 `AUTH_REQUIRED` | 카카오 세션에 수동 인증 필요 | 짧은 원격 lease 생성 후 인증; 동일 run 재개 |
| run 상태 `PARTIAL` | 일부 사진·방·연결 미완료 | 누락 수·원인·재시도 가능 항목을 표시 |

오류 응답에는 원문 대화·학생 개인정보·서명 URL·토큰·stack trace를 넣지 않는다. request ID와 안정된 오류코드를 사용한다. 사진 한 장이 만료되었다고 전체 작업을 데이터 없는 FAILED로 덮어쓰지 않고, 작업 실패가 있어도 성공한 원문 artifact는 보존한다.

### 10.12 Private 이미지·PDF 전달과 미리보기

현재 CSP는 `img-src 'self' data:`, `connect-src 'self'`, `object-src 'none'`이며 대부분의 응답은 framing을 금지한다. 따라서 카카오 signed URL을 `<img>`에 직접 넣거나 브라우저에 범용 URL proxy를 제공하지 않는다. 수집한 이미지의 인증된 same-origin preview/download route를 사용한다.

파일 URL에는 NAS path·실제 저장 파일명·임의 object key를 받지 않는다. attachment/export의 logical ID와 pin을 해석한 후 source 권한·revision·schema·media type·SHA-256·lifecycle을 확인한다. canonical blob을 public static 디렉터리에 복사하지 않는다.

pin의 출처는 **서버가 검증·발행한 immutable revision manifest**다. `rooms/{room_id}/messages`의 첨부 참조와 question revision 상세에는 `attachment_id`·`attachment_revision_id`·검증된 `sha256`·media metadata를 넣는다. 성공한 `exports/{export_id}` 응답에는 `export_revision_id`와 그 manifest에 고정된 PDF·페이지 preview pointer를 넣는다. 이 기능의 canonical 내부 참조는 `ArtifactMemberPointer`이며 `member_path`를 필수로 고정한다. 실제로 존재하는 API `ArtifactPointer`를 projection에 사용할 경우 `member_path → artifact_member`의 명시적 변환과 각 타입의 길이 제한을 검증하고 member 누락을 거부한다. nullable member를 primary-file fallback으로 해석하지 않는다. NAS `logical_uri`는 권한·파일 선택 근거가 아니다. 기능 전용 DTO에는 domain ID와 exact revision·검증 metadata만 노출할 수 있으며 이때 generic API pointer 변환을 생략한다. 이 기능별 DTO는 새 계약이다.

브라우저는 해당 응답에서 받은 revision을 필수 query로 전달한다. 아래는 **서명 URL이 아닌 신규 same-origin 인증 route의 형식 예**다.

```text
/studio/api/v1/kakao-archive/attachments/attachment_111/download?revision_id=attachmentrev_222
/studio/api/v1/kakao-archive/attachments/attachment_111/preview?revision_id=attachmentrev_222
/studio/api/v1/kakao-archive/exports/export_333/download?revision_id=exportrev_444
/studio/api/v1/kakao-archive/exports/export_333/pages/1/preview?revision_id=exportrev_444
```

서버는 query를 신뢰된 hash나 권한으로 간주하지 않고 해당 logical ID에 속하는 revision인지 확인한다. 실제 bytes의 기대 hash는 저장된 manifest에서 가져온다. query가 없으면 임의 `latest`로 보정하지 않고 입력 오류로 종료한다. 잘못된 소속·미완료·철회된 자료는 내보내지 않는다. 매 요청마다 Studio/API 인증과 source owner를 검증하고 `Cache-Control: private, no-store`를 적용한다. URL을 복사했다고 인증이나 source 권한을 얻을 수 없어야 한다.

[기존 downloads.py](https://github.com/teddyok1206/eomai/blob/6a824aa48967270cc116661813d3d734f2f16e4e/apps/web_gui/eom_web_gui/downloads.py)의 bounded download와 `download_response`를 재사용한다. 현재 구현은 chunk 검증, 1MiB memory threshold 뒤 spool, 동시 capacity 2, 길이/hash 확인과 ASGI 종료 시 정리를 제공한다. 신규 gateway에서 큰 파일 전체를 `.content`로 적재하는 별도 경로를 만들지 않는다.

초기 PDF 미리보기는 인증된 페이지 PNG와 PDF 다운로드 버튼으로 구성한다. 현재 inline PDF iframe 예외는 기존 item-db source preview 경로에 한정되어 있으므로 신규 PDF를 iframe으로 표시하려면 정확한 신규 경로만 추가하고 관련 CSP·frame 테스트를 만든다. 전체 `/studio`의 frame 제한을 해제하지 않는다.

학생 원문은 `textContent` 또는 동등한 escaping으로 표시한다. 선택·줄바꿈을 보존하되 메시지의 HTML·스크립트를 실행하지 않는다. 이미지 grid는 lazy loading과 제한된 동시 요청을 사용하고 view를 떠날 때 object URL을 해제한다. 질문 한 페이지에 배치할 수 없는 사진은 원본을 몰래 잘라 넣지 않고 layout 오류를 표시한다.

### 10.13 배포 파일·검증·문맥 갱신

[release_integrity.py](https://github.com/teddyok1206/eomai/blob/6a824aa48967270cc116661813d3d734f2f16e4e/apps/web_gui/eom_web_gui/release_integrity.py)의 `REQUIRED_RUNTIME_FILES`에 신규 JS·CSS·BFF contract·route를 추가한다. `static/*` package-data만으로 필수 runtime 무결성 목록까지 갱신되지는 않는다. 운영 source tree를 직접 읽는 fallback을 만들지 않는다.

`scripts/api/export_openapi.sh`로 OpenAPI와 checksum을 갱신하고 `scripts/contracts/audit_wire_contracts.py`로 canonical schema mirror를 확인한다. 신규 DB migration은 기존 protected release 절차와 API readiness의 지원 head를 함께 다룬다. 설치 source와 공개 main의 일치 여부는 실제 release record로 확인한다.

| 기존 검증 | 이번 변경에서 유지할 경계 |
| --- | --- |
| `tests/web_gui/test_studio_workbench.py` | query route round-trip·permission fail-closed |
| `tests/web_gui/test_studio_boot_navigation.py` | 늦은 boot 응답·owner/view 변경; 신규 controller stub 추가 |
| `tests/web_gui/test_frontend_backend_alignment.py` | JS 호출 method/path와 BFF/API 등록 정합성 |
| `tests/web_gui/test_api.py`, `test_gateway.py`, `test_security.py` | 세션·CSRF·typed projection·경로 검증 |
| `tests/web_gui/test_bounded_downloads.py`, `test_bounded_download_edges.py` | hash·길이·취소·spool 정리 |
| `tests/web_gui/test_gui_principle_alignment.py`, `test_design_system.py` | 기존 UI token·human mode·모바일 |
| `tests/web_gui/test_release_integrity.py`, `test_caddy_public_handover.py` | wheel runtime·현재 공개 프록시 경계 |
| `tests/api/test_router_common.py`, `test_identity_integration.py` | 멱등 command·실제 Operator 인증 |
| `tests/unit/test_dependency_boundaries.py`, `test_code_context_navigation.py` | 의존 방향·문맥 포인터 |

신규 테스트 파일은 `tests/web_gui/test_kakao_archive.py`, `test_kakao_archive_gateway.py`, `kakao_archive_browser_checks.mjs`, `tests/api/test_kakao_archive_routes.py`, `test_kakao_archive_permissions.py`로 제안한다. route·auth·download가 실제로 연결된 테스트를 작성하고 문자열 존재 검사만으로 완료 판정하지 않는다.

필수 시나리오는 무인증·CSRF 누락·다른 owner source 접근 거부, actor/session/profile 경로 위조 거부, DRAFT의 수집·주기 실행 거부, VERIFY_CHANNEL 대상 불일치, binding commands의 ADMIN+collect 검사, 동일 제출 재실행, 다른 body의 key 재사용 충돌, 질문 revision 경합, packet의 과거 pin 유지, account/view 전환 후 늦은 응답 무시다.

원격 경계에서는 ADMIN만 있거나 remote permission만 있는 경우 거부, 다른 API session·만료·폐기·권한 회수·absolute TTL 초과 renew 거부, 같은 lease의 갱신 경합과 활성 WebSocket 종료를 검사한다. private 다운로드는 revision query 누락·다른 logical ID의 revision·hash 실패·철회된 source를 거부하고 과거 정상 pin의 bytes가 바뀌지 않는지 확인한다. FULL/REPEAT 모두 전체 방의 새 CSV를 요청하고 AI dispatch를 호출하지 않는 것도 통합 시나리오에 포함한다.

실제 backend collection 실행은 UI를 닫아도 유지되어야 하고 원격 인증 view를 닫는 동작과 collection cancel은 구별해야 한다. UI 로그인 성공·작업 접수·수집 완료·PDF 생성·교육용 최종 검토를 서로 다른 상태로 표시한다.

구현 후 `docs/agent-context/system-map.md`, `document-output.md`, `index.json`에 새 owner·공개 흐름·테스트 포인터를 추가한다. 긴 설계 정본은 architecture 문서 한 곳에 두고 developer context에는 학생 원문·로그·인증 자료를 복제하지 않는다. 기존 자료 학습·ChatGPT·GraphRAG·임베딩 기능에는 이번 pipeline을 연결하지 않는다.

---

<a id="section-11"></a>

## 11. 런타임·원격 로그인·서버 배포 설계

이 절은 기존 Scientific Studio에 붙일 **제안 설계**다. Kakao 계정, 실제 운영 서버, 설치된 TigerVNC·websockify·Chromium에는 접속하지 않았다.
검토한 저장소 기준은 `6a824aa48967270cc116661813d3d734f2f16e4e`이며, 운영 설치본과 같다는 의미는 아니다.
아래의 새 endpoint, Linux 사용자, 경로와 unit 이름은 구현 시 확정할 제안값이다.

### 11.1 현재 저장소에서 확인한 연결 지점

| 확인한 파일·심볼 | 현재 사실 | 이번 기능에 주는 제약 |
| --- | --- | --- |
| `config/caddy/Caddyfile` | Caddy admin은 보호된 Unix socket, 공개 upstream은 Studio 8790뿐 | admin socket과 기존 경로를 보존하고 원격 화면만 좁게 추가 |
| `config/systemd/caddy.service.d/eom-security.conf` | caddy-admin 디렉터리0700, UMask0077, Unix socket을 지정한 ExecReload | 새 기능을 위해 Caddy 제어 권한을 넓히지 않음 |
| `app.py::login`, `COOKIE_NAME` | `eom_studio_session` cookie의 Path는 `/studio` | 통합 원격 URL도 `/studio/` 아래에 배치 |
| `sessions.py::SessionStore` | bounded process-local session 저장소 | Caddy가 cookie 문자열만 보고 인증할 수 없고 Web 재시작 후 재인증 필요 |
| `settings.py::ServerSettings` | loopback bind와 Web worker1개를 강제 | 원격 화면 때문에 BFF를 임의로 다중 worker로 바꾸지 않음 |
| `gateways.py::HttpApplicationGateway._authorized` | API 토큰은 서버에 보관하고 refresh lock을 공유 | 새로운 인증 요청도 이 경계를 사용하고 토큰을 noVNC로 보내지 않음 |
| `app.py::require_admin_session` | WebSession의 역할 projection 검사 | 민감한 원격 제어는 API의 현재 권한·객체 범위도 재검증 |
| `infra/systemd/eom-web-gui.service` | 전용 eom-web UID, 외부 egress 차단, NAS·worker home 차단 | Web 프로세스 안에서 Kakao 브라우저를 실행하지 않음 |
| `infra/systemd/eom-image-reference-acquirer@.service` | 외부 수집용 전용 UID, local workspace, NAS 접근 금지 | 새 deterministic browser runtime의 격리 패턴 참고 |
| `infra/polkit/50-eom-worker-units.rules` | owner별 고정 unit 이름·verb allowlist | 새 runtime 활성화 권한을 별도 검토·검증 |
| `release_integrity.py::REQUIRED_RUNTIME_FILES` | Web wheel의 전체 파일 inventory 검사 | UI 모듈 추가도 정식 build·release 검증에 반영 |

위 근거의 고정 commit 링크는 이 절 끝의 Runtime-R1–Runtime-R13에 있다. 검색한 범위에서는 Kakao 채널 collector, noVNC, websockify 또는 TigerVNC runtime의 기존 구현을 발견하지 못했다.
일부 기출 웹 수집 테스트에 있는 Kakao CDN 주소는 이 기능의 구현 근거가 아니다.

### 11.2 권장 책임 배치

Studio는 제어 화면과 인증된 command/query를 제공한다. Application API는 실제 operator와 Identity session을 확인하고 원격 작업의 권한·객체 범위를 판정한다.
Orchestrator의 좁은 runtime adapter가 브라우저 runtime의 작업과 수동 모드 전환을 지시한다.
collector는 명시된 local 입력을 읽고 local 결과를 제출하며 DB·NAS를 직접 쓰지 않는다. artifact 등록·정본 보관은 기존 Orchestrator publication 경계를 사용한다.

실행 구조는 기존 `visual_reference_acquisition.py`의 staged typed command, 고정 실행, 결과 검증, publication 경계를 참고한다.
수집 run/task/attempt의 정본 상태와 artifact publication에서 생성되는 JobRecord는 별개다. 기존 `CatalogArtifactService.commit_file_set()`이 생성하여 반환한 `publication_job_id`를 domain 결과에 연결한다.
이를 맞추려고 가짜 authoring job을 먼저 만들거나 기존 smoke worker 경로를 재해석하지 않는다.

브라우저 session service와 Xvnc·websockify 보조 프로세스는 하나의 업무 runtime 경계로 관리한다.
MVP는 connector/profile 하나, browser+Xvnc 실행 하나, gateway 실행 하나로 제한한다. 두 실행의 OS UID는 분리하되 별도의 범용 job queue나 worker framework를 만들지 않는다.
주기 실행은 core 설계의 owner tick loop와 PostgreSQL schedule/run 상태를 사용한다.
systemd는 고정 runtime 실행을 맡으며 별도 collector timer·cron이나 worker의 직접 DB claim을 추가하지 않는다.

### 11.3 공개 경로와 내부 연결

| 구간 | 제안 경로·연결 | 인증·접근 주체 |
| --- | --- | --- |
| Studio 화면 | 기존 `https://eomai.duckdns.org/studio/` | 기존 Studio 인증 |
| noVNC HTML·정적 파일 | `/studio/admin/remote/*` | Caddy가 매 요청을 Web authorization endpoint로 확인 |
| noVNC WebSocket | `wss://eomai.duckdns.org/studio/admin/remote/websockify` | 현재 Studio session, ADMIN+remote permission, 해당 connector의 원격 lease, Origin |
| authorization 내부 조회 | 제안 `/studio/api/v1/kakao-archive/remote/authorize` | Caddy가127.0.0.1:8790으로 직접 호출 |
| Caddy→websockify | 제안 `/run/eom-kakao-remote/gateway.sock` | 제한된 Unix socket 그룹 |
| websockify→VNC | 제안 `/run/eom-kakao-vnc/vnc.sock` | browser·gateway만 속한 별도 VNC-connect 그룹 |
| Chromium→X display | 전용 display와 Xauthority | 같은 runtime의 승인된 프로세스만 |

공개 noVNC 경로에 `/studio`를 포함하는 것은 cookie Path를 존중하기 위한 결정이다.
`/admin/remote/*`를 별도로 열면 현재 Studio cookie가 전달되지 않는다.
메뉴를 ADMIN에게만 보여주는 UI 제어는 HTTP·WebSocket 인증을 대신하지 못한다.

### 11.4 원격 session과 manual lease

원격 화면을 요청하면 먼저 **수동 제어 lease**를 획득한다. 이 lease는 Kakao 로그인 cookie의 유효기간과 별개이며, 프로필을 누가 언제 조작할 수 있는지를 결정한다.
원격 화면은 세션을 유지하는 도구이고, Kakao 세션을 무기한 보장하는 수단은 아니다.

수동 세션 생성·갱신·종료 command endpoint는 모두 신규 제안이며 공개 schema부터 정의한다. route의 구체 이름은 구현자가 기존 API 명명과 충돌 여부를 확인해 확정한다.
변경 요청에는 기존 Studio ADMIN 검사, CSRF 검사와 API idempotency 경계를 적용한다.
GET authorization 조회는 이미 존재하는 lease를 확인할 뿐 시작·갱신·재시도를 발생시키지 않는다.

권한 판단에 필요한 값은 다음과 같다.

- 실제 인증된 operator와 API Identity session.
- 그 operator가 현재 사용할 수 있는 connector/channel 객체.
- 원격 lease의 owner, 대상 profile, 모드, 발급 epoch, 만료 시각과 종료 여부.
- 해당 profile의 자동 수집 실행 여부와 전환 가능한 checkpoint.
- 현재 설치된 runtime이 지원하는 제어 capability.

API의 `Auth`가 인증한 Identity `session_id`를 서버가 직접 파생하여 lease owner로 pin한다. 프런트엔드가 제출한 operator ID, session ID 또는 ADMIN 문자열은 권한 근거로 사용하지 않는다.
`websession_*`는 bearer cookie이므로 일반 DB 식별자·감사 로그·worker 입력에 원문으로 기록하지 않는다.
BFF는 자신의 메모리 WebSession에 원격 lease pointer만 연결하면 된다. DB에는 API가 파생한 비밀이 아닌 Identity session 참조와 domain lease metadata를 보관한다.

현재 `_operator_view()`는 API session ID를 Web 공개 projection에서 제외한다. 이 사실을 우회하려고 프런트엔드에 인증 토큰을 노출하거나 session ID 입력란을 만들지 않는다.
새 application use case는 `Auth`의 실제 `AccessAuthentication.session_id`와 `RequestContext.actor()`로 도출한 identity 및 현재 권한 재검증을 사용한다. `owner_capture()`가 신규 operation에 자동 제공된다고 가정하지 않는다. 추가 authenticated owner capture가 필요해지면 해당 operation 등록·capture 생성·consumer 계약을 별도 명시적으로 변경한다.
ADMIN 역할뿐 아니라 대상 connector 소유·위임·사용 가능 상태를 함께 검사한다.
다른 ADMIN이 존재한다는 이유만으로 현재 다른 사용자가 제어 중인 Kakao 프로필을 넘겨주지 않는다.

### 11.5 authorization endpoint의 응답 계약

제안 endpoint는 현재 Web cookie를 SessionStore에서 해석하고, 필요한 API 권한·lease 조회를 수행한다.
Caddy가 전달한 원래 URI·method를 읽어 허용된 정적 파일 요청 또는 고정 WebSocket 경로인지 확인한다.
임의 upstream, 임의 파일 경로, 다른 profile이나 임의 명령을 이 endpoint로 선택하게 하지 않는다.
WebSocket은 정확히 `/studio/admin/remote/websockify`만 허용하고 실제 지원하는 method·handshake 형태·정확한 Origin을 확인한다.
정적 자산 URL을 이용한 WebSocket upgrade와 예상하지 않은 method는 거부한다. 고정 URL은 client의 약속이 아니라 서버에서 강제할 계약이다.
활성 manual lease의 현재 owner와 대상 binding 권한을 추가 확인한다.
해당 endpoint는 정상 허용 때만204 등2xx를 반환한다. `authorized: false`를 HTTP200으로 반환하면 Caddy가 허용하므로 금지한다.
응답 body·header에 Kakao 비밀번호, cookie, VNC secret 또는 CDP endpoint를 넣지 않는다.

| 상황 | 권장 응답 의미 |
| --- | --- |
| 현재 세션·권한·scope·lease가 모두 유효 | 204, body 없음 |
| Studio 세션 없음 또는 재인증 필요 | 401 |
| 현재 역할·scope·Origin 불일치 | 403 |
| 해당 사용자의 활성 manual lease 없음·모드 충돌 | 403, 존재 비공개 정책에서는404; 제어 command의409와 구분 |
| 권한 service나 runtime 상태를 신뢰할 수 없음 | 503, 허용으로 대체하지 않음 |

현재 Web의 cached `session.operator`만으로 장기 원격 제어를 허용하지 않는다. 새 API use case에서 현재 인증·ADMIN·`kakao_archive:remote` permission·binding scope를 확인한다.
API 토큰 refresh는 기존 `_authorized`와 `refresh_lock` 계약을 유지한다.
재인증 실패를 cached role로 우회하거나 새로운 사용자를 대신 만들어 계속 진행하지 않는다.

### 11.6 이미 연결된 WebSocket의 철회

Caddy의 forward_auth는 접속 전 검사다. 이미 열린 WebSocket은 HTTP 인증 조회를 매 frame마다 반복하지 않으므로 별도 종료 경계가 필요하다.
초기 구현은 **manual lease 하나당 websockify 실행 하나**를 Orchestrator의 runtime adapter가 제어한다.
lease가 끝나면 해당 고정 gateway unit과 연결 자식 프로세스를 종료하여 기존 viewer까지 끊는다.
새 lease에서는 새 gateway epoch를 사용하고 이전 연결을 재사용하지 않는다.

초기 제안값은 UI heartbeat10초, 갱신 TTL30초, lease 생성부터 절대 최대20분이다. 실제 로그인 시간·네트워크 특성을 보고 확정한다.
heartbeat는 기존 session·CSRF와 API의 현재 권한·scope 검사를 통과해야 한다.
heartbeat로도 최초 발급 때 확정한20분 상한을 넘길 수 없으며 만료 후에는 현재 권한으로 새 lease를 요청한다.
종료 버튼, Studio logout, session 철회, ADMIN 제거, 대상 권한 철회는 lease 종료로 연결한다.
즉시 종료 통지가 누락돼도 supervisor의 TTL 만료가 연결을 닫아야 한다.
권한 service가 응답하지 않으면 새 TTL을 발급하지 않는다. 설계·운영 문서에 최대 철회 지연을 TTL과 처리 여유의 합으로 명시한다.
브라우저는 background tab의 timer를 제한할 수 있으므로 탭 전환·화면 잠금·절전 후 heartbeat가 늦어져 연결이 종료될 수 있다.
이 경우 권한을 무기한 유지하지 않고 화면으로 돌아온 사용자가 상태를 확인해 수동 재연결하는 것이 의도된 동작이다. 만료된 lease를 자동으로 부활시키지 않는다.

viewer가 잠깐 끊기는 것과 lease가 종료되는 것은 다른 사건이다.
짧은 연결 장애만으로 로그인 중인 Chromium을 즉시 죽이지 않고 유효 lease 안에서는 재연결을 허용한다.
lease 종료 후에는 gateway와 기존 viewer를 먼저 닫고, 브라우저를 정상 종료하여 profile을 flush한다.
이전 프로세스 종료 확인 후 새 AUTO fence·profile lock으로 다시 열어 세션·채널 probe를 통과해야 자동 수집을 재개한다.
권한 철회나 불명확한 프로세스 상태에서는 AUTO를 자동 재개하지 않고 STOPPED 또는 ERROR 등 정의된 상태로 전이한다.
Web 재시작으로 SessionStore가 사라지면 이전 viewer의 권한을 추정 복원하지 않는다.
API lease와 runtime의 잔여 상태를 reconcile하고, TTL 종료 또는 재인증 경로로 정리한다.

### 11.7 Caddyfile 전체 제안

아래는 기존 설정을 보존한 **설계 예시**다. 새 authorization endpoint와 UDS runtime이 먼저 구현돼야 동작한다.
Caddy2.11.4의 실제 설치 바이너리로 adapt/validate와 양·음성 검증을 수행하기 전에는 운영 적용 완료로 간주하지 않는다.

```caddyfile
{
    # Local workloads include untrusted renderer processes. Keep Caddy's
    # configuration API off TCP loopback and behind a caddy-only directory.
    admin unix//run/caddy-admin/admin.sock
}

eomai.duckdns.org {
    header Strict-Transport-Security "max-age=31536000"

    route {
        @root path /
        redir @root /studio/ 308

        # PROPOSED: direct public calls to the internal authorization route.
        @remoteAuthPublic path /studio/api/v1/kakao-archive/remote/authorize
        respond @remoteAuthPublic 404

        # PROPOSED: must remain before the existing /studio reverse proxy.
        handle /studio/admin/remote/* {
            route {
                @badRemoteWebSocketOrigin {
                    path /studio/admin/remote/websockify
                    not header Origin https://eomai.duckdns.org
                }
                respond @badRemoteWebSocketOrigin 403

                request_header -X-EOM-Remote-*
                request_header X-EOM-Remote-Original-Upgrade {http.request.header.Upgrade}
                request_header X-EOM-Remote-Original-Connection {http.request.header.Connection}
                request_header X-EOM-Remote-Original-Proto {http.request.proto}
                forward_auth 127.0.0.1:8790 {
                    uri /studio/api/v1/kakao-archive/remote/authorize
                    # The auth clone must reach FastAPI as ordinary HTTP.
                    header_up -Upgrade
                    header_up -Connection
                }

                # Authorization sees the original URI before this rewrite.
                uri strip_prefix /studio/admin/remote

                header {
                    Cache-Control "no-store"
                    X-Content-Type-Options "nosniff"
                    X-Frame-Options "SAMEORIGIN"
                    Content-Security-Policy "frame-ancestors 'self'"
                }

                reverse_proxy unix//run/eom-kakao-remote/gateway.sock {
                    header_up -Cookie
                    header_up -Authorization
                    header_up -X-EOM-Remote-*
                }
            }
        }

        @studio path /studio /studio/*
        reverse_proxy @studio 127.0.0.1:8790

        respond 404
    }
}
```

outer·inner `route`는 적은 순서대로 처리하도록 둔다.
`handle_path`는 prefix를 먼저 제거하므로 이 설계에서는 `handle` 후 인증, 그 다음 명시적 `uri strip_prefix`를 사용한다.
forward_auth는 clone한 요청을 GET으로 바꾸고 원래 method·URI를 `X-Forwarded-Method`, `X-Forwarded-Uri`에 설정한다.
추가로 **인증 clone에서만 Upgrade·Connection을 제거**한다. Uvicorn은 WebSocket upgrade header가 있으면 HTTP GET route 이전에 WebSocket scope로 전환할 수 있으므로, 이 처리가 없으면 HTTP용 authorize endpoint가 정상 WS 요청을 거부할 수 있다. 원래 handshake 정보는 삭제 전에 별도 순차 `request_header`로 캡처하고 클라이언트가 보낸 같은 prefix를 먼저 제거한다. header_up 내부에서 삭제와 같은 header의 placeholder 캡처를 섞지 않는다.

BFF는 `X-Forwarded-Method/Uri`, `X-EOM-Remote-Original-Upgrade/Connection/Proto`, Origin과 필요한 Sec-WebSocket header를 검증한다. 이 metadata는 identity 증거가 아니며 실제 Studio/API 세션·현재 권한·lease 검사를 대체하지 않는다. 최종 gateway proxy에서는 캡처 metadata만 제거하고 원래 Upgrade·Connection은 유지한다. 인증 subrequest는 HTTP204, 실제 gateway 연결은 정상101과 양방향 RFB로 이어지는지 실측한다.
기존 `/studio` upstream은 경로를 strip하지 않는다.
기존에 공개하지 않은 API8765·Observe8780·기타8000을 새 catch-all upstream으로 추가하지 않는다.

authorization endpoint의 공개 요청은 Caddy에서404지만 내부 auth subrequest는127.0.0.1:8790으로 직접 간다. 그러므로 이 응답 차이가 forward_auth의 동작을 막지 않는다.
localhost라는 이유만으로 요청을 신뢰하거나 `X-Remote-User` 같은 사용자 입력 header를 권한으로 받아들이면 안 된다.
동일 host의 다른 프로세스는 loopback에 요청할 수 있으므로 endpoint 자체가 실제 cookie·API 권한을 검사해야 한다.
Caddy가 설정한 원래 URI는 resource 선택 정보이며 authentication credential이 아니다.

Origin 검사는 브라우저의 다른 사이트에서 원격 연결을 여는 것을 제한하는 보조 경계다. 그 자체가 operator 인증은 아니며 비브라우저 client는 Origin을 지정할 수 있다.
위 matcher는 고정 transport 경로에 프로토콜 구분 없이 Origin을 요구하므로 복잡한 WebSocket CEL 표현이 필요 없다.
이 단순화는 authorization 구현이 정확한 path·method·Origin·handshake를 확인하고 다른 경로의 upgrade를 거부할 때 성립한다.
실제 Caddy와 noVNC 조합에서 고정 경로의 Origin 거부와 정적 자산 경로를 이용한 upgrade 거부를 모두 확인한다.
초기 WS 지원 범위는 실제 통합시험한 HTTP/1.1 GET·Upgrade websocket handshake다. HTTP/2·3 extended CONNECT는 검사 구현과 브라우저 통합시험 전에 허용하지 않는다. 이를 맞추려고 기존 Studio의 HTTP/2 설정을 전역으로 바꾸지 않는다. 정적 자산 URL의 upgrade 요청도 캡처한 원래 handshake 정보로 거부한다.
일반적인 WebSocket reverse proxy에 nginx용 Connection/Upgrade 설정을 그대로 복사할 필요는 없다.

### 11.8 iframe과 noVNC 자산 배치

초기 UI는 Studio의 운영 도구 안에 전용 iframe을 두는 방식이 충분하다. iframe은 활성 manual lease를 얻은 뒤에만 `/studio/admin/remote/vnc.html`을 연다.
재연결·종료 상태는 Studio가 보여주고, 인증 오류를 숨긴 채 무한 reconnect하지 않는다.
noVNC의 WebSocket 주소는 같은 origin의 `wss://.../studio/admin/remote/websockify`다.

noVNC current 문서는 `path`에 완전한 WebSocket URL 또는 상대 경로를 허용한다.
구버전의 host/port/encrypt/path 조합과 다를 수 있으므로 선택한 고정 release의 문서·UI 구현을 기준으로 설정한다.
URLSearchParams 등으로 값을 인코딩하고 비밀번호·cookie·장기 bearer token을 query에 넣지 않는다.
비밀이 아닌 lease ID가 필요해도 현재 session과 server-side lease 검증을 대체하는 bearer로 취급하지 않는다.
초기 단일 profile 설계에서는 현재 WebSession에 연결한 활성 lease로 식별하면 별도 URL token 체계가 필요 없다.

현재 Studio 응답의 `frame-ancestors 'none'`과 X-Frame-Options DENY는 Studio 자체의 iframe 삽입을 막는다.
이것이 Studio가 동일 origin의 noVNC iframe을 포함하는 것을 곧바로 금지하는 것은 아니다.
noVNC 응답에만 필요한 same-origin framing을 허용하고 Studio 전체 보호 header를 완화하지 않는다.
추가 CSP 강화는 고정된 noVNC 자산·WebSocket 동작을 검증한 뒤 해당 route에 한정해 적용한다.
client의 `viewOnly` 옵션은 권한 제어가 아니므로 자동 수집 중 안전한 관찰 모드의 근거로 사용하지 않는다.

noVNC는 예컨대 `/opt/eom/kakao-remote/releases/<pinned-release>/noVNC`에 root 소유·runtime read-only로 설치한다.
필요한 app/core/vendor와 license를 포함한 정확한 배포 inventory·hash를 기록한다.
웹 root에는 이 검증된 정적 자산만 두고 CSV, 사진, 프로필, 다운로드 workspace를 넣지 않는다.
현재 Web wheel의 `static/*` package-data와 exact runtime inventory에 noVNC 폴더를 임의 복사하지 않는다.
Studio용 작은 UI 모듈은 Web wheel과 `REQUIRED_RUNTIME_FILES`에 정식 추가한다.

### 11.9 UID·디렉터리·socket 권한

browser UID의 예시는 `eom-kakao`, gateway UID는 `eom-kakao-remote`이며 설치 계약에서 확정한다.
기존 `eom-cdx-01`부터06까지의 Codex 슬롯·로그인 자료를 재사용하지 않는다.
새 UID에 sudo, Docker, 기존 `eom` 또는 `caddy` 그룹을 주지 않는다.
브라우저 profile은 해당 전용 UID만 읽고 쓸 수 있어야 한다.

| 제안 자원 | 소유·모드 의도 | 접근 범위 |
| --- | --- | --- |
| `/var/lib/eom-kakao`와 profile | eom-kakao, 디렉터리0700 | browser runtime 전용 |
| `/run/eom-kakao-private` | eom-kakao,0700 | Xauthority·runtime lock, gateway 접근 불가 |
| `/run/eom-kakao-vnc` | eom-kakao:eom-kakao-vnc,2750 | browser는 생성, gateway는 traverse |
| `vnc.sock` | eom-kakao:eom-kakao-vnc,0660 | 승인된 gateway만 VNC에 연결 |
| `/run/eom-kakao-remote` | eom-kakao-remote:eom-kakao-proxy,2750 | gateway는 생성, Caddy는 traverse |
| `gateway.sock` | eom-kakao-remote:eom-kakao-proxy,0660 | Caddy가 gateway에 연결 |
| local capture output | 별도 검증된 handoff 권한 | runtime 작성, Orchestrator 검증·읽기 |
| 고정 noVNC·browser·Python release | root 소유, runtime read-only | 실행 파일·자산의 runtime 변경 금지 |

`eom-kakao-vnc` 그룹은 browser·gateway만, `eom-kakao-proxy`는 gateway·Caddy만 사용한다.
Caddy는 raw VNC socket, Xauthority, Kakao profile과 output handoff 그룹에 접근하지 않는다.
gateway도 profile·Xauthority·capture output 파일에는 접근하지 않는다. gateway에 VNC 연결 권한이 있다는 것은 화면을 보고 제어할 수 있다는 의미이며 이 능력까지 격리됐다고 주장하지 않는다.
다만 gateway 취약점으로 browser profile 파일을 직접 읽을 수 있는 같은-UID 배치를 피한다.
이 분리는 browser renderer와 별도 UID라는 사실만으로 보장되지 않으며 socket·디렉터리 권한과 unit sandbox를 실제 검사한다.
두 그룹 중 어느 것도 기존 Caddy admin 그룹이나 NAS의 `eom` 그룹을 대신하지 않는다.
worker에게 NAS 권한을 주기 위해 기존 `eom` 그룹에 추가하는 해결책은 사용하지 않는다.
output은 명시된 local staging 경계로 전달하고 profile·secret 경로를 결과 manifest에서 참조하지 못하게 검증한다.

`/run`은 재부팅 후 다시 만들어야 한다.
root-owned tmpfiles 규칙 또는 검토한 RuntimeDirectory 절차로 owner·group·mode를 재현한다.
여러 디렉터리의 group이 다른데 하나의 RuntimeDirectoryMode만으로 해결됐다고 가정하지 않는다.
stale socket 처리에는 실제 socket type·owner·활성 프로세스 검사를 적용하고 임의 symlink나 regular file을 unlink하지 않는다.
private socket 자체뿐 아니라 모든 상위 디렉터리의 traverse 권한을 검사한다.

### 11.10 TigerVNC를 이용한 가상 화면

기본 후보는 **TigerVNC Xvnc**다. Xvnc는 물리 모니터 없이 가상 X 화면과 VNC server를 함께 제공하므로 Xvfb+x11vnc를 대체할 수 있다.
공식 문서에 `-rfbunixpath`, `-rfbunixmode`, TCP listener를 끄는 `-rfbport -1`이 명시돼 있다.
설치 패키지의 executable 이름·버전·지원 옵션은 아직 확인하지 않았다.

설치 버전을 확인한 뒤 구성할 옵션의 예시는 다음과 같다.

```text
Xvnc :<전용-display>
  -geometry <검증한-화면크기> -depth 24
  -auth <전용-Xauthority>
  -nolisten tcp
  -rfbport -1
  -rfbunixpath /run/eom-kakao-vnc/vnc.sock
  -rfbunixmode 0660
  -SecurityTypes VncAuth
  -PasswordFile <보호된-vncpasswd-파일>
```

위는 shell에 그대로 붙여 넣을 실행 명령이 아니라 검증할 옵션 목록이다.
X11의 `-nolisten tcp`와 VNC의 `-rfbport -1`은 서로 다른 listener를 닫는다.
Xauthority cookie를 생성·보호하고 승인된 Chromium에만 DISPLAY·XAUTHORITY를 전달한다.
`-ac`나 무제한 `xhost +`로 화면 접근 제어를 끄지 않는다.
기본 `VncAuth` 구성의 비밀번호는 운영자가 별도로 설정하여 보호된 vncpasswd 파일로 관리하고 argv·URL·로그에 넣지 않는다.
websockify는 RFB 인증을 대신 수행하지 않으므로 사용자는 noVNC의 credential prompt에 이 **별도 VNC 비밀번호를 수동 입력**한다.
이 비밀번호는 Kakao 로그인 비밀번호와 다르다. 화면 연결 후 필요한 Kakao 로그인·2FA는 원격 브라우저 안에서 사용자가 수행한다.
VNC 비밀번호를 query, localStorage, sessionStorage, Artifact, 설정 manifest에 저장하지 않고 prompt 입력값은 현재 연결에만 사용한다.
추가 입력창을 없애기 위해 승인 없이 `SecurityTypes None`으로 바꾸거나 공개 TCP VNC로 전환하지 않는다.
VncAuth를 강력한 외부 인증의 대체물로 보지 않고 Studio 인증·UDS 권한을 주 경계로 둔다.

이 가상 화면에는 수집용 브라우저만 열고 기존 개인 desktop이나 운영 terminal을 공유하지 않는다.
headless Chromium은 이 화면에 나타나지 않는다. noVNC를 사용하는 manual 모드는 headed browser를 Xvnc display에 띄워야 한다.
자동 수집도 동일 화면에서 관찰하려면 headed 실행을 택하되 제어·관찰 모드를 서버에서 분리한다.
초기 버전에서는 manual 전용 gateway만 열고 자동 실행 중 원격 조작을 허용하지 않는 편이 단순하다.

x11vnc를 대안으로 선택할 때는 설치본의 실제 Unix socket 지원을 별도로 검증한다.
`-unixsockonly`는 버전별 문서가 달라 공통 지원 명령으로 단정할 수 없다.
이 설계는 확인하지 않은 x11vnc flag 조합을 필수 설치 명령으로 제공하지 않는다.

### 11.11 websockify UDS 구성

upstream의 `websocketproxy.py` parser를 확인한 결과 다음 조합은 positional listen/target endpoint가 필요 없다.
`--unix-listen`이 listen 주소를, `--unix-target`이 target 주소를 대체한다.
`--unix-listen-mode 660`은8진수 권한으로 해석된다.

```text
<고정-Conda-environment>/bin/websockify
  --unix-listen /run/eom-kakao-remote/gateway.sock
  --unix-listen-mode 660
  --unix-target /run/eom-kakao-vnc/vnc.sock
  --web <고정-noVNC-release-root>
```

이 역시 설치된 release의 help·실제 연결 검증을 거쳐 supervisor argv로 확정할 예시다.
해당 UDS 경로에는 `--libserver`를 추가하지 않는다.
조사한 upstream의 LibProxyServer는 Unix listener 옵션을 같은 방식으로 적용하지 않으며 일부 옵션을 무시한다.
systemd/supervisor가 생명주기를 관리하므로 자체 daemon 옵션도 사용하지 않는다.
필요하다면 upstream의 ExpectOrigin auth plugin을 WebSocket 보조 검사로 검토하되 Studio 권한 검사를 대체하지 않는다.
정적 요청에는 보통 Origin이 없으므로 Origin 전용 검사를 모든 HTTP 자산 요청에 무조건 강제하지 않는다.

gateway의 HTTP·WebSocket은 permissioned UDS로만 받는다. 공개 TLS는 Caddy가 처리하고 브라우저는 WSS를 사용한다.
기본 설계에서 TCP6080이나5901을 추가로 열지 않는다.
gateway 종료 시 listener만 닫히고 이미 fork된 연결 프로세스가 살아남지 않는지 검증한다.
TTL 만료는 listener 제거뿐 아니라 현재 viewer의 RFB 데이터 흐름 종료까지 관측해야 한다.

### 11.12 browser profile과 모드 전환

profile마다 DB의 실행 claim과 OS의 실제 exclusive lock을 함께 사용한다. DB lease는 업무 동시성을, OS lock은 직접 수동 실행·재시작을 포함한 동일 profile 중복 사용을 막는다.
profile 경로는 browser service가 소유하고 요청자가 arbitrary userDataDir을 지정할 수 없게 한다.
일반 사용자의 Chrome 기본 프로필을 자동화에 연결하지 않는다.

runtime 모드는 core 설계와 동일한 `STOPPED/AUTO/PAUSING/MANUAL/AUTH_REQUIRED/ERROR`다.
collection run의 `COLLECTING` 등 업무 상태나 기존 global JobRecord 상태와 혼용하지 않는다.

| 현재 runtime 모드 | 요청·사건 | 처리 |
| --- | --- | --- |
| STOPPED | 권한 확인된 자동 수집 claim | 새 fence·profile lock으로 브라우저 시작 후 AUTO |
| AUTO | manual 요청 | PAUSING으로 전환하고 현재 원자 작업의 안전 지점까지 기다림 |
| PAUSING | checkpoint 완료 | 실행권 반환→browser close/flush·종료 확인→manual fence·lock 아래 headed reopen→gateway |
| AUTH_REQUIRED | 유효 manual lease | headed mode와 gateway를 시작하여 사용자 로그인 |
| MANUAL | 완료·재개 요청 또는 재개를 허용한 만료 | gateway 종료→browser 정상 종료·flush→새 fence로 재개·probe |
| MANUAL | 권한 철회·재개 비허용 종료 | gateway와 browser 정리 후 STOPPED 등 정의된 상태 |
| 어떤 모드든 | 불명확한 프로세스·lock 잔재 | ERROR에서 reconcile, 강제 중복 실행 금지 |

manual→AUTO 전환도 DB의 배타성과 OS lock을 유지·재확인하며 같은 profile의 두 프로세스가 겹치지 않게 한다.
새 브라우저를 띄우기 전에 이전 context와 브라우저 프로세스가 종료됐는지 확인한다.
살아 있는 프로세스의 Chromium SingletonLock을 지워 강제로 profile을 열지 않는다.
기본적으로 context.close를 통한 정상 종료로 profile을 flush하고 제한 시간을 넘은 경우에만 해당 runtime 프로세스를 종료한다.
재시작 후 PID만으로 이전 실행을 동일시하지 말고 unit/runtime epoch와 실제 프로세스를 함께 reconcile한다.
login 완료 버튼을 누른 사실만으로 세션 검증 성공이나 AUTO 전환 가능 상태를 기록하지 않는다.

### 11.13 systemd·Conda·sandbox

Python executable, Playwright 버전, browser revision과 noVNC/websockify release를 명시적으로 pin한다. Conda 경로는 신규 runtime 전용으로 선택하고 ambient Python이나 운영 checkout import에 의존하지 않는다.
Kakao runtime의 기능 때문에 기존 Web/Runner egress 제한을 넓히지 않는다.
새 browser 프로세스는 Kakao 로그인·채널·첨부 다운로드에 필요한 인터넷 접근을 별도로 검증한다.
Kakao CDN host·redirect는 실제 관찰 결과로 결정하며 추정 목록을 영구 allowlist로 고정하지 않는다.

기존 Web와 Runner의 `IPAddressDeny=any`, `IPAddressAllow=localhost`를 새 browser unit에 그대로 복사하면 외부 접속이 막힌다.
browser와 Xvnc는 같은 browser session unit이 소유하여 동일 PrivateTmp에서 X socket을 공유한다.
gateway는 별도 UID의 고정 unit으로 두고 VNC의 pathname UDS만 연결한다.
gateway는 인터넷이 필요 없으므로 AF_UNIX·private network 등 좁은 연결 범위를 검증할 수 있다.
browser·Xvnc까지 별도 unit에 무심코 PrivateTmp를 각각 켜면 `/tmp/.X11-unix`가 달라져 display 연결이 실패할 수 있다.

새 unit에는 전용 UID, read-only 실행 release, 필요한 profile·workspace만 쓰기, NAS·다른 worker home 차단을 적용한다.
프로세스·메모리·종료 예산을 명시하되 Chromium subprocess 수와 정상 profile flush를 실제로 확인한다.
runtime 전체 종료는 두 unit의 자식까지 정리하고, manual gateway 종료는 browser 생명주기와 구분한다.
Orchestrator만 고정 두 unit을 제어하며 browser worker가 gateway UID를 kill하기 위한 sudo나 범용 제어 권한을 얻지 않는다.
gateway의 TTL watchdog은 owner가 승인한 짧은 lease 기한만 적용하며 임의로 연장하지 않는다. 소유 owner가 중단되어도 watchdog은 만료 시 기존 연결을 끊어야 한다.
worker에게 arbitrary systemctl, transient unit 또는 임의 executable 실행 권한을 주지 않는다.
새 fixed unit·control verb의 좁은 polkit 허용과 교차 owner 거부 테스트를 함께 추가한다.

Playwright의 Chromium sandbox 옵션 기본값은 false라고 공식 문서에 명시돼 있다.
제안 launcher는 `chromium_sandbox=True`를 명시하고 설치 OS·unit 제약 아래에서 실제 실행을 확인한다.
실행 실패를 무조건 `--no-sandbox`로 해결하지 않는다.
저장소의 AppArmor 규칙은 Codex bundled bwrap의 특정 executable 경로에 대한 것이며 Chromium 허용 근거가 아니다.
새 실행 파일에 필요한 좁은 정책을 검토하고 전역 unprivileged-userns 제한을 일괄 해제하지 않는다.

질문집 PDF renderer에는 Kakao 로그인 profile을 재사용하지 않는다. 학생 메시지와 첨부는 untrusted 입력이므로 별도 offline renderer·workspace에서 처리한다.
renderer에는 인증 profile과 network 접근을 주지 않고 정규화한 텍스트와 검증된 local 이미지 pointer만 전달한다.
HTML+Chromium 출력 대안을 선택해도 collector와 renderer의 OS 권한·profile은 분리하고 본문을 escape한다.

### 11.14 배포·검증·rollback 순서

1. 기존 source·설치 wheel·활성 설정·실행 프로세스의 버전을 구분해 inventory를 작성한다.
2. 새 protocol, owner adapter, Web authorization과 manual lifecycle을 synthetic fixture로 검증한다.
3. 전용 UID·그룹·runtime 디렉터리·root-owned release·고정 unit을 준비하고 초기 capability는 비활성으로 둔다.
4. 외부 공개 없이 private display와 UDS 전체 연결을 확인한다.
5. 같은 host의 renderer·Codex worker UID로 profile, Xauthority, VNC UDS, gateway UDS 접근 거부를 확인한다.
6. Caddy·Web 변경을 compatible release set으로 설치하고 제한된 operator와 한 channel로 pilot한다.
7. 실제 수집·사진 회수·중복 처리·로그인 재진입·문서 완료를 확인한 뒤 주기 실행을 활성화한다.

저장소의 `install_public_handover.sh`는 초기 Caddy admin 이전을 포함한 설치기다.
매번 그대로 실행해야 한다고 가정하지 말고 현재 보호된 drop-in과 설치·rollback 경계를 재사용한다.
운영 Caddyfile은 `/etc/caddy/Caddyfile`이며 repo의 설정 파일 변경만으로 운영에 적용되지는 않는다.
기존 Unix socket ExecReload를 유지한 `systemctl reload caddy`가 일반 설정 변경 경로다.

Caddy의 supplementary group을 최초 추가하면 이미 실행 중인 프로세스의 그룹은 reload로 바뀌지 않는다.
이 경우 계획된 서비스 restart가 필요하며 해당 변경과 영향 범위를 배포 절차에 명시한다.
`/run/caddy-admin`의0700이나 admin socket 권한을 낮춰 이 문제를 해결하지 않는다.
repo 문맥에 기록된 systemd daemon-reload와 실행 pin 영향도 확인하고 활성 native 작업과 조율한다.
새 기능을 설치하기 위해 무관한 GPU·QUERY·Codex 실행 전체를 임의로 재시작하지 않는다.

| 검증 대상 | 실제 기대 결과 |
| --- | --- |
| 기존 공개 경로 | `/`는308, `/studio`와 로그인은 기존 동작, 무관한 경로는404 |
| 내부 authorization route 외부 호출 |404 |
| 원격 HTML·정적 파일·WS에 session 없음 |401 또는 정의된 명확한 거부 |
| ADMIN 또는 remote permission 한쪽만 있음, 다른 connector scope, 타인 lease |거부 |
| 잘못된·없는 WS Origin |거부 |
| 정적 자산 URL로 WS upgrade 또는 예상 밖 method |거부 |
| spoof한 operator·권한 header만 제출 |권한 획득 불가 |
| 유효 manual lease |iframe 자산과 실제 WSS 연결 정상 |
| WS 요청의 인증 subrequest |BFF scope.type이 http, auth204 후 실제 gateway101·RFB 양방향 연결 |
| logout·권한 철회·TTL 만료 |새 접속 거부와 기존 viewer 종료를 모두 관측 |
| host listener |추가 VNC/6080 TCP listener 없음, 기존 admin TCP2019 없음 |
| reboot·gateway crash·Web restart |socket mode 재현, stale lease 정리, 재인증 전 연결 불가 |
| profile 동시 사용 |자동·수동·직접 재시작 중 두 번째 owner 거부 |

rollback은 먼저 신규 수집 admission과 원격 lease 발급을 중지한다. 진행 중 결과의 local staging·publication 상태를 확인하고 gateway와 browser를 정상 종료한다.
검증한 이전 Caddyfile·Web/runtime release로 돌아가며 기존 Unix admin 보호를 유지한다.
이미 저장한 artifact·수집 이력·권한 감사 기록이나 profile을 배포 실패 정리라는 이유로 삭제하지 않는다.
additive DB schema와 새 기록이 생겼다면 호환 rollback 범위를 정하고 무조건 down migration하지 않는다.
브라우저 버전 변경은 profile 호환성에 영향을 줄 수 있으므로 살아 있는 profile 디렉터리를 덮어쓰지 않는다.

### 11.15 보조 대안의 경계

별도 `/admin/remote/*`와 Caddy basic_auth를 쓰는 구성은 제한된 bootstrap 대안일 뿐 기본 통합안이 아니다.
그 비밀번호는 Studio logout·역할 철회와 자동으로 연결되지 않는다는 차이를 명시해야 한다.
UDS가 설치 패키지에서 불가능할 때만 private network namespace 또는 검증된 TCP+backend 인증 대안을 검토한다.
127.0.0.1 bind만으로 같은 host의 untrusted renderer가 격리됐다고 보지 않는다.
unauthenticated VNC5901 또는 gateway6080을 열어 두는 fallback은 채택하지 않는다.

### 11.16 근거 링크

저장소 링크는 모두 검토한 commit에 고정했다. upstream 문서는 설치 release를 선택할 때 다시 대조한다.

- Runtime-R1: [기존 Caddyfile](https://github.com/teddyok1206/eomai/blob/6a824aa48967270cc116661813d3d734f2f16e4e/config/caddy/Caddyfile), [Caddy systemd drop-in](https://github.com/teddyok1206/eomai/blob/6a824aa48967270cc116661813d3d734f2f16e4e/config/systemd/caddy.service.d/eom-security.conf).
- Runtime-R2: [Web app 인증·cookie·CSP](https://github.com/teddyok1206/eomai/blob/6a824aa48967270cc116661813d3d734f2f16e4e/apps/web_gui/eom_web_gui/app.py), [SessionStore](https://github.com/teddyok1206/eomai/blob/6a824aa48967270cc116661813d3d734f2f16e4e/apps/web_gui/eom_web_gui/sessions.py).
- Runtime-R3: [Web settings](https://github.com/teddyok1206/eomai/blob/6a824aa48967270cc116661813d3d734f2f16e4e/apps/web_gui/eom_web_gui/settings.py), [HttpApplicationGateway](https://github.com/teddyok1206/eomai/blob/6a824aa48967270cc116661813d3d734f2f16e4e/apps/web_gui/eom_web_gui/gateways.py).
- Runtime-R4: [현재 API auth/account·me](https://github.com/teddyok1206/eomai/blob/6a824aa48967270cc116661813d3d734f2f16e4e/apps/application_api/eom_api/routers/auth.py), [Identity auth capture](https://github.com/teddyok1206/eomai/blob/6a824aa48967270cc116661813d3d734f2f16e4e/services/identity_service/eom_identity_service/auth_service.py).
- Runtime-R5: [Web systemd unit](https://github.com/teddyok1206/eomai/blob/6a824aa48967270cc116661813d3d734f2f16e4e/infra/systemd/eom-web-gui.service), [외부 수집 worker unit](https://github.com/teddyok1206/eomai/blob/6a824aa48967270cc116661813d3d734f2f16e4e/infra/systemd/eom-image-reference-acquirer%40.service).
- Runtime-R6: [fixed-unit polkit 경계](https://github.com/teddyok1206/eomai/blob/6a824aa48967270cc116661813d3d734f2f16e4e/infra/polkit/50-eom-worker-units.rules), [ADR0032](https://github.com/teddyok1206/eomai/blob/6a824aa48967270cc116661813d3d734f2f16e4e/docs/adr/0032-fixed-template-systemd-worker-launcher.md).
- Runtime-R7: [Web package-data](https://github.com/teddyok1206/eomai/blob/6a824aa48967270cc116661813d3d734f2f16e4e/apps/web_gui/pyproject.toml), [Web release inventory](https://github.com/teddyok1206/eomai/blob/6a824aa48967270cc116661813d3d734f2f16e4e/apps/web_gui/eom_web_gui/release_integrity.py).
- Runtime-R8: [Caddy 설치·검증·rollback](https://github.com/teddyok1206/eomai/blob/6a824aa48967270cc116661813d3d734f2f16e4e/scripts/web_gui/install_public_handover.sh), [public handover runbook](https://github.com/teddyok1206/eomai/blob/6a824aa48967270cc116661813d3d734f2f16e4e/docs/operations/SCIENTIFIC_STUDIO_PUBLIC_HANDOVER.md).
- Runtime-R9: [개발·운영 문맥](https://github.com/teddyok1206/eomai/blob/6a824aa48967270cc116661813d3d734f2f16e4e/docs/agent-context/development-operations.md), [AGENTS 규칙](https://github.com/teddyok1206/eomai/blob/6a824aa48967270cc116661813d3d734f2f16e4e/AGENTS.md).
- Runtime-R10: [전용 Codex bwrap AppArmor 규칙](https://github.com/teddyok1206/eomai/blob/6a824aa48967270cc116661813d3d734f2f16e4e/infra/apparmor/eom-codex-bwrap), [worker runtime 배포](https://github.com/teddyok1206/eomai/blob/6a824aa48967270cc116661813d3d734f2f16e4e/scripts/workflow/deploy_worker_runtime.sh).
- Runtime-R11: [UDS peer UID 검증의 기존 사례](https://github.com/teddyok1206/eomai/blob/6a824aa48967270cc116661813d3d734f2f16e4e/services/orchestrator/eom_orchestrator/codex_auth_broker_server.py).
- Runtime-R12: [Caddy 회귀 테스트](https://github.com/teddyok1206/eomai/blob/6a824aa48967270cc116661813d3d734f2f16e4e/tests/web_gui/test_caddy_public_handover.py).
- Runtime-R13: [VisualReferenceAcquisitionCoordinator](https://github.com/teddyok1206/eomai/blob/6a824aa48967270cc116661813d3d734f2f16e4e/services/orchestrator/eom_orchestrator/visual_reference_acquisition.py).
- Runtime-U1: [Caddy forward_auth](https://caddyserver.com/docs/caddyfile/directives/forward_auth), [route 순서](https://caddyserver.com/docs/caddyfile/directives/route), [uri 변환](https://caddyserver.com/docs/caddyfile/directives/uri).
- Runtime-U2: [Caddy matchers와 WebSocket 예시](https://caddyserver.com/docs/caddyfile/matchers), [reverse_proxy와 Unix socket](https://caddyserver.com/docs/caddyfile/directives/reverse_proxy), [request_header](https://caddyserver.com/docs/caddyfile/directives/request_header).
- Runtime-U3: [TigerVNC Xvnc 공식 옵션](https://tigervnc.org/doc/Xvnc.html), [X server의 auth·nolisten](https://xorg.freedesktop.org/archive/X11R7.5/doc/man/man1/Xserver.1.html).
- Runtime-U4: [websockify parser와 UDS 구현](https://github.com/novnc/websockify/blob/master/websockify/websocketproxy.py), [upstream auth plugins](https://github.com/novnc/websockify/blob/master/websockify/auth_plugins.py).
- Runtime-U5: [noVNC embedding](https://github.com/novnc/noVNC/blob/master/docs/EMBEDDING.md), [RFB API](https://github.com/novnc/noVNC/blob/master/docs/API.md).
- Runtime-U6: [Playwright persistent context·profile·Chromium sandbox](https://playwright.dev/python/docs/api/class-browsertype#browser-type-launch-persistent-context), [systemd 실행 격리 옵션](https://www.freedesktop.org/software/systemd/man/latest/systemd.exec.html).
- Runtime-U7: [Chrome의 background page timer 제한](https://developer.chrome.com/blog/timer-throttling-in-chrome-88).
- Runtime-U8: [Uvicorn의 WebSocket scope 전환](https://uvicorn.dev/concepts/websockets/), [h11 구현의 upgrade 판정](https://github.com/Kludex/uvicorn/blob/main/uvicorn/protocols/http/h11_impl.py). Caddy와 Uvicorn을 실제 결합한 동작은 설치 release에서 검증한다.

---

<a id="section-12"></a>

## 12. 구현 파일·계약·배포 산출물

### 12.1 backend 신규 모듈 제안

아래는 책임을 구분하기 위한 파일 배치안이다. 현재 존재한다고 주장하는 목록이 아니다. 작은 순수 함수는 불필요하게 service class로 만들지 않는다.

| 신규 경로 | 책임 |
|---|---|
| `packages/catalog_contracts/eom_catalog_contracts/kakao_archive.py` | binding·room·snapshot·question·packet 및 Catalog IPC 계약 |
| `packages/catalog_contracts/eom_catalog_contracts/kakao_question_report.py` | export plan/result·layout policy·manifest |
| `schemas/kakao-archive/*.schema.json` | 기능 계약의 canonical JSON Schema |
| `packages/catalog_contracts/eom_catalog_contracts/resources/kakao-archive/` | Catalog에서 필요한 schema mirror |
| `services/catalog_service/eom_catalog_service/kakao_archive_models.py` | Catalog 소유 ORM 모델 |
| `.../kakao_archive_authorization.py` | 현재 operator·binding·source·revision 권한 |
| `.../kakao_archive_service.py` | binding·수집 명령·상태 query의 application use case |
| `.../kakao_archive_coordinator.py` | domain run/task claim·checkpoint·재개 |
| `.../kakao_archive_intake.py` | local capture 결과 수락·Artifact 발행·projection 연결 |
| `.../kakao_csv_parser.py` | 원본 bytes의 strict parse·정규화 receipt |
| `.../kakao_message_alignment.py` | 순수 sequence 정합·불확실성 표현 |
| `.../kakao_question_rules.py` | 순수 후보 규칙·기간 선택·수동 편집 검증 |
| `.../kakao_question_service.py` | question revision·split/merge·student mapping |
| `.../kakao_question_report_service.py` | packet·학생 subset·export·결과 검증 |
| `.../kakao_archive_dispatch.py` | 기능별 typed Catalog IPC dispatch |
| `services/orchestrator/eom_orchestrator/kakao_runtime_adapter.py` | 고정 browser/remote/renderer 실행과 로컬 결과 검증 |
| `services/orchestrator/eom_orchestrator/kakao_runtime_reconcile.py` | unit·profile lock·fence·lease 잔여 상태 정합 |
| `services/kakao_archive_worker/eom_kakao_archive_worker/cli.py` | 제한된 worker command 진입점 |
| `.../browser_runtime.py` | Playwright context·profile·AUTO/MANUAL 실행 |
| `.../channel_adapter.py` | 관측·검증한 실제 카카오 DOM 동작 |
| `.../capture_output.py` | worker local 결과 manifest 생성 |
| `.../question_pdf.py` | local PyMuPDF 조판 및 receipt |
| `.../remote_gateway_lifetime.py` | 승인된 lease 기한으로 gateway 종료를 보장하는 좁은 보조 실행 |

`.../`는 직전 명시한 package 디렉터리 기준이다. 이 표를 기준으로 모든 파일을 빈 class로 미리 만드는 작업은 하지 않는다. 실제 두 책임이 작고 함께 바뀌면 한 모듈에서 시작할 수 있다.

### 12.2 worker 계약의 설치 경계

worker는 Catalog 서비스 전체를 import해서 실행하지 않는다. browser와 PDF worker가 공유하는 입력·결과 계약은 DB·NAS·FastAPI에 의존하지 않아야 한다.

**설계 결정:** 신규 `packages/kakao_archive_contracts/eom_kakao_archive_contracts/`에 worker I/O만 가진 작은 pure contract package를 둔다. 기존 `image_contracts`와 같은 명시적 배포 경계의 선례를 따른다. Catalog의 업무 DTO와 public API DTO는 각 기존 package에 남는다.

| pure worker 계약 | 포함할 내용 |
|---|---|
| `CaptureCommand` | command/task/attempt ID, source binding ID, fence, allowed operation, 한도, capability revision |
| `CaptureResult` | 동일 command identity, 관측 범위, local members, hash, 상태·수량, 오류 |
| `RenderCommand` | export/packet/subset identity, manifest hash, local member 목록, layout/font pin |
| `RenderResult` | 입력 pin, PDF/preview/receipt local members, 페이지 수, 검증 상태 |

local member는 `relative_path + sha256 + size_bytes + media_type`로 표현한다. worker가 임의 NAS pointer를 dereference하지 않는다. full ArtifactMemberPointer의 resolution은 Catalog/Orchestrator가 맡고 worker에는 materialized 입력만 전달한다.

카카오 도메인·Catalog IPC·worker I/O의 canonical schema는 `schemas/kakao-archive/` 한 곳에 둔다. 공개 API envelope/DTO 계약은 기존 규칙에 따라 `schemas/api/v1/`에 둔다. 서로 다른 계층의 계약임을 구분하고 동일 계약에 두 정본을 만들지 않는다. worker용 package resource에는 worker I/O subset만 동일 바이트로 포함하고, 기존 mirror audit에 이 대응을 추가한다. 동일 계약을 별도 손작성 사본으로 갈라지게 하지 않는다.

pure package, isolated worker wheel, 기존 core distribution의 설치 dependency closure를 명시한다. 저장소에 없는 distribution 이름을 이미 설치된 package처럼 `pip install`하도록 문서화하지 않는다. 새 wheel metadata와 고정 build hash를 구현의 일부로 만든다.

### 12.3 기존 composition 변경 지점

- Catalog `application_runner.py`: feature service·coordinator 구성, 설정 비활성 기본값.
- Catalog `application_server.py`: 신규 typed dispatch와 허용 peer/operation 규칙.
- API `catalog_application_client.py`: 신규 command/query와 identity·response 검증.
- `migrations/env.py`: 새 ORM metadata 등록.
- `catalog_contracts/validation.py`: 신규 schema resource 등록.
- 루트 및 신규 package `pyproject.toml`: package/module/resource·의존성 이유.
- `operator_identity/contracts.py` 및 새 migration: 권한 enum·DB seed.
- Web `release_integrity.py`: 신규 runtime 파일.
- OpenAPI JSON·SHA, canonical schema mirror·contract audit.
- 기존 deployment/readiness의 지원 migration head와 source pin.
- `infra/systemd/`, `infra/polkit/`, 보호된 배포 helper: 고정 runtime unit·UID·그룹·경로.

현재 소스에 없는 generic workflow type을 추가하면 별도 immutable protocol·DB check·consumer release 변경이 필요하다. 첫 버전의 좁은 Catalog coordinator를 위해 WorkflowRunner 전역 application step 제약을 느슨하게 풀지 않는다.

### 12.4 신규 의존성과 이유

| 구성요소 | 이유 | 범위 |
|---|---|---|
| Playwright Python | 동적 관리자 UI·다운로드·persistent browser 자동화 | collector 전용 Conda |
| pin된 Chromium | 같은 browser 동작과 profile 호환성 | collector runtime |
| TigerVNC Xvnc | 모니터 없는 서버의 가상 화면·원격 인증 | 전용 browser unit |
| websockify | noVNC의 WebSocket을 private VNC UDS로 전달 | gateway 전용 환경 |
| noVNC | Studio 안의 browser remote viewer | 고정 read-only release |
| PyMuPDF | 질문 한 페이지 조판·PDF 검증·PNG preview | 기존 의존성을 맞춘 offline renderer |
| 한글 font 파일 | 실제 글꼴·기호·배치 재현 | 고정 hash와 사용 조건을 확인한 font set |

Kakao 기능을 위해 API·Web·GPU worker 환경 전체에 browser 패키지를 설치하지 않는다. browser binary 업데이트와 profile migration은 application wheel 업데이트와 구분하여 검증한다.

버전 숫자는 구현 시 배포 환경에서 선택·pin하고 manifest에 기록한다. “latest” URL을 실행 시마다 내려받아 운영하지 않는다.

---

<a id="section-13"></a>

## 13. 구현 순서와 단계별 완료 증거

### 13.1 작업 순서

| 단계 | 작업 | 완료 증거 |
|---|---|---|
| P0 | 현재 HEAD·설치 release·환경·기존 owner 확인 | 기준표, 실제 경로, migration head, 보호 경계 |
| P1 | schema·pure rules·DB 모델·Artifact 수락 | 익명 CSV/이미지 fixture로 원본→projection→question revision |
| P2 | Studio view·API/BFF·권한·binding bootstrap | 세션·CSRF·scope·CAS·download 실제 연결 |
| P3 | private runtime·원격 수동 인증 | UDS, 단일 profile lock, 유효 lease 접속과 철회 |
| P4 | 한 방의 실제 export·사진 실증 | capability receipt, 원문/사진 수동 대조, 정확한 연결 |
| P5 | 전체 방 inventory·반복 수집·복구 | 누락 없는 observed scope, 실패 복구·중복 방지 |
| P6 | 학생·질문 검토·packet·학생별 PDF | 한 질문 한 페이지, 모든 필수 사진, 검토 가능한 preview |
| P7 | 정기 실행·관측·백업·release | 두 번 이상 반복 실행, 재시작·재인증·rollback 검증 |

P1의 fixture 구현과 P2의 화면·계약 작업은 병행할 수 있다. 카카오 추가 인증이 필요한 P3/P4만 사람의 실제 인증 동작이 필요하다. 이를 이유로 계약·저장·질문 편집·PDF 구현 전체를 대기시키지 않는다.

P4가 실패했을 때는 확보 가능한 CSV importer와 검토·PDF 기능을 유지할 수 있으나, 그것만으로 “주기적 전체 방·사진 자동 수집 완료”라고 보고하지 않는다.

### 13.2 세부 작업과 의존 관계

| 작업 ID | 결과물 | 선행 |
|---|---|---|
| W01 | 현재 architecture inventory와 짧은 ADR | 없음 |
| W02 | 기능·worker schema, ID·state·error 정의 | W01 |
| W03 | additive migration, domain aggregate, ACL, index | W02 |
| W04 | Artifact intake·pointer resolution·recovery | W02, W03 |
| W05 | CSV parser·sequence matching·attachment receipt | W02, W04 |
| W06 | UI/API·binding 설정·학생 mapping | W02, W03 |
| W07 | virtual display·browser·manual lease·Caddy 분기 | W02, W06 |
| W08 | 실제 UI adapter·한 방 실증 | W05, W07 |
| W09 | 전체 inventory·task coordinator·scheduler | W03, W08 |
| W10 | 질문 규칙·수동 편집·revision 충돌 처리 | W05, W06 |
| W11 | packet·학생별 renderer·preview·download | W04, W10 |
| W12 | recovery·권한 철회·실운영 pilot·release record | W07, W09, W11 |

각 작업의 PR 또는 변경 설명에는 문제, 변경 책임, 실제 resulting behavior, 실행한 검증과 남은 제한을 적는다. 전체 feature branch가 크면 protocol→storage→runtime→UI→collector→renderer로 검토 가능한 변경 단위로 나눈다. 필수 경계를 구현하지 않은 상태에서 feature flag를 켜지 않는다.

### 13.3 Codex가 먼저 확인할 read-only 항목

운영 세션의 기존 도구·권한 범위에서 다음을 확인한다. 비밀값을 출력하거나 환경 파일 전체를 덤프하지 않는다.

~~~text
현재 Git HEAD와 작업 트리의 사용자 변경
기존 AGENTS.md와 관련 agent-context
Caddy 실제 unit·drop-in·ExecReload와 version
실제로 읽는 /etc/caddy/Caddyfile의 비밀 없는 route
Web/API/Catalog/Runner의 실행 identity·설치 wheel/release pin
PostgreSQL 현재 migration revision과 새 기능 배포 호환 범위
NAS 실제 mount option과 trusted management group
새 UID·UDS·profile·workspace를 둘 수 있는 디스크/권한
Xvnc/websockify 지원 옵션과 Chromium sandbox 실행 가능 여부
현재 돌아가는 장시간 작업과 systemd 변경의 영향
~~~

이 설계 작성에서는 실제 운영 호스트에 이 검사를 수행하지 않았다. `caddy.service` 실행 사실과 Caddy version은 사용자가 제공한 정보다. 그 외 운영 정보는 저장소 설정과 구분하여 실측한다.

### 13.4 배포 산출물

- canonical schema 및 hash, frozen DTO, schema mirror.
- migration과 RBAC seed.
- 설치 가능한 core/Web/API 및 worker wheel, 고정 dependency lock.
- 보호된 runtime unit과 좁은 polkit 변경.
- noVNC·websockify·Chromium·font release 기록.
- feature-disabled 기본 설정.
- 기존 방식으로 검증한 Caddyfile와 rollback copy.
- 익명 test fixture, 수용 테스트 결과.
- 실제 한 방·전체 scope pilot receipt.
- UI·운영 runbook·개발 context index 갱신.

`/home/eom/EOMIS`는 변경하지 않는다. 운영 프로세스가 개발 checkout을 읽도록 `PYTHONPATH`를 임시 추가하는 방식으로 배포하지 않는다.

---

<a id="section-14"></a>

## 14. 테스트와 수용 기준

### 14.1 테스트 계층

| 계층 | 확인할 것 | 외부 계정 필요 |
|---|---|---|
| 순수 unit | CSV, timezone, 정합, 질문 규칙, 날짜 정책, manifest | 없음 |
| protocol | schema/Pydantic/mirror, unknown field, pin/hash 검증 | 없음 |
| DB integration | unique·FK·CAS·claim·lease·idempotency·migration | disposable PostgreSQL |
| Artifact integration | staged file·NAS publication recovery·pointer read | 격리된 테스트 storage |
| Web/API | 인증·CSRF·권한·scope·ETag·bounded download | 없음 |
| renderer | 한글·복수 사진·overflow·page mapping | 고정 local fixture |
| runtime privileged | UID·UDS·unit·profile lock·sandbox | 격리된 Linux 시험 환경 |
| Kakao live | 목록 범위·실제 CSV·사진·재인증 | 허용된 실제 계정, 명시적 live test |

저장소의 guarded disposable DB 절차를 사용한다. 기존 `scripts/api/testdb_prepare.sh`, `testdb_run.sh`, 정리 절차를 확인하고 필요한 목적을 추가한다. `testdb_run.sh`는 임의 pytest 인자를 받아 주는 범용 wrapper가 아니므로, 존재하지 않는 `kakao-tests` 인자를 이미 지원한다고 가정하지 않는다.

운영 DB에 test fixture를 넣거나, root DB 권한으로 테스트가 성공하도록 우회하지 않는다.

### 14.2 원본·정합 필수 사례

| ID | 입력·상황 | 기대 결과 |
|---|---|---|
| C01 | BOM·쉼표·따옴표·여러 줄 MESSAGE | 원문 손실 없는 parse |
| C02 | invalid encoding | 명시적 오류, replacement 문자로 성공 금지 |
| C03 | 새 column·필수 column 누락 | schema observation 또는 오류 |
| C04 | 같은 초·같은 sender·같은 text 두 번 | 두 occurrence 유지 |
| C05 | 같은 CSV 반복 수집 | 관측은 추가, canonical 표시 중복 없음 |
| C06 | 일부만 포함한 후속 CSV | 이전 메시지를 삭제로 판단하지 않음 |
| C07 | 불명확한 동일 사진 marker 연속 | 강제 매칭 없이 unresolved |
| C08 | 사진 한 bubble에 여러 이미지 | 실제 개수·순서 모두 기록 |
| C09 | 같은 사진을 다른 메시지에서 재전송 | blob 재사용, occurrence 둘 유지 |
| C10 | 같은 다운로드 파일명, 다른 바이트 | 별도 blob, 잘못된 연결 없음 |
| C11 | HTML 로그인 응답을 JPG로 받음 | image download 실패 |
| C12 | 만료 URL 후 새 viewer 링크 | 정상 재획득 또는 정확한 expired/auth 구분 |
| C13 | timezone 미확정 월 경계 | 날짜 결과 미확정, 확정값 위조 금지 |
| C14 | 방 목록 virtualized/reordered | 중복 없이 inventory, 미확정 종료는 partial |
| C15 | 담당자·라벨 filter 남음 | 초기화 확인 또는 scope incomplete |
| C16 | 동일 학생 이름 두 방·서로 다른 사람 | 자동 student merge 없음 |
| C17 | 재수집 중 늦게 도착한 worker | fence 불일치 결과 수락 거부 |
| C18 | 삭제된 메시지 관측 | 원본 history 보존, 새 질문 검토 상태 반영 |

fixture는 원본 샘플의 구조를 재현하되 실제 이름·전화번호·학원·학교·메시지·사진을 공개 Git에 넣지 않는다. 무작위 placeholder만 넣어 중요한 줄바꿈·동일 시각·복수 사진 조건이 사라지지 않게 한다.

### 14.3 질문·기간·PDF 필수 사례

| ID | 입력·상황 | 기대 결과 |
|---|---|---|
| Q01 | 학생 연속 글+사진 후 관리자 답변 | 학생 turn 후보와 reply context 분리 |
| Q02 | 여러 날 뒤 관리자 답변 | 임의 24시간 split 없음 |
| Q03 | 월말 학생 질문·다음 달 답변 | 첫 학생 시각 정책으로 올바른 월 선택 |
| Q04 | 한 글에 질문 둘 | 수동 text span split 및 provenance |
| Q05 | 첫 메시지를 제외 | 새 revision에서 기간 귀속 재계산 |
| Q06 | 사람이 편집한 뒤 새 snapshot | 수동 결정 보존, 충돌 검토 |
| Q07 | 미확보 사진이 있는 질문 | required set 유지, FINAL blocker |
| Q08 | 같은 packet, 서로 다른 학생 | 다른 subset/build key/PDF |
| Q09 | 같은 입력의 DRAFT와 FINAL | 서로 바꾸어 cache hit하지 않음 |
| Q10 | 한글·그리스 문자·기호·긴 글 | glyph·bounds 검증 |
| Q11 | 세로로 긴 사진·30장 같은 큰 묶음 | 불가능하면 layout review, 누락 성공 금지 |
| Q12 | 사진 회전·수동 crop | 원본 보존, transform pin |
| Q13 | PDF 10페이지지만 마지막 본문 잘림 | page count만으로 통과하지 않음 |
| Q14 | 원본 해상도 부족 | 품질 상태·검토 결정 표시 |
| Q15 | 늦게 사진 원본 확보 | 기존 PDF 불변, 새 revision/export |
| Q16 | 학생별 export 일부 실패·미접수 | 개별 상태, 전체 성공 표시 금지 |

### 14.4 인증·원격·경계 필수 사례

- 무인증 HTTP와 WS, CSRF 없는 mutation 거부.
- 권한 없는 Studio 사용자, 타인 binding, 다른 session lease 거부.
- arbitrary actor·role·session·NAS path·CDP URL 입력 거부.
- WebSession raw cookie·API bearer를 DB/로그/worker 입력에 남기지 않음.
- grant 또는 operator 상태 변경 후 preview·build·cache hit·download 재검증.
- 잘못된 Origin, 정적 경로를 통한 WS upgrade, 임의 upstream 선택 거부.
- 로그아웃·권한 철회·TTL 만료 후 이미 연결된 viewer도 종료.
- websockify listener만 닫고 child WS가 남는 경우 실패로 판정.
- 다른 renderer/worker UID의 profile·Xauthority·UDS·NAS 읽기 거부.
- AUTO와 MANUAL이 동시에 같은 profile을 제어하지 않음.
- 브라우저 crash 후 살아 있는 lock을 지워 이중 실행하지 않음.
- direct generic Artifact download를 통한 private 자료 접근 우회 없음.
- 공개 경로의 `/` redirect, 기존 `/studio`, 마지막 404와 Caddy Unix admin 유지.
- noVNC의 framing 허용이 Studio 전체 CSP를 약화시키지 않음.
- 카카오 수집에서 customer-support/general-chat/material-learning/embedding/Graph 호출 없음.

### 14.5 복구 필수 사례

각 중단 지점에서 재개 시 중복·누락·권한 확대가 없어야 한다.

~~~text
다운로드 도중 종료
다운로드 완료 후 result manifest 작성 전 종료
manifest 완료 후 core 수락 전 종료
Artifact staging 도중 종료
NAS 발행 후 DB Artifact record 갱신 전 종료
Artifact 발행 후 domain snapshot 연결 전 종료
question manifest 발행 후 current revision CAS 실패
PDF 렌더 완료 후 export acceptance 전 종료
Web restart로 session store 소실
gateway 종료 실패 또는 TTL watchdog 재시작
서버 reboot 후 /run 디렉터리·socket 재생성
권한 철회와 결과 commit이 경합
~~~

기존 Catalog Artifact commit recovery와 pinned pointer 테스트에 새 기능 사례를 추가한다. 이미 검증된 공통 알고리즘을 새롭게 복제해 테스트만 비슷하게 만드는 방식은 피한다.

### 14.6 최종 수용 체크

완료 보고에는 아래 증거가 있어야 한다.

1. 실제 한 방의 CSV·사진을 사람이 대조한 결과.
2. 검증한 목록 scope와 “전체”의 정의.
3. 같은 입력 재실행 시 중복 표시가 증가하지 않는 결과.
4. 인증 만료 후 안전한 pause와 동일 run 재개.
5. 학생 한 명의 여러 질문이 질문 수와 같은 PDF 페이지로 생성된 결과.
6. 원문·사진·페이지의 누락/잘림 검사 결과와 대표 preview.
7. 다른 사용자의 데이터 및 원격 화면 접근 거부 결과.
8. 원문·세션이 AI/Graph·공개 static·표준 log로 흐르지 않는 결과.
9. 설치 artifact·migration·release pin과 운영에 실제 적용한 범위.
10. 아직 미확정인 UI capability·사진 범위·운영 한계.

UI만 동작하거나 API가202를 반환하는 것은 전체 완료 증거가 아니다.

---

<a id="section-15"></a>

## 15. 용량·성능·운영

### 15.1 실제 측정 후 조정할 항목

실제 방 수·메시지 수·사진 크기는 조사하지 않았다. 아래는 산정식이며 운영 규모의 주장으로 읽지 않는다.

~~~text
한 회차 시간
≈ 목록 조사 시간
 + 모든 방의 (열기 + CSV export + 첨부 탐색 + 새 파일 다운로드) 시간

새 canonical 사진 증가량
≈ 새 고유 사진 수 × 평균 파일 크기

snapshot 저장 증가량
≈ 변경된 CSV 원본 + normalization/receipt + 관측 metadata

PDF 생성 비용
≈ 선택 본문 길이 + 선택 사진 decode 바이트 + 출력 페이지 수
~~~

초기 pilot에서 방당 median/p95 시간, 다운로드 수·바이트, memory peak, PDF 페이지당 시간, NAS commit 시간을 측정한다. 이 값으로 주기와 한도를 선택한다.

첫 전체 이력 수집과 반복 수집은 부하가 다르다. 한 회차가 주기보다 오래 걸리면 다음 회차를 중첩시키지 않고 coalesce한다. 기존 Studio/GPU/문서 작업의 자원을 침범하지 않도록 새 unit의 CPU·memory·I/O 한도를 실측한다.

### 15.2 보수적인 초기 실행 정책

- 하나의 browser가 한 방씩 처리.
- 사진 다운로드도 처음에는 직렬 처리.
- 반복된 오류 또는 제한 응답에서는 binding 전체 속도를 낮춤.
- active download·render의 byte/pixel/time 한도 설정.
- CSV parse·message 목록·preview 모두 bounded request.
- 이미지 목록은 lazy loading, 무제한 thumbnail 동시 요청 금지.
- raw CSV와 normalization은 동일 byte+parser version이면 재사용 가능한지 확인.
- domain snapshot 관측 기록은 byte 재사용과 관계없이 보존.
- 디스크 부족 시 새 다운로드를 멈추고 이미 받은 결과는 복구 가능한 상태로 유지.

같은 immutable 파일을 조회할 때마다 여러 번 전체 hash 계산하지 않도록 기존 validated read context를 재사용한다. 신뢰 경계에서 필요한 hash 검증을 성능 이유로 제거하지 않는다.

### 15.3 운영 화면과 runbook

운영자는 최소한 다음을 할 수 있어야 한다.

| 운영 동작 | 기대 결과 |
|---|---|
| 수집 실행 | durable run 생성 및 상태 링크 |
| 자동 수집 비활성 | 새 schedule admission만 중지 |
| 현재 작업 일시 정지 | checkpoint에서 pause |
| 인증 화면 열기 | 해당 세션의 짧은 manual lease |
| 인증 확인·재개 | 실제 채널 확인 후 AUTO 복귀 |
| 실패 방/사진 재시도 | 대상만 새 attempt |
| 누락 목록 보기 | 원인·재시도 가능 여부·관측 근거 |
| 질문 검토 | 학생·경계·사진·표시 교정 |
| PDF 생성 | 학생별 export 상태와 immutable 결과 |
| 로그/오류 조사 | request/task ID로 제한된 diagnostic 조회 |

자동 수집이 멈춘 경우 기본 조사 순서:

1. source session·channel 일치 여부.
2. 최근 run의 inventory/room/attachment 오류 코드.
3. runtime unit과 active fence/profile lock.
4. local workspace와 디스크 여유.
5. NAS publication 상태와 기존 recovery receipt.
6. adapter·capability·release 변경 여부.

비밀번호·cookie가 포함될 수 있는 전체 HAR·trace·profile을 일상 diagnostic bundle에 넣지 않는다. 필요한 민감 evidence는 범위·보존·접근을 명시해 별도 관리한다.

### 15.4 초기값과 후속 결정

| 사항 | 첫 구현 방향 | 나중에 바꿀 근거 |
|---|---|---|
| 채널 수 | 1 binding | 실제 복수 채널 요구 |
| 권한 | owner-only + 기능 permission; 원격은 ADMIN 추가 | 명시적 팀 공유 필요 |
| 반복 주기 | 기본 비활성, 활성화 시24시간 제안 | 수집 소요·신규 사진 빈도 |
| 전체 방 CSV | 매 회차 수행 | 완전성을 입증한 변경 감지 전략 |
| 메시지 ID | 관측한 source ID 우선 | 실증 실패 시 snapshot-only 유지 |
| 질문 구분 | turn_v1 + 사람 검토 | versioned 규칙 개선 |
| 출력 | 학생별 PDF | ZIP/합본/HWPX 요구 |
| renderer | PyMuPDF | 실제 한글·조판 한계 실증 |
| 원격 화면 | manual lease에서만 활성 | 별도 안전한 관찰 기능 요구 |
| 자동 발행 | 기본 비활성, DRAFT 자동화는 가능 | 검토 방식·품질 기준 확정 |
| 보존·purge | 논리 retirement, 자동 물리삭제 비활성 | 기존 Artifact lifecycle과 통합 설계 |

이 표는 구현 담당자가 진행할 수 있도록 정한 초기 방향이다. 모든 항목을 사용자에게 다시 질문하고 구현을 멈추라는 목록이 아니다. 실계정 인증과 운영 환경 실측이 필요한 지점만 구분하여 진행한다.

---

<a id="section-16"></a>

## 16. 설계 결정 기록

| 결정 | 선택 이유 | 검토한 더 단순한 대안과 한계 |
|---|---|---|
| 웹 UI 자동화 | 일반 채널 과거 내역 공개 API 부재, 기존 export 사용 가능성 | 공개 API만 사용하면 현재 요구를 충족하지 못함 |
| CSV+별도 사진 관측 | 샘플 CSV에 사진 ID/파일명 없음 | 파일명 join은 근거 없는 연결 |
| snapshot 우선 | 안정적 source ID가 없어도 원본을 보존 가능 | 날짜·내용 hash dedup는 실제 중복 발화를 잃음 |
| 기존 Catalog/Orchestrator | 저장소의 권한·Artifact·배포 구조와 일치 | 독립 SQLite/NAS writer는 두 정본과 복구 경계를 만듦 |
| source별 권한 | 학생 원문은 일반 Item 열람 권한과 다름 | 기존 item:read 재사용은 과도한 접근 |
| 별도 browser UID | 인증 profile과 외부 페이지 격리 | Web process 안의 browser는 자격·파일 경계를 섞음 |
| private UDS 원격 경로 | 같은 host의 untrusted renderer가 존재 | loopback VNC만으로는 접근 격리가 안 됨 |
| 현재 세션+manual lease | 인증 만료·철회와 실제 WS 종료 연결 | handshake auth만으로 열린 연결은 끝나지 않음 |
| turn 기반 후보+검토 | AI 없이 추적 가능한 결과 | 의미 기반 완전 자동 분류는 근거 없음 |
| pin된 packet | 반복 출력과 감사 가능 | “현재 기간 검색” 저장은 나중에 결과가 바뀜 |
| 학생별 export | 사용자 요구와 단일 PDF API 정합 | 다학생 PDF를 하나의 캐시 key로 만들면 혼동 |
| PyMuPDF local renderer | 기존 의존성, 정확한 page/bounds 제어 | 기존 HWPX에 가짜 Item 입력은 모델 의미 왜곡 |
| overflow 검토 | 한 페이지와 가독성을 동시에 유지 | silent crop·초소형 축소는 자료를 훼손 |

---

<a id="section-17"></a>

## 17. 구현 세션에 붙여 넣을 지시문

아래 지시문과 이 Markdown 파일을 함께 전달한다.

~~~text
첨부한 KAKAO_CHANNEL_ARCHIVE_STUDIO_IMPLEMENTATION_SPEC.md를 기준으로
현재 EOM Scientific Studio에 카카오 채널 학생 질문 기능을 구현해 주세요.

이 문서는 https://github.com/teddyok1206/eomai 의
6a824aa48967270cc116661813d3d734f2f16e4e 커밋을 조사한 설계입니다.
먼저 현재 HEAD, AGENTS.md, 관련 agent-context, 설치된 release와의 차이를
확인하고 현재 코드의 실제 owner 및 배포 경계를 우선해 통합해 주세요.

목표:
- 관리자/매니저 계정으로 접근 가능한 모든 채팅방의 CSV와 사진 수집.
- 무인 Linux에서 주기 실행, 인증 만료 시 Studio 안의 제한된 원격 화면.
- 원본 보존, 학생 연결, 결정론적 질문 후보와 수동 분할/병합/제외.
- 기간별 질문을 학생마다 PDF로 생성하고 한 질문당 한 페이지 유지.
- 런타임 LLM/OCR/embedding/AI 호출 없음.

반드시 지킬 구조:
- 기존 static ES module + FastAPI BFF + Application API + Catalog +
  Orchestrator + PostgreSQL + NAS Artifact를 확장.
- worker는 local staged input/result만 사용하고 DB/NAS에 직접 접근하지 않음.
- publication Job과 capture 실행 attempt를 구별.
- 기존 immutable schema, Job enum, WorkflowRunner 제약을 임의로 완화하지 않음.
- student/room/message identity를 이름이나 timestamp/text hash만으로 만들지 않음.
- 사진은 다운로드 당시 메시지/album occurrence와 연결하고 파일명 join 금지.
- source ID가 없으면 snapshot-only fallback과 불확실성을 유지.
- 신규 source 권한과 object scope, 현재 권한 재확인.
- Item/GraphRAG/material-learning/customer-support AI 경로에 자동 등록하지 않음.
- existing /studio prefix, HSTS, root redirect, 404, Caddy Unix admin 보존.
- 원격 URL은 /studio/admin/remote/*, 현재 ADMIN+remote 권한+source scope+
  session-bound manual lease를 검증하고 기존 WS의 만료/철회도 구현.
- renderer는 카카오 profile 없는 별도 offline runtime.
- 질문당 한 페이지 조건은 누락/잘림/최소 크기까지 검사.
- packet/student/subset/mode/layout/renderer/font를 export key에 pin.
- 원문/사진/세션/로그를 공개 Git에 넣지 않음.

진행:
1. schema와 작은 ADR, 실제 변경 파일·설치 경계를 확정.
2. 익명 fixture로 저장/질문/출력 경로와 UI/API를 구현.
3. private runtime과 원격 인증을 연결.
4. 실제 한 방의 CSV/복수 사진을 실증하고 capability receipt 작성.
5. 전체 목록/반복 수집/인증 중단/복구를 구현.
6. 학생별 PDF, preview, permission/overflow/recovery 검증 완료.
7. 기존 protected release 절차와 승인 범위 안에서 배포 산출물 준비.

실제 Kakao selector, 내부 endpoint, 설치 command, 운영 migration 적용 상태를
추측해서 기정사실로 쓰지 마세요. 필요한 수동 인증 전까지 가능한 구현과
검증을 계속 진행하고, 수동 작업이 필요한 정확한 순간과 이유만 알려 주세요.

완료 보고에는 구현한 동작, 수행한 테스트, 실제 적용 범위,
capability 실증 결과, 남은 제한을 구분해 주세요.
문서 작성 요청 자체는 운영 변경 실행을 뜻하지 않으므로
이 구현 세션에 이미 부여된 작업/배포 권한 범위를 따르세요.
~~~

---

<a id="section-18"></a>

## 18. 출처와 조사 범위

### 18.1 사용자 제공 정보

- 모니터 없는 Linux 서버에서 운용할 계획.
- 기존 DuckDNS 주소와 HTTPS 웹서비스.
- Caddy가 외부 HTTPS를 받아 Studio `127.0.0.1:8790`으로 전달.
- Nginx·Apache는 실행하지 않음.
- `config/caddy/Caddyfile`의 실제 내용.
- Caddy version `v2.11.4`.
- 카카오 권한은 마스터가 아닌 관리자/매니저.
- AI 없는 자동화, CSV·사진, 기간별·학생별·질문당 한 페이지 자료 목표.
- 실제 CSV 샘플의 구조·행 수·hash. 샘플의 개인정보 원문은 문서에 포함하지 않음.

### 18.2 저장소 근거

모든 아래 링크는 조사한 커밋에 고정했다. UI·저장·runtime 절에는 추가 상세 파일 링크가 있다.

- [R1 — AGENTS.md][R1]
- [R2 — 모듈 경계][R2]
- [R3 — 개발·운영 문맥][R3]
- [R4 — 실제 Caddyfile][R4]
- [R5 — Catalog Artifact 발행·읽기][R5]
- [R6 — ArtifactMemberPointer][R6]
- [R7 — 현재 WorkflowRunner 모델 제약][R7]
- [R8 — Orchestrator 외부 수집 실행 선례][R8]
- [R9 — Python·의존성·package 구성][R9]

### 18.3 공식 외부 문서

- [K1 — 일반 채널 1:1 채팅 조회 API 제공 여부에 대한 카카오 공식 답변][K1]
- [K2 — 카카오톡 채널 개발자 API 개요][K2]
- [K3 — 상담톡 공식 안내][K3]
- [K4 — 채널 관리자 1:1 채팅 공식 가이드][K4]
- [P1 — Playwright Python 다운로드][P1]
- [P2 — Playwright persistent context·profile·sandbox][P2]
- [M1 — PyMuPDF Page][M1]
- [M2 — PyMuPDF Font][M2]
- [M3 — PyMuPDF Shape][M3]

Caddy·noVNC·websockify·TigerVNC·systemd의 상세 근거는 원격 runtime 절 끝에 별도로 정리했다. upstream 문서는 변할 수 있으므로 구현에서는 실제 설치 release와 다시 대조한다.

### 18.4 이번 조사에서 하지 않은 것

- 사용자의 운영 서버·PostgreSQL·NAS 접속.
- 운영 배포, Caddy reload/restart, migration 적용.
- 로그인된 카카오 관리자센터의 DOM·네트워크 실증.
- 실제 사진 원본 다운로드 및 메시지 association 실증.
- 사용자 자료를 이용한 실제 PDF 생성.
- 저장소 source 수정, commit, PR, push.

따라서 문서의 architecture와 실제 코드 접점은 조사 결과이고, 카카오 UI capability·운영 설치 상태·실행 수치는 pilot 검증 대상이다.

[R1]: https://github.com/teddyok1206/eomai/blob/6a824aa48967270cc116661813d3d734f2f16e4e/AGENTS.md
[R2]: https://github.com/teddyok1206/eomai/blob/6a824aa48967270cc116661813d3d734f2f16e4e/docs/architecture/MODULE_BOUNDARIES.md
[R3]: https://github.com/teddyok1206/eomai/blob/6a824aa48967270cc116661813d3d734f2f16e4e/docs/agent-context/development-operations.md
[R4]: https://github.com/teddyok1206/eomai/blob/6a824aa48967270cc116661813d3d734f2f16e4e/config/caddy/Caddyfile
[R5]: https://github.com/teddyok1206/eomai/blob/6a824aa48967270cc116661813d3d734f2f16e4e/services/catalog_service/eom_catalog_service/artifacts.py
[R6]: https://github.com/teddyok1206/eomai/blob/6a824aa48967270cc116661813d3d734f2f16e4e/packages/protocol/eom_protocol/artifact_members.py
[R7]: https://github.com/teddyok1206/eomai/blob/6a824aa48967270cc116661813d3d734f2f16e4e/services/workflow_runner/eom_workflow_runner/models.py
[R8]: https://github.com/teddyok1206/eomai/blob/6a824aa48967270cc116661813d3d734f2f16e4e/services/orchestrator/eom_orchestrator/visual_reference_acquisition.py
[R9]: https://github.com/teddyok1206/eomai/blob/6a824aa48967270cc116661813d3d734f2f16e4e/pyproject.toml
[K1]: https://devtalk.kakao.com/t/1-1-api/151415
[K2]: https://developers.kakao.com/docs/ko/kakaotalk-channel/common
[K3]: https://kakaobusiness.gitbook.io/main/ad/cstalk
[K4]: https://kakaobusiness.gitbook.io/main/channel/run/chat
[P1]: https://playwright.dev/python/docs/downloads
[P2]: https://playwright.dev/python/docs/api/class-browsertype#browser-type-launch-persistent-context
[M1]: https://pymupdf.readthedocs.io/en/latest/page.html
[M2]: https://pymupdf.readthedocs.io/en/latest/font.html
[M3]: https://pymupdf.readthedocs.io/en/latest/shape.html
