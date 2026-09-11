from app.schemas.recommendation import RecommendationEvidence


class FakeAnswerer:
    """가격·하드웨어·최종 답변 담당의 답변 전용 대역. 질문 분해와 독립적이다."""

    def __init__(self, calls: list[str] | None = None, answer: str = "테스트 답변"):
        self.calls = calls if calls is not None else []
        self.answer = answer
        self.question: str | None = None
        self.evidence: RecommendationEvidence | None = None

    async def generate(self, question: str, evidence: RecommendationEvidence) -> str:
        self.calls.append("answer")
        self.question = question
        self.evidence = evidence
        return self.answer
