"""공통 계약: 조건 판정 상태와 출력 언어. 변경 시 모든 담당자와 조율한다."""

from typing import Literal

from pydantic import BaseModel

CheckStatus = Literal["met", "unmet", "unknown", "skipped"]

# 사람이 읽는 출력(답변·리뷰 한줄평·warnings·판정 이유)의 언어. 조건 추출과 SSE 단계 이름은
# 언어와 무관하게 한국어다
Language = Literal["ko", "en"]


class ConditionCheck(BaseModel):
    status: CheckStatus
    reason: str
