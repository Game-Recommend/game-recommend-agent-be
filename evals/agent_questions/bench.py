"""루트 README의 예상 질문 5개를 실제 키로 실행해 단계 순서·횟수·지연·답변을 기록한다.

이 저장소(에이전트)와 원본 `game-recommend-be`(고정 파이프라인) 모두 `assemble()` →
`recommender.run(question, progress)` 계약이 같아 같은 스크립트로 잰다.

실행은 **대상 저장소의 venv로, 그 저장소 루트를 현재 디렉터리로** 한다. `.env`를 현재 디렉터리에서
읽고, `app` 패키지는 각 venv에 editable로 설치된 것을 쓴다.

    # 이 저장소 (에이전트)
    .venv/bin/python evals/agent_questions/bench.py --label agent

    # 원본 저장소 (고정 파이프라인). 질문은 이 저장소 README에서 읽는다
    cd ../game-recommend-be && .venv/bin/python \\
      ../game-recommend-agent-be/evals/agent_questions/bench.py --label baseline

실제 외부 API와 LLM을 부르므로 CI에서는 돌리지 않는다. 질문 하나에 20~40초, 비용이 든다.
"""

import argparse
import asyncio
import json
import re
import time
from collections import Counter
from datetime import date
from pathlib import Path

from app.assembly import assemble, missing_settings
from app.config import get_settings

EVAL_DIR = Path(__file__).resolve().parent
REPO_ROOT = EVAL_DIR.parents[1]
LABELS = {"agent": "에이전트", "baseline": "원본"}


def load_questions(path: Path) -> list[dict]:
    """README '## 예상 질문' 절의 불릿에서 유형과 질문을 뽑는다."""
    body = path.read_text(encoding="utf-8").split("## 예상 질문", 1)[1].split("\n## ", 1)[0]
    found = re.findall(r'^- \*\*(.+?)\*\*:\s*"(.+?)"\s*$', body, flags=re.MULTILINE)
    return [{"kind": kind, "question": question} for kind, question in found]


async def run_one(recommender, item: dict) -> dict:
    """질문 하나를 실행하고 진행 이벤트를 시각과 함께 남긴다."""
    events: list[dict] = []
    started = time.perf_counter()

    def progress(stage: str, status: str, detail: str | None = None) -> None:
        events.append(
            {
                "t": round(time.perf_counter() - started, 2),
                "stage": stage,
                "status": status,
                "detail": detail,
            }
        )

    record: dict = {"kind": item["kind"], "question": item["question"]}
    try:
        response = await recommender.run(item["question"], progress)
    except Exception as exc:  # 기록이 목적이므로 한 질문의 실패로 멈추지 않는다
        record["error"] = f"{type(exc).__name__}: {exc}"
    else:
        record["answer"] = response.answer
        record["games"] = [
            {
                "name": game.game.name,
                "price_krw": game.price.quote.amount_krw if game.price.quote else None,
                "price_status": game.price.check.status,
                "hardware_status": game.hardware.check.status,
                "review": game.review.summary if game.review else None,
            }
            for game in response.games
        ]
        record["excluded_count"] = len(response.excluded_games)
        record["warnings"] = response.warnings
        record["conditions"] = response.conditions.model_dump(exclude_none=True)
    record["seconds"] = round(time.perf_counter() - started, 2)
    record["events"] = events
    starts = [event["stage"] for event in events if event["status"] == "started"]
    record["stage_order"] = starts
    record["stage_counts"] = dict(Counter(starts))
    record["failed_stages"] = [e["stage"] for e in events if e["status"] == "failed"]
    return record


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--label", choices=sorted(LABELS), required=True)
    parser.add_argument("--out", type=Path, help="기본값: runs/<오늘 날짜>/<label>.json")
    parser.add_argument("--questions", type=Path, default=REPO_ROOT / "README.md")
    args = parser.parse_args()

    display = LABELS[args.label]
    out = args.out or EVAL_DIR / "runs" / date.today().isoformat() / f"{args.label}.json"

    assembled = assemble()
    if assembled is None:
        missing = ", ".join(missing_settings(get_settings()))
        raise SystemExit(f"필수 설정이 비어 있습니다: {missing}")

    questions = load_questions(args.questions)
    print(f"[{display}] 질문 {len(questions)}개")
    records = []
    try:
        for index, item in enumerate(questions, start=1):
            print(f"  {index}/{len(questions)} {item['kind']} ...", flush=True)
            record = await run_one(assembled.recommender, item)
            status = record.get("error") or f"{len(record.get('games', []))}개 추천"
            print(f"    {record['seconds']}초 · {status}", flush=True)
            records.append(record)
    finally:
        await assembled.aclose()

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(
            {"label": display, "model": get_settings().agent_model, "records": records},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"[{display}] 기록: {out}")


if __name__ == "__main__":
    asyncio.run(main())
