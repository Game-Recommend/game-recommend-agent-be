"""저장된 실행 기록의 단계 타임라인으로 요청당 시간을 LLM 왕복과 Tool·I/O로 나눈다.

외부 API를 부르지 않는다. 전체 지연은 두 저장소의 구조를 비교하는 수치로 쓸 수 없다. 에이전트
저장소에만 있는 I/O 패치(리뷰 요약 병렬화 등)가 Tool 쪽 시간을 줄이기 때문이다. 구조가 만드는 차이는
LLM 왕복에 있으므로 둘을 나눠서 본다.

- LLM 왕복
  - 원본(고정 파이프라인): `질문 분해` + `최종 답변 생성`
  - 에이전트: `질문 분해` + `에이전트 추론` 구간에서 Tool 단계가 돌지 않은 시간(Tool을 고르는 왕복)
- Tool·I/O: Tool 단계 구간의 합집합. 병렬로 돈 단계는 겹친 만큼 한 번만 센다.
  사양 판정과 리뷰 요약 안의 LLM 호출은 두 저장소 모두 Tool 단계 안에 있어 이쪽에 들어간다.

빈 추천은 Tool을 거의 돌리지 않고 끝나므로 기본으로 추천을 낸 문항만 본다.

    .venv/bin/python -m evals.agent_e2e.latency_breakdown evals/agent_e2e/runs/<UTC timestamp> [...]
"""

import argparse
import json
import statistics
from pathlib import Path

PARSE_STAGE = "질문 분해"
AGENT_STAGE = "에이전트 추론"
ANSWER_STAGE = "최종 답변 생성"
TOOL_STAGES = frozenset({"게임 검색", "가격", "하드웨어", "리뷰 점수", "리뷰 요약", "미디어"})

Span = tuple[float, float]


def spans(stages: list[dict]) -> dict[str, list[Span]]:
    """단계별 (시작, 끝) 목록. 같은 단계가 여러 번 나오면 시작한 순서대로 짝을 짓는다."""
    started: dict[str, list[float]] = {}
    found: dict[str, list[Span]] = {}
    for event in stages:
        stage = event["stage"]
        if event["status"] == "started":
            started.setdefault(stage, []).append(event["t"])
        elif started.get(stage):
            found.setdefault(stage, []).append((started[stage].pop(0), event["t"]))
    return found


def covered(intervals: list[Span]) -> float:
    """구간들의 합집합 길이. 겹친 부분은 한 번만 센다."""
    total, end = 0.0, None
    for start, stop in sorted(intervals):
        if end is None or start > end:
            total += stop - start
            end = stop
        elif stop > end:
            total += stop - end
            end = stop
    return total


def breakdown(stages: list[dict]) -> dict[str, float]:
    """기록 하나의 LLM 왕복·Tool 시간. `에이전트 추론` 단계가 있으면 에이전트 기록으로 본다."""
    found = spans(stages)
    tools = [span for stage in TOOL_STAGES for span in found.get(stage, [])]
    llm = sum(stop - start for start, stop in found.get(PARSE_STAGE, []))
    if AGENT_STAGE in found:
        begin, finish = found[AGENT_STAGE][0]
        inside = [
            (max(start, begin), min(stop, finish))
            for start, stop in tools
            if start < finish and stop > begin
        ]
        llm += (finish - begin) - covered(inside)
    else:
        llm += sum(stop - start for start, stop in found.get(ANSWER_STAGE, []))
    reviews = sum(stop - start for start, stop in found.get("리뷰 요약", []))
    return {"llm": llm, "tools": covered(tools), "reviews": reviews}


def summarize(records: list[dict], *, with_games_only: bool = True) -> dict:
    scored = [record for record in records if not record.get("error")]
    if with_games_only:
        scored = [record for record in scored if record.get("recommended_count")]
    parts = [breakdown(record["stages"]) for record in scored]

    def median(values: list[float]) -> float | None:
        return round(statistics.median(values), 2) if values else None

    return {
        "scored": len(scored),
        "total_median": median([record["seconds"] for record in scored]),
        "llm_median": median([part["llm"] for part in parts]),
        "tools_median": median([part["tools"] for part in parts]),
        "reviews_median": median([part["reviews"] for part in parts]),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("run_dirs", nargs="+", type=Path)
    parser.add_argument("--all", action="store_true", help="추천 0개로 끝난 문항도 넣는다")
    args = parser.parse_args()
    for run_dir in args.run_dirs:
        lines = (run_dir / "results.jsonl").read_text(encoding="utf-8").splitlines()
        summary = summarize(
            [json.loads(line) for line in lines if line.strip()], with_games_only=not args.all
        )
        print(
            f"{run_dir.name}: {summary['scored']}문항 · 전체 {summary['total_median']}초 · "
            f"LLM 왕복 {summary['llm_median']}초 · Tool·I/O {summary['tools_median']}초"
            f"(그중 리뷰 요약 {summary['reviews_median']}초)"
        )


if __name__ == "__main__":
    main()
