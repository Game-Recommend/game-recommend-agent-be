"""저장된 실행 기록을 현재 채점 규칙으로 다시 채점한다. 외부 API·LLM을 부르지 않는다.

채점 규칙(score.py)이 바뀌면 이미 돌린 실행을 다시 돌릴 필요 없이 이 스크립트로 수치를 맞춘다.
`results.jsonl`에 답변 원문과 추천 게임 이름이 남아 있어 **답변 형식 축만** 다시 계산할 수 있다.
조건·궤적 축은 응답 전체가 필요하므로 기록된 판정을 그대로 쓴다.

원본 `results.jsonl`·`summary.json`은 건드리지 않고 같은 디렉터리에 `summary.rescored.json`을 쓴다.

    .venv/bin/python -m evals.agent_e2e.rescore evals/agent_e2e/runs/20260917T070118Z
"""

import argparse
import json
from pathlib import Path

from evals.agent_e2e.run_eval import summarize
from evals.agent_e2e.score import answer_format_problems

RULE = "answer_format: 추천 0개면 2~6문장, 아니면 3~6문장"


def rescore_record(record: dict) -> dict:
    """오류로 끝난 기록은 그대로 둔다."""
    if record.get("error"):
        return record
    problems = answer_format_problems(record["answer"], record["recommended"])
    return {
        **record,
        "answer_format_problems": problems,
        "answer_format_passed": not problems,
        "passed": record["constraints_passed"] and record["trajectory_passed"] and not problems,
    }


def rescore_run(run_dir: Path) -> dict:
    lines = (run_dir / "results.jsonl").read_text(encoding="utf-8").splitlines()
    records = [rescore_record(json.loads(line)) for line in lines if line.strip()]
    original = json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))
    summary = summarize(records)
    summary["rescored"] = {
        "rule": RULE,
        "original_passed": original["passed"],
        "original_answer_format": original["axes"]["answer_format"],
    }
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("run_dirs", nargs="+", type=Path)
    args = parser.parse_args()
    for run_dir in args.run_dirs:
        summary = rescore_run(run_dir)
        out = run_dir / "summary.rescored.json"
        out.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        before = summary["rescored"]
        print(
            f"{run_dir.name}: 통과 {before['original_passed']} → {summary['passed']}"
            f"/{summary['scored']}, 답변 형식 {before['original_answer_format']} → "
            f"{summary['axes']['answer_format']} ({out})"
        )


if __name__ == "__main__":
    main()
