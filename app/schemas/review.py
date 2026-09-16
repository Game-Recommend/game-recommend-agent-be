"""리뷰 담당: 리뷰 요약 결과 모델."""

from pydantic import BaseModel, Field


class ReviewSummary(BaseModel):
    igdb_id: int
    summary: str
    source_urls: list[str] = Field(default_factory=list)

class ReviewScore(BaseModel):
    igdb_id: int
    total_positive: int
    total_negative: int
    total_reviews: int
    recommend_ratio: float
    wilson_score: float
    review_score_desc: str | None = None