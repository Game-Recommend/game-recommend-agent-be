"""리뷰 점수 Tool: Steam 사용자 리뷰 통계를 조회해 후보 게임의 평가 지표를 제공한다."""

from langchain.tools import ToolRuntime, tool

from app.agent.context import AgentContext
from app.schemas.review import ReviewScore

STAGE = "리뷰 점수"


def compact_review_score(result: ReviewScore) -> dict:
    """LLM에 전달할 리뷰 점수 정보를 압축한다."""
    return {
        "igdb_id": result.igdb_id,
        "total_reviews": result.total_reviews,
        "recommend_ratio": result.recommend_ratio,
        "wilson_score": result.wilson_score,
        "review_score_desc": result.review_score_desc,
    }


async def fetch_review_scores(
    ctx: AgentContext,
    igdb_ids: list[int],
) -> dict:
    games = ctx.store.resolve(igdb_ids)

    results = await ctx.tools.review_score.run(games)

    return {
        "review_scores": [
            compact_review_score(results[game.igdb_id])
            for game in games
            if game.igdb_id in results
        ]
    }

@tool("get_review_scores")
async def get_review_scores(
    igdb_ids: list[int],
    runtime: ToolRuntime[AgentContext],
) -> str:
    """후보 게임의 Steam 사용자 리뷰 통계를 조회한다.

    - search_games가 반환한 igdb_id를 전달한다.
    - 여러 게임의 리뷰 통계를 한 번에 조회할 수 있다.
    - recommend_ratio는 전체 리뷰 중 추천 리뷰의 실제 비율이다.
    - wilson_score는 리뷰 수에 따른 불확실성을 고려한
      95% Wilson 신뢰구간의 하한값이다.
    - review_score_desc는 Steam이 제공하는 종합 리뷰 평가 문구다.
    - Steam App ID가 없는 게임은 결과에 포함되지 않을 수 있다.
    """
    ctx = runtime.context
    return await ctx.run_stage(
        STAGE,
        fetch_review_scores(ctx, igdb_ids),
    )
