"""고정 워크플로: 질문 분해 → 검색 → 가격/사양 병렬 → 병합 → 리뷰 → 답변."""

import asyncio
import logging
from collections.abc import Awaitable

from app.pipeline.final_answer.answerer import Answerer
from app.pipeline.query_processing.parser import QueryParser
from app.schemas.common import ConditionCheck
from app.schemas.price import PriceResult
from app.schemas.recommendation import EvaluatedGame, RecommendationEvidence, RecommendationResponse
from app.tools.game_search import GameSearchTool
from app.tools.hardware import HardwareTool
from app.tools.price import PriceTool
from app.tools.review_summary import ReviewSummaryTool

logger = logging.getLogger(__name__)


class PipelineStageError(Exception):
    """질문 분해·검색·답변 생성처럼 계속 진행할 수 없는 단계의 실패."""


class RecommendationOrchestrator:
    def __init__(
        self,
        parser: QueryParser,
        game_search: GameSearchTool,
        price: PriceTool,
        hardware: HardwareTool,
        review_summary: ReviewSummaryTool,
        answerer: Answerer,
        *,
        stage_timeout_seconds: float = 30,
    ):
        if stage_timeout_seconds <= 0:
            raise ValueError("stage_timeout_seconds must be positive")
        self.parser = parser
        self.game_search = game_search
        self.price = price
        self.hardware = hardware
        self.review_summary = review_summary
        self.answerer = answerer
        self.stage_timeout_seconds = stage_timeout_seconds

    async def _required[T](self, name: str, call: Awaitable[T]) -> T:
        try:
            return await asyncio.wait_for(call, timeout=self.stage_timeout_seconds)
        except Exception as exc:
            logger.warning("Required pipeline stage failed: %s (%s)", name, type(exc).__name__)
            raise PipelineStageError(f"{name} 단계를 완료하지 못했습니다.") from exc

    async def _optional[T](
        self, name: str, call: Awaitable[T], warnings: list[str]
    ) -> T | None:
        try:
            return await asyncio.wait_for(call, timeout=self.stage_timeout_seconds)
        except Exception as exc:
            logger.warning("Optional pipeline stage failed: %s (%s)", name, type(exc).__name__)
            warnings.append(f"{name} 호출 실패: 해당 정보를 확인할 수 없습니다.")
            return None

    async def run(self, question: str) -> RecommendationResponse:
        conditions = await self._required("질문 분해", self.parser.parse(question))
        games = await self._required("게임 검색", self.game_search.run(conditions))
        evidence = RecommendationEvidence(conditions=conditions)

        if games:
            prices, hardware = await asyncio.gather(
                self._optional(
                    "가격", self.price.run(games, conditions.max_price_krw), evidence.warnings
                ),
                self._optional(
                    "하드웨어", self.hardware.run(games, conditions.hardware), evidence.warnings
                ),
            )
            for game in games:
                price_result = (prices or {}).get(game.igdb_id) or PriceResult(
                    igdb_id=game.igdb_id,
                    check=ConditionCheck(
                        status="unknown" if conditions.max_price_krw is not None else "skipped",
                        reason="가격 확인 불가",
                    ),
                )
                hardware_result = (hardware or {}).get(game.igdb_id) or ConditionCheck(
                    status="unknown" if conditions.hardware is not None else "skipped",
                    reason="사양 확인 불가",
                )
                evaluated = EvaluatedGame(game=game, price=price_result, hardware=hardware_result)
                if all(
                    check.status in {"met", "skipped"}
                    for check in (price_result.check, hardware_result)
                ):
                    evidence.games.append(evaluated)
                else:
                    evidence.excluded_games.append(evaluated)

            # 검색 결과의 우선순위를 유지한다. 모든 필수 조건을 검사한 뒤 개수를 제한한다.
            evidence.games = evidence.games[: conditions.recommendation_count]
            if evidence.games:
                reviews = await self._optional(
                    "리뷰 요약",
                    self.review_summary.run([result.game for result in evidence.games]),
                    evidence.warnings,
                )
                for result in evidence.games:
                    result.review = (reviews or {}).get(result.game.igdb_id)
                    if result.review is None:
                        evidence.warnings.append(f"{result.game.name}: 리뷰 요약 확인 불가")
                    if result.price.quote is None:
                        evidence.warnings.append(f"{result.game.name}: 원화 가격 확인 불가")

        if not evidence.games:
            evidence.warnings.append("모든 필수 조건을 충족한다고 확인된 후보가 없습니다.")
        answer = await self._required("최종 답변 생성", self.answerer.generate(question, evidence))
        return RecommendationResponse(**evidence.model_dump(), answer=answer)
