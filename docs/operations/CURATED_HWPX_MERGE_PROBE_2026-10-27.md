# 다종 문항 HWPX 합본 격리 검증 (2026-10-27 UTC)

## 범위와 입력

운영 서비스와 GPU INDEX는 변경하지 않았다. 사용자 제공 N제 ZIP에서 고유번호 10991과 11436의 원본 HWPX를 읽어 임시 작업공간에서만 실험했다. 원본 SHA-256은 각각 `736a722f9f1dda7f8cc05c862745e67c69cdaaf6d4717ffa25995d15ac251e99`, `abad699d2ea599d5612561094cdb5c46cddd328543d54310471ed7d742d56f9b`다. hwp-cli 1.3.1 릴리스 바이너리는 게시된 SHA-256과 대조한 뒤 설치하지 않고 격리 실행했다. 실험은 `eom-image`의 제한된 systemd 실행공간에서 수행했다.

## 결과

- `merge --strict`는 metadata/package passthrough/도형 ID 관련 손실 이벤트를 보고하고 합본을 거부했다.
- 비엄격 합본은 생성됐고 SHA-256은 `b101a3a1f0256f82abbaae7f91aa95751b02da3243025e84f184d3ddcb40c9c3`다. 손실 보고서는 `document_metadata_superseded` 1건, `document_package_passthrough_dropped` 4건, `gso_object_id_renumbered` 4건이다. 이 파일은 운영 Artifact로 등록하지 않았다.
- 자체 HWPX 검사와 EOM Builder의 marker 제거 상태 구조 검사는 통과했다. 각 원본과 합본에서 분리한 해당 segment에 대한 hwp-cli 구조 비교도 `identical=true`였다. 병합 후 이미지 멤버 세 개의 바이트 SHA-256도 원본과 같았다.
- 동일한 hwp-cli 렌더러의 첫 페이지 비교에서 10991은 원본/분리본 PNG가 바이트 동일했으나, 11436은 크게 달랐다. 원본에는 노트북 그림과 표/상자 배치가 있었고 분리본에는 주요 배치가 사라지거나 선·도형이 흩어져 있었다. 렌더러가 글꼴 대체와 shaping 실패를 경고했으므로 이 관찰만으로 실제 한글의 표시 결과를 단정하지 않는다.
- 독립 확인으로 같은 11436 원본과 분리본을 서버의 LibreOffice로 각각 PDF 변환했다. 두 파일 모두 A3 1쪽으로 열렸지만, 원본 PDF에는 노트북 그림·제품 사양 표가 있고 분리본 PDF에는 그림 대신 반복된 도형 선이 나타났다. 파생 PDF SHA-256은 원본 `a8f0dadb69f69db20795c38afe6b2c5c751aa118da232e7dc93ea68b05b72f27`, 분리본 `61520f0381f91d3b7ebdcba4df1e1a14741e89cab7c377fec1cc42ff8541ac02`다. 이 변환도 별도 제한된 systemd 서비스에서 수행했다. **두 렌더러에서 같은 눈에 띄는 손상이 재현되어, 구조 비교·media hash·package 검사만으로 시각적 동등성을 주장할 수 없다는 반례가 확정됐다.** 실제 한글 편집 품질은 여전히 별도 수동 검증 항목이다.
- 별도 HWP 12109(`219f3a0510977af996b0177ac9c0b8159bfe1d6459fcd556f4566e8940e01d79`)의 HWPX 변환도 `control_removed` 1건, `metadata_value_removed` 2건을 기록했다. 혼합 HWP/HWPX 합본 경로로 승격하지 않았다.

### 11436 손상의 좁혀진 원인

11436 원본의 `Contents/content.hpf`는 그림 멤버 `BinData/image1.png`에 `id="image1"`을 할당하고 `Contents/section0.xml`은 `binaryItemIDRef="image1"`을 사용한다. 병합 출력에서는 첫 번째 문항의 `BinData/image1.PNG`가 `id="image1"`을 차지하고, 11436의 원래 그림 바이트는 `BinData/image1_2.png`/`id="image1_2"`로 옮겨졌다. 그러나 11436 section의 `binaryItemIDRef`는 `image1` 그대로였다. 이미지 바이트 SHA가 보존됐어도 **section→manifest ID 참조가 다른 문항의 이미지로 연결**된 것이다.

정식 출력과 분리된 진단용 임시 사본에서 이 단일 section 참조만 `image1_2`로 고쳐 LibreOffice PDF로 다시 렌더하자 노트북 그림과 제품 사양 표가 다시 나타났다. 진단 PDF SHA-256은 `2521f75e757aad1a4eb85316a2264cb5064db456eed8248fba829927f38e0cd1`다. 이 1건은 결함 원인을 확인하는 실험이지, 임의 HWPX 전체의 정확성이나 합본 출력 승인은 아니다. 정식 Builder는 manifest ID/멤버명 충돌과 **모든 section의 해당 참조를 함께 재매핑**하고, 재매핑 전후의 정확한 media hash·참조 해결·시각 차이를 자동 검증해야 한다. 원본 11436 및 기존 저장된 조립 revision은 수정하지 않았다.

후속 소스 후보 `eom_hwpx_builder.curated_binary_lineage`는 원본별 단일 section과 병합 후보의 section 수·참조 노드 순서를 확인한 뒤, manifest member의 **SHA-256과 media type 쌍**으로 각 binary 참조를 별도 출력 후보에 재매핑한다. 누락된 원본 바이트, 참조 개수/노드 종류 불일치, 기존 출력 덮어쓰기는 거부한다. 10991+11436 실제 병합 후보에서 `position=2, image1→image1_2` 한 건을 찾아 새 후보를 만들었고, 정확한 원본 media lineage를 다시 확인했다. 집중 및 기존 시험지 합본 회귀 21건이 통과했다. 이 helper는 아직 공식 Manager/Builder 실행 또는 운영 서비스에 연결하지 않았으며, **그림 참조만** 검증한다. 위의 전체 시각·수식·표·편집 품질 게이트를 대체하지 않는다.

## 판정과 후속 경계

`curated-document-assembly`의 저장·재열기만 운영에서 제공한다. 현재 후보 변환기의 비엄격 합본을 편집 가능한 정식 출력으로 배포하지 않는다. 다음 구현은 확인된 binary manifest ID 충돌과 section 참조 재매핑부터 회귀 테스트로 고정한 후, style/header/section/도형 자원까지 검증하고 원본 구조를 가능한 한 보존하는 package-level 경계를 비교한다. 교정한 병합기는 원본별 텍스트·표·수식·그림·페이지 설정과 실제 편집성을 비교하는 acceptance를 통과해야 한다. 구조 검사나 손실 코드의 단순 허용 목록은 대체 증거가 아니다.

이 임시 실험 파일과 PNG는 정본 NAS Artifact가 아니며 Git에 포함하지 않는다. 원본과 저장된 조립 revision의 포인터·해시는 변경하지 않았다.
