"""가격·하드웨어 담당: 사용자 사양과 호환성 판정 모델."""

from typing import Literal

from pydantic import BaseModel, Field


class HardwareSpecs(BaseModel):
    cpu: str | None = None
    gpu: str | None = None
    ram_gb: float | None = Field(default=None, gt=0)
    os: str | None = None
    raw_text: str | None = None


class HardwareAssessment(BaseModel):
    igdb_id: int
    status: Literal["met", "unmet", "unknown"]
    reason: str
