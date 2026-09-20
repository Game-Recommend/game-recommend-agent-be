"""리뷰 담당 Tool: 선택한 후보의 Steam 리뷰를 모아 한줄평을 만든다.

느리고 비용이 드는 도구라 description에서 "최종 추천 후보에만" 부르도록 안내한다.
실제 수집·요약은 팀원 모듈 `app/tools/review_summary.py`(→ `SteamReviewSummaryClient`)가 한다.

"평가 좋은 게임" 조건은 이 Tool이 아니라 get_review_scores(review_score.py)가 맡는다. 여기는 고른
뒤 카드에 쓰는 문장이고, 그쪽은 고르는 데 쓰는 수치다.
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
    """최종 추천 후보의 Steam 사용자 리뷰를 수집해 한국어 한줄평으로 요약한다.

    가격과 사양 등 필수 조건을 확인한 뒤 최종 추천을 결정하는 단계에서만 호출한다.
    리뷰 수집과 LLM 요약에 시간이 걸리고 비용이 발생하므로 검색된 전체 후보에는 호출하지 않는다.

    입력:
    - igdb_ids: 리뷰를 확인할 최종 후보 게임의 IGDB ID 목록.
    - 가격·사양 조건을 통과한 후보만 전달한다.

    결과:
    - igdb_id: 게임의 IGDB ID
    - name: 게임 이름
    - summary: Steam 사용자 리뷰를 바탕으로 만든 약 100자 한국어 한줄평
    - summary가 null이면 Steam 리뷰를 확보하지 못한 것이므로 내용을 추측하지 않는다.
    """
    ctx = runtime.context
    return await ctx.run_stage(STAGE, summarize(ctx, igdb_ids))
