# 미사용 코드·개발 산출물 정리와 README 개편

2026-11-10 UTC. 기준 source `318ac1d3c118e99edea54b01b308fa6f83e5c6ef`.
사용자 요청 범위는 미사용 코드·산출물 정리와 제품 중심 GitHub README다.
운영 기능·계약 변경이나 새로운 정리 서비스 도입은 포함하지 않는다.

## 코드와 문서

- tracked Python의 private 함수 후보를 AST와 호출 참조로 조사하고, entrypoint·공개 export·
  CLI·테스트·staging 호출을 대조했다. 정적 검색만으로 모든 동적 미사용 코드를 판정하지 않는다.
- `science_assessment_web_corpus_service._build_manifest`는 과거 V1 작성 함수이며
  실제 `publish()`는 V2 작성만 사용한다. 테스트 외 호출이 없는 85줄의 함수·import를 제거했다.
- 신규 작성 테스트 두 개를 실제 V2 경로로 연결했다. 과거 V1 manifest의 JSON Schema·
  공개 모델·검증기는 보존하고, 기존 V1 fixture에 acquisition 연결·metadata 변조 거부 검사를
  추가했다. DB schema·released contract bytes·과거 Artifact를 바꾸지 않았다.
- README를 116줄에서 54줄로 줄였다. 제품 기능·업무 흐름·데이터 원칙·문서 진입점을 남기고,
  장문의 버전·배포 표는 `docs/status/README_CHECKPOINT_2026-11-10.md`로 보존했다.
  보존본의 행들은 서로 다른 시점의 기록임을 명시했다.
- `docs/README.md`에 기능별 설계·운영 탐색을 모았다. 진행률과 배포 세부 수치를 README에
  다시 누적하지 않도록 개발 문맥도 갱신했다.

## 실제 파일 정리

기존 검토된 일회성 정리 절차를 재사용했다. 새 timer·자동 삭제·NAS 이동은 만들지 않았다.
24시간 이상 지난 build 후보의 Git ancestry·wheel source identity·복구 파일을 확인하고,
실행 프로세스의 argv/cwd/exe/open descriptor와 현재·직전 release를 제외했다.
삭제 직전에는 고정 목록의 경로·소유자·inode·mtime·symlink/mount·현재 참조를 다시 검사했다.

| 삭제 범위 | 디렉터리 수 | 복구 방법 |
| --- | ---: | --- |
| 개발 도구 캐시·build·egg-info | 5 | 같은 source와 명시적 개발 환경에서 재생성 |
| source가 남아 있는 Python bytecode | 19 | 원래 Python source에서 재생성 |
| 완료된 API build source 복사본 | 21 | 보존된 source archive·wheel·Git commit |
| 오래된 Web 설치 시뮬레이션 | 5 | 보존된 wheel로 재생성 |
| 오래된 Web staging 복사본 | 5 | 해당 Git commit으로 재생성 |
| 합계 | **55** | 정본·설치본 삭제 없음 |

삭제 대상의 사전 할당 크기 합계는 2,977,980,416 bytes다.
같은 파일시스템의 실제 여유 증가 관측은 **2,951,254,016 bytes, 약 2.75GiB**다.
다른 writer가 실행 중이므로 두 수치의 차이는 정상이며 확보 용량을 고정 성능 지표로 쓰지 않는다.
후속 테스트가 새 캐시를 생성하는 것은 이전 대상이 남았다는 의미가 아니다.

staging 사용자 업로드·원본·실패 로그·운영 복구 스크립트, wheel/source archive,
설치 runtime·모델·벡터·Graph·문항·인증·백업은 보존했다. 특히 staging의 일회성 스크립트도
최근 복구/배포 wrapper에서 참조하는 경우가 있어 이름만 보고 일괄 삭제하지 않았다.
`/home/eom/EOMIS`와 운영 데이터 행은 삭제 대상이 아니다.

최초 3/7일 age 기준 계획은 실행하지 않았고, 검토한 24시간 기준 새 계획으로 한 번 적용했다.
두 계획과 실행 보고를 기존 Orchestrator file-set publisher로 NAS에 등록했다.
이 감사 Artifact 등록은 아래 정리 작업 자체의 업무 DB mutation 0과 별개다.

- Artifact: `artifact_48074388f8654e2188fd642bbcd23767`
- Revision: `rev_be6540e7a2924084ab0c4073a9e4f532`
- Member: `cleanup-report.json`
- SHA-256: `sha256:713052a52757fa4d8db7807eb701f487d29832e9f7cbe7fda7acd773d53a032d`
- 정식 등록 후 Catalog bytes/hash 재조회: PASS.

## 검증과 운영 영향

- 자료 수집·V1/V2 계약·중복 처리·실제 V2 writer·의존 경계·개발 문맥: **54 PASS**.
- 변경 코드 Ruff·format·core mypy·Git diff whitespace 검사 PASS.
- README·문서 안내·보존본의 로컬 링크 67개 존재 확인 PASS.
- 추가 V1 회귀 fixture의 시각 불일치로 첫 실행이 실패했다. fixture를 원 acquisition 시각과
  맞춘 후 전체 집중 suite를 재실행했으며, 이를 운영 버그로 재분류하거나 제품 계약을 완화하지 않았다.
- 정리 전후 INDEX·자료 학습·API·채팅의 PID/InvocationID 동일, active.
  HTTPS readiness는 `READY`였다. 서비스 재시작·배포·문항 생성·GPU 재계산은 0회다.
- 소스 삭제는 Git으로 복원 가능하다. 실행 중인 호환 release `acb834ac`와 frozen INDEX는
  유지하며, 미사용 함수 제거만을 위해 운영을 재배포하지 않는다.

이번 결과는 참조가 확인된 정리 범위다. 모든 미사용 코드가 제거됐다거나 향후 오류가 없다는
판정이 아니다. 다음 정리도 현재 실행·복구 경로와 exact target 확인을 먼저 수행한다.
