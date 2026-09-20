"""평가 실행기의 채점 오류를 막는 오프라인 검사. 실제 API를 호출하지 않는다."""

import asyncio
import json
from pathlib import Path

import httpx2

from app.clients.cheapshark import CheapSharkClient
from app.clients.exchange_rate import ExchangeRateClient
from app.clients.pcgamingwiki import PcGamingWikiClient
from app.schemas.hardware import HardwareAssessment
from evals.non_steam.run_eval import (
    NoJudge,
    evaluate_consistency,
    evaluate_price,
    evaluate_wiki,
    summarize,
)

DATA = json.loads(Path(__file__).with_name("dataset.json").read_text())
WIKI_CASES = [c for c in DATA if c["kind"] == "wiki"]
PRICE_CASES = [c for c in DATA if c["kind"] == "price"]
CONS_CASES = [c for c in DATA if c["kind"] == "consistency"]


def http_with(routes):
    def handler(request):
        for prefix, body in routes.items():
            if str(request.url).startswith(prefix):
                return httpx2.Response(200, content=json.dumps(body))
        return httpx2.Response(500)

    return httpx2.AsyncClient(transport=httpx2.MockTransport(handler))


class StubJudge:
    def __init__(self, status="met"):
        self.status = status

    async def judge(self, hardware, requests):
        return [
            HardwareAssessment(igdb_id=r.igdb_id, status=self.status, reason="검사")
            for r in requests
        ]


def test_dataset_ids_are_unique_and_kinds_balanced():
    ids = [c["id"] for c in DATA]
    assert len(ids) == len(set(ids))
    assert (len(WIKI_CASES), len(PRICE_CASES), len(CONS_CASES)) == (20, 15, 5)


# 제목 묶음 조회(action=query)에서 없는 문서는 최상위 error가 아니라 pages 항목으로 온다.
# 최상위 error는 진짜 API 실패라 클라이언트가 예외를 올린다
# (그 경우는 test_wiki_error_fails_every_case가 본다).
MISSING = {"query": {"pages": []}}


def test_wiki_scoring_only_checks_cases_with_expected_match():
    # 모든 페이지가 없고 검색도 비어 있는 응답: expected_match=True는 실패, None은 기록만(통과)
    def handler(request):
        if request.url.params.get("action") == "opensearch":
            return httpx2.Response(200, content=json.dumps(["q", [], [], []]))
        return httpx2.Response(200, content=json.dumps(MISSING))

    http = httpx2.AsyncClient(transport=httpx2.MockTransport(handler))
    results = asyncio.run(evaluate_wiki(WIKI_CASES, PcGamingWikiClient(http, NoJudge())))
    by_id = {r["id"]: r for r in results}
    assert not by_id["W01"]["passed"]  # LoL은 매칭돼야 한다
    assert by_id["W20"]["passed"]  # 음성 대조군은 미매칭이 기대값
    assert by_id["W03"]["passed"] and not by_id["W03"]["matched"]  # 기록만
    summary = summarize(results, 1342.0)["wiki"]
    assert summary["matched"] == 0 and summary["expected_match_checked"] == 6


def test_wiki_error_fails_every_case():
    http = http_with({})  # 500
    results = asyncio.run(evaluate_wiki(WIKI_CASES, PcGamingWikiClient(http, NoJudge())))
    assert all(r["error"] == "HTTPStatusError" and not r["passed"] for r in results)


def test_price_scoring_distinguishes_free_quoted_omitted_and_range():
    http = http_with(
        {
            "https://www.cheapshark.com/api/1.0/games": [
                {"external": "Alan Wake 2", "cheapest": "49.99", "cheapestDealID": "d"},
                {"external": "Alan Wake", "cheapest": "0.50", "cheapestDealID": "e"},
            ],
            "https://api.frankfurter.dev/v1/latest": {"rates": {"KRW": 1342.79}},
        }
    )
    client = CheapSharkClient(http, ExchangeRateClient(http))
    results = asyncio.run(evaluate_price(PRICE_CASES, client))
    by_id = {r["id"]: r for r in results}
    assert by_id["P01"]["actual"] == "free" and by_id["P01"]["passed"]
    assert by_id["P07"]["actual"] == "quoted" and by_id["P07"]["passed"]
    assert by_id["P07"]["via_cheapshark"]
    assert by_id["P09"]["actual"] == "quoted" and not by_id["P09"]["passed"]  # 671원: 범위 밖
    assert by_id["P08"]["actual"] == "omitted" and by_id["P08"]["passed"]
    assert by_id["P10"]["actual"] == "omitted" and not by_id["P10"]["passed"]  # quoted 기대
    summary = summarize(results, 1342.79)["price"]
    assert summary["by_actual"]["quoted"] == 2 and summary["false_unavailable"] == 0
    assert summary["rate_in_sane_range"]


def test_consistency_requires_same_status_on_both_formats_and_field_parity():
    deterministic = next(c for c in CONS_CASES if c["id"] == "C01")  # RAM 부족
    result = asyncio.run(evaluate_consistency(deterministic, NoJudge()))
    assert result["field_parity"] == {"os": True, "cpu": True, "gpu": True, "ram_gb": True}
    assert result["statuses"] == {"steam": "unmet", "wiki": "unmet"} and result["passed"]

    llm_case = next(c for c in CONS_CASES if c["id"] == "C03")  # GPU 동일
    assert asyncio.run(evaluate_consistency(llm_case, StubJudge("met")))["passed"]
    wrong = asyncio.run(evaluate_consistency(llm_case, StubJudge("unmet")))
    assert wrong["consistent"] and not wrong["passed"]  # 일관되지만 기대값과 다르면 실패
    failed = asyncio.run(evaluate_consistency(llm_case, NoJudge()))
    assert failed["judge_failed"] and not failed["passed"]
