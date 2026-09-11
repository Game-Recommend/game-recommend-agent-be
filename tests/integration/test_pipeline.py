import asyncio

import pytest

from app.pipeline.query_processing.conditions import GameConditions
from app.schemas.price import PriceQuote


def test_filters_by_id_before_limiting_and_only_reviews_survivors(recommender, services):
    response = asyncio.run(recommender.run("게임 하나 추천"))

    assert [result.game.igdb_id for result in response.games] == [3]
    assert [result.game.igdb_id for result in response.excluded_games] == [1, 2]
    assert response.excluded_games[0].price.check.status == "unmet"
    assert response.excluded_games[1].hardware.status == "unknown"
    assert services.reviews.reviewed_ids == [3]
    assert services.calls[:2] == ["parse", "search"]
    assert services.calls[-2:] == ["reviews", "answer"]
    assert response.games[0].review.summary == "테스트 요약"


def test_price_and_hardware_overlap_and_reviews_wait_for_both(recommender, services, monkeypatch):
    async def scenario():
        price_started = asyncio.Event()
        hardware_started = asyncio.Event()
        completed = set()
        original_price = services.price_hardware.fetch_prices
        original_hardware = services.price_hardware.assess
        original_reviews = services.reviews.summarize

        async def price(games):
            price_started.set()
            await hardware_started.wait()
            result = await original_price(games)
            completed.add("price")
            return result

        async def hardware(games, specs):
            hardware_started.set()
            await price_started.wait()
            result = await original_hardware(games, specs)
            completed.add("hardware")
            return result

        async def reviews(games):
            assert completed == {"price", "hardware"}
            return await original_reviews(games)

        monkeypatch.setattr(services.price_hardware, "fetch_prices", price)
        monkeypatch.setattr(services.price_hardware, "assess", hardware)
        monkeypatch.setattr(services.reviews, "summarize", reviews)
        response = await asyncio.wait_for(recommender.run("추천"), timeout=1)
        assert response.games[0].review is not None

    asyncio.run(scenario())


@pytest.mark.parametrize("field", ["quotes", "assessments"])
def test_missing_required_data_is_not_a_pass(recommender, services, field):
    setattr(services.price_hardware, field, [])
    response = asyncio.run(recommender.run("추천"))

    assert response.games == []
    assert len(response.excluded_games) == 3
    assert "reviews" not in services.calls
    assert services.calls[-1] == "answer"


@pytest.mark.parametrize("method", ["fetch_prices", "assess"])
def test_failed_branch_preserves_other_branch_results(recommender, services, monkeypatch, method):
    async def fail(*args):
        raise ConnectionError("private provider details")

    monkeypatch.setattr(services.price_hardware, method, fail)
    response = asyncio.run(recommender.run("추천"))

    assert response.games == []
    assert "reviews" not in services.calls
    assert "private provider details" not in response.model_dump_json()
    third = response.excluded_games[2]
    if method == "fetch_prices":
        assert third.price.check.status == "unknown"
        assert third.hardware.status == "met"
    else:
        assert third.price.check.status == "met"
        assert third.hardware.status == "unknown"


def test_no_candidates_skips_all_enrichment(recommender, services):
    services.catalog.games = []
    response = asyncio.run(recommender.run("추천"))
    assert response.games == []
    assert services.calls == ["parse", "search", "answer"]


def test_absent_conditions_skip_checks_but_keep_price_lookup(recommender, services):
    services.parser.conditions = GameConditions()
    services.price_hardware.quotes = []
    response = asyncio.run(recommender.run("추천"))
    assert len(response.games) == 3
    assert "hardware" not in services.calls
    assert "price" in services.calls
    assert all(game.hardware.status == "skipped" for game in response.games)
    assert all(game.price.check.status == "skipped" for game in response.games)
    assert any("원화 가격 확인 불가" in warning for warning in response.warnings)


def test_zero_budget_accepts_only_confirmed_free_games(recommender, services):
    services.parser.conditions = GameConditions(max_price_krw=0)
    services.price_hardware.quotes = [
        PriceQuote(igdb_id=3, amount_krw=0),
        PriceQuote(igdb_id=1, amount_krw=1),
    ]
    response = asyncio.run(recommender.run("무료 게임"))
    assert [game.game.igdb_id for game in response.games] == [3]


def test_review_timeout_preserves_candidates_without_inventing_summary(
    recommender, services, monkeypatch
):
    async def never_finishes(games):
        await asyncio.Event().wait()

    recommender.stage_timeout_seconds = 0.05
    monkeypatch.setattr(services.reviews, "summarize", never_finishes)
    response = asyncio.run(recommender.run("추천"))
    assert len(response.games) == 1
    assert response.games[0].review is None
    assert any("리뷰 요약 호출 실패" in warning for warning in response.warnings)
    assert services.calls[-1] == "answer"
