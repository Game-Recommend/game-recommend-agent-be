import asyncio

from app.schemas.game import GameCandidate
from app.schemas.price import PriceQuote, PriceUnavailable
from app.tools.price import PriceTool
from tests.price_hardware.fakes import FakePriceHardware


def test_budget_boundary_and_missing_price_are_distinct():
    games = [GameCandidate(igdb_id=i, name=str(i)) for i in (1, 2, 3)]
    client = FakePriceHardware(
        quotes=[PriceQuote(igdb_id=2, amount_krw=101), PriceQuote(igdb_id=1, amount_krw=100)],
        assessments=[],
    )
    result = asyncio.run(PriceTool(client).run(games, max_price_krw=100))
    assert result[1].check.status == "met"
    assert result[2].check.status == "unmet"
    assert result[3].check.status == "unknown"


def test_free_game_budget_does_not_accept_missing_price():
    games = [GameCandidate(igdb_id=i, name=str(i)) for i in (1, 2)]
    client = FakePriceHardware(quotes=[PriceQuote(igdb_id=1, amount_krw=0)], assessments=[])
    result = asyncio.run(PriceTool(client).run(games, max_price_krw=0))
    assert result[1].check.status == "met"
    assert result[2].check.status == "unknown"


def test_unavailable_price_is_unmet_even_without_budget():
    games = [GameCandidate(igdb_id=i, name=str(i)) for i in (1, 2)]
    client = FakePriceHardware(
        quotes=[PriceUnavailable(igdb_id=1, reason="한국 스토어 미판매")], assessments=[]
    )
    without_budget = asyncio.run(PriceTool(client).run(games, max_price_krw=None))
    assert without_budget[1].check.status == "unmet"
    assert without_budget[1].check.reason == "한국 스토어 미판매"
    assert without_budget[1].quote is None
    assert without_budget[2].check.status == "skipped"

    with_budget = asyncio.run(PriceTool(client).run(games, max_price_krw=100))
    assert with_budget[1].check.status == "unmet"
    assert with_budget[2].check.status == "unknown"
