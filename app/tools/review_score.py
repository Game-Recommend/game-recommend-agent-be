"""Steam 리뷰 점수 조회 서비스 Tool."""

from app.clients.contracts.review_score import ReviewScoreClient
from app.schemas.game import GameCandidate
from app.schemas.review import ReviewScore


class ReviewScoreTool:
    """게임 후보들의 Steam 리뷰 점수를 조회한다."""

    def __init__(self, client: ReviewScoreClient):
        self.client = client

    async def run(
        self,
        games: list[GameCandidate],
    ) -> dict[int, ReviewScore]:
        if not games:
            return {}

        results = await self.client.scores(games)

        return {
            result.igdb_id: result
            for result in results
        }