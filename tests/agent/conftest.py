"""에이전트 테스트 조립. 역할별 대역은 각 담당 디렉터리의 fakes.py를 그대로 쓴다."""

from types import SimpleNamespace

import pytest

from app.agent.context import AgentContext, CandidateStore, ToolSet
from app.agent.runner import AgentRecommender
from app.pipeline.query_processing.conditions import GameConditions
from app.schemas.game import GameCandidate
from app.schemas.hardware import HardwareAssessment, HardwareSpecs
from app.schemas.price import PriceQuote
from app.tools.game_search import GameSearchTool
from app.tools.hardware import HardwareTool
from app.tools.media import MediaTool
from app.tools.price import PriceTool
from app.tools.review_summary import ReviewSummaryTool
from tests.agent.fakes import scripted
from tests.igdb.fakes import FakeCatalog
from tests.media.fakes import FakeMedia
from tests.price_hardware.fakes import FakePriceHardware
from tests.query_processing.fakes import FakeQueryParser
from tests.reviews.fakes import FakeReviews

# 예산 100원, 사양 조건 있음, 2개 요청. 통과 후보는 3번뿐이다:
# 1번은 예산 초과(unmet), 2번은 사양 확인 불가(unknown), 3번은 둘 다 충족.
CONDITIONS = GameConditions(
    max_price_krw=100,
    hardware=HardwareSpecs(cpu="test CPU"),
    genres=["Adventure"],
    recommendation_count=2,
)
GAMES = [GameCandidate(igdb_id=i, name=f"Game {i}", steam_app_id=i * 10) for i in (1, 2, 3)]


@pytest.fixture
def services():
    calls: list[str] = []
    return SimpleNamespace(
        calls=calls,
        parser=FakeQueryParser(CONDITIONS, calls),
        catalog=FakeCatalog(list(GAMES), calls),
        price_hardware=FakePriceHardware(
            quotes=[
                PriceQuote(igdb_id=3, amount_krw=100),
                PriceQuote(igdb_id=1, amount_krw=150),
                PriceQuote(igdb_id=2, amount_krw=50),
            ],
            assessments=[
                HardwareAssessment(igdb_id=3, status="met", reason="사양 충족"),
                HardwareAssessment(igdb_id=1, status="met", reason="사양 충족"),
                HardwareAssessment(igdb_id=2, status="unknown", reason="비교 근거 없음"),
            ],
            calls=calls,
        ),
        reviews=FakeReviews(calls),
        media=FakeMedia(calls=calls),
    )


@pytest.fixture
def toolset(services) -> ToolSet:
    return ToolSet(
        game_search=GameSearchTool(services.catalog),
        price=PriceTool(services.price_hardware),
        hardware=HardwareTool(services.price_hardware),
        review_summary=ReviewSummaryTool(services.reviews),
        media=MediaTool(services.media),
    )


@pytest.fixture
def store() -> CandidateStore:
    store = CandidateStore(CONDITIONS)
    store.add_candidates(list(GAMES))
    return store


@pytest.fixture
def context(toolset, store) -> AgentContext:
    return AgentContext(conditions=CONDITIONS, store=store, tools=toolset)


@pytest.fixture
def make_recommender(services, toolset):
    """대본(AIMessage 순서)으로 에이전트 추천기를 만든다."""

    def factory(*script, **kwargs) -> AgentRecommender:
        return AgentRecommender(services.parser, toolset, scripted(*script), **kwargs)

    return factory
