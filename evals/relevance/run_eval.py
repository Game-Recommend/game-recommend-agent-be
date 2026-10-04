"""취향 적합도 평가 실행기. 저장소 루트에서 실행한다. `.env`의 키를 읽는다.

    .venv/bin/python -m evals.relevance.run_eval --limit 5     # 먼저 작게 확인한다
    .venv/bin/python -m evals.relevance.run_eval --concurrency 2
    .venv/bin/python -m evals.relevance.run_eval --no-judge    # 목록이 달라지는지만 본다
    .venv/bin/python -m evals.relevance.run_eval --ids R033 R038   # 지정한 문항만
    # 원본 저장소를 실제로 돌린 기록(run_original.py)과도 비교한다
    .venv/bin/python -m evals.relevance.run_eval \
        --original evals/relevance/runs/original/<stamp>/results.jsonl

**실제 외부 API와 LLM을 부른다.** 40문항에 에이전트 약 $0.3, 심판(gpt-4o-mini, 문항당 두 번)
약 $0.03, 10분 안팎이다. `--original`을 주면 심판 비용이 약 $0.03 더 든다. CI에서는 돌리지 않는다.

문항마다 (1) 에이전트를 끝까지 실행하고 (2) 같은 조건으로 검색·가격·사양을 다시 돌려 **통과 후보를
검색 순서대로 자른 대조 목록**을 만든 뒤 (3) 두 목록이 다르면 심판에게 자리를 바꿔 두 번 묻는다.
대조 목록을 만들 때 Steam 조회는 에이전트 실행이 채운 캐시를 쓴다. 원본 기록이 있으면 (4) 같은
질문에 원본이 낸 목록과도 같은 규칙으로 비교한다.
"""

import argparse
import asyncio
import hashlib
import json
import time
from datetime import UTC, datetime
from pathlib import Path

from app.agent.prompts import AGENT_SYSTEM
from app.assembly import assemble, missing_settings
from app.config import get_settings
from app.schemas.game import GameCandidate
from evals.relevance.judge import JUDGE_MODEL, JUDGE_SYSTEM, PairJudge, describe_list
from evals.relevance.score import (
    Side,
    baseline_pick,
    combine,
    overlap,
    parse_original,
    summarize,
    to_side,
    versus_original_outcome,
)

EVAL_DIR = Path(__file__).resolve().parent


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


async def compare(
    judge: PairJudge,
    question: str,
    agent: list[GameCandidate],
    other: list[GameCandidate],
    amounts: dict[int, int | None],
    other_side: Side = "baseline",
) -> dict:
    """자리를 바꿔 두 번 묻고 합친다. 어느 쪽이 에이전트인지는 심판에게 알리지 않는다."""
    agent_text, other_text = describe_list(agent, amounts), describe_list(other, amounts)
    first, second = await asyncio.gather(
        judge.judge(question, agent_text, other_text),  # 에이전트가 A
        judge.judge(question, other_text, agent_text),  # 에이전트가 B
    )
    sides = [to_side(first.winner, "A", other_side), to_side(second.winner, "B", other_side)]
    return {
        "outcome": combine(*sides),
        "verdicts": [
            {"agent_is": "A", "side": sides[0], "reason": first.reason},
            {"agent_is": "B", "side": sides[1], "reason": second.reason},
        ],
    }


async def against_original(
    judge: PairJudge | None,
    question: str,
    agent: list[GameCandidate],
    agent_amounts: dict[int, int | None],
    original: dict,
) -> dict:
    """같은 질문에 원본이 낸 목록과 비교한다. 빈 추천은 승패로 세지 않는다."""
    if error := original.get("error"):
        return {"error": error}
    games, original_amounts = parse_original(original)
    agent_ids, original_ids = [g.igdb_id for g in agent], [g.igdb_id for g in games]
    result: dict = {"games": [game.name for game in games]}
    if agent_ids and original_ids:
        result["overlap"] = overlap(agent_ids, original_ids)
    if outcome := versus_original_outcome(agent_ids, original_ids):
        return result | {"outcome": outcome}
    if judge is None:
        return result | {"outcome": "tie", "verdicts": []}
    # 두 목록에 같은 게임이 있으면 같은 가격으로 적는다
    amounts = original_amounts | agent_amounts
    return result | await compare(judge, question, agent, games, amounts, "original")


async def run_one(
    recommender, item: dict, judge: PairJudge | None, original: dict | None = None
) -> dict:
    started = time.perf_counter()
    record = dict(item)
    try:
        response = await recommender.run(item["question"])
        record["seconds"] = round(time.perf_counter() - started, 2)
        conditions = response.conditions
        record["conditions"] = conditions.model_dump(exclude_none=True, exclude_defaults=True)
        agent = [game.game for game in response.games]
        record["agent"] = [game.name for game in agent]
        agent_amounts = {
            game.game.igdb_id: game.price.quote.amount_krw
            for game in response.games
            if game.price.quote is not None
        }
        if original is not None:
            record["original"] = await against_original(
                judge, item["question"], agent, agent_amounts, original
            )
        if not agent:
            return record | {"outcome": "empty", "baseline": [], "overlap": None}

        # 고정 파이프라인이 했을 선택을 같은 도구로 다시 계산한다
        tools = recommender.tools
        candidates = await tools.game_search.run(conditions)
        prices = await tools.price.run(candidates, conditions.max_price_krw)
        hardware = await tools.hardware.run(candidates, conditions.hardware)
        baseline = baseline_pick(candidates, prices, hardware, len(agent))
        record["baseline"] = [game.name for game in baseline]
        record["candidates"] = len(candidates)
        agent_ids = [game.igdb_id for game in agent]
        baseline_ids = [game.igdb_id for game in baseline]
        record["overlap"] = overlap(agent_ids, baseline_ids)
        # 에이전트가 추천한 게임이 다시 계산한 후보에 없으면 두 목록의 후보 풀이 다른 것이다
        pool = {game.igdb_id for game in candidates}
        record["pool_mismatch"] = [game.name for game in agent if game.igdb_id not in pool]

        if set(agent_ids) == set(baseline_ids):
            return record | {"outcome": "same"}
        if judge is None:
            return record | {"outcome": "tie", "verdicts": []}
        amounts = {
            igdb_id: result.quote.amount_krw if result.quote is not None else None
            for igdb_id, result in prices.items()
        }
        amounts |= agent_amounts
        return record | await compare(judge, item["question"], agent, baseline, amounts)
    except Exception as exc:
        record.setdefault("seconds", round(time.perf_counter() - started, 2))
        return record | {"error": f"{type(exc).__name__}: {exc}"}


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--limit", type=int, help="앞에서 N문항만 실행한다")
    parser.add_argument("--ids", nargs="+", help="지정한 문항만 실행한다 (예: R033 R038)")
    parser.add_argument("--concurrency", type=int, default=2)
    parser.add_argument("--no-judge", action="store_true", help="심판을 생략한다")
    parser.add_argument("--judge-model", default=JUDGE_MODEL)
    parser.add_argument("--out", type=Path, help="기본값: runs/<UTC timestamp>/")
    parser.add_argument(
        "--original", type=Path, help="run_original.py의 results.jsonl. 원본이 낸 목록과도 비교한다"
    )
    args = parser.parse_args()

    settings = get_settings()
    dataset = (EVAL_DIR / "dataset.json").read_text(encoding="utf-8")
    cases = json.loads(dataset)
    if args.ids:
        cases = [case for case in cases if case["id"] in set(args.ids)]
    if args.limit:
        cases = cases[: args.limit]
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    out = args.out or EVAL_DIR / "runs" / stamp
    if out.exists():
        raise SystemExit(f"이미 있는 디렉터리다: {out}")

    originals: dict[str, dict] | None = None
    original_meta: dict = {}
    if args.original:
        original_text = args.original.read_text(encoding="utf-8")
        meta = json.loads((args.original.parent / "metadata.json").read_text(encoding="utf-8"))
        if meta["dataset_sha256"] != sha256(dataset):
            raise SystemExit(f"원본 기록의 문항이 지금 dataset.json과 다르다: {args.original}")
        originals = {record["id"]: record for record in map(json.loads, original_text.splitlines())}
        original_meta = {
            "results": str(args.original),
            "results_sha256": sha256(original_text),
            "commit": meta["commit"],
            "model": meta["model"],
        }

    assembled = assemble()
    if assembled is None:
        raise SystemExit(f"필수 설정이 비어 있습니다: {', '.join(missing_settings(settings))}")
    judge = None if args.no_judge else PairJudge(settings.openai_api_key, args.judge_model)
    semaphore = asyncio.Semaphore(args.concurrency)
    done = 0
    print(f"실행: 문항 {len(cases)}개, 동시성 {args.concurrency}, 심판 {not args.no_judge}")

    async def one(item: dict) -> dict:
        nonlocal done
        original = None
        if originals is not None:
            original = originals.get(item["id"], {"error": "원본 기록에 없는 문항"})
        async with semaphore:
            record = await run_one(assembled.recommender, item, judge, original)
            done += 1
            status = record.get("error") or record["outcome"]
            progress = f"{done}/{len(cases)} {item['id']} {record['seconds']}초"
            print(f"  {progress} · {status}", flush=True)
            return record

    try:
        records = await asyncio.gather(*(one(item) for item in cases))
    finally:
        await assembled.aclose()
        if judge is not None:
            await judge.aclose()

    records = sorted(records, key=lambda record: record["id"])
    summary = summarize(records)
    out.mkdir(parents=True)
    (out / "metadata.json").write_text(
        json.dumps(
            {
                "started_at": stamp,
                "agent_model": settings.agent_model,
                "judge_model": None if args.no_judge else args.judge_model,
                "cases": len(cases),
                "concurrency": args.concurrency,
                "dataset_sha256": sha256(dataset),
                "agent_prompt_sha256": sha256(AGENT_SYSTEM),
                "judge_prompt_sha256": sha256(JUDGE_SYSTEM),
            }
            | ({"original": original_meta} if original_meta else {}),
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    with (out / "results.jsonl").open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    (out / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    outcomes = summary["outcomes"]
    print(
        f"\n에이전트 승 {outcomes['agent']} · 대조 목록 승 {outcomes['baseline']} · "
        f"비김 {outcomes['tie']} · 같은 목록 {outcomes['same']} · 빈 추천 {outcomes['empty']} "
        f"(오류 {summary['errors']})"
    )
    print(
        f"  승부가 난 문항 중 에이전트 승률 {summary['agent_win_rate']}, "
        f"목록이 달랐던 비율 {summary['changed_rate']}, 겹침 평균 {summary['overlap_mean']}"
    )
    for name, counts in summary["by_family"].items():
        print(f"  {name:10} {counts}")
    if (versus := summary.get("original")) is not None:
        outcomes = versus["outcomes"]
        print(
            f"실제 원본과 비교: 에이전트 승 {outcomes['agent']} · 원본 승 {outcomes['original']} · "
            f"비김 {outcomes['tie']} · 같은 목록 {outcomes['same']} · "
            f"원본 빈 추천 {outcomes['original_empty']} · 에이전트 빈 추천 {outcomes['empty']} "
            f"(오류 {versus['errors']})"
        )
        print(f"  승부가 난 문항 중 에이전트 승률 {versus['agent_win_rate']}")
    print(f"기록: {out}")


if __name__ == "__main__":
    asyncio.run(main())
