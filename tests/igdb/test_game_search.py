import asyncio

from app.pipeline.query_processing.conditions import GameConditions
from app.schemas.game import GameCandidate
from app.tools.game_search import GameSearchTool
from tests.igdb.fakes import FakeCatalog


def test_deduplicates_by_id_without_truncating_before_budget_filter():
    games = [
        GameCandidate(igdb_id=20, name="동일 이름"),
        GameCandidate(igdb_id=10, name="동일 이름"),
        GameCandidate(igdb_id=20, name="동일 이름"),
    ]
    client = FakeCatalog(games)
    conditions = GameConditions(players=4, recommendation_count=1)

    result = asyncio.run(GameSearchTool(client).run(conditions))

    assert [game.igdb_id for game in result] == [20, 10]
    assert client.conditions == conditions
