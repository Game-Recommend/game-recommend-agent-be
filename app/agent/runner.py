"""에이전트 추천기.

요청 한 건의 흐름이 LangGraph `StateGraph` 하나다. LangChain `create_agent`가 만든 Tool 호출 루프는
그 안의 서브그래프 노드다.

그래프 (`make graph`로 출력)
1. parse: 질문 분해. 파서(팀원 모듈)로 GameConditions를 만든다. 기준값은 여기서 나와 Tool에
   주입된다.
2. agent: 에이전트 루프. LLM이 search_games → get_prices·assess_hardware(같은 턴 병렬) →
   summarize_reviews를 골라 부르고 RecommendationDraft를 제출한다.
   반복 상한은 recursion_limit, 한 번의 루프 시간은 total_timeout(노드 timeout)이다.
3. safety_net: 안전망. 추천 후보 중 가격·사양을 조회하지 않은 게임은 러너가 직접 조회한다. README의
   "실패나 누락은 필수 조건 통과로 처리하지 않는다"를 모델의 성실함에 맡기지 않는다.
4. validate: 후검증. 후보에 있는 id인지, 판정을 통과했는지, 개수 이하인지 검사한다. 위반하면
   retry가 거부 사유를 메시지로 붙여 agent로 돌려보내고, 그래도 안 되면 502다.
   위반은 아니지만 되물을 일이 두 가지 있다. 각각 한 번만 되묻고, 재시도 횟수를 쓰지 않으며,
   다시 같은 결과면 에이전트의 판단으로 받는다.
   - 빈 초안인데 판정을 통과한 후보가 남아 있다. 모델이 status=skipped를 "확인 못 함"으로 읽고
     빈손으로 끝내는 일을 막는다.
   - 추천 목록의 게임 이름이 answer에 없다. 카드와 본문이 다른 게임을 말하는 일을 막는다.
5. judge → reviews·media(병렬) → respond: 확정 후보의 리뷰 요약(미조회분)과 미디어를 붙이고
   RecommendationResponse를 만든다.

후보와 도구 결과는 그래프 state가 아니라 컨텍스트(`AgentContext.store`)에 쌓는다. Tool이 컨텍스트만
받기 때문이다. state에는 메시지·초안·재시도 횟수처럼 노드 사이를 오가는 값만 둔다.

진행 이벤트는 노드와 Tool 안(`AgentContext.run_stage`)에서 나와 `stream_progress`가 SSE로 흘린다.
단계 이름: 질문 분해, 에이전트 추론, 게임 검색, 가격, 하드웨어, 리뷰 요약, 조건 판정, 미디어.
"""

import asyncio
import logging
from collections.abc import AsyncIterator
from typing import Annotated, Literal, NotRequired, TypedDict

from langchain.agents import create_agent
from langchain.agents.structured_output import ToolStrategy
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, AnyMessage, HumanMessage
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.graph.state import CompiledStateGraph
from langgraph.runtime import Runtime

from app.agent.context import AgentContext, ToolSet, unique
from app.agent.progress import PipelineStageError, Progress, silent, stream_progress
from app.agent.prompts import (
    AGENT_SYSTEM,
    build_empty_challenge,
    build_name_challenge,
    build_rejection,
    build_user_input,
)
from app.agent.schemas import RecommendationDraft
from app.agent.tools import build_tools
from app.agent.tools import hardware as hardware_tool
from app.agent.tools import price as price_tool
from app.agent.tools import reviews as reviews_tool
from app.pipeline.query_processing.parser import QueryParser
from app.schemas.recommendation import PipelineEvent, RecommendationResponse

logger = logging.getLogger(__name__)

AGENT_STAGE = "에이전트 추론"
# ToolStrategy가 최종 출력을 이 이름의 도구 호출로 받는다
DRAFT_TOOL_NAME = RecommendationDraft.__name__


class PipelineState(TypedDict):
    """노드 사이를 오가는 값. `messages`·`structured_response`는 agent 서브그래프와 같은 키다."""

    question: str
    messages: Annotated[list[AnyMessage], add_messages]
    structured_response: NotRequired[RecommendationDraft | None]
    attempts: NotRequired[int]  # 후검증에서 거부된 횟수
    problems: NotRequired[list[str]]  # 마지막 후검증의 거부 사유
    overlooked: NotRequired[list[int]]  # 빈 초안인데 판정을 통과한 후보 (되물을 대상)
    unmentioned: NotRequired[list[int]]  # 추천했는데 answer에 이름이 없는 게임 (되물을 대상)
    asked: NotRequired[list[str]]  # 이미 한 되묻기 종류("empty", "names"). 종류마다 한 번만 한다
    # 되묻기 전의 초안. 후검증은 통과한 초안이라, 되물은 뒤의 초안이 끝내 거부되면 여기로 돌아간다
    fallback_draft: NotRequired[RecommendationDraft | None]
    recommended_ids: NotRequired[list[int]]
    response: NotRequired[RecommendationResponse]


def count_tool_calls(messages: list[AnyMessage]) -> int:
    """에이전트가 부른 도메인 Tool 횟수. 최종 출력용 도구 호출은 세지 않는다."""
    return sum(
        1
        for message in messages
        if isinstance(message, AIMessage)
        for call in message.tool_calls
        if call["name"] != DRAFT_TOOL_NAME
    )


class AgentRecommender:
    """`Recommender` 계약 구현."""

    def __init__(
        self,
        parser: QueryParser,
        tools: ToolSet,
        model: BaseChatModel,
        *,
        system_prompt: str = AGENT_SYSTEM,
        stage_timeout_seconds: float = 30,
        total_timeout_seconds: float = 120,
        recursion_limit: int = 20,
        max_validation_retries: int = 1,
    ):
        if stage_timeout_seconds <= 0 or total_timeout_seconds <= 0:
            raise ValueError("timeouts must be positive")
        self.parser = parser
        self.tools = tools
        self.stage_timeout_seconds = stage_timeout_seconds
        self.total_timeout_seconds = total_timeout_seconds
        self.recursion_limit = recursion_limit
        self.max_validation_retries = max_validation_retries
        self.agent = create_agent(
            model,
            build_tools(),
            system_prompt=system_prompt,
            context_schema=AgentContext,
            # 최종 출력을 도구 호출로 받는다. 어떤 tool-calling 모델과도 같은 경로로 동작하고,
            # 모델이 자유 텍스트로 끝내지 못하게 한다.
            response_format=ToolStrategy(RecommendationDraft),
        )
        self.graph = self._build_graph()

    def _build_graph(self) -> CompiledStateGraph:
        builder = StateGraph(PipelineState, context_schema=AgentContext)
        builder.add_node("parse", self._parse)
        # 컴파일된 에이전트를 그대로 노드로 붙인다. messages·structured_response 키와 컨텍스트를
        # 부모와 공유한다. timeout은 루프 한 번(재시도마다 새로)의 상한이다.
        builder.add_node("agent", self.agent, timeout=self.total_timeout_seconds)
        builder.add_node("safety_net", self._safety_net)
        builder.add_node("validate", self._validate)
        builder.add_node("retry", self._retry)
        builder.add_node("judge", self._judge)
        builder.add_node("reviews", self._reviews)
        builder.add_node("media", self._media)
        builder.add_node("respond", self._respond)

        builder.add_edge(START, "parse")
        builder.add_edge("parse", "agent")
        builder.add_edge("agent", "safety_net")
        builder.add_edge("safety_net", "validate")
        builder.add_conditional_edges("validate", self._route, {"retry": "retry", "judge": "judge"})
        builder.add_edge("retry", "agent")
        # 리뷰 요약과 미디어는 같은 단계에서 병렬로 돌고 respond에서 만난다
        builder.add_edge("judge", "reviews")
        builder.add_edge("judge", "media")
        builder.add_edge(["reviews", "media"], "respond")
        builder.add_edge("respond", END)
        return builder.compile()

    def stream(self, question: str) -> AsyncIterator[PipelineEvent]:
        return stream_progress(self.run, question)

    def graph_mermaid(self) -> str:
        """발표·문서용 그래프. agent 서브그래프(model·tools)까지 펼친다."""
        return self.graph.get_graph(xray=1).draw_mermaid()

    async def run(self, question: str, progress: Progress = silent) -> RecommendationResponse:
        ctx = AgentContext.pending(self.tools, progress, self.stage_timeout_seconds)
        # 서브그래프는 같은 상한을 자기 카운터로 센다. 부모 노드 수가 상한에 걸리지 않게만 한다.
        # 루프는 첫 시도 + 거부 재시도 + 되묻기 두 종류(빈 초안, 이름)다.
        pipeline_steps = 4 * (self.max_validation_retries + 3) + 4
        try:
            result = await self.graph.ainvoke(
                {"question": question, "messages": []},
                context=ctx,
                config={"recursion_limit": max(self.recursion_limit, pipeline_steps)},
            )
        except PipelineStageError:
            raise  # 실패 이벤트는 노드가 이미 냈다
        except Exception as exc:
            # 노드가 다루지 않는 실패는 agent 서브그래프에서 난다 (모델 오류·반복 상한·시간 초과)
            logger.warning("Agent loop failed (%s)", type(exc).__name__)
            ctx.progress(AGENT_STAGE, "failed", None)
            raise PipelineStageError("에이전트 추론 단계를 완료하지 못했습니다.") from exc
        return result["response"]

    # --- 노드 ---

    async def _parse(self, state: PipelineState, runtime: Runtime[AgentContext]) -> dict:
        ctx = runtime.context
        ctx.progress("질문 분해", "started", None)
        try:
            conditions = await asyncio.wait_for(
                self.parser.parse(state["question"]), timeout=self.stage_timeout_seconds
            )
        except Exception as exc:
            logger.warning("Query parsing failed (%s)", type(exc).__name__)
            ctx.progress("질문 분해", "failed", None)
            raise PipelineStageError("질문 분해 단계를 완료하지 못했습니다.") from exc
        ctx.progress("질문 분해", "completed", None)
        ctx.begin(conditions)
        # 에이전트 추론 단계는 재시도를 포함해 judge까지 이어진다
        ctx.progress(AGENT_STAGE, "started", None)
        opening = HumanMessage(content=build_user_input(state["question"], conditions))
        return {"messages": [opening], "attempts": 0}

    async def _safety_net(self, state: PipelineState, runtime: Runtime[AgentContext]) -> dict:
        """안전망: 추천 후보 중 가격·사양을 조회하지 않은 게임을 러너가 직접 조회한다."""
        ctx = runtime.context
        draft = state.get("structured_response")
        if not isinstance(draft, RecommendationDraft):
            ctx.progress(AGENT_STAGE, "failed", None)
            raise PipelineStageError("에이전트가 추천을 확정하지 못했습니다.")
        known = ctx.store.candidates
        ids = [igdb_id for igdb_id in unique(draft.recommended_igdb_ids) if igdb_id in known]
        pending = []
        if missing := [igdb_id for igdb_id in ids if igdb_id not in ctx.store.prices]:
            pending.append(ctx.run_stage(price_tool.STAGE, price_tool.fetch_prices(ctx, missing)))
        if missing := [igdb_id for igdb_id in ids if igdb_id not in ctx.store.hardware]:
            pending.append(ctx.run_stage(hardware_tool.STAGE, hardware_tool.assess(ctx, missing)))
        if pending:
            await asyncio.gather(*pending)
        return {}

    async def _validate(self, state: PipelineState, runtime: Runtime[AgentContext]) -> dict:
        """후검증. 거부 사유가 남고 재시도도 다 썼으면 필수 단계 실패다.

        거부 사유가 없어도 되물을 일이 있으면 종류마다 한 번만 되묻는다. 빈 초안인데 통과 후보가
        있는 경우와, 추천한 게임 이름이 answer에 없는 경우다.
        """
        ctx = runtime.context
        draft = state["structured_response"]
        problems = ctx.store.validate_draft(draft)
        if problems and state["attempts"] >= self.max_validation_retries:
            if (fallback := state.get("fallback_draft")) is not None:
                # 되물은 뒤의 초안이 끝내 검증을 통과하지 못했다. 되묻기가 200이던 응답을 502로
                # 바꾸지 않도록, 되묻기 전의 초안으로 돌아간다.
                logger.warning("Draft after challenge rejected, keeping earlier: %s", problems)
                return {
                    "structured_response": fallback,
                    "problems": [],
                    "overlooked": [],
                    "unmentioned": [],
                }
            logger.warning("Agent draft rejected after retries: %s", problems)
            ctx.progress(AGENT_STAGE, "failed", None)
            raise PipelineStageError("에이전트가 조건에 맞는 추천을 확정하지 못했습니다.")
        asked = state.get("asked") or []
        overlooked: list[int] = []
        unmentioned: list[int] = []
        if not problems:
            if not draft.recommended_igdb_ids:
                overlooked = ctx.store.passing_ids() if "empty" not in asked else []
            elif "names" not in asked:
                unmentioned = ctx.store.unmentioned_ids(draft)
        return {"problems": problems, "overlooked": overlooked, "unmentioned": unmentioned}

    @staticmethod
    def _route(state: PipelineState) -> Literal["retry", "judge"]:
        asking = state["problems"] or state["overlooked"] or state["unmentioned"]
        return "retry" if asking else "judge"

    async def _retry(self, state: PipelineState, runtime: Runtime[AgentContext]) -> dict:
        """메시지를 붙여 agent로 돌려보낸다. 지난 초안은 지운다.

        거부면 사유를 붙이고 재시도 횟수를 센다. 되묻기면 횟수를 세지 않는 대신 되물은 종류와
        지금의 초안을 남겨 둔다(같은 것을 다시 묻지 않고, 뒤의 초안이 거부되면 돌아갈 자리다).
        """
        if state["problems"]:
            logger.info("Agent draft rejected, retrying: %s", state["problems"])
            return {
                "messages": [HumanMessage(content=build_rejection(state["problems"]))],
                "structured_response": None,
                "attempts": state["attempts"] + 1,
            }
        ctx = runtime.context
        draft = state["structured_response"]
        if state["overlooked"]:
            kind = "empty"
            games = ctx.store.resolve(state["overlooked"])
            logger.info("Empty draft with %d passing candidates, asking once more", len(games))
            challenge = build_empty_challenge(games, ctx.conditions.recommendation_count)
        else:
            kind = "names"
            missing = ctx.store.resolve(state["unmentioned"])
            logger.info("Answer omits %d recommended games, asking once more", len(missing))
            recommended = ctx.store.resolve(unique(draft.recommended_igdb_ids))
            challenge = build_name_challenge(missing, recommended)
        return {
            "messages": [HumanMessage(content=challenge)],
            "structured_response": None,
            "fallback_draft": draft,
            "asked": [*(state.get("asked") or []), kind],
        }

    async def _judge(self, state: PipelineState, runtime: Runtime[AgentContext]) -> dict:
        ctx = runtime.context
        ctx.progress(AGENT_STAGE, "completed", f"도구 호출 {count_tool_calls(state['messages'])}회")
        ids = unique(state["structured_response"].recommended_igdb_ids)
        # 추천은 후검증을 통과했으므로 조회에 실패해 checked가 아니어도 통과로 센다
        passing = len(set(ctx.store.passing_ids()) | set(ids))
        excluded = len(ctx.store.excluded_ids(ids))
        ctx.progress(
            "조건 판정", "completed", f"통과 {passing}개 중 {len(ids)}개 추천, 제외 {excluded}개"
        )
        return {"recommended_ids": ids}

    async def _reviews(self, state: PipelineState, runtime: Runtime[AgentContext]) -> dict:
        """확정 후보의 리뷰 요약(미조회분). 실패는 경고만 남긴다."""
        ctx = runtime.context
        ids = state["recommended_ids"]
        if missing := [igdb_id for igdb_id in ids if igdb_id not in ctx.store.reviews]:
            await ctx.run_stage(reviews_tool.STAGE, reviews_tool.summarize(ctx, missing))
        return {}

    async def _media(self, state: PipelineState, runtime: Runtime[AgentContext]) -> dict:
        """확정 후보의 미디어. 실패는 경고만 남긴다."""
        ctx = runtime.context
        if self.tools.media is None or not state["recommended_ids"]:
            return {}
        games = ctx.store.resolve(state["recommended_ids"])
        media = await ctx.optional("미디어", self.tools.media.run(games))
        if media:
            ctx.store.media.update(media)
        return {}

    async def _respond(self, state: PipelineState, runtime: Runtime[AgentContext]) -> dict:
        ids = state["recommended_ids"]
        evidence = runtime.context.store.build_evidence(ids)
        for result in evidence.games:
            if result.review is None:
                evidence.warnings.append(f"{result.game.name}: 리뷰 요약 확인 불가")
            if result.price.quote is None:
                evidence.warnings.append(f"{result.game.name}: 원화 가격 확인 불가")
        if not ids:
            evidence.warnings.append("모든 필수 조건을 충족한다고 확인된 후보가 없습니다.")
        answer = state["structured_response"].answer
        return {"response": RecommendationResponse(**evidence.model_dump(), answer=answer)}


def draw_graph() -> str:
    """모델 없이 그래프만 그린다. `make graph`가 부른다."""
    from langchain_core.language_models.fake_chat_models import GenericFakeChatModel

    from app.pipeline.query_processing.llm_parser import LLMQueryParser

    # 그래프 모양은 parser·tools·model 인스턴스와 무관하다. 호출하지 않으므로 대역을 넣는다.
    recommender = AgentRecommender(
        LLMQueryParser(),
        None,  # type: ignore[arg-type]
        GenericFakeChatModel(messages=iter([])),
    )
    return recommender.graph_mermaid()


if __name__ == "__main__":
    print(draw_graph())
