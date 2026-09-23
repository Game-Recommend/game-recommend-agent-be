"""가격·하드웨어 담당: `steam_app_id` 유무로 Steam 클라이언트와 폴백 클라이언트를 나눠 부른다.

- `steam_app_id`가 있는 후보 → Steam(steam_store.py). 원화 가격과 사양을 직접 받는다.
- 없는 후보 → 가격은 cheapshark.py(무료 게임 표 → CheapShark + 환율),
  사양은 pcgamingwiki.py. 둘 다 게임명 정확 일치로만 연결하고, 못 찾으면 unknown이다.
- Steam 조회 실패는 기존처럼 예외로 올린다(도구 전체가 unknown). 폴백 실패는 경고만 남기고
  Steam 결과를 보존한다. 폴백 대상 게임만 unknown이 된다.

두 클라이언트는 각각 PriceClient·HardwareClient 계약을 그대로 만족하므로 도구 쪽 변경이 없다.
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable

from app.clients.contracts.hardware import HardwareClient
from app.clients.contracts.price import PriceClient
from app.schemas.common import Language
from app.schemas.game import GameCandidate
from app.schemas.hardware import HardwareAssessment, HardwareSpecs
from app.schemas.price import PriceQuote, PriceUnavailable

logger = logging.getLogger(__name__)


def split_by_steam(games: list[GameCandidate]) -> tuple[list[GameCandidate], list[GameCandidate]]:
    steam = [game for game in games if game.steam_app_id is not None]
    other = [game for game in games if game.steam_app_id is None]
    return steam, other


async def _merged[T](
    games: list[GameCandidate],
    name: str,
    primary: Callable[[list[GameCandidate]], Awaitable[list[T]]],
    fallback: Callable[[list[GameCandidate]], Awaitable[list[T]]],
) -> list[T]:
    steam, other = split_by_steam(games)
    primary_task = primary(steam) if steam else _empty()
    fallback_task = _guarded(name, fallback(other)) if other else _empty()
    primary_results, fallback_results = await asyncio.gather(primary_task, fallback_task)
    return [*primary_results, *fallback_results]


async def _empty() -> list:
    return []


async def _guarded[T](name: str, call: Awaitable[list[T]]) -> list[T]:
    try:
        return await call
    except Exception as exc:
        logger.warning("Fallback %s lookup failed (%s)", name, type(exc).__name__)
        return []


class RoutedPriceClient:
    def __init__(self, steam: PriceClient, fallback: PriceClient):
        self.steam = steam
        self.fallback = fallback

    async def fetch_prices(
        self, games: list[GameCandidate], *, language: Language = "ko"
    ) -> list[PriceQuote | PriceUnavailable]:
        return await _merged(
            games,
            "price",
            lambda subset: self.steam.fetch_prices(subset, language=language),
            lambda subset: self.fallback.fetch_prices(subset, language=language),
        )


class RoutedHardwareClient:
    def __init__(self, steam: HardwareClient, fallback: HardwareClient):
        self.steam = steam
        self.fallback = fallback

    async def assess(
        self,
        games: list[GameCandidate],
        hardware: HardwareSpecs | None,
        *,
        language: Language = "ko",
    ) -> list[HardwareAssessment]:
        return await _merged(
            games,
            "hardware",
            lambda subset: self.steam.assess(subset, hardware, language=language),
            lambda subset: self.fallback.assess(subset, hardware, language=language),
        )
