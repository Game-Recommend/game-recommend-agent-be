from app.clients.contracts.reviews import ReviewSummaryClient
from app.schemas.common import Language
from app.schemas.game import GameCandidate
from app.schemas.review import ReviewSummary


class ReviewSummaryTool:
    def __init__(self, client: ReviewSummaryClient):
        self.client = client

    async def run(
        self, games: list[GameCandidate], *, language: Language = "ko"
    ) -> dict[int, ReviewSummary]:
        if not games:
            return {}
        return {
            result.igdb_id: result
            for result in await self.client.summarize(games, language=language)
        }
