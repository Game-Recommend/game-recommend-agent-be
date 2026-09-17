"""에이전트 계층 공통 계약: Tool 묶음, 요청 컨텍스트, 후보 저장소.

Tool 파일(app/agent/tools/*.py)은 여기 정의된 규약만 쓴다.
- 기준값(예산·사용자 사양·추천 개수)은 LLM이 인자로 넘기지 않고
  `AgentContext.conditions`에서 읽는다.
- Tool은 igdb_id 목록을 받고 `CandidateStore.resolve()`로 후보 객체를 되찾는다.
- Tool은 LLM에 줄 압축 JSON(dict)을 돌려주고, 응답용 전체 pydantic 모델은 `CandidateStore`에 쌓는다.
- Tool 본문은 `AgentContext.run_stage()`로 감싸 진행 이벤트·시간 제한·실패 처리를 공통으로 한다.
"""

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from app.agent.progress import Progress, silent
from app.agent.schemas import RecommendationDraft
from app.pipeline.query_processing.conditions import GameConditions
from app.schemas.common import ConditionCheck
from app.schemas.game import GameCandidate
from app.schemas.hardware import HardwareResult
from app.schemas.media import GameMedia
from app.schemas.price import PriceResult
from app.schemas.recommendation import EvaluatedGame, RecommendationEvidence
from app.schemas.review import ReviewSummary
from app.tools.game_search import GameSearchTool
from app.tools.hardware import HardwareTool
from app.tools.media import MediaTool
from app.tools.price import PriceTool
from app.tools.review_score import ReviewScoreTool
from app.tools.review_summary import ReviewSummaryTool

logger = logging.getLogger(__name__)

# 통과 규칙: 필수 조건 판정이 met이거나 조건이 없어 skipped인 경우만 추천한다.
PASSING = frozenset({"met", "skipped"})
STATUS_LABELS = {"met": "충족", "unmet": "미충족", "unknown": "확인 불가", "skipped": "검사 생략"}


def unique(igdb_ids: list[int]) -> list[int]:
    """순서를 지키며 중복을 없앤다."""
    return list(dict.fromkeys(igdb_ids))


def dumps(payload: dict) -> str:
    """LLM에 돌려줄 Tool 결과. 한글을 이스케이프하지 않아 토큰을 아낀다."""
    return json.dumps(payload, ensure_ascii=False)


@dataclass
class ToolSet:
    """assembly.py가 한 번 만들어 모든 요청이 공유하는 서비스 도구. 팀원 모듈을 그대로 감싼다."""

    game_search: GameSearchTool
    price: PriceTool
    hardware: HardwareTool
    review_summary: ReviewSummaryTool
    review_score: ReviewScoreTool
    media: MediaTool | None = None


class UnknownCandidateError(ValueError):
    """LLM이 search_games 결과에 없는 igdb_id를 넘겼다. 경고 없이 LLM에게만 알린다."""


class CandidateStore:
    """요청 하나 동안 후보와 도구 결과를 igdb_id로 모은다. 후보는 검색 순서를 유지한다."""

    def __init__(self, conditions: GameConditions):
        self.conditions = conditions
        self.candidates: dict[int, GameCandidate] = {}
        self.prices: dict[int, PriceResult] = {}
        self.hardware: dict[int, HardwareResult] = {}
        self.reviews: dict[int, ReviewSummary] = {}
        self.media: dict[int, GameMedia] = {}
        self.warnings: list[str] = []

    def warn(self, message: str) -> None:
        """같은 경고를 두 번 남기지 않는다. 안전망이 실패한 도구를 다시 부를 수 있다."""
        if message not in self.warnings:
            self.warnings.append(message)

    def add_candidates(self, games: list[GameCandidate]) -> list[GameCandidate]:
        """처음 보는 후보만 추가하고, 추가된 후보를 돌려준다."""
        added = []
        for game in games:
            if game.igdb_id not in self.candidates:
                self.candidates[game.igdb_id] = game
                added.append(game)
        return added

    def resolve(self, igdb_ids: list[int]) -> list[GameCandidate]:
        """LLM이 넘긴 id를 후보 객체로 되돌린다. 모르는 id가 섞여 있으면 전체를 거부한다."""
        unknown = [igdb_id for igdb_id in unique(igdb_ids) if igdb_id not in self.candidates]
        if unknown:
            raise UnknownCandidateError(
                f"후보 목록에 없는 igdb_id: {unknown}. search_games 결과에 있는 id만 넘기세요."
            )
        return [self.candidates[igdb_id] for igdb_id in unique(igdb_ids)]

    def checked(self, igdb_id: int) -> bool:
        """가격이나 사양을 한 번이라도 조회한 후보인가.

        조회하지 않은 후보는 판단한 적이 없으므로 제외 목록에 넣지 않는다.
        """
        return igdb_id in self.prices or igdb_id in self.hardware

    def evaluate(self, igdb_id: int) -> EvaluatedGame:
        """후보 하나의 판정을 모은다.

        조회하지 않은 항목은 조건이 있으면 unknown, 없으면 skipped다.
        """
        conditions = self.conditions
        price = self.prices.get(igdb_id) or PriceResult(
            igdb_id=igdb_id,
            check=ConditionCheck(
                status="unknown" if conditions.max_price_krw is not None else "skipped",
                reason="가격 확인 불가",
            ),
        )
        hardware = self.hardware.get(igdb_id) or HardwareResult(
            igdb_id=igdb_id,
            check=ConditionCheck(
                status="unknown" if conditions.hardware is not None else "skipped",
                reason="사양 확인 불가",
            ),
        )
        return EvaluatedGame(
            game=self.candidates[igdb_id],
            price=price,
            hardware=hardware,
            review=self.reviews.get(igdb_id),
            media=self.media.get(igdb_id),
        )

    def passes(self, igdb_id: int) -> bool:
        return not self.failing_reasons(igdb_id)

    def failing_reasons(self, igdb_id: int) -> list[str]:
        """추천할 수 없는 이유. 비어 있으면 통과다."""
        evaluated = self.evaluate(igdb_id)
        return [
            f"{label} {STATUS_LABELS[check.status]}({check.reason})"
            for label, check in (
                ("가격", evaluated.price.check),
                ("사양", evaluated.hardware.check),
            )
            if check.status not in PASSING
        ]

    def validate_draft(self, draft: RecommendationDraft) -> list[str]:
        """확정 전 검사. 문제가 없으면 빈 목록, 있으면 LLM에게 돌려줄 문장 목록."""
        problems: list[str] = []
        ids = unique(draft.recommended_igdb_ids)
        if unknown := [igdb_id for igdb_id in ids if igdb_id not in self.candidates]:
            problems.append(f"후보 목록에 없는 igdb_id: {unknown}")
        limit = self.conditions.recommendation_count
        if len(ids) > limit:
            problems.append(f"추천 개수는 {limit}개 이하여야 합니다 (현재 {len(ids)}개)")
        for igdb_id in ids:
            if igdb_id in self.candidates and (reasons := self.failing_reasons(igdb_id)):
                name = self.candidates[igdb_id].name
                problems.append(
                    f"{name}(igdb_id {igdb_id})은 추천할 수 없습니다: {', '.join(reasons)}"
                )
        if not draft.answer.strip():
            problems.append("answer가 비어 있습니다")
        return problems

    def excluded_ids(self, recommended_ids: list[int]) -> list[int]:
        """조회했는데 필수 조건에 걸린 후보.

        조회하지 않은 후보는 판단하지 않았으므로 넣지 않는다.
        """
        recommended = set(recommended_ids)
        return [
            igdb_id
            for igdb_id in self.candidates
            if igdb_id not in recommended and self.checked(igdb_id) and not self.passes(igdb_id)
        ]

    def build_evidence(self, recommended_ids: list[int]) -> RecommendationEvidence:
        """응답 본문. 제외 후보의 review·media는 README 계약대로 항상 null이다."""
        evidence = RecommendationEvidence(conditions=self.conditions, warnings=list(self.warnings))
        evidence.games = [self.evaluate(igdb_id) for igdb_id in recommended_ids]
        for igdb_id in self.excluded_ids(recommended_ids):
            excluded = self.evaluate(igdb_id)
            excluded.review = None
            excluded.media = None
            evidence.excluded_games.append(excluded)
        return evidence


@dataclass
class AgentContext:
    """요청 하나의 컨텍스트. `create_agent(context_schema=AgentContext)`로 각 Tool에 주입된다."""

    conditions: GameConditions
    store: CandidateStore
    tools: ToolSet
    progress: Progress = silent
    stage_timeout_seconds: float = 30
    stages: list[str] = field(default_factory=list)  # run_stage로 실행한 단계 이름 (테스트·진단용)

    @classmethod
    def pending(
        cls, tools: ToolSet, progress: Progress = silent, stage_timeout_seconds: float = 30
    ) -> "AgentContext":
        """질문 분해 전의 컨텍스트.

        그래프 실행 중에는 컨텍스트를 바꿔 끼울 수 없어, 빈 조건으로 만들고 질문 분해 노드가
        `begin()`으로 확정한다.
        """
        conditions = GameConditions()
        return cls(
            conditions=conditions,
            store=CandidateStore(conditions),
            tools=tools,
            progress=progress,
            stage_timeout_seconds=stage_timeout_seconds,
        )

    def begin(self, conditions: GameConditions) -> None:
        """질문 분해 결과로 조건과 후보 저장소를 연다. Tool은 이 뒤에만 실행된다."""
        self.conditions = conditions
        self.store = CandidateStore(conditions)

    async def run_stage(
        self,
        stage: str,
        call: Awaitable[dict],
        *,
        detail: Callable[[dict], str | None] | None = None,
    ) -> str:
        """Tool 본문을 감싼다.

        진행 이벤트를 내고, 시간 제한을 걸고, 실패는 오류 JSON으로 LLM에 돌려준다.

        - 성공: payload를 JSON 문자열로 돌려준다 (LLM 입력).
        - 후보에 없는 id: LLM의 실수이므로 경고 없이 오류 JSON만 돌려준다.
        - 그 외 실패·시간 초과: warnings에 남기고 오류 JSON. 예외를 올리지 않아 에이전트가
          계속 진행한다.
        """
        self.stages.append(stage)
        self.progress(stage, "started", None)
        try:
            payload = await asyncio.wait_for(call, timeout=self.stage_timeout_seconds)
        except UnknownCandidateError as exc:
            self.progress(stage, "failed", None)
            return dumps({"error": str(exc)})
        except Exception as exc:
            logger.warning("Agent tool stage failed: %s (%s)", stage, type(exc).__name__)
            self.store.warn(f"{stage} 호출 실패: 해당 정보를 확인할 수 없습니다.")
            self.progress(stage, "failed", None)
            return dumps({"error": f"{stage} 조회에 실패했습니다. 이 정보 없이 진행하세요."})
        self.progress(stage, "completed", detail(payload) if detail is not None else None)
        return dumps(payload)

    async def optional[T](self, stage: str, call: Awaitable[T]) -> T | None:
        """Tool 밖 후처리(미디어 등)용. 실패하면 경고만 남기고 None을 돌려준다."""
        self.stages.append(stage)
        self.progress(stage, "started", None)
        try:
            result = await asyncio.wait_for(call, timeout=self.stage_timeout_seconds)
        except Exception as exc:
            logger.warning("Agent post stage failed: %s (%s)", stage, type(exc).__name__)
            self.store.warn(f"{stage} 호출 실패: 해당 정보를 확인할 수 없습니다.")
            self.progress(stage, "failed", None)
            return None
        self.progress(stage, "completed", None)
        return result
