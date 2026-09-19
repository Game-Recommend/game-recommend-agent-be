"""검색 후보 풀 평가. LLM을 부르지 않는다. 루트에서 실행한다.

    .venv/bin/python -m evals.search_pool.run_eval --label before

IGDB 검색(`app/clients/igdb.py`)이 문항별로 어떤 후보를 내는지만 본다. 가격·사양 판정과 에이전트는
돌리지 않는다. 입력은 엔드투엔드 실행에서 파서가 실제로 낸 조건(dataset.json)이다.

실제 IGDB와 Steam 스토어를 부른다. Steam 상세 API는 IP당 5분에 약 200회 제한이 있어 문항별 상위
후보만, 간격을 두고 조회한다(기본 1.6초). 그래서 100문항에 수 분이 걸린다. CI에서는 돌리지 않는다.
"""

import argparse
import asyncio
import json
import statistics
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

import httpx2

from app.clients import igdb
from app.clients.steam_store import AppDetails, SteamStoreClient
from app.config import get_settings

ROOT = Path(__file__).resolve().parent
HEAD = 5  # 조건이 느슨한 질문에서 그대로 추천이 되는 앞쪽 후보 수(기본 추천 개수)


async def search_all(cases: list[dict]) -> list[dict]:
    """문항마다 검색을 돌린다. IGDB는 초당 4회 제한이라 순서대로 부른다."""
    records = []
    for index, case in enumerate(cases, 1):
        record = {key: case[key] for key in ("id", "family", "question", "conditions")}
        try:
            rows = await igdb.search(case["conditions"])
        except Exception as exc:
            record["error"] = f"{type(exc).__name__}: {exc}"
            rows = []
        record["candidates"] = [
            {"igdb_id": row["igdb_id"], "name": row["name"], "steam_app_id": row["steam_app_id"]}
            for row in rows
        ]
        records.append(record)
        print(f"  {index}/{len(cases)} {case['id']} 후보 {len(rows)}개", flush=True)
    return records


async def release_years(igdb_ids: list[int]) -> dict[int, int]:
    """후보의 첫 출시 연도. 후보 모델에 없는 값이라 평가에서만 따로 조회한다."""
    settings = get_settings()
    years: dict[int, int] = {}
    async with httpx2.AsyncClient(timeout=30) as client:
        for start in range(0, len(igdb_ids), 500):
            chunk = ",".join(str(igdb_id) for igdb_id in igdb_ids[start : start + 500])
            body = f"fields first_release_date; where id = ({chunk}); limit 500;"
            for row in await igdb._post(client, settings, "games", body):
                if released := row.get("first_release_date"):
                    years[row["id"]] = datetime.fromtimestamp(released, UTC).year
    return years


async def steam_details(app_ids: list[int], interval: float) -> dict[int, dict]:
    """한국 스토어 기준 상세. 실패한 앱은 {"error": ...}로 남긴다."""
    results: dict[int, dict] = {}
    async with httpx2.AsyncClient(timeout=20) as http:
        client = SteamStoreClient(http, judge=None)
        for index, app_id in enumerate(app_ids, 1):
            try:
                details: AppDetails = await client.get_app_details(app_id)
            except Exception as exc:
                results[app_id] = {"error": type(exc).__name__}
            else:
                results[app_id] = {
                    "available": details.available,
                    "is_free": details.is_free,
                    "price_krw": details.price_krw,
                    "has_requirements": details.requirements is not None,
                }
            if index % 25 == 0:
                print(f"  Steam {index}/{len(app_ids)}", flush=True)
            await asyncio.sleep(interval)
    return results


def share(part: int, whole: int) -> float | None:
    return round(part / whole, 4) if whole else None


def summarize(
    records: list[dict], years: dict[int, int], steam: dict[int, dict], top_k: int
) -> dict:
    scored = [record for record in records if not record.get("error")]
    with_candidates = [record for record in scored if record["candidates"]]
    everything = [c for record in scored for c in record["candidates"]]
    head = [c for record in scored for c in record["candidates"][:HEAD]]
    top = [c for record in scored for c in record["candidates"][:top_k]]

    def median_year(candidates: list[dict]) -> int | None:
        known = [years[c["igdb_id"]] for c in candidates if c["igdb_id"] in years]
        return int(statistics.median(known)) if known else None

    # 같은 게임이 몇 문항의 앞쪽 후보에 드는가. 질문과 무관하게 같은 게임이 나오는 정도를 본다
    head_questions = Counter(
        name for record in scored for name in {c["name"] for c in record["candidates"][:HEAD]}
    )

    def steam_summary(candidates: list[dict]) -> dict:
        on_steam = [c for c in candidates if c["steam_app_id"] is not None]
        checked = [steam[c["steam_app_id"]] for c in on_steam if c["steam_app_id"] in steam]
        done = [detail for detail in checked if "error" not in detail]
        priced = [
            d for d in done if d["available"] and (d["is_free"] or d["price_krw"] is not None)
        ]
        prices = [0 if d["is_free"] else d["price_krw"] for d in priced]
        return {
            "candidates": len(candidates),
            "on_steam": share(len(on_steam), len(candidates)),
            "lookup_errors": len(checked) - len(done),
            # 아래 비율의 분모는 상세 조회에 성공한 Steam 후보다
            "kr_available": share(sum(d["available"] for d in done), len(done)),
            "priced": share(len(priced), len(done)),
            "price_le_10000": share(sum(price <= 10000 for price in prices), len(done)),
            "price_le_30000": share(sum(price <= 30000 for price in prices), len(done)),
            "free": share(sum(price == 0 for price in prices), len(done)),
            "has_requirements": share(sum(d["has_requirements"] for d in done), len(done)),
            "price_median_krw": int(statistics.median(prices)) if prices else None,
        }

    families: dict[str, dict] = {}
    for record in scored:
        bucket = families.setdefault(
            record["family"], {"cases": 0, "zero_candidates": 0, "top": []}
        )
        bucket["cases"] += 1
        bucket["zero_candidates"] += not record["candidates"]
        bucket["top"].extend(record["candidates"][:top_k])

    return {
        "cases": len(records),
        "errors": len(records) - len(scored),
        "zero_candidates": sorted(r["id"] for r in scored if not r["candidates"]),
        "candidates_median": int(statistics.median(len(r["candidates"]) for r in scored))
        if scored
        else None,
        "on_steam": share(sum(c["steam_app_id"] is not None for c in everything), len(everything)),
        "release_year_median": median_year(everything),
        f"release_year_median_head{HEAD}": median_year(head),
        "distinct_games": len({c["igdb_id"] for c in everything}),
        f"distinct_games_head{HEAD}": len({c["igdb_id"] for c in head}),
        f"most_common_head{HEAD}": [
            {"name": name, "questions": count, "share": share(count, len(with_candidates))}
            for name, count in head_questions.most_common(5)
        ],
        f"steam_top{top_k}": steam_summary(top),
        "by_family": {
            name: {
                "cases": bucket["cases"],
                "zero_candidates": bucket["zero_candidates"],
                **{
                    key: value
                    for key, value in steam_summary(bucket["top"]).items()
                    if key in ("priced", "price_le_10000", "price_le_30000", "free")
                },
            }
            for name, bucket in sorted(families.items())
        },
    }


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--label", required=True, help="runs/<label>/에 기록한다")
    parser.add_argument("--limit", type=int, help="앞에서 N문항만 실행한다")
    parser.add_argument("--top-k", type=int, default=10, help="Steam 상세를 볼 문항별 상위 후보 수")
    parser.add_argument("--steam-interval", type=float, default=1.6, help="Steam 호출 간격(초)")
    parser.add_argument("--no-steam", action="store_true", help="Steam 상세 조회를 생략한다")
    args = parser.parse_args()

    out = ROOT / "runs" / args.label
    if out.exists():
        raise SystemExit(f"이미 있는 디렉터리다: {out}")
    dataset = json.loads((ROOT / "dataset.json").read_text(encoding="utf-8"))
    cases = dataset["cases"][: args.limit] if args.limit else dataset["cases"]

    print(f"검색: {len(cases)}문항")
    records = await search_all(cases)
    years = await release_years(sorted({c["igdb_id"] for r in records for c in r["candidates"]}))
    app_ids = sorted(
        {
            c["steam_app_id"]
            for r in records
            for c in r["candidates"][: args.top_k]
            if c["steam_app_id"] is not None
        }
    )
    steam: dict[int, dict] = {}
    if not args.no_steam:
        print(f"Steam 상세: 문항별 상위 {args.top_k}개의 서로 다른 앱 {len(app_ids)}개")
        steam = await steam_details(app_ids, args.steam_interval)
    summary = summarize(records, years, steam, args.top_k)

    out.mkdir(parents=True)
    (out / "metadata.json").write_text(
        json.dumps(
            {
                "started_at": datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ"),
                "label": args.label,
                "source_run": dataset["source_run"],
                "cases": len(cases),
                "top_k": args.top_k,
                "steam": not args.no_steam,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    with (out / "results.jsonl").open("w", encoding="utf-8") as handle:
        for record in records:
            for candidate in record["candidates"]:
                candidate["year"] = years.get(candidate["igdb_id"])
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    (out / "steam.json").write_text(
        json.dumps(steam, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
    )
    (out / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"기록: {out}")


if __name__ == "__main__":
    asyncio.run(main())
