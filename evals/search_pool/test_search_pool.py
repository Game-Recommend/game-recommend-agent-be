"""검색 후보 풀 평가의 집계 검사. API를 부르지 않는다."""

from evals.search_pool.run_eval import summarize


def candidate(igdb_id, name, steam_app_id=None):
    return {"igdb_id": igdb_id, "name": name, "steam_app_id": steam_app_id}


RECORDS = [
    {
        "id": "E1",
        "family": "count",
        "candidates": [
            candidate(1, "Thief II", 10),
            candidate(2, "Thief", 20),
            candidate(3, "LoL"),
        ],
    },
    {"id": "E2", "family": "count", "candidates": [candidate(1, "Thief II", 10)]},
    {"id": "E3", "family": "free", "candidates": []},
    {"id": "E4", "family": "free", "candidates": [], "error": "HTTPStatusError: 429"},
]
YEARS = {1: 2000, 2: 2014, 3: 2009}
STEAM = {
    10: {"available": True, "is_free": False, "price_krw": 7690, "has_requirements": True},
    20: {"available": False, "is_free": False, "price_krw": None, "has_requirements": False},
}


def test_summary_counts_zero_candidates_and_repeated_games():
    summary = summarize(RECORDS, YEARS, STEAM, top_k=10)

    assert summary["cases"] == 4 and summary["errors"] == 1
    assert summary["zero_candidates"] == ["E3"]  # 오류로 끝난 문항은 세지 않는다
    assert summary["distinct_games"] == 3
    assert summary["release_year_median"] == 2004  # 2000, 2014, 2009, 2000
    # 후보가 있는 두 문항 모두의 앞쪽에 Thief II가 있다
    assert summary["most_common_head5"][0] == {"name": "Thief II", "questions": 2, "share": 1.0}
    assert summary["on_steam"] == 0.75


def test_steam_shares_use_successfully_checked_steam_candidates_as_denominator():
    steam = summarize(RECORDS, YEARS, STEAM, top_k=10)["steam_top10"]

    assert steam["candidates"] == 4 and steam["on_steam"] == 0.75
    # Steam 후보 3개(10, 20, 10) 중 한국 스토어에서 살 수 있는 것은 10번 두 번
    assert steam["kr_available"] == steam["priced"] == round(2 / 3, 4)
    assert steam["price_le_10000"] == round(2 / 3, 4)
    assert steam["price_median_krw"] == 7690


def test_summary_without_steam_lookup():
    steam = summarize(RECORDS, YEARS, {}, top_k=10)["steam_top10"]

    assert steam["kr_available"] is None and steam["price_median_krw"] is None
    assert summarize([], {}, {}, top_k=10)["candidates_median"] is None
