from typing import Protocol

from app.schemas.game import GameCandidate
from app.schemas.price import PriceQuote, PriceUnavailable


class PriceClient(Protocol):
    async def fetch_prices(self, games: list[GameCandidate]) -> list[PriceQuote | PriceUnavailable]:
        """원화 가격을 확인한 게임은 PriceQuote, 구매 불가를 확인한 게임은 PriceUnavailable.

        이유를 모르는 조회 실패는 생략한다. 네트워크 실패는 예외로 전달한다.
        """
        ...
