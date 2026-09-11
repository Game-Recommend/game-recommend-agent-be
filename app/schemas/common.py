"""공통 계약: 조건 판정 상태. 변경 시 모든 담당자와 조율한다."""

from typing import Literal

from pydantic import BaseModel

CheckStatus = Literal["met", "unmet", "unknown", "skipped"]


class ConditionCheck(BaseModel):
    status: CheckStatus
    reason: str
