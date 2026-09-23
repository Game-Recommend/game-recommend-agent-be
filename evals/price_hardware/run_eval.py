"""고정 Steam 대역 + 실제 OpenAISpecJudge 평가. 루트에서 python -m evals.price_hardware.run_eval."""

import argparse
import asyncio
import hashlib
import json
import time
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

import httpx2
from openai import AsyncOpenAI

from app.clients.hardware_judge import SYSTEM_PROMPT, OpenAISpecJudge
from app.clients.steam_store import SteamStoreClient
from app.config import get_settings
from app.schemas.game import GameCandidate
from app.schemas.hardware import HardwareSpecs
from app.tools.hardware import HardwareTool
from app.tools.price import PriceTool

ROOT = Path(__file__).resolve().parent


def requirement_html(spec):
    if spec is None:
        return ""
    labels = {"cpu": "Processor", "gpu": "Graphics", "ram_gb": "Memory", "os": "OS"}
    return (
        "<ul>"
        + "".join(
            f"<li><strong>{labels[k]}:</strong> {v}{' GB RAM' if k == 'ram_gb' else ''}</li>"
            for k, v in spec.items()
        )
        + "</ul>"
    )


def store_entry(store=None, minimum=None, recommended=None):
    s = store or {}
    if not s.get("available", True):
        return {"success": False}
    data = {
        "is_free": s.get("is_free", False),
        "packages": s.get("packages", [1]),
        "release_date": {"coming_soon": s.get("coming_soon", False)},
        "pc_requirements": {
            "minimum": requirement_html(minimum),
            "recommended": requirement_html(recommended),
        },
    }
    if not s.get("no_price"):
        data["price_overview"] = {
            "currency": s.get("currency", "KRW"),
            "final": s.get("final", 2700000),
        }
    return {"success": True, "data": data}


class RecordingJudge:
    def __init__(self, judge):
        self.judge = judge
        self.calls = 0
        self.error = None
        self.verdicts = []
        self.requested_ids = []

    async def judge_specs(self, hardware, requests, **options):
        self.calls += 1
        self.requested_ids.extend(request.igdb_id for request in requests)
        try:
            result = await self.judge.judge(hardware, requests, **options)
            self.verdicts = [v.model_dump() for v in result]
            return result
        except Exception as exc:
            # 예외 메시지는 인증 정보/요청 헤더를 포함할 수 있어 저장하지 않는다.
            self.error = {
                "type": type(exc).__name__,
                "status_code": getattr(exc, "status_code", None),
            }
            raise


class JudgeAdapter:
    def __init__(self, recorder):
        self.recorder = recorder

    async def judge(self, hardware, requests, **options):
        # 판정기 계약의 선택 인자(language 등)는 그대로 넘긴다
        return await self.recorder.judge_specs(hardware, requests, **options)


async def evaluate(case, repeat, judge):
    recorder = RecordingJudge(judge)
    entries = {}
    if case["kind"] == "hardware":
        games = [
            GameCandidate(igdb_id=g["igdb_id"], name=g["name"], steam_app_id=g["steam_app_id"])
            for g in case["games"]
        ]
        for g in case["games"]:
            if g["steam_app_id"] is not None:
                entries[g["steam_app_id"]] = store_entry(
                    minimum=g["minimum"], recommended=g.get("recommended")
                )
    else:
        games = [GameCandidate(igdb_id=1, name="합성 가격 게임", steam_app_id=1)]
        entries[1] = store_entry(case["store"])

    def handler(request):
        app_id = int(request.url.params["appids"])
        return httpx2.Response(200, json={str(app_id): entries[app_id]})

    start = time.monotonic()
    async with httpx2.AsyncClient(transport=httpx2.MockTransport(handler)) as http:
        client = SteamStoreClient(http, JudgeAdapter(recorder))
        if case["kind"] == "hardware":
            hardware = HardwareSpecs(**case["hardware"]) if case["hardware"] is not None else None
            output = await HardwareTool(client).run(games, hardware)
            expected = {g["igdb_id"]: g["expected"] for g in case["games"]}
        else:
            output = await PriceTool(client).run(games, case["budget_krw"])
            expected = {1: case["expected"]}
    rows = []
    returned_ids = Counter(v["igdb_id"] for v in recorder.verdicts)
    for game in games:
        result = output[game.igdb_id]
        row = {
            "igdb_id": game.igdb_id,
            "expected": expected[game.igdb_id],
            "actual": result.check.status,
            "reason": result.check.reason,
            "status_match": result.check.status == expected[game.igdb_id],
        }
        # 빈 응답이 도구에서 unknown으로 바뀌어 정답으로 집계되는 것을 방지한다.
        row["response_complete"] = (
            game.igdb_id not in recorder.requested_ids or returned_ids[game.igdb_id] == 1
        )
        row["status_match"] = row["status_match"] and row["response_complete"]
        if case["kind"] == "price":
            amount = result.quote.amount_krw if result.quote else None
            row.update(amount_krw=amount, amount_match=amount == case["expected_amount_krw"])
        rows.append(row)
    routing_match = bool(recorder.calls) == case["expects_llm"]
    return {
        "id": case["id"],
        "repeat": repeat,
        "kind": case["kind"],
        "gold_basis": case["gold_basis"],
        "category": case["category"],
        "llm_calls": recorder.calls,
        "llm_error": recorder.error,
        "raw_verdicts": recorder.verdicts,
        "routing_match": routing_match,
        "elapsed_seconds": round(time.monotonic() - start, 3),
        "rows": rows,
        "passed": recorder.error is None
        and routing_match
        and all(r["status_match"] and r.get("amount_match", True) for r in rows),
    }


async def live_steam(judge):
    results = []
    async with httpx2.AsyncClient(timeout=20) as http:
        client = SteamStoreClient(http, judge)
        for app_id in (570, 620, 1245620):
            try:
                detail = await client.get_app_details(app_id)
                results.append({"app_id": app_id, "ok": True, "details": detail.model_dump()})
            except Exception as exc:
                results.append({"app_id": app_id, "ok": False, "error": type(exc).__name__})
    return results


def summarize(results):
    groups = {}
    for name, selected in {
        "all": results,
        "llm": [r for r in results if r["llm_calls"]],
        "deterministic": [r for r in results if not r["llm_calls"]],
        "llm_without_provisional": [
            r
            for r in results
            if r["llm_calls"]
            and r["gold_basis"] not in {"provisional_performance", "policy_proposal"}
        ],
    }.items():
        rows = [row for r in selected if not r["llm_error"] for row in r["rows"]]
        unmet = [row for row in rows if row["expected"] == "unmet"]
        unknown = [row for row in rows if row["expected"] == "unknown"]
        groups[name] = {
            "case_runs": len(selected),
            "passed_case_runs": sum(r["passed"] for r in selected),
            "api_errors": sum(r["llm_error"] is not None for r in selected),
            "valid_verdicts": len(rows),
            "matching_verdicts": sum(r["status_match"] for r in rows),
            "unmet_total": len(unmet),
            "false_met_from_unmet": sum(r["actual"] == "met" for r in unmet),
            "unknown_total": len(unknown),
            "false_met_from_unknown": sum(r["actual"] == "met" for r in unknown),
            "confusion": dict(Counter(f"{r['expected']} -> {r['actual']}" for r in rows)),
        }
    by_case = {}
    for r in results:
        if r["llm_error"] is None:
            by_case.setdefault(r["id"], set()).add(tuple(row["actual"] for row in r["rows"]))
    groups["inconsistent_cases"] = [key for key, values in by_case.items() if len(values) > 1]
    return groups


async def main(args):
    data_bytes = ROOT.joinpath("dataset.json").read_bytes()
    dataset = json.loads(data_bytes)
    settings = get_settings()
    if not settings.openai_api_key:
        raise SystemExit("OPENAI_API_KEY가 설정되지 않았습니다.")
    path = ROOT / args.output
    path.mkdir(parents=True, exist_ok=True)
    metadata = {
        "started_at": datetime.now(UTC).isoformat(),
        "model": settings.openai_model,
        "dataset_sha256": hashlib.sha256(data_bytes).hexdigest(),
        "prompt_sha256": hashlib.sha256(SYSTEM_PROMPT.encode()).hexdigest(),
        "repeats_llm": args.repeats,
        "repeats_deterministic": 1,
        "scope": "synthetic Steam fixtures + live existing OpenAISpecJudge; no question parser",
    }
    results = []
    # 기존 결과 덮어쓰기 방지
    with (path / "metadata.json").open("x") as file:
        json.dump(metadata, file, ensure_ascii=False, indent=2)
    async with AsyncOpenAI(api_key=settings.openai_api_key, timeout=45, max_retries=0) as api:
        judge = OpenAISpecJudge(api, settings.openai_model)
        # 첫 LLM 사례로 인증/연결을 확인한 뒤 나머지를 실행한다.
        first = await evaluate(dataset[0], 1, judge)
        results.append(first)
        with (path / "results.jsonl").open("a") as file:
            file.write(json.dumps(first, ensure_ascii=False) + "\n")
        if first["llm_error"]:
            print(json.dumps({"preflight_error": first["llm_error"]}), flush=True)
        else:
            semaphore = asyncio.Semaphore(args.concurrency)

            async def run(case, repeat):
                async with semaphore:
                    result = await evaluate(case, repeat, judge)
                    results.append(result)
                    with (path / "results.jsonl").open("a") as file:
                        file.write(json.dumps(result, ensure_ascii=False) + "\n")
                    print(
                        f"{result['id']} repeat={repeat} passed={result['passed']} "
                        f"error={result['llm_error']}",
                        flush=True,
                    )

            jobs = [
                (case, repeat)
                for case in dataset
                for repeat in range(1, (args.repeats if case["expects_llm"] else 1) + 1)
                if not (case["id"] == dataset[0]["id"] and repeat == 1)
            ]
            await asyncio.gather(*(run(case, repeat) for case, repeat in jobs))
        if args.live_steam:
            (path / "steam_live.json").write_text(
                json.dumps(await live_steam(judge), ensure_ascii=False, indent=2) + "\n"
            )
    summary = summarize(results)
    (path / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--repeats", type=int, default=2)
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument("--output", default=datetime.now(UTC).strftime("runs/%Y%m%dT%H%M%SZ"))
    parser.add_argument("--live-steam", action="store_true")
    args = parser.parse_args()
    if args.repeats < 1 or args.concurrency < 1:
        parser.error("repeats와 concurrency는 1 이상이어야 합니다.")
    asyncio.run(main(args))
