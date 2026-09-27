"""Project accepted visual observations into a source-bound subject inventory.

The projection uses a fixed alias index and per-subject reference sets. Construction is
O(V + M + R), where V is the number of visual observations, M is the number of alias matches, and
R is the emitted reference count. No source bytes or full Item payloads are copied into the result.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from eom_catalog_contracts import (
    AssessmentVisualPatternObservation,
    KnowledgeAnalysisResultV9,
    LegacyItemExtractionResult,
)
from eom_image_contracts import (
    ImageEvaluationArtifactMember,
    LocalImageScienceVisualSubjectInventory,
    ScienceVisualSubject,
    ScienceVisualSubjectOmission,
    ScienceVisualSubjectSourceReference,
    content_sha256,
    text_sha256,
)

SubjectFamily = Literal[
    "ABSTRACT_SCIENCE_MODEL",
    "EARTH_SPACE",
    "LAB_APPARATUS",
    "LIVING_ORGANISM",
    "MICROSCOPIC_STRUCTURE",
    "PHYSICAL_OBJECT",
    "REAL_WORLD_SCENE",
]
SubjectRoute = Literal["BLOCKED", "HYBRID", "LORA_RASTER", "PYTHON_SVG"]
SubjectPrimitive = Literal[
    "APPARATUS",
    "AXIS_PLOT",
    "CELL_CROSS_SECTION",
    "CIRCUIT",
    "CONTENT_TABLE",
    "FLOW_DIAGRAM",
    "GENERIC_LABELLED_DIAGRAM",
    "GEOLOGIC_SECTION",
    "MAP_BOUNDARY",
    "ORBITAL_SYSTEM",
    "PARTICLE_SYSTEM",
    "RAY_DIAGRAM",
    "TIMELINE",
    "VECTOR_FIELD",
]


class ScienceVisualSubjectProjectionError(RuntimeError):
    """Stable fail-closed error for inconsistent accepted-source projections."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class AcceptedVisualSubjectSource:
    accepted: KnowledgeAnalysisResultV9
    accepted_result: ImageEvaluationArtifactMember
    extraction: LegacyItemExtractionResult
    extraction_result: ImageEvaluationArtifactMember


@dataclass(frozen=True, slots=True)
class SubjectDefinition:
    key: str
    label_ko: str
    label_en: str
    aliases_ko: tuple[str, ...]
    family: SubjectFamily
    route: SubjectRoute
    primitive: SubjectPrimitive | None
    raster_prompt_en: str | None = None
    blocked_reason: (
        Literal[
            "COPYRIGHT_REPRODUCTION_RISK",
            "NO_SAFE_RENDER_ROUTE",
            "POLICY_PROHIBITED_CONTENT",
        ]
        | None
    ) = None
    aliases_en: tuple[str, ...] = ()


def _raster(subject: str) -> str:
    return (
        "monochrome Korean science assessment illustration of "
        f"{subject}, plain white background, restrained grayscale, clean silhouette, "
        "no text, no labels, no watermark, no decorative border"
    )


def _hybrid(subject: str) -> str:
    return (
        "monochrome non-authoritative background layer for a Korean science assessment showing "
        f"{subject}, plain white background, restrained grayscale, no text, no labels, "
        "leave exact geometry and annotations to a vector overlay"
    )


SUBJECT_DEFINITIONS: tuple[SubjectDefinition, ...] = (
    SubjectDefinition(
        "AIR_CUSHION_PACKAGING",
        "공기 완충 포장재",
        "air cushion packaging",
        ("에어 매트", "공기 완충", "포장재"),
        "PHYSICAL_OBJECT",
        "LORA_RASTER",
        None,
        _raster("air-filled protective packaging or an inflated landing mat"),
        aliases_en=("air-filled protective packaging", "landing mat", "inflated packing"),
    ),
    SubjectDefinition(
        "APPLE_TREE",
        "사과나무",
        "apple tree",
        ("사과나무", "사과 A", "사과 B"),
        "LIVING_ORGANISM",
        "HYBRID",
        "VECTOR_FIELD",
        _hybrid("an apple tree branch with fruit"),
        aliases_en=("apple tree",),
    ),
    SubjectDefinition(
        "ATOM_MODEL",
        "원자 모형",
        "atom model",
        ("원자", "전자껍질"),
        "ABSTRACT_SCIENCE_MODEL",
        "PYTHON_SVG",
        "PARTICLE_SYSTEM",
    ),
    SubjectDefinition(
        "ATOMIC_NUCLEUS",
        "원자핵",
        "atomic nucleus",
        ("원자핵", "양성자", "중성자"),
        "ABSTRACT_SCIENCE_MODEL",
        "PYTHON_SVG",
        "PARTICLE_SYSTEM",
    ),
    SubjectDefinition(
        "BATTERY_CELL",
        "전지",
        "electric cell",
        ("건전지", "전지 기호", "화학 전지"),
        "LAB_APPARATUS",
        "PYTHON_SVG",
        "CIRCUIT",
    ),
    SubjectDefinition(
        "BACTERIA",
        "세균",
        "bacteria",
        ("세균", "항생제"),
        "MICROSCOPIC_STRUCTURE",
        "PYTHON_SVG",
        "CELL_CROSS_SECTION",
        aliases_en=("bacteria", "antibiotic"),
    ),
    SubjectDefinition(
        "BEAKER", "비커", "beaker", ("비커",), "LAB_APPARATUS", "PYTHON_SVG", "APPARATUS"
    ),
    SubjectDefinition(
        "BIODIVERSITY",
        "생물 다양성",
        "biodiversity",
        ("유전적 다양성", "종 다양성", "생태계 다양성", "생물 다양성"),
        "LIVING_ORGANISM",
        "HYBRID",
        "GENERIC_LABELLED_DIAGRAM",
        _hybrid("three distinct biodiversity examples without people or text"),
        aliases_en=(
            "biodiversity",
            "genetic diversity",
            "species diversity",
            "ecosystem diversity",
        ),
    ),
    SubjectDefinition(
        "BIOLOGICAL_CELL",
        "세포",
        "biological cell",
        ("세포",),
        "MICROSCOPIC_STRUCTURE",
        "PYTHON_SVG",
        "CELL_CROSS_SECTION",
        aliases_en=("plant-cell", "plant cell", "cell schematic"),
    ),
    SubjectDefinition(
        "BURR_FRUIT",
        "도꼬마리 열매",
        "bur fruit",
        ("도꼬마리", "열매"),
        "LIVING_ORGANISM",
        "LORA_RASTER",
        None,
        _raster("a hooked bur fruit specimen"),
        aliases_en=("bur fruit", "burr fruit"),
    ),
    SubjectDefinition(
        "CELL_MEMBRANE",
        "세포막",
        "cell membrane",
        ("세포막", "인지질"),
        "MICROSCOPIC_STRUCTURE",
        "PYTHON_SVG",
        "CELL_CROSS_SECTION",
        aliases_en=("membrane movement", "phospholipid", "cell membrane"),
    ),
    SubjectDefinition(
        "CELL_ORGANELLE",
        "세포 소기관",
        "cell organelle",
        ("소기관", "미토콘드리아", "엽록체", "리보솜"),
        "MICROSCOPIC_STRUCTURE",
        "PYTHON_SVG",
        "CELL_CROSS_SECTION",
    ),
    SubjectDefinition(
        "CHEMICAL_FLASK",
        "플라스크",
        "laboratory flask",
        ("플라스크",),
        "LAB_APPARATUS",
        "PYTHON_SVG",
        "APPARATUS",
    ),
    SubjectDefinition(
        "CHEMICAL_REACTION",
        "화학 반응",
        "chemical reaction",
        ("화학 반응", "반응물", "생성물", "산소와의 반응", "반응식"),
        "ABSTRACT_SCIENCE_MODEL",
        "PYTHON_SVG",
        "FLOW_DIAGRAM",
    ),
    SubjectDefinition(
        "COLLISION_MOMENTUM",
        "충돌과 운동량",
        "collision and momentum",
        (
            "충돌 전",
            "충돌 후",
            "평균 힘",
            "충돌 상황",
            "운동량",
            "벽과 충돌",
            "힘-시간",
            "질량·속력",
            "속력-시간",
            "방향 힘",
        ),
        "ABSTRACT_SCIENCE_MODEL",
        "PYTHON_SVG",
        "VECTOR_FIELD",
        aliases_en=("collision", "momentum", "force-time"),
    ),
    SubjectDefinition(
        "CONSUMER_SCIENCE_PRODUCT",
        "생활 과학 제품",
        "consumer science product",
        ("빵", "비누", "손 소독제", "습기 제거제", "연료 용기"),
        "PHYSICAL_OBJECT",
        "HYBRID",
        "GENERIC_LABELLED_DIAGRAM",
        _hybrid("simple household science-related products"),
        aliases_en=("soap", "hand sanitizer", "moisture absorber", "fuel container"),
    ),
    SubjectDefinition(
        "CIRCUIT_COMPONENTS",
        "전기 회로",
        "electric circuit",
        ("회로", "전구", "스위치", "저항", "도선"),
        "LAB_APPARATUS",
        "PYTHON_SVG",
        "CIRCUIT",
    ),
    SubjectDefinition(
        "CLIMATE_ATMOSPHERE",
        "기권과 대기",
        "atmosphere and climate",
        ("기권", "대기", "기온"),
        "EARTH_SPACE",
        "PYTHON_SVG",
        "GENERIC_LABELLED_DIAGRAM",
    ),
    SubjectDefinition(
        "CLOUD_WEATHER",
        "구름과 날씨",
        "cloud and weather scene",
        ("구름", "태풍", "강수"),
        "EARTH_SPACE",
        "LORA_RASTER",
        None,
        _raster("cloud formations or a weather scene"),
    ),
    SubjectDefinition(
        "COIL_ELECTROMAGNET",
        "코일",
        "coil and electromagnet",
        ("코일", "전자석"),
        "LAB_APPARATUS",
        "PYTHON_SVG",
        "CIRCUIT",
    ),
    SubjectDefinition(
        "CRYSTAL_SOLID",
        "결정과 고체",
        "crystal or solid structure",
        ("결정 구조", "결정격자", "고체"),
        "ABSTRACT_SCIENCE_MODEL",
        "PYTHON_SVG",
        "PARTICLE_SYSTEM",
    ),
    SubjectDefinition(
        "DIGITAL_MEASUREMENT_DISPLAY",
        "디지털 측정 화면",
        "digital measurement display",
        ("전광판", "스마트폰 화면", "소음 수준", "제한 속도", "현재 속도"),
        "PHYSICAL_OBJECT",
        "PYTHON_SVG",
        "GENERIC_LABELLED_DIAGRAM",
        aliases_en=("smartphone display", "numeric sound-level", "speed warning display"),
    ),
    SubjectDefinition(
        "DNA_NUCLEIC_ACID",
        "DNA와 핵산",
        "DNA and nucleic acid",
        ("디엔에이", "핵산", "염기", "코돈"),
        "MICROSCOPIC_STRUCTURE",
        "PYTHON_SVG",
        "GENERIC_LABELLED_DIAGRAM",
        aliases_en=("dna", "rna", "codon", "nucleic acid"),
    ),
    SubjectDefinition(
        "EARLY_UNIVERSE",
        "초기 우주",
        "early universe",
        ("빅뱅", "우주의 탄생", "초기 우주", "우주 모형", "우주론"),
        "EARTH_SPACE",
        "PYTHON_SVG",
        "PARTICLE_SYSTEM",
        aliases_en=("big bang", "early-universe", "early universe", "expanding universe"),
    ),
    SubjectDefinition(
        "EARTH_GLOBE",
        "지구",
        "Earth globe",
        ("지구",),
        "EARTH_SPACE",
        "PYTHON_SVG",
        "ORBITAL_SYSTEM",
    ),
    SubjectDefinition(
        "EARTH_SYSTEM_INTERACTION",
        "지구계 상호 작용",
        "Earth system interaction",
        ("생물권", "지권", "수권", "기권의 상호", "권역 간"),
        "EARTH_SPACE",
        "PYTHON_SVG",
        "FLOW_DIAGRAM",
        aliases_en=("earth system interaction", "biosphere", "geosphere", "hydrosphere"),
    ),
    SubjectDefinition(
        "ELECTRODE", "전극", "electrode", ("전극",), "LAB_APPARATUS", "PYTHON_SVG", "APPARATUS"
    ),
    SubjectDefinition(
        "ELECTRIC_GRID",
        "송전과 변전",
        "electric power grid",
        ("변전소", "송전선", "송전탑"),
        "PHYSICAL_OBJECT",
        "PYTHON_SVG",
        "CIRCUIT",
        aliases_en=("substation", "transmission line", "power grid"),
    ),
    SubjectDefinition(
        "ELECTRONIC_COMPONENT",
        "전자 부품",
        "electronic component",
        ("전자 부품", "전자 소자", "반도체 소자", "LED등", "발광 다이오드"),
        "PHYSICAL_OBJECT",
        "PYTHON_SVG",
        "CIRCUIT",
        aliases_en=("electronic component", "semiconductor device", "led"),
    ),
    SubjectDefinition(
        "ENZYME_REACTION",
        "효소 반응",
        "enzyme reaction",
        ("카탈레이스", "과산화 수소", "효소 반응"),
        "ABSTRACT_SCIENCE_MODEL",
        "PYTHON_SVG",
        "FLOW_DIAGRAM",
        aliases_en=("enzyme reaction", "catalase", "hydrogen peroxide"),
    ),
    SubjectDefinition(
        "ECOSYSTEM_NETWORK",
        "생태계 관계",
        "ecosystem network",
        ("생산자", "소비자", "분해자", "생물적 요인", "비생물적 요인", "먹이사슬"),
        "LIVING_ORGANISM",
        "PYTHON_SVG",
        "FLOW_DIAGRAM",
        aliases_en=("ecosystem", "producer", "consumer", "decomposer", "food chain"),
    ),
    SubjectDefinition(
        "FOSSIL",
        "화석",
        "fossil",
        ("화석", "삼엽충", "암모나이트"),
        "EARTH_SPACE",
        "LORA_RASTER",
        None,
        _raster("a fossil specimen with visible surface texture"),
    ),
    SubjectDefinition(
        "GALAXY_NEBULA",
        "은하와 성운",
        "galaxy or nebula",
        ("은하", "성운", "초신성"),
        "EARTH_SPACE",
        "LORA_RASTER",
        None,
        _raster("a galaxy, nebula, or supernova remnant"),
    ),
    SubjectDefinition(
        "GRAPHENE_LATTICE",
        "그래핀 격자",
        "graphene lattice",
        ("그래핀", "흑연 층", "육각형 원자"),
        "ABSTRACT_SCIENCE_MODEL",
        "PYTHON_SVG",
        "PARTICLE_SYSTEM",
        aliases_en=("graphene", "hexagonal atom-network", "graphite layer"),
    ),
    SubjectDefinition(
        "GAS_PARTICLES",
        "기체 입자",
        "gas particles",
        ("기체",),
        "ABSTRACT_SCIENCE_MODEL",
        "PYTHON_SVG",
        "PARTICLE_SYSTEM",
    ),
    SubjectDefinition(
        "GEOLOGIC_PLATE",
        "지각판",
        "tectonic plate",
        ("해양판", "대륙판", "판의 경계", "판 경계"),
        "EARTH_SPACE",
        "PYTHON_SVG",
        "GEOLOGIC_SECTION",
    ),
    SubjectDefinition(
        "GEOLOGIC_ROCK",
        "암석",
        "rock texture",
        ("암석", "광물", "퇴적암", "화성암", "변성암"),
        "EARTH_SPACE",
        "LORA_RASTER",
        None,
        _raster("a natural rock or mineral specimen texture"),
    ),
    SubjectDefinition(
        "HUMAN_FIGURE",
        "사람",
        "anonymous human figure",
        ("사람", "인물", "선수"),
        "REAL_WORLD_SCENE",
        "PYTHON_SVG",
        "GENERIC_LABELLED_DIAGRAM",
        aliases_en=("human figure", "person figure"),
    ),
    SubjectDefinition(
        "HEAT_ENGINE",
        "열기관",
        "heat engine",
        ("열기관", "고열원", "저열원", "열량"),
        "ABSTRACT_SCIENCE_MODEL",
        "PYTHON_SVG",
        "FLOW_DIAGRAM",
        aliases_en=("heat engine", "hot reservoir", "cold reservoir"),
    ),
    SubjectDefinition(
        "ION_MODEL",
        "이온",
        "ion model",
        ("이온",),
        "ABSTRACT_SCIENCE_MODEL",
        "PYTHON_SVG",
        "PARTICLE_SYSTEM",
    ),
    SubjectDefinition(
        "LAB_BALANCE",
        "저울",
        "laboratory balance",
        ("저울", "전자저울"),
        "LAB_APPARATUS",
        "PYTHON_SVG",
        "APPARATUS",
    ),
    SubjectDefinition(
        "LAB_BURNER",
        "가열 장치",
        "laboratory burner",
        ("알코올램프", "가열 장치", "버너", "가열하는 실험"),
        "LAB_APPARATUS",
        "PYTHON_SVG",
        "APPARATUS",
    ),
    SubjectDefinition(
        "LAB_THERMOMETER",
        "온도계",
        "thermometer",
        ("온도계",),
        "LAB_APPARATUS",
        "PYTHON_SVG",
        "APPARATUS",
    ),
    SubjectDefinition(
        "LABORATORY_SETUP",
        "실험 장치",
        "laboratory apparatus setup",
        ("실험 장치", "실험기구"),
        "LAB_APPARATUS",
        "PYTHON_SVG",
        "APPARATUS",
    ),
    SubjectDefinition(
        "LANDSCAPE_TERRAIN",
        "지형과 경관",
        "landscape or terrain",
        ("절벽", "산맥", "폭포", "해안", "지형"),
        "EARTH_SPACE",
        "LORA_RASTER",
        None,
        _raster("a natural geological landscape or terrain"),
    ),
    SubjectDefinition(
        "LENS_OPTICS",
        "렌즈",
        "optical lens",
        ("렌즈",),
        "PHYSICAL_OBJECT",
        "PYTHON_SVG",
        "RAY_DIAGRAM",
    ),
    SubjectDefinition(
        "MAGNET",
        "자석",
        "magnet",
        ("자석", "자기장"),
        "PHYSICAL_OBJECT",
        "PYTHON_SVG",
        "VECTOR_FIELD",
    ),
    SubjectDefinition(
        "MEASURING_DEVICE",
        "측정 기구",
        "measuring instrument",
        ("측정기", "센서"),
        "LAB_APPARATUS",
        "PYTHON_SVG",
        "APPARATUS",
    ),
    SubjectDefinition(
        "MICROSCOPE",
        "현미경",
        "microscope",
        ("현미경",),
        "LAB_APPARATUS",
        "PYTHON_SVG",
        "APPARATUS",
    ),
    SubjectDefinition(
        "MICROSCOPIC_TISSUE",
        "현미경 조직",
        "microscopic biological tissue",
        ("조직", "현미경 사진", "현미경사진"),
        "MICROSCOPIC_STRUCTURE",
        "LORA_RASTER",
        None,
        _raster("a microscopic biological tissue texture"),
    ),
    SubjectDefinition(
        "MRI_SCANNER",
        "MRI 장치",
        "MRI scanner",
        ("MRI", "자기 공명 영상"),
        "PHYSICAL_OBJECT",
        "PYTHON_SVG",
        "APPARATUS",
        aliases_en=("mri scanner", "mri apparatus"),
    ),
    SubjectDefinition(
        "MIRROR_OPTICS",
        "거울",
        "optical mirror",
        ("거울",),
        "PHYSICAL_OBJECT",
        "PYTHON_SVG",
        "RAY_DIAGRAM",
    ),
    SubjectDefinition(
        "MOLECULE",
        "분자",
        "molecule",
        ("분자", "분자 구조", "공 모형", "입자 모형"),
        "ABSTRACT_SCIENCE_MODEL",
        "PYTHON_SVG",
        "PARTICLE_SYSTEM",
        aliases_en=("molecular-structure", "molecular structure", "molecule"),
    ),
    SubjectDefinition(
        "MOTION_SEQUENCE",
        "연속 운동 위치",
        "motion sequence",
        (
            "연속 위치",
            "시간 간격별 위치",
            "자유 낙하",
            "수평으로 던진",
            "수직으로 낙하",
            "격자 위",
            "공기 중 패널",
            "진공 중 패널",
            "깃털과 구슬",
            "수평면 위",
            "힘 F",
        ),
        "ABSTRACT_SCIENCE_MODEL",
        "PYTHON_SVG",
        "VECTOR_FIELD",
        aliases_en=("free fall", "falling positions", "motion sequence", "projectile positions"),
    ),
    SubjectDefinition(
        "MOON",
        "달",
        "Moon",
        ("달 표면", "달의 위상", "월식"),
        "EARTH_SPACE",
        "LORA_RASTER",
        None,
        _raster("the Moon or a cratered lunar surface"),
    ),
    SubjectDefinition(
        "NON_HUMAN_ANIMAL",
        "동물",
        "non-human animal",
        ("동물", "물고기", "새우", "조개", "곤충", "새의"),
        "LIVING_ORGANISM",
        "LORA_RASTER",
        None,
        _raster("a non-human animal specimen or silhouette"),
    ),
    SubjectDefinition(
        "OCEAN_WATER",
        "해양",
        "ocean and seawater",
        ("해양", "해수", "바다", "수온"),
        "EARTH_SPACE",
        "HYBRID",
        "MAP_BOUNDARY",
        _hybrid("an ocean or seawater scene"),
    ),
    SubjectDefinition(
        "ORBITAL_SYSTEM",
        "천체 궤도",
        "orbital system",
        ("공전", "자전", "궤도", "태양계"),
        "EARTH_SPACE",
        "PYTHON_SVG",
        "ORBITAL_SYSTEM",
    ),
    SubjectDefinition(
        "PERIODIC_TABLE",
        "주기율표",
        "periodic table",
        ("주기율표",),
        "ABSTRACT_SCIENCE_MODEL",
        "PYTHON_SVG",
        "CONTENT_TABLE",
    ),
    SubjectDefinition(
        "PIE_CHART",
        "원형 그래프",
        "pie chart",
        ("원형 그래프", "원 그래프", "원그래프", "도넛형 원", "원형 분할"),
        "ABSTRACT_SCIENCE_MODEL",
        "PYTHON_SVG",
        "AXIS_PLOT",
        aliases_en=("pie chart", "doughnut chart"),
    ),
    SubjectDefinition(
        "PLANT_ORGANISM",
        "식물",
        "plant organism",
        ("식물", "잎의", "뿌리", "줄기"),
        "LIVING_ORGANISM",
        "LORA_RASTER",
        None,
        _raster("a plant specimen or botanical structure"),
    ),
    SubjectDefinition(
        "PRISM_OPTICS",
        "프리즘",
        "optical prism",
        ("프리즘", "분광기"),
        "PHYSICAL_OBJECT",
        "PYTHON_SVG",
        "RAY_DIAGRAM",
    ),
    SubjectDefinition(
        "PROJECTILE_BALL",
        "공과 포물선 운동",
        "ball and projectile motion",
        ("포물선", "공의 운동", "공을", "공이", "발사체", "빨대"),
        "PHYSICAL_OBJECT",
        "PYTHON_SVG",
        "VECTOR_FIELD",
    ),
    SubjectDefinition(
        "PROTEIN_POLYMER",
        "단백질",
        "protein or polymer chain",
        ("단백질", "아미노산", "펩타이드"),
        "MICROSCOPIC_STRUCTURE",
        "PYTHON_SVG",
        "GENERIC_LABELLED_DIAGRAM",
    ),
    SubjectDefinition(
        "SAFETY_EQUIPMENT",
        "안전 장치",
        "safety equipment",
        ("안전장치", "안전 장치", "헬멧", "범퍼", "에어 매트", "타이어"),
        "PHYSICAL_OBJECT",
        "HYBRID",
        "GENERIC_LABELLED_DIAGRAM",
        _hybrid("protective equipment such as a helmet, bumper, tire, or landing mat"),
        aliases_en=(
            "safety equipment",
            "padded helmet",
            "car bumper",
            "landing mat",
            "protective packaging",
        ),
    ),
    SubjectDefinition(
        "SCIENCE_REPORT_PANEL",
        "과학 탐구 보고서",
        "science inquiry report panel",
        (
            "과학 탐구 보고서",
            "탐구 주제",
            "탐구 과정",
            "탐구 결과",
            "준비물",
            "실험 과정",
            "실험 그림",
            "순서도식",
        ),
        "ABSTRACT_SCIENCE_MODEL",
        "PYTHON_SVG",
        "CONTENT_TABLE",
        aliases_en=("science inquiry report", "materials, procedure, and result"),
    ),
    SubjectDefinition(
        "SEISMOMETER",
        "지진계",
        "seismometer",
        ("지진계", "회전 원통", "매달린 추"),
        "LAB_APPARATUS",
        "PYTHON_SVG",
        "APPARATUS",
        aliases_en=("seismometer", "rotating drum"),
    ),
    SubjectDefinition(
        "SIGNAL_WAVEFORM",
        "신호 파형",
        "signal waveform",
        ("신호", "펄스", "연속 신호", "불연속 신호"),
        "ABSTRACT_SCIENCE_MODEL",
        "PYTHON_SVG",
        "AXIS_PLOT",
        aliases_en=("signal plot", "continuous", "rectangular pulses"),
    ),
    SubjectDefinition(
        "SILICATE_STRUCTURE",
        "규산염 구조",
        "silicate structure",
        ("규산염", "사면체", "휘석", "각섬석", "단사슬"),
        "ABSTRACT_SCIENCE_MODEL",
        "PYTHON_SVG",
        "PARTICLE_SYSTEM",
        aliases_en=("silicate tetrahedron", "pyroxene", "amphibole"),
    ),
    SubjectDefinition(
        "SPECTRUM_PLOT",
        "스펙트럼",
        "spectrum plot",
        ("스펙트럼", "방출선", "흡수선", "파장"),
        "ABSTRACT_SCIENCE_MODEL",
        "PYTHON_SVG",
        "AXIS_PLOT",
        aliases_en=("spectrum", "emission-spectrum", "absorption-spectrum", "wavelength"),
    ),
    SubjectDefinition(
        "SOLAR_PANEL",
        "태양 전지판",
        "solar panel",
        ("태양 전지", "태양전지", "태양광 패널"),
        "PHYSICAL_OBJECT",
        "PYTHON_SVG",
        "GENERIC_LABELLED_DIAGRAM",
    ),
    SubjectDefinition(
        "SOLUTION_LIQUID",
        "용액",
        "solution or liquid",
        ("수용액", "용액", "증류수"),
        "LAB_APPARATUS",
        "PYTHON_SVG",
        "APPARATUS",
    ),
    SubjectDefinition(
        "SPACECRAFT",
        "우주선",
        "spacecraft",
        ("우주선", "위성", "탐사선"),
        "EARTH_SPACE",
        "HYBRID",
        "GENERIC_LABELLED_DIAGRAM",
        _hybrid("a spacecraft or artificial satellite"),
    ),
    SubjectDefinition(
        "SPRING", "용수철", "spring", ("용수철",), "PHYSICAL_OBJECT", "PYTHON_SVG", "VECTOR_FIELD"
    ),
    SubjectDefinition(
        "STAR_FIELD",
        "별과 항성",
        "star field",
        ("별빛", "항성", "별의 진화", "별 진화 단계", "별의 스펙트럼"),
        "EARTH_SPACE",
        "LORA_RASTER",
        None,
        _raster("a sparse astronomical star field"),
    ),
    SubjectDefinition(
        "STELLAR_INTERIOR",
        "별 내부 구조",
        "stellar interior",
        ("별 내부", "별의 내부", "동심원 별", "동심층", "중심핵"),
        "EARTH_SPACE",
        "PYTHON_SVG",
        "ORBITAL_SYSTEM",
        aliases_en=("stellar interior", "concentric stellar layers"),
    ),
    SubjectDefinition(
        "STUDENT_OR_TEACHER",
        "학생과 교사",
        "anonymous student or teacher figure",
        ("학생", "교사", "선생"),
        "REAL_WORLD_SCENE",
        "PYTHON_SVG",
        "GENERIC_LABELLED_DIAGRAM",
        aliases_en=("student figure", "teacher figure", "student"),
    ),
    SubjectDefinition(
        "SUN", "태양", "Sun", ("태양", "일식"), "EARTH_SPACE", "PYTHON_SVG", "ORBITAL_SYSTEM"
    ),
    SubjectDefinition(
        "SUPERCONDUCTING_CABLE",
        "초전도 전력 케이블",
        "superconducting power cable",
        ("초전도 전력 케이블", "초전도 케이블", "액체 질소", "절연층"),
        "PHYSICAL_OBJECT",
        "PYTHON_SVG",
        "APPARATUS",
        aliases_en=("superconducting power cable",),
    ),
    SubjectDefinition(
        "SYRINGE", "주사기", "syringe", ("주사기",), "LAB_APPARATUS", "PYTHON_SVG", "APPARATUS"
    ),
    SubjectDefinition(
        "TEST_TUBE", "시험관", "test tube", ("시험관",), "LAB_APPARATUS", "PYTHON_SVG", "APPARATUS"
    ),
    SubjectDefinition(
        "VEHICLE_CAR",
        "자동차",
        "car",
        ("자동차", "전기차", "승용차", "범퍼"),
        "PHYSICAL_OBJECT",
        "PYTHON_SVG",
        "VECTOR_FIELD",
    ),
    SubjectDefinition(
        "VENN_DIAGRAM",
        "벤 다이어그램",
        "Venn diagram",
        ("벤 다이어그램", "원이 겹친", "공통 영역"),
        "ABSTRACT_SCIENCE_MODEL",
        "PYTHON_SVG",
        "GENERIC_LABELLED_DIAGRAM",
        aliases_en=("venn diagram", "overlapping circles"),
    ),
    SubjectDefinition(
        "VOLCANO",
        "화산",
        "volcano",
        ("화산", "마그마", "용암"),
        "EARTH_SPACE",
        "HYBRID",
        "GEOLOGIC_SECTION",
        _hybrid("a volcano or volcanic landscape"),
    ),
    SubjectDefinition(
        "WATER_CYCLE",
        "물의 순환",
        "water cycle",
        ("물의 순환", "물 순환"),
        "EARTH_SPACE",
        "PYTHON_SVG",
        "FLOW_DIAGRAM",
    ),
)

_DEFINITIONS_BY_KEY = {definition.key: definition for definition in SUBJECT_DEFINITIONS}
if len(_DEFINITIONS_BY_KEY) != len(SUBJECT_DEFINITIONS):
    raise RuntimeError("SCIENCE_VISUAL_SUBJECT_DEFINITION_DUPLICATE")


def _contains_alias(text: str, alias: str) -> bool:
    # Korean case particles are attached to nouns, so ASCII-style word boundaries lose real
    # matches (for example ``비커에``). The curated aliases deliberately exclude ambiguous
    # one-syllable tokens; direct membership is therefore both simpler and more complete.
    return alias in text


def _fallback_definition(representation_kind: str, rendering_mode: str) -> SubjectDefinition:
    if representation_kind == "TABLE":
        return SubjectDefinition(
            "DATA_TABLE",
            "자료 표",
            "data table",
            ("자료 표",),
            "ABSTRACT_SCIENCE_MODEL",
            "PYTHON_SVG",
            "CONTENT_TABLE",
        )
    if representation_kind in {"BAR_GRAPH", "LINE_GRAPH", "SCATTER_PLOT"}:
        return SubjectDefinition(
            "DATA_PLOT",
            "자료 그래프",
            "data plot",
            ("자료 그래프",),
            "ABSTRACT_SCIENCE_MODEL",
            "PYTHON_SVG",
            "AXIS_PLOT",
        )
    if representation_kind == "FLOW":
        return SubjectDefinition(
            "PROCESS_FLOW",
            "과정 흐름",
            "process flow",
            ("과정 흐름",),
            "ABSTRACT_SCIENCE_MODEL",
            "PYTHON_SVG",
            "FLOW_DIAGRAM",
        )
    if representation_kind == "TIMELINE":
        return SubjectDefinition(
            "TIMELINE",
            "시간 순서",
            "timeline",
            ("시간 순서",),
            "ABSTRACT_SCIENCE_MODEL",
            "PYTHON_SVG",
            "TIMELINE",
        )
    if representation_kind == "APPARATUS":
        return SubjectDefinition(
            "GENERIC_LAB_APPARATUS",
            "기타 실험 장치",
            "other laboratory apparatus",
            ("기타 실험 장치",),
            "LAB_APPARATUS",
            "PYTHON_SVG",
            "APPARATUS",
        )
    if representation_kind == "PARTICLE_MODEL":
        return SubjectDefinition(
            "GENERIC_PARTICLE_MODEL",
            "기타 입자 모형",
            "other particle model",
            ("기타 입자 모형",),
            "ABSTRACT_SCIENCE_MODEL",
            "PYTHON_SVG",
            "PARTICLE_SYSTEM",
        )
    if representation_kind == "MAP":
        return SubjectDefinition(
            "GENERIC_SCIENCE_MAP",
            "과학 지도",
            "science map",
            ("과학 지도",),
            "EARTH_SPACE",
            "PYTHON_SVG",
            "MAP_BOUNDARY",
        )
    if representation_kind == "CROSS_SECTION":
        return SubjectDefinition(
            "GENERIC_CROSS_SECTION",
            "과학 단면도",
            "science cross section",
            ("과학 단면도",),
            "ABSTRACT_SCIENCE_MODEL",
            "PYTHON_SVG",
            "GENERIC_LABELLED_DIAGRAM",
        )
    if representation_kind == "PHOTOGRAPH" or rendering_mode == "RASTER":
        return SubjectDefinition(
            "UNCLASSIFIED_RASTER_SUBJECT",
            "미분류 래스터 대상",
            "unclassified raster subject",
            ("미분류 래스터 대상",),
            "REAL_WORLD_SCENE",
            "BLOCKED",
            None,
            blocked_reason="NO_SAFE_RENDER_ROUTE",
        )
    return SubjectDefinition(
        "GENERIC_SCIENCE_DIAGRAM",
        "기타 과학 도식",
        "other science diagram",
        ("기타 과학 도식",),
        "ABSTRACT_SCIENCE_MODEL",
        "PYTHON_SVG",
        "GENERIC_LABELLED_DIAGRAM",
    )


def classify_science_visual_subjects(
    *,
    composition_summary: str,
    reconstruction_guidance: str,
    representation_kind: str,
    rendering_mode: str,
) -> tuple[SubjectDefinition, ...]:
    """Return stable subject definitions for one visual observation."""

    if representation_kind == "NONE" or rendering_mode == "TEXT_ONLY":
        return ()
    source_text = f"{composition_summary} {reconstruction_guidance}"
    source_text_casefolded = source_text.casefold()
    matched = tuple(
        definition
        for definition in SUBJECT_DEFINITIONS
        if any(_contains_alias(source_text, alias) for alias in definition.aliases_ko)
        or any(alias.casefold() in source_text_casefolded for alias in definition.aliases_en)
    )
    return matched or (_fallback_definition(representation_kind, rendering_mode),)


def _reference(
    source: AcceptedVisualSubjectSource,
    *,
    item_revision_id: str,
    item_proposal_id: str,
    pattern: AssessmentVisualPatternObservation,
) -> ScienceVisualSubjectSourceReference:
    visual_pattern_id = pattern.pattern_id
    source_anchor_ids = tuple(sorted(pattern.source_anchor_ids))
    return ScienceVisualSubjectSourceReference(
        item_revision_id=item_revision_id,
        accepted_analysis_result=source.accepted_result,
        extraction_result=source.extraction_result,
        item_proposal_id=item_proposal_id,
        visual_pattern_id=visual_pattern_id,
        source_anchor_ids=source_anchor_ids,
        representation_kind=pattern.representation_kind,
        rendering_mode=pattern.rendering_mode,
        composition_summary_sha256=text_sha256(pattern.composition_summary),
        reconstruction_guidance_sha256=text_sha256(pattern.reconstruction_guidance),
    )


def project_science_visual_subject_inventory(
    *,
    sources: tuple[AcceptedVisualSubjectSource, ...],
    training_authorization: ImageEvaluationArtifactMember,
    pattern_inventory: ImageEvaluationArtifactMember,
    target_set_sha256: str,
    created_at: datetime,
    created_by: str,
) -> LocalImageScienceVisualSubjectInventory:
    """Build one immutable, closed subject inventory from exact accepted sources."""

    if tuple(source.accepted.source.item_revision_id for source in sources) != tuple(
        sorted({source.accepted.source.item_revision_id for source in sources})
    ):
        raise ScienceVisualSubjectProjectionError("SCIENCE_VISUAL_SUBJECT_SOURCE_SET_INVALID")
    definitions: dict[str, SubjectDefinition] = dict(_DEFINITIONS_BY_KEY)
    references: dict[str, dict[tuple[str, str, str], ScienceVisualSubjectSourceReference]] = {}
    omissions: list[ScienceVisualSubjectOmission] = []
    source_observations: set[tuple[str, str, str]] = set()

    for source in sources:
        accepted_source = source.accepted.source
        if (
            source.extraction.extraction_result_id != accepted_source.extraction_result_id
            or source.extraction.result_sha256 != accepted_source.extraction_result_sha256
        ):
            raise ScienceVisualSubjectProjectionError(
                "SCIENCE_VISUAL_SUBJECT_SOURCE_POINTER_MISMATCH"
            )
        items = tuple(
            item
            for item in source.extraction.items
            if item.item_proposal_id == accepted_source.item_proposal_id
            and item.item_number == accepted_source.item_number
        )
        if len(items) != 1:
            raise ScienceVisualSubjectProjectionError(
                "SCIENCE_VISUAL_SUBJECT_ITEM_PROPOSAL_UNRESOLVED"
            )
        item = items[0]
        for pattern in item.visual_patterns:
            observation_key = (
                accepted_source.item_revision_id,
                item.item_proposal_id,
                pattern.pattern_id,
            )
            if observation_key in source_observations:
                raise ScienceVisualSubjectProjectionError(
                    "SCIENCE_VISUAL_SUBJECT_OBSERVATION_DUPLICATE"
                )
            source_observations.add(observation_key)
            if pattern.representation_kind == "NONE" or pattern.rendering_mode == "TEXT_ONLY":
                omissions.append(
                    ScienceVisualSubjectOmission(
                        item_revision_id=accepted_source.item_revision_id,
                        item_proposal_id=item.item_proposal_id,
                        visual_pattern_id=pattern.pattern_id,
                        reason=(
                            "NO_RENDERED_SUBJECT"
                            if pattern.representation_kind == "NONE"
                            else "TEXT_ONLY_PATTERN"
                        ),
                    )
                )
                continue
            matched = classify_science_visual_subjects(
                composition_summary=pattern.composition_summary,
                reconstruction_guidance=pattern.reconstruction_guidance,
                representation_kind=pattern.representation_kind,
                rendering_mode=pattern.rendering_mode,
            )
            for definition in matched:
                definitions.setdefault(definition.key, definition)
            reference = _reference(
                source,
                item_revision_id=accepted_source.item_revision_id,
                item_proposal_id=item.item_proposal_id,
                pattern=pattern,
            )
            for definition in matched:
                references.setdefault(definition.key, {})[reference.observation_key] = reference

    subjects: list[ScienceVisualSubject] = []
    for key in sorted(references):
        definition = definitions[key]
        subject_id = "imgscisubject_" + content_sha256(key).removeprefix("sha256:")[:32]
        subjects.append(
            ScienceVisualSubject(
                subject_id=subject_id,
                subject_key=key,
                label_ko=definition.label_ko,
                label_en=definition.label_en,
                aliases_ko=tuple(sorted(set(definition.aliases_ko))),
                family=definition.family,
                render_route=definition.route,
                renderer_primitive=definition.primitive,
                raster_prompt_en=definition.raster_prompt_en,
                raster_prompt_sha256=(
                    None
                    if definition.raster_prompt_en is None
                    else text_sha256(definition.raster_prompt_en)
                ),
                blocked_reason=definition.blocked_reason,
                references=tuple(references[key][value] for value in sorted(references[key])),
            )
        )

    identity_body = {
        "training_authorization_revision_id": training_authorization.artifact_revision_id,
        "pattern_inventory_revision_id": pattern_inventory.artifact_revision_id,
        "target_set_sha256": target_set_sha256,
        "subject_definition_keys": tuple(subject.subject_key for subject in subjects),
    }
    identity = content_sha256(identity_body).removeprefix("sha256:")
    body = {
        "schema_version": "local-image-science-visual-subject-inventory/1.0",
        "inventory_id": f"imgscisubjectinventory_{identity[:32]}",
        "inventory_revision_id": f"imgscisubjectinventoryrev_{identity[32:64]}",
        "revision_number": 1,
        "previous_revision_id": None,
        "training_authorization": training_authorization.model_dump(mode="json"),
        "pattern_inventory": pattern_inventory.model_dump(mode="json"),
        "target_set_sha256": target_set_sha256,
        "source_item_count": len(sources),
        "source_visual_observation_count": len(source_observations),
        "covered_visual_observation_count": len(source_observations) - len(omissions),
        "subjects": tuple(subject.model_dump(mode="json") for subject in subjects),
        "omissions": tuple(
            omission.model_dump(mode="json")
            for omission in sorted(omissions, key=lambda value: value.observation_key)
        ),
        "created_at": created_at.isoformat().replace("+00:00", "Z"),
        "created_by": created_by,
    }
    return LocalImageScienceVisualSubjectInventory.model_validate(
        {**body, "inventory_sha256": content_sha256(body)}
    )
