"""통합 계약: 최종 답변 근거와 HTTP 요청·응답. 변경 시 소비자와 조율한다."""

from typing import Literal

from pydantic import BaseModel, Field

from app.pipeline.query_processing.conditions import GameConditions
from app.schemas.common import Language
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
    language: Language = Field(
        default="ko",
        description=(
            "answer·리뷰 한줄평·warnings·판정 이유(check.reason)의 언어. SSE 단계 이름·detail, "
            "오류 문장, conditions 값은 언어와 무관하게 한국어다."
        ),
    )


class StageEvent(BaseModel):
    """SSE 진행 이벤트. 단계 이름은 오케스트레이터의 한국어 단계명이다."""

    event: Literal["stage"] = "stage"
    stage: str
    status: Literal["started", "completed", "failed"]
    detail: str | None = None


class ResultEvent(BaseModel):
    """SSE 마지막 이벤트. JSON 응답과 같은 `RecommendationResponse`를 담는다."""

    event: Literal["result"] = "result"
    result: RecommendationResponse


class ErrorEvent(BaseModel):
    """필수 단계 실패. JSON 응답의 502 detail과 같은 문장이다."""

    event: Literal["error"] = "error"
    detail: str


PipelineEvent = StageEvent | ResultEvent | ErrorEvent
