"""서버 시작 시 `.env` 설정으로 실제 연동 어댑터를 조립해 추천 파이프라인을 만든다.

역할별 구현체를 여기서 한 번만 잇는다. 로직은 각 담당 모듈에 있고, 이 파일은 생성자 인자만 맞춘다.

| 단계 | 구현체 |
| --- | --- |
| 질문 분해 | `LLMQueryParser` (질문 가공 담당) |
| 게임 검색 | `IgdbCatalogClient` → `igdb.search()` (IGDB 담당) |
| 가격·사양 | `SteamStoreClient`; Steam에 없으면 `CheapSharkClient`·`PcGamingWikiClient` |
| GPU·CPU 판정 | `OpenAISpecJudge` (`routing.py`가 Steam 유무로 분기) |
| 리뷰 요약 | `SteamReviewSummaryClient` (리뷰 담당, `steam_reviews.py`) |
| 미디어 | `MediaResolver` (SteamGridDB → Steam CDN → IGDB) |
| 최종 답변 | `OpenAIAnswerer` |

OPENAI_API_KEY와 IGDB 키가 없으면 조립하지 않는다(`/recommend`는 503). STEAMGRIDDB_API_KEY가 없으면
로고·배너는 Steam CDN·IGDB만 쓴다.
리뷰 클라이언트는 생성자에서 환경 변수 OPENAI_API_KEY를 직접 읽는다.

동작 확인: `python -m app.assembly "3만 원 이하 협동 게임 3개 추천해줘"`
"""

import asyncio
import json
import logging
import sys
from dataclasses import dataclass

import httpx2
from openai import AsyncOpenAI

from app.clients.cheapshark import CheapSharkClient
from app.clients.exchange_rate import ExchangeRateClient
from app.clients.hardware_judge import OpenAISpecJudge
from app.clients.igdb import IgdbCatalogClient
from app.clients.igdb_media import IgdbMediaClient
from app.clients.media import MediaResolver
from app.clients.pcgamingwiki import PcGamingWikiClient
from app.clients.routing import RoutedHardwareClient, RoutedPriceClient
from app.clients.steam_reviews import SteamReviewSummaryClient
from app.clients.steam_store import SteamStoreClient
from app.clients.steamgriddb import SteamGridDBClient
from app.config import Settings, get_settings
from app.pipeline.final_answer.llm_answerer import OpenAIAnswerer
from app.pipeline.orchestrator import RecommendationOrchestrator
from app.pipeline.query_processing.llm_parser import LLMQueryParser
from app.tools.game_search import GameSearchTool
from app.tools.hardware import HardwareTool
from app.tools.media import MediaTool
from app.tools.price import PriceTool
from app.tools.review_summary import ReviewSummaryTool

logger = logging.getLogger(__name__)

REQUIRED_SETTINGS = ("openai_api_key", "igdb_client_id", "igdb_client_secret")


def missing_settings(settings: Settings) -> list[str]:
    """비어 있는 필수 설정의 환경 변수 이름."""
    return [name.upper() for name in REQUIRED_SETTINGS if not getattr(settings, name)]


@dataclass
class AssembledRecommender:
    """조립한 파이프라인과, 종료 시 닫아야 하는 공유 클라이언트."""

    recommender: RecommendationOrchestrator
    http: httpx2.AsyncClient
    openai: AsyncOpenAI

    async def aclose(self) -> None:
        await self.http.aclose()
        await self.openai.close()


def assemble(settings: Settings | None = None) -> AssembledRecommender | None:
    """필수 키가 있으면 실제 어댑터로 오케스트레이터를 만들고, 없으면 None."""
    if settings is None:
        settings = get_settings()
    if missing := missing_settings(settings):
        logger.warning("Recommender not assembled; missing settings: %s", ", ".join(missing))
        return None

    # Steam·CheapShark·PCGamingWiki·환율은 키가 없어 HTTP 클라이언트 하나를 공유한다.
    http = httpx2.AsyncClient(timeout=20)
    openai = AsyncOpenAI(api_key=settings.openai_api_key, timeout=25, max_retries=1)
    judge = OpenAISpecJudge(openai, settings.openai_model)
    # 가격·사양 도구가 같은 인스턴스를 받아 appdetails를 한 번만 조회한다
    steam = SteamStoreClient(http, judge)
    prices = RoutedPriceClient(steam, CheapSharkClient(http, ExchangeRateClient(http)))
    hardware = RoutedHardwareClient(steam, PcGamingWikiClient(http, judge))

    steamgriddb = None
    if settings.steamgriddb_api_key:
        steamgriddb = SteamGridDBClient(settings.steamgriddb_api_key)
    else:
        logger.warning(
            "STEAMGRIDDB_API_KEY is empty; logos and banners use Steam CDN and IGDB only"
        )
    media = MediaResolver(
        steamgriddb, IgdbMediaClient(settings.igdb_client_id, settings.igdb_client_secret)
    )

    recommender = RecommendationOrchestrator(
        parser=LLMQueryParser(),
        game_search=GameSearchTool(IgdbCatalogClient()),
        price=PriceTool(prices),
        hardware=HardwareTool(hardware),
        review_summary=ReviewSummaryTool(SteamReviewSummaryClient()),
        answerer=OpenAIAnswerer(openai, settings.openai_model),
        media=MediaTool(media),
    )
    return AssembledRecommender(recommender, http, openai)


async def _main(question: str) -> None:
    assembled = assemble()
    if assembled is None:
        missing = ", ".join(missing_settings(get_settings()))
        raise SystemExit(f"필수 설정이 비어 있습니다: {missing}")
    try:
        response = await assembled.recommender.run(question)
    finally:
        await assembled.aclose()
    print(json.dumps(response.model_dump(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING)
    asyncio.run(_main(" ".join(sys.argv[1:]).strip() or "3만 원 이하 협동 게임 3개 추천해줘"))
