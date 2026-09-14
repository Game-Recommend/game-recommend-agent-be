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

CheapShark·RAWG 폴백은 1차 범위에서 제외했다. Steam에 가격이 없는 경우는 모두 이유를
확인할 수 있고(무료·미출시·구매 불가), 사양이 없는 게임은 RAWG에도 대개 없기 때문이다.
"""

import asyncio
import html
import logging
import re
import time

import httpx2
from pydantic import BaseModel

from app.clients.hardware_judge import JudgeRequest, SpecJudge
from app.schemas.game import GameCandidate
from app.schemas.hardware import HardwareAssessment, HardwareSpecs, RequirementSpec
from app.schemas.price import PriceQuote, PriceUnavailable

logger = logging.getLogger(__name__)

APPDETAILS_URL = "https://store.steampowered.com/api/appdetails"
STORE_PAGE_URL = "https://store.steampowered.com/app/{app_id}"

_TAG_RE = re.compile(r"<[^>]+>")
_LABELS = ("OS", "Processor", "Memory", "Graphics")
_OTHER_LABELS = ("DirectX", "Network", "Storage", "Sound Card", "Additional Notes", "Recommended")
_LABEL_ALTERNATION = "|".join(re.escape(label) for label in (*_LABELS, *_OTHER_LABELS))
_FIELD_RE = re.compile(
    rf"(?P<label>{_LABEL_ALTERNATION})\s*\*?\s*:\s*(?P<value>.*?)"
    rf"(?=(?:{_LABEL_ALTERNATION})\s*\*?\s*:|$)",
    re.DOTALL,
)
_RAM_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(GB|MB)", re.IGNORECASE)


# 모델명으로 인정하는 조건: 세 자리 이상 숫자가 있거나(RTX 3060, i5-12400, 780M)
# 알려진 내장 그래픽 계열명이 있다. "i5", "Ryzen 5"의 한 자리 숫자는 세대를 말해 주지 않는다.
# "내장그래픽", "GeForce", "i5"처럼 등급을 알 수 없는 값은 비교하지 않는다.
_KNOWN_IGPU_RE = re.compile(r"iris|uhd|arc|vega|radeon graphics", re.IGNORECASE)
# LLM은 처음 보는 이름("ZetaPixel Q999")도 성능이 낮다고 추측해 unmet을 주므로,
# 알려진 제품 계열이 아니면 판정을 보류한다. 계열이 빠져 있으면 여기에 추가한다.
_KNOWN_FAMILY_RE = re.compile(
    r"geforce|gtx|rtx|titan|quadro|radeon|\brx\b|\bhd\b|vega|arc|iris|uhd"
    r"|\bcore\b|\bi[3579]\b|i[3579]-|ryzen|athlon|threadripper|xeon|pentium|celeron|\bfx\b"
    r"|지포스|라데온|라이젠|코어|인텔|엔비디아",  # 한글 별칭
    re.IGNORECASE,
)
_APPLE_SILICON_RE = re.compile(r"\bapple\b|\bm[1-4]\b", re.IGNORECASE)
_MODEL_EXAMPLES = {"gpu": "Iris Xe, Radeon 780M", "cpu": "i5-12400"}


def user_spec_issue(hardware: HardwareSpecs) -> str | None:
    """사용자 GPU·CPU 값이 비교 가능한 모델명이 아니면 그 이유. 문제가 없으면 None."""
    for component in ("gpu", "cpu"):
        value = getattr(hardware, component)
        if not value:
            continue
        if _APPLE_SILICON_RE.search(value):
            # Steam pc_requirements는 Windows 기준이라 Apple Silicon과 비교할 수 없다
            return "Mac 사양 판정 미지원"
        has_model = re.search(r"\d{3,}", value) or _KNOWN_IGPU_RE.search(value)
        if not (has_model and _KNOWN_FAMILY_RE.search(value)):
            label = component.upper()
            return f"{label} 모델 확인 필요 (예: {_MODEL_EXAMPLES[component]})"
    return None


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


def parse_requirements(requirements_html: str) -> RequirementSpec | None:
    """`pc_requirements.minimum`/`recommended` HTML을 항목별로 푼다. 항목이 없으면 None."""
    text = _TAG_RE.sub(" ", requirements_html.replace("<br>", "\n").replace("</li>", "\n"))
    text = html.unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"^(?:Minimum|Recommended)\s*:\s*", "", text, flags=re.IGNORECASE)
    fields = {m.group("label"): m.group("value").strip() for m in _FIELD_RE.finditer(text)}
    fields = {label: value for label, value in fields.items() if label in _LABELS and value}
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
        if pc_requirements.get("minimum"):
            requirements = parse_requirements(pc_requirements["minimum"])
        if pc_requirements.get("recommended"):
            recommended = parse_requirements(pc_requirements["recommended"])
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
        # 사용자 쪽 정보 부족(모델 없는 내장그래픽, Mac)은 게임과 무관하게 한 번만 판단한다.
        # 이 경우 제외하지 않고 skipped로 통과시켜 답변에서 요구 사양을 보여주고 되묻는다.
        issue = user_spec_issue(hardware) if hardware else None
        results: list[HardwareAssessment] = []
        to_judge: list[JudgeRequest] = []
        for game in games:
            detail = details.get(game.igdb_id)
            requirement = detail.requirements if detail else None
            if hardware is None:
                # 비교할 조건이 없어도 답변에 보여줄 요구 사양은 싣는다
                results.append(_assessment(game, "skipped", "사용자 사양 조건 없음", detail))
                continue
            if requirement is None:
                results.append(_assessment(game, "unknown", "요구 사양 정보 없음", detail))
                continue
            if hardware.ram_gb and requirement.ram_gb and hardware.ram_gb < requirement.ram_gb:
                reason = f"메모리 부족: 최소 {_gb(requirement.ram_gb)}, 보유 {_gb(hardware.ram_gb)}"
                results.append(_assessment(game, "unmet", reason, detail))
                continue
            if issue:
                results.append(_assessment(game, "skipped", issue, detail))
                continue
            components = [
                c for c in ("gpu", "cpu") if getattr(hardware, c) and getattr(requirement, c)
            ]
            if components:
                to_judge.append(
                    JudgeRequest(
                        igdb_id=game.igdb_id,
                        name=game.name,
                        requirement=requirement,
                        components=components,
                    )
                )
            elif hardware.gpu or hardware.cpu:
                results.append(
                    _assessment(game, "unknown", "비교할 공통 GPU·CPU 항목 없음", detail)
                )
            elif hardware.ram_gb and requirement.ram_gb:
                results.append(
                    _assessment(game, "met", f"메모리 충족: 최소 {_gb(requirement.ram_gb)}", detail)
                )
            else:
                results.append(_assessment(game, "unknown", "비교할 사양 항목 없음", detail))
        if to_judge:
            results.extend(await self._judge(hardware, to_judge, details))
        return results

    async def _judge(
        self,
        hardware: HardwareSpecs,
        requests: list[JudgeRequest],
        details: dict[int, AppDetails],
    ) -> list[HardwareAssessment]:
        # 판정기 실패가 메모리 규칙으로 이미 확정한 결과까지 지우지 않도록 여기서 막는다
        try:
            verdicts = {v.igdb_id: v for v in await self.judge.judge(hardware, requests)}
        except Exception as exc:
            logger.warning("Spec judge failed (%s)", type(exc).__name__)
            verdicts = {}
        results = []
        for request in requests:
            verdict = verdicts.get(request.igdb_id)
            status, reason = (
                (verdict.status, verdict.reason) if verdict else ("unknown", "GPU·CPU 판정 실패")
            )
            results.append(
                HardwareAssessment(
                    igdb_id=request.igdb_id,
                    status=status,
                    reason=reason,
                    requirement=request.requirement,
                    recommended=details[request.igdb_id].recommended,
                )
            )
        return results


def _assessment(
    game: GameCandidate, status: str, reason: str, detail: AppDetails | None
) -> HardwareAssessment:
    return HardwareAssessment(
        igdb_id=game.igdb_id,
        status=status,
        reason=reason,
        requirement=detail.requirements if detail else None,
        recommended=detail.recommended if detail else None,
    )


def _gb(value: float) -> str:
    return f"{value:g} GB"
