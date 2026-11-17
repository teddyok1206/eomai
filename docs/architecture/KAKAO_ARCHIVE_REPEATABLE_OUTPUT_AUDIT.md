# KakaoTalk 자료의 반복 자동 출력 점검

상태: 2026-11-17 source `76032729`와 실제 수신 샘플을 대조한 개발 점검.
사용자 요구: **개발 Codex가 매번 읽고 배치해 주는 일회성 결과가 아닌, 시스템의 반복 기능**.
일반 수집/질문 구성/출력은 비AI를 유지하며 선택적 교재 보강만 공유 Codex 슬롯을 사용한다.

## 결론

**현재 샘플의 모양은 만들었지만, 같은 수준의 전체 자동화는 아직 미완료다.**
이 PDF를 운영 API가 처음부터 끝까지 생성했다고 보고하면 안 된다. 실제 사진·학생 질문·
조교 답변을 사용했으나 아래 수동 처리가 있다. 샘플 제작용 staging 프로그램을 운영 기능으로
복사하거나 새 자료마다 개발자가 수정하는 방식은 채택하지 않는다.

## 1. 실제 샘플에 들어간 사람/개발 에이전트의 판단

| 단계 | 이번 처리 | 자동화 완료로 볼 수 없는 이유 |
| --- | --- | --- |
| 사진 연결 | 직접 pixels와 질문 내용을 대조해2장을 배치 | provider 메시지/첨부 occurrence 검증이 아니다 |
| 질문 선택 | CSV 행을 직접 골라3질문과3답변을 묶음 | 감사 인사·소개·날짜 경계 판단이 개발 스크립트에 들어감 |
| 학생 표시 | 샘플용 익명 표시와 소개문 제외 | 실제 학생 mapping/표시 수정 revision을 채택한 것이 아님 |
| 답변/metadata | 질문 PDF에 답변 쪽과 기록 박스를 별도 보고 프로그램으로 조립 | Studio packet/export의 공개 저장/출력 경로가 아니다 |
| 관련 개념 | 역할 프롬프트 초안만 준비 | 실제 교재 retrieval·원문 페이지·crop·편집 저장은 미연결 |

원래 수신/원문은 보존했다. 사진 표식3개 중1장은 미확보이고 조교 사진 표식은 없다.
수동 배치를 SOURCE_VERIFIED나 완전 수집으로 올리지 않았다. sample manifest도
`PRIVATE_USER_REQUESTED_SAMPLE_NOT_CATALOG_EXPORT`라고 표시한다.

## 2. 기존 코드에서 재사용할 수 있는 부분

| 담당 | 확인한 구현 | 현재 증거의 한계 |
| --- | --- | --- |
| 원본 입력 | Orchestrator `kakao_download_inputs.py`의 exact run/fence·receipt·hash reader | 전달 파일 무결성과 실제 방/메시지 정합은 다름 |
| 정규화/후보 | `kakao_csv_parser.py`, `kakao_question_rules.py` | role/order/timezone/사진 연결 근거가 필요; semantic 경계 보장은 아님 |
| 질문 저장·편집 | `kakao_question_service.py`, `kakao_question_compose_service.py`, `kakao_question_editing.py` | 실제 수신 source가 수락돼야 같은 공개 경로를 사용 가능 |
| 학생 묶음 | `kakao_packet_service.py`와 학생 exact subset | 일반 packet은 보강 편집 manifest가 아님 |
| 실행·다운로드 | `kakao_export_service.py`, `kakao_pdf_delivery.py`, Orchestrator executor/launcher | source/합성 HTTP 검증과 실제 계정 end-to-end는 구분 |
| 사진·본문 출력 | worker `question_pdf.py`, Catalog `kakao_render_projection.py` | 현재1질문1쪽; staff 사진/본문은 include_replies로 포함하나 역할별 보강 쪽은 없음 |

`tests/integration/test_kakao_delivery_http.py`의
`test_actual_studio_packet_student_pdf_download_and_same_request_replay`는 합성 CSV/사진을
실제 BFF→API→Catalog/임시 DB→저장→packet→renderer→file GET에 연결한다. 완료본의
같은 POST/GET은 재렌더하지 않으며 권한·CSRF를 확인한다. 이는 기존 모듈 연결의 증거이지
실제 카카오 사진 연결·이번6쪽 보고서의 운영 자동화 증거는 아니다.

## 3. 확인된 일반화 문제와 담당 경계

### A. 실제 역할·사진 occurrence와 수집 범위

`manual_observation.py`는 bounded DOM metadata를 읽지만 실제 사이트에서 확인되지 않은
role selector/메시지 ID/album 순서를 사실로 만들지 않는다. 과거 수신3건에는 이 관측이 없다.
실제 한 방에서 검증한 adapter가 CSV 행·학생/조교 역할·각 첨부를 묶어 source owner에
넘겨야 한다. filename·nickname·같은 문장/시각·사진 내용 추측으로 자동 확정하지 않는다.
초기 설정/명시적 수동 확인은 UI에 기록할 수 있지만 개발자의 새 스크립트를 매번 요구하지 않는다.

### B. 감사 인사 다음의 새 질문과 날짜

현재 frozen `turn_v1`은 학생 메시지 묶음과 staff 답변을 교대로 묶는다. 답변 뒤의 감사 인사와
며칠 뒤의 새 질문 사이에 staff 발화가 없으면 둘이 같은 후보에 들어갈 수 있다. 이때 시작일은
새 질문일이 아니라 감사 인사일이 돼 기간 조회에도 영향을 준다. 이번 샘플은 개발자가 이를
분리했으므로 이 부분을 자동화 성공으로 셀 수 없다.

익명 재현을 `tests/unit/test_kakao_archive_rules.py`의
`test_turn_v1_acknowledgement_can_precede_a_later_question_in_one_candidate`에 남겼다.
이 테스트는 현행 한계를 기록하며 새 기능 acceptance가 아니다. released v1을 재해석하지 말고,
기존 후보 owner에 필요한 successor 경계 규칙·검토 이유를 추가한다. 검증된 시간 간격/소스
boundary를 사용하고, ‘감사합니다’ 문자열 목록이나 이번 날짜·행 번호를 하드코딩하지 않는다.
문장 하나에 독립 질문이 여러 개면 일반 분할 UI를 사용하고 그 결과는 재수집으로 덮지 않는다.

### C. 여섯 구성의 정식 편집·출력

현재 `RenderManifest`는 역할 없는 text/image block을 한 질문1쪽에 투영한다. staff block은
원래 질문에 role이 있고 `include_replies`로 선택되지만, 질문·답변·metadata·개념 쪽을 분리해
저장/출력하는 구조는 아직 아니다. 샘플 후처리 코드를 서비스로 들여오지 말고
`KAKAO_QUESTION_STUDY_PACKET_DESIGN.md`의 얇은 successor에서 이 역할과 exact 원본 pin을
표현한다. 공용 packet/export/Artifact/권한·멱등/실행 owner를 확장하며 병렬 출력 플랫폼은 만들지 않는다.

### D. 교재 보강에서 모델에 맡길 일과 코드에 남길 일

버전 있는 역할 프롬프트로 필요한 개념·근거·설명 초안을 제안한다. core는 실제 현재 권한의
GraphRAG 결과, source/analysis/Artifact pin·원문 geometry·crop 범위를 검증한다. 문서마다
개발 Codex가 NAS에서 교재를 직접 찾아 합성하는 방식은 배제한다. 실제 페이지를 못 읽은
경우 모델이 ‘캡처 완료’라고 반환해도 수락하지 않는다. 추천 실패는 일반 PDF/편집을 막지 않는다.

## 4. 반복 기능의 완료 기준

1. 새 자료의 이름·행 번호·학생·주제·날짜를 코드에 추가하지 않고 같은 API/화면으로 처리한다.
2. 검증된 source가 있는 여러 방/날짜·학생에서 학생/조교 사진과 본문을 정확히 분리한다.
3. 후보 구성→기간 선택→질문/수동 편집 저장→여섯 구성 편집본→학생별 PDF가 공식 저장소로
   연결되고, 서비스 재시작/새로고침 후 exact revision을 다시 읽는다.
4. 불명확한 발신자·경계·시간대·사진·교재는 사유 있는 검토 상태다. 모든 예외에 개발 에이전트를
   부르는 대신 기존 UI에서 확인·수정한다. 손실을 숨겨 성공으로 표시하지 않는다.
5. 동일 요청/replay/완료본 GET은 저장본을 반환하며 모델·캡처·렌더를 다시 실행하지 않는다.
6. 실제 교재를 바꾸거나 사용자 편집 후 오래된 추천이 도착해도 잘못된 자료를 덮지 않는다.
7. 다른 학생 데이터 혼입, 다중 동일 메시지 소실, 사진 filename 오연결, 긴 답변/원문 crop,
   권한 철회·중단·재수집·동시 편집을 재현 가능한 fixture/임시 DB로 검증한다.
8. 실제 한 방과 접근 가능한 전체 방의 주기 수집을 별도로 실증한다. 개발용 sample PDF나
   synthetic E2E PASS로 이 gate를 대신하지 않는다.

다음 구현은 **수신물의 역할/사진/원문 확인을 공식 source로 연결하는 경계와 여섯 구성의
후속 편집·render 계약**을 우선한다. 원격 재로그인 없이 가능한 계약·저장·합성 회귀를 진행하고,
실제 provider selector 확인만 사용자 원격 세션이 준비됐을 때 수행한다. 전체 목표는 미완료다.
