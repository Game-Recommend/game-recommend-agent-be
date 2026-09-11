from app.clients.contracts.price import PriceClient
from app.schemas.common import ConditionCheck
from app.schemas.game import GameCandidate
from app.schemas.price import PriceResult


class PriceTool:
    def __init__(self, client: PriceClient):
        self.client = client

    async def run(
        self, games: list[GameCandidate], max_price_krw: int | None
    ) -> dict[int, PriceResult]:
        quotes = {quote.igdb_id: quote for quote in await self.client.fetch_prices(games)}
        results = {}
        for game in games:
            quote = quotes.get(game.igdb_id)
            if max_price_krw is None:
                check = ConditionCheck(status="skipped", reason="예산 조건 없음")
            elif quote is None:
                check = ConditionCheck(status="unknown", reason="원화 가격 확인 불가")
            elif quote.amount_krw <= max_price_krw:
                check = ConditionCheck(status="met", reason="예산 이하")
            else:
                check = ConditionCheck(status="unmet", reason="예산 초과")
            results[game.igdb_id] = PriceResult(igdb_id=game.igdb_id, quote=quote, check=check)
        return results
