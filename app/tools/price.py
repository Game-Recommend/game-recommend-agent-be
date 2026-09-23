from app.clients.contracts.price import PriceClient
from app.schemas.common import ConditionCheck, Language
from app.schemas.game import GameCandidate
from app.schemas.price import PriceQuote, PriceResult, PriceUnavailable

# 판정 이유. 구매 불가 이유는 클라이언트가 같은 언어로 만든다
REASONS: dict[Language, dict[str, str]] = {
    "ko": {
        "no_budget": "예산 조건 없음",
        "no_quote": "원화 가격 확인 불가",
        "within_budget": "예산 이하",
        "over_budget": "예산 초과",
    },
    "en": {
        "no_budget": "No budget condition",
        "no_quote": "KRW price unavailable",
        "within_budget": "Within budget",
        "over_budget": "Over budget",
    },
}


class PriceTool:
    def __init__(self, client: PriceClient):
        self.client = client

    async def run(
        self, games: list[GameCandidate], max_price_krw: int | None, *, language: Language = "ko"
    ) -> dict[int, PriceResult]:
        reasons = REASONS[language]
        lookups = {
            lookup.igdb_id: lookup
            for lookup in await self.client.fetch_prices(games, language=language)
        }
        results = {}
        for game in games:
            lookup = lookups.get(game.igdb_id)
            quote = lookup if isinstance(lookup, PriceQuote) else None
            if isinstance(lookup, PriceUnavailable):
                # 구매할 수 없는 게임은 예산 조건이 없어도 추천하지 않는다
                check = ConditionCheck(status="unmet", reason=lookup.reason)
            elif max_price_krw is None:
                check = ConditionCheck(status="skipped", reason=reasons["no_budget"])
            elif quote is None:
                check = ConditionCheck(status="unknown", reason=reasons["no_quote"])
            elif quote.amount_krw <= max_price_krw:
                check = ConditionCheck(status="met", reason=reasons["within_budget"])
            else:
                check = ConditionCheck(status="unmet", reason=reasons["over_budget"])
            results[game.igdb_id] = PriceResult(igdb_id=game.igdb_id, quote=quote, check=check)
        return results
