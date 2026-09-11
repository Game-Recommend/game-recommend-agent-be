from typing import Protocol

from app.schemas.game import GameCandidate
from app.schemas.review import ReviewSummary


class ReviewSummaryClient(Protocol):
    async def summarize(self, games: list[GameCandidate]) -> list[ReviewSummary]:
        """외부 리뷰 요약 API 또는 리뷰 수집 + LLM 요약 어댑터."""
        ...
