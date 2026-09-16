"""Steam appreviews 응답 파싱과 리뷰 점수 계산. 실제 호출 없이 MockTransport로 검증한다."""

import asyncio
import json

import httpx2

from app.clients.steam_review_score import SteamReviewScoreClient, calculate_wilson_score
from app.schemas.game import GameCandidate


def game(igdb_id: int, app_id: int | None = None) -> GameCandidate:
    return GameCandidate(igdb_id=igdb_id, name=f"게임{igdb_id}", steam_app_id=app_id)


def query_summary(**overrides) -> dict:
    data = {
        "total_positive": 950,
        "total_negative": 50,
        "total_reviews": 1000,
        "review_score_desc": "Very Positive",
    }
    data.update(overrides)
    return {"success": 1, "query_summary": data}


def make_client(responses: dict[int, dict | int], calls: list[int] | None = None):
    calls = calls if calls is not None else []

    def handler(request: httpx2.Request) -> httpx2.Response:
        app_id = int(request.url.path.rsplit("/", 1)[-1])
        calls.append(app_id)
        outcome = responses[app_id]
        if isinstance(outcome, int):
            return httpx2.Response(outcome, content=json.dumps({}))
        return httpx2.Response(200, content=json.dumps(outcome))

    http = httpx2.AsyncClient(transport=httpx2.MockTransport(handler))
    return SteamReviewScoreClient(http), calls


def test_scores_parses_query_summary_and_sends_expected_params():
    captured: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        captured.append(request)
        return httpx2.Response(200, content=json.dumps(query_summary()))

    http = httpx2.AsyncClient(transport=httpx2.MockTransport(handler))
    client = SteamReviewScoreClient(http)

    results = asyncio.run(client.scores([game(1, app_id=570)]))

    assert len(results) == 1
    result = results[0]
    assert result.igdb_id == 1
    assert result.total_positive == 950
    assert result.total_negative == 50
    assert result.total_reviews == 1000
    assert result.recommend_ratio == 0.95
    assert round(result.wilson_score, 4) == round(calculate_wilson_score(950, 1000), 4)
    assert result.review_score_desc == "Very Positive"

    assert len(captured) == 1
    request = captured[0]
    assert request.url.path == "/appreviews/570"
    assert request.url.params["filter"] == "all"
    assert request.url.params["purchase_type"] == "all"
    assert request.url.params["language"] == "all"
    assert request.url.params["num_per_page"] == "1"


def test_scores_with_zero_total_reviews_is_zero_safe():
    client, _ = make_client(
        {
            570: query_summary(
                total_positive=0,
                total_negative=0,
                total_reviews=0,
                review_score_desc="No user reviews",
            )
        }
    )

    results = asyncio.run(client.scores([game(1, app_id=570)]))

    assert len(results) == 1
    assert results[0].recommend_ratio == 0.0
    assert results[0].wilson_score == 0.0


def test_scores_skips_games_without_steam_app_id():
    client, calls = make_client({})

    results = asyncio.run(client.scores([game(1, app_id=None)]))

    assert results == []
    assert calls == []


def test_scores_handles_missing_query_summary_without_raising():
    client, _ = make_client({570: {"success": 0}})

    results = asyncio.run(client.scores([game(1, app_id=570)]))

    assert len(results) == 1
    assert results[0].total_reviews == 0
    assert results[0].recommend_ratio == 0.0
    assert results[0].wilson_score == 0.0
    assert results[0].review_score_desc is None


def test_scores_isolates_single_game_failure():
    client, _ = make_client(
        {
            570: query_summary(),
            999: 500,
        }
    )

    results = asyncio.run(client.scores([game(1, app_id=570), game(2, app_id=999)]))

    assert [result.igdb_id for result in results] == [1]
