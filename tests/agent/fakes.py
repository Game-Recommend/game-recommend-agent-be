"""에이전트 계층 전용 대역: 대본대로 tool_calls를 내는 가짜 ChatModel. OpenAI를 부르지 않는다."""

import itertools

from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage, BaseMessage
from pydantic import Field

from app.agent.runner import DRAFT_TOOL_NAME

_ids = itertools.count(1)


class ScriptedChatModel(GenericFakeChatModel):
    """`messages` 순서대로 AIMessage를 돌려준다.

    create_agent가 모델을 부를 때마다 거치는 bind_tools는 자기 자신을 돌려주고, 그때 받은 Tool
    이름을 `offered`에 남긴다. 호출마다 받은 메시지(시스템 프롬프트 포함)는 `received`에 남는다.
    """

    offered: list[list[str]] = Field(default_factory=list)
    received: list[list[BaseMessage]] = Field(default_factory=list)

    def bind_tools(self, tools, **kwargs):
        self.offered.append([tool.name for tool in tools])
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        self.received.append(list(messages))
        return super()._generate(messages, stop=stop, run_manager=run_manager, **kwargs)


def tool_calls(*calls: tuple[str, dict]) -> AIMessage:
    """한 턴에 여러 Tool을 동시에 부르는 AIMessage."""
    return AIMessage(
        content="",
        tool_calls=[
            {"name": name, "args": args, "id": f"call-{next(_ids)}-{name}"} for name, args in calls
        ],
    )


def draft(ids: list[int], answer: str | None = None) -> AIMessage:
    """최종 출력(RecommendationDraft) 제출. ToolStrategy는 이를 같은 이름의 도구 호출로 받는다.

    러너는 추천한 게임 이름이 answer에 없으면 되묻는다. 그래서 기본 답변은 대역 후보의
    이름(Game N)을 담는다.
    """
    if answer is None:
        answer = " ".join(["테스트 답변", *(f"Game {igdb_id}" for igdb_id in ids)])
    return tool_calls((DRAFT_TOOL_NAME, {"recommended_igdb_ids": ids, "answer": answer}))


def search(**args) -> AIMessage:
    return tool_calls(("search_games", args))


def checks(ids: list[int]) -> AIMessage:
    """가격·사양을 같은 턴에 병렬로 부른다."""
    return tool_calls(("get_prices", {"igdb_ids": ids}), ("assess_hardware", {"igdb_ids": ids}))


def reviews(ids: list[int]) -> AIMessage:
    return tool_calls(("summarize_reviews", {"igdb_ids": ids}))


def scripted(*messages: AIMessage) -> ScriptedChatModel:
    return ScriptedChatModel(messages=iter(messages))
