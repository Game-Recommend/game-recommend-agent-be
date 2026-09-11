from typing import Protocol

from app.schemas.game import GameCandidate
from app.schemas.price import PriceQuote


class PriceClient(Protocol):
    async def fetch_prices(self, games: list[GameCandidate]) -> list[PriceQuote]: ...
