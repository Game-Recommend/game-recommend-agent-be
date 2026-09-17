"""에이전트 엔드투엔드 평가 실행기. LangSmith 데이터셋에 올리고 실험을 돌린다.

**실제 외부 API와 LLM을 부른다.** 질문 하나에 약 20초와 LLM 비용 $0.006이 들고, IGDB·Steam
응답이 바뀌면 추천도 바뀐다. CI에서는 돌리지 않는다.

저장소 루트에서 실행한다. `.env`의 키를 읽는다.

    .venv/bin/python -m evals.agent_e2e.run_eval --limit 5    # 먼저 작게 확인한다
    .venv/bin/python -m evals.agent_e2e.run_eval              # 100문항, 약 $0.7 / 10분
    .venv/bin/python -m evals.agent_e2e.run_eval --no-judge   # LLM 심판 생략

동시성은 외부 API(IGDB·Steam) 사정을 고려해 기본 4다. 올리면 빨라지지만 레이트리밋에 걸릴 수
있고, 그 실패는 에이전트 품질이 아니라 실행 환경 문제로 기록된다.
"""

import argparse
import asyncio
import hashlib
import json
import time
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

from langsmith import Client

from app.agent.prompts import AGENT_SYSTEM
from app.assembly import assemble, missing_settings
from app.config import get_settings
from evals.agent_e2e.judge import AnswerJudge
from evals.agent_e2e.score import score_case

EVAL_DIR = Path(__file__).resolve().parent
DATASET_NAME = "agent-e2e"


def load_dataset() -> list[dict]:
    return json.loads((EVAL_DIR / "dataset.json").read_text(encoding="utf-8"))


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sync_langsmith_dataset(client: Client, cases: list[dict]) -> None:
    """데이터셋을 LangSmith에 만들거나 문항을 최신으로 맞춘다."""
    if client.has_dataset(dataset_name=DATASET_NAME):
        dataset = client.read_dataset(dataset_name=DATASET_NAME)
        existing = {
            example.metadata.get("case_id"): example
            for example in client.list_examples(dataset_id=dataset.id)
            if example.metadata
        }
    else:
        dataset = client.create_dataset(
            dataset_name=DATASET_NAME,
            description=(
                "AgentRecommender 엔드투엔드 평가. 정답 추천 목록은 없고, 응답만 보고 "
                "기계로 검증할 수 있는 필수 조건을 기대값으로 둔다."
            ),
        )
        existing = {}

    to_create = [item for item in cases if item["id"] not in existing]
    if to_create:
        client.create_examples(
            dataset_id=dataset.id,
            inputs=[{"question": item["question"]} for item in to_create],
            metadata=[{"case_id": item["id"], **item} for item in to_create],
        )
    to_update = []
    for item in cases:
        example = existing.get(item["id"])
        if example is None:
            continue
        stored = {
            key: value
            for key, value in (example.metadata or {}).items()
            if key != "dataset_split"
        }
        if stored != {"case_id": item["id"], **item} or example.inputs != {
            "question": item["question"]
        }:
            to_update.append((example, item))
    for example, item in to_update:
        client.update_example(
            example_id=example.id,
            inputs={"question": item["question"]},
            metadata={"case_id": item["id"], **item},
        )
    print(
        f"LangSmith 데이터셋 '{DATASET_NAME}': 문항 {len(cases)}개 "
        f"(신규 {len(to_create)}개, 갱신 {len(to_update)}개)"
    )


async def run_one(recommender, item: dict, judge: AnswerJudge | None) -> dict:
    """질문 하나를 실행하고 채점한다. 진행 이벤트를 단계 기록으로 남긴다."""
    stages: list[dict] = []
    started = time.perf_counter()

    def progress(stage: str, status: str, detail: str | None = None) -> None:
        stages.append(
            {
                "t": round(time.perf_counter() - started, 2),
                "stage": stage,
                "status": status,
                "detail": detail,
            }
        )

    try:
        response = await recommender.run(item["question"], progress)
    except Exception as exc:
        return {
            "id": item["id"],
            "family": item["family"],
            "question": item["question"],
            "passed": False,
            "error": f"{type(exc).__name__}: {exc}",
            "seconds": round(time.perf_counter() - started, 2),
            "stages": stages,
        }

    record = score_case(item, response, stages)
    record["question"] = item["question"]
    record["why"] = item["why"]
    record["seconds"] = round(time.perf_counter() - started, 2)
    record["stages"] = stages
    record["answer"] = response.answer
    record["conditions"] = response.conditions.model_dump(exclude_none=True)

    if judge is not None:
        try:
            verdict = await judge.judge(item["question"], response)
        except Exception as exc:
            record["judge_error"] = f"{type(exc).__name__}: {exc}"
        else:
            record["judge"] = verdict.model_dump()
    return record


def summarize(records: list[dict]) -> dict:
    """축별·계열별 집계.

    **오류로 끝난 문항은 정확도 분모에서 뺀다.** 네트워크·레이트리밋 실패는 에이전트 품질이
    아니라 실행 환경 문제이므로 `errors`로 따로 센다(evals/price_hardware와 같은 관례).
    LLM 심판 점수도 자동 정확도에 섞지 않고 따로 낸다.
    """
    families: dict[str, dict] = {}
    for record in records:
        bucket = families.setdefault(
            record["family"],
            {"attempted": 0, "scored": 0, "passed": 0, "errors": 0, "failed_ids": []},
        )
        bucket["attempted"] += 1
        if record.get("error"):
            bucket["errors"] += 1
            continue
        bucket["scored"] += 1
        if record.get("passed"):
            bucket["passed"] += 1
        else:
            bucket["failed_ids"].append(record["id"])

    scored_records = [record for record in records if not record.get("error")]
    axes = Counter()
    for record in scored_records:
        for axis in ("constraints_passed", "trajectory_passed", "answer_format_passed"):
            if record.get(axis):
                axes[axis] += 1

    scored = [record for record in records if record.get("judge")]
    judge_summary = None
    if scored:
        grounded = [record["judge"]["grounded_score"] for record in scored]
        linked = [record["judge"]["linked_score"] for record in scored]
        judge_summary = {
            "judged": len(scored),
            "errors": sum(1 for record in records if record.get("judge_error")),
            "grounded_mean": round(sum(grounded) / len(grounded), 2),
            "linked_mean": round(sum(linked) / len(linked), 2),
            "grounded_distribution": dict(sorted(Counter(grounded).items())),
            "linked_distribution": dict(sorted(Counter(linked).items())),
            "grounded_below_4": sorted(
                record["id"] for record in scored if record["judge"]["grounded_score"] < 4
            ),
            "linked_below_4": sorted(
                record["id"] for record in scored if record["judge"]["linked_score"] < 4
            ),
        }

    seconds = sorted(record["seconds"] for record in records)
    attempted = len(records)
    scored = len(scored_records)
    passed = sum(1 for record in scored_records if record.get("passed"))
    recommended = [
        record["recommended_count"] for record in scored_records if "recommended_count" in record
    ]
    return {
        "attempted": attempted,
        "scored": scored,
        "passed": passed,
        # 분모는 오류 없이 끝난 문항 수다
        "accuracy": round(passed / scored, 4) if scored else 0.0,
        "errors": attempted - scored,
        "error_kinds": dict(
            Counter(record["error"].split(":")[0] for record in records if record.get("error"))
        ),
        "axes": {
            "constraints": axes["constraints_passed"],
            "trajectory": axes["trajectory_passed"],
            "answer_format": axes["answer_format_passed"],
        },
        "empty_recommendations": sum(1 for count in recommended if count == 0),
        "latency_seconds": {
            "median": seconds[len(seconds) // 2] if seconds else None,
            "max": seconds[-1] if seconds else None,
        },
        "judge": judge_summary,
        "by_family": {
            name: {
                **bucket,
                "accuracy": round(bucket["passed"] / bucket["scored"], 4)
                if bucket["scored"]
                else None,
            }
            for name, bucket in sorted(families.items())
        },
    }


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, help="앞에서 N문항만 실행한다")
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument("--no-judge", action="store_true", help="LLM 심판을 생략한다")
    parser.add_argument("--no-langsmith", action="store_true", help="데이터셋 동기화를 생략한다")
    parser.add_argument("--out", type=Path, help="기본값: runs/<UTC timestamp>/")
    args = parser.parse_args()

    settings = get_settings()
    cases = load_dataset()
    if args.limit:
        cases = cases[: args.limit]
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    out = args.out or EVAL_DIR / "runs" / stamp
    if out.exists():
        raise SystemExit(f"이미 있는 디렉터리다: {out}")

    if not args.no_langsmith:
        sync_langsmith_dataset(Client(), load_dataset())

    assembled = assemble()
    if assembled is None:
        raise SystemExit(f"필수 설정이 비어 있습니다: {', '.join(missing_settings(settings))}")

    judge = None if args.no_judge else AnswerJudge(settings.openai_api_key)
    semaphore = asyncio.Semaphore(args.concurrency)
    done = 0
    print(f"실행: 문항 {len(cases)}개, 동시성 {args.concurrency}, 심판 {not args.no_judge}")

    async def one(item: dict) -> dict:
        nonlocal done
        async with semaphore:
            record = await run_one(assembled.recommender, item, judge)
            done += 1
            status = record.get("error") or (
                f"추천 {record.get('recommended_count', 0)}개"
                + ("" if record.get("passed") else " · 위반")
            )
            print(
                f"  {done}/{len(cases)} {item['id']} {record['seconds']}초 · {status}",
                flush=True,
            )
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
                "openai_model": settings.openai_model,
                "judge_model": None if args.no_judge else "gpt-4o-mini",
                "cases": len(cases),
                "concurrency": args.concurrency,
                "dataset_sha256": sha256((EVAL_DIR / "dataset.json").read_text(encoding="utf-8")),
                "agent_prompt_sha256": sha256(AGENT_SYSTEM),
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
    (out / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    print(
        f"\n통과 {summary['passed']}/{summary['scored']} = {summary['accuracy']:.1%}"
        f"  (문항 {summary['attempted']}개 중 오류 {summary['errors']}개는 분모에서 제외)"
    )
    if summary["errors"]:
        kinds = ", ".join(f"{kind} {count}건" for kind, count in summary["error_kinds"].items())
        print(f"  오류 종류: {kinds}")
        print("  오류가 많으면 --concurrency를 낮춰 다시 돌린다(외부 API 레이트리밋·네트워크)")
    print(
        f"  축별: 조건 {summary['axes']['constraints']}, 궤적 {summary['axes']['trajectory']}, "
        f"답변 형식 {summary['axes']['answer_format']} (각 /{summary['scored']})"
    )
    print(
        f"  추천 0개 {summary['empty_recommendations']}건, "
        f"지연 중앙값 {summary['latency_seconds']['median']}초"
    )
    if summary["judge"]:
        judge_summary = summary["judge"]
        print(
            f"  LLM 심판: 근거 {judge_summary['grounded_mean']}/5, "
            f"조건 연결 {judge_summary['linked_mean']}/5 (심판 오류 {judge_summary['errors']}건)"
        )
    for name, bucket in summary["by_family"].items():
        accuracy = "     -" if bucket["accuracy"] is None else f"{bucket['accuracy']:6.1%}"
        errors = f"  오류 {bucket['errors']}" if bucket["errors"] else ""
        print(f"  {name:9} {bucket['passed']:3}/{bucket['scored']:3} = {accuracy}{errors}")
    print(f"기록: {out}")


if __name__ == "__main__":
    asyncio.run(main())
