"""bench.py가 남긴 두 기록을 마크다운으로 바꾼다.

`--table`은 루트 README에 붙일 요약 표만, 기본은 REPORT.md 본문(요약 표 + 질문별 상세와
타임라인)을 낸다. 관찰·해석은 사람이 REPORT.md에 덧붙이므로 이 스크립트가 파일을 덮어쓰지 않는다.

    .venv/bin/python evals/agent_questions/report.py runs/2026-09-17/{agent,baseline}.json
    .venv/bin/python evals/agent_questions/report.py --table runs/2026-09-17/{agent,baseline}.json
"""

import argparse
import json
from pathlib import Path

TOOL_STAGES = ("게임 검색", "가격", "하드웨어", "리뷰 점수", "리뷰 요약")
AGENT_STAGE = "에이전트 추론"


def tool_calls(record: dict) -> list[str]:
    """LLM이 부른 Tool 단계를 순서대로. 추론이 끝난 뒤의 단계는 러너가 부른 것이라 뺀다.

    러너는 추천이 확정된 뒤 리뷰 요약(미조회분)을 직접 부른다. 이를 섞으면 에이전트가 고른 도구가
    아닌 것까지 "에이전트가 부른 Tool"로 읽힌다.
    """
    calls = []
    for event in record.get("events", []):
        if event["stage"] == AGENT_STAGE and event["status"] != "started":
            break
        if event["status"] == "started" and event["stage"] in TOOL_STAGES:
            calls.append(event["stage"])
    return calls


def cell(record: dict) -> str:
    if "error" in record:
        return "미측정"
    return f"{record['seconds']}초 · {len(record.get('games', []))}개"


def print_table(pairs: list[tuple[dict, dict]]) -> None:
    print("| 질문 유형 | 원본 (고정 파이프라인) | 에이전트 | 에이전트가 부른 Tool (순서) |")
    print("| --- | --- | --- | --- |")
    for before, after in pairs:
        order = " → ".join(tool_calls(after)) or "-"
        print(f"| {after['kind']} | {cell(before)} | {cell(after)} | {order} |")


def print_details(pairs: list[tuple[dict, dict]]) -> None:
    for before, after in pairs:
        print(f"\n### {after['kind']}\n")
        print(f"> {after['question']}\n")
        for label, record in (("원본", before), ("에이전트", after)):
            if "error" in record:
                print(f"- **{label}**: 미측정 — {record['error']}")
                continue
            names = ", ".join(game["name"] for game in record["games"]) or "추천 없음"
            print(f"- **{label}** ({record['seconds']}초, 추천 {len(record['games'])}개): {names}")
            print(f"  - 제외 {record['excluded_count']}개 · 경고 {len(record['warnings'])}건")
            for warning in record["warnings"]:
                print(f"    - {warning}")
        if after.get("events"):
            print("\n에이전트 타임라인:\n")
            print("```text")
            for event in after["events"]:
                detail = f" · {event['detail']}" if event["detail"] else ""
                print(f"{event['t']:>6.2f}s  {event['stage']:<9} {event['status']}{detail}")
            print("```")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("agent", type=Path, help="에이전트 기록 JSON")
    parser.add_argument("baseline", type=Path, help="원본 기록 JSON")
    parser.add_argument("--table", action="store_true", help="요약 표만 낸다")
    parser.add_argument("--details", action="store_true", help="질문별 상세만 낸다")
    args = parser.parse_args()

    agent = json.loads(args.agent.read_text(encoding="utf-8"))
    baseline = json.loads(args.baseline.read_text(encoding="utf-8"))
    pairs = list(zip(baseline["records"], agent["records"], strict=True))

    if not args.details:
        print_table(pairs)
    if not args.table:
        if not args.details:
            print("\n## 질문별 상세")
        print_details(pairs)


if __name__ == "__main__":
    main()
