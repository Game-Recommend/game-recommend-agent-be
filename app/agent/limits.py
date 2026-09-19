"""Tool별 호출 횟수 제한. 프롬프트의 "at most once"를 코드로 집행한다.

시스템 프롬프트는 같은 Tool을 다시 부르지 말라고 하지만 모델은 가끔 어긴다. "스토리 중심 게임
1개만"이라는 질문에서 통과 후보의 리뷰를 한 게임씩 여덟 번 읽다가 반복 상한(recursion_limit)에
걸려 502로 끝난 일이 있다(evals/agent_e2e/REPORT.md). 호출마다 igdb_id가 달라 인자 중복 검사로는
잡히지 않으므로 횟수를 센다.

두 겹으로 막는다.
- 실행 거부(`awrap_tool_call`): 상한을 넘긴 호출은 Tool 본문을 돌리지 않고 안내 문장만 돌려준다.
  한 턴에 같은 Tool을 여러 번 부른 경우도 여기서 걸린다.
- 목록에서 빼기(`awrap_model_call`): 한 번 거부된 Tool은 다음 모델 호출부터 주지 않는다. 모델이
  안내를 무시해도 같은 Tool을 더 부를 수 없다. 최종 출력(RecommendationDraft)은 ToolStrategy가 늘
  붙이고 tool_choice="any"로 강제하므로, 남은 Tool이 없으면 모델은 초안을 낼 수밖에 없다.

상한에 닿기만 한 Tool은 빼지 않는다. 정상 흐름에서는 Tool 목록이 바뀌지 않아 모델이 받는 입력도,
제공자의 프롬프트 캐시도 그대로다.

횟수는 요청 단위다(`AgentContext.tool_calls`). 후검증 재시도나 되묻기로 에이전트 루프에 다시
들어가도 이어서 센다. 러너가 직접 부르는 안전망·리뷰 요약은 ToolNode를 거치지 않아 세지 않는다.
"""

import logging
from collections.abc import Awaitable, Callable, Mapping

from langchain.agents.middleware import AgentMiddleware, ModelRequest, ModelResponse
from langchain_core.messages import ToolMessage
from langgraph.prebuilt.tool_node import ToolCallRequest
from langgraph.types import Command

from app.agent.context import AgentContext, dumps
from app.agent.prompts import build_call_limit_notice

logger = logging.getLogger(__name__)

# 요청 하나에서 LLM이 각 Tool을 실행할 수 있는 횟수.
# - 검색·가격·사양은 다시 불러도 결과가 같다(가격·사양은 서버가 후보 전체를 조회한다). 1회다.
# - 리뷰 Tool 둘은 모델이 igdb_id를 넘긴다. 후보에 없는 id를 넘겨 거부되면 고쳐서 다시 부를 수
#   있어야 하므로 2회다.
# 실측(같은 동작의 엔드투엔드 300건)에서 정상 흐름은 어떤 Tool도 두 번 부르지 않았다.
TOOL_CALL_LIMITS: Mapping[str, int] = {
    "search_games": 1,
    "get_prices": 1,
    "assess_hardware": 1,
    "get_review_scores": 2,
    "summarize_reviews": 2,
}


class ToolCallLimiter(AgentMiddleware):
    """`create_agent(middleware=[...])`에 넣는다. 표에 없는 Tool은 제한하지 않는다."""

    def __init__(self, limits: Mapping[str, int] = TOOL_CALL_LIMITS):
        super().__init__()
        self.limits = dict(limits)

    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command]],
    ) -> ToolMessage | Command:
        name = request.tool_call["name"]
        limit = self.limits.get(name)
        if limit is None:
            return await handler(request)
        calls = request.runtime.context.tool_calls
        # await 전에 센다. 한 턴의 호출들은 동시에 실행되므로, 실행이 끝난 뒤에 세면 같은 턴의
        # 중복이 모두 통과한다. 거부한 호출도 센다. 상한을 넘겼다는 기록이 다음 모델 호출에서
        # 이 Tool을 빼는 근거다.
        calls[name] += 1
        if calls[name] > limit:
            logger.info("Tool call over limit refused: %s (limit %d)", name, limit)
            return ToolMessage(
                content=dumps({"error": build_call_limit_notice(name, limit)}),
                name=name,
                tool_call_id=request.tool_call["id"],
                status="error",
            )
        result = await handler(request)
        if isinstance(result, ToolMessage) and result.status == "error":
            # 인자 검증에서 걸려 Tool 본문이 돌지 않았다. 고쳐서 다시 부를 수 있게 되돌린다.
            # (본문이 돈 뒤의 실패는 run_stage가 오류 JSON으로 바꿔 정상 상태로 돌려준다)
            calls[name] -= 1
        return result

    async def awrap_model_call(
        self,
        request: ModelRequest[AgentContext],
        handler: Callable[[ModelRequest[AgentContext]], Awaitable[ModelResponse]],
    ) -> ModelResponse:
        calls = request.runtime.context.tool_calls
        refused = {name for name, limit in self.limits.items() if calls[name] > limit}
        if refused:
            tools = [
                tool for tool in request.tools if isinstance(tool, dict) or tool.name not in refused
            ]
            request = request.override(tools=tools)
        return await handler(request)
