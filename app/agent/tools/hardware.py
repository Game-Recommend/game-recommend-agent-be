"""가격·하드웨어 담당 Tool: 후보의 최소 요구 사양 조회와 사용자 PC 호환 판정.

사용자 사양(`HardwareSpecs`)은 LLM이 넘기지 않고 `ctx.conditions.hardware`를 서버가 주입한다.
판정 규칙(메모리 숫자 비교, GPU·CPU LLM 판정)은 팀원 모듈 `app/tools/hardware.py`와
클라이언트에 있다.
"""

from langchain.tools import ToolRuntime, tool

from app.agent.context import AgentContext
from app.schemas.hardware import HardwareResult, RequirementSpec

STAGE = "하드웨어"

FIELD_LIMIT = 60  # CPU·GPU는 "A 또는 B 이상" 나열이 길다. 판정은 이미 끝났으니 표시용으로만 남긴다
RAW_LIMIT = 200  # 항목 추출에 실패했을 때만 쓰는 원문


def clip(value: str, limit: int) -> str:
    """LLM에 넘길 길이로 자른다. 자른 자리는 …로 표시해 잘렸음을 알린다."""
    value = " ".join(value.split())
    return value if len(value) <= limit else value[: limit - 1].rstrip() + "…"


def compact_spec(spec: RequirementSpec | None) -> str | None:
    """요구 사양을 "OS ..., CPU ..., RAM 8GB" 한 줄로 줄인다. 쓸 내용이 없으면 None이다."""
    if spec is None:
        return None
    parts = [
        f"{label} {clip(value, FIELD_LIMIT)}"
        for label, value in (
            ("OS", spec.os),
            ("CPU", spec.cpu),
            ("GPU", spec.gpu),
            ("RAM", f"{spec.ram_gb:g}GB" if spec.ram_gb else None),
        )
        if value
    ]
    if parts:
        return ", ".join(parts)
    return clip(spec.raw_text, RAW_LIMIT) or None


def compact_hardware(result: HardwareResult) -> dict:
    return {
        "igdb_id": result.igdb_id,
        "minimum": compact_spec(result.requirement),
        "status": result.check.status,
        "reason": result.check.reason,
    }


async def assess(ctx: AgentContext, igdb_ids: list[int]) -> dict:
    games = ctx.store.resolve(igdb_ids)
    results = await ctx.tools.hardware.run(games, ctx.conditions.hardware)
    ctx.store.hardware.update(results)
    return {
        "user_hardware": ctx.conditions.hardware.model_dump(exclude_none=True)
        if ctx.conditions.hardware is not None
        else None,
        "assessments": [compact_hardware(results[game.igdb_id]) for game in games],
    }


@tool("assess_hardware")
async def assess_hardware(
    runtime: ToolRuntime[AgentContext], igdb_ids: list[int] | None = None
) -> str:
    """후보 게임의 최소 요구 사양을 조회하고, 사용자가 말한 PC 사양으로 실행 가능한지 판정한다.

    - 서버가 search_games가 돌려준 후보 전체를 조회한다. igdb_ids는 비워도 되고, 넘겨도 결과는
      후보 전체다. 한 번만 부르면 된다.
    - 사용자 PC 사양은 서버가 알고 있으므로 인자로 넘기지 않는다.
    - status: met=사양 충족, unmet=미달, unknown=비교 근거 없음,
      skipped=사용자가 사양을 말하지 않음.
      unmet과 unknown인 게임은 추천할 수 없다. 요구 사양 문자열만 보고 스스로 판정하지 않는다.
    - 사양 조건이 없어도 답변과 카드에 최소 사양이 쓰이므로 추천 후보를 정하기 전에 호출한다.
    """
    ctx = runtime.context
    return await ctx.run_stage(STAGE, assess(ctx, ctx.store.all_ids()))
