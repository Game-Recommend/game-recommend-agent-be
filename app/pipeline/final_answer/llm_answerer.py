"""가격·하드웨어·최종 답변 담당: OpenAI로 화면 상단 요약 답변을 생성하는 `Answerer` 구현."""

import logging

from openai import AsyncOpenAI

from app.config import Settings, get_settings
from app.pipeline.final_answer.prompts import ANSWER_SYSTEM, build_answer_input
from app.schemas.recommendation import RecommendationEvidence

logger = logging.getLogger(__name__)


class OpenAIAnswerer:
    """`Answerer` 계약 구현. 프롬프트 구성은 `prompts.build_answer_input`이 담당한다."""

    def __init__(self, client: AsyncOpenAI, model: str):
        self.client = client
        self.model = model

    @classmethod
    def from_settings(cls, settings: Settings | None = None) -> "OpenAIAnswerer":
        settings = settings or get_settings()
        if not settings.openai_api_key:
            raise ValueError("OPENAI_API_KEY가 설정되지 않았습니다.")
        return cls(AsyncOpenAI(api_key=settings.openai_api_key), settings.openai_model)

    async def generate(self, question: str, evidence: RecommendationEvidence) -> str:
        response = await self.client.responses.create(
            model=self.model,
            instructions=ANSWER_SYSTEM,
            input=build_answer_input(question, evidence),
        )
        answer = (response.output_text or "").strip()
        if not answer:
            logger.warning("Final answer LLM returned empty output (model=%s)", self.model)
            raise ValueError("최종 답변 LLM이 빈 응답을 반환했습니다.")
        return answer
