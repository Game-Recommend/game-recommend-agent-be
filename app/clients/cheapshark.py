"""가격·하드웨어 담당: Steam에 없는 게임의 가격 폴백. 무료 게임 표 → CheapShark 순서로 확인한다.

routing.py가 `steam_app_id`가 없는 후보만 이 클라이언트로 보낸다. Steam에 있는 게임은
steam_store.py가 원화 가격을 직접 받으므로 여기로 오지 않는다.

- 무료 게임 표(free_games.py): 자체 런처 무료 게임은 스토어 API에 가격이 없으므로 먼저 본다.
- CheapShark(키 불필요): `GET https://www.cheapshark.com/api/1.0/games?title=<게임명>&exact=1`
  - 응답 항목: `gameID`, `steamAppID`, `cheapest`(USD 문자열), `cheapestDealID`,
    `external`(스토어 표기명)
  - `exact=1`을 줘도 대소문자·기호 차이는 허용되므로 정규화한 제목이 같은 항목만 인정한다.
    이름이 다른 항목(후속작·DLC·번들)을 같은 게임으로 연결하지 않는다.
  - `cheapest`는 USD다. exchange_rate.py로 원화 정수로 바꾼 값만 PriceQuote에 넣는다.
    환율 조회에 실패하면 가격을 내지 않는다(→ unknown).
  - 설명적인 User-Agent 헤더가 없으면 요청을 거부한다.
  - 결과가 없는 게임은 이유를 모르므로 생략한다(→ unknown). 미판매라고 단정하지 않는다.
"""

import asyncio
import logging

import httpx2

from app.clients.exchange_rate import ExchangeRateClient
from app.clients.free_games import FREE_GAMES, normalize_title
from app.schemas.game import GameCandidate
from app.schemas.price import PriceQuote, PriceUnavailable

logger = logging.getLogger(__name__)

GAMES_URL = "https://www.cheapshark.com/api/1.0/games"
DEAL_URL = "https://www.cheapshark.com/redirect?dealID={deal_id}"
USER_AGENT = "game-recommend-be/0.1"


class CheapSharkClient:
    """PriceClient 구현. 게임명 정확 일치로만 연결한다."""

    def __init__(
        self,
        http: httpx2.AsyncClient,
        exchange_rate: ExchangeRateClient,
        *,
        free_games: dict[str, str] | None = None,
        max_concurrency: int = 4,
    ):
        self.http = http
        self.exchange_rate = exchange_rate
        self.free_games = FREE_GAMES if free_games is None else free_games
        self._semaphore = asyncio.Semaphore(max_concurrency)

    async def fetch_prices(self, games: list[GameCandidate]) -> list[PriceQuote | PriceUnavailable]:
        results: list[PriceQuote | PriceUnavailable] = []
        to_lookup: list[GameCandidate] = []
        for game in games:
            if (url := self.free_games.get(normalize_title(game.name))) is not None:
                results.append(PriceQuote(igdb_id=game.igdb_id, amount_krw=0, source_url=url))
            else:
                to_lookup.append(game)
        if not to_lookup:
            return results
        found = await asyncio.gather(*(self._lookup_usd(game) for game in to_lookup))
        priced = [(game, usd, deal) for game, (usd, deal) in zip(to_lookup, found, strict=True)]
        priced = [item for item in priced if item[1] is not None]
        if not priced:
            return results
        try:
            rate = await self.exchange_rate.usd_to_krw()
        except Exception as exc:
            # 환율 없이는 원화 가격을 만들 수 없다. 가격을 생략해 unknown으로 남긴다.
            logger.warning("USD→KRW exchange rate unavailable (%s)", type(exc).__name__)
            return results
        for game, usd, deal_id in priced:
            results.append(
                PriceQuote(
                    igdb_id=game.igdb_id,
                    amount_krw=round(usd * rate),
                    source_url=DEAL_URL.format(deal_id=deal_id) if deal_id else None,
                )
            )
        return results

    async def _lookup_usd(self, game: GameCandidate) -> tuple[float | None, str | None]:
        """정규화한 제목이 같은 항목의 (USD 최저가, 딜 ID). 없으면 (None, None)."""
        async with self._semaphore:
            response = await self.http.get(
                GAMES_URL,
                params={"title": game.name, "exact": 1},
                headers={"User-Agent": USER_AGENT},
            )
        response.raise_for_status()
        wanted = normalize_title(game.name)
        for entry in response.json() or []:
            if normalize_title(str(entry.get("external", ""))) != wanted:
                continue
            try:
                usd = float(entry["cheapest"])
            except (KeyError, TypeError, ValueError):
                continue
            if usd < 0:
                continue
            return usd, entry.get("cheapestDealID") or None
        return None, None
