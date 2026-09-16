"""Steam 사용자 리뷰 통계 조회 클라이언트."""

import asyncio
import logging
import math

import httpx2 as httpx

from app.schemas.game import GameCandidate
from app.schemas.review import ReviewScore

logger = logging.getLogger(__name__)

APPREVIEWS_URL = "https://store.steampowered.com/appreviews"


def calculate_wilson_score(positive: int, total: int) -> float:
    """추천 리뷰 비율의 95% Wilson 신뢰구간 하한을 계산한다."""
    if total == 0:
        return 0.0

    z = 1.96
    p = positive / total

    return (
        p
        + z**2 / (2 * total)
        - z * math.sqrt((p * (1 - p) + z**2 / (4 * total)) / total)
    ) / (1 + z**2 / total)


class SteamReviewScoreClient:
    """Steam 리뷰 통계를 이용해 게임별 리뷰 점수를 조회한다."""

    def __init__(self, http: httpx.AsyncClient, *, max_concurrency: int = 4):
        self.http = http
        self._semaphore = asyncio.Semaphore(max_concurrency)

    async def _get_review_score(self, game: GameCandidate) -> ReviewScore:
        response = await self.http.get(
            f"{APPREVIEWS_URL}/{game.steam_app_id}",
            params={
                "json": 1,
                "language": "all",
                "filter": "all",
                "purchase_type": "all",
                "num_per_page": 1,
            },
        )
        response.raise_for_status()

        # success:false(삭제·비공개 앱)나 예상 밖 응답이면 query_summary가 없을 수 있다
        summary = response.json().get("query_summary") or {}

        total_positive = summary.get("total_positive", 0)
        total_negative = summary.get("total_negative", 0)
        total_reviews = summary.get("total_reviews", 0)

        recommend_ratio = total_positive / total_reviews if total_reviews > 0 else 0.0

        return ReviewScore(
            igdb_id=game.igdb_id,
            total_positive=total_positive,
            total_negative=total_negative,
            total_reviews=total_reviews,
            recommend_ratio=recommend_ratio,
            wilson_score=calculate_wilson_score(total_positive, total_reviews),
            review_score_desc=summary.get("review_score_desc"),
        )

    async def _guarded(self, game: GameCandidate) -> ReviewScore | None:
        try:
            async with self._semaphore:
                return await self._get_review_score(game)
        except (httpx.HTTPError, ValueError) as exc:
            logger.warning(
                "Steam review score lookup failed: igdb_id=%s (%s)",
                game.igdb_id,
                type(exc).__name__,
            )
            return None

    async def scores(
        self,
        games: list[GameCandidate],
    ) -> list[ReviewScore]:
        """Steam App ID가 있는 게임들의 리뷰 통계를 병렬 조회한다.

        조회에 실패한 게임은 결과에서 빠지며, 다른 게임 조회에 영향을 주지 않는다.
        """
        valid_games = [game for game in games if game.steam_app_id is not None]

        if not valid_games:
            return []

        results = await asyncio.gather(*(self._guarded(game) for game in valid_games))

        return [result for result in results if result is not None]
