"""통합 테스트 전용 조립. 역할별 대역의 구현은 각 담당 디렉터리에 둔다."""

from types import SimpleNamespace

import pytest

from app.pipeline.orchestrator import RecommendationOrchestrator
from app.pipeline.query_processing.conditions import GameConditions
from app.schemas.game import GameCandidate
from app.schemas.hardware import HardwareAssessment, HardwareSpecs
from app.schemas.price import PriceQuote
from app.tools.game_search import GameSearchTool
from app.tools.hardware import HardwareTool
from app.tools.price import PriceTool
from app.tools.review_summary import ReviewSummaryTool
from tests.igdb.fakes import FakeCatalog
from tests.price_hardware.fakes import FakePriceHardware
from tests.price_hardware.final_answer.fakes import FakeAnswerer
from tests.query_processing.fakes import FakeQueryParser
from tests.reviews.fakes import FakeReviews


@pytest.fixture(autouse=True)
def no_real_keys(monkeypatch):
    """`steam_reviews.py`의 `load_dotenv()`가 로컬 .env 키를 os.environ에 올린다.

    테스트가 실제 키로 파이프라인을 조립해 외부 API를 부르지 않도록 여기서 지운다.
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
        answerer=FakeAnswerer(calls),
    )


@pytest.fixture
def recommender(services):
    return RecommendationOrchestrator(
        parser=services.parser,
        game_search=GameSearchTool(services.catalog),
        price=PriceTool(services.price_hardware),
        hardware=HardwareTool(services.price_hardware),
        review_summary=ReviewSummaryTool(services.reviews),
        answerer=services.answerer,
    )
