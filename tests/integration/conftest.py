"""통합 테스트 전용 조립.

역할별 대역은 각 담당 디렉터리에, 대본 모델은 tests/agent/fakes.py에 둔다.
"""

from types import SimpleNamespace

import pytest

from app.agent.context import ToolSet
from app.agent.runner import AgentRecommender
from app.pipeline.query_processing.conditions import GameConditions
from app.schemas.game import GameCandidate
from app.schemas.hardware import HardwareAssessment, HardwareSpecs
from app.schemas.price import PriceQuote
from app.tools.game_search import GameSearchTool
from app.tools.hardware import HardwareTool
from app.tools.price import PriceTool
from app.tools.review_summary import ReviewSummaryTool
from tests.agent.fakes import checks, draft, reviews, scripted, search
from tests.igdb.fakes import FakeCatalog
from tests.price_hardware.fakes import FakePriceHardware
from tests.query_processing.fakes import FakeQueryParser
from tests.reviews.fakes import FakeReviews


@pytest.fixture(autouse=True)
def no_real_keys(monkeypatch):
    """`steam_reviews.py`의 `load_dotenv()`가 로컬 .env 키를 os.environ에 올린다.

    테스트가 실제 키로 추천기를 조립해 외부 API를 부르지 않도록 여기서 지운다.
    """
    for name in (
        "OPENAI_API_KEY",
        "IGDB_CLIENT_ID",
        "IGDB_CLIENT_SECRET",
        "STEAMGRIDDB_API_KEY",
        "API_KEY",
    ):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def services():
    calls = []
    return SimpleNamespace(
        calls=calls,
        parser=FakeQueryParser(
            GameConditions(
                max_price_krw=100,
                hardware=HardwareSpecs(cpu="test CPU"),
                recommendation_count=1,
            ),
            calls,
        ),
        catalog=FakeCatalog(
            [GameCandidate(igdb_id=i, name=f"Game {i}") for i in (1, 2, 3)], calls
        ),
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
    )


# 에이전트 대본: 검색 → 가격·사양 병렬 → 통과한 3번 리뷰 → 3번 추천
SCRIPT = (search(genres=[]), checks([1, 2, 3]), reviews([3]), draft([3], "테스트 답변"))


@pytest.fixture
def recommender(services):
    tools = ToolSet(
        game_search=GameSearchTool(services.catalog),
        price=PriceTool(services.price_hardware),
        hardware=HardwareTool(services.price_hardware),
        review_summary=ReviewSummaryTool(services.reviews),
    )
    return AgentRecommender(services.parser, tools, scripted(*SCRIPT))
