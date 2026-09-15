"""에이전트 추천기.

LangChain `create_agent`로 Tool 호출 루프를 돌리고, 결과를 검증해 응답으로 만든다.

흐름
1. 질문 분해: 파서(팀원 모듈)로 GameConditions를 만든다. 기준값은 여기서 나와 Tool에 주입된다.
2. 에이전트 루프: LLM이 search_games → get_prices·assess_hardware(같은 턴 병렬) →
   summarize_reviews를 골라 부르고 RecommendationDraft를 제출한다.
   반복 상한은 recursion_limit, 전체 시간은 total_timeout이다.
3. 안전망: 추천 후보 중 가격·사양을 조회하지 않은 게임은 러너가 직접 조회한다. README의
   "실패나 누락은 필수 조건 통과로 처리하지 않는다"를 모델의 성실함에 맡기지 않는다.
4. 후검증: 후보에 있는 id인지, 판정을 통과했는지, 개수 이하인지 검사한다. 위반하면 거부 사유를
   메시지로 붙여 한 번 더 호출하고, 그래도 안 되면 502다.
5. 후처리: 확정 후보의 리뷰 요약(미조회분)과 미디어를 붙이고 RecommendationResponse를 만든다.

진행 이벤트는 Tool 안(`AgentContext.run_stage`)에서 나오므로 고정 파이프라인과 같은
SSE 인코더를 쓴다.
단계 이름: 질문 분해, 에이전트 추론, 게임 검색, 가격, 하드웨어, 리뷰 요약, 조건 판정, 미디어.
"""

import asyncio
import logging
from collections.abc import AsyncIterator

from langchain.agents import create_agent
from langchain.agents.structured_output import ToolStrategy
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, AnyMessage, HumanMessage

from app.agent.context import AgentContext, CandidateStore, ToolSet, unique
from app.agent.prompts import AGENT_SYSTEM, build_rejection, build_user_input
from app.agent.schemas import RecommendationDraft
from app.agent.tools import build_tools
from app.agent.tools import hardware as hardware_tool
from app.agent.tools import price as price_tool
from app.agent.tools import reviews as reviews_tool
from app.pipeline.progress import PipelineStageError, Progress, silent, stream_progress
from app.pipeline.query_processing.parser import QueryParser
from app.schemas.recommendation import PipelineEvent, RecommendationResponse

logger = logging.getLogger(__name__)

AGENT_STAGE = "에이전트 추론"
# ToolStrategy가 최종 출력을 이 이름의 도구 호출로 받는다
DRAFT_TOOL_NAME = RecommendationDraft.__name__


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
    """`Recommender` 계약 구현. 고정 파이프라인(`RecommendationOrchestrator`)과 같은 응답을 낸다."""

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

    def stream(self, question: str) -> AsyncIterator[PipelineEvent]:
        return stream_progress(self.run, question)

    def graph_mermaid(self) -> str:
        """발표·문서용 그래프."""
        return self.agent.get_graph().draw_mermaid()

    async def run(self, question: str, progress: Progress = silent) -> RecommendationResponse:
        progress("질문 분해", "started", None)
        try:
            conditions = await asyncio.wait_for(
                self.parser.parse(question), timeout=self.stage_timeout_seconds
            )
        except Exception as exc:
            logger.warning("Query parsing failed (%s)", type(exc).__name__)
            progress("질문 분해", "failed", None)
            raise PipelineStageError("질문 분해 단계를 완료하지 못했습니다.") from exc
        progress("질문 분해", "completed", None)

        store = CandidateStore(conditions)
        ctx = AgentContext(
            conditions=conditions,
            store=store,
            tools=self.tools,
            progress=progress,
            stage_timeout_seconds=self.stage_timeout_seconds,
        )
        draft = await self._decide(question, ctx)
        ids = unique(draft.recommended_igdb_ids)
        excluded = len(store.excluded_ids(ids))
        progress("조건 판정", "completed", f"추천 {len(ids)}개, 제외 {excluded}개")

        await self._finalize(ids, ctx)
        evidence = store.build_evidence(ids)
        for result in evidence.games:
            if result.review is None:
                evidence.warnings.append(f"{result.game.name}: 리뷰 요약 확인 불가")
            if result.price.quote is None:
                evidence.warnings.append(f"{result.game.name}: 원화 가격 확인 불가")
        if not ids:
            evidence.warnings.append("모든 필수 조건을 충족한다고 확인된 후보가 없습니다.")
        return RecommendationResponse(**evidence.model_dump(), answer=draft.answer)

    async def _decide(self, question: str, ctx: AgentContext) -> RecommendationDraft:
        """에이전트 루프 + 안전망 + 후검증. 통과한 초안만 돌려준다."""
        ctx.progress(AGENT_STAGE, "started", None)
        opening = HumanMessage(content=build_user_input(question, ctx.conditions))
        messages: list[AnyMessage] = [opening]
        try:
            draft, messages = await self._invoke(messages, ctx)
            for attempt in range(self.max_validation_retries + 1):
                await self._ensure_checks(draft, ctx)
                problems = ctx.store.validate_draft(draft)
                if not problems:
                    break
                if attempt == self.max_validation_retries:
                    logger.warning("Agent draft rejected after retries: %s", problems)
                    raise PipelineStageError("에이전트가 조건에 맞는 추천을 확정하지 못했습니다.")
                logger.info("Agent draft rejected, retrying: %s", problems)
                messages.append(HumanMessage(content=build_rejection(problems)))
                draft, messages = await self._invoke(messages, ctx)
        except PipelineStageError:
            ctx.progress(AGENT_STAGE, "failed", None)
            raise
        except Exception as exc:
            logger.warning("Agent loop failed (%s)", type(exc).__name__)
            ctx.progress(AGENT_STAGE, "failed", None)
            raise PipelineStageError("에이전트 추론 단계를 완료하지 못했습니다.") from exc
        ctx.progress(AGENT_STAGE, "completed", f"도구 호출 {count_tool_calls(messages)}회")
        return draft

    async def _invoke(
        self, messages: list[AnyMessage], ctx: AgentContext
    ) -> tuple[RecommendationDraft, list[AnyMessage]]:
        result = await asyncio.wait_for(
            self.agent.ainvoke(
                {"messages": messages},
                context=ctx,
                config={"recursion_limit": self.recursion_limit},
            ),
            timeout=self.total_timeout_seconds,
        )
        draft = result.get("structured_response")
        if not isinstance(draft, RecommendationDraft):
            raise PipelineStageError("에이전트가 추천을 확정하지 못했습니다.")
        return draft, list(result["messages"])

    async def _ensure_checks(self, draft: RecommendationDraft, ctx: AgentContext) -> None:
        """안전망: 추천 후보 중 가격·사양을 조회하지 않은 게임을 러너가 직접 조회한다."""
        known = ctx.store.candidates
        ids = [igdb_id for igdb_id in unique(draft.recommended_igdb_ids) if igdb_id in known]
        pending = []
        if missing := [igdb_id for igdb_id in ids if igdb_id not in ctx.store.prices]:
            pending.append(ctx.run_stage(price_tool.STAGE, price_tool.fetch_prices(ctx, missing)))
        if missing := [igdb_id for igdb_id in ids if igdb_id not in ctx.store.hardware]:
            pending.append(ctx.run_stage(hardware_tool.STAGE, hardware_tool.assess(ctx, missing)))
        if pending:
            await asyncio.gather(*pending)

    async def _finalize(self, ids: list[int], ctx: AgentContext) -> None:
        """확정 후보의 리뷰 요약(미조회분)과 미디어를 병렬로 붙인다. 실패는 경고만 남긴다."""
        if not ids:
            return
        games = ctx.store.resolve(ids)
        pending = []
        if missing := [game.igdb_id for game in games if game.igdb_id not in ctx.store.reviews]:
            pending.append(ctx.run_stage(reviews_tool.STAGE, reviews_tool.summarize(ctx, missing)))
        if self.tools.media is not None:
            pending.append(self._media(games, ctx))
        await asyncio.gather(*pending)

    async def _media(self, games, ctx: AgentContext) -> None:
        assert self.tools.media is not None
        media = await ctx.optional("미디어", self.tools.media.run(games))
        if media:
            ctx.store.media.update(media)


def draw_graph() -> str:
    """모델 없이 그래프만 그린다. `make graph`가 부른다."""
    from langchain_core.language_models.fake_chat_models import GenericFakeChatModel

    agent = create_agent(
        GenericFakeChatModel(messages=iter([])),
        build_tools(),
        system_prompt=AGENT_SYSTEM,
        context_schema=AgentContext,
        response_format=ToolStrategy(RecommendationDraft),
    )
    return agent.get_graph().draw_mermaid()


if __name__ == "__main__":
    print(draw_graph())
