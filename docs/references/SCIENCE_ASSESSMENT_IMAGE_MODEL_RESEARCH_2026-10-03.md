# 과학 평가 문항 이미지 모델·프레임워크 조사

기준일: 2026-10-03 UTC

## 목적

EOM이 만드는 과학 삽화를 평가원·교육청 시험지의 흑백 선화와 섞었을 때 쉽게 구별되지
않는 수준으로 개선하기 위한 기술 후보를 정리한다. 이 문서는 연구 결과이며 특정 모델의
운영 활성화나 기존 `ssd1b.v7` 설정 변경을 승인하지 않는다.

EOM의 목표는 한 모델이 내용·형태·스타일·문자까지 모두 생성하게 하는 것이 아니다.
각 책임을 다음처럼 분리한다.

```text
검증된 참조 이미지
    -> 선화·윤곽 구조 제어
    -> 로컬 확산 모델 + EOM 시험지 스타일 LoRA
    -> 흑백 정리와 톤 정규화
    -> 코드 기반 SVG 문자·화살표·축·수치
    -> PNG Artifact와 HWPX 내부 embedding
```

참조 이미지는 물체의 형태와 구성을, 구조 제어기는 위치와 부품 관계를, LoRA는 시험지의
획·명암·점묘·여백 문법만 담당한다. 의미가 정확해야 하는 라벨과 기하 요소는 계속
결정론적 SVG/Python 경계가 담당한다.

## 현재 기준선

- 운영 기준선은 SSD-1B 계열의 격리된 Diffusers provider이다.
- 현재 `/etc/eom/local-image-provider.json`에서 확인한 활성 설정은 V6이다.
  `sdxl-morphology-img2img/2.2`, reference strength `0.35`, V6 후처리와 결정론적 overlay를
  사용한다. V7은 기관 스타일 비교를 위한 후보이며 활성 운영 설정으로 간주하지 않는다.
- SSD-1B는 빠른 기준선과 rollback 후보로 보존한다.
- SSD-1B는 SDXL에서 일부 레이어를 제거한 증류 모델이므로 SDXL용 ControlNet이나
  T2I-Adapter의 drop-in 호환성을 가정하지 않는다.
- 현재 institutional object line-art와 raster/texture/scene 표본은 서로 다른 분포이므로
  하나의 통계나 하나의 LoRA 데이터셋으로 합치지 않는다.

관련 저장소 기준선:

- `config/local-image-provider.ssd1b.v7.json`
- `docs/architecture/LOCAL_GPU_IMAGE_ORCHESTRATION_V1.md`
- `docs/status/INSTITUTIONAL_IMAGE_STYLE_CANDIDATE_2026-10-02.md`

SSD-1B 공식 모델 카드는 1.3B 규모의 SDXL 증류 모델이며 빠른 생성을 장점으로 제시하지만,
사실적으로 정확한 실세계 표현에는 적합하지 않다는 한계도 명시한다.

- <https://huggingface.co/segmind/SSD-1B>

## 우선순위 후보

### 1. SDXL + T2I-Adapter Lineart + EOM LoRA

가장 먼저 검증할 후보이다. T2I-Adapter는 SDXL의 외부 선화 조건을 받아 구조를 제어하는
약 79M 규모의 가벼운 adapter다. 전체 ControlNet보다 작고 Apache-2.0으로 공개되어 있으며,
현재 16GB GPU에서 품질과 운용 비용의 균형이 가장 좋을 가능성이 높다.

- 논문: <https://arxiv.org/abs/2302.08453>
- 공식 모델: <https://huggingface.co/TencentARC/t2i-adapter-lineart-sdxl-1.0>
- Diffusers 학습 문서:
  <https://github.com/huggingface/diffusers/blob/main/docs/source/en/training/t2i_adapters.md>

### 2. SDXL + Canny ControlNet + IP-Adapter Plus + EOM LoRA

ControlNet은 윤곽·깊이·분할 같은 공간 조건을 강제하고, IP-Adapter는 참조 이미지의 물체
형태와 시각 특징을 보충한다. 형태 보존력이 더 높을 수 있지만 모델 수와 튜닝 축이 늘고
VRAM·지연 비용이 더 크다.

- ControlNet: <https://arxiv.org/abs/2302.05543>
- SDXL Canny ControlNet: <https://huggingface.co/diffusers/controlnet-canny-sdxl-1.0>
- IP-Adapter: <https://arxiv.org/abs/2308.06721>
- 공식 가중치: <https://huggingface.co/h94/IP-Adapter>
- Diffusers 결합 가이드: <https://huggingface.co/docs/diffusers/main/using_diffusers/ip_adapter>

### 3. Informative Drawings + EOM 후처리

사진을 의미 있는 선화로 바꾸는 비확산 baseline이다. 복잡한 자연물·천체·생물을 시험지
선화로 바꾸는 비교군으로 가치가 있다. 공식 구현은 오래된 PyTorch에 고정되어 있으므로
격리된 연구 환경에서만 평가하고 운영 dependency로 바로 넣지 않는다.

- 논문: <https://arxiv.org/abs/2203.12691>
- 코드: <https://github.com/carolineec/informative-drawings>

### 4. 후속 연구 후보

- SD 3.5 Medium: 프롬프트 이해와 복잡한 장면의 후속 비교군.
  <https://huggingface.co/stabilityai/stable-diffusion-3.5-medium>
- Qwen-Image-Edit: 편집 품질 연구군. 16GB에서는 양자화와 CPU offload가 필요하다.
  <https://huggingface.co/Qwen/Qwen-Image-Edit>
- InstantStyle: 참조 이미지의 내용 유출을 줄이고 스타일 레이어만 주입하는 후보.
  <https://arxiv.org/abs/2404.02733>
- StyleAligned: 한 시험지 안의 여러 그림 스타일을 일관되게 만드는 후속 후보.
  <https://arxiv.org/abs/2312.02133>
- SDEdit: 원본 충실도와 생성 자연스러움을 노이즈 강도로 조절하는 현재 strength sweep의
  연구 근거. <https://arxiv.org/abs/2108.01073>
- CLIPasso와 diffvg: 벡터 단순화·SVG 연구용 기준선이며 일반 물체 생성기를 대체하지
  않는다. <https://arxiv.org/abs/2202.05822>, <https://github.com/BachiLi/diffvg/>

FLUX.1 Kontext dev는 12B 규모, 16GB 환경의 높은 offload 비용, 비상업 라이선스 때문에
회사 운영 후보에서 제외한다. <https://huggingface.co/black-forest-labs/FLUX.1-Kontext-dev>

## 2026-10-03 추가 확인: 선화 추출 가중치의 원 배포처

기존 `lllyasviel/Annotators`의 `other` 표기와 빈 모델 카드만으로 가중치 사용 범위를
판단하지 않았다. 원 저자의
[Informative Drawings Space README](https://huggingface.co/spaces/carolineec/informativedrawings/blob/bd4b4299be505803e036203a39c02024b4cfee11/README.md)는
MIT를 명시하고 실제 가중치도 같은 저장소에서 배포한다. 고정 revision은
`bd4b4299be505803e036203a39c02024b4cfee11`이다. 공개 Hub 파일 메타데이터를 조회해 다음
동일성을 확인했다. 이는 파일 출처 확인이며, 해당 모델의 실제 검수 결과는 아니다.

| 원 저자 파일 | Annotators 대응 파일 | 바이트 수 | SHA-256 |
|---|---|---:|---|
| `model.pth` | `sk_model.pth` | 17,173,511 | `c686ced2a666b4850b4bb6ccf0748031c3eda9f822de73a34b8979970d90f0c6` |
| `model2.pth` | `sk_model2.pth` | 17,173,511 | `30a534781061f34e83bb9406b4335da4ff2616c95d22a585c1245aa8363e74e0` |

대조한 Annotators revision은 `982e7edaec38759d914a963c48c4726685de7d96`이다.
첫 실험은 원 배포본의 style 1만 선택하며, style 2를 추가 비교한 것으로 간주하지 않는다.
[원 저자 구현](https://huggingface.co/spaces/carolineec/informativedrawings/blob/bd4b4299be505803e036203a39c02024b4cfee11/app.py)과
[고정 controlnet_aux 구현](https://github.com/huggingface/controlnet_aux/blob/v0.0.7/src/controlnet_aux/lineart/__init__.py)의
3-residual-block 구조와 가중치 파일 동일성을 확인했지만, 원 구현의 무제한 `torch.load`는
복제하지 않는다. 제한적 CPU `weights_only=True` 변환, 정확한 텐서 키·형상·유한값 검사,
safetensors 런타임, MIT 고지 보존을 별도 검증한다. Gradio/torchvision/OpenCV나 외부 추론
서비스는 도입하지 않는다. 새 의존성 없이 기존 Torch/Pillow/NumPy로 작은 추출 구조를
격리 provider에 포팅할 계획이다.

기존 grayscale inversion은 회색 면까지 조건에 포함하며 학습된 윤곽 추출과 같지 않다.
다만 T2I 강도 0 실험도 품질이 낮았으므로 원인을 추출기 하나로 단정하지 않는다.
후속 추출 실험은 [ADR 0180](../adr/0180-pinned-informative-lineart-extractor.md)의 별도
계약·revision으로 기록한다. 기존 SDXL 1.0 정책, 팀장 프롬프트 원문, LoRA 가중치와 운영
V6는 변경하지 않는다. 아직 가중치 다운로드·변환·설치나 추출 결과의 품질 PASS는 없다.

## 프레임워크 선택

### 2026-10-04 실행 결과에 따른 구조 제어 후보 재검토

실제 SDXL 출력 72장과 고정 CPU 정리 파생 6장은 모두 자체 불합격이다. LoRA 배경을
하얗게 정리해도 뿌리·잎맥·선풍기 중심/망·바퀴 발광 표시가 보존되지 않는다.
이는 독립 평가나 모든 모델에 대한 결론이 아니라, 현재 고정 입력 실험의 관찰이다.

다음 가설은 기존 계획의 ControlNet/IP-Adapter 후보에서 **Canny ControlNet 한 요소만**
먼저 비교하는 것이다. [공식 모델 카드](https://huggingface.co/diffusers/controlnet-canny-sdxl-1.0)는
SDXL용 Canny 조건과 OpenRAIL++ 가중치 표기를 제공한다. [공식 파일 목록](https://huggingface.co/diffusers/controlnet-canny-sdxl-1.0/tree/main)의
fp16 safetensors만 후보로 삼고 pickle 파일/전체 snapshot은 받지 않는다. 14:54 UTC 읽기 전용
조회 당시 정확한 revision·설정·예상 가중치 SHA를 ADR 0191에 기록했으며 그 시점에는 실제
가중치를 받지 않았다. 이후 고정 Hub 라이선스 매핑 근거와 실제 실행을 검증했다(아래 후속 결과).
[Diffusers 0.35.2 소스](https://github.com/huggingface/diffusers/blob/v0.35.2/src/diffusers/pipelines/controlnet/pipeline_controlnet_sd_xl.py)에서
공간 조건과 LoRA를 같이 사용하는 경로를 확인했지만 우리 그림에서 개선된다는 뜻은 아니다.

현재 실험 환경의 Diffusers 0.35.2/Torch 2.7.1+cu128/PEFT 0.17.1/Pillow 11.3.0은 유지한다.
초기 조회 당시 OpenCV는 없었고, 이후 이유·버전·해시·라이선스를 고정한
`opencv-python-headless==4.11.0.86`만 lab에 선택적으로 설치했다. 실제 worker ABI/Canny,
`pip check`와 설치 RECORD를 확인했고 다른 수치 라이브러리는 유지했다. 고정 CPU 변환으로
윤곽 입력 3장을 120ms에 준비·등록했으며, 원본과 직접 비교한 필수 세부 보존은 3/3 PASS다.
이는 전처리 입력 검수일 뿐 완성 그림의 품질 PASS가 아니다. 변환 없는 replay도 통과했고
이 CPU checkpoint 당시 controller 가중치·GPU 생성·재학습은 없었다. 비슷한 Pillow 필터를
Canny라고 부르지 않는다.
구현·예산·보존 경계는 [ADR 0191](../adr/0191-bounded-sdxl-spatial-conditioning-alternative.md)에
제안으로 기록했다. 기존 T2I·CPU 출력과 판단, 운영 V6는 보존한다.

운영 프레임워크는 기존 Hugging Face Diffusers를 유지한다.

17:15 UTC 후속 결과: 같은 3원본과 모든 공통 수치·문구를 고정한 Canny ControlNet
BASE/LORA 6장을 실제 생성했다(45.948초, peak 약 10.02GiB). 설치·라이선스·해시·등록·재조회는
통과했으나 최종 그림은 자체 6/6 불합격이다. LoRA 조건에서 원본 배치·잎맥·양쪽 바퀴의 발광
표식이 개선된 것은 관찰되지만 회색/격자 배경과 거친 선을 해결한 것은 아니다.
BASE 선풍기에는 객체 2개가 추가됐고, BASE 식물 원시 PNG는 색채도 남는다. 최종 흑백 crop이
원시 품질을 대신하지 않는다. 기존 72장의 불합격을 바꾸지 않고 새 6장을 더해 원본 누적 78장,
정리 파생 6장·입력 map 3장은 별도로 관리한다. 독립 blind/heldout·추가 학습·운영 활성화는 없으며,
다음은 배경 원인의 읽기 전용 입력/수치 경계 점검이다. 현재 결과만으로 ControlNet 전체나
LoRA 일반 성능을 결론 내리지 않는다.

18:12 UTC 후속 결과: 입력 세 원본은 해시가 일치하고 테두리가 완전히 흰 RGB였다.
읽기 전용 코드 점검에서 명백한 중복 정규화는 발견하지 못했지만 VAE 오류가 없다는 증명은 아니다.
고정 [Diffusers 0.35.2 Img2Img 소스](https://github.com/huggingface/diffusers/blob/v0.35.2/src/diffusers/pipelines/controlnet/pipeline_controlnet_sd_xl_img2img.py)의
시작 이미지와 윤곽 조건을 분리하는 경로로 마지막 6장만 비교했다. 원본 흑백 RGB를 흰 캔버스의
초기 이미지로도 주고 strength0.35를 고정했다. 문구·seed·모델·LoRA·Canny 조건은 유지했으며
30-step 스케줄에서 실제 denoising은10 steps다. 21.220초/peak 약10.02GiB, 등록·재현·재조회 PASS.
회색 격자 배경이 사라지고 원본의 필수 구성이 유지돼 자체 원본 보존/흰 배경 검수는6/6 PASS다.
BASE도 개선됐으므로 이 성과는 **원본 보존 초기화 방식의 개선**이지 LoRA 일반 성능 증명이 아니다.
원본과 거의 같은 선화의 재현은 새 사진을 선화로 바꾸는 시험과 다르다. native RGB의 색채 잔재와
별도 고정 grayscale crop도 구분한다. 기존 불합격78장·정리 파생6장의 판정은 유지한다.
원본 누적84장, 전체 fallback12/12 소진이며 추가 TRAIN 강도/seed/문구 sweep은 없다.
출력·자체 검수·21개 비바이너리 증거 pointer는 ADR0191과 운영 계획에 기록했다.
다음은 reserved 평가 모집단과 blind 평가 계약의 읽기 전용 호환성 확인이다. 기존 blind V1에
probe-output PNG를 semantic-raster로 다시 이름 붙이거나 TRAIN3개를12/32개로 반복하지 않는다.
독립 blind/heldout·새 학습·운영 활성화는 아직 없고 운영 V6는 유지한다.

- ControlNet, T2I-Adapter, IP-Adapter, LoRA를 지원한다.
- 모델 revision과 weight hash를 고정할 수 있다.
- CPU offload와 양자화를 지원한다.
- EOM의 격리 provider와 protocol-first 계약으로 감싸기 쉽다.

문서:

- <https://huggingface.co/docs/diffusers/main/index>
- <https://huggingface.co/docs/diffusers/main/optimization/memory>

ComfyUI와 InvokeAI는 조합을 빠르게 확인하는 오프라인 연구 GUI로는 유용하지만 동적
node/plugin과 별도 실행 관리 계층을 EOM 운영 핵심에 도입하지 않는다. EOM의 모델 실행은
계속 orchestrator와 고정된 provider 계약을 통한다.

- <https://github.com/comfy-org/ComfyUI>
- <https://invoke.ai/>

## 데이터셋 전략

권장 분류는 다음과 같다.

- 물체 선화: 자동차, 인체, 동물, 식물, 실험 기구
- 자연·천체: 지형, 행성, 은하, 기상
- 과학 장면: 충돌, 운동, 실험 배치
- 코드 우선 도식: 회로, 그래프, 광선, 장치 연결
- raster로 만들지 않을 것: 표, 수식, 정확한 축과 라벨 중심 도식

현재 수십 개 선화는 micro-LoRA 탐색에는 사용할 수 있지만 일반화를 주장하기에는 작다.
심각한 style-LoRA 비교 전에는 승인된 비정답 노출 object line-art crop 100~300개를 목표로
한다. train/test는 이미지 무작위 분할이 아니라 원본 시험지·출처 문서 단위로 분리해
동일 시험지의 스타일 누수를 막는다.

LoRA는 형태나 과학 내용을 외우지 않고 다음 스타일 특성만 학습해야 한다.

- 획 굵기와 끝 처리
- 흑백 단계와 점묘
- 내부 디테일 밀도
- 시험지 여백과 대상 점유율
- 배경·장식 제거

## 평가 계약

FID는 작은 표본에서 주제 차이와 스타일 차이를 섞으므로 주 판정 지표로 사용하지 않는다.
자동 평가는 다음을 보조적으로 사용한다.

- edge F1과 약간의 dilation 허용
- bounding box, 중심, 점유율
- connected component와 획 굵기 분포
- foreground/dark/mid-tone/halftone 분포
- OCR 기반 가짜 문자 검출
- DreamSim 또는 DINOv2 의미·구성 유사도
- 작은 정렬 오차에 강한 shift-tolerant LPIPS

관련 연구:

- DreamSim: <https://arxiv.org/abs/2306.09344>
- DINOv2: <https://arxiv.org/abs/2304.07193>
- Shift-tolerant LPIPS: <https://arxiv.org/abs/2207.13686>

최종 기준은 같은 depiction key를 대상으로 한 기관 이미지와 EOM 이미지의 origin-hidden
blind 2AFC이다. 최소 32개 depiction, 3명 이상의 독립 검토자처럼 대상과 검토자를 분리한
평가를 권장한다. 단순히 차이를 발견하지 못한 것이 아니라 사전에 정한 동등성 범위 안에
기관 이미지 선택률이 들어오는지를 판단한다. 별도로 과학 정확성, 형태 보존, 구성,
pseudotext를 평가한다.

## 첫 비교 실험

배포 없이 다음 네 후보를 같은 참조·프롬프트·seed에서 비교한다.

1. 현재 SSD-1B V7
2. Informative Drawings + EOM 후처리
3. SDXL + T2I-Adapter Lineart + EOM LoRA
4. SDXL + Canny ControlNet + IP-Adapter Plus + EOM LoRA

참조 대상 12개와 후보별 seed 2개라면 총 96개다. 작은 pilot은 6개 대상, 48개 결과로
시작할 수 있다. 각 실행에는 모델 revision/hash, reference hash, prompt revision, seed,
adapter weight, peak VRAM, latency, output hash를 기록한다. 자동 gate를 통과한 결과만 blind
review에 넣는다.

승자가 생기더라도 기존 V7을 수정하지 않는다. 새 model/provider/config/result 계약의
successor를 schema-first로 추가하고 runtime download 없이 검증된 weight revision을
pin한다. worker는 NAS에 쓰지 않으며 orchestrator만 검증된 결과를 Artifact로 commit한다.

## 결론

첫 구현 후보는 다음 조합이다.

```text
SDXL + T2I-Adapter Lineart + EOM 시험지 스타일 LoRA
     + V7 흑백 정리 + deterministic SVG overlay
```

형태 충실도가 부족한 사례에는 ControlNet과 IP-Adapter Plus 조합을 비교한다. SSD-1B는
속도 기준선과 rollback으로 유지하고 SD 3.5 Medium과 Qwen-Image-Edit은 2차 연구군으로
둔다. 품질 도약의 핵심은 LoRA에게 형태까지 외우게 하는 것이 아니라 구조 제어와 스타일
학습의 책임을 분리하는 것이다.
