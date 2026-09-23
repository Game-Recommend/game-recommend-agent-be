from app.schemas.common import Language
from app.schemas.game import GameCandidate
from app.schemas.review import ReviewSummary


class FakeReviews:
    def __init__(self, calls: list[str] | None = None):
        self.calls = calls if calls is not None else []
        self.reviewed_ids: list[int] = []
        self.languages: list[Language] = []  # 호출마다 받은 language

    async def summarize(
        self, games: list[GameCandidate], *, language: Language = "ko"
    ) -> list[ReviewSummary]:
        self.calls.append("reviews")
        self.reviewed_ids = [game.igdb_id for game in games]
        self.languages.append(language)
        return [ReviewSummary(igdb_id=game.igdb_id, summary="테스트 요약") for game in games]
