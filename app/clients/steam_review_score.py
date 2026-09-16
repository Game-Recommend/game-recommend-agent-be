"""Steam 사용자 리뷰 통계 조회 클라이언트."""

import asyncio
import math

import httpx2 as httpx

from app.schemas.game import GameCandidate
from app.schemas.review import ReviewScore


def calculate_wilson_score(positive: int, total: int) -> float:
    """추천 리뷰 비율의 95% Wilson 신뢰구간 하한을 계산한다."""
    if total == 0:
        return 0.0

    z = 1.96
    p = positive / total

    return (
        p
        + z**2 / (2 * total)
        - z * math.sqrt(
            (p * (1 - p) + z**2 / (4 * total)) / total
        )
    ) / (1 + z**2 / total)


class SteamReviewScoreClient:
    """Steam 리뷰 통계를 이용해 게임별 리뷰 점수를 조회한다."""

    async def _get_review_score(
        self,
        game: GameCandidate,
    ) -> ReviewScore:
        url = (
            f"https://store.steampowered.com/"
            f"appreviews/{game.steam_app_id}"
        )

        params = {
            "json": 1,
            "language": "all",
            "purchase_type": "all",
            "num_per_page": 1,
        }

        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.get(url, params=params)
            response.raise_for_status()

        data = response.json()
        summary = data["query_summary"]

        total_positive = summary["total_positive"]
        total_negative = summary["total_negative"]
        total_reviews = summary["total_reviews"]

        recommend_ratio = (
            total_positive / total_reviews
            if total_reviews > 0
            else 0.0
        )

        wilson_score = calculate_wilson_score(
            total_positive,
            total_reviews,
        )

        return ReviewScore(
            igdb_id=game.igdb_id,
            total_positive=total_positive,
            total_negative=total_negative,
            total_reviews=total_reviews,
            recommend_ratio=recommend_ratio,
            wilson_score=wilson_score,
            review_score_desc=summary.get("review_score_desc"),
        )

    async def scores(
        self,
        games: list[GameCandidate],
    ) -> list[ReviewScore]:
        """Steam App ID가 있는 게임들의 리뷰 통계를 병렬 조회한다."""
        valid_games = [
            game
            for game in games
            if game.steam_app_id is not None
        ]

        if not valid_games:
            return []

        return list(
            await asyncio.gather(
                *(
                    self._get_review_score(game)
                    for game in valid_games
                )
            )
        )