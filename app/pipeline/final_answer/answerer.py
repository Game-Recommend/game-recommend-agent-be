"""가격·하드웨어·최종 답변 담당: 후보와 리뷰 요약으로 최종 답변을 생성하는 계약.

질문 가공과 별도 구현체·프롬프트를 사용한다. 실제 LLM 연동은 이 패키지에 추가한다.
"""

from typing import Protocol

from app.schemas.recommendation import RecommendationEvidence


class Answerer(Protocol):
    async def generate(self, question: str, evidence: RecommendationEvidence) -> str:
        """games만 추천하고 근거·누락 정보를 설명한다. 제외 후보를 추천하지 않는다.

        games가 비었으면 충족 후보가 없음을 설명한다. 조건을 임의로 완화하지 않는다.
        """
        ...
