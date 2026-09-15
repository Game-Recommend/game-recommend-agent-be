"""OpenAIAnswerer 호출 경계 검증. 실제 OpenAI 호출은 하지 않는다."""

import asyncio
from types import SimpleNamespace

import pytest

from app.config import Settings
from app.pipeline.final_answer.llm_answerer import OpenAIAnswerer
from app.pipeline.final_answer.prompts import ANSWER_SYSTEM
from app.pipeline.query_processing.conditions import GameConditions
from app.schemas.recommendation import RecommendationEvidence


class _FakeResponses:
    def __init__(self, output_text: str):
        self.output_text = output_text
        self.kwargs: dict | None = None

    async def create(self, **kwargs):
        self.kwargs = kwargs
        return SimpleNamespace(output_text=self.output_text)


def _client(output_text: str):
    responses = _FakeResponses(output_text)
    return SimpleNamespace(responses=responses), responses


def test_generate_sends_system_prompt_and_built_input():
    client, responses = _client("  요약 답변  ")
    evidence = RecommendationEvidence(conditions=GameConditions(max_price_krw=30000))

    answer = asyncio.run(OpenAIAnswerer(client, "test-model").generate("3만 원 게임", evidence))

    assert answer == "요약 답변"
    assert responses.kwargs["model"] == "test-model"
    assert responses.kwargs["instructions"] == ANSWER_SYSTEM
    assert "3만 원 게임" in responses.kwargs["input"]
    assert "예산: 30,000원 이하" in responses.kwargs["input"]


def test_generate_rejects_empty_output():
    client, _ = _client("")
    evidence = RecommendationEvidence(conditions=GameConditions())

    with pytest.raises(ValueError, match="빈 응답"):
        asyncio.run(OpenAIAnswerer(client, "m").generate("질문", evidence))


def test_from_settings_requires_api_key():
    with pytest.raises(ValueError, match="OPENAI_API_KEY"):
        OpenAIAnswerer.from_settings(Settings(openai_api_key="", _env_file=None))

    answerer = OpenAIAnswerer.from_settings(
        Settings(openai_api_key="sk-test", openai_model="gpt-test", _env_file=None)
    )
    assert answerer.model == "gpt-test"
