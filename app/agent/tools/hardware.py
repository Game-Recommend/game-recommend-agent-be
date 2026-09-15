"""가격·하드웨어 담당 Tool: 후보의 최소 요구 사양 조회와 사용자 PC 호환 판정.

사용자 사양(`HardwareSpecs`)은 LLM이 넘기지 않고 `ctx.conditions.hardware`를 서버가 주입한다.
판정 규칙(메모리 숫자 비교, GPU·CPU LLM 판정)은 팀원 모듈 `app/tools/hardware.py`와
클라이언트에 있다.
"""

from langchain.tools import ToolRuntime, tool

from app.agent.context import AgentContext
from app.schemas.hardware import HardwareResult, RequirementSpec

STAGE = "하드웨어"


def compact_spec(spec: RequirementSpec | None) -> str | None:
    if spec is None:
        return None
    parts = [
        f"{label} {value}"
        for label, value in (
            ("OS", spec.os),
            ("CPU", spec.cpu),
            ("GPU", spec.gpu),
            ("RAM", f"{spec.ram_gb:g}GB" if spec.ram_gb else None),
        )
        if value
    ]
    return ", ".join(parts) if parts else spec.raw_text[:200]


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
async def assess_hardware(igdb_ids: list[int], runtime: ToolRuntime[AgentContext]) -> str:
    """후보 게임의 최소 요구 사양을 조회하고, 사용자가 말한 PC 사양으로 실행 가능한지 판정한다.

    - search_games가 돌려준 igdb_id만 넘긴다. 후보 전체를 한 번에 넘기면 한 번의 호출로 끝난다.
    - 사용자 PC 사양은 서버가 알고 있으므로 인자로 넘기지 않는다.
    - status: met=사양 충족, unmet=미달, unknown=비교 근거 없음,
      skipped=사용자가 사양을 말하지 않음.
      unmet과 unknown인 게임은 추천할 수 없다. 요구 사양 문자열만 보고 스스로 판정하지 않는다.
    - 사양 조건이 없어도 답변과 카드에 최소 사양이 쓰이므로 추천 후보를 정하기 전에 호출한다.
    """
    ctx = runtime.context
    return await ctx.run_stage(STAGE, assess(ctx, igdb_ids))
