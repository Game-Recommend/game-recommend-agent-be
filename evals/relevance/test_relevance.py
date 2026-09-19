"""선택 관련성 평가의 순수 로직 검사. API를 부르지 않는다."""

import json
from pathlib import Path

from app.schemas.common import ConditionCheck
from app.schemas.game import GameCandidate
from app.schemas.hardware import HardwareResult
from app.schemas.price import PriceQuote, PriceResult
from evals.relevance.judge import describe_game, describe_list
from evals.relevance.score import baseline_pick, combine, overlap, summarize, to_side

DATA = json.loads((Path(__file__).parent / "dataset.json").read_text(encoding="utf-8"))


def games(*ids):
    return [GameCandidate(igdb_id=i, name=f"Game {i}") for i in ids]


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
