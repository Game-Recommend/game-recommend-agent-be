"""Steam에 없는 후보의 폴백: 환율, CheapShark 가격, PCGamingWiki 사양, steam_app_id 기준 라우팅."""

import asyncio
import json

import httpx2
import pytest

from app.clients.cheapshark import CheapSharkClient
from app.clients.exchange_rate import ExchangeRateClient
from app.clients.free_games import FREE_GAMES, normalize_title
from app.clients.pcgamingwiki import PcGamingWikiClient
from app.clients.routing import RoutedHardwareClient, RoutedPriceClient
from app.schemas.game import GameCandidate
from app.schemas.hardware import HardwareAssessment, HardwareSpecs
from app.schemas.price import PriceQuote, PriceUnavailable
from tests.price_hardware.fakes import FakePriceHardware, FakeSpecJudge

RATE_PAYLOAD = {"amount": 1.0, "base": "USD", "date": "2026-09-11", "rates": {"KRW": 1342.79}}


def game(igdb_id: int, name: str, app_id: int | None = None) -> GameCandidate:
    return GameCandidate(igdb_id=igdb_id, name=name, steam_app_id=app_id)


def http_with(routes: dict[str, object], calls: list[httpx2.Request] | None = None):
    """URL 경로 접두어 → 응답 본문(dict/list) 또는 상태 코드."""
    calls = calls if calls is not None else []

    def handler(request: httpx2.Request) -> httpx2.Response:
        calls.append(request)
        for prefix, body in routes.items():
            if str(request.url).startswith(prefix):
                if isinstance(body, int):
                    return httpx2.Response(body)
                return httpx2.Response(200, content=json.dumps(body))
        return httpx2.Response(404)

    return httpx2.AsyncClient(transport=httpx2.MockTransport(handler)), calls




class FailingRate:
    async def usd_to_krw(self) -> float:
        raise RuntimeError("down")


# ---------- 환율 ----------


def test_exchange_rate_converts_and_caches():
    http, calls = http_with({"https://api.frankfurter.dev/v1/latest": RATE_PAYLOAD})
    client = ExchangeRateClient(http)

    async def scenario():
        first = await client.usd_to_krw()
        second = await client.convert_usd(49.99)
        return first, second

    rate, krw = asyncio.run(scenario())
    assert rate == 1342.79
    assert krw == round(49.99 * 1342.79)
    assert len(calls) == 1  # 두 번째 호출은 캐시
    assert calls[0].url.params["from"] == "USD" and calls[0].url.params["to"] == "KRW"


def test_exchange_rate_rejects_missing_or_invalid_rate():
    for payload in ({"rates": {}}, {"rates": {"KRW": 0}}):
        http, _ = http_with({"https://api.frankfurter.dev/v1/latest": payload})
        with pytest.raises(ValueError):
            asyncio.run(ExchangeRateClient(http).usd_to_krw())


# ---------- 무료 게임 표 ----------


def test_normalize_title_ignores_case_space_and_symbols():
    assert normalize_title("Honkai: Star Rail") == normalize_title("honkai star rail")
    assert normalize_title("League of Legends") in FREE_GAMES
    assert normalize_title("League of Legends 2") not in FREE_GAMES


# ---------- CheapShark ----------


def test_cheapshark_converts_exact_match_to_krw_and_uses_free_table():
    http, calls = http_with(
        {
            "https://www.cheapshark.com/api/1.0/games": [
                {"external": "Alan Wake 2: Deluxe", "cheapest": "69.99", "cheapestDealID": "x"},
                {"external": "ALAN WAKE 2", "cheapest": "49.99", "cheapestDealID": "deal%3D1"},
            ],
            "https://api.frankfurter.dev/v1/latest": RATE_PAYLOAD,
        }
    )
    client = CheapSharkClient(http, ExchangeRateClient(http))
    results = asyncio.run(
        client.fetch_prices([game(1, "Alan Wake 2"), game(2, "League of Legends")])
    )

    by_id = {r.igdb_id: r for r in results}
    assert isinstance(by_id[1], PriceQuote)
    assert by_id[1].amount_krw == round(49.99 * 1342.79)
    assert by_id[1].source_url == "https://www.cheapshark.com/redirect?dealID=deal%3D1"
    assert isinstance(by_id[2], PriceQuote) and by_id[2].amount_krw == 0
    assert by_id[2].source_url == "https://www.leagueoflegends.com/"
    cheapshark_calls = [c for c in calls if "cheapshark" in str(c.url)]
    assert len(cheapshark_calls) == 1  # 무료 표에 있는 게임은 조회하지 않는다
    assert cheapshark_calls[0].url.params["exact"] == "1"
    assert cheapshark_calls[0].headers["User-Agent"].startswith("game-recommend-be")


def test_cheapshark_omits_games_without_exact_title_match():
    http, _ = http_with(
        {
            "https://www.cheapshark.com/api/1.0/games": [
                {"external": "Alan Wake", "cheapest": "9.99", "cheapestDealID": "x"}
            ],
            "https://api.frankfurter.dev/v1/latest": RATE_PAYLOAD,
        }
    )
    client = CheapSharkClient(http, ExchangeRateClient(http))
    results = asyncio.run(client.fetch_prices([game(1, "Alan Wake 2")]))
    assert results == []  # 이유를 모르면 PriceUnavailable이 아니라 생략(unknown)


def test_cheapshark_omits_usd_prices_when_exchange_rate_fails():
    http, _ = http_with(
        {
            "https://www.cheapshark.com/api/1.0/games": [
                {"external": "Alan Wake 2", "cheapest": "49.99", "cheapestDealID": "x"}
            ]
        }
    )
    client = CheapSharkClient(http, FailingRate())
    results = asyncio.run(
        client.fetch_prices([game(1, "Alan Wake 2"), game(2, "League of Legends")])
    )
    assert [r.igdb_id for r in results] == [2]  # 무료 표 결과는 환율과 무관하게 남는다
    assert not any(isinstance(r, PriceUnavailable) for r in results)


def test_cheapshark_raises_on_http_error():
    http, _ = http_with({"https://www.cheapshark.com/api/1.0/games": 500})
    client = CheapSharkClient(http, FailingRate())
    with pytest.raises(httpx2.HTTPStatusError):
        asyncio.run(client.fetch_prices([game(1, "Alan Wake 2")]))


# ---------- PCGamingWiki ----------

WIKITEXT = """{{Infobox game|title=Alan Wake II}}
==System requirements==
{{System requirements
|OSfamily = Windows
|ref=<ref name="SysReqs"/>

|minOS    = 10
|minCPU   = Intel Core i5-4460
|minCPU2  = AMD FX-6300
|minRAM   = 8 GB
|minHD    = 20 GB
|minGPU   = [[Nvidia GeForce GTX 960]]
|minGPU2  = AMD Radeon R7 370
|minDX    = 11

|recOS    = 11
|recRAM   = 16 GB
|recGPU   = Nvidia GeForce RTX 2060
|notes    = {{ii}} [https://example.com/official Official system requirements] <br>
{{ii}} Second note
}}
{{System requirements
|OSfamily = OS X
|minOS    = 10.14
|minRAM   = 4 GB
}}
"""

NO_TEMPLATE = "{{Infobox game|title=Roblox}}"


def wiki_http(
    pages: dict[str, str],
    *,
    redirects: dict[str, str] | None = None,
    search: list[str] = (),
    error: dict | None = None,
    split_after: int | None = None,
    calls=None,
):
    """최종 제목 → 원문. MediaWiki 묶음 조회(action=query)를 흉내 낸다.

    요청 제목은 MediaWiki처럼 첫 글자를 대문자로 정규화(`normalized`)하고 `redirects`(요청 제목 →
    최종 제목)를 거쳐 pages에서 찾는다. 없으면 missing, `|`가 든 제목은 invalid다. opensearch는
    search 목록을 돌려준다. split_after가 있으면 첫 응답은 그 수까지만 원문을 싣고 continue를 붙인다
    (잘린 응답). error가 있으면 그 오류를 돌려준다.
    """
    calls = calls if calls is not None else []
    redirects = redirects or {}

    def handler(request: httpx2.Request) -> httpx2.Response:
        calls.append(request)
        params = request.url.params
        if params.get("action") == "opensearch":
            body = [params["search"], list(search), [""] * len(search), []]
            return httpx2.Response(200, content=json.dumps(body))
        if error is not None:
            return httpx2.Response(200, content=json.dumps({"error": error}))
        normalized, redirected, entries = [], [], []
        for title in queried_titles(request):
            if "|" in title:
                entries.append({"title": title, "invalid": True})
                continue
            canonical = title[:1].upper() + title[1:]
            if canonical != title:
                normalized.append({"from": title, "to": canonical})
            final = redirects.get(canonical, canonical)
            if final != canonical:
                redirected.append({"from": canonical, "to": final})
            if final in pages:
                revisions = [{"slots": {"main": {"content": pages[final]}}}]
                entries.append({"pageid": 1, "title": final, "revisions": revisions})
            else:
                entries.append({"title": final, "missing": True})
        query = {"pages": entries}
        if normalized:
            query["normalized"] = normalized
        if redirected:
            query["redirects"] = redirected
        body = {"query": query}
        if split_after is not None and "rvcontinue" not in params:
            for entry in entries[split_after:]:
                entry.pop("revisions", None)
            body["continue"] = {"rvcontinue": "next", "continue": "||"}
        return httpx2.Response(200, content=json.dumps(body))

    return httpx2.AsyncClient(transport=httpx2.MockTransport(handler)), calls


def wiki_actions(calls: list[httpx2.Request]) -> list[str]:
    return [call.url.params["action"] for call in calls]


def queried_titles(call: httpx2.Request) -> list[str]:
    """묶음 조회 요청의 제목들. 값이 U+001F로 시작하면 그것이 구분자다."""
    return call.url.params["titles"].lstrip("\x1f").split("\x1f")


def test_pcgamingwiki_parses_windows_template_and_joins_alternatives():
    http, calls = wiki_http({"Alan Wake II": WIKITEXT}, redirects={"Alan Wake 2": "Alan Wake II"})
    client = PcGamingWikiClient(http, FakeSpecJudge())
    requirements = asyncio.run(client.fetch_requirements([game(1, "Alan Wake 2")]))

    spec = requirements[1]
    assert spec.minimum is not None
    assert spec.minimum.os == "Windows 10"
    assert spec.minimum.cpu == "Intel Core i5-4460 or AMD FX-6300"
    assert spec.minimum.gpu == "Nvidia GeForce GTX 960 or AMD Radeon R7 370"  # 위키 링크 제거
    assert spec.minimum.ram_gb == 8
    assert spec.minimum.source_url == "https://www.pcgamingwiki.com/wiki/Alan_Wake_II"
    assert spec.recommended is not None and spec.recommended.ram_gb == 16
    assert spec.recommended.gpu == "Nvidia GeForce RTX 2060"
    assert calls[0].url.params["redirects"] == "1"
    assert calls[0].headers["User-Agent"].startswith("game-recommend-be")


def test_pcgamingwiki_fetches_all_titles_in_one_query():
    http, calls = wiki_http(
        {"Alan Wake II": WIKITEXT, "League of Legends": NO_TEMPLATE},
        redirects={"Alan Wake 2": "Alan Wake II"},
    )
    client = PcGamingWikiClient(http, FakeSpecJudge())
    games = [game(1, "Alan Wake 2"), game(2, "League of Legends"), game(3, "Bloodborne")]
    requirements = asyncio.run(client.fetch_requirements(games))

    assert set(requirements) == {1, 2}  # 없는 페이지(Bloodborne)는 키가 없다
    assert requirements[1].minimum is not None
    assert requirements[1].minimum.source_url.endswith("/Alan_Wake_II")  # 리다이렉트된 최종 제목
    assert requirements[2].minimum is None  # 페이지는 있지만 템플릿이 없다
    # 게임 수와 무관하게 묶음 조회 한 번, 못 찾은 게임만 제목 검색
    assert wiki_actions(calls) == ["query", "opensearch"]
    assert queried_titles(calls[0]) == ["Alan Wake 2", "League of Legends", "Bloodborne"]
    assert calls[1].url.params["search"] == "Bloodborne"


def test_pcgamingwiki_uses_search_only_for_normalized_exact_title():
    http, calls = wiki_http({"VALORANT": WIKITEXT}, search=["Valorant (mod)", "VALORANT"])
    client = PcGamingWikiClient(http, FakeSpecJudge())
    requirements = asyncio.run(client.fetch_requirements([game(1, "valorant")]))
    assert requirements[1].minimum is not None
    # 묶음 조회 실패 → 검색 → 정규화 제목이 같은 것만 다시 묶음 조회
    assert wiki_actions(calls) == ["query", "opensearch", "query"]
    assert queried_titles(calls[2]) == ["VALORANT"]


def test_pcgamingwiki_missing_page_is_absent_and_similar_titles_are_ignored():
    http, calls = wiki_http({}, search=["Alan Wake", "Alan Wake II Deluxe"])
    client = PcGamingWikiClient(http, FakeSpecJudge())
    assert asyncio.run(client.fetch_requirements([game(1, "Alan Wake 2")])) == {}
    assert wiki_actions(calls) == ["query", "opensearch"]

    results = asyncio.run(client.assess([game(1, "Alan Wake 2")], HardwareSpecs(ram_gb=16)))
    assert results[0].status == "unknown" and results[0].requirement is None
    assert len(calls) == 2  # 못 찾은 결과도 캐시한다


def test_pcgamingwiki_page_without_template_counts_as_looked_up_and_is_cached():
    http, calls = wiki_http({"Roblox": NO_TEMPLATE})
    client = PcGamingWikiClient(http, FakeSpecJudge())
    first = asyncio.run(client.fetch_requirements([game(1, "Roblox"), game(2, "roblox")]))
    second = asyncio.run(client.fetch_requirements([game(1, "Roblox")]))
    assert first[1].minimum is None and first[2] == first[1]
    assert second == {1: first[1]}
    assert len(calls) == 1  # 정규화 제목이 같은 후보는 한 번만, 두 번째 호출은 캐시
    assert queried_titles(calls[0]) == ["Roblox"]


def test_pcgamingwiki_follows_continue_when_response_is_truncated():
    http, calls = wiki_http({"Alan Wake II": WIKITEXT, "Roblox": NO_TEMPLATE}, split_after=1)
    client = PcGamingWikiClient(http, FakeSpecJudge())
    requirements = asyncio.run(
        client.fetch_requirements([game(1, "Alan Wake II"), game(2, "Roblox")])
    )
    assert set(requirements) == {1, 2} and requirements[1].minimum is not None
    assert wiki_actions(calls) == ["query", "query"]
    assert calls[1].url.params["rvcontinue"] == "next"  # 첫 응답의 continue를 그대로 돌려보낸다


def test_pcgamingwiki_splits_more_than_fifty_titles():
    names = [f"Game {index}" for index in range(51)]
    http, calls = wiki_http(dict.fromkeys(names, NO_TEMPLATE))
    client = PcGamingWikiClient(http, FakeSpecJudge())
    games = [game(index + 1, name) for index, name in enumerate(names)]
    assert len(asyncio.run(client.fetch_requirements(games))) == 51
    assert wiki_actions(calls) == ["query", "query"]
    assert sorted(len(queried_titles(call)) for call in calls) == [1, 50]


def test_pcgamingwiki_invalid_title_is_treated_as_missing():
    http, calls = wiki_http({})
    client = PcGamingWikiClient(http, FakeSpecJudge())
    assert asyncio.run(client.fetch_requirements([game(1, "Foo|Bar")])) == {}
    assert wiki_actions(calls) == ["query", "opensearch"]
    assert queried_titles(calls[0]) == ["Foo|Bar"]  # U+001F 구분자라 |가 든 이름도 그대로 간다


def test_pcgamingwiki_raises_on_other_api_errors():
    http, _ = wiki_http({}, error={"code": "ratelimited"})
    client = PcGamingWikiClient(http, FakeSpecJudge())
    with pytest.raises(RuntimeError):
        asyncio.run(client.fetch_requirements([game(1, "X")]))


def test_pcgamingwiki_assess_uses_shared_rules_and_judge():
    judge = FakeSpecJudge(
        [HardwareAssessment(igdb_id=1, status="met", reason="GPU 충족: GTX 960 이상")]
    )
    http, _ = wiki_http({"Alan Wake II": WIKITEXT}, redirects={"Alan Wake 2": "Alan Wake II"})
    client = PcGamingWikiClient(http, judge)

    low_memory = asyncio.run(client.assess([game(1, "Alan Wake 2")], HardwareSpecs(ram_gb=4)))
    assert low_memory[0].status == "unmet" and "메모리 부족" in low_memory[0].reason
    assert judge.requests == []  # 메모리 규칙으로 끝나면 판정기를 부르지 않는다

    judged = asyncio.run(
        client.assess([game(1, "Alan Wake 2")], HardwareSpecs(gpu="RTX 3060", ram_gb=16))
    )
    assert judged[0].status == "met"
    assert judged[0].recommended is not None and judged[0].recommended.ram_gb == 16
    assert [r.igdb_id for r in judge.requests] == [1]


# ---------- 라우팅 ----------


class RecordingClient(FakePriceHardware):
    """어느 후보를 받았는지 기록한다."""

    def __init__(self, quotes=(), assessments=(), *, error: Exception | None = None):
        super().__init__(list(quotes), list(assessments))
        self.error = error
        self.received: list[list[int]] = []

    async def fetch_prices(self, games):
        self.received.append([g.igdb_id for g in games])
        if self.error:
            raise self.error
        return self.quotes

    async def assess(self, games, hardware):
        self.received.append([g.igdb_id for g in games])
        if self.error:
            raise self.error
        return self.assessments


GAMES = [game(1, "Steam Game", app_id=10), game(2, "League of Legends"), game(3, "Other", 30)]


def test_routed_price_splits_by_steam_app_id_and_merges():
    steam = RecordingClient(quotes=[PriceQuote(igdb_id=1, amount_krw=100)])
    fallback = RecordingClient(quotes=[PriceQuote(igdb_id=2, amount_krw=0)])
    results = asyncio.run(RoutedPriceClient(steam, fallback).fetch_prices(GAMES))

    assert steam.received == [[1, 3]]
    assert fallback.received == [[2]]
    assert sorted(r.igdb_id for r in results) == [1, 2]


def test_routed_hardware_passes_user_specs_to_both_sides():
    steam = RecordingClient(assessments=[HardwareAssessment(igdb_id=1, status="met", reason="ok")])
    fallback = RecordingClient(
        assessments=[HardwareAssessment(igdb_id=2, status="unknown", reason="정보 없음")]
    )
    results = asyncio.run(
        RoutedHardwareClient(steam, fallback).assess(GAMES, HardwareSpecs(ram_gb=16))
    )
    assert steam.received == [[1, 3]] and fallback.received == [[2]]
    assert {r.igdb_id: r.status for r in results} == {1: "met", 2: "unknown"}


def test_routed_skips_empty_sides():
    steam = RecordingClient(quotes=[PriceQuote(igdb_id=1, amount_krw=100)])
    fallback = RecordingClient()
    asyncio.run(RoutedPriceClient(steam, fallback).fetch_prices([GAMES[0]]))
    assert fallback.received == []
    asyncio.run(RoutedPriceClient(steam, fallback).fetch_prices([GAMES[1]]))
    assert steam.received == [[1]]


def test_routed_keeps_steam_results_when_fallback_fails():
    steam = RecordingClient(quotes=[PriceQuote(igdb_id=1, amount_krw=100)])
    fallback = RecordingClient(error=RuntimeError("wiki down"))
    results = asyncio.run(RoutedPriceClient(steam, fallback).fetch_prices(GAMES))
    assert [r.igdb_id for r in results] == [1]


def test_routed_propagates_steam_failure():
    steam = RecordingClient(error=RuntimeError("steam down"))
    fallback = RecordingClient(quotes=[PriceQuote(igdb_id=2, amount_krw=0)])
    with pytest.raises(RuntimeError):
        asyncio.run(RoutedPriceClient(steam, fallback).fetch_prices(GAMES))
