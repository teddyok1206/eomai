# SSD 임시 파일·미사용 코드 정리

2026-11-13 UTC. 기준 source `ab6c44da`.
사용자 요청에 따라 정본·현재 실행·복구 자료는 보존하고 재생성 가능한 파일을 정리했다.
새 자동 삭제 서비스·timer·의존성·DB schema는 만들지 않았다.

## 삭제한 로컬 파일

| 범위 | 디렉터리 수 | 복구 방법 |
| --- | ---: | --- |
| 저장소 도구 cache·build·egg-info | 5 | 보존된 source로 재생성 |
| 대응하는 Python source가 있는 bytecode cache | 22 | source에서 재생성 |
| 완료된 API build source 복사본 | 2 | 보존된 `source.tar`·wheel·Git commit |
| Web 설치 시뮬레이션 | 8 | 보존된 wheel |
| Web staging 복사본 | 8 | 보존된 wheel·Git commit |
| 합계 | **45** | 정본·설치 runtime 삭제 없음 |

대상 할당 크기 합계 550,789,120 bytes. 정리 창의 filesystem 여유 증가 관측은
542,543,872 bytes(약 **0.51GiB**)다. 배경 writer와 후속 테스트가 있으므로 수치는 근사치다.
테스트에서 새로 생성한 작은 cache는 삭제했던 이전 객체가 남았다는 뜻이 아니다.

기존에 검토된 일회성 정리 operator를 hash로 고정해 재사용했다. 24시간 경과·Git ancestry·
정확한 wheel source identity와 복구 파일을 확인하고, 현재/직전 주요 release와 설치된
controller release를 보존했다. 각 대상의 owner·inode·mtime·symlink/mount 여부 및 실행
프로세스의 argv/cwd/exe/open descriptor 참조를 검사한 뒤 낮은 CPU/I/O 우선순위로 삭제했다.

`staging`의 N제 ZIP·교과서 업로드·Excel·HWPX/PDF 원본·실패 증거·복구 스크립트는
삭제하지 않았다. NAS 정본·Graph·벡터·모델·백업, 인증/env, 배포 wheel/source archive,
소켓·설치본 및 `/home/eom/EOMIS`도 보존했다. `/tmp` 전체나 오래된 파일 전부를 지운 것이 아니다.

## 미사용 코드

tracked source Python 1,959개를 대상으로 private 함수 후보를 조사하고 import·호출·CLI·
테스트·staging 참조를 추가 확인했다. 정적 분석이 모든 동적 호출의 부재를 증명하지는 않는다.

- `stage_science_visual_campaign_review_batches.py`의 호출 없는 `_safe_read`, `_object`와
  그 두 import만 제거했다. 실제 `_load_campaign`은 기존 Orchestrator
  `resolve_science_visual_campaign`을 계속 호출한다. 파일 보호·JSON 검증은 그 owner에 남는다.
- 비슷한 이름의 publisher 함수는 실제 사용되므로 보존했다.
- `_capture_verified_access`, `_api_unix_socket_epoch`와 trainer directory 함수는 파일 안에서
  호출되지 않아도 다른 모듈/테스트가 사용하는 것을 확인해 보존했다.
- 기존 isolated CLI import 검증을 publisher와 stager 둘 다 검사하도록 확장했다.
  일반 회귀 테스트나 historical contract reader를 오래됐다는 이유로 제거하지 않았다.

## 검증·운영 영향

- CLI 삭제 전 baseline 2 PASS. 최종 corpus/CLI·image runtime·의존 경계·개발 문맥 suite
  **109 PASS**(baseline을 별도 합산하지 않음).
- 변경 파일 Ruff·format, stager mypy 1 source, Git whitespace 검사 PASS.
- 정리 전후 API/Web/INDEX/QUERY/Catalog/창작 학습/자료 학습/채팅의 PID·InvocationID·상태 동일.
  API READY, HTTPS HTTP 200. INDEX의 계속되는 근거 검증도 확인했다.
- 정리 자체의 service 재시작·모델 실행·업무 DB 변경은 모두 0회다. 감사 Artifact 등록의
  Job/manifest 저장은 별도 보관 작업이다. 불필요한 source helper 제거만을 위해 운영 wheel을
  재설치하거나 GPU 실행 pin을 바꾸지 않는다.
- 소스 삭제는 Git으로 복원 가능하며 삭제 디렉터리별 복구 참조는 감사 manifest에 남긴다.

## 감사 보관

원 계획 `/tmp/eom-ssd-cleanup-plan-20261113.json`과 적용 보고
`/tmp/eom-ssd-cleanup-report-20261113.json`, 정리 전후 서비스 관측·테스트·타입 검사 결과를
기존 Catalog/Orchestrator file-set commit 경계로 NAS에 보관한다. 큰 임시 파일을 다시
복제하거나 generated evidence를 Git에 넣지 않는다. 확정 포인터는 아래에 덧붙인다.

- Artifact: `artifact_4f2062ac069846a98e54c6e43a8fae8a`
- Revision: `rev_f00f6a5899e942e19f77fc48a46e00bb`
- 11 members, 전체 bytes/hash 재조회 PASS. 이 포인터를 덧붙이기 전 문서와 실제 삭제
  목록·복구 참조·운영 관측을 보관했다. 자격증명·env 원문·문항 내용은 포함하지 않았다.
