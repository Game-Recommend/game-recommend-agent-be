"""가격·하드웨어 담당: Steam 스토어 상세 API로 원화 가격과 PC 요구 사양을 조회한다.

게임명이 아니라 GameCandidate.steam_app_id로 조회한다. 가격과 사양이 같은 응답에 오므로
appid당 한 번만 호출하고, 가격·사양 병렬 실행 중 겹치는 요청은 진행 중인 호출을 공유한다.

- 상세: `GET https://store.steampowered.com/api/appdetails?appids=<appid>&cc=kr&l=english`
  - `cc=kr`로 한국 스토어 가격을 받는다. `price_overview.final`은 원화 ×100 단위다
    (2700000 = ₩27,000). 통화가 KRW가 아니면 가격으로 쓰지 않는다.
  - `l=english`는 `pc_requirements` 라벨(OS/Processor/Memory/Graphics)을 고정하기 위해서다.
    `l=korean`이면 라벨이 번역되어 파싱이 흔들린다.
  - `pc_requirements`는 dict(`minimum`/`recommended` HTML) 또는 빈 list다.
  - 한국 미판매·삭제된 앱은 `success: false`가 온다. 이때는 사양도 받을 수 없다.
- 키가 없고 IP당 5분에 약 200회 제한이 있다. 동시 요청 수를 제한한다.

Steam에 있는 게임은 여기서 끝난다. 가격이 없는 경우도 이유를 확인할 수 있다(무료·미출시·구매 불가).
`steam_app_id`가 없는 후보는 routing.py가 cheapshark.py·pcgamingwiki.py 폴백으로 보낸다.
사양 판정 규칙은 hardware_assessor.py에 있어 폴백과 같은 기준을 쓴다.
"""

import asyncio
import html
import logging
import re
import time

import httpx2
from pydantic import BaseModel

from app.clients.hardware_assessor import GameRequirements, assess_requirements
from app.clients.hardware_judge import SpecJudge
from app.schemas.game import GameCandidate
from app.schemas.hardware import HardwareAssessment, HardwareSpecs, RequirementSpec
from app.schemas.price import PriceQuote, PriceUnavailable

logger = logging.getLogger(__name__)

APPDETAILS_URL = "https://store.steampowered.com/api/appdetails"
STORE_PAGE_URL = "https://store.steampowered.com/app/{app_id}"

_TAG_RE = re.compile(r"<[^>]+>")
# 항목 라벨 → 정규 키. Steam은 OS/Processor/Memory/Graphics로 고정되지만
# 개발사 원문을 그대로 실은 출처는 "Operating system", "Graphics card", "CPU"처럼 표기가 갈린다.
_LABEL_ALIASES: dict[str, str] = {
    "os": "OS",
    "operating system": "OS",
    "processor": "Processor",
    "cpu": "Processor",
    "memory": "Memory",
    "ram": "Memory",
    "graphics": "Graphics",
    "graphics card": "Graphics",
    "video card": "Graphics",
    "video": "Graphics",
    "gpu": "Graphics",
}
# 값을 끊는 용도로만 쓰는 라벨. 파싱 결과에는 넣지 않는다.
_OTHER_LABELS = (
    "DirectX",
    "DirectX version",
    "Network",
    "Internet",
    "Storage",
    "Hard Drive",
    "Hard Disk Space",
    "Free Disk Space",
    "Disk Space",
    "Video Memory",
    "VRAM",
    "Sound Card",
    "Sound",
    "Resolution",
    "Additional Notes",
    "Additional",
    "Notes",
    "Other Requirements",
    "Recommended",
    "Minimum",
)
# 긴 라벨을 먼저 시도해 "Graphics card"가 "Graphics"로, "Video Memory"가 "Memory"로 잘리지 않게 한다
_LABEL_ALTERNATION = "|".join(
    re.escape(label)
    for label in sorted((*_LABEL_ALIASES, *_OTHER_LABELS), key=len, reverse=True)
)
_FIELD_RE = re.compile(
    rf"(?<![A-Za-z])(?P<label>{_LABEL_ALTERNATION})\s*\*?\s*:\s*(?P<value>.*?)"
    rf"(?=(?<![A-Za-z])(?:{_LABEL_ALTERNATION})\s*\*?\s*:|$)",
    re.DOTALL | re.IGNORECASE,
)
_RAM_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(GB|MB)", re.IGNORECASE)


class AppDetails(BaseModel):
    """appdetails 응답에서 가격·사양 판정에 필요한 부분만 정규화한 결과."""

    app_id: int
    available: bool  # success:false면 False (한국 미판매·삭제)
    is_free: bool = False
    coming_soon: bool = False
    price_krw: int | None = None
    has_packages: bool = False
    requirements: RequirementSpec | None = None  # 최소 사양
    recommended: RequirementSpec | None = None  # 권장 사양


def parse_requirements(
    requirements_html: str, *, source_url: str | None = None
) -> RequirementSpec | None:
    """`pc_requirements.minimum`/`recommended` HTML을 항목별로 푼다. 항목이 없으면 None."""
    text = _TAG_RE.sub(" ", requirements_html.replace("<br>", "\n").replace("</li>", "\n"))
    text = html.unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"^(?:Minimum|Recommended)\s*:\s*", "", text, flags=re.IGNORECASE)
    fields: dict[str, str] = {}
    for match in _FIELD_RE.finditer(text):
        key = _LABEL_ALIASES.get(match.group("label").lower())
        value = match.group("value").strip().rstrip(",;").strip()  # 한 줄 나열의 구분 쉼표 제거
        if key and value and key not in fields:  # 같은 항목이 두 번 나오면 첫 값을 쓴다
            fields[key] = value
    if not fields:
        return None
    ram_gb = None
    if memory := fields.get("Memory"):
        if ram := _RAM_RE.search(memory):
            amount, unit = float(ram.group(1)), ram.group(2).upper()
            ram_gb = amount if unit == "GB" else amount / 1024
    return RequirementSpec(
        os=fields.get("OS"),
        cpu=fields.get("Processor"),
        gpu=fields.get("Graphics"),
        ram_gb=ram_gb,
        raw_text=text,
        source_url=source_url,
    )


def parse_app_details(app_id: int, payload: dict) -> AppDetails:
    entry = payload.get(str(app_id)) or {}
    if not entry.get("success"):
        return AppDetails(app_id=app_id, available=False)
    data = entry.get("data") or {}
    price_krw = None
    if overview := data.get("price_overview"):
        if overview.get("currency") == "KRW" and isinstance(overview.get("final"), int):
            price_krw = overview["final"] // 100
        else:
            logger.warning(
                "Steam price is not KRW for app %s: %s", app_id, overview.get("currency")
            )
    requirements = recommended = None
    pc_requirements = data.get("pc_requirements")
    if isinstance(pc_requirements, dict):
        source_url = STORE_PAGE_URL.format(app_id=app_id)
        if pc_requirements.get("minimum"):
            requirements = parse_requirements(pc_requirements["minimum"], source_url=source_url)
        if pc_requirements.get("recommended"):
            recommended = parse_requirements(pc_requirements["recommended"], source_url=source_url)
    return AppDetails(
        app_id=app_id,
        available=True,
        is_free=bool(data.get("is_free")),
        coming_soon=bool((data.get("release_date") or {}).get("coming_soon")),
        price_krw=price_krw,
        has_packages=bool(data.get("packages")),
        requirements=requirements,
        recommended=recommended,
    )


class SteamStoreClient:
    """PriceClient와 HardwareClient를 모두 구현한다. 두 도구에 같은 인스턴스를 주입한다."""

    def __init__(
        self,
        http: httpx2.AsyncClient,
        judge: SpecJudge,
        *,
        country_code: str = "kr",
        cache_ttl_seconds: float = 600,
        max_concurrency: int = 4,
    ):
        self.http = http
        self.judge = judge
        self.country_code = country_code
        self.cache_ttl_seconds = cache_ttl_seconds
        self._semaphore = asyncio.Semaphore(max_concurrency)
        self._cache: dict[int, tuple[float, AppDetails]] = {}
        self._inflight: dict[int, asyncio.Future[AppDetails]] = {}

    async def get_app_details(self, app_id: int) -> AppDetails:
        cached = self._cache.get(app_id)
        if cached and time.monotonic() - cached[0] < self.cache_ttl_seconds:
            return cached[1]
        if (inflight := self._inflight.get(app_id)) is not None:
            return await inflight
        future = asyncio.ensure_future(self._fetch(app_id))
        self._inflight[app_id] = future
        try:
            details = await future
        finally:
            self._inflight.pop(app_id, None)
        self._cache[app_id] = (time.monotonic(), details)
        return details

    async def _fetch(self, app_id: int) -> AppDetails:
        async with self._semaphore:
            response = await self.http.get(
                APPDETAILS_URL,
                params={"appids": app_id, "cc": self.country_code, "l": "english"},
            )
        response.raise_for_status()
        return parse_app_details(app_id, response.json())

    async def _details_for(self, games: list[GameCandidate]) -> dict[int, AppDetails]:
        # steam_app_id가 없는 후보는 게임명으로 찾지 않고 조회 불가로 둔다
        targets = [game for game in games if game.steam_app_id is not None]
        details = await asyncio.gather(*(self.get_app_details(g.steam_app_id) for g in targets))
        return {game.igdb_id: detail for game, detail in zip(targets, details, strict=True)}

    async def fetch_prices(self, games: list[GameCandidate]) -> list[PriceQuote | PriceUnavailable]:
        details = await self._details_for(games)
        results: list[PriceQuote | PriceUnavailable] = []
        for game in games:
            detail = details.get(game.igdb_id)
            if detail is None:
                continue
            source_url = STORE_PAGE_URL.format(app_id=detail.app_id)
            if not detail.available:
                results.append(PriceUnavailable(igdb_id=game.igdb_id, reason="한국 스토어 미판매"))
            elif detail.is_free:
                results.append(
                    PriceQuote(igdb_id=game.igdb_id, amount_krw=0, source_url=source_url)
                )
            elif detail.price_krw is not None:
                results.append(
                    PriceQuote(
                        igdb_id=game.igdb_id, amount_krw=detail.price_krw, source_url=source_url
                    )
                )
            elif detail.coming_soon:
                results.append(PriceUnavailable(igdb_id=game.igdb_id, reason="미출시"))
            elif detail.has_packages:
                pass  # 번들로만 팔아 단독 가격이 없다 → unknown
            else:
                results.append(
                    PriceUnavailable(igdb_id=game.igdb_id, reason="현재 Steam에서 구매 불가")
                )
        return results

    async def assess(
        self, games: list[GameCandidate], hardware: HardwareSpecs | None
    ) -> list[HardwareAssessment]:
        details = await self._details_for(games)
        requirements = {
            igdb_id: GameRequirements(minimum=detail.requirements, recommended=detail.recommended)
            for igdb_id, detail in details.items()
        }
        return await assess_requirements(games, hardware, requirements, self.judge)
