"""가격·하드웨어 담당: Steam에 없는 게임의 PC 요구 사양 폴백. PCGamingWiki를 쓴다.

routing.py가 `steam_app_id`가 없는 후보만 이 클라이언트로 보낸다. 판정 규칙은
hardware_assessor.py를 Steam과 공유하므로 여기서는 요구 사양 조회만 담당한다.

- MediaWiki API, 키 불필요: `GET https://www.pcgamingwiki.com/w/api.php`
  - 원문 묶음 조회: `action=query&prop=revisions&rvprop=content&rvslots=main&redirects=1
    &formatversion=2&titles=<제목들>`. 제목 50개까지 한 요청으로 받는다(일반 사용자 상한).
    게임마다 따로 조회하면 30개에 20초 가까이 걸리지만 묶으면 1초 안팎이다(2026-09-18 실측).
    "Alan Wake 2" → "Alan Wake II"처럼 리다이렉트가 잦아 `redirects=1`이 필요하고, 응답의
    `normalized`(첫 글자 대문자화 등)·`redirects`로 요청한 제목을 최종 제목에 잇는다.
    없는 페이지는 `missing`, 제목으로 쓸 수 없는 문자열은 `invalid`로 표시된다.
    제목 구분자는 U+001F를 써서 이름에 `|`가 있어도 된다. 응답이 커서 잘리면 `continue`가
    오므로 이어서 받는다.
  - 제목 검색: `action=opensearch&search=<게임명>&limit=5`. 묶음 조회에서 못 찾은 게임만 여기서
    정규화한 제목이 같은 후보를 고르고, 그 제목들을 다시 한 번 묶어 조회한다. 유사 제목으로 임의
    연결하지 않는다.
  - 원문의 `{{System requirements ...}}` 템플릿에 항목이 이미 나뉘어 있다
    (`minOS`, `minCPU`, `minCPU2`, `minRAM`, `minGPU`, `minGPU2`, `minGPU3`, `rec*`).
    OS별 템플릿이 여러 개면 `OSfamily = Windows`를 쓴다. Steam 요구 사양도 Windows 기준이다.
  - 커뮤니티 위키라 공식 출처 링크가 `notes`에 붙는 경우가 많다. 페이지 URL을 출처로 남긴다.
- 비영리 위키이므로 동시 요청을 줄이고 User-Agent를 명시한다. 묶음 조회 덕에 요청 수가 게임 수와
  무관해졌고, 게임별로 나가는 요청은 못 찾은 게임의 제목 검색뿐이다.
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
TITLES_PER_QUERY = 50  # MediaWiki 일반 사용자의 `titles` 상한
TITLE_SEPARATOR = "\x1f"  # 값이 U+001F로 시작하면 MediaWiki가 `|` 대신 이를 구분자로 본다
MAX_CONTINUE_ROUNDS = 5  # 잘린 응답을 이어받는 횟수 상한. 50개면 보통 한 번에 온다

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


Page = tuple[str, str]  # (최종 제목, 원문)


class PcGamingWikiClient:
    """HardwareClient 구현. 게임명 정확 일치(리다이렉트 포함)로만 연결한다."""

    def __init__(
        self,
        http: httpx2.AsyncClient,
        judge: SpecJudge,
        *,
        max_concurrency: int = 4,
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
        # 정규화한 제목이 같은 후보는 한 번만 조회한다. 캐시(못 찾은 게임 포함)에 있으면 건너뛴다
        pending: dict[str, str] = {}
        for game in games:
            key = normalize_title(game.name)
            if not self._cached(key):
                pending.setdefault(key, game.name)
        if pending:
            found = await self._lookup_all(pending)
            now = time.monotonic()
            for key, result in found.items():
                self._cache[key] = (now, result)
        results: dict[int, GameRequirements] = {}
        for game in games:
            cached = self._cache.get(normalize_title(game.name))
            if cached is not None and cached[1] is not None:
                results[game.igdb_id] = cached[1]
        return results

    def _cached(self, key: str) -> bool:
        cached = self._cache.get(key)
        return cached is not None and time.monotonic() - cached[0] < self.cache_ttl_seconds

    async def _lookup_all(self, pending: dict[str, str]) -> dict[str, GameRequirements | None]:
        """정규화 제목 → 요구 사양(못 찾으면 None).

        묶음 조회 → 못 찾은 것만 제목 검색 → 검색으로 찾은 제목 묶음 조회 순서다.
        """
        pages = await self._fetch_pages(list(pending.values()))
        results: dict[str, GameRequirements | None] = {}
        misses: dict[str, str] = {}
        for key, name in pending.items():
            if (page := pages.get(name)) is not None:
                results[key] = _requirements(page)
            else:
                misses[key] = name
        if misses:
            # 직접 조회 실패: 검색 결과 중 정규화한 제목이 같은 것만 인정한다
            # ("valorant" → "VALORANT")
            searched = await asyncio.gather(
                *(self._search_titles(name) for name in misses.values())
            )
            candidates = {
                key: [title for title in titles if normalize_title(title) == key]
                for key, titles in zip(misses, searched, strict=True)
            }
            titles = list(dict.fromkeys(title for found in candidates.values() for title in found))
            pages = await self._fetch_pages(titles)
            for key, found in candidates.items():
                page = next((pages[title] for title in found if pages.get(title) is not None), None)
                results[key] = _requirements(page) if page is not None else None
        return results

    async def _fetch_pages(self, titles: list[str]) -> dict[str, Page | None]:
        """요청 제목 → (최종 제목, 원문). 없거나 제목으로 쓸 수 없으면 None.

        50개씩 묶어 조회한다.
        """
        chunks = [titles[i : i + TITLES_PER_QUERY] for i in range(0, len(titles), TITLES_PER_QUERY)]
        pages: dict[str, Page | None] = {}
        for chunk in await asyncio.gather(*(self._query_pages(chunk) for chunk in chunks)):
            pages.update(chunk)
        return pages

    async def _query_pages(self, titles: list[str]) -> dict[str, Page | None]:
        params = {
            "action": "query",
            "prop": "revisions",
            "rvprop": "content",
            "rvslots": "main",
            "titles": TITLE_SEPARATOR + TITLE_SEPARATOR.join(titles),
            "redirects": 1,
            "format": "json",
            "formatversion": 2,
        }
        alias: dict[str, str] = {}  # 요청 제목 → 정규화·리다이렉트된 제목
        pages: dict[str, dict] = {}  # 최종 제목 → 페이지 항목
        continuation: dict = {}
        for _ in range(MAX_CONTINUE_ROUNDS):
            payload = await self._get(**params, **continuation)
            if (error := payload.get("error")) is not None:
                raise RuntimeError(f"PCGamingWiki API error: {error.get('code')}")
            query = payload.get("query") or {}
            for entry in (*query.get("normalized", ()), *query.get("redirects", ())):
                alias[entry["from"]] = entry["to"]
            for page in query.get("pages", ()):
                # 잘린 응답에서 원문 없이 온 항목은 이어받은 응답의 항목으로 바꾼다
                if page.get("revisions") or page.get("title") not in pages:
                    pages[page.get("title")] = page
            if not (continuation := payload.get("continue") or {}):
                break
        else:
            logger.warning(
                "PCGamingWiki query still truncated after %d rounds", MAX_CONTINUE_ROUNDS
            )
        return {requested: _resolve(requested, alias, pages) for requested in titles}

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


def _resolve(requested: str, alias: dict[str, str], pages: dict[str, dict]) -> Page | None:
    """요청 제목을 정규화·리다이렉트 사슬을 따라 최종 페이지에 잇는다. 없으면 None."""
    title = requested
    for _ in range(len(alias)):  # 사슬은 별칭 수보다 길 수 없다(순환 방지)
        if (target := alias.get(title)) is None:
            break
        title = target
    page = pages.get(title)
    if page is None or page.get("missing") or page.get("invalid"):
        return None
    revisions = page.get("revisions") or []
    slots = (revisions[0].get("slots") or {}) if revisions else {}
    content = (slots.get("main") or {}).get("content")
    if content is None:
        return None
    return page.get("title") or title, content


def _requirements(page: Page) -> GameRequirements:
    title, wikitext = page
    url = PAGE_URL.format(title=title.replace(" ", "_"))
    # 페이지는 있지만 사양 템플릿이 없으면 "조회됨, 항목 없음"으로 남긴다
    return parse_requirements_page(wikitext, url) or GameRequirements()
