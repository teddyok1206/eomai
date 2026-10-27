# 다종 문항 HWPX 합본 격리 검증 (2026-10-27 UTC)

## 범위와 입력

운영 서비스와 GPU INDEX는 변경하지 않았다. 사용자 제공 N제 ZIP에서 고유번호 10991과 11436의 원본 HWPX를 읽어 임시 작업공간에서만 실험했다. 원본 SHA-256은 각각 `736a722f9f1dda7f8cc05c862745e67c69cdaaf6d4717ffa25995d15ac251e99`, `abad699d2ea599d5612561094cdb5c46cddd328543d54310471ed7d742d56f9b`다. hwp-cli 1.3.1 릴리스 바이너리는 게시된 SHA-256과 대조한 뒤 설치하지 않고 격리 실행했다. 실험은 `eom-image`의 제한된 systemd 실행공간에서 수행했다.

## 결과

- `merge --strict`는 metadata/package passthrough/도형 ID 관련 손실 이벤트를 보고하고 합본을 거부했다.
- 비엄격 합본은 생성됐고 SHA-256은 `b101a3a1f0256f82abbaae7f91aa95751b02da3243025e84f184d3ddcb40c9c3`다. 손실 보고서는 `document_metadata_superseded` 1건, `document_package_passthrough_dropped` 4건, `gso_object_id_renumbered` 4건이다. 이 파일은 운영 Artifact로 등록하지 않았다.
- 자체 HWPX 검사와 EOM Builder의 marker 제거 상태 구조 검사는 통과했다. 각 원본과 합본에서 분리한 해당 segment에 대한 hwp-cli 구조 비교도 `identical=true`였다. 병합 후 이미지 멤버 세 개의 바이트 SHA-256도 원본과 같았다.
- 그럼에도 동일한 hwp-cli 렌더러의 첫 페이지 비교에서 10991은 원본/분리본 PNG가 바이트 동일했으나, 11436은 크게 달랐다. 원본에는 노트북 그림과 표/상자 배치가 있었고 분리본에는 주요 배치가 사라지거나 선·도형이 흩어져 있었다. 렌더러가 글꼴 대체와 shaping 실패를 경고했으므로 이 관찰만으로 실제 한글의 표시 결과를 단정하지는 않는다. 하지만 **구조 비교·media hash·package 검사만으로 시각적 동등성을 주장할 수 없다는 반례**로 충분하다.
- 별도 HWP 12109(`219f3a0510977af996b0177ac9c0b8159bfe1d6459fcd556f4566e8940e01d79`)의 HWPX 변환도 `control_removed` 1건, `metadata_value_removed` 2건을 기록했다. 혼합 HWP/HWPX 합본 경로로 승격하지 않았다.

## 판정과 후속 경계

`curated-document-assembly`의 저장·재열기만 운영에서 제공한다. 현재 후보 변환기의 비엄격 합본을 편집 가능한 정식 출력으로 배포하지 않는다. 다음 검증은 독립적인 두 번째 렌더러 또는 실제 한글에서 11436 원본/합본의 배치 차이를 확인하고, 원인인 style/header/section 자원 재매핑을 좁히는 것이다. 교정한 병합기는 원본별 텍스트·표·수식·그림·페이지 설정과 실제 편집성을 비교하는 acceptance를 통과해야 한다. 구조 검사나 손실 코드의 단순 허용 목록은 대체 증거가 아니다.

이 임시 실험 파일과 PNG는 정본 NAS Artifact가 아니며 Git에 포함하지 않는다. 원본과 저장된 조립 revision의 포인터·해시는 변경하지 않았다.
