import asyncio
from types import SimpleNamespace

from app.agent.context import CandidateStore
from app.agent.tools.reviews import summarize
from app.pipeline.query_processing.conditions import GameConditions
from app.schemas.game import GameCandidate
from app.tools.review_summary import ReviewSummaryTool
from tests.reviews.fakes import FakeReviews


def test_summarize_returns_compressed_reviews():
    store = CandidateStore(GameConditions())
    store.add_candidates(
        [
            GameCandidate(igdb_id=1, name="Game 1", steam_app_id=10),
            GameCandidate(igdb_id=3, name="Game 3", steam_app_id=30),
        ]
    )

    fake_reviews = FakeReviews()

    context = SimpleNamespace(
        store=store,
        tools=SimpleNamespace(
            review_summary=ReviewSummaryTool(fake_reviews)
        ),
    )

    result = asyncio.run(summarize(context, [1, 3]))

    assert result == {
        "reviews": [
            {
                "igdb_id": 1,
                "name": "Game 1",
                "summary": "테스트 요약",
            },
            {
                "igdb_id": 3,
                "name": "Game 3",
                "summary": "테스트 요약",
            },
        ]
    }

def test_summarize_returns_null_when_steam_app_id_is_missing():
    store = CandidateStore(GameConditions())
    store.add_candidates(
        [
            GameCandidate(
                igdb_id=1,
                name="No Steam Game",
                steam_app_id=None,
            )
        ]
    )

    class FakeReviewsWithoutSteam:
        async def summarize(self, games):
            return []

    context = SimpleNamespace(
        store=store,
        tools=SimpleNamespace(
            review_summary=ReviewSummaryTool(FakeReviewsWithoutSteam())
        ),
    )

    result = asyncio.run(summarize(context, [1]))

    assert result == {
        "reviews": [
            {
                "igdb_id": 1,
                "name": "No Steam Game",
                "summary": None,
            }
        ]
    }

def test_summarize_reviews_returns_error_json_on_failure():
    store = CandidateStore(GameConditions())
    store.add_candidates(
        [GameCandidate(igdb_id=1, name="Game 1", steam_app_id=10)]
    )

    class FailingReviews:
        async def summarize(self, games):
            raise ConnectionError("Steam API failure")

    review_summary = ReviewSummaryTool(FailingReviews())

    from app.agent.context import AgentContext, ToolSet

    context = AgentContext(
        conditions=GameConditions(),
        store=store,
        tools=ToolSet(
            game_search=None,
            price=None,
            hardware=None,
            review_summary=review_summary,
            review_score=None,
        ),
    )

    result = asyncio.run(context.run_stage("리뷰 요약", summarize(context, [1])))

    assert '"error"' in result