# 최신 출제 Pack 접수 호환성 누락 수정

## 원인과 범위

사용자 문의 `webreq_c9e71f1db8dfcd98209ad932` 직후의 API 요청
`req_8b7d174049ed43dcf3d177f86fd45e9a`는 2026-11-12 15:36 UTC
`workflow_start`에서 `CONTENT_PACK_COMPATIBILITY_FAILED`로 종료됐다.
운영 Catalog의 read-only `bind_request`와 설치본의 순수 brief 검사에서 동일 오류를
재현했다. 최신 Pack 1.20.19의 정식 V5 smoke request를 V3 계열 오류로 거부했다.

모델 설정은 current RELEASED revision 33이며 변경할 필요가 없다.
교과서 필수 Pack 1.20.19는 public-similarity successor 집합에는 있지만 Catalog의
V5 material 집합이 1.20.18 단일 상수만 복사해 최신 successor를 빠뜨렸다.
이 집합에서 파생하는 그림 binding 및 reference-composition 정책도 함께 누락됐다.

## 수정

기존 담당 `workflow_catalog`가 같은 Catalog의
`SIMILARITY_REFERENCE_PACK_VERSIONS`를 재사용한다. 새 범용 registry나
implicit latest/semver 허용을 추가하지 않는다. 작은 immutable set의 membership은 O(1).
요청·그림 binding·그림 prompt 계약이 같은 명시적 successor 집합을 사용한다.

Pack bytes/hash, 팀장 프롬프트, schema, DB, 모델 설정, 과거 실행 pin은 변경하지 않는다.
오류 기록을 성공으로 바꾸거나 기존 요청을 자동 재실행하지 않는다.

## 검증과 배포 경계

- 수정 전 1.20.19의 AUTO/TEXT/DATA/INQUIRY/TABLE 1·2/IMAGE 1·2/MIXED 모두 실패,
  1.20.17/18의 같은 18개 조합은 통과함을 재현했다.
- 실제 `bind_request`의 workflow/brief/profile/image guard를 우회하지 않는 회귀를 추가했다.
  구형 V4 Pack·미검토 미래 버전 거부도 유지한다.
- focused 117 PASS, Ruff PASS. 변경한 두 Python 파일의 집중 mypy PASS.
  일반 mypy traversal은 무관한 두 파일의 기존 오류 5개를 보고했으며 이번 변경으로
  숨기거나 수정하지 않았다. 첫 테스트 fixture 작성 오류와 재현 로그도 보존한다.
- 요청·Pack·그림 adapter·자료 형식·유사도 prompt 경계·모델 설정/API admission의
  확장 회귀 313 PASS. 새 모델 추론이나 GPU 실행은 포함하지 않는다.
- 운영 read-only probe는 실제 활성 Pack/profile/image binding과 current preset을 읽으며
  DB 쓰기·문항 생성·모델 호출을 하지 않는다. 실제 사용자 생성 성공과 구분한다.
- 설치는 기존 compatible-release owner와 wheel 검증을 재사용한다. Web 수정 없음,
  migration 없음. 진행 중 작업이 없을 때 관련 공유 runtime을 인계하며 INDEX·수치
  runtime·기존 자료 학습 pin은 보존한다. 운영 적용 결과는 아래에 추가한다.
