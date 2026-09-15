"""통합 계약: 최종 답변 근거와 HTTP 요청·응답. 변경 시 소비자와 조율한다."""

from pydantic import BaseModel, Field

from app.pipeline.query_processing.conditions import GameConditions
from app.schemas.game import GameCandidate
from app.schemas.hardware import HardwareResult
from app.schemas.media import GameMedia
from app.schemas.price import PriceResult
from app.schemas.review import ReviewSummary


class EvaluatedGame(BaseModel):
    game: GameCandidate
    price: PriceResult
    hardware: HardwareResult
    review: ReviewSummary | None = None
    media: GameMedia | None = None


class RecommendationEvidence(BaseModel):
    conditions: GameConditions
    games: list[EvaluatedGame] = Field(default_factory=list)
    excluded_games: list[EvaluatedGame] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class RecommendationResponse(RecommendationEvidence):
    answer: str


class RecommendationRequest(BaseModel):
    question: str = Field(min_length=1, max_length=5000, pattern=r"\S")
