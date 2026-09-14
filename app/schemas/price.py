"""가격·하드웨어 담당: 원화 가격과 예산 판정 모델."""

from pydantic import BaseModel, Field

from app.schemas.common import ConditionCheck


class PriceQuote(BaseModel):
    igdb_id: int = Field(gt=0)
    amount_krw: int = Field(ge=0)  # 클라이언트가 통화·단위를 검증한 최종 구매 가격
    source_url: str | None = None


class PriceUnavailable(BaseModel):
    """가격이 없는 이유를 확인한 경우. 미판매·미출시처럼 구매 자체가 불가능한 상태다.

    이유를 모르는 조회 실패는 이 모델 대신 결과에서 생략한다 (→ unknown).
    """

    igdb_id: int = Field(gt=0)
    reason: str


class PriceResult(BaseModel):
    igdb_id: int
    quote: PriceQuote | None = None
    check: ConditionCheck
