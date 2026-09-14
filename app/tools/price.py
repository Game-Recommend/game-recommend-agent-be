from app.clients.contracts.price import PriceClient
from app.schemas.common import ConditionCheck
from app.schemas.game import GameCandidate
from app.schemas.price import PriceQuote, PriceResult, PriceUnavailable


class PriceTool:
    def __init__(self, client: PriceClient):
        self.client = client

    async def run(
        self, games: list[GameCandidate], max_price_krw: int | None
    ) -> dict[int, PriceResult]:
        lookups = {lookup.igdb_id: lookup for lookup in await self.client.fetch_prices(games)}
        results = {}
        for game in games:
            lookup = lookups.get(game.igdb_id)
            quote = lookup if isinstance(lookup, PriceQuote) else None
            if isinstance(lookup, PriceUnavailable):
                # 구매할 수 없는 게임은 예산 조건이 없어도 추천하지 않는다
                check = ConditionCheck(status="unmet", reason=lookup.reason)
            elif max_price_krw is None:
                check = ConditionCheck(status="skipped", reason="예산 조건 없음")
            elif quote is None:
                check = ConditionCheck(status="unknown", reason="원화 가격 확인 불가")
            elif quote.amount_krw <= max_price_krw:
                check = ConditionCheck(status="met", reason="예산 이하")
            else:
                check = ConditionCheck(status="unmet", reason="예산 초과")
            results[game.igdb_id] = PriceResult(igdb_id=game.igdb_id, quote=quote, check=check)
        return results
