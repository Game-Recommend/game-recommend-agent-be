"""비Steam 폴백 실측 평가. 루트에서 python -m evals.non_steam.run_eval.

PCGamingWiki·CheapShark·Frankfurter를 실제로 호출하고, 판정 일관성(C)만 OpenAISpecJudge를 쓴다.
정답은 dataset.json에 고정돼 있으며 모델 입력에 전달하지 않는다.
"""

import argparse
import asyncio
import hashlib
import json
import time
from datetime import UTC, datetime
from pathlib import Path

import httpx2
from openai import AsyncOpenAI

from app.clients.cheapshark import DEAL_URL, CheapSharkClient
from app.clients.exchange_rate import ExchangeRateClient
from app.clients.hardware_assessor import GameRequirements, assess_requirements
from app.clients.hardware_judge import SYSTEM_PROMPT, OpenAISpecJudge
from app.clients.pcgamingwiki import PcGamingWikiClient, parse_requirements_page
from app.clients.steam_store import parse_requirements
from app.config import get_settings
from app.schemas.game import GameCandidate
from app.schemas.hardware import HardwareSpecs
from app.schemas.price import PriceQuote, PriceUnavailable

ROOT = Path(__file__).resolve().parent
FIELDS = ("os", "cpu", "gpu", "ram_gb")


class NoJudge:
    """LLM을 쓰지 않을 때. 요청을 받으면 실패로 기록되도록 예외를 던진다."""

    async def judge(self, hardware, requests):
        raise RuntimeError("LLM judge disabled")


# ---------- W: PCGamingWiki ----------


async def evaluate_wiki(cases: list[dict], client: PcGamingWikiClient) -> list[dict]:
    games = [GameCandidate(igdb_id=i, name=c["name"]) for i, c in enumerate(cases, 1)]
    start = time.monotonic()
    error = None
    try:
        found = await client.fetch_requirements(games)
    except Exception as exc:
        found, error = {}, type(exc).__name__
    elapsed = round(time.monotonic() - start, 3)
    results = []
    for game, case in zip(games, cases, strict=True):
        spec = found.get(game.igdb_id)
        minimum = spec.minimum if spec else None
        parsed = [f for f in FIELDS if minimum and getattr(minimum, f)] if minimum else []
        results.append(
            {
                **case,
                "matched": spec is not None,
                "has_minimum": minimum is not None,
                "has_recommended": bool(spec and spec.recommended),
                "parsed_fields": parsed,
                "minimum_raw": minimum.raw_text[:300] if minimum else None,
                "error": error,
                "passed": error is None
                and (
                    case["expected_match"] is None
                    or case["expected_match"] == (spec is not None)
                ),
                "elapsed_seconds": elapsed,
            }
        )
    return results


# ---------- P: 가격 ----------


def classify_price(result: PriceQuote | PriceUnavailable | None) -> str:
    if result is None:
        return "omitted"
    if isinstance(result, PriceUnavailable):
        return "unavailable"
    return "free" if result.amount_krw == 0 else "quoted"


async def evaluate_price(cases: list[dict], client: CheapSharkClient) -> list[dict]:
    games = [GameCandidate(igdb_id=i, name=c["name"]) for i, c in enumerate(cases, 1)]
    start = time.monotonic()
    error = None
    try:
        by_id = {r.igdb_id: r for r in await client.fetch_prices(games)}
    except Exception as exc:
        by_id, error = {}, type(exc).__name__
    elapsed = round(time.monotonic() - start, 3)
    results = []
    for game, case in zip(games, cases, strict=True):
        result = by_id.get(game.igdb_id)
        actual = classify_price(result)
        krw = result.amount_krw if isinstance(result, PriceQuote) else None
        in_range = True
        if actual == "quoted" and case["krw_range"]:
            low, high = case["krw_range"]
            in_range = low <= krw <= high
        results.append(
            {
                **case,
                "actual": actual,
                "amount_krw": krw,
                "source_url": getattr(result, "source_url", None),
                "via_cheapshark": bool(
                    getattr(result, "source_url", "")
                    and str(result.source_url).startswith(DEAL_URL.split("?")[0])
                ),
                "error": error,
                "passed": error is None and actual == case["expected"] and in_range,
                "elapsed_seconds": elapsed,
            }
        )
    return results


# ---------- C: 판정 일관성 ----------


async def evaluate_consistency(case: dict, judge) -> dict:
    steam_spec = parse_requirements(case["steam_html"])
    wiki_page = parse_requirements_page(case["wikitext"], "https://example.com/wiki")
    wiki_spec = wiki_page.minimum if wiki_page else None
    field_parity = {
        f: getattr(steam_spec, f, None) == getattr(wiki_spec, f, None) for f in FIELDS
    }
    games = [
        GameCandidate(igdb_id=1, name="Steam 형식 게임"),
        GameCandidate(igdb_id=2, name="PCGamingWiki 형식 게임"),
    ]
    requirements = {
        1: GameRequirements(minimum=steam_spec),
        2: GameRequirements(minimum=wiki_spec),
    }
    hardware = HardwareSpecs(**case["hardware"])
    start = time.monotonic()
    assessments = {
        a.igdb_id: a for a in await assess_requirements(games, hardware, requirements, judge)
    }
    statuses = {"steam": assessments[1].status, "wiki": assessments[2].status}
    reasons = {"steam": assessments[1].reason, "wiki": assessments[2].reason}
    judge_failed = any("판정 실패" in r for r in reasons.values())
    return {
        "id": case["id"],
        "kind": "consistency",
        "category": case["category"],
        "expected": case["expected"],
        "expects_llm": case["expects_llm"],
        "field_parity": field_parity,
        "statuses": statuses,
        "reasons": reasons,
        "judge_failed": judge_failed,
        "consistent": statuses["steam"] == statuses["wiki"],
        "passed": all(field_parity.values())
        and not judge_failed
        and statuses["steam"] == statuses["wiki"] == case["expected"],
        "elapsed_seconds": round(time.monotonic() - start, 3),
    }


# ---------- 집계 ----------


def summarize(results: list[dict], rate: float | None) -> dict:
    wiki = [r for r in results if r["kind"] == "wiki"]
    price = [r for r in results if r["kind"] == "price"]
    cons = [r for r in results if r["kind"] == "consistency"]
    with_min = [r for r in wiki if r["has_minimum"]]
    return {
        "wiki": {
            "cases": len(wiki),
            "errors": sum(r["error"] is not None for r in wiki),
            "matched": sum(r["matched"] for r in wiki),
            "with_minimum": len(with_min),
            "with_all_four_fields": sum(len(r["parsed_fields"]) == 4 for r in with_min),
            "field_counts": {f: sum(f in r["parsed_fields"] for r in with_min) for f in FIELDS},
            "expected_match_checked": sum(r["expected_match"] is not None for r in wiki),
            "expected_match_passed": sum(
                r["passed"] for r in wiki if r["expected_match"] is not None
            ),
        },
        "price": {
            "cases": len(price),
            "errors": sum(r["error"] is not None for r in price),
            "passed": sum(r["passed"] for r in price),
            "by_actual": {
                k: sum(r["actual"] == k for r in price)
                for k in ("free", "quoted", "omitted", "unavailable")
            },
            "false_unavailable": sum(r["actual"] == "unavailable" for r in price),
            "usd_to_krw": rate,
            "rate_in_sane_range": rate is not None and 1000 <= rate <= 2000,
        },
        "consistency": {
            "cases": len(cons),
            "judge_failures": sum(r["judge_failed"] for r in cons),
            "field_parity_all": sum(all(r["field_parity"].values()) for r in cons),
            "consistent": sum(r["consistent"] for r in cons),
            "passed": sum(r["passed"] for r in cons),
        },
    }


async def main(args):
    data_bytes = ROOT.joinpath("dataset.json").read_bytes()
    dataset = json.loads(data_bytes)
    settings = get_settings()
    use_llm = bool(settings.openai_api_key) and not args.no_llm
    path = ROOT / args.output
    path.mkdir(parents=True, exist_ok=True)
    metadata = {
        "started_at": datetime.now(UTC).isoformat(),
        "model": settings.openai_model if use_llm else None,
        "dataset_sha256": hashlib.sha256(data_bytes).hexdigest(),
        "prompt_sha256": hashlib.sha256(SYSTEM_PROMPT.encode()).hexdigest(),
        "scope": (
            "live PCGamingWiki + CheapShark + Frankfurter; consistency uses live OpenAISpecJudge"
        ),
    }
    with (path / "metadata.json").open("x") as file:  # 기존 결과 덮어쓰기 방지
        json.dump(metadata, file, ensure_ascii=False, indent=2)

    results: list[dict] = []
    rate = None
    async with httpx2.AsyncClient(timeout=20) as http:
        exchange = ExchangeRateClient(http)
        try:
            rate = await exchange.usd_to_krw()
        except Exception as exc:
            print(json.dumps({"exchange_rate_error": type(exc).__name__}), flush=True)
        judge = NoJudge()
        api = None
        if use_llm:
            api = AsyncOpenAI(api_key=settings.openai_api_key, timeout=45, max_retries=0)
            judge = OpenAISpecJudge(api, settings.openai_model)
        try:
            wiki_results, price_results = await asyncio.gather(
                evaluate_wiki(
                    [c for c in dataset if c["kind"] == "wiki"],
                    PcGamingWikiClient(http, judge),
                ),
                evaluate_price(
                    [c for c in dataset if c["kind"] == "price"],
                    CheapSharkClient(http, exchange),
                ),
            )
            results.extend(wiki_results)
            results.extend(price_results)
            for case in (c for c in dataset if c["kind"] == "consistency"):
                if case["expects_llm"] and not use_llm:
                    continue
                results.append(await evaluate_consistency(case, judge))
        finally:
            if api is not None:
                await api.close()

    with (path / "results.jsonl").open("w") as file:
        for r in results:
            file.write(json.dumps(r, ensure_ascii=False) + "\n")
            print(f"{r['id']} passed={r['passed']}", flush=True)
    summary = summarize(results, rate)
    (path / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default=datetime.now(UTC).strftime("runs/%Y%m%dT%H%M%SZ"))
    parser.add_argument("--no-llm", action="store_true", help="판정 일관성의 LLM 사례를 건너뛴다")
    asyncio.run(main(parser.parse_args()))
