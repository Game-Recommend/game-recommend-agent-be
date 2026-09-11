"""질문 가공 담당: 자연어 질문을 `GameConditions`(conditions.py)로 바꾸는 계약.

실제 LLM 연동·질문 분해 프롬프트는 이 패키지에 추가한다.
LLM 공급자는 아직 정하지 않았다. 정하면 키를 `app/config.py`와 `.env.example`에 추가한다.
"""

from typing import Protocol

from app.pipeline.query_processing.conditions import GameConditions


class QueryParser(Protocol):
    async def parse(self, question: str) -> GameConditions:
        """자연어를 검증된 조건으로 변환. 사용자가 생략한 조건은 추측하지 않는다."""
        ...
