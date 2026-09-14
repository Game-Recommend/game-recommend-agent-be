from app.clients.hardware_judge import JudgeRequest
from app.schemas.game import GameCandidate
from app.schemas.hardware import HardwareAssessment, HardwareSpecs
from app.schemas.price import PriceQuote, PriceUnavailable


class FakePriceHardware:
    def __init__(
        self,
        quotes: list[PriceQuote | PriceUnavailable],
        assessments: list[HardwareAssessment],
        calls: list[str] | None = None,
    ):
        self.quotes = quotes
        self.assessments = assessments
        self.calls = calls if calls is not None else []

    async def fetch_prices(self, games: list[GameCandidate]) -> list[PriceQuote | PriceUnavailable]:
        self.calls.append("price")
        return self.quotes

    async def assess(
        self, games: list[GameCandidate], hardware: HardwareSpecs | None
    ) -> list[HardwareAssessment]:
        self.calls.append("hardware")
        return self.assessments


class FakeSpecJudge:
    """SteamStoreClient에 주입하는 GPU·CPU 판정 대역. 요청받은 igdb_id를 기록한다."""

    def __init__(
        self, verdicts: list[HardwareAssessment] | None = None, error: Exception | None = None
    ):
        self.verdicts = verdicts or []
        self.error = error
        self.requests: list[JudgeRequest] = []
        self.hardware: HardwareSpecs | None = None

    async def judge(
        self, hardware: HardwareSpecs, requests: list[JudgeRequest]
    ) -> list[HardwareAssessment]:
        self.hardware = hardware
        self.requests.extend(requests)
        if self.error is not None:
            raise self.error
        return self.verdicts
