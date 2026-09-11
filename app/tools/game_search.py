from app.clients.contracts.catalog import GameCatalogClient
from app.pipeline.query_processing.conditions import GameConditions
from app.schemas.game import GameCandidate


class GameSearchTool:
    def __init__(self, client: GameCatalogClient):
        self.client = client

    async def run(self, conditions: GameConditions) -> list[GameCandidate]:
        games = await self.client.search(conditions)
        # 후속 가격·사양 필터링 전에 추천 개수로 자르지 않는다.
        return list({game.igdb_id: game for game in games}.values())
