"""가격·하드웨어 담당: GPU·CPU 요구 사양과 사용자 PC를 비교하는 판정기.

메모리는 숫자 비교로 끝나지만 "GTX 1060 or better" 같은 GPU·CPU 문자열은 등급표가 필요하다.
등급표를 직접 관리하는 대신 LLM에 판정을 맡기고, 판정은 후보 전체를 한 번에 요청한다.

LLM은 부품별 met/unmet/unknown과 짧은 근거만 내고, 어떤 부품을 비교할지(compare)·전체 판정·
이유 문장은 코드가 정한다. v1에서 LLM이 최종 문장을 자유롭게 쓰게 했더니 GPU만 보고 통과시키거나,
미달 판정에 "이상입니다"라고 쓰거나, 프롬프트 예시의 부품명을 사용자 부품처럼 베끼는 문제가 있었다.
"""

import json
import logging
from typing import Literal, Protocol

from openai import AsyncOpenAI
from pydantic import BaseModel

from app.schemas.common import Language
from app.schemas.hardware import HardwareAssessment, HardwareSpecs, RequirementSpec

logger = logging.getLogger(__name__)

Component = Literal["gpu", "cpu"]
COMPONENT_LABELS: dict[Component, str] = {"gpu": "GPU", "cpu": "CPU"}
# 이유 문장의 고정 낱말. 부품명·요구 사양은 입력에서, note는 LLM 출력에서 온다
MINIMUM_LABELS: dict[Language, str] = {"ko": "최소", "en": "minimum"}
STATUS_LABELS: dict[Language, dict[str, str]] = {
    "ko": {"met": "충족", "unmet": "미달", "unknown": "판단 불가"},
    "en": {"met": "met", "unmet": "not met", "unknown": "undetermined"},
}
# note를 쓸 언어. 판정기 프롬프트에서 요청마다 바뀌는 자리는 이것뿐이다
NOTE_LANGUAGES: dict[Language, str] = {"ko": "한국어", "en": "영어"}


class JudgeRequest(BaseModel):
    igdb_id: int
    name: str
    requirement: RequirementSpec
    components: list[Component]  # 사용자와 게임 양쪽에 값이 있어 비교할 수 있는 항목


class SpecJudge(Protocol):
    async def judge(
        self,
        hardware: HardwareSpecs,
        requests: list[JudgeRequest],
        *,
        language: Language = "ko",
    ) -> list[HardwareAssessment]:
        """게임별 met/unmet/unknown. 확신이 없으면 unknown이며, 결과가 없는 게임은 생략한다.

        reason은 language로 쓴다.
        """
        ...


_PROMPT_TEMPLATE = """당신은 PC 게임의 최소 요구 사양과 사용자 PC 부품을 비교하는 판정기입니다.

입력: user_hardware(사용자 부품)와 games 목록. 게임마다 igdb_id, name, minimum(최소 요구 사양),
compare(이 게임에서 비교할 항목: "gpu", "cpu")가 있습니다.
출력: 게임마다 igdb_id와, compare에 있는 항목별 {component, status, note}.

판정 규칙:
- 게임마다 그 게임의 minimum만 보고 판정합니다. 다른 게임의 요구 사양을 참고하거나 섞지 않습니다.
- compare에 있는 항목은 반드시 출력하고, 없는 항목은 출력하지 않습니다.
- status: met = 사용자 부품 성능이 최소 요구 이상, unmet = 미달, unknown = 판단 불가.
- 최소 요구가 "A or B", "A / B"처럼 여러 개면 그중 가장 낮은 것과 비교합니다.
- 최소 요구가 특정 모델이 아니라 기능 요건(DirectX 11, Shader Model, VRAM 1GB 등)이면
  사용자 부품이 그 기능을 갖추면 met입니다. 최신 내장 그래픽도 해당하면 met입니다.
- 최소 요구가 "고성능 그래픽카드", "최신 CPU"처럼 비교 기준이 없으면 unknown입니다.
- 사용자 부품이 GeForce, Radeon, Arc, Core, Ryzen처럼 알려진 제품 계열이 아니거나
  세대·등급을 알 수 없으면 unknown입니다. 모르는 이름을 성능이 낮다고 추측해 unmet을 주지 않습니다.
- VRAM 미달(unmet)은 사용자 부품에 요구보다 작은 용량이 명시된 경우에만 판정합니다
  (예: 사용자 "GTX 1060 3GB", 요구 "GTX 1060 6GB"). 용량이 적혀 있지 않으면 그 모델의
  표준 용량으로 봅니다.
- 노트북(Laptop, Mobile, Max-Q) GPU는 데스크톱 동명 모델보다 낮게 봅니다.
  데스크톱 모델을 요구하고 확신이 없으면 unknown입니다.
- 세대 차이가 크면 최신 부품이 구형 최소 요구를 충족하는 것으로 봅니다
  (예: 12세대 노트북 CPU i5-1240P는 8세대 데스크톱 i5-8400 최소 요구 이상).
- note는 {note_language} 한 구절(30자 이내)로 두 부품의 상대 등급만 적습니다.
  입력에 없는 부품명을 지어내지 않습니다.
"""


def build_system_prompt(language: Language = "ko") -> str:
    """판정기 프롬프트. note 언어만 요청마다 바뀐다.

    본문에 `{component, status, note}`가 있어 str.format 대신 자리 하나만 바꾼다.
    """
    return _PROMPT_TEMPLATE.replace("{note_language}", NOTE_LANGUAGES[language])


# 기본(한국어) 프롬프트. 평가 스크립트가 이 해시를 실행 기록에 남긴다
SYSTEM_PROMPT = build_system_prompt("ko")


class _ComponentVerdict(BaseModel):
    component: Component
    status: Literal["met", "unmet", "unknown"]
    note: str


class _Verdict(BaseModel):
    igdb_id: int
    components: list[_ComponentVerdict]


class _JudgeOutput(BaseModel):
    verdicts: list[_Verdict]


def compose_assessment(
    request: JudgeRequest,
    hardware: HardwareSpecs,
    verdict: _Verdict | None,
    language: Language = "ko",
) -> HardwareAssessment:
    """부품별 판정을 전체 판정과 이유 문장으로 합친다.

    부품명·요구 사양 같은 사실은 입력에서만 가져오고 LLM 출력에서는 status와 note만 쓴다.
    """
    by_component = {c.component: c for c in verdict.components} if verdict else {}
    statuses: list[str] = []
    parts: list[str] = []
    for component in request.components:
        user_value = getattr(hardware, component)
        required = getattr(request.requirement, component)
        result = by_component.get(component)
        status = result.status if result else "unknown"
        statuses.append(status)
        note = f" ({result.note})" if result and result.note else ""
        parts.append(
            f"{COMPONENT_LABELS[component]} {user_value} vs {MINIMUM_LABELS[language]} "
            f"'{required}' → {STATUS_LABELS[language][status]}{note}"
        )
    if "unmet" in statuses:
        overall = "unmet"
    elif "unknown" in statuses:
        overall = "unknown"
    else:
        overall = "met"
    return HardwareAssessment(
        igdb_id=request.igdb_id,
        status=overall,
        reason="; ".join(parts),
        requirement=request.requirement,
    )


class OpenAISpecJudge:
    def __init__(self, client: AsyncOpenAI, model: str):
        self.client = client
        self.model = model

    async def judge(
        self,
        hardware: HardwareSpecs,
        requests: list[JudgeRequest],
        *,
        language: Language = "ko",
    ) -> list[HardwareAssessment]:
        if not requests:
            return []
        payload = {
            "user_hardware": hardware.model_dump(include={"gpu", "cpu"}, exclude_none=True),
            "games": [
                {
                    "igdb_id": request.igdb_id,
                    "name": request.name,
                    "minimum": request.requirement.model_dump(
                        include=set(request.components), exclude_none=True
                    ),
                    "compare": request.components,
                }
                for request in requests
            ],
        }
        response = await self.client.responses.parse(
            model=self.model,
            instructions=build_system_prompt(language),
            input=json.dumps(payload, ensure_ascii=False),
            text_format=_JudgeOutput,
        )
        output = response.output_parsed
        if output is None:
            logger.warning("Spec judge returned no parsed output (model=%s)", self.model)
            return []
        verdicts = {v.igdb_id: v for v in output.verdicts}
        return [
            compose_assessment(r, hardware, verdicts.get(r.igdb_id), language) for r in requests
        ]
