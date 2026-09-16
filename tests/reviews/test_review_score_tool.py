import asyncio
from types import SimpleNamespace

from app.agent.context import CandidateStore
from app.agent.tools.review_score import fetch_review_scores
from app.clients.steam_review_score import calculate_wilson_score
from app.pipeline.query_processing.conditions import GameConditions
from app.schemas.game import GameCandidate
from app.schemas.review import ReviewScore
from app.tools.review_score import ReviewScoreTool


class FakeReviewScoreClient:
    async def scores(self, games):
        return [
            ReviewScore(
                igdb_id=game.igdb_id,
                total_positive=950,
                total_negative=50,
                total_reviews=1000,
                recommend_ratio=0.95,
                wilson_score=0.9347,
                review_score_desc="Very Positive",
            )
            for game in games
            if game.steam_app_id is not None
        ]


def test_fetch_review_scores_returns_compressed_scores():
    store = CandidateStore(GameConditions())
    store.add_candidates(
        [
            GameCandidate(
                igdb_id=1,
                name="Game 1",
                steam_app_id=10,
            ),
            GameCandidate(
                igdb_id=2,
                name="Game 2",
                steam_app_id=20,
            ),
        ]
    )

    context = SimpleNamespace(
        store=store,
        tools=SimpleNamespace(
            review_score=ReviewScoreTool(FakeReviewScoreClient())
        ),
    )

    result = asyncio.run(
        fetch_review_scores(context, [1, 2])
    )

    assert result == {
        "review_scores": [
            {
                "igdb_id": 1,
                "total_reviews": 1000,
                "recommend_ratio": 0.95,
                "wilson_score": 0.9347,
                "review_score_desc": "Very Positive",
            },
            {
                "igdb_id": 2,
                "total_reviews": 1000,
                "recommend_ratio": 0.95,
                "wilson_score": 0.9347,
                "review_score_desc": "Very Positive",
            },
        ]
    }


def test_fetch_review_scores_skips_game_without_steam_app_id():
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

    context = SimpleNamespace(
        store=store,
        tools=SimpleNamespace(
            review_score=ReviewScoreTool(FakeReviewScoreClient())
        ),
    )

    result = asyncio.run(
        fetch_review_scores(context, [1])
    )

    assert result == {
        "review_scores": []
    }

def test_calculate_wilson_score():
    score = calculate_wilson_score(
        positive=950,
        total=1000,
    )

    # 실제 추천 비율 0.95보다 조금 낮아야 한다.
    assert 0 < score < 0.95
    assert round(score, 4) == 0.9347


def test_calculate_wilson_score_with_zero_reviews():
    score = calculate_wilson_score(
        positive=0,
        total=0,
    )

    assert score == 0.0


def test_review_score_tool_run_returns_results_keyed_by_igdb_id():
    games = [
        GameCandidate(igdb_id=1, name="Game 1", steam_app_id=10),
        GameCandidate(igdb_id=2, name="No Steam Game", steam_app_id=None),
    ]

    tool = ReviewScoreTool(FakeReviewScoreClient())
    results = asyncio.run(tool.run(games))

    assert set(results) == {1}
    assert results[1].igdb_id == 1
    assert results[1].total_reviews == 1000


def test_review_score_tool_run_with_no_games_returns_empty_dict():
    tool = ReviewScoreTool(FakeReviewScoreClient())
    results = asyncio.run(tool.run([]))

    assert results == {}