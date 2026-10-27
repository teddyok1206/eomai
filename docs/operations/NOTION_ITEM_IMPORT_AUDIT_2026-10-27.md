# 노션 문항 원본 가져오기 사후 감사

확인 시각: 2026-10-27 UTC. 이 기록은 **읽기 전용** 검증 결과이며 정본 Item 승인, Graph 게시, 문항 내용·교육 품질 검수의 증거가 아니다.

## 고정 입력과 결과

- import: `extimport_d2019be75aa943636bfa8b7fb7f4a92e`
- 정본 workbook Artifact의 SHA-256: `sha256:2e04e7c0b6b3d507a846bb0a25b75e3313110595d8f399806fcbc087ad4be8fe`
- 검사: `eomctl content external-items verify --import-id extimport_d2019be75aa943636bfa8b7fb7f4a92e`
- 결과: `PASS`; A:AF 32칸을 포함한 행 1,297개, L/M/N 교정본 링크 관찰 3,042개, 선택된 최종 문서 1,053개가 일치했다.
- 판정별 건수: `MATCHED=1,042`, `MATCHED_DETECTED_HWPX=1`, `MATCHED_IDENTICAL_COPIES=10`, `DOCUMENT_MISSING=6`, `NAME_MISMATCH=7`, `LINK_UNSUPPORTED=1`, `DRAFT_ONLY=225`, `REJECTED=5`. 합계 1,297.
- 연결 예외 14건은 [검수 기록](NOTION_ITEM_LINK_EXCEPTIONS_2026-10-27.md)에 고유번호·행·셀·ZIP 후보 해시별로 남아 있으며 자동 연결/정본 승격 대상에서 제외한다.

## 검증 의미와 한계

검사는 로컬 staging 경로가 아닌 import에 pin된 NAS workbook Artifact를 해시 검증 후 다시 해독한다. import가 보존한 mapping revision/hash, 각 행 번호·U·A:AF 원값과 셀 메타데이터·관찰 해시·검색 facet, 교정본 링크 수 및 선택 문서의 Intake source-file 해시 관계를 운영 DB와 대조한다. 실패 시 값이나 이력을 고치지 않고 해당 오류 코드와 행 번호로 멈춘다.

원본 HWP/HWPX 파일 1,087개의 실제 바이트를 모두 다시 읽는 전수 NAS 검사는 이 명령에 포함되지 않는다. 문서 한 건의 Catalog private-socket 스트림은 정확한 Artifact/member/media/hash 검증을 거쳐 별도로 확인했으나, 사용자 HTTPS 다운로드 전 구간 검증은 아직 별개다. 원본 파일의 문항 내용, 정답·해설, 저작권/소유권, 편집 가능한 HWPX 변환 품질은 이 감사로 승인되지 않는다.

실행 당시에는 소스 후보의 새 읽기 전용 명령으로 검사했고, disposable PostgreSQL의 external-item 회귀 6개도 PASS였다. 동일 소스가 설치·활성화된 운영 릴리스의 결과로 오인하지 않는다. 배포 후에는 설치본 명령으로 같은 import를 재검증한다.

배포 후 재검증: 2026-10-27 16:17 UTC에 설치된 `/srv/eom/conda/envs/eom-api/bin/eomctl`의 같은 `verify --import-id`를 읽기 전용으로 실행해 `PASS`를 받았다. workbook SHA-256, 1,297행, 3,042개 교정본 링크, 선택 최종 문서 1,053개와 위 판정별 건수가 모두 일치했다. 이는 운영에 설치된 릴리스가 원본 workbook Artifact와 source-only DB 관찰을 재현한다는 증거이며, 원본 문서 전체 바이트·문항 내용·Graph/승인 상태의 전수 검증은 아니다.

## 운영 화면 확인

2026-10-27 UTC에 사용자가 Scientific Studio의 `데이터 → DB`에서 검색 후 `문항 정보 보기`, `PDF 미리보기 준비`, `PDF 열기`가 보이고 동작한다고 확인했다. 앞서 상세 패널이 화면 아래에 숨겨지던 문제를 고친 운영 Web을 새로고침한 뒤의 확인이다. 사용자는 이 응답에서 문항 고유번호를 지정하지 않았으므로, **운영 화면의 대표 동선 PASS**로만 기록한다. 1,053개 파일 전체의 렌더링 품질·정본 Item 등록·Graph 게시 PASS로 확대 해석하지 않는다.
