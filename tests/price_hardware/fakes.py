from app.schemas.game import GameCandidate
from app.schemas.hardware import HardwareAssessment, HardwareSpecs
from app.schemas.price import PriceQuote


class FakePriceHardware:
    def __init__(
        self,
        quotes: list[PriceQuote],
        assessments: list[HardwareAssessment],
        calls: list[str] | None = None,
    ):
        self.quotes = quotes
        self.assessments = assessments
        self.calls = calls if calls is not None else []

    async def fetch_prices(self, games: list[GameCandidate]) -> list[PriceQuote]:
        self.calls.append("price")
        return self.quotes

    async def assess(
        self, games: list[GameCandidate], hardware: HardwareSpecs
    ) -> list[HardwareAssessment]:
        self.calls.append("hardware")
        return self.assessments
