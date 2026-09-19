"""가격·하드웨어 담당 Tool: 후보의 원화 가격과 예산 판정. 다른 Tool 파일이 따라 할 참조 예시다.

구조
- `fetch_prices(ctx, igdb_ids)`가 실제 일을 한다. 테스트 대상이고, 러너의 안전망도
  이 함수를 직접 부른다.
- `get_prices`는 LLM에 노출되는 LangChain Tool이다. docstring이 곧 LLM이 읽는 사용 설명서이므로
  언제 부르고 언제 부르지 말지, 결과를 어떻게 해석할지 적는다. 조회 대상은 LLM이 넘긴 id가 아니라
  후보 전체다(`CandidateStore.all_ids`).
- 예산은 LLM이 넘기지 않는다. `ctx.conditions.max_price_krw`를 서버가 주입한다.
- LLM에는 압축 dict만 돌려주고, 응답용 `PriceResult`는 `ctx.store.prices`에 쌓는다.
"""

from langchain.tools import ToolRuntime, tool

from app.agent.context import AgentContext
from app.schemas.price import PriceResult

STAGE = "가격"


def compact_price(result: PriceResult) -> dict:
    return {
        "igdb_id": result.igdb_id,
        "amount_krw": result.quote.amount_krw if result.quote is not None else None,
        "status": result.check.status,
        "reason": result.check.reason,
    }


async def fetch_prices(ctx: AgentContext, igdb_ids: list[int]) -> dict:
    games = ctx.store.resolve(igdb_ids)
    results = await ctx.tools.price.run(games, ctx.conditions.max_price_krw)
    ctx.store.prices.update(results)
    return {
        "budget_krw": ctx.conditions.max_price_krw,
        "prices": [compact_price(results[game.igdb_id]) for game in games],
    }


@tool("get_prices")
async def get_prices(
    runtime: ToolRuntime[AgentContext], igdb_ids: list[int] | None = None
) -> str:
    """후보 게임의 한국 스토어 원화 가격을 조회하고 예산 조건을 판정한다.

    - 서버가 search_games가 돌려준 후보 전체를 조회한다. igdb_ids는 비워도 되고, 넘겨도 결과는
      후보 전체다. 한 번만 부르면 된다.
    - 예산은 서버가 알고 있으므로 인자로 넘기지 않는다.
    - status: met=예산 이하, unmet=예산 초과 또는 구매 불가, unknown=가격 확인 불가,
      skipped=예산 조건 없음.
      unmet과 unknown인 게임은 추천할 수 없다.
    - 예산 조건이 없어도 답변과 카드에 가격이 쓰이므로 추천 후보를 정하기 전에 반드시 호출한다.
      amount_krw가 null이면 가격을 지어내지 말고 확인하지 못했다고 쓴다.
    """
    ctx = runtime.context
    return await ctx.run_stage(STAGE, fetch_prices(ctx, ctx.store.all_ids()))
