"""질문 파서 평가 실행기. LangSmith 데이터셋에 올리고 실험을 돌린다.

저장소 루트에서 실행한다. `.env`의 `OPENAI_API_KEY`와 `LANGSMITH_API_KEY`를 읽는다.
LLM 호출은 문항 수만큼(210문항 = 210회)이며 gpt-4o-mini 기준 약 $0.05다(3회 반복은 약 $0.15).

    .venv/bin/python -m evals.parser_conditions.run_eval                 # 전체 210문항
    .venv/bin/python -m evals.parser_conditions.run_eval --limit 20      # 앞 20문항만
    .venv/bin/python -m evals.parser_conditions.run_eval --no-langsmith  # 로컬 기록만

LangSmith에 올리지 않아도 `runs/<UTC timestamp>/`에 같은 기록을 남긴다. 기존 디렉터리는
덮어쓰지 않는다. 정답은 모델 입력에 전달하지 않고, 별도 LLM 채점기도 쓰지 않는다.
"""

import argparse
import asyncio
import hashlib
import json
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

from langsmith import Client, aevaluate

from app.pipeline.query_processing.conditions import GameConditions
from app.pipeline.query_processing.llm_parser import LLMQueryParser
from app.pipeline.query_processing.prompts import QUERY_PARSER_SYSTEM
from evals.parser_conditions.score import score_case

EVAL_DIR = Path(__file__).resolve().parent
DATASET_NAME = "parser-conditions"


def load_dataset() -> list[dict]:
    return json.loads((EVAL_DIR / "dataset.json").read_text(encoding="utf-8"))


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sync_langsmith_dataset(client: Client, cases: list[dict]) -> str:
    """데이터셋을 LangSmith에 만들거나 문항을 최신으로 맞춘다.

    정답(`gold` 등)은 outputs가 아니라 metadata에 넣는다. 채점은 이 저장소의 score.py가 하고,
    LangSmith는 기록과 비교 화면만 담당한다.
    """
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
                "질문 파서(LLMQueryParser)가 자연어를 GameConditions로 바꾸는 계약 평가. "
                "정답 근거는 QUERY_PARSER_SYSTEM이다."
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

    # 정답을 고치면 LangSmith 쪽도 맞춰야 한다. 질문이나 정답이 달라진 문항만 갱신한다.
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
        wanted = {"case_id": item["id"], **item}
        if stored != wanted or example.inputs != {"question": item["question"]}:
            to_update.append((example, item))
    for example, item in to_update:
        client.update_example(
            example_id=example.id,
            inputs={"question": item["question"]},
            metadata={"case_id": item["id"], **item},
        )

    # 데이터셋에만 남은 문항은 사람이 지운다. 자동으로 지우면 과거 실험과 비교가 끊긴다.
    orphans = sorted(set(existing) - {item["id"] for item in cases})
    print(
        f"LangSmith 데이터셋 '{DATASET_NAME}': 문항 {len(cases)}개 "
        f"(신규 {len(to_create)}개, 갱신 {len(to_update)}개)"
    )
    if orphans:
        print(f"  데이터셋에만 남은 문항 {len(orphans)}개: {', '.join(orphans)}")
    return str(dataset.id)


def build_evaluators(by_id: dict[str, dict]):
    """축별 평가자. 점수는 score.py가 계산하고 여기서는 이름만 붙인다."""

    def evaluate_one(run, example) -> list[dict]:
        item = by_id[example.metadata["case_id"]]
        conditions = run.outputs.get("conditions")
        if conditions is None:
            return [
                {"key": "passed", "score": 0, "comment": f"파싱 실패: {run.outputs.get('error')}"}
            ]
        scored = score_case(item, GameConditions.model_validate(conditions))
        return [
            {
                "key": "passed",
                "score": int(scored["passed"]),
                "comment": "; ".join(
                    scored["field_problems"]
                    + scored["preference_problems"]
                    + scored["invariant_problems"]
                )
                or "통과",
            },
            {"key": "fields", "score": int(scored["fields_passed"])},
            {"key": "preferences", "score": int(scored["preferences_passed"])},
            {"key": "invariants", "score": int(scored["invariants_passed"])},
        ]

    return [evaluate_one]


def record_from_outputs(item: dict, outputs: dict | None) -> dict:
    """실행 결과 하나를 채점해 기록으로 만든다. LLM을 다시 부르지 않는다."""
    conditions = (outputs or {}).get("conditions")
    if conditions is None:
        record = {
            "id": item["id"],
            "family": item["family"],
            "passed": False,
            "error": (outputs or {}).get("error", "출력 없음"),
        }
    else:
        record = score_case(item, GameConditions.model_validate(conditions))
        record["actual"] = conditions
    record["question"] = item["question"]
    record["basis"] = item["basis"]
    return record


async def records_from_experiment(results, by_id: dict[str, dict]) -> list[dict]:
    """LangSmith 실험 결과를 그대로 채점한다. 문항당 LLM 호출은 1회로 끝난다."""
    records = []
    async for row in results:
        case_id = row["example"].metadata.get("case_id")
        item = by_id.get(case_id)
        if item is None:  # 데이터셋에는 있으나 이번 실행 대상이 아닌 문항
            continue
        records.append(record_from_outputs(item, row["run"].outputs))
    return records


async def run_local(cases: list[dict], concurrency: int) -> list[dict]:
    """LangSmith 없이 문항을 돌리고 채점한다."""
    parser = LLMQueryParser()
    semaphore = asyncio.Semaphore(concurrency)
    done = 0

    async def one(item: dict) -> dict:
        nonlocal done
        async with semaphore:
            try:
                conditions = await parser.parse(item["question"])
            except Exception as exc:
                outputs = {"conditions": None, "error": f"{type(exc).__name__}: {exc}"}
            else:
                outputs = {"conditions": conditions.model_dump()}
            record = record_from_outputs(item, outputs)
            done += 1
            if done % 20 == 0:
                print(f"  {done}/{len(cases)} ...", flush=True)
            return record

    return await asyncio.gather(*(one(item) for item in cases))


def summarize(records: list[dict], repeats: int) -> dict:
    """문항별로 반복을 묶어 집계한다.

    문항이 통과했다는 것은 모든 반복이 통과했다는 뜻이다(엄격). 반복 사이에 결과가 갈린
    문항은 `flaky`로 따로 세어, 프롬프트를 고쳐 해결할 버그와 모델 흔들림을 구분한다.
    """
    by_case: dict[str, list[dict]] = {}
    for record in records:
        by_case.setdefault(record["id"], []).append(record)

    cases_summary: dict[str, dict] = {}
    families: dict[str, dict] = {}
    for case_id, runs in sorted(by_case.items()):
        passed_runs = sum(1 for run in runs if run.get("passed"))
        stable_pass = passed_runs == len(runs)
        flaky = 0 < passed_runs < len(runs)
        family = runs[0]["family"]
        cases_summary[case_id] = {
            "family": family,
            "runs": len(runs),
            "passed_runs": passed_runs,
            "stable_pass": stable_pass,
            "flaky": flaky,
            "errors": sum(1 for run in runs if run.get("error")),
        }
        bucket = families.setdefault(
            family,
            {"cases": 0, "stable_pass": 0, "flaky": 0, "stable_fail_ids": [], "flaky_ids": []},
        )
        bucket["cases"] += 1
        if stable_pass:
            bucket["stable_pass"] += 1
        elif flaky:
            bucket["flaky"] += 1
            bucket["flaky_ids"].append(case_id)
        else:
            bucket["stable_fail_ids"].append(case_id)

    total_cases = len(by_case)
    stable_pass = sum(1 for case in cases_summary.values() if case["stable_pass"])
    flaky = sum(1 for case in cases_summary.values() if case["flaky"])
    axes = Counter()
    for record in records:
        for axis in ("fields_passed", "preferences_passed", "invariants_passed"):
            if record.get(axis):
                axes[axis] += 1

    return {
        "repeats": repeats,
        "cases": total_cases,
        "case_runs": len(records),
        "stable_pass": stable_pass,
        "flaky": flaky,
        "stable_fail": total_cases - stable_pass - flaky,
        "accuracy_strict": round(stable_pass / total_cases, 4) if total_cases else 0.0,
        "accuracy_by_run": round(
            sum(1 for record in records if record.get("passed")) / len(records), 4
        )
        if records
        else 0.0,
        "errors": sum(1 for record in records if record.get("error")),
        "axes_by_run": {
            "fields": axes["fields_passed"],
            "preferences": axes["preferences_passed"],
            "invariants": axes["invariants_passed"],
        },
        "by_family": {
            name: {
                **bucket,
                "accuracy_strict": round(bucket["stable_pass"] / bucket["cases"], 4),
            }
            for name, bucket in sorted(families.items())
        },
        "flaky_cases": sorted(
            case_id for case_id, case in cases_summary.items() if case["flaky"]
        ),
        "stable_fail_cases": sorted(
            case_id
            for case_id, case in cases_summary.items()
            if not case["stable_pass"] and not case["flaky"]
        ),
    }


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, help="앞에서 N문항만 실행한다")
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument(
        "--repeats", type=int, default=1, help="문항당 반복 횟수. 모델 흔들림과 버그를 구분한다"
    )
    parser.add_argument("--no-langsmith", action="store_true", help="로컬 기록만 남긴다")
    parser.add_argument("--out", type=Path, help="기본값: runs/<UTC timestamp>/")
    args = parser.parse_args()

    cases = load_dataset()
    if args.limit:
        cases = cases[: args.limit]
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    out = args.out or EVAL_DIR / "runs" / stamp
    if out.exists():
        raise SystemExit(f"이미 있는 디렉터리다: {out}")

    experiment = None
    if not args.no_langsmith:
        client = Client()
        sync_langsmith_dataset(client, load_dataset())
        by_id = {item["id"]: item for item in cases}
        target_parser = LLMQueryParser()

        async def target(inputs: dict) -> dict:
            try:
                conditions = await target_parser.parse(inputs["question"])
            except Exception as exc:
                return {"conditions": None, "error": f"{type(exc).__name__}: {exc}"}
            return {"conditions": conditions.model_dump()}

        print(f"LangSmith 실험 시작: 문항 {len(cases)}개, 동시성 {args.concurrency}")
        # list_examples의 순서는 dataset.json 순서와 다르다. --limit은 case_id로 고른다.
        data = DATASET_NAME
        if args.limit:
            wanted = {item["id"] for item in cases}
            data = [
                example
                for example in client.list_examples(dataset_name=DATASET_NAME)
                if example.metadata and example.metadata.get("case_id") in wanted
            ]
            if len(data) != len(wanted):
                raise SystemExit(
                    f"데이터셋에서 찾은 문항이 {len(data)}개로 요청({len(wanted)}개)과 다르다"
                )
        results = await aevaluate(
            target,
            data=data,
            evaluators=build_evaluators(by_id),
            experiment_prefix="parser-conditions",
            max_concurrency=args.concurrency,
            num_repetitions=args.repeats,
            metadata={"model": "gpt-4o-mini", "prompt_sha256": sha256(QUERY_PARSER_SYSTEM)},
        )
        experiment = results.experiment_name
        print(f"LangSmith 실험: {experiment}")
        records = await records_from_experiment(results, by_id)
    else:
        print(
            f"로컬 실행: 문항 {len(cases)}개 x {args.repeats}회, 동시성 {args.concurrency}"
        )
        records = []
        for _ in range(args.repeats):
            records += await run_local(cases, args.concurrency)

    missing = {item["id"] for item in cases} - {record["id"] for record in records}
    if missing:
        raise SystemExit(f"결과가 빠진 문항이 있다: {sorted(missing)}")
    records.sort(key=lambda record: record["id"])
    summary = summarize(records, args.repeats)

    out.mkdir(parents=True)
    (out / "metadata.json").write_text(
        json.dumps(
            {
                "started_at": stamp,
                "model": "gpt-4o-mini",
                "cases": len(cases),
                "repeats": args.repeats,
                "concurrency": args.concurrency,
                "dataset_sha256": sha256((EVAL_DIR / "dataset.json").read_text(encoding="utf-8")),
                "prompt_sha256": sha256(QUERY_PARSER_SYSTEM),
                "langsmith_experiment": experiment,
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
        f"\n문항 {summary['cases']}개 x {summary['repeats']}회 = {summary['case_runs']}회 실행"
    )
    print(
        f"전 회차 통과 {summary['stable_pass']}/{summary['cases']} "
        f"= {summary['accuracy_strict']:.1%}  "
        f"(흔들림 {summary['flaky']}개, 전 회차 실패 {summary['stable_fail']}개)"
    )
    for name, bucket in summary["by_family"].items():
        print(
            f"  {name:9} {bucket['stable_pass']:3}/{bucket['cases']:3} "
            f"= {bucket['accuracy_strict']:6.1%}  흔들림 {bucket['flaky']}"
        )
    if summary["stable_fail_cases"]:
        print(f"  전 회차 실패: {', '.join(summary['stable_fail_cases'])}")
    if summary["flaky_cases"]:
        print(f"  흔들림: {', '.join(summary['flaky_cases'])}")
    print(f"기록: {out}")


if __name__ == "__main__":
    asyncio.run(main())
