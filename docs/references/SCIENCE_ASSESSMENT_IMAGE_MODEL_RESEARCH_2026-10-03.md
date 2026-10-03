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
- `sdxl-morphology-img2img/2.2`, reference strength `0.35`, V7 후처리와 결정론적 overlay를
  사용한다.
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

## 프레임워크 선택

운영 프레임워크는 기존 Hugging Face Diffusers를 유지한다.

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
