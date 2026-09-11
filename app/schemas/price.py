"""가격·하드웨어 담당: 원화 가격과 예산 판정 모델."""

from pydantic import BaseModel, Field

from app.schemas.common import ConditionCheck


class PriceQuote(BaseModel):
    igdb_id: int = Field(gt=0)
    amount_krw: int = Field(ge=0)  # 클라이언트가 통화·단위를 검증한 최종 구매 가격
    source_url: str | None = None


class PriceResult(BaseModel):
    igdb_id: int
    quote: PriceQuote | None = None
    check: ConditionCheck
