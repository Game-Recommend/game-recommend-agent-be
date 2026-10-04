"""원본 고정 파이프라인으로 취향 적합도 문항을 실행해 추천 목록을 남긴다.

`run_eval.py --original`이 이 기록을 읽어 에이전트의 목록과 1:1로 비교한다. 대조 목록은 고정
파이프라인의 선택 규칙을 같은 후보에 적용한 것이고, 이 기록은 원본 저장소 `game-recommend-be`를
실제로 돌린 결과다.

실행은 **원본 저장소의 venv로, 원본 저장소 루트를 현재 디렉터리로** 한다. `.env`를 현재 디렉터리에서
읽고, `app` 패키지는 원본 venv에 editable로 설치된 것을 쓴다. 원본 저장소는 고치지 않는다.

    cd ../game-recommend-be && .venv/bin/python \\
      ../game-recommend-agent-be/evals/relevance/run_original.py --limit 1   # 먼저 작게 확인한다
    cd ../game-recommend-be && .venv/bin/python \\
      ../game-recommend-agent-be/evals/relevance/run_original.py             # 40문항, 동시성 2

`app`이 원본의 것으로 풀리므로 이 저장소의 모듈은 import하지 않는다. 기록은 `score.parse_original`이
읽는다. **실제 외부 API와 LLM을 부른다.** 40문항에 약 $0.24, 5분 안팎이다. CI에서는 돌리지 않는다.
"""

import argparse
import asyncio
import hashlib
import json
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

EVAL_DIR = Path(__file__).resolve().parent


def to_record(response) -> dict:
    """원본 응답에서 비교에 쓰는 값만 남긴다. 심판에게 보여 줄 후보 정보와 원화 가격이다."""
    return {
        "conditions": response.conditions.model_dump(
            mode="json", exclude_none=True, exclude_defaults=True
        ),
        "original": [result.game.name for result in response.games],
        "games": [
            {
                "game": result.game.model_dump(mode="json"),
                "amount_krw": result.price.quote.amount_krw if result.price.quote else None,
            }
            for result in response.games
        ],
    }


async def run_one(recommender, item: dict) -> dict:
    record = dict(item)
    # 원본의 단계 detail(`후보 30개`, `통과 25개 중 5개 선택, 제외 5개`)로 빈 추천의 원인을 가른다
    details: dict[str, str] = {}
    failed: list[str] = []

    def progress(stage: str, status: str, detail: str | None = None) -> None:
        if status == "failed":
            failed.append(stage)
        elif status == "completed" and detail:
            details[stage] = detail

    started = time.perf_counter()
    try:
        response = await recommender.run(item["question"], progress)
    except Exception as exc:  # 한 문항의 실패로 멈추지 않는다. 비교에서는 오류로 뺀다
        record["error"] = f"{type(exc).__name__}: {exc}"
    else:
        record |= to_record(response)
    record["seconds"] = round(time.perf_counter() - started, 2)
    record["details"] = details
    record["failed_stages"] = failed
    return record


def git(*args: str) -> str:
    return subprocess.run(["git", *args], capture_output=True, text=True).stdout.strip()


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--limit", type=int, help="앞에서 N문항만 실행한다")
    parser.add_argument("--ids", nargs="+", help="지정한 문항만 실행한다 (예: R033 R038)")
    parser.add_argument("--concurrency", type=int, default=2)
    parser.add_argument("--out", type=Path, help="기본값: runs/original/<UTC timestamp>/")
    args = parser.parse_args()

    # 원본 venv의 editable 설치는 저장소를 옮기기 전 경로를 가리킨다.
    # 현재 디렉터리(원본 루트)의 app을 쓴다
    sys.path.insert(0, str(Path.cwd()))
    from app.assembly import assemble, missing_settings
    from app.config import get_settings

    settings = get_settings()
    dataset = (EVAL_DIR / "dataset.json").read_text(encoding="utf-8")
    cases = json.loads(dataset)
    if args.ids:
        cases = [case for case in cases if case["id"] in set(args.ids)]
    if args.limit:
        cases = cases[: args.limit]
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    out = args.out or EVAL_DIR / "runs" / "original" / stamp
    if out.exists():
        raise SystemExit(f"이미 있는 디렉터리다: {out}")

    assembled = assemble()
    if assembled is None:
        raise SystemExit(f"필수 설정이 비어 있습니다: {', '.join(missing_settings(settings))}")
    semaphore = asyncio.Semaphore(args.concurrency)
    done = 0
    print(f"원본 실행: 문항 {len(cases)}개, 동시성 {args.concurrency}")

    async def one(item: dict) -> dict:
        nonlocal done
        async with semaphore:
            record = await run_one(assembled.recommender, item)
            done += 1
            status = record.get("error") or f"{len(record['original'])}개 추천"
            progress = f"{done}/{len(cases)} {item['id']} {record['seconds']}초"
            print(f"  {progress} · {status}", flush=True)
            return record

    try:
        records = await asyncio.gather(*(one(item) for item in cases))
    finally:
        await assembled.aclose()

    records = sorted(records, key=lambda record: record["id"])
    out.mkdir(parents=True)
    (out / "metadata.json").write_text(
        json.dumps(
            {
                "started_at": stamp,
                "repository": Path.cwd().name,
                "commit": git("rev-parse", "HEAD"),
                # 원본 앱 코드에 커밋하지 않은 수정이 있었는지
                "app_dirty": bool(git("status", "--porcelain", "--", "app")),
                "model": settings.openai_model,
                "cases": len(cases),
                "concurrency": args.concurrency,
                "dataset_sha256": hashlib.sha256(dataset.encode("utf-8")).hexdigest(),
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    with (out / "results.jsonl").open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")

    errors = sum(1 for record in records if record.get("error"))
    empty = sum(1 for record in records if not record.get("error") and not record["original"])
    print(f"\n추천 목록 {len(records) - errors - empty} · 빈 추천 {empty} · 오류 {errors}")
    print(f"기록: {out}")


if __name__ == "__main__":
    asyncio.run(main())
