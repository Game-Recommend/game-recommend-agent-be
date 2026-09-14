"""가격·하드웨어 담당: Steam에 없는 게임의 PC 요구 사양 폴백. PCGamingWiki를 쓴다.

routing.py가 `steam_app_id`가 없는 후보만 이 클라이언트로 보낸다. 판정 규칙은
hardware_assessor.py를 Steam과 공유하므로 여기서는 요구 사양 조회만 담당한다.

- MediaWiki API, 키 불필요: `GET https://www.pcgamingwiki.com/w/api.php`
  - 페이지 원문: `action=parse&page=<제목>&prop=wikitext&redirects=1&format=json`
    "Alan Wake 2" → "Alan Wake II"처럼 리다이렉트가 잦아 `redirects=1`이 필요하다.
    없는 페이지는 `error.code == "missingtitle"`이다.
  - 제목 검색: `action=opensearch&search=<게임명>&limit=5`. 직접 조회가 실패하면 여기서
    정규화한 제목이 같은 후보를 고른다. 유사 제목으로 임의 연결하지 않는다.
  - 원문의 `{{System requirements ...}}` 템플릿에 항목이 이미 나뉘어 있다
    (`minOS`, `minCPU`, `minCPU2`, `minRAM`, `minGPU`, `minGPU2`, `minGPU3`, `rec*`).
    OS별 템플릿이 여러 개면 `OSfamily = Windows`를 쓴다. Steam 요구 사양도 Windows 기준이다.
  - 커뮤니티 위키라 공식 출처 링크가 `notes`에 붙는 경우가 많다. 페이지 URL을 출처로 남긴다.
- 비영리 위키이므로 동시 요청을 줄이고 User-Agent를 명시한다.
"""

import asyncio
import html
import logging
import re
import time

import httpx2

from app.clients.free_games import normalize_title
from app.clients.hardware_assessor import GameRequirements, assess_requirements
from app.clients.hardware_judge import SpecJudge
from app.schemas.game import GameCandidate
from app.schemas.hardware import HardwareAssessment, HardwareSpecs, RequirementSpec

logger = logging.getLogger(__name__)

API_URL = "https://www.pcgamingwiki.com/w/api.php"
PAGE_URL = "https://www.pcgamingwiki.com/wiki/{title}"
USER_AGENT = "game-recommend-be/0.1 (https://github.com/Game-Recommend/game-recommend-be)"

_TEMPLATE_START = "{{System requirements"
_REF_RE = re.compile(r"<ref[^>]*/>|<ref[^>]*>.*?</ref>", re.DOTALL)
_TAG_RE = re.compile(r"<[^>]+>")
_WIKILINK_RE = re.compile(r"\[\[(?:[^|\]]*\|)?([^\]]*)\]\]")  # [[대상|표시]] → 표시
_EXTLINK_RE = re.compile(r"\[https?://\S+\s+([^\]]*)\]")  # [url 표시] → 표시
_INLINE_TEMPLATE_RE = re.compile(r"\{\{[^{}]*\}\}")  # {{ii}} 같은 아이콘 템플릿
_RAM_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(GB|MB)", re.IGNORECASE)


def _clean(value: str) -> str:
    value = _REF_RE.sub("", value)
    value = _WIKILINK_RE.sub(r"\1", value)
    value = _EXTLINK_RE.sub(r"\1", value)
    value = _INLINE_TEMPLATE_RE.sub("", value)
    value = _TAG_RE.sub(" ", value)
    value = html.unescape(value)
    return re.sub(r"\s+", " ", value).strip()


def extract_templates(wikitext: str) -> list[dict[str, str]]:
    """`{{System requirements ...}}` 템플릿들을 필드 dict로 푼다. 중첩 템플릿의 괄호를 센다."""
    templates = []
    position = 0
    while (start := wikitext.find(_TEMPLATE_START, position)) != -1:
        depth = 0
        end = start
        for index in range(start, len(wikitext) - 1):
            pair = wikitext[index : index + 2]
            if pair == "{{":
                depth += 1
            elif pair == "}}":
                depth -= 1
                if depth == 0:
                    end = index + 2
                    break
        else:
            break
        body = wikitext[start + len(_TEMPLATE_START) : end - 2]
        fields: dict[str, str] = {}
        # 필드는 줄 첫머리의 `|key = value`로 시작한다. 값 안의 `|`(링크 표시 등)는 줄 안에 머문다.
        for line in body.split("\n"):
            if line.lstrip().startswith("|") and "=" in line:
                key, _, value = line.lstrip()[1:].partition("=")
                fields[key.strip()] = value.strip()
        templates.append(fields)
        position = end
    return templates


def _spec(fields: dict[str, str], prefix: str, source_url: str) -> RequirementSpec | None:
    def joined(*keys: str) -> str | None:
        values = [_clean(fields.get(key, "")) for key in keys]
        values = [v for v in values if v]
        return " or ".join(values) if values else None

    os_version = _clean(fields.get(f"{prefix}OS", ""))
    family = _clean(fields.get("OSfamily", "")) or "Windows"
    os_text = f"{family} {os_version}".strip() if os_version else None
    cpu = joined(f"{prefix}CPU", f"{prefix}CPU2", f"{prefix}CPU3")
    gpu = joined(f"{prefix}GPU", f"{prefix}GPU2", f"{prefix}GPU3")
    ram_text = _clean(fields.get(f"{prefix}RAM", ""))
    ram_gb = None
    if ram := _RAM_RE.search(ram_text):
        amount, unit = float(ram.group(1)), ram.group(2).upper()
        ram_gb = amount if unit == "GB" else amount / 1024
    if not any((os_text, cpu, gpu, ram_gb)):
        return None
    parts = [
        f"{label}: {value}"
        for label, value in (
            ("OS", os_text),
            ("Processor", cpu),
            ("Memory", ram_text or None),
            ("Graphics", gpu),
        )
        if value
    ]
    return RequirementSpec(
        os=os_text,
        cpu=cpu,
        gpu=gpu,
        ram_gb=ram_gb,
        raw_text="; ".join(parts),
        source_url=source_url,
    )


def parse_requirements_page(wikitext: str, source_url: str) -> GameRequirements | None:
    """Windows 템플릿(없으면 첫 템플릿)의 최소·권장 사양. 템플릿이 없으면 None."""
    templates = extract_templates(wikitext)
    if not templates:
        return None
    windows = [t for t in templates if _clean(t.get("OSfamily", "")).lower() == "windows"]
    fields = (windows or templates)[0]
    return GameRequirements(
        minimum=_spec(fields, "min", source_url), recommended=_spec(fields, "rec", source_url)
    )


class PcGamingWikiClient:
    """HardwareClient 구현. 게임명 정확 일치(리다이렉트 포함)로만 연결한다."""

    def __init__(
        self,
        http: httpx2.AsyncClient,
        judge: SpecJudge,
        *,
        max_concurrency: int = 2,
        cache_ttl_seconds: float = 3600,
    ):
        self.http = http
        self.judge = judge
        self.cache_ttl_seconds = cache_ttl_seconds
        self._semaphore = asyncio.Semaphore(max_concurrency)
        self._cache: dict[str, tuple[float, GameRequirements | None]] = {}

    async def assess(
        self, games: list[GameCandidate], hardware: HardwareSpecs | None
    ) -> list[HardwareAssessment]:
        requirements = await self.fetch_requirements(games)
        return await assess_requirements(games, hardware, requirements, self.judge)

    async def fetch_requirements(self, games: list[GameCandidate]) -> dict[int, GameRequirements]:
        """igdb_id → 요구 사양. 페이지를 못 찾은 게임은 키 자체를 넣지 않는다."""
        found = await asyncio.gather(*(self._lookup(game.name) for game in games))
        return {
            game.igdb_id: spec
            for game, spec in zip(games, found, strict=True)
            if spec is not None
        }

    async def _lookup(self, name: str) -> GameRequirements | None:
        key = normalize_title(name)
        cached = self._cache.get(key)
        if cached and time.monotonic() - cached[0] < self.cache_ttl_seconds:
            return cached[1]
        page = await self._parse_page(name)
        if page is None:
            # 직접 조회 실패: 검색 결과 중 정규화한 제목이 같은 것만 인정한다
            # ("valorant" → "VALORANT")
            for title in await self._search_titles(name):
                if normalize_title(title) == key:
                    page = await self._parse_page(title)
                    if page is not None:
                        break
        result = None
        if page is not None:
            title, wikitext = page
            url = PAGE_URL.format(title=title.replace(" ", "_"))
            # 페이지는 있지만 사양 템플릿이 없으면 "조회됨, 항목 없음"으로 남긴다
            result = parse_requirements_page(wikitext, url) or GameRequirements()
        self._cache[key] = (time.monotonic(), result)
        return result

    async def _parse_page(self, title: str) -> tuple[str, str] | None:
        payload = await self._get(
            action="parse", page=title, prop="wikitext", redirects=1, format="json"
        )
        if (error := payload.get("error")) is not None:
            if error.get("code") == "missingtitle":
                return None
            raise RuntimeError(f"PCGamingWiki API error: {error.get('code')}")
        parse = payload.get("parse") or {}
        wikitext = (parse.get("wikitext") or {}).get("*", "")
        return parse.get("title") or title, wikitext

    async def _search_titles(self, name: str) -> list[str]:
        payload = await self._get(action="opensearch", search=name, limit=5, format="json")
        return list(payload[1]) if isinstance(payload, list) and len(payload) > 1 else []

    async def _get(self, **params):
        async with self._semaphore:
            response = await self.http.get(
                API_URL, params=params, headers={"User-Agent": USER_AGENT}
            )
        response.raise_for_status()
        return response.json()
