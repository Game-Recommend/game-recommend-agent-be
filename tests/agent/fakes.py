"""에이전트 계층 전용 대역: 대본대로 tool_calls를 내는 가짜 ChatModel. OpenAI를 부르지 않는다."""

import itertools

from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage

from app.agent.runner import DRAFT_TOOL_NAME

_ids = itertools.count(1)


class ScriptedChatModel(GenericFakeChatModel):
    """`messages` 순서대로 AIMessage를 돌려준다.

    create_agent가 부르는 bind_tools는 자기 자신을 돌려준다.
    """

    def bind_tools(self, tools, **kwargs):
        return self


def tool_calls(*calls: tuple[str, dict]) -> AIMessage:
    """한 턴에 여러 Tool을 동시에 부르는 AIMessage."""
    return AIMessage(
        content="",
        tool_calls=[
            {"name": name, "args": args, "id": f"call-{next(_ids)}-{name}"} for name, args in calls
        ],
    )


def draft(ids: list[int], answer: str = "테스트 답변") -> AIMessage:
    """최종 출력(RecommendationDraft) 제출. ToolStrategy는 이를 같은 이름의 도구 호출로 받는다."""
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
