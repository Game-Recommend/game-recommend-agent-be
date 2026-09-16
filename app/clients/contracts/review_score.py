from typing import Protocol

from app.schemas.game import GameCandidate
from app.schemas.review import ReviewScore


class ReviewScoreClient(Protocol):
    async def scores(self, games: list[GameCandidate]) -> list[ReviewScore]:
        """Steam 사용자 리뷰 통계 기반 리뷰 점수.

        조회에 실패한 게임은 이유를 모르므로 생략한다. 네트워크 실패로 배치 전체가
        실패하지 않도록 게임별로 흡수한다.
        """
        ...
