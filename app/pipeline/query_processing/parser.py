"""질문 가공 담당: 자연어 질문을 `GameConditions`(conditions.py)로 바꾸는 계약.

구현은 같은 패키지의 `llm_parser.py`(OpenAI `gpt-4o-mini`)이고 프롬프트는 `prompts.py`에 있다.
키는 `app/config.py`의 `OPENAI_API_KEY`다.
"""

from typing import Protocol

from app.pipeline.query_processing.conditions import GameConditions


class QueryParser(Protocol):
    async def parse(self, question: str) -> GameConditions:
        """자연어를 검증된 조건으로 변환. 사용자가 생략한 조건은 추측하지 않는다."""
        ...
