from app.pipeline.query_processing.conditions import GameConditions


class FakeQueryParser:
    """질문 가공 담당의 전용 대역. 실제 LLM 품질 검증용이 아니다."""

    def __init__(self, conditions: GameConditions, calls: list[str] | None = None):
        self.conditions = conditions
        self.calls = calls if calls is not None else []

    async def parse(self, question: str) -> GameConditions:
        self.calls.append("parse")
        return self.conditions
