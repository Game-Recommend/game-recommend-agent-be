"""취향 적합도 평가의 순수 로직 검사. API를 부르지 않는다."""

import asyncio
import json
from pathlib import Path

from app.pipeline.query_processing.conditions import GameConditions
from app.schemas.common import ConditionCheck
from app.schemas.game import GameCandidate
from app.schemas.hardware import HardwareResult
from app.schemas.price import PriceQuote, PriceResult
from app.schemas.recommendation import EvaluatedGame, RecommendationResponse
from evals.relevance.judge import PairVerdict, describe_game, describe_list
from evals.relevance.run_eval import against_original
from evals.relevance.run_original import to_record
from evals.relevance.score import (
    baseline_pick,
    combine,
    overlap,
    parse_original,
    summarize,
    to_side,
    versus_original_outcome,
)

DATA = json.loads((Path(__file__).parent / "dataset.json").read_text(encoding="utf-8"))


def games(*ids):
    return [GameCandidate(igdb_id=i, name=f"Game {i}") for i in ids]


def original_record(*ids):
    """run_original.py가 남기는 한 문항. 가격은 모른다."""
    rows = [{"game": game.model_dump(mode="json"), "amount_krw": None} for game in games(*ids)]
    return {"games": rows}


class ScriptedJudge:
    """정해 둔 순서로 답하는 심판. 에이전트가 A인 질문을 먼저 받는다."""

    def __init__(self, *winners):
        self.winners = list(winners)

    async def judge(self, question, list_a, list_b):
        return PairVerdict(winner=self.winners.pop(0), reason="테스트")


def price(igdb_id, status, amount=10000):
    quote = PriceQuote(igdb_id=igdb_id, amount_krw=amount) if amount is not None else None
    check = ConditionCheck(status=status, reason="테스트")
    return PriceResult(igdb_id=igdb_id, quote=quote, check=check)


def spec(igdb_id, status):
    return HardwareResult(igdb_id=igdb_id, check=ConditionCheck(status=status, reason="테스트"))


def test_dataset_has_unique_questions_in_three_families():
    assert len(DATA) == 40
    assert len({item["id"] for item in DATA}) == len({item["question"] for item in DATA}) == 40
    assert {item["family"] for item in DATA} == {"taste", "situation", "mixed"}


def test_baseline_pick_takes_passing_candidates_in_search_order():
    candidates = games(1, 2, 3, 4, 5)
    prices = {
        1: price(1, "unmet"),
        2: price(2, "met"),
        3: price(3, "unknown", amount=None),
        4: price(4, "skipped"),
        5: price(5, "met"),
    }
    hardware = {i: spec(i, "skipped") for i in (1, 2, 3, 4)} | {5: spec(5, "unmet")}

    picked = baseline_pick(candidates, prices, hardware, count=5)

    # 1번은 예산 초과, 3번은 가격 확인 불가, 5번은 사양 미달이다
    assert [game.igdb_id for game in picked] == [2, 4]
    assert [g.igdb_id for g in baseline_pick(candidates, prices, hardware, count=1)] == [2]


def test_baseline_pick_skips_candidates_without_a_verdict():
    candidates = games(1, 2)
    picked = baseline_pick(candidates, {2: price(2, "met")}, {2: spec(2, "met")}, count=2)
    assert [game.igdb_id for game in picked] == [2]


def test_verdict_position_is_mapped_back_to_the_list_owner():
    assert to_side("A", agent_is="A") == "agent"
    assert to_side("A", agent_is="B") == "baseline"
    assert to_side("B", agent_is="B") == "agent"
    assert to_side("tie", agent_is="A") == "tie"
    assert to_side("B", agent_is="A", other="original") == "original"


def test_win_requires_the_same_side_in_both_orders():
    assert combine("agent", "agent") == "agent"
    assert combine("baseline", "baseline") == "baseline"
    # 자리를 바꾸자 판정이 뒤집혔다면 자리 편향이다
    assert combine("agent", "baseline") == "tie"
    assert combine("agent", "tie") == "tie"


def test_overlap_is_jaccard():
    assert overlap([1, 2, 3], [1, 2, 3]) == 1.0
    assert overlap([1, 2], [2, 3]) == round(1 / 3, 4)
    assert overlap([1], [2]) == 0.0


def test_summary_counts_outcomes_and_win_rate():
    def record(id_, family, outcome, shared=0.5, **extra):
        return {"id": id_, "family": family, "outcome": outcome, "overlap": shared, **extra}

    summary = summarize(
        [
            record("R1", "taste", "agent"),
            record("R2", "taste", "agent"),
            record("R3", "taste", "baseline"),
            record("R4", "mixed", "tie", shared=0.25),
            record("R5", "mixed", "same", shared=1.0),
            record("R6", "mixed", "empty", shared=None),
            {"id": "R7", "family": "mixed", "error": "PipelineStageError: x"},
        ]
    )

    assert summary["scored"] == 6 and summary["errors"] == 1
    assert summary["outcomes"] == {"agent": 2, "baseline": 1, "tie": 1, "same": 1, "empty": 1}
    assert summary["agent_win_rate"] == round(2 / 3, 4)
    # 목록이 달랐던 문항은 승·패·비김 네 개다
    assert summary["changed_rate"] == round(4 / 6, 4)
    assert summary["overlap_mean"] == round((0.5 * 3 + 0.25) / 4, 4)
    assert summary["by_family"]["taste"]["agent"] == 2


def test_summary_without_decided_questions():
    summary = summarize([{"id": "R1", "family": "taste", "outcome": "same", "overlap": 1.0}])
    assert summary["agent_win_rate"] is None and summary["overlap_mean"] is None
    # 원본 기록 없이 돌린 실행의 요약은 예전 형식 그대로다
    assert "original" not in summary


def test_original_record_round_trips_candidates_and_prices():
    portal = GameCandidate(
        igdb_id=72, name="Portal 2", genres=["Puzzle"], summary="퍼즐", playtime_hours=8.5
    )
    thief = GameCandidate(igdb_id=11, name="Thief II")
    response = RecommendationResponse(
        conditions=GameConditions(),
        games=[
            EvaluatedGame(game=portal, price=price(72, "met", 11000), hardware=spec(72, "met")),
            EvaluatedGame(
                game=thief, price=price(11, "skipped", amount=None), hardware=spec(11, "skipped")
            ),
        ],
        answer="답변",
    )
    # 파일에 썼다가 읽은 것과 같다
    record = json.loads(json.dumps(to_record(response), ensure_ascii=False))

    listed, amounts = parse_original(record)

    assert record["original"] == ["Portal 2", "Thief II"]
    assert listed == [portal, thief]
    assert amounts == {72: 11000, 11: None}


def test_empty_lists_are_not_counted_as_wins_against_the_original():
    assert versus_original_outcome([], [1, 2]) == "empty"
    assert versus_original_outcome([], []) == "empty"
    assert versus_original_outcome([1, 2], []) == "original_empty"
    assert versus_original_outcome([1, 2], [2, 1]) == "same"
    assert versus_original_outcome([1, 2], [1, 3]) is None


def test_against_original_judges_both_orders_and_names_the_other_side():
    # 자리를 바꿔도 두 번 모두 원본 목록을 골랐다
    result = asyncio.run(
        against_original(ScriptedJudge("B", "A"), "질문", games(1, 2), {}, original_record(3, 4))
    )

    assert result["outcome"] == "original"
    assert [verdict["side"] for verdict in result["verdicts"]] == ["original", "original"]
    assert result["games"] == ["Game 3", "Game 4"] and result["overlap"] == 0.0

    # 한 번은 에이전트, 한 번은 원본을 골랐다면 자리 편향이라 비긴다
    split = asyncio.run(
        against_original(ScriptedJudge("A", "A"), "질문", games(1, 2), {}, original_record(3, 4))
    )
    assert split["outcome"] == "tie"


def test_against_original_skips_the_judge_for_errors_and_empty_lists():
    def run(agent, original):
        return asyncio.run(against_original(None, "질문", agent, {}, original))

    assert run(games(1), {"error": "PipelineStageError: x"}) == {"error": "PipelineStageError: x"}
    assert run(games(1), original_record()) == {"games": [], "outcome": "original_empty"}
    assert run([], original_record(1)) == {"games": ["Game 1"], "outcome": "empty"}
    same = run(games(1, 2), original_record(2, 1))
    assert same["outcome"] == "same" and same["overlap"] == 1.0


def test_summary_reports_the_original_comparison_separately():
    def record(id_, family, versus):
        return {"id": id_, "family": family, "outcome": "tie", "overlap": 0.5, "original": versus}

    summary = summarize(
        [
            record("R1", "taste", {"outcome": "agent", "overlap": 0.0}),
            record("R2", "taste", {"outcome": "agent", "overlap": 0.2}),
            record("R3", "mixed", {"outcome": "original", "overlap": 0.4}),
            record("R4", "mixed", {"outcome": "tie", "overlap": 0.2}),
            record("R5", "mixed", {"outcome": "original_empty"}),
            record("R6", "mixed", {"error": "원본 기록에 없는 문항"}),
            {"id": "R7", "family": "mixed", "error": "PipelineStageError: x"},
        ]
    )

    versus = summary["original"]
    assert versus["scored"] == 5 and versus["errors"] == 2
    assert versus["outcomes"] == {
        "agent": 2,
        "original": 1,
        "tie": 1,
        "same": 0,
        "empty": 0,
        "original_empty": 1,
    }
    # 원본의 빈 추천은 승패에 넣지 않는다
    assert versus["agent_win_rate"] == round(2 / 3, 4)
    assert versus["overlap_mean"] == round(0.8 / 4, 4)
    assert versus["by_family"]["taste"]["agent"] == 2
    # 원본 기록의 오류는 대조 목록과의 비교에서 문항을 빼지 않는다
    assert summary["scored"] == 6 and summary["outcomes"]["tie"] == 6


def test_judge_evidence_uses_only_tool_values():
    game = GameCandidate(
        igdb_id=72,
        name="Portal 2",
        genres=["Puzzle"],
        themes=["Science fiction"],
        playtime_hours=8.5,
        summary="x" * 400,
    )

    text = describe_game(game, 11000)

    assert "- Portal 2" in text and "분류: Puzzle, Science fiction" in text
    assert "완료 시간: 8.5시간" in text and "가격: 11,000원" in text
    assert text.endswith("…") and len(text.splitlines()[-1]) < 320
    # 가격을 모르면 지어내지 않고 줄을 뺀다
    assert "가격" not in describe_list([game], {})
