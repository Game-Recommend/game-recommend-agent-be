from app.clients.hardware_judge import JudgeRequest
from app.schemas.common import Language
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
        self.languages: list[Language] = []  # 호출마다 받은 language

    async def fetch_prices(
        self, games: list[GameCandidate], *, language: Language = "ko"
    ) -> list[PriceQuote | PriceUnavailable]:
        self.calls.append("price")
        self.languages.append(language)
        return self.quotes

    async def assess(
        self,
        games: list[GameCandidate],
        hardware: HardwareSpecs | None,
        *,
        language: Language = "ko",
    ) -> list[HardwareAssessment]:
        self.calls.append("hardware")
        self.languages.append(language)
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
        self.language: Language | None = None

    async def judge(
        self,
        hardware: HardwareSpecs,
        requests: list[JudgeRequest],
        *,
        language: Language = "ko",
    ) -> list[HardwareAssessment]:
        self.hardware = hardware
        self.language = language
        self.requests.extend(requests)
        if self.error is not None:
            raise self.error
        return self.verdicts
