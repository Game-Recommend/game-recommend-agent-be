"""지연 분해의 순수 로직. 저장된 기록의 단계 타임라인만 쓴다."""

import pytest

from evals.agent_e2e.latency_breakdown import breakdown, covered, summarize


def ev(t, stage, status):
    return {"t": t, "stage": stage, "status": status, "detail": None}


def timeline(*rows):
    """(단계, 시작, 끝) 목록을 시각순 이벤트로 바꾼다."""
    events = [ev(start, stage, "started") for stage, start, _ in rows]
    events += [ev(stop, stage, "completed") for stage, _, stop in rows]
    return sorted(events, key=lambda event: (event["t"], event["status"] != "started"))


def test_covered_counts_overlap_once():
    assert covered([(1.0, 3.0), (2.0, 4.0), (6.0, 7.0)]) == 4.0
    assert covered([(1.0, 5.0), (2.0, 3.0)]) == 4.0
    assert covered([]) == 0.0


def test_baseline_llm_time_is_parsing_plus_final_answer():
    stages = timeline(
        ("질문 분해", 0.0, 1.0),
        ("게임 검색", 1.0, 3.0),
        ("가격", 3.0, 4.0),
        ("리뷰 요약", 4.0, 10.0),
        ("최종 답변 생성", 10.0, 12.5),
    )
    assert breakdown(stages) == pytest.approx({"llm": 3.5, "tools": 9.0, "reviews": 6.0})


def test_agent_llm_time_is_the_reasoning_span_without_tools():
    # 가격·사양은 같은 턴에 병렬로 돈다. 추론이 끝난 뒤의 리뷰 요약은 러너가 부른 것이다
    stages = timeline(
        ("질문 분해", 0.0, 1.0),
        ("에이전트 추론", 1.0, 9.0),
        ("게임 검색", 2.0, 4.0),
        ("가격", 5.0, 6.0),
        ("하드웨어", 5.0, 6.5),
        ("리뷰 요약", 9.0, 11.0),
    )
    # 추론 8초 중 Tool이 돈 시간은 2 + 1.5초다
    assert breakdown(stages) == pytest.approx({"llm": 5.5, "tools": 5.5, "reviews": 2.0})


def test_failed_tool_stage_still_counts_as_tool_time():
    stages = [
        ev(0.0, "질문 분해", "started"),
        ev(1.0, "질문 분해", "completed"),
        ev(1.0, "에이전트 추론", "started"),
        ev(2.0, "리뷰 요약", "started"),
        ev(5.0, "리뷰 요약", "failed"),
        ev(6.0, "에이전트 추론", "completed"),
    ]
    assert breakdown(stages) == pytest.approx({"llm": 3.0, "tools": 3.0, "reviews": 3.0})


def test_summary_skips_errors_and_empty_recommendations():
    stages = timeline(("질문 분해", 0.0, 1.0), ("최종 답변 생성", 1.0, 2.0))
    records = [
        {"id": "E1", "seconds": 2.0, "recommended_count": 2, "stages": stages},
        {"id": "E2", "seconds": 1.0, "recommended_count": 0, "stages": stages},
        {"id": "E3", "seconds": 9.0, "error": "X: y"},
    ]
    assert summarize(records)["scored"] == 1
    assert summarize(records, with_games_only=False)["scored"] == 2
    assert summarize([])["llm_median"] is None
