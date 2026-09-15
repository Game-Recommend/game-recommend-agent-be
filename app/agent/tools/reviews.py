"""리뷰 담당 Tool: 선택한 후보의 Steam 리뷰를 모아 한줄평을 만든다.

느리고 비용이 드는 도구라 description에서 "최종 추천 후보에만" 부르도록 안내한다.
실제 수집·요약은 팀원 모듈 `app/tools/review_summary.py`(→ `SteamReviewSummaryClient`)가 한다.

TODO(리뷰 담당): description을 다듬고, 에이전트가 "평가 좋은 게임" 조건에 쓸 수 있는 긍정 비율 같은
압축 필드를 검토한다(ReviewSummary 모델 확장은 리뷰 담당 결정).
"""

from langchain.tools import ToolRuntime, tool

from app.agent.context import AgentContext

STAGE = "리뷰 요약"


async def summarize(ctx: AgentContext, igdb_ids: list[int]) -> dict:
    games = ctx.store.resolve(igdb_ids)
    results = await ctx.tools.review_summary.run(games)
    ctx.store.reviews.update(results)
    return {
        "reviews": [
            {
                "igdb_id": game.igdb_id,
                "name": game.name,
                "summary": results[game.igdb_id].summary if game.igdb_id in results else None,
            }
            for game in games
        ]
    }


@tool("summarize_reviews")
async def summarize_reviews(igdb_ids: list[int], runtime: ToolRuntime[AgentContext]) -> str:
    """게임의 Steam 사용자 리뷰를 모아 100자 내외 한국어 한줄평을 만든다.

    - 최종 추천할 후보에만 호출한다. 게임당 수 초와 LLM 비용이 들므로 후보 전체에 부르지 않는다.
    - 가격·사양 판정을 통과한 게임의 igdb_id만 넘긴다. 사용자가 "평가 좋은 게임"처럼 리뷰를 조건으로
      말했으면 통과 후보를 요청 개수보다 조금 넓게 넣어 비교한 뒤 고른다.
    - summary가 null이면 Steam에 없는 게임 등으로 리뷰를 확보하지 못한 것이다.
      리뷰를 지어내지 않는다.
    """
    ctx = runtime.context
    return await ctx.run_stage(STAGE, summarize(ctx, igdb_ids))
